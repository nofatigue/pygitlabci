"""Smoke-test the engine against real-world `.gitlab-ci.yml` snapshots from
public GitLab projects.

Fixtures live under `tests/fixtures/public_ci/<slug>/.gitlab-ci.yml` (see
`SOURCES.md` in that directory for provenance). Each one was selected
because it compiles to a non-empty Pipeline without dragging in the rest of
its repo — i.e. its `extends:` chains and `!reference` paths resolve from
the root file alone.

Refresh the corpus with `scratch/fetch_probes.sh` then
`scratch/install_fixtures.sh`.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from gitlabci_sim.compiler import compile_pipeline
from gitlabci_sim.includes import resolve_includes
from gitlabci_sim.loader import resolve_references
from gitlabci_sim.variables import Context

FIXTURES = Path(__file__).parent / "fixtures" / "public_ci"
SLUGS = sorted(p.name for p in FIXTURES.iterdir() if p.is_dir())


@pytest.mark.parametrize("slug", SLUGS, ids=SLUGS)
def test_real_world_pipeline_compiles(slug: str) -> None:
    yaml_path = FIXTURES / slug / ".gitlab-ci.yml"
    assert yaml_path.exists(), f"missing fixture: {yaml_path}"

    res = resolve_includes(yaml_path)
    merged = resolve_references(res.merged)
    pipeline = compile_pipeline(
        merged,
        Context(ref="main", pipeline_source="push"),
        source_files=res.source_files,
    )

    assert pipeline.jobs, f"{slug}: pipeline has no jobs"
    assert pipeline.stages, f"{slug}: pipeline has no stages"
    # Every job's stage must be declared up top — sanity check that the
    # compiler produced an internally consistent Pipeline.
    declared = set(pipeline.stages)
    for name, job in pipeline.jobs.items():
        assert job.stage in declared, f"{slug}: job {name!r} on undeclared stage {job.stage!r}"


def test_corpus_has_ten_fixtures() -> None:
    """If a fixture is removed or fails to install, this is the canary."""
    assert len(SLUGS) == 10, f"expected 10 public-CI fixtures, found {len(SLUGS)}: {SLUGS}"
