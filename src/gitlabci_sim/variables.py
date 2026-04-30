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

    def predefined(self) -> dict[str, str]:
        return {
            "CI": "true",
            "GITLAB_CI": "true",
            "CI_COMMIT_REF_NAME": self.ref,
            "CI_COMMIT_BRANCH": self.ref,
            "CI_COMMIT_SHA": self.commit_sha,
            "CI_COMMIT_SHORT_SHA": self.commit_sha[:8],
            "CI_PIPELINE_SOURCE": self.pipeline_source,
            "CI_PROJECT_PATH": self.project_path,
            "CI_PROJECT_NAME": self.project_path.rsplit("/", 1)[-1],
            "CI_DEFAULT_BRANCH": "main",
        }


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
