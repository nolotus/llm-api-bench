"""Transport module for OpenAI-compatible streaming chat completions.

Timings reflect client receive-time offsets using time.monotonic_ns(),
not provider/server token-time. Events arriving in the same read batch
share the exact receive_ns timestamp at the socket read boundary.

Deadline Scope & Observer Effect Disclosure:
- Standard library http.client/socket operations (such as blocking DNS resolution
  via getaddrinfo and HTTP header parsing in getresponse()) as well as user
  synchronous disk-bound on_event callbacks cannot be preemptively terminated
  without unsafe OS thread kills or signal corruption.
- timeout_s is therefore enforced as a cooperative operation deadline across
  network socket reads and immediately after each synchronous callback execution.
- If a synchronous callback overruns the deadline (even on the terminal [DONE] event),
  done is marked False and error is set to 'Timeout'.
- Synchronous fsync in callbacks creates an observer effect on inter-batch receive
  timings by delaying subsequent socket reads; cumulative callback overhead is tracked
  and disclosed in 'audit_callback_ms'.
"""
from __future__ import annotations
import codecs
import ipaddress
import json
import socket
import ssl
import time
import urllib.parse
from datetime import datetime, timezone
from http.client import HTTPConnection, HTTPSConnection
from typing import Any, Callable

MAX_EVENT_BYTES: int = 1024 * 1024       # 1 MB max per SSE event
MAX_TOTAL_BYTES: int = 32 * 1024 * 1024  # 32 MB max total bytes per stream
DEFAULT_TIMEOUT_S: float = 120.0

ALLOWED_HEADERS: frozenset[str] = frozenset({
    "content-type",
    "date",
    "request-id",
    "x-request-id",
    "x-stainless-request-id",
    "x-amzn-requestid",
    "cf-ray",
    "x-b3-traceid",
    "traceparent",
    "retry-after",
    "retry-after-ms",
    "x-should-retry",
    "x-ratelimit-limit-requests",
    "x-ratelimit-limit-tokens",
    "x-ratelimit-remaining-requests",
    "x-ratelimit-remaining-tokens",
    "x-ratelimit-reset-requests",
    "x-ratelimit-reset-tokens",
    "x-ratelimit-limit",
    "x-ratelimit-remaining",
    "x-ratelimit-reset",
    "ratelimit-limit",
    "ratelimit-remaining",
    "ratelimit-reset",
})


def _is_loopback(host: str) -> bool:
    if not host:
        return False
    h = host.lower().strip("[]")
    if h in ("localhost", "127.0.0.1", "::1"):
        return True
    try:
        return ipaddress.ip_address(h).is_loopback
    except ValueError:
        return False


def _filter_headers(raw_headers: list[tuple[str, str]]) -> dict[str, str]:
    allowed: dict[str, str] = {}
    for k, v in raw_headers:
        lk = k.lower().strip()
        if lk in ALLOWED_HEADERS:
            allowed[lk] = v
    return allowed


def _resolve_url(base_url: str) -> tuple[str, str, int, str]:
    parsed = urllib.parse.urlsplit(base_url)
    scheme = parsed.scheme.lower()
    host = parsed.hostname or ""
    port = parsed.port
    if port is None:
        port = 443 if scheme == "https" else 80

    path = parsed.path
    if not path or path == "/":
        endpoint = "/chat/completions"
    elif path.endswith("/chat/completions"):
        endpoint = path
    else:
        endpoint = f"{path.rstrip('/')}/chat/completions"

    if parsed.query:
        endpoint = f"{endpoint}?{parsed.query}"

    return scheme, host, port, endpoint


