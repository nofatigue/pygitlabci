"""Variable expansion + predefined GitLab CI variables.

We support the most commonly-relied-on predefined vars. The rest can be supplied via
`--var` flags (or programmatically via `Context`).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

VAR_RE = re.compile(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?")


@dataclass
class Context:
    """Runtime context for evaluating variables / rules."""
    ref: str = "main"
    pipeline_source: str = "push"
    project_path: str = "group/project"
    commit_sha: str = "0" * 40
    changed_files: list[str] = field(default_factory=list)
    extra: dict[str, str] = field(default_factory=dict)
    # MR fields — only emitted as CI_MERGE_REQUEST_* when pipeline_source is
    # "merge_request_event". Defaults are filled in to give configs that read
    # `$CI_MERGE_REQUEST_TARGET_BRANCH_NAME` something sensible to compare.
    mr_iid: int | None = None
    mr_source_branch: str | None = None
    mr_target_branch: str | None = None
    mr_title: str | None = None
    mr_labels: list[str] = field(default_factory=list)

    @classmethod
    def push(
        cls,
        ref: str = "main",
        *,
        changed: list[str] | None = None,
        variables: dict[str, str] | None = None,
        commit_sha: str | None = None,
        project_path: str = "group/project",
    ) -> Context:
        """A branch-push pipeline. Sets `pipeline_source='push'`, populates CI_COMMIT_BRANCH."""
        return cls(
            ref=ref,
            pipeline_source="push",
            changed_files=list(changed or []),
            extra=dict(variables or {}),
            commit_sha=commit_sha or ("0" * 40),
            project_path=project_path,
        )

    @classmethod
    def tag(
        cls,
        name: str,
        *,
        variables: dict[str, str] | None = None,
        commit_sha: str | None = None,
        project_path: str = "group/project",
    ) -> Context:
        """A tag-release pipeline. Sets `pipeline_source='tag'`, CI_COMMIT_TAG=name,
        and omits CI_COMMIT_BRANCH (matching real GitLab tag pipelines)."""
        return cls(
            ref=name,
            pipeline_source="tag",
            extra=dict(variables or {}),
            commit_sha=commit_sha or ("0" * 40),
            project_path=project_path,
        )

    @classmethod
    def mr(
        cls,
        *,
        source: str = "feature/x",
        target: str = "main",
        changed: list[str] | None = None,
        iid: int | None = None,
        title: str | None = None,
        labels: list[str] | None = None,
        variables: dict[str, str] | None = None,
        commit_sha: str | None = None,
        project_path: str = "group/project",
    ) -> Context:
        """A merge-request pipeline. Sets `pipeline_source='merge_request_event'` and the
        CI_MERGE_REQUEST_* predefined vars; omits CI_COMMIT_BRANCH (matching real MR pipelines)."""
        return cls(
            ref=source,
            pipeline_source="merge_request_event",
            changed_files=list(changed or []),
            extra=dict(variables or {}),
            commit_sha=commit_sha or ("0" * 40),
            project_path=project_path,
            mr_iid=iid,
            mr_source_branch=source,
            mr_target_branch=target,
            mr_title=title,
            mr_labels=list(labels or []),
        )

    def predefined(self) -> dict[str, str]:
        env: dict[str, str] = {
            "CI": "true",
            "GITLAB_CI": "true",
            "CI_COMMIT_REF_NAME": self.ref,
            "CI_COMMIT_SHA": self.commit_sha,
            "CI_COMMIT_SHORT_SHA": self.commit_sha[:8],
            "CI_PIPELINE_SOURCE": self.pipeline_source,
            "CI_PROJECT_PATH": self.project_path,
            "CI_PROJECT_NAME": self.project_path.rsplit("/", 1)[-1],
            "CI_DEFAULT_BRANCH": "main",
        }
        if self.pipeline_source == "merge_request_event":
            # Real GitLab MR pipelines run on the merge result, not on a branch,
            # so CI_COMMIT_BRANCH is intentionally absent.
            env["CI_MERGE_REQUEST_IID"] = str(self.mr_iid) if self.mr_iid is not None else "1"
            env["CI_MERGE_REQUEST_SOURCE_BRANCH_NAME"] = self.mr_source_branch or self.ref
            env["CI_MERGE_REQUEST_TARGET_BRANCH_NAME"] = self.mr_target_branch or "main"
            if self.mr_title is not None:
                env["CI_MERGE_REQUEST_TITLE"] = self.mr_title
            env["CI_MERGE_REQUEST_LABELS"] = ",".join(self.mr_labels)
        elif self.pipeline_source == "tag":
            # Tag pipelines: CI_COMMIT_TAG is set, CI_COMMIT_BRANCH is not.
            env["CI_COMMIT_TAG"] = self.ref
        else:
            env["CI_COMMIT_BRANCH"] = self.ref
        return env


def expand(value: Any, env: dict[str, str]) -> Any:
    """Recursively expand $VAR / ${VAR} references in strings inside lists/dicts."""
    if isinstance(value, str):
        return _expand_str(value, env)
    if isinstance(value, list):
        return [expand(v, env) for v in value]
    if isinstance(value, dict):
        return {k: expand(v, env) for k, v in value.items()}
    return value


def _expand_str(s: str, env: dict[str, str]) -> str:
    def repl(m: re.Match[str]) -> str:
        return env.get(m.group(1), m.group(0))
    return VAR_RE.sub(repl, s)


def merge_env(*layers: dict[str, str]) -> dict[str, str]:
    """Layer variable scopes left-to-right; later wins."""
    out: dict[str, str] = {}
    for layer in layers:
        out.update({k: str(v) for k, v in layer.items()})
    return out
