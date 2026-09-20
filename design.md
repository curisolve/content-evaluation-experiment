# Filter-first evaluation design

Status: engineering plan captured for implementation, September 20, 2026. No runnable implementation yet; subject/source approval and pilot calibration remain pending.

The [README](README.md) owns scope and delivery tracking. This design supersedes the earlier review/rewrite/draft comparison. The objective is inexpensive, fast verification and selection of a varied pool for downstream human approval. Neither automated rewriting nor human repair is part of the experiment.

## Architecture

Use a standalone Python CLI with domain-neutral modules for configuration, generation, validation, evaluation, selection, workflow, storage, and reporting. Keep subject-specific criteria and sources in versioned configuration. Provider SDKs sit behind local protocols; their response objects never enter domain models. Include fake providers and recorded-response replay.

SQLite stores immutable candidates, source manifests, evaluator attempts/results, decisions, selections, audit labels, and the event journal. A coordinator invokes generation once and evaluates the same valid candidates in two isolated arms. Arm A uses a structured generative judge; arm B uses JEV atomic typed judgments. A shared deterministic policy engine applies each arm's frozen calibrated policy. A shared diversity/coverage selector operates independently on each arm's passing set. Export selected originals without modifying their content.

See [architecture and flow](docs/architecture.md) and the editable [Excalidraw source](docs/architecture.excalidraw).

## Minimal contracts

- `Candidate`: immutable ID, family ID, cohort, subject/schema version, structured MCQ, audience, difficulty, topic and learning objective, source requirement IDs, source-pack hash, generation metadata and input hash.
- `ExperimentManifest`: input order and hashes, family/split assignments, seeds, source pack, prompt/rubric/policy/selector versions, requested models, concurrency/rate limits, budgets and selection/coverage targets.
- `ProviderAttempt`: operation and attempt IDs, candidate/arm links, requested and returned model, normalized input hash, timestamps, usage, latency, estimated/actual cost provenance, redacted raw-result reference, success or typed error.
- `Evaluation`: typed check IDs, normalized judgments, applicable confidence/uncertainty, critical failures, rubric version and attempt link. Higher normalized scores always mean better; missing/failed evaluations never become scores.
- `Decision`: pass, withhold, or unresolved; stable reason codes and evidence check IDs; exact policy version. Deterministic invalidity is a separate validation decision.
- `Selection`: selected or excluded, reason, duplicate representative/group and similarity evidence when applicable, coverage state, selector version and input ordering.
- `AuditLabel`: exact candidate version, reviewer qualifications/pseudonym, dimension labels, disposition, defects/severity, cited evidence, timing, and supersession/adjudication links.
- `Event`: the durable envelope and lifecycle described in [events.md](docs/events.md).

`ProviderAttempt` usage must follow the [token and cost accounting contract](docs/events.md#token-and-cost-accounting): retain raw reported usage plus normalized billing categories, exact provider/model/service configuration, a versioned rate card, and measured/estimated/unknown provenance. Include generation and semantic-provider calls, not just the evaluation arms. Preserve reasoning counts as a breakdown of output when applicable rather than billing them twice. Default comparisons use one fixed LLM model against JEV; compact structured outputs, cache policy, and any batch-mode variant are explicit manifest settings.

Store intended flaws separately from evaluator and reviewer packets. Never expose arm, score, route, cohort, or intended flaw in blinded audit exports. Use an opaque review ID mapping retained by the coordinator.

## Workflow and stopping

An immutable input is validated once. Invalid inputs are withheld and counted. Each valid input gets one logical evaluation per arm, with bounded transient retries. A successful evaluation becomes pass or withhold under that arm's policy; an unsuccessful or uncertain evaluation remains unresolved/withheld from selection. Only quality passes enter selection. Diversity exclusions do not imply a quality failure. Only selected originals enter the approval export.

Record all attempts and terminal outcomes, including rate limits, exhausted retries, timeouts, cancellation, budget exhaustion, and incomplete provider calls after a crash. A provider outage cannot turn an item into a pass. Resume completed logical work idempotently; do not claim exactly-once external billing when a provider response was lost. Record unknown usage/cost explicitly.

Use a fixed, shared pool and order for the paired study. Freeze per-provider concurrency and limits and disclose them. Measure actual arm elapsed time; do not add per-call latencies and label the sum wall time. Shared generation/validation costs and time are part of each hypothetical standalone deployment estimate, with the allocation documented. Report actual experiment spending separately.

An operational run can generate more bounded batches until quality/diversity targets or resource caps are reached. Defer adaptive generation in the first paired benchmark. Quality gates stay fixed even when coverage targets cannot be filled.

## Quality and redundancy

Derive atomic checks from the approved subject; deterministic validation remains authoritative for shape and mechanically provable rules. JEV produces typed judgments, never rewrites or narrative explanations. The generative baseline returns the same necessary decision fields, with model-specific calibration where needed. Fairness means equivalent criteria/context and disclosed settings, not pretending the evaluators use identical prompts or confidence scales.

Start with normalized exact fingerprints and one reproducible semantic method. Version normalization, embedding/model choice if used, similarity threshold, tie-breaking, and ordering. Preserve similarity edges and group membership: pairwise thresholds are not necessarily transitive. Choose and document a grouping algorithm before implementation. The same selector settings apply to both arms. Use stable ordering to choose representatives, and include learning-objective/requirement evidence in manual checks of suspected redundancy. Audit both exclusions and retained near-neighbors to estimate false merges and missed redundancy.

A candidate may be a valid quality pass yet contribute no new variety. Report quality passes, nonredundant selections, family counts, and coverage separately. Do not claim topic coverage proves semantic variety.

## Evidence and reporting

The development pilot labels the same 60 immutable inputs once and uses those labels for both arms. Independently double-label 15 stratified inputs. Pilot labels support tuning only. Keep source parents, mutations, and semantic near-duplicate families together when splitting; use fresh held-out families after freezing the configuration.

Audit all selected items when feasible. If larger runs require sampling, predeclare sampling strata and probabilities for selected and withheld items, preserve the sample manifest, and use weighted estimators. Selected-only audit supports selection quality, not missed-good yield or defect recall. Treat unresolved and missing labels explicitly. Report ordinary and challenge cohorts separately, with paired comparisons and family-aware uncertainty.

Reports include counts and denominators, quality/critical escapes, diverse yield and coverage, cost and time to target, cost per selected item, audited quality estimates, good items withheld, provider failure rates, cost completeness, and human audit effort. Do not divide spending by an unaudited count and call it cost per verified-good item. Freeze adoption gates and a justified held-out sample size after the pilot; insufficient evidence is a valid result.

## Verification and exclusions

Required tests cover schema validation, check polarity, routing uncertainty/errors, idempotent resume, immutable input sharing, selector determinism, blinding, accounting, atomic state/event persistence, cancellation/crash recovery, and identical projections from live events versus replay. Use temporary databases and fake/recorded adapters; live tests are opt-in with small budgets. Preserve seed and exact returned model metadata; live generation need not be deterministic.

No web UI, model training, external publication, automatic learner approval, rewriting, cross-project imports, or full TUI implementation in the first milestone. The event journal and replay contract are mandatory now so the TUI can be added without reconstructing lost history.
