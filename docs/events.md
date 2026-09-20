# Durable events and replay

Status: target contract. The initial implementation supplies a SQLite event journal, hash-verified JSONL replay, attempt accounting, and resume; remaining work is listed in the [development guide](development.md). This document also specifies capabilities not yet implemented.

Capture every application-observable operation, attempt, decision, and state transition from run creation through completion, cancellation, or failure. This includes generation, validation, both evaluator arms, quality routing, duplicate detection, coverage selection, exports, audits, and reporting. Provider-internal computation is not observable; token streaming is optional and cannot be required for correct replay.

## Envelope and persistence

Each event contains `event_id`, `event_schema_version`, `event_type`, `run_id`, strictly increasing run-local `sequence`, UTC occurrence/persistence timestamps, elapsed monotonic time within a process session, `session_id`, optional `arm`, `candidate_id`, `family_id`, `operation_id`, `attempt_id`, parent/causation IDs, and a typed payload. Include configuration/input/artifact hashes or immutable references where relevant. Record explicit reason codes, not only free-form messages.

A single durable sequence reflects commit order, not presumed provider completion order. Allocate it transactionally in SQLite. Persist state transitions and their events in the same transaction; a successful state change without its event is a correctness failure. Record a durable intent before an external call and its result after return. On restart, unresolved intents become recovery events and remain unknown until reconciled; do not invent completion or zero cost.

The event journal is append-only. Corrections and late usage updates are new events that reference prior ones. Large candidates, responses, source snapshots, and exports live as immutable artifacts with hashes; events reference them. Keep artifact retention sufficient for replay. Never put credentials or authorization headers in the journal; scrub provider errors and raw payload references before export.

Required event writes must not be dropped to keep the pipeline running faster. Fail/pause with an explicit recoverable error when durable recording is unavailable. UI subscribers may lag or disconnect without affecting execution: they resume from their last sequence. Do not make a TUI process the source of truth.

## Event families

| Family | Required examples and payload evidence |
|---|---|
| Run | created, started, resumed, stop_requested, completed, cancelled, failed; manifest and stop reason |
| Operation | queued, started, completed, failed, skipped; stage, inputs/outputs and dependencies |
| Provider attempt | started, succeeded, failed, retry_scheduled, recovery_unknown; provider/model, timings, error category and backoff |
| Candidate | generated, validation_passed, validation_failed; immutable artifact and failed rule IDs |
| Evaluation | completed, unresolved; check results/reference, uncertainties and critical failures |
| Decision | quality_passed, quality_withheld; policy and evidence/reason IDs |
| Diversity | exact_duplicate, similarity_measured, group_assigned, representative_selected, excluded; scores, method and immutable evidence |
| Coverage | selection_added, selection_excluded, target_reached, gap_recorded; before/after projection inputs and target version |
| Accounting | usage_recorded, cost_estimated, cost_corrected, budget_reached; units, currency, price version, scope and completeness |
| Artifact | approval_exported, audit_exported, report_created; hash, mapping version and count |
| Human audit | label_imported, adjudication_recorded; immutable label reference and supersession links |

Operation/attempt identities must let projections avoid counting the same provider success twice when multiple event families describe it. Each queued operation has a terminal outcome or an explicit outstanding/unknown state. Capture necessary similarity/selection evidence without logging arbitrary internal loop iterations.

## Token and cost accounting

Record usage for every provider attempt in both arms, including generation and semantic filtering. Preserve the provider's original usage object and a normalized representation with:

- Input and output token counts; cache-read and cache-write counts, including cache-duration categories where priced differently; reasoning-token counts when exposed.
- Explicit semantics for totals and subsets. Provider input counters differ; cached tokens may already be included in a total or reported separately. Reasoning tokens may already be included in output. Never sum overlapping counters into a bill twice.
- Provider, endpoint/gateway, request ID, requested and returned model, service tier, batch/caching/reasoning settings, region where relevant, attempt identity and timing.
- Usage provenance (`provider_reported`, `estimated`, or `unknown`) and field availability. An unavailable breakdown is null/unknown, not zero. Failed/timed-out attempts may still incur charges.
- Cost currency, pricing-table ID/version, source URL and retrieval/effective date, applicable billable units/rates and modifiers, and estimate completeness. Use decimal arithmetic; round for display only.

Calculate standard-price cost as the sum of nonoverlapping billable quantities times their applicable rates, plus any documented fees. Model-specific adapters define these quantities from provider usage. Snapshot rates before a run; never silently reprice historical results from a live website. Store later actual billing, discounts, credits, and corrections separately with provenance and links to the estimate. If only aggregate billing is available, label its allocation instead of claiming per-request actual charges.

Sum across all attempts, including retries and failed calls with known charges. Unknown charges remain visible. Distinguish per-arm evaluation cost, shared generation/selection cost, hypothetical standalone pipeline cost for each arm, and the actual combined experiment bill. A zero selected count makes cost per selected item undefined, not zero. A missed target is reported with its incurred spending and elapsed time.

Report evaluation dollars per 1,000 attempted MCQs, pipeline dollars per selected nonredundant MCQ, and cost/time to target alongside audited quality and coverage. Include cold/warm cache behavior; keep batch processing separate from synchronous latency comparisons. Different tokenizers mean equal source text need not yield equal token counts. Do not infer a savings ratio from token prices alone.

Pricing references to snapshot during adapter setup: [OpenAI](https://developers.openai.com/api/docs/pricing), [Anthropic](https://platform.claude.com/docs/en/about-claude/pricing), and [TypeSafe](https://typesafe.ai/blog/introducing-system-one-models-and-jev). These links are discovery sources, not pinned rate cards. Confirm the actual endpoint's billing and usage schema before live runs.

Accounting tests must cover provider-specific cache totals, reasoning subsets, missing usage, retried calls, rate versions, decimal precision, late corrections, and reconciliation of shared versus per-arm costs. Replay reproduces both token counters and cost estimates without fetching current prices.

## Replay and dashboard

Export the complete journal as versioned JSONL plus a manifest of referenced artifacts. A reducer consumes events in sequence and reconstructs counters, candidate locations, queues, decisions, selected sets, coverage, usage, cost, and outstanding work without calling providers. Reducers declare supported schema versions; reject unsupported events rather than silently skipping state changes. Snapshot projections are an optimization only, validated against replay from sequence one.

Animation uses recorded elapsed intervals within a session; process restarts and clock changes are explicit boundaries. Support pause, step, speed control and seek in the future TUI. Replay speed never changes measured latency or throughput. Keep the live and replay reducers identical and versioned.

The dashboard should show:

- Shared generation/validation feeding two evaluator lanes, then quality and diversity selection.
- Generated, invalid, evaluated, passed, withheld, unresolved, duplicate-excluded and selected counts, with clear denominators.
- Per-arm elapsed time, throughput, p50/p95 latency, retries, spend, budget remaining and unknown-cost warnings.
- Per-provider input/output tokens, cache reads/writes, available reasoning breakdown, and measured versus estimated usage; standard-price estimates separate from actual charges.
- Coverage achieved versus target and remaining gaps; selected representatives and duplicate groups.
- Live rubric-pass yield; independently audited quality and critical escapes only after labels arrive, with sample sizes.

Minimum verification: live projections equal replayed projections; resume introduces no duplicate logical work/counts; concurrent completions retain a total event order; a crash between intent and response is visible; cancellation retains partial results; cost corrections recompute totals; exported events/artifacts reproduce the report without network access.
