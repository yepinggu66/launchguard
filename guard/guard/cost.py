"""COST checks: the loop that keeps calling a model until the card declines.

No CVE will ever describe this bug. A missing ``max_tokens`` on a call inside a
``while True`` is three lines of perfectly valid Python and a four-figure bill
by morning. That asymmetry — trivial code, unbounded spend — is the whole
reason this check is worth a PR comment.
"""

from __future__ import annotations

import ast
import re

from .model import HIGH, LOW, MEDIUM, Finding

_CALL_RE = re.compile(
    r"(?:^|\.)(?:"
    r"chat\.completions\.(?:create|stream)"
    r"|completions\.create"
    r"|responses\.create"
    r"|messages\.(?:create|stream)"
    r"|generate_content(?:_async)?"
    r"|(?:a)?completion"
    r"|invoke_model"
    r")$"
)

_SDK_HINTS = (
    "openai",
    "anthropic",
    "litellm",
    "google.generativeai",
    "google.genai",
    "groq",
    "ollama",
    "mistralai",
    "cohere",
    "vertexai",
    "together",
    "replicate",
    "dashscope",
    "zhipuai",
    "qianfan",
    "bedrock",
)

_CAP_KWARGS = frozenset(
    {
        "max_tokens",
        "max_completion_tokens",
        "max_output_tokens",
        "max_new_tokens",
        "maxOutputTokens",
        "maxTokens",
    }
)

_CLIENT_CTORS = frozenset(
    {
        "OpenAI",
        "AsyncOpenAI",
        "AzureOpenAI",
        "AsyncAzureOpenAI",
        "Anthropic",
        "AsyncAnthropic",
        "AnthropicBedrock",
        "Groq",
        "AsyncGroq",
        "Mistral",
        "Cohere",
        "Client",
        "GenerativeModel",
    }
)

# Only builders whose own API accepts an iteration ceiling. `create_react_agent`
# and openai-agents' `Agent` take recursion limits elsewhere, so flagging them
# here would be a false claim.
_AGENT_BUILDERS = frozenset({"AgentExecutor", "initialize_agent"})

_MAX_ITER_KWARGS = ("max_iterations", "max_iter", "max_turns", "max_steps", "max_loops")
_UNBOUNDED_ITER = 100

# Agent frameworks that wrap model calls: worth parsing even when the file never
# mentions a provider SDK directly.
_FRAMEWORK_HINTS = (
    "langchain",
    "langgraph",
    "crewai",
    "autogen",
    "llama_index",
    "llamaindex",
    "pydantic_ai",
    "smolagents",
    "dspy",
)

# Cheap pre-filter: no model SDK mentioned anywhere -> no parse at all.
COST_TEXT_HINTS = tuple(dict.fromkeys(_SDK_HINTS + _FRAMEWORK_HINTS))


def check_python(rel: str, text: str) -> list[Finding]:
    low = text.lower()
    if not any(hint in low for hint in COST_TEXT_HINTS):
        return []
    try:
        tree = ast.parse(text, filename=rel)
    except (SyntaxError, ValueError):
        return []
    return _Walker(rel, text).run(tree)


