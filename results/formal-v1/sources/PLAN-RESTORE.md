# Reconstructing and verifying the frozen plan

The distributable plan uses `plan/tasks.jsonl.gz`. It was created with gzip mtime set to zero; `plan/tasks.jsonl` remains intact locally and was not removed or modified. To restore the canonical sibling needed by the repository planner:

```sh
gzip -dc results/formal-v1/plan/tasks.jsonl.gz > results/formal-v1/plan/tasks.jsonl
python - <<'PY'
from bench import verify_plan
manifest, tasks = verify_plan('results/formal-v1/plan')
print(len(tasks), manifest['tasks_sha256'])
PY
```

Run from the repository root with Python available. The first command writes/replaces the reconstructed uncompressed sibling, so on machines where that path may already contain data, verify the destination first or choose a fresh copy of the plan directory. `verify_plan` checks the manifest digest, task count, and semantic digest (SHA-256 over newline-joined canonical JSON rows). This is separate from the raw-byte SHA-256 of the JSONL file and from the gzip archive SHA-256; all three are recorded in `PREREGISTRATION.md`.

The checked archive is 7,922,465 bytes; the original JSONL is 169,438,490 bytes. Decompressing the retained archive was streamed and compared byte-for-byte against the original local file, with identical raw-byte SHA-256 `3c1b496b213a15dd9553993a657fcd9d86d035d8cbd0e9d27a24d25748c4f62a`. Manifest and tasks were verified locally without executing any benchmark requests.
