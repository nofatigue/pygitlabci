"""Child pipeline support — both static (`trigger:include:local`) and dynamic
(`trigger:include:artifact`).

Static child pipelines are resolved at compile time: their YAML lives on disk and we can
parse it now. The resulting child Pipeline is attached to the trigger job's
`JobRun.child_pipeline` once that job is marked successful.

Dynamic child pipelines come from a job's artifact at runtime. We can't see the YAML
until the user feeds it to us; the CLI prompts (or `--child-yaml` provides) the path.

In both cases, when a child pipeline is attached its jobs are *flattened* into the
parent state with names prefixed `<parent_job>/<child_job>`. They show up as ready in
the same recompute pass.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from .compiler import compile_pipeline
from .includes import resolve_includes
from .loader import resolve_references
from .model import Job, JobRun, Need, Pipeline, PipelineState
from .variables import Context


def load_child_pipeline_from_yaml(path: Path, ctx: Context | None = None) -> Pipeline:
    res = resolve_includes(path)
    merged = resolve_references(res.merged)
    return compile_pipeline(merged, ctx or Context(), source_files=res.source_files)


def attach_child_pipeline(
    state: PipelineState,
    parent_job_name: str,
    child: Pipeline,
) -> PipelineState:
    """Splice a child pipeline into `state` under the given parent job.

    All child jobs get renamed `<parent>/<child>`. Child stages are appended to the
    parent's stage list (suffixed similarly) so existing stage validation still works.
    """
    parent_run = state.runs.get(parent_job_name)
    if parent_run is None:
        raise KeyError(f"unknown parent job: {parent_job_name}")

    pipe = state.pipeline
    new_pipeline = _splice(pipe, parent_job_name, child)

    new_runs = dict(state.runs)
    for child_name, _ in child.jobs.items():
        prefixed = _prefix(parent_job_name, child_name)
        new_runs[prefixed] = JobRun(
            name=prefixed,
            status="manual" if new_pipeline.jobs[prefixed].when == "manual" else "pending",
        )

    parent_run = JobRun(
        name=parent_job_name,
        status=parent_run.status,
        child_pipeline=child,
    )
    new_runs[parent_job_name] = parent_run

    # Recompute via simulator to get an up-to-date `ready`.
    from .simulator import _recompute  # local import to avoid cycle at module load
    spliced = PipelineState(pipeline=new_pipeline, runs=new_runs)
    return _recompute(spliced)


def _splice(parent: Pipeline, parent_job: str, child: Pipeline) -> Pipeline:
    """Return a new Pipeline with child's jobs/stages folded in.

    Every child job gains a synthetic `needs:` on the parent so it can't run until the
    trigger job succeeds — matches GitLab parent-child semantics.
    """
    parent = deepcopy(parent)

    # Append child stages with prefix; keep .pre / .post anchors.
    new_stages = list(parent.stages)
    for s in child.stages:
        if s in {".pre", ".post"}:
            continue  # don't duplicate sentinel stages
        candidate = _prefix(parent_job, s)
        if candidate not in new_stages:
            new_stages.append(candidate)

    # Build prefixed jobs.
    new_jobs = dict(parent.jobs)
    for name, job in child.jobs.items():
        prefixed_name = _prefix(parent_job, name)
        prefixed_stage = (
            _prefix(parent_job, job.stage) if job.stage not in {".pre", ".post"} else job.stage
        )
        prefixed_needs: list[Need] = [Need(job=parent_job)]
        for n in job.needs:
            prefixed_needs.append(
                Need(
                    job=_prefix(parent_job, n.job),
                    artifacts=n.artifacts,
                    optional=n.optional,
                )
            )
        new_jobs[prefixed_name] = Job(
            **{
                **job.model_dump(),
                "name": prefixed_name,
                "stage": prefixed_stage,
                "needs": prefixed_needs,
                "source_file": job.source_file,
            }
        )

    # New edges: parent → first child layer + child internal edges.
    new_edges = list(parent.edges)
    for name, job in child.jobs.items():
        prefixed = _prefix(parent_job, name)
        new_edges.append((parent_job, prefixed))
        for n in job.needs:
            new_edges.append((_prefix(parent_job, n.job), prefixed))

    return Pipeline(
        stages=new_stages,
        jobs=new_jobs,
        edges=new_edges,
        source_files=list(set(parent.source_files) | set(child.source_files)),
        workflow_when=parent.workflow_when,
        global_variables=parent.global_variables,
    )


def _prefix(parent_job: str, name: str) -> str:
    return f"{parent_job}/{name}"


def attach_static_child_pipelines(
    state: PipelineState,
    base_dir: Path,
    ctx: Context | None = None,
) -> PipelineState:
    """For every `trigger:include:local` job in the pipeline, load + splice the child."""
    pipe = state.pipeline
    new_state = state
    for name, job in list(pipe.jobs.items()):
        trig = job.trigger
        if trig is None or trig.kind != "child_local":
            continue
        for inc in trig.include:
            child_path = (base_dir / inc).resolve()
            child = load_child_pipeline_from_yaml(child_path, ctx)
            new_state = attach_child_pipeline(new_state, name, child)
    return new_state


__all__ = [
    "attach_child_pipeline",
    "attach_static_child_pipelines",
    "load_child_pipeline_from_yaml",
]
