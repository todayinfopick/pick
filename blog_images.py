# -*- coding: utf-8 -*-
"""블로그 글에 넣을 이미지: 대표 이미지(사진+제목), 본문 사진, 핵심 정리 카드.
사진은 일반 글과 같은 Pixabay 키(PIXABAY_API_KEY)로 찾는다. 키가 없거나 못 찾으면 글자만 있는 이미지로 대신한다."""
import io
import random

import requests
from PIL import Image, ImageDraw

import image_tools
from image_tools import font, wrap, PALETTES
from main import env, log, check

W, H = 1200, 800
CARD_H = 900


def find_photo(query, used):
    """Pixabay에서 가로 사진 한 장 → (PIL 이미지, 사진 id). 없으면 (None, None)."""
    if not query or not env("PIXABAY_API_KEY"):
        return None, None
    r = requests.get("https://pixabay.com/api/", timeout=30,
                     params={"key": env("PIXABAY_API_KEY"), "q": query[:100], "image_type": "photo",
                             "orientation": "horizontal", "safesearch": "true", "min_width": 1200,
                             "per_page": 30})
    check(r, "Pixabay 사진 검색")
    hits = [(f"pixabay:{h['id']}", h["largeImageURL"]) for h in r.json().get("hits", [])]
    fresh = [h for h in hits if h[0] not in used]
    if not fresh and " " in query.strip():  # 검색어가 너무 좁으면 앞 단어만으로 한 번 더
        return find_photo(query.split()[0], used)
    if not fresh:
        return None, None
    pid, url = random.choice(fresh[:10])
    img = requests.get(url, timeout=60)
    img.raise_for_status()
    log(f"    사진 {pid} ({query})")
    return Image.open(io.BytesIO(img.content)).convert("RGB"), pid


def _gradient(w, h, start, alpha):
    """아래로 갈수록 어두워지는 검은 막 (글자가 잘 읽히게)."""
    g = Image.new("L", (1, h))
    for y in range(h):
        g.putpixel((0, y), 0 if y < start else int(alpha * (y - start) / max(1, h - start)))
    return Image.merge("RGBA", (Image.new("L", (w, h), 0),) * 3 + (g.resize((w, h)),))


def cover(path, title, label, photo=None):
    """대표 이미지: 사진 위에 제목. 사진이 없으면 단색 배경에 제목."""
    bg, accent, fg = random.choice(PALETTES)
    if photo is not None:
        img = image_tools.cover(photo, W, H).convert("RGBA")
        img.alpha_composite(_gradient(W, H, int(H * 0.25), 235))
        img = img.convert("RGB")
        fg = "#FFFFFF"
    else:
        img = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(img)
    f = font(66)
    lines = wrap(d, title, f, W - 140)[:3]
    y = H - 90 - len(lines) * 86
    if label:
        lf = font(30)
        lw = d.textlength(label, font=lf)
        d.rounded_rectangle((70, y - 78, 70 + lw + 48, y - 26), radius=26, fill=accent)
        d.text((94, y - 52), label, font=lf, fill="#111111" if photo is not None else bg, anchor="lm")
    for ln in lines:
        d.text((70, y), ln, font=f, fill=fg)
        y += 86
    img.save(path, quality=90)
    return path


def photo(path, im):
    image_tools.cover(im, W, H).save(path, quality=88)
    return path


def card(path, title, lines):
    """핵심 정리 카드: 제목 + 번호 붙은 줄 몇 개."""
    bg, accent, fg = random.choice(PALETTES)
    img = Image.new("RGB", (W, CARD_H), bg)
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, W, 18), fill=accent)
    tf, lf, nf = font(60), font(42), font(34)
    y = 90
    for ln in wrap(d, title, tf, W - 160)[:2]:
        d.text((80, y), ln, font=tf, fill=fg)
        y += 78
    d.rectangle((80, y + 14, 200, y + 22), fill=accent)
    y += 70
    lines = [s for s in lines if s][:5]
    gap = 110
    for i, text in enumerate(lines, 1):
        d.ellipse((80, y, 136, y + 56), fill=accent)
        d.text((108, y + 28), str(i), font=nf, fill=bg, anchor="mm")
        wl = wrap(d, text, lf, W - 260)[:2]
        for k, ln in enumerate(wl):
            d.text((168, y + 6 + k * 52), ln, font=lf, fill=fg)
        y += gap + (40 if len(wl) > 1 else 0)
    img = img.crop((0, 0, W, max(630, min(CARD_H, y + 40))))  # 줄이 적으면 아래 빈 곳을 잘라 냄
    img.save(path)
    return path
