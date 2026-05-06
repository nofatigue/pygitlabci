"""Recursive `include:` resolver — local files only for v1.

GitLab's `include:` accepts several forms; we handle the local subset:

    include: path/to/file.yml
    include:
      - path/to/file.yml
      - local: path/to/other.yml
    include:
      local: path/to/file.yml
    include:
      - template: Security/SAST.gitlab-ci.yml

Path resolution: include paths are resolved against the **root project directory**
(the directory containing the entry `.gitlab-ci.yml`), not the file containing the
include directive — this matches GitLab's semantics. Leading `/` is stripped.

`template:` includes are resolved offline against `<project_root>/templates/<path>`.
Drop a copy of the GitLab template under `templates/` in the project to satisfy
`- template: Foo/Bar.gitlab-ci.yml`. If the file isn't there we warn and skip.

Globs (`*`, `**`) are expanded against the root project dir; matches are sorted for
determinism. Remote/project includes are recorded but skipped with a warning.

`default:` blocks across files are merged per-key, with the file declaring the include
beating the included file (matches GitLab's "main file wins" precedence). All other
top-level keys use shallow override.
"""
from __future__ import annotations

from copy import deepcopy
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

    The directory containing `root_path` is treated as the project root for
    resolving include paths and glob expansion.
    """
    root_path = root_path.resolve()
    project_root = root_path.parent
    seen: set[Path] = set()
    sources: list[str] = []
    warnings: list[str] = []
    merged = _load_with_includes(root_path, project_root, seen, sources, warnings)
    return IncludeResult(merged=merged, source_files=sources, warnings=warnings)


def _load_with_includes(
    path: Path,
    project_root: Path,
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

    for kind, pattern in _normalize_include(include_spec, warnings):
        for local_path in _expand_include(kind, pattern, project_root, warnings):
            sub = _load_with_includes(local_path, project_root, seen, sources, warnings)
            _merge_top_level(accumulated, sub)

    _merge_top_level(accumulated, raw)
    return accumulated


def _normalize_include(spec: Any, warnings: list[str]) -> list[tuple[str, str]]:
    """Return list of (kind, pattern) entries; warn on unsupported forms.

    Kinds: `local` (regular path/glob, project-root-relative), `template` (resolved
    against `<project_root>/templates/`).
    """
    if spec is None:
        return []
    items = spec if isinstance(spec, list) else [spec]
    out: list[tuple[str, str]] = []
    for item in items:
        if isinstance(item, str):
            out.append(("local", item))
        elif isinstance(item, dict):
            if "local" in item:
                out.append(("local", item["local"]))
            elif "template" in item:
                out.append(("template", item["template"]))
            elif "remote" in item:
                warnings.append(f"include: remote ({item['remote']}) skipped — local-only in v1")
            elif "project" in item:
                warnings.append(f"include: project ({item['project']}) skipped — local-only in v1")
            else:
                warnings.append(f"include: unrecognised form skipped: {item}")
        else:
            warnings.append(f"include: unrecognised form skipped: {item}")
    return out


def _expand_include(
    kind: str, pattern: str, project_root: Path, warnings: list[str],
) -> list[Path]:
    if kind == "template":
        return _expand_template(pattern, project_root, warnings)
    return _expand_local(pattern, project_root, warnings)


def _expand_template(pattern: str, project_root: Path, warnings: list[str]) -> list[Path]:
    """Resolve a `template:` include against `<project_root>/templates/<path>`.

    No network access; this is the offline fallback. If you need the GitLab-shipped
    template, fetch it once and commit it under `templates/` in your project (the
    wireshark example does this for Security/SAST.gitlab-ci.yml).
    """
    cleaned = pattern.lstrip("/")
    candidate = (project_root / "templates" / cleaned).resolve()
    if candidate.is_file():
        return [candidate]
    warnings.append(
        f"include: template ({pattern}) skipped — drop a copy at "
        f"{project_root.name}/templates/{cleaned} to enable"
    )
    return []


def _expand_local(pattern: str, project_root: Path, warnings: list[str]) -> list[Path]:
    """Resolve a local include pattern against the project root.

    Supports `*` and `**` globs. Leading `/` is stripped (GitLab treats `/foo` as
    project-root-relative, same as `foo`).
    """
    cleaned = pattern.lstrip("/")
    if not _has_glob(cleaned):
        return [(project_root / cleaned).resolve()]
    matches = sorted(project_root.glob(cleaned))
    if not matches:
        warnings.append(f"include: glob '{pattern}' matched no files")
        return []
    return [m.resolve() for m in matches if m.is_file()]


def _has_glob(s: str) -> bool:
    return any(ch in s for ch in "*?[")


_DEFAULT_KEYS = {
    "after_script", "artifacts", "before_script", "cache", "hooks",
    "id_tokens", "image", "interruptible", "retry", "services", "tags",
}


def _merge_top_level(dst: dict[str, Any], src: dict[str, Any]) -> None:
    """Top-level keys: src overrides dst, except `default:` which merges per-key."""
    for k, v in src.items():
        if k == "default" and isinstance(v, dict) and isinstance(dst.get("default"), dict):
            merged_default = deepcopy(dst["default"])
            for dk, dv in v.items():
                merged_default[dk] = deepcopy(dv)
            dst["default"] = merged_default
        else:
            dst[k] = v


__all__ = ["resolve_includes", "IncludeResult"]
