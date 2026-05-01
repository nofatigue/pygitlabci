"""FastAPI app + uvicorn entrypoint (`sim-web`)."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from gitlabci_sim.compiler import CompileError
from gitlabci_sim.variables import Context

from .mermaid import render_dag
from .sessions import Session, SessionStore

_HERE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(_HERE / "templates"))
store = SessionStore()
app = FastAPI(title="gitlabci-sim-web")
app.mount("/static", StaticFiles(directory=str(_HERE / "static")), name="static")


@dataclass
class Config:
    examples_path: Path = field(default_factory=lambda: Path("examples").resolve())


CONFIG = Config()


def _list_examples() -> list[dict[str, str]]:
    """Subdirectories of CONFIG.examples_path that contain a .gitlab-ci.yml."""
    root = CONFIG.examples_path
    if not root.is_dir():
        return []
    out: list[dict[str, str]] = []
    for p in sorted(root.iterdir()):
        if not p.is_dir():
            continue
        if (p / ".gitlab-ci.yml").exists() or (p / ".gitlab-ci.yaml").exists():
            out.append({"name": p.name, "path": str(p)})
    return out


def _parse_kv_lines(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if "=" not in line:
            raise ValueError(f"vars must be KEY=VALUE per line, got {line!r}")
        k, _, v = line.partition("=")
        out[k.strip()] = v
    return out


def _parse_lines(text: str) -> list[str]:
    return [line.strip() for line in (text or "").splitlines() if line.strip()]


def _panel(request: Request, session: Session) -> HTMLResponse:
    by_stage: dict[str, list] = {s: [] for s in session.pipeline.stages}
    for job in session.pipeline.jobs.values():
        by_stage.setdefault(job.stage, []).append(job)
    ready = set(session.state.ready)
    ready_by_stage: dict[str, int] = {
        stage: sum(1 for job in jobs if job.name in ready)
        for stage, jobs in by_stage.items()
    }
    return templates.TemplateResponse(
        request,
        "_pipeline.html",
        {
            "session": session,
            "mermaid_source": render_dag(session.pipeline, session.state.runs),
            "jobs_by_stage": by_stage,
            "ready_by_stage": ready_by_stage,
        },
    )


def _error(request: Request, message: str) -> HTMLResponse:
    return templates.TemplateResponse(request, "_error.html", {"message": message})


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "examples": _list_examples(),
            "examples_path": str(CONFIG.examples_path),
        },
    )


@app.post("/sessions", response_class=HTMLResponse)
def create_session(
    request: Request,
    path: str = Form(...),
    ref: str = Form("main"),
    source: str = Form("push"),
    vars: str = Form(""),
    changed: str = Form(""),
) -> HTMLResponse:
    try:
        ctx = Context(
            ref=ref,
            pipeline_source=source,
            changed_files=_parse_lines(changed),
            extra=_parse_kv_lines(vars),
        )
        session = store.create(Path(path).expanduser(), ctx)
    except FileNotFoundError as e:
        return _error(request, str(e))
    except CompileError as e:
        return _error(request, f"compile error: {e}")
    except ValueError as e:
        return _error(request, str(e))
    return _panel(request, session)


@app.post("/sessions/{session_id}/apply", response_class=HTMLResponse)
def apply_action(
    request: Request,
    session_id: str,
    job: str = Form(...),
    status: str = Form(...),
) -> HTMLResponse:
    try:
        session = store.get(session_id)
    except KeyError:
        return _error(request, "session expired — reload the pipeline")
    try:
        session = store.apply(session_id, {job: status})  # type: ignore[dict-item]
    except KeyError as e:
        return _error(request, f"unknown job: {e}")
    return _panel(request, session)


@app.post("/sessions/{session_id}/apply_stage", response_class=HTMLResponse)
def apply_stage(
    request: Request,
    session_id: str,
    stage: str = Form(...),
    status: str = Form(...),
) -> HTMLResponse:
    try:
        session = store.get(session_id)
    except KeyError:
        return _error(request, "session expired — reload the pipeline")
    affected = {
        name: status  # type: ignore[misc]
        for name in session.state.ready
        if session.pipeline.jobs[name].stage == stage
    }
    session = store.apply(session_id, affected)  # empty dict is a safe no-op
    return _panel(request, session)


@app.post("/sessions/{session_id}/reset", response_class=HTMLResponse)
def reset_session(request: Request, session_id: str) -> HTMLResponse:
    try:
        session = store.reset(session_id)
    except KeyError:
        return _error(request, "session expired — reload the pipeline")
    return _panel(request, session)


@app.get("/sessions/{session_id}/state.json")
def state_json(session_id: str) -> Response:
    try:
        session = store.get(session_id)
    except KeyError as e:
        raise HTTPException(404, "no such session") from e
    return Response(
        session.state.model_dump_json(indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="state-{session_id}.json"'},
    )


def main() -> None:
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser(
        prog="sim-web",
        description="Browse and step through GitLab CI pipelines in a browser.",
    )
    parser.add_argument(
        "--examples",
        default="examples",
        metavar="PATH",
        help="Folder to scan for browsable example projects (default: ./examples)",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    CONFIG.examples_path = Path(args.examples).expanduser().resolve()
    uvicorn.run(app, host=args.host, port=args.port)
