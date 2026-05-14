"""Canonical pydantic models — the JSON contract for parsed/compiled pipelines."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

JobStatus = Literal[
    "success",
    "failed",
    "skipped",
    "manual",
    "running",
    "pending",
    "canceled",
]

WhenValue = Literal[
    "on_success",
    "on_failure",
    "always",
    "manual",
    "delayed",
    "never",
]


class Need(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job: str
    artifacts: bool = True
    optional: bool = False


class Trigger(BaseModel):
    """trigger: spec on a job. Either include (child pipeline) or project (downstream)."""
    model_config = ConfigDict(extra="forbid")
    kind: Literal["child_local", "child_artifact", "downstream", "unknown"]
    include: list[str] = Field(default_factory=list)
    artifact: str | None = None
    job: str | None = None
    project: str | None = None
    strategy: Literal["depend", "mirror"] | None = None


class RuleEvaluation(BaseModel):
    """Per-rule trace: did this rule (at this index in the job's `rules:` list) match,
    and what was the deciding clause?"""
    model_config = ConfigDict(extra="forbid")
    index: int
    rule: dict[str, Any] = Field(default_factory=dict)
    matched: bool
    reason: str  # human-readable: "if false ($REF=feature)", "changes matched src/x.py", ...
    when: str | None = None  # the `when:` this rule would have produced if matched


class Job(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    stage: str
    script: list[str] = Field(default_factory=list)
    before_script: list[str] = Field(default_factory=list)
    after_script: list[str] = Field(default_factory=list)
    needs: list[Need] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    when: WhenValue = "on_success"
    allow_failure: bool = False
    variables: dict[str, str] = Field(default_factory=dict)
    rules_matched: dict[str, Any] | None = None
    rules_evaluation: list[RuleEvaluation] = Field(default_factory=list)
    matched_rule_index: int | None = None
    trigger: Trigger | None = None
    extends_chain: list[str] = Field(default_factory=list)
    source_file: str | None = None
    triggered: bool = True
    not_triggered_reason: str | None = None


class CompiledPipeline(BaseModel):
    """Raw pipeline data model — what `compile_pipeline` returns.

    For tests and ergonomic loading, use `gitlabci_sim.Pipeline` instead, which wraps
    this model with a one-liner constructor that resolves includes and references.
    """
    model_config = ConfigDict(extra="forbid")
    stages: list[str]
    jobs: dict[str, Job]
    edges: list[tuple[str, str]] = Field(default_factory=list)
    source_files: list[str] = Field(default_factory=list)
    workflow_when: WhenValue = "on_success"
    global_variables: dict[str, str] = Field(default_factory=dict)
    # Jobs whose rules dropped them — kept for visibility in `--show-not-triggered`
    # and the dimmed DAG. Not part of the simulator's run set.
    not_triggered: dict[str, Job] = Field(default_factory=dict)


class JobRun(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    status: JobStatus
    child_pipeline: CompiledPipeline | None = None


class PipelineState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pipeline: CompiledPipeline
    runs: dict[str, JobRun] = Field(default_factory=dict)
    ready: list[str] = Field(default_factory=list)
    finished: bool = False
