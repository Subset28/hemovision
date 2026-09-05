# Open Questions

> Read `research/memory/README.md` first.

## Literature-grounded hypothesis generation — future work

`research/literature/` is deliberately near-empty at Phase C seed time.
Experiments in this phase are seeded from already-verified local findings
(Phase B/B.5 baseline data), not literature-driven hypotheses, because the
Researcher LLM role has no live API key in this environment
(`OPENROUTER_API_KEY` unset — see `.env.example`, `research/llm/`). Once a
real key exists, the Researcher role should read `research/literature/*` and
propose hypotheses grounded in externally-verified claims (via WebFetch/
WebSearch, never training-data recall alone) — this is not started.

## Unresolved from Phase B/B.5

- Does Person recall degrade differently for small-vs-occluded-vs-confused
  causes when analyzed independently (deconfounded)? Open Images'
  `IsOccluded` binary flag cannot support this on its own — EXP-0003 (class
  confusion) and a possible future EXP targeting occlusion severity
  specifically would help, but neither fully resolves it.
- Real on-device (ANE/CoreML) latency for any candidate change — nothing in
  this lab can answer this without a Mac + physical iPhone
  (`REQUIRES_MAC`/`REQUIRES_IPHONE` validation_requirement in
  `research/experiment_registry.py`).
- Whether YOLO26n (referenced in commit history, never actually shipped —
  see `OMNISIGHT_ARCHITECTURE.md` section 3) would improve Person/Stairs
  recall — EXP-0005 is BLOCKED pending evidence from 0002-0004 that model
  capacity/architecture, not thresholding/preprocessing/class-confusion, is
  the limiting factor.
- Whether the human-collected OmniSight-specific dataset
  (`docs/DATASETS.md` Section 8) would change any of these findings — Open
  Images V7 is explicitly documented as not representative of real
  accessibility-usage conditions.

## EXP-0004 (2026-09-05T00:48:38.175398+00:00)

- Family: preprocessing
- Status: INCONCLUSIVE
- Hypothesis: A single, simple image preprocessing transform (contrast/sharpening/CLAHE) applied before inference improves difficult Person detection without unacceptable latency cost.
- Reasons: primary metric 'person.recall' delta (+0.0198) is below the minimum meaningful delta (0.03)
