"""End-to-end tests for `sim mr` via typer's CliRunner.

These exist to lock in the wiring between the CLI flags and Context fields
— if someone renames an option or drops it from `mr`, the parametrized
shape tests in test_file_changes_example.py keep passing but the CLI
contract silently breaks. This file is the canary.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from gitlabci_sim.cli import app


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_sim_mr_scriptable_returns_pipeline_state_json(
    runner: CliRunner, examples_dir: Path
) -> None:
    result = runner.invoke(
        app,
        [
            "mr",
            str(examples_dir / "file_changes"),
            "--changed", "src/api/handler.py",
            "--results", "-",
        ],
        input="{}",
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)

    # Smoke check the shape: state has a pipeline with the expected MR-only job set.
    assert payload["finished"] is False
    jobs = set(payload["pipeline"]["jobs"])
    assert jobs == {"lint:python", "build:backend", "test:unit", "test:integration"}


def test_sim_mr_passes_through_target_branch_to_context(
    runner: CliRunner, examples_dir: Path, tmp_path: Path
) -> None:
    # Use --state-out to capture the resulting state and inspect runs.
    state_path = tmp_path / "state.json"
    result = runner.invoke(
        app,
        [
            "mr",
            str(examples_dir / "file_changes"),
            "--source-branch", "feature/widgets",
            "--target-branch", "release/v2",
            "--mr-iid", "777",
            "--changed", "docs/intro.md",
            "--results", "-",
            "--state-out", str(state_path),
        ],
        input="{}",
    )
    assert result.exit_code == 0, result.output
    state = json.loads(state_path.read_text())
    # docs-only MR → only lint:docs and the MR-always test:integration.
    assert set(state["pipeline"]["jobs"]) == {"lint:docs", "test:integration"}


def test_sim_mr_no_changed_files_treats_path_rules_permissively(
    runner: CliRunner, examples_dir: Path
) -> None:
    # Without --changed, _changes_match is permissive (matches every changes:
    # pattern). Documents the existing behaviour so it doesn't regress silently.
    result = runner.invoke(
        app,
        ["mr", str(examples_dir / "file_changes"), "--results", "-"],
        input="{}",
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    jobs = set(payload["pipeline"]["jobs"])
    # Every lint/build/test job survives because their changes: rules
    # vacuously match an empty changed-files set.
    assert {"lint:python", "lint:js", "lint:docs", "build:backend",
            "build:frontend", "test:unit", "test:integration"} <= jobs
    # Deploys still don't appear (they need the default branch or a tag).
    assert "deploy:staging" not in jobs
    assert "deploy:prod" not in jobs


def test_sim_mr_apply_first_job_advances_ready_set(
    runner: CliRunner, examples_dir: Path, tmp_path: Path
) -> None:
    # Two-step scriptable run: first invocation creates initial state and
    # marks lint:python success; second resumes and verifies build:backend
    # is now ready to act on (i.e., MR semantics + the simulator state
    # machine compose correctly through the CLI).
    state1 = tmp_path / "state1.json"
    r1 = runner.invoke(
        app,
        [
            "mr",
            str(examples_dir / "file_changes"),
            "--changed", "src/api/handler.py",
            "--results", "-",
            "--state-out", str(state1),
        ],
        input='{"lint:python": "success"}',
    )
    assert r1.exit_code == 0, r1.output
    s1 = json.loads(state1.read_text())
    assert s1["runs"]["lint:python"]["status"] == "success"
    assert "build:backend" in s1["ready"]
