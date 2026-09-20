# Independent reviewers and measured accuracy

## Generator is not the reviewer

New CMTO runs default to an Anthropic generator (`claude-opus-5`) and an OpenAI
reviewer (the exact `OPENAI_MODEL` in your environment, or explicit `--model`).
`--generator` and `--generator-model` configure generation independently.
Both provider/model pairs and their price snapshots are frozen. The generator's
usage is priced using its own rate card, not the reviewer's. Same-model
generation/review is rejected before paid calls, including execution of legacy
same-model configurations. Historical journals remain readable.

The existing OpenAI structured-output adapter is retained, following
[official structured-output documentation](https://developers.openai.com/api/docs/guides/structured-outputs).
There is no automatic substitution of another model when configuration is missing.

## Reuse the completed Opus pool

Preview with the configured OpenAI reviewer:

```bash
uv run --env-file .env content-eval cmto-reevaluate \
  76c675b1-3d10-4591-a6a2-5851c90372bc \
  --db runs/cmto.sqlite --max-estimated-usd 5
```

Add `--model gpt-5.6-sol` only if that is the exact reviewer you intend to use.
Add `--execute` to explicitly authorize paid execution. This creates a new linked
run: no generation, unchanged twenty candidates, identical order and authority,
and at most forty calls (twenty OpenAI plus twenty JEV). Both evaluators run anew;
old JEV judgments remain in the parent rather than being silently mixed with new
measurements. Only OpenAI and JEV keys are needed for reevaluation.

The new run's costs cover new evaluation calls, not parent generation or earlier
evaluations. Parent run ID, manifest hash, pool hash, inputs and input hashes are
frozen in the new manifest. Reevaluation does not modify the parent or its policy.
The existing provisional threshold/uncertainty policy is preserved, not calibrated
or repaired as part of this change.

For fresh data, preview `cmto-run --max-estimated-usd 5` with the same environment.
Its source-review/hash gate still applies. Do not regenerate this existing pool
merely to change its reviewer.

## Accuracy needs reference labels

A model's pass rate, agreement with Opus/GPT, or intended wrong-key construction
is not measured accuracy. The default accuracy column is N/A until independent
human reference labels have been imported. Human review is measurement of the
filter, not a request to edit or approve the generated questions.

After the new evaluation completes, substitute its run ID:

```bash
uv run content-eval export-audit RUN_ID runs/audit-review.json --db runs/cmto.sqlite
```

Share only that packet with a reviewer who has not seen arm outcomes or intended
defects. Do not share the event journal or coordinator logs. The packet includes
frozen authority, rubric questions, and original content with opaque review IDs.
It hides candidate/family/cohort IDs, model identities, judgments and selections,
randomizes order and separates adjacent variants when possible. Wording can still
reveal related items; this is blinding to metadata, not a guarantee against inference.

The reviewer fills in:

- `reviewer_id`, relevant `qualification`, and `independent: true`;
- `reference_type: human` for independent human review, or `proxy` for model-based
  reference judgments (never mixed into human accuracy);
- per item: `disposition` = `acceptable`, `revisable`, `rejectable`, or `unresolved`;
  `notes` with the rationale/source basis, and `review_seconds` for active effort.

Leave unreviewed dispositions null. Do not edit candidate content, hashes, source
or criteria. Both revisable and rejectable mean the original is unsuitable to pass
unchanged. Do not assume seeded defects are ground truth. Qualification and
independence are reviewer attestations, not credentials verified by the software.

```bash
uv run content-eval import-audit RUN_ID runs/audit-review.json --db runs/cmto.sqlite
uv run content-eval compare RUN_ID --db runs/cmto.sqlite
uv run content-eval report RUN_ID --db runs/cmto.sqlite
```

Import is validated before appending a durable event. Tampered inputs, duplicate
IDs, missing provenance, and overwrites of existing labels are rejected. Partial
imports are supported; on later import, leave previously imported dispositions
null or omit those items. This initial version has no label revision, multi-rater
adjudication, per-dimension labels or uncertainty intervals: finalize labels before
import; unresolved references remain excluded from accuracy.

## What the columns mean

Accuracy is correct pass/withhold decisions divided by reference-labelled,
evaluated items. A pass is correct for an acceptable reference; a withhold is
correct for a revisable/rejectable reference. Model abstentions earn no correctness
credit in this primary measure, but are separately counted—not silently discarded.
Missing or unresolved human reference labels are excluded, with counts and coverage.

The detailed report also gives accuracy on decisive answers only, decision
coverage, pass precision, acceptable-item recall, false accepts/rejects, reference
coverage and reference uncertainty. With no decisive predictions, decisive accuracy
is null. With no reference labels, all accuracy percentages are null, not zero.
Proxy agreement is reported separately as `proxy_accuracy_details`.

The compact `compare` table shows evaluation cost, median latency, accuracy,
labelled/evaluated items versus pool size, and all unresolved model decisions.
JSON additionally splits ordinary, defect, and paraphrase populations. All-item
accuracy mixes constructed challenge cases with ordinary items; it is not an
operational-prevalence estimate. Partial audit results describe only labelled
items, not unlabelled items or a future population. Family correlation and small
sample size limit conclusions.

These labels assess item quality, not semantic redundancy or final approval.
Audit activity does not increase the recorded inference elapsed time. Reports and
JSONL replay derive the same metrics from immutable label events.
