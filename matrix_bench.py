#!/usr/bin/env python3
"""Cross-provider unified matrix benchmark planner, probe, and runner.

Standard library only (+ local bench, budget, transport modules).
Enforces strict per-provider budget ledgers, fail-closed accounting,
interleaved balanced multi-tier scheduling, and durable logging.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import itertools
import json
import os
import random
import sys
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable

import bench
import budget
import transport

SIZES = (1000, 4000, 16000, 32000)
LONG_OUTPUT_CAP = 32
THROUGHPUT_TARGET = 1000
THROUGHPUT_OUTPUT_CAP = 512
REPEATS_PER_GROUP = 5  # 1 initial + 4 reuse

NEW_PROVIDER_MAX_CAP = Decimal("2.00")
LITHOS_MAX_CAP = Decimal("15.00")
TOKEN_BUFFER = 512


class MatrixBenchError(Exception):
    """Base error for matrix benchmark failures."""


class AuditWriteFailed(MatrixBenchError):
    """Raised when event log persistence fails during streaming."""


def canonical(obj: Any) -> bytes:
    """Canonical compact JSON serialization for hashing."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha(data: bytes) -> str:
    """Compute sha256 hex digest."""
    return hashlib.sha256(data).hexdigest()


def _append_jsonl(path: Path | str, obj: dict[str, Any]) -> None:
    """Durable append to JSONL file with fsync."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, sort_keys=True, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())


def load_matrix(matrix_path: Path | str) -> dict[str, Any]:
    """Load and validate benchmark matrix configuration."""
    p = Path(matrix_path)
    if not p.is_file():
        raise MatrixBenchError(f"Matrix file not found: {p}")
    try:
        cfg = json.loads(p.read_text(encoding="utf-8"))
    except Exception as err:
        raise MatrixBenchError(f"Failed to parse matrix JSON: {err}") from err
    validate_matrix(cfg)
    return cfg


def validate_matrix(cfg: dict[str, Any]) -> None:
    """Validate matrix schema, provider fields, tiers, prices, and budget caps."""
    if not isinstance(cfg, dict):
        raise MatrixBenchError("Matrix configuration must be a dictionary")
    if "providers" not in cfg or not isinstance(cfg["providers"], dict):
        raise MatrixBenchError("Matrix must contain 'providers' mapping")

    for p_key, p_cfg in cfg["providers"].items():
        if not isinstance(p_cfg, dict):
            raise MatrixBenchError(f"Provider {p_key} config must be a dictionary")
        for req in ("name", "base_url", "env_name", "budget_cap_usd", "tiers"):
            if req not in p_cfg:
                raise MatrixBenchError(f"Provider {p_key} missing required field '{req}'")

        # Validate budget cap
        try:
            cap = Decimal(str(p_cfg["budget_cap_usd"]))
        except (InvalidOperation, ValueError) as err:
            raise MatrixBenchError(f"Provider {p_key} invalid budget_cap_usd: {err}") from err
        if not cap.is_finite() or cap <= 0:
            raise MatrixBenchError(f"Provider {p_key} budget cap must be finite and positive")

        if p_key == "lithos":
            if cap > LITHOS_MAX_CAP:
                raise MatrixBenchError(f"Lithos budget cap ({cap}) exceeds maximum allowed ({LITHOS_MAX_CAP})")
        else:
            if cap > NEW_PROVIDER_MAX_CAP:
                raise MatrixBenchError(f"Provider {p_key} budget cap ({cap}) exceeds maximum allowed ({NEW_PROVIDER_MAX_CAP})")

        tiers = p_cfg.get("tiers")
        if not isinstance(tiers, dict) or not tiers:
            raise MatrixBenchError(f"Provider {p_key} must contain non-empty 'tiers'")

        for t_key, t_cfg in tiers.items():
            if not isinstance(t_cfg, dict):
                raise MatrixBenchError(f"Provider {p_key} tier {t_key} must be a dictionary")
            if not t_cfg.get("model"):
                raise MatrixBenchError(f"Provider {p_key} tier {t_key} missing model")
            prices = t_cfg.get("prices_usd_per_million")
            if not isinstance(prices, dict):
                raise MatrixBenchError(f"Provider {p_key} tier {t_key} missing prices_usd_per_million")
            for price_key in ("input", "cached_input", "output"):
                if price_key not in prices:
                    raise MatrixBenchError(f"Provider {p_key} tier {t_key} missing price '{price_key}'")
                try:
                    p = Decimal(str(prices[price_key]))
                except (InvalidOperation, ValueError) as err:
                    raise MatrixBenchError(f"Provider {p_key} tier {t_key} invalid price '{price_key}': {err}") from err
                if not p.is_finite() or p < 0:
                    raise MatrixBenchError(f"Provider {p_key} tier {t_key} price '{price_key}' must be finite and non-negative")


def calculate_cost(
    provider_key: str,
    tier_key: str,
    prompt_tokens: int,
    cached_tokens: int,
    completion_tokens: int,
    matrix_cfg: dict[str, Any],
) -> Decimal:
    """Calculate USD cost for a specific provider tier."""
    prices = matrix_cfg["providers"][provider_key]["tiers"][tier_key]["prices_usd_per_million"]
    c_str = budget.cost_usd(
        prompt_tokens,
        cached_tokens,
        completion_tokens,
        str(prices["input"]),
        str(prices["cached_input"]),
        str(prices["output"]),
    )
    return Decimal(c_str)


def hold_usd(
    provider_key: str,
    tier_key: str,
    input_upper_tokens: int,
    output_cap_tokens: int,
    matrix_cfg: dict[str, Any],
) -> str:
    """Conservative hold cost assuming 0 cached tokens."""
    return str(calculate_cost(provider_key, tier_key, input_upper_tokens, 0, output_cap_tokens, matrix_cfg))


def _tier_permutations(tier_names: list[str], seed: int | None = None) -> list[tuple[str, ...]]:
    """Generate balanced permutations of tiers for interleaved scheduling."""
    sorted_tiers = sorted(tier_names)
    perms = list(itertools.permutations(sorted_tiers))
    if seed is not None:
        rng = random.Random(seed)
        rng.shuffle(perms)
    return perms


def _request_order(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Interleaved ordering: within each group, repeats are dispatched alternating across tiers."""
    grouped: dict[tuple[str, int, str], list[dict[str, Any]]] = {}
    for task in tasks:
        key = (task["kind"], task["target_tokens"], task["pair_id"])
        grouped.setdefault(key, []).append(task)

    ordered: list[dict[str, Any]] = []
    # Sort groups deterministically: long first by target_tokens, then throughput
    sorted_group_keys = sorted(
        grouped.keys(),
        key=lambda k: (0 if k[0] == "long" else 1, k[1], k[2]),
    )
    for key in sorted_group_keys:
        rows = grouped[key]
        ordered.extend(sorted(rows, key=lambda x: (x["repeat_index"], x["schedule_index"])))
    return ordered


