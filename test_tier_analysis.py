#!/usr/bin/env python3
"""Comprehensive unit tests for tier_analysis.py."""
import json, subprocess, sys, tempfile, unittest
from pathlib import Path

import tier_analysis as ta


def make_event(ns, content=None, reasoning=None):
    delta = {}
    if content is not None:
        delta["content"] = content
    if reasoning is not None:
        delta["reasoning_content"] = reasoning
    return {"elapsed_ns": ns, "data": json.dumps({"choices": [{"delta": delta}]})}


def make_record(**kw):
    pair_id = kw.get("pair_id", "pair-001")
    tier = kw.get("tier", "base")
    d = {
        "request_id": "req-001",
        "run_id": "test-run",
        "tier": tier,
        "pair_id": pair_id,
        "group_id": f"{pair_id}-{tier}",
        "phase": "comparison_formal",
        "kind": "long",
        "target_tokens": 1000,
        "repeat_index": 0,
        "protocol": "tier-comparison-v1",
        "request": {"model": "base-model", "messages": [{"role": "user", "content": "hi"}], "stream": True},
        "transport": {
            "status": 200,
            "done": True,
            "error": None,
            "headers_ms": 10.0,
            "first_generated_ms": 15.0,
            "first_content_ms": 20.0,
            "last_generated_ms": 100.0,
            "total_ms": 110.0,
            "final_usage": {
                "prompt_tokens": 100,
                "completion_tokens": 300,
                "prompt_tokens_details": {"cached_tokens": 50},
            },
            "events": [make_event(1_000_000, "chunk1"), make_event(101_000_000, "chunk2")],
        },
        "accounting": {
            "reserved_usd": "0.001",
            "computed_usd": "0.0005",
            "basis": "provider_usage",
        },
    }
    d.update(kw)
    return d


def make_block(pair_id, run_id="test-run", kind="long", target_tokens=1000, repeat_index=0,
               base_ttft=100.0, fast_ttft=80.0, ultra_ttft=60.0,
               base_tokens=300, fast_tokens=300, ultra_tokens=300,
               base_events=None, fast_events=None, ultra_events=None,
               base_status=200, fast_status=200, ultra_status=200,
               base_done=True, fast_done=True, ultra_done=True,
               base_error=None, fast_error=None, ultra_error=None):
    recs = []
    configs = [
        ("base", base_ttft, base_tokens, base_events, base_status, base_done, base_error),
        ("fast", fast_ttft, fast_tokens, fast_events, fast_status, fast_done, fast_error),
        ("ultra", ultra_ttft, ultra_tokens, ultra_events, ultra_status, ultra_done, ultra_error),
    ]
    for tier, ttft, comp_tokens, evs, status, done, err in configs:
        if evs is None:
            evs = [make_event(1_000_000, "start"), make_event(101_000_000, "end")]
        recs.append(
            make_record(
                request_id=f"{run_id}-{pair_id}-{tier}",
                run_id=run_id,
                tier=tier,
                pair_id=pair_id,
                group_id=f"{pair_id}-{tier}",
                phase="comparison_formal",
                kind=kind,
                target_tokens=target_tokens,
                repeat_index=repeat_index,
                transport={
                    "status": status,
                    "done": done,
                    "error": err,
                    "first_content_ms": ttft,
                    "total_ms": ttft + 50.0,
                    "final_usage": {
                        "prompt_tokens": 100,
                        "completion_tokens": comp_tokens,
                        "prompt_tokens_details": {"cached_tokens": 20},
                    },
                    "events": evs,
                },
                accounting={
                    "reserved_usd": "0.001",
                    "computed_usd": "0.0005",
                    "basis": "provider_usage",
                },
            )
        )
    return recs


