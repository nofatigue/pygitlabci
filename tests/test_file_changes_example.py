"""The examples/file_changes/ pipeline shape across (source, ref, changed_files).

Each parametrized case asserts the *exact* set of jobs that survive rules
evaluation, so accidental rule-fragment edits in the example show up here.

Written against the high-level `Pipeline` + `PipelineTesting` API.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from gitlabci_sim import Context, Pipeline
from gitlabci_sim.testing import JobPattern, PipelineTesting


@pytest.fixture
def example(examples_dir: Path) -> Path:
    return examples_dir / "file_changes"


def test_mr_with_python_change_runs_python_lint_build_and_tests(example: Path) -> None:
    pipe = Pipeline(
        example,
        Context.mr(source="feature/x", target="main", changed=["src/api/handler.py"]),
    )
    PipelineTesting(pipe).assert_jobs_exactly([
        "lint:python",
        "build:backend",
        "test:unit",
        "test:integration",  # always runs on MRs
    ])


def test_mr_with_only_docs_change_runs_docs_lint_and_integration(example: Path) -> None:
    pipe = Pipeline(
        example,
        Context.mr(source="feature/x", changed=["docs/intro.md", "README.md"]),
    )
    # Docs-only MR: lint:docs (matches **/*.md), test:integration (always on MRs).
    # No python/js linting, no build, no test:unit.
    PipelineTesting(pipe).assert_jobs_exactly(["lint:docs", "test:integration"])


def test_mr_with_frontend_change_runs_js_pipeline(example: Path) -> None:
    pipe = Pipeline(
        example,
        Context.mr(source="feature/x", changed=["web/src/App.tsx"]),
    )
    PipelineTesting(pipe).assert_jobs_exactly([
        "lint:js",
        "build:frontend",
        "test:unit",         # web/**/*.tsx is in test:unit's changes list
        "test:integration",  # always on MRs
    ])


def test_mr_with_mixed_change_runs_relevant_per_path(example: Path) -> None:
    pipe = Pipeline(
        example,
        Context.mr(
            source="feature/x",
            changed=["src/api/handler.py", "web/src/App.tsx", "docs/intro.md"],
        ),
    )
    t = PipelineTesting(pipe)
    t.assert_jobs_exist([
        "lint:python",
        "lint:js",
        "lint:docs",
        "build:backend",
        "build:frontend",
        "test:unit",
        "test:integration",
    ])
    # Deploys never run in MRs.
    t.assert_jobs_not_exist(["deploy:staging", "deploy:prod"])


def test_default_branch_push_includes_deploy_staging_but_not_prod(example: Path) -> None:
    pipe = Pipeline(
        example,
        Context.push(ref="main", changed=["src/api/handler.py"]),
    )
    t = PipelineTesting(pipe)
    # deploy:staging fires on default-branch (no path gate).
    t.assert_job_exists("deploy:staging")
    # deploy:prod is tag-only.
    t.assert_job_not_exists("deploy:prod")
    # test:integration falls back to on_default_branch when not an MR.
    t.assert_job_exists("test:integration")


def test_non_default_branch_push_with_no_changes_drops_deploys(example: Path) -> None:
    pipe = Pipeline(
        example,
        Context.push(ref="feature/x", changed=["src/api/handler.py"]),
    )
    PipelineTesting(pipe).assert_jobs_not_exist([
        "deploy:staging",
        "deploy:prod",
        "test:integration",  # only fires on MRs or default branch
    ])


def test_tag_pipeline_runs_manual_prod_deploy(example: Path) -> None:
    pipe = Pipeline(example, Context.tag("v1.2.3"))
    t = PipelineTesting(pipe)
    # deploy:prod is the only manual job on tag pipelines.
    t.assert_job_exists(JobPattern(name="deploy:prod", when="manual"))
    # Default-branch-only deploys/tests don't fire on tag pipelines.
    t.assert_job_not_exists("deploy:staging")


def test_changes_pattern_with_no_match_drops_lint_python(example: Path) -> None:
    # Only a JS file changed → python lint should NOT run, even though it has
    # a changes: rule with **/*.py.
    pipe = Pipeline(
        example,
        Context.mr(source="feature/x", changed=["web/src/App.tsx"]),
    )
    PipelineTesting(pipe).assert_job_not_exists("lint:python")
