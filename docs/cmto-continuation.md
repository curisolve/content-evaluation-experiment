# Continuing a stopped CMTO generation run

Use `cmto-continue`, not a fresh `cmto-run`, to preserve completed generation.
This creates a linked child run and never edits the parent journal. It reuses
validated `candidate.prepared` records byte-for-byte and preserves the frozen
subject, sources, rubric, generator/LLM model, evaluator configuration and prices.

Preview is read-only and needs no keys:

```bash
uv run content-eval cmto-continue 64cb221f-8211-422c-992f-42eee6a0e963 \
  --db runs/cmto.sqlite --max-estimated-usd 5 --max-calls 57 \
  --generation-timeout-seconds 120
```

For that run, the preview identifies two reusable candidates, three prior calls,
$0.16844 of known estimated charges, one unknown-cost attempt and at most 54 new
calls. The total call allowance of 57 includes the failed prior attempt. These
counts and charges come from the local journal, not a new provider request.

## Explicit execution and uncertain billing

The client timed out without receiving usage for the third call. It may already
have been billed. A retry is a new request, not a guarantee that the old request
was cancelled or free.

To execute, add all of:

- `--execute`, with keys loaded using `uv run --env-file .env`;
- `--acknowledge-uncertain-attempts` when prior attempts have unknown cost;
- a positive `--unknown-cost-reserve-usd AMOUNT` covering all unresolved historical
  attempts in this continuation chain.

For example, choosing `--unknown-cost-reserve-usd 0.25` reserves $0.25 of the $5
admission budget for unknown historical charges. This is a user-selected allowance,
**not a billing estimate or guaranteed ceiling**. Provider billing may differ.
The reserve is never added to reported known costs or used to mark accounting
complete.

The guards include all prior attempts, known costs and this reserve plus the
next-call admission estimate. A new unknown-cost response stops the child again;
the acknowledgement covers historical calls, not future unknown charges.
Continuation caps must be explicit and are limited to 80 total calls. The usual
fresh-run cap remains 56, with no automatic retries.

## Timeout and report changes

Fresh `cmto-run` and `cmto-continue` default to a 120-second generation timeout,
configurable with `--generation-timeout-seconds` up to 300 seconds. Evaluator
timeouts remain frozen separately (30 seconds in the current configuration).
HTTP timeouts limit individual network operations, not overall experiment duration.

Early bounded exits now emit `run.stopped` and report `status: stopped`.
The reducer also reports old CMTO `run.completed` events with early-stop reasons
as stopped, without rewriting them. Only pool exhaustion reports completion;
it still does not establish audited quality.

Child reports distinguish newly prepared and reused candidates, expose parent
hashes, prior calls/known costs/unknown counts, and include prior known costs in
the chain's total. Provider token counters remain local to each run. Unknown
historical billing keeps the chain's `experiment_cost_complete` false even if
all new calls have complete usage.

## Safety limits

Continuation currently handles generation stops only. It rejects parents that
already froze a pool or started evaluation, invalid generated content, and a
successful response that lacks a prepared record (which needs local recovery,
not a paid retry). General `resume`/evaluation resume are unchanged.

Only one continuation may be created from a parent in the same journal database.
If a child also stops, inspect it and continue from that child. Do not branch from
an older parent or copy journals to bypass the check. Parent references and reused
content are frozen in the child manifest, so reports and JSONL replay are
self-contained; the original journal remains available for detailed usage audit.
