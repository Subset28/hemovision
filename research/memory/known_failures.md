# Known Failures

> Read `research/memory/README.md` first.

Seeded from Phase B/B.5 findings (`reports/baseline/`, `docs/FAILURE_TAXONOMY.md`).

## Person recall — the dominant, highest-confidence finding

- Person: Recall=0.211 (GT=303 — largest hazard-class sample, high
  confidence). Precision=0.667. Model misses ~4 of 5 annotated Person boxes
  at the real conf=0.4 operating point.
- Failure breakdown of the 239 missed boxes (`reports/baseline/person_failure_analysis.md`):
  - 65.3% `IsOccluded=True` (but confounded with small+clutter — see below).
  - 64.0% box area < 2% of image (small/distant).
  - 41.8% had a same-class candidate below conf=0.4 (threshold-recoverable,
    at a real precision cost — see threshold sweep below).
  - 35.1% classification confusion — model predicted `Man`/`Woman`/`Human
    body`/`Clothing` at the same location instead of `Person`.
    **SUPERSEDED (Phase E)** — this informal figure counted any same-location
    alternate-class detection at any confidence, including near-zero noise.
    EXP-0003's rigorous IoU-based re-matching (confidence>=0.4, IoU>=0.5)
    found genuine SEMANTIC_CLASS_CONFUSION is only 13/239 = 5.4% of Person
    misses — see `reports/baseline/person_class_confusion_analysis.md` and
    the structured, queryable version of this correction in
    `research/memory.db` (`uv run python -m research.cli memory query
    person-failure-modes`), which marks the old 35.1% record
    `status=SUPERSEDED` and the new 5.4% record `status=ACTIVE`.
  - Only 6.3% had zero candidate at any confidence — most misses ARE
    "detected as something," just not a confident correct Person box.

## Threshold alone does not fix Person recall

- `benchmark/results/diagnostics/threshold_sweep.json`: conf=0.05 -> Person
  recall 0.211->0.479, but precision collapses 0.667->0.312. A real but
  partial, expensive lever — do NOT recommend lowering conf in production.

## Occlusion is confounded, not a clean independent cause

- `benchmark/results/diagnostics/occlusion_analysis.json`: of all
  occlusion-tagged failures, 56.0% are ALSO small (<2% area) and 88.7% are
  ALSO in a cluttered image (>8 boxes). `_classify_failure` checks occlusion
  first and returns immediately, so "occlusion dominates" should be read as
  "largest tagged category," not "proven independent cause."

## Thin-sample hazard classes — treat with explicit skepticism

- Stairs (GT=45), Truck (GT=42), Bus/Motorcycle (GT=49 each) are thin-sample.
  A swing of a handful of boxes moves their recall by ~10 points. Never
  present their numbers with Person/Car's implied statistical confidence.
  `research/evaluation_policy.py`'s `sample_size_floors` encodes this as an
  automatic INCONCLUSIVE downgrade.

## Latency proxy limitations

- Windows/CUDA latency (p50=18.0ms, p95=57.1ms in the current baseline) is an
  inference-only proxy. NOT iPhone ANE, NOT end-to-end, NOT device-validated.
  Any experiment claiming a latency win must carry this caveat forward.

## Production known-issues (from `docs/system_overview.md`, pre-existing)

- Seated-person distance overestimation.
- Glass/mirror LiDAR failure mode.
- Dense-crowd tracker ID churn.
