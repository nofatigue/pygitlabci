"""GitLab CI pipeline simulator.

High-level API for tests and scripts:

    from gitlabci_sim import Pipeline, Context

    pipe = Pipeline("path/to/repo", Context.mr(source="feature/x", target="main"))
    pipe.jobs   # dict[str, Job]

For pytest assertions, see `gitlabci_sim.testing`.
"""
from .model import CompiledPipeline, Job, JobRun, Need, PipelineState, Trigger
from .pipeline import Pipeline
from .variables import Context

__all__ = [
    "CompiledPipeline",
    "Context",
    "Job",
    "JobRun",
    "Need",
    "Pipeline",
    "PipelineState",
    "Trigger",
]
