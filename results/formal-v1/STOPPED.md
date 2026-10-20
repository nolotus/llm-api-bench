# Run Termination Record: Formal-v1 (lithos-formal-v1-20261020-a)

## 1. Executive Summary & Termination Reason

- **Task Identifier**: `ptask26635`
- **Run Identifier**: `lithos-formal-v1-20261020-a`
- **Stopped Reason**: `scope_changed_to_three_tier_comparison`
- **Termination Mechanism**: Process signaled via `SIGTERM` (graceful termination of finite run by user command).
- **Vendor Status**: **No provider outage or protocol failure**. LithosAI API was responding normally with zero protocol errors.
- **Root Cause of Termination**: The user requested a scope adjustment to conduct a three-tier comparison across **Base**, **Fast**, and **Ultra** tiers. Consequently, this standalone single-tier formal run was halted early to avoid wasteful expenditure and ensure all comparative tiers are benchmarked under a unified, independently preregistered experimental protocol.
- **Completion Capsule Absence**: Because the process was halted externally via `SIGTERM`, no normal task-completion capsule or `execution-status` file was emitted. The run is formally categorized as **stopped_incomplete** (931/1200 planned formal tasks executed). It must not be reported as a full 1200-task completion.
- **Timestamps**:
  - **Last Recorded Task (UTC)**: `2026-10-20T04:49:02.513944+00:00`
  - **Archived Timestamp (UTC)**: `2026-10-20T04:52:00Z` *(Archived timestamp generated via system clock `date -u`; exact SIGTERM time is not artificially fabricated)*.

---

## 2. Shared Ledger & Budget Verification

Direct audit of shared budget ledger (`results/lithos-budget.jsonl`) and execution records (`results/lithos-budget.jsonl.records.jsonl`) demonstrates full mathematical consistency with zero unverified holds.

| Metric | Value | Audit Status |
| :--- | :--- | :--- |
| **Initial Budget Cap** | $15.000000000 USD | Exact matching `init` record |
| **Total Conservative Settle** | $0.452329872 USD | Exact matching ledger sum |
| **Remaining Budget** | $14.547670128 USD | Exact `15.0 - total_settled` |
| **Pilot Phase Conservative Settle** | $0.010909584 USD | 23 pilot requests |
| **Formal Phase Conservative Settle** | $0.441420288 USD | 931 formal requests |
| **Ledger Reserve Transactions** | 954 | Exact matching 954 total requests |
| **Ledger Settle Transactions** | 954 | Exact matching 954 total requests |
| **Pending Holds Count** | 0 | Zero outstanding reservations |
| **Unknown Holds Predicate** | `reserved_ids == settled_ids` | **True** (No unreleased or dangling holds) |

---

## 3. Protocol Success & Transport Statistics

- **Total Recorded Requests**: 954 (23 Pilot + 931 Formal)
- **Protocol Status**: 954 / 954 (`openai-compatible-chat-completions`)
- **Transport HTTP Status 200**: 954 / 954
- **Transport Errors**: 0
- **Protocol Success Rate**: 100.0% (all executed tasks completed with valid event streams and usage metrics)

---

## 4. Task Execution Breakdown & Group Truncation Audit

The planned formal execution consisted of 1200 tasks across 432 groups. Execution halted during group `lithos-formal-v1-20261020-a-4000-g00002`.

### 4.1 Token Target Breakdown

| Target Tokens | Planned Tasks | Executed Tasks | Unexecuted Tasks | Completion Rate |
| :--- | :--- | :--- | :--- | :--- |
| **1,000** | 480 | 368 | 112 | 76.67% |
| **4,000** | 240 | 188 | 52 | 78.33% |
| **16,000** | 240 | 190 | 50 | 79.17% |
| **32,000** | 240 | 185 | 55 | 77.08% |
| **Total** | **1200** | **931** | **269** | **77.58%** |

### 4.2 Group Truncation Analysis

