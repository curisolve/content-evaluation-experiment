# Provider setup and smoke tests

Work in `projects/worktrees/content-evaluation-experiment/provider-adapters`, branch `feat/provider-adapters`, based on `feat/cli-foundation`. The synchronized `main` checkout is unchanged. No live API calls were made while implementing these adapters.

## Credentials

Create a local `.env` from `.env.example` and fill in the keys on this machine:

```dotenv
TYPESAFE_API_KEY=your-typesafe-key
ANTHROPIC_API_KEY=your-anthropic-key
OPENAI_API_KEY=your-openai-key
OPENAI_MODEL=gpt-5.6-sol
```

The GPT example is illustrative: explicitly choose `gpt-5.6-sol`, `gpt-5.6-terra`, or `gpt-5.6-luna` for your comparison. There is no default substitution for an unspecified GPT-5.6 variant. `claude-opus-5` is the Anthropic model ID; JEV is pinned to `jev-1.13.0` rather than a moving latest alias.

`.env` is ignored by Git. Keep it in the machine-local worktree; configure keys separately on your other machine. No key values appear in the journal, report, or readiness command. The app does not automatically discover or source arbitrary environment files; load the selected file explicitly with uv:

```bash
uv sync --locked --python 3.14
uv run --env-file .env content-eval check-providers
```

This prints only a boolean for each key's presence. It does not verify authentication, model availability, account balance, or permissions and makes no network calls. The offline `demo` command never uses these keys.

## Preview, then execute

```bash
uv run --env-file .env content-eval live-smoke --llm anthropic
uv run --env-file .env content-eval live-smoke --llm openai
```

These commands print the full non-secret manifest, source, questions, schema, model settings, rates, and maximum call count without creating a database or calling a provider. Override `OPENAI_MODEL` with `--model` if needed. Each run compares JEV against one chosen LLM on identical inputs; run the same fixed seed/count with the other LLM for a second exploratory comparison.

Adding `--execute` makes paid calls:

```bash
uv run --env-file .env content-eval live-smoke --llm anthropic --execute
uv run --env-file .env content-eval live-smoke --llm openai --execute
```

Default: one synthetic arithmetic item, one call per arm. Maximum: five inputs and ten calls; structurally invalid inputs make no calls. There are no automatic live retries, redirects or gateway endpoints. Requests are limited to 16,000 serialized bytes, LLM output defaults to 1,024 tokens, and each HTTP operation has a 30-second timeout. These limits bound the smoke workload; they are not a provider-enforced dollar cap or a total-run deadline.

The command tests connectivity and accounting only. It is not a CMTO rubric, generation pipeline, calibrated policy, or evidence of quality/savings. The fixture rubric has two checks: keyed sum correctness and rationale consistency. JEV asks both Nouls together and preserves their probabilities; the LLM returns compact pass/fail/uncertain verdicts, not invented calibrated probabilities or explanations. Smoke thresholds are placeholders. An uncertain, refused, incomplete, malformed, or failed evaluation cannot select an item as a quality pass.

## Accounting, failures, and replay

Every call is preceded by a durable attempt event and followed by a result or error event. Responses include returned model, available request ID, raw redacted result, raw/normalized usage, and decimal estimated cost. The price snapshot is frozen in the run manifest using published standard global/direct text rates retrieved September 20, 2026. It does not include account credits, contractual discounts, tax, or actual billed reconciliation.

OpenAI input totals include cache reads/writes; they are subtracted before pricing uncached input. Reasoning is counted within output, not billed again. Anthropic ordinary input, cache reads and cache writes are separate; five-minute and one-hour writes have separate prices. JEV output tokens are recorded with zero output charge. Missing/inconsistent counters remain unknown, with raw usage retained. Refusals and invalid outputs retain usage when supplied and can still incur cost.

An unexpected returned model or OpenAI service tier makes cost unknown rather than applying a potentially wrong rate. Account access and exact response fields still need a live smoke test; constructing fixtures cannot establish those facts. Both input context and standard-rate assumptions are deliberately restricted to this small text-only test.

Use `runs --db runs/live.sqlite` to locate an interrupted run. `live-resume RUN_ID` previews its state; add `--execute` and load local keys to perform any remaining calls. Completed runs are no-ops. Generic `resume` cannot silently replace live adapters with fake ones. A request interrupted after intent remains unknown and is withheld rather than retried. An incompatible saved smoke configuration is rejected rather than silently repriced or reprompted.

`report`, `export-events`, and `replay` work with live runs too. Replay never calls providers and uses the original frozen rates/results. Actual billed dollars remain null until reconciliation; estimated spending is separate.

## Official contracts used

- [TypeSafe API](https://docs.typesafe.ai/api), [Noul](https://docs.typesafe.ai/primitives/noul), [model and price](https://docs.typesafe.ai/models).
- [OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs), [cache accounting](https://developers.openai.com/api/docs/guides/prompt-caching), [pricing](https://developers.openai.com/api/docs/pricing).
- [Anthropic structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs), [models](https://platform.claude.com/docs/en/models/overview), [pricing](https://platform.claude.com/docs/en/about-claude/pricing).

`tests/test_live.py` uses HTTP mock transports only. Default CI makes no paid requests.