def plan(
    matrix_path: Path | str,
    output_dir: Path | str,
    groups: int = 3,
    throughput_groups: int = 3,
    seed: int = 42,
    run_id: str = "matrix-v1",
    bpt: float = 2.0,
    force: bool = False,
) -> dict[str, Any]:
    """Generate cross-provider benchmark plan."""
    if groups < 3:
        raise MatrixBenchError(f"groups must be at least 3, got {groups}")
    if throughput_groups < 1:
        raise MatrixBenchError(f"throughput_groups must be at least 1, got {throughput_groups}")
    if bpt <= 0:
        raise MatrixBenchError(f"bytes_per_token must be positive, got {bpt}")

    matrix_file = Path(matrix_path)
    matrix_bytes = matrix_file.read_bytes()
    matrix_cfg = load_matrix(matrix_file)

    out = Path(output_dir)
    if out.exists():
        if not force:
            raise MatrixBenchError(f"Output directory already exists: {out} (use force=True to overwrite)")
    else:
        out.mkdir(parents=True, exist_ok=True)

    tasks: list[dict[str, Any]] = []
    provider_summaries: dict[str, Any] = {}
    total_planned_usd = Decimal("0")

    for p_key, p_cfg in matrix_cfg["providers"].items():
        tiers = p_cfg["tiers"]
        tier_names = sorted(tiers.keys())
        perms = _tier_permutations(tier_names, seed=seed)
        p_tasks: list[dict[str, Any]] = []
        p_planned_usd = Decimal("0")

        # 1. Four sizes for TTFT & prefix caching: 1K / 4K / 16K / 32K
        for size in SIZES:
            for g in range(groups):
                order = perms[g % len(perms)]
                local_seed = int.from_bytes(
                    hashlib.sha256(f"{seed}:{p_key}:{size}:{g}".encode("utf-8")).digest()[:8],
                    "big",
                )
                shared_text = bench.sentences(
                    random.Random(local_seed),
                    f"pair-{size}-{g}",
                    int(size * bpt),
                )
                for rep in range(REPEATS_PER_GROUP):
                    for ix, t_name in enumerate(order):
                        t_cfg = tiers[t_name]
                        nonce = sha(f"{run_id}|{p_key}|long|{size}|{g}|{t_name}".encode("utf-8"))[:24]
                        text = (
                            f"Run nonce {nonce}. {shared_text}\n\n"
                            f"Task variation {rep}: compare a distinct consequence and state one additional limitation.\n\n"
                            "Analyze this scenario and provide a structured evidence-based answer. State assumptions, alternatives, and limitations."
                        )
                        in_upper = len(text.encode("utf-8")) + TOKEN_BUFFER
                        out_cap = LONG_OUTPUT_CAP
                        upper_usd = hold_usd(p_key, t_name, in_upper, out_cap, matrix_cfg)
                        p_planned_usd += Decimal(upper_usd)

                        payload = {
                            "model": t_cfg["model"],
                            "messages": [{"role": "user", "content": text}],
                            "max_tokens": out_cap,
                            "stream": True,
                        }
                        task_row = {
                            "request_id": f"{run_id}-{p_key}-long-{size}-g{g:05d}-{t_name}-r{rep:02d}",
                            "run_id": run_id,
                            "provider": p_key,
                            "tier": t_name,
                            "model": t_cfg["model"],
                            "kind": "long",
                            "target_tokens": size,
                            "group_id": f"{p_key}-long-{size}-g{g:05d}-{t_name}",
                            "pair_id": f"{p_key}-long-{size}-g{g:05d}",
                            "repeat_index": rep,
                            "schedule_index": ix,
                            "output_cap_tokens": out_cap,
                            "input_upper_tokens": in_upper,
                            "upper_usd": upper_usd,
                            "nonce": nonce,
                            "payload": payload,
                        }
                        p_tasks.append(task_row)

        # 2. 1K throughput test with cap=512
        for g in range(throughput_groups):
            order = perms[g % len(perms)]
            local_seed = int.from_bytes(
                hashlib.sha256(f"{seed}:{p_key}:throughput:{g}".encode("utf-8")).digest()[:8],
                "big",
            )
            shared_text = bench.sentences(
                random.Random(local_seed),
                f"throughput-{g}",
                int(THROUGHPUT_TARGET * bpt),
            )
            for ix, t_name in enumerate(order):
                t_cfg = tiers[t_name]
                nonce = sha(f"{run_id}|{p_key}|throughput|{THROUGHPUT_TARGET}|{g}|{t_name}".encode("utf-8"))[:24]
                text = (
                    f"Run nonce {nonce}. {shared_text}\n\n"
                    "Analyze this scenario and provide a structured evidence-based answer. State assumptions, alternatives, and limitations."
                )
                in_upper = len(text.encode("utf-8")) + TOKEN_BUFFER
                out_cap = THROUGHPUT_OUTPUT_CAP
                upper_usd = hold_usd(p_key, t_name, in_upper, out_cap, matrix_cfg)
                p_planned_usd += Decimal(upper_usd)

                payload = {
                    "model": t_cfg["model"],
                    "messages": [{"role": "user", "content": text}],
                    "max_tokens": out_cap,
                    "stream": True,
                }
                task_row = {
                    "request_id": f"{run_id}-{p_key}-throughput-1000-g{g:05d}-{t_name}-r00",
                    "run_id": run_id,
                    "provider": p_key,
                    "tier": t_name,
                    "model": t_cfg["model"],
                    "kind": "throughput",
                    "target_tokens": THROUGHPUT_TARGET,
                    "group_id": f"{p_key}-throughput-1000-g{g:05d}-{t_name}",
                    "pair_id": f"{p_key}-throughput-1000-g{g:05d}",
                    "repeat_index": 0,
                    "schedule_index": ix,
                    "output_cap_tokens": out_cap,
                    "input_upper_tokens": in_upper,
                    "upper_usd": upper_usd,
                    "nonce": nonce,
                    "payload": payload,
                }
                p_tasks.append(task_row)

        # Budget cap verification for this provider
        cap_usd = Decimal(str(p_cfg["budget_cap_usd"]))
        if p_planned_usd > cap_usd:
            raise MatrixBenchError(
                f"Provider '{p_key}' planned upper cost (${p_planned_usd}) exceeds budget cap (${cap_usd})"
            )

        provider_summaries[p_key] = {
            "name": p_cfg["name"],
            "budget_cap_usd": str(cap_usd),
            "planned_upper_usd": str(p_planned_usd),
            "task_count": len(p_tasks),
            "tiers": tier_names,
            "schedule": [list(p) for p in perms],
        }
        total_planned_usd += p_planned_usd
        tasks.extend(p_tasks)

    # Write tasks.jsonl
    tasks_raw = b"".join(canonical(t) + b"\n" for t in tasks)
    tasks_file = out / "tasks.jsonl"
    with open(tasks_file, "wb") as f:
        f.write(tasks_raw)
        f.flush()
        os.fsync(f.fileno())

    manifest: dict[str, Any] = {
        "matrix_version": matrix_cfg.get("matrix_version", 1),
        "run_id": run_id,
        "seed": seed,
        "matrix_file": str(matrix_file.resolve()),
        "matrix_sha256": sha(matrix_bytes),
        "tasks_file": "tasks.jsonl",
        "tasks_sha256": sha(tasks_raw),
        "task_count": len(tasks),
        "sizes": list(SIZES),
        "groups_per_size": groups,
        "throughput_groups": throughput_groups,
        "repeats_per_group": REPEATS_PER_GROUP,
        "bytes_per_token": bpt,
        "providers": provider_summaries,
        "planned_upper_usd": str(total_planned_usd),
    }
    manifest["manifest_sha256"] = sha(canonical(manifest))

    manifest_file = out / "manifest.json"
    with open(manifest_file, "w", encoding="utf-8") as f:
        f.write(json.dumps(manifest, sort_keys=True, indent=2) + "\n")
        f.flush()
        os.fsync(f.fileno())

    return manifest


