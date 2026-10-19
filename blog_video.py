# -*- coding: utf-8 -*-
"""블로그 상품 글에 넣을 짧은 사진 슬라이드 영상 (가로 16:9 블로그용 + 세로 9:16 클립·쇼츠·릴스용).
장면: 표지(어두운 배경 + 노란 글씨 흰 테두리 + 빨간 밑줄) → 상품 사진 4~6장(천천히 확대 + 아래 자막 한 줄)
→ "자세한 내용은 본문에서" 카드. video_tools.py(쿠팡 릴스)와 같은 방식으로 프레임을 ffmpeg에 흘려 넣는다.
배경음악은 저장소 bgm/ 폴더에 저작권 없는 음악(mp3 등)을 넣어 두면 작게 깔린다. 없으면 무음."""
import pathlib
import random
import subprocess

from PIL import Image, ImageDraw, ImageFilter, ImageOps

import image_tools as it
from video_tools import _ffmpeg, AUDIO_EXT

FPS = 25
FADE = 0.4
COVER_SEC, PHOTO_SEC, END_SEC = 2.5, 3.5, 2.5
BGM_DIR = pathlib.Path(__file__).resolve().parent / "bgm"

BG = (11, 14, 29)            # 썸네일 배경 남색
PANEL = (45, 41, 33)         # 왼쪽 비스듬한 면
YELLOW = (255, 226, 122)
RED = (217, 65, 95)
HEAVY_FONTS = ["/usr/share/fonts/truetype/nanum/NanumGothicExtraBold.ttf", "/usr/share/fonts/truetype/nanum/NanumSquareB.ttf",
               "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
               r"C:\Windows\Fonts\malgunbd.ttf"]


def _heavy(size):
    for p in HEAVY_FONTS:
        if pathlib.Path(p).exists():
            from PIL import ImageFont
            return ImageFont.truetype(p, size)
    return it.font(size)


def _backdrop(w, h):
    """썸네일과 같은 바탕: 남색 + 왼쪽 비스듬한 면 + 흐린 원 두 개."""
    im = Image.new("RGB", (w, h), BG)
    d = ImageDraw.Draw(im)
    d.polygon([(0, 0), (int(w * 0.41), 0), (int(w * 0.29), h), (0, h)], fill=PANEL)
    r = int(min(w, h) * 0.37)
    d.ellipse((w - r * 1.6, -r * 0.9, w - r * 1.6 + r * 2, -r * 0.9 + r * 2), fill=(42, 24, 42))
    r2 = int(min(w, h) * 0.33)
    d.ellipse((-r2, h - r2 * 0.75, r2, h - r2 * 0.75 + r2 * 2), fill=(62, 58, 48))
    return im


def _fit_lines(d, text, fnt, max_w, max_lines=2):
    lines = it.wrap(d, text, fnt, max_w)
    return lines[:max_lines]


