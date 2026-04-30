import pytest

from gitlabci_sim.rules import apply_rules, eval_if
from gitlabci_sim.variables import Context


@pytest.mark.parametrize(
    "expr,env,expected",
    [
        ('$REF == "main"', {"REF": "main"}, True),
        ('$REF == "main"', {"REF": "feature"}, False),
        ('$REF != "main"', {"REF": "feature"}, True),
        ('$X == "a" && $Y == "b"', {"X": "a", "Y": "b"}, True),
        ('$X == "a" && $Y == "b"', {"X": "a", "Y": "c"}, False),
        ('$X == "a" || $Y == "b"', {"X": "a", "Y": "c"}, True),
        ('$REF =~ /^feat/', {"REF": "feature/x"}, True),
        ('$REF !~ /^feat/', {"REF": "main"}, True),
        ('$VAR', {"VAR": "anything"}, True),
        ('$VAR', {"VAR": ""}, False),
        ('$VAR', {}, False),
        ('!($X == "a")', {"X": "b"}, True),
        ('($X == "a") && ($Y == "b")', {"X": "a", "Y": "b"}, True),
        ('$X == "a" && ($Y == "b" || $Z == "c")', {"X": "a", "Z": "c"}, True),
    ],
)
def test_eval_if(expr, env, expected):
    assert eval_if(expr, env) is expected


def test_rules_first_match_wins():
    job = {
        "rules": [
            {"if": '$REF == "main"', "when": "on_success"},
            {"if": '$REF =~ /feat/', "when": "manual"},
            {"when": "never"},
        ],
    }
    out = apply_rules(job, Context(ref="feature/x"), {"REF": "feature/x"})
    assert not out.dropped
    assert out.when == "manual"


def test_rules_no_match_drops():
    job = {"rules": [{"if": '$REF == "main"'}]}
    out = apply_rules(job, Context(ref="other"), {"REF": "other"})
    assert out.dropped


def test_rules_when_never_drops():
    job = {"rules": [{"if": '$REF == "main"', "when": "never"}]}
    out = apply_rules(job, Context(ref="main"), {"REF": "main"})
    assert out.dropped


def test_rules_changes_match():
    job = {"rules": [{"changes": ["src/**/*.py"], "when": "on_success"}]}
    out = apply_rules(job, Context(changed_files=["src/app/main.py"]), {})
    assert not out.dropped
    out2 = apply_rules(job, Context(changed_files=["docs/readme.md"]), {})
    assert out2.dropped


def test_rules_extra_variables():
    job = {
        "rules": [
            {"if": '$REF == "main"', "variables": {"DEPLOY_TARGET": "prod"}},
        ],
    }
    out = apply_rules(job, Context(ref="main"), {"REF": "main"})
    assert out.extra_variables == {"DEPLOY_TARGET": "prod"}


def test_only_refs():
    job = {"only": ["main", "tags"]}
    out = apply_rules(job, Context(ref="main"), {})
    assert not out.dropped
    out2 = apply_rules(job, Context(ref="other"), {})
    assert out2.dropped


def test_except_refs():
    job = {"except": ["main"]}
    out = apply_rules(job, Context(ref="main"), {})
    assert out.dropped
    out2 = apply_rules(job, Context(ref="feature"), {})
    assert not out2.dropped


def test_no_rules_no_only():
    out = apply_rules({}, Context(), {})
    assert not out.dropped
    assert out.when is None
