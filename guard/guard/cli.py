"""Guard command line: scan one repo, batch-scan many, prepare a PR comment."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .model import GuardReport
from .render import (
    BatchSummary,
    badge_svg,
    card_svg,
    comment_markdown,
    index_markdown,
    thread_markdown,
)
from .scan import VERSION, scan_repo

FAIL_ON_CHOICES = ("none", "critical", "high", "medium")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="guard",
        description="Launch guard: credentials, runaway model loops, wildcard permissions.",
    )
    parser.add_argument("--version", action="version", version=f"agentproof-guard {VERSION}")
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan", help="scan one repository or directory")
    scan.add_argument("path", nargs="?", default=".")
    scan.add_argument("--json", dest="json_out", help="write the full report as JSON")
    scan.add_argument("--comment", dest="comment_out", help="write the PR comment markdown")
    scan.add_argument("--badge", dest="badge_out", help="write the grade badge SVG")
    scan.add_argument("--fail-on", default="critical", choices=FAIL_ON_CHOICES)
    scan.add_argument("--max-files", type=int, default=None)
    scan.add_argument("--quiet", action="store_true")

    batch = sub.add_parser("batch", help="scan many repositories into one shareable bundle")
    batch.add_argument("paths", nargs="+")
    batch.add_argument("--out", default="guard-out")
    batch.add_argument("--max-files", type=int, default=None)

    pr = sub.add_parser("pr", help="render the comment for a GitHub pull_request event")
    pr.add_argument("--event", default=None, help="path to event JSON (default: $GITHUB_EVENT_PATH)")
    pr.add_argument("--out", default="guard-out/comment.md")
    pr.add_argument("--fail-on", default="critical", choices=FAIL_ON_CHOICES)

    demo = sub.add_parser("demo", help="generate a small failing app and scan it")
    demo.add_argument("--out", default="guard-out/demo")

    args = parser.parse_args(argv)
    if args.command == "scan":
        return _cmd_scan(args)
    if args.command == "batch":
        return _cmd_batch(args)
    if args.command == "demo":
        return _cmd_demo(args)
    return _cmd_pr(args)


# ---------------------------------------------------------------------------


def _cmd_scan(args) -> int:
    report = scan_repo(args.path, **_scan_kwargs(args))
    _print_summary(report)

    if args.json_out:
        _write(args.json_out, json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    if args.comment_out:
        _write(args.comment_out, comment_markdown(report, repo_slug=_slug_from_path(args.path)))
    if args.badge_out:
        _write(args.badge_out, badge_svg(report))

    _set_outputs(report)
    return _exit_code(report, args.fail_on)


def _cmd_pr(args) -> int:
    event_path = args.event or os.environ.get("GITHUB_EVENT_PATH")
    slug = ""
    if event_path and Path(event_path).exists():
        event = json.loads(Path(event_path).read_text(encoding="utf-8"))
        repo = event.get("repository") or {}
        slug = repo.get("full_name", "") or ""
        pull = event.get("pull_request") or {}
        number = pull.get("number")
        if number:
            print(f"event: {slug}#{number}")

    report = scan_repo(".", max_files=None)
    _print_summary(report)
    _write(args.out, comment_markdown(report, repo_slug=slug))
    _set_outputs(report, comment_path=args.out)
    return _exit_code(report, args.fail_on)


def _cmd_demo(args) -> int:
    from .demo import build_tree

    out = Path(args.out)
    app = build_tree(out / "demo-app")
    report = scan_repo(app)
    _print_summary(report)
    _write(out / "comment.md", comment_markdown(report, repo_slug="demo/vibe-coded-app"))
    _write(out / "badge.svg", badge_svg(report))
    _write(out / "report.json", json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    print(f"\nwrote {out}/comment.md, badge.svg, report.json")
    return 0


def _cmd_batch(args) -> int:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    summary = BatchSummary()
    payload: list[dict] = []

    for raw in args.paths:
        path = Path(raw)
        if not path.is_dir():
            print(f"skip (not a directory): {raw}", file=sys.stderr)
            continue
        report = scan_repo(path, max_files=args.max_files or 6000)
        slug = _slug_from_path(str(path))
        repo_dir = out / slug
        repo_dir.mkdir(parents=True, exist_ok=True)
        _write(repo_dir / "comment.md", comment_markdown(report, repo_slug=slug))
        _write(repo_dir / "badge.svg", badge_svg(report))
        _write(repo_dir / "report.json", json.dumps(report.to_dict(), indent=2, ensure_ascii=False))

        entry = {
            "slug": slug,
            "grade": report.grade,
            "risk_score": report.risk_score,
            "blockers": len(report.blockers),
            "advisory": len(report.warnings),
            "files": report.files_scanned,
            "ms": report.duration_ms,
            "by_rule": report.by_rule,
        }
        summary.repos.append(entry)
        payload.append(entry)
        print(
            f"{slug:<42} {report.grade:>2}  blockers={len(report.blockers):<3} "
            f"files={report.files_scanned:<6} {report.duration_ms}ms"
        )

    _write(out / "index.md", index_markdown(summary))
    _write(out / "index.json", json.dumps(payload, indent=2, ensure_ascii=False))
    _write(out / "card.svg", card_svg(summary))
    _write(out / "thread.md", thread_markdown(summary))
    print(f"\nwrote {out}/  ({len(summary.repos)} repos, {summary.files:,} files)")
    return 0


# ---------------------------------------------------------------------------


def _scan_kwargs(args) -> dict:
    kwargs: dict = {}
    if getattr(args, "max_files", None):
        kwargs["max_files"] = args.max_files
    return kwargs


def _slug_from_path(raw: str) -> str:
    name = Path(raw).resolve().name
    return name or "repo"


def _write(path: str | Path, content: str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def _print_summary(report: GuardReport) -> None:
    counts = report.by_severity
    # Console output stays ASCII: Windows runners default to a legacy code page
    # and a mojibake log is a support ticket.
    print(
        f"grade {report.grade} ({report.risk_score}/100) | "
        f"{report.files_scanned:,} files | {report.duration_ms}ms | "
        f"critical={counts['critical']} high={counts['high']} "
        f"medium={counts['medium']} low={counts['low']}"
    )
    if report.truncated:
        print("note: file cap reached, scan was truncated", file=sys.stderr)
    for finding in report.sorted_findings()[:15]:
        print(
            f"  [{finding.severity.upper():<8}] {finding.rule_id} "
            f"{finding.location} - {finding.title}"
        )


def _exit_code(report: GuardReport, fail_on: str) -> int:
    counts = report.by_severity
    if fail_on == "none":
        return 0
    if fail_on == "critical" and counts["critical"]:
        return 1
    if fail_on == "high" and (counts["critical"] or counts["high"]):
        return 1
    if fail_on == "medium" and (counts["critical"] or counts["high"] or counts["medium"]):
        return 1
    return 0


def _set_outputs(report: GuardReport, *, comment_path: str = "") -> None:
    """Publish GitHub Action outputs when running inside an Action."""
    target = os.environ.get("GITHUB_OUTPUT")
    if not target:
        return
    counts = report.by_severity
    lines = [
        f"grade={report.grade}",
        f"risk_score={report.risk_score}",
        f"blockers={len(report.blockers)}",
        f"critical={counts['critical']}",
        f"high={counts['high']}",
        f"medium={counts['medium']}",
        f"low={counts['low']}",
        f"findings={len(report.findings)}",
        f"files={report.files_scanned}",
    ]
    if comment_path:
        lines.append(f"comment_path={comment_path}")
    try:
        with open(target, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    except OSError:
        pass


if __name__ == "__main__":
    raise SystemExit(main())
