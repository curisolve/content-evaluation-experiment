# CMTO development collection

This is a small data-collection workflow, not a calibrated quality benchmark or an
approval pipeline. It has been tested offline with mocked provider responses.
The existing live smoke evidence covers arithmetic, not this CMTO prompt.

Run commands from the `cmto-source-pack` development worktree. The captured
HTML/text must exist locally; Git contains hashes, not the full source files.

## Review and preview (no API calls)

```bash
uv run content-eval cmto-pack --output source-artifacts/cmto-2026-09-20/context-v1.json
uv run content-eval cmto-run --max-estimated-usd 5
```

The output file refuses overwrite. It contains the full extracted authority,
stable requirement IDs, source provenance, subject and rubric, and a pack hash.
Review it before executing. Extraction includes all nine consent requirements
and all nineteen boundaries requirements, including nested clauses and the
paragraphs governing each list. The allowed citation set is narrower than the
context: excluded rules remain visible so their exceptions are not silently lost.

The extractor's structure was checked against the captured HTML. This is **not**
independent domain approval. Uncaptured glossary definitions and referenced
standards remain dependencies: questions requiring them are outside this slice.
The reviewed hash acknowledges this development scope, not clinical correctness.

## Explicit paid execution

After review, substitute the hash emitted by `cmto-pack`:

```bash
uv run --env-file .env content-eval cmto-run \
  --llm openai --generator anthropic --generator-model claude-opus-5 --max-estimated-usd 5 \
  --reviewed-pack-hash PACK_HASH --execute --db runs/cmto.sqlite
```

For OpenAI use `--llm openai --model YOUR_EXACT_OPENAI_MODEL`, or set
`OPENAI_MODEL` in the loaded environment. Existing supported model/rate snapshots
are unchanged. Generator, reviewer, and JEV credentials must all be present before
fresh generation starts. Reevaluation needs only reviewer and JEV credentials.
No network is used by preview.

A new command invocation generates a new pool. Do **not** treat separate
Anthropic/OpenAI invocations as a three-way same-pool comparison. This slice
compares JEV against one chosen LLM on identical inputs within a run. Use
`cmto-reevaluate` to review an existing frozen pool without regeneration.

The generator is configured independently from the reviewer: by default Opus
generates and the configured OpenAI model reviews. Same-model generation/review
is rejected. See [independent review and accuracy](accuracy.md), including a
zero-generation command for reevaluating an existing completed pool.
Code allocates twelve ordinary slots,
creates four intended wrong-key variants deterministically, and requests four
paraphrases of designated parents. Family, cohort and construction labels are
retained in the journal but hidden from evaluator requests. Intended defects and
duplicates are construction metadata, not human-verified labels.

The resulting twenty items are frozen and shuffled once; both evaluators see the
same order, source context and ten rubric questions. Threshold `0.9` is a
provisional development policy; `--threshold` changes it explicitly and freezes it
in the manifest. LLM verdicts remain categorical; their internal numeric mapping
is not a calibrated probability. TypeSafe's Noul probabilities are retained.
See [Noul guidance](https://docs.typesafe.ai/primitives/noul) and the
[citation-checking pattern](https://docs.typesafe.ai/cookbooks/citation_check).

Structured generation/evaluation uses the existing direct HTTP adapters and
provider schemas: [OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
and [Anthropic structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs).
There are no provider SDK retries or repair calls.

## Bounds and stops

- At most 56 calls: sixteen generation calls and forty evaluation calls.
  `--max-calls` can lower this cap.
- Each request has a 100,000-byte serialized-input limit and the configured
  provider timeout. Generation defaults to 120 seconds, configurable with
  `--generation-timeout-seconds` (maximum 300); evaluation remains at 30 seconds.
  Generated candidates have a 12,000-byte limit.
- Generation and LLM evaluation allow at most 4,096 output tokens per call.
  JEV returns the fixed typed-check set; it has no generative output cap parameter.
- Before each call, the coordinator checks cumulative known estimated charges
  plus a next-call admission reserve: request UTF-8 byte count plus 8,192 estimated
  input tokens, highest input-bucket rate, and maximum configured output tokens.
  This is intentionally a conservative heuristic, **not a tokenizer guarantee or
  hard provider billing cap**. Use provider-side billing controls as well.
- Missing usage, an unexpected model/tier, or an interrupted attempt prevents
  further paid calls. Generation failures or invalid generated items stop without
  repair. All received output/usage is journalled before local parsing.
- `stop_reason` distinguishes pool exhaustion, call/spend guards, invalid output,
  provider failure, and interruption. `collection_complete` distinguishes reaching
  the end of the fixed pool from an early bounded stop; it does not certify quality.
- There is no wall-clock deadline or concurrency. Generation-only stops can use
  [explicit linked continuation](cmto-continuation.md), preserving prepared items
  and historical costs. Uncertain prior calls require acknowledgement and a
  positive budget reserve; they are never silently reissued. A new `cmto-run`
  is a new paid experiment, not a resume.

## Inspect and replay

```bash
uv run content-eval runs --db runs/cmto.sqlite
uv run content-eval report RUN_ID --db runs/cmto.sqlite
uv run content-eval export-events RUN_ID runs/cmto-events.jsonl --db runs/cmto.sqlite
uv run content-eval replay runs/cmto-events.jsonl
```

The append-only journal freezes source text, prompt/schema/rubric versions,
allocation, prices, requests, raw redacted responses, token usage, budget
admissions, pool hashes, judgments and selection decisions. It contains source
text and construction labels: keep it local/private; it is not a blinded audit
packet or an artifact to commit.

Reports show generator cost separately, per-arm evaluation cost, and the actual
experiment's estimated total (shared generation counted once). Unknown accounting
remains unknown. Ordinary, defect, and paraphrase counts are separate; combined
per-item ratios are not production-yield estimates. Accuracy remains unmeasured
until independent reference labels are imported; actual billed charges stay null.

Selection is still exact-text-only and provisional. Semantic redundancy and
coverage quotas are not implemented, so selected count is not verified diverse
yield. CMTO approval export is deliberately blocked. Blinded audit packets, label
import, and same-pool reevaluation are available in the [accuracy guide](accuracy.md).
Calibration, semantic-duplicate selection, adjudication, and a fresh held-out
comparison remain follow-on work.
