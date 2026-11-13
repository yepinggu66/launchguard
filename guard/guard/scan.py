"""Scan orchestration: one pass over the tree, three checks, one report.

The one-pass rule is deliberate. Reading every file three times triples the I/O
on a big repo for no benefit, and a PR bot that is slow is a PR bot that gets
removed.
"""

from __future__ import annotations

import time
from pathlib import Path

from . import cost, fsutil, leak, perm
from .model import Finding, GuardReport

VERSION = "0.1.0"


def scan_repo(
    target: str | Path,
    *,
    max_files: int = fsutil.DEFAULT_MAX_FILES,
    checks: tuple[str, ...] = ("leak", "cost", "perm"),
) -> GuardReport:
    root = Path(target)
    started = time.perf_counter()
    entries, truncated = fsutil.walk(root, max_files=max_files)

    findings: list[Finding] = []
    bytes_scanned = 0
    files_scanned = 0

    for rel, path, size in entries:
        try:
            raw = path.read_bytes()[: fsutil.MAX_FILE_BYTES]
        except OSError:
            continue
        if fsutil.is_binary(raw):
            continue
        bytes_scanned += len(raw)
        files_scanned += 1
        text = fsutil.decode(raw)
        low_name = rel.rsplit("/", 1)[-1].lower()

        if "leak" in checks:
            if low_name.startswith(".env") or any(hint in raw for hint in leak.LEAK_BYTE_HINTS):
                findings.extend(leak.check_text(rel, text))

        if "perm" in checks:
            findings.extend(perm.check_text(rel, text))

        if "cost" in checks and rel.lower().endswith((".py", ".pyi")):
            findings.extend(cost.check_python(rel, text))

    findings = _postprocess(_dedupe(findings))
    duration_ms = int((time.perf_counter() - started) * 1000)

    return GuardReport(
        target=str(root),
        files_scanned=files_scanned,
        bytes_scanned=bytes_scanned,
        duration_ms=duration_ms,
        truncated=truncated,
        findings=findings,
    )


def _postprocess(findings: list[Finding]) -> list[Finding]:
    """Collapse the one rule that is useful as a count but useless as a list.

    ``COST-03`` (client built without an explicit timeout) is true dozens of
    times in any codebase that instantiates ``OpenAI()`` per module. Thirty
    identical rows is noise; one row saying "30 clients, first at x.py:10" is a
    fact someone can act on.
    """
    clients = [f for f in findings if f.rule_id == "COST-03"]
    if len(clients) <= 1:
        return findings

    first = clients[0]
    merged = Finding(
        check="cost",
        rule_id="COST-03",
        severity="low",
        title=f"{len(clients)} model clients created without an explicit timeout",
        location=first.location,
        detail=(
            f"{len(clients)} client constructions rely on SDK defaults for timeout and "
            f"retries. First occurrence: {first.location}."
        ),
        fix="Construct clients with an explicit `timeout=` and `max_retries=`.",
        evidence=first.evidence,
    )
    return [f for f in findings if f.rule_id != "COST-03"] + [merged]


def _dedupe(findings: list[Finding]) -> list[Finding]:
    """Drop exact duplicates, and drop PERM-04 where LEAK-01 already named the key."""
    leak_files = {f.location.rsplit(":", 1)[0] for f in findings if f.rule_id == "LEAK-01"}
    seen: set[tuple[str, str]] = set()
    out: list[Finding] = []
    for f in findings:
        if f.rule_id == "PERM-04" and f.location.rsplit(":", 1)[0] in leak_files:
            continue
        key = (f.rule_id, f.location)
        if key in seen:
            continue
        seen.add(key)
        out.append(f)
    return out
