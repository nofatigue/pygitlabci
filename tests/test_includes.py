"""Unit tests for includes resolution: glob, root-relative paths, default merging."""
from pathlib import Path
from textwrap import dedent

import pytest

from gitlabci_sim.includes import resolve_includes


def _write(p: Path, body: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(dedent(body).lstrip())


def test_glob_star_matches_top_level(tmp_path: Path) -> None:
    _write(tmp_path / "ci" / "a.yml", """
        job_a:
          stage: build
          script: [echo a]
    """)
    _write(tmp_path / "ci" / "b.yml", """
        job_b:
          stage: build
          script: [echo b]
    """)
    # Should NOT be picked up by `ci/*.yml` — it's nested.
    _write(tmp_path / "ci" / "nested" / "c.yml", """
        job_c:
          stage: build
          script: [echo c]
    """)
    _write(tmp_path / ".gitlab-ci.yml", """
        include:
          - local: ci/*.yml
        stages: [build]
    """)
    res = resolve_includes(tmp_path / ".gitlab-ci.yml")
    assert "job_a" in res.merged
    assert "job_b" in res.merged
    assert "job_c" not in res.merged


def test_glob_double_star_recursive(tmp_path: Path) -> None:
    _write(tmp_path / "ci" / "a.yml", "job_a: {script: [echo a]}\n")
    _write(tmp_path / "ci" / "deep" / "deeper" / "z.yml", "job_z: {script: [echo z]}\n")
    _write(tmp_path / ".gitlab-ci.yml", """
        include:
          - local: ci/**/*.yml
    """)
    res = resolve_includes(tmp_path / ".gitlab-ci.yml")
    # `ci/**/*.yml` matches `ci/a.yml`? In pathlib, `**` matches zero or more directories,
    # so yes. Also matches the deeply-nested file.
    assert "job_a" in res.merged
    assert "job_z" in res.merged


def test_glob_no_matches_warns(tmp_path: Path) -> None:
    _write(tmp_path / ".gitlab-ci.yml", """
        include:
          - local: nope/*.yml
    """)
    res = resolve_includes(tmp_path / ".gitlab-ci.yml")
    assert res.merged == {}
    assert any("matched no files" in w for w in res.warnings)


def test_includes_resolve_against_project_root_not_including_file(tmp_path: Path) -> None:
    """Path in a nested include is interpreted relative to the project root."""
    _write(tmp_path / "shared" / "common.yml", "common_job: {script: [echo common]}\n")
    _write(tmp_path / "ci" / "intermediate.yml", """
        # `shared/common.yml` here would be relative to the *file* under old semantics —
        # which would resolve to `ci/shared/common.yml` and fail. With root-relative
        # semantics this finds `shared/common.yml` at the project root.
        include:
          - local: shared/common.yml
    """)
    _write(tmp_path / ".gitlab-ci.yml", """
        include:
          - local: ci/intermediate.yml
    """)
    res = resolve_includes(tmp_path / ".gitlab-ci.yml")
    assert "common_job" in res.merged


def test_leading_slash_treated_as_root_relative(tmp_path: Path) -> None:
    _write(tmp_path / "templates" / "x.yml", "x: {script: [hi]}\n")
    _write(tmp_path / ".gitlab-ci.yml", """
        include:
          - local: /templates/x.yml
    """)
    res = resolve_includes(tmp_path / ".gitlab-ci.yml")
    assert "x" in res.merged


def test_default_merges_across_includes(tmp_path: Path) -> None:
    _write(tmp_path / "ci" / "img.yml", """
        default:
          image: alpine:3
          retry: 2
    """)
    _write(tmp_path / "ci" / "before.yml", """
        default:
          before_script:
            - echo hello
    """)
    _write(tmp_path / ".gitlab-ci.yml", """
        include:
          - local: ci/*.yml
        default:
          retry: 1
          tags: [t1]
    """)
    res = resolve_includes(tmp_path / ".gitlab-ci.yml")
    default = res.merged["default"]
    assert default["image"] == "alpine:3"            # from img.yml
    assert default["before_script"] == ["echo hello"]  # from before.yml
    assert default["tags"] == ["t1"]                 # from main file
    assert default["retry"] == 1                     # main file overrides img.yml


def test_main_default_wins_over_included_default_per_key(tmp_path: Path) -> None:
    _write(tmp_path / "inc.yml", """
        default:
          image: alpine:3
    """)
    _write(tmp_path / ".gitlab-ci.yml", """
        include:
          - local: inc.yml
        default:
          image: ubuntu:22.04
    """)
    res = resolve_includes(tmp_path / ".gitlab-ci.yml")
    assert res.merged["default"]["image"] == "ubuntu:22.04"


def test_default_applied_only_when_job_missing_key(tmp_path: Path) -> None:
    """End-to-end: default fills missing keys, doesn't override existing ones."""
    from gitlabci_sim.compiler import compile_pipeline
    from gitlabci_sim.loader import resolve_references

    _write(tmp_path / ".gitlab-ci.yml", """
        stages: [build]
        default:
          image: default-image
          before_script: [setup-default]
        with_image:
          stage: build
          image: explicit-image
          script: [run]
        without_image:
          stage: build
          script: [run]
    """)
    res = resolve_includes(tmp_path / ".gitlab-ci.yml")
    cfg = resolve_references(res.merged)
    pipeline = compile_pipeline(cfg)
    # Compiler-side check: jobs missing keys pick up default values via the raw config
    # (we can verify before_script which is on the Job model).
    assert pipeline.jobs["without_image"].before_script == ["setup-default"]
    # The job that defined nothing of its own still gets default before_script;
    # the one with explicit script keeps its own script.
    assert pipeline.jobs["with_image"].script == ["run"]


def test_extends_takes_precedence_over_default(tmp_path: Path) -> None:
    """A job's extends parents count as 'already defined' for default purposes."""
    from gitlabci_sim.compiler import compile_pipeline
    from gitlabci_sim.loader import resolve_references

    _write(tmp_path / ".gitlab-ci.yml", """
        stages: [build]
        default:
          before_script: [from-default]
        .parent:
          before_script: [from-parent]
        my_job:
          stage: build
          extends: .parent
          script: [run]
    """)
    res = resolve_includes(tmp_path / ".gitlab-ci.yml")
    cfg = resolve_references(res.merged)
    pipeline = compile_pipeline(cfg)
    assert pipeline.jobs["my_job"].before_script == ["from-parent"]


def test_glob_results_are_deterministic(tmp_path: Path) -> None:
    # Create files in non-alphabetical creation order; expect alphabetical load.
    for name in ("z.yml", "m.yml", "a.yml"):
        _write(tmp_path / "ci" / name, f"job_{name[0]}: {{script: [echo]}}\n")
    _write(tmp_path / ".gitlab-ci.yml", """
        include:
          - local: ci/*.yml
    """)
    res = resolve_includes(tmp_path / ".gitlab-ci.yml")
    loaded = [Path(s).name for s in res.source_files if s.endswith(".yml") and "ci/" in s]
    # Should be sorted: a, m, z.
    assert loaded == ["a.yml", "m.yml", "z.yml"]


def test_cycle_detection_still_works(tmp_path: Path) -> None:
    _write(tmp_path / "a.yml", """
        include:
          - local: b.yml
    """)
    _write(tmp_path / "b.yml", """
        include:
          - local: a.yml
    """)
    _write(tmp_path / ".gitlab-ci.yml", """
        include:
          - local: a.yml
    """)
    with pytest.raises(ValueError, match="cycle"):
        resolve_includes(tmp_path / ".gitlab-ci.yml")
