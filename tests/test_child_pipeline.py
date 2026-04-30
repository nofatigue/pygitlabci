from pathlib import Path

from gitlabci_sim.child_pipeline import (
    attach_child_pipeline,
    load_child_pipeline_from_yaml,
)
from gitlabci_sim.compiler import compile_pipeline
from gitlabci_sim.includes import resolve_includes
from gitlabci_sim.loader import resolve_references
from gitlabci_sim.simulator import apply, initial_state
from gitlabci_sim.variables import Context


def _compile_dir(d: Path):
    res = resolve_includes(d / ".gitlab-ci.yml")
    merged = resolve_references(res.merged)
    return compile_pipeline(merged, Context(), source_files=res.source_files)


def test_compile_marks_trigger_artifact(examples_dir: Path) -> None:
    p = _compile_dir(examples_dir / "child_pipeline")
    assert "trigger_child" in p.jobs
    trig = p.jobs["trigger_child"].trigger
    assert trig is not None
    assert trig.kind == "child_artifact"
    assert trig.artifact == "child.yml"
    assert trig.job == "generator"


def test_attach_child_pipeline_after_success(examples_dir: Path) -> None:
    p = _compile_dir(examples_dir / "child_pipeline")
    s = initial_state(p)
    s = apply(s, {"generator": "success"})
    assert "trigger_child" in s.ready

    child = load_child_pipeline_from_yaml(
        examples_dir / "child_pipeline" / "fixtures" / "child.yml"
    )
    s = attach_child_pipeline(s, "trigger_child", child)
    s = apply(s, {"trigger_child": "success"})

    # Child jobs should appear with prefix.
    assert "trigger_child/work_a" in s.pipeline.jobs
    assert "trigger_child/work_b" in s.pipeline.jobs

    # work_a depends on parent trigger; trigger succeeded → work_a is ready.
    assert "trigger_child/work_a" in s.ready

    s = apply(s, {"trigger_child/work_a": "success"})
    assert "trigger_child/work_b" in s.ready
    s = apply(s, {"trigger_child/work_b": "success"})
    assert s.finished is True
