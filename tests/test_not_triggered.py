"""Coverage for the not-triggered surface: rule-dropped jobs are kept on
`pipeline.not_triggered` (hidden from the simulator), each Job carries a per-rule
evaluation trace, and the dimmed DAG renders dotted edges."""
from __future__ import annotations

from pathlib import Path

from gitlabci_sim.compiler import compile_pipeline
from gitlabci_sim.includes import resolve_includes
from gitlabci_sim.loader import load_yaml_string, resolve_references
from gitlabci_sim.variables import Context
from gitlabci_sim.web.mermaid import render_dag


def test_dropped_job_lives_on_not_triggered(tmp_path: Path) -> None:
    cfg = load_yaml_string(
        """
stages: [build]
runs_on_main:
  stage: build
  script: ['x']
  rules:
    - if: '$CI_COMMIT_REF_NAME == "main"'
      when: on_success
gated:
  stage: build
  script: ['y']
  rules:
    - if: '$CI_COMMIT_REF_NAME == "main"'
      when: on_success
    - when: never
"""
    )
    pipeline = compile_pipeline(cfg, Context(ref="feature/x", pipeline_source="push"))
    assert "runs_on_main" not in pipeline.jobs
    assert "gated" not in pipeline.jobs
    # Both should surface as not_triggered with reasons.
    assert set(pipeline.not_triggered) == {"runs_on_main", "gated"}
    runs_on_main = pipeline.not_triggered["runs_on_main"]
    assert runs_on_main.triggered is False
    assert runs_on_main.not_triggered_reason == "no rule matched"
    gated = pipeline.not_triggered["gated"]
    # `when: never` is the matched rule -> drop_reason describes which.
    assert "when:never" in (gated.not_triggered_reason or "")
    assert gated.matched_rule_index == 1


def test_rules_evaluation_traces_each_rule() -> None:
    cfg = load_yaml_string(
        """
stages: [a]
deploy:
  stage: a
  script: ['x']
  rules:
    - if: '$CI_COMMIT_REF_NAME == "main"'
      when: on_success
    - if: '$CI_COMMIT_REF_NAME =~ /^feat/'
      when: manual
    - when: never
"""
    )
    p = compile_pipeline(cfg, Context(ref="feature/x", pipeline_source="push"))
    job = p.jobs["deploy"]  # triggered: rule index 1 matches
    assert job.matched_rule_index == 1
    assert len(job.rules_evaluation) == 3
    rule0, rule1, rule2 = job.rules_evaluation
    assert rule0.matched is False
    assert rule0.reason.startswith("if false")
    assert rule1.matched is True
    assert "if true" in rule1.reason
    # rule index 2 doesn't get evaluated because rule 1 already matched.
    assert rule2.matched is False
    assert "earlier rule matched" in rule2.reason


def test_changes_match_reason_records_matching_pair() -> None:
    cfg = load_yaml_string(
        """
stages: [a]
docs_build:
  stage: a
  script: ['x']
  rules:
    - changes: ['docs/**/*.md']
      when: on_success
"""
    )
    # `docs/**/*.md` requires at least one path segment under docs/ (fnmatch semantics).
    p = compile_pipeline(cfg, Context(changed_files=["docs/intro/quickstart.md", "src/main.py"]))
    rule = p.jobs["docs_build"].rules_evaluation[0]
    assert rule.matched is True
    assert "docs/intro/quickstart.md" in rule.reason


def test_dimmed_dag_includes_not_triggered_with_dashed_edges(tmp_path: Path) -> None:
    cfg = load_yaml_string(
        """
stages: [build, deploy]
build:
  stage: build
  script: ['x']
deploy:
  stage: deploy
  script: ['y']
  needs: [build]
  rules:
    - if: '$CI_COMMIT_REF_NAME == "main"'
      when: on_success
"""
    )
    p = compile_pipeline(cfg, Context(ref="feature/x", pipeline_source="push"))
    # Default DAG: only triggered jobs.
    default_dag = render_dag(p, runs={})
    assert "deploy" not in default_dag
    # Dimmed DAG: includes not_triggered + dashed edge from its needs target.
    full_dag = render_dag(p, runs={}, include_not_triggered=True)
    assert "deploy" in full_dag
    assert "build -.->" in full_dag  # dashed edge syntax for not-triggered targets
    assert "classDef not_triggered" in full_dag


def test_template_include_falls_back_to_local_templates_dir(tmp_path: Path) -> None:
    """`- template: Foo/Bar.gitlab-ci.yml` resolves to `<root>/templates/Foo/Bar.gitlab-ci.yml`."""
    (tmp_path / "templates" / "Foo").mkdir(parents=True)
    (tmp_path / "templates" / "Foo" / "Bar.gitlab-ci.yml").write_text(
        "from_template:\n  stage: build\n  script: ['hi']\n"
    )
    (tmp_path / ".gitlab-ci.yml").write_text(
        "stages: [build]\ninclude:\n  - template: Foo/Bar.gitlab-ci.yml\n"
    )
    res = resolve_includes(tmp_path / ".gitlab-ci.yml")
    assert res.warnings == []
    p = compile_pipeline(resolve_references(res.merged), Context())
    assert "from_template" in p.jobs


def test_template_include_missing_warns_with_path_hint(tmp_path: Path) -> None:
    (tmp_path / ".gitlab-ci.yml").write_text(
        "include:\n  - template: Security/SAST.gitlab-ci.yml\n"
    )
    res = resolve_includes(tmp_path / ".gitlab-ci.yml")
    assert any("templates/Security/SAST.gitlab-ci.yml" in w for w in res.warnings)


def test_simulator_ignores_not_triggered_jobs(tmp_path: Path) -> None:
    """`pipeline.not_triggered` must not leak into the simulator's run set."""
    from gitlabci_sim.simulator import initial_state

    cfg = load_yaml_string(
        """
stages: [a]
runs:
  stage: a
  script: ['x']
gated:
  stage: a
  script: ['x']
  rules:
    - when: never
"""
    )
    p = compile_pipeline(cfg, Context())
    s = initial_state(p)
    assert "gated" not in s.runs
    assert "runs" in s.runs
