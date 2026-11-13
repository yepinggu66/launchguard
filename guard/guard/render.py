"""Rendering: the PR comment, the badge, the share card, the public thread.

Everything a stranger sees is produced here, so the formatting rules are strict:

* the comment is short by default and long only on click (a wall of text in a PR
  gets muted, and a muted bot has zero growth value);
* every claim carries a location a human can click through to;
* the card has to look good enough that someone screenshots it unprompted,
  because that screenshot is the entire acquisition channel.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from html import escape as _xml_escape

from .model import CRITICAL, HIGH, LOW, MEDIUM

MARKER = "<!-- agentproof-guard:v1 -->"
DOCS_URL = "https://github.com/yepinggu66/agentproof-cloud/tree/main/guard"
VERSION = "0.1.0"

_GRADE_COLOR = {
    "A": "#2ea043",
    "B": "#3fb950",
    "C": "#d29922",
    "D": "#db6d28",
    "F": "#f85149",
}
_SEV_ICON = {CRITICAL: "\U0001f534", HIGH: "\U0001f534", MEDIUM: "\U0001f7e1", LOW: "\u26aa"}


# ---------------------------------------------------------------------------
# PR comment
# ---------------------------------------------------------------------------


def comment_markdown(report, *, repo_slug: str = "") -> str:
    counts = report.by_severity
    blockers = counts[CRITICAL] + counts[HIGH]
    advisory = counts[MEDIUM] + counts[LOW]
    target = f"`{repo_slug}`" if repo_slug else "this pull request"

    lines = [MARKER, ""]

    if not report.findings:
        lines += [
            "## \U0001f6e1\ufe0f Launch guard: clear",
            "",
            f"{report.files_scanned:,} files scanned in {report.duration_ms / 1000:.1f}s "
            "— no exposed credentials, unbounded model loops, or wildcard permissions.",
            "",
            _footer(),
        ]
        return "\n".join(lines)

    if blockers and advisory:
        title = f"**{blockers} blocking**, {advisory} advisory"
    elif blockers:
        title = f"**{blockers} blocking**"
    else:
        title = f"{advisory} advisory"

    lines += [
        f"## \U0001f6e1\ufe0f Launch guard: {title}",
        "",
        f"{target} \u00b7 grade **{report.grade}** ({report.risk_score}/100) \u00b7 "
        f"{report.files_scanned:,} files \u00b7 {report.duration_ms}ms",
        "",
    ]

    blocking_findings = [f for f in report.sorted_findings() if f.is_blocker]
    if blocking_findings:
        lines += ["### Fix before merge", "", "| | Location | Finding |", "|:--:|---|---|"]
        for finding in blocking_findings[:8]:
            icon = _SEV_ICON.get(finding.severity, "\u26aa")
            lines.append(
                f"| {icon} | `{_cell(finding.location)}` | {_cell(finding.title)} |"
            )
        if len(blocking_findings) > 8:
            lines.append(f"| | | *+{len(blocking_findings) - 8} more blocking findings* |")
        lines.append("")

    warning_findings = [f for f in report.sorted_findings() if not f.is_blocker]
    if warning_findings:
        lines += [
            f"<details><summary>\U0001f7e1 {len(warning_findings)} advisory finding(s)</summary>",
            "",
            "| Location | Finding |",
            "|---|---|",
        ]
        for finding in warning_findings[:15]:
            lines.append(f"| `{_cell(finding.location)}` | {_cell(finding.title)} |")
        if len(warning_findings) > 15:
            lines.append(f"| | *+{len(warning_findings) - 15} more* |")
        lines += ["", "</details>", ""]

    lines += [
        "<details><summary>\U0001f527 One prompt that fixes all of it "
        f"({len(report.sorted_findings())} findings)</summary>",
        "",
        "```text",
        fix_prompt(report),
        "```",
        "",
        "</details>",
        "",
        _footer(),
    ]
    return "\n".join(lines)


def fix_prompt(report, *, max_items: int = 12) -> str:
    """A paste-ready instruction block for Cursor / Claude Code / Copilot."""
    findings = report.sorted_findings()[:max_items]
    lines = [
        "Fix the launch-blocking issues below in this repository.",
        "Change only what is listed. Do not refactor unrelated code, do not rename public APIs.",
        "",
    ]
    for idx, finding in enumerate(findings, 1):
        lines.append(f"{idx}. {finding.location} \u2014 {finding.fix}")
    if len(report.sorted_findings()) > max_items:
        lines.append(
            f"\n({len(report.sorted_findings()) - max_items} lower-severity findings omitted; "
            "ask the user before touching those.)"
        )
    lines += [
        "",
        "After the edits, confirm for each item what changed, and never print a credential value.",
    ]
    return "\n".join(lines)


def _footer() -> str:
    return (
        f"<sub><a href=\"{DOCS_URL}\">agentproof-guard</a> v{VERSION} \u00b7 "
        "static analysis, nothing leaves the runner \u00b7 "
        f"re-run by pushing a commit</sub>"
    )


def _cell(value: str) -> str:
    return value.replace("|", "\\|")


# ---------------------------------------------------------------------------
# Badge
# ---------------------------------------------------------------------------


def badge_svg(report) -> str:
    grade = report.grade
    color = _GRADE_COLOR[grade]
    blockers = len(report.blockers)
    right = f"{grade}" if not blockers else f"{grade} \u00b7 {blockers} blk"
    right_width = 46 + 7 * len(right)
    left_width = 128
    width = left_width + right_width
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="28" role="img" aria-label="launch guard: {grade}">
  <title>launch guard: {grade}</title>
  <g>
    <rect width="{left_width}" height="28" fill="#0b0e14"/>
    <rect x="{left_width}" width="{right_width}" height="28" fill="{color}"/>
  </g>
  <g fill="#e6edf3" text-anchor="middle" font-family="'Segoe UI',Verdana,DejaVu Sans,sans-serif" font-size="11">
    <text x="{left_width // 2}" y="18">\U0001f6e1 launch guard</text>
    <text x="{left_width + right_width // 2}" y="18" font-weight="600" fill="#0b0e14">{_xml_escape(right)}</text>
  </g>
</svg>
"""


