"""pytest helpers for asserting against compiled CI pipelines.

Typical usage:

    from gitlabci_sim import Pipeline, Context
    from gitlabci_sim.testing import PipelineTesting, JobPattern

    def test_main_pipeline():
        pipe = Pipeline("examples/starforge", Context.push(ref="main"))
        t = PipelineTesting(pipe)
        t.assert_jobs_exist(["lint:python", "build:api"])
        t.assert_job_exists(JobPattern(name="deploy:api:prod", when="manual"))
        t.assert_no_warnings()

`JobPattern` is a declarative matcher. All fields are optional and AND-ed together.
A pattern with no fields set matches every job.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field, fields
from typing import Union

from .model import Job
from .pipeline import Pipeline

JobMatcher = Union[str, "JobPattern"]


@dataclass(frozen=True)
class JobPattern:
    """Declarative matcher for a compiled `Job`.

    All fields are optional and AND-ed together. `name_regex` is matched against
    the full job name (`re.fullmatch`). `needs_contains` / `extends_contains` /
    `script_contains` check that every listed item appears in the job's
    corresponding list. `variables_contains` checks key/value pairs.
    """
    name: str | None = None
    name_regex: str | None = None
    stage: str | None = None
    when: str | None = None
    allow_failure: bool | None = None
    trigger_kind: str | None = None
    needs_contains: list[str] = field(default_factory=list)
    extends_contains: list[str] = field(default_factory=list)
    script_contains: list[str] = field(default_factory=list)
    variables_contains: dict[str, str] = field(default_factory=dict)

    def matches(self, job: Job) -> bool:
        if self.name is not None and job.name != self.name:
            return False
        if self.name_regex is not None and not re.fullmatch(self.name_regex, job.name):
            return False
        if self.stage is not None and job.stage != self.stage:
            return False
        if self.when is not None and job.when != self.when:
            return False
        if self.allow_failure is not None and job.allow_failure != self.allow_failure:
            return False
        if self.trigger_kind is not None:
            actual = job.trigger.kind if job.trigger else None
            if actual != self.trigger_kind:
                return False
        if self.needs_contains:
            actual = {n.job for n in job.needs}
            for n in self.needs_contains:
                if n not in actual:
                    return False
        if self.extends_contains:
            for n in self.extends_contains:
                if n not in job.extends_chain:
                    return False
        if self.script_contains:
            for fragment in self.script_contains:
                if not any(fragment in line for line in job.script):
                    return False
        if self.variables_contains:
            for k, v in self.variables_contains.items():
                if job.variables.get(k) != v:
                    return False
        return True

    def describe(self) -> str:
        """Compact human description like `JobPattern(name='x', when='manual')`."""
        parts: list[str] = []
        for f in fields(self):
            value = getattr(self, f.name)
            if value in (None, [], {}):
                continue
            parts.append(f"{f.name}={value!r}")
        return f"JobPattern({', '.join(parts)})" if parts else "JobPattern(<any>)"


class PipelineAssertionError(AssertionError):
    """Raised by PipelineTesting when an assertion fails. A subclass of AssertionError
    so pytest still treats it as a normal test failure."""


class PipelineTesting:
    """Wrap a `Pipeline` in pytest-friendly assertions.

    All `assert_*` methods raise `PipelineAssertionError` (a subclass of
    `AssertionError`) on failure, with messages designed for pytest output.
    """

    def __init__(self, pipeline: Pipeline) -> None:
        self.pipeline = pipeline

    # ----- existence -----------------------------------------------------

    def assert_job_exists(self, matcher: JobMatcher) -> Job:
        """Assert at least one triggered job matches. Returns the (first) matching job."""
        if isinstance(matcher, str):
            if matcher not in self.pipeline.jobs:
                self._raise_missing(matcher)
            return self.pipeline.jobs[matcher]
        matches = self.match_jobs(matcher)
        if not matches:
            self._raise_no_match(matcher)
        return matches[0]

    def assert_jobs_exist(self, matchers: Iterable[JobMatcher]) -> None:
        """Assert that every listed name/pattern matches at least one job. Reports all
        misses in a single error message rather than failing on the first one."""
        missing: list[str] = []
        for m in matchers:
            if isinstance(m, str):
                if m not in self.pipeline.jobs:
                    missing.append(repr(m))
            else:
                if not self.match_jobs(m):
                    missing.append(m.describe())
        if missing:
            raise PipelineAssertionError(
                "expected jobs to exist but did not match:\n  "
                + "\n  ".join(missing)
                + "\n\nactual jobs: "
                + self._fmt_job_list()
            )

    def assert_job_not_exists(self, matcher: JobMatcher) -> None:
        if isinstance(matcher, str):
            if matcher in self.pipeline.jobs:
                raise PipelineAssertionError(
                    f"expected job {matcher!r} to NOT exist, but it does\n"
                    f"actual jobs: {self._fmt_job_list()}"
                )
            return
        matches = self.match_jobs(matcher)
        if matches:
            raise PipelineAssertionError(
                f"expected no jobs matching {matcher.describe()}, but {len(matches)} did: "
                f"{[j.name for j in matches]}"
            )

    def assert_jobs_not_exist(self, matchers: Iterable[JobMatcher]) -> None:
        unexpected: list[str] = []
        for m in matchers:
            if isinstance(m, str):
                if m in self.pipeline.jobs:
                    unexpected.append(repr(m))
            else:
                hits = self.match_jobs(m)
                if hits:
                    unexpected.append(
                        f"{m.describe()} matched {[j.name for j in hits]}"
                    )
        if unexpected:
            raise PipelineAssertionError(
                "expected jobs to NOT exist but they did:\n  "
                + "\n  ".join(unexpected)
            )

    def assert_jobs_exactly(self, names: Iterable[str]) -> None:
        """Assert the triggered jobs are *exactly* the given set — no more, no less."""
        expected = set(names)
        actual = set(self.pipeline.jobs)
        if expected != actual:
            missing = expected - actual
            extra = actual - expected
            lines = ["pipeline jobs do not match expected set:"]
            if missing:
                lines.append(f"  missing: {sorted(missing)}")
            if extra:
                lines.append(f"  unexpected: {sorted(extra)}")
            raise PipelineAssertionError("\n".join(lines))

    # ----- workflow / counts ---------------------------------------------

    def assert_workflow_dropped(self) -> None:
        """Assert the workflow:rules: dropped the entire pipeline (zero jobs)."""
        if self.pipeline.workflow_when != "never":
            raise PipelineAssertionError(
                f"expected workflow to be dropped (workflow_when='never'), "
                f"but it is {self.pipeline.workflow_when!r} with "
                f"{len(self.pipeline.jobs)} job(s)"
            )

    def assert_workflow_runs(self) -> None:
        """Assert workflow:rules did NOT drop the pipeline."""
        if self.pipeline.workflow_when == "never":
            raise PipelineAssertionError(
                "expected workflow to run, but workflow_when='never' (pipeline dropped)"
            )

    def assert_no_jobs(self) -> None:
        if self.pipeline.jobs:
            raise PipelineAssertionError(
                f"expected zero triggered jobs, got {len(self.pipeline.jobs)}: "
                f"{self._fmt_job_list()}"
            )

    def assert_job_count(
        self,
        triggered: int | None = None,
        not_triggered: int | None = None,
    ) -> None:
        """Assert counts of triggered and/or not-triggered jobs."""
        if triggered is not None and len(self.pipeline.jobs) != triggered:
            raise PipelineAssertionError(
                f"expected {triggered} triggered job(s), got {len(self.pipeline.jobs)}: "
                f"{self._fmt_job_list()}"
            )
        if not_triggered is not None and len(self.pipeline.not_triggered) != not_triggered:
            names = sorted(self.pipeline.not_triggered)
            raise PipelineAssertionError(
                f"expected {not_triggered} not-triggered job(s), "
                f"got {len(self.pipeline.not_triggered)}: {names}"
            )

    def assert_no_warnings(self) -> None:
        """Assert include resolution produced no warnings."""
        if self.pipeline.warnings:
            raise PipelineAssertionError(
                "expected no include-resolution warnings, got:\n  "
                + "\n  ".join(self.pipeline.warnings)
            )

    # ----- matching helpers ----------------------------------------------

    def match_jobs(self, pattern: JobPattern) -> list[Job]:
        """Return every triggered job matching `pattern`, in pipeline insertion order."""
        return [j for j in self.pipeline.jobs.values() if pattern.matches(j)]

    def match_not_triggered(self, pattern: JobPattern) -> list[Job]:
        """Same as `match_jobs` but against `pipeline.not_triggered`."""
        return [j for j in self.pipeline.not_triggered.values() if pattern.matches(j)]

    # ----- internal helpers ----------------------------------------------

    def _fmt_job_list(self) -> str:
        names = sorted(self.pipeline.jobs)
        if not names:
            return "<none>"
        return ", ".join(names)

    def _raise_missing(self, name: str) -> None:
        not_trig = name in self.pipeline.not_triggered
        hint = (
            f" (it was filtered out by rules — see pipeline.not_triggered[{name!r}])"
            if not_trig
            else ""
        )
        raise PipelineAssertionError(
            f"expected job {name!r} to exist{hint}\n"
            f"actual jobs: {self._fmt_job_list()}"
        )

    def _raise_no_match(self, pattern: JobPattern) -> None:
        raise PipelineAssertionError(
            f"no job matched {pattern.describe()}\n"
            f"actual jobs: {self._fmt_job_list()}"
        )


__all__ = ["JobPattern", "PipelineTesting", "PipelineAssertionError"]
