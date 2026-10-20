import unittest
from unittest.mock import patch

from live_transport import make_transport

FAKE_KEY = "FAKE_KEY"


class LiveTransportTests(unittest.TestCase):
    def test_payload_and_response_fields_pass_through(self):
        response = {"status": 200, "final_usage": {"x": 1}, "done": True,
                    "first_generated_ms": 1.2, "first_content_ms": 2.3,
                    "total_ms": 4.5, "finish_reason": "stop", "events": [{"a": 1}]}
        task = {"payload": {"model": "m", "messages": [], "stream_options": {"x": 2}}}
        tier = {"extra_body": {"model": "other", "temperature": 0, "messages": [1], "stream": False}}
        callback = lambda event: None
        with patch("live_transport.transport.stream_chat", return_value=response) as mocked:
            result = make_transport("http://localhost", FAKE_KEY, timeout_s=7, on_event=callback)(task, tier)
        self.assertIs(result, response)
        args, kwargs = mocked.call_args
        self.assertEqual(args[:2], ("http://localhost", FAKE_KEY))
        self.assertEqual(args[2], {"model": "m", "messages": [], "stream_options": {"x": 2, "include_usage": True}, "temperature": 0, "stream": True})
        self.assertEqual(kwargs, {"timeout_s": 7, "on_event": callback, "extra_headers": None})
        for field in ("status", "final_usage", "done", "first_generated_ms", "first_content_ms", "total_ms", "finish_reason", "events"):
            self.assertIs(result[field], response[field])
        self.assertNotIn(FAKE_KEY, repr(result))

    def test_exception_propagates_without_key(self):
        message = "upstream failure"
        with patch("live_transport.transport.stream_chat", side_effect=RuntimeError(message)):
            with self.assertRaisesRegex(RuntimeError, message) as caught:
                make_transport("http://localhost", FAKE_KEY)({"payload": {}}, {})
        self.assertNotIn(FAKE_KEY, str(caught.exception))

    def test_exception_with_key_is_sanitized(self):
        with patch("live_transport.transport.stream_chat", side_effect=RuntimeError("failure " + FAKE_KEY)):
            with self.assertRaises(RuntimeError) as caught:
                make_transport("http://localhost", FAKE_KEY)({"payload": {}}, {})
        self.assertNotIn(FAKE_KEY, str(caught.exception))


if __name__ == "__main__":
    unittest.main()
