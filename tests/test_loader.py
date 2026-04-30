from pathlib import Path

from gitlabci_sim.includes import resolve_includes
from gitlabci_sim.loader import Reference, load_yaml_string, resolve_references


def test_load_simple(examples_dir: Path) -> None:
    res = resolve_includes(examples_dir / "simple" / ".gitlab-ci.yml")
    assert "build" in res.merged
    assert "deploy" in res.merged
    assert res.merged["stages"] == ["build", "test", "deploy"]
    assert len(res.source_files) == 1


def test_includes_merge(examples_dir: Path) -> None:
    res = resolve_includes(examples_dir / "with_includes" / ".gitlab-ci.yml")
    # Top-level keys from all files should be present.
    assert "build_app" in res.merged       # from templates/build.yml
    assert "deploy_app" in res.merged      # from templates/deploy.yml
    assert "unit_test" in res.merged       # from root
    assert ".python_job" in res.merged     # template (hidden) job
    assert len(res.source_files) == 3


def test_reference_tag_resolves() -> None:
    text = """
.shared:
  script:
    - echo one
    - echo two
job:
  script:
    - !reference [.shared, script]
    - echo three
"""
    raw = load_yaml_string(text)
    # !reference appears as a Reference marker before resolution.
    assert isinstance(raw["job"]["script"][0], Reference)
    resolved = resolve_references(raw)
    assert resolved["job"]["script"] == ["echo one", "echo two", "echo three"]


def test_yaml_anchor_alias() -> None:
    text = """
.shared: &shared
  - one
  - two
job:
  script:
    - *shared
    - three
"""
    raw = load_yaml_string(text)
    # ruamel resolves YAML anchors at load time.
    # The aliased list shows up as a nested list at position 0.
    assert raw["job"]["script"][0] == ["one", "two"]
    assert raw["job"]["script"][1] == "three"
