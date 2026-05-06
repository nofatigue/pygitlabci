"""CLI coverage for new flags: `sim tag`, `--show-not-triggered`, `--explain`."""
from __future__ import annotations

import json
from pathlib import Path
from textwrap import dedent

import pytest
from typer.testing import CliRunner

from gitlabci_sim.cli import app


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def gated_project(tmp_path: Path) -> Path:
    (tmp_path / ".gitlab-ci.yml").write_text(dedent("""\
        stages: [build, deploy]
        build:
          stage: build
          script: ['x']
        deploy:
          stage: deploy
          script: ['x']
          rules:
            - if: '$CI_COMMIT_TAG =~ /^v[0-9]/'
              when: on_success
            - when: never
    """))
    return tmp_path


def test_plan_hides_not_triggered_by_default(runner: CliRunner, gated_project: Path) -> None:
    result = runner.invoke(app, ["plan", str(gated_project), "--ref", "main"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    # `deploy` was rule-dropped (no tag set) — must NOT appear in the JSON.
    assert "deploy" not in payload["jobs"]
    # And `not_triggered` is redacted from the default output.
    assert payload.get("not_triggered") in (None, {})


def test_plan_show_not_triggered_surfaces_dropped_jobs(
    runner: CliRunner, gated_project: Path
) -> None:
    result = runner.invoke(
        app, ["plan", str(gated_project), "--ref", "main", "--show-not-triggered"]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert "deploy" not in payload["jobs"]
    assert "deploy" in payload["not_triggered"]
    assert payload["not_triggered"]["deploy"]["triggered"] is False
    # `when: never` matched at index 1 -> drop reason names that rule.
    assert "when:never" in payload["not_triggered"]["deploy"]["not_triggered_reason"]
    assert payload["not_triggered"]["deploy"]["matched_rule_index"] == 1


def test_plan_explain_prints_rule_trace(runner: CliRunner, gated_project: Path) -> None:
    result = runner.invoke(
        app, ["plan", str(gated_project), "--ref", "main", "--explain", "deploy"]
    )
    assert result.exit_code == 0, result.output
    # Should mention rule trace details — match on substrings, not formatting.
    assert "deploy" in result.output
    assert "not triggered" in result.output
    assert "if false" in result.output  # rule 0 (CI_COMMIT_TAG empty) didn't match
    assert "when:never" in result.output  # rule 1 fired, dropping the job


def test_run_repl_explain_command_prints_rule_trace(
    runner: CliRunner, gated_project: Path
) -> None:
    """`sim run` REPL: `explain <job>` shows per-rule reasons inline."""
    # Feed: explain the rule-dropped `deploy` job, then quit.
    result = runner.invoke(
        app,
        ["run", str(gated_project), "--ref", "main"],
        input="explain deploy\nquit\n",
    )
    assert result.exit_code == 0, result.output
    assert "not triggered" in result.output
    assert "if false" in result.output  # CI_COMMIT_TAG empty -> rule 0 false
    assert "when:never" in result.output


def test_run_repl_not_triggered_listing(
    runner: CliRunner, gated_project: Path
) -> None:
    result = runner.invoke(
        app,
        ["run", str(gated_project), "--ref", "main"],
        input="not-triggered\nquit\n",
    )
    assert result.exit_code == 0, result.output
    assert "deploy" in result.output
    assert "when:never" in result.output


def test_sim_tag_sets_pipeline_source_and_commit_tag(
    runner: CliRunner, gated_project: Path, tmp_path: Path
) -> None:
    state_path = tmp_path / "state.json"
    result = runner.invoke(
        app,
        [
            "tag",
            str(gated_project),
            "--tag", "v1.2.3",
            "--results", "-",
            "--state-out", str(state_path),
        ],
        input="{}",
    )
    assert result.exit_code == 0, result.output
    state = json.loads(state_path.read_text())
    # Tag pipeline: `deploy` rule matches CI_COMMIT_TAG, so it should be triggered.
    assert "deploy" in state["pipeline"]["jobs"]
    assert state["pipeline"]["global_variables"] == {}
    # Confirm the predefined env got CI_COMMIT_TAG=v1.2.3 by checking the deploy job
    # exists (which only happens when the rule matched).
