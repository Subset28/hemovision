# OmniSight Autonomous Research Lab — Implementation Plan (Phase A Deliverable)

Covers what exists, what's missing, what to build, where each piece runs, and recommended order. Windows PC = compute node; M4 Mac mini = build/device-validation node. Lab lives in a **separate directory** (`OmniSight-Lab`), never mixed into this production repo.

## 1. What Already Exists (reusable)

| Asset | Location | Reusable for |
|---|---|---|
| `BenchmarkSession.swift` / `PerformanceMonitor.swift` | `ios/OmniSightApp` | Data source for device benchmark — already emits frame latency p50/p95, tracker events, TTS suppression ratios. Extend to persist JSON; don't rebuild. |
| `DecisionLog.swift` | `ios/OmniSightApp` | Audit trail of TTS decisions — reusable for device-benchmark TTS-latency aggregation. |
| `docs/system_overview.md` | repo root | Accurate, pre-existing failure-mode/latency-budget documentation — direct input to benchmark robustness categories and hypothesis generation, not something to regenerate. |
| `ScanningData.mlpackage` | `ios/OmniSightApp` | The actual model under test — source of truth for Windows model benchmarking (export/convert as needed for PyTorch/ONNX/coremltools). |
| `ios/fastlane/Fastfile` | `ios/fastlane` | Existing build/beta/submit pipeline — device validation should call into this (build lane only), never touch submit/release/bump_build lanes. |
| Git repo itself | — | Isolation mechanism (`experiment/EXP-XXXX` branches) already available, no tooling needed beyond scripting branch creation. |

## 2. What's Missing (must be built)

- Any evaluation dataset (public/synthetic, licensed, non-PII) — nothing exists.
- Any accuracy/mAP measurement pipeline — `BenchmarkSession` is UX/perf-only.
- Experiment database (SQLite schema per master spec Phase 3).
- Experiment directory structure (`experiments/{queued,active,completed,rejected,failed}`).
- Research memory files (`research_memory/*.md`).
- LLM abstraction layer (OpenRouter routing, role-based model config).
- Orchestrator (queue, Git branch automation, resource limits, retries).
- Objective/acceptance-criteria config (deterministic accept/reject).
- `omnilab` CLI (status/pause/resume/stop, dry-run, run).
- Mac-side build/validation bridge (Windows → Git → Mac → Xcode → results → Windows DB).
- Reporting (daily/weekly markdown + figures).
- Test target for OmniSight itself does **not** exist — out of this lab's scope to add unilaterally; note it as a gap but do not create one without explicit approval (it touches production code).

## 3. Machine/Runtime Allocation

| Component | Runs on | Notes |
|---|---|---|
| Windows model benchmark (`benchmark.run`) | Windows (RTX 3070 Ti) | Model inference outside the app — PyTorch/ONNX/coremltools |
| Experiment DB, orchestrator, research memory, reporting | Windows | Pure Python/SQLite, no iOS dependency |
| LLM calls (OpenRouter) | Windows (network call out) | Never sends real user photos/PII — synthetic/public data only |
| Device benchmark execution | **Mac mini + physical iPhone** | ARKit/LiDAR/TTS/thermal/battery cannot be simulated or run on Windows |
| `xcodebuild`/`simctl`/`devicectl` | **Mac mini** | Requires Xcode; feasibility of `devicectl` automation unconfirmed — first task on Mac side |
| Git branch creation/experiment code changes | Windows (writes), Mac (pulls to build/validate) | Windows never runs `xcodebuild` directly |
| App Store submission, signing, production merges | **Human only** (user) | Never automated, per Absolute Rules #1, #9 |

## 4. Recommended Build Order (maps to master spec's Implementation Order)

