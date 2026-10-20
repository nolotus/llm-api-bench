# Output/reasoning cap evidence — LithosAI DeepSeek-V4.1-Flash

**Decision:** `reasoning_cap_verified=true` for preregistration planning only. This is documentation-based evidence, not a pilot or live API verification. No real API request was made for this evidence check.

## Provider documentation

The full official LithosAI page [Agent Integrations](https://docs.lithosai.com/agent-integrations.md) was captured from the provided local raw fetch at `results/formal-v1/sources/agent-integrations.md`. Its “Limitations” section states: “Reasoning tokens and the final answer share the output budget. Selecting `max` effort does not increase that budget.” It also advises increasing output budget within the model limit if `finish_reason: length` occurs.

Captured-source SHA-256: `b029b753fa13c6f8957e7212367bb0710ccf11c0e75fac2d4c36209a7c8fdaee`. The fetch wrapper’s fullContent source capture SHA-256: `cfc6cc84aa5a3ea49b3f45607f0aa0eec37888736e63f4666dbbae404ed9a7e4`.

The local captured LithosAI OpenAPI schema is retained at `results/formal-v1/sources/openapi-capture.log` (SHA-256 `e2e767425b22d81ec863e0cc69810493c267ab1f36a02bde0a1a5ee87e7d807d`). It exposes nullable `max_tokens`, `max_completion_tokens`, and `reasoning_effort`; it does not itself define their accounting semantics.

## Interpretation and limitation

The documentation explicitly establishes a shared output budget at the product level. Applying that statement to the Chat Completions request’s configured output cap (`max_tokens`; with `max_completion_tokens` as the corresponding schema alternative) is an explicit API/schema mapping assumption. Therefore this flag records a documented basis sufficient to preregister capped formal runs, **not** empirical validation that this exact model/provider route enforces the cap, nor a guarantee about billing/accounting beyond the quoted statement. The shared-budget statement concerns output/reasoning token budget; it does not certify invoice charges or that local `actual_usd` estimates equal provider charges. Pilot reports of `reasoning_tokens=0` are not evidence for this decision. Model identity remains an alias, not immutable weights/version.
