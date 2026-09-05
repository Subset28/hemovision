"""Phase H — dry-run research agent pipeline tests. Every LLM response here
is MOCKED (research/llm/base.py::LLMProvider fake, no network) — the
repo-wide socket guard in tests/conftest.py would refuse a real call anyway.
"""

from __future__ import annotations

import json

import pytest

from research.db import OmniLabDB
from research.dry_run.budget import DryRunBudgetExceededError, DryRunCallBudget
from research.dry_run.pipeline import render_report, run_dry_run_cycle, write_artifacts
from research.llm.base import ErrorCategory, LLMProvider, LLMResponse, LLMUnavailableError, RunBudget
from research.llm.router import LLMRouter
from research.llm.structured_output import ValidationError

VALID_PROPOSAL = {
    "selected_problem": "small-person misses",
    "selection_rationale": "baseline shows a recall gap concentrated in small/distant persons",
    "title": "Temporal aggregation for small-person misses",
    "family": "temporal_pipeline",
    "research_question": "Does multi-frame aggregation recover small-person misses?",
    "hypothesis": "3-frame temporal aggregation recovers >=5% of small-person misses vs "
                  "single-frame baseline, because single-frame detection lacks motion cues "
                  "for small/distant persons.",
    "motivation": "Prior single-frame knobs were exhausted; this targets a structural gap.",
    "independent_variables": ["temporal_window_frames"],
    "dependent_variables": ["person.recall"],
    "control_condition": "single-frame baseline eval",
    "baseline_comparison": "RUN-20260904-002",
    "success_criteria": {"primary_metric": "person.recall", "min_meaningful_delta": 0.03},
    "supports_hypothesis_if": "recall improves >=0.03",
    "rejects_hypothesis_if": "recall improves <0.03",
    "inconclusive_if": "mixed guardrail results",
    "evidence_references": [],
    "prior_experiment_ids": [],
    "controlled_variables": {},
    "procedure": "run temporal aggregation offline on eval set",
    "production_impact": False,
    "production_impact_description": "",
    "data_privacy_classification": "NONE",
    "external_api_required": False,
    "mac_iphone_required": True,
    "acknowledges_rejected_hypothesis_ids": [],
    "materially_new_rationale": "",
}

VALID_REVIEW_NO_REVISION = {
    "novelty_assessment": "novel vs EXP-0001..0005",
    "scientific_validity_assessment": "plausible mechanism",
    "targets_verified_failure_mode": True,
    "success_criteria_deterministic": True,
    "confounding_notes": "none major",
    "dataset_can_answer_question": True,
    "sample_size_adequate": True,
    "leakage_risk_notes": "none",
    "privacy_safety_ok": True,
    "feasibility_notes": "feasible offline",
    "worth_running": True,
    "recommends_revision": False,
    "revision_notes": "",
    "summary": "worth running",
}

VALID_REVIEW_REQUESTS_REVISION = dict(VALID_REVIEW_NO_REVISION, recommends_revision=True,
                                       revision_notes="tighten the success criteria")


def _proposal_json(**overrides) -> str:
    d = dict(VALID_PROPOSAL)
    d.update(overrides)
    return json.dumps(d)


def _review_json(**overrides) -> str:
    d = dict(VALID_REVIEW_NO_REVISION)
    d.update(overrides)
    return json.dumps(d)


class QueueProvider(LLMProvider):
    """Returns queued (text, model) pairs in order, one per call, regardless
    of role/model requested. Raises LLMUnavailableError if the queue is
    empty (a 4th call attempted when only 3 were queued, say) or if a queued
    item is itself an exception instance."""

    def __init__(self, items: list):
        self.items = list(items)
        self.calls: list[tuple[str, str]] = []

    def complete(self, prompt: str, role: str, model: str = "", **kwargs) -> LLMResponse:
        self.calls.append((role, model))
        if not self.items:
            raise LLMUnavailableError("QueueProvider: no more queued responses (unexpected extra call)")
        item = self.items.pop(0)
        if isinstance(item, Exception):
            raise item
        return LLMResponse(text=item, tokens_used=10, cost_usd=0.0, model_used=model)