- **Total Planned Groups**: 432
- **Fully Executed Groups**: 332
- **Unexecuted Groups**: 99 (all tasks omitted)
- **Partially Executed / Truncated Group**: Exactly 1 group
  - **Group ID**: `lithos-formal-v1-20261020-a-4000-g00002`
  - **Target Tokens**: 4,000
  - **Planned Repeats**: 5 (`r00`, `r01`, `r02`, `r03`, `r04`)
  - **Executed Repeats (3)**: `r00`, `r01`, `r02`
  - **Unexecuted Repeats (2)**: `r03`, `r04`
  - *Context*: This explains why the 4,000 token target executed exactly 188 tasks (37 completed groups $\times$ 5 tasks + 3 tasks from group `g00002` = 188 tasks), leaving 52 tasks unexecuted (2 from group `g00002` + 10 full unexecuted groups $\times$ 5 tasks = 52 tasks).

---

## 5. Experimental Integrity & Policy Directives

1. **No Backfilling / No Patching**: The missing 269 tasks will **not** be patched or backfilled into this run directory. Doing so would violate temporal consistency and introduce non-stationary network/provider conditions.
2. **No Conflation with Comparison Batches**: Data from this aborted formal-v1 run will not be merged with the upcoming simultaneous Base vs Fast vs Ultra comparison.
3. **Data Role (Supplementary Only)**: The 931 executed formal records and 23 pilot records are preserved strictly as supplementary baseline measurements.
4. **No Main Speed Leaderboard**: Because the run was truncated at 931/1200 tasks with uneven group representation, **no main speed leaderboard** will be generated from this run.
5. **Independent Preregistration**: The new multi-tier comparison batch will be independently specified, sized, and preregistered prior to execution.

---

## 6. Security & Credential Scanning

- **Credential Scan Clean**: `true`
- **Raw API Key Disclosure**: None. No API keys, authorization tokens, or environment credentials were read into or exported in this archive.
- **Source/Raw File Preservation**: Raw ledgers (`lithos-budget.jsonl`, `events.jsonl`, `records.jsonl`, `manifest.json`) and source directories were inspected in read-only mode and left unmodified.

---

## 7. Inventory of Unexecuted Plan Task IDs (269 Tasks)

All 269 unexecuted task IDs are cataloged below and stored in machine-readable JSON format in `results/formal-v1/STOPPED.json`.

<details>
<summary>Click to view all 269 unexecuted formal task request IDs</summary>

