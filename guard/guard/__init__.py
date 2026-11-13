"""agentproof-guard: the three checks that only matter once AI writes your code.

Public surface::

    from guard import scan_repo, comment_markdown, badge_svg

Nothing in this package imports agentproof or any third-party module, so it
runs unchanged inside a GitHub Action on a bare runner.
"""

from __future__ import annotations

from .model import CRITICAL, HIGH, LOW, MEDIUM, Finding, GuardReport
from .render import (
    BatchSummary,
    badge_svg,
    card_svg,
    comment_markdown,
    fix_prompt,
    index_markdown,
    thread_markdown,
)
from .scan import VERSION, scan_repo

__version__ = VERSION

__all__ = [
    "CRITICAL",
    "HIGH",
    "LOW",
    "MEDIUM",
    "BatchSummary",
    "Finding",
    "GuardReport",
    "VERSION",
    "__version__",
    "badge_svg",
    "card_svg",
    "comment_markdown",
    "fix_prompt",
    "index_markdown",
    "scan_repo",
    "thread_markdown",
]
