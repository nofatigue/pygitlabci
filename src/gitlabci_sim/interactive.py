"""Interactive REPL for stepping through a pipeline by hand.

Commands:
    pass <name>        mark job success
    fail <name>        mark job failed
    skip <name>        mark job skipped
    cancel <name>      mark job canceled
    state              re-print current state
    show <name>        show full job details
    explain <name>     show the rule-by-rule trace for a job (alias: why)
    not-triggered      list jobs whose rules dropped them (alias: nt)
    save <path>        write current state to file
    quit / exit / q    leave the session
    help / ?           command list

Tab-style completion is intentionally skipped; index shortcuts work instead:
    pass 1             same as `pass <ready_jobs[0]>`
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .explain import print_rule_trace
from .model import JobStatus, PipelineState
from .simulator import apply

STATUS_STYLE = {
    "pending": "dim",
    "manual": "yellow",
    "running": "cyan",
    "success": "green",
    "failed": "red",
    "skipped": "dim",
    "canceled": "magenta",
}


def run_session(
    state: PipelineState,
    console: Console | None = None,
    on_child_pipeline: Callable[[str, PipelineState], PipelineState] | None = None,
) -> PipelineState:
    """Run an interactive session and return the final state."""
    console = console or Console()
    print_state(state, console)

    while True:
        if state.finished:
            console.print("\n[bold green]pipeline finished[/]")
            return state
        try:
            line = console.input("\n[bold cyan]sim> [/]").strip()
        except (EOFError, KeyboardInterrupt):
            console.print()
            return state
        if not line:
            continue

        cmd, _, rest = line.partition(" ")
        rest = rest.strip()
        cmd = cmd.lower()

        if cmd in {"q", "quit", "exit"}:
            return state
        if cmd in {"help", "?"}:
            _print_help(console)
            continue
        if cmd == "state":
            print_state(state, console)
            continue
        if cmd == "show":
            _show_job(state, rest, console)
            continue
        if cmd in {"explain", "why"}:
            _explain_job(state, rest, console)
            continue
        if cmd in {"not-triggered", "nt"}:
            _list_not_triggered(state, console)
            continue
        if cmd == "save":
            if not rest:
                console.print("[red]usage: save <path>[/]")
                continue
            Path(rest).write_text(state.model_dump_json(indent=2))
            console.print(f"[green]wrote {rest}[/]")
            continue

        status_for_cmd = {
            "pass": "success",
            "ok": "success",
            "fail": "failed",
            "skip": "skipped",
            "cancel": "canceled",
        }
        if cmd in status_for_cmd:
            target = _resolve_target(state, rest)
            if target is None:
                console.print(f"[red]no such job/index: {rest!r}[/]")
                continue
            new_status: JobStatus = status_for_cmd[cmd]  # type: ignore[assignment]
            state = apply(state, {target: new_status})
            console.print(f"[{STATUS_STYLE[new_status]}]{target} → {new_status}[/]")
            if (
                on_child_pipeline is not None
                and new_status == "success"
                and state.pipeline.jobs[target].trigger is not None
                and state.pipeline.jobs[target].trigger.kind == "child_artifact"  # type: ignore[union-attr]
            ):
                state = on_child_pipeline(target, state)
            print_state(state, console)
            continue

        console.print(f"[red]unknown command: {cmd!r} (try 'help')[/]")


def print_state(state: PipelineState, console: Console) -> None:
    table = Table(title="jobs", show_lines=False)
    table.add_column("#", justify="right", style="dim")
    table.add_column("name")
    table.add_column("stage")
    table.add_column("status")
    table.add_column("when", style="dim")

    ready = list(state.ready)
    ready_set = set(ready)

    rows: list[tuple] = []
    for name, job in state.pipeline.jobs.items():
        run = state.runs[name]
        idx = ""
        if name in ready_set:
            idx = str(ready.index(name) + 1)
        style = STATUS_STYLE.get(run.status, "")
        rows.append((idx, name, job.stage, f"[{style}]{run.status}[/]", job.when))

    rows.sort(key=lambda r: (state.pipeline.stages.index(r[2]), r[1]))
    for r in rows:
        table.add_row(*r)

    console.print(table)
    if ready:
        console.print(
            Panel.fit(
                f"ready: [bold]{', '.join(ready)}[/]",
                style="green" if not state.finished else "blue",
            )
        )


def _resolve_target(state: PipelineState, rest: str) -> str | None:
    if not rest:
        return None
    if rest.isdigit():
        i = int(rest) - 1
        if 0 <= i < len(state.ready):
            return state.ready[i]
        return None
    if rest in state.pipeline.jobs:
        return rest
    return None


def _show_job(state: PipelineState, name: str, console: Console) -> None:
    job = state.pipeline.jobs.get(name) or state.pipeline.not_triggered.get(name)
    if job is None:
        console.print(f"[red]no such job: {name!r}[/]")
        return
    console.print_json(job.model_dump_json())


def _explain_job(state: PipelineState, name: str, console: Console) -> None:
    if not name:
        console.print("[red]usage: explain <job-name>[/]")
        return
    job = state.pipeline.jobs.get(name) or state.pipeline.not_triggered.get(name)
    if job is None:
        console.print(f"[red]no such job: {name!r}[/]")
        return
    print_rule_trace(job, console)


def _list_not_triggered(state: PipelineState, console: Console) -> None:
    nt = state.pipeline.not_triggered
    if not nt:
        console.print("[dim]no not-triggered jobs in this pipeline[/]")
        return
    table = Table(title=f"not-triggered ({len(nt)})", show_lines=False)
    table.add_column("name")
    table.add_column("stage")
    table.add_column("reason", style="dim")
    rows = sorted(
        nt.values(),
        key=lambda j: (
            state.pipeline.stages.index(j.stage) if j.stage in state.pipeline.stages else 99,
            j.name,
        ),
    )
    for job in rows:
        table.add_row(job.name, job.stage, job.not_triggered_reason or "—")
    console.print(table)
    console.print("[dim](use 'explain <name>' to see the per-rule trace)[/]")


def _print_help(console: Console) -> None:
    console.print(
        Panel.fit(
            "Commands:\n"
            "  pass <name|#>     mark success (alias: ok)\n"
            "  fail <name|#>     mark failed\n"
            "  skip <name|#>     mark skipped\n"
            "  cancel <name|#>   mark canceled\n"
            "  state             redraw the table\n"
            "  show <name>       full job details (JSON)\n"
            "  explain <name>    rule-by-rule trace (alias: why)\n"
            "  not-triggered     list rule-dropped jobs (alias: nt)\n"
            "  save <path>       write current state JSON\n"
            "  help              this help\n"
            "  quit              leave (state lost unless saved)",
            title="help",
        )
    )
