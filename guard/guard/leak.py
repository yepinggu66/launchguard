"""LEAK checks: credentials that end up in a git history or in a browser bundle.

Why this check exists at all: in 2026 the expensive incident is no longer only
"a vulnerability shipped". It is "a working API key shipped" — the key is
billable the moment it is public, and deleting the commit does not un-spend the
money. So this check is about *billable material reaching a place it can be
read*, not about CVEs.
"""

from __future__ import annotations

import re

from .model import CRITICAL, HIGH, LOW, MEDIUM, Finding

# ---------------------------------------------------------------------------
# Byte hints. scan.py checks these before paying for a regex pass.
# ---------------------------------------------------------------------------
LEAK_BYTE_HINTS = (
    b"sk-",
    b"AIza",
    b"AKIA",
    b"ghp_",
    b"gho_",
    b"github_pat_",
    b"xox",
    b"rk_live",
    b"sk_live",
    b"SG.",
    b"npm_",
    b"hf_",
    b"gsk_",
    b"pplx-",
    b"r8_",
    b"fc-",
    b"-----BEGIN",
    b"api_key=",
    b"apikey=",
    b"access_token=",
)

# Ordered most-specific first; the first hit on a line wins.
_SECRETS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("openai-project-key", re.compile(r"\bsk-proj-[A-Za-z0-9_-]{40,}")),
    ("anthropic-key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{24,}")),
    ("openrouter-key", re.compile(r"\bsk-or-v1-[A-Za-z0-9]{40,}")),
    ("openai-key", re.compile(r"\bsk-[A-Za-z0-9]{40,}")),
    ("google-api-key", re.compile(r"\bAIza[0-9A-Za-z_-]{30,}")),
    ("aws-access-key-id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github-pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{30,}")),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}")),
    ("slack-token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{20,}")),
    ("stripe-live-key", re.compile(r"\b[rs]k_live_[A-Za-z0-9]{20,}")),
    ("sendgrid-key", re.compile(r"\bSG\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}")),
    ("npm-token", re.compile(r"\bnpm_[A-Za-z0-9]{36}\b")),
    ("huggingface-token", re.compile(r"\bhf_[A-Za-z0-9]{30,}")),
    ("groq-key", re.compile(r"\bgsk_[A-Za-z0-9]{40,}")),
    ("perplexity-key", re.compile(r"\bpplx-[A-Za-z0-9]{40,}")),
    ("replicate-token", re.compile(r"\br8_[A-Za-z0-9]{30,}")),
    ("firecrawl-key", re.compile(r"\bfc-[A-Za-z0-9]{30,}")),
)

_QUERY_SECRET_RE = re.compile(
    r"[?&](?:api[_-]?key|apikey|access[_-]?token|auth[_-]?token|client[_-]?secret)"
    r"=([A-Za-z0-9\-_.]{16,})"
)

_PLACEHOLDER_HINTS = (
    "xxxx",
    "your",
    "example",
    "placeholder",
    "change_me",
    "changeme",
    "dummy",
    "fake",
    "redacted",
    "insert",
    "replace",
    "abcdefg",
    "1234567890",
    "not_a_real",
    "sample",
)

# Committed dotenv files are a finding on their own; these are the safe variants.
_ENV_ALLOWED = frozenset(
    {".env.example", ".env.sample", ".env.template", ".env.dist", ".env.test", ".env.ci"}
)

# Directories whose contents are shipped to the browser verbatim.
_SERVED_DIRS = frozenset({"public", "static", "www", "assets", "out", "dist", "build", "cdn"})
# File types that are *always* readable by whoever loads the page.
_CLIENT_SUFFIXES = frozenset({".html", ".htm", ".jsx", ".tsx", ".vue", ".svelte", ".astro"})


def check_text(rel: str, text: str) -> list[Finding]:
    findings = _hardcoded_secrets(rel, text)
    findings.extend(_committed_dotenv(rel, findings))
    findings.extend(_secret_in_query(rel, text))
    return findings


# ---------------------------------------------------------------------------


def _is_placeholder(token: str) -> bool:
    low = token.lower()
    if len(set(low)) <= 3:
        return True
    if _is_prose_like(token):
        return True
    return any(hint in low for hint in _PLACEHOLDER_HINTS)


