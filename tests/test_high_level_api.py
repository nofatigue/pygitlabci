"""Tests for the high-level `Pipeline` + `Context.{push,tag,mr}` API."""
from __future__ import annotations

from pathlib import Path

import pytest

from gitlabci_sim import CompiledPipeline, Context, Pipeline


def test_pipeline_loads_from_directory(examples_dir: Path) -> None:
    pipe = Pipeline(examples_dir / "simple")
    assert set(pipe.jobs) == {"build", "test", "deploy"}
    assert pipe.stages[0] == ".pre"
    assert pipe.stages[-1] == ".post"


def test_pipeline_loads_from_yaml_file(examples_dir: Path) -> None:
    pipe = Pipeline(examples_dir / "simple" / ".gitlab-ci.yml")
    assert set(pipe.jobs) == {"build", "test", "deploy"}


def test_pipeline_accepts_string_path(examples_dir: Path) -> None:
    pipe = Pipeline(str(examples_dir / "simple"))
    assert "build" in pipe.jobs


def test_pipeline_compiled_is_pydantic_model(examples_dir: Path) -> None:
    pipe = Pipeline(examples_dir / "simple")
    assert isinstance(pipe.compiled, CompiledPipeline)
    # Round-trip serialisation works.
    dumped = pipe.compiled.model_dump_json()
    restored = CompiledPipeline.model_validate_json(dumped)
    assert set(restored.jobs) == set(pipe.jobs)


def test_pipeline_repr_and_membership(examples_dir: Path) -> None:
    pipe = Pipeline(examples_dir / "simple")
    assert "build" in pipe
    assert "no_such_job" not in pipe
    assert len(pipe) == len(pipe.jobs) == 3
    assert "Pipeline(" in repr(pipe)


def test_pipeline_get_job_returns_triggered_or_not(examples_dir: Path) -> None:
    pipe = Pipeline(examples_dir / "with_includes", Context.push(ref="feature/x"))
    # deploy_app is filtered out by rules on feature branches → it's in not_triggered.
    assert "deploy_app" not in pipe
    assert "deploy_app" in pipe.not_triggered
    job = pipe.get_job("deploy_app")
    assert job.name == "deploy_app"
    assert job.triggered is False


def test_pipeline_get_job_raises_for_unknown(examples_dir: Path) -> None:
    pipe = Pipeline(examples_dir / "simple")
    with pytest.raises(KeyError):
        pipe.get_job("no_such_job")


def test_pipeline_missing_path_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        Pipeline(tmp_path / "does_not_exist")


def test_pipeline_directory_without_ci_yml_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="no .gitlab-ci.yml"):
        Pipeline(tmp_path)


def test_pipeline_from_string_compiles_inline_yaml() -> None:
    pipe = Pipeline.from_string(
        """
stages: [build, test]
build_job:
  stage: build
  script: ["make"]
test_job:
  stage: test
  script: ["pytest"]
  needs: [build_job]
"""
    )
    assert set(pipe.jobs) == {"build_job", "test_job"}
    assert ("build_job", "test_job") in pipe.edges


def test_context_push_sets_branch_var(examples_dir: Path) -> None:
    pipe = Pipeline(examples_dir / "simple", Context.push(ref="release/1"))
    assert pipe.context.pipeline_source == "push"
    assert pipe.context.ref == "release/1"
    assert pipe.context.predefined()["CI_COMMIT_BRANCH"] == "release/1"
    assert "CI_COMMIT_TAG" not in pipe.context.predefined()


def test_context_tag_sets_tag_var_and_omits_branch() -> None:
    ctx = Context.tag("v2.0.0")
    env = ctx.predefined()
    assert ctx.pipeline_source == "tag"
    assert env["CI_COMMIT_TAG"] == "v2.0.0"
    assert env["CI_COMMIT_REF_NAME"] == "v2.0.0"
    assert "CI_COMMIT_BRANCH" not in env


def test_context_mr_sets_mr_vars_and_omits_branch() -> None:
    ctx = Context.mr(source="feat/x", target="main", changed=["a.py"], iid=42, labels=["bug"])
    env = ctx.predefined()
    assert ctx.pipeline_source == "merge_request_event"
    assert env["CI_MERGE_REQUEST_SOURCE_BRANCH_NAME"] == "feat/x"
    assert env["CI_MERGE_REQUEST_TARGET_BRANCH_NAME"] == "main"
    assert env["CI_MERGE_REQUEST_IID"] == "42"
    assert env["CI_MERGE_REQUEST_LABELS"] == "bug"
    assert "CI_COMMIT_BRANCH" not in env
    assert ctx.changed_files == ["a.py"]
