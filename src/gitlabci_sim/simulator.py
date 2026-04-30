"""Pipeline state machine — pure functions over PipelineState.

Two entrypoints:

    initial_state(pipeline) -> PipelineState
    apply(state, results) -> PipelineState

`results` is a mapping `{job_name: status}` — what the user just decided. We update the
runs, then recompute the ready set: jobs whose upstream gating is satisfied and which
haven't started yet.

Gating rules:
- A job's "upstream" is its `needs:` list when present, otherwise all jobs in earlier
  stages (stage barriers, classic GitLab behaviour pre-needs).
- For each upstream job U:
    * `on_success`     → ready when ALL upstream succeeded (allow_failure counts as success)
    * `on_failure`     → ready when ANY upstream truly failed (no allow_failure)
    * `always`         → ready when all upstream finished (any terminal status)
    * `manual`/`delayed` → same as `on_success` for gating, but the job sits as `manual`
                          until explicitly run.
"""
from __future__ import annotations

from .model import Job, JobRun, JobStatus, Pipeline, PipelineState

TERMINAL: set[str] = {"success", "failed", "skipped", "canceled"}
PASSING_FOR_DOWNSTREAM: set[str] = {"success", "skipped"}


def initial_state(pipeline: Pipeline) -> PipelineState:
    runs: dict[str, JobRun] = {}
    for name, job in pipeline.jobs.items():
        if job.when == "manual":
            runs[name] = JobRun(name=name, status="manual")
        else:
            runs[name] = JobRun(name=name, status="pending")
    state = PipelineState(pipeline=pipeline, runs=runs)
    return _recompute(state)


def apply(state: PipelineState, results: dict[str, JobStatus]) -> PipelineState:
    """Update statuses for the given jobs, then recompute ready/finished."""
    new_runs = dict(state.runs)
    for name, status in results.items():
        if name not in state.pipeline.jobs:
            raise KeyError(f"unknown job: {name}")
        prev = new_runs.get(name) or JobRun(name=name, status="pending")
        new_runs[name] = JobRun(name=name, status=status, child_pipeline=prev.child_pipeline)
    new_state = PipelineState(pipeline=state.pipeline, runs=new_runs)
    return _recompute(new_state)


def _recompute(state: PipelineState) -> PipelineState:
    pipe = state.pipeline
    runs = dict(state.runs)
    upstream = _build_upstream(pipe)

    ready: list[str] = []
    for name, job in pipe.jobs.items():
        run = runs[name]
        if run.status not in {"pending", "manual"}:
            continue
        if not _gates_satisfied(job, upstream[name], runs):
            continue
        if job.when == "on_failure":
            if not _any_real_failure(pipe, upstream[name], runs):
                runs[name] = JobRun(name=name, status="skipped")
                continue
        elif job.when == "on_success":
            if _any_real_failure(pipe, upstream[name], runs):
                runs[name] = JobRun(name=name, status="skipped")
                continue
        ready.append(name)

    finished = all(runs[n].status in TERMINAL for n in pipe.jobs)
    return PipelineState(pipeline=pipe, runs=runs, ready=ready, finished=finished)


def _build_upstream(pipe: Pipeline) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {n: [] for n in pipe.jobs}
    stage_idx = {s: i for i, s in enumerate(pipe.stages)}
    by_stage: dict[str, list[str]] = {s: [] for s in pipe.stages}
    for j in pipe.jobs.values():
        by_stage[j.stage].append(j.name)
    for name, job in pipe.jobs.items():
        if job.needs:
            out[name] = [n.job for n in job.needs if n.job in pipe.jobs]
        else:
            # Stage-barrier mode: depend on every job in every earlier stage.
            idx = stage_idx[job.stage]
            up: list[str] = []
            for prev_idx in range(idx):
                up.extend(by_stage[pipe.stages[prev_idx]])
            out[name] = up
    return out


def _gates_satisfied(job: Job, ups: list[str], runs: dict[str, JobRun]) -> bool:
    """Wait for every upstream that's in the pipeline. Optional needs to non-existent
    jobs are auto-satisfied (the upstream simply isn't in `ups`)."""
    if not ups:
        return True
    for up in ups:
        run = runs.get(up)
        if run is None or run.status not in TERMINAL:
            return False
    return True


def _any_real_failure(pipe: Pipeline, ups: list[str], runs: dict[str, JobRun]) -> bool:
    """True iff any upstream failed AND was not marked allow_failure."""
    for up in ups:
        run = runs.get(up)
        if run is None or run.status != "failed":
            continue
        up_job = pipe.jobs.get(up)
        if up_job and up_job.allow_failure:
            continue
        return True
    return False


__all__ = ["initial_state", "apply"]