def stream_chat(
    base_url: str,
    api_key: str,
    payload: dict,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    on_event: Callable[[dict], Any] | None = None,
) -> dict:
    """Stream chat completion using stdlib http.client.

    Fresh connection per request, no keepalive, no redirects, no retries.
    Client receive-time offsets with time.monotonic_ns().
    """
    start_ns = time.monotonic_ns()
    deadline_ns = start_ns + int(timeout_s * 1e9)
    started_at_utc = datetime.now(timezone.utc).isoformat()

    headers_ms: float | None = None
    first_generated_ms: float | None = None
    first_content_ms: float | None = None
    last_generated_ms: float | None = None
    status: int | None = None
    resp_headers: dict[str, str] = {}
    events: list[dict] = []
    final_usage: dict | None = None
    response_model: str | None = None
    finish_reason: str | None = None
    done: bool = False
    error: str | None = None
    audit_callback_ms: float = 0.0

    def invoke_callback(ev: dict) -> bool:
        """Invokes on_event synchronously, tracks duration, and enforces deadline.

        Returns True on success; returns False on audit failure or deadline timeout.
        """
        nonlocal audit_callback_ms, error, done
        if on_event is None:
            return True
        cb_start = time.monotonic_ns()
        try:
            on_event(ev)
        except Exception:
            audit_callback_ms += (time.monotonic_ns() - cb_start) / 1e6
            error = "AuditWriteFailed"
            done = False
            return False
        audit_callback_ms += (time.monotonic_ns() - cb_start) / 1e6
        if time.monotonic_ns() > deadline_ns:
            error = "Timeout"
            done = False
            return False
        return True

    conn: HTTPConnection | None = None

    try:
        try:
            scheme, host, port, endpoint = _resolve_url(base_url)
        except Exception:
            error = "ValueError"
            raise

        if scheme == "https":
            pass
        elif scheme == "http":
            if not _is_loopback(host):
                error = "InsecureScheme"
                raise ValueError("HTTP only allowed for loopback addresses")
        else:
            error = "InsecureScheme"
            raise ValueError(f"Unsupported scheme: {scheme}")

        req_payload = dict(payload)
        req_payload.setdefault("stream", True)
        body_bytes = json.dumps(req_payload).encode("utf-8")

        req_headers = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "Connection": "close",
        }
        if api_key:
            req_headers["Authorization"] = f"Bearer {api_key}"

        rem_ns = deadline_ns - time.monotonic_ns()
        if rem_ns <= 0:
            error = "Timeout"
            raise TimeoutError("Deadline exceeded before connect")
        rem_s = max(rem_ns / 1e9, 0.001)

        if scheme == "https":
            ctx = ssl.create_default_context()
            conn = HTTPSConnection(host, port, timeout=rem_s, context=ctx)
        else:
            conn = HTTPConnection(host, port, timeout=rem_s)

        conn.connect()
        raw_sock = conn.sock

        rem_ns = deadline_ns - time.monotonic_ns()
        if rem_ns <= 0:
            error = "Timeout"
            raise TimeoutError("Deadline exceeded before request")
        if raw_sock:
            raw_sock.settimeout(max(rem_ns / 1e9, 0.001))

        conn.request("POST", endpoint, body=body_bytes, headers=req_headers)

        rem_ns = deadline_ns - time.monotonic_ns()
        if rem_ns <= 0:
            error = "Timeout"
            raise TimeoutError("Deadline exceeded before getresponse")
        if raw_sock:
            raw_sock.settimeout(max(rem_ns / 1e9, 0.001))

        resp = conn.getresponse()
        headers_ms = (time.monotonic_ns() - start_ns) / 1e6
        status = resp.status
        resp_headers = _filter_headers(resp.getheaders())

        # Safely preserve socket reference for read1 loop
        if raw_sock is None:
            raw_sock = conn.sock
        if raw_sock is None and hasattr(resp, "fp") and hasattr(resp.fp, "raw"):
            raw_sock = getattr(resp.fp.raw, "_sock", None)

        if 300 <= status < 400:
            error = "RedirectNotAllowed"
            return _build_record(
                started_at_utc, headers_ms, first_generated_ms, first_content_ms,
                last_generated_ms, start_ns, status, resp_headers, events,
                final_usage, response_model, finish_reason, done, error, audit_callback_ms,
            )

        if status >= 400:
            error = "HTTPError"
            return _build_record(
                started_at_utc, headers_ms, first_generated_ms, first_content_ms,
                last_generated_ms, start_ns, status, resp_headers, events,
                final_usage, response_model, finish_reason, done, error, audit_callback_ms,
            )

        decoder = codecs.getincrementaldecoder("utf-8")(errors="strict")
        buffer = ""
        current_event_data: list[str] = []
        has_event_data = False
        total_bytes = 0

        while True:
            rem_ns = deadline_ns - time.monotonic_ns()
            if rem_ns <= 0:
                error = "Timeout"
                break
            sock_obj = raw_sock or conn.sock
            if sock_obj:
                try:
                    sock_obj.settimeout(max(rem_ns / 1e9, 0.001))
                except (OSError, AttributeError):
                    pass

            try:
                chunk = resp.read1(4096)
            except (socket.timeout, TimeoutError):
                error = "Timeout"
                break
            except (ConnectionResetError, BrokenPipeError, ConnectionError):
                error = "EOFWithoutDone"
                break

            # Immediate timestamp at read boundary for this entire batch
            receive_ns = time.monotonic_ns()
            batch_elapsed_ns = receive_ns - start_ns
            batch_elapsed_ms = batch_elapsed_ns / 1e6

            if not chunk:
                # EOF reached
                try:
                    remaining_text = decoder.decode(b"", final=True)
                    buffer += remaining_text
                except UnicodeDecodeError:
                    error = "InvalidUTF8"
                    break

                if buffer or has_event_data:
                    if buffer:
                        line = buffer.rstrip("\r\n")
                        if line.startswith("data:"):
                            val = line[5:]
                            if val.startswith(" "):
                                val = val[1:]
                            current_event_data.append(val)
                            has_event_data = True
                    if has_event_data:
                        raw_data = "\n".join(current_event_data)
                        if raw_data.strip() == "[DONE]":
                            done_ev = {"elapsed_ns": batch_elapsed_ns, "raw": raw_data, "data": raw_data}
                            events.append(done_ev)
                            if not invoke_callback(done_ev):
                                break
                            done = True
                        else:
                            try:
                                parsed = json.loads(raw_data)
                            except Exception:
                                bad_ev = {"elapsed_ns": batch_elapsed_ns, "raw": raw_data, "data": raw_data}
                                events.append(bad_ev)
                                if not invoke_callback(bad_ev):
                                    break
                                error = "InvalidEventJSON"
                                break
                            e_dict = {"elapsed_ns": batch_elapsed_ns, "raw": raw_data, "data": raw_data}
                            if isinstance(parsed, dict):
                                for k, v in parsed.items():
                                    if k not in e_dict:
                                        e_dict[k] = v
                            events.append(e_dict)
                            if not invoke_callback(e_dict):
                                break

                if not done and error is None:
                    error = "EOFWithoutDone"
                break

            total_bytes += len(chunk)
            if total_bytes > MAX_TOTAL_BYTES:
                error = "TotalBytesExceeded"
                break

            try:
                text = decoder.decode(chunk)
            except UnicodeDecodeError:
                error = "InvalidUTF8"
                break

            buffer += text
            if len(buffer) + sum(len(x) for x in current_event_data) > MAX_EVENT_BYTES:
                error = "EventSizeExceeded"
                break

            i = 0
            n = len(buffer)
            line_start = 0

            while i < n:
                ch = buffer[i]
                if ch == "\r":
                    if i + 1 < n:
                        if buffer[i + 1] == "\n":
                            line = buffer[line_start:i]
                            i += 2
                            line_start = i
                        else:
                            line = buffer[line_start:i]
                            i += 1
                            line_start = i
                    else:
                        break
                elif ch == "\n":
                    line = buffer[line_start:i]
                    i += 1
                    line_start = i
                else:
                    i += 1
                    continue

                if line == "":
                    if has_event_data:
                        raw_data = "\n".join(current_event_data)
                        current_event_data = []
                        has_event_data = False

                        if raw_data.strip() == "[DONE]":
                            done_ev = {"elapsed_ns": batch_elapsed_ns, "raw": raw_data, "data": raw_data}
                            events.append(done_ev)
                            if not invoke_callback(done_ev):
                                break
                            done = True
                            break

                        try:
                            parsed = json.loads(raw_data)
                        except Exception:
                            bad_ev = {"elapsed_ns": batch_elapsed_ns, "raw": raw_data, "data": raw_data}
                            events.append(bad_ev)
                            if not invoke_callback(bad_ev):
                                break
                            error = "InvalidEventJSON"
                            break

                        event_dict = {"elapsed_ns": batch_elapsed_ns, "raw": raw_data, "data": raw_data}
                        if isinstance(parsed, dict):
                            for k, v in parsed.items():
                                if k not in event_dict:
                                    event_dict[k] = v
                        events.append(event_dict)

                        if not invoke_callback(event_dict):
                            break

                        if isinstance(parsed, dict):
                            if parsed.get("model") and not response_model:
                                response_model = parsed.get("model")
                            if parsed.get("usage") is not None:
                                final_usage = parsed.get("usage")

                            choices = parsed.get("choices")
                            if isinstance(choices, list):
                                has_r = False
                                has_c = False
                                for choice in choices:
                                    if not isinstance(choice, dict):
                                        continue
                                    fr = choice.get("finish_reason")
                                    if fr is not None:
                                        finish_reason = fr
                                    delta = choice.get("delta")
                                    if isinstance(delta, dict):
                                        r = delta.get("reasoning_content") or delta.get("reasoning")
                                        if r and isinstance(r, str) and len(r) > 0:
                                            has_r = True
                                        c = delta.get("content")
                                        if c and isinstance(c, str) and len(c) > 0:
                                            has_c = True

                                if has_r:
                                    if first_generated_ms is None:
                                        first_generated_ms = batch_elapsed_ms
                                    last_generated_ms = batch_elapsed_ms
                                if has_c:
                                    if first_content_ms is None:
                                        first_content_ms = batch_elapsed_ms
                                    if first_generated_ms is None:
                                        first_generated_ms = batch_elapsed_ms
                                    last_generated_ms = batch_elapsed_ms
                elif line.startswith(":"):
                    pass
                elif line.startswith("data:"):
                    has_event_data = True
                    val = line[5:]
                    if val.startswith(" "):
                        val = val[1:]
                    current_event_data.append(val)

            buffer = buffer[line_start:]
            if done or error:
                break

    except (socket.timeout, TimeoutError):
        if error is None:
            error = "Timeout"
    except (ConnectionRefusedError, ConnectionResetError, BrokenPipeError, ConnectionError):
        if error is None:
            error = "ConnectionError"
    except Exception as exc:
        if error is None:
            error = type(exc).__name__
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    return _build_record(
        started_at_utc, headers_ms, first_generated_ms, first_content_ms,
        last_generated_ms, start_ns, status, resp_headers, events,
        final_usage, response_model, finish_reason, done, error, audit_callback_ms,
    )


def _build_record(
    started_at_utc: str,
    headers_ms: float | None,
    first_generated_ms: float | None,
    first_content_ms: float | None,
    last_generated_ms: float | None,
    start_ns: int,
    status: int | None,
    headers: dict[str, str],
    events: list[dict],
    final_usage: dict | None,
    response_model: str | None,
    finish_reason: str | None,
    done: bool,
    error: str | None,
    audit_callback_ms: float,
) -> dict:
    total_ms = (time.monotonic_ns() - start_ns) / 1e6
    return {
        "started_at_utc": started_at_utc,
        "headers_ms": headers_ms,
        "first_generated_ms": first_generated_ms,
        "first_content_ms": first_content_ms,
        "last_generated_ms": last_generated_ms,
        "total_ms": total_ms,
        "status": status,
        "headers": headers,
        "events": events,
        "final_usage": final_usage,
        "response_model": response_model,
        "finish_reason": finish_reason,
        "done": done,
        "error": error,
        "audit_callback_ms": audit_callback_ms,
        "deadline_scope": "cooperative_network_and_callback",
    }
