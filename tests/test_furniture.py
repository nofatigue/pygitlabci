"""End-to-end tests for the furniture example pipeline.

Pipeline shape under test:
    lint                       (1)
      → build_<item>           (50, all need lint)
        → test_<item>          (20, only first 20 items)
        → deploy_<item>        (50, when: manual, need their build)
"""
from pathlib import Path

import pytest

from gitlabci_sim.compiler import compile_pipeline
from gitlabci_sim.includes import resolve_includes
from gitlabci_sim.loader import resolve_references
from gitlabci_sim.simulator import apply, initial_state
from gitlabci_sim.variables import Context

# Single source of truth — must match examples/furniture/generate.py.
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "examples" / "furniture"))
from generate import FURNITURE, TESTED  # noqa: E402


@pytest.fixture(scope="module")
def furniture_pipeline(examples_dir: Path):
    res = resolve_includes(examples_dir / "furniture" / ".gitlab-ci.yml")
    merged = resolve_references(res.merged)
    return compile_pipeline(merged, Context(), source_files=res.source_files)


# ---- structural checks ---------------------------------------------------------

def test_total_job_count(furniture_pipeline) -> None:
    # 1 lint + 50 build + 20 test + 50 deploy = 121
    assert len(furniture_pipeline.jobs) == 121


def test_furniture_list_length() -> None:
    assert len(FURNITURE) == 50
    assert len(TESTED) == 20
    assert TESTED == FURNITURE[:20]


def test_stages_present(furniture_pipeline) -> None:
    # We add .pre / .post sentinels around the user's stages.
    assert furniture_pipeline.stages == [".pre", "lint", "build", "test", "deploy", ".post"]


def test_lint_job_exists(furniture_pipeline) -> None:
    assert "lint" in furniture_pipeline.jobs
    j = furniture_pipeline.jobs["lint"]
    assert j.stage == "lint"
    assert j.script == ["flake8 ."]
    assert j.needs == []
    assert j.when == "on_success"


def test_50_build_jobs_each_need_lint(furniture_pipeline) -> None:
    builds = [n for n in furniture_pipeline.jobs if n.startswith("build_")]
    assert len(builds) == 50
    for item in FURNITURE:
        name = f"build_{item}"
        assert name in furniture_pipeline.jobs, f"missing {name}"
        job = furniture_pipeline.jobs[name]
        assert job.stage == "build"
        assert job.when == "on_success"
        assert [n.job for n in job.needs] == ["lint"]
        assert job.script == [f"make build_{item}"]


def test_20_test_jobs_each_need_their_build(furniture_pipeline) -> None:
    tests = [n for n in furniture_pipeline.jobs if n.startswith("test_")]
    assert len(tests) == 20
    for item in TESTED:
        name = f"test_{item}"
        assert name in furniture_pipeline.jobs, f"missing {name}"
        job = furniture_pipeline.jobs[name]
        assert job.stage == "test"
        assert job.when == "on_success"
        assert [n.job for n in job.needs] == [f"build_{item}"]


def test_no_test_jobs_for_untested_items(furniture_pipeline) -> None:
    untested = FURNITURE[20:]
    for item in untested:
        assert f"test_{item}" not in furniture_pipeline.jobs


def test_50_deploy_jobs_all_manual_each_needing_their_build(furniture_pipeline) -> None:
    deploys = [n for n in furniture_pipeline.jobs if n.startswith("deploy_")]
    assert len(deploys) == 50
    for item in FURNITURE:
        name = f"deploy_{item}"
        assert name in furniture_pipeline.jobs, f"missing {name}"
        job = furniture_pipeline.jobs[name]
        assert job.stage == "deploy"
        assert job.when == "manual", f"{name} should be manual, got {job.when}"
        assert [n.job for n in job.needs] == [f"build_{item}"]


def test_edges_are_correct_count(furniture_pipeline) -> None:
    # 50 build edges (lint→build_X) + 20 test edges (build_X→test_X) + 50 deploy edges
    # (build_X→deploy_X) = 120 total.
    assert len(furniture_pipeline.edges) == 50 + 20 + 50


def test_lint_to_each_build_edge(furniture_pipeline) -> None:
    edges = set(furniture_pipeline.edges)
    for item in FURNITURE:
        assert ("lint", f"build_{item}") in edges


def test_build_to_test_edges(furniture_pipeline) -> None:
    edges = set(furniture_pipeline.edges)
    for item in TESTED:
        assert (f"build_{item}", f"test_{item}") in edges