# ---------------------------------------------------------------------------
# Batch summary + share card + thread
# ---------------------------------------------------------------------------


@dataclass
class BatchSummary:
    repos: list[dict] = field(default_factory=list)
    generated_at: str = ""

    def __post_init__(self) -> None:
        if not self.generated_at:
            self.generated_at = (
                _dt.datetime.now(_dt.timezone.utc)
                .isoformat(timespec="seconds")
                .replace("+00:00", "Z")
            )

    @property
    def files(self) -> int:
        return sum(r["files"] for r in self.repos)

    @property
    def seconds(self) -> float:
        return sum(r["ms"] for r in self.repos) / 1000.0

    @property
    def rule_counts(self) -> dict[str, int]:
        totals: dict[str, int] = {}
        for repo in self.repos:
            for rule, count in repo.get("by_rule", {}).items():
                totals[rule] = totals.get(rule, 0) + count
        return totals

    @property
    def dirty(self) -> list[dict]:
        return [r for r in self.repos if r["blockers"] > 0]

    @property
    def clean(self) -> list[dict]:
        return [r for r in self.repos if r["blockers"] == 0 and r["advisory"] == 0]

    @property
    def with_findings(self) -> list[dict]:
        return [r for r in self.repos if r["blockers"] + r["advisory"] > 0]

    @property
    def worst(self) -> list[dict]:
        return sorted(self.repos, key=lambda r: (-r["blockers"], -r["advisory"]))[:6]