def _router(items: list) -> LLMRouter:
    # A fresh, isolated UsageTracker per router — the real, persisted
    # research/llm_usage.json is a SHARED file across the whole test session
    # (many other test modules exercise the default UsageTracker too); using
    # it here would let this file's calls silently deplete/be depleted by
    # unrelated tests' daily budget and make these tests order-dependent.
    import tempfile
    from pathlib import Path

    from research.llm.base import UsageTracker

    tracker_path = Path(tempfile.mkstemp(suffix=".json")[1])
    tracker = UsageTracker(path=tracker_path, max_per_day=1000)
    return LLMRouter(provider=QueueProvider(items), usage_tracker=tracker)


def _isolated_router(provider: LLMProvider) -> LLMRouter:
    """Same isolation rationale as `_router()` above, for tests that need a
    custom provider (not just a fixed response queue)."""
    import tempfile
    from pathlib import Path

    from research.llm.base import UsageTracker

    tracker_path = Path(tempfile.mkstemp(suffix=".json")[1])
    return LLMRouter(provider=provider, usage_tracker=UsageTracker(path=tracker_path, max_per_day=1000))


def _experiments_row_count() -> int:
    with OmniLabDB() as db:
        return len(db.list_experiments())


# ---------------------------------------------------------------------------
# Happy path / ordering
# ---------------------------------------------------------------------------


class TestHappyPath:
    def test_full_cycle_two_calls_no_revision(self):
        router = _router([_proposal_json(), _review_json()])
        result = run_dry_run_cycle(router=router, authorized=True, dry_run_budget=DryRunCallBudget(3))
        assert result.calls_made == 2
        assert result.stopped_reason == ""
        assert result.proposal is not None
        assert result.reviewer_critique is not None
        assert result.revised is False
        assert result.final_validation is not None

    def test_memory_loaded_before_any_llm_call(self, monkeypatch):
        """Order-of-operations: generate_context_packet() must run before the
        first LLM call is attempted."""
        order: list[str] = []

        import research.dry_run.pipeline as pipeline_mod

        real_generate = pipeline_mod.generate_context_packet

        def spy_generate(db):
            order.append("context")
            return real_generate(db)

        monkeypatch.setattr(pipeline_mod, "generate_context_packet", spy_generate)

        class OrderingProvider(LLMProvider):
            def complete(self, prompt, role, model="", **kwargs):
                order.append(f"llm:{role}")
                if role == "researcher":
                    return LLMResponse(text=_proposal_json(), tokens_used=1, cost_usd=0.0, model_used=model)
                return LLMResponse(text=_review_json(), tokens_used=1, cost_usd=0.0, model_used=model)

        router = _isolated_router(OrderingProvider())
        run_dry_run_cycle(router=router, authorized=True, dry_run_budget=DryRunCallBudget(3))
        assert order[0] == "context"
        assert order[1] == "llm:researcher"

    def test_rejected_hypothesis_context_included_in_prompt(self):
        """The context packet passed to the researcher LLM call must include
        the rejected_directions list (inspect the constructed prompt)."""
        captured = {}

        class CapturingProvider(LLMProvider):
            def complete(self, prompt, role, model="", **kwargs):
                if role == "researcher" and "researcher" not in captured:
                    captured["researcher"] = prompt
                    return LLMResponse(text=_proposal_json(), tokens_used=1, cost_usd=0.0, model_used=model)
                return LLMResponse(text=_review_json(), tokens_used=1, cost_usd=0.0, model_used=model)

        router = _isolated_router(CapturingProvider())
        run_dry_run_cycle(router=router, authorized=True, dry_run_budget=DryRunCallBudget(3))
        prompt = captured["researcher"]
        assert "rejected_directions" in prompt
        assert "EXP-0001" in prompt  # a real rejected-hypothesis experiment id must appear


# ---------------------------------------------------------------------------
# Redundancy rejection — the 5 exact redundant directions.
# ---------------------------------------------------------------------------


