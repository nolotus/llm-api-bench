"""Budget enforcement and cost calculation ledger for LLM benchmark execution.

Standard library only, thread/process-safe POSIX flock file locking, append-only JSONL
journal with per-operation fsync, Decimal precision.
"""
from __future__ import annotations

import fcntl
import json
import os
import pathlib
from decimal import Decimal, InvalidOperation
from typing import Any


def _parse_decimal_str(val: Any, field_name: str = "amount") -> Decimal:
    """Parse and validate a finite, non-negative Decimal from a string.

    Rejects bools, ints, floats, non-str types, negative numbers, and non-finite values (NaN, Inf).
    """
    if isinstance(val, bool) or not isinstance(val, str):
        raise TypeError(f"{field_name} must be a str, got {type(val).__name__}")
    try:
        d = Decimal(val)
    except (InvalidOperation, ValueError) as err:
        raise ValueError(f"Invalid decimal string for {field_name}: {val!r}") from err
    if not d.is_finite():
        raise ValueError(f"{field_name} must be finite: {val!r}")
    if d < 0:
        raise ValueError(f"{field_name} must be non-negative: {val!r}")
    return d


def cost_usd(
    prompt_tokens: int,
    cached_tokens: int,
    completion_tokens: int,
    input_per_million: str,
    cached_per_million: str,
    output_per_million: str,
) -> str:
    """Calculate request cost in USD.

    Reject bools, negatives, cache > input, and nonfinite prices.
    Cost calculation:
        uncached_prompt_tokens = prompt_tokens - cached_tokens
        cost = (uncached_prompt_tokens * input_per_million
                + cached_tokens * cached_per_million
                + completion_tokens * output_per_million) / 1_000_000
    """
    for name, val in [
        ("prompt_tokens", prompt_tokens),
        ("cached_tokens", cached_tokens),
        ("completion_tokens", completion_tokens),
    ]:
        if isinstance(val, bool):
            raise TypeError(f"{name} cannot be a bool")
        if not isinstance(val, int):
            raise TypeError(f"{name} must be an int, got {type(val).__name__}")
        if val < 0:
            raise ValueError(f"{name} must be non-negative: {val}")

    if cached_tokens > prompt_tokens:
        raise ValueError(f"cached_tokens ({cached_tokens}) cannot exceed prompt_tokens ({prompt_tokens})")

    input_price = _parse_decimal_str(input_per_million, "input_per_million")
    cached_price = _parse_decimal_str(cached_per_million, "cached_per_million")
    output_price = _parse_decimal_str(output_per_million, "output_per_million")

    one_million = Decimal("1000000")
    uncached_tokens = prompt_tokens - cached_tokens

    cost = (
        Decimal(uncached_tokens) * input_price
        + Decimal(cached_tokens) * cached_price
        + Decimal(completion_tokens) * output_price
    ) / one_million

    return str(cost)


