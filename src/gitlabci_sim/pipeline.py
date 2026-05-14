"""High-level user-facing `Pipeline` — the one-liner entrypoint for tests + scripts.

Wraps the three-step pipeline build chain (`resolve_includes` → `resolve_references`
→ `compile_pipeline`) into a single constructor:

    pipe = Pipeline("path/to/repo", Context.mr(source="feature/x", target="main"))
    pipe.jobs            # dict[str, Job]
    pipe.stages          # list[str]
    pipe.warnings        # include-resolution warnings
    pipe.compiled        # underlying CompiledPipeline (pydantic), for serialisation

`path` may be a directory (looks for `.gitlab-ci.yml` / `.gitlab-ci.yaml`) or a YAML
file directly. For raw YAML strings, use `Pipeline.from_string(...)`.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from .compiler import compile_pipeline
from .includes import resolve_includes
from .loader import resolve_references
from .model import CompiledPipeline, Job
from .variables import Context


class Pipeline:
    """Loaded + compiled GitLab CI pipeline.

    Attribute access (`jobs`, `stages`, `edges`, `not_triggered`, `workflow_when`,
    `global_variables`, `source_files`) delegates to the underlying CompiledPipeline.
    """

    def __init__(
        self,
        path: str | Path,
        context: Context | None = None,
    ) -> None:
        root = _resolve_entry(Path(path))
        self.context: Context = context or Context()
        self.root: Path = root
        result = resolve_includes(root)
        merged = resolve_references(result.merged)
        self.warnings: list[str] = list(result.warnings)
        self._compiled: CompiledPipeline = compile_pipeline(
            merged, self.context, source_files=result.source_files
        )

    @classmethod
    def from_string(cls, yaml_text: str, context: Context | None = None) -> Pipeline:
        """Compile a single YAML string. No `include:` resolution (single-file only)."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".gitlab-ci.yml", delete=False
        ) as f:
            f.write(yaml_text)
            tmp_path = Path(f.name)
        try:
            return cls(tmp_path, context)
        finally:
            tmp_path.unlink(missing_ok=True)

    @property
    def compiled(self) -> CompiledPipeline:
        """The underlying pydantic CompiledPipeline. Use for serialisation / round-tripping."""
        return self._compiled

    @property
    def jobs(self) -> dict[str, Job]:
        return self._compiled.jobs

    @property
    def not_triggered(self) -> dict[str, Job]:
        return self._compiled.not_triggered

    @property
    def stages(self) -> list[str]:
        return self._compiled.stages

    @property
    def edges(self) -> list[tuple[str, str]]:
        return self._compiled.edges

    @property
    def workflow_when(self) -> str:
        return self._compiled.workflow_when

    @property
    def global_variables(self) -> dict[str, str]:
        return self._compiled.global_variables

    @property
    def source_files(self) -> list[str]:
        return self._compiled.source_files

    def get_job(self, name: str) -> Job:
        """Triggered or not-triggered job by name. Raises KeyError if absent."""
        if name in self._compiled.jobs:
            return self._compiled.jobs[name]
        if name in self._compiled.not_triggered:
            return self._compiled.not_triggered[name]
        raise KeyError(name)

    def __contains__(self, name: str) -> bool:
        return name in self._compiled.jobs

    def __iter__(self):
        return iter(self._compiled.jobs)

    def __len__(self) -> int:
        return len(self._compiled.jobs)

    def __repr__(self) -> str:
        return (
            f"Pipeline(root={self.root.name!r}, "
            f"jobs={len(self._compiled.jobs)}, "
            f"not_triggered={len(self._compiled.not_triggered)})"
        )

    def model_dump(self, **kwargs: Any) -> dict[str, Any]:
        """Pass-through to the underlying CompiledPipeline.model_dump for convenience."""
        return self._compiled.model_dump(**kwargs)

    def model_dump_json(self, **kwargs: Any) -> str:
        return self._compiled.model_dump_json(**kwargs)


def _resolve_entry(path: Path) -> Path:
    """Return the entry YAML path: if `path` is a directory, look for .gitlab-ci.yml."""
    if path.is_file():
        return path
    if path.is_dir():
        for name in (".gitlab-ci.yml", ".gitlab-ci.yaml"):
            candidate = path / name
            if candidate.exists():
                return candidate
        raise FileNotFoundError(f"no .gitlab-ci.yml found in {path}")
    raise FileNotFoundError(f"path does not exist: {path}")


__all__ = ["Pipeline"]
