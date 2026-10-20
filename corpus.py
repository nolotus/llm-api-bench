"""Deterministic local prompt corpus generators."""

from __future__ import annotations


def _unit(tag: str) -> str:
    # A stable, readable ASCII unit; tag is included in every generated body.
    clean = ''.join(ch if ch.isascii() and ch.isalnum() else '_' for ch in str(tag)) or 'sample'
    return f"Corpus {clean} contains repeatable English benchmark material. "


def build_text(target_tokens: int, *, bytes_per_token: float = 4.6,
               tag: str, suffix: str = "") -> str:
    """Build a deterministic ASCII string near target_tokens * bytes_per_token bytes.

    The body depends only on tag and target size. suffix is strictly appended,
    allowing callers to vary a final repetition marker without changing prefix.
    """
    if target_tokens < 0 or bytes_per_token <= 0:
        raise ValueError("target_tokens must be nonnegative and bytes_per_token positive")
    target_bytes = max(0, round(target_tokens * bytes_per_token))
    unit = _unit(tag)
    # Fill the requested byte budget exactly (before suffix), without splitting
    # the stability contract: all same-tag bodies are prefixes of longer ones.
    body = (unit * ((target_bytes // len(unit)) + 1))[:target_bytes]
    return body + suffix


def build_pair(target_tokens: int, tag: str, rep: int) -> tuple[str, str]:
    """Return cold/warm prompts sharing an identical body prefix."""
    cold = build_text(target_tokens, tag=tag)
    warm = build_text(target_tokens, tag=tag, suffix=f"rep{rep:02d}")
    return cold, warm


def build_growth(turns: list[int], tag: str) -> list[str]:
    """Build cumulative prompts for increasing target-token milestones."""
    result: list[str] = []
    previous_target = 0
    for target in turns:
        if target < previous_target:
            raise ValueError("turn targets must be nondecreasing")
        addition = build_text(target - previous_target, tag=tag)
        result.append((result[-1] if result else "") + addition)
        previous_target = target
    return result


def estimate_tokens(text: str, bytes_per_token: float) -> int:
    if bytes_per_token <= 0:
        raise ValueError("bytes_per_token must be positive")
    return round(len(text.encode("utf-8")) / bytes_per_token)


def actual_ratio(bytes_len: int, tokens: int) -> float:
    if tokens <= 0:
        raise ValueError("tokens must be positive")
    return bytes_len / tokens
