"""Resolve `extends:` chains.

GitLab semantics:
- A job may extend one or more parents (string or list).
- Parents are merged in order; the child's own keys override.
- Merge is deep for mappings (e.g. variables), but list/scalar values replace wholesale.
- Hidden jobs (names starting with `.`) are templates that can be extended but never run.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

# Top-level keys in a CI config that are NOT jobs.
NON_JOB_KEYS = {
    "stages",
    "variables",
    "default",
    "workflow",
    "include",
    "image",
    "services",
    "before_script",
    "after_script",
    "cache",
    "pages",
}


def is_job_key(name: str, value: Any) -> bool:
    if name in NON_JOB_KEYS:
        return False
    if not isinstance(value, dict):
        return False
    return True


def resolve_all_extends(config: dict[str, Any]) -> dict[str, Any]:
    """Return a new config where every job has its `extends:` chain flattened in-place."""
    out = deepcopy(config)
    job_names = [k for k, v in out.items() if is_job_key(k, v)]
    resolved: dict[str, dict[str, Any]] = {}
    for name in job_names:
        resolved[name] = _resolve_job(name, out, resolved, stack=())
    for name, job in resolved.items():
        out[name] = job
    return out


def _resolve_job(
    name: str,
    config: dict[str, Any],
    cache: dict[str, dict[str, Any]],
    stack: tuple[str, ...],
) -> dict[str, Any]:
    if name in cache:
        return cache[name]
    if name in stack:
        raise ValueError(f"extends cycle: {' -> '.join((*stack, name))}")
    raw = config.get(name)
    if not isinstance(raw, dict):
        raise KeyError(f"extends target not found or not a job: {name}")

    parents_spec = raw.get("extends")
    parents = _normalize_parents(parents_spec)

    merged: dict[str, Any] = {}
    chain: list[str] = []
    for parent in parents:
        parent_resolved = _resolve_job(parent, config, cache, stack=(*stack, name))
        chain.extend(parent_resolved.get("_extends_chain", []))
        chain.append(parent)
        _deep_merge(merged, parent_resolved)

    own = {k: v for k, v in raw.items() if k != "extends"}
    _deep_merge(merged, own)
    if chain:
        merged["_extends_chain"] = chain
    cache[name] = merged
    return merged


def _normalize_parents(spec: Any) -> list[str]:
    if spec is None:
        return []
    if isinstance(spec, str):
        return [spec]
    if isinstance(spec, list):
        return [str(s) for s in spec]
    raise ValueError(f"extends must be string or list, got {type(spec).__name__}")


def _deep_merge(dst: dict[str, Any], src: dict[str, Any]) -> None:
    """Mutate dst, layering src on top. Mappings merge deeply; everything else replaces."""
    for k, v in src.items():
        if k == "_extends_chain":
            continue
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _deep_merge(dst[k], v)
        else:
            dst[k] = deepcopy(v)
