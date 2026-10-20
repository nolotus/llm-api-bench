#!/usr/bin/env python3
"""Multi-tier benchmark analysis and paired contrast tool. Standard library only."""
from __future__ import annotations
import argparse, json, math, random, statistics
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

import analysis

BOOTSTRAPS = 500
TIERS = ("base", "fast", "ultra")
PHASE = "comparison_formal"


class TierAnalysisError(ValueError):
    """Raised when record contract, tier, pair, or uniqueness constraints are violated."""
    pass


def _finite(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _record_ttft(r: dict) -> float | None:
    t = analysis._transport(r)
    if t.get("status") != 200 or t.get("done") is not True or t.get("error"):
        return None
    v = t.get("first_content_ms")
    if _finite(v) and v >= 0:
        return float(v)
    return None


def _record_chunk_rate(r: dict) -> float | None:
    t = analysis._transport(r)
    u = analysis._usage(r)
    n = u.get("completion")
    if t.get("status") != 200 or t.get("done") is not True or t.get("error"):
        return None
    if not analysis._valid_count(n) or n < 256:
        return None
    es = analysis._events(r)
    content = []
    reasoning = False
    for e in es:
        choices = e.get("choices")
        if not isinstance(choices, list):
            continue
        for ch in choices:
            delta = ch.get("delta", {}) if isinstance(ch, dict) else {}
            if not isinstance(delta, dict):
                continue
            if delta.get("reasoning_content"):
                reasoning = True
            text = delta.get("content")
            if isinstance(text, str) and text:
                content.append(e.get("elapsed_ns"))
    if reasoning or len(content) < 2 or any(not _finite(x) for x in content):
        return None
    duration = (content[-1] - content[0]) / 1e9
    if duration <= 0:
        return None
    return float(n / duration)


def _paired_metric_summary(values_by_pair: dict[str, float], seed: int) -> dict:
    valid_items = [(pid, val) for pid, val in values_by_pair.items() if val is not None and _finite(val)]
    n = len(valid_items)
    if n == 0:
        return {
            "n": 0,
            "mean": None,
            "median": None,
            "p50": None,
            "iqr": None,
            "min": None,
            "max": None,
            "median95_ci": None,
        }
    vals = sorted(val for _, val in valid_items)
    mean = float(statistics.mean(vals))
    median = float(statistics.median(vals))
    p50 = median
    lo = float(vals[0])
    hi = float(vals[-1])
    if n > 1:
        q = statistics.quantiles(vals, n=4, method="inclusive")
        iqr = float(q[2] - q[0])
    else:
        iqr = 0.0

    # Gate bootstrap CI on >= 20 pairs
    if n < 20:
        ci = None
    else:
        pair_ids = sorted(pid for pid, _ in valid_items)
        rng = random.Random(seed)
        meds = []
        for _ in range(BOOTSTRAPS):
            sample = [values_by_pair[pair_ids[rng.randrange(n)]] for _ in range(n)]
            meds.append(float(statistics.median(sample)))
        meds.sort()
        ci = [meds[12], meds[487]] if len(meds) == BOOTSTRAPS else None

    return {
        "n": n,
        "mean": mean,
        "median": median,
        "p50": p50,
        "iqr": iqr,
        "min": lo,
        "max": hi,
        "median95_ci": ci,
    }


def summarize_tiers(records: Iterable[dict], run_id: str, seed: int = 20261020) -> dict:
    rows = list(records)
    total_records = len(rows)

    excluded_other_run = 0
    excluded_pilot = 0
    excluded_legacy_formal = 0
    excluded_non_comparison_formal = 0

    valid_records: list[dict] = []
    seen_request_ids: set[str] = set()
    seen_pair_tier_groups: dict[tuple[str, str], str] = {}
    seen_group_to_owner: dict[str, tuple[str, str]] = {}
    seen_pair_tier_reps: set[tuple[str, str, int]] = set()
    seen_pair_identity: dict[str, tuple[str, int]] = {}

    for idx, r in enumerate(rows):
        if not isinstance(r, dict):
            raise TierAnalysisError(f"Row {idx} is not a dict: got {type(r).__name__}")
        r_run = r.get("run_id")
        phase = r.get("phase")

        if r_run != run_id:
            excluded_other_run += 1
            if phase == "pilot":
                excluded_pilot += 1
            elif phase == "formal":
                excluded_legacy_formal += 1
            continue

        if phase != PHASE:
            excluded_non_comparison_formal += 1
            if phase == "pilot":
                excluded_pilot += 1
            elif phase == "formal":
                excluded_legacy_formal += 1
            continue

        # Strict validation on comparison_formal records for target run_id
        rid = r.get("request_id")
        if not rid or not isinstance(rid, str):
            raise TierAnalysisError(f"Record at index {idx} has missing or non-string request_id: {rid!r}")
        if rid in seen_request_ids:
            raise TierAnalysisError(f"Duplicate request_id encountered: {rid}")
        seen_request_ids.add(rid)

        tier = r.get("tier")
        if not tier or tier not in TIERS:
            raise TierAnalysisError(f"Record {rid} has missing or invalid tier: {tier!r}. Must be one of {TIERS}")

        pair_id = r.get("pair_id")
        if pair_id is None or pair_id == "":
            raise TierAnalysisError(f"Record {rid} has missing or empty pair_id")

        group_id = r.get("group_id")
        if group_id is None or group_id == "":
            raise TierAnalysisError(f"Record {rid} has missing or empty group_id")

        kind = r.get("kind")
        if kind not in ("long", "throughput"):
            raise TierAnalysisError(f"Record {rid} has invalid kind: {kind!r}. Must be 'long' or 'throughput'")

        target = r.get("target_tokens")
        if isinstance(target, bool) or not isinstance(target, int) or target <= 0:
            raise TierAnalysisError(f"Record {rid} has invalid target_tokens: {target!r}. Must be a positive integer")

        rep = r.get("repeat_index")
        if isinstance(rep, bool) or not isinstance(rep, int):
            raise TierAnalysisError(f"Record {rid} has invalid repeat_index: {rep!r}. Must be an integer")
        if kind == "throughput" and rep != 0:
            raise TierAnalysisError(f"Record {rid} is throughput but repeat_index is {rep}. Must be 0")
        if kind == "long" and rep not in range(5):
            raise TierAnalysisError(f"Record {rid} is long but repeat_index is {rep}. Must be in 0..4")

        # 1. Consistent group_id for same (pair_id, tier)
        pair_tier_key = (pair_id, tier)
        if pair_tier_key in seen_pair_tier_groups:
            if seen_pair_tier_groups[pair_tier_key] != group_id:
                raise TierAnalysisError(
                    f"Record {rid}: inconsistent group_id for pair {pair_id} tier {tier}: "
                    f"{group_id!r} != {seen_pair_tier_groups[pair_tier_key]!r}"
                )
        else:
            seen_pair_tier_groups[pair_tier_key] = group_id

        # 2. Reverse mapping: group_id is bound strictly to (pair_id, tier)
        if group_id in seen_group_to_owner:
            if seen_group_to_owner[group_id] != pair_tier_key:
                raise TierAnalysisError(
                    f"Record {rid}: group_id {group_id!r} reused across different pair/tier: "
                    f"{pair_tier_key} vs {seen_group_to_owner[group_id]}"
                )
        else:
            seen_group_to_owner[group_id] = pair_tier_key

        # 3. No duplicate repeat_index for the same (pair_id, tier)
        rep_key = (pair_id, tier, rep)
        if rep_key in seen_pair_tier_reps:
            raise TierAnalysisError(f"Record {rid}: duplicate repeat_index {rep} for pair {pair_id} tier {tier}")
        seen_pair_tier_reps.add(rep_key)

        # 4. Consistency of kind and target_tokens per pair_id
        pair_identity = (kind, target)
        if pair_id in seen_pair_identity:
            if seen_pair_identity[pair_id] != pair_identity:
                raise TierAnalysisError(
                    f"Record {rid}: pair_id {pair_id!r} has conflicting kind/target: "
                    f"{pair_identity} vs {seen_pair_identity[pair_id]}"
                )
        else:
            seen_pair_identity[pair_id] = pair_identity

        valid_records.append(r)

    # 1. Independent per-tier summarization using analysis.summarize
    tier_summaries: dict[str, dict] = {}
    for t in TIERS:
        tier_recs = [dict(r, phase="formal") for r in valid_records if r.get("tier") == t]
        tier_summaries[t] = analysis.summarize(tier_recs, seed=seed)

    # 2. Paired comparison stratified by (kind, target_tokens, fresh/reuse) tuple
    strata_pairs: dict[tuple[str, int, str], dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for r in valid_records:
        kind = r["kind"]
        target = r["target_tokens"]
        rep = r.get("repeat_index", 0)
        freshness = "reuse" if rep > 0 else "fresh"
        stratum_key = (kind, target, freshness)
        pair_id = str(r["pair_id"])
        strata_pairs[stratum_key][pair_id].append(r)

    paired_comparisons: dict[str, dict] = {}
    all_warnings: list[str] = []

    for stratum_tuple in sorted(strata_pairs.keys(), key=lambda t: (t[0], t[1], t[2])):
        kind_val, target_val, freshness_val = stratum_tuple
        stratum_display_key = f"{kind_val}|{target_val}|{freshness_val}"
        pairs_dict = strata_pairs[stratum_tuple]
        pairs_total = len(pairs_dict)

        complete_pairs: dict[str, dict[str, Any]] = {}
        missing_pairs = 0
        missing_by_tier = {t: 0 for t in TIERS}

        # Track token fairness across complete pairs
        pair_prompt_tokens: dict[str, dict[str, int]] = {}
        pair_completion_tokens: dict[str, dict[str, int]] = {}

        for pid, p_recs in sorted(pairs_dict.items()):
            pair_reps = set(r.get("repeat_index", 0) for r in p_recs)
            recs_by_tier = {t: [r for r in p_recs if r.get("tier") == t] for t in TIERS}

            tier_ttfts: dict[str, float | None] = {}
            tier_speeds: dict[str, float | None] = {}
            tier_prompts: dict[str, int | None] = {}
            tier_completions: dict[str, int | None] = {}
            tier_succ_reps: dict[str, set[int]] = {}

            for t in TIERS:
                trecs = recs_by_tier[t]
                succ_ttfts = []
                succ_reps = set()
                for r in trecs:
                    v = _record_ttft(r)
                    if v is not None:
                        succ_ttfts.append(v)
                        succ_reps.add(r.get("repeat_index", 0))

                tier_succ_reps[t] = succ_reps
                tier_ttfts[t] = float(statistics.median(succ_ttfts)) if succ_ttfts else None

                speeds = [_record_chunk_rate(r) for r in trecs]
                valid_speeds = [x for x in speeds if x is not None]
                tier_speeds[t] = float(statistics.median(valid_speeds)) if valid_speeds else None

                prompts = [analysis._usage(r).get("prompt") for r in trecs]
                valid_prompts = [x for x in prompts if x is not None]
                tier_prompts[t] = int(round(statistics.median(valid_prompts))) if valid_prompts else None

                completions = [analysis._usage(r).get("completion") for r in trecs]
                valid_completions = [x for x in completions if x is not None]
                tier_completions[t] = int(round(statistics.median(valid_completions))) if valid_completions else None

            # All three tiers must have all reps in pair_reps successfully to be complete
            missing_tiers = [t for t in TIERS if tier_succ_reps[t] != pair_reps or len(pair_reps) == 0]
            if missing_tiers:
                missing_pairs += 1
                for mt in missing_tiers:
                    missing_by_tier[mt] += 1
            else:
                complete_pairs[pid] = {
                    "ttft": tier_ttfts,
                    "speed": tier_speeds,
                    "prompt": tier_prompts,
                    "completion": tier_completions,
                }
                if all(tier_prompts[t] is not None for t in TIERS):
                    pair_prompt_tokens[pid] = {t: tier_prompts[t] for t in TIERS}  # type: ignore
                if all(tier_completions[t] is not None for t in TIERS):
                    pair_completion_tokens[pid] = {t: tier_completions[t] for t in TIERS}  # type: ignore

        # Prepare pairwise contrasts
        contrasts = (
            ("fast_vs_base", "fast", "base"),
            ("ultra_vs_base", "ultra", "base"),
            ("ultra_vs_fast", "ultra", "fast"),
        )
        comparisons_res: dict[str, dict] = {}
        for cname, target_tier, ref_tier in contrasts:
            diff_by_pair: dict[str, float] = {}
            ratio_by_pair: dict[str, float] = {}
            speed_ratio_by_pair: dict[str, float] = {}

            for pid, pdata in complete_pairs.items():
                t_val = pdata["ttft"][target_tier]
                r_val = pdata["ttft"][ref_tier]
                diff_by_pair[pid] = t_val - r_val
                if r_val > 0:
                    ratio_by_pair[pid] = t_val / r_val

                t_speed = pdata["speed"][target_tier]
                r_speed = pdata["speed"][ref_tier]
                if t_speed is not None and r_speed is not None and r_speed > 0:
                    speed_ratio_by_pair[pid] = t_speed / r_speed

            # Seed offsets per metric for deterministic independent bootstrap
            diff_summary = _paired_metric_summary(diff_by_pair, seed=seed)
            diff_summary["formula"] = f"{target_tier} - {ref_tier} (ms)"
            diff_summary["direction"] = f"Negative values mean {target_tier} had lower TTFT (started sooner)."

            ratio_summary = _paired_metric_summary(ratio_by_pair, seed=seed)
            ratio_summary["formula"] = f"{target_tier} / {ref_tier}"
            ratio_summary["direction"] = f"Ratio < 1.0 means {target_tier} had lower TTFT."

            speed_summary = _paired_metric_summary(speed_ratio_by_pair, seed=seed)
            speed_summary["formula"] = f"{target_tier} / {ref_tier}"
            speed_summary["direction"] = f"Ratio > 1.0 means {target_tier} had higher chunk throughput."
            speed_summary["note"] = (
                "Approximate chunk speed ratio for long outputs (>= 256 completion tokens); "
                "null when not estimable, single chunk, or reasoning present."
            )

            comparisons_res[cname] = {
                "first_content_ms_diff": diff_summary,
                "first_content_ms_ratio": ratio_summary,
                "chunk_speed_ratio": speed_summary,
            }

        # Token fairness and output length check
        max_prompt_diff = 0
        for pid, pts in pair_prompt_tokens.items():
            diff = max(pts.values()) - min(pts.values())
            if diff > max_prompt_diff:
                max_prompt_diff = diff

        max_completion_diff = 0
        for pid, cts in pair_completion_tokens.items():
            diff = max(cts.values()) - min(cts.values())
            if diff > max_completion_diff:
                max_completion_diff = diff

        stratum_warnings: list[str] = []
        if max_completion_diff > 0:
            w = (
                f"Stratum [{stratum_display_key}]: Output length variation observed across tiers "
                f"(maximum within-pair completion token difference: {max_completion_diff}). "
                f"Compare throughput and chunk speeds with caution as generation lengths differed."
            )
            stratum_warnings.append(w)
            all_warnings.append(w)

        token_fairness = {
            "max_within_pair_prompt_token_diff": max_prompt_diff,
            "max_within_pair_completion_token_diff": max_completion_diff,
            "has_output_length_discrepancy": max_completion_diff > 0,
            "prompt_tokens_mean_by_tier": {
                t: (float(statistics.mean([pts[t] for pts in pair_prompt_tokens.values()])) if pair_prompt_tokens else None)
                for t in TIERS
            },
            "completion_tokens_mean_by_tier": {
                t: (float(statistics.mean([cts[t] for cts in pair_completion_tokens.values()])) if pair_completion_tokens else None)
                for t in TIERS
            },
            "nonce_token_deviation_disclosure": (
                "Prompts across tiers share identical task templates and sizing targets, but each has a 24-character "
                "tier-specific nonce near the prefix start to isolate caches across tiers. Provider token counts may "
                "vary slightly due to nonce tokenization boundaries."
            ),
        }

        paired_comparisons[stratum_display_key] = {
            "stratum": {
                "kind": kind_val,
                "target_tokens": target_val,
                "freshness": freshness_val,
            },
            "pairs_total": pairs_total,
            "pairs_complete": len(complete_pairs),
            "missing_pairs": missing_pairs,
            "missing_details_by_tier": missing_by_tier,
            "comparisons": comparisons_res,
            "token_fairness": token_fairness,
            "winner_policy": "No majority-vote winner declared; report signed numeric contrasts directly.",
            "warnings": stratum_warnings,
        }

    # 3. Cost accounting summary (explicitly local computed, NOT provider bill)
    computed_cost_by_tier: dict[str, Decimal] = {t: Decimal("0") for t in TIERS}
    reserved_by_tier: dict[str, Decimal] = {t: Decimal("0") for t in TIERS}
    unknown_holds_count = 0
    unknown_holds_reserved = Decimal("0")
    cache_unknown_count: dict[str, int] = {t: 0 for t in TIERS}

    for r in valid_records:
        t = r["tier"]
        acc = r.get("accounting")
        if isinstance(acc, dict):
            comp = acc.get("computed_usd")
            resv = acc.get("reserved_usd")
            basis = acc.get("basis")

            if resv is not None:
                try:
                    reserved_by_tier[t] += Decimal(str(resv))
                except Exception:
                    pass

            if comp is not None:
                try:
                    computed_cost_by_tier[t] += Decimal(str(comp))
                except Exception:
                    pass
            else:
                unknown_holds_count += 1
                if resv is not None:
                    try:
                        unknown_holds_reserved += Decimal(str(resv))
                    except Exception:
                        pass

            if basis == "unknown":
                unknown_holds_count += 1

        # Check cache unknown status from transport usage
        u = analysis._usage(r)
        if u.get("cached") is None:
            cache_unknown_count[t] += 1

    total_computed = sum(computed_cost_by_tier.values())
    total_reserved = sum(reserved_by_tier.values())
    total_cache_unknown = sum(cache_unknown_count.values())

    accounting_summary = {
        "label": "Computed local accounting cost, NOT provider invoice or billing",
        "computed_cost_by_tier_usd": {t: str(computed_cost_by_tier[t]) for t in TIERS},
        "computed_cost_total_usd": str(total_computed),
        "reserved_by_tier_usd": {t: str(reserved_by_tier[t]) for t in TIERS},
        "reserved_total_usd": str(total_reserved),
        "unknown_holds": {
            "count": unknown_holds_count,
            "reserved_usd": str(unknown_holds_reserved),
        },
        "cache_unknown_count": total_cache_unknown,
        "cache_unknown_by_tier": cache_unknown_count,
        "note": (
            "Actual costs are locally priced using measured tokens and registered rates. "
            "Unsettled/unknown holds and cache-unknown requests are tracked separately and not coerced to zero."
        ),
    }

    report = {
        "run_id": run_id,
        "seed": seed,
        "total_records_read": total_records,
        "excluded_other_run": excluded_other_run,
        "excluded_pilot": excluded_pilot,
        "excluded_legacy_formal": excluded_legacy_formal,
        "excluded_non_comparison_formal": excluded_non_comparison_formal,
        "valid_comparison_formal_requests": len(valid_records),
        "tiers": tier_summaries,
        "paired_comparisons": paired_comparisons,
        "accounting_summary": accounting_summary,
        "warnings": all_warnings,
        "disclosures_and_limitations": {
            "precision_policy": (
                "When sample size n < 20, confidence intervals are suppressed (null). "
                "Small sample sizes do not provide stability or precision guarantees."
            ),
            "statistical_claims": (
                "No universal statistical significance or model weight identity is claimed. "
                "Pairwise metrics report observed sample differences and ratios; no majority-vote winner is declared."
            ),
            "prompt_nonce_skew": (
                "Prompts across tiers share the same template except for a 24-character tier-specific nonce near the "
                "prefix start to prevent cross-tier cache contamination. Minor prompt token differences may exist."
            ),
            "cost_accounting": "Cost sums are locally computed from usage and declared price schedules, NOT verified provider billings or invoices.",
            "timing_measurements": "Client receive-time measurements include network and client event chunk behavior, not server token-time.",
        },
    }
    return report


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("input", type=Path, help="Input records.jsonl file")
    p.add_argument("--run-id", required=True, help="Target comparison run_id")
    p.add_argument("--output", type=Path, required=True, help="Output report JSON file")
    p.add_argument("--seed", type=int, default=20261020, help="Random seed for bootstrap (default: 20261020)")
    args = p.parse_args(argv)

    records = []
    with args.input.open(encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            if line.strip():
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError as e:
                    p.error(f"line {i}: invalid JSON: {e.msg}")

    try:
        report = summarize_tiers(records, run_id=args.run_id, seed=args.seed)
    except Exception as e:
        p.error(str(e))

    args.output.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
