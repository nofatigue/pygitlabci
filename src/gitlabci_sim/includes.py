"""Recursive `include:` resolver — local files only for v1.

GitLab's `include:` accepts several forms; we handle the local subset:

    include: path/to/file.yml
    include:
      - path/to/file.yml
      - local: path/to/other.yml
    include:
      local: path/to/file.yml

Remote/project/template includes are recorded but skipped with a warning.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .loader import load_yaml


@dataclass
class IncludeResult:
    merged: dict[str, Any]
    source_files: list[str]
    warnings: list[str] = field(default_factory=list)


def resolve_includes(root_path: Path) -> IncludeResult:
    """Load `root_path` and recursively merge any `include:` directives.

    Returns the merged dict (top-level keys union'd; later wins per GitLab semantics) and
    the ordered list of files contributing to the result.
    """
    seen: set[Path] = set()
    sources: list[str] = []
    warnings: list[str] = []
    merged = _load_with_includes(root_path.resolve(), seen, sources, warnings)
    return IncludeResult(merged=merged, source_files=sources, warnings=warnings)


def _load_with_includes(
    path: Path,
    seen: set[Path],
    sources: list[str],
    warnings: list[str],
) -> dict[str, Any]:
    if path in seen:
        raise ValueError(f"include cycle detected at {path}")
    seen.add(path)
    if not path.exists():
        raise FileNotFoundError(f"included file not found: {path}")

    sources.append(str(path))
    raw = load_yaml(path) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"top-level YAML in {path} must be a mapping")

    include_spec = raw.pop("include", None)
    accumulated: dict[str, Any] = {}

    for inc in _normalize_include(include_spec, warnings):
        local_path = (path.parent / inc).resolve()
        sub = _load_with_includes(local_path, seen, sources, warnings)
        _shallow_merge(accumulated, sub)

    _shallow_merge(accumulated, raw)
    return accumulated


def _normalize_include(spec: Any, warnings: list[str]) -> list[str]:
    """Return the list of local file paths to include; warn on unsupported forms."""
    if spec is None:
        return []
    items = spec if isinstance(spec, list) else [spec]
    paths: list[str] = []
    for item in items:
        if isinstance(item, str):
            paths.append(item)
        elif isinstance(item, dict):
            if "local" in item:
                paths.append(item["local"])
            elif "remote" in item:
                warnings.append(f"include: remote ({item['remote']}) skipped — local-only in v1")
            elif "project" in item:
                warnings.append(f"include: project ({item['project']}) skipped — local-only in v1")
            elif "template" in item:
                warnings.append(f"include: template ({item['template']}) skipped — local-only in v1")
            else:
                warnings.append(f"include: unrecognised form skipped: {item}")
        else:
            warnings.append(f"include: unrecognised form skipped: {item}")
    return paths


def _shallow_merge(dst: dict[str, Any], src: dict[str, Any]) -> None:
    """Top-level keys: src overrides dst (matches GitLab include precedence)."""
    for k, v in src.items():
        dst[k] = v
