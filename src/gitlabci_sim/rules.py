"""rules:/only:/except: evaluation.

`apply_rules(job_dict, ctx, env)` returns a `RuleOutcome` saying whether the job is dropped,
which `when` to use, and any `variables` / `allow_failure` injected by the matched rule.
"""
from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .variables import Context, expand


@dataclass
class RuleOutcome:
    dropped: bool = False
    when: str | None = None
    allow_failure: bool | None = None
    extra_variables: dict[str, str] | None = None
    matched_rule: dict | None = None


def apply_rules(job: dict[str, Any], ctx: Context, env: dict[str, str]) -> RuleOutcome:
    rules = job.get("rules")
    if rules is not None:
        return _eval_rules(rules, ctx, env)
    return _eval_only_except(job, ctx, env)


def _eval_rules(rules: list[Any], ctx: Context, env: dict[str, str]) -> RuleOutcome:
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        if not _rule_matches(rule, ctx, env):
            continue
        when = rule.get("when", "on_success")
        if when == "never":
            return RuleOutcome(dropped=True, matched_rule=rule)
        return RuleOutcome(
            when=when,
            allow_failure=rule.get("allow_failure"),
            extra_variables={str(k): str(v) for k, v in (rule.get("variables") or {}).items()},
            matched_rule=rule,
        )
    # No rule matched: job is dropped (matches GitLab default).
    return RuleOutcome(dropped=True)


def _rule_matches(rule: dict[str, Any], ctx: Context, env: dict[str, str]) -> bool:
    if "if" in rule:
        if not eval_if(str(rule["if"]), env):
            return False
    if "changes" in rule:
        patterns = rule["changes"]
        if isinstance(patterns, dict):
            patterns = patterns.get("paths", [])
        if not _changes_match(patterns or [], ctx.changed_files):
            return False
    if "exists" in rule:
        if not _exists_match(rule["exists"]):
            return False
    return True


def _eval_only_except(job: dict[str, Any], ctx: Context, env: dict[str, str]) -> RuleOutcome:
    only = job.get("only")
    except_ = job.get("except")
    if only is None and except_ is None:
        return RuleOutcome()

    def matches(spec: Any) -> bool:
        if isinstance(spec, list):
            return any(_ref_matches(str(s), ctx) for s in spec)
        if isinstance(spec, dict):
            refs = spec.get("refs")
            if refs and not any(_ref_matches(str(r), ctx) for r in refs):
                return False
            variables = spec.get("variables")
            if variables and not all(eval_if(str(v), env) for v in variables):
                return False
            return True
        return False

    if only is not None and not matches(only):
        return RuleOutcome(dropped=True)
    if except_ is not None and matches(except_):
        return RuleOutcome(dropped=True)
    return RuleOutcome()


# ---- if: expression evaluation -------------------------------------------------

# A small, deliberately limited evaluator: comparisons (==, !=, =~, !~), boolean
# &&/||, parens, string literals, variable refs. Good enough for ~95% of real configs.

_TOKEN_RE = re.compile(
    r"""
    \s*(?:
        (?P<lparen>\() |
        (?P<rparen>\)) |
        (?P<and>&&) |
        (?P<or>\|\|) |
        (?P<not>!(?![=~])) |
        (?P<eq>==) |
        (?P<ne>!=) |
        (?P<rmatch>=~) |
        (?P<rnotmatch>!~) |
        (?P<regex>/(?:\\.|[^/\\])*/[a-z]*) |
        (?P<dquoted>"(?:\\.|[^"\\])*") |
        (?P<squoted>'(?:\\.|[^'\\])*') |
        (?P<var>\$\{?[A-Za-z_][A-Za-z0-9_]*\}?) |
        (?P<word>[A-Za-z_][A-Za-z0-9_]*)
    )
    """,
    re.VERBOSE,
)


def eval_if(expr: str, env: dict[str, str]) -> bool:
    tokens = _tokenize(expr)
    parser = _Parser(tokens, env)
    result = parser.parse_or()
    if parser.pos != len(tokens):
        raise ValueError(f"unexpected trailing tokens in if-expression: {expr!r}")
    return _truthy(result)


