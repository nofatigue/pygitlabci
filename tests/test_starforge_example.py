"""End-to-end parsing/compilation of the starforge example.

Covers: glob includes, root-relative include resolution, multi-file `default:` merging,
extends + default precedence, and rule-driven job filtering across pipeline sources.
"""
from pathlib import Path

import pytest

from gitlabci_sim.compiler import compile_pipeline
from gitlabci_sim.includes import resolve_includes
from gitlabci_sim.loader import resolve_references
from gitlabci_sim.variables import Context


@pytest.fixture(scope="module")
def starforge_root(examples_dir: Path) -> Path:
    return examples_dir / "starforge" / ".gitlab-ci.yml"


def _compile(path: Path, ctx: Context):
    res = resolve_includes(path)
    cfg = resolve_references(res.merged)
    return compile_pipeline(cfg, ctx, res.source_files), res


def test_all_files_loaded_via_globs(starforge_root: Path) -> None:
    res = resolve_includes(starforge_root)
    # Entry + 13 includes, all reached via globs except the two named deploy files.
    assert len(res.source_files) == 14
    assert res.warnings == []
    expected = {
        "ci/defaults/base.yml", "ci/defaults/before.yml",
        "ci/templates/python.yml", "ci/templates/nodejs.yml",
        "ci/templates/docker.yml", "ci/templates/deploy.yml",
        "ci/stages/lint.yml", "ci/stages/test.yml", "ci/stages/build.yml",
        "ci/services/api.yml", "ci/services/web.yml",
        "ci/deploy/staging.yml", "ci/deploy/production.yml",
    }
    found = {str(Path(s).relative_to(starforge_root.parent)) for s in res.source_files
             if Path(s) != starforge_root}
    assert found == expected


def test_multi_file_default_merges_per_key(starforge_root: Path) -> None:
    res = resolve_includes(starforge_root)
    default = res.merged["default"]
    # base.yml contributed image + interruptible.
    assert default["image"] == "registry.example.com/builders/ubuntu:22.04"
    assert default["interruptible"] is True
    # before.yml contributed before_script.
    assert default["before_script"][0].startswith('echo "[ci]')
    # Main file contributed tags + overrode retry (was 2 in base.yml, now 1).
    assert default["tags"] == ["kubernetes", "linux"]
    assert default["retry"] == 1


def test_default_fills_in_jobs_without_extends(starforge_root: Path) -> None:
    pipeline, _ = _compile(starforge_root, Context(ref="main", pipeline_source="push"))
    notify = pipeline.jobs["notify:staging"]
    # No extends -> should get every default key the job didn't set.
    assert notify.before_script[0].startswith('echo "[ci] starforge')
    assert notify.before_script[1] == "mkdir -p .cache"
    assert notify.extends_chain == []
    # Job kept its own stage/script/needs.
    assert notify.stage == "verify"
    assert notify.needs[0].job == "verify:staging"


def test_default_does_not_override_extends(starforge_root: Path) -> None:
    pipeline, _ = _compile(starforge_root, Context(ref="main", pipeline_source="push"))
    lint_py = pipeline.jobs["lint:python"]
    # before_script comes from .python_setup (via extends), NOT from default.
    assert lint_py.before_script[0] == "python -m pip install --upgrade pip"
    assert "echo" not in lint_py.before_script[0]


def test_two_parent_extends_last_wins(starforge_root: Path) -> None:
    pipeline, _ = _compile(starforge_root, Context(ref="main", pipeline_source="push"))
    web = pipeline.jobs["build:web"]
    assert web.extends_chain == [".node_setup", ".docker_build"]
    # .docker_build was listed second -> its before_script wins.
    assert web.before_script[0].startswith("docker login")


def test_workflow_drops_pipeline_off_main(starforge_root: Path) -> None:
    pipeline, _ = _compile(starforge_root, Context(ref="topic/x", pipeline_source="push"))
    assert pipeline.workflow_when == "never"
    assert pipeline.jobs == {}


def test_main_branch_pipeline_has_all_jobs(starforge_root: Path) -> None:
    pipeline, _ = _compile(starforge_root, Context(ref="main", pipeline_source="push"))
    names = set(pipeline.jobs)
    assert names == {
        "lint:python", "lint:js",
        "test:unit", "test:integration",
        "build:api", "build:web",
        "deploy:api:staging", "deploy:web:staging",
        "deploy:api:prod", "deploy:web:prod",
        "verify:staging", "notify:staging",
        "verify:production",
    }
    # Production deploys + verification are gated behind manual.
    for manual_job in ("deploy:api:prod", "deploy:web:prod", "verify:production"):
        assert pipeline.jobs[manual_job].when == "manual"


def test_mr_pipeline_drops_production(starforge_root: Path) -> None:
    ctx = Context(
        ref="feat/x",
        pipeline_source="merge_request_event",
        mr_source_branch="feat/x",
        mr_target_branch="main",
    )
    pipeline, _ = _compile(starforge_root, ctx)
    names = set(pipeline.jobs)
    # MR has no CI_COMMIT_BRANCH, so the prod jobs' rule (requires main) doesn't match
    # and the jobs are filtered out.
    assert "deploy:api:prod" not in names
    assert "deploy:web:prod" not in names
    assert "verify:production" not in names
    # test:integration's rule matches CI_PIPELINE_SOURCE == merge_request_event.
    assert "test:integration" in names


def test_dag_edges_match_needs(starforge_root: Path) -> None:
    pipeline, _ = _compile(starforge_root, Context(ref="main", pipeline_source="push"))
    edges = set(pipeline.edges)
    # A few load-bearing edges from the DAG.
    assert ("lint:python", "test:unit") in edges
    assert ("test:unit", "build:api") in edges
    assert ("lint:js", "build:web") in edges
    assert ("build:api", "deploy:api:staging") in edges
    assert ("deploy:api:staging", "verify:staging") in edges
    assert ("deploy:web:staging", "verify:staging") in edges
    assert ("verify:staging", "notify:staging") in edges
    assert ("deploy:api:prod", "verify:production") in edges
