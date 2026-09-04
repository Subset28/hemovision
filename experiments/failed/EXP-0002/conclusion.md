# EXP-0002 — Conclusion

**Final status**: FAILED

**Raw evaluation-policy verdict**: FAILED

**Notes**: Real inference re-run at imgsz=960 (candidate) vs the canonical imgsz=640 baseline, same model weights/conf/iou/manifest. This is an inference-time-only resolution change — benchmark/config.py's real IMGSZ=640 is unchanged.

**Reasoning**:
- guardrail 'hazard.recall' violated: 0.4491 does not satisfy gte 0.4604 (hazard recall must not drop more than 0.02 below baseline)