def _tokenize(expr: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    pos = 0
    while pos < len(expr):
        m = _TOKEN_RE.match(expr, pos)
        if not m:
            raise ValueError(f"unexpected character at {pos} in {expr!r}")
        if m.end() == pos:
            raise ValueError(f"empty token at {pos} in {expr!r}")
        for name, value in m.groupdict().items():
            if value is not None:
                tokens.append((name, value))
                break
        pos = m.end()
    return tokens


class _Parser:
    def __init__(self, tokens: list[tuple[str, str]], env: dict[str, str]) -> None:
        self.tokens = tokens
        self.env = env
        self.pos = 0

    def peek(self) -> tuple[str, str] | None:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def eat(self, kind: str | None = None) -> tuple[str, str]:
        tok = self.peek()
        if tok is None:
            raise ValueError("unexpected end of expression")
        if kind and tok[0] != kind:
            raise ValueError(f"expected {kind}, got {tok}")
        self.pos += 1
        return tok

    def parse_or(self) -> Any:
        left = self.parse_and()
        while self.peek() and self.peek()[0] == "or":
            self.eat("or")
            right = self.parse_and()
            left = _truthy(left) or _truthy(right)
        return left

    def parse_and(self) -> Any:
        left = self.parse_not()
        while self.peek() and self.peek()[0] == "and":
            self.eat("and")
            right = self.parse_not()
            left = _truthy(left) and _truthy(right)
        return left

    def parse_not(self) -> Any:
        if self.peek() and self.peek()[0] == "not":
            self.eat("not")
            return not _truthy(self.parse_not())
        return self.parse_cmp()

    def parse_cmp(self) -> Any:
        left = self.parse_atom()
        tok = self.peek()
        if tok and tok[0] in {"eq", "ne", "rmatch", "rnotmatch"}:
            op = self.eat()[0]
            right = self.parse_atom()
            return _compare(op, left, right)
        return left

    def parse_atom(self) -> Any:
        tok = self.peek()
        if tok is None:
            raise ValueError("expected atom")
        kind, value = tok
        if kind == "lparen":
            self.eat("lparen")
            inner = self.parse_or()
            self.eat("rparen")
            return inner
        self.eat()
        if kind == "dquoted":
            return _interp(_unquote(value), self.env)
        if kind == "squoted":
            return _unquote(value)
        if kind == "regex":
            return _Regex(value)
        if kind == "var":
            name = value.strip("${}")
            return self.env.get(name, "")
        if kind == "word":
            # Bare word: treat as variable name (GitLab also accepts $VAR with $).
            return self.env.get(value, value)
        raise ValueError(f"unexpected token: {tok}")


class _Regex:
    __slots__ = ("pattern", "flags")

    def __init__(self, raw: str) -> None:
        # raw is /.../[flags]
        body, _, flags = raw[1:].rpartition("/")
        flag_bits = 0
        if "i" in flags:
            flag_bits |= re.IGNORECASE
        if "m" in flags:
            flag_bits |= re.MULTILINE
        self.pattern = re.compile(body, flag_bits)


def _compare(op: str, left: Any, right: Any) -> bool:
    if op == "eq":
        return str(left) == str(right)
    if op == "ne":
        return str(left) != str(right)
    if op in {"rmatch", "rnotmatch"}:
        if isinstance(right, _Regex):
            regex = right.pattern
        elif isinstance(left, _Regex):
            regex = left.pattern
            left, right = right, left  # normalise: subject on left
        else:
            regex = re.compile(str(right))
        matched = bool(regex.search(str(left)))
        return matched if op == "rmatch" else not matched
    raise ValueError(f"unknown comparison operator: {op}")


def _truthy(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if v is None:
        return False
    if isinstance(v, str):
        return v != ""
    return bool(v)


def _unquote(s: str) -> str:
    return s[1:-1].encode("utf-8").decode("unicode_escape")


def _interp(s: str, env: dict[str, str]) -> str:
    return expand(s, env)


# ---- helpers -------------------------------------------------------------------

def _ref_matches(spec: str, ctx: Context) -> bool:
    """Match an only/except ref entry against the current context.

    Supported: exact branch name; pseudo-refs `branches`, `tags`, `merge_requests`,
    `pushes`; `/regex/`.
    """
    if spec == "branches":
        return ctx.pipeline_source in {"push", "web", "schedule", "trigger", "api"}
    if spec == "tags":
        return ctx.pipeline_source == "tag"
    if spec in {"merge_requests", "merge_request"}:
        return ctx.pipeline_source == "merge_request_event"
    if spec == "pushes":
        return ctx.pipeline_source == "push"
    if spec.startswith("/") and spec.endswith("/") and len(spec) >= 2:
        pattern = re.compile(spec[1:-1])
        return bool(pattern.search(ctx.ref))
    return spec == ctx.ref


def _changes_match(patterns: list[str], changed: list[str]) -> bool:
    if not changed:
        # No changed-file context provided: be permissive.
        return True
    for p in patterns:
        for f in changed:
            if fnmatch.fnmatch(f, p):
                return True
    return False


def _exists_match(spec: Any) -> bool:
    patterns = spec if isinstance(spec, list) else [spec]
    for p in patterns:
        for _ in Path(".").glob(str(p)):
            return True
    return False
