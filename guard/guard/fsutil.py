"""Deterministic, bounded file walking for the guard scanner.

Bounded matters more than complete: a PR bot that takes 6 minutes or walks a
vendored ``node_modules`` is a bot people uninstall. Every limit here exists to
keep the worst case predictable.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

# Directories that never contain first-party launch risk, or that are famous
# sources of red herrings (fixture keys, vendored code, build output).
SKIP_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        ".venv",
        "venv",
        ".env.d",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".nox",
        "dist",
        "build",
        ".next",
        ".nuxt",
        ".output",
        ".svelte-kit",
        ".tmp",
        "tmp",
        ".workbuddy",
        "guard-out",
        "site-packages",
        ".cache",
        "coverage",
        "htmlcov",
        "vendor",
        "third_party",
        "tests",
        "test",
        "__tests__",
        "fixtures",
        "__fixtures__",
        "docs",
        "doc",
    }
)

# Files we are willing to interpret as text. An allowlist (rather than a binary
# sniff alone) keeps the walk from spending time on models, images and wheels.
SCAN_SUFFIXES = frozenset(
    {
        "",
        ".py",
        ".pyi",
        ".js",
        ".mjs",
        ".cjs",
        ".jsx",
        ".ts",
        ".tsx",
        ".mts",
        ".cts",
        ".vue",
        ".svelte",
        ".astro",
        ".html",
        ".htm",
        ".json",
        ".jsonc",
        ".yml",
        ".yaml",
        ".toml",
        ".ini",
        ".cfg",
        ".conf",
        ".env",
        ".sh",
        ".bash",
        ".zsh",
        ".ps1",
        ".bat",
        ".cmd",
        ".dockerfile",
        ".tf",
        ".tfvars",
        ".hcl",
        ".gradle",
        ".properties",
        ".rb",
        ".go",
        ".rs",
        ".java",
        ".kt",
        ".php",
        ".cs",
        ".swift",
        ".dart",
        ".ex",
        ".exs",
        ".md",
        ".mdx",
        ".txt",
    }
)

MAX_FILE_BYTES = 512 * 1024
DEFAULT_MAX_FILES = 6000

# Test files carry fixture credentials by design. Scanning them is how a guard
# earns its reputation as a noisy bot.
_TEST_NAME_RE = re.compile(
    r"(^test_.*\.py$|.*_test\.py$|^conftest\.py$|.*\.test\.[cm]?[jt]sx?$|"
    r".*\.spec\.[cm]?[jt]sx?$|.*\.stories\.[cm]?[jt]sx?$|.*\.test\.py$)",
    re.IGNORECASE,
)


def is_scannable_name(name: str) -> bool:
    lower = name.lower()
    if lower in SKIP_DIRS:
        return False
    if _TEST_NAME_RE.match(lower):
        return False
    if lower.startswith(".env"):
        return True
    suffix = os.path.splitext(lower)[1]
    return suffix in SCAN_SUFFIXES


def decode(data: bytes) -> str:
    """Decode bytes to text without ever raising on a weird encoding."""
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    for encoding in ("utf-8", "utf-16", "latin-1"):
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, UnicodeError):
            continue
    return data.decode("utf-8", errors="replace")


def is_binary(data: bytes) -> bool:
    return b"\x00" in data[:8192]


def rel_path(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def walk(
    root: Path,
    *,
    max_files: int = DEFAULT_MAX_FILES,
    max_file_bytes: int = MAX_FILE_BYTES,
) -> tuple[list[tuple[str, Path, int]], bool]:
    """Return ``([(rel_path, path, size)], truncated)`` deterministically sorted."""
    root = Path(root)
    entries: list[tuple[str, Path, int]] = []

    if root.is_file():
        size = root.stat().st_size
        return [(root.name, root, min(size, max_file_bytes))], False

    truncated = False
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            d for d in dirnames if d.lower() not in SKIP_DIRS and not d.startswith("__")
        )
        for name in sorted(filenames):
            if not is_scannable_name(name):
                continue
            path = Path(dirpath) / name
            try:
                size = path.stat().st_size
            except OSError:
                continue
            if size == 0:
                continue
            if len(entries) >= max_files:
                truncated = True
                break
            entries.append((rel_path(path, root), path, size))
        if truncated:
            break

    entries.sort(key=lambda item: item[0])
    return entries, truncated
