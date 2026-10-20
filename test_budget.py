"""Unit tests for budget.py ledger and cost calculations."""
from __future__ import annotations

import os
import pathlib
import tempfile
import unittest
from decimal import Decimal

from budget import BudgetLedger, cost_usd


class TestCostUsd(unittest.TestCase):
    """Test cost_usd function contract and edge cases."""

    def test_standard_pricing(self) -> None:
        # Base input .15, cache .003, output .60 dollars per million
        # 1000 prompt tokens, 400 cached tokens -> 600 uncached tokens
        # 200 completion tokens
        # uncached: 600 * 0.15 / 1e6 = 0.000090
        # cached: 400 * 0.003 / 1e6 = 0.0000012
        # completion: 200 * 0.60 / 1e6 = 0.000120
        # total: 0.000090 + 0.0000012 + 0.000120 = 0.0002112
        cost = cost_usd(
            prompt_tokens=1000,
            cached_tokens=400,
            completion_tokens=200,
            input_per_million="0.15",
            cached_per_million="0.003",
            output_per_million="0.60",
        )
        self.assertEqual(cost, "0.0002112")

    def test_zero_tokens(self) -> None:
        cost = cost_usd(
            prompt_tokens=0,
            cached_tokens=0,
            completion_tokens=0,
            input_per_million="0.15",
            cached_per_million="0.003",
            output_per_million="0.60",
        )
        self.assertEqual(Decimal(cost), Decimal("0"))

    def test_all_cached(self) -> None:
        # 500 prompt tokens all cached, 0 completion tokens
        cost = cost_usd(
            prompt_tokens=500,
            cached_tokens=500,
            completion_tokens=0,
            input_per_million="0.15",
            cached_per_million="0.003",
            output_per_million="0.60",
        )
        # 500 * 0.003 / 1e6 = 0.0000015
        self.assertEqual(cost, "0.0000015")

    def test_reject_bools_for_tokens(self) -> None:
        with self.assertRaises(TypeError):
            cost_usd(True, 0, 0, "0.15", "0.003", "0.60")  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            cost_usd(100, False, 0, "0.15", "0.003", "0.60")  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            cost_usd(100, 0, True, "0.15", "0.003", "0.60")  # type: ignore[arg-type]

    def test_reject_negative_tokens(self) -> None:
        with self.assertRaises(ValueError):
            cost_usd(-1, 0, 0, "0.15", "0.003", "0.60")
        with self.assertRaises(ValueError):
            cost_usd(10, -1, 0, "0.15", "0.003", "0.60")
        with self.assertRaises(ValueError):
            cost_usd(10, 0, -5, "0.15", "0.003", "0.60")

    def test_reject_cache_greater_than_input(self) -> None:
        with self.assertRaises(ValueError):
            cost_usd(100, 101, 10, "0.15", "0.003", "0.60")

    def test_reject_nonfinite_or_negative_prices(self) -> None:
        for bad_price in ["NaN", "Infinity", "-Infinity", "-0.15", "abc"]:
            with self.subTest(bad_price=bad_price):
                with self.assertRaises(ValueError):
                    cost_usd(100, 0, 0, bad_price, "0.003", "0.60")
                with self.assertRaises(ValueError):
                    cost_usd(100, 0, 0, "0.15", bad_price, "0.60")
                with self.assertRaises(ValueError):
                    cost_usd(100, 0, 0, "0.15", "0.003", bad_price)

    def test_reject_non_str_or_bool_prices(self) -> None:
        with self.assertRaises(TypeError):
            cost_usd(100, 0, 0, 0.15, "0.003", "0.60")  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            cost_usd(100, 0, 0, "0.15", True, "0.60")  # type: ignore[arg-type]


