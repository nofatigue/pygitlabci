"""CLI entrypoint — `sim ...` commands."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import typer
from rich.console import Console

from .child_pipeline import (
    attach_child_pipeline,
    attach_static_child_pipelines,
    load_child_pipeline_from_yaml,
)
from .compiler import compile_pipeline
from .includes import resolve_includes
from .interactive import run_session
from .loader import resolve_references
from .model import PipelineState
from .simulator import apply as sim_apply
from .simulator import initial_state
from .variables import Context

app = typer.Typer(add_completion=False, no_args_is_help=True, help="GitLab CI pipeline simulator")
console = Console()
err_console = Console(stderr=True)


def _die(msg: str) -> None:
    err_console.print(f"[bold red]error:[/] {msg}")
    raise typer.Exit(code=1)


@app.callback()
def _root() -> None:
    """Force typer into multi-command mode even with a single command registered."""


def _find_root(target: Path) -> Path:
    """Resolve `target` to a YAML file. If a directory, look for .gitlab-ci.yml."""
    if target.is_file():
        return target
    if target.is_dir():
        candidate = target / ".gitlab-ci.yml"
        if candidate.exists():
            return candidate
        candidate = target / ".gitlab-ci.yaml"
        if candidate.exists():
            return candidate
        raise typer.BadParameter(f"no .gitlab-ci.yml found in {target}")
    raise typer.BadParameter(f"path does not exist: {target}")


@app.command()
def parse(
    target: Path = typer.Argument(..., help="Folder containing .gitlab-ci.yml, or a YAML file"),
) -> None:
    """Load + merge includes + resolve !reference, print the raw merged config as JSON."""
    root = _find_root(target)
    result = resolve_includes(root)
    merged = resolve_references(result.merged)
    for w in result.warnings:
        err_console.print(f"[yellow]warning:[/] {w}")
    output = {
        "source_files": result.source_files,
        "config": merged,
    }
    console.print_json(json.dumps(output, default=str))


def _parse_var_list(values: list[str] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for v in values or []:
        if "=" not in v:
            raise typer.BadParameter(f"--var must be KEY=VALUE, got {v!r}")
        k, _, val = v.partition("=")
        out[k] = val
    return out


@app.command()
def plan(
    target: Path = typer.Argument(..., help="Folder containing .gitlab-ci.yml, or a YAML file"),
    ref: str = typer.Option("main", "--ref", help="Branch/tag for CI_COMMIT_REF_NAME"),
    pipeline_source: str = typer.Option("push", "--source"),
    var: list[str] | None = typer.Option(None, "--var", help="KEY=VALUE; repeat for multiple"),
    changed: list[str] | None = typer.Option(None, "--changed", help="Changed file (repeat)"),
    fmt: str = typer.Option("json", "--format", help="json or table"),
) -> None:
    """Compile the pipeline and print the canonical Pipeline JSON (or a table)."""
    root = _find_root(target)
    result = resolve_includes(root)
    merged = resolve_references(result.merged)
    for w in result.warnings:
        err_console.print(f"[yellow]warning:[/] {w}")

    ctx = Context(
        ref=ref,
        pipeline_source=pipeline_source,
        changed_files=list(changed or []),
        extra=_parse_var_list(var),
    )
    pipeline = compile_pipeline(merged, ctx, source_files=result.source_files)
    if fmt == "table":
        _print_pipeline_table(pipeline)
    elif fmt == "json":
        console.print_json(pipeline.model_dump_json())
    else:
        raise typer.BadParameter(f"--format must be json or table, got {fmt!r}")


def _print_pipeline_table(pipeline) -> None:
    from rich.table import Table

    table = Table(title=f"pipeline ({len(pipeline.jobs)} jobs)")
    table.add_column("stage")
    table.add_column("job")
    table.add_column("when", style="dim")
    table.add_column("needs")
    table.add_column("trigger", style="cyan")

    rows = []
    for name, job in pipeline.jobs.items():
        needs = ", ".join(n.job for n in job.needs) or "-"
        trig = job.trigger.kind if job.trigger else ""
        rows.append((job.stage, name, job.when, needs, trig))
    rows.sort(key=lambda r: (pipeline.stages.index(r[0]), r[1]))
    for r in rows:
        table.add_row(*r)
    console.print(table)


def _to_mermaid(pipeline) -> str:
    """Render the pipeline DAG as Mermaid `graph LR`."""
    lines = ["graph LR"]
    # Group jobs by stage as subgraphs for readability.
    by_stage: dict[str, list[str]] = {}
    for name, job in pipeline.jobs.items():
        by_stage.setdefault(job.stage, []).append(name)
    for stage, jobs in by_stage.items():
        lines.append(f"  subgraph {_mermaid_id(stage)}[{stage}]")
        for j in jobs:
            lines.append(f"    {_mermaid_id(j)}[{j}]")
        lines.append("  end")
    for src, dst in pipeline.edges:
        lines.append(f"  {_mermaid_id(src)} --> {_mermaid_id(dst)}")
    return "\n".join(lines)


def _mermaid_id(name: str) -> str:
    return name.replace("/", "__").replace(".", "_").replace("-", "_")


@app.command()
def graph(
    target: Path = typer.Argument(..., help="Folder containing .gitlab-ci.yml, or a YAML file"),
    ref: str = typer.Option("main", "--ref"),
    var: list[str] | None = typer.Option(None, "--var"),
) -> None:
    """Emit the pipeline DAG as a Mermaid graph (paste into a renderer to view)."""
    ctx = Context(ref=ref, extra=_parse_var_list(var))
    pipeline, _ = _build_pipeline(target, ctx)
    typer.echo(_to_mermaid(pipeline))


def _build_pipeline(target: Path, ctx: Context) -> tuple:
    from .compiler import CompileError

    root = _find_root(target)
    try:
        result = resolve_includes(root)
        merged = resolve_references(result.merged)
    except FileNotFoundError as e:
        _die(str(e))
    except KeyError as e:
        _die(f"!reference target not found: {e}")
    except ValueError as e:
        _die(str(e))
    for w in result.warnings:
        err_console.print(f"[yellow]warning:[/] {w}")
    try:
        return compile_pipeline(merged, ctx, source_files=result.source_files), result
    except CompileError as e:
        _die(str(e))


def _parse_child_yaml(values: list[str] | None) -> dict[str, Path]:
    """--child-yaml JOB=PATH for dynamic trigger:include:artifact jobs."""
    out: dict[str, Path] = {}
    for v in values or []:
        if "=" not in v:
            raise typer.BadParameter(f"--child-yaml must be JOB=PATH, got {v!r}")
        k, _, val = v.partition("=")
        out[k] = Path(val)
    return out


@app.command()
def run(
    target: Path = typer.Argument(..., help="Folder containing .gitlab-ci.yml, or a YAML file"),
    ref: str = typer.Option("main", "--ref"),
    pipeline_source: str = typer.Option("push", "--source"),
    var: list[str] | None = typer.Option(None, "--var"),
    changed: list[str] | None = typer.Option(None, "--changed"),
    results: str | None = typer.Option(
        None,
        "--results",
        help="Path to JSON {job: status}, or '-' for stdin. Scriptable mode.",
    ),
    state_in: Path | None = typer.Option(None, "--state-in", help="Resume from saved state JSON"),
    state_out: Path | None = typer.Option(None, "--state-out", help="Write final state JSON"),
    child_yaml: list[str] | None = typer.Option(
        None,
        "--child-yaml",
        help="JOB=PATH; YAML to attach when JOB (a trigger:include:artifact job) succeeds",
    ),
) -> None:
    """Run the pipeline interactively, or scriptably with --results."""
    ctx = Context(
        ref=ref,
        pipeline_source=pipeline_source,
        changed_files=list(changed or []),
        extra=_parse_var_list(var),
    )
    pipeline, source = _build_pipeline(target, ctx)

    if state_in:
        state = PipelineState.model_validate_json(state_in.read_text())
    else:
        state = initial_state(pipeline)
        # Eagerly attach static child pipelines (trigger:include:local).
        root_dir = _find_root(target).parent
        state = attach_static_child_pipelines(state, root_dir, ctx)

    child_map = _parse_child_yaml(child_yaml)

    def _on_success_attach(parent: str, st: PipelineState) -> PipelineState:
        if parent not in child_map:
            return st
        child = load_child_pipeline_from_yaml(child_map[parent], ctx)
        return attach_child_pipeline(st, parent, child)

    if results is not None:
        if results == "-":
            payload = json.load(sys.stdin)
        else:
            payload = json.loads(Path(results).read_text())
        # First attach any child YAMLs whose parent we're about to mark success.
        for parent, status in payload.items():
            if status == "success" and parent in child_map:
                child = load_child_pipeline_from_yaml(child_map[parent], ctx)
                state = attach_child_pipeline(state, parent, child)
        state = sim_apply(state, payload)
        if state_out:
            state_out.write_text(state.model_dump_json(indent=2))
        console.print_json(state.model_dump_json())
        return

    state = run_session(state, console=console, on_child_pipeline=_on_success_attach)
    if state_out:
        state_out.write_text(state.model_dump_json(indent=2))


if __name__ == "__main__":
    app()
