"""In-memory session store.

Each Session owns one compiled Pipeline and the running PipelineState. Sessions
are keyed by an opaque hex id and live for the lifetime of the process — no
persistence, no auth.

The store wraps the same compile → initial_state → apply chain the CLI uses, so
behaviour stays identical between the two surfaces.
"""
from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass, field
from pathlib import Path

from gitlabci_sim.child_pipeline import attach_static_child_pipelines
from gitlabci_sim.compiler import compile_pipeline
from gitlabci_sim.includes import resolve_includes
from gitlabci_sim.loader import resolve_references
from gitlabci_sim.model import CompiledPipeline, JobStatus, PipelineState
from gitlabci_sim.simulator import apply as sim_apply
from gitlabci_sim.simulator import initial_state
from gitlabci_sim.variables import Context


@dataclass
class Session:
    id: str
    pipeline: CompiledPipeline
    ctx: Context
    root: Path
    state: PipelineState
    warnings: list[str] = field(default_factory=list)


def _resolve_target(target: Path) -> Path:
    if target.is_file():
        return target
    if target.is_dir():
        for name in (".gitlab-ci.yml", ".gitlab-ci.yaml"):
            candidate = target / name
            if candidate.exists():
                return candidate
        raise FileNotFoundError(f"no .gitlab-ci.yml found in {target}")
    raise FileNotFoundError(f"path does not exist: {target}")


def _build(target: Path, ctx: Context) -> tuple[CompiledPipeline, Path, list[str]]:
    root = _resolve_target(target)
    result = resolve_includes(root)
    merged = resolve_references(result.merged)
    pipeline = compile_pipeline(merged, ctx, source_files=result.source_files)
    return pipeline, root, list(result.warnings)


def _initial(pipeline: CompiledPipeline, root: Path, ctx: Context) -> PipelineState:
    state = initial_state(pipeline)
    return attach_static_child_pipelines(state, root.parent, ctx)


class SessionStore:
    """Thread-safe dict of session_id → Session."""

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()

    def create(self, target: Path, ctx: Context) -> Session:
        pipeline, root, warnings = _build(target, ctx)
        state = _initial(pipeline, root, ctx)
        session = Session(
            id=secrets.token_hex(8),
            pipeline=pipeline,
            ctx=ctx,
            root=root,
            state=state,
            warnings=warnings,
        )
        with self._lock:
            self._sessions[session.id] = session
        return session

    def get(self, session_id: str) -> Session:
        with self._lock:
            session = self._sessions.get(session_id)
        if session is None:
            raise KeyError(session_id)
        return session

    def apply(self, session_id: str, results: dict[str, JobStatus]) -> Session:
        session = self.get(session_id)
        with self._lock:
            session.state = sim_apply(session.state, results)
        return session

    def reset(self, session_id: str) -> Session:
        session = self.get(session_id)
        with self._lock:
            session.state = _initial(session.pipeline, session.root, session.ctx)
        return session

    def delete(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)