def _is_prose_like(token: str) -> bool:
    """`sk-ant-replay-must-never-reach-a-provider` is a sentence, not a key.

    Seen in the wild: a CI workflow that sets a deliberately unusable provider
    key so recorded tests can never reach a real API. Flagging it teaches the
    reader to ignore the bot.
    """
    body = token
    for prefix in ("sk-proj-", "sk-ant-", "sk-or-v1-", "sk-", "gsk_", "ghp_", "github_pat_"):
        if body.startswith(prefix):
            body = body[len(prefix):]
            break
    parts = [part for part in re.split(r"[-_]", body) if part]
    if len(parts) < 3:
        return False
    words = [part for part in parts if part.isalpha() and len(part) >= 3]
    return len(words) >= 3 and len(words) / len(parts) >= 0.6


def _is_shipped(rel: str, text: str) -> bool:
    parts = rel.lower().split("/")
    if any(part in _SERVED_DIRS for part in parts[:-1]):
        return True
    suffix = "." + rel.lower().rsplit(".", 1)[-1] if "." in rel else ""
    if suffix in _CLIENT_SUFFIXES:
        return True
    head = text.lstrip()[:220]
    return '"use client"' in head or "'use client'" in head


def _redact(label: str, token: str) -> str:
    head = token[: min(7, len(token))]
    return f"{label}:{head}\u2026 ({len(token)} chars)"


def _trim(value: str, limit: int = 180) -> str:
    value = " ".join(value.split())
    return value if len(value) <= limit else value[: limit - 1] + "\u2026"


def _hardcoded_secrets(rel: str, text: str) -> list[Finding]:
    shipped = _is_shipped(rel, text)
    severity = CRITICAL if shipped else HIGH
    where = "a file that ships to the browser" if shipped else "source code"

    findings: list[Finding] = []
    seen: set[tuple[str, int]] = set()

    for lineno, line in enumerate(text.splitlines(), 1):
        if len(line) > 4000:  # minified bundle: the key is unreadable anyway
            continue
        best: tuple[int, str, str] | None = None
        for label, pattern in _SECRETS:
            match = pattern.search(line)
            if not match:
                continue
            token = match.group(0)
            if _is_placeholder(token):
                continue
            if best is None or match.start() < best[0] or (
                match.start() == best[0] and len(token) > len(best[2])
            ):
                best = (match.start(), label, token)

        if best is None:
            continue
        _, label, token = best
        if (label, lineno) in seen:
            continue
        seen.add((label, lineno))

        redacted = _redact(label, token)
        evidence = _trim(line.replace(token, redacted))
        findings.append(
            Finding(
                check="leak",
                rule_id="LEAK-01",
                severity=severity,
                title=f"{label} hardcoded in {where}",
                location=f"{rel}:{lineno}",
                detail=(
                    f"{label} ({len(token)} chars) is committed as a literal. "
                    "Anything in the repo is readable by every clone and every fork, "
                    "and it stays readable in history after you delete the line."
                ),
                fix=(
                    "Revoke and rotate the key first, then read it from a server-side "
                    "environment variable. Never wire a credential into a NEXT_PUBLIC_ / "
                    "VITE_ / REACT_APP_ / EXPO_PUBLIC_ variable."
                ),
                evidence=evidence,
            )
        )
        if len(findings) >= 25:
            break

    return findings


def _committed_dotenv(rel: str, secret_findings: list[Finding]) -> list[Finding]:
    name = rel.rsplit("/", 1)[-1].lower()
    if not name.startswith(".env") or name in _ENV_ALLOWED:
        return []
    if secret_findings:
        # The credential finding is the one that matters; do not double-report.
        return []
    return [
        Finding(
            check="leak",
            rule_id="LEAK-02",
            severity=MEDIUM,
            title="dotenv file committed to the repository",
            location=f"{rel}:1",
            detail=(
                f"`{name}` is tracked by git. Even with harmless values today, one "
                "added secret later is published automatically."
            ),
            fix=f"Add `{name}` to .gitignore, commit `{name}.example` instead, and rotate anything it ever held.",
        )
    ]


def _secret_in_query(rel: str, text: str) -> list[Finding]:
    findings: list[Finding] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        if len(line) > 4000:
            continue
        match = _QUERY_SECRET_RE.search(line)
        if not match or _is_placeholder(match.group(1)):
            continue
        findings.append(
            Finding(
                check="leak",
                rule_id="LEAK-03",
                severity=LOW,
                title="credential-shaped value in a URL query string",
                location=f"{rel}:{lineno}",
                detail=(
                    "Query strings are copied into access logs, proxy logs and Referer "
                    "headers, which is a quiet way for a key to travel."
                ),
                fix="Send the credential in an Authorization header instead of the query string.",
                evidence=_trim(line.replace(match.group(1), _redact("query", match.group(1)))),
            )
        )
        if len(findings) >= 5:
            break
    return findings
