"""Batch-reserved benchmark runner; transport is injected and never defaults to network."""
from __future__ import annotations
import argparse, json, time, uuid
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable
from budget import BudgetLedger, cost_usd

class StageBenchError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message); self.code = code

def _upper(task: dict[str, Any], tier: dict[str, Any]) -> str:
    if "output_upper_tokens" not in task and "max_tokens" not in task:
        raise ValueError("task requires output_upper_tokens or max_tokens")
    out = task.get("output_upper_tokens", task.get("max_tokens"))
    if not isinstance(out, int) or isinstance(out, bool) or out <= 0: raise ValueError("output token upper bound must be > 0")
    payload = task.get("payload", {})
    size = len(payload.encode("utf-8")) if isinstance(payload, str) else len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    p = tier["prices_usd_per_million"]
    value = cost_usd(task.get("input_upper_tokens", size), 0, out, p["input"], p.get("cached_input", p["input"]), p["output"])
    if Decimal(value) <= 0: raise ValueError("upper_usd must be > 0")
    # Safety margin: real usage has exceeded the byte-derived token estimate (observed 2% on
    # Baseten). Without headroom a single overshoot marks the ledger overrun and halts the run.
    return str((Decimal(value) * Decimal("1.10")).quantize(Decimal("0.000000001")))

