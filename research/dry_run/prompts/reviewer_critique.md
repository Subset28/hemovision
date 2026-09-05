# Dry-run reviewer critique prompt (Phase H)

{system_policy}

## Dry-run-specific instructions

- This is a DRY RUN. The proposal you are reviewing will NOT be executed.
  Nothing you say can approve it for execution, set a research verdict, or
  grant any human-authority approval flag — you have no field for any of
  those in the required JSON schema below, and any extra field matching a
  Phase F approval-flag name or a result field (metrics/research_verdict/
  verdict/...) will cause your entire response to be rejected.
- Your role is critique, not decision. A human (and the deterministic local
  validator) makes the actual queue-eligibility call.

## Proposal under review

```json
{proposal_json}
```

## Context packet (same one the proposer saw)

```json
{context_packet_json}
```

## What to assess

- Novelty vs. EXP-0001 through EXP-0005 (already-tested directions).
- Scientific validity of the hypothesis and mechanism.
- Whether the mechanism targets a verified failure mode from the context
  packet, or an unverified assumption.
- Whether the success criteria are deterministic/machine-checkable.
- Likely confounding variables.
- Whether the available dataset can actually answer the research question.
- Sample-size adequacy for the target failure bucket.
- Benchmark/test-data leakage risk.
- Privacy/safety boundary respect.
- Feasibility given the family's typical scope.
- Your overall judgment of whether this is worth running.

## Required output format

Respond with ONE JSON object and nothing else. Required fields:

```
{{
  "novelty_assessment": "...",
  "scientific_validity_assessment": "...",
  "targets_verified_failure_mode": true,
  "success_criteria_deterministic": true,
  "confounding_notes": "...",
  "dataset_can_answer_question": true,
  "sample_size_adequate": true,
  "leakage_risk_notes": "...",
  "privacy_safety_ok": true,
  "feasibility_notes": "...",
  "worth_running": true,
  "recommends_revision": false,
  "revision_notes": "",
  "summary": "..."
}}
```
