# Frozen-policy validation run

This is a prospective check of the proposed filter, not production approval.
The architecture/design-decision write-up is deferred to the user's later session.

Freeze the plan before any generation:

```bash
uv run content-eval cmto-validate DEVELOPMENT_RUN_ID --db runs/cmto.sqlite \
  --max-estimated-usd 5 --output runs/validation-plan.json
```

Review the plan, then execute with its exact manifest hash:

```bash
uv run --env-file .env content-eval cmto-validate DEVELOPMENT_RUN_ID \
  --db runs/cmto.sqlite --max-estimated-usd 5 \
  --reviewed-manifest-hash HASH_FROM_PREVIEW --execute
```

The manifest freezes the ten checks, all-checks-above-0.5 rule (ties withhold),
explicit LLM uncertainty withholding, and source/provider/model/rate snapshots.
Jev's original 0.1–0.9 uncertainty flag remains recorded but does not veto routing.
Missing/invalid evaluations remain unresolved. This uses the same decision function
as the offline experiment. Normal development defaults and historical runs do not change.

The new pool has 12 fresh ordinary questions, 4 wrong-key challenge mutations and
4 paraphrases of NEW parents. No candidates or human labels are carried over.
Only old stems are supplied to generation as exclusions; evaluator inputs never
contain old scores or labels. Exact normalized stem overlap stops the batch, with
the paid generation attempt still recorded. Semantic uniqueness is NOT guaranteed.
There is at most one validation start per development parent, at most 56 calls,
no automatic retries/replacements, and a $5 estimated admission guard—not a billing cap.
Continuation/reevaluation of validation runs is deliberately blocked pending
explicit protocol review so a failed batch is not silently replaced or retuned.

After completion, export a new blinded audit packet with `export-audit`.
Before seeing model decisions, the reviewer should judge suitability unchanged:
optional wording improvements do not require rejection; necessary corrections do.
Semantic redundancy is separate from item correctness. Obtain a separate cross-pool
scenario/family-overlap review before claiming held-out independence.

Import the new labels with `import-audit`; use `compare` and `report` for metrics.
Do not adjust the policy after seeing labels. Report ordinary and challenge
populations separately, including uncertainty, false accepts/rejects, precision,
recall, cost and latency. Twenty correlated items cannot establish production safety.
The report's validation status intentionally remains pending the external quality
and overlap review; the software does not independently attest either.
