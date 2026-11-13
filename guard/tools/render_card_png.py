"""Dev-only: render guard-out/index.json to a 1200x630 PNG card.

Not part of the Action. The scanner stays standard-library-only; this script
exists because X does not accept an SVG and a screenshot of a browser window
looks worse than the same layout drawn directly.

    python guard/tools/render_card_png.py guard-out/index.json guard-out/card.png
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1200, 630
BG = (11, 14, 20)
FG = (230, 237, 243)
MUTED = (139, 148, 158)
DIM = (110, 118, 129)
GREEN = (63, 185, 80)
RULE = (33, 38, 45)

GRADE_COLOR = {
    "A": (46, 160, 67),
    "B": (63, 185, 80),
    "C": (210, 153, 34),
    "D": (219, 109, 40),
    "F": (248, 81, 73),
}

FONTS = Path("C:/Windows/Fonts")


def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    for candidate in (name, "segoeui.ttf"):
        path = FONTS / candidate
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def _spaced(text: str) -> str:
    return " ".join(text)


def render(index_path: str, out_path: str) -> None:
    repos = json.loads(Path(index_path).read_text(encoding="utf-8"))
    total_files = sum(int(r["files"]) for r in repos)
    total_ms = sum(int(r["ms"]) for r in repos)
    flagged = [r for r in repos if r["blockers"] + r["advisory"] > 0]
    flagged.sort(key=lambda r: (-r["blockers"], -r["advisory"]))

    rule_counts: dict[str, int] = {}
    for repo in repos:
        for rule, count in (repo.get("by_rule") or {}).items():
            rule_counts[rule] = rule_counts.get(rule, 0) + count

    image = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(image)
    draw.rectangle([0, 0, W, 4], fill=GREEN)

    draw.text((80, 78), _spaced("LAUNCH GUARD / STATIC SCAN"), font=_font("consola.ttf", 17), fill=GREEN)
    draw.text(
        (80, 124),
        f"{len(repos)} agent repos, {total_files:,} files",
        font=_font("segoeuib.ttf", 40),
        fill=FG,
    )
    draw.text(
        (80, 186),
        f"{len(flagged)} of {len(repos)} repos had at least one finding",
        font=_font("segoeui.ttf", 24),
        fill=MUTED,
    )

    stats = [
        (rule_counts.get("LEAK-01", 0), "hardcoded credentials"),
        (rule_counts.get("COST-01", 0) + rule_counts.get("COST-04", 0), "loops with no exit"),
        (rule_counts.get("COST-02", 0), "calls with no token cap"),
        (
            rule_counts.get("PERM-01", 0) + rule_counts.get("PERM-02", 0) + rule_counts.get("PERM-03", 0),
            "wildcard permissions",
        ),
    ]
    number_font = _font("consolab.ttf", 56)
    label_font = _font("segoeui.ttf", 18)
    grid = [(80, 244), (410, 244), (80, 344), (410, 344)]
    for (x, y), (number, label) in zip(grid, stats):
        draw.text((x, y), f"{number:,}", font=number_font, fill=FG)
        draw.text((x, y + 62), label, font=label_font, fill=MUTED)

    draw.line([80, 470, 1120, 470], fill=RULE, width=1)

    draw.text((700, 178), _spaced("FINDINGS"), font=_font("consola.ttf", 17), fill=MUTED)
    row_font = _font("consola.ttf", 19)
    count_font = _font("consola.ttf", 18)
    for idx, repo in enumerate(flagged[:6]):
        y = 220 + idx * 42
        slug = repo["slug"].replace("__", "/")
        if len(slug) > 26:
            slug = slug[:25] + "\u2026"
        draw.text((700, y), slug, font=row_font, fill=MUTED)
        grade = str(repo["grade"])
        draw.text((1110, y), grade, font=_font("consolab.ttf", 20), fill=GRADE_COLOR.get(grade, MUTED), anchor="ra")
        draw.text((1160, y), str(repo["blockers"] + repo["advisory"]), font=count_font, fill=DIM, anchor="ra")

    draw.text(
        (80, 506),
        f"scanned in {total_ms / 1000:.0f}s  -  nothing left the runner",
        font=_font("segoeui.ttf", 18),
        fill=DIM,
    )
    draw.text(
        (80, 548),
        "github.com/yepinggu66/agentproof-cloud",
        font=_font("consola.ttf", 20),
        fill=FG,
    )

    target = Path(out_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target, "PNG")
    print(f"wrote {target} ({target.stat().st_size:,} bytes)")


if __name__ == "__main__":
    args = sys.argv[1:]
    render(args[0] if args else "guard-out/index.json", args[1] if len(args) > 1 else "guard-out/card.png")
