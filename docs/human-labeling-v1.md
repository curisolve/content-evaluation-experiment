# Human audit guide v1

Status: revised draft for owner review. Applies to subject `cmto_v1`, version `1.0.0-draft.2`. This is a measurement protocol, not a requirement to approve or repair every generated question.

## Unit, blinding, and timing

Review an immutable MCQ with its stem, four options, key, rationale, audience, difficulty, and frozen authority pack. Judge the stated facts and applicable exceptions; do not rescue an answer by inventing facts. Incorrect distractors are expected: check that each is inferior under the actual scenario. Check key and rationale independently.

The coordinator exports opaque review IDs and hides arm, scores, route, cohort, intended flaws, and selection outcomes. Randomize order, separate family variants, and record reviewer overlap. Label each version once for both arms because neither arm rewrites it. Record the initial verdict and active review time; editing is not required. Final approval of selected items is a separate downstream activity.

## Dimensions and verdicts

Use `pass`, `fail`, or `uncertain`; `not_applicable` requires a reason.

| ID | Pass criterion |
|---|---|
| authority_accuracy | Key and rationale preserve applicable source requirements, conditions and exceptions. |
| unique_answer | Exactly one option is best and all distractors are demonstrably inferior. |
| scenario_sufficiency | Facts needed to apply the source are present. |
| rationale_consistency | Rationale supports the key, explains distractors, and contradicts neither stem nor authority. |
| clarity | No confusing wording, tricks, negation or accidental answer cues. |
| audience_fit | Knowledge demands suit the audience and difficulty. |
| safety_professionalism | Key and rationale endorse no unsafe or prohibited conduct. |
| source_traceability | References locate supporting requirements in the frozen source pack. |

Disposition is `acceptable` (no edits needed), `revisable` (noncritical bounded edits would preserve the objective and correct key), or `rejectable` (critical defect, wrong key, multiple/no answers, unsupported central claim, or fundamental reconstruction). Revisable is an analytical label; it does not create a human editing task. Both revisable and rejectable are filter misses if selected as ready for approval.

`unresolved` is a review status with final disposition unset, not a fourth quality label. Missing/contradictory authority, uncertainty on any applicable dimension, or insufficient expertise requires adjudication. Never count unresolved or absent labels as passes.

Critical defects include endorsed invalid consent, boundary violations, improper disclosure, unsafe practice, and false/misleading records. Other wrong answers or ambiguity may be major; local wording problems may be minor. Severity is independent of repair effort: changing one character in a wrong key does not make the submitted item acceptable. Record all defects and cited source locators.

## Pilot and subsequent sampling

Audit all 60 development inputs once, including 40 ordinary items and 20 controlled variants. Independently double-label a stratified 25% (15 inputs), spanning topics, audiences, difficulties and both cohorts. Keep intended-flaw metadata hidden. Report agreement before adjudication. Additional flagged reviews are separate from the random subset. Preserve original labels and adjudication rationale; no overwritten judgments or fabricated consensus.

For larger held-out runs, audit selected items and a probability sample of withheld items, with known inclusion probabilities and a frozen sample manifest. Sampling may be stratified by cohort and the paired outcomes of both filters, but those strata remain hidden from reviewers. Reuse a label for the same immutable input across arms. Use weighting and family-aware uncertainty in aggregate estimates. Selected-only labels cannot establish good-item loss or full defect recall. A single qualified reviewer cannot establish inter-rater reliability.

Audit semantic redundancy separately using blinded pairs or groups: record whether items test effectively the same learning point through interchangeable scenarios. Sample suspected exclusions and retained near-neighbors. A shared topic alone is insufficient. Preserve grouping and pair-sampling evidence; content correctness and redundancy are separate judgments.

## Records and reporting

Capture opaque review ID and coordinator mapping to immutable candidate ID; reviewer pseudonym/qualification; guide/source versions; dimension labels; defects/severity; source locators and reasons; initial disposition or unresolved reason; active review seconds; timestamps; and supersession/adjudication references. Redundancy labels additionally record both item IDs or group ID and the sampling method.

Report audited acceptability and critical defects among selected items, quality-pass versus selection outcomes, good items withheld, per-defect detection, and reviewer effort. Show denominators, missing/unresolved labels, and sampling coverage. Separate ordinary from challenge results. Pilot data is for development only; held-out policies, safety gates, and selection configuration are frozen before evaluation.
