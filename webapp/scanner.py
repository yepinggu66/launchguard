"""Repo fetching + scanning for the public app.

Two hard rules: never execute anything from the tarball, and never let a
user-supplied string decide more than ``owner/repo``.
"""

from __future__ import annotations

import io
import re
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "guard") not in sys.path:
    sys.path.insert(0, str(ROOT / "guard"))

from guard import scan_repo  # noqa: E402
from guard import fsutil  # noqa: E402

MAX_TARBALL = 40 * 1024 * 1024
MAX_MEMBERS = 3000

_NAME_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,38})$")
_SNIPPET_FILES = {"code.py", "mcp.json"}


class ScanError(Exception):
    """A failure we are willing to show the visitor."""


def parse_repo(raw: str) -> tuple[str, str]:
    value = (raw or "").strip()
    value = value.removeprefix("https://github.com/").removeprefix("http://github.com/")
    value = value.strip("/")
    if value.endswith(".git"):
        value = value[:-4]
    parts = value.split("/")
    if len(parts) != 2:
        raise ScanError("Use the form owner/repo, for example unclecode/crawl4ai.")
    owner, repo = parts
    if not _NAME_RE.match(owner) or not _NAME_RE.match(repo):
        raise ScanError("That does not look like a repository name.")
    return owner, repo


def _download(owner: str, repo: str) -> bytes:
    import urllib.error
    import urllib.request

    url = f"https://codeload.github.com/{owner}/{repo}/tar.gz/HEAD"
    request = urllib.request.Request(url, headers={"User-Agent": "launchguard/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = response.read(MAX_TARBALL + 1)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            raise ScanError(f"{owner}/{repo} is not public (or does not exist).") from error
        raise ScanError(f"GitHub returned {error.code}. Try again in a moment.") from error
    except Exception as error:  # noqa: BLE001 - network shapes vary
        raise ScanError("Could not reach GitHub. Try again in a moment.") from error
    if len(data) > MAX_TARBALL:
        raise ScanError("That repository is too large to scan here. Clone it and run the CLI.")
    return data


def _extract(data: bytes, target: Path) -> int:
    try:
        archive = tarfile.open(fileobj=io.BytesIO(data), mode="r:gz")
    except tarfile.TarError as error:
        raise ScanError("GitHub returned something that is not a tarball.") from error

    selected: list[tarfile.TarInfo] = []
    with archive:
        for member in archive.getmembers():
            if not member.isfile() or member.size > fsutil.MAX_FILE_BYTES:
                continue
            parts = member.name.split("/")[1:]  # drop the repo-sha/ prefix
            if not parts:
                continue
            if any(part.lower() in fsutil.SKIP_DIRS for part in parts[:-1]):
                continue
            if not fsutil.is_scannable_name(parts[-1]):
                continue
            selected.append(member)
            if len(selected) >= MAX_MEMBERS:
                break
        try:
            archive.extractall(target, members=selected, filter="data")
        except TypeError:  # Python < 3.12
            archive.extractall(target, members=selected)
    return len(selected)


def scan_github(owner: str, repo: str) -> dict:
    data = _download(owner, repo)
    with tempfile.TemporaryDirectory(prefix="lg-") as tmp:
        files = _extract(data, Path(tmp))
        if files == 0:
            raise ScanError("No scannable source files found in that repository.")
        report = scan_repo(tmp)
    payload = report.to_dict()
    payload["target"] = f"{owner}/{repo}"
    return payload


def scan_snippet(text: str, filename: str = "code.py") -> dict:
    if not text.strip():
        raise ScanError("Paste some code first.")
    if len(text) > 200_000:
        raise ScanError("That snippet is too long. Scan the repository instead.")
    name = filename if filename in _SNIPPET_FILES else "code.py"
    with tempfile.TemporaryDirectory(prefix="lg-") as tmp:
        target = Path(tmp) / name
        target.write_text(text, encoding="utf-8")
        report = scan_repo(tmp)
    payload = report.to_dict()
    payload["target"] = f"snippet:{name}"
    return payload
