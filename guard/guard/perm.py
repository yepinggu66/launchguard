"""PERM checks: configurations that hand an agent more authority than it needs.

The scan already covers MCP servers in the agentproof engine (MCP-01..13). This
module deliberately covers a different surface — the *permission switches* that
disable the harness altogether — because those are the ones that turn a small
bug into a full-machine action with nobody watching.
"""

from __future__ import annotations

import json
import re

from .model import CRITICAL, HIGH, MEDIUM, Finding

_CREDENTIAL_KEY_RE = re.compile(
    r"(?:api[_-]?key|apikey|secret|token|password|passwd|credential|private[_-]?key)",
    re.IGNORECASE,
)
_PLACEHOLDER_HINTS = ("xxxx", "your", "example", "placeholder", "changeme", "dummy", "fake", "redacted", "<", "${", "$(")

_JSON_SUFFIXES = (".json", ".jsonc")
_MCP_CONFIG_NAMES = (
    "mcp.json",
    "claude_desktop_config.json",
    "mcp_config.json",
    ".mcp.json",
    "settings.json",
    "settings.local.json",
    "permissions.json",
)
_SERVERS_KEYS = ("mcpServers", "servers", "mcp_servers")


def check_text(rel: str, text: str) -> list[Finding]:
    findings: list[Finding] = []
    name = rel.rsplit("/", 1)[-1].lower()

    if name in _MCP_CONFIG_NAMES or name.endswith(_JSON_SUFFIXES):
        findings.extend(_check_json_permissions(rel, text))

    findings.extend(_check_skip_flags(rel, text))

    if name in ("policy.yaml", "policy.yml", "agentproof.policy.yaml", "agentproof.yaml"):
        findings.extend(_check_fail_open_policy(rel, text))

    return findings


# ---------------------------------------------------------------------------
# JSON: MCP servers, Claude Code settings, permission allowlists
# ---------------------------------------------------------------------------


def _load_json(text: str) -> object | None:
    try:
        return json.loads(text)
    except (ValueError, RecursionError):
        pass
    stripped = re.sub(r"^\s*//.*$", "", text, flags=re.MULTILINE)
    try:
        return json.loads(stripped)
    except (ValueError, RecursionError):
        return None


def _line_of(text: str, needle: str) -> int:
    idx = text.find(needle)
    if idx < 0:
        return 1
    return text.count("\n", 0, idx) + 1


def _is_placeholder(value: object) -> bool:
    if not isinstance(value, str):
        return True
    low = value.lower()
    if len(value) < 8 or len(set(low)) <= 3:
        return True
    return any(hint in low for hint in _PLACEHOLDER_HINTS)


def _check_json_permissions(rel: str, text: str) -> list[Finding]:
    data = _load_json(text)
    if data is None:
        return _regex_fallback(rel, text)

    findings: list[Finding] = []

    if _has_truthy(data, "dangerouslySkipPermissions"):
        line = _line_of(text, "dangerouslySkipPermissions")
        findings.append(
            Finding(
                check="perm",
                rule_id="PERM-01",
                severity=CRITICAL,
                title="agent runs with permission prompts disabled",
                location=f"{rel}:{line}",
                detail=(
                    "`dangerouslySkipPermissions` is enabled, so the agent executes tool "
                    "calls without asking. Every over-broad tool in this config becomes a "
                    "silent action rather than a prompt."
                ),
                fix="Remove the switch; scope the tools instead (`allowedTools` per server, deny-by-default).",
                evidence="dangerouslySkipPermissions: true",
            )
        )

    for server_name, spec, key_path in _iter_servers(data):
        if isinstance(spec, dict):
            if _wildcard(spec.get("allowedTools")) or _wildcard(spec.get("tools")):
                line = _line_of(text, '"allowedTools"') if "allowedTools" in text else _line_of(text, '"tools"')
                findings.append(
                    Finding(
                        check="perm",
                        rule_id="PERM-02",
                        severity=HIGH,
                        title=f"MCP server `{server_name}` allows every tool",
                        location=f"{rel}:{line}",
                        detail=(
                            "A wildcard tool allowlist means the agent can call any tool the "
                            "server exposes, including ones added in a future server release."
                        ),
                        fix=f"Replace the wildcard with the specific tools the agent needs for `{server_name}`.",
                        evidence=f'"{server_name}": {{"allowedTools": ["*"]}}',
                    )
                )
            if spec.get("autoApprove") is True:
                line = _line_of(text, "autoApprove")
                findings.append(
                    Finding(
                        check="perm",
                        rule_id="PERM-02",
                        severity=HIGH,
                        title=f"MCP server `{server_name}` auto-approves tool calls",
                        location=f"{rel}:{line}",
                        detail="`autoApprove: true` removes the human confirmation step for this server.",
                        fix="Drop autoApprove and approve per-tool, or gate it behind a signed policy.",
                        evidence=f'"{server_name}": {{"autoApprove": true}}',
                    )
                )
            env = spec.get("env")
            if isinstance(env, dict):
                for env_key, env_value in env.items():
                    if not _CREDENTIAL_KEY_RE.search(str(env_key)):
                        continue
                    if _is_placeholder(env_value):
                        continue
                    line = _line_of(text, str(env_key))
                    findings.append(
                        Finding(
                            check="perm",
                            rule_id="PERM-04",
                            severity=MEDIUM,
                            title=f"credential handed to MCP server `{server_name}` via env",
                            location=f"{rel}:{line}",
                            detail=(
                                f"`{env_key}` is passed to a third-party server process as a "
                                "plaintext environment value. The server can read it, log it, "
                                "or forward it."
                            ),
                            fix="Pass a scoped, short-lived token instead of a long-lived key; rotate it per session.",
                            evidence=f'"{env_key}": "<redacted>"',
                        )
                    )

    perms = data.get("permissions") if isinstance(data, dict) else None
    if isinstance(perms, dict) and _wildcard(perms.get("allow")):
        line = _line_of(text, '"permissions"')
        findings.append(
            Finding(
                check="perm",
                rule_id="PERM-02",
                severity=HIGH,
                title="permission allowlist is a wildcard",
                location=f"{rel}:{line}",
                detail="`permissions.allow: [\"*\"]` grants every tool in the workspace.",
                fix="Enumerate the tools the agent actually needs; deny everything else.",
                evidence='permissions: {allow: ["*"]}',
            )
        )

    return findings