1. **Phase B — Baseline benchmark (Windows)**: source/construct an eval dataset first (blocking dependency for everything downstream); implement `benchmark.run` per `BENCHMARK_PLAN.md`.
2. **Phase C — Experiment database**: SQLite schema, minimal CRUD, no automation yet.
3. **Phase D — Failure analysis**: consumes Phase B's output; categorize against `system_overview.md`'s known failure modes first, let data suggest refinements.
4. **Phase E — Research memory**: seed `failure_modes.md` from Phase D + `system_overview.md`; seed `discoveries.md` empty.
5. **Phase F — Experiment schema/directory**: `experiments/` structure, per-experiment file templates.
6. **Phase G — LLM abstraction**: OpenRouter client, role config, `.env.example`, usage tracking (40 calls/day default).
7. **Phase H — Dry-run agent**: propose experiments, write records, explain intended changes — no code modification.
8. **Phase I — Autonomous loop**: only after several dry-run experiments are manually reviewed and look sane.
9. **Phase J — Resource management**: `omnilab status/pause/resume/stop`, GPU/CPU/VRAM/RAM monitors.
10. **Phase K — Reporting**: daily/weekly markdown, real numbers only.
11. **Phase L — Mac/iOS device validation bridge**: only after Windows-side loop is stable; first confirm `xcodebuild`/`devicectl` actually work on this hardware before building automation around them.
12. **Phase M — Long-running mode**: last, gradual limit increases per Phase 27/28.

Do not skip ahead — each phase gates the next per master spec.

## 5. Estimated Complexity

| Phase | Complexity | Why |
|---|---|---|
| B (baseline benchmark) | High | No dataset, no eval pipeline exists — full ground-up build, plus dataset sourcing/licensing work |
| C (DB) | Low | Standard SQLite schema |
| D (failure analysis) | Medium | Clustering/categorization logic, but grounded in existing docs |
| E (research memory) | Low | Markdown files, mostly process discipline |
| F (experiment schema) | Low | Directory conventions + templates |
| G (LLM abstraction) | Medium | Router + quota tracking, needs to be provider-agnostic (models will rotate) |
| H (dry-run agent) | Medium-High | First real LLM-driven reasoning component |
| I (autonomous loop) | High | Full OBSERVE→...→NEXT loop, resumability, state recovery |
| J (resource mgmt) | Medium | OS-level monitoring (GPU via nvidia-smi, etc.) |
| K (reporting) | Low-Medium | Aggregation + markdown/plot generation from DB |
| L (Mac/iOS bridge) | High, uncertain | `devicectl` automation feasibility unknown; may require significant manual-step fallback |
| M (long-run mode) | Low | Mostly wiring/limits once I-K are stable |

## 6. Risks

- **No eval dataset**: the single biggest blocker — everything downstream (baseline, acceptance criteria, hard-negative mining) depends on it. Must be resolved before Phase B can produce trustworthy numbers.
- **YOLOv8m→YOLO26n ambiguity**: the repo's own commit history claims a swap that didn't happen. The lab's first "experiment" candidates will likely be exactly this swap — good first real experiment, but must not be assumed pre-validated.
- **`devicectl` automation uncertainty**: Phase L could be far more manual than the spec's ideal flow if device automation isn't fully scriptable — plan for a manual-trigger fallback from day one rather than assuming full automation.
- **iOS deployment-target mismatch** (16 vs 17.6): could affect which physical devices are valid for device benchmarking — resolve/confirm before building device-benchmark tooling around a specific target.
- **Production safety**: lab must never write into `ios/` directly outside of an `experiment/EXP-XXXX` branch, and never touch `ios/fastlane/Fastfile`'s beta/submit/release lanes.

## 7. Privacy Concerns

- No real user photos, faces, voices, or app telemetry may be sent to OpenRouter/cloud LLMs — Absolute Rule #6.
- Eval dataset for Phase B must be public/synthetic/self-created and appropriately licensed (Open Images V7 itself, being the model's training source, is a candidate for held-out eval slices if license terms allow — verify before using).
- `GoogleService-Info.plist` (Firebase keys) must never be exposed to the autonomous agent's file access — exclude from any context/sandbox the lab builds.

## 8. Directory Layout

```
C:\Projects\OmniSight          (or wherever this repo lives — production, read-only to the lab except via experiment branches)
C:\Projects\OmniSight-Lab      (new — all lab machinery: benchmark/, experiments/, research_memory/, agent/, reports/, omnilab CLI, SQLite DB)
```

The lab repo references the OmniSight repo as an external path/submodule-like dependency, not a copy — experiments operate via Git branches inside the actual OmniSight repo, orchestrated from the lab.

## 9. Next Step

Per master spec: **STOP here.** Do not begin Phase B until explicitly approved.
