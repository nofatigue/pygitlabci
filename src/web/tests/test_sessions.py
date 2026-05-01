"""SessionStore behaviour: create / get / apply / reset / delete."""
from __future__ import annotations

from pathlib import Path

import pytest
from gitlabci_sim.variables import Context

from gitlabci_sim_web.sessions import SessionStore


@pytest.fixture
def store() -> SessionStore:
    return SessionStore()


@pytest.fixture
def furniture(examples_dir: Path) -> Path:
    return examples_dir / "furniture"


def test_create_returns_session_with_initial_ready_set(
    store: SessionStore, furniture: Path
) -> None:
    session = store.create(furniture, Context())

    assert session.id
    assert session.state.ready == ["lint"]
    assert not session.state.finished
    assert "lint" in session.pipeline.jobs


def test_get_returns_same_session(store: SessionStore, furniture: Path) -> None:
    created = store.create(furniture, Context())
    fetched = store.get(created.id)
    assert fetched is created


def test_get_unknown_id_raises(store: SessionStore) -> None:
    with pytest.raises(KeyError):
        store.get("does-not-exist")


def test_apply_advances_ready_set(store: SessionStore, furniture: Path) -> None:
    session = store.create(furniture, Context())
    updated = store.apply(session.id, {"lint": "success"})

    assert updated is session  # in-place mutation
    assert "lint" not in updated.state.ready
    assert any(name.startswith("build_") for name in updated.state.ready)


def test_apply_unknown_job_raises(store: SessionStore, furniture: Path) -> None:
    session = store.create(furniture, Context())
    with pytest.raises(KeyError):
        store.apply(session.id, {"no_such_job": "success"})


def test_reset_returns_to_initial(store: SessionStore, furniture: Path) -> None:
    session = store.create(furniture, Context())
    store.apply(session.id, {"lint": "success"})
    store.reset(session.id)

    assert session.state.ready == ["lint"]


def test_create_unknown_path_raises(store: SessionStore, tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        store.create(tmp_path / "nope", Context())


def test_create_directory_without_yaml_raises(
    store: SessionStore, tmp_path: Path
) -> None:
    with pytest.raises(FileNotFoundError):
        store.create(tmp_path, Context())


def test_delete_removes_session(store: SessionStore, furniture: Path) -> None:
    session = store.create(furniture, Context())
    store.delete(session.id)
    with pytest.raises(KeyError):
        store.get(session.id)
