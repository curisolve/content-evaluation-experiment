# Offline filter-first policy analysis

The baseline policy returns unresolved whenever any Jev probability lies between
0.1 and 0.9, before considering other failed checks. This can mask a strong negative
judgment on one check with an uncertain judgment on another.

The separate, opt-in `analyze-policy` command reuses completed evaluations without
changing the live policy, saved decisions, labels, selection, or historical costs.
It makes no API calls. Both arms use the same required checks and cutoff.

```bash
uv run content-eval analyze-policy RUN_ID --db runs/cmto.sqlite \
  --output runs/policy-conservative.json
uv run content-eval analyze-policy RUN_ID --db runs/cmto.sqlite \
  --threshold 0.5 --output runs/policy-majority.json
```

The default cutoff is the original manifest threshold (currently 0.9). The second
command is an exploratory conventional yes/no cutoff, not a fitted optimum or a
production recommendation. A score of exactly 0.5 is withheld. Every required
check must meet the cutoff; critical failures always withhold. A categorical LLM
uncertain answer withholds. Jev's saved uncertainty flag was derived from the old
cutoff; it is retained in the output but is not a separate veto. Missing evaluations
and rubric mismatches remain unresolved rather than being fabricated into judgments.

Withhold means not admitted to the human-approval queue, not proven factually
wrong. Zero unresolved therefore measures routing completeness, not certainty.
Inspect false accepts, false rejects, pass precision, recall and yield as well.
Passing counts precede deduplication and final selection.

The JSON artifact includes the parent run, manifest and last-event hashes, policy
definition/hash, per-item decisions linked to original result events and raw scores,
population-specific reference metrics, and a hash of the analysis. Output creation
is exclusive: existing artifacts are not overwritten. Analysis does not append to
the inference journal; that baseline stays immutable. The artifact is reproducible
against the identified journal snapshot. New inference cost is zero; displayed
source costs and latency are inherited measurements, not newly incurred charges.

These are post-hoc development results on a tiny, correlated pool. Labels retain
reviewer notes and any owner scope adjustments; do not present them as unchanged
blinded judgments. Freeze a chosen policy before collecting an independently
reviewed held-out pool. Do not optimize cutoffs against these labels and then claim
held-out accuracy. Semantic deduplication remains out of scope.

Design reference: TypeSafe's [Noul documentation](https://docs.typesafe.ai/primitives/noul)
distinguishes a probability of yes from quality intensity and leaves threshold
selection to the application. This analysis uses that distinction without claiming
the probabilities are calibrated for this domain.