class BudgetLedger:
    """Durable append-only JSONL budget ledger with POSIX flock and fsync.

    Tracks dollar commitments, enforces maximum capacity, handles unknown usage holds,
    flags overrun conditions, and fails closed on corrupt journal state.
    """

    def __init__(self, path: pathlib.Path | str, cap_usd: str) -> None:
        self._path = pathlib.Path(path)
        self._cap = _parse_decimal_str(cap_usd, "cap_usd")
        self._committed = Decimal("0")
        self._overrun = False
        self._requests: dict[str, dict[str, Any]] = {}
        self._closed = False
        self._poisoned = False
        self._poison_error: str | None = None

        self._path.parent.mkdir(parents=True, exist_ok=True)

        self._fd = os.open(str(self._path), os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, OSError) as err:
            os.close(self._fd)
            self._fd = -1
            self._closed = True
            raise BlockingIOError(f"Failed to acquire exclusive lock on {self._path}: {err}") from err

        try:
            self._replay()
        except Exception:
            self.close()
            raise

    @property
    def overrun(self) -> bool:
        """Return True if ledger is in overrun state."""
        return self._overrun

    @property
    def poisoned(self) -> bool:
        """Return True if ledger is poisoned due to persistence failure."""
        return self._poisoned

    @property
    def healthy(self) -> bool:
        """Return True if ledger is operational and healthy."""
        return not self._poisoned and not self._closed

    def _append_raw(self, record: dict[str, Any]) -> None:
        if self._poisoned:
            raise RuntimeError(f"BudgetLedger is poisoned due to previous write failure: {self._poison_error}")
        if self._closed or self._fd < 0:
            raise RuntimeError("BudgetLedger is closed")
        try:
            line = json.dumps(record, separators=(",", ":"), allow_nan=False) + "\n"
            data = line.encode("utf-8")
            os.lseek(self._fd, 0, os.SEEK_END)
            total_written = 0
            while total_written < len(data):
                written = os.write(self._fd, data[total_written:])
                if written == 0:
                    raise OSError("Write returned 0 bytes")
                total_written += written
            os.fsync(self._fd)
        except Exception as err:
            self._poisoned = True
            self._poison_error = str(err)
            raise

    def _replay(self) -> None:
        """Replay existing journal lines. Fail closed on corrupt/incomplete journal."""
        os.lseek(self._fd, 0, os.SEEK_SET)
        data = b""
        while True:
            chunk = os.read(self._fd, 65536)
            if not chunk:
                break
            data += chunk

        if not data:
            init_record = {"type": "init", "cap_usd": str(self._cap)}
            self._append_raw(init_record)
            return

        lines = data.split(b"\n")
        if lines and lines[-1] == b"":
            lines = lines[:-1]
        else:
            raise ValueError(f"Journal {self._path} has incomplete tail (missing trailing newline)")

        if not lines:
            raise ValueError(f"Journal {self._path} contains no valid records")

        first = True
        for line_no, raw_line in enumerate(lines, 1):
            if not raw_line.strip():
                raise ValueError(f"Journal {self._path} line {line_no} is empty/corrupt")
            try:
                record = json.loads(raw_line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as e:
                raise ValueError(f"Journal {self._path} line {line_no} invalid JSON: {e}") from e

            if not isinstance(record, dict) or "type" not in record:
                raise ValueError(f"Journal {self._path} line {line_no} malformed record")

            rec_type = record["type"]
            if first:
                first = False
                if rec_type != "init":
                    raise ValueError(f"Journal {self._path} missing init header")
                recorded_cap = _parse_decimal_str(record.get("cap_usd"), "journal cap_usd")
                if recorded_cap != self._cap:
                    raise ValueError(
                        f"Ledger cap mismatch: journal initialized with {recorded_cap}, requested {self._cap}"
                    )
                continue

            if rec_type == "reserve":
                req_id = record.get("request_id")
                if not isinstance(req_id, str) or not req_id:
                    raise ValueError(f"Journal {self._path} line {line_no} invalid request_id")
                if req_id in self._requests:
                    raise ValueError(f"Journal {self._path} line {line_no} duplicate reserve for {req_id}")
                upper_dec = _parse_decimal_str(record.get("upper_usd"), "upper_usd")
                self._requests[req_id] = {
                    "status": "reserved",
                    "upper_usd": upper_dec,
                    "committed": upper_dec,
                }
                self._committed += upper_dec

            elif rec_type == "settle":
                req_id = record.get("request_id")
                if not isinstance(req_id, str) or not req_id:
                    raise ValueError(f"Journal {self._path} line {line_no} invalid request_id")
                if req_id not in self._requests:
                    raise ValueError(f"Journal {self._path} line {line_no} settle unknown request_id: {req_id}")
                entry = self._requests[req_id]
                if entry["status"] != "reserved":
                    raise ValueError(f"Journal {self._path} line {line_no} duplicate settle for {req_id}")

                actual_raw = record.get("actual_usd")
                if actual_raw is None:
                    entry["status"] = "settled_unknown"
                else:
                    actual_dec = _parse_decimal_str(actual_raw, "actual_usd")
                    entry["status"] = "settled"
                    entry["actual_usd"] = actual_dec
                    diff = actual_dec - entry["upper_usd"]
                    self._committed += diff
                    if actual_dec > entry["upper_usd"]:
                        self._overrun = True
            else:
                raise ValueError(f"Journal {self._path} line {line_no} unknown record type: {rec_type}")

        os.lseek(self._fd, 0, os.SEEK_END)

    def reserve(self, request_id: str, upper_usd: str) -> bool:
        """Reserve upper bound amount for request_id.

        Raises RuntimeError if ledger is closed or poisoned.
        Raises ValueError on duplicate request_id or invalid input.
        Returns False if reservation would exceed cap or if ledger is in overrun state.
        Returns True on success.
        """
        if self._poisoned:
            raise RuntimeError(f"BudgetLedger is poisoned due to previous write failure: {self._poison_error}")
        if self._closed:
            raise RuntimeError("BudgetLedger is closed")
        if not isinstance(request_id, str) or not request_id:
            raise ValueError(f"request_id must be a non-empty string, got {request_id!r}")
        if request_id in self._requests:
            raise ValueError(f"Duplicate request_id: {request_id!r}")

        upper_dec = _parse_decimal_str(upper_usd, "upper_usd")

        if self._overrun:
            return False

        if self._committed + upper_dec > self._cap:
            return False

        proposed_committed = self._committed + upper_dec

        # Persist BEFORE mutating in-memory state
        self._append_raw({"type": "reserve", "request_id": request_id, "upper_usd": str(upper_dec)})

        # Only mutate in-memory state after successful write and fsync
        self._committed = proposed_committed
        self._requests[request_id] = {
            "status": "reserved",
            "upper_usd": upper_dec,
            "committed": upper_dec,
        }
        return True

    def settle(self, request_id: str, actual_usd: str | None) -> None:
        """Settle a previous reservation.

        Raises RuntimeError if ledger is closed or poisoned.
        If actual_usd is None, conservatively retains the full upper_usd hold.
        If actual_usd exceeds upper_usd, records actual cost, flags overrun, and stops further reserves.
        Raises KeyError if request_id was not reserved.
        Raises ValueError if request_id was already settled or actual_usd is invalid.
        """
        if self._poisoned:
            raise RuntimeError(f"BudgetLedger is poisoned due to previous write failure: {self._poison_error}")
        if self._closed:
            raise RuntimeError("BudgetLedger is closed")
        if not isinstance(request_id, str) or not request_id:
            raise ValueError(f"request_id must be a non-empty string, got {request_id!r}")
        if request_id not in self._requests:
            raise KeyError(f"Unknown request_id: {request_id!r}")

        entry = self._requests[request_id]
        if entry["status"] != "reserved":
            raise ValueError(f"request_id already settled: {request_id!r}")

        if actual_usd is None:
            # Persist BEFORE mutating in-memory state
            self._append_raw({"type": "settle", "request_id": request_id, "actual_usd": None})
            entry["status"] = "settled_unknown"
            return

        actual_dec = _parse_decimal_str(actual_usd, "actual_usd")
        upper_dec = entry["upper_usd"]
        diff = actual_dec - upper_dec
        is_overrun = actual_dec > upper_dec

        # Persist BEFORE mutating in-memory state
        self._append_raw({"type": "settle", "request_id": request_id, "actual_usd": str(actual_dec)})

        # Only mutate in-memory state after successful write and fsync
        entry["status"] = "settled"
        entry["actual_usd"] = actual_dec
        self._committed += diff
        if is_overrun:
            self._overrun = True

    def snapshot(self) -> dict[str, Any]:
        """Return dict with cap_usd, committed_usd, remaining_usd, and health status."""
        if self._closed:
            raise RuntimeError("BudgetLedger is closed")
        snap: dict[str, Any] = {
            "cap_usd": str(self._cap),
            "committed_usd": str(self._committed),
            "remaining_usd": str(self._cap - self._committed),
            "healthy": not self._poisoned,
        }
        if self._poisoned:
            snap["poisoned"] = True
            snap["error"] = self._poison_error
        return snap

    def close(self) -> None:
        """Unlock and close underlying file descriptor."""
        if self._closed:
            return
        self._closed = True
        if self._fd >= 0:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
            except OSError:
                pass
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = -1

    def __enter__(self) -> BudgetLedger:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass
