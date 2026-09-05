# EXP-0003 — Analysis

## Verdict (from research/evaluation_policy.py, unmodified)

- guardrail `hazard.precision` violated: 0.6785 does not satisfy `gte` 0.7570 (hazard precision must not drop more than 0.05 below baseline) — margin 0.0785, well outside the 0.01 noise margin, so this is a hard FAIL, not a noisy/ambiguous one.
- `hazard.recall` and `latency.p95_ms` guardrails were satisfied.
- Raw evaluation-policy verdict: **FAILED**. `verdict_interpretation` is the identity map for this experiment (not confirmatory-negation like EXP-0001), so final experiment status: **FAILED**.

## 1. Five-category breakdown of the 239 recomputed Person false negatives

| Category | Count | % |
|---|---|---|
| TRUE_DETECTOR_MISS | 92 | 38.5% |
| LOW_CONFIDENCE_PERSON | 82 | 34.3% |
| SEMANTIC_CLASS_CONFUSION | 13 | 5.4% |
| LOCALIZATION_FAILURE | 52 | 21.8% |
| **Total** | **239** | **100.0%** |

Recomputed FN count (239) matches the baseline's own Person FN count exactly (per_class.json: fn=239), confirming this recomputation is consistent with the official baseline scoring — no methodology drift in the FN denominator.

Secondary flag: DUPLICATE_MULTI_LABEL present on 46/239 FNs overall; of the 13 SEMANTIC_CLASS_CONFUSION cases, 7 also show DUPLICATE_MULTI_LABEL (multiple distinct human-related classes stacked over the same GT box).

## 2. Dominant confusion classes (SEMANTIC_CLASS_CONFUSION only)

Man: 10, Boy: 2, Woman: 1 (13 total — no subpart class ever won the primary-alt-class ranking; subparts never reach the 0.5 IoU / 0.4 confidence bar against a full-body GT in this dataset).

## 3. Is the Phase B.5 35.1% figure still correct under this more rigorous matching?

**No — it drops to 5.4% (13/239).** The Phase B.5 figure counted ANY same-location alternate-class detection at ANY confidence (including near-zero-confidence noise from the conf=0.01 capture) as "confusion," with no diagnostic confidence floor. Requiring the alias/subpart prediction to clear a genuine, production-comparable confidence floor (0.4) before counting as SEMANTIC_CLASS_CONFUSION reclassifies most of that gap: LOCALIZATION_FAILURE (52, 21.8%, includes weak-confidence alias signals that are localized but too faint to count as real confusion) and TRUE_DETECTOR_MISS (92, 38.5%). A genuinely large category the earlier analysis never separated out at all is LOW_CONFIDENCE_PERSON (82, 34.3%) — a correctly-labeled Person prediction that simply scored below 0.4; this is a confidence problem, not a labeling problem, and belongs to a different fix (thresholding — already tested and rejected by EXP-0001).

## 4. Small vs. non-small breakdown (small = GT area < 2% of image, matching Phase B.5's convention)

- **Small** (n=153): TRUE_DETECTOR_MISS=68 (44.4%), LOW_CONFIDENCE_PERSON=49 (32.0%), SEMANTIC_CLASS_CONFUSION=3 (2.0%), LOCALIZATION_FAILURE=33 (21.6%)
- **Non-small** (n=86): TRUE_DETECTOR_MISS=24 (27.9%), LOW_CONFIDENCE_PERSON=33 (38.4%), SEMANTIC_CLASS_CONFUSION=10 (11.6%), LOCALIZATION_FAILURE=19 (22.1%)

The conclusion does NOT hold uniformly: semantic confusion is a real (if modest) phenomenon for non-small instances (11.6%) but nearly disappears for small ones (2.0%) — consistent with a small/distant person simply lacking enough resolved pixels for ANY confident classification (Person or alias), whereas a larger, closer person is more likely to be confidently mislabeled as Man/Woman than missed outright.

## 5. Counterfactual rescorings

| Counterfactual | Person P | Person R | Hazard P | Hazard R | Recovered GTs | New FPs |
|---|---|---|---|---|---|---|
| A. Person only (official baseline) | 0.667 | 0.211 | 0.807 | 0.480 | 0 | 0 |
| B. + whole-person aliases (conf>=0.4) | 0.384 | 0.257 | 0.679 | 0.499 | 14 | 93 |
| C. + person subparts (conf>=0.4) | 0.332 | 0.257 | 0.642 | 0.499 | 14 | 125 |
| D. aliases, conf>=0.25 | 0.332 | 0.314 | 0.618 | 0.521 | 31 | 159 |
| D. aliases, conf>=0.4 (=B) | 0.384 | 0.257 | 0.679 | 0.499 | 14 | 93 |
| D. aliases, conf>=0.6 | 0.545 | 0.218 | 0.769 | 0.483 | 2 | 23 |
| D. aliases, conf>=0.8 | 0.640 | 0.211 | 0.800 | 0.480 | 0 | 4 |

