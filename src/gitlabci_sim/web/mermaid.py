"""Render a Pipeline + runs map as Mermaid `graph LR` source.

Stage subgraphs + edges from `pipeline.edges`. Each job gets a Mermaid `class`
matching its current run status, paired with `classDef` styles for colour.

`render_dag(..., include_not_triggered=True)` emits a second variant that also
shows `pipeline.not_triggered` jobs as dimmed nodes — useful for "what would have
run on a different ref/source?" exploration. The web UI hides this view by default.
"""
from __future__ import annotations

from gitlabci_sim.model import CompiledPipeline, JobRun

_STATUS_STYLES: dict[str, str] = {
    "success": "fill:#c8f7c5,stroke:#2e7d32,color:#000",
    "failed": "fill:#f7c5c5,stroke:#c62828,color:#000",
    "running": "fill:#cfe8ff,stroke:#1565c0,color:#000",
    "manual": "fill:#fff4c5,stroke:#f9a825,color:#000",
    "skipped": "fill:#eee,stroke:#888,color:#555",
    "canceled": "fill:#ddd,stroke:#666,color:#555",
}

_NOT_TRIGGERED_STYLE = "fill:#f5f5f5,stroke:#bbb,color:#999,stroke-dasharray:4 3"


def _mermaid_id(name: str) -> str:
    return name.replace("/", "__").replace(".", "_").replace("-", "_")


def render_dag(
    pipeline: CompiledPipeline,
    runs: dict[str, JobRun],
    include_not_triggered: bool = False,
) -> str:
    lines: list[str] = ["graph LR"]

    for status, style in _STATUS_STYLES.items():
        lines.append(f"  classDef {status} {style}")
    if include_not_triggered:
        lines.append(f"  classDef not_triggered {_NOT_TRIGGERED_STYLE}")

    by_stage: dict[str, list[tuple[str, bool]]] = {s: [] for s in pipeline.stages}
    for name, job in pipeline.jobs.items():
        by_stage.setdefault(job.stage, []).append((name, True))
    if include_not_triggered:
        for name, job in pipeline.not_triggered.items():
            by_stage.setdefault(job.stage, []).append((name, False))

    for stage in pipeline.stages:
        jobs = by_stage.get(stage, [])
        if not jobs:
            continue
        # Prefix the subgraph id so it can't collide with a job that shares the
        # stage's name (e.g. a `lint` job in a `lint` stage — Mermaid uses one
        # namespace for subgraphs and nodes, and a duplicate id is a parse error).
        lines.append(f"  subgraph s_{_mermaid_id(stage)}[{stage}]")
        for job_name, _ in jobs:
            lines.append(f"    {_mermaid_id(job_name)}[{job_name}]")
        lines.append("  end")

    for src, dst in pipeline.edges:
        lines.append(f"  {_mermaid_id(src)} --> {_mermaid_id(dst)}")

    if include_not_triggered:
        for src, dst in _not_triggered_edges(pipeline):
            lines.append(f"  {_mermaid_id(src)} -.-> {_mermaid_id(dst)}")

    by_status: dict[str, list[str]] = {}
    for name, run in runs.items():
        if run.status in _STATUS_STYLES:
            by_status.setdefault(run.status, []).append(_mermaid_id(name))
    for status, ids in by_status.items():
        lines.append(f"  class {','.join(ids)} {status}")

    if include_not_triggered and pipeline.not_triggered:
        ids = [_mermaid_id(n) for n in pipeline.not_triggered]
        lines.append(f"  class {','.join(ids)} not_triggered")

    return "\n".join(lines)


def _not_triggered_edges(pipeline: CompiledPipeline) -> list[tuple[str, str]]:
    """Best-effort edges for not-triggered jobs.

    `pipeline.edges` only covers triggered jobs; we add dashed edges from each
    not-triggered job's `needs:` (when targets exist somewhere in the graph) so the
    dimmed DAG shows where the job would have slotted in.
    """
    all_names = set(pipeline.jobs) | set(pipeline.not_triggered)
    out: list[tuple[str, str]] = []
    for name, job in pipeline.not_triggered.items():
        for n in job.needs:
            if n.job in all_names:
                out.append((n.job, name))
    return out
