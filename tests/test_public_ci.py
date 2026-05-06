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

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
SLUGS = sorted(p.name for p in EXAMPLES.iterdir() if "__" in p.name and (p / ".gitlab-ci.yml").exists())

# Per-fixture allowlist for expected parse warnings. Each entry must match a substring
# of an emitted warning. Anything we *don't* expect should fail the test — the goal is
# to catch silent regressions like a missing `template:` (the wireshark SAST case).
#
# The GNOME fixtures depend on GitLab CI Components (`include: - component: ...@...`),
# which is a newer GitLab feature we can't resolve offline. Accept those known-skipped
# warnings; any new warning still fails the fixture.
EXPECTED_WARNING_FRAGMENTS: dict[str, list[str]] = {
    "gnome__glib": ["component"],
    "gnome__glibmm": ["component"],
    "gnome__gnome-online-accounts": ["component"],
    "gnome__gnome-system-monitor": ["component"],
    "gnome__gobject-introspection": ["project (gnome/citemplates)", "component"],
    "gnome__gtkmm": ["component"],
    "gnome__libxslt": ["component"],
    "gnome__pango": ["component"],
}


def _classify_warning(warning: str, allowed_fragments: list[str]) -> str | None:
    """Return the matched fragment, or None if the warning is unexpected."""
    for frag in allowed_fragments:
        if frag in warning:
            return frag
    return None


@pytest.mark.parametrize("slug", SLUGS, ids=SLUGS)
def test_real_world_pipeline_compiles(slug: str) -> None:
    yaml_path = EXAMPLES / slug / ".gitlab-ci.yml"
    assert yaml_path.exists(), f"missing fixture: {yaml_path}"

    res = resolve_includes(yaml_path)
    # Real-world configs must parse without unexpected warnings — a warning means we
    # silently skipped an include or a glob, and the resulting pipeline doesn't reflect
    # what GitLab itself would run. If a fixture genuinely needs a template, drop a
    # copy under `<fixture>/templates/<path>` (see examples/wireshark__wireshark/templates).
    allowed = EXPECTED_WARNING_FRAGMENTS.get(slug, [])
    unexpected = [w for w in res.warnings if _classify_warning(w, allowed) is None]
    assert not unexpected, f"{slug}: unexpected parse warnings: {unexpected}"

    merged = resolve_references(res.merged)
    pipeline = compile_pipeline(
        merged,
        Context(ref="main", pipeline_source="push"),
        source_files=res.source_files,
    )

    assert pipeline.jobs or pipeline.not_triggered, f"{slug}: pipeline has no jobs"
    assert pipeline.stages, f"{slug}: pipeline has no stages"
    declared = set(pipeline.stages)
    for name, job in pipeline.jobs.items():
        assert job.stage in declared, f"{slug}: job {name!r} on undeclared stage {job.stage!r}"


def test_wireshark_loads_sast_template_offline() -> None:
    """The Security/SAST.gitlab-ci.yml include must resolve from the local templates dir.

    If this regresses, every SAST job in `pipeline.not_triggered` would disappear —
    that's the whole reason the templates were committed alongside the fixture.
    """
    yaml_path = EXAMPLES / "wireshark__wireshark" / ".gitlab-ci.yml"
    res = resolve_includes(yaml_path)
    assert res.warnings == []
    merged = resolve_references(res.merged)
    pipeline = compile_pipeline(
        merged,
        Context(ref="master", pipeline_source="push"),
        source_files=res.source_files,
    )
    sast_jobs = {n for n in pipeline.not_triggered if "sast" in n}
    assert "sast" in sast_jobs, f"missing SAST jobs from template; got {sast_jobs}"
    assert "gitlab-advanced-sast" in sast_jobs


def test_corpus_has_ten_fixtures() -> None:
    """If a fixture is removed or fails to install, this is the canary."""
    assert len(SLUGS) == 10, f"expected 10 public-CI fixtures, found {len(SLUGS)}: {SLUGS}"
