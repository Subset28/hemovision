# EXP-0001 — Conclusion

**Final status**: PASSED

**Raw evaluation-policy verdict**: FAILED

**Notes**: Confirmatory/control experiment. Evidence source: benchmark\results\diagnostics\threshold_sweep.json. Compares the canonical baseline (conf=0.4) against the same model/weights/manifest evaluated at conf=0.05 (a real captured configuration, not a hypothetical). No new inference was run; no benchmark/config.py values were changed.

**Reasoning**:
- guardrail 'hazard.precision' violated: 0.3814 does not satisfy gte 0.7570 (hazard precision must not drop more than 0.05 below baseline)