def _normalize(response: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(response, dict): raise TypeError("transport result must be a mapping")
    # Accept raw transport records or already-adapted records.
    status = response.get("status", response.get("http_status"))
    usage = response.get("final_usage", response.get("usage"))
    done = response.get("done", response.get("success"))
    if status is None or not isinstance(done, bool): raise ValueError("transport schema requires status and boolean done")
    usage_norm = None
    if usage is not None:
        if not isinstance(usage, dict): raise ValueError("usage must be a mapping or null")
        if "prompt_tokens" in usage or "completion_tokens" in usage:
            inp, out = usage.get("prompt_tokens"), usage.get("completion_tokens")
            details = usage.get("prompt_tokens_details") or {}
            cached = details.get("cached_tokens", usage.get("prompt_cache_hit_tokens", 0)) if isinstance(details, dict) else usage.get("prompt_cache_hit_tokens", 0)
        elif "input_tokens" in usage and "output_tokens" in usage:
            inp, out = usage["input_tokens"], usage["output_tokens"]
            # Anthropic input_tokens includes cached tokens; subtract cache reads to avoid double billing.
            cached = usage.get("cache_read_input_tokens", usage.get("cached_input_tokens", 0))
        else: raise ValueError("unsupported usage schema")
        if not all(isinstance(x, int) and not isinstance(x, bool) and x >= 0 for x in (inp, out, cached)) or cached > inp:
            raise ValueError("invalid usage token counts")
        usage_norm = {"input_tokens": inp, "output_tokens": out, "cached_input_tokens": cached}
    events = response.get("events", response.get("chunk_times_ms", []))
    if not isinstance(events, list): raise ValueError("events must be a list")
    chunks = []
    for ev in events[:256]:
        if isinstance(ev, dict):
            ns = ev.get("elapsed_ns")
            chunks.append(ns / 1_000_000 if isinstance(ns, (int, float)) else ev.get("elapsed_ms", ev.get("time_ms")))
        else: chunks.append(ev)
    return {"http_status": status, "done": done, "final_usage": usage_norm,
        "first_token_ms": response.get("first_generated_ms", response.get("first_token_ms")),
        "first_content_ms": response.get("first_content_ms"), "total_ms": response.get("total_ms"),
        "finish_reason": response.get("finish_reason"), "chunk_times_ms": chunks,
        "error": response.get("error")}

def _call(transport: Callable[..., Any], task: dict[str, Any], tier: dict[str, Any]) -> dict[str, Any]:
    start_time = datetime.now(timezone.utc).isoformat(); started = time.monotonic()
    try:
        record = _normalize(transport(task, tier))
    except Exception as exc:
        record = {"http_status": None, "done": False, "final_usage": None, "first_token_ms": None, "first_content_ms": None, "total_ms": (time.monotonic()-started)*1000, "finish_reason": None, "chunk_times_ms": [], "error": f"{type(exc).__name__}: {exc}"}
    record["started_at_utc"] = start_time
    if record.get("total_ms") is None: record["total_ms"] = (time.monotonic()-started)*1000
    return record

def run_batch(matrix_path: str | Path, provider_key: str, tier_key: str, tasks: list[dict[str, Any]], ledger_path: str | Path, transport: Callable[..., Any] | None = None, max_workers: int = 4) -> dict[str, Any]:
    if transport is None: raise ValueError("transport must be supplied; no default network transport")
    if max_workers < 1: raise ValueError("max_workers must be positive")
    matrix = json.loads(Path(matrix_path).read_text(encoding="utf-8")); provider = matrix["providers"][provider_key]; tier = provider["tiers"][tier_key]
    ids = [str(t.get("request_id") or uuid.uuid4()) for t in tasks]
    if len(ids) != len(set(ids)): raise ValueError("duplicate request_id in batch")
    uppers = [_upper(t, tier) for t in tasks]
    lp = Path(ledger_path); nb = lp.with_name("not_before.json")
    if nb.exists():
        data = json.loads(nb.read_text(encoding="utf-8"))
        if data.get("provider") == provider_key and data.get("tier") == tier_key and datetime.fromisoformat(data["not_before_utc"]) > datetime.now(timezone.utc):
            raise StageBenchError("NOT_BEFORE", "provider/tier cooldown has not expired")
    ledger = BudgetLedger(lp, provider["budget_cap_usd"]); reserved: set[str] = set(); sent: set[str] = set(); results: dict[str, dict[str, Any]] = {}
    try:
        states = {}
        if lp.exists():
            for line in lp.read_text(encoding="utf-8").splitlines():
                rec = json.loads(line)
                if rec.get("type") == "reserve": states[rec["request_id"]] = "reserved"
                elif rec.get("type") == "settle": states[rec["request_id"]] = "settled_unknown" if rec.get("actual_usd") is None else "settled"
        if "reserved" in states.values(): raise StageBenchError("EXISTING_HOLD", "ledger contains reserved request")
        if sum(map(Decimal, uppers), Decimal(0)) > Decimal(ledger.snapshot()["remaining_usd"]): raise StageBenchError("BUDGET_INSUFFICIENT", "batch upper total exceeds remaining budget")
        for rid, upper in zip(ids, uppers):
            if not ledger.reserve(rid, upper): raise StageBenchError("BUDGET_INSUFFICIENT", f"reserve failed for {rid}")
            reserved.add(rid)
        next_i = 0; pending = {}; breaker = False; failures = 0
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            def submit():
                nonlocal next_i
                rid = ids[next_i]; sent.add(rid); pending[pool.submit(_call, transport, tasks[next_i], tier)] = rid; next_i += 1
            while next_i < len(tasks) and len(pending) < max_workers: submit()
            while pending:
                done, _ = wait(tuple(pending), return_when=FIRST_COMPLETED)
                for fut in done:
                    rid = pending.pop(fut); r = fut.result(); results[rid] = r
                    if r.get("http_status") == 429: breaker = True
                    if r.get("http_status") != 200 or not r.get("done") or r.get("error"): failures += 1
                    else: failures = 0
                if not breaker and failures < 3:
                    while next_i < len(tasks) and len(pending) < max_workers: submit()
        for i in range(next_i, len(tasks)):
            rid=ids[i]; results[rid] = {"status":"not_sent", "started_at_utc":None, "http_status":None, "first_token_ms":None,"first_content_ms":None,"total_ms":None,"final_usage":None,"finish_reason":None,"chunk_times_ms":[]}
            ledger.settle(rid, "0"); reserved.discard(rid)
        for rid, upper in zip(ids[:next_i], uppers[:next_i]):
            r=results[rid]; usage=r.get("final_usage"); actual=None
            if usage is not None and r.get("http_status") == 200 and r.get("done"):
                p=tier["prices_usd_per_million"]; actual=cost_usd(usage["input_tokens"],usage["cached_input_tokens"],usage["output_tokens"],p["input"],p.get("cached_input",p["input"]),p["output"])
            ledger.settle(rid, actual); reserved.discard(rid); r.update(status="sent",request_id=rid,upper_usd=upper)
        if breaker: nb.write_text(json.dumps({"provider":provider_key,"tier":tier_key,"not_before_utc":(datetime.now(timezone.utc)+timedelta(seconds=60)).isoformat()}),encoding="utf-8")
        with lp.with_name("stage_records.jsonl").open("a",encoding="utf-8") as f:
            for rid in ids:
                r=results[rid]; rec={k:r.get(k) for k in ("status","started_at_utc","http_status","first_token_ms","first_content_ms","total_ms","final_usage","finish_reason","chunk_times_ms")}; rec.update(request_id=rid,provider=provider_key,tier=tier_key); f.write(json.dumps(rec,ensure_ascii=False)+"\n")
        snap=ledger.snapshot()
        return {"provider":provider_key,"tier":tier_key,"requests":[{**results[rid],"request_id":rid,"upper_usd":upper} for rid,upper in zip(ids,uppers)],"not_before_path":str(nb) if breaker else None,"committed_usd":snap["committed_usd"],"remaining_usd":snap["remaining_usd"],"overrun":ledger.overrun}
    finally:
        # Only known-unsent reservations can be safely released. Sent requests retain unknown holds.
        for rid in list(reserved):
            if rid not in sent:
                try: ledger.settle(rid,"0")
                except Exception: pass
        ledger.close()

def main():
    p=argparse.ArgumentParser(description="Plan only; never sends requests"); p.add_argument("--matrix",default="providers/benchmark-matrix.json"); p.add_argument("--provider",required=True); p.add_argument("--tier",required=True); p.add_argument("--tasks",type=int,default=1); a=p.parse_args()
    m=json.loads(Path(a.matrix).read_text()); pr=m["providers"][a.provider]; print(json.dumps({"mode":"plan-only","provider":a.provider,"tier":a.tier,"budget_cap_usd":pr["budget_cap_usd"],"task_count":a.tasks,"model":pr["tiers"][a.tier]["model"],"network_requests":0},indent=2))
if __name__ == "__main__": main()