def card_svg(summary: BatchSummary) -> str:
    """1200x630 share card. Designed to be screenshotted, not read closely."""
    rules = summary.rule_counts
    creds = rules.get("LEAK-01", 0)
    loops = rules.get("COST-01", 0) + rules.get("COST-04", 0)
    caps = rules.get("COST-02", 0)
    perms = rules.get("PERM-01", 0) + rules.get("PERM-02", 0) + rules.get("PERM-03", 0)

    blocks = [
        (f"{creds:,}", "hardcoded credentials"),
        (f"{loops:,}", "loops with no exit"),
        (f"{caps:,}", "calls with no token cap"),
        (f"{perms:,}", "wildcard permissions"),
    ]
    stats = []
    for idx, (number, label) in enumerate(blocks):
        x = 80 + idx * 268
        stats.append(
            f'<text x="{x}" y="372" font-size="64" font-weight="700" fill="#e6edf3" '
            f'font-family="Consolas,ui-monospace,monospace">{_xml_escape(number)}</text>'
            f'<text x="{x}" y="404" font-size="21" fill="#8b949e" '
            f'font-family="\'Segoe UI\',sans-serif">{_xml_escape(label)}</text>'
        )

    flagged = sorted(
        summary.with_findings, key=lambda r: (-r["blockers"], -r["advisory"])
    )

    rows = []
    for idx, repo in enumerate(flagged[:6]):
        y = 232 + idx * 44
        color = _GRADE_COLOR.get(repo["grade"], "#8b949e")
        rows.append(
            f'<text x="700" y="{y}" font-size="20" fill="#8b949e" '
            f'font-family="Consolas,ui-monospace,monospace">{_xml_escape(_pretty_slug(repo["slug"])[:34])}</text>'
            f'<text x="1100" y="{y}" font-size="20" font-weight="700" fill="{color}" '
            f'text-anchor="end" font-family="Consolas,ui-monospace,monospace">{_xml_escape(repo["grade"])}</text>'
            f'<text x="1150" y="{y}" font-size="18" fill="#8b949e" text-anchor="end" '
            f'font-family="Consolas,ui-monospace,monospace">{repo["blockers"] + repo["advisory"]}</text>'
        )

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630">
  <rect width="1200" height="630" fill="#0b0e14"/>
  <rect x="0" y="0" width="1200" height="4" fill="#2ea043"/>
  <text x="80" y="96" font-size="19" letter-spacing="4" fill="#3fb950"
        font-family="Consolas,ui-monospace,monospace">LAUNCH GUARD / STATIC SCAN</text>
  <text x="80" y="176" font-size="44" font-weight="700" fill="#e6edf3"
        font-family="'Segoe UI',Inter,sans-serif">{len(summary.repos)} agent repos, {summary.files:,} files</text>
  <text x="80" y="226" font-size="27" fill="#8b949e"
        font-family="'Segoe UI',Inter,sans-serif">{len(summary.with_findings)} of {len(summary.repos)} repos had at least one finding</text>
  {''.join(stats)}
  <line x1="80" y1="440" x2="1120" y2="440" stroke="#21262d" stroke-width="1"/>
  <text x="700" y="200" font-size="19" letter-spacing="2" fill="#8b949e"
        font-family="Consolas,ui-monospace,monospace">FINDINGS</text>
  {''.join(rows)}
  <text x="80" y="536" font-size="19" fill="#6e7681"
        font-family="'Segoe UI',Inter,sans-serif">scanned in {summary.seconds:.0f}s \u00b7 nothing left the runner</text>
  <text x="80" y="578" font-size="21" fill="#e6edf3"
        font-family="Consolas,ui-monospace,monospace">github.com/yepinggu66/agentproof-cloud</text>