def _iter_servers(data: object):
    if not isinstance(data, dict):
        return
    for key in _SERVERS_KEYS:
        servers = data.get(key)
        if isinstance(servers, dict):
            for name, spec in servers.items():
                yield str(name), spec, key


def _has_truthy(data: object, key: str) -> bool:
    if isinstance(data, dict):
        for candidate, value in data.items():
            if candidate == key and value is True:
                return True
            if _has_truthy(value, key):
                return True
    elif isinstance(data, list):
        return any(_has_truthy(item, key) for item in data)
    return False


def _wildcard(value: object) -> bool:
    if value == "*":
        return True
    if isinstance(value, list):
        return any(item == "*" for item in value)
    return False


def _regex_fallback(rel: str, text: str) -> list[Finding]:
    findings: list[Finding] = []
    if re.search(r'"dangerouslySkipPermissions"\s*:\s*true', text):
        findings.append(
            Finding(
                check="perm",
                rule_id="PERM-01",
                severity=CRITICAL,
                title="agent runs with permission prompts disabled",
                location=f"{rel}:{_line_of(text, 'dangerouslySkipPermissions')}",
                detail="`dangerouslySkipPermissions: true` disables the human confirmation step.",
                fix="Remove the switch and scope tools per server instead.",
                evidence="dangerouslySkipPermissions: true",
            )
        )
    if re.search(r'"(?:allowedTools|tools)"\s*:\s*\[\s*"\*"\s*\]', text):
        findings.append(
            Finding(
                check="perm",
                rule_id="PERM-02",
                severity=HIGH,
                title="MCP tool allowlist is a wildcard",
                location=f"{rel}:{_line_of(text, 'allowedTools')}",
                detail="A wildcard allowlist lets the agent call every tool the server exposes.",
                fix="Replace the wildcard with the exact tools required.",
                evidence='allowedTools: ["*"]',
            )
        )
    return findings


# ---------------------------------------------------------------------------
# Everything else: CLI bypass flags and fail-open policies
# ---------------------------------------------------------------------------


_DOC_SUFFIXES = (".md", ".mdx", ".txt", ".rst", ".adoc")

# The flag only matters where something is actually *launched*. Without this
# gate the check fires on its own documentation, on this file's own constant,
# and on every blog post that mentions the flag.
_INVOCATION_RE = re.compile(
    r"(claude|npx|node\b|python3?\b|docker|bash|sh -c|subprocess|Popen|"
    r"check_output|os\.system|\.run\(|exec\(|spawn|entrypoint|command)",
    re.IGNORECASE,
)


def _check_skip_flags(rel: str, text: str) -> list[Finding]:
    if rel.lower().endswith(_DOC_SUFFIXES):
        return []
    if "--dangerously-skip-permissions" not in text:
        return []
    for lineno, line in enumerate(text.splitlines(), 1):
        if "--dangerously-skip-permissions" not in line:
            continue
        if not _INVOCATION_RE.search(line):
            continue
        return [
            Finding(
                check="perm",
                rule_id="PERM-01",
                severity=CRITICAL,
                title="agent invoked with --dangerously-skip-permissions",
                location=f"{rel}:{lineno}",
                detail=(
                    "A script or task runs the agent with approvals disabled. Anyone who can "
                    "edit a prompt can now trigger a tool call with no human in the loop."
                ),
                fix="Remove the flag from scripts and CI; if it is needed for an unattended job, "
                "scope that job to a dedicated least-privilege tool set.",
                evidence="--dangerously-skip-permissions",
            )
        ]
    return []


def _check_fail_open_policy(rel: str, text: str) -> list[Finding]:
    findings: list[Finding] = []
    for start_line, block in _blocks(text):
        joined = "\n".join(block)
        action_wildcard = re.search(r"action:\s*[\"']?\*[\"']?\s*$", joined, re.MULTILINE)
        effect_allow = re.search(r"effect:\s*[\"']?allow[\"']?", joined)
        if action_wildcard and effect_allow:
            findings.append(
                Finding(
                    check="perm",
                    rule_id="PERM-03",
                    severity=CRITICAL,
                    title="policy allows `*` — fail-open",
                    location=f"{rel}:{start_line}",
                    detail=(
                        "The policy grants `action: \"*\"` with `effect: allow`, so any tool "
                        "call that is not explicitly denied is approved. A policy that "
                        "allows by default is a log, not a gate."
                    ),
                    fix='Flip the catch-all to `action: "*", effect: deny` and enumerate the allowed actions.',
                    evidence='action: "*" ... effect: allow',
                )
            )
    return findings


def _blocks(text: str) -> list[tuple[int, list[str]]]:
    """Split a YAML rule list into ``(start_line, lines)`` blocks."""
    blocks: list[tuple[int, list[str]]] = []
    current: list[str] = []
    start = 0
    for idx, line in enumerate(text.splitlines(), 1):
        if re.match(r"\s*-\s+\w", line):
            if current:
                blocks.append((start, current))
            current = [line]
            start = idx
        elif current:
            current.append(line)
    if current:
        blocks.append((start, current))
    return blocks
