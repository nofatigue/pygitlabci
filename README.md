# gitlabci-sim

Simulate GitLab CI pipelines from a folder of `.gitlab-ci.yml` files — without pushing
to GitLab.

- Parse + flatten `include:`, `extends:`, `!reference`, anchors → one canonical JSON.
- Compile to a `Pipeline` model with stages, jobs, dependencies, edges.
- Step through it: mark jobs success/failure, see what unlocks next.
- Dynamic child pipelines (`trigger:include:artifact`) supported — attach the generated
  YAML at runtime.

## Install

```sh
uv sync --extra dev
```

## Quickstart

### Inspect the merged config

```sh
uv run sim parse examples/with_includes
```

Outputs the merged YAML (after `include:` + `!reference`) as JSON.

### Compile + view the pipeline

```sh
uv run sim plan examples/needs_dag --format table
uv run sim plan examples/with_includes --ref main      # JSON, default
uv run sim plan examples/with_includes --ref feature/x # different rules outcome
```

`--var KEY=VAL` to override variables; `--changed path/to/file.py` for `rules:changes:`.

### Step through a pipeline

```sh
uv run sim run examples/needs_dag
```

Interactive table of ready jobs. Type `pass 1` (or `pass <name>`), `fail 1`, `skip 1`,
`state`, `show <name>`, `save out.json`, `quit`.

### Simulate an MR with given changes

```sh
uv run sim mr examples/file_changes \
  --source-branch feature/widgets --target-branch main \
  --changed src/api/handler.py --changed tests/test_api.py
```

Sets `CI_PIPELINE_SOURCE=merge_request_event`, populates the
`CI_MERGE_REQUEST_*` predefined variables, omits `CI_COMMIT_BRANCH` (matching
real GitLab MR pipelines), and feeds the listed paths into `rules:changes:`
evaluation. Same `--results`, `--state-in/out` scriptable flags as `run`.

### Scriptable run

```sh
echo '{"compile": "success", "assets": "success"}' \
  | uv run sim run examples/needs_dag --results -
```

Returns the resulting `PipelineState` JSON. Combine with `--state-in` / `--state-out`
to chain steps in scripts and tests.

### Dynamic child pipelines

When a job has `trigger:include:artifact`, you can't know the child YAML until the job
runs. Tell the simulator where to find it:

```sh
echo '{"generator": "success", "trigger_child": "success"}' \
  | uv run sim run examples/child_pipeline \
      --child-yaml trigger_child=examples/child_pipeline/fixtures/child.yml \
      --results -
```

Child jobs are spliced in as `<parent>/<child>` and become part of `ready`.

### Render the DAG

```sh
uv run sim graph examples/needs_dag
```

Outputs Mermaid (`graph LR ...`); paste into any Mermaid renderer.

## Web UI (optional `[web]` extra)

```sh
uv sync --extra web                          # or: pip install gitlabci-sim[web]
uv run sim-web                               # http://127.0.0.1:8765
uv run sim-web --examples /some/folder       # browse a different examples dir
uv run sim-web --host 0.0.0.0 --port 9000
```

The index page lists every project in the examples folder (anything with
a `.gitlab-ci.yml`) as click-to-load buttons, plus a manual "Load by
path" form. Each session shows a Mermaid DAG color-coded by status,
per-stage panels with bulk `✓ all ready` / `✗ all ready` buttons, and a
download for the full `PipelineState` JSON.

The path you load is interpreted on the **server's filesystem** — this
is a local dev tool. No auth, no persistence, no cross-tab sync.

## Scope

In v1: `stages`, jobs, `needs`, `dependencies`, `when`, `allow_failure`, `rules`
(`if`, `changes`, `exists`, `variables`), `only`/`except` (refs + variables),
`extends`, `include` (local files), `default`, variables (predefined + global + job),
`!reference`, YAML anchors, `trigger` (local + artifact child pipelines).

Out of scope (intentional): `parallel`/matrix, services, cache/artifacts semantics
beyond presence, remote/project/template includes.

## Development

```sh
uv run pytest
uv run ruff check
```

## Architecture

```
loader → includes → extends → variables → rules → compiler → simulator → cli
                                                              ↑
                                                       child_pipeline
```

Each layer is a pure function; output of every layer is JSON-serializable so each is
inspectable on its own.
