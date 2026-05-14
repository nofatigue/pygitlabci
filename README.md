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

## Python API

For tests and scripts, the high-level entrypoint is a one-liner:

```python
from gitlabci_sim import Pipeline, Context

pipe = Pipeline("path/to/repo", Context.push(ref="main"))

pipe.jobs           # dict[str, Job] — triggered jobs after rules
pipe.not_triggered  # jobs filtered out by rules
pipe.stages         # list[str]
pipe.edges          # list[(src, dst)] — the DAG
pipe.warnings       # include-resolution warnings (remote skips, missing templates)
pipe.compiled       # the underlying CompiledPipeline pydantic model (for serialisation)
```

`Pipeline(path, ctx)` accepts either a directory (looks for `.gitlab-ci.yml`) or a YAML
file. Use `Pipeline.from_string(yaml_text, ctx)` to compile inline YAML (single-file).

### Context

Construct a `Context` directly, or use the factories for common pipeline shapes:

```python
Context.push(ref="main", changed=["src/a.py"])
Context.tag("v1.2.3")
Context.mr(source="feat/x", target="main", changed=["src/a.py"], labels=["bug"])
```

Each factory sets `pipeline_source` and the right `CI_*` predefined vars (MR pipelines
omit `CI_COMMIT_BRANCH`, tag pipelines set `CI_COMMIT_TAG`, etc.).

### Pytest helpers

`gitlabci_sim.testing` ships a `PipelineTesting` wrapper with declarative assertions:

```python
from gitlabci_sim import Pipeline, Context
from gitlabci_sim.testing import PipelineTesting, JobPattern

def test_main_pipeline():
    pipe = Pipeline("examples/starforge", Context.push(ref="main"))
    t = PipelineTesting(pipe)

    t.assert_jobs_exist(["lint:python", "build:api", "deploy:api:staging"])
    t.assert_job_exists(JobPattern(name="deploy:api:prod", when="manual"))
    t.assert_jobs_not_exist(["deploy:legacy"])
    t.assert_jobs_exactly([...])              # whole-set equality
    t.assert_no_warnings()

def test_mr_drops_production():
    pipe = Pipeline("examples/starforge", Context.mr(source="feat/x", target="main"))
    PipelineTesting(pipe).assert_jobs_not_exist([
        "deploy:api:prod", "deploy:web:prod", "verify:production",
    ])

def test_workflow_drops_off_main():
    pipe = Pipeline("examples/starforge", Context.push(ref="topic/x"))
    PipelineTesting(pipe).assert_workflow_dropped()
```

`JobPattern` is a declarative matcher; all fields are AND-ed:

```python
JobPattern(
    name="deploy:prod",          # exact name
    name_regex=r"deploy:.*prod", # regex over the name (fullmatch)
    stage="deploy",
    when="manual",
    allow_failure=False,
    trigger_kind="child_local",  # for trigger:include: jobs
    needs_contains=["build:api"],
    extends_contains=[".docker_build"],
    script_contains=["make build"],
    variables_contains={"ENV": "prod"},
)
```

PipelineTesting assertions:

| method | what it checks |
|---|---|
| `assert_job_exists(name_or_pattern)` | returns the (first) matching Job |
| `assert_jobs_exist([names_or_patterns])` | reports all misses in one error |
| `assert_job_not_exists(name_or_pattern)` | |
| `assert_jobs_not_exist([...])` | |
| `assert_jobs_exactly([names])` | whole-set equality (missing + unexpected) |
| `assert_workflow_dropped()` | `workflow:rules:` produced `when: never` |
| `assert_workflow_runs()` | inverse of the above |
| `assert_no_jobs()` | zero triggered jobs |
| `assert_job_count(triggered=, not_triggered=)` | |
| `assert_no_warnings()` | include resolution produced no warnings |
| `match_jobs(pattern) -> list[Job]` | the building block; returns matching jobs |
| `match_not_triggered(pattern)` | same, over `pipeline.not_triggered` |

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

Jobs whose `rules:` dropped them are hidden by default. Two ways to inspect them:

```sh
uv run sim plan examples/with_includes --ref feature/x --format table --show-not-triggered
uv run sim plan examples/with_includes --ref feature/x --explain deploy_app
uv run sim plan examples/with_includes --ref feature/x --explain all
```

`--explain <job>` prints the rule-by-rule trace (matched/no-match + reason) for one
job; `--explain all` dumps it for every job in the pipeline.

### Offline `template:` includes

`include: - template: Foo/Bar.gitlab-ci.yml` resolves against
`<project_root>/templates/Foo/Bar.gitlab-ci.yml` — no network access. To wire up a
GitLab-shipped template (e.g. `Security/SAST.gitlab-ci.yml`), fetch it once and commit
it under `templates/` next to your `.gitlab-ci.yml`. See
`examples/wireshark__wireshark/templates/` for a worked example.

### Step through a pipeline

```sh
uv run sim run examples/needs_dag
```

Interactive table of ready jobs. Type `pass 1` (or `pass <name>`), `fail 1`, `skip 1`,
`state`, `show <name>`, `save out.json`, `quit`.

### Simulate a tag release

```sh
uv run sim tag examples/with_includes --tag v1.2.3
```

Sets `CI_PIPELINE_SOURCE=tag` and `CI_COMMIT_TAG=v1.2.3` (and `CI_COMMIT_REF_NAME`).
`CI_COMMIT_BRANCH` is omitted, matching real tag pipelines. Same scriptable
`--results`, `--state-in/out`, `--child-yaml` flags as `run`.

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

## Web UI

```sh
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
