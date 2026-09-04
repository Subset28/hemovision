"""OmniSight evaluation benchmark — additive, non-production, read-only toward ios/.

This package is never imported by, or coupled to, the shipped iOS app. It exists to
measure the accuracy/latency of the already-shipped CoreML pipeline (YOLOv8m-OIV7)
against small, honestly-labeled evaluation datasets. See BENCHMARK_PLAN.md and
docs/DATASETS.md at the repo root for full context.
"""
