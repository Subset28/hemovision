"""Schema-version migration registry for research/experiment_spec.py.

Phase F item #12's extension point. Deliberately minimal right now (a single
no-op 1.0 -> 1.0 entry) — do not over-engineer a migration framework for
versions that don't exist yet. What matters is that the extension point is
REAL: adding a future 1.1 or 2.0 migration means writing one function and
registering it here, not touching research/experiment_spec.py's loader.

Compatibility policy
---------------------------------------------------------------------------
- Same MAJOR version: a proposal dict loads directly, no migration function
  required, even if the minor version differs (e.g. 1.0 -> 1.2 loads as-is;
  additive minor fields are expected to have safe defaults).
- Different MAJOR version: requires an explicit, registered migration
  function for the exact (from_version, to_version) pair. If none is
  registered, raise UnsupportedSchemaVersionError — never silently guess a
  migration or load the data as-is across a major-version boundary.
- Missing/unrecognized schema_version on the input dict: raise
  SchemaVersionError immediately, before any other validation runs.
"""

from __future__ import annotations

from typing import Callable

from research.experiment_spec import SCHEMA_VERSION, SchemaVersionError

MigrationFn = Callable[[dict], dict]

# Keyed by (from_version, to_version).
MIGRATIONS: dict[tuple[str, str], MigrationFn] = {}


def register_migration(from_version: str, to_version: str):
    def _decorator(fn: MigrationFn) -> MigrationFn:
        MIGRATIONS[(from_version, to_version)] = fn
        return fn
    return _decorator


@register_migration("1.0", "1.0")
def _v1_0_noop(data: dict) -> dict:
    """No-op — the only migration that exists today, kept real (not
    hand-waved) so the registry pattern and its test are exercising an
    actual function, not an empty stub."""
    return data


def _major(version: str) -> str:
    return version.split(".", 1)[0]


def migrate_proposal_dict(data: dict, target_version: str = SCHEMA_VERSION) -> dict:
    """Return `data` (a raw ExperimentProposal-shaped dict) migrated to
    `target_version`. Raises SchemaVersionError if schema_version is missing,
    and UnsupportedSchemaVersionError if no migration path exists across a
    major-version boundary."""
    version = data.get("schema_version")
    if not version:
        raise SchemaVersionError(
            "proposal dict is missing schema_version — refusing to guess. "
            "Every ExperimentProposal must declare an explicit schema_version."
        )
    if version == target_version:
        return data
    if _major(version) == _major(target_version):
        # Same-major-version specs load directly per policy above.
        migrated = dict(data)
        migrated["schema_version"] = target_version
        return migrated
    key = (version, target_version)
    if key not in MIGRATIONS:
        raise UnsupportedSchemaVersionError(
            f"no migration registered from schema_version {version!r} to "
            f"{target_version!r} (different major version, no path available) — "
            "raising rather than silently guessing a migration."
        )
    return MIGRATIONS[key](data)


class UnsupportedSchemaVersionError(SchemaVersionError):
    pass
