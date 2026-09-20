# Offline CLI foundation

The CLI currently runs synthetic arithmetic fixtures through two fake evaluators. It tests orchestration and accounting, not JEV/LLM accuracy, CMTO content, or provider pricing. Both fake arms intentionally give the same judgments and use synthetic rates. No credentials or network calls are needed to run it after dependency installation.

Opt-in [real-provider smoke adapters](providers.md) are also available. They use the same toy fixtures with actual APIs; mocked tests verify contracts, but no account-specific live verification has been performed. The offline demo remains unchanged.

Use a development worktree, not the synchronized `worksync` checkout.

## Setup and run

```bash
uv sync --locked --python 3.14
uv run content-eval demo --dry-run
uv run content-eval demo --count 12 --target 5 --db runs/demo.sqlite
uv run content-eval runs --db runs/demo.sqlite
```

The demo prints JSON containing a `run_id`, per-arm counts, exact-duplicate exclusions, target gaps, token estimates, synthetic costs, attempt latency percentiles and observed session elapsed time. No audit labels exist yet, so audited quality is null. Actual provider spending is zero; synthetic cost estimates are clearly labeled. The same frozen input pool feeds both arms; invalid items never reach either evaluator.

Copy the run ID into these commands:

```bash
uv run content-eval report RUN_ID --db runs/demo.sqlite
uv run content-eval resume RUN_ID --db runs/demo.sqlite
uv run content-eval export-events RUN_ID runs/events.jsonl --db runs/demo.sqlite
uv run content-eval replay runs/events.jsonl
uv run content-eval export-approval RUN_ID runs/approval.json --arm llm --db runs/demo.sqlite
```

Exports refuse to overwrite existing files. The approval export preserves the selected original content and is explicitly marked `demo_only_not_approved`. JSONL includes all source text, frozen inputs, policies, synthetic rates and results needed for replay; no separate artifacts or database are needed. Export metadata itself is appended after the exported snapshot. Hash chaining detects accidental corruption, gaps and edits; it is not a signature against malicious rewriting of the entire journal.

To exercise provider failures:

```bash
uv run content-eval demo --count 6 --failure-mode transient
uv run content-eval demo --count 6 --failure-mode unavailable
```

Transient failures trigger at most two attempts per candidate/arm. The fake retry delay is zero. Missing usage/cost remains unknown; per-selected cost is null when accounting is incomplete. The current fake workload is bounded by `--count` (maximum 1,000), not dollar or time budgets.

Ctrl-C records cancellation. Use `runs` to find the ID and `resume` to continue. A completed run is a no-op on resume. A call interrupted after its durable intent is recorded as unknown and its candidate withheld in that arm; it is not silently retried or assumed free. Persisted successful calls are reused if interruption occurred before the later decision or selection. Original inputs are loaded from the journal rather than regenerated.

## Implementation boundaries

SQLite events are append-only and hash chained. State is derived from events, eliminating a second mutable state table. Each append uses a transaction, WAL and FULL synchronization. A nonblocking advisory file lock permits one coordinator per database on macOS/Linux. The implementation is not a distributed or Windows runner. Events contain UTC timestamps plus process-session monotonic offsets; replay uses their original values. Report and replay use the same reducer.

Pydantic contracts keep candidates, policies, usage, rates and evaluation results outside provider SDKs. Token input categories are disjoint, reasoning is a subset of output, and decimal cost calculation does not round until display. The generic inclusive-input constructor requires known disjoint cache categories. The live adapters additionally normalize provider-specific usage and retain raw responses. The optional `jev` SDK dependency is locked; the current adapters use direct HTTP so every request is observable without SDK retries.

Still required before a meaningful pilot:

- Approved/frozen CMTO sources; configuration-driven generation and atomic rubric; live verification of real adapters and recorded-response fixtures. Current tests use constructed response fixtures, not recorded live results.
- Semantic redundancy selection, audited duplicate decisions and coverage quotas. Current selection uses exact normalized stem/options fingerprints plus a count target; it does not establish semantic variety.
- Blinded audit packets, label import/adjudication, cohort-separated quality metrics and uncertainty intervals. Approval export is not a blinded audit export.
- Deadline/spend caps, per-provider concurrency/rate limits, real backoff, standalone-arm elapsed-time measurement and time-to-target reporting. Fake arms are interleaved; their latencies are not real-provider benchmarks.
- Richer typed event payload schemas, external artifact bundles, durable export intents/recovery, billing corrections/reconciliation, and complete coverage/stop events. Live adapters distinguish cache-duration pricing, but reconciliation against actual bills remains pending. Current exports record completion after writing; a crash in that gap can leave an unjournaled file, which is never overwritten automatically.
- A live TUI, animated replay controls, and human-readable benchmark report. Current commands return JSON and JSONL.

These limits are intentional and visible; successful fake execution is not evidence of quality or cost savings.

## Checks

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest
```

CI runs these checks on Python 3.14 with locked dependencies. Tests cover routing polarity/uncertainty, immutable shared inputs, deterministic generation, decimal/token accounting, retries, outages, interruption/resume, journal immutability, writer exclusion, corruption detection, unchanged exports, and equality of stored and replayed reports. Default tests are credential-free.