class TestRedundancyRejection:
    @pytest.mark.parametrize(
        "family,independent_variables",
        [
            ("threshold_postprocessing", ["confidence_threshold lowered to 0.1"]),
            ("small_object", ["increase input resolution / imgsz to 960px"]),
            ("class_confusion", ["broad Man/Woman/Boy/Girl remapping to Person at scoring time"]),
            ("preprocessing", ["generic CLAHE preprocessing transform before inference"]),
            ("model_variant", ["simply use a bigger YOLO checkpoint / model architecture"]),
        ],
    )
    def test_redundant_proposal_rejected_without_retry_budget(self, family, independent_variables):
        """Mocked LLM output literally proposes each of the 5 already-
        rejected directions, with acknowledges_rejected_hypothesis_ids left
        empty. Budget of 1 (no room for a retry) proves the deterministic
        check fires and the pipeline surfaces rejection rather than passing
        the proposal through as if it were novel."""
        router = _router([_proposal_json(family=family, independent_variables=independent_variables)])
        result = run_dry_run_cycle(router=router, authorized=True, dry_run_budget=DryRunCallBudget(1))
        assert result.redundancy_rejected_initial is True
        assert result.redundancy_conflicts, "expected a detected conflict"
        assert "redundancy" in result.stopped_reason.lower()
        assert result.reviewer_critique is None  # never sent to the reviewer

    def test_redundant_proposal_with_bounded_retry_resolves(self):
        """With budget for a retry, a corrected 2nd proposal (with
        acknowledgment + rationale) proceeds to review."""
        router = _router([
            _proposal_json(family="threshold_postprocessing",
                            independent_variables=["confidence_threshold lowered to 0.1"]),
            _proposal_json(
                acknowledges_rejected_hypothesis_ids=["EXP-0001"],
                materially_new_rationale="this time we combine it with per-class calibration, not "
                                          "a global threshold change",
            ),
            _review_json(),
        ])
        result = run_dry_run_cycle(router=router, authorized=True, dry_run_budget=DryRunCallBudget(3))
        assert result.redundancy_rejected_initial is True
        assert result.calls_made == 3
        assert result.reviewer_critique is not None

    def test_acknowledged_redundancy_without_retry_needed(self):
        """A first proposal that ALREADY acknowledges the conflict + gives a
        rationale is not rejected at all — proceeds straight to review."""
        router = _router([
            _proposal_json(
                family="threshold_postprocessing",
                independent_variables=["confidence_threshold lowered to 0.1"],
                acknowledges_rejected_hypothesis_ids=["EXP-0001"],
                materially_new_rationale="combined with per-class calibration this time",
            ),
            _review_json(),
        ])
        result = run_dry_run_cycle(router=router, authorized=True, dry_run_budget=DryRunCallBudget(3))
        assert result.redundancy_rejected_initial is False
        assert result.calls_made == 2


# ---------------------------------------------------------------------------
# Malformed output handling
# ---------------------------------------------------------------------------


class TestMalformedOutput:
    def test_malformed_proposal_json_rejected_cleanly(self):
        router = _router(["not json at all"])
        result = run_dry_run_cycle(router=router, authorized=True, dry_run_budget=DryRunCallBudget(3))
        assert result.proposal is None
        assert "structured-output validation" in result.stopped_reason

    def test_malformed_reviewer_output_rejected_cleanly(self):
        router = _router([_proposal_json(), "{}"])  # reviewer output missing every required field
        result = run_dry_run_cycle(router=router, authorized=True, dry_run_budget=DryRunCallBudget(3))
        assert result.reviewer_critique is None
        assert "reviewer step failed" in result.stopped_reason
        # local validation must still be reported even though the reviewer step failed
        assert result.final_validation is not None


# ---------------------------------------------------------------------------
# Reviewer cannot set a verdict or grant an approval — structural tests.
# ---------------------------------------------------------------------------