class TestBudgetLedgerLifecycle(unittest.TestCase):
    """Test BudgetLedger basic lifecycle, flock lock, and directory creation."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.ledger_path = pathlib.Path(self.tmpdir.name) / "sub" / "ledger.jsonl"

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_directory_and_file_creation(self) -> None:
        ledger = BudgetLedger(self.ledger_path, "10.00")
        try:
            self.assertTrue(self.ledger_path.exists())
            snap = ledger.snapshot()
            self.assertEqual(snap["cap_usd"], "10.00")
            self.assertEqual(snap["committed_usd"], "0")
            self.assertEqual(snap["remaining_usd"], "10.00")
        finally:
            ledger.close()

    def test_concurrent_writer_rejected_by_flock(self) -> None:
        ledger1 = BudgetLedger(self.ledger_path, "10.00")
        try:
            with self.assertRaises(BlockingIOError):
                BudgetLedger(self.ledger_path, "10.00")
        finally:
            ledger1.close()

        # After closing, another instance can acquire lock
        ledger2 = BudgetLedger(self.ledger_path, "10.00")
        ledger2.close()

    def test_context_manager(self) -> None:
        with BudgetLedger(self.ledger_path, "5.00") as ledger:
            self.assertTrue(ledger.reserve("req-1", "1.50"))
            self.assertEqual(ledger.snapshot()["committed_usd"], "1.50")
        # Should be unlocked after exiting with statement
        with BudgetLedger(self.ledger_path, "5.00") as ledger2:
            self.assertEqual(ledger2.snapshot()["committed_usd"], "1.50")

    def test_invalid_cap_rejected(self) -> None:
        for bad_cap in ["-5.00", "NaN", "Inf", "abc", 10.0]:
            with self.subTest(bad_cap=bad_cap):
                if isinstance(bad_cap, str):
                    with self.assertRaises(ValueError):
                        BudgetLedger(self.ledger_path, bad_cap)
                else:
                    with self.assertRaises(TypeError):
                        BudgetLedger(self.ledger_path, bad_cap)  # type: ignore[arg-type]


class TestBudgetLedgerOperations(unittest.TestCase):
    """Test reserve, settle, holds, duplicate detection, and overrun handling."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.ledger_path = pathlib.Path(self.tmpdir.name) / "ledger.jsonl"
        self.ledger = BudgetLedger(self.ledger_path, "10.00")

    def tearDown(self) -> None:
        self.ledger.close()
        self.tmpdir.cleanup()

    def test_reserve_and_snapshot(self) -> None:
        ok = self.ledger.reserve("req-1", "3.00")
        self.assertTrue(ok)
        snap = self.ledger.snapshot()
        self.assertEqual(snap["committed_usd"], "3.00")
        self.assertEqual(snap["remaining_usd"], "7.00")

    def test_reserve_exceeding_cap_rejected(self) -> None:
        self.assertTrue(self.ledger.reserve("req-1", "8.00"))
        # Attempt to reserve 3.00 when only 2.00 remaining
        self.assertFalse(self.ledger.reserve("req-2", "3.00"))
        snap = self.ledger.snapshot()
        self.assertEqual(snap["committed_usd"], "8.00")
        self.assertEqual(snap["remaining_usd"], "2.00")

        # Reserve exact remaining
        self.assertTrue(self.ledger.reserve("req-3", "2.00"))
        self.assertEqual(self.ledger.snapshot()["remaining_usd"], "0.00")

    def test_reserve_duplicate_id_raises(self) -> None:
        self.assertTrue(self.ledger.reserve("req-1", "1.00"))
        with self.assertRaises(ValueError):
            self.ledger.reserve("req-1", "1.00")

    def test_reserve_invalid_arguments(self) -> None:
        with self.assertRaises(ValueError):
            self.ledger.reserve("", "1.00")
        with self.assertRaises(ValueError):
            self.ledger.reserve("req-1", "-1.00")
        with self.assertRaises(ValueError):
            self.ledger.reserve("req-2", "NaN")

    def test_settle_normal(self) -> None:
        self.assertTrue(self.ledger.reserve("req-1", "4.00"))
        self.ledger.settle("req-1", "2.50")
        snap = self.ledger.snapshot()
        # Committed adjusted from 4.00 down to 2.50
        self.assertEqual(snap["committed_usd"], "2.50")
        self.assertEqual(snap["remaining_usd"], "7.50")

    def test_settle_unknown_usage_retains_hold(self) -> None:
        self.assertTrue(self.ledger.reserve("req-1", "4.00"))
        # actual_usd=None retains full hold conservatively
        self.ledger.settle("req-1", None)
        snap = self.ledger.snapshot()
        self.assertEqual(snap["committed_usd"], "4.00")
        self.assertEqual(snap["remaining_usd"], "6.00")

    def test_settle_duplicate_or_unknown_id(self) -> None:
        with self.assertRaises(KeyError):
            self.ledger.settle("nonexistent", "1.00")

        self.assertTrue(self.ledger.reserve("req-1", "2.00"))
        self.ledger.settle("req-1", "1.00")
        with self.assertRaises(ValueError):
            self.ledger.settle("req-1", "1.00")

        # Reserve duplicate ID after settle must also raise
        with self.assertRaises(ValueError):
            self.ledger.reserve("req-1", "1.00")

    def test_immediate_durable_fsync(self) -> None:
        # Without closing ledger, records must be durable and readable from disk
        self.assertTrue(self.ledger.reserve("req-fsync", "1.23"))
        with open(self.ledger_path, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip()]
        # lines should contain init and reserve
        self.assertEqual(len(lines), 2)
        self.assertIn('"type":"reserve"', lines[1])
        self.assertIn('"request_id":"req-fsync"', lines[1])

    def test_overrun_flags_stops_reservations_and_does_not_conceal(self) -> None:
        self.assertTrue(self.ledger.reserve("req-1", "5.00"))
        # Actual cost exceeds reserved hold
        self.ledger.settle("req-1", "6.50")
        self.assertTrue(self.ledger.overrun)

        # Committed reflects full actual cost (6.50), not concealed
        snap = self.ledger.snapshot()
        self.assertEqual(snap["committed_usd"], "6.50")
        self.assertEqual(snap["remaining_usd"], "3.50")

        # Further reservations MUST be stopped
        self.assertFalse(self.ledger.reserve("req-2", "1.00"))

    def test_overrun_exceeding_total_cap_shows_negative_remaining(self) -> None:
        self.assertTrue(self.ledger.reserve("req-1", "9.00"))
        # Actual exceeds entire cap 10.00
        self.ledger.settle("req-1", "11.50")
        self.assertTrue(self.ledger.overrun)

        snap = self.ledger.snapshot()
        self.assertEqual(snap["committed_usd"], "11.50")
        self.assertEqual(snap["remaining_usd"], "-1.50")


