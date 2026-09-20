# Content evaluation experiment

Status: runnable offline CLI foundation, September 20, 2026. Real provider adapters, subject/source approval, and pilot calibration remain pending.

How quickly and cheaply can we identify enough high-quality, varied MCQs to send for final human approval?

This standalone experiment compares a generative reviewer with JEV's typed atomic judgments as filters over the same fresh MCQs. Neither evaluator rewrites questions. A shared selection stage removes redundancy and maintains coverage. Selected items become an internal approval queue; problematic items are withheld, with no expectation that humans repair them. Human approval is downstream of the pipeline, not the experiment's product.

The evaluation must distinguish **rubric passes** from **independently verified quality**. A small blinded audit measures filter performance; it does not require approving or repairing the entire generated pool.

## Documents

- [Run the offline CLI and development checks](docs/development.md)

- [Engineering design](design.md)
- [Architecture and flow](docs/architecture.md), with an editable [Excalidraw diagram](docs/architecture.excalidraw)
- [Event and replay contract](docs/events.md)
- [Human audit guide](docs/human-labeling-v1.md)
- [Subject specification](subjects/cmto_v1.yaml)
- [Source inventory](subjects/sources/cmto_sources_v1.yaml)

The YAML files are complementary, not copies: the subject specification owns scope, format, quality criteria, and pilot allocation; the inventory owns source provenance and freezing. Their filenames now distinguish those roles. Application code remains domain-neutral.

## Smallest useful comparison

Generate each original once, preserve it, and supply both evaluators with the same frozen source context and quality criteria.

| Stage | A: Generative filter | B: JEV filter |
|---|---|---|
| Validate | Shared deterministic checks | Same checks on the same originals |
| Evaluate | Structured rubric judgments from a generative model | Atomic typed rubric judgments from JEV |
| Decide | Pass, withhold, or unresolved | Same decision semantics |
| Select | Shared diversity and coverage selector | Same selector and targets |
| Export | Original selected items for approval | Original selected items for approval |

No generative fallback, rewrite loop, repair loop, external publishing integration, or web UI in the first milestone. Failed schema validation withholds an item; provider errors remain unresolved. A pass requires the quality gates, not confidence alone. Near-boundary or uncertain judgments are withheld from the approval queue. The final thresholds are calibrated on development data and frozen before held-out evaluation.

The baseline returns structured judgments sufficient to apply its declared policy. Providers may have different score semantics: do not assume their confidence values are interchangeable. Freeze each arm's calibrated decision policy while keeping the quality criteria, sources, candidates, selection rules, and resource conditions comparable.

### Proposed development pilot

Keep the existing 60-item budget: 40 ordinary generated originals and 20 single-defect variants from ten of those originals. Preserve the seven-topic coverage, two audiences, and difficulty mix. This is a development pilot, not confirmatory evidence or 60 independent scenarios.

Audit all 60 immutable inputs once, blinded to both arms. Both arms evaluate unchanged versions, so the same human labels can assess both filters. No need to label two rewritten outputs or ask reviewers to edit. Independently double-label a stratified 25% sample (15 items); adjudicate disagreements and uncertainty. If qualified reviewers are unavailable, report proxy-only results and leave verified quality unestablished.

After the pilot, freeze policies and a fresh family-separated held-out batch sized using observed yields, disagreement, rare-defect counts, and the precision needed for a decision. Remove the provisional 600-item commitment. For a larger batch, audit selected items and a probability sample of withheld items with recorded inclusion probabilities; do not silently treat unaudited items as correct or estimate false-negative rates from the selected queue alone.

Keep ordinary-generation and defect-enriched challenge results separate. Ordinary items estimate operational yield and efficiency; challenge variants probe defect detection. Challenge items never contribute to production-like throughput claims.

### Enough quality and variety

Specify a target number of selected MCQs, topic/audience/difficulty coverage, a maximum redundancy rate, a spend cap, and a wall-time cap before each run. Values remain proposed until pilot evidence supports them. Generation runs in bounded batches and stops on a target or cap; record the stop reason and unfilled coverage cells.

Start with exact normalized-text deduplication plus one versioned semantic similarity method over stem and options. Preserve keys, rationales, source requirements, and learning objectives for review of suspected duplicates. Similar wording or a shared topic is not automatically redundancy; flag same-learning-point, interchangeable scenarios and audit a sample of duplicate decisions. Record all exclusions and their representative item. Family IDs prevent seeded mutation variants from masquerading as independent variety. A coverage gap must never relax the quality threshold.

