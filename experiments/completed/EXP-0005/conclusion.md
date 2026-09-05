# EXP-0005 — Conclusion

**Execution status**: COMPLETED

**Research verdict**: INCONCLUSIVE

**Raw evaluation-policy verdict**: INCONCLUSIVE

**Notes**: Real inference re-run (2 passes: conf=0.4 official + conf=0.01 diagnostic capture) for 4 pre-registered model-checkpoint candidates over the full 380-image eval manifest, imgsz=640/iou=0.7 held constant, same manifest as the canonical baseline -- the model checkpoint/architecture was the ONLY changed variable per candidate. Candidate C (yolo11m, COCO-trained) required the COCO<->OIV7 common-class mapping (Stairs excluded, structurally absent from COCO); Person is directly comparable across all 4 candidates. Representative candidate for this experiment's stored DB verdict: 'D_yolov8l_oiv7_diagnostic_upper_bound' (selection rule: best fixed-conf=0.4 person.recall delta among candidates clearing all guardrails; falls back to numerically-best-regardless if none clear -- see research/_exp0005_preregister.py). Every candidate's own metrics/verdict/failure-bucket transitions/precision-matched sweep are recorded in model_comparison.json and person_transitions.json regardless of which one is representative. 380 static images, Windows/CUDA proxy hardware, no CoreML/ANE execution -- this is a Windows/CUDA, static-image, offline measurement only. No production model was replaced; ios/ was never touched.

**Reasoning**:
- primary metric 'person.recall' delta (+0.0198) is below the minimum meaningful delta (0.03)