</svg>
"""


def index_markdown(summary: BatchSummary) -> str:
    lines = [
        "# Launch guard \u2014 batch report",
        "",
        f"`{len(summary.repos)}` repositories \u00b7 `{summary.files:,}` files \u00b7 "
        f"`{summary.seconds:.0f}s` \u00b7 {summary.generated_at}",
        "",
        "| Repo | Grade | Blockers | Advisory | Files | Comment |",
        "|---|---|--:|--:|--:|---|",
    ]
    for repo in sorted(summary.repos, key=lambda r: (-r["blockers"], r["slug"])):
        lines.append(
            f"| `{repo['slug']}` | **{repo['grade']}** | {repo['blockers']} | "
            f"{repo['advisory']} | {repo['files']:,} | [comment]({repo['slug']}/comment.md) |"
        )
    lines += ["", "## Findings by rule", "", "| Rule | Count |", "|---|--:|"]
    for rule, count in sorted(summary.rule_counts.items(), key=lambda kv: -kv[1]):
        lines.append(f"| `{rule}` | {count} |")
    return "\n".join(lines)


def thread_markdown(summary: BatchSummary) -> str:
    """A pattern-first thread.

    Deliberately not a statistics flex: the finding that survives scrutiny in a
    well-maintained corpus is *low* — which is exactly the honest hook. "The
    libraries are careful, your app isn't" is a claim a stranger can check.
    """
    rules = summary.rule_counts
    creds = rules.get("LEAK-01", 0)
    loops = rules.get("COST-01", 0) + rules.get("COST-04", 0)
    uncapped = rules.get("COST-02", 0)
    perms = rules.get("PERM-01", 0) + rules.get("PERM-02", 0) + rules.get("PERM-03", 0)
    flagged = [r for r in summary.repos if r["blockers"] + r["advisory"] > 0]
    flagged.sort(key=lambda r: (-r["blockers"], -r["advisory"]))

    where = "\n".join(
        f"\u2022 {_pretty_slug(r['slug'])} \u2014 {r['blockers'] + r['advisory']} "
        f"finding(s), grade {r['grade']}"
        for r in flagged[:5]
    ) or "\u2022 nothing at all"

    return f"""**1/{7}**
Six lines of Python. No bug, no CVE, passes code review:

`while True:` \u2192 `client.chat.completions.create(...)` \u2192 no `break`, no `max_tokens`, SDK default retries.

That is how a $4,000 invoice happens overnight.

**2/{7}**
Nothing in the standard toolchain catches it:

\u2022 linters check syntax, not spend
\u2022 Dependabot checks versions, not loop exits
\u2022 code review reads intent, and the intent looked fine

**3/{7}**
So I wrote three checks for the failure modes that only exist once AI writes the code:

1. credentials that end up somewhere readable
2. model calls in loops with no exit
3. permission switches that turn the approval prompt off

**4/{7}**
I ran it over {len(summary.repos)} widely used agent / MCP repositories: {summary.files:,} files.

\u2022 {creds} hardcoded {_plural(creds, 'credential')}
\u2022 {loops} runaway {_plural(loops, 'loop')}
\u2022 {uncapped} uncapped model {_plural(uncapped, 'call')}
\u2022 {perms} permission {_plural(perms, 'bypass', 'bypasses')}

{len(flagged)} of {len(summary.repos)} repos had at least one finding \u2014 most of it advisory.

**5/{7}**
Which is the point.

The libraries are careful. Adapters forward `**kwargs`, vendors pass budgets explicitly, nobody hardcodes a key in a published package.

The bugs live in application code \u2014 the thing you and I write at 2am with an agent.

**6/{7}**
Where the findings were:

{where}

Each one has a file:line. Nothing is inferred from a README, and no credential value is ever printed \u2014 the report redacts it.

**7/{7}**
It runs as a GitHub Action: one comment per PR, edited in place, with a paste-ready fix prompt.

Stdlib Python, no telemetry, nothing leaves your runner:
{DOCS_URL}

Run it on your own repo first. Then tell me which check is too noisy \u2014 I will tune it or drop it.
"""


def _pretty_slug(slug: str) -> str:
    return slug.replace("__", "/")


def _plural(count: int, singular: str, plural: str | None = None) -> str:
    if count == 1:
        return singular
    return plural or f"{singular}s"


__all__ = [
    "BatchSummary",
    "MARKER",
    "badge_svg",
    "card_svg",
    "comment_markdown",
    "fix_prompt",
    "index_markdown",
    "thread_markdown",
]
