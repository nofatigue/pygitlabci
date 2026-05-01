"""End-to-end tests for the FastAPI app.

Each test creates its own session and reads its id back out of the rendered
panel, so tests don't share session-store state.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from gitlabci_sim_web.app import app

SESSION_ID_RE = re.compile(r'data-session-id="([0-9a-f]+)"')


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def furniture_path(examples_dir: Path) -> str:
    return str(examples_dir / "furniture")


def _create(client: TestClient, path: str) -> str:
    resp = client.post("/sessions", data={"path": path})
    assert resp.status_code == 200, resp.text
    match = SESSION_ID_RE.search(resp.text)
    assert match, f"no session-id in response: {resp.text[:300]}"
    return match.group(1)


def test_index_renders_form(client: TestClient) -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    assert 'name="path"' in resp.text
    assert "gitlabci-sim" in resp.text


def test_create_session_renders_pipeline_panel(client: TestClient, furniture_path: str) -> None:
    resp = client.post("/sessions", data={"path": furniture_path})
    assert resp.status_code == 200
    assert "lint" in resp.text
    assert "graph LR" in resp.text  # mermaid source
    assert "build_chair" in resp.text
    assert "Ready" in resp.text


def test_apply_advances_ready_set(client: TestClient, furniture_path: str) -> None:
    sid = _create(client, furniture_path)
    resp = client.post(f"/sessions/{sid}/apply", data={"job": "lint", "status": "success"})
    assert resp.status_code == 200
    # lint should now show as success; build jobs should be ready
    assert "status-success" in resp.text
    assert "build_chair" in resp.text


def test_reset_returns_to_initial_state(client: TestClient, furniture_path: str) -> None:
    sid = _create(client, furniture_path)
    client.post(f"/sessions/{sid}/apply", data={"job": "lint", "status": "success"})
    resp = client.post(f"/sessions/{sid}/reset")
    assert resp.status_code == 200
    # back to lint pending — only lint in ready set, no success pills
    assert "status-success" not in resp.text


def test_state_json_endpoint(client: TestClient, furniture_path: str) -> None:
    sid = _create(client, furniture_path)
    resp = client.get(f"/sessions/{sid}/state.json")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    payload = json.loads(resp.text)
    assert payload["pipeline"]["jobs"]["lint"]["name"] == "lint"
    assert payload["ready"] == ["lint"]


def test_create_with_unknown_path_renders_error(client: TestClient, tmp_path: Path) -> None:
    resp = client.post("/sessions", data={"path": str(tmp_path / "nope")})
    assert resp.status_code == 200
    assert "error" in resp.text.lower()
    assert "data-session-id" not in resp.text


def test_apply_unknown_job_renders_error(client: TestClient, furniture_path: str) -> None:
    sid = _create(client, furniture_path)
    resp = client.post(
        f"/sessions/{sid}/apply", data={"job": "no_such_job", "status": "success"}
    )
    assert resp.status_code == 200
    assert "unknown job" in resp.text.lower()


def test_reset_unknown_session_renders_error(client: TestClient) -> None:
    resp = client.post("/sessions/deadbeef/reset")
    assert resp.status_code == 200
    assert "session expired" in resp.text.lower()


def test_state_json_unknown_session_404(client: TestClient) -> None:
    resp = client.get("/sessions/deadbeef/state.json")
    assert resp.status_code == 404


def test_create_with_malformed_vars_renders_error(
    client: TestClient, furniture_path: str
) -> None:
    resp = client.post("/sessions", data={"path": furniture_path, "vars": "no-equals-here"})
    assert resp.status_code == 200
    assert "error" in resp.text.lower()
    assert "KEY=VALUE" in resp.text or "key=value" in resp.text.lower()


def test_apply_stage_marks_every_ready_job_in_the_stage(
    client: TestClient, furniture_path: str
) -> None:
    sid = _create(client, furniture_path)
    # Get past the lint gate so the build stage has many ready jobs.
    client.post(f"/sessions/{sid}/apply", data={"job": "lint", "status": "success"})
    resp = client.post(
        f"/sessions/{sid}/apply_stage", data={"stage": "build", "status": "success"}
    )
    assert resp.status_code == 200

    state = client.get(f"/sessions/{sid}/state.json").json()
    build_jobs = [
        name for name, job in state["pipeline"]["jobs"].items() if job["stage"] == "build"
    ]
    assert build_jobs, "expected at least one build job"
    assert all(state["runs"][n]["status"] == "success" for n in build_jobs)


def test_apply_stage_with_no_ready_jobs_is_a_safe_noop(
    client: TestClient, furniture_path: str
) -> None:
    sid = _create(client, furniture_path)
    # No jobs in the `deploy` stage are ready yet — endpoint should re-render
    # without erroring.
    resp = client.post(
        f"/sessions/{sid}/apply_stage", data={"stage": "deploy", "status": "success"}
    )
    assert resp.status_code == 200
    state = client.get(f"/sessions/{sid}/state.json").json()
    assert state["runs"]["lint"]["status"] in {"pending", "manual"}


def test_panel_renders_per_stage_sections(client: TestClient, furniture_path: str) -> None:
    resp = client.post("/sessions", data={"path": furniture_path})
    assert resp.status_code == 200
    # One <section class="stage" data-stage="..."> per non-empty stage.
    assert 'data-stage="lint"' in resp.text
    assert 'data-stage="build"' in resp.text
    assert 'data-stage="test"' in resp.text
    assert 'data-stage="deploy"' in resp.text
    # Stage-level "all ready" button only appears when something is ready.
    assert "all ready" in resp.text  # lint stage has 1 ready job initially


def test_panel_no_stage_button_when_nothing_ready_in_stage(
    client: TestClient, furniture_path: str
) -> None:
    resp = client.post("/sessions", data={"path": furniture_path})
    # The deploy section is rendered but should not have its own "all ready"
    # button initially. Cheap check: count "apply_stage" form actions — only
    # one stage (lint) has ready jobs at session start.
    assert resp.text.count("apply_stage") == 1