def test_build_to_deploy_edges(furniture_pipeline) -> None:
    edges = set(furniture_pipeline.edges)
    for item in FURNITURE:
        assert (f"build_{item}", f"deploy_{item}") in edges


# ---- progression checks --------------------------------------------------------

def test_initial_ready_only_lint(furniture_pipeline) -> None:
    s = initial_state(furniture_pipeline)
    assert s.ready == ["lint"]
    # All 50 deploys are pre-marked as manual but blocked by their build.
    for item in FURNITURE:
        assert s.runs[f"deploy_{item}"].status == "manual"
    assert s.finished is False


def test_after_lint_all_50_builds_ready(furniture_pipeline) -> None:
    s = initial_state(furniture_pipeline)
    s = apply(s, {"lint": "success"})
    expected = {f"build_{item}" for item in FURNITURE}
    assert set(s.ready) == expected
    assert len(s.ready) == 50


def test_after_all_builds_tests_ready_and_deploys_appear_in_ready(furniture_pipeline) -> None:
    s = initial_state(furniture_pipeline)
    s = apply(s, {"lint": "success"})
    s = apply(s, {f"build_{item}": "success" for item in FURNITURE})
    # 20 tests should be ready.
    test_names = {f"test_{item}" for item in TESTED}
    deploy_names = {f"deploy_{item}" for item in FURNITURE}
    assert test_names.issubset(set(s.ready))
    # Manual deploys also surface as ready (user can choose to trigger them).
    assert deploy_names.issubset(set(s.ready))
    # Nothing else in ready.
    assert set(s.ready) == test_names | deploy_names
    # Pipeline is not finished — manual deploys aren't terminal until acted upon.
    assert s.finished is False


def test_partial_build_unlocks_only_corresponding_test_and_deploy(furniture_pipeline) -> None:
    s = initial_state(furniture_pipeline)
    s = apply(s, {"lint": "success"})
    s = apply(s, {"build_chair": "success"})
    # test_chair (since chair is tested) and deploy_chair should be ready.
    assert "test_chair" in s.ready
    assert "deploy_chair" in s.ready
    # Other tests/deploys must NOT be ready — their builds haven't finished.
    assert "test_sofa" not in s.ready
    assert "deploy_sofa" not in s.ready


def test_untested_build_does_not_unlock_test(furniture_pipeline) -> None:
    s = initial_state(furniture_pipeline)
    s = apply(s, {"lint": "success"})
    s = apply(s, {"build_lamp": "success"})  # lamp is in untested set
    # lamp has no test_lamp; deploy_lamp is ready (manual).
    assert "deploy_lamp" in s.ready
    assert "test_lamp" not in s.pipeline.jobs


def test_full_run_to_finished(furniture_pipeline) -> None:
    s = initial_state(furniture_pipeline)
    s = apply(s, {"lint": "success"})
    s = apply(s, {f"build_{item}": "success" for item in FURNITURE})
    s = apply(s, {f"test_{item}": "success" for item in TESTED})
    # Tests done, but 50 manual deploys remain → not finished.
    assert s.finished is False
    # Now manually trigger every deploy.
    s = apply(s, {f"deploy_{item}": "success" for item in FURNITURE})
    assert s.finished is True


def test_failed_lint_skips_everything(furniture_pipeline) -> None:
    s = initial_state(furniture_pipeline)
    s = apply(s, {"lint": "failed"})
    # Every build is on_success → skipped.
    for item in FURNITURE:
        assert s.runs[f"build_{item}"].status == "skipped"
    # Tests/deploys never get a chance — also skipped (since their build was skipped).
    for item in TESTED:
        assert s.runs[f"test_{item}"].status == "skipped"
    for item in FURNITURE:
        assert s.runs[f"deploy_{item}"].status == "skipped"
    assert s.finished is True


def test_failed_single_build_skips_only_its_dependents(furniture_pipeline) -> None:
    s = initial_state(furniture_pipeline)
    s = apply(s, {"lint": "success"})
    s = apply(s, {"build_chair": "failed"})
    # chair's test + deploy → skipped.
    assert s.runs["test_chair"].status == "skipped"
    assert s.runs["deploy_chair"].status == "skipped"
    # Other items should still be ready (their builds are still pending).
    assert "build_sofa" in s.ready
    # sofa's test should NOT be in ready yet — its build hasn't run.
    assert "test_sofa" not in s.ready