def _dotted(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _dotted(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    if isinstance(node, ast.Call):
        return _dotted(node.func)
    return ""


_INTERNAL_ROOTS = frozenset({"self", "cls", "super"})


def _root_name(dotted: str) -> str:
    return dotted.split(".", 1)[0].split("(", 1)[0]


class _Walker:
    def __init__(self, rel: str, text: str) -> None:
        self.rel = rel
        self.text = text
        self.findings: list[Finding] = []
        self._ctor_reported = False
        self._cap_reported = 0
        self._defined: set[str] = set()

    def run(self, tree: ast.Module) -> list[Finding]:
        # Names of functions this module defines. A call to `<x>.completion(...)`
        # in a module that *implements* `completion` is delegation inside an
        # adapter, not a caller spending money without a budget.
        self._defined = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.While):
                self._check_loop(node)
            elif isinstance(node, ast.Call):
                self._check_call(node)
        return self.findings

    # -------------------------------------------------------------- loops ---
    def _check_loop(self, node: ast.While) -> None:
        if not _is_literal_true(node.test):
            return
        # `_CALL_RE` is required here as well as `_looks_like_sdk`, otherwise any
        # `self.flush_queue()` inside a polling loop counts as a model call in
        # every file that happens to import openai.
        calls = [
            n
            for n in _iter_loop_scope(node)
            if isinstance(n, ast.Call)
            and _CALL_RE.search(_dotted(n.func))
            and self._is_llm_call(n)
        ]
        if not calls:
            return
        if _can_exit(node):
            return
        line = node.lineno
        self.findings.append(
            Finding(
                check="cost",
                rule_id="COST-01",
                severity=HIGH,
                title="model call inside a `while True` with no exit",
                location=f"{self.rel}:{line}",
                detail=(
                    f"`{_dotted(calls[0].func)}(...)` runs inside a loop that has no "
                    "break, return or raise. If the model keeps answering — or keeps "
                    "failing — the loop keeps paying."
                ),
                fix=(
                    "Bound the loop: a max iteration count or a token/price budget that "
                    "the loop checks, plus a `break` on the terminal condition."
                ),
                evidence=_trim(self._source_line(line)),
            )
        )

    # -------------------------------------------------------------- calls ---
    def _check_call(self, node: ast.Call) -> None:
        name = _dotted(node.func)
        if not name:
            return

        if _CALL_RE.search(name) and self._is_llm_call(node):
            self._check_output_cap(node, name)
            return

        leaf = name.rsplit(".", 1)[-1]
        if leaf in _CLIENT_CTORS and not self._ctor_reported and self._looks_like_sdk(name):
            self._check_client(node, name)
            return

        if leaf in _AGENT_BUILDERS:
            self._check_agent_budget(node, name)

    def _is_llm_call(self, node: ast.Call) -> bool:
        name = _dotted(node.func)
        if not name or "(" in name:
            return False
        return self._looks_like_sdk(name)

    def _looks_like_sdk(self, name: str) -> bool:
        """A method called `completion`/`Client` is only a model call if this file
        actually imports a model SDK — otherwise it is just an ordinary method."""
        if any(name.startswith(hint) or f"{hint}." in name for hint in _SDK_HINTS):
            return True
        low = self.text.lower()
        return any(f"import {hint}" in low or f"from {hint}" in low for hint in _SDK_HINTS)

    def _check_output_cap(self, node: ast.Call, name: str) -> None:
        # `self.completion(...)` / `super().completion(...)` is a library
        # implementing the call, not a caller choosing its budget. Flagging
        # those made the check fire 39 times inside litellm's provider adapters.
        if _root_name(name) in _INTERNAL_ROOTS:
            return
        if name.rsplit(".", 1)[-1] in self._defined:
            return
        if any(kw.arg is None for kw in node.keywords):
            return  # **kwargs: unknowable, stay quiet
        if any(kw.arg in _CAP_KWARGS for kw in node.keywords):
            return
        if _dict_has_cap(node):
            return
        if self._cap_reported >= 6:
            return
        self._cap_reported += 1
        line = getattr(node.func, "lineno", node.lineno)
        self.findings.append(
            Finding(
                check="cost",
                rule_id="COST-02",
                severity=MEDIUM,
                title="model call with no output-token cap",
                location=f"{self.rel}:{line}",
                detail=(
                    f"`{name}(...)` sets no max_tokens / max_completion_tokens / "
                    "max_output_tokens, so a prompt that derails in production is "
                    "billed for the model's full output window on every call."
                ),
                fix="Pass an explicit output cap and include it in the prompt contract.",
                evidence=_trim(self._source_line(line)),
            )
        )

    def _check_client(self, node: ast.Call, name: str) -> None:
        self._ctor_reported = True
        kwargs = {kw.arg for kw in node.keywords if kw.arg}
        if "timeout" in kwargs or "max_retries" in kwargs:
            return
        line = getattr(node.func, "lineno", node.lineno)
        self.findings.append(
            Finding(
                check="cost",
                rule_id="COST-03",
                severity=LOW,
                title="model client created without timeout or retry cap",
                location=f"{self.rel}:{line}",
                detail=(
                    f"`{name}()` relies on SDK defaults for timeout and retries. A slow "
                    "upstream then holds the request (and the money) for the default window."
                ),
                fix="Construct the client with an explicit `timeout=` and `max_retries=`.",
                evidence=_trim(self._source_line(line)),
            )
        )

    def _check_agent_budget(self, node: ast.Call, name: str) -> None:
        if node.keywords and any(kw.arg is None for kw in node.keywords):
            return
        for kw in node.keywords:
            if kw.arg in _MAX_ITER_KWARGS:
                value = kw.value
                if isinstance(value, ast.Constant) and isinstance(value.value, int):
                    if value.value < _UNBOUNDED_ITER:
                        return
                    break
                return
        line = getattr(node.func, "lineno", node.lineno)
        self.findings.append(
            Finding(
                check="cost",
                rule_id="COST-04",
                severity=HIGH,
                title="agent executor with no iteration ceiling",
                location=f"{self.rel}:{line}",
                detail=(
                    f"`{name}(...)` sets no max_iterations / max_turns, so a planner "
                    "that stops converging re-plans until something else stops it."
                ),
                fix="Pass `max_iterations` (or the framework's equivalent) and handle the ceiling explicitly.",
                evidence=_trim(self._source_line(line)),
            )
        )

    # ------------------------------------------------------------- helpers ---
    def _source_line(self, lineno: int) -> str:
        lines = self.text.splitlines()
        if 1 <= lineno <= len(lines):
            return lines[lineno - 1]
        return ""


def _is_literal_true(node: ast.expr) -> bool:
    if isinstance(node, ast.Constant):
        return node.value is True or node.value == 1
    return False


def _iter_loop_scope(node: ast.AST):
    """Walk the loop body without descending into nested functions or classes.

    A `return` inside a `def` that happens to be defined in the loop body does
    not exit the loop, and a model call inside that def does not run once per
    iteration. Both mistakes were visible on real repositories.
    """
    stack = [node]
    while stack:
        current = stack.pop()
        for child in ast.iter_child_nodes(current):
            if isinstance(
                child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)
            ):
                continue
            yield child
            stack.append(child)


def _can_exit(node: ast.While) -> bool:
    for sub in _iter_loop_scope(node):
        if isinstance(sub, (ast.Break, ast.Return, ast.Raise)):
            return True
    return False


def _dict_has_cap(node: ast.Call) -> bool:
    for sub in ast.walk(node):
        if isinstance(sub, ast.Dict):
            for key in sub.keys:
                if isinstance(key, ast.Constant) and key.value in _CAP_KWARGS:
                    return True
    return False


def _trim(value: str, limit: int = 180) -> str:
    value = " ".join(value.split())
    return value if len(value) <= limit else value[: limit - 1] + "\u2026"
