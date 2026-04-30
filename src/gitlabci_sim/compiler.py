"""Compile a merged GitLab CI config into the canonical Pipeline model.

Pipeline assembly order:
1. Resolve includes + !reference (done by caller).
2. Apply `default:` to each job.
3. Resolve `extends:` chains (deep merge).
4. Filter via rules (M3) — done here too if rules module available.
5. Build Job objects, validate stages and needs, compute edges.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from .extends import is_job_key, resolve_all_extends
from .model import Job, Need, Pipeline, Trigger
from .rules import apply_rules
from .variables import Context, expand, merge_env

DEFAULT_STAGES = [".pre", "build", "test", "deploy", ".post"]


class CompileError(ValueError):
    """Raised when a config cannot be compiled into a valid Pipeline."""


def compile_pipeline(
    config: dict[str, Any],
    context: Context | None = None,
    source_files: list[str] | None = None,
) -> Pipeline:
    ctx = context or Context()

    cfg = deepcopy(config)
    stages = _resolve_stages(cfg)
    workflow_when = _resolve_workflow(cfg, ctx)
    if workflow_when == "never":
        return Pipeline(
            stages=stages,
            jobs={},
            edges=[],
            source_files=source_files or [],
            workflow_when="never",
            global_variables=_to_str_dict(cfg.get("variables", {})),
        )

    default_block = cfg.get("default", {}) or {}
    global_vars = _to_str_dict(cfg.get("variables", {}))

    # Apply default + extends to every job.
    cfg = _apply_default(cfg, default_block)
    cfg = resolve_all_extends(cfg)

    raw_jobs = {k: v for k, v in cfg.items() if is_job_key(k, v) and not k.startswith(".")}

    # Build env per job (predefined + global + job-level) and expand variables.
    base_env = merge_env(ctx.predefined(), ctx.extra, global_vars)

    jobs: dict[str, Job] = {}
    for name, raw in raw_jobs.items():
        job_vars = _to_str_dict(raw.get("variables", {}))
        env = merge_env(base_env, job_vars)

        # Rules are evaluated against the *unexpanded* config (the parser handles $VAR).
        rule_outcome = apply_rules(raw, ctx, env)
        if rule_outcome.dropped:
            continue

        # Pre-expand everything except `rules`/`only`/`except` (already consumed).
        expanded = {k: expand(v, env) for k, v in raw.items() if k not in {"rules", "only", "except"}}

        when = rule_outcome.when or expanded.get("when") or "on_success"
        allow_failure = bool(
            rule_outcome.allow_failure
            if rule_outcome.allow_failure is not None
            else expanded.get("allow_failure", False)
        )

        job = Job(
            name=name,
            stage=str(expanded.get("stage", "test")),
            script=_as_str_list(expanded.get("script", [])),
            before_script=_as_str_list(expanded.get("before_script", [])),
            after_script=_as_str_list(expanded.get("after_script", [])),
            needs=_parse_needs(expanded.get("needs")),
            dependencies=_as_str_list(expanded.get("dependencies", [])),
            when=when,
            allow_failure=allow_failure,
            variables=merge_env(job_vars, rule_outcome.extra_variables or {}),
            rules_matched=rule_outcome.matched_rule,
            trigger=_parse_trigger(expanded.get("trigger")),
            extends_chain=expanded.get("_extends_chain", []),
        )
        jobs[name] = job

    _validate_stages(jobs, stages)
    _validate_needs(jobs)
    edges = _compute_edges(jobs, stages)

    return Pipeline(
        stages=stages,
        jobs=jobs,
        edges=edges,
        source_files=source_files or [],
        workflow_when=workflow_when,
        global_variables=global_vars,
    )


def _resolve_stages(cfg: dict[str, Any]) -> list[str]:
    stages = cfg.get("stages")
    if not stages:
        return list(DEFAULT_STAGES)
    if not isinstance(stages, list):
        raise CompileError("stages: must be a list")
    out = list(stages)
    if ".pre" not in out:
        out.insert(0, ".pre")
    if ".post" not in out:
        out.append(".post")
    return out


def _resolve_workflow(cfg: dict[str, Any], ctx: Context) -> str:
    wf = cfg.get("workflow")
    if not wf:
        return "on_success"
    rules = wf.get("rules") if isinstance(wf, dict) else None
    if not rules:
        return "on_success"
    base_env = merge_env(ctx.predefined(), ctx.extra, _to_str_dict(cfg.get("variables", {})))
    outcome = apply_rules({"rules": rules}, ctx, base_env)
    if outcome.dropped:
        return "never"
    return outcome.when or "on_success"


_DEFAULT_KEYS = {
    "image", "services", "before_script", "after_script", "cache",
    "tags", "timeout", "retry", "interruptible", "artifacts",
}


def _apply_default(cfg: dict[str, Any], default: dict[str, Any]) -> dict[str, Any]:
    if not default:
        return cfg
    for name, value in list(cfg.items()):
        if not is_job_key(name, value):
            continue
        for k, v in default.items():
            if k in _DEFAULT_KEYS and k not in value:
                value[k] = deepcopy(v)
    return cfg


def _parse_needs(spec: Any) -> list[Need]:
    if spec is None:
        return []
    out: list[Need] = []
    items = spec if isinstance(spec, list) else [spec]
    for item in items:
        if isinstance(item, str):
            out.append(Need(job=item))
        elif isinstance(item, dict) and "job" in item:
            out.append(
                Need(
                    job=str(item["job"]),
                    artifacts=bool(item.get("artifacts", True)),
                    optional=bool(item.get("optional", False)),
                )
            )
        else:
            raise CompileError(f"unrecognised needs entry: {item!r}")
    return out


def _parse_trigger(spec: Any) -> Trigger | None:
    if spec is None:
        return None
    if isinstance(spec, str):
        # `trigger: group/project` shorthand for downstream multi-project.
        return Trigger(kind="downstream", project=spec)
    if not isinstance(spec, dict):
        return None
    if "project" in spec:
        return Trigger(
            kind="downstream",
            project=str(spec["project"]),
            strategy=spec.get("strategy"),
        )
    include = spec.get("include")
    if include is None:
        return Trigger(kind="unknown")
    items = include if isinstance(include, list) else [include]
    locals_: list[str] = []
    artifact: str | None = None
    artifact_job: str | None = None
    for item in items:
        if isinstance(item, str):
            locals_.append(item)
        elif isinstance(item, dict):
            if "local" in item:
                locals_.append(item["local"])
            elif "artifact" in item:
                artifact = item["artifact"]
                artifact_job = item.get("job")
    if artifact:
        return Trigger(
            kind="child_artifact",
            artifact=artifact,
            job=artifact_job,
            strategy=spec.get("strategy"),
        )
    return Trigger(
        kind="child_local",
        include=locals_,
        strategy=spec.get("strategy"),
    )


def _validate_stages(jobs: dict[str, Job], stages: list[str]) -> None:
    valid = set(stages)
    for job in jobs.values():
        if job.stage not in valid:
            raise CompileError(
                f"job '{job.name}' references unknown stage '{job.stage}' "
                f"(known: {', '.join(stages)})"
            )


def _validate_needs(jobs: dict[str, Job]) -> None:
    names = set(jobs)
    for job in jobs.values():
        for need in job.needs:
            if need.job not in names and not need.optional:
                raise CompileError(
                    f"job '{job.name}' needs unknown job '{need.job}'"
                )
    # cycle detection — DFS over the needs graph.
    white, gray, black = 0, 1, 2
    color: dict[str, int] = {n: white for n in names}

    def visit(n: str, stack: list[str]) -> None:
        if color[n] == gray:
            cycle = stack[stack.index(n):] + [n]
            raise CompileError(f"needs cycle: {' -> '.join(cycle)}")
        if color[n] == black:
            return
        color[n] = gray
        stack.append(n)
        for need in jobs[n].needs:
            if need.job in jobs:
                visit(need.job, stack)
        stack.pop()
        color[n] = black

    for n in names:
        if color[n] == white:
            visit(n, [])


def _compute_edges(jobs: dict[str, Job], stages: list[str]) -> list[tuple[str, str]]:
    """If a job uses needs:, that's the edge set. Otherwise edges follow stage order."""
    edges: list[tuple[str, str]] = []
    stage_idx = {s: i for i, s in enumerate(stages)}
    by_stage: dict[str, list[str]] = {s: [] for s in stages}
    for j in jobs.values():
        by_stage[j.stage].append(j.name)

    for job in jobs.values():
        if job.needs:
            for need in job.needs:
                if need.job in jobs:
                    edges.append((need.job, job.name))
            continue
        # No needs: depends on all jobs in the previous stage.
        idx = stage_idx[job.stage]
        for prev_idx in range(idx - 1, -1, -1):
            prev_jobs = by_stage[stages[prev_idx]]
            if prev_jobs:
                for prev in prev_jobs:
                    edges.append((prev, job.name))
                break
    return edges


def _as_str_list(v: Any) -> list[str]:
    if v is None:
        return []
    if isinstance(v, str):
        return [v]
    if isinstance(v, list):
        out: list[str] = []
        for item in v:
            if isinstance(item, list):
                out.extend(str(i) for i in item)
            else:
                out.append(str(item))
        return out
    return [str(v)]


def _to_str_dict(d: Any) -> dict[str, str]:
    if not isinstance(d, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in d.items():
        if isinstance(v, dict) and "value" in v:
            out[str(k)] = str(v["value"])
        else:
            out[str(k)] = str(v)
    return out


__all__ = ["compile_pipeline", "CompileError"]
