# Live smoke verification

Evidence recorded September 20, 2026 from the completed CLI JSON reports pasted by the user. These are user-run live calls, not mocked test output. This summary does not claim independent inspection of raw provider responses or invoices. No credentials or raw run databases are committed.

Both runs used one synthetic arithmetic MCQ. Both arms completed one attempt, passed and selected the same original, and reported no failures, retries, unresolved judgments, or outstanding attempts. Estimated cost accounting was complete in all four calls; actual billed cost and audited quality remain unknown.

| Run / arm | Input tokens | Output tokens | Latency (ms) | Estimated USD |
|---|---:|---:|---:|---:|
| Anthropic pairing: JEV | 496 | 41 | 680.069541 | 0.000020832 |
| Anthropic pairing: Opus 5 | 623 | 27 | 3032.234792 | 0.00379 |
| OpenAI pairing: JEV | 496 | 41 | 448.671083 | 0.000020832 |
| OpenAI pairing: configured OpenAI model | 262 | 24 | 2869.684792 | 0.001528 |

All calls reported zero cache reads/writes. Reasoning counts were unavailable for both JEV calls and the Anthropic call; the OpenAI call reported zero. The report's zero reasoning total must be interpreted alongside `unknown_reasoning_attempts`.

## Run identifiers

- Anthropic command: `uv run --env-file .env content-eval live-smoke --llm anthropic --execute`
- Run ID: `fe8c5f5d-af4e-463b-bbcf-4c1bb2488b13`
- Manifest hash: `81c31182eee3ea4619addbda2e3d38aa96eb1150d7787dbbbaf12a0b3ef94a29`
- Observed active elapsed time: 3722.157625 ms.

- OpenAI command: `uv run --env-file .env content-eval live-smoke --llm openai --execute`
- Run ID: `5e73a5e0-37af-4c15-9b73-b5e891a4f1f1`
- Manifest hash: `a937b3b7f3d0f59411d5a88ccff886a0549b531d190af6714e325ee600e5556b`
- Observed active elapsed time: 3328.407541 ms.

The pasted report does not expose the exact OpenAI model ID; inspect the run's persisted manifest and attempt events before making model-specific claims. Do not infer that ID from pricing alone.

These runs establish working end-to-end requests, routing, and usage/cost reporting for the exercised paths. One toy item per pairing does not establish CMTO accuracy, semantic diversity, stable latency distributions, calibrated thresholds, or general cost/quality superiority. Reported p50 and p95 equal the single observed attempt latency. Full source freezing, rubric development, and audited evaluation remain ahead.

The implementation also passed 42 credential-free tests, strict mypy, ruff lint/format checks, and a package build before handoff. CI configuration is included; this statement describes local verification, not an assertion about remote CI status.
