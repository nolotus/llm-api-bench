"""Adapter from stage_bench's (task, tier) callable to transport.stream_chat."""
from typing import Any, Callable

import transport


def make_transport(
    base_url: str,
    api_key: str,
    *,
    timeout_s: float = 120,
    on_event: Callable[[dict], Any] | None = None,
    extra_headers: dict[str, str] | None = None,
) -> Callable[[dict, dict], dict]:
    def call(task: dict, tier: dict) -> dict:
        payload = dict(task["payload"])
        extra = tier.get("extra_body")
        if isinstance(extra, dict):
            for key, value in extra.items():
                if key not in payload:
                    payload[key] = value
        payload["stream"] = True
        options = payload.get("stream_options")
        options = dict(options) if isinstance(options, dict) else {}
        options["include_usage"] = True
        payload["stream_options"] = options
        try:
            return transport.stream_chat(base_url, api_key, payload, timeout_s=timeout_s, on_event=on_event, extra_headers=extra_headers)
        except Exception as exc:
            # Do not allow credentials (including URL userinfo) into surfaced text.
            message = str(exc).replace(api_key, "[REDACTED]")
            from urllib.parse import urlsplit, urlunsplit
            parsed = urlsplit(base_url)
            if parsed.username is not None or parsed.password is not None:
                safe_netloc = parsed.hostname or ""
                if parsed.port is not None:
                    safe_netloc += f":{parsed.port}"
                message = message.replace(base_url, urlunsplit((parsed.scheme, safe_netloc, parsed.path, parsed.query, parsed.fragment)))
            if message != str(exc):
                raise RuntimeError(message) from None
            raise
    return call
