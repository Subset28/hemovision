"""Phase-I CANDIDATE-0002 admission-boundary audit (section 11): adding
coreml_replacement_required/signing_distribution_change_required to
ExperimentProposal exposed a latent Phase F freeze/hash defect -- ANY
additive field change would make research/experiment_specs/EXP-0001..0005's
stored frozen_hash mismatch the live schema's to_dict(), since asdict()
always materializes every current dataclass field (with its default) even
for keys absent from the original frozen JSON. research/experiment_spec.py's
verify_integrity() now tolerates this for fields explicitly listed in
_FIELDS_ADDED_AFTER_PHASE_F_FREEZE, ONLY when their loaded value is exactly
the class default (i.e. the field simply didn't exist at freeze time) --
genuine tampering of any field, old or new, must still raise."""

from __future__ import annotations

import pytest

from research.backfill_experiment_specs import load_spec
from research.experiment_spec import (
    FrozenProposalTamperedError,
    SCHEMA_VERSION,
    ExperimentProposal,
    ExperimentSpec,
    _FIELDS_ADDED_AFTER_PHASE_F_FREEZE,
    _proposal_hash,
)


def _minimal_proposal(**overrides) -> ExperimentProposal:
    defaults = dict(
        schema_version=SCHEMA_VERSION,
        experiment_id="EXP-9001",
        title="t",
        family="threshold_postprocessing",
        hypothesis="h",
        motivation="m",
        research_question="rq",
        baseline_run_id="RUN-20260904-002",
        independent_variables=("x",),
        dependent_variables=("person.recall",),
        control_condition="c",
        baseline_comparison="RUN-20260904-002",
        success_criteria={"primary_metric": "person.recall", "min_meaningful_delta": 0.03},
    )
    defaults.update(overrides)
    return ExperimentProposal(**defaults)


class TestHistoricalSpecsLoadCleanly:
    @pytest.mark.parametrize("exp_id", ["EXP-0001", "EXP-0002", "EXP-0003", "EXP-0004", "EXP-0005"])
    def test_all_five_load_without_tamper_error(self, exp_id):
        spec = load_spec(exp_id)  # must not raise FrozenProposalTamperedError
        assert spec.proposal.experiment_id == exp_id
        # The new fields load as their untouched default -- confirming
        # nothing was silently backfilled to a non-default/fabricated value.
        assert spec.proposal.coreml_replacement_required is False
        assert spec.proposal.signing_distribution_change_required is False


class TestToleranceIsNarrow:
    def test_simulated_pre_fix_frozen_hash_still_verifies(self):
        """Simulates exactly what happened to EXP-0001..0005: a frozen_hash
        computed BEFORE the new fields existed (by excluding them here)
        must still verify cleanly against a proposal where those fields are
        untouched defaults."""
        proposal = _minimal_proposal()
        legacy_hash = _proposal_hash(proposal, exclude=frozenset(_FIELDS_ADDED_AFTER_PHASE_F_FREEZE))
        spec = ExperimentSpec(proposal=proposal, status="APPROVED", frozen_hash=legacy_hash)
        spec.verify_integrity()  # must not raise

    def test_genuine_tampering_of_a_new_field_still_raises(self):
        """If a NEW field's value is NOT at its default (i.e. it was
        actually set to something, whether legitimately after a real
        freeze-then-amend, or by unauthorized tampering bypassing amend()),
        the legacy-hash fallback must NOT silently swallow that -- this
        proves the tolerance is narrowly scoped to 'field didn't exist yet',
        never to 'field was changed outside amend()'."""
        proposal = _minimal_proposal()
        legacy_hash = _proposal_hash(proposal, exclude=frozenset(_FIELDS_ADDED_AFTER_PHASE_F_FREEZE))
        tampered = _minimal_proposal(coreml_replacement_required=True)  # not the default
        spec = ExperimentSpec(proposal=tampered, status="APPROVED", frozen_hash=legacy_hash)
        with pytest.raises(FrozenProposalTamperedError):
            spec.verify_integrity()

    def test_genuine_tampering_of_a_pre_existing_field_still_raises(self):
        """Tampering with an ORIGINAL (non-new) field must still be caught
        exactly as before -- this fix only ever grants grace for the
        explicitly listed new fields, nothing else."""
        proposal = _minimal_proposal()
        frozen_hash = _proposal_hash(proposal)
        tampered = _minimal_proposal(hypothesis="a different hypothesis entirely")
        spec = ExperimentSpec(proposal=tampered, status="APPROVED", frozen_hash=frozen_hash)
        with pytest.raises(FrozenProposalTamperedError):
            spec.verify_integrity()

    def test_normal_current_schema_hash_still_verifies_directly(self):
        """The common case (spec frozen under the CURRENT full schema)
        needs no fallback at all -- direct hash match."""
        proposal = _minimal_proposal()
        frozen_hash = _proposal_hash(proposal)
        spec = ExperimentSpec(proposal=proposal, status="APPROVED", frozen_hash=frozen_hash)
        spec.verify_integrity()  # must not raise
