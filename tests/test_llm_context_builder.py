"""Phase G — context builder tests (research/llm/context_builder.py):
deterministic packet usage, category tracking, size observability, and
exclusion of disallowed/secret-like data."""

from __future__ import annotations

from pathlib import Path

import pytest

from research.llm.context_builder import build_context
from research.memory_db import MemoryDB, MemoryRecord


@pytest.fixture()
def seeded_db(tmp_path: Path) -> MemoryDB:
    db = MemoryDB(db_path=tmp_path / "memory.db")
    db.insert(
        MemoryRecord(
            record_id="MEM-0001",
            claim="Baseline person recall is 0.91",
            tag="VERIFIED",
            experiment_id="EXP-0001",
            category="person_recall",
            artifact_path="benchmark/results/baseline/results.json",
        )
    )
    db.insert(
        MemoryRecord(
            record_id="MEM-0002",
            claim="Lowering confidence threshold does not help stairs recall",
            tag="REJECTED_HYPOTHESIS",
            experiment_id="EXP-0002",
            category="stairs",
            artifact_path="experiments/completed/EXP-0002/results.json",
        )
    )
    yield db
    db.close()


class TestBuildContext:
    def test_deterministic_same_input_same_output(self, seeded_db: MemoryDB):
        c1 = build_context(seeded_db)
        c2 = build_context(seeded_db)
        assert c1.text == c2.text

    def test_categories_default_to_baseline_only(self, seeded_db: MemoryDB):
        built = build_context(seeded_db)
        assert built.categories_included["baseline"] is True
        assert built.categories_included["objective"] is False
        assert built.categories_included["code_excerpt"] is False

    def test_objective_included_when_passed(self, seeded_db: MemoryDB):
        built = build_context(seeded_db, objective="Should we retry EXP-0002 with a different threshold?")
        assert built.categories_included["objective"] is True
        assert "Should we retry EXP-0002" in built.text

    def test_code_excerpt_never_auto_pulled(self, seeded_db: MemoryDB):
        built = build_context(seeded_db)
        assert built.categories_included["code_excerpt"] is False
        assert "def " not in built.text  # no source code leaked in by default

    def test_code_excerpt_included_only_when_explicitly_passed(self, seeded_db: MemoryDB):
        built = build_context(seeded_db, code_excerpt="def foo(): return 1")
        assert built.categories_included["code_excerpt"] is True
        assert "def foo" in built.text

    def test_size_is_observable(self, seeded_db: MemoryDB):
        built = build_context(seeded_db)
        assert built.char_count == len(built.text)
        assert built.approx_token_estimate > 0

    def test_secret_like_code_excerpt_flagged_not_silently_included(self, seeded_db: MemoryDB):
        built = build_context(seeded_db, code_excerpt="OPENROUTER_API_KEY=sk-leaked-abcdef1234567890")
        assert built.privacy_violations  # flagged
        assert built.is_safe is False

    def test_clean_context_is_safe(self, seeded_db: MemoryDB):
        built = build_context(seeded_db)
        assert built.is_safe is True
        assert built.privacy_violations == []

    def test_never_dumps_raw_repo_files(self, seeded_db: MemoryDB, tmp_path: Path):
        # Sanity check on the design constraint: build_context has no
        # filesystem-walking code path other than reading the memory DB
        # passed to it -- there is no argument that could make it read an
        # arbitrary file from disk.
        import inspect

        from research.llm import context_builder

        source = inspect.getsource(context_builder)
        assert "open(" not in source
        assert "Path(" not in source or "glob" not in source  # no directory walking
