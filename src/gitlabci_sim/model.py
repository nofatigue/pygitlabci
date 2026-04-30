"""Canonical pydantic models — the JSON contract for parsed/compiled pipelines."""
from __future__ import annotations

from typing import Literal

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
    rules_matched: dict | None = None
    trigger: Trigger | None = None
    extends_chain: list[str] = Field(default_factory=list)
    source_file: str | None = None


class Pipeline(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stages: list[str]
    jobs: dict[str, Job]
    edges: list[tuple[str, str]] = Field(default_factory=list)
    source_files: list[str] = Field(default_factory=list)
    workflow_when: WhenValue = "on_success"
    global_variables: dict[str, str] = Field(default_factory=dict)


class JobRun(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    status: JobStatus
    child_pipeline: Pipeline | None = None


class PipelineState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pipeline: Pipeline
    runs: dict[str, JobRun] = Field(default_factory=dict)
    ready: list[str] = Field(default_factory=list)
    finished: bool = False