class TestReviewerCannotActAsAuthority:
    def test_reviewer_response_field_names_exclude_verdict_and_approvals(self):
        from research.llm.structured_output import APPROVAL_FLAG_FIELDS, RESULT_ONLY_FIELDS, ReviewerCritique

        field_names = {f.name for f in ReviewerCritique.__dataclass_fields__.values()}
        assert not (field_names & APPROVAL_FLAG_FIELDS)
        assert not (field_names & RESULT_ONLY_FIELDS)
        assert "research_verdict" not in field_names
        assert "verdict" not in field_names

    def test_reviewer_json_smuggling_an_approval_flag_is_rejected(self):
        from research.llm.structured_output import ValidationError, parse_and_validate_reviewer_critique

        payload = dict(VALID_REVIEW_NO_REVISION)
        payload["production_swift_modification_approved"] = True
        with pytest.raises(ValidationError):
            parse_and_validate_reviewer_critique(json.dumps(payload))

    def test_reviewer_json_smuggling_a_verdict_is_rejected(self):
        from research.llm.structured_output import ValidationError, parse_and_validate_reviewer_critique

        payload = dict(VALID_REVIEW_NO_REVISION)
        payload["research_verdict"] = "PASS"
        with pytest.raises(ValidationError):
            parse_and_validate_reviewer_critique(json.dumps(payload))

    def test_proposal_json_smuggling_an_approval_flag_is_rejected(self):
        from research.llm.structured_output import ValidationError, parse_and_validate_proposal

        payload = dict(VALID_PROPOSAL)
        payload["mac_iphone_deployment_approved"] = True
        with pytest.raises(ValidationError):
            parse_and_validate_proposal(json.dumps(payload))

    def test_built_proposal_always_has_all_seven_approvals_false(self):
        """Even if somehow a ProposalResponse existed with extra attributes,
        _build_proposal hard-codes all 7 flags False — never derived from
        parsed content."""
        from research.dry_run.pipeline import _build_proposal
        from research.llm.structured_output import parse_and_validate_proposal

        pr = parse_and_validate_proposal(_proposal_json())
        proposal = _build_proposal(pr, "EXP-9001", "RUN-20260904-002")
        assert proposal.production_swift_modification_approved is False
        assert proposal.coreml_model_replacement_approved is False
        assert proposal.new_training_approved is False
        assert proposal.private_user_data_use_approved is False
        assert proposal.external_upload_approved is False
        assert proposal.mac_iphone_deployment_approved is False
        assert proposal.signing_distribution_change_approved is False


# ---------------------------------------------------------------------------
# Bounded revision loop.
# ---------------------------------------------------------------------------


class TestBoundedRevisionLoop:
    def test_reviewer_requests_revision_triggers_exactly_one_more_call(self):
        router = _router([
            _proposal_json(),
            _review_json(recommends_revision=True, revision_notes="tighten success criteria"),
            _proposal_json(success_criteria={"primary_metric": "person.recall",
                                              "min_meaningful_delta": 0.05}),
        ])
        result = run_dry_run_cycle(router=router, authorized=True, dry_run_budget=DryRunCallBudget(3))
        assert result.calls_made == 3
        assert result.revised is True
        assert result.revision_reason == "tighten success criteria"

    def test_reviewer_does_not_request_revision_no_third_call(self):
        """Explicit 'don't call unnecessarily': even with budget remaining,
        a reviewer that does not ask for revision must not trigger a 3rd
        call."""
        router = _router([_proposal_json(), _review_json(recommends_revision=False)])
        result = run_dry_run_cycle(router=router, authorized=True, dry_run_budget=DryRunCallBudget(3))
        assert result.calls_made == 2
        assert result.revised is False

    def test_never_a_fourth_step_even_if_revision_reviewer_wanted_more(self):
        """After a revision, the pipeline does not send the revised
        proposal back to the reviewer again — max 3 calls total, period."""
        router = _router([
            _proposal_json(),
            _review_json(recommends_revision=True, revision_notes="tighten"),
            _proposal_json(),
        ])
        result = run_dry_run_cycle(router=router, authorized=True, dry_run_budget=DryRunCallBudget(3))
        assert result.calls_made == 3
        # a 4th queued item would have raised if consumed; QueueProvider had none queued.


# ---------------------------------------------------------------------------
# Max external-call count enforcement.
# ---------------------------------------------------------------------------


