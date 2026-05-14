"""End-to-end parsing/compilation of the starforge example.

Covers: glob includes, root-relative include resolution, multi-file `default:` merging,
extends + default precedence, and rule-driven job filtering across pipeline sources.

This file doubles as a worked example of the high-level `Pipeline` + `PipelineTesting`
API. The lower-level `compile_pipeline` / `resolve_includes` chain is still exercised
indirectly (via the Pipeline constructor) and is tested directly in test_compiler.py.
"""
from pathlib import Path

import pytest

from gitlabci_sim import Context, Pipeline
from gitlabci_sim.testing import JobPattern, PipelineTesting


@pytest.fixture(scope="module")
def starforge_root(examples_dir: Path) -> Path:
    return examples_dir / "starforge"


def test_all_files_loaded_via_globs(starforge_root: Path) -> None:
    pipe = Pipeline(starforge_root, Context.push(ref="main"))
    # Entry + 13 includes, all reached via globs except the two named deploy files.
    assert len(pipe.source_files) == 14
    PipelineTesting(pipe).assert_no_warnings()
    expected = {
        "ci/defaults/base.yml", "ci/defaults/before.yml",
        "ci/templates/python.yml", "ci/templates/nodejs.yml",
        "ci/templates/docker.yml", "ci/templates/deploy.yml",
        "ci/stages/lint.yml", "ci/stages/test.yml", "ci/stages/build.yml",
        "ci/services/api.yml", "ci/services/web.yml",
        "ci/deploy/staging.yml", "ci/deploy/production.yml",
    }
    entry = starforge_root / ".gitlab-ci.yml"
    found = {str(Path(s).relative_to(starforge_root)) for s in pipe.source_files
             if Path(s) != entry}
    assert found == expected


def test_multi_file_default_merges_per_key(starforge_root: Path) -> None:
    pipe = Pipeline(starforge_root, Context.push(ref="main"))
    # `notify:staging` has no extends, so the merged `default:` block is its sole source
    # for image / before_script / tags / retry — observable via the compiled job.
    notify = pipe.jobs["notify:staging"]
    # before.yml contributed before_script (the "echo [ci]" line is the first entry).
    assert notify.before_script[0].startswith('echo "[ci]')
    # The full default `before_script` (from before.yml) is two lines; both should be
    # applied since notify defines no before_script of its own.
    assert notify.before_script[1] == "mkdir -p .cache"


def test_default_fills_in_jobs_without_extends(starforge_root: Path) -> None:
    pipe = Pipeline(starforge_root, Context.push(ref="main"))
    notify = pipe.jobs["notify:staging"]
    # No extends -> should get every default key the job didn't set.
    assert notify.before_script[0].startswith('echo "[ci] starforge')
    assert notify.before_script[1] == "mkdir -p .cache"
    assert notify.extends_chain == []
    # Job kept its own stage/script/needs.
    assert notify.stage == "verify"
    assert notify.needs[0].job == "verify:staging"


def test_default_does_not_override_extends(starforge_root: Path) -> None:
    pipe = Pipeline(starforge_root, Context.push(ref="main"))
    lint_py = pipe.jobs["lint:python"]
    # before_script comes from .python_setup (via extends), NOT from default.
    assert lint_py.before_script[0] == "python -m pip install --upgrade pip"
    assert "echo" not in lint_py.before_script[0]


def test_two_parent_extends_last_wins(starforge_root: Path) -> None:
    pipe = Pipeline(starforge_root, Context.push(ref="main"))
    # Pattern-based assertion: build:web extends both templates, in this order.
    PipelineTesting(pipe).assert_job_exists(
        JobPattern(name="build:web", extends_contains=[".node_setup", ".docker_build"]),
    )
    web = pipe.jobs["build:web"]
    assert web.extends_chain == [".node_setup", ".docker_build"]
    # .docker_build was listed second -> its before_script wins.
    assert web.before_script[0].startswith("docker login")


def test_workflow_drops_pipeline_off_main(starforge_root: Path) -> None:
    pipe = Pipeline(starforge_root, Context.push(ref="topic/x"))
    t = PipelineTesting(pipe)
    t.assert_workflow_dropped()
    t.assert_no_jobs()


def test_main_branch_pipeline_has_all_jobs(starforge_root: Path) -> None:
    pipe = Pipeline(starforge_root, Context.push(ref="main"))
    t = PipelineTesting(pipe)
    t.assert_jobs_exactly([
        "lint:python", "lint:js",
        "test:unit", "test:integration",
        "build:api", "build:web",
        "deploy:api:staging", "deploy:web:staging",
        "deploy:api:prod", "deploy:web:prod",
        "verify:staging", "notify:staging",
        "verify:production",
    ])
    # Production deploys + verification are gated behind manual.
    t.assert_jobs_exist([
        JobPattern(name="deploy:api:prod", when="manual"),
        JobPattern(name="deploy:web:prod", when="manual"),
        JobPattern(name="verify:production", when="manual"),
    ])


def test_mr_pipeline_drops_production(starforge_root: Path) -> None:
    pipe = Pipeline(
        starforge_root,
        Context.mr(source="feat/x", target="main"),
    )
    t = PipelineTesting(pipe)
    # MR has no CI_COMMIT_BRANCH, so the prod jobs' rule (requires main) doesn't match
    # and the jobs are filtered out.
    t.assert_jobs_not_exist(["deploy:api:prod", "deploy:web:prod", "verify:production"])
    # test:integration's rule matches CI_PIPELINE_SOURCE == merge_request_event.
    t.assert_job_exists("test:integration")
    # Nothing manual on MRs — production gates are gone.
    assert PipelineTesting(pipe).match_jobs(JobPattern(when="manual")) == []


def test_dag_edges_match_needs(starforge_root: Path) -> None:
    pipe = Pipeline(starforge_root, Context.push(ref="main"))
    edges = set(pipe.edges)
    # A few load-bearing edges from the DAG.
    assert ("lint:python", "test:unit") in edges
    assert ("test:unit", "build:api") in edges
    assert ("lint:js", "build:web") in edges
    assert ("build:api", "deploy:api:staging") in edges
    assert ("deploy:api:staging", "verify:staging") in edges
    assert ("deploy:web:staging", "verify:staging") in edges
    assert ("verify:staging", "notify:staging") in edges
    assert ("deploy:api:prod", "verify:production") in edges
