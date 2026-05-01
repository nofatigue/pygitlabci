# Web GUI build plan

A thin HTMX + Mermaid frontend over the existing simulator. Lives in `src/web/`
as a separate uv-workspace package (`gitlabci-sim-web`) so the engine's
runtime deps stay clean.

## Stack
- **Backend:** FastAPI + uvicorn, Jinja2 templates, in-memory session store.
- **Frontend:** plain HTML, HTMX for interactions, Mermaid for the DAG, no build step.
- **Path input:** server-side filesystem path (local-only tool, matches the CLI).

## Layout

```
src/web/
  PLAN.md
  README.md
  pyproject.toml
  gitlabci_sim_web/
    __init__.py
    app.py            # FastAPI app + uvicorn entrypoint (`sim-web`)
    sessions.py       # SessionStore: dict[str, Session] behind a lock
    mermaid.py        # render_dag(pipeline, runs) -> mermaid source
    templates/
      index.html
      _pipeline.html  # HTMX-targeted partial: toolbar + DAG + table + ready set
    static/
      styles.css
  tests/
    test_app.py
```

## REST surface

| method  | path                          | body / form                              | returns                       |
|---------|-------------------------------|------------------------------------------|-------------------------------|
| GET     | `/`                           | —                                        | `index.html`                  |
| POST    | `/sessions`                   | `path, ref, source, vars, changed`       | `_pipeline.html` partial      |
| POST    | `/sessions/{id}/apply`        | `job, status`                            | `_pipeline.html` partial      |
| POST    | `/sessions/{id}/reset`        | —                                        | `_pipeline.html` partial      |
| GET     | `/sessions/{id}/state.json`   | —                                        | full `PipelineState` JSON     |

Errors render an inline error fragment, not a stack trace.

## v1 scope
- Load a pipeline from a server-side path with `ref`, `--source`, vars, changed files
- DAG view (Mermaid, color-coded by job status)
- Per-job action buttons: success / failed / run-manually (only for ready jobs)
- Ready-set list (the headline thing from the CLI)
- Reset, export state JSON

## Out of scope (v1)
- Auth / multi-user
- Child-pipeline trigger UI (model supports it, no buttons yet)
- Persistence across process restarts
- Live cross-tab updates (websockets / SSE)
- File upload (server-side path only)

## Build steps (one commit each)
1. **Workspace + skeleton** — root `[tool.uv.workspace]`, `src/web/pyproject.toml`,
   empty package, this PLAN.md. `uv sync` succeeds.
2. **Session store + tests** — `SessionStore` class with `create/get/apply/reset`,
   covered by pytest.
3. **Backend endpoints + templates** — FastAPI app, `index.html`, `_pipeline.html`,
   HTMX wiring, status-colored Mermaid. End-to-end useful slice.
4. **End-to-end tests** — httpx tests against FastAPI hitting `examples/furniture`:
   create → apply → reset, plus error path.
5. **README + smoke test** — `src/web/README.md` with run instructions; manual
   browser smoke test against `examples/furniture`.

## Status colors (Mermaid `classDef`)
- success: `fill:#c8f7c5,stroke:#2e7d32`
- failed:  `fill:#f7c5c5,stroke:#c62828`
- running: `fill:#cfe8ff,stroke:#1565c0`
- manual:  `fill:#fff4c5,stroke:#f9a825`
- skipped: `fill:#eee,stroke:#888`
- pending: default
