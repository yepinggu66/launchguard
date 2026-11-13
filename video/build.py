"""Build the Launch Guard promo video: frames (PIL) + voiceover (edge-tts) + music (numpy).

    python video/build.py            # -> video/out/launchguard-promo.mp4

The timeline is driven by the real voiceover duration, so the visuals never drift
away from the narration when a line is reworded.
"""

from __future__ import annotations

import asyncio
import math
import subprocess
import sys
import tempfile
import wave
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

import edge_tts

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "video" / "out"
CACHE = ROOT / "video" / ".cache"

W, H, FPS = 1920, 1080, 30
M = 120  # safe margin

BG_TOP = (11, 14, 20)
BG_BOTTOM = (5, 7, 11)
FG = (230, 237, 243)
MUTED = (139, 148, 158)
DIM = (110, 118, 129)
LINE = (31, 38, 52)
PANEL = (12, 17, 26)
GREEN = (63, 185, 80)
GREEN_D = (46, 160, 67)
RED = (248, 81, 73)
AMBER = (210, 153, 34)
ORANGE = (219, 109, 40)
CODE_BG = (7, 10, 16)

FONTS = Path("C:/Windows/Fonts")
VOICE = "en-US-AndrewNeural"
SITE = "launchguard-production-e3a01252.up.railway.app"
REPO = "github.com/yepinggu66/launchguard"

_font_cache: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    key = (name, size)
    if key not in _font_cache:
        _font_cache[key] = ImageFont.truetype(str(FONTS / name), size)
    return _font_cache[key]