class TestCallBudget:
    def test_fourth_call_refused_locally_no_network(self):
        """A budget of 3, exhausted by proposal+review+revision, refuses a
        conceptual 4th attempt before any network activity — proven here by
        constructing a DryRunCallBudget directly and checking it raises with
        zero calls made after exhaustion."""
        budget = DryRunCallBudget(max_calls=3)
        for _ in range(3):
            budget.check()
            budget.record()
        with pytest.raises(DryRunBudgetExceededError):
            budget.check()
        assert budget.calls_made == 3  # the refused check made no additional call

    def test_pipeline_never_exceeds_budget_even_when_reviewer_keeps_asking(self):
        router = _router([_proposal_json(), _review_json(recommends_revision=True, revision_notes="x"),
                           _proposal_json()])
        result = run_dry_run_cycle(router=router, authorized=True, dry_run_budget=DryRunCallBudget(3))
        assert result.calls_made <= 3

    def test_failed_call_still_counted_against_budget(self):
        router = _router([LLMUnavailableError("simulated provider failure")])
        result = run_dry_run_cycle(router=router, authorized=True, dry_run_budget=DryRunCallBudget(3))
        assert result.calls_made == 1
        assert "unavailable" in result.stopped_reason


# ---------------------------------------------------------------------------
# Local deterministic validation is authoritative, not the LLM's opinion.
# ---------------------------------------------------------------------------


class TestLocalValidationAuthoritative:
    def test_reviewer_says_great_but_local_validator_disagrees(self):
        """Proposal has mac_iphone_required=False while its family
        (temporal_pipeline) requires REQUIRES_IPHONE per the registry — the
        deterministic validator must flag this as an ERROR even though the
        mocked reviewer enthusiastically says everything is fine."""
        router = _router([
            _proposal_json(mac_iphone_required=False),
            _review_json(worth_running=True, scientific_validity_assessment="looks great, definitely valid"),
        ])
        result = run_dry_run_cycle(router=router, authorized=True, dry_run_budget=DryRunCallBudget(3))
        assert result.reviewer_critique.worth_running is True
        assert result.final_validation.is_valid is False
        assert any(i.code == "MAC_IPHONE_REQUIRED_MISMATCH" for i in result.final_validation.errors)


# ---------------------------------------------------------------------------
# Artifact — final report must be unmistakably marked non-executed.
# ---------------------------------------------------------------------------


class TestArtifactMarking:
    def test_report_contains_literal_dry_run_line(self):
        router = _router([_proposal_json(), _review_json()])
        result = run_dry_run_cycle(router=router, authorized=True, dry_run_budget=DryRunCallBudget(3))
        report_text = render_report(result)
        assert "DRY RUN ONLY — NOT EXECUTED" in report_text
        assert "Actually queued: NO" in report_text

    def test_write_artifacts_creates_expected_files_only(self, tmp_path, monkeypatch):
        import research.dry_run.pipeline as pipeline_mod

        monkeypatch.setattr(pipeline_mod, "DRY_RUN_PROPOSALS_DIR", tmp_path / "proposals")
        monkeypatch.setattr(pipeline_mod, "DRY_RUN_REPORTS_DIR", tmp_path / "reports")

        router = _router([_proposal_json(), _review_json()])
        result = run_dry_run_cycle(router=router, authorized=True, dry_run_budget=DryRunCallBudget(3))
        json_path, report_path = write_artifacts(result)

        assert json_path.exists()
        assert report_path.exists()
        data = json.loads(json_path.read_text(encoding="utf-8"))
        assert data["actually_queued"] is False
        assert data["artifact_type"] == "DRY_RUN_PROPOSAL"
        assert "DRY RUN ONLY" in report_path.read_text(encoding="utf-8")

    def test_report_filename_includes_dryrun_id_no_same_minute_collision(self, tmp_path, monkeypatch):
        """Regression test for a real bug hit during the Phase H completion
        retry: two dry-run attempts (DRYRUN-0003, DRYRUN-0004) landed in the
        same clock-minute and the old minute-only report filename
        (YYYY-MM-DD-HHMM.md) let the second overwrite the first's report --
        DRYRUN-0003's JSON survived but its rendered report was silently
        lost, violating "every dry-run attempt, including failed ones, stays
        historically inspectable." The filename must include dryrun_id."""
        import research.dry_run.pipeline as pipeline_mod

        monkeypatch.setattr(pipeline_mod, "DRY_RUN_PROPOSALS_DIR", tmp_path / "proposals")
        monkeypatch.setattr(pipeline_mod, "DRY_RUN_REPORTS_DIR", tmp_path / "reports")

        router1 = _router([_proposal_json(), _review_json()])
        result1 = run_dry_run_cycle(router=router1, authorized=True, dry_run_budget=DryRunCallBudget(3))
        _, report_path_1 = write_artifacts(result1)

        router2 = _router([_proposal_json(), _review_json()])
        result2 = run_dry_run_cycle(router=router2, authorized=True, dry_run_budget=DryRunCallBudget(3))
        _, report_path_2 = write_artifacts(result2)

        assert result1.dryrun_id != result2.dryrun_id
        assert report_path_1 != report_path_2, "two distinct dry-run reports must never share a filename"
        assert report_path_1.exists(), "the first report must survive the second write, even in the same minute"
        assert report_path_2.exists()
        assert result1.dryrun_id in report_path_1.name
        assert result2.dryrun_id in report_path_2.name