def _title_card(w, h, text, sub=""):
    """노란 글씨 + 흰 테두리 + 검은 그림자 + 빨간 밑줄 (보내 준 썸네일 모양)."""
    im = _backdrop(w, h)
    d = ImageDraw.Draw(im)
    size = int(min(w, h) * (0.15 if w > h else 0.12))
    while size > 40:
        fnt = _heavy(size)
        lines = _fit_lines(d, text, fnt, w * 0.86)
        if len(lines) <= 2 and all(d.textlength(x, font=fnt) <= w * 0.86 for x in lines):
            break
        size -= 6
    lh = int(size * 1.25)
    y0 = h // 2 - lh * len(lines) // 2
    for i, line in enumerate(lines):
        y = y0 + i * lh
        bar_y = y + int(size * 0.8)  # 글씨 아랫부분에 걸치는 밑줄 (썸네일처럼)
        d.rounded_rectangle((int(w * 0.05), bar_y, int(w * 0.95), bar_y + max(8, size // 6)), radius=size // 10, fill=RED)
        sw = max(6, size // 11)
        d.text((w // 2 + sw, y + sw), line, font=fnt, fill=(0, 0, 0), anchor="mt", stroke_width=sw, stroke_fill=(0, 0, 0))
        d.text((w // 2, y), line, font=fnt, fill=YELLOW, anchor="mt", stroke_width=sw, stroke_fill=(255, 255, 255))
    if sub:
        sf = it.font(int(size * 0.32))
        d.text((w // 2, y0 + lh * len(lines) + int(size * 0.35)), sub, font=sf, fill=(220, 224, 235), anchor="mt")
    return im


class Photo:
    """사진 장면: 흐린 같은 사진을 바탕에 깔고, 사진 전체가 보이게 가운데 놓고 천천히 확대·이동 + 아래 자막."""

    def __init__(self, w, h, photo, caption, k):
        self.w, self.h = w, h
        bg = ImageOps.fit(photo, (w, h), Image.LANCZOS).filter(ImageFilter.GaussianBlur(28))
        self.bg = Image.blend(bg, Image.new("RGB", (w, h), (0, 0, 0)), 0.45)
        box_h = int(h * (0.78 if w > h else 0.62))
        fg = ImageOps.contain(photo, (int(w * 0.9), box_h), Image.LANCZOS)
        self.fg = fg
        self.top = int(h * 0.06) if w > h else int(h * 0.12)
        self.zoom = (1.0, 1.08) if k % 2 == 0 else (1.08, 1.0)
        self.shift = (-1, 1)[k % 2] * int(w * 0.015)
        self.cap = self._caption(caption)

    def _caption(self, text):
        w, h = self.w, self.h
        ov = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        if not text:
            return ov
        d = ImageDraw.Draw(ov)
        size = int(min(w, h) * (0.065 if w > h else 0.06))
        fnt = it.font(size)
        tw = d.textlength(text, font=fnt)
        bh = int(size * 1.8)
        y = h - bh - int(h * (0.06 if w > h else 0.14))
        x0, x1 = int((w - tw) / 2 - size * 0.8), int((w + tw) / 2 + size * 0.8)
        d.rounded_rectangle((x0, y, x1, y + bh), radius=bh // 4, fill=(0, 0, 0, 175))
        d.text((w // 2, y + bh // 2), text, font=fnt, fill=YELLOW if text.startswith("✔") else (255, 255, 255), anchor="mm")
        return ov

    def render(self, p):
        frame = self.bg.copy()
        z = self.zoom[0] + (self.zoom[1] - self.zoom[0]) * p
        fw, fh = int(self.fg.width * z), int(self.fg.height * z)
        fg = self.fg.resize((fw, fh), Image.BILINEAR)
        x = (self.w - fw) // 2 + int(self.shift * (p - 0.5))
        y = self.top + (self.fg.height - fh) // 2
        frame.paste(fg, (x, y))
        frame.paste(self.cap, (0, 0), self.cap)
        return frame


class Still:
    def __init__(self, im):
        self.im = im

    def render(self, p):
        return self.im


def _bgm():
    files = [f for f in BGM_DIR.glob("*") if f.suffix.lower() in AUDIO_EXT] if BGM_DIR.is_dir() else []
    return str(random.choice(files)) if files else None


def make(out, title, photos, lines, w=1920, h=1080):
    """영상 하나를 out(mp4)에 만든다. photos: PIL 이미지(4~6장 씀), lines: 자막(사진마다 한 줄)."""
    shots = photos[:6]
    if len(shots) < 4:
        raise RuntimeError("영상에 쓸 상품 사진이 4장보다 적습니다.")
    caps = [x for x in lines if x][:len(shots)]
    scenes = [(COVER_SEC, Still(_title_card(w, h, title)))]
    for k, ph in enumerate(shots):
        scenes.append((PHOTO_SEC, Photo(w, h, ph, caps[k] if k < len(caps) else "", k)))
    scenes.append((END_SEC, Still(_title_card(w, h, "자세한 내용은 본문에서", "아래 글에서 구성·가격을 확인하세요"))))
    total = sum(s for s, _ in scenes)
    bgm = _bgm()
    cmd = [_ffmpeg(), "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}",
           "-r", str(FPS), "-i", "-"]
    cmd += ["-stream_loop", "-1", "-i", bgm] if bgm else ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]
    cmd += ["-map", "0:v", "-map", "1:a", "-t", f"{total:.2f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-ar", "44100"]
    if bgm:  # 작게 깔고 끝에서 줄임
        cmd += ["-af", f"volume=0.25,afade=t=out:st={max(0, total - 1.5):.2f}:d=1.5"]
    cmd += ["-movflags", "+faststart", str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    try:
        start, k, nxt = 0.0, 0, {}
        for f in range(int(round(total * FPS))):
            t = f / FPS
            while k < len(scenes) - 1 and t >= start + scenes[k][0]:
                start += scenes[k][0]
                k += 1
            dur, sc = scenes[k]
            frame = sc.render(min(1.0, (t - start) / dur))
            if k < len(scenes) - 1 and t - start > dur - FADE:  # 다음 장면과 겹쳐 넘어가기
                if k + 1 not in nxt:
                    nxt[k + 1] = scenes[k + 1][1].render(0)
                frame = Image.blend(frame, nxt[k + 1], (t - start - (dur - FADE)) / FADE)
            proc.stdin.write(frame.tobytes())
    finally:
        proc.stdin.close()
        proc.wait()
    if proc.returncode != 0 or not pathlib.Path(out).exists():
        raise RuntimeError("영상 만들기에 실패했습니다 (ffmpeg 오류).")
    return out
