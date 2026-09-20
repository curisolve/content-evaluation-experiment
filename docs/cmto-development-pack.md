# Consent and boundaries development pack

This is a 20-item development slice of the broader CMTO subject, authorized in the conversation. It does not replace the later 60-item pilot or establish a held-out benchmark. No questions have been generated and no paid model calls are part of this source-preparation work.

The [scoped subject](../subjects/cmto_consent_boundaries_v1.json) defines 12 ordinary originals, four controlled-defect variants and four semantic-duplicate variants. The [atomic rubric](../rubrics/cmto_consent_boundaries_v1.json) is configuration for implementation and calibration, not a calibrated evaluator or a human approval decision.

## Applicability and provenance

CMTO's August 2026 announcement explicitly says the consolidation takes effect September 8, 2026 and specifically identifies the merger of the two boundaries/draping standards. This resolves the earlier uncertainty caused by treating page update dates as possible effective dates. [CMTO effective-date announcement](https://www.cmto.com/all-touchpoints/standards-and-policy-consolidation-effective-september-8-2026/).

The selected consent and boundaries pages both display September 8, 2026 approval/update dates. Record applicability as September 8, 2026 with the announcement as evidence; do not apply these versions to historical scenarios. The old 2022 introductory PDF is not effective-date evidence for this pack.

Capture exact HTML entity bytes and reproducibly normalized visible text using `scripts/capture_cmto.py`. Raw snapshots and normalized full text stay under ignored `source-artifacts/`; only metadata/hashes are committed. The website says all rights reserved, and redistribution permission has not been established. This does not claim a reuse license. Keep the original files available locally for verification; later transfer them through an appropriate artifact mechanism, not Git metadata or active-worktree synchronization.

A later download may differ because of page chrome or substantive changes. Never overwrite a frozen capture; use a new directory/version. The normalizer retains whole-page visible text and is not yet an evaluator context extractor. Preserve full relevant requirement text, not the abbreviated map below, in eventual provider requests.

## Requirement map

IDs are `source_id:requirements.N`, following the numbered requirements on the frozen HTML page. These summaries aid coverage planning and do not replace the source.

| Source | Locators | Coverage focus |
|---|---|---|
| Consent | 1 | Consent discussion before assessment, treatment or treatment-plan change; preserve all six discussion elements. |
| Consent | 3 | Voluntary, relevant consent without deception. |
| Consent | 8 | Ongoing monitoring and rechecking consent when appropriate. |
| Consent | 9 | Record consent discussions within 24 hours; retain applicable consent records. |
| Boundaries | 3–5 | Patient participation does not justify violations; manage power imbalance and professional conduct. |
| Boundaries | 6–7 | Prompt handling/documentation of accidental crossings; requested companions. |
| Boundaries | 9–12 | Clothing/draping preferences, preparation, proposed touch and ongoing comfort/consent. |
| Boundaries | 15–18 | Explicit permission and alternatives for under-clothing care; privacy, clothing adjustment and secure barriers. |
| Boundaries | 19 | Exposure limits and applicable comfort exceptions; exclude sensitive areas from this slice. |

Sources: [Consent](https://www.cmto.com/rules/standard-of-practice-consent/), [Professional Boundaries, Draping, and Physical Privacy](https://www.cmto.com/rules/standard-of-practice-professional-boundaries-draping-and-physical-privacy/).

Capacity disputes, minors, substances, sensitive areas, childbirth, and numerical gift-value thresholds are out of scope. Reference dependencies must still be checked case by case: if a question requires an excluded glossary definition, other standard or legal authority to resolve, withhold it until that source is approved and captured. Do not infer that excluding a topic removes exceptions from the source itself.

## Before generation

Check the local captures without network access:

```bash
uv run python scripts/verify_cmto_pack.py subjects/sources/cmto_consent_boundaries.capture.json source-artifacts/cmto-2026-09-20
```

The committed manifest is the integrity reference. Captures are machine-local and are not included in a clone. A fresh capture is a new version, not guaranteed to match these hashes. Integrity verification alone does not satisfy the content-review gate.

Verify all three artifacts against the committed capture manifest. Implement stable requirement extraction with full context and resolved locators, then wire the configured subject/rubric into generator and evaluator requests. The present live CLI remains an arithmetic smoke test; this new pack does not silently change it. Freeze a run manifest with exact models, source hashes, prompt/rubric versions, shared candidate ordering and a bounded spend/call budget.

Audit all 20 versions once for the paired comparisons. Review the four near-duplicate variants separately for semantic equivalence; different wording is not automatically variety. Label intended defects and near-duplicates only as construction metadata, hidden from evaluators and reviewers. Use these development labels to tune selection and assess whether the broader pilot is warranted.
