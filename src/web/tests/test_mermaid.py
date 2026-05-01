"""Mermaid renderer regression coverage."""
from __future__ import annotations

from gitlabci_sim_web.mermaid import render_dag

from gitlabci_sim.model import Job, JobRun, Pipeline


def _pipeline_with_stage_and_job_sharing_a_name() -> Pipeline:
    # A `lint` job in a `lint` stage — the v1 renderer used the same id for
    # both the subgraph and the node, which Mermaid 11 rejects with
    # "Syntax error in text".
    return Pipeline(
        stages=["lint", "build"],
        jobs={
            "lint": Job(name="lint", stage="lint", script=["echo lint"]),
            "build_chair": Job(name="build_chair", stage="build"),
        },
        edges=[("lint", "build_chair")],
    )


def test_subgraph_id_does_not_collide_with_same_named_job() -> None:
    pipeline = _pipeline_with_stage_and_job_sharing_a_name()
    runs = {
        "lint": JobRun(name="lint", status="pending"),
        "build_chair": JobRun(name="build_chair", status="pending"),
    }

    out = render_dag(pipeline, runs)

    assert "subgraph s_lint[lint]" in out
    assert "subgraph lint[lint]" not in out  # the buggy form
    # The job node should still be declared with its own id.
    assert "lint[lint]" in out


def test_render_includes_class_assignments_per_status() -> None:
    pipeline = _pipeline_with_stage_and_job_sharing_a_name()
    runs = {
        "lint": JobRun(name="lint", status="success"),
        "build_chair": JobRun(name="build_chair", status="failed"),
    }

    out = render_dag(pipeline, runs)

    assert "class lint success" in out
    assert "class build_chair failed" in out
