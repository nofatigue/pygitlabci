"""The examples/file_changes/ pipeline shape across (source, ref, changed_files).

Each parametrized case asserts the *exact* set of jobs that survive rules
evaluation, so accidental rule-fragment edits in the example show up here.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from gitlabci_sim.compiler import compile_pipeline
from gitlabci_sim.includes import resolve_includes
from gitlabci_sim.loader import resolve_references
from gitlabci_sim.variables import Context


def _compile(target: Path, ctx: Context):
    res = resolve_includes(target / ".gitlab-ci.yml")
    merged = resolve_references(res.merged)
    return compile_pipeline(merged, ctx, source_files=res.source_files)


@pytest.fixture
def example(examples_dir: Path) -> Path:
    return examples_dir / "file_changes"


def test_mr_with_python_change_runs_python_lint_build_and_tests(example: Path) -> None:
    ctx = Context(
        pipeline_source="merge_request_event",
        ref="feature/x",
        mr_target_branch="main",
        changed_files=["src/api/handler.py"],
    )
    pipe = _compile(example, ctx)

    assert set(pipe.jobs) == {
        "lint:python",
        "build:backend",
        "test:unit",
        "test:integration",  # always runs on MRs
    }


def test_mr_with_only_docs_change_runs_docs_lint_and_integration(example: Path) -> None:
    ctx = Context(
        pipeline_source="merge_request_event",
        ref="feature/x",
        changed_files=["docs/intro.md", "README.md"],
    )
    pipe = _compile(example, ctx)

    # Docs-only MR: lint:docs (matches **/*.md), test:integration (always on MRs).
    # No python/js linting, no build, no test:unit.
    assert set(pipe.jobs) == {"lint:docs", "test:integration"}


def test_mr_with_frontend_change_runs_js_pipeline(example: Path) -> None:
    ctx = Context(
        pipeline_source="merge_request_event",
        ref="feature/x",
        changed_files=["web/src/App.tsx"],
    )
    pipe = _compile(example, ctx)

    assert set(pipe.jobs) == {
        "lint:js",
        "build:frontend",
        "test:unit",         # web/**/*.tsx is in test:unit's changes list
        "test:integration",  # always on MRs
    }


def test_mr_with_mixed_change_runs_relevant_per_path(example: Path) -> None:
    ctx = Context(
        pipeline_source="merge_request_event",
        ref="feature/x",
        changed_files=["src/api/handler.py", "web/src/App.tsx", "docs/intro.md"],
    )
    pipe = _compile(example, ctx)

    assert set(pipe.jobs) == {
        "lint:python",
        "lint:js",
        "lint:docs",
        "build:backend",
        "build:frontend",
        "test:unit",
        "test:integration",
    }
    # Deploys never run in MRs.
    assert "deploy:staging" not in pipe.jobs
    assert "deploy:prod" not in pipe.jobs


def test_default_branch_push_includes_deploy_staging_but_not_prod(example: Path) -> None:
    ctx = Context(
        pipeline_source="push",
        ref="main",
        changed_files=["src/api/handler.py"],
    )
    pipe = _compile(example, ctx)

    # deploy:staging fires on default-branch (no path gate).
    assert "deploy:staging" in pipe.jobs
    # deploy:prod is tag-only.
    assert "deploy:prod" not in pipe.jobs
    # test:integration falls back to on_default_branch when not an MR.
    assert "test:integration" in pipe.jobs


def test_non_default_branch_push_with_no_changes_drops_deploys(example: Path) -> None:
    ctx = Context(
        pipeline_source="push",
        ref="feature/x",
        changed_files=["src/api/handler.py"],
    )
    pipe = _compile(example, ctx)

    assert "deploy:staging" not in pipe.jobs
    assert "deploy:prod" not in pipe.jobs
    # test:integration only fires on MRs or default branch.
    assert "test:integration" not in pipe.jobs


def test_tag_pipeline_runs_manual_prod_deploy(example: Path) -> None:
    ctx = Context(pipeline_source="tag", ref="v1.2.3")
    pipe = _compile(example, ctx)

    assert "deploy:prod" in pipe.jobs
    assert pipe.jobs["deploy:prod"].when == "manual"
    # Default-branch-only deploys/tests don't fire on tag pipelines.
    assert "deploy:staging" not in pipe.jobs


def test_changes_pattern_with_no_match_drops_lint_python(example: Path) -> None:
    # Only a JS file changed → python lint should NOT run, even though it has
    # a changes: rule with **/*.py.
    ctx = Context(
        pipeline_source="merge_request_event",
        ref="feature/x",
        changed_files=["web/src/App.tsx"],
    )
    pipe = _compile(example, ctx)
    assert "lint:python" not in pipe.jobs
