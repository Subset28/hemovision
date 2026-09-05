# EXP-0003 — Conclusion

**Final status**: FAILED

**Raw evaluation-policy verdict**: FAILED

**Notes**: Diagnostic/measurement-only experiment — no production code or config changed. 'Candidate' metrics here are counterfactual B (whole-person alias set accepted as Person at IoU>=0.5, confidence>=0.4) — the most direct scoring-time realization of the hypothesis. Counterfactuals A (restated baseline), C (+subparts), and D (confidence-floor sweep) are computed and fully reported in analysis.md / reports/baseline/person_class_confusion_analysis.md but not themselves fed into this pass/fail check. The standard hazard guardrails (precision/recall floors, latency, sample-size floors) are applied UNMODIFIED, per the EXP-0003 spec's instruction not to loosen the evaluation policy for a diagnostic-shaped experiment — a hard guardrail violation here means a real evidence-based FAILED verdict, not an INCONCLUSIVE hand-wave and not a forced PASSED.

**Reasoning**:
- guardrail 'hazard.precision' violated: 0.6785 does not satisfy gte 0.7570 (hazard precision must not drop more than 0.05 below baseline)

## Forward-looking assessment (opinion only — not a decision to act on)

Genuine SEMANTIC_CLASS_CONFUSION is real but modest (5.4% of Person FNs, 13/239, dominated by
Man/Boy/Woman) and does not survive as a viable postprocessing/class-remapping fix — every
counterfactual that exploits it costs more hazard-level precision than the recall it recovers, and no
confidence floor rescues that tradeoff. Postprocessing/class-remapping along these lines should NOT be
pursued further as-is. The dominant categories are TRUE_DETECTOR_MISS (38.5%) and LOW_CONFIDENCE_PERSON
(34.3%) — LOW_CONFIDENCE_PERSON is already known (EXP-0001) to be unfixable by simple thresholding
without a precision collapse, and TRUE_DETECTOR_MISS is consistent with EXP-0002's finding that raising
input resolution alone did not move Person recall. Taken together, EXP-0001/0002/0003 all point AWAY
from postprocessing-only and resolution-only fixes and toward the detector's underlying representational
capacity being the binding constraint (small/occluded/low-confidence true misses, not a labeling
artifact) — which is suggestive of, but does not itself justify or unblock, EXP-0005 (model_variant).
EXP-0005 remains BLOCKED per explicit task instruction regardless of this trend. EXP-0004
(preprocessing) is a comparatively lower-cost next step than EXP-0005 and has not been ruled out by any
evidence gathered here.
