# Generic content-generation evaluation experiment

Status: handoff and design guidelines  
Date: 2026-09-19

## Handoff

Build this as a new, standalone Python project. It must not import, copy, migrate, or depend on files, code, schemas, prompts, content, or history from any existing project. The experiment creates its own generated examples, fixtures, labels, configuration, and database.

The goal is to determine whether JEV can evaluate generated content reliably enough to route straightforward items directly to human review while sending weak or uncertain items to a generative reviewer for diagnosis. JEV makes typed, atomic judgments; it does not generate explanations or rewrites.

Before implementation, the owner must choose a **subject for generation**. Record it in a small subject specification containing:

- subject name and intended audience
- content format to generate
- learning or communication objective
- allowed and excluded scope
- difficulty levels, if relevant
- factual sources or authority standard
- safety or quality risks
- what makes an item acceptable, revisable, or rejectable

Do not invent a domain rubric before the subject is chosen. The subject specification is the source for the generator prompt, deterministic rules, evaluator rubric, and human-labeling guide.

The first milestone is an offline CLI experiment, not a production application. Stop after producing a benchmark report and make the adoption decision from evidence.

### Expected deliverables

1. A new repository with its own README, dependency lockfile, environment example, and CI checks.
2. A versioned subject specification and content schema.
3. A generator that creates a fresh synthetic benchmark pool for the selected subject.
4. Deterministic validation for rules that code can prove.
5. A versioned JEV rubric made of atomic typed questions.
6. A generative-reviewer adapter used as a comparison and optional remediation stage.
7. Fake provider adapters for unit and contract tests.
8. Append-only experiment storage.
9. A reproducible benchmark command and machine-readable manifest.
10. A Markdown and JSON report covering quality, calibration, routing, latency, cost, and disagreements.

### Completion criteria

The handoff is complete when another developer can clone only the new repository, choose or read its subject specification, configure provider keys, generate a fresh dataset, run all tests, reproduce the benchmark, and understand the result without access to any other repository.

## Design guidelines

### 1. Greenfield and domain-independent

- Use neutral names such as `content`, `candidate`, `dimension`, and `evaluation`; do not encode a particular organization, profession, exam, or subject in package names.
- Keep subject-specific material in versioned configuration and prompt files, not application code.
- Generate all experiment content inside the new project. Do not require an import command or a seed dataset from another system.
- Use public factual references where the chosen subject needs an authority source. Record source identifiers with generated items.
- Treat generated examples as untrusted until validated and reviewed.

### 2. Suggested stack and layout

Use Python 3.12+, `uv`, Pydantic v2, Typer, SQLite, `pytest`, `pytest-asyncio`, `ruff`, and a static type checker. Keep telemetry behind an internal interface. Avoid a web UI until the evaluation contract and routing policy are stable.

```text
content-evaluation-experiment/
├── pyproject.toml
├── uv.lock
├── README.md
├── .env.example
├── subjects/
│   └── selected_subject.yaml
├── rubrics/
│   └── subject_v1.yaml
├── policies/
│   └── shadow_v1.yaml
├── src/content_eval/
│   ├── cli.py
│   ├── config.py
│   ├── domain/
│   ├── generation/
│   ├── evaluation/
│   ├── policy/
│   ├── workflow/
│   ├── storage/
│   └── telemetry/
├── tests/
│   ├── unit/
│   ├── contract/
│   ├── integration/
│   └── fixtures/
└── experiments/
    ├── manifests/
    └── reports/
```

Provider implementations must satisfy local protocols. Provider SDK types must not leak into domain models, policy code, or tests.

### 3. Pipeline boundary

```text
subject specification
        |
        v
fresh content generation
        |
        v
deterministic validation
        |
        v
JEV atomic evaluation --------> versioned routing policy
                                     | clean and confident
                                     |---------------------> human review
                                     |
                                     | weak or uncertain
                                     v
                          generative diagnosis/rewrite
                                     |
                                     v
                                human review
```

During the experiment, run JEV and the baseline generative reviewer in shadow mode. Neither may approve, publish, or perform external side effects. Only a human may assign the final benchmark label.

### 4. Domain contracts

Define a stable `Candidate` model with:

- immutable candidate ID
- subject-specification version
- requested content type and difficulty
- structured generated content
- generator, exact model, prompt version, seed, batch, and timestamps
- optional factual-source references

Keep the generated payload flexible enough for the selected content format, but validate it through a versioned Pydantic schema. Do not place provider response objects in the domain model.

Every provider call creates an append-only `EvaluationRun` with:

- run ID and candidate ID
- evaluator kind and exact returned model identifier
- rubric and policy versions
- normalized input hash
- complete normalized result
- raw result or a redacted reference
- usage, latency, retry count, and estimated cost
- success or explicit error category
- creation timestamp

Never overwrite an earlier run. Derive the current view by querying the latest applicable successful run.

