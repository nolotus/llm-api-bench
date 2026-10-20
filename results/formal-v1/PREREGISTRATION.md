# Formal benchmark v1 — preregistration (plan only)

**Status:** preregistered plan artifact; not executed. No provider API call was made in preparing this plan. The current authorized task prepares artifacts only; the parent may proceed with the separately authorized review/publication step after this handoff. Record the published revision in the runner's preregistered-revision field before formal execution.

## Scope and frozen design

- Provider/model alias: LithosAI `deepseek-ai/DeepSeek-V4.1-Flash`; alias verification does not establish immutable model weights/version.
- API protocol: OpenAI-compatible Chat Completions; prices snapshot USD per million tokens: input **$0.15**, cached input **$0.003**, output **$0.60**. Prices are the configured snapshot and must be rechecked before execution; no claim that provider billing exactly matches client accounting.
- Synthetic prompt target sizes: 1,000 / 4,000 / 16,000 / 32,000 tokens (these are generation-sizing targets, not tokenizer-verified exact prompt lengths). 48 independent prefix groups per size, five ordered long repeats per group; 240 throughput requests at target 1,000/output cap 512. Long requests use output cap 32. Total **1,200 planned requests**: 960 long + 240 throughput. Group order is seeded/shuffled; repeat index strictly increases within each group.
- Run ID `lithos-formal-v1-20261020-a`; seed `20261020`; bytes-per-token sizing assumption `6.5`; concurrency 1; no retries. Runner imposes at least two seconds between requests. Stop on any usage-bound violation, budget hold failure, three failures, or provider rate limit; do not retry ambiguous requests.
- Planned upper cost in the frozen manifest is **$13.49742075**. Shared pilot+formal ledger cap remains **$15.00**. Pilot completed requests' locally computed conservative accounting amount in the ledger: **$0.010909584** (23 completed pilot records summed from `actual_usd`; this is not a confirmed provider invoice/actual charge). Arithmetic remaining from the local $15 ledger cap after this amount is **$14.989090416**. Formal upper bound plus this local pilot accounting amount is **$13.508330334**, below the $15 ledger cap by $1.491669666; none of these figures guarantees provider billing. The planner caps formal plan size at 90% of its $15 budget ($13.50); its planned $13.49742075 is just below this threshold. The planner's sizing threshold does not itself subtract pilot spend, so the shared-ledger reservation remains the runtime authority. Execution still must use the shared $15 ledger and stop if reservation is refused. Cost estimates depend on prompt-byte/token and provider usage assumptions; this is not a provider invoice guarantee.
- Estimated duration: at least 40 minutes from the fixed two-second inter-request delay alone (1,200 requests); actual service time/network delays add to this. Pilot observations are not a reliable duration guarantee. Run in one continuous session if practical; execution region is **unknown/not controlled** and must be recorded if available.
- Latency: collect client-observed timing fields. Frozen `analysis.py` computes p95 only with at least 100 observations and 100 distinct groups, and p99 only with at least 1,000 distinct groups. Each long size/reuse stratum (48 groups, 240 observations) therefore has p95/p99 **null**; throughput has p95 eligible with 240 independent request groups, but p99 **null**. These are reporting eligibility rules, not acceptance/stability guarantees. Client receive-time is not server token-generation time. Record missing usage/cache fields as unknown, never as zero. Results describe this run/sample only; no broad population claim.

## Reasoning-cap evidence and caveat

`reasoning_cap_verified=true` is set on a documentation basis for this preregistration: official LithosAI integration documentation says reasoning tokens and final answer share the output budget, and max effort does not increase it. The OpenAPI schema lists `max_tokens` / `max_completion_tokens`; mapping the product-level statement to these request fields remains an explicit schema/API interpretation assumption, not a model-specific pilot validation. Pilot `reasoning_tokens=0` is not evidence of the cap. The provider/model route's enforcement and billing are not empirically verified. See `CAP-EVIDENCE.md` and archived source files. Reassess this evidence if provider documentation, route, or request field changes.

## Frozen artifacts and integrity

- Plan: `plan/manifest.json` and the deterministic gzip distribution `plan/tasks.jsonl.gz`. The uncompressed `plan/tasks.jsonl` remains intact in the working tree for local verification; do not add it to GitHub (it is 169,438,490 bytes, above GitHub's 100 MB per-file limit). Restoring the exact canonical plan for `verify_plan` is described in `sources/PLAN-RESTORE.md`.
- Manifest SHA-256: `504c62cf2296810dd676c0f2d662109ed997c82db4330f2590a7c310de254935`.
- Tasks semantic digest from manifest (SHA-256 of newline-joined canonical JSON rows): `00d3bc5041d5a84c846ddd84e6123dda32de235c356d37ddc933b769109f4f2a`.
- Original `tasks.jsonl` raw-byte SHA-256: `3c1b496b213a15dd9553993a657fcd9d86d035d8cbd0e9d27a24d25748c4f62a`; restored gzip stream was byte-for-byte compared to it.
- Distribution `tasks.jsonl.gz` SHA-256: `3124357bc9af46788fcf6161b141142631c47a2a43553aa1d790a1842925100c`; 7,922,465 bytes (original 169,438,490 bytes).
- Provider config SHA-256 as frozen into plan: see manifest `config_sha256`; config flag's documentation basis and limitation appear above.
- Local archive timestamp (not asserted as source-fetch time): **2026-10-20T03:44:27Z**. Official docs raw local capture did not establish an exact retrieval timestamp.
- Any change to tasks, config, prices, cap semantics, or protocol requires a new reviewed preregistration/plan; do not mutate the frozen plan in place.

## Handoff

This preparation did not execute the plan. The parent can continue the already-authorized review/publication workflow; this section does not add a new authorization gate. Record the published revision in the run command before formal execution. No provider API request was made as part of this plan-preparation task.
