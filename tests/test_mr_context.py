"""Context.predefined() shape across pipeline_source values.

The MR mode is the interesting one: CI_MERGE_REQUEST_* must appear, and
CI_COMMIT_BRANCH must NOT — real GitLab MR pipelines run on the merge
result, so they don't have a single source branch they're on.
"""
from __future__ import annotations

from gitlabci_sim.variables import Context


def test_push_sets_commit_branch_and_no_mr_vars() -> None:
    env = Context(ref="feature/x", pipeline_source="push").predefined()

    assert env["CI_PIPELINE_SOURCE"] == "push"
    assert env["CI_COMMIT_BRANCH"] == "feature/x"
    assert env["CI_COMMIT_REF_NAME"] == "feature/x"
    assert "CI_MERGE_REQUEST_IID" not in env
    assert "CI_MERGE_REQUEST_SOURCE_BRANCH_NAME" not in env
    assert "CI_MERGE_REQUEST_TARGET_BRANCH_NAME" not in env
    assert "CI_COMMIT_TAG" not in env


def test_tag_sets_commit_tag_and_omits_branch() -> None:
    env = Context(ref="v1.2.3", pipeline_source="tag").predefined()

    assert env["CI_PIPELINE_SOURCE"] == "tag"
    assert env["CI_COMMIT_TAG"] == "v1.2.3"
    assert "CI_COMMIT_BRANCH" not in env
    assert "CI_MERGE_REQUEST_IID" not in env


def test_mr_populates_merge_request_vars_and_omits_commit_branch() -> None:
    ctx = Context(
        ref="feature/widgets",
        pipeline_source="merge_request_event",
        mr_iid=42,
        mr_source_branch="feature/widgets",
        mr_target_branch="main",
        mr_title="Add widgets endpoint",
        mr_labels=["backend", "needs-review"],
    )
    env = ctx.predefined()

    assert env["CI_PIPELINE_SOURCE"] == "merge_request_event"
    assert env["CI_MERGE_REQUEST_IID"] == "42"
    assert env["CI_MERGE_REQUEST_SOURCE_BRANCH_NAME"] == "feature/widgets"
    assert env["CI_MERGE_REQUEST_TARGET_BRANCH_NAME"] == "main"
    assert env["CI_MERGE_REQUEST_TITLE"] == "Add widgets endpoint"
    assert env["CI_MERGE_REQUEST_LABELS"] == "backend,needs-review"
    # The defining absence: configs that gate on $CI_COMMIT_BRANCH must see it
    # missing in MR mode (matches GitLab semantics).
    assert "CI_COMMIT_BRANCH" not in env
    # CI_COMMIT_REF_NAME still tracks the source branch.
    assert env["CI_COMMIT_REF_NAME"] == "feature/widgets"


def test_mr_with_only_required_fields_uses_safe_defaults() -> None:
    # Bare-minimum MR Context (no IID, branches, title, labels): predefined()
    # should still emit usable defaults so configs don't choke on missing vars.
    env = Context(pipeline_source="merge_request_event").predefined()

    assert env["CI_MERGE_REQUEST_IID"] == "1"
    assert env["CI_MERGE_REQUEST_SOURCE_BRANCH_NAME"] == "main"  # falls back to ref
    assert env["CI_MERGE_REQUEST_TARGET_BRANCH_NAME"] == "main"
    assert env["CI_MERGE_REQUEST_LABELS"] == ""
    assert "CI_MERGE_REQUEST_TITLE" not in env
