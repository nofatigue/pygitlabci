"""Render a Pipeline + runs map as Mermaid `graph LR` source.

Stage subgraphs + edges from `pipeline.edges`. Each job gets a Mermaid `class`
matching its current run status, paired with `classDef` styles for colour.
"""
from __future__ import annotations

from gitlabci_sim.model import JobRun, Pipeline

_STATUS_STYLES: dict[str, str] = {
    "success": "fill:#c8f7c5,stroke:#2e7d32,color:#000",
    "failed": "fill:#f7c5c5,stroke:#c62828,color:#000",
    "running": "fill:#cfe8ff,stroke:#1565c0,color:#000",
    "manual": "fill:#fff4c5,stroke:#f9a825,color:#000",
    "skipped": "fill:#eee,stroke:#888,color:#555",
    "canceled": "fill:#ddd,stroke:#666,color:#555",
}


def _mermaid_id(name: str) -> str:
    return name.replace("/", "__").replace(".", "_").replace("-", "_")


def render_dag(pipeline: Pipeline, runs: dict[str, JobRun]) -> str:
    lines: list[str] = ["graph LR"]

    for status, style in _STATUS_STYLES.items():
        lines.append(f"  classDef {status} {style}")

    by_stage: dict[str, list[str]] = {s: [] for s in pipeline.stages}
    for name, job in pipeline.jobs.items():
        by_stage.setdefault(job.stage, []).append(name)

    for stage in pipeline.stages:
        jobs = by_stage.get(stage, [])
        if not jobs:
            continue
        # Prefix the subgraph id so it can't collide with a job that shares the
        # stage's name (e.g. a `lint` job in a `lint` stage — Mermaid uses one
        # namespace for subgraphs and nodes, and a duplicate id is a parse error).
        lines.append(f"  subgraph s_{_mermaid_id(stage)}[{stage}]")
        for job_name in jobs:
            lines.append(f"    {_mermaid_id(job_name)}[{job_name}]")
        lines.append("  end")

    for src, dst in pipeline.edges:
        lines.append(f"  {_mermaid_id(src)} --> {_mermaid_id(dst)}")

    by_status: dict[str, list[str]] = {}
    for name, run in runs.items():
        if run.status in _STATUS_STYLES:
            by_status.setdefault(run.status, []).append(_mermaid_id(name))
    for status, ids in by_status.items():
        lines.append(f"  class {','.join(ids)} {status}")

    return "\n".join(lines)
