"""Tests for the launch guard.

The bar is precision, not coverage: every test here either proves a rule fires on
the exact shape it targets, or proves it stays silent on the near-miss that would
make a PR comment untrustworthy.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from guard import scan_repo
from guard.demo import DEMO_KEY
from guard.render import (
    MARKER,
    BatchSummary,
    badge_svg,
    card_svg,
    comment_markdown,
    fix_prompt,
    thread_markdown,
)

# Distinct enough characters that the placeholder heuristic stays out of the way.
FAKE_KEY = "sk-proj-" + "aB3dE5fG7hJ9kL2mN4pQ6rS8tU0vW1xY3zA5bC7dE9fG1h"
FAKE_ANTHROPIC = "sk-ant-api03-" + "Zq4Rt7Yw2Ep9Ks6Ld3Fg8Hj5Mn1Bv0Cx"


def _tree(root: Path, files: dict[str, str]) -> Path:
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return root


def _rules(report) -> set[str]:
    return {finding.rule_id for finding in report.findings}


# ---------------------------------------------------------------------------
# LEAK
# ---------------------------------------------------------------------------


def test_clean_repo_is_grade_a(tmp_path):
    _tree(
        tmp_path,
        {
            "app/main.py": "import os\n\nKEY = os.environ['OPENAI_API_KEY']\nprint('hi')\n",
            "README.md": "# hello\n",
        },
    )
    report = scan_repo(tmp_path)
    assert report.findings == []
    assert report.grade == "A"
    assert report.files_scanned == 2


def test_placeholder_is_not_a_finding(tmp_path):
    _tree(tmp_path, {"app/config.py": 'OPENAI_KEY = "sk-your-key-here-xxxxxxxxxxxxxxxxxxxxxxxx"\n'})
    assert scan_repo(tmp_path).findings == []


def test_prose_key_used_in_ci_is_not_a_finding(tmp_path):
    # litellm's recorded-e2e workflow: a provider-shaped key that exists purely
    # so a recorded test can never reach a real API.
    _tree(
        tmp_path,
        {".github/workflows/e2e.yml": "env:\n  ANTHROPIC_API_KEY: sk-ant-replay-must-never-reach-a-provider\n"},
    )
    assert scan_repo(tmp_path).findings == []


def test_key_in_shipped_file_is_critical(tmp_path):
    _tree(tmp_path, {"public/config.js": f'const OPENAI_KEY = "{FAKE_KEY}";\n'})
    report = scan_repo(tmp_path)
    leak = [f for f in report.findings if f.rule_id == "LEAK-01"]
    assert len(leak) == 1
    assert leak[0].severity == "critical"
    assert leak[0].location == "public/config.js:1"


def test_key_in_server_code_is_high(tmp_path):
    _tree(tmp_path, {"app/client.py": f'API_KEY = "{FAKE_ANTHROPIC}"\n'})
    leak = [f for f in scan_repo(tmp_path).findings if f.rule_id == "LEAK-01"]
    assert leak and leak[0].severity == "high"


def test_secret_is_never_reproduced(tmp_path):
    _tree(tmp_path, {"public/config.js": f'const OPENAI_KEY = "{FAKE_KEY}";\n'})
    report = scan_repo(tmp_path)
    blob = json.dumps(report.to_dict())
    assert FAKE_KEY not in blob
    assert FAKE_KEY not in comment_markdown(report)
    assert "sk-proj" in blob  # the scheme is still named, for triage


def test_client_component_counts_as_shipped(tmp_path):
    _tree(
        tmp_path,
        {
            "app/page.tsx": f'"use client";\nconst key = "{FAKE_KEY}";\nexport default function P() {{ return null; }}\n'
        },
    )
    leak = [f for f in scan_repo(tmp_path).findings if f.rule_id == "LEAK-01"]
    assert leak and leak[0].severity == "critical"


def test_committed_dotenv_is_reported(tmp_path):
    _tree(tmp_path, {".env": "APP_NAME=demo\n"})
    assert "LEAK-02" in _rules(scan_repo(tmp_path))


def test_dotenv_example_is_ignored(tmp_path):
    _tree(tmp_path, {".env.example": "OPENAI_API_KEY=\n"})
    assert scan_repo(tmp_path).findings == []


def test_dotenv_with_a_real_key_reports_the_key_not_the_file(tmp_path):
    _tree(tmp_path, {".env": f"OPENAI_API_KEY={FAKE_KEY}\n"})
    report = scan_repo(tmp_path)
    assert "LEAK-01" in _rules(report)
    assert "LEAK-02" not in _rules(report)


def test_tests_directory_is_out_of_scope(tmp_path):
    _tree(tmp_path, {"tests/fixtures/keys.py": f'KEY = "{FAKE_KEY}"\n'})
    assert scan_repo(tmp_path).findings == []


# ---------------------------------------------------------------------------
# COST
# ---------------------------------------------------------------------------

_UNBOUNDED = """\
from openai import OpenAI