- `lithos-formal-v1-20261020-a-4000-g00002-long-r03`
- `lithos-formal-v1-20261020-a-4000-g00002-long-r04`
- `lithos-formal-v1-20261020-a-1000-g00002-long-r00`
- `lithos-formal-v1-20261020-a-1000-g00002-long-r01`
- `lithos-formal-v1-20261020-a-1000-g00002-long-r02`
- `lithos-formal-v1-20261020-a-1000-g00002-long-r03`
- `lithos-formal-v1-20261020-a-1000-g00002-long-r04`
- `lithos-formal-v1-20261020-a-throughput-00184-throughput-r00`
- `lithos-formal-v1-20261020-a-16000-g00030-long-r00`
- `lithos-formal-v1-20261020-a-16000-g00030-long-r01`
- `lithos-formal-v1-20261020-a-16000-g00030-long-r02`
- `lithos-formal-v1-20261020-a-16000-g00030-long-r03`
- `lithos-formal-v1-20261020-a-16000-g00030-long-r04`
- `lithos-formal-v1-20261020-a-throughput-00198-throughput-r00`
- `lithos-formal-v1-20261020-a-throughput-00238-throughput-r00`
- `lithos-formal-v1-20261020-a-throughput-00023-throughput-r00`
- `lithos-formal-v1-20261020-a-throughput-00040-throughput-r00`
- `lithos-formal-v1-20261020-a-16000-g00045-long-r00`
- `lithos-formal-v1-20261020-a-16000-g00045-long-r01`
- `lithos-formal-v1-20261020-a-16000-g00045-long-r02`
- `lithos-formal-v1-20261020-a-16000-g00045-long-r03`
- `lithos-formal-v1-20261020-a-16000-g00045-long-r04`
- `lithos-formal-v1-20261020-a-throughput-00053-throughput-r00`
- `lithos-formal-v1-20261020-a-1000-g00036-long-r00`
- `lithos-formal-v1-20261020-a-1000-g00036-long-r01`
- `lithos-formal-v1-20261020-a-1000-g00036-long-r02`
- `lithos-formal-v1-20261020-a-1000-g00036-long-r03`
- `lithos-formal-v1-20261020-a-1000-g00036-long-r04`
- `lithos-formal-v1-20261020-a-1000-g00023-long-r00`
- `lithos-formal-v1-20261020-a-1000-g00023-long-r01`
- `lithos-formal-v1-20261020-a-1000-g00023-long-r02`
- `lithos-formal-v1-20261020-a-1000-g00023-long-r03`
- `lithos-formal-v1-20261020-a-1000-g00023-long-r04`
- `lithos-formal-v1-20261020-a-throughput-00230-throughput-r00`
- `lithos-formal-v1-20261020-a-32000-g00026-long-r00`
- `lithos-formal-v1-20261020-a-32000-g00026-long-r01`
- `lithos-formal-v1-20261020-a-32000-g00026-long-r02`
- `lithos-formal-v1-20261020-a-32000-g00026-long-r03`
- `lithos-formal-v1-20261020-a-32000-g00026-long-r04`
- `lithos-formal-v1-20261020-a-throughput-00009-throughput-r00`
- `lithos-formal-v1-20261020-a-throughput-00012-throughput-r00`
- `lithos-formal-v1-20261020-a-1000-g00020-long-r00`
- `lithos-formal-v1-20261020-a-1000-g00020-long-r01`
- `lithos-formal-v1-20261020-a-1000-g00020-long-r02`
- `lithos-formal-v1-20261020-a-1000-g00020-long-r03`
- `lithos-formal-v1-20261020-a-1000-g00020-long-r04`
- `lithos-formal-v1-20261020-a-throughput-00152-throughput-r00`
- `lithos-formal-v1-20261020-a-16000-g00016-long-r00`
- `lithos-formal-v1-20261020-a-16000-g00016-long-r01`
- `lithos-formal-v1-20261020-a-16000-g00016-long-r02`
- `lithos-formal-v1-20261020-a-16000-g00016-long-r03`
- `lithos-formal-v1-20261020-a-16000-g00016-long-r04`
- `lithos-formal-v1-20261020-a-throughput-00122-throughput-r00`
- `lithos-formal-v1-20261020-a-throughput-00164-throughput-r00`
- `lithos-formal-v1-20261020-a-throughput-00066-throughput-r00`
- `lithos-formal-v1-20261020-a-throughput-00133-throughput-r00`
- `lithos-formal-v1-20261020-a-throughput-00084-throughput-r00`
- `lithos-formal-v1-20261020-a-throughput-00013-throughput-r00`
- `lithos-formal-v1-20261020-a-throughput-00090-throughput-r00`
- `lithos-formal-v1-20261020-a-32000-g00000-long-r00`
- `lithos-formal-v1-20261020-a-32000-g00000-long-r01`
- `lithos-formal-v1-20261020-a-32000-g00000-long-r02`
- `lithos-formal-v1-20261020-a-32000-g00000-long-r03`
- `lithos-formal-v1-20261020-a-32000-g00000-long-r04`
- `lithos-formal-v1-20261020-a-4000-g00024-long-r00`
- `lithos-formal-v1-20261020-a-4000-g00024-long-r01`
- `lithos-formal-v1-20261020-a-4000-g00024-long-r02`
- `lithos-formal-v1-20261020-a-4000-g00024-long-r03`
- `lithos-formal-v1-20261020-a-4000-g00024-long-r04`
- `lithos-formal-v1-20261020-a-throughput-00162-throughput-r00`
- `lithos-formal-v1-20261020-a-throughput-00011-throughput-r00`
- `lithos-formal-v1-20261020-a-throughput-00176-throughput-r00`
- `lithos-formal-v1-20261020-a-throughput-00155-throughput-r00`
- `lithos-formal-v1-20261020-a-16000-g00024-long-r00`
- `lithos-formal-v1-20261020-a-16000-g00024-long-r01`
- `lithos-formal-v1-20261020-a-16000-g00024-long-r02`
- `lithos-formal-v1-20261020-a-16000-g00024-long-r03`
- `lithos-formal-v1-20261020-a-16000-g00024-long-r04`
- `lithos-formal-v1-20261020-a-1000-g00012-long-r00`
- `lithos-formal-v1-20261020-a-1000-g00012-long-r01`
- `lithos-formal-v1-20261020-a-1000-g00012-long-r02`
- `lithos-formal-v1-20261020-a-1000-g00012-long-r03`
- `lithos-formal-v1-20261020-a-1000-g00012-long-r04`
- `lithos-formal-v1-20261020-a-32000-g00046-long-r00`
- `lithos-formal-v1-20261020-a-32000-g00046-long-r01`
- `lithos-formal-v1-20261020-a-32000-g00046-long-r02`
- `lithos-formal-v1-20261020-a-32000-g00046-long-r03`
- `lithos-formal-v1-20261020-a-32000-g00046-long-r04`
- `lithos-formal-v1-20261020-a-32000-g00005-long-r00`
- `lithos-formal-v1-20261020-a-32000-g00005-long-r01`
- `lithos-formal-v1-20261020-a-32000-g00005-long-r02`
- `lithos-formal-v1-20261020-a-32000-g00005-long-r03`
- `lithos-formal-v1-20261020-a-32000-g00005-long-r04`
- `lithos-formal-v1-20261020-a-throughput-00192-throughput-r00`
- `lithos-formal-v1-20261020-a-16000-g00017-long-r00`
- `lithos-formal-v1-20261020-a-16000-g00017-long-r01`
- `lithos-formal-v1-20261020-a-16000-g00017-long-r02`
- `lithos-formal-v1-20261020-a-16000-g00017-long-r03`
- `lithos-formal-v1-20261020-a-16000-g00017-long-r04`
- `lithos-formal-v1-20261020-a-throughput-00117-throughput-r00`
- `lithos-formal-v1-20261020-a-throughput-00099-throughput-r00`
- `lithos-formal-v1-20261020-a-32000-g00039-long-r00`
- `lithos-formal-v1-20261020-a-32000-g00039-long-r01`
- `lithos-formal-v1-20261020-a-32000-g00039-long-r02`
- `lithos-formal-v1-20261020-a-32000-g00039-long-r03`
- `lithos-formal-v1-20261020-a-32000-g00039-long-r04`
- `lithos-formal-v1-20261020-a-32000-g00021-long-r00`
- `lithos-formal-v1-20261020-a-32000-g00021-long-r01`
- `lithos-formal-v1-20261020-a-32000-g00021-long-r02`
- `lithos-formal-v1-20261020-a-32000-g00021-long-r03`
- `lithos-formal-v1-20261020-a-32000-g00021-long-r04`
- `lithos-formal-v1-20261020-a-1000-g00041-long-r00`
- `lithos-formal-v1-20261020-a-1000-g00041-long-r01`
- `lithos-formal-v1-20261020-a-1000-g00041-long-r02`
- `lithos-formal-v1-20261020-a-1000-g00041-long-r03`
- `lithos-formal-v1-20261020-a-1000-g00041-long-r04`
- `lithos-formal-v1-20261020-a-throughput-00203-throughput-r00`
- `lithos-formal-v1-20261020-a-16000-g00027-long-r00`
- `lithos-formal-v1-20261020-a-16000-g00027-long-r01`
- `lithos-formal-v1-20261020-a-16000-g00027-long-r02`
- `lithos-formal-v1-20261020-a-16000-g00027-long-r03`
- `lithos-formal-v1-20261020-a-16000-g00027-long-r04`
- `lithos-formal-v1-20261020-a-throughput-00042-throughput-r00`
- `lithos-formal-v1-20261020-a-throughput-00200-throughput-r00`
- `lithos-formal-v1-20261020-a-throughput-00067-throughput-r00`
- `lithos-formal-v1-20261020-a-throughput-00210-throughput-r00`
- `lithos-formal-v1-20261020-a-throughput-00106-throughput-r00`
- `lithos-formal-v1-20261020-a-throughput-00105-throughput-r00`
- `lithos-formal-v1-20261020-a-throughput-00197-throughput-r00`
- `lithos-formal-v1-20261020-a-32000-g00011-long-r00`
- `lithos-formal-v1-20261020-a-32000-g00011-long-r01`
- `lithos-formal-v1-20261020-a-32000-g00011-long-r02`
- `lithos-formal-v1-20261020-a-32000-g00011-long-r03`
- `lithos-formal-v1-20261020-a-32000-g00011-long-r04`
- `lithos-formal-v1-20261020-a-throughput-00222-throughput-r00`
- `lithos-formal-v1-20261020-a-32000-g00040-long-r00`
- `lithos-formal-v1-20261020-a-32000-g00040-long-r01`
- `lithos-formal-v1-20261020-a-32000-g00040-long-r02`
- `lithos-formal-v1-20261020-a-32000-g00040-long-r03`
- `lithos-formal-v1-20261020-a-32000-g00040-long-r04`
- `lithos-formal-v1-20261020-a-throughput-00218-throughput-r00`
- `lithos-formal-v1-20261020-a-throughput-00180-throughput-r00`
- `lithos-formal-v1-20261020-a-throughput-00173-throughput-r00`
- `lithos-formal-v1-20261020-a-throughput-00035-throughput-r00`
- `lithos-formal-v1-20261020-a-throughput-00159-throughput-r00`
- `lithos-formal-v1-20261020-a-4000-g00026-long-r00`
- `lithos-formal-v1-20261020-a-4000-g00026-long-r01`
- `lithos-formal-v1-20261020-a-4000-g00026-long-r02`
- `lithos-formal-v1-20261020-a-4000-g00026-long-r03`
- `lithos-formal-v1-20261020-a-4000-g00026-long-r04`
- `lithos-formal-v1-20261020-a-1000-g00035-long-r00`
- `lithos-formal-v1-20261020-a-1000-g00035-long-r01`
- `lithos-formal-v1-20261020-a-1000-g00035-long-r02`
- `lithos-formal-v1-20261020-a-1000-g00035-long-r03`
- `lithos-formal-v1-20261020-a-1000-g00035-long-r04`
- `lithos-formal-v1-20261020-a-throughput-00016-throughput-r00`
- `lithos-formal-v1-20261020-a-throughput-00046-throughput-r00`
- `lithos-formal-v1-20261020-a-4000-g00034-long-r00`
- `lithos-formal-v1-20261020-a-4000-g00034-long-r01`
- `lithos-formal-v1-20261020-a-4000-g00034-long-r02`
- `lithos-formal-v1-20261020-a-4000-g00034-long-r03`
- `lithos-formal-v1-20261020-a-4000-g00034-long-r04`
- `lithos-formal-v1-20261020-a-throughput-00191-throughput-r00`
- `lithos-formal-v1-20261020-a-throughput-00188-throughput-r00`
- `lithos-formal-v1-20261020-a-16000-g00014-long-r00`
- `lithos-formal-v1-20261020-a-16000-g00014-long-r01`
- `lithos-formal-v1-20261020-a-16000-g00014-long-r02`
- `lithos-formal-v1-20261020-a-16000-g00014-long-r03`
- `lithos-formal-v1-20261020-a-16000-g00014-long-r04`
- `lithos-formal-v1-20261020-a-4000-g00020-long-r00`
- `lithos-formal-v1-20261020-a-4000-g00020-long-r01`
- `lithos-formal-v1-20261020-a-4000-g00020-long-r02`
- `lithos-formal-v1-20261020-a-4000-g00020-long-r03`
- `lithos-formal-v1-20261020-a-4000-g00020-long-r04`
- `lithos-formal-v1-20261020-a-32000-g00004-long-r00`
- `lithos-formal-v1-20261020-a-32000-g00004-long-r01`
- `lithos-formal-v1-20261020-a-32000-g00004-long-r02`
- `lithos-formal-v1-20261020-a-32000-g00004-long-r03`
- `lithos-formal-v1-20261020-a-32000-g00004-long-r04`
- `lithos-formal-v1-20261020-a-4000-g00006-long-r00`
- `lithos-formal-v1-20261020-a-4000-g00006-long-r01`
- `lithos-formal-v1-20261020-a-4000-g00006-long-r02`
- `lithos-formal-v1-20261020-a-4000-g00006-long-r03`
- `lithos-formal-v1-20261020-a-4000-g00006-long-r04`
- `lithos-formal-v1-20261020-a-16000-g00019-long-r00`
- `lithos-formal-v1-20261020-a-16000-g00019-long-r01`
- `lithos-formal-v1-20261020-a-16000-g00019-long-r02`
- `lithos-formal-v1-20261020-a-16000-g00019-long-r03`
- `lithos-formal-v1-20261020-a-16000-g00019-long-r04`
- `lithos-formal-v1-20261020-a-4000-g00027-long-r00`
- `lithos-formal-v1-20261020-a-4000-g00027-long-r01`
- `lithos-formal-v1-20261020-a-4000-g00027-long-r02`
- `lithos-formal-v1-20261020-a-4000-g00027-long-r03`
- `lithos-formal-v1-20261020-a-4000-g00027-long-r04`
- `lithos-formal-v1-20261020-a-throughput-00078-throughput-r00`
- `lithos-formal-v1-20261020-a-throughput-00151-throughput-r00`
- `lithos-formal-v1-20261020-a-throughput-00130-throughput-r00`
- `lithos-formal-v1-20261020-a-4000-g00028-long-r00`
- `lithos-formal-v1-20261020-a-4000-g00028-long-r01`
- `lithos-formal-v1-20261020-a-4000-g00028-long-r02`
- `lithos-formal-v1-20261020-a-4000-g00028-long-r03`
- `lithos-formal-v1-20261020-a-4000-g00028-long-r04`
- `lithos-formal-v1-20261020-a-throughput-00092-throughput-r00`
- `lithos-formal-v1-20261020-a-16000-g00011-long-r00`
- `lithos-formal-v1-20261020-a-16000-g00011-long-r01`
- `lithos-formal-v1-20261020-a-16000-g00011-long-r02`
- `lithos-formal-v1-20261020-a-16000-g00011-long-r03`
- `lithos-formal-v1-20261020-a-16000-g00011-long-r04`
- `lithos-formal-v1-20261020-a-throughput-00026-throughput-r00`
- `lithos-formal-v1-20261020-a-16000-g00031-long-r00`
- `lithos-formal-v1-20261020-a-16000-g00031-long-r01`
- `lithos-formal-v1-20261020-a-16000-g00031-long-r02`
- `lithos-formal-v1-20261020-a-16000-g00031-long-r03`
- `lithos-formal-v1-20261020-a-16000-g00031-long-r04`
- `lithos-formal-v1-20261020-a-4000-g00008-long-r00`
- `lithos-formal-v1-20261020-a-4000-g00008-long-r01`
- `lithos-formal-v1-20261020-a-4000-g00008-long-r02`
- `lithos-formal-v1-20261020-a-4000-g00008-long-r03`
- `lithos-formal-v1-20261020-a-4000-g00008-long-r04`
- `lithos-formal-v1-20261020-a-1000-g00026-long-r00`
- `lithos-formal-v1-20261020-a-1000-g00026-long-r01`
- `lithos-formal-v1-20261020-a-1000-g00026-long-r02`
- `lithos-formal-v1-20261020-a-1000-g00026-long-r03`
- `lithos-formal-v1-20261020-a-1000-g00026-long-r04`
- `lithos-formal-v1-20261020-a-throughput-00068-throughput-r00`
- `lithos-formal-v1-20261020-a-4000-g00041-long-r00`
- `lithos-formal-v1-20261020-a-4000-g00041-long-r01`
- `lithos-formal-v1-20261020-a-4000-g00041-long-r02`
- `lithos-formal-v1-20261020-a-4000-g00041-long-r03`
- `lithos-formal-v1-20261020-a-4000-g00041-long-r04`
- `lithos-formal-v1-20261020-a-1000-g00004-long-r00`
- `lithos-formal-v1-20261020-a-1000-g00004-long-r01`
- `lithos-formal-v1-20261020-a-1000-g00004-long-r02`
- `lithos-formal-v1-20261020-a-1000-g00004-long-r03`
- `lithos-formal-v1-20261020-a-1000-g00004-long-r04`
- `lithos-formal-v1-20261020-a-32000-g00018-long-r00`
- `lithos-formal-v1-20261020-a-32000-g00018-long-r01`
- `lithos-formal-v1-20261020-a-32000-g00018-long-r02`
- `lithos-formal-v1-20261020-a-32000-g00018-long-r03`
- `lithos-formal-v1-20261020-a-32000-g00018-long-r04`
- `lithos-formal-v1-20261020-a-4000-g00010-long-r00`
- `lithos-formal-v1-20261020-a-4000-g00010-long-r01`
- `lithos-formal-v1-20261020-a-4000-g00010-long-r02`
- `lithos-formal-v1-20261020-a-4000-g00010-long-r03`
- `lithos-formal-v1-20261020-a-4000-g00010-long-r04`
- `lithos-formal-v1-20261020-a-throughput-00061-throughput-r00`
- `lithos-formal-v1-20261020-a-throughput-00215-throughput-r00`
- `lithos-formal-v1-20261020-a-throughput-00236-throughput-r00`
- `lithos-formal-v1-20261020-a-32000-g00007-long-r00`
- `lithos-formal-v1-20261020-a-32000-g00007-long-r01`
- `lithos-formal-v1-20261020-a-32000-g00007-long-r02`
- `lithos-formal-v1-20261020-a-32000-g00007-long-r03`
- `lithos-formal-v1-20261020-a-32000-g00007-long-r04`
- `lithos-formal-v1-20261020-a-throughput-00054-throughput-r00`
- `lithos-formal-v1-20261020-a-1000-g00027-long-r00`
- `lithos-formal-v1-20261020-a-1000-g00027-long-r01`
- `lithos-formal-v1-20261020-a-1000-g00027-long-r02`
- `lithos-formal-v1-20261020-a-1000-g00027-long-r03`
- `lithos-formal-v1-20261020-a-1000-g00027-long-r04`
- `lithos-formal-v1-20261020-a-1000-g00040-long-r00`
- `lithos-formal-v1-20261020-a-1000-g00040-long-r01`
- `lithos-formal-v1-20261020-a-1000-g00040-long-r02`
- `lithos-formal-v1-20261020-a-1000-g00040-long-r03`
- `lithos-formal-v1-20261020-a-1000-g00040-long-r04`
- `lithos-formal-v1-20261020-a-throughput-00226-throughput-r00`
- `lithos-formal-v1-20261020-a-throughput-00141-throughput-r00`
- `lithos-formal-v1-20261020-a-throughput-00189-throughput-r00`
- `lithos-formal-v1-20261020-a-throughput-00043-throughput-r00`
- `lithos-formal-v1-20261020-a-throughput-00204-throughput-r00`

</details>
