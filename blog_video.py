# -*- coding: utf-8 -*-
"""블로그 상품 글에 넣을 짧은 사진 슬라이드 영상 (가로 16:9 블로그용 + 세로 9:16 클립·쇼츠·릴스용).
장면: 표지(상품 사진을 살린 4가지 디자인 × 6가지 색 중 무작위) → 상품 사진 4~6장(천천히 확대 + 아래 자막 한 줄)
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


CLASSIC_LOOKS = [  # 글씨 색(줄마다 번갈아), 테두리, 밑줄/띠 색, 띠 방식
    {"fill": [(255, 255, 255), (255, 214, 0)], "stroke": (0, 0, 0), "bar": (230, 30, 60), "box": False},
    {"fill": [(255, 214, 0)], "stroke": (0, 0, 0), "bar": (230, 30, 60), "box": False},
    {"fill": [(255, 255, 255)], "stroke": (0, 0, 0), "bar": (232, 36, 52), "box": True},
    {"fill": [(255, 255, 255), (120, 230, 255)], "stroke": (10, 20, 60), "bar": (0, 120, 255), "box": False},
]


def _title_card(w, h, text, sub="", look=None, bg=None):
    """굵은 글씨 + 검은 테두리·그림자 + 밑줄(또는 띠). look이 없으면 흰·노랑 번갈아 쓰는 기본."""
    look = look or CLASSIC_LOOKS[0]
    im = bg.copy() if bg is not None else _backdrop(w, h)
    d = ImageDraw.Draw(im)
    size = int(min(w, h) * (0.15 if w > h else 0.12))
    while size > 40:
        fnt = _heavy(size)
        lines = _fit_lines(d, text, fnt, w * 0.86, 9)
        if len(lines) <= (2 if w > h else 3) and all(d.textlength(x, font=fnt) <= w * 0.86 for x in lines):
            break
        size -= 6
    lh = int(size * (1.38 if look["box"] else 1.25))
    y0 = h // 2 - lh * len(lines) // 2
    sw = max(6, size // 10)
    for i, line in enumerate(lines):
        y = y0 + i * lh
        if look["box"]:  # 줄마다 빨간 띠 위에 흰 글씨
            tw = d.textlength(line, font=fnt)
            pad = size * 0.3
            d.rectangle((w / 2 - tw / 2 - pad, y - size * 0.12, w / 2 + tw / 2 + pad, y + size * 1.12), fill=look["bar"])
        else:
            bar_y = y + int(size * 0.8)  # 글씨 아랫부분에 걸치는 밑줄 (썸네일처럼)
            d.rounded_rectangle((int(w * 0.05), bar_y, int(w * 0.95), bar_y + max(8, size // 6)), radius=size // 10, fill=look["bar"])
        fill = look["fill"][i % len(look["fill"])]
        d.text((w // 2 + sw // 2 + 4, y + sw // 2 + 6), line, font=fnt, fill=(0, 0, 0), anchor="mt", stroke_width=sw, stroke_fill=(0, 0, 0))
        d.text((w // 2, y), line, font=fnt, fill=fill, anchor="mt", stroke_width=sw, stroke_fill=look["stroke"])
    if sub:
        sf = it.font(int(size * 0.32))
        d.text((w // 2, y0 + lh * len(lines) + int(size * 0.35)), sub, font=sf, fill=(220, 224, 235), anchor="mt")
    return im


PALETTES = [  # (바탕, 강조, 글씨, 작은 글씨)
    ((14, 17, 30), (255, 214, 92), (255, 255, 255), (205, 212, 230)),
    ((246, 241, 232), (232, 93, 63), (28, 28, 30), (95, 90, 84)),
    ((18, 52, 45), (126, 224, 170), (255, 255, 255), (196, 228, 214)),
    ((33, 30, 74), (255, 128, 171), (255, 255, 255), (214, 210, 244)),
    ((255, 255, 255), (37, 99, 235), (17, 24, 39), (90, 98, 112)),
    ((40, 24, 16), (255, 170, 72), (255, 248, 238), (230, 210, 190)),
]
STYLES = ("bleed", "split", "frame", "classic")
BADGES = ("오늘의 추천", "꼼꼼 정리", "구매 전 체크", "핵심만 쏙", "살펴보기")


def _fit_title(d, text, w_max, size, min_size, max_lines=3):
    """제목이 max_lines 줄 안에 들어가는 가장 큰 글씨 크기와 줄들."""
    while True:
        fnt = _heavy(size)
        lines = it.wrap(d, text, fnt, w_max)
        if len(lines) <= max_lines or size <= min_size:
            return fnt, size, lines[:max_lines]
        size -= 4


def _badge(d, x, y, text, size, fill, color):
    fnt = it.font(size)
    tw = d.textlength(text, font=fnt)
    pad = size * 0.7
    d.rounded_rectangle((x, y, x + tw + pad * 2, y + size * 1.8), radius=int(size * 0.9), fill=fill)
    d.text((x + pad, y + size * 0.9), text, font=fnt, fill=color, anchor="lm")
    return y + size * 1.8


def _shadow_paste(im, photo, box, radius):
    """둥근 모서리 사진 카드 + 은은한 그림자."""
    x, y = box
    pw, ph = photo.size
    sh = Image.new("RGBA", im.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle((x + 10, y + 18, x + pw + 10, y + ph + 18), radius=radius, fill=(0, 0, 0, 110))
    sh = sh.filter(ImageFilter.GaussianBlur(18))
    im.paste(sh, (0, 0), sh)
    mask = Image.new("L", photo.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, pw, ph), radius=radius, fill=255)
    im.paste(photo, (x, y), mask)


def _cover(w, h, title, photo=None, style=None, pal=None):
    """표지: 상품 사진을 살린 여러 디자인 중 하나 (영상마다 디자인·색이 바뀜). 사진이 없으면 예전 글씨 표지."""
    if photo is None:
        return _title_card(w, h, title)
    style = style or random.choice(STYLES)
    bg, acc, fg, sub = pal or random.choice(PALETTES)
    badge = random.choice(BADGES)
    wide = w > h
    u = min(w, h)
    if style == "classic":
        im = ImageOps.fit(photo, (w, h), Image.LANCZOS).filter(ImageFilter.GaussianBlur(24))
        im = Image.blend(im, Image.new("RGB", (w, h), (0, 0, 0)), 0.55)
        return _classic_on(im, w, h, title)
    if style == "bleed":  # 사진 꽉 채우고 아래를 어둡게, 큰 흰 글씨
        im = ImageOps.fit(photo, (w, h), Image.LANCZOS).convert("RGB")
        grad = Image.linear_gradient("L").resize((w, h))
        grad = grad.point(lambda v: int(max(0, v - 110) * 1.8))
        im.paste(Image.new("RGB", (w, h), (0, 0, 0)), (0, 0), grad.point(lambda v: min(235, v)))
        d = ImageDraw.Draw(im)
        m = int(u * 0.07)
        fnt, size, lines = _fit_title(d, title, w - m * 2, int(u * (0.12 if wide else 0.1)), int(u * 0.05))
        lh = int(size * 1.22)
        y = h - m - lh * len(lines) - (0 if wide else int(h * 0.08))
        _badge(d, m, y - int(u * 0.075) - int(size * 0.2), badge, int(u * 0.042), acc, bg if sum(bg) < 300 else (255, 255, 255))
        for i, ln in enumerate(lines):
            d.text((m, y + i * lh), ln, font=fnt, fill=(255, 255, 255), stroke_width=max(2, size // 30), stroke_fill=(0, 0, 0))
        d.rectangle((m, y + lh * len(lines) + int(size * 0.12), m + int(u * 0.12), y + lh * len(lines) + int(size * 0.12) + max(6, size // 12)), fill=acc)
        return im
    im = Image.new("RGB", (w, h), bg)
    d = ImageDraw.Draw(im)
    if style == "split":  # 한쪽은 색 면 + 글씨, 한쪽은 사진
        if wide:
            pw = int(w * 0.5)
            im.paste(ImageOps.fit(photo, (pw, h), Image.LANCZOS), (w - pw, 0))
            d.rectangle((w - pw - int(u * 0.015), 0, w - pw, h), fill=acc)
            box_w, x0, top, bottom = w - pw - int(u * 0.16), int(u * 0.08), 0, h
        else:
            ph = int(h * 0.5)
            im.paste(ImageOps.fit(photo, (w, ph), Image.LANCZOS), (0, 0))
            d.rectangle((0, ph, w, ph + int(u * 0.015)), fill=acc)
            box_w, x0, top, bottom = w - int(u * 0.16), int(u * 0.08), ph, h - int(h * 0.08)
        fnt, size, lines = _fit_title(d, title, box_w, int(u * 0.1), int(u * 0.045), 4)
        lh = int(size * 1.25)
        bsz = int(u * 0.042)
        block = bsz * 1.8 + u * 0.04 + lh * len(lines)
        y = top + (bottom - top - block) / 2
        y = _badge(d, x0, y, badge, bsz, acc, bg if sum(bg) < 300 else (255, 255, 255)) + u * 0.04
        for i, ln in enumerate(lines):
            d.text((x0, y + i * lh), ln, font=fnt, fill=fg, stroke_width=max(1, size // 45), stroke_fill=fg)
        return im
    # frame: 색 바탕에 사진 카드, 위아래로 제목
    m = int(u * 0.07)
    d.ellipse((w - u * 0.5, -u * 0.25, w + u * 0.2, u * 0.45), fill=tuple(int(a * 0.25 + b * 0.75) for a, b in zip(acc, bg)))
    if wide:
        card_w = int(w * 0.42)
        ph_im = ImageOps.contain(photo, (card_w, h - m * 2), Image.LANCZOS)
        _shadow_paste(im, ph_im, (w - m - ph_im.width, (h - ph_im.height) // 2), int(u * 0.03))
        box_w = w - m * 3 - ph_im.width
        fnt, size, lines = _fit_title(d, title, box_w, int(u * 0.1), int(u * 0.045), 4)
        lh = int(size * 1.25)
        y = (h - lh * len(lines)) / 2
        d.text((m, y - u * 0.09), badge, font=it.font(int(u * 0.046)), fill=acc)
        for i, ln in enumerate(lines):
            d.text((m, y + i * lh), ln, font=fnt, fill=fg, stroke_width=max(1, size // 45), stroke_fill=fg)
        d.rectangle((m, y + lh * len(lines) + u * 0.03, m + u * 0.1, y + lh * len(lines) + u * 0.03 + max(6, size // 12)), fill=acc)
    else:
        fnt, size, lines = _fit_title(d, title, w - m * 2, int(u * 0.1), int(u * 0.05), 3)
        lh = int(size * 1.25)
        y = int(h * 0.1)
        d.text((m, y), badge, font=it.font(int(u * 0.05)), fill=acc)
        y += int(u * 0.08)
        for i, ln in enumerate(lines):
            d.text((m, y + i * lh), ln, font=fnt, fill=fg, stroke_width=max(1, size // 45), stroke_fill=fg)
        top = y + lh * len(lines) + int(u * 0.06)
        ph_im = ImageOps.contain(photo, (w - m * 2, h - top - int(h * 0.1)), Image.LANCZOS)
        _shadow_paste(im, ph_im, ((w - ph_im.width) // 2, top), int(u * 0.03))
    return im


def _cover_photo(shots):
    """표지에 깔 사진: 앞쪽 사진 중 흰 바탕 로고·누끼보다 색과 명암이 풍부한 사진."""
    from PIL import ImageStat

    def score(im):
        st = ImageStat.Stat(im.convert("RGB").resize((96, 96)))
        bright = sum(st.mean) / 3
        return sum(st.stddev) / 3 - max(0, bright - 200) * 0.8
    return max(shots[:4], key=score)


def _classic_on(base, w, h, title):
    """굵은 글씨 표지(흰·노랑 글씨 + 검은 테두리 + 밑줄/띠)를 흐린 상품 사진 위에."""
    return _title_card(w, h, title, look=random.choice(CLASSIC_LOOKS), bg=base)


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


def _footer(w, h, text):
    """모든 장면 맨 아래에 작게 까는 한 줄 (쿠팡 릴스의 대가성 문구)."""
    size = max(22, int(min(w, h) * 0.026))
    fnt = it.font(size)
    bh = int(size * 1.9)
    ov = Image.new("RGBA", (w, bh), (0, 0, 0, 140))
    ImageDraw.Draw(ov).text((w // 2, bh // 2), text, font=fnt, fill=(235, 235, 235), anchor="mm")
    return ov


def make(out, title, photos, lines, w=1920, h=1080, end=("자세한 내용은 본문에서", "아래 글에서 구성·가격을 확인하세요"),
         footer="", cover=None, style=None, pal=None, cover_img=None):
    """영상 하나를 out(mp4)에 만든다. photos: PIL 이미지(4~6장 씀), lines: 자막(사진마다 한 줄).
    end: 마무리 카드 (제목, 작은 글), footer: 모든 장면 아래에 까는 한 줄 (비우면 없음).
    cover: 표지 사진 (없으면 자동으로 고름), style·pal: 표지 디자인·색 (없으면 무작위), cover_img: 다 만든 표지 화면(있으면 그대로 씀)."""
    shots = photos[:6]
    if len(shots) < 4:
        raise RuntimeError("영상에 쓸 상품 사진이 4장보다 적습니다.")
    caps = [x for x in lines if x][:len(shots)]
    if cover_img is None:
        cover_img = _cover(w, h, title, cover or _cover_photo(shots), style, pal)
    scenes = [(COVER_SEC, Still(ImageOps.fit(cover_img.convert("RGB"), (w, h))))]
    for k, ph in enumerate(shots):
        scenes.append((PHOTO_SEC, Photo(w, h, ph, caps[k] if k < len(caps) else "", k)))
    scenes.append((END_SEC, Still(_title_card(w, h, *end))))
    foot = _footer(w, h, footer) if footer else None
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
            if foot is not None:
                frame = frame.copy()
                frame.paste(foot, (0, h - foot.height), foot)
            proc.stdin.write(frame.tobytes())
    finally:
        proc.stdin.close()
        proc.wait()
    if proc.returncode != 0 or not pathlib.Path(out).exists():
        raise RuntimeError("영상 만들기에 실패했습니다 (ffmpeg 오류).")
    return out