class TestStructuredOutputWiring:
    """Regression coverage for connecting run_dry_run_cycle's orchestration
    loop to research/llm/model_catalog.py's pre-flight gate and research/llm/
    structured_output.py's schema builders -- research/llm/openrouter.py's
    `_call_llm` choke point already accepted `model_catalog`/
    `require_structured_output`/`response_format`, but run_dry_run_cycle
    never forwarded them to any of its 4 call sites until this fix."""

    def test_default_call_omits_response_format_unchanged_behavior(self):
        """A caller that doesn't pass model_catalog/require_structured_output
        (every existing caller before this fix) must see byte-identical
        behavior -- no response_format kwarg reaches the provider."""

        class RecordingProvider(LLMProvider):
            def __init__(self, items):
                self.items = list(items)
                self.received_kwargs: list[dict] = []

            def complete(self, prompt, role, model="", **kwargs):
                self.received_kwargs.append(kwargs)
                item = self.items.pop(0)
                return LLMResponse(text=item, tokens_used=10, cost_usd=0.0, model_used=model)

        provider = RecordingProvider([_proposal_json(), _review_json()])
        router = _isolated_router(provider)
        run_dry_run_cycle(router=router, authorized=True, dry_run_budget=DryRunCallBudget(3))

        assert all(kw.get("response_format") is None for kw in provider.received_kwargs)
        assert all(kw.get("model_catalog") is None for kw in provider.received_kwargs)

    def test_structured_output_enabled_sends_distinct_schemas_per_role(self):
        """With require_structured_output=True + a permissive model_catalog,
        the researcher call must carry the proposal JSON schema and the
        reviewer call must carry the (distinct) reviewer JSON schema."""

        class RecordingProvider(LLMProvider):
            def __init__(self, items):
                self.items = list(items)
                self.calls: list[tuple[str, dict]] = []

            def complete(self, prompt, role, model="", **kwargs):
                self.calls.append((role, kwargs))
                item = self.items.pop(0)
                return LLMResponse(text=item, tokens_used=10, cost_usd=0.0, model_used=model)

        provider = RecordingProvider([_proposal_json(), _review_json()])
        router = _isolated_router(provider)
        permissive_catalog = {
            "test/model": {"pricing": {"prompt": "0", "completion": "0"}, "supported_parameters": ["response_format", "structured_outputs"]},
        }
        # Point both roles at the same permissive catalog entry for this test.
        for role_cfg in router._roles.values():
            role_cfg["preferred_model"] = "test/model"

        run_dry_run_cycle(
            router=router, authorized=True, dry_run_budget=DryRunCallBudget(3),
            model_catalog=permissive_catalog, require_structured_output=True,
        )

        researcher_calls = [kw for role, kw in provider.calls if role == "researcher"]
        reviewer_calls = [kw for role, kw in provider.calls if role == "reviewer"]
        assert researcher_calls and researcher_calls[0]["response_format"]["json_schema"]["name"] == "proposal_response"
        assert reviewer_calls and reviewer_calls[0]["response_format"]["json_schema"]["name"] == "reviewer_critique"
        assert (
            researcher_calls[0]["response_format"]["json_schema"]["schema"]
            != reviewer_calls[0]["response_format"]["json_schema"]["schema"]
        )

    def test_capability_gate_blocks_before_network_when_wired(self):
        """A catalog entry lacking response_format support must reject the
        call locally -- the mocked provider must never be invoked."""

        class SpyProvider(LLMProvider):
            def __init__(self):
                self.call_count = 0

            def complete(self, prompt, role, model="", **kwargs):
                self.call_count += 1
                raise AssertionError("provider.complete() must never be called for an incapable model")

        provider = SpyProvider()
        router = _isolated_router(provider)
        unsupported_catalog = {
            "test/model": {"pricing": {"prompt": "0", "completion": "0"}, "supported_parameters": []},
        }
        for role_cfg in router._roles.values():
            role_cfg["preferred_model"] = "test/model"

        result = run_dry_run_cycle(
            router=router, authorized=True, dry_run_budget=DryRunCallBudget(3),
            model_catalog=unsupported_catalog, require_structured_output=True,
        )

        assert provider.call_count == 0
        assert result.calls_made == 0
        assert "capabilit" in result.stopped_reason.lower() or "unavailable" in result.stopped_reason.lower()

    def test_failed_call_still_records_token_usage_and_actual_model(self):
        """Regression test for a second bug found alongside the openrouter.py
        ordering fix (Phase H token/reasoning audit, DRYRUN-0005):
        _call_llm's LLMUnavailableError handler built a CallRecord without
        ever reading diag.get("usage")/diag.get("model_used"), so even
        after openrouter.py started capturing usage on an empty-completion
        failure, the pipeline layer discarded it a second time. A failed
        call's CallRecord must carry whatever usage/model data the provider
        diagnostics actually contained."""

        class EmptyCompletionProvider(LLMProvider):
            def complete(self, prompt, role, model="", **kwargs):
                raise LLMUnavailableError(
                    "OpenRouter returned an empty completion",
                    category=ErrorCategory.EMPTY_RESPONSE,
                    diagnostics={
                        "http_status": 200,
                        "envelope_parsed": True,
                        "choices_present": True,
                        "message_present": True,
                        "content_present": False,
                        "content_length": 0,
                        "finish_reason": "length",
                        "model_used": "liquid/lfm-2.5-2.6b:free",
                        "request_id": "gen-test123",
                        "usage": {
                            "prompt_tokens": 1200, "completion_tokens": 2048,
                            "total_tokens": 3248, "reasoning_tokens": 2048,
                        },
                    },
                )

        router = _isolated_router(EmptyCompletionProvider())
        result = run_dry_run_cycle(router=router, authorized=True, dry_run_budget=DryRunCallBudget(3))

        assert len(result.call_records) == 1
        cr = result.call_records[0]
        assert cr.token_usage == {
            "prompt_tokens": 1200, "completion_tokens": 2048,
            "total_tokens": 3248, "reasoning_tokens": 2048,
        }
        assert cr.actual_model_returned == "liquid/lfm-2.5-2.6b:free"
        assert cr.finish_reason == "length"

    def test_failed_call_records_provider_error_message(self):
        """Regression test for a gap found via DRYRUN-0006 (Phase H
        token/reasoning audit follow-up): openrouter.py's
        _safe_error_body_fields() extracts OpenRouter's own human-readable
        error.message text into diagnostics["provider_error_message"], but
        CallRecord never had a field for it and _call_llm never copied it
        over -- so a 400 (or any HTTP error) with a genuinely explanatory
        message from OpenRouter was reduced to just a numeric status code,
        with no way to know WHY the request was rejected."""

        class HttpErrorProvider(LLMProvider):
            def complete(self, prompt, role, model="", **kwargs):
                raise LLMUnavailableError(
                    "OpenRouter HTTP error 400",
                    category=ErrorCategory.HTTP_ERROR,
                    diagnostics={
                        "http_status": 400,
                        "provider_error_code": 400,
                        "provider_error_message": "reasoning is not supported for this model",
                    },
                )

        router = _isolated_router(HttpErrorProvider())
        result = run_dry_run_cycle(router=router, authorized=True, dry_run_budget=DryRunCallBudget(3))

        assert result.call_records[0].provider_error_message == "reasoning is not supported for this model"
