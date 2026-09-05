# Person Class-Confusion Analysis (EXP-0003)

Rigorous, IoU-based re-classification of all 239 Person ground-truth false negatives at the official baseline (conf=0.4, iou=0.7, run RUN-20260904-002), recomputed directly from `benchmark/results/baseline/predictions.jsonl` + `benchmark/results/diagnostics/low_conf_predictions.jsonl` + `data/manifests/eval_manifest.jsonl` — no new inference was run. Supersedes the informal 35.1% figure in `reports/baseline/person_failure_analysis.md` with a confidence-floor-aware, bug-free-matched breakdown (see Section 3).

## 1. Five-category breakdown (sums to 100% of the recomputed FN set)

| Category | Count | % |
|---|---|---|
| TRUE_DETECTOR_MISS | 92 | 38.5% |
| LOW_CONFIDENCE_PERSON | 82 | 34.3% |
| SEMANTIC_CLASS_CONFUSION | 13 | 5.4% |
| LOCALIZATION_FAILURE | 52 | 21.8% |
| **Total** | **239** | **100.0%** |

Secondary flag: **DUPLICATE_MULTI_LABEL** present on 46 of 239 FNs overall; of the 13 SEMANTIC_CLASS_CONFUSION cases, 7 also show DUPLICATE_MULTI_LABEL (multiple distinct human-related classes stacked over the same GT box).

## 2. Dominant confusion classes (SEMANTIC_CLASS_CONFUSION cases only)

| Alternate class | Count |
|---|---|
| Man | 10 |
| Boy | 2 |
| Woman | 1 |

## 3. Is the Phase B.5 35.1% figure still correct?

**No.** Under this more rigorous IoU-based matching, with an explicit diagnostic confidence floor (0.4, matching production) required on the alternate class, only **13/239 (5.4%)** of Person FNs are genuine SEMANTIC_CLASS_CONFUSION — far below the earlier 35.1% (84/239). The earlier figure counted ANY same-location alternate-class detection at ANY confidence (including near-zero-confidence noise at conf=0.01) as 'confusion'; most of that gap is reclassified here as LOCALIZATION_FAILURE (52, 21.8%, includes weak-confidence alias signals) or TRUE_DETECTOR_MISS (92, 38.5%). A genuinely large category not previously broken out at all is LOW_CONFIDENCE_PERSON (82, 34.3%) — correctly labeled Person, just below 0.4.

## 4. Small vs. non-small breakdown

**Small (<2% image area)** (n=153): TRUE_DETECTOR_MISS=68 (44.4%), LOW_CONFIDENCE_PERSON=49 (32.0%), SEMANTIC_CLASS_CONFUSION=3 (2.0%), LOCALIZATION_FAILURE=33 (21.6%)
**Non-small** (n=86): TRUE_DETECTOR_MISS=24 (27.9%), LOW_CONFIDENCE_PERSON=33 (38.4%), SEMANTIC_CLASS_CONFUSION=10 (11.6%), LOCALIZATION_FAILURE=19 (22.1%)

Semantic confusion is proportionally more common among non-small instances (11.6%) than small ones (2.0%) — consistent with a small/distant person simply not having enough resolved pixels for ANY confident classification (Person or alias), whereas a larger, closer person is more likely to be confidently (mis)labeled as Man/Woman than to be missed outright.

## 5. Counterfactual rescorings (diagnostic-only; never changes production config)

| Counterfactual | Person P | Person R | Hazard P | Hazard R | Recovered GTs | New FPs |
|---|---|---|---|---|---|---|
| A. Person only (official baseline) | 0.667 | 0.211 | 0.807 | 0.480 | 0 | 0 |
| B. + whole-person aliases (conf>=0.4) | 0.384 | 0.257 | 0.679 | 0.499 | 14 | 93 |
| C. + person subparts (conf>=0.4) | 0.332 | 0.257 | 0.642 | 0.499 | 14 | 125 |
| D. whole-person aliases, conf>=0.25 | 0.332 | 0.314 | 0.618 | 0.521 | 31 | 159 |
| D. whole-person aliases, conf>=0.4 | 0.384 | 0.257 | 0.679 | 0.499 | 14 | 93 |
| D. whole-person aliases, conf>=0.6 | 0.545 | 0.218 | 0.769 | 0.483 | 2 | 23 |
| D. whole-person aliases, conf>=0.8 | 0.640 | 0.211 | 0.800 | 0.480 | 0 | 4 |

**Man/Woman aliases are NOT clean equivalents of Person.** Accepting them at the production confidence threshold (counterfactual B) recovers only 14 GTs but introduces 93 new false positives — Person precision collapses from 0.667 to 0.384, and hazard-level precision drops from 0.807 to 0.679 (a 0.129 drop, which fails the standard hazard-precision guardrail of baseline-0.05 by a wide, non-noisy margin).

**Subpart classes (counterfactual C) recover essentially nothing beyond B** (0 additional GTs) while adding even more false positives (125 vs. B's 93) — confirming the expected mechanism: a 'Human hand'/'Human face' box is typically much smaller than a full-body GT box, so it rarely clears the 0.5 IoU match threshold against a whole-person GT; when it does clear a spatial floor elsewhere, it is usually a spurious co-occurrence, not a recoverable miss. **Subpart classes are too noisy to use as Person evidence.**

**Confidence-conditioning (counterfactual D) does not rescue the tradeoff**: raising the alias-acceptance confidence floor to 0.6 or 0.8 shrinks the new-FP cost substantially but also shrinks recovered recall to near-zero, because most alias predictions with high enough confidence to matter were already close to the noisy end of the distribution. There is no sweet spot in this sweep that recovers meaningful recall while preserving hazard precision.

**Conclusion: semantic remapping does NOT recover recall while preserving precision.** The clean, mutually-exclusive breakdown in Section 1 shows genuine SEMANTIC_CLASS_CONFUSION is a real but modest phenomenon (5.4% of misses, dominated by Man/Boy/Woman), and even fully exploiting it via scoring-time remapping costs far more precision than the recall it buys back.

See `experiments/*/EXP-0003/{hypothesis.md,methodology.md,analysis.md,conclusion.md}` for the full experiment record, and `benchmark/results/diagnostics/{person_confusion_analysis,person_counterfactuals}.json` for the complete per-box data this report summarizes.