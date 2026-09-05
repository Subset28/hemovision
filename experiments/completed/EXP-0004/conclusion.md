# EXP-0004 — Conclusion

**Final status**: INCONCLUSIVE

**Raw evaluation-policy verdict**: INCONCLUSIVE

**Notes**: Real inference re-run (2 passes: conf=0.4 official + conf=0.01 diagnostic capture) for 5 pre-registered candidates over the full 380-image eval manifest, same weights/imgsz=640/iou=0.7/manifest as the canonical baseline — preprocessing was the ONLY changed variable per candidate. Identity/no-op control exactly reproduced the official baseline (correctness check passed). Representative candidate for this experiment's stored DB verdict: 'gamma' (selection rule: best person.recall delta among candidates clearing all guardrails; falls back to numerically-best-regardless if none clear — see research/_exp0004_preregister.py). Every candidate's own metrics/verdict are recorded in results.json['per_candidate_verdicts'] and reports/baseline/person_preprocessing_analysis.md regardless of which one is representative. 380 static images, no video/tracking/LiDAR/TTS/real-camera processing — this is a Windows/CUDA, static-image, offline measurement only.

**Reasoning**:
- primary metric 'person.recall' delta (+0.0198) is below the minimum meaningful delta (0.03)
