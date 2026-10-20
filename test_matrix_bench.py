#!/usr/bin/env python3
"""Unit tests for matrix_bench.py (all mocked, zero real network calls or cost)."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

import matrix_bench as mb


class TestMatrixBench(unittest.TestCase):
    def setUp(self) -> None:
        self.matrix_path = Path("providers/benchmark-matrix.json")
        self.assertTrue(self.matrix_path.is_file(), "benchmark-matrix.json must exist")

    def test_load_and_validate_matrix(self) -> None:
        """Verify real providers/benchmark-matrix.json passes validation."""
        cfg = mb.load_matrix(self.matrix_path)
        self.assertIn("providers", cfg)
        self.assertEqual(
            set(cfg["providers"].keys()),
            {"baseten", "fireworks", "deepinfra", "deepseek_official", "lithos"},
        )
        # Check caps
        for p_key, p_cfg in cfg["providers"].items():
            cap = Decimal(p_cfg["budget_cap_usd"])
            if p_key == "lithos":
                self.assertLessEqual(cap, Decimal("15.00"))
            else:
                self.assertLessEqual(cap, Decimal("2.00"))

    def test_matrix_validation_rejects_invalid_caps_and_prices(self) -> None:
        """Ensure budget cap guards and price validation fail closed."""
        cfg = mb.load_matrix(self.matrix_path)
        bad_cfg = json.loads(json.dumps(cfg))

        # 1. Non-lithos cap > 2.00
        bad_cfg["providers"]["baseten"]["budget_cap_usd"] = "2.50"
        with self.assertRaises(mb.MatrixBenchError):
            mb.validate_matrix(bad_cfg)

        # 2. Lithos cap > 15.00
        bad_cfg = json.loads(json.dumps(cfg))
        bad_cfg["providers"]["lithos"]["budget_cap_usd"] = "15.01"
        with self.assertRaises(mb.MatrixBenchError):
            mb.validate_matrix(bad_cfg)

        # 3. Invalid negative price
        bad_cfg = json.loads(json.dumps(cfg))
        bad_cfg["providers"]["fireworks"]["tiers"]["standard"]["prices_usd_per_million"]["input"] = "-0.1"
        with self.assertRaises(mb.MatrixBenchError):
            mb.validate_matrix(bad_cfg)

    def test_plan_generation_and_integrity(self) -> None:
        """Verify plan generates 4 sizes (>=3 groups, 5 repeats) + 1K throughput, with balanced schedule."""
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir) / "plan"
            manifest = mb.plan(
                matrix_path=self.matrix_path,
                output_dir=out_dir,
                groups=3,
                throughput_groups=3,
                seed=123,
                run_id="test-run-1",
            )
            self.assertEqual(manifest["groups_per_size"], 3)
            self.assertEqual(manifest["throughput_groups"], 3)
            self.assertEqual(manifest["repeats_per_group"], 5)
            self.assertEqual(manifest["sizes"], [1000, 4000, 16000, 32000])

            # Check files exist
            m_file = out_dir / "manifest.json"
            t_file = out_dir / "tasks.jsonl"
            self.assertTrue(m_file.is_file())
            self.assertTrue(t_file.is_file())

            # Read and verify tasks
            tasks = [json.loads(line) for line in t_file.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(manifest["task_count"], len(tasks))

            # Verify manifest and tasks integrity validator
            loaded_m, loaded_tasks = mb._validate_plan(out_dir)
            self.assertEqual(len(loaded_tasks), len(tasks))
            self.assertEqual(loaded_m["manifest_sha256"], manifest["manifest_sha256"])

            # Verify long tasks cap=32, throughput tasks cap=512
            for t in tasks:
                self.assertIn("provider", t)
                self.assertIn("tier", t)
                if t["kind"] == "long":
                    self.assertEqual(t["output_cap_tokens"], 32)
                    self.assertEqual(t["payload"]["max_tokens"], 32)
                    self.assertIn(t["target_tokens"], (1000, 4000, 16000, 32000))
                    self.assertIn(t["repeat_index"], range(5))
                else:
                    self.assertEqual(t["kind"], "throughput")
                    self.assertEqual(t["output_cap_tokens"], 512)
                    self.assertEqual(t["payload"]["max_tokens"], 512)
                    self.assertEqual(t["target_tokens"], 1000)
                    self.assertEqual(t["repeat_index"], 0)

            # Check multi-tier scheduling balance for Baseten (2 tiers) and Lithos (3 tiers)
            baseten_tasks = [t for t in tasks if t["provider"] == "baseten" and t["kind"] == "long"]
            baseten_groups: dict[str, list[dict]] = {}
            for t in baseten_tasks:
                baseten_groups.setdefault(t["pair_id"], []).append(t)

            first_tiers = []
            for pair_id, g_tasks in sorted(baseten_groups.items()):
                rep0 = [x for x in g_tasks if x["repeat_index"] == 0]
                self.assertEqual(len(rep0), 2)  # 2 tiers
                rep0_sorted = sorted(rep0, key=lambda x: x["schedule_index"])
                first_tiers.append(rep0_sorted[0]["tier"])

            # Both standard and fast appear in first position
            self.assertIn("standard", first_tiers)
            self.assertIn("fast", first_tiers)

    def test_plan_cli(self) -> None:
        """Verify CLI execution of plan subcommand."""
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir) / "plan"
            rc = mb.main([
                "plan",
                "--matrix", str(self.matrix_path),
                "--output", str(out_dir),
                "--groups", "3",
            ])
            self.assertEqual(rc, 0)
            self.assertTrue((out_dir / "manifest.json").is_file())

    def test_probe_success_and_mock(self) -> None:
        """Verify probe with mock transport returns connectivity and usage."""
        def mock_transport(base_url, key, payload, timeout_s=30.0, on_event=None):
            return {
                "status": 200,
                "done": True,
                "response_model": payload["model"],
                "final_usage": {
                    "prompt_tokens": 15,
                    "completion_tokens": 2,
                    "total_tokens": 17,
                },
                "headers": {"x-request-id": "mock-req-123"},
            }

        res = mb.probe(
            provider_key="baseten",
            tier_key="standard",
            matrix_path=self.matrix_path,
            api_key="mock-key",
            mock_transport=mock_transport,
        )
        self.assertTrue(res["success"])
        self.assertTrue(res["model_match"])
        self.assertEqual(res["status"], 200)
        self.assertEqual(res["final_usage"]["prompt_tokens"], 15)

    def test_probe_model_mismatch_and_error(self) -> None:
        """Verify probe flags model mismatch and failure."""
        def mock_mismatch(base_url, key, payload, timeout_s=30.0, on_event=None):
            return {
                "status": 200,
                "done": True,
                "response_model": "wrong-model-name",
                "final_usage": {"prompt_tokens": 10, "completion_tokens": 5},
            }

        res = mb.probe(
            provider_key="fireworks",
            tier_key="standard",
            matrix_path=self.matrix_path,
            api_key="mock-key",
            mock_transport=mock_mismatch,
        )
        self.assertFalse(res["model_match"])
        self.assertEqual(res["response_model"], "wrong-model-name")

    def test_probe_missing_api_key(self) -> None:
        """Verify probe fails closed when API key is missing."""
        env_backup = os.environ.get("BASETEN_API_KEY")
        if "BASETEN_API_KEY" in os.environ:
            del os.environ["BASETEN_API_KEY"]
        try:
            with self.assertRaises(mb.MatrixBenchError):
                mb.probe(
                    provider_key="baseten",
                    tier_key="standard",
                    matrix_path=self.matrix_path,
                )
        finally:
            if env_backup:
                os.environ["BASETEN_API_KEY"] = env_backup

    def test_run_success_with_independent_ledger(self) -> None:
        """Verify run dispatches tasks, journals records/events, and settles costs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            plan_dir = Path(tmpdir) / "plan"
            mb.plan(
                matrix_path=self.matrix_path,
                output_dir=plan_dir,
                groups=3,
                throughput_groups=3,
                run_id="run-test",
            )

            ledger_file = Path(tmpdir) / "baseten-budget.jsonl"

            events_logged = []
            def mock_transport(base_url, key, payload, timeout_s=120.0, on_event=None):
                if on_event:
                    on_event({"choices": [{"delta": {"content": "Hello"}}]})
                    events_logged.append(True)
                return {
                    "status": 200,
                    "done": True,
                    "response_model": payload["model"],
                    "final_usage": {
                        "prompt_tokens": 100,
                        "completion_tokens": 10,
                        "prompt_cache_hit_tokens": 50,
                    },
                }

            result = mb.run(
                plan_path=plan_dir,
                provider_key="baseten",
                ledger_path=ledger_file,
                matrix_path=self.matrix_path,
                api_key="mock-key",
                mock_transport=mock_transport,
                max_requests=5,
                sleep=lambda _: None,
            )

            self.assertEqual(result["sent"], 5)
            self.assertEqual(result["completed"], 5)
            self.assertTrue(ledger_file.is_file())
            self.assertTrue(Path(str(ledger_file) + ".records.jsonl").is_file())
            self.assertTrue(Path(str(ledger_file) + ".events.jsonl").is_file())

            # Verify records journal content
            records = [
                json.loads(line)
                for line in Path(str(ledger_file) + ".records.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertEqual(len(records), 5)
            for r in records:
                self.assertEqual(r["status"], "complete")
                self.assertEqual(r["provider"], "baseten")
                self.assertIsNotNone(r["accounting"]["computed_usd"])

    def test_run_stream_break_handles_fail_closed(self) -> None:
        """Verify incomplete stream (done=False) records stream_break and does NOT settle."""
        with tempfile.TemporaryDirectory() as tmpdir:
            plan_dir = Path(tmpdir) / "plan"
            mb.plan(self.matrix_path, plan_dir, groups=3, throughput_groups=3)
            ledger_file = Path(tmpdir) / "fireworks-budget.jsonl"

            def mock_broken_stream(base_url, key, payload, timeout_s=120.0, on_event=None):
                return {
                    "status": 200,
                    "done": False,  # Stream disconnected before [DONE]
                    "response_model": payload["model"],
                    "final_usage": None,
                }

            result = mb.run(
                plan_path=plan_dir,
                provider_key="fireworks",
                ledger_path=ledger_file,
                matrix_path=self.matrix_path,
                api_key="mock-key",
                mock_transport=mock_broken_stream,
                max_requests=1,
                sleep=lambda _: None,
            )

            self.assertEqual(result["sent"], 1)
            self.assertEqual(result["completed"], 0)

            rec_file = Path(str(ledger_file) + ".records.jsonl")
            record = json.loads(rec_file.read_text(encoding="utf-8").strip())
            self.assertEqual(record["status"], "stream_break")
            self.assertIsNone(record["accounting"]["computed_usd"])

    def test_run_429_persists_not_before_and_stops(self) -> None:
        """Verify HTTP 429 halts execution and writes cooldown file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            plan_dir = Path(tmpdir) / "plan"
            mb.plan(self.matrix_path, plan_dir, groups=3, throughput_groups=3)
            ledger_file = Path(tmpdir) / "deepinfra-budget.jsonl"

            def mock_429(base_url, key, payload, timeout_s=120.0, on_event=None):
                return {
                    "status": 429,
                    "done": False,
                    "headers": {"retry-after": "60"},
                }

            result = mb.run(
                plan_path=plan_dir,
                provider_key="deepinfra",
                ledger_path=ledger_file,
                matrix_path=self.matrix_path,
                api_key="mock-key",
                mock_transport=mock_429,
                max_requests=5,
                sleep=lambda _: None,
            )

            # Stopped after 1 request
            self.assertEqual(result["sent"], 1)
            self.assertEqual(result["completed"], 0)

            not_before = Path(str(ledger_file) + ".not-before.json")
            self.assertTrue(not_before.is_file())
            content = json.loads(not_before.read_text(encoding="utf-8").strip())
            self.assertEqual(content["status"], "429")
            self.assertEqual(content["retry_after"], "60")

    def test_run_circuit_breaker_after_three_failures(self) -> None:
        """Verify circuit breaker trips after 3 consecutive failures."""
        with tempfile.TemporaryDirectory() as tmpdir:
            plan_dir = Path(tmpdir) / "plan"
            mb.plan(self.matrix_path, plan_dir, groups=3, throughput_groups=3)
            ledger_file = Path(tmpdir) / "deepseek-budget.jsonl"

            def mock_500(base_url, key, payload, timeout_s=120.0, on_event=None):
                return {
                    "status": 500,
                    "done": False,
                }

            result = mb.run(
                plan_path=plan_dir,
                provider_key="deepseek_official",
                ledger_path=ledger_file,
                matrix_path=self.matrix_path,
                api_key="mock-key",
                mock_transport=mock_500,
                max_requests=10,
                sleep=lambda _: None,
            )

            # Tripped at exactly 3 failures
            self.assertEqual(result["sent"], 3)
            self.assertEqual(result["completed"], 0)
            self.assertEqual(result["failures"], 3)

    def test_run_budget_cap_exhaustion_stops_safely(self) -> None:
        """Verify that when ledger hard cap is reached, dispatch halts without network call."""
        with tempfile.TemporaryDirectory() as tmpdir:
            plan_dir = Path(tmpdir) / "plan"
            mb.plan(self.matrix_path, plan_dir, groups=3, throughput_groups=3)
            ledger_file = Path(tmpdir) / "lithos-budget.jsonl"

            # Pre-populate ledger with a committed amount equal to the cap ($15.00)
            with mb.budget.BudgetLedger(ledger_file, "15.00") as led:
                led.reserve("prior-001", "15.00")
                led.settle("prior-001", "15.00")

            calls = []
            def mock_transport(base_url, key, payload, timeout_s=120.0, on_event=None):
                calls.append(payload)
                return {"status": 200, "done": True, "response_model": payload["model"]}

            result = mb.run(
                plan_path=plan_dir,
                provider_key="lithos",
                ledger_path=ledger_file,
                matrix_path=self.matrix_path,
                api_key="mock-key",
                mock_transport=mock_transport,
                sleep=lambda _: None,
            )

            # Headroom is only $0.01; long tasks hold > $0.01, so reserve() returns False immediately
            self.assertEqual(result["sent"], 0)
            self.assertEqual(len(calls), 0)


if __name__ == "__main__":
    unittest.main()
