# Content evaluation experiment

Status: planning; no runnable application yet. Decisions recorded September 19, 2026.

Can JEV's typed atomic judgments reduce generative-review work while producing MCQ drafts of equal or better quality, without increasing final human review effort?

This standalone Python CLI experiment compares two workflows on the same freshly generated questions. Automated processing ends by creating internal drafts. Humans verify those drafts afterward and provide the benchmark's ground truth. Creating a draft does not approve it for learners.

Repository: `git@github.com:curisolve/content-evaluation-experiment.git`.
See [design.md](design.md) for engineering requirements. This README captures the agreed scope and tracks delivery; neither document describes an already implemented system.

## Selected subject

- **Subject:** Applying Ontario CMTO professional standards.
- **Audience:** Practising registered massage therapists (RMTs) and RMT students.
- **Format:** Four-option, single-best-answer MCQs, with an answer key, rationale, source references, and recorded difficulty/audience.
- **Objective:** Recognize and apply professional obligations in realistic practice scenarios.
- **Authority:** [CMTO Standards of Practice and Code of Ethics](https://www.cmto.com/rmts/standards-of-practice-and-code-of-ethics/), with a frozen source inventory recording URLs, retrieval dates, document versions/effective dates, and content hashes.
- **Initial scope:** Questions directly supported by selected standards, including consent, privacy, records, boundaries/draping, fees, conflicts of interest, and safety. Broader clinical efficacy, diagnosis, and legal interpretation require additional approved authorities.
- **Risks:** Incorrect obligations, omitted exceptions, outdated requirements, ambiguous answer keys, unsupported rationales, and misleading advice.

The feasibility review found enough breadth for a pilot and likely several hundred meaningful questions. This is a planning estimate, not evidence that JEV works. The reviewed CMTO pages displayed September 8, 2026 updates; verify effective-date guidance before freezing sources. Give both evaluation arms equivalent authoritative context instead of relying on model memory.

Review the draft [subject specification](subjects/cmto_v1.yaml), [source inventory](subjects/sources/cmto_v1.yaml), and [human-labeling guide](docs/human-labeling-v1.md) before rubric implementation. The source inventory is not yet frozen: effective dates and exact source snapshots/hashes remain to be resolved before generation. Keep subject-specific rules and prompts in configuration; application packages remain domain-neutral. Generate original synthetic scenarios, not copied question banks or real patient records.

## Agreed comparison and workflow

Generate each original MCQ once and use the same immutable input in both arms. Apply identical deterministic validation and equivalent source context. Hold reviewer model, prompts, revision limits, and other shared settings constant where possible.

| Stage | A: Without JEV | B: With JEV |
|---|---|---|
| Validate | Deterministic checks | Identical deterministic checks |
| Evaluate | Generative reviewer examines every valid MCQ | JEV makes atomic typed judgments on every valid MCQ |
| Route | Reviewer identifies whether revision is needed | Clean, confident MCQs go directly to draft; weak, uncertain, critical-failure, or near-boundary items go to the generative reviewer |
| Revise | Apply policy-controlled revisions when needed | Apply the same revision process when review is required |
| Create drafts | Save resulting MCQs as internal drafts | Save resulting MCQs as internal drafts |
| Verify | Humans review drafts at the end | Humans review drafts at the end |

High confidence alone never means high quality. Direct-to-draft routing requires passing quality checks, sufficient confidence, and no critical defects or unresolved uncertainty. JEV generates neither explanations nor rewrites. Record its scores for a secondary evaluator-only analysis; the primary comparison is the two end-to-end workflows above.

In the first CLI milestone, publishing a draft means storing an internal draft record and exporting a review batch. External publishing-platform integration and learner-facing publication are outside this milestone.

### Revisions, validation, and failures

- Preserve original candidates, all evaluations, and every revision as append-only records linked by candidate family and arm. Never replace the original with a rewrite.
- Revalidate revisions. Bound repair/review attempts and account for their cost and latency; unresolved issues remain visible on drafts needing attention.
- Structurally invalid content must be repaired before entering the ordinary draft set. Retain unrepaired records in an attention queue/export and include them in failure totals.
- Provider failure is an error event, never a low quality score or an implicit pass. Structurally valid content can still reach a draft needing human attention when a provider is unavailable.
- Only humans assign final benchmark labels: acceptable as-is, revisable, or rejectable, plus dimension/defect labels. Record post-edit acceptance separately from the initial verdict.

## Benchmark method

1. **Pilot: approximately 60 original MCQs.** Check source coverage, scenario diversity, labeling consistency, and end-to-end feasibility before scaling.
2. **Main benchmark: provisionally 600 original MCQs.** Mix ordinary generation with a separately reported challenge set containing controlled single-defect mutations and polished but incorrect questions. This is a planning target, not a statistically validated sample size; two arms may produce up to twice as many draft outputs to assess.
3. **Human labeling after draft creation.** Blind reviewers to arm, evaluator scores, and intended-flaw metadata. Randomize presentation and avoid showing related variants together. Use qualified reviewers, double-label a meaningful subset, and adjudicate disagreements. Measure review time and edits.
4. **Calibration before held-out evaluation.** Review pilot/development drafts first, tune on development labels, and freeze the rubric, prompts, models, policy, and safety gates before evaluating the held-out test set. Human verification remains last within each batch.
5. **Prevent leakage.** Freeze development/validation/test manifests before tuning. Keep originals, mutations, and near-duplicate scenario families in the same split. Do not expose intended flaws to evaluators or human labelers. Audit coverage by requirement so repeated wording does not masquerade as independent evidence.
6. **Preserve evaluator ground truth.** Final draft labels measure workflow outcomes. To assess JEV on originals that were later revised, also label preserved originals in the final blinded review stage; do not apply a revision's label to its original.
7. **Report distinct populations.** Ordinary-generation results estimate operational routing savings; defect-enriched challenge results test detection. Do not pool them into an implied real-world prevalence estimate.

Record deterministic seeds and exact prompt/model metadata. Live model generation may still vary; frozen inputs and recorded/fake responses support exact replay. Any later tuning after inspecting test results requires a fresh held-out set for a new confirmatory claim.

At an assumed 3–5 minutes per reviewed item, 600 items alone take 30–50 reviewer hours. Two-arm outputs, preserved originals, second reviews, and adjudication increase that estimate; use measured pilot effort to budget the main study.

## Measures and adoption decision

Compare arms on the same candidate families and report sample counts and uncertainty intervals, accounting for related variants.

| Measure | What it answers |
|---|---|
| Acceptance without edits; revision and rejection rates | Are the final drafts useful? |
| Critical defects remaining in drafts | Does either workflow deliver unacceptable content? |
| Human time and editing effort | Does saved model work create extra human work? |
| Generative-review calls avoided | How much review does JEV eliminate? |
| Total provider cost and p50/p95 latency | Is the complete workflow more efficient, including retries and repairs? |
| Unacceptable originals routed directly to draft | Does selective routing miss defects? Report both missed-rejected / all-rejected and rejected-direct / all-direct counts and rates. |
| Per-defect recall, dimension agreement, confusion matrices, probability calibration | How well do JEV's atomic judgments match human labels on the evaluated version? |
| Route proportions, failures, and repeated-run stability | Is the workflow reliable and consistent? |

Track safety-critical defects separately from other quality defects and report by topic/audience where sample sizes permit. Define thresholds, acceptable quality differences, and minimum critical-defect counts using the subject risks and pilot evidence before the held-out run. Adopt only if documented safety gates pass, generative-review work decreases, and human effort does not increase. The conclusion may be adopt, revise, reject, or insufficient evidence.

## Engineering boundaries

Use Python, `uv`, Pydantic v2, Typer, SQLite, pytest, ruff, and a static type checker. The existing project specifies Python >=3.14 and `typesafe-sdk`; verify compatibility before fixing runtime/provider versions. Isolate SDKs behind local protocols, include fake adapters, and keep default tests credential-free.

Version subject specifications, schemas, prompts, rubrics, policies, and source inventories. Persist append-only runs with input hashes, exact returned model identifiers, normalized results, raw/redacted references, usage, cost, latency, retries, and errors. Support dry runs, resumability, deterministic selection, bounded retries, provider-specific limits, and JSON command output. Keep secrets out of Git and reports.

No other project's code, prompts, schemas, datasets, or history are dependencies. No web UI, automatic learner-facing approval, model training, or production publishing is included in the first milestone.

## Delivery tracker

Update this table as work progresses, linking verification evidence or artifacts before marking a milestone done.

| Milestone | Status | Completion evidence / next action |
|---|---|---|
| Review design and development configuration | Done | Requirements reviewed; worktree-only development confirmed. |
| Assess subject and agree workflow | Done | CMTO/RMT MCQs selected; two-arm draft-first comparison recorded above. |
| Establish repository and development worktree | Done | Local main initialized from existing project files; origin configured; `docs/experiment-plan` worktree created. |
| Capture plan | Done | README and aligned design; application remains unimplemented. |
| Prepare versioned subject and source inventory | Done | Draft subject, seven-topic inventory, proposed 60-item coverage, and human-labeling guide linked above. |
| Approve subject and freeze sources | Owner review / pending freeze | Confirm draft criteria and pilot allocation; resolve effective dates and capture source snapshots/hashes before generation. |
| Scaffold CLI and quality checks | Pending | README usage, environment example, locked dependencies, lint/type checks, tests, and CI. |
| Define contracts and append-only storage | Pending | Candidate revisions, runs, sources, arm lineage, drafts, labels, events, and manifests. |
| Build fake-provider workflow | Pending | Both arms produce review exports; error/resume and deterministic replay checks pass. |
| Add subject generation, rubric, and real adapters | Pending | Grounded generation, deterministic rules, atomic rubric, reviewer/revision adapter, polarity and failure tests. |
| Run and label pilot | Pending | About 60 original questions; blinded review, adjudication, coverage and effort assessment. |
| Freeze main benchmark and routing policy | Pending | Split manifests, development calibration, safety gates, sample-size justification, frozen configuration. |
| Run held-out comparison and final human review | Pending | Paired arm results, complete labels, human effort, costs, errors, and stability measurements. |
| Report and adoption decision | Pending | Markdown/JSON reports, reproducible manifest/replay, standalone setup verified; stop at evidence-based decision. |

## Local development configuration

Follow `/Users/abtin/work/AGENTS.md`: `projects/worksync/content-evaluation-experiment` stays on clean `main`; work happens on separate branches under `projects/worktrees/content-evaluation-experiment/`; Git metadata stays machine-local under `projects/gitstate/`. Do not synchronize metadata or active worktrees.

Current documentation worktree: `/Users/abtin/work/projects/worktrees/content-evaluation-experiment/docs-plan`, branch `docs/experiment-plan`. This path is a local workspace detail, not a requirement for someone cloning the standalone repository elsewhere.