class TestTierAnalysis(unittest.TestCase):
    def test_old_record_filtering(self):
        """Test exclusion and counting of old 931 formal, 23 pilot, and other run records."""
        records = [
            # 931 legacy formal records from prior run
            *[make_record(request_id=f"legacy-{i}", run_id="formal-v1", phase="formal") for i in range(931)],
            # 23 pilot records
            *[make_record(request_id=f"pilot-{i}", run_id="formal-v1", phase="pilot") for i in range(23)],
            # Candidate records for target comparison run
            *make_block("pair-001", run_id="comparison-run-v1"),
            # Same target run but non-comparison_formal phase
            make_record(request_id="comp-pilot", run_id="comparison-run-v1", phase="pilot"),
            make_record(request_id="comp-formal", run_id="comparison-run-v1", phase="formal"),
        ]

        report = ta.summarize_tiers(records, run_id="comparison-run-v1")
        self.assertEqual(report["total_records_read"], 931 + 23 + 3 + 2)
        self.assertEqual(report["excluded_other_run"], 954)
        self.assertEqual(report["excluded_legacy_formal"], 932)  # 931 old run + 1 this run
        self.assertEqual(report["excluded_pilot"], 24)  # 23 old run + 1 this run
        self.assertEqual(report["excluded_non_comparison_formal"], 2)
        self.assertEqual(report["valid_comparison_formal_requests"], 3)
        self.assertEqual(report["tiers"]["base"]["formal_requests"], 1)

    def test_tier_separation_not_mixed(self):
        """Test that per-tier records are segregated and not mixed."""
        records = make_block("p1", base_ttft=100.0, fast_ttft=50.0, ultra_ttft=25.0)
        report = ta.summarize_tiers(records, run_id="test-run")

        strata_base = report["tiers"]["base"]["strata"]
        strata_fast = report["tiers"]["fast"]["strata"]
        strata_ultra = report["tiers"]["ultra"]["strata"]

        k = "long|1000|new"
        self.assertEqual(strata_base[k]["time_ms"]["first_content_ms"]["mean"], 100.0)
        self.assertEqual(strata_fast[k]["time_ms"]["first_content_ms"]["mean"], 50.0)
        self.assertEqual(strata_ultra[k]["time_ms"]["first_content_ms"]["mean"], 25.0)

    def test_duplicate_request_id_raises(self):
        """Test that duplicate request_ids in comparison_formal raise TierAnalysisError."""
        r1 = make_record(request_id="dup-1", tier="base")
        r2 = make_record(request_id="dup-1", tier="fast")
        with self.assertRaises(ta.TierAnalysisError) as ctx:
            ta.summarize_tiers([r1, r2], run_id="test-run")
        self.assertIn("Duplicate request_id", str(ctx.exception))

    def test_missing_or_invalid_tier_raises(self):
        """Test that missing or invalid tier raises TierAnalysisError."""
        r_missing = make_record(request_id="r1", tier=None)
        with self.assertRaises(ta.TierAnalysisError) as ctx:
            ta.summarize_tiers([r_missing], run_id="test-run")
        self.assertIn("missing or invalid tier", str(ctx.exception))

        r_invalid = make_record(request_id="r2", tier="turbo")
        with self.assertRaises(ta.TierAnalysisError) as ctx:
            ta.summarize_tiers([r_invalid], run_id="test-run")
        self.assertIn("missing or invalid tier", str(ctx.exception))

    def test_missing_pair_id_raises(self):
        """Test that missing or empty pair_id raises TierAnalysisError."""
        r_none = make_record(request_id="r1", pair_id=None)
        with self.assertRaises(ta.TierAnalysisError) as ctx:
            ta.summarize_tiers([r_none], run_id="test-run")
        self.assertIn("missing or empty pair_id", str(ctx.exception))

        r_empty = make_record(request_id="r2", pair_id="")
        with self.assertRaises(ta.TierAnalysisError) as ctx:
            ta.summarize_tiers([r_empty], run_id="test-run")
        self.assertIn("missing or empty pair_id", str(ctx.exception))

    def test_missing_pair_counting(self):
        """Test that incomplete pairs missing any tier are counted in missing_pairs, not 0."""
        records = []
        # Pair 1: complete
        records.extend(make_block("p1", base_ttft=100.0, fast_ttft=80.0, ultra_ttft=60.0))
        # Pair 2: missing ultra
        records.append(make_record(request_id="p2-b", tier="base", pair_id="p2"))
        records.append(make_record(request_id="p2-f", tier="fast", pair_id="p2"))
        # Pair 3: ultra failed (status 500)
        records.extend(make_block("p3", ultra_status=500, ultra_done=False))

        report = ta.summarize_tiers(records, run_id="test-run")
        stratum = report["paired_comparisons"]["long|1000|fresh"]
        self.assertEqual(stratum["pairs_total"], 3)
        self.assertEqual(stratum["pairs_complete"], 1)
        self.assertEqual(stratum["missing_pairs"], 2)
        self.assertEqual(stratum["missing_details_by_tier"]["ultra"], 2)
        self.assertEqual(stratum["missing_details_by_tier"]["base"], 0)

    def test_pair_bootstrap_gate_under_and_over_20(self):
        """Test bootstrap gating: null when pairs < 20, CI present when pairs >= 20."""
        # 5 pairs (< 20)
        small_records = []
        for i in range(5):
            small_records.extend(make_block(f"p{i}", base_ttft=100.0 + i, fast_ttft=80.0 + i, ultra_ttft=60.0 + i))
        rep_small = ta.summarize_tiers(small_records, run_id="test-run")
        c_small = rep_small["paired_comparisons"]["long|1000|fresh"]["comparisons"]["fast_vs_base"]["first_content_ms_diff"]
        self.assertEqual(c_small["n"], 5)
        self.assertIsNone(c_small["median95_ci"])

        # 25 pairs (>= 20)
        large_records = []
        for i in range(25):
            large_records.extend(make_block(f"p{i}", base_ttft=100.0 + i, fast_ttft=80.0 + (i % 3), ultra_ttft=60.0 + i))
        rep_large = ta.summarize_tiers(large_records, run_id="test-run")
        c_large = rep_large["paired_comparisons"]["long|1000|fresh"]["comparisons"]["fast_vs_base"]["first_content_ms_diff"]
        self.assertEqual(c_large["n"], 25)
        self.assertIsNotNone(c_large["median95_ci"])
        self.assertEqual(len(c_large["median95_ci"]), 2)
        self.assertLessEqual(c_large["median95_ci"][0], c_large["median95_ci"][1])

    def test_seed_determinism(self):
        """Test that bootstrap results are deterministic for the same seed."""
        records = []
        for i in range(25):
            records.extend(make_block(f"p{i}", base_ttft=100.0 + (i * 2), fast_ttft=80.0 + i, ultra_ttft=50.0 + i))
        res1 = ta.summarize_tiers(records, run_id="test-run", seed=12345)
        res2 = ta.summarize_tiers(records, run_id="test-run", seed=12345)
        self.assertEqual(res1, res2)

    def test_cache_unknown_not_coerced_to_zero(self):
        """Test that cache unknown is preserved and not converted to 0."""
        # Record with no cached_tokens field
        r = make_record(
            transport={
                "status": 200,
                "done": True,
                "error": None,
                "first_content_ms": 50.0,
                "final_usage": {"prompt_tokens": 100, "completion_tokens": 300},
                "events": [],
            }
        )
        report = ta.summarize_tiers([r], run_id="test-run")
        self.assertEqual(report["accounting_summary"]["cache_unknown_count"], 1)
        base_usage = report["tiers"]["base"]["strata"]["long|1000|new"]["usage"]
        self.assertEqual(base_usage["cache_known_requests"], 0)
        self.assertIsNone(base_usage["token_weighted_cached_rate"])

    def test_failed_requests_excluded_from_latency_and_ttft(self):
        """Test that failed requests (status != 200, done != True, error) are excluded."""
        recs = [
            make_record(request_id="r-ok", tier="base", pair_id="p1",
                        transport={"status": 200, "done": True, "error": None, "first_content_ms": 40.0, "total_ms": 100.0}),
            make_record(request_id="r-fail-status", tier="base", pair_id="p1",
                        transport={"status": 500, "done": True, "error": None, "first_content_ms": 10.0, "total_ms": 20.0}),
            make_record(request_id="r-fail-error", tier="base", pair_id="p1",
                        transport={"status": 200, "done": True, "error": "timeout", "first_content_ms": 10.0, "total_ms": 20.0}),
            make_record(request_id="r-not-done", tier="base", pair_id="p1",
                        transport={"status": 200, "done": False, "error": None, "first_content_ms": 10.0, "total_ms": 20.0}),
        ]
        self.assertEqual(ta._record_ttft(recs[0]), 40.0)
        self.assertIsNone(ta._record_ttft(recs[1]))
        self.assertIsNone(ta._record_ttft(recs[2]))
        self.assertIsNone(ta._record_ttft(recs[3]))

    def test_different_output_length_warning(self):
        """Test that varying completion token lengths across tiers trigger warning."""
        recs = make_block("p1", base_tokens=260, fast_tokens=350, ultra_tokens=400)
        report = ta.summarize_tiers(recs, run_id="test-run")
        stratum = report["paired_comparisons"]["long|1000|fresh"]
        self.assertTrue(stratum["token_fairness"]["has_output_length_discrepancy"])
        self.assertEqual(stratum["token_fairness"]["max_within_pair_completion_token_diff"], 140)
        self.assertTrue(any("Output length variation observed" in w for w in stratum["warnings"]))
        self.assertTrue(any("Output length variation observed" in w for w in report["warnings"]))

    def test_unestimable_chunk_rate(self):
        """Test that reasoning content, single chunk, or completion < 256 result in null chunk rate."""
        # 1. Reasoning present
        r_reasoning = make_record(
            transport={
                "status": 200, "done": True, "error": None,
                "final_usage": {"prompt_tokens": 100, "completion_tokens": 300},
                "events": [make_event(1_000_000, "chunk1", reasoning="thought"), make_event(2_000_000, "chunk2")]
            }
        )
        self.assertIsNone(ta._record_chunk_rate(r_reasoning))

        # 2. Single chunk
        r_single = make_record(
            transport={
                "status": 200, "done": True, "error": None,
                "final_usage": {"prompt_tokens": 100, "completion_tokens": 300},
                "events": [make_event(1_000_000, "single_chunk")]
            }
        )
        self.assertIsNone(ta._record_chunk_rate(r_single))

        # 3. completion_tokens < 256
        r_short = make_record(
            transport={
                "status": 200, "done": True, "error": None,
                "final_usage": {"prompt_tokens": 100, "completion_tokens": 128},
                "events": [make_event(1_000_000, "chunk1"), make_event(2_000_000, "chunk2")]
            }
        )
        self.assertIsNone(ta._record_chunk_rate(r_short))

    def test_cost_accounting_not_called_provider_bill(self):
        """Test cost accounting label and unknown holds separation."""
        r = make_record(
            accounting={"reserved_usd": "0.015", "computed_usd": "0.0075", "basis": "provider_usage"}
        )
        report = ta.summarize_tiers([r], run_id="test-run")
        acc = report["accounting_summary"]
        self.assertNotIn("provider bill", acc["label"].lower())
        self.assertIn("computed local accounting cost", acc["label"].lower())
        self.assertEqual(acc["computed_cost_by_tier_usd"]["base"], "0.0075")
        self.assertEqual(acc["unknown_holds"]["count"], 0)

    def test_cli_execution(self):
        """Test CLI python3 tier_analysis.py records.jsonl --run-id ID --output report.json."""
        records = make_block("p1", run_id="cli-run")
        with tempfile.TemporaryDirectory() as td:
            in_file = Path(td) / "records.jsonl"
            out_file = Path(td) / "report.json"
            with in_file.open("w", encoding="utf-8") as f:
                for r in records:
                    f.write(json.dumps(r) + "\n")

            cmd = [
                sys.executable,
                "tier_analysis.py",
                str(in_file),
                "--run-id",
                "cli-run",
                "--output",
                str(out_file),
            ]
            res = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, f"CLI failed: {res.stderr}")
            self.assertTrue(out_file.exists())
            data = json.loads(out_file.read_text(encoding="utf-8"))
            self.assertEqual(data["run_id"], "cli-run")
            self.assertEqual(data["valid_comparison_formal_requests"], 3)

    def test_non_dict_row_raises_clear_error(self):
        """Test that non-dict rows raise TierAnalysisError instead of being silently dropped."""
        with self.assertRaises(ta.TierAnalysisError) as ctx:
            ta.summarize_tiers(["bad-string-row"], run_id="test-run")
        self.assertIn("is not a dict", str(ctx.exception))

        with self.assertRaises(ta.TierAnalysisError) as ctx:
            ta.summarize_tiers([None], run_id="test-run")
        self.assertIn("is not a dict", str(ctx.exception))

    def test_cross_tier_group_reuse_rejected(self):
        """Test that group_id cannot be reused across different tiers (each tier is independent)."""
        # 1. group_id shared across different tiers in same pair
        r1 = make_record(request_id="r1", pair_id="pair-C", tier="base", group_id="grp-common")
        r2 = make_record(request_id="r2", pair_id="pair-C", tier="fast", group_id="grp-common")
        with self.assertRaises(ta.TierAnalysisError) as ctx:
            ta.summarize_tiers([r1, r2], run_id="test-run")
        self.assertIn("reused across different pair/tier", str(ctx.exception))

        # 2. group_id shared across different tiers in different pairs
        r3 = make_record(request_id="r3", pair_id="pair-D", tier="base", group_id="grp-cross")
        r4 = make_record(request_id="r4", pair_id="pair-E", tier="ultra", group_id="grp-cross")
        with self.assertRaises(ta.TierAnalysisError) as ctx:
            ta.summarize_tiers([r3, r4], run_id="test-run")
        self.assertIn("reused across different pair/tier", str(ctx.exception))

    def test_same_tier_group_reused_across_pair_rejected(self):
        """Test that group_id within the same tier cannot be reused across different pairs."""
        r1 = make_record(request_id="r1", pair_id="pair-A", tier="base", group_id="grp-base-shared")
        r2 = make_record(request_id="r2", pair_id="pair-B", tier="base", group_id="grp-base-shared")
        with self.assertRaises(ta.TierAnalysisError) as ctx:
            ta.summarize_tiers([r1, r2], run_id="test-run")
        self.assertIn("reused across different pair/tier", str(ctx.exception))

    def test_inconsistent_group_for_same_pair_tier_rejected(self):
        """Test that same (pair_id, tier) cannot have multiple different group_ids."""
        r1 = make_record(request_id="r1", pair_id="pair-1", tier="base", group_id="grp-1", repeat_index=1)
        r2 = make_record(request_id="r2", pair_id="pair-1", tier="base", group_id="grp-2", repeat_index=2)
        with self.assertRaises(ta.TierAnalysisError) as ctx:
            ta.summarize_tiers([r1, r2], run_id="test-run")
        self.assertIn("inconsistent group_id for pair", str(ctx.exception))

    def test_duplicate_repeat_index_for_same_pair_tier_rejected(self):
        """Test that duplicate repeat_index for the same (pair_id, tier) is rejected."""
        r1 = make_record(request_id="r1", pair_id="pair-1", tier="base", group_id="grp-1", repeat_index=1)
        r2 = make_record(request_id="r2", pair_id="pair-1", tier="base", group_id="grp-1", repeat_index=1)
        with self.assertRaises(ta.TierAnalysisError) as ctx:
            ta.summarize_tiers([r1, r2], run_id="test-run")
        self.assertIn("duplicate repeat_index", str(ctx.exception))

    def test_cross_kind_or_size_pair_conflict_rejected(self):
        """Test that a pair_id cannot span multiple sizes or kinds."""
        # Different target_tokens
        r1 = make_record(request_id="r1", pair_id="p-clash", tier="base", target_tokens=1000)
        r2 = make_record(request_id="r2", pair_id="p-clash", tier="fast", target_tokens=4000)
        with self.assertRaises(ta.TierAnalysisError) as ctx:
            ta.summarize_tiers([r1, r2], run_id="test-run")
        self.assertIn("conflicting kind/target", str(ctx.exception))

        # Different kind
        r3 = make_record(request_id="r3", pair_id="p-kind", tier="base", kind="long")
        r4 = make_record(request_id="r4", pair_id="p-kind", tier="fast", kind="throughput")
        with self.assertRaises(ta.TierAnalysisError) as ctx:
            ta.summarize_tiers([r3, r4], run_id="test-run")
        self.assertIn("conflicting kind/target", str(ctx.exception))

    def test_realistic_block_15_records_fresh_and_reuse_same_pair(self):
        """Test the realistic block fixture: 1 pair_id with 3 tiers * 5 reps = 15 records.

        Simultaneously passed to summarize_tiers.
        Fresh (rep 0) and reuse (reps 1..4) must both produce pairs_complete == 1 under the same pair_id!
        """
        records = []
        pair_id = "block-real-001"
        # TTFT schedule:
        # base: rep0=150, rep1=110, rep2=120, rep3=130, rep4=140 -> reuse median = 125.0
        # fast: rep0=100, rep1=70,  rep2=80,  rep3=90,  rep4=100 -> reuse median = 85.0
        # ultra: rep0=70, rep1=40,  rep2=50,  rep3=60,  rep4=70  -> reuse median = 55.0
        base_ttfts = [150.0, 110.0, 120.0, 130.0, 140.0]
        fast_ttfts = [100.0, 70.0, 80.0, 90.0, 100.0]
        ultra_ttfts = [70.0, 40.0, 50.0, 60.0, 70.0]

        for rep in range(5):
            for tier, ttfts in (("base", base_ttfts), ("fast", fast_ttfts), ("ultra", ultra_ttfts)):
                records.append(make_record(
                    request_id=f"real-{pair_id}-{tier}-r{rep:02d}",
                    run_id="real-run",
                    tier=tier,
                    pair_id=pair_id,
                    group_id=f"{pair_id}-{tier}",
                    phase="comparison_formal",
                    kind="long",
                    target_tokens=1000,
                    repeat_index=rep,
                    protocol="tier-comparison-v1",
                    transport={
                        "status": 200,
                        "done": True,
                        "error": None,
                        "first_content_ms": ttfts[rep],
                        "total_ms": ttfts[rep] + 50.0,
                        "final_usage": {"prompt_tokens": 100, "completion_tokens": 300},
                        "events": [make_event(1_000_000, "a"), make_event(101_000_000, "b")],
                    },
                    accounting={"reserved_usd": "0.001", "computed_usd": "0.0005", "basis": "provider_usage"},
                ))

        self.assertEqual(len(records), 15)
        report = ta.summarize_tiers(records, run_id="real-run")

        # 1. Fresh stratum (rep 0)
        fresh_stratum = report["paired_comparisons"]["long|1000|fresh"]
        self.assertEqual(fresh_stratum["pairs_total"], 1)
        self.assertEqual(fresh_stratum["pairs_complete"], 1)
        self.assertEqual(fresh_stratum["missing_pairs"], 0)
        # Fresh contrasts:
        # fast vs base diff = 100 - 150 = -50
        self.assertEqual(fresh_stratum["comparisons"]["fast_vs_base"]["first_content_ms_diff"]["median"], -50.0)
        # ultra vs base diff = 70 - 150 = -80
        self.assertEqual(fresh_stratum["comparisons"]["ultra_vs_base"]["first_content_ms_diff"]["median"], -80.0)

        # 2. Reuse stratum (reps 1..4)
        reuse_stratum = report["paired_comparisons"]["long|1000|reuse"]
        self.assertEqual(reuse_stratum["pairs_total"], 1)
        self.assertEqual(reuse_stratum["pairs_complete"], 1)
        self.assertEqual(reuse_stratum["missing_pairs"], 0)
        # Reuse contrasts:
        # fast vs base diff = 85.0 - 125.0 = -40.0
        self.assertEqual(reuse_stratum["comparisons"]["fast_vs_base"]["first_content_ms_diff"]["median"], -40.0)
        # ultra vs base diff = 55.0 - 125.0 = -70.0
        self.assertEqual(reuse_stratum["comparisons"]["ultra_vs_base"]["first_content_ms_diff"]["median"], -70.0)

    def test_multi_block_realistic_fixture(self):
        """Test multiple complete blocks (e.g. 2 blocks = 30 records) sharing fresh and reuse."""
        records = []
        for b_idx in range(2):
            pid = f"block-{b_idx:03d}"
            for rep in range(5):
                for tier, offset in (("base", 100.0), ("fast", 80.0), ("ultra", 60.0)):
                    records.append(make_record(
                        request_id=f"run-{pid}-{tier}-r{rep}",
                        run_id="multi-run",
                        tier=tier,
                        pair_id=pid,
                        group_id=f"{pid}-{tier}",
                        phase="comparison_formal",
                        kind="long",
                        target_tokens=1000,
                        repeat_index=rep,
                        transport={
                            "status": 200, "done": True, "error": None,
                            "first_content_ms": offset + (b_idx * 10.0) + rep,
                            "total_ms": offset + 100.0,
                            "final_usage": {"prompt_tokens": 100, "completion_tokens": 300},
                        },
                    ))
        self.assertEqual(len(records), 30)
        report = ta.summarize_tiers(records, run_id="multi-run")
        self.assertEqual(report["paired_comparisons"]["long|1000|fresh"]["pairs_complete"], 2)
        self.assertEqual(report["paired_comparisons"]["long|1000|reuse"]["pairs_complete"], 2)

    def test_kind_and_target_tokens_validation(self):
        """Test validation of kind in ('long', 'throughput') and target_tokens positive int (rejecting bool)."""
        bad_kind = make_record(request_id="r1", kind="short")
        with self.assertRaises(ta.TierAnalysisError) as ctx:
            ta.summarize_tiers([bad_kind], run_id="test-run")
        self.assertIn("invalid kind", str(ctx.exception))

        bool_target = make_record(request_id="r2", target_tokens=True)
        with self.assertRaises(ta.TierAnalysisError) as ctx:
            ta.summarize_tiers([bool_target], run_id="test-run")
        self.assertIn("invalid target_tokens", str(ctx.exception))

        zero_target = make_record(request_id="r3", target_tokens=0)
        with self.assertRaises(ta.TierAnalysisError) as ctx:
            ta.summarize_tiers([zero_target], run_id="test-run")
        self.assertIn("invalid target_tokens", str(ctx.exception))

        tp_bad_rep = make_record(request_id="r4", kind="throughput", repeat_index=1)
        with self.assertRaises(ta.TierAnalysisError) as ctx:
            ta.summarize_tiers([tp_bad_rep], run_id="test-run")
        self.assertIn("repeat_index is 1. Must be 0", str(ctx.exception))

    def test_valid_4_reuse_group_and_median_aggregation(self):
        """Test valid 4-reuse reps (1..4) for a pair: correct median per tier and contrasts."""
        records = []
        # Base TTFTs: 110, 120, 130, 140 -> median = 125.0
        # Fast TTFTs: 70, 80, 90, 100 -> median = 85.0
        # Ultra TTFTs: 40, 50, 60, 70 -> median = 55.0
        for rep in (1, 2, 3, 4):
            records.append(make_record(
                request_id=f"reuse-base-r{rep}", tier="base", pair_id="pair-reuse",
                group_id="grp-reuse-base", repeat_index=rep,
                transport={"status": 200, "done": True, "error": None, "first_content_ms": 100.0 + rep * 10.0}
            ))
            records.append(make_record(
                request_id=f"reuse-fast-r{rep}", tier="fast", pair_id="pair-reuse",
                group_id="grp-reuse-fast", repeat_index=rep,
                transport={"status": 200, "done": True, "error": None, "first_content_ms": 60.0 + rep * 10.0}
            ))
            records.append(make_record(
                request_id=f"reuse-ultra-r{rep}", tier="ultra", pair_id="pair-reuse",
                group_id="grp-reuse-ultra", repeat_index=rep,
                transport={"status": 200, "done": True, "error": None, "first_content_ms": 30.0 + rep * 10.0}
            ))

        report = ta.summarize_tiers(records, run_id="test-run")
        stratum = report["paired_comparisons"]["long|1000|reuse"]
        self.assertEqual(stratum["pairs_total"], 1)
        self.assertEqual(stratum["pairs_complete"], 1)
        self.assertEqual(stratum["missing_pairs"], 0)

        # Fast vs Base: diff = 85.0 - 125.0 = -40.0; ratio = 85.0 / 125.0 = 0.68
        f_b = stratum["comparisons"]["fast_vs_base"]
        self.assertEqual(f_b["first_content_ms_diff"]["median"], -40.0)
        self.assertAlmostEqual(f_b["first_content_ms_ratio"]["median"], 0.68)

        # Ultra vs Base: diff = 55.0 - 125.0 = -70.0; ratio = 55.0 / 125.0 = 0.44
        u_b = stratum["comparisons"]["ultra_vs_base"]
        self.assertEqual(u_b["first_content_ms_diff"]["median"], -70.0)
        self.assertAlmostEqual(u_b["first_content_ms_ratio"]["median"], 0.44)

    def test_incomplete_reuse_marked_missing(self):
        """Test that if any tier is missing a rep in a reuse group, it is marked incomplete."""
        records = []
        for rep in (1, 2, 3, 4):
            records.append(make_record(
                request_id=f"inc-b-r{rep}", tier="base", pair_id="pair-inc",
                group_id="grp-inc-base", repeat_index=rep,
                transport={"status": 200, "done": True, "error": None, "first_content_ms": 100.0}
            ))
            records.append(make_record(
                request_id=f"inc-f-r{rep}", tier="fast", pair_id="pair-inc",
                group_id="grp-inc-fast", repeat_index=rep,
                transport={"status": 200, "done": True, "error": None, "first_content_ms": 80.0}
            ))
            # Ultra missing rep 4!
            if rep != 4:
                records.append(make_record(
                    request_id=f"inc-u-r{rep}", tier="ultra", pair_id="pair-inc",
                    group_id="grp-inc-ultra", repeat_index=rep,
                    transport={"status": 200, "done": True, "error": None, "first_content_ms": 60.0}
                ))

        report = ta.summarize_tiers(records, run_id="test-run")
        stratum = report["paired_comparisons"]["long|1000|reuse"]
        self.assertEqual(stratum["pairs_total"], 1)
        self.assertEqual(stratum["pairs_complete"], 0)
        self.assertEqual(stratum["missing_pairs"], 1)
        self.assertEqual(stratum["missing_details_by_tier"]["ultra"], 1)
        self.assertEqual(stratum["missing_details_by_tier"]["base"], 0)
        self.assertEqual(stratum["missing_details_by_tier"]["fast"], 0)

    def test_runner_plan_fixture_metadata_compatibility(self):
        """Test compatibility with tasks generated by tier_bench.plan (pure offline plan)."""
        import gzip
        import tier_bench as tb
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ledger = root / "ledger"
            ledger.write_text('{"type":"init","cap_usd":"15"}\n')
            cfg = root / "cfg.json"
            cfg.write_text(json.dumps({
                "provider": "Lithos",
                "base_url": "http://127.0.0.1:8000/v1",
                "api_key_env": "TEST_KEY",
            }))
            out = root / "out"
            m = tb.plan(cfg, ledger, "plan-run-001", 42, out)
            raw = gzip.open(out / "tasks.jsonl.gz", "rt", encoding="utf-8").read()
            tasks = [json.loads(line) for line in raw.splitlines() if line.strip()]

            # Build realistic execution records using tier_bench's exact record structure,
            # mapping matched block identity so group_id is bound strictly to (block_pair_id, tier)
            records = []
            for t in tasks:
                block_id = f"{t['kind']}-{t['target_tokens']}-block-{t['request_id'].split('-g')[1].split('-')[0]}"
                group_id = f"{block_id}-{t['tier']}"
                record = {k: t[k] for k in ('request_id', 'run_id', 'tier', 'phase', 'kind', 'target_tokens', 'repeat_index', 'protocol')}
                record.update(
                    pair_id=block_id,
                    group_id=group_id,
                    request=t['payload'],
                    transport={
                        "status": 200, "done": True, "error": None,
                        "first_content_ms": 50.0, "total_ms": 100.0,
                        "final_usage": {"prompt_tokens": 100, "completion_tokens": 300},
                        "events": [make_event(1_000_000, "a"), make_event(101_000_000, "b")]
                    },
                    accounting={"reserved_usd": "0.001", "computed_usd": "0.0005", "basis": "provider_usage"}
                )
                records.append(record)

            report = ta.summarize_tiers(records, run_id="plan-run-001")
            self.assertEqual(report["valid_comparison_formal_requests"], len(tasks))
            self.assertEqual(report["run_id"], "plan-run-001")
            self.assertTrue(len(report["paired_comparisons"]) > 0)
            for sname, sdata in report["paired_comparisons"].items():
                self.assertGreater(sdata["pairs_complete"], 0)
                self.assertEqual(sdata["missing_pairs"], 0)


if __name__ == "__main__":
    unittest.main()