def _validate_plan(plan_path: Path | str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Validate plan directory integrity against self-verifying manifest."""
    d = Path(plan_path)
    if d.is_file():
        m_file = d
        d = d.parent
    else:
        m_file = d / "manifest.json"

    if not m_file.is_file():
        raise MatrixBenchError(f"Manifest not found: {m_file}")

    m = json.loads(m_file.read_text(encoding="utf-8"))
    claimed_hash = m.pop("manifest_sha256", None)
    if not claimed_hash or claimed_hash != sha(canonical(m)):
        raise MatrixBenchError("Manifest integrity verification failed (sha256 mismatch)")
    m["manifest_sha256"] = claimed_hash

    tasks_path = d / m.get("tasks_file", "tasks.jsonl")
    if not tasks_path.is_file():
        # Fallback to .gz if present
        if (d / "tasks.jsonl.gz").is_file():
            tasks_path = d / "tasks.jsonl.gz"
        else:
            raise MatrixBenchError(f"Tasks file not found: {tasks_path}")

    if str(tasks_path).endswith(".gz"):
        raw = gzip.open(tasks_path, "rb").read()
    else:
        raw = tasks_path.read_bytes()

    if sha(raw) != m.get("tasks_sha256"):
        raise MatrixBenchError("Tasks file integrity verification failed (sha256 mismatch)")

    tasks = [json.loads(line) for line in raw.splitlines() if line.strip()]
    if len(tasks) != m.get("task_count"):
        raise MatrixBenchError(f"Task count mismatch: expected {m.get('task_count')}, got {len(tasks)}")

    return m, tasks


def probe(
    provider_key: str,
    tier_key: str,
    matrix_path: Path | str = "providers/benchmark-matrix.json",
    api_key: str | None = None,
    mock_transport: Callable[..., dict[str, Any]] | None = None,
    timeout_s: float = 30.0,
) -> dict[str, Any]:
    """Execute 1 lightweight probe to verify connectivity, actual model, and usage structure."""
    matrix_cfg = load_matrix(matrix_path)
    if provider_key not in matrix_cfg["providers"]:
        raise MatrixBenchError(f"Provider '{provider_key}' not found in matrix configuration")
    p_cfg = matrix_cfg["providers"][provider_key]

    if tier_key not in p_cfg["tiers"]:
        raise MatrixBenchError(f"Tier '{tier_key}' not found for provider '{provider_key}'")
    t_cfg = p_cfg["tiers"][tier_key]

    key = api_key or os.environ.get(p_cfg["env_name"])
    if not key:
        raise MatrixBenchError(f"API key unavailable: environment variable '{p_cfg['env_name']}' is not set")

    probe_payload = {
        "model": t_cfg["model"],
        "messages": [{"role": "user", "content": "Respond with the single word: pong"}],
        "max_tokens": 16,
        "stream": True,
    }

    transport_fn = mock_transport or transport.stream_chat
    start_time = time.monotonic()
    try:
        resp = transport_fn(
            p_cfg["base_url"],
            key,
            probe_payload,
            timeout_s=timeout_s,
        )
    except Exception as err:
        return {
            "provider": provider_key,
            "tier": tier_key,
            "requested_model": t_cfg["model"],
            "status": None,
            "done": False,
            "success": False,
            "error": f"TransportException: {type(err).__name__}: {err}",
            "elapsed_ms": (time.monotonic() - start_time) * 1000.0,
        }

    status_code = resp.get("status")
    done = bool(resp.get("done"))
    response_model = resp.get("response_model")
    final_usage = resp.get("final_usage")

    model_match = response_model == t_cfg["model"]
    is_success = (status_code == 200) and done and bool(final_usage)

    return {
        "provider": provider_key,
        "tier": tier_key,
        "requested_model": t_cfg["model"],
        "response_model": response_model,
        "model_match": model_match,
        "status": status_code,
        "done": done,
        "final_usage": final_usage,
        "headers": resp.get("headers", {}),
        "error": resp.get("error"),
        "success": is_success,
        "elapsed_ms": (time.monotonic() - start_time) * 1000.0,
    }


def run(
    plan_path: Path | str,
    provider_key: str,
    ledger_path: Path | str | None = None,
    matrix_path: Path | str = "providers/benchmark-matrix.json",
    api_key: str | None = None,
    mock_transport: Callable[..., dict[str, Any]] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    max_requests: int = 0,
    inter_request_sleep: float = 2.0,
) -> dict[str, Any]:
    """Execute benchmark plan for a specific provider with strict budget ledger."""
    manifest, all_tasks = _validate_plan(plan_path)

    matrix_file = Path(matrix_path)
    if matrix_file.is_file():
        matrix_cfg = load_matrix(matrix_file)
    else:
        # Fallback to matrix file recorded in manifest
        matrix_cfg = load_matrix(manifest.get("matrix_file", matrix_path))

    if provider_key not in matrix_cfg["providers"]:
        raise MatrixBenchError(f"Provider '{provider_key}' not defined in benchmark matrix")
    p_cfg = matrix_cfg["providers"][provider_key]

    # Validate ledger budget cap
    cap_usd_str = str(p_cfg["budget_cap_usd"])
    cap_usd = Decimal(cap_usd_str)
    if provider_key == "lithos":
        if cap_usd > LITHOS_MAX_CAP:
            raise MatrixBenchError(f"Lithos budget cap ({cap_usd}) exceeds maximum allowed ({LITHOS_MAX_CAP})")
    else:
        if cap_usd > NEW_PROVIDER_MAX_CAP:
            raise MatrixBenchError(f"Provider {provider_key} budget cap ({cap_usd}) exceeds maximum allowed ({NEW_PROVIDER_MAX_CAP})")

    if ledger_path is None:
        ledger_path = Path("results") / f"{provider_key}-budget.jsonl"
    ledger_p = Path(ledger_path)

    # API key verification
    key = api_key or os.environ.get(p_cfg["env_name"])
    if not key:
        raise MatrixBenchError(f"API key unavailable for provider '{provider_key}': env var '{p_cfg['env_name']}' is not set")

    # Filter tasks for this provider and order them
    provider_tasks = [t for t in all_tasks if t.get("provider") == provider_key]
    if not provider_tasks:
        raise MatrixBenchError(f"No tasks found in plan for provider '{provider_key}'")
    ordered_tasks = _request_order(provider_tasks)

    # Set up records journal paths
    recpath = Path(str(ledger_p) + ".records.jsonl")
    evpath = Path(str(ledger_p) + ".events.jsonl")
    notbefore = Path(str(ledger_p) + ".not-before.json")

    # Also record in plan directory for audit convenience
    plan_dir = Path(plan_path) if Path(plan_path).is_dir() else Path(plan_path).parent
    plan_recpath = plan_dir / "records" / f"{provider_key}.records.jsonl"

    if notbefore.exists():
        raise MatrixBenchError(f"Persistent rate-limit cooldown present at {notbefore}; manual review required")

    existing_records: list[dict[str, Any]] = []
    if recpath.exists():
        try:
            for line in recpath.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    rec = json.loads(line)
                    if not isinstance(rec, dict) or "request_id" not in rec:
                        raise MatrixBenchError("Record journal entry malformed")
                    existing_records.append(rec)
        except Exception as err:
            raise MatrixBenchError(f"Failed to read existing records journal: {err}") from err

    done_ids = {r["request_id"] for r in existing_records}
    if len(done_ids) != len(existing_records):
        raise MatrixBenchError("Duplicate request_id found in record journal")

    sent = 0
    completed = 0
    consecutive_failures = 0
    transport_fn = mock_transport or transport.stream_chat

    # Instantiate independent BudgetLedger for this provider
    with budget.BudgetLedger(ledger_p, cap_usd_str) as led:
        if not led.snapshot().get("healthy") or led.overrun:
            raise MatrixBenchError("Ledger is unhealthy or in overrun state")

        ledger_ids = set(led._requests)
        if done_ids - ledger_ids:
            raise MatrixBenchError("Record journal contains IDs absent from trusted ledger")

        # Check for unresolved holds from this plan
        unresolved = [
            t["request_id"]
            for t in ordered_tasks
            if t["request_id"] in led._requests and led._requests[t["request_id"]].get("status") == "reserved"
        ]
        if unresolved:
            raise MatrixBenchError("Unresolved request reservation found in ledger; manual reconciliation required")

        for task in ordered_tasks:
            rid = task["request_id"]
            if rid in led._requests:
                continue

            if max_requests > 0 and sent >= max_requests:
                break

            upper_usd = task["upper_usd"]
            # Fail-closed budget reservation before network call
            if not led.reserve(rid, upper_usd):
                # Budget cap reached, cease execution cleanly
                break

            rec = {
                "request_id": rid,
                "run_id": task["run_id"],
                "provider": provider_key,
                "tier": task["tier"],
                "pair_id": task["pair_id"],
                "group_id": task["group_id"],
                "kind": task["kind"],
                "target_tokens": task["target_tokens"],
                "repeat_index": task["repeat_index"],
                "payload": task["payload"],
            }
            tr: dict[str, Any] = {}
            code: int | None = None
            actual: str | None = None
            basis = "unknown"
            status = "unknown"

            try:
                audit_ok = [True]

                def on_event_cb(ev: dict[str, Any]) -> None:
                    try:
                        _append_jsonl(evpath, {"request_id": rid, "event": ev})
                    except Exception:
                        audit_ok[0] = False
                        raise AuditWriteFailed("Failed to persist streaming event")

                sent += 1
                payload = dict(task["payload"])
                if provider_key == "baseten":
                    payload["stream_options"] = {"include_usage": True}
                resp = transport_fn(p_cfg["base_url"], key, payload, on_event=on_event_cb)
                tr = resp
                code = resp.get("status")
                is_done = bool(resp.get("done"))

                if code == 200 and is_done:
                    u = resp.get("final_usage") or {}
                    pt = u.get("prompt_tokens")
                    ct = u.get("completion_tokens")
                    ch = (
                        u.get("prompt_cache_hit_tokens")
                        or u.get("prompt_cached_tokens")
                        or (u.get("prompt_tokens_details") or {}).get("cached_tokens")
                        or 0
                    )

                    if not isinstance(pt, int) or not isinstance(ct, int) or pt < 0 or ct < 0:
                        status = "invalid_usage"
                    elif pt > task["input_upper_tokens"] or ct > task["output_cap_tokens"]:
                        status = "usage_bound_violation"
                    elif resp.get("response_model") != task["payload"]["model"] and not (
                        provider_key == "baseten"
                        and resp.get("response_model") in ("deepseek-v4.1-flash", "deepseek-ai/DeepSeek-V4.1-Flash")
                    ):
                        status = "model_mismatch"
                    else:
                        actual = str(calculate_cost(provider_key, task["tier"], pt, ch, ct, matrix_cfg))
                        basis = "usage_reported"
                        status = "complete"
                elif code == 200 and not is_done:
                    status = "stream_break"
                elif code == 429:
                    status = "rate_limited"
                elif code in (401, 402, 403, 404):
                    status = f"http_{code}"
                else:
                    status = f"http_{code if code is not None else 'unknown'}"

                if actual is None:
                    actual = upper_usd
                if Decimal(actual) > Decimal(upper_usd):
                    status = "usage_over_cap"
                if not audit_ok[0]:
                    status = "audit_callback_failure"

                rec.update(
                    transport=tr,
                    accounting={
                        "reserved_usd": upper_usd,
                        "computed_usd": actual if status == "complete" else None,
                        "basis": basis if status == "complete" else status,
                    },
                    status=status,
                )

                # Durable terminal record before settlement
                _append_jsonl(recpath, rec)
                if plan_recpath != recpath:
                    _append_jsonl(plan_recpath, rec)

                done_ids.add(rid)

                if status == "complete":
                    led.settle(rid, actual)
                    completed += 1
                    consecutive_failures = 0
                else:
                    consecutive_failures += 1

            except Exception as exc:
                if isinstance(exc, AuditWriteFailed):
                    raise
                rec.update(
                    transport=tr,
                    accounting={"reserved_usd": upper_usd, "computed_usd": None, "basis": "unknown_hold"},
                    status="execution_exception",
                    error_type=type(exc).__name__,
                )
                try:
                    _append_jsonl(recpath, rec)
                    if plan_recpath != recpath:
                        _append_jsonl(plan_recpath, rec)
                except Exception:
                    raise MatrixBenchError("Record persistence failed; reservation retained") from None
                break

            # 429 handling & cooldown
            if code == 429:
                retry_after = (tr.get("headers") or {}).get("retry-after") or (tr.get("headers") or {}).get("retry-after-ms")
                _append_jsonl(notbefore, {"request_id": rid, "retry_after": retry_after, "status": "429"})
                break

            # Immediate abort on fatal errors
            if code in (401, 402, 403, 404) or status in (
                "model_mismatch",
                "invalid_usage",
                "usage_bound_violation",
                "usage_over_cap",
                "audit_callback_failure",
            ):
                break

            # Circuit breaker: 3 consecutive non-complete failures
            if consecutive_failures >= 3:
                break

            if not led.snapshot().get("healthy") or led.overrun:
                raise MatrixBenchError("Ledger is unhealthy or in overrun state")

            sleep(inter_request_sleep)

    return {
        "provider": provider_key,
        "sent": sent,
        "completed": completed,
        "failures": consecutive_failures,
        "records_path": str(recpath),
        "events_path": str(evpath),
        "ledger_path": str(ledger_p),
    }


def main(argv: list[str] | None = None) -> int:
    """CLI dispatcher."""
    p = argparse.ArgumentParser(description="Cross-provider unified matrix benchmark")
    sub = p.add_subparsers(dest="cmd", required=True)

    # plan
    plan_p = sub.add_parser("plan", help="Generate benchmark plan")
    plan_p.add_argument("--matrix", default="providers/benchmark-matrix.json", help="Path to matrix configuration JSON")
    plan_p.add_argument("--output", required=True, help="Output directory for plan")
    plan_p.add_argument("--groups", type=int, default=3, help="Prefix groups per size (>= 3)")
    plan_p.add_argument("--throughput-groups", type=int, default=3, help="Throughput groups (>= 1)")
    plan_p.add_argument("--seed", type=int, default=42, help="Deterministic seed")
    plan_p.add_argument("--run-id", default="matrix-v1", help="Benchmark run identifier")
    plan_p.add_argument("--bytes-per-token", "--bpt", dest="bpt", type=float, default=2.0, help="Bytes per token estimate")
    plan_p.add_argument("--force", "--overwrite", dest="force", action="store_true", help="Overwrite existing output directory")

    # probe
    probe_p = sub.add_parser("probe", help="Probe provider connectivity and usage structure")
    probe_p.add_argument("--provider", required=True, help="Provider key")
    probe_p.add_argument("--tier", required=True, help="Tier key")
    probe_p.add_argument("--matrix", default="providers/benchmark-matrix.json", help="Path to matrix configuration JSON")
    probe_p.add_argument("--api-key", help="API key override")
    probe_p.add_argument("--timeout", type=float, default=30.0, help="Timeout in seconds")

    # run
    run_p = sub.add_parser("run", help="Run benchmark against provider")
    run_p.add_argument("--plan", required=True, help="Path to plan directory or manifest.json")
    run_p.add_argument("--provider", required=True, help="Provider key")
    run_p.add_argument("--ledger", help="Path to budget ledger file (default results/<provider>-budget.jsonl)")
    run_p.add_argument("--matrix", default="providers/benchmark-matrix.json", help="Path to matrix configuration JSON")
    run_p.add_argument("--api-key", help="API key override")
    run_p.add_argument("--max-requests", type=int, default=0, help="Maximum requests to dispatch (0 = unlimited)")
    run_p.add_argument("--inter-request-sleep", type=float, default=2.0, help="Sleep between requests in seconds")

    args = p.parse_args(argv)

    try:
        if args.cmd == "plan":
            manifest = plan(
                matrix_path=args.matrix,
                output_dir=args.output,
                groups=args.groups,
                throughput_groups=args.throughput_groups,
                seed=args.seed,
                run_id=args.run_id,
                bpt=args.bpt,
                force=args.force,
            )
            print(json.dumps(manifest, indent=2))
            return 0
        elif args.cmd == "probe":
            res = probe(
                provider_key=args.provider,
                tier_key=args.tier,
                matrix_path=args.matrix,
                api_key=args.api_key,
                timeout_s=args.timeout,
            )
            print(json.dumps(res, indent=2))
            return 0 if res.get("success") else 1
        elif args.cmd == "run":
            res = run(
                plan_path=args.plan,
                provider_key=args.provider,
                ledger_path=args.ledger,
                matrix_path=args.matrix,
                api_key=args.api_key,
                max_requests=args.max_requests,
                inter_request_sleep=args.inter_request_sleep,
            )
            print(json.dumps(res, indent=2))
            return 0
    except Exception as err:
        print(f"matrix_bench: {type(err).__name__}: {err}", file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
