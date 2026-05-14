"""Tests for `gitlabci_sim.testing` — JobPattern + PipelineTesting assertions.

Covers both positive paths and the failure shape so users get useful error messages.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from gitlabci_sim import Context, Pipeline
from gitlabci_sim.testing import (
    JobPattern,
    PipelineAssertionError,
    PipelineTesting,
)


@pytest.fixture
def simple(examples_dir: Path) -> Pipeline:
    return Pipeline(examples_dir / "simple")


@pytest.fixture
def with_includes_feature(examples_dir: Path) -> Pipeline:
    # deploy_app is rule-filtered out on feature branches → ends up in not_triggered.
    return Pipeline(examples_dir / "with_includes", Context.push(ref="feature/x"))


@pytest.fixture
def starforge_main(examples_dir: Path) -> Pipeline:
    return Pipeline(examples_dir / "starforge", Context.push(ref="main"))


# ----- JobPattern ---------------------------------------------------------

def test_jobpattern_empty_matches_everything(simple: Pipeline) -> None:
    t = PipelineTesting(simple)
    matches = t.match_jobs(JobPattern())
    assert {j.name for j in matches} == set(simple.jobs)


def test_jobpattern_by_name(simple: Pipeline) -> None:
    t = PipelineTesting(simple)
    matches = t.match_jobs(JobPattern(name="build"))
    assert [j.name for j in matches] == ["build"]


def test_jobpattern_by_name_regex(starforge_main: Pipeline) -> None:
    t = PipelineTesting(starforge_main)
    matches = t.match_jobs(JobPattern(name_regex=r"deploy:.*:prod"))
    assert {j.name for j in matches} == {"deploy:api:prod", "deploy:web:prod"}


def test_jobpattern_by_when(simple: Pipeline) -> None:
    t = PipelineTesting(simple)
    matches = t.match_jobs(JobPattern(when="manual"))
    assert [j.name for j in matches] == ["deploy"]


def test_jobpattern_by_stage(starforge_main: Pipeline) -> None:
    t = PipelineTesting(starforge_main)
    matches = t.match_jobs(JobPattern(stage="build"))
    assert {j.name for j in matches} == {"build:api", "build:web"}


def test_jobpattern_combines_fields(starforge_main: Pipeline) -> None:
    t = PipelineTesting(starforge_main)
    matches = t.match_jobs(JobPattern(stage="deploy:production", when="manual"))
    assert {j.name for j in matches} == {"deploy:api:prod", "deploy:web:prod"}


def test_jobpattern_needs_contains(starforge_main: Pipeline) -> None:
    t = PipelineTesting(starforge_main)
    matches = t.match_jobs(JobPattern(name="verify:staging"))
    assert len(matches) == 1
    # Sanity: verify:staging needs both staging deploys.
    deeper = t.match_jobs(
        JobPattern(needs_contains=["deploy:api:staging", "deploy:web:staging"])
    )
    assert any(j.name == "verify:staging" for j in deeper)


def test_jobpattern_extends_contains(starforge_main: Pipeline) -> None:
    t = PipelineTesting(starforge_main)
    docker_jobs = t.match_jobs(JobPattern(extends_contains=[".docker_build"]))
    assert {j.name for j in docker_jobs} == {"build:api", "build:web"}


def test_jobpattern_describe_is_useful() -> None:
    p = JobPattern(name="deploy", when="manual")
    s = p.describe()
    assert "name='deploy'" in s
    assert "when='manual'" in s
    # Empty pattern still describes.
    assert "any" in JobPattern().describe()


# ----- existence assertions ----------------------------------------------

def test_assert_job_exists_by_name(simple: Pipeline) -> None:
    t = PipelineTesting(simple)
    job = t.assert_job_exists("build")
    assert job.name == "build"


def test_assert_job_exists_missing_lists_actual_jobs(simple: Pipeline) -> None:
    t = PipelineTesting(simple)
    with pytest.raises(PipelineAssertionError) as excinfo:
        t.assert_job_exists("nope")
    msg = str(excinfo.value)
    assert "'nope'" in msg
    assert "actual jobs:" in msg
    assert "build" in msg


def test_assert_job_exists_hints_at_not_triggered(with_includes_feature: Pipeline) -> None:
    t = PipelineTesting(with_includes_feature)
    with pytest.raises(PipelineAssertionError) as excinfo:
        t.assert_job_exists("deploy_app")
    msg = str(excinfo.value)
    assert "filtered out by rules" in msg
    assert "not_triggered" in msg


def test_assert_job_exists_by_pattern(simple: Pipeline) -> None:
    t = PipelineTesting(simple)
    job = t.assert_job_exists(JobPattern(when="manual"))
    assert job.name == "deploy"


def test_assert_job_exists_pattern_no_match(simple: Pipeline) -> None:
    t = PipelineTesting(simple)
    with pytest.raises(PipelineAssertionError, match="no job matched"):
        t.assert_job_exists(JobPattern(name="missing"))


def test_assert_jobs_exist_collects_all_misses(simple: Pipeline) -> None:
    t = PipelineTesting(simple)
    with pytest.raises(PipelineAssertionError) as excinfo:
        t.assert_jobs_exist(["build", "ghost1", "ghost2", JobPattern(name="ghost3")])
    msg = str(excinfo.value)
    assert "'ghost1'" in msg
    assert "'ghost2'" in msg
    assert "ghost3" in msg
    # 'build' exists — must NOT be reported.
    assert "'build'" not in msg.split("actual jobs:")[0]


def test_assert_jobs_exist_passes_when_all_present(simple: Pipeline) -> None:
    PipelineTesting(simple).assert_jobs_exist(["build", "test", "deploy"])


def test_assert_job_not_exists_passes_for_absent(simple: Pipeline) -> None:
    PipelineTesting(simple).assert_job_not_exists("ghost")
    PipelineTesting(simple).assert_job_not_exists(JobPattern(name="ghost"))


def test_assert_job_not_exists_fails_for_present(simple: Pipeline) -> None:
    t = PipelineTesting(simple)
    with pytest.raises(PipelineAssertionError, match="expected job 'build' to NOT exist"):
        t.assert_job_not_exists("build")


def test_assert_jobs_not_exist_collects_all_present(simple: Pipeline) -> None:
    t = PipelineTesting(simple)
    with pytest.raises(PipelineAssertionError) as excinfo:
        t.assert_jobs_not_exist(["build", "test", "ghost"])
    msg = str(excinfo.value)
    assert "'build'" in msg
    assert "'test'" in msg
    assert "'ghost'" not in msg


def test_assert_jobs_exactly_passes(simple: Pipeline) -> None:
    PipelineTesting(simple).assert_jobs_exactly(["build", "test", "deploy"])


def test_assert_jobs_exactly_reports_missing_and_extra(simple: Pipeline) -> None:
    t = PipelineTesting(simple)
    with pytest.raises(PipelineAssertionError) as excinfo:
        t.assert_jobs_exactly(["build", "ghost"])
    msg = str(excinfo.value)
    assert "missing" in msg and "'ghost'" in msg
    assert "unexpected" in msg


# ----- workflow / counts -------------------------------------------------

def test_assert_workflow_dropped_passes(examples_dir: Path) -> None:
    pipe = Pipeline(examples_dir / "starforge", Context.push(ref="topic/x"))
    PipelineTesting(pipe).assert_workflow_dropped()


def test_assert_workflow_dropped_fails_when_running(simple: Pipeline) -> None:
    t = PipelineTesting(simple)
    with pytest.raises(PipelineAssertionError, match="expected workflow to be dropped"):
        t.assert_workflow_dropped()


def test_assert_workflow_runs_passes(simple: Pipeline) -> None:
    PipelineTesting(simple).assert_workflow_runs()


def test_assert_workflow_runs_fails_when_dropped(examples_dir: Path) -> None:
    pipe = Pipeline(examples_dir / "starforge", Context.push(ref="topic/x"))
    with pytest.raises(PipelineAssertionError, match="workflow_when='never'"):
        PipelineTesting(pipe).assert_workflow_runs()


def test_assert_no_jobs_passes_when_dropped(examples_dir: Path) -> None:
    pipe = Pipeline(examples_dir / "starforge", Context.push(ref="topic/x"))
    PipelineTesting(pipe).assert_no_jobs()


def test_assert_no_jobs_fails_when_present(simple: Pipeline) -> None:
    with pytest.raises(PipelineAssertionError, match="expected zero triggered jobs"):
        PipelineTesting(simple).assert_no_jobs()


def test_assert_job_count_triggered(simple: Pipeline) -> None:
    PipelineTesting(simple).assert_job_count(triggered=3)


def test_assert_job_count_wrong_triggered(simple: Pipeline) -> None:
    with pytest.raises(PipelineAssertionError, match="expected 5 triggered job"):
        PipelineTesting(simple).assert_job_count(triggered=5)


def test_assert_job_count_not_triggered(with_includes_feature: Pipeline) -> None:
    # On feature/x, deploy_app is filtered → 1 not_triggered.
    PipelineTesting(with_includes_feature).assert_job_count(not_triggered=1)


def test_assert_no_warnings_passes(simple: Pipeline) -> None:
    PipelineTesting(simple).assert_no_warnings()


def test_assert_no_warnings_fails_when_warnings_present(tmp_path: Path) -> None:
    yml = tmp_path / ".gitlab-ci.yml"
    yml.write_text(
        """
include:
  - remote: https://example.com/remote.yml
stages: [build]
build:
  stage: build
  script: ["echo hi"]
"""
    )
    pipe = Pipeline(yml)
    assert pipe.warnings  # sanity: remote includes warn but don't fail
    with pytest.raises(PipelineAssertionError, match="warnings"):
        PipelineTesting(pipe).assert_no_warnings()
