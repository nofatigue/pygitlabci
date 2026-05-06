"""Shared `--explain` / `explain` rendering: prints a Job's rule-by-rule trace.

Used by `sim plan --explain <job>` (cli.py) and the `explain <job>` REPL command
(interactive.py). Returns nothing; writes Rich output to the supplied console.
"""
from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .model import Job


def print_rule_trace(job: Job, console: Console) -> None:
    flag = "[green]triggered[/]" if job.triggered else "[red]not triggered[/]"
    header = f"[bold]{job.name}[/] — {flag} (when: {job.when})"
    if not job.triggered and job.not_triggered_reason:
        header += f"\n[dim]reason: {job.not_triggered_reason}[/]"
    if job.triggered and job.matched_rule_index is not None:
        header += f"\n[dim]matched rule index: {job.matched_rule_index}[/]"
    console.print(Panel.fit(header, style="cyan"))

    if not job.rules_evaluation:
        console.print("[dim]  (no rules: section — implicit on_success)[/]\n")
        return
    table = Table(show_header=True, header_style="dim")
    table.add_column("#", justify="right")
    table.add_column("matched")
    table.add_column("when")
    table.add_column("rule")
    table.add_column("reason")
    for ev in job.rules_evaluation:
        mark = "[green]✓[/]" if ev.matched else "[dim]·[/]"
        rule_repr = ", ".join(f"{k}={v!r}" for k, v in ev.rule.items())
        table.add_row(str(ev.index), mark, ev.when or "-", rule_repr or "-", ev.reason)
    console.print(table)
    console.print()