Use explicit workflow states:

```text
generated -> validated -> shadow_evaluated -> awaiting_human
          -> remediation_requested -> remediated -> awaiting_human
          -> accepted | rejected
```

An evaluator failure is a visible state or event, never a low quality score.

### 5. Rubric design

Build the rubric only after the subject specification is approved.

- Decompose quality into atomic questions that can be judged independently.
- Use binary probability judgments for crisp defects.
- Use ordered scores only when the dimension is genuinely gradual, and describe every level concretely.
- Make each check's polarity consistent in the adapter: `1.0` always means the candidate meets the rubric.
- Keep evidence check IDs so every aggregate dimension can be traced to its atomic inputs.
- Separate factual correctness, instruction compliance, clarity, internal consistency, audience fit, safety, and style when those dimensions apply.
- Do not ask JEV to explain defects or rewrite content.
- Keep deterministic checks authoritative for schema shape, bounds, required fields, duplicated values, and other mechanically provable rules.

A normalized result should contain dimension scores, applicable confidence values, hard failures, uncertain checks, evidence check IDs, and a proposed route. It must not pretend that typed evaluation produced narrative comments.

### 6. Policy design

Keep routing policy outside evaluator prompts and version it independently.

The policy should:

1. Normalize evaluator outputs.
2. Aggregate atomic checks into named display dimensions.
3. Identify critical dimensions from the subject's documented risks.
4. Route hard failures, uncertainty, and near-boundary results to generative diagnosis and then human review.
5. Route only clean, confident candidates directly to human review.
6. Record what would have happened without changing the real review path during shadow mode.

Do not choose final thresholds by intuition. Calibrate them on a labeled development split, then evaluate them once on a frozen held-out split.

### 7. Fresh benchmark construction

Create the benchmark without copying existing private content:

1. Generate a diverse synthetic pool from the selected subject specification.
2. Include expected-good and intentionally flawed items.
3. Create controlled mutation pairs that introduce exactly one defect at a time.
4. Include difficult cases that appear polished but contain factual or logical errors.
5. Have qualified humans label every dimension and final disposition.
6. Double-label a meaningful sample and adjudicate disagreements.
7. Freeze train, validation, and test manifests before threshold tuning.

The generator must support a deterministic seed and record all prompt/model metadata. Synthetic labels such as “intended flaw” are test construction metadata, not ground truth; human review establishes the benchmark label.

### 8. Testing strategy

Tests must be generic and self-contained.

- Unit tests use inline builders or fixtures created inside the new repository.
- Contract tests use fake provider responses checked against local protocols.
- Integration tests create temporary databases and generated sample records at runtime.
- No test reads paths, environment files, datasets, or source code from another repository.
- No test requires real provider credentials unless explicitly marked as an opt-in live test.
- Live tests use a small limit, never run in default CI, and store no secrets or proprietary prompts in artifacts.
- Add polarity tests proving that every normalized score uses the same “higher is better” convention.
- Add replay tests proving that a frozen manifest and fake responses produce the same report.
- Add failure tests for timeouts, malformed provider output, retries, and partial runs.

### 9. Benchmark and rollout

Compare three arms over the same normalized candidates:

1. Baseline generative reviewer.
2. JEV evaluator.
3. JEV routing followed by generative remediation where policy requires it.

Choose acceptance metrics after the subject risks are known. At minimum, report:

- unsafe-pass rate for human-rejected items routed as clean
- recall for each critical defect
- per-dimension agreement with humans
- disposition precision, recall, and confusion matrix
- probability calibration
- percentage routed to each stage
- p50/p95 latency and provider cost per candidate
- stability across repeated runs

Adopt selective routing only when the held-out results meet the documented safety gates and reduce generative-review calls without increasing human effort. Any rubric, prompt, threshold, provider model, or subject-specification change creates a new version and requires replay against the frozen benchmark.

### 10. Reliability and operations

- Keep provider keys only in environment variables or a secret manager.
- Retry only transient failures with bounded exponential backoff and jitter.
- Configure concurrency and rate limits independently per provider.
- Make submissions idempotent for `(input_hash, rubric_version, evaluator, model)` unless explicitly forced.
- Record the exact returned model identifier.
- Confirm provider retention, training, region, and deletion terms before sending sensitive material.
- Never let evaluator availability block manual review; degraded mode routes candidates to humans with a visible error.
- Support dry runs, resumability, deterministic selection, and JSON output for every experiment command.

### 11. Deliberate exclusions

The first milestone does not include:

- importing or migrating content from another project
- production publishing or automatic approval
- automatic application of generated rewrites
- a web editor or review queue
- translation or localization
- model training or fine-tuning
- treating one model's output as human truth

The experiment should answer one question: **for the selected subject, can typed atomic evaluation reduce generative-review work without allowing unacceptable content to bypass that review?**
