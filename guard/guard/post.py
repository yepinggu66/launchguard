"""Create or update the single guard comment on a pull request.

One comment, edited in place, keyed by a hidden marker. A bot that appends a new
comment on every push is a bot people mute; a bot that rewrites one comment is a
bot people read.

Standard library only (urllib), so it runs on a bare runner:
    python guard/post.py <body-file>
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

_HERE = Path(__file__).resolve()
if __package__ in (None, ""):  # pragma: no cover - direct script execution
    sys.path.insert(0, str(_HERE.parent.parent))

from guard.render import MARKER  # noqa: E402

API = os.environ.get("GITHUB_API_URL", "https://api.github.com")
MAX_PAGES = 10


def _request(method: str, url: str, token: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Authorization", f"Bearer {token}")
    request.add_header("Accept", "application/vnd.github+json")
    request.add_header("X-GitHub-Api-Version", "2022-11-28")
    request.add_header("User-Agent", "agentproof-guard")
    if data is not None:
        request.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(request, timeout=20) as response:
        raw = response.read()
    return json.loads(raw.decode("utf-8")) if raw else {}


def _find_existing(repo: str, number: int, token: str) -> int | None:
    for page in range(1, MAX_PAGES + 1):
        url = f"{API}/repos/{repo}/issues/{number}/comments?per_page=100&page={page}"
        comments = _request("GET", url, token)
        if not isinstance(comments, list) or not comments:
            return None
        for comment in comments:
            body = comment.get("body") or ""
            if MARKER in body:
                return int(comment["id"])
        if len(comments) < 100:
            return None
    return None


def post(body_path: str) -> int:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    event_path = os.environ.get("GITHUB_EVENT_PATH", "")

    if not token:
        print("guard: no GITHUB_TOKEN, skipping comment", file=sys.stderr)
        return 0
    if not repo or not event_path or not Path(event_path).exists():
        print("guard: no pull request context, skipping comment", file=sys.stderr)
        return 0

    event = json.loads(Path(event_path).read_text(encoding="utf-8"))
    number = (event.get("pull_request") or {}).get("number") or (event.get("issue") or {}).get("number")
    if not number:
        print("guard: event is not a pull request, skipping comment", file=sys.stderr)
        return 0

    body = Path(body_path).read_text(encoding="utf-8")
    existing = _find_existing(repo, int(number), token)

    try:
        if existing:
            result = _request("PATCH", f"{API}/repos/{repo}/issues/comments/{existing}", token, {"body": body})
            action = "updated"
        else:
            result = _request("POST", f"{API}/repos/{repo}/issues/{number}/comments", token, {"body": body})
            action = "created"
    except urllib.error.HTTPError as error:  # a missing comment must never fail the build
        print(f"guard: could not post comment ({error.code}): {error.reason}", file=sys.stderr)
        return 0
    except urllib.error.URLError as error:
        print(f"guard: could not reach GitHub: {error.reason}", file=sys.stderr)
        return 0

    print(f"guard: {action} comment {result.get('html_url', '')}")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    default = os.environ.get("GUARD_COMMENT_PATH", "guard-out/comment.md")
    return post(argv[0] if argv else default)


if __name__ == "__main__":
    raise SystemExit(main())
