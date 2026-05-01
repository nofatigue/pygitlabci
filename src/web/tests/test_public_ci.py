"""Smoke-test the engine against real-world `.gitlab-ci.yml` snapshots from
public GitLab projects.

Each `examples/<owner>__<repo>/` directory holds a fetched snapshot — see
`examples/PUBLIC_CI.md` for provenance. Selection criterion: compiles to a
non-empty Pipeline from the root file alone (no project-include resolution
required).

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

REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = REPO_ROOT / "examples"
SLUGS = sorted(p.name for p in EXAMPLES.iterdir() if "__" in p.name and (p / ".gitlab-ci.yml").exists())


@pytest.mark.parametrize("slug", SLUGS, ids=SLUGS)
def test_real_world_pipeline_compiles(slug: str) -> None:
    yaml_path = EXAMPLES / slug / ".gitlab-ci.yml"
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
    declared = set(pipeline.stages)
    for name, job in pipeline.jobs.items():
        assert job.stage in declared, f"{slug}: job {name!r} on undeclared stage {job.stage!r}"


def test_corpus_has_ten_fixtures() -> None:
    """If a fixture is removed or fails to install, this is the canary."""
    assert len(SLUGS) == 10, f"expected 10 public-CI fixtures, found {len(SLUGS)}: {SLUGS}"
