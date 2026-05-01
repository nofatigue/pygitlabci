# gitlabci-sim-web

A small browser GUI for the [gitlabci-sim](../..) engine. HTMX over FastAPI,
no build step.

![architecture: form → POST /sessions → HTMX swaps in pipeline panel; click ✓/✗ → POST /apply → re-render]

## Run

From the repo root:

```sh
uv sync --all-packages --all-extras       # one-time
uv run sim-web                            # serves on http://127.0.0.1:8765
uv run sim-web --examples /some/dir       # browse a different folder
uv run sim-web --host 0.0.0.0 --port 9000
```

Open http://127.0.0.1:8765 in a browser. You'll see a list of every
project in the examples folder (anything containing a `.gitlab-ci.yml`)
as click-to-load buttons, plus a "Load by path" form for ad-hoc YAML
files anywhere on disk.

## What you get

- **Example browser:** every project in `--examples PATH` (default
  `./examples`) shows as a click-to-load button on the index page.
- **DAG view:** Mermaid `graph LR`, color-coded by run status.
- **Per-stage panels:** one section per stage, with `✓ all ready` / `✗ all
  ready` buttons that flip every ready job in that stage in one apply.
- **Ready panel:** the same headline list the CLI's interactive mode shows.
- **Reset:** rebuild the initial state (without re-reading the YAML).
- **Download state.json:** the full `PipelineState`, same shape as the CLI's
  `--state-out`.

## Path input

The path you type is interpreted on the **server's filesystem** — this is a
local dev tool. There's no upload form (yet). Relative paths are resolved
against the cwd `sim-web` was launched from.

## What it does *not* do (v1)

- No auth, no multi-user isolation. Every browser tab shares the same
  `SessionStore`.
- No persistence. Restart the server, all sessions are gone.
- No child-pipeline trigger UI. The model supports them; there's just no
  button to attach a child YAML yet.
- No live updates across tabs. Each panel re-renders on its own actions.

## Layout

See [PLAN.md](PLAN.md) for the architecture and the build steps that got us
here. In short:

```
gitlabci_sim_web/
  app.py        # FastAPI app, endpoints, uvicorn entrypoint
  sessions.py   # in-memory SessionStore (thread-safe dict)
  mermaid.py    # render_dag(pipeline, runs) -> Mermaid source
  templates/    # Jinja2 — index.html, _pipeline.html, _error.html
  static/       # styles.css
tests/          # pytest, httpx TestClient
```

## Tests

```sh
uv run pytest src/web
```