client = OpenAI()


def answer(prompt: str) -> str:
    while True:
        result = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
        )
        return result.choices[0].message.content
"""

# The `return` sits inside the loop, so the loop does exit: no COST-01.
_BOUNDED = """\
from openai import OpenAI

client = OpenAI(timeout=30, max_retries=2)


def answer(prompt: str) -> str:
    while True:
        result = client.chat.completions.create(
            model="gpt-4o",
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
        if result:
            break
    return "done"
"""


def test_unbounded_model_loop(tmp_path):
    _tree(tmp_path, {"app/agent.py": _UNBOUNDED})
    rules = _rules(scan_repo(tmp_path))
    assert "COST-02" in rules  # no max_tokens
    assert "COST-03" in rules  # client without timeout
    # `return` inside the loop means this one actually can exit.
    assert "COST-01" not in rules


def test_truly_unbounded_loop(tmp_path):
    source = """\
from openai import OpenAI

client = OpenAI()


def spin() -> None:
    while True:
        client.chat.completions.create(model="gpt-4o", max_tokens=64, messages=[])
"""
    _tree(tmp_path, {"app/spin.py": source})
    assert "COST-01" in _rules(scan_repo(tmp_path))


def test_capped_and_configured_call_is_quiet(tmp_path):
    _tree(tmp_path, {"app/agent.py": _BOUNDED})
    assert scan_repo(tmp_path).findings == []


def test_agent_executor_without_iteration_cap(tmp_path):
    source = """\
from langchain.agents import AgentExecutor

executor = AgentExecutor(agent=agent, tools=tools)
"""
    _tree(tmp_path, {"app/chain.py": source})
    assert "COST-04" in _rules(scan_repo(tmp_path))


def test_agent_executor_with_cap_is_quiet(tmp_path):
    source = """\
from langchain.agents import AgentExecutor

executor = AgentExecutor(agent=agent, tools=tools, max_iterations=10)
"""
    _tree(tmp_path, {"app/chain.py": source})
    assert "COST-04" not in _rules(scan_repo(tmp_path))


def test_crewai_max_iter_spelling_is_recognised(tmp_path):
    source = """\
from langchain.agents import AgentExecutor

executor = AgentExecutor(agent=agent, tools=tools, max_iter=15)
"""
    _tree(tmp_path, {"app/chain.py": source})
    assert "COST-04" not in _rules(scan_repo(tmp_path))


def test_non_sdk_completion_method_is_not_a_model_call(tmp_path):
    source = """\
class Thing:
    def completion(self):
        return 1


thing = Thing()
thing.completion()
"""
    _tree(tmp_path, {"app/thing.py": source})
    assert scan_repo(tmp_path).findings == []


# Regressions found by scanning real repositories (litellm, 2026-11-13).

def test_polling_loop_in_a_file_that_imports_openai_is_not_a_model_loop(tmp_path):
    source = """\
import asyncio

from openai import OpenAI

client = OpenAI()


async def periodic_flush(self) -> None:
    while True:
        await asyncio.sleep(5)
        await self.flush_queue()
"""
    _tree(tmp_path, {"app/logger.py": source})
    assert "COST-01" not in _rules(scan_repo(tmp_path))


def test_nested_function_return_does_not_exit_the_outer_loop(tmp_path):
    source = """\
from openai import OpenAI

client = OpenAI()


def spin() -> None:
    while True:
        def helper():
            return 1
        client.chat.completions.create(model="gpt-4o", max_tokens=8, messages=[])
"""
    _tree(tmp_path, {"app/spin.py": source})
    assert "COST-01" in _rules(scan_repo(tmp_path))


def test_test_files_are_out_of_scope(tmp_path):
    _tree(
        tmp_path,
        {
            "src/CreateThing.test.tsx": f'const k = "{FAKE_KEY}";\n',
            "app/test_client.py": f'KEY = "{FAKE_KEY}"\n',
            "app/conftest.py": f'KEY = "{FAKE_KEY}"\n',
        },
    )
    assert scan_repo(tmp_path).findings == []


# ---------------------------------------------------------------------------
# PERM
# ---------------------------------------------------------------------------


def test_dangerous_skip_permissions(tmp_path):
    _tree(tmp_path, {".claude/settings.json": json.dumps({"dangerouslySkipPermissions": True})})
    perm = [f for f in scan_repo(tmp_path).findings if f.rule_id == "PERM-01"]
    assert perm and perm[0].severity == "critical"


def test_skip_permissions_flag_in_scripts(tmp_path):
    _tree(tmp_path, {"scripts/run.sh": "claude -p 'fix tests' --dangerously-skip-permissions\n"})
    assert "PERM-01" in _rules(scan_repo(tmp_path))


def test_skip_permissions_mentioned_in_docs_is_not_a_finding(tmp_path):
    _tree(
        tmp_path,
        {
            "README.md": "Never run: claude --dangerously-skip-permissions\n",
            "app/flags.py": 'FLAG = "--dangerously-skip-permissions"\n',
        },
    )
    assert "PERM-01" not in _rules(scan_repo(tmp_path))


def test_wildcard_tool_allowlist(tmp_path):
    config = {"mcpServers": {"files": {"command": "npx", "allowedTools": ["*"]}}}
    _tree(tmp_path, {"mcp.json": json.dumps(config)})
    perm = [f for f in scan_repo(tmp_path).findings if f.rule_id == "PERM-02"]
    assert perm and "files" in perm[0].title


def test_scoped_tool_allowlist_is_quiet(tmp_path):
    config = {"mcpServers": {"files": {"command": "npx", "allowedTools": ["read_file"]}}}
    _tree(tmp_path, {"mcp.json": json.dumps(config)})
    assert scan_repo(tmp_path).findings == []


def test_fail_open_policy(tmp_path):
    policy = 'version: 1\nrules:\n  - id: allow-all\n    action: "*"\n    effect: allow\n'
    _tree(tmp_path, {"policy.yaml": policy})
    perm = [f for f in scan_repo(tmp_path).findings if f.rule_id == "PERM-03"]
    assert perm and perm[0].severity == "critical"


def test_fail_closed_policy_is_quiet(tmp_path):
    policy = (
        'version: 1\nrules:\n  - id: allow-search\n    action: kb.search\n    effect: allow\n'
        '  - id: deny-everything-else\n    action: "*"\n    effect: deny\n'
    )
    _tree(tmp_path, {"policy.yaml": policy})
    assert scan_repo(tmp_path).findings == []


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _dirty_report(tmp_path):
    _tree(
        tmp_path,
        {
            "public/config.js": f'const OPENAI_KEY = "{FAKE_KEY}";\n',
            "app/spin.py": "from openai import OpenAI\nwhile True:\n    OpenAI().chat.completions.create(model='m')\n",
            ".claude/settings.json": json.dumps({"dangerouslySkipPermissions": True}),
        },
    )
    return scan_repo(tmp_path)


def test_comment_is_marked_and_compact(tmp_path):
    report = _dirty_report(tmp_path)
    body = comment_markdown(report, repo_slug="acme/rocket")
    assert body.startswith(MARKER)
    assert "acme/rocket" in body
    assert "Fix before merge" in body
    assert "One prompt that fixes all of it" in body
    assert len(body.splitlines()) < 60


def test_fix_prompt_names_locations(tmp_path):
    report = _dirty_report(tmp_path)
    prompt = fix_prompt(report)
    assert "public/config.js:1" in prompt
    assert "rotate" in prompt.lower()


def test_badge_is_valid_svg(tmp_path):
    report = _dirty_report(tmp_path)
    svg = badge_svg(report)
    ET.fromstring(svg)
    assert report.grade in svg


def test_card_and_thread_render():
    summary = BatchSummary(
        repos=[
            {"slug": "acme/rocket", "grade": "D", "risk_score": 40, "blockers": 3, "advisory": 1, "files": 120, "ms": 800, "by_rule": {"LEAK-01": 2}},
            {"slug": "acme/anvil", "grade": "A", "risk_score": 0, "blockers": 0, "advisory": 0, "files": 80, "ms": 400, "by_rule": {}},
        ]
    )
    card = card_svg(summary)
    ET.fromstring(card)
    assert "2 agent repos, 200 files" in card
    thread = thread_markdown(summary)
    assert "1/7" in thread and "2/7" in thread
    assert summary.files == 200
    assert [r["slug"] for r in summary.dirty] == ["acme/rocket"]


def test_report_json_shape(tmp_path):
    report = _dirty_report(tmp_path)
    payload = report.to_dict()
    assert payload["format"] == "agentproof-guard-v1"
    assert payload["grade"] == report.grade
    assert payload["summary"]["total"] == len(report.findings)
    assert all("location" in f for f in payload["findings"])


# ---------------------------------------------------------------------------
# Demo tree (the artifact people actually look at)
# ---------------------------------------------------------------------------


def test_demo_tree_hits_all_three_checks(tmp_path):
    from guard.demo import build_tree

    report = scan_repo(build_tree(tmp_path / "demo-app"))
    rules = _rules(report)
    assert {"LEAK-01", "PERM-01", "PERM-02", "COST-01"} <= rules
    assert report.grade == "F"
    body = comment_markdown(report, repo_slug="demo/vibe-coded-app")
    assert "Fix before merge" in body
    assert DEMO_KEY not in body
