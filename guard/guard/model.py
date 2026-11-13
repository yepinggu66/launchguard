"""Guard data model: severity, findings, report, grading.

Standard library only. This package must run inside a GitHub Action on a bare
runner with no ``pip install`` step, so nothing here may import agentproof or
any third-party module.
"""

from __future__ import annotations

import datetime as _dt
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

CRITICAL = "critical"
HIGH = "high"
MEDIUM = "medium"
LOW = "low"

SEVERITY_ORDER = {CRITICAL: 0, HIGH: 1, MEDIUM: 2, LOW: 3}

# One finding is enough to act on; three is a pattern. Capping the per-rule
# contribution keeps a single chatty rule from drowning out everything else.
SEVERITY_WEIGHT = {CRITICAL: 35, HIGH: 12, MEDIUM: 4, LOW: 1}
PER_RULE_CAP = 3


@dataclass(frozen=True)
class Finding:
    """A single rule hit at a single location."""

    check: str  # "leak" | "cost" | "perm"
    rule_id: str
    severity: str
    title: str
    location: str  # repo-relative path:line
    detail: str
    fix: str
    evidence: str = ""  # ALWAYS redacted; never the raw credential

    @property
    def is_blocker(self) -> bool:
        return self.severity in (CRITICAL, HIGH)

    def to_dict(self) -> dict[str, Any]:
        return {
            "check": self.check,
            "rule_id": self.rule_id,
            "severity": self.severity,
            "title": self.title,
            "location": self.location,
            "detail": self.detail,
            "fix": self.fix,
            "evidence": self.evidence,
        }


@dataclass
class GuardReport:
    target: str
    generated_at: str = ""
    files_scanned: int = 0
    bytes_scanned: int = 0
    duration_ms: int = 0
    truncated: bool = False
    findings: list[Finding] = field(default_factory=list)

    # ---------------------------------------------------------------- helpers

    def __post_init__(self) -> None:
        if not self.generated_at:
            self.generated_at = (
                _dt.datetime.now(_dt.timezone.utc)
                .isoformat(timespec="seconds")
                .replace("+00:00", "Z")
            )

    @property
    def by_severity(self) -> dict[str, int]:
        counts = {CRITICAL: 0, HIGH: 0, MEDIUM: 0, LOW: 0}
        for f in self.findings:
            counts[f.severity] = counts.get(f.severity, 0) + 1
        return counts

    @property
    def by_rule(self) -> dict[str, int]:
        return dict(Counter(f.rule_id for f in self.findings))

    @property
    def blockers(self) -> list[Finding]:
        return [f for f in self.findings if f.severity in (CRITICAL, HIGH)]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity in (MEDIUM, LOW)]

    @property
    def risk_score(self) -> int:
        severity_of: dict[str, str] = {}
        for f in self.findings:
            severity_of.setdefault(f.rule_id, f.severity)
        total = sum(
            min(n, PER_RULE_CAP) * SEVERITY_WEIGHT[severity_of[rule]]
            for rule, n in Counter(f.rule_id for f in self.findings).items()
        )
        return min(100, total)

    @property
    def grade(self) -> str:
        score = self.risk_score
        if score == 0:
            return "A"
        if score <= 10:
            return "B"
        if score <= 25:
            return "C"
        if score <= 45:
            return "D"
        return "F"

    @property
    def clean(self) -> bool:
        return not self.findings

    def sorted_findings(self) -> list[Finding]:
        return sorted(
            self.findings,
            key=lambda f: (SEVERITY_ORDER[f.severity], f.check, f.rule_id, f.location),
        )

    def to_dict(self) -> dict[str, Any]:
        counts = self.by_severity
        return {
            "format": "agentproof-guard-v1",
            "target": self.target,
            "generated_at": self.generated_at,
            "risk_score": self.risk_score,
            "grade": self.grade,
            "files_scanned": self.files_scanned,
            "bytes_scanned": self.bytes_scanned,
            "duration_ms": self.duration_ms,
            "truncated": self.truncated,
            "summary": {
                "total": len(self.findings),
                "by_severity": counts,
                "by_rule": self.by_rule,
                "blockers": len(self.blockers),
            },
            "findings": [f.to_dict() for f in self.sorted_findings()],
        }
