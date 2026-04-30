from pathlib import Path

from gitlabci_sim.compiler import compile_pipeline
from gitlabci_sim.includes import resolve_includes
from gitlabci_sim.loader import load_yaml_string, resolve_references
from gitlabci_sim.simulator import apply, initial_state
from gitlabci_sim.variables import Context


def _compile_dir(d: Path):
    res = resolve_includes(d / ".gitlab-ci.yml")
    merged = resolve_references(res.merged)
    return compile_pipeline(merged, Context())


def test_initial_ready_simple(examples_dir: Path) -> None:
    p = _compile_dir(examples_dir / "simple")
    s = initial_state(p)
    assert s.ready == ["build"]
    assert s.runs["deploy"].status == "manual"   # `when: manual`
    assert s.finished is False


def test_progression_simple(examples_dir: Path) -> None:
    p = _compile_dir(examples_dir / "simple")
    s = initial_state(p)
    s = apply(s, {"build": "success"})
    assert s.ready == ["test"]
    s = apply(s, {"test": "success"})
    # deploy is manual → still pending until explicit run.
    assert "deploy" not in s.ready or s.runs["deploy"].status == "manual"
    s = apply(s, {"deploy": "success"})
    assert s.finished is True


def test_needs_dag_unlocks(examples_dir: Path) -> None:
    p = _compile_dir(examples_dir / "needs_dag")
    s = initial_state(p)
    assert set(s.ready) == {"compile", "assets"}

    s = apply(s, {"compile": "success"})
    # unit_test only needs compile.
    assert "unit_test" in s.ready
    assert "integration_test" not in s.ready  # still needs assets

    s = apply(s, {"assets": "success"})
    assert "integration_test" in s.ready

    s = apply(s, {"unit_test": "success", "integration_test": "success"})
    assert "deploy_staging" in s.ready

    s = apply(s, {"deploy_staging": "success"})
    # cleanup is when:always, deploy_prod is when:manual
    assert "cleanup" in s.ready
    assert s.runs["deploy_prod"].status == "manual"


def test_on_failure_runs_only_on_failure() -> None:
    cfg = load_yaml_string(
        """
stages: [a, b]
build:
  stage: a
  script: ["x"]
notify:
  stage: b
  script: ["alert"]
  when: on_failure
"""
    )
    p = compile_pipeline(cfg)
    s = initial_state(p)
    s = apply(s, {"build": "success"})
    # build succeeded → notify should be skipped.
    assert s.runs["notify"].status == "skipped"

    s = initial_state(p)
    s = apply(s, {"build": "failed"})
    assert "notify" in s.ready


def test_allow_failure_does_not_block_downstream() -> None:
    cfg = load_yaml_string(
        """
stages: [a, b]
flaky:
  stage: a
  script: ["x"]
  allow_failure: true
deploy:
  stage: b
  script: ["d"]
  needs: [flaky]
"""
    )
    p = compile_pipeline(cfg)
    s = initial_state(p)
    s = apply(s, {"flaky": "failed"})
    # allow_failure → deploy should still be ready.
    assert "deploy" in s.ready


def test_failure_skips_on_success_downstream() -> None:
    cfg = load_yaml_string(
        """
stages: [a, b]
build:
  stage: a
  script: ["x"]
deploy:
  stage: b
  script: ["d"]
  needs: [build]
"""
    )
    p = compile_pipeline(cfg)
    s = initial_state(p)
    s = apply(s, {"build": "failed"})
    assert s.runs["deploy"].status == "skipped"
    assert s.finished is True


def test_optional_need_satisfied_if_missing() -> None:
    cfg = load_yaml_string(
        """
stages: [a]
hello:
  stage: a
  script: ["echo"]
  needs:
    - job: missing
      optional: true
"""
    )
    p = compile_pipeline(cfg)
    s = initial_state(p)
    assert "hello" in s.ready