For the paired comparison, use the same fixed input pool and order in both arms. Replay prefixes to compare time/cost to the selection target; an arm that fails to reach it is reported as such. Adaptive generation to fill gaps is a later operational feature, because it changes the inputs seen by each arm.

## Measures and decision

Primary measures are cost and elapsed time per selected nonredundant MCQ, audited acceptability of that selection, and topic/audience/difficulty coverage. Report both evaluator-only and full-pipeline costs, including generation, semantic filtering, retries, and failed calls. Shared costs are charged equally in each standalone-arm estimate, and counted once in the actual experiment bill.

Record provider-reported input, output, cache-read/cache-write, and reasoning tokens where available for every attempt in both arms, preserving provider-specific accounting semantics. Calculate costs using a frozen, dated price table for the exact model and service tier; keep actual billed charges and credits separate from standard-price estimates. Unknown usage is not zero. See the [token and cost contract](docs/events.md#token-and-cost-accounting).

Start with JEV versus one fixed LLM model, with the LLM adapter interchangeable between OpenAI and Anthropic. Require compact structured judgments rather than narrative explanations. Permit caching and record its configuration and measured effects; evaluate batch processing as a separate cost/latency configuration. Compare evaluation dollars per 1,000 attempted MCQs, full-pipeline dollars per selected nonredundant MCQ, and cost/elapsed time to target alongside audited quality and coverage. Token counts describe each provider's work; dollars and useful yield are the cross-provider comparison.

Also report:

- Selection yield and target attainment, exact and semantic exclusions, remaining coverage gaps.
- Critical-defect escapes and any-edit-needed rate among selected items, with denominators and uncertainty intervals.
- Good items withheld, per-defect detection, unresolved decisions, provider errors, and repeated-run variation.
- p50/p95 evaluation latency, end-to-end elapsed time, throughput, provider usage and cost completeness.
- Human audit minutes separately from downstream approval effort; no editing-time objective.

Do not equate selected count with verified-good count. Where sampling is used, label estimates as estimates and apply sampling weights; uncertainty must account for related families. Zero observed critical failures in a small audit is not proof of safety. Compare cost/time only alongside measured quality and diversity. The outcome can be adopt, revise, reject, or insufficient evidence.

## Events and TUI

Every application-observable operation and state transition must produce a durable, ordered event, including attempts, errors, retries, decisions, exclusions, export, cancellation, and stop reasons. This is a first-milestone requirement, not optional telemetry. See the [event contract](docs/events.md).

The first implementation provides the event journal, JSONL export, deterministic replay, and a textual/JSON report. A live TUI dashboard and animated replay are a subsequent presentation layer over those same events. The proposed dashboard shows both filter lanes, counters, cost, throughput, coverage, duplicate groups, and reasons items were withheld. Audited quality appears only when labels are available, clearly separated from live rubric passes.

## Boundaries and next steps

The foundation uses Python >=3.14, `uv`, Pydantic v2, Typer, SQLite, pytest, ruff, and mypy. Dependencies are locked; `typesafe-sdk` is an optional `jev` extra reserved for the real adapter. Use local provider protocols and fake adapters; default tests need no credentials. Generate synthetic scenarios only. Do not import another project's code, prompts, datasets, or history.

| Milestone | Status / next action |
|---|---|
| Project setup and original plan | Done; original draft-and-revise approach superseded by this filter-first proposal |
| Subject and source inventory | Drafts available; owner review and source freeze pending |
| Simplified experiment and event contract | Captured, including diagrams, token/cost accounting, and replay requirements; the initial implementation follows a documented subset |
| CLI, storage, fake filters, event replay | Initial slice implemented: `src/content_eval/`, `tests/test_foundation.py`, locked dependencies and CI. See [development guide](docs/development.md) for commands and remaining contract work. |
| Source freeze, rubric, real adapters, diversity selector | Pending; resolve source effective dates and snapshots before generation |
| Development pilot and blinded audit | Pending; proposed 60 inputs plus 15 independent second reviews |
| Frozen held-out evaluation and report | Pending; set sample size, targets, budgets, and quality gates from pilot evidence |
| Live TUI and animated replay | Follow-on; journal/replay compatibility required from the first milestone |

Follow `/Users/abtin/work/AGENTS.md`: `worksync/content-evaluation-experiment` stays on clean `main`; development occurs on separate branches under `projects/worktrees/content-evaluation-experiment/`. Git metadata and development worktrees remain machine-local. Use remote branches and commits to transfer development between laptop and desktop.
