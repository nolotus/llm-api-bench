import json
import tempfile
import unittest
from pathlib import Path

from stage_bench import StageBenchError, run_batch


class StageBenchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.matrix = self.root / "matrix.json"
        self.ledger = self.root / "ledger.jsonl"
        self.make_matrix("10.00")

    def tearDown(self):
        self.tmp.cleanup()

    def make_matrix(self, cap):
        data = {"providers": {"p": {"budget_cap_usd": cap, "tiers": {
            "a": {"model": "m", "prices_usd_per_million": {"input": "1", "cached_input": "0.1", "output": "2"}},
            "b": {"model": "m", "prices_usd_per_million": {"input": "3", "cached_input": "0.3", "output": "4"}},
            "c": {"model": "m", "prices_usd_per_million": {"input": "5", "cached_input": "0.5", "output": "6"}},
        }}}}
        self.matrix.write_text(json.dumps(data), encoding="utf-8")

    def test_cap_failure_zero_send(self):
        self.make_matrix("0.000001")
        called = []
        with self.assertRaises(StageBenchError) as e:
            run_batch(self.matrix, "p", "a", [{"request_id":"x", "payload":"x", "output_upper_tokens":1}], self.ledger, lambda *a: called.append(a))
        self.assertEqual(e.exception.code, "BUDGET_INSUFFICIENT")
        self.assertEqual(len(called), 0)
        self.assertFalse(any(json.loads(line).get("type") == "reserve" for line in self.ledger.read_text().splitlines()))

    def test_three_tier_costs(self):
        for tier, inp, out in (("a", "1", "2"), ("b", "3", "4"), ("c", "5", "6")):
            path = self.root / (tier + ".jsonl")
            res = run_batch(self.matrix, "p", tier, [{"request_id":tier,"payload":"", "input_upper_tokens":100,"output_upper_tokens":100}], path,
                lambda task, t: {"status":200,"done":True,"final_usage":{"prompt_tokens":10,"completion_tokens":5},"finish_reason":"stop"})
            self.assertEqual(res["requests"][0]["final_usage"]["input_tokens"], 10)
            from decimal import Decimal
            self.assertEqual(Decimal(res["requests"][0]["upper_usd"]), (Decimal(int(inp)*100+int(out)*100) / Decimal(1000000)) * Decimal("1.10"))  # intentional safety margin
            lines = [json.loads(x) for x in path.read_text().splitlines()]
            actual = next(x["actual_usd"] for x in lines if x.get("type") == "settle")
            self.assertEqual(Decimal(actual), Decimal(int(inp)*10+int(out)*5) / Decimal(1000000))

    def test_missing_usage_retains_unknown(self):
        res = run_batch(self.matrix, "p", "a", [{"request_id":"x","payload":"x","output_upper_tokens":1}], self.ledger, lambda *a: {"status":200,"done":True,"finish_reason":"stop"})
        self.assertIsNone(res["requests"][0]["final_usage"])
        text = self.ledger.read_text()
        self.assertIn('"actual_usd":null', text)

    def test_429_stops_remaining_and_no_retry(self):
        calls = []
        def transport(task, tier):
            calls.append(task["request_id"])
            return {"status":429,"done":False,"finish_reason":"error"}
        res = run_batch(self.matrix, "p", "a", [{"request_id":str(i),"payload":"","max_tokens":10} for i in range(4)], self.ledger, transport, max_workers=1)
        self.assertEqual(len(calls), 1)
        self.assertTrue(Path(res["not_before_path"]).exists())
        self.assertTrue(all(x.get("status") == "not_sent" for x in res["requests"][1:]))
        lines = [json.loads(x) for x in self.ledger.read_text().splitlines()]
        settled = [x for x in lines if x.get("type") == "settle"]
        self.assertEqual(len(settled), 4)
        self.assertEqual(sum(x.get("actual_usd") == "0" for x in settled), 3)
        self.assertEqual(sum(x.get("actual_usd") is None for x in settled), 1)
        from budget import BudgetLedger
        with BudgetLedger(self.ledger, "10.00") as ledger:
            self.assertEqual(ledger.snapshot()["committed_usd"], "0.000022000")  # includes intentional 1.10 reserve margin

    def test_existing_hold_blocks(self):
        from budget import BudgetLedger
        with BudgetLedger(self.ledger, "10.00") as ledger:
            ledger.reserve("held", "1")
        with self.assertRaises(StageBenchError) as e:
            run_batch(self.matrix, "p", "a", [], self.ledger, lambda *a: {})
        self.assertEqual(e.exception.code, "EXISTING_HOLD")

    def test_request_ids_unique_and_bounded_batch(self):
        calls = []
        def transport(task, tier):
            calls.append(task["request_id"])
            return {"status":200,"done":True,"final_usage":{"prompt_tokens":0,"completion_tokens":0},"finish_reason":"stop"}
        tasks = [{"request_id":f"r{i}","payload":"","max_tokens":10} for i in range(4)]
        run_batch(self.matrix, "p", "a", tasks, self.ledger, transport, max_workers=3)
        lines = [json.loads(x) for x in self.ledger.read_text().splitlines()]
        reserved = [x["request_id"] for x in lines if x.get("type") == "reserve"]
        self.assertEqual(len(calls), len(tasks))
        self.assertEqual(len(reserved), len(set(reserved)))

    def test_parallel_inflight_window(self):
        import threading
        entered = threading.Barrier(2)
        release = threading.Event()
        active = 0
        peak = 0
        guard = threading.Lock()
        def transport(task, tier):
            nonlocal active, peak
            with guard:
                active += 1
                peak = max(peak, active)
            entered.wait(timeout=3)
            release.wait(timeout=3)
            with guard: active -= 1
            return {"status":200,"done":True,"final_usage":{"prompt_tokens":0,"completion_tokens":0},"finish_reason":"stop"}
        timer = threading.Timer(0.2, release.set)
        timer.start()
        try:
            run_batch(self.matrix, "p", "a", [{"request_id":f"p{i}","payload":"","max_tokens":10} for i in range(4)], self.root / "parallel.jsonl", transport, max_workers=4)
        finally:
            release.set(); timer.cancel()
        self.assertGreaterEqual(peak, 2)

    def test_real_transport_contract_two_batches(self):
        from decimal import Decimal
        from budget import cost_usd
        def transport(task, tier):
            return {"status":200,"done":True,"final_usage":{"prompt_tokens":100,"completion_tokens":20,"prompt_tokens_details":{"cached_tokens":10}},"first_generated_ms":12,"first_content_ms":15,"total_ms":30,"finish_reason":"stop","events":[]}
        for batch in range(2):
            tasks=[{"request_id":f"t{batch}-{i}","payload":"x","input_upper_tokens":200,"output_upper_tokens":50} for i in range(3)]
            result=run_batch(self.matrix,"p","a",tasks,self.ledger,transport,max_workers=2)
            self.assertEqual(len(result["requests"]),3)
            expected=Decimal(cost_usd(100,10,20,"1","0.1","2"))
            lines=[json.loads(x) for x in self.ledger.read_text().splitlines()]
            settled={x["request_id"]:x["actual_usd"] for x in lines if x.get("type")=="settle"}
            for task in tasks: self.assertEqual(Decimal(settled[task["request_id"]]),expected)
            self.assertTrue(all(x["status"]=="sent" and x["finish_reason"]=="stop" for x in result["requests"]))

    def test_missing_output_bound_has_no_reserve_or_send(self):
        calls=[]
        with self.assertRaises(ValueError):
            run_batch(self.matrix,"p","a",[{"request_id":"no-output","payload":"hi"}],self.ledger,lambda *a:calls.append(a))
        self.assertEqual(calls,[])
        lines=[json.loads(x) for x in self.ledger.read_text().splitlines()] if self.ledger.exists() else []
        self.assertFalse(any(x.get("type")=="reserve" for x in lines))

    def test_duplicate_ids_fail_before_any_reservation(self):
        from budget import BudgetLedger
        with self.assertRaises(ValueError):
            run_batch(self.matrix,"p","a",[{"request_id":"dup","payload":"x","max_tokens":10},{"request_id":"dup","payload":"y","max_tokens":10}],self.ledger,lambda *a:{})
        lines=[json.loads(x) for x in self.ledger.read_text().splitlines()] if self.ledger.exists() else []
        reserves=[x for x in lines if x.get("type")=="reserve"]
        settles=[x for x in lines if x.get("type")=="settle"]
        self.assertEqual(reserves,[])
        self.assertEqual(settles,[])
        with BudgetLedger(self.ledger,"10.00") as ledger: self.assertEqual(ledger.snapshot()["committed_usd"],"0")

    def test_unknown_usage_keeps_hold_and_allows_next_batch(self):
        from decimal import Decimal
        first=run_batch(self.matrix,"p","a",[{"request_id":"unknown","payload":"x","max_tokens":10}],self.ledger,lambda *a:{"status":200,"done":True,"finish_reason":"stop"})
        lines=[json.loads(x) for x in self.ledger.read_text().splitlines()]
        self.assertTrue(any(x.get("type")=="settle" and x.get("request_id")=="unknown" and x.get("actual_usd") is None for x in lines))
        upper=Decimal(first["requests"][0]["upper_usd"])
        self.assertEqual(Decimal(first["remaining_usd"]),Decimal("10.00")-upper)
        second=run_batch(self.matrix,"p","a",[{"request_id":"next","payload":"x","max_tokens":10}],self.ledger,lambda *a:{"status":200,"done":True,"final_usage":{"prompt_tokens":1,"completion_tokens":1},"finish_reason":"stop"})
        self.assertEqual(second["requests"][0]["status"],"sent")


if __name__ == "__main__":
    unittest.main()
