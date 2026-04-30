from pathlib import Path

import pytest

from gitlabci_sim.compiler import CompileError, compile_pipeline
from gitlabci_sim.includes import resolve_includes
from gitlabci_sim.loader import load_yaml_string, resolve_references
from gitlabci_sim.variables import Context


def _compile_dir(d: Path, **ctx_kw):
    res = resolve_includes(d / ".gitlab-ci.yml")
    merged = resolve_references(res.merged)
    return compile_pipeline(merged, Context(**ctx_kw), source_files=res.source_files)


def test_simple_pipeline(examples_dir: Path) -> None:
    p = _compile_dir(examples_dir / "simple")
    assert set(p.jobs) == {"build", "test", "deploy"}
    assert p.stages[0] == ".pre"
    assert p.stages[-1] == ".post"
    assert p.jobs["deploy"].when == "manual"
    # No needs: edges from stage barriers (build → test, test → deploy).
    assert ("build", "test") in p.edges
    assert ("test", "deploy") in p.edges


def test_needs_dag(examples_dir: Path) -> None:
    p = _compile_dir(examples_dir / "needs_dag")
    assert {n.job for n in p.jobs["integration_test"].needs} == {"compile", "assets"}
    assert ("compile", "integration_test") in p.edges
    assert ("assets", "integration_test") in p.edges
    assert p.jobs["deploy_prod"].when == "manual"
    assert p.jobs["cleanup"].when == "always"
    # `cleanup` needs deploy_staging optionally; should still validate.
    assert any(n.optional for n in p.jobs["cleanup"].needs)


def test_extends_and_includes(examples_dir: Path) -> None:
    p = _compile_dir(examples_dir / "with_includes", ref="main")
    # Hidden .python_job should not appear.
    assert ".python_job" not in p.jobs
    # build_app extends .python_job → inherits before_script.
    assert p.jobs["build_app"].before_script == ["pip install -e ."]
    # unit_test pulls .python_job's before_script via !reference.
    assert "pip install -e ." in p.jobs["unit_test"].script
    # variable expansion: $APP_NAME → "demo".
    assert any("demo" in s for s in p.jobs["unit_test"].script)
    # deploy_app rule: only on main → present here.
    assert "deploy_app" in p.jobs


def test_includes_rule_drops_off_main(examples_dir: Path) -> None:
    p = _compile_dir(examples_dir / "with_includes", ref="feature/x")
    assert "deploy_app" not in p.jobs


def test_unknown_stage_raises() -> None:
    cfg = load_yaml_string(
        """
stages: [build]
job:
  stage: nope
  script: ["x"]
"""
    )
    with pytest.raises(CompileError, match="unknown stage"):
        compile_pipeline(cfg)


def test_needs_cycle_detected() -> None:
    cfg = load_yaml_string(
        """
stages: [a]
j1:
  stage: a
  script: ["x"]
  needs: [j2]
j2:
  stage: a
  script: ["x"]
  needs: [j1]
"""
    )
    with pytest.raises(CompileError, match="cycle"):
        compile_pipeline(cfg)


def test_unknown_needs_raises() -> None:
    cfg = load_yaml_string(
        """
stages: [a]
j1:
  stage: a
  script: ["x"]
  needs: [missing]
"""
    )
    with pytest.raises(CompileError, match="unknown job"):
        compile_pipeline(cfg)
