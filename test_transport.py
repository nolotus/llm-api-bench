"""Unit tests for transport.py.

Verifies fresh connections, no retries, no redirects, SSE streaming,
monotonic timing, UTF-8 across chunks, multi-line / CRLF, role/empty chunk ignoring,
reasoning vs content separation, usage not summed, header allowlisting,
AuditWriteFailed callback behavior, slow trickle cumulative timeout,
exact same-batch event timing, sleep callback exceeding deadline,
DONE callback exceeding deadline, and clean error reporting.
"""
from __future__ import annotations
import http.server
import json
import socket
import socketserver
import threading
import time
import unittest
from typing import Any

from transport import stream_chat


class MockServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def start_mock_server(handler_cls):
    server = MockServer(("127.0.0.1", 0), handler_cls)
    port = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port


class TestTransport(unittest.TestCase):
    def test_baseline_success(self):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("X-Request-Id", "req-12345")
                self.send_header("X-RateLimit-Remaining", "99")
                self.send_header("Date", "Tue, 20 Oct 2026 12:00:00 GMT")
                self.send_header("Set-Cookie", "secret_cookie=foo")
                self.send_header("Authorization", "secret_auth")
                self.end_headers()

                # Chunk 1: role only (should not trigger TTFT)
                c1 = json.dumps({"model": "gpt-4o", "choices": [{"delta": {"role": "assistant"}}]})
                self.wfile.write(f"data: {c1}\n\n".encode("utf-8"))
                self.wfile.flush()
                time.sleep(0.01)

                # Chunk 2: reasoning content
                c2 = json.dumps({"choices": [{"delta": {"reasoning_content": "thinking"}}]})
                self.wfile.write(f"data: {c2}\n\n".encode("utf-8"))
                self.wfile.flush()
                time.sleep(0.01)

                # Chunk 3: actual content
                c3 = json.dumps({"choices": [{"delta": {"content": "Hello world"}}]})
                self.wfile.write(f"data: {c3}\n\n".encode("utf-8"))
                self.wfile.flush()
                time.sleep(0.01)

                # Chunk 4: finish reason + usage
                c4 = json.dumps({
                    "choices": [{"delta": {}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                })
                self.wfile.write(f"data: {c4}\n\n".encode("utf-8"))
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()

        server, port = start_mock_server(Handler)
        try:
            seen_events = []
            res = stream_chat(
                f"http://127.0.0.1:{port}",
                "sk-test-secret-key",
                {"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
                timeout_s=5.0,
                on_event=seen_events.append,
            )
            self.assertEqual(res["status"], 200)
            self.assertTrue(res["done"])
            self.assertIsNone(res["error"])
            self.assertEqual(res["response_model"], "gpt-4o")
            self.assertEqual(res["finish_reason"], "stop")
            self.assertEqual(res["final_usage"], {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15})
            # 4 chunks + 1 [DONE] terminal event
            self.assertEqual(len(res["events"]), 5)
            self.assertEqual(len(seen_events), 5)
            self.assertEqual(seen_events[-1]["raw"], "[DONE]")
            self.assertIn("audit_callback_ms", res)
            self.assertEqual(res["deadline_scope"], "cooperative_network_and_callback")

            # Check allowlist headers
            self.assertEqual(res["headers"]["content-type"], "text/event-stream")
            self.assertEqual(res["headers"]["x-request-id"], "req-12345")
            self.assertEqual(res["headers"]["x-ratelimit-remaining"], "99")
            self.assertIn("date", res["headers"])
            self.assertNotIn("set-cookie", res["headers"])
            self.assertNotIn("authorization", res["headers"])

            # Check timings
            self.assertIsNotNone(res["headers_ms"])
            self.assertIsNotNone(res["first_generated_ms"])
            self.assertIsNotNone(res["first_content_ms"])
            self.assertIsNotNone(res["last_generated_ms"])
            self.assertGreater(res["first_content_ms"], res["first_generated_ms"])
            self.assertGreaterEqual(res["last_generated_ms"], res["first_content_ms"])
            self.assertGreaterEqual(res["total_ms"], res["last_generated_ms"])
        finally:
            server.shutdown()
            server.server_close()

    def test_role_and_empty_chunks_ignored_for_ttft(self):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                # Empty content and role only
                c1 = json.dumps({"choices": [{"delta": {"role": "assistant"}}]})
                c2 = json.dumps({"choices": [{"delta": {"content": ""}}]})
                self.wfile.write(f"data: {c1}\n\n".encode("utf-8"))
                self.wfile.write(f"data: {c2}\n\n".encode("utf-8"))
                self.wfile.flush()
                time.sleep(0.02)
                # First non-empty
                c3 = json.dumps({"choices": [{"delta": {"content": "Hi"}}]})
                self.wfile.write(f"data: {c3}\n\n".encode("utf-8"))
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()

        server, port = start_mock_server(Handler)
        try:
            res = stream_chat(f"http://127.0.0.1:{port}", "sk-key", {})
            self.assertTrue(res["done"])
            self.assertIsNotNone(res["first_generated_ms"])
            self.assertIsNotNone(res["first_content_ms"])
            self.assertEqual(res["first_generated_ms"], res["first_content_ms"])
        finally:
            server.shutdown()
            server.server_close()

    def test_final_usage_last_only_not_summed(self):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                c1 = json.dumps({"usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}})
                c2 = json.dumps({"usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}})
                self.wfile.write(f"data: {c1}\n\n".encode("utf-8"))
                self.wfile.write(f"data: {c2}\n\n".encode("utf-8"))
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()

        server, port = start_mock_server(Handler)
        try:
            res = stream_chat(f"http://127.0.0.1:{port}", "sk-key", {})
            self.assertEqual(res["final_usage"], {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30})
        finally:
            server.shutdown()
            server.server_close()

    def test_stream_break_eof_without_done(self):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                c = json.dumps({"choices": [{"delta": {"content": "part"}}]})
                self.wfile.write(f"data: {c}\n\n".encode("utf-8"))
                self.wfile.flush()

        server, port = start_mock_server(Handler)
        try:
            res = stream_chat(f"http://127.0.0.1:{port}", "key", {})
            self.assertFalse(res["done"])
            self.assertEqual(res["error"], "EOFWithoutDone")
        finally:
            server.shutdown()
            server.server_close()

    def test_invalid_event_json(self):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                self.wfile.write(b"data: {broken json\n\n")
                self.wfile.flush()

        server, port = start_mock_server(Handler)
        try:
            seen = []
            res = stream_chat(f"http://127.0.0.1:{port}", "key", {}, on_event=seen.append)
            self.assertFalse(res["done"])
            self.assertEqual(res["error"], "InvalidEventJSON")
            # Raw broken event persisted for audit before failure
            self.assertEqual(len(seen), 1)
            self.assertEqual(seen[0]["raw"], "{broken json")
        finally:
            server.shutdown()
            server.server_close()

    def test_invalid_utf8(self):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                self.wfile.write(b"data: \xff\xfe\xfd\n\n")
                self.wfile.flush()

        server, port = start_mock_server(Handler)
        try:
            res = stream_chat(f"http://127.0.0.1:{port}", "key", {})
            self.assertFalse(res["done"])
            self.assertEqual(res["error"], "InvalidUTF8")
        finally:
            server.shutdown()
            server.server_close()

    def test_timeout(self):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                time.sleep(0.5)
                self.send_response(200)
                self.end_headers()

        server, port = start_mock_server(Handler)
        try:
            res = stream_chat(f"http://127.0.0.1:{port}", "key", {}, timeout_s=0.1)
            self.assertFalse(res["done"])
            self.assertEqual(res["error"], "Timeout")
        finally:
            server.shutdown()
            server.server_close()

    def test_redirect_not_allowed(self):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                self.send_response(307)
                self.send_header("Location", "/redirected")
                self.end_headers()

        server, port = start_mock_server(Handler)
        try:
            res = stream_chat(f"http://127.0.0.1:{port}", "key", {})
            self.assertEqual(res["status"], 307)
            self.assertFalse(res["done"])
            self.assertEqual(res["error"], "RedirectNotAllowed")
        finally:
            server.shutdown()
            server.server_close()

    def test_insecure_scheme_rejected(self):
        res = stream_chat("http://example.com/v1", "key", {})
        self.assertFalse(res["done"])
        self.assertEqual(res["error"], "InsecureScheme")

    def test_utf8_split_across_chunks(self):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                chinese_char = "好".encode("utf-8")  # 3 bytes: e5 a5 bd
                part1 = b'data: {"choices":[{"delta":{"content":"' + chinese_char[:1]
                part2 = chinese_char[1:] + b'"}}]}\n\ndata: [DONE]\n\n'
                self.wfile.write(part1)
                self.wfile.flush()
                time.sleep(0.01)
                self.wfile.write(part2)
                self.wfile.flush()

        server, port = start_mock_server(Handler)
        try:
            res = stream_chat(f"http://127.0.0.1:{port}", "key", {})
            self.assertTrue(res["done"])
            self.assertIsNone(res["error"])
            self.assertEqual(len(res["events"]), 2)
            self.assertEqual(res["events"][0]["choices"][0]["delta"]["content"], "好")
            self.assertEqual(res["events"][1]["raw"], "[DONE]")
        finally:
            server.shutdown()
            server.server_close()

    def test_crlf_and_multiline_data(self):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                # CRLF, comments, multiline data
                body = (
                    b": comment\r\n"
                    b"data: {\"choices\": [{\"delta\": {\"content\": \"hello\"}}]}\r\n\r\n"
                    b"data: [DONE]\r\n\r\n"
                )
                self.wfile.write(body)
                self.wfile.flush()

        server, port = start_mock_server(Handler)
        try:
            res = stream_chat(f"http://127.0.0.1:{port}", "key", {})
            self.assertTrue(res["done"])
            self.assertIsNone(res["error"])
            self.assertEqual(len(res["events"]), 2)
        finally:
            server.shutdown()
            server.server_close()

    def test_http_error_sanitized(self):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"error": "invalid api key sk-12345"}')
                self.wfile.flush()

        server, port = start_mock_server(Handler)
        try:
            res = stream_chat(f"http://127.0.0.1:{port}", "sk-secret", {})
            self.assertEqual(res["status"], 401)
            self.assertFalse(res["done"])
            self.assertEqual(res["error"], "HTTPError")
            # Verify secret not leaked
            self.assertNotIn("sk-secret", json.dumps(res))
        finally:
            server.shutdown()
            server.server_close()

    def test_callback_failure_stops_stream_and_marks_audit_write_failed(self):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                try:
                    c1 = json.dumps({"choices": [{"delta": {"content": "c1"}}]})
                    self.wfile.write(f"data: {c1}\n\n".encode("utf-8"))
                    self.wfile.flush()
                    c2 = json.dumps({"choices": [{"delta": {"content": "c2"}}]})
                    self.wfile.write(f"data: {c2}\n\n".encode("utf-8"))
                    self.wfile.write(b"data: [DONE]\n\n")
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    pass

        server, port = start_mock_server(Handler)
        try:
            def bad_callback(event):
                raise OSError("Disk full / permission denied on audit log")

            res = stream_chat(f"http://127.0.0.1:{port}", "key", {}, on_event=bad_callback)
            self.assertFalse(res["done"])
            self.assertEqual(res["error"], "AuditWriteFailed")
        finally:
            server.shutdown()
            server.server_close()

    def test_slow_trickle_cumulative_deadline_timeout(self):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                # 6 chunks, each sleeping 0.05s (total 0.3s), individual chunk < 0.1s socket idle, but cumulative > 0.15s deadline
                for i in range(6):
                    time.sleep(0.05)
                    try:
                        c = json.dumps({"choices": [{"delta": {"content": f"t{i}"}}]})
                        self.wfile.write(f"data: {c}\n\n".encode("utf-8"))
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError):
                        break

        server, port = start_mock_server(Handler)
        try:
            res = stream_chat(f"http://127.0.0.1:{port}", "key", {}, timeout_s=0.15)
            self.assertFalse(res["done"])
            self.assertEqual(res["error"], "Timeout")
        finally:
            server.shutdown()
            server.server_close()

    def test_retry_and_rate_limit_headers_allowlist(self):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Retry-After", "10")
                self.send_header("Retry-After-Ms", "10000")
                self.send_header("X-Should-Retry", "true")
                self.send_header("X-RateLimit-Reset-Tokens", "1500")
                self.send_header("X-Custom-Unknown", "deny-this")
                self.end_headers()
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()

        server, port = start_mock_server(Handler)
        try:
            res = stream_chat(f"http://127.0.0.1:{port}", "key", {})
            self.assertTrue(res["done"])
            self.assertEqual(res["headers"]["retry-after"], "10")
            self.assertEqual(res["headers"]["retry-after-ms"], "10000")
            self.assertEqual(res["headers"]["x-should-retry"], "true")
            self.assertEqual(res["headers"]["x-ratelimit-reset-tokens"], "1500")
            self.assertNotIn("x-custom-unknown", res["headers"])
        finally:
            server.shutdown()
            server.server_close()

    def test_same_batch_events_share_exact_receive_timestamp(self):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                # Send two events in one single TCP packet / read
                c1 = json.dumps({"choices": [{"delta": {"content": "one"}}]})
                c2 = json.dumps({"choices": [{"delta": {"content": "two"}}]})
                batch = f"data: {c1}\n\ndata: {c2}\n\ndata: [DONE]\n\n".encode("utf-8")
                self.wfile.write(batch)
                self.wfile.flush()

        server, port = start_mock_server(Handler)
        try:
            events_seen = []
            def slow_journal(ev):
                events_seen.append(ev)
                time.sleep(0.02)  # Simulate slow fsync write

            res = stream_chat(f"http://127.0.0.1:{port}", "key", {}, on_event=slow_journal)
            self.assertTrue(res["done"])
            self.assertEqual(len(events_seen), 3)
            # In the same read batch, events share the exact same socket receive timestamp
            self.assertEqual(events_seen[0]["elapsed_ns"], events_seen[1]["elapsed_ns"])
            self.assertEqual(events_seen[1]["elapsed_ns"], events_seen[2]["elapsed_ns"])
        finally:
            server.shutdown()
            server.server_close()

    def test_sleep_callback_exceeds_deadline_returns_timeout_and_does_not_succeed(self):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                try:
                    c1 = json.dumps({"choices": [{"delta": {"content": "c1"}}]})
                    self.wfile.write(f"data: {c1}\n\n".encode("utf-8"))
                    self.wfile.flush()
                    time.sleep(0.05)
                    c2 = json.dumps({"choices": [{"delta": {"content": "c2"}}]})
                    self.wfile.write(f"data: {c2}\n\n".encode("utf-8"))
                    self.wfile.write(b"data: [DONE]\n\n")
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    pass

        server, port = start_mock_server(Handler)
        try:
            def blocking_callback(ev):
                time.sleep(0.2)  # Overrun timeout_s=0.15

            res = stream_chat(f"http://127.0.0.1:{port}", "key", {}, timeout_s=0.15, on_event=blocking_callback)
            self.assertFalse(res["done"])
            self.assertEqual(res["error"], "Timeout")
            self.assertGreater(res["audit_callback_ms"], 150.0)
            # Second chunk was not processed because stream stopped immediately
            self.assertEqual(len(res["events"]), 1)
        finally:
            server.shutdown()
            server.server_close()

    def test_done_callback_sleep_exceeds_deadline_marks_done_false_and_error_timeout(self):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()

        server, port = start_mock_server(Handler)
        try:
            def blocking_done_callback(ev):
                if ev.get("raw") == "[DONE]":
                    time.sleep(0.25)  # Overrun timeout_s=0.15 on terminal event

            res = stream_chat(f"http://127.0.0.1:{port}", "key", {}, timeout_s=0.15, on_event=blocking_done_callback)
            self.assertFalse(res["done"])
            self.assertEqual(res["error"], "Timeout")
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