def sans(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return font("segoeuib.ttf" if bold else "segoeui.ttf", size)


def mono(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return font("consolab.ttf" if bold else "consola.ttf", size)


def ease_out(t: float) -> float:
    return 1 - (1 - max(0.0, min(1.0, t))) ** 3


def ease_in_out(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def clamp01(t: float) -> float:
    return max(0.0, min(1.0, t))


# ---------------------------------------------------------------- background


_bg_cache: Image.Image | None = None


def background() -> Image.Image:
    global _bg_cache
    if _bg_cache is not None:
        return _bg_cache.copy()

    img = Image.new("RGB", (W, H), BG_TOP)
    draw = ImageDraw.Draw(img)
    for y in range(H):
        t = y / (H - 1)
        draw.line([(0, y), (W, y)], fill=tuple(int(BG_TOP[i] * (1 - t) + BG_BOTTOM[i] * t) for i in range(3)))

    # a single soft green glow in the top-left, like a screen edge light
    glow = Image.new("RGB", (W, H), (0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse([-500, -700, 900, 420], fill=(12, 46, 24))
    glow = glow.filter(ImageFilter.GaussianBlur(220))
    img = Image.blend(img, Image.composite(glow, img, glow.convert("L").point(lambda v: min(255, v * 3))), 0.55)
    _bg_cache = img
    return img.copy()


from PIL import ImageFilter  # noqa: E402  (used by background())


# ---------------------------------------------------------------- chrome


def chrome(img: Image.Image, progress: float, draw: ImageDraw.ImageDraw) -> None:
    # top progress line
    draw.rectangle([0, 0, W, 4], fill=(18, 24, 33))
    draw.rectangle([0, 0, int(W * progress), 4], fill=GREEN)

    draw.rectangle([M, 62, M + 14, 76], fill=GREEN)
    label = "L A U N C H   G U A R D"
    draw.text((M + 28, 58), label, font=mono(19), fill=MUTED)

    draw.text((W - M, 60), "static scan · no upload", font=mono(17), fill=DIM, anchor="ra")


def watermark(draw: ImageDraw.ImageDraw, text: str = SITE) -> None:
    draw.text((M, H - 64), text, font=mono(19), fill=(70, 78, 90))


def scene_fade(img: Image.Image, dur: float, t: float) -> Image.Image:
    alpha = min(clamp01(t / 0.25), clamp01((dur - t) / 0.25))
    if alpha >= 0.999:
        return img
    black = Image.new("RGB", img.size, (0, 0, 0))
    return Image.blend(black, img, alpha)


def rounded(draw: ImageDraw.ImageDraw, box, radius: int, fill=None, outline=None, width: int = 1) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


# ---------------------------------------------------------------- scenes


@dataclass
class Scene:
    key: str
    vo: str
    min_dur: float
    draw: callable
    dur: float = 0.0


def _text_block(draw, xy, lines, font_obj, fill, spacing=1.25):
    x, y = xy
    line_h = int(font_obj.size * spacing)
    for i, line in enumerate(lines):
        draw.text((x, y + i * line_h), line, font=font_obj, fill=fill)
    return y + len(lines) * line_h


# --- scene 1: the six lines -------------------------------------------------

CODE = [
    [("def ", "kw"), ("stream_answer", "fn"), ("(prompt):", "fg")],
    [("    ", "fg"), ("while ", "kw"), ("True:", "const")],
    [("        try:", "kw")],
    [("            out = ", "fg"), ("client.chat.completions.create(", "call")],
    [('                model="gpt-4o-mini",', "fg")],
    [('                messages=[{"role": "user", "content": prompt}])', "fg")],
    [("            yield ", "kw"), ("out.choices[0].delta.content", "fg")],
    [("        except Exception:", "kw")],
    [("            continue", "kw")],
]

SYNTAX = {
    "kw": (255, 123, 114),
    "fn": (210, 168, 255),
    "const": ((121, 192, 255)),
    "call": (210, 168, 255),
    "fg": (201, 209, 217),
    "str": (165, 214, 255),
}


def draw_code_card(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int, typed: float) -> None:
    rounded(draw, [x, y, x + w, y + h], 18, fill=CODE_BG, outline=LINE, width=2)
    for i, cx in enumerate((0, 22, 44)):
        draw.ellipse([x + 24 + cx, y + 22, x + 34 + cx, y + 32], fill=(38, 45, 58))
    draw.line([(x, y + 52), (x + w, y + 52)], fill=LINE, width=1)

    line_h = 44
    top = y + 78
    # type by characters, preserving segment colours
    budget = int(typed)
    f = mono(27)
    for row, segments in enumerate(CODE):
        cy = top + row * line_h
        cx = x + 34
        for text, kind in segments:
            if budget <= 0:
                break
            piece = text[:budget]
            budget -= len(piece)
            draw.text((cx, cy), piece, font=f, fill=SYNTAX[kind])
            cx += draw.textlength(piece, font=f)
        if budget <= 0:
            break

    cursor_x = x + 34
    cursor_y = top
    remaining = int(typed)
    for row, segments in enumerate(CODE):
        line_len = sum(len(t) for t, _ in segments)
        if remaining <= line_len:
            partial = remaining
            cursor_x = x + 34
            for text, _ in segments:
                take = min(partial, len(text))
                cursor_x += draw.textlength(text[:take], font=f)
                partial -= take
                if partial <= 0:
                    break
            cursor_y = top + row * line_h
            break
        remaining -= line_len


def scene_hook(draw, t, dur, img):
    draw.text((M, 168), "STATIC SCAN FOR AI-WRITTEN CODE", font=mono(22), fill=GREEN)
    draw.text((M, 214), "The most expensive", font=sans(76, bold=True), fill=FG)
    draw.text((M, 302), "code you can ship.", font=sans(76, bold=True), fill=MUTED)

    typed = min(1.0, max(0.0, (t - 0.9) / 3.6)) * sum(len("".join(s for s, _ in row)) for row in CODE)
    draw_code_card(draw, M, 452, 1180, 470, typed)

    if t > 4.9:
        a = ease_out((t - 4.9) / 0.5)
        red = tuple(int(0 + (RED[i] - 0) * a) for i in range(3))
        # left rail on the offending lines
        draw.rectangle([M - 14, 452 + 78 + 44 - 6, M - 8, 452 + 78 + 44 + 40], fill=red)
        draw.text((M + 1210, 452 + 78 + 44 + 2), "no break", font=mono(24), fill=red)
        draw.rectangle([M - 14, 452 + 78 + 3 * 44 - 6, M - 8, 452 + 78 + 3 * 44 + 40], fill=red)
        draw.text((M + 1210, 452 + 78 + 3 * 44 + 2), "no max_tokens", font=mono(24), fill=red)


# --- scene 2: the invoice ---------------------------------------------------


def scene_bill(draw, t, dur, img):
    draw.text((M, 168), "ONE NIGHT · ONE LOOP", font=mono(22), fill=GREEN)
    draw.text((M, 208), "The invoice, in real time.", font=sans(64, bold=True), fill=FG)

    p = ease_in_out(clamp01((t - 0.4) / 2.4))
    value = 4183.44 * p
    text = f"${value:,.2f}"
    f = mono(168, bold=True)
    draw.text((M, 360), text, font=f, fill=FG)

    if t > 2.8:
        a = ease_out((t - 2.8) / 0.5)
        y = 620
        for i, label in enumerate(["no bug", "no CVE", "passes review", "billed anyway"]):
            x = M + i * 300
            colour = RED if label == "billed anyway" else MUTED
            draw.rounded_rectangle([x, y, x + 260, y + 58], radius=29,
                                   fill=None if label == "billed anyway" else PANEL,
                                   outline=colour, width=2)
            draw.text((x + 130, y + 29), label, font=sans(24), fill=colour, anchor="mm")

        draw.text((M, 760), "gpt-4o-mini  ·  default timeout  ·  2 retries  ·  no max_tokens",
                  font=mono(22), fill=DIM)

    bars = 26
    for i in range(bars):
        pct = clamp01((p - i / bars * 0.55)) if p > 0 else 0
        bh = 8 + int(120 * pct)
        x = M + 980 + i * 30
        colour = RED if i > bars * 0.55 else AMBER
        draw.rectangle([x, 520 - bh, x + 14, 520], fill=colour)
    draw.text((M + 980, 540), "token spend", font=mono(18), fill=DIM)


# --- scene 3: nobody checks the invoice -------------------------------------


def scene_gap(draw, t, dur, img):
    draw.text((M, 150), "WHY NOTHING CATCHES IT", font=mono(22), fill=GREEN)

    rows = [
        ("linters", "syntax"),
        ("dependency bots", "versions"),
        ("code review", "intent"),
        ("your invoice", "nobody"),
    ]
    for i, (left, right) in enumerate(rows):
        appear = clamp01((t - 0.35 * i) / 0.45)
        if appear <= 0:
            continue
        y = 260 + i * 150
        x_off = int((1 - ease_out(appear)) * 40)
        is_last = i == len(rows) - 1
        draw.text((M - x_off, y), left, font=mono(46), fill=FG if is_last else MUTED)
        draw.text((M + 700, y), "checks", font=mono(30), fill=DIM)
        draw.text((M + 900, y), right, font=mono(46), fill=RED if is_last else FG)
        draw.line([(M - 20, y + 74), (M + 1240, y + 74)], fill=LINE, width=1)


# --- scene 4: the three checks ----------------------------------------------

CHECKS = [
    ("LEAK", "CRITICAL", ("credential in a file", "that ships"), "public/config.js:12", RED),
    ("COST", "HIGH", ("model call in a loop", "with no exit"), "app/agent.py:88", ORANGE),
    ("PERM", "CRITICAL", ("approval switch", "turned off"), ".claude/settings.json:3", RED),
]


def scene_checks(draw, t, dur, img):
    draw.text((M, 140), "THREE CHECKS", font=mono(22), fill=GREEN)
    draw.text((M, 178), "Failure modes that only exist now.", font=sans(58, bold=True), fill=FG)

    card_w, card_h, gap = 520, 430, 40
    for i, (name, sev, desc, loc, colour) in enumerate(CHECKS):
        appear = clamp01((t - 0.5 - i * 0.55) / 0.5)
        if appear <= 0:
            continue
        x = M + i * (card_w + gap)
        y = 320 + int((1 - ease_out(appear)) * 40)
        layer = Image.new("RGBA", (card_w + 4, card_h + 4), (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        ld.rounded_rectangle([0, 0, card_w, card_h], radius=20,
                             fill=(14, 19, 28, 255), outline=LINE + (255,), width=2)
        ld.text((34, 34), name, font=mono(30, bold=True), fill=colour + (255,))
        ld.rounded_rectangle([34, 86, 34 + 158, 86 + 36], radius=18, outline=colour + (255,), width=1)
        ld.text((34 + 79, 86 + 18), sev, font=mono(18), fill=colour + (255,), anchor="mm")
        ld.text((34, 170), desc[0], font=sans(28), fill=FG + (255,))
        ld.text((34, 210), desc[1], font=sans(28), fill=FG + (255,))
        ld.line([(34, 300), (card_w - 34, 300)], fill=LINE + (255,), width=1)
        ld.text((34, 330), "\u2192", font=sans(24), fill=DIM + (255,))
        ld.text((84, 328), loc, font=mono(19), fill=(165, 180, 252, 255))
        layer.putalpha(layer.getchannel("A").point(lambda v: int(v * appear)))
        img.paste(layer, (x, y), layer)


# --- scene 5: the proof -----------------------------------------------------


def scene_proof(draw, t, dur, img):
    draw.text((M, 130), "ON REAL REPOSITORIES", font=mono(22), fill=GREEN)

    # browser mock
    bx, by, bw, bh = M, 210, 1130, 560
    rounded(draw, [bx, by, bx + bw, by + bh], 16, fill=(10, 13, 19), outline=LINE, width=2)
    rounded(draw, [bx, by, bx + bw, by + 48], 16, fill=(16, 21, 30))
    draw.rectangle([bx, by + 34, bx + bw, by + 48], fill=(16, 21, 30))
    for i, cx in enumerate((0, 22, 44)):
        draw.ellipse([bx + 20 + cx, by + 16, bx + 30 + cx, by + 26], fill=(40, 47, 60))
    draw.rounded_rectangle([bx + 96, by + 12, bx + bw - 24, by + 38], radius=8, fill=(9, 12, 18))
    draw.text((bx + 112, by + 17), SITE + "/r/mKyiFrT_MA", font=mono(17), fill=DIM)

    draw.rounded_rectangle([bx + 40, by + 86, bx + 172, by + 218], radius=14, fill=ORANGE)
    draw.text((bx + 106, by + 152), "C", font=mono(72, bold=True), fill=(4, 20, 10), anchor="mm")
    draw.text((bx + 200, by + 96), "risk 16/100", font=mono(30), fill=FG)
    draw.text((bx + 200, by + 142), "160 files · 1 blocking · 1 advisory", font=mono(19), fill=MUTED)

    findings = [
        ("high", "deploy/docker/c4ai-doc-context.md:340", "groq-key hardcoded in source code"),
        ("medium", "crawl4ai/cli.py:88", "model call with no output-token cap"),
    ]
    for i, (sev, loc, title) in enumerate(findings):
        y = by + 268 + i * 130
        colour = ORANGE if sev == "high" else AMBER
        draw.rounded_rectangle([bx + 40, y, bx + 40 + 96, y + 32], radius=16, outline=colour, width=1)
        draw.text((bx + 88, y + 16), sev, font=mono(16), fill=colour, anchor="mm")
        draw.text((bx + 40, y + 46), loc, font=mono(19), fill=(165, 180, 252))
        draw.text((bx + 40, y + 74), title, font=sans(20), fill=MUTED)

    # the line that lands
    if t > 6.2:
        a = ease_out((t - 6.2) / 0.6)
        x = 1290
        draw.text((x, 300), "The libraries", font=sans(44, bold=True), fill=MUTED)
        draw.text((x, 356), "are clean.", font=sans(44, bold=True), fill=MUTED)
        draw.text((x, 448), "The app layer", font=sans(44, bold=True), fill=FG)
        draw.text((x, 504), "is not.", font=sans(44, bold=True), fill=RED)

    stats = [("9", "repos"), ("10,872", "files"), ("1", "credential"), ("18", "uncapped calls")]
    for i, (num, label) in enumerate(stats):
        x = M + i * 270
        draw.text((x, 830), num, font=mono(46, bold=True), fill=FG)
        draw.text((x, 894), label, font=mono(20), fill=DIM)


# --- scene 6: call to action ------------------------------------------------


def scene_cta(draw, t, dur, img):
    draw.text((M, 150), "SCAN YOUR REPO", font=mono(22), fill=GREEN)
    draw.text((M, 190), "Twenty seconds.", font=sans(84, bold=True), fill=FG)
    draw.text((M, 292), "Free for public repos.", font=sans(84, bold=True), fill=MUTED)

    bw, bh = 1090, 96
    rounded(draw, [M, 470, M + bw, 470 + bh], 14, fill=(15, 22, 33), outline=GREEN, width=2)
    draw.text((M + 34, 470 + bh // 2), SITE, font=mono(34), fill=FG, anchor="lm")

    if t > 0.8:  # the thing being advertised is actually running
        dot_x = M + bw - 96
        draw.ellipse([dot_x, 470 + bh // 2 - 16, dot_x + 12, 470 + bh // 2 - 4], fill=GREEN)
        draw.text((dot_x + 20, 470 + bh // 2), "live", font=mono(22), fill=GREEN, anchor="lm")

    rounded(draw, [M, 600, M + 360, 600 + 72], 12, fill=GREEN_D)
    draw.text((M + 180, 600 + 36), "$29 human audit", font=sans(30, bold=True), fill=(4, 20, 10), anchor="mm")
    draw.text((M + 400, 636), REPO, font=mono(26), fill=MUTED, anchor="lm")
    draw.text((M, 706), "Card or PayPal  ·  human review  ·  fix PR within 24h", font=sans(26), fill=FG)
    draw.text((M, 744), "Free scanning for public repos  ·  no signup", font=sans(24), fill=DIM)

    draw.text((M, 800), "Static analysis. Nothing leaves your runner. No telemetry.",
              font=sans(28), fill=DIM)


SCENES = [
    Scene("hook", "This is the most expensive six lines of Python you can write today.", 7.0, scene_hook),
    Scene("bill", "No bug. No CVE. It passes code review, and it runs until someone notices the invoice.", 6.4, scene_bill),
    Scene("gap", "Linters check syntax. Dependency scanners check versions. Reviewers check intent. Nobody checks the invoice.", 7.2, scene_gap),
    Scene("checks", "So I wrote three checks for the failure modes that only exist once AI writes the code: credentials that end up readable, model calls in loops with no exit, and permission prompts that got switched off.", 12.0, scene_checks),
    Scene("proof", "It runs on any public repository in about twenty seconds. I scanned nine popular agent repositories, ten thousand files, and found one live credential and eighteen uncapped model calls. The libraries are clean. The app layer is not.", 15.0, scene_proof),
    Scene("cta", "Scan any repo for free. Or twenty nine dollars for a human to confirm every finding and send a fix PR.", 8.0, scene_cta),
]


# ---------------------------------------------------------------- audio


def synthesize(scenes: list[Scene]) -> float:
    """Render one mp3 per scene, then assemble a single 48k mono VO wav."""
    CACHE.mkdir(parents=True, exist_ok=True)

    async def _one(index: int, text: str) -> Path:
        target = CACHE / f"vo-{index}.mp3"
        if target.exists() and target.stat().st_size > 4000:
            return target
        # Same voice for every scene, or the video changes narrator halfway. If
        # the endpoint keeps refusing, fail loudly instead of silently swapping.
        for attempt in range(4):
            try:
                communicate = edge_tts.Communicate(text, VOICE, rate="+4%")
                audio = b""
                async for chunk in communicate.stream():
                    if chunk["type"] == "audio":
                        audio += chunk["data"]
                if len(audio) > 4000:
                    target.write_bytes(audio)
                    return target
                print(f"scene {index}: empty audio, retrying", file=sys.stderr)
            except Exception as error:  # noqa: BLE001 - the endpoint is flaky
                print(f"scene {index} attempt {attempt + 1}: {error}", file=sys.stderr)
            await asyncio.sleep(2.0 * (attempt + 1))
        raise SystemExit(f"could not synthesize scene {index} with {VOICE}")

    async def _all() -> None:
        for i, scene in enumerate(scenes):
            await _one(i, scene.vo)

    asyncio.run(_all())

    for i, scene in enumerate(scenes):
        mp3 = CACHE / f"vo-{i}.mp3"
        wav = CACHE / f"vo-{i}.wav"
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp3), "-ar", "48000", "-ac", "1", str(wav)],
            check=True,
        )
        with wave.open(str(wav)) as handle:
            seconds = handle.getnframes() / handle.getframerate()
        scene.dur = max(scene.min_dur, seconds + 0.75)
    return sum(s.dur for s in scenes)


def read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path)) as handle:
        frames = handle.readframes(handle.getnframes())
        data = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    return data


def build_audio(scenes: list[Scene], total: float) -> Path:
    sr = 48000
    n = int(total * sr) + sr // 2
    voice = np.zeros(n, dtype=np.float32)

    cursor = 0.0
    starts: list[float] = []
    for i, scene in enumerate(scenes):
        starts.append(cursor)
        clip = read_wav(CACHE / f"vo-{i}.wav")
        # 30ms fade in/out so concatenation never clicks
        fade = int(0.03 * sr)
        if len(clip) > 2 * fade:
            clip[:fade] *= np.linspace(0, 1, fade)
            clip[-fade:] *= np.linspace(1, 0, fade)
        at = int((cursor + 0.18) * sr)
        end = min(n, at + len(clip))
        voice[at:end] += clip[: end - at]
        cursor += scene.dur

    t = np.arange(n) / sr

    # --- music: two detuned pads + gentle pulse, deliberately quiet
    def pad(freq: float, level: float, detune: float = 0.6) -> np.ndarray:
        return (
            np.sin(2 * math.pi * freq * t)
            + np.sin(2 * math.pi * (freq + detune) * t)
        ) * level

    music = pad(55.0, 0.10) + pad(82.5, 0.06) + pad(110.0, 0.035)
    music *= 0.55 + 0.45 * np.sin(2 * math.pi * 0.09 * t)
    music *= np.clip((t - 0.2) / 1.2, 0, 1)  # fade in

    # --- sfx
    def tick(at: float, freq: float = 1180.0, level: float = 0.16, decay: float = 0.06) -> None:
        length = int(0.18 * sr)
        start = int(at * sr)
        if start + length >= n:
            return
        local = np.arange(length) / sr
        env = np.exp(-local / decay)
        music_sfx[start:start + length] += (
            np.sin(2 * math.pi * freq * local) * env * level
        ).astype(np.float32)

    def thud(at: float, level: float = 0.45) -> None:
        length = int(0.5 * sr)
        start = int(at * sr)
        if start + length >= n:
            return
        local = np.arange(length) / sr
        env = np.exp(-local / 0.12)
        music_sfx[start:start + length] += (
            np.sin(2 * math.pi * 58 * local) * env * level
        ).astype(np.float32)

    music_sfx = np.zeros(n, dtype=np.float32)
    for i, start in enumerate(starts):
        tick(start + 0.05, 900.0, 0.05, 0.05)
    # the invoice lands, the check cards appear
    bill_start = starts[1]
    thud(bill_start + 2.75)
    checks_start = starts[3]
    for k in range(3):
        tick(checks_start + 0.5 + k * 0.55, 1320.0, 0.10, 0.045)

    mix = voice * 1.0 + music * 0.9 + music_sfx
    # duck the music slightly under the voice
    envelope = np.abs(voice)
    kernel = np.ones(4800, dtype=np.float32) / 4800
    envelope = np.convolve(envelope, kernel, mode="same")
    mix = voice + (music + music_sfx) * (1.0 - 0.5 * np.clip(envelope * 4, 0, 1))

    peak = float(np.max(np.abs(mix))) or 1.0
    mix = mix / peak * 0.92

    target = CACHE / "mix.wav"
    with wave.open(str(target), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sr)
        handle.writeframes((mix * 32767).astype(np.int16).tobytes())
    return target


# ---------------------------------------------------------------- render


def render(scenes: list[Scene], audio: Path, total: float, out: Path) -> None:
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
        "-i", str(audio),
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        "-c:a", "aac", "-b:a", "192k", "-shortest",
        str(out),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    cursor = 0.0
    frame_count = 0
    for index, scene in enumerate(scenes):
        frames = int(round(scene.dur * FPS))
        for f in range(frames):
            t = f / FPS
            img = background()
            draw = ImageDraw.Draw(img)
            progress = clamp01((cursor + t) / total)
            chrome(img, progress, draw)
            watermark(draw, SITE if scene.key != "cta" else "")
            scene.draw(draw, t, scene.dur, img)
            img = scene_fade(img, scene.dur, t)
            proc.stdin.write(img.tobytes())
            frame_count += 1
        cursor += scene.dur

    proc.stdin.close()
    stderr = proc.stderr.read().decode("utf-8", "replace")
    code = proc.wait()
    if code != 0:
        print(stderr[-2000:], file=sys.stderr)
        raise SystemExit(f"ffmpeg failed with {code}")
    print(f"rendered {frame_count} frames, {total:.1f}s -> {out}")


def stills() -> None:
    """Render one representative frame per scene so layout can be checked fast."""
    OUT.mkdir(parents=True, exist_ok=True)
    for scene in SCENES:
        t = scene.min_dur * 0.62
        img = background()
        draw = ImageDraw.Draw(img)
        chrome(img, 0.4, draw)
        watermark(draw, SITE if scene.key != "cta" else "")
        scene.draw(draw, t, scene.min_dur, img)
        path = OUT / f"still-{scene.key}.png"
        img.save(path)
        print("wrote", path)


def main() -> None:
    if "--stills" in sys.argv:
        stills()
        return
    OUT.mkdir(parents=True, exist_ok=True)
    total = synthesize(SCENES)
    print(f"timeline: {total:.1f}s across {len(SCENES)} scenes")
    for scene in SCENES:
        print(f"  {scene.key:<8} {scene.dur:5.2f}s")
    audio = build_audio(SCENES, total)
    out = OUT / "launchguard-promo.mp4"
    render(SCENES, audio, total, out)


if __name__ == "__main__":
    main()
