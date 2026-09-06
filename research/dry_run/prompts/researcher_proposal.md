# Dry-run researcher proposal prompt (Phase H)

{system_policy}

## Dry-run-specific instructions (read carefully — these OVERRIDE anything
## that would otherwise imply real execution)

- This is a DRY RUN. Your proposal will NOT be executed, queued, or run
  against the benchmark. No experiment branch will be created. No
  benchmark evaluation will happen as a result of anything you write.
- Do NOT report any empirical result, metric value, or outcome as if it were
  observed — you have no ability to run anything, so any such claim would be
  fabricated. Every metric field you produce is a PRE-REGISTERED plan
  (what will be measured), never an observed number.
- Do NOT set, imply, or reference any human-authority approval flag —
  you have no field for one in the required JSON schema below, and any
  extra field you add matching one of Phase F's 7 approval-flag names will
  cause your entire response to be rejected.
- You must pick exactly ONE unresolved problem from the candidate list
  below and explain your choice with evidence from the context packet, not
  just assert it.
- Your hypothesis must be falsifiable, cite prior evidence record IDs from
  the context packet, name a target failure bucket, and state a mechanism —
  vague claims ("this should help") are not acceptable.
- Before finalizing, check your own proposal's family + independent
  variable against the context packet's "rejected_directions" list. If your
  proposed direction is substantially the same as an already-rejected one
  (lower confidence threshold, higher input resolution, broad person-class
  remapping, generic pixel preprocessing, or simply a bigger checkpoint of
  the same architecture/vocabulary), you MUST either propose something
  genuinely different, or explicitly set `acknowledges_rejected_hypothesis_ids`
  to the relevant EXP-XXXX/MEM-XXXX id(s) and give a `materially_new_rationale`
  explaining what is different this time. A deterministic local checker will
  independently verify this — it is not optional and cannot be talked around.
- `dataset_version`, `model_config_ref`, `isolation_requirements`,
  `reproducibility_requirements`, `implementation_scope`,
  `expected_artifacts`, `compute_resource_estimate` are REQUIRED. For each:
  give a real, concrete value if you actually know one, or state an
  explicit blocking prerequisite/limitation sentence if you do not (e.g.
  "PREREQUISITE: training manifest does not yet exist and must be
  constructed before this dataset_version can be assigned"). A bare
  placeholder ("TBD", "unknown", "N/A", "none", "...") is REJECTED by a
  deterministic local checker — it is indistinguishable from not having
  thought about the field at all. Do not fabricate a checkpoint hash,
  dataset version string, or resource-usage number that doesn't actually
  exist yet — an honest, explicit "not yet known, here's why and what would
  resolve it" is always acceptable; a plausible-looking invented value is
  never acceptable.
  - `isolation_requirements`: your deterministic train/eval isolation
    requirement — what exact check (e.g. image-ID hash exclusion against
    which manifest) would guarantee zero train/eval overlap.
  - `compute_resource_estimate`: a proposal-stage JSON object estimate
    (e.g. `{{"gpu": "RTX 3070 Ti", "estimated_gpu_hours": 6}}`), never a
    fabricated measured value.
  - `expected_artifacts`: list of expected output file names/paths this
    experiment would produce if executed.

## Candidate unresolved problems (pick exactly one)

- TRUE_DETECTOR_MISS: the model simply never emits any Person detection with
  sufficient overlap for a given ground truth.
- Low-confidence Person detections that fall below the production threshold.
- Localization failures (detection present but IoU too low to count as a match).
- Small/distant-person misses.
- Training-data / representation gaps in the underlying model's training set.
- Temporal/video evidence — using multiple frames rather than a single image.
- Tracking-assisted recovery of a miss using neighboring frames.
- OmniSight-specific evaluation data collection (closing a measurement gap,
  not an inference-time knob).
- Accessibility-specific application-level decision logic (e.g. what the app
  DOES with a given detection/confidence, downstream of the detector).

## Context packet (read-only, compact — this is your only source of prior
## evidence; do not assume any fact not stated here)

```json
{context_packet_json}
```

## Required output format

Respond with ONE JSON object and nothing else (no markdown fences, no prose
outside the JSON). Required fields:

```
{{
  "selected_problem": "...",
  "selection_rationale": "...",
  "title": "...",
  "family": "one of: threshold_postprocessing | class_confusion | small_object | preprocessing | model_variant | training_data | temporal_pipeline | application_decision_logic",
  "research_question": "...",
  "hypothesis": "...",
  "motivation": "...",
  "independent_variables": ["..."],
  "dependent_variables": ["..."],
  "control_condition": "...",
  "baseline_comparison": "...",
  "success_criteria": {{"primary_metric": "person.recall", "min_meaningful_delta": 0.03}},
  "supports_hypothesis_if": "...",
  "rejects_hypothesis_if": "...",
  "inconclusive_if": "...",
  "evidence_references": ["MEM-XXXX", "..."],
  "prior_experiment_ids": ["EXP-XXXX", "..."],
  "controlled_variables": {{}},
  "procedure": "...",
  "production_impact": false,
  "production_impact_description": "...",
  "data_privacy_classification": "NONE",
  "external_api_required": false,
  "mac_iphone_required": false,
  "coreml_replacement_required": false,
  "signing_distribution_change_required": false,
  "acknowledges_rejected_hypothesis_ids": [],
  "materially_new_rationale": "",
  "dataset_version": "... (real value, or an explicit blocking-prerequisite sentence)",
  "model_config_ref": "... (real value, or an explicit blocking-prerequisite sentence)",
  "implementation_scope": "...",
  "expected_artifacts": ["..."],
  "reproducibility_requirements": "...",
  "isolation_requirements": "...",
  "compute_resource_estimate": {{"gpu": "...", "estimated_gpu_hours": 0}}
}}
```
