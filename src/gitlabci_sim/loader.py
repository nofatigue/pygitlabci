"""YAML loading with GitLab-specific !reference tag support.

GitLab's `!reference [job, key]` is a custom tag that splices in another node's value.
We round-trip with ruamel.yaml so anchors/aliases also work, then walk the result and
resolve references after `include:` has flattened everything into a single mapping.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq


class Reference:
    """Marker for an unresolved !reference [a, b, c]."""
    __slots__ = ("path",)

    def __init__(self, path: list[str]) -> None:
        self.path = path

    def __repr__(self) -> str:
        return f"Reference({self.path!r})"


def _yaml() -> YAML:
    yaml = YAML(typ="rt")
    yaml.preserve_quotes = True

    def _ref_constructor(constructor, node):  # type: ignore[no-untyped-def]
        # node is a SequenceNode of strings.
        seq = constructor.construct_sequence(node, deep=True)
        return Reference(list(seq))

    yaml.constructor.add_constructor("!reference", _ref_constructor)
    return yaml


def load_yaml(path: Path) -> Any:
    """Load a single YAML file, returning a plain dict/list tree (with Reference markers)."""
    with path.open("r") as f:
        data = _yaml().load(f)
    return _to_plain(data)


def load_yaml_string(text: str) -> Any:
    data = _yaml().load(text)
    return _to_plain(data)


def _to_plain(node: Any) -> Any:
    """Convert ruamel CommentedMap/Seq into plain dict/list, preserving Reference markers."""
    if isinstance(node, CommentedMap) or isinstance(node, dict):
        return {str(k): _to_plain(v) for k, v in node.items()}
    if isinstance(node, CommentedSeq) or isinstance(node, list):
        return [_to_plain(v) for v in node]
    return node


def resolve_references(root: dict[str, Any]) -> dict[str, Any]:
    """Walk the tree, replacing Reference markers with the value at the given path.

    `root` is the merged top-level dict (after include: resolution). References point at
    job-level keys, e.g. `!reference [.shared, script]` → root[".shared"]["script"].
    """
    def walk(node: Any) -> Any:
        if isinstance(node, Reference):
            return _resolve_path(root, node.path)
        if isinstance(node, dict):
            return {k: walk(v) for k, v in node.items()}
        if isinstance(node, list):
            out: list[Any] = []
            for item in node:
                resolved = walk(item)
                # !reference inside a list splices flat (matches GitLab behaviour for
                # script/before_script lists).
                if isinstance(item, Reference) and isinstance(resolved, list):
                    out.extend(resolved)
                else:
                    out.append(resolved)
            return out
        return node

    return walk(root)


def _resolve_path(root: dict[str, Any], path: list[str]) -> Any:
    cur: Any = root
    for part in path:
        if not isinstance(cur, dict) or part not in cur:
            raise KeyError(f"!reference path not found: {path}")
        cur = cur[part]
    # Resolve nested references in the result too.
    if isinstance(cur, (dict, list, Reference)):
        return _walk_inline(root, cur)
    return cur


def _walk_inline(root: dict[str, Any], node: Any) -> Any:
    if isinstance(node, Reference):
        return _resolve_path(root, node.path)
    if isinstance(node, dict):
        return {k: _walk_inline(root, v) for k, v in node.items()}
    if isinstance(node, list):
        out: list[Any] = []
        for item in node:
            resolved = _walk_inline(root, item)
            if isinstance(item, Reference) and isinstance(resolved, list):
                out.extend(resolved)
            else:
                out.append(resolved)
        return out
    return node