(Note: counterfactual B recovers 14 GTs via global greedy re-matching, vs. 13 in the per-box primary-category tally in Section 1 — an expected, minor, and documented discrepancy: Section 1's classification is a per-box LOCAL decision tree, while the counterfactual is a GLOBAL re-match across the whole dataset, which can occasionally resolve one additional case differently, e.g. a candidate that lost a local tie in the per-box analysis but wins the global greedy assignment.)

## 6. Answers to the verification questions

1. **How many missed people were localized correctly but labeled differently?** 13 (5.4%) under the rigorous per-box classification; 14 under the global counterfactual re-match. Both far below the informal 35.1%.
2. **Which alternate labels account for the most recoverable misses?** Man (10) >> Boy (2) > Woman (1). No subpart class ever wins.
3. **Are Man/Woman predictions genuinely equivalent detections, or do they introduce meaningful FPs?** They introduce SUBSTANTIAL false positives when accepted as Person: counterfactual B recovers only 14 GTs but introduces 93 new false positives — Person precision collapses from 0.667 to 0.384, and hazard-level precision drops 0.128 (0.807→0.679), which fails the standard guardrail (baseline−0.05) by a wide, non-noisy margin (violation margin 0.0785). They are NOT clean equivalents.
4. **Are subpart classes useful evidence, or too noisy?** Too noisy, empirically confirmed: counterfactual C recovers ZERO additional GTs beyond B (`recovered_gts_beyond_B: 0`) while adding 32 MORE false positives (125 vs. B's 93) — subpart boxes (Human hand/face/etc.) are typically far smaller than a full-body GT box and essentially never clear the 0.5 IoU match threshold against it; when a subpart candidate does clear a spatial floor somewhere, it is a spurious co-occurrence rather than a recoverable Person miss.
5. **Does semantic remapping recover recall substantially while preserving precision?** No. B recovers +4.6pp Person recall (0.211→0.257) at the cost of −28.3pp Person precision (0.667→0.384) and −12.8pp hazard precision (0.807→0.679). The confidence-floor sweep (D) confirms there is no rescuing sweet spot: at conf>=0.6 the FP cost shrinks to 23 but so does the recovered-GT count (2); at conf>=0.8, recovery is 0 gained for 4 new FPs. Recall gain and precision cost move together at every point on this curve — there is no honest way to present the recall gain without the FP cost, and the FP cost dominates at every setting that recovers meaningful recall.
6. **Is the ~35% confusion figure still correct under more rigorous IoU-based matching?** No — see Section 3. It drops to 5.4% (13/239) once a genuine confidence floor and bug-free per-box scoping are applied. The apparent "35%" was mostly localization noise and below-floor confidence signal, not genuine class confusion.
7. **Does the conclusion hold separately for small vs. non-small Person instances?** No — see Section 4. Semantic confusion is a real, if still modest, phenomenon for non-small instances (11.6%) and nearly disappears for small ones (2.0%). The overall conclusion (remapping doesn't pay off) holds in aggregate and for both subgroups on the precision-cost side, but the "how much genuine confusion exists" breakdown differs materially by size.

## Caveats / unresolved methodological issues

- Category C's diagnostic confidence floor (0.4, matching production) is a genuine methodological CHOICE, not a ground truth — a lower floor (e.g. the task spec's suggested alternative) would move some LOCALIZATION_FAILURE cases into SEMANTIC_CLASS_CONFUSION. The 5.4% figure is specifically "confusion the model would have surfaced at the real production threshold," not "any hint of a different label at any confidence" (which is closer to the old 35.1%, now understood to conflate several distinct phenomena).
- The 13-vs-14 discrepancy between the per-box classification and the global counterfactual re-match (Section 5's parenthetical) is expected given the two algorithms operate at different scopes (local decision tree vs. global greedy matching) — flagged explicitly rather than silently reconciled.
- Person-subpart classes were verified present in the live model (`benchmark/diagnostics/human_class_map.py::verify_against_model`), but "Human beard" was checked and confirmed ABSENT from this model's 601-class list — a task-spec candidate class deliberately excluded, not an oversight.