class TestBudgetLedgerRestartAndIntegrity(unittest.TestCase):
    """Test persistence across restarts, cap mismatch rejection, and fail-closed corrupt tail handling."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.ledger_path = pathlib.Path(self.tmpdir.name) / "ledger.jsonl"

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_restart_preserves_state_and_holds(self) -> None:
        # Session 1: reserve r1, settle r2 with None (retaining hold), settle r3 normal
        with BudgetLedger(self.ledger_path, "20.00") as ledger:
            ledger.reserve("r1", "3.00")  # in-flight
            ledger.reserve("r2", "4.00")
            ledger.settle("r2", None)     # settled unknown
            ledger.reserve("r3", "5.00")
            ledger.settle("r3", "2.00")   # settled normal
            snap1 = ledger.snapshot()
            self.assertEqual(snap1["committed_usd"], "9.00")  # 3 + 4 + 2

        # Session 2: reload from disk
        with BudgetLedger(self.ledger_path, "20.00") as ledger:
            snap2 = ledger.snapshot()
            self.assertEqual(snap2["committed_usd"], "9.00")
            self.assertEqual(snap2["remaining_usd"], "11.00")

            # Duplicate IDs cannot be reserved again
            with self.assertRaises(ValueError):
                ledger.reserve("r1", "1.00")
            with self.assertRaises(ValueError):
                ledger.reserve("r2", "1.00")
            with self.assertRaises(ValueError):
                ledger.reserve("r3", "1.00")

            # In-flight r1 can still be settled
            ledger.settle("r1", "1.50")
            self.assertEqual(ledger.snapshot()["committed_usd"], "7.50")  # 1.5 + 4 + 2

    def test_restart_preserves_overrun_stop(self) -> None:
        with BudgetLedger(self.ledger_path, "10.00") as ledger:
            ledger.reserve("r1", "2.00")
            ledger.settle("r1", "3.00")  # overrun
            self.assertTrue(ledger.overrun)

        # Reload
        with BudgetLedger(self.ledger_path, "10.00") as ledger:
            self.assertTrue(ledger.overrun)
            # Further reservations stopped even after restart
            self.assertFalse(ledger.reserve("r2", "1.00"))

    def test_restart_with_different_cap_rejected(self) -> None:
        with BudgetLedger(self.ledger_path, "10.00") as ledger:
            ledger.reserve("r1", "1.00")

        # Restart with different cap must raise ValueError
        with self.assertRaises(ValueError):
            BudgetLedger(self.ledger_path, "15.00")

    def test_corrupt_incomplete_tail_fail_closed(self) -> None:
        with BudgetLedger(self.ledger_path, "10.00") as ledger:
            ledger.reserve("r1", "1.00")

        # Append incomplete truncated JSON tail without newline
        with open(self.ledger_path, "ab") as f:
            f.write(b'{"type":"reserve","request_id":"r2"')

        with self.assertRaises(ValueError):
            BudgetLedger(self.ledger_path, "10.00")

    def test_corrupt_invalid_json_line_fail_closed(self) -> None:
        with BudgetLedger(self.ledger_path, "10.00") as ledger:
            ledger.reserve("r1", "1.00")

        # Append corrupt line with newline
        with open(self.ledger_path, "ab") as f:
            f.write(b'{"type":"reserve", broken json}\n')

        with self.assertRaises(ValueError):
            BudgetLedger(self.ledger_path, "10.00")

    def test_corrupt_empty_line_fail_closed(self) -> None:
        with BudgetLedger(self.ledger_path, "10.00") as ledger:
            ledger.reserve("r1", "1.00")

        # Append empty line
        with open(self.ledger_path, "ab") as f:
            f.write(b'\n')

        with self.assertRaises(ValueError):
            BudgetLedger(self.ledger_path, "10.00")

    def test_corrupt_missing_init_fail_closed(self) -> None:
        # Write reserve without init
        with open(self.ledger_path, "wb") as f:
            f.write(b'{"type":"reserve","request_id":"r1","upper_usd":"1.00"}\n')

        with self.assertRaises(ValueError):
            BudgetLedger(self.ledger_path, "10.00")

    def test_corrupt_journal_duplicate_reserve_in_file_fail_closed(self) -> None:
        with open(self.ledger_path, "wb") as f:
            f.write(b'{"type":"init","cap_usd":"10.00"}\n')
            f.write(b'{"type":"reserve","request_id":"r1","upper_usd":"1.00"}\n')
            f.write(b'{"type":"reserve","request_id":"r1","upper_usd":"1.00"}\n')

        with self.assertRaises(ValueError):
            BudgetLedger(self.ledger_path, "10.00")

    def test_corrupt_journal_unknown_record_type_fail_closed(self) -> None:
        with open(self.ledger_path, "wb") as f:
            f.write(b'{"type":"init","cap_usd":"10.00"}\n')
            f.write(b'{"type":"corrupt_type","foo":"bar"}\n')

        with self.assertRaises(ValueError):
            BudgetLedger(self.ledger_path, "10.00")

    def test_corrupt_journal_settle_unknown_fail_closed(self) -> None:
        with open(self.ledger_path, "wb") as f:
            f.write(b'{"type":"init","cap_usd":"10.00"}\n')
            f.write(b'{"type":"settle","request_id":"r_missing","actual_usd":"1.00"}\n')

        with self.assertRaises(ValueError):
            BudgetLedger(self.ledger_path, "10.00")


class TestBudgetLedgerFaultInjection(unittest.TestCase):
    """Fault injection tests for fsync/disk failures guarding against budget leaks."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.ledger_path = pathlib.Path(self.tmpdir.name) / "ledger.jsonl"
        self.orig_fsync = os.fsync

    def tearDown(self) -> None:
        os.fsync = self.orig_fsync
        self.tmpdir.cleanup()

    def test_fsync_failure_on_reserve_poisons_ledger_and_blocks_new_requests(self) -> None:
        ledger = BudgetLedger(self.ledger_path, "10.00")

        # Inject fsync failure
        def failing_fsync(fd: int) -> None:
            raise OSError(5, "Simulated disk I/O failure on fsync")

        os.fsync = failing_fsync

        with self.assertRaises(OSError):
            ledger.reserve("r1", "4.00")

        # Ledger must now be poisoned
        self.assertTrue(ledger.poisoned)
        self.assertFalse(ledger.healthy)

        snap = ledger.snapshot()
        self.assertFalse(snap["healthy"])
        self.assertTrue(snap["poisoned"])
        self.assertEqual(snap["committed_usd"], "0")  # memory was not committed

        # Restore fsync to verify the poisoned instance still refuses any new requests
        os.fsync = self.orig_fsync
        with self.assertRaises(RuntimeError):
            ledger.reserve("r2", "1.00")
        with self.assertRaises(RuntimeError):
            ledger.settle("r1", "1.00")

        ledger.close()

    def test_fsync_failure_on_settle_none_retains_hold_and_poisons(self) -> None:
        ledger = BudgetLedger(self.ledger_path, "10.00")
        self.assertTrue(ledger.reserve("r1", "5.00"))

        def failing_fsync(fd: int) -> None:
            raise OSError(5, "Simulated disk I/O failure on fsync")

        os.fsync = failing_fsync

        with self.assertRaises(OSError):
            ledger.settle("r1", None)

        self.assertTrue(ledger.poisoned)
        snap = ledger.snapshot()
        self.assertFalse(snap["healthy"])
        # Retains conservative hold of 5.00
        self.assertEqual(snap["committed_usd"], "5.00")

        os.fsync = self.orig_fsync
        with self.assertRaises(RuntimeError):
            ledger.reserve("r2", "1.00")

        ledger.close()

    def test_fsync_failure_on_settle_reduce_hold_prevents_budget_leak(self) -> None:
        # Audit finding reproduction:
        # reserve r1 for 8.00 out of 10.00 cap.
        # settle r1 to 0.00 fails on fsync.
        # Must NOT release 8.00 hold in memory, must poison instance,
        # and must block any subsequent reserve (e.g. r2 for 5.00).
        ledger = BudgetLedger(self.ledger_path, "10.00")
        self.assertTrue(ledger.reserve("r1", "8.00"))
        self.assertEqual(ledger.snapshot()["committed_usd"], "8.00")

        def failing_fsync(fd: int) -> None:
            raise OSError(5, "Simulated disk I/O failure on fsync")

        os.fsync = failing_fsync

        with self.assertRaises(OSError):
            ledger.settle("r1", "0.00")

        # Verify hold was NOT released to 0
        self.assertTrue(ledger.poisoned)
        snap = ledger.snapshot()
        self.assertFalse(snap["healthy"])
        self.assertEqual(snap["committed_usd"], "8.00")
        self.assertEqual(snap["remaining_usd"], "2.00")

        # Verify subsequent request (which would exceed cap if 8.00 was released) is blocked
        os.fsync = self.orig_fsync
        with self.assertRaises(RuntimeError):
            ledger.reserve("r2", "5.00")

        ledger.close()


if __name__ == "__main__":
    unittest.main()
