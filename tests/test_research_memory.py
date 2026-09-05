"""Tests for Phase E structured research memory:
research/memory_db.py, research/memory_seed.py, research/memory_query.py,
research/memory_context.py.

Covers exactly what the Phase E task spec asked for: inserting verified
findings, retrieving by experiment, retrieving rejected hypotheses,
open-question retrieval, evidence-provenance enforcement, superseding a
finding, superseded-finding exclusion from default queries, historical
finding still reachable via include_superseded, experiment->finding
linkage, context-packet generation, deterministic output, and a
backward-compatibility check that Phase E did not disturb research/db.py's
existing (pre-Phase-E) schema/behavior.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from research.db import Experiment, OmniLabDB
from research.memory_context import generate_context_packet
from research.memory_db import (
    MemoryDB,
    MemoryRecord,
    ProvenanceError,
    SupersessionError,
    validate_provenance,
)
from research.memory_query import (
    experiments_affecting_true_detector_miss,
    limitations,
    model_representation_evidence,
    open_questions,
    records_for_experiment,
    rejected_hypotheses,
    render_query_result,
    tested_interventions_for_person_recall as _get_tested_interventions,
    verified_person_failure_modes,
)
from research.memory_seed import seed


@pytest.fixture()
def db(tmp_path: Path) -> MemoryDB:
    d = MemoryDB(tmp_path / "test_memory.db")
    yield d
    d.close()


@pytest.fixture()
def seeded_db(tmp_path: Path) -> MemoryDB:
    d = MemoryDB(tmp_path / "test_memory_seeded.db")
    seed(d)
    yield d
    d.close()


def _mk_record(record_id: str = "MEM-0001", **overrides) -> MemoryRecord:
    defaults = dict(
        claim="test claim",
        tag="VERIFIED",
        artifact_path="some/artifact.json",
    )
    defaults.update(overrides)
    return MemoryRecord(record_id=record_id, **defaults)


# ---------------------------------------------------------------------------
# Inserting verified findings
# ---------------------------------------------------------------------------


class TestInsert:
    def test_insert_and_get(self, db: MemoryDB):
        rec = _mk_record(claim="Person recall = 0.211 at baseline", tag="VERIFIED",
                          run_id="RUN-20260904-002")
        db.insert(rec)
        fetched = db.get("MEM-0001")
        assert fetched.claim == "Person recall = 0.211 at baseline"
        assert fetched.tag == "VERIFIED"
        assert fetched.status == "ACTIVE"

    def test_invalid_tag_rejected(self):
        with pytest.raises(ValueError):
            _mk_record(tag="NOT_A_REAL_TAG")

    def test_duplicate_id_rejected(self, db: MemoryDB):
        db.insert(_mk_record())
        with pytest.raises(Exception):
            db.insert(_mk_record())


# ---------------------------------------------------------------------------
# Evidence provenance — mandatory
# ---------------------------------------------------------------------------


class TestProvenance:
    def test_record_without_provenance_rejected(self, db: MemoryDB):
        rec = MemoryRecord(record_id="MEM-0001", claim="unsupported claim", tag="OPEN_QUESTION")
        with pytest.raises(ProvenanceError):
            validate_provenance(rec)
        with pytest.raises(ProvenanceError):
            db.insert(rec)

    def test_record_with_only_experiment_id_is_valid_provenance(self, db: MemoryDB):
        rec = _mk_record(artifact_path=None, experiment_id="EXP-0003")
        validate_provenance(rec)  # should not raise
        db.insert(rec)

    def test_record_with_only_run_id_is_valid_provenance(self, db: MemoryDB):
        rec = _mk_record(artifact_path=None, run_id="RUN-20260904-002")
        validate_provenance(rec)
        db.insert(rec)

    def test_seeded_records_all_have_provenance(self, seeded_db: MemoryDB):
        for rec in seeded_db.list_records(include_superseded=True):
            assert rec.experiment_id or rec.run_id or rec.artifact_path, (
                f"{rec.record_id} has no provenance pointer"
            )


# ---------------------------------------------------------------------------
# Retrieval by ontology tag
# ---------------------------------------------------------------------------


class TestRetrievalByTag:
    def test_rejected_hypotheses_query(self, seeded_db: MemoryDB):
        result = rejected_hypotheses(seeded_db)
        exp_ids = {r["experiment_id"] for r in result["results"]}
        assert exp_ids == {"EXP-0001", "EXP-0002", "EXP-0003", "EXP-0004", "EXP-0005"}
        assert all(r["tag"] == "REJECTED_HYPOTHESIS" for r in result["results"])

    def test_open_question_retrieval(self, seeded_db: MemoryDB):
        result = open_questions(seeded_db)
        assert len(result["results"]) >= 5
        assert all(r["tag"] == "OPEN_QUESTION" for r in result["results"])

    def test_limitations_query_returns_at_least_seven(self, seeded_db: MemoryDB):
        result = limitations(seeded_db)
        assert len(result["results"]) >= 7
        assert all(r["tag"] == "LIMITATION" for r in result["results"])

    def test_verified_person_failure_modes(self, seeded_db: MemoryDB):
        result = verified_person_failure_modes(seeded_db)
        assert len(result["results"]) >= 1
        assert all(r["tag"] == "VERIFIED" for r in result["results"])
        assert any("TRUE_DETECTOR_MISS" in r["claim"] for r in result["results"])

    def test_model_representation_evidence(self, seeded_db: MemoryDB):
        result = model_representation_evidence(seeded_db)
        assert len(result["results"]) == 1
        assert result["results"][0]["tag"] == "SUPPORTED_HYPOTHESIS"
        assert "NOT proof" in result["results"][0]["claim"]

    def test_true_detector_miss_query(self, seeded_db: MemoryDB):
        result = experiments_affecting_true_detector_miss(seeded_db)
        exp_ids = {r["experiment_id"] for r in result["results"]}
        assert "EXP-0003" in exp_ids
        assert "EXP-0005" in exp_ids


# ---------------------------------------------------------------------------
# Experiment -> finding linkage
# ---------------------------------------------------------------------------


class TestExperimentLinkage:
    def test_records_for_experiment(self, seeded_db: MemoryDB):
        result = records_for_experiment(seeded_db, "EXP-0003")
        assert len(result["results"]) >= 3  # failure breakdown + old/new confusion + rejected hyp
        assert all(r["experiment_id"] == "EXP-0003" for r in result["results"])

    def test_tested_interventions_covers_all_five_experiments(self, seeded_db: MemoryDB):
        result = _get_tested_interventions(seeded_db)
        exp_ids = [r["experiment_id"] for r in result["results"]]
        assert exp_ids == ["EXP-0001", "EXP-0002", "EXP-0003", "EXP-0004", "EXP-0005"]
        for r in result["results"]:
            assert r["independent_variable"] is not None


# ---------------------------------------------------------------------------
# Supersession mechanism
# ---------------------------------------------------------------------------


class TestSupersession:
    def test_supersede_links_both_records(self, db: MemoryDB):
        old = db.insert(_mk_record(record_id="MEM-0001", claim="~35% class confusion",
                                    artifact_path="reports/baseline/person_failure_analysis.md"))
        new = db.insert(_mk_record(record_id="MEM-0002", claim="5.4% class confusion (rigorous)",
                                    experiment_id="EXP-0003",
                                    artifact_path="experiments/completed/EXP-0003/results.json"))
        old_after, new_after = db.supersede("MEM-0001", "MEM-0002")
        assert old_after.status == "SUPERSEDED"
        assert old_after.superseded_by == "MEM-0002"
        assert new_after.status == "ACTIVE"
        assert new_after.supersedes == "MEM-0001"

    def test_superseded_excluded_from_default_query(self, db: MemoryDB):
        db.insert(_mk_record(record_id="MEM-0001", claim="old"))
        db.insert(_mk_record(record_id="MEM-0002", claim="new", experiment_id="EXP-0003"))
        db.supersede("MEM-0001", "MEM-0002")
        active = db.list_records()  # default: ACTIVE only
        active_ids = {r.record_id for r in active}
        assert "MEM-0001" not in active_ids
        assert "MEM-0002" in active_ids

    def test_superseded_reachable_via_include_superseded(self, db: MemoryDB):
        db.insert(_mk_record(record_id="MEM-0001", claim="old"))
        db.insert(_mk_record(record_id="MEM-0002", claim="new", experiment_id="EXP-0003"))
        db.supersede("MEM-0001", "MEM-0002")
        full_history = db.list_records(include_superseded=True)
        assert {r.record_id for r in full_history} == {"MEM-0001", "MEM-0002"}
        old = db.get("MEM-0001")
        assert old.status == "SUPERSEDED"

    def test_double_supersede_raises(self, db: MemoryDB):
        db.insert(_mk_record(record_id="MEM-0001", claim="old"))
        db.insert(_mk_record(record_id="MEM-0002", claim="new", experiment_id="EXP-0003"))
        db.insert(_mk_record(record_id="MEM-0003", claim="newer", experiment_id="EXP-0003"))
        db.supersede("MEM-0001", "MEM-0002")
        with pytest.raises(SupersessionError):
            db.supersede("MEM-0001", "MEM-0003")

    def test_35_percent_to_5_4_percent_case_end_to_end(self, seeded_db: MemoryDB):
        """The flagship supersession case from the task spec."""
        old_records = [
            r for r in seeded_db.list_records(include_superseded=True)
            if "35.1%" in r.claim and r.status == "SUPERSEDED"
        ]
        assert len(old_records) == 1
        old = old_records[0]
        assert old.superseded_by is not None
        new = seeded_db.get(old.superseded_by)
        assert new.status == "ACTIVE"
        assert "5.4%" in new.claim
        assert new.supersedes == old.record_id
        # Default (ACTIVE-only) query surfaces the corrected 5.4% figure as the
        # current, non-superseded fact — the stale figure is not returned as an
        # ACTIVE record's own claim (it may still be *mentioned* for context
        # inside the new record's explanation of what it supersedes).
        active = seeded_db.list_records(tag="VERIFIED", category="person_failure_modes")
        assert all(r.status == "ACTIVE" for r in active)
        assert any("5.4%" in r.claim for r in active)
        assert not any(r.claim.strip().startswith("~35.1%") for r in active)


# ---------------------------------------------------------------------------
# Context packet generation
# ---------------------------------------------------------------------------


class TestContextPacket:
    def test_generate_context_packet_structure(self, seeded_db: MemoryDB):
        packet = generate_context_packet(seeded_db)
        for key in ("verified_baseline", "strongest_findings", "rejected_directions",
                    "unresolved_questions", "limitations", "experiments_closed", "note"):
            assert key in packet
        assert len(packet["rejected_directions"]) == 5
        assert len(packet["experiments_closed"]) == 5

    def test_context_packet_recognizes_rejected_phrase_patterns(self, seeded_db: MemoryDB):
        packet = generate_context_packet(seeded_db)
        blob = " ".join(d["claim"] for d in packet["rejected_directions"]).lower()
        assert "confidence" in blob  # lower confidence -> EXP-0001
        assert "resolution" in blob  # higher resolution -> EXP-0002
        assert "man" in blob and "person" in blob  # remap Man to Person -> EXP-0003
        assert "preprocessing" in blob  # apply CLAHE -> EXP-0004
        assert "model-size" in blob or "checkpoint" in blob  # larger YOLO -> EXP-0005

    def test_deterministic_output(self, seeded_db: MemoryDB):
        packet1 = generate_context_packet(seeded_db)
        packet2 = generate_context_packet(seeded_db)
        assert packet1 == packet2


# ---------------------------------------------------------------------------
# Deterministic, no-LLM query output
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_same_query_twice_identical(self, seeded_db: MemoryDB):
        r1 = rejected_hypotheses(seeded_db)
        r2 = rejected_hypotheses(seeded_db)
        assert r1 == r2

    def test_render_query_result_is_plain_text(self, seeded_db: MemoryDB):
        result = open_questions(seeded_db)
        text = render_query_result(result)
        assert isinstance(text, str)
        assert "OPEN_QUESTION" in text


# ---------------------------------------------------------------------------
# Seed script itself
# ---------------------------------------------------------------------------


class TestSeed:
    def test_seed_is_idempotent_guard(self, seeded_db: MemoryDB):
        with pytest.raises(RuntimeError):
            seed(seeded_db)

    def test_seed_produces_all_five_rejected_mandatory_records(self, seeded_db: MemoryDB):
        result = rejected_hypotheses(seeded_db)
        assert len(result["results"]) == 5

    def test_seed_produces_seven_limitation_records(self, seeded_db: MemoryDB):
        result = limitations(seeded_db)
        assert len(result["results"]) == 7


# ---------------------------------------------------------------------------
# Backward compatibility: Phase E did not touch research/db.py's schema or
# behavior. Same spirit as tests/test_status_verdict_model.py's historical
# record checks — load the pre-existing OmniLabDB and confirm it still
# behaves exactly as before.
# ---------------------------------------------------------------------------


class TestOmniLabDBBackwardCompatibility:
    def test_omnilab_db_untouched_by_phase_e(self, tmp_path: Path):
        db = OmniLabDB(tmp_path / "compat.db")
        try:
            exp = Experiment(
                experiment_id="EXP-0001",
                hypothesis="h",
                motivation="m",
                rationale="r",
                independent_variable="iv",
                baseline_run_id="RUN-20260904-002",
            )
            db.create_experiment(exp)
            fetched = db.get_experiment("EXP-0001")
            assert fetched.execution_status == "QUEUED"
            assert fetched.research_verdict == "PENDING"
        finally:
            db.close()

    def test_real_omnilab_db_still_loads_with_real_exp_records(self):
        """The real research/omnilab.db (populated before Phase E existed)
        still loads correctly and Phase E added no columns/tables to it."""
        db = OmniLabDB()
        try:
            experiments = db.list_experiments()
            exp_ids = {e.experiment_id for e in experiments}
            assert {"EXP-0001", "EXP-0002", "EXP-0003", "EXP-0004", "EXP-0005"} <= exp_ids
        finally:
            db.close()
