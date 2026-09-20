# Human labeling guide v1

Status: draft for owner review. Applies to subject `cmto_v1`, version `1.0.0-draft.1`. This is a human guide, not an implemented JEV rubric.

## Review unit and authority

Review one immutable MCQ version: stem, four options, key, rationale, audience, difficulty, and a common frozen source pack. Use the approved source requirements and their exceptions. Do not substitute recollection for the selected authority. If authority is missing, contradictory, or not applicable, mark review unresolved and explain what evidence is needed.

An incorrect distractor is expected. Judge whether it is appropriately incorrect under the stated facts; do not mark the item factually defective simply because distractors are false. Check the key and rationale independently. Do not infer missing scenario facts to rescue an answer.

## Blinding and sequence

1. A coordinator assigns opaque review IDs and randomizes presentation after automated draft creation. Hide arm, evaluator scores/comments, route, revision history, intended flaws, and cohort.
2. Review the item against sources before viewing another related item. Separate family variants and avoid assigning both arms of the same item together when practical; record reviewer overlap.
3. Assign dimension labels and the initial disposition before editing. Record source locators and a concise reason for failures or uncertainty.
4. Record active review time separately from editing time and pauses. Preserve the submitted draft, proposed edits, and post-edit verdict separately.
5. Label preserved originals in the same final review phase when needed for detection metrics. A revised draft's label is not the original's label.
6. Error/attention flags may be revealed after the initial content judgment for operational handling; record this separately to preserve the blinded comparison.

## Dimensions

Use `pass`, `fail`, or `uncertain`; use `not_applicable` only with an explanation. These are proposed human dimensions; atomic evaluator questions will be derived after approval.

| ID | Pass criterion |
|---|---|
| authority_accuracy | The key and rationale are supported by the applicable frozen source; conditions and exceptions are preserved. |
| unique_answer | Exactly one option is best; every distractor is demonstrably inferior under the stated facts. |
| scenario_sufficiency | The scenario supplies the facts needed to determine the answer without invented assumptions. |
| rationale_consistency | The rationale supports the key, explains distractors, and does not contradict the stem or source. |
| clarity | Wording is interpretable without trick phrasing, confusing negation, or accidental answer cues. |
| audience_fit | Knowledge demands and terminology suit the tagged audience and difficulty. |
| safety_professionalism | The keyed answer and rationale do not endorse unsafe or professionally prohibited conduct. |
| source_traceability | References locate the actual supporting requirements in the approved source pack. |

Mechanical validation separately checks option count, IDs, empty/duplicate values, required fields, and key membership. A valid key identifier does not establish that its answer is correct.

## Disposition and severity

- **Acceptable:** Passes all applicable dimensions and needs no edit.
- **Revisable:** Has no critical defect; bounded edits preserve the learning objective and correct key. Examples: an unnecessarily awkward sentence, a weak distractor, or an imprecise locator where support is unambiguous.
- **Rejectable:** Has any critical defect, an incorrect key, multiple/no defensible answers, unsupported central advice, or needs fundamental reconstruction. A wrong key remains rejectable even if changing one character fixes it.
- **Unresolved:** Not a fourth quality verdict. Record missing evidence, conflicting authority, or insufficient reviewer expertise; seek adjudication and leave final disposition unset.

Severity is independent of edit effort. Mark critical when the endorsed answer or explanation could teach invalid consent, boundary violations, improper disclosure, unsafe practice, or falsification/misleading records. Other failures may be major (wrong answer, ambiguity, unsupported claim) or minor (local clarity or presentation). Record all defects, not just the most severe. If any applicable dimension remains uncertain, final disposition remains unresolved until adjudication.

## Reviewer records

Capture review ID; immutable candidate-version ID via coordinator mapping; reviewer pseudonymous ID and qualification; labeling-guide and source-pack versions; each dimension label; defect IDs/severity; source locators; concise reasoning; initial disposition; unresolved reason; review/edit time in seconds; proposed edits; post-edit verdict; and timestamps.

The coordinator retains arm/family mappings outside the blinded packet. Human labels and adjudications are append-only with supersession links, never overwrites.

## Independent review and adjudication

Proposed pilot protocol: independently double-label a stratified 25% sample of each arm's drafts, rounded up, spanning topics, audiences, and difficulty, plus a sample of preserved originals. Additional flagged cases may be reviewed, but report them separately from the random sample. Compute agreement on independent labels before adjudication.

A qualified second reviewer or adjudicator resolves disagreements using cited authority, preserving both original judgments and the rationale for resolution. If no second qualified reviewer is available, report single-reviewer evidence and leave inter-rater reliability unestablished. Do not fabricate consensus.

## Reporting safeguards

Report all submitted originals, created drafts, attention cases, unresolved labels, and excluded records with reasons. Report acceptance without edits separately from post-edit acceptance. Count both revisable and rejectable drafts as needing human intervention; report critical defects separately.

For JEV direct-to-draft analysis, report rejected-direct / all-rejected originals and rejected-direct / all-direct originals, plus intervention-needed-direct / all-direct. Use labels for the exact version JEV evaluated. Do not treat missing human labels as passes.

Pilot labels inform development only. Freeze the policy and safety gates before held-out processing. Human verification stays at the end of each batch.

## Owner review checklist

- Confirm scope and definitions of acceptable, revisable, rejectable, and critical defects.
- Confirm the proposed pilot coverage and reviewer assignments.
- Resolve source applicability and freeze the authoritative pack before generation.
- Use pilot data to set main-study sample size, safety gates, and acceptable quality differences.
