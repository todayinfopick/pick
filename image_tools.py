# -*- coding: utf-8 -*-
"""카드 이미지 자동 생성 + 이미지/영상을 공개 주소로 업로드.
인스타그램·쓰레드 API는 '인터넷에서 열리는 주소'만 받기 때문에 업로드가 필요하다.
  - CLOUDINARY_URL 이 있으면 Cloudinary (이미지·영상 모두)
  - 없으면 IMGBB_API_KEY 로 imgbb (이미지만)"""
import base64
import hashlib
import io
import os
import pathlib
import random
import re
import time
import urllib.parse

import requests
from PIL import Image, ImageDraw, ImageFont, ImageOps

BASE = pathlib.Path(__file__).resolve().parent
OUT_DIR = BASE / "media"

FONT_CANDIDATES = [
    r"C:\Windows\Fonts\malgunbd.ttf",
    r"C:\Windows\Fonts\malgun.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
]

PALETTES = [  # (배경, 강조색, 글자색)
    ("#1F2A44", "#FFB703", "#FFFFFF"),
    ("#F4EDE4", "#E76F51", "#2B2B2B"),
    ("#0B3D2E", "#9BE564", "#FFFFFF"),
    ("#2D1E4F", "#FF7AB6", "#FFFFFF"),
    ("#FFF7D6", "#1D4ED8", "#1F2937"),
    ("#141414", "#FF5A36", "#FFFFFF"),
    ("#E8F1FF", "#2563EB", "#0F172A"),
    ("#FDECEF", "#D6336C", "#3A1D2B"),
]

PHOTO_LAYOUTS = ["split", "full", "frame"]
TEXT_LAYOUTS = ["left", "center"]


def random_palette():
    return random.choice(PALETTES)

LABEL = "오늘의 추천템"
CTA = "구매 링크는 게시물·프로필 링크에서"
DISCLOSURE_SHORT = "쿠팡 파트너스 활동의 일환으로 수수료를 제공받습니다"


# ---------------------------------------------------------------- 공통 도구
def font(size):
    custom = (os.getenv("FONT_PATH") or "").strip()
    for path in ([custom] if custom else []) + FONT_CANDIDATES:
        if path and os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


def palette(name):
    return PALETTES[sum(map(ord, name)) % len(PALETTES)]


def wrap(draw, text, fnt, max_width):
    """띄어쓰기 단위로 줄바꿈하고, 한 단어가 너무 길 때만 글자 단위로 자른다."""
    lines, line = [], ""
    for word in str(text).split():
        trial = f"{line} {word}" if line else word
        if draw.textlength(trial, font=fnt) <= max_width:
            line = trial
            continue
        if line:
            lines.append(line)
        line = ""
        for ch in word:
            if draw.textlength(line + ch, font=fnt) <= max_width:
                line += ch
            else:
                lines.append(line)
                line = ch
    if line:
        lines.append(line)
    return lines


def text_block(draw, x, y, text, fnt, fill, max_width, line_h, max_lines, center_w=None):
    """여러 줄 글자를 그리고 다음 y 좌표를 돌려준다. center_w를 주면 가운데 정렬."""
    for ln in wrap(draw, text, fnt, max_width)[:max_lines]:
        if center_w:
            draw.text((center_w // 2, y), ln, font=fnt, fill=fill, anchor="ma")
        else:
            draw.text((x, y), ln, font=fnt, fill=fill)
        y += line_h
    return y


def pill(draw, x, y, text, fnt, bg, fg, pad_x=28, h=72):
    w = draw.textlength(text, font=fnt)
    draw.rounded_rectangle((x, y, x + w + pad_x * 2, y + h), radius=h // 2, fill=bg)
    draw.text((x + pad_x, y + h // 2), text, font=fnt, fill=fg, anchor="lm")


def cover(im, w, h):
    return ImageOps.fit(im, (w, h), Image.LANCZOS)


def slug(text):
    s = "".join(c for c in text if c.isalnum())[:40]
    return s or "item"


def resolve_path(src):
    p = pathlib.Path(src.strip().strip('"'))
    p = p if p.is_absolute() else BASE / p
    if not p.exists():
        # 윈도우는 확장자를 숨기는 경우가 많아, 빠졌으면 흔한 확장자를 붙여서 찾아본다
        for ext in (".png", ".jpg", ".jpeg", ".webp", ".mp4", ".mov", ".PNG", ".JPG"):
            cand = p.with_name(p.name + ext)
            if cand.exists():
                return cand
    return p


_SIZE_RE = re.compile(r"/(\d{2,4})x(\d{2,4})ex/")


def bigger_versions(url):
    """쿠팡 썸네일 주소(.../212x212ex/...)면 더 큰 크기 주소부터 차례로 돌려준다."""
    if "coupangcdn.com" in url and _SIZE_RE.search(url):
        for size in ("1000x1000ex", "700x700ex", "492x492ex"):
            yield _SIZE_RE.sub(f"/{size}/", url, count=1)
    yield url


def load_photo(src):
    """인터넷 주소 또는 내 PC 경로의 사진을 불러온다. 실패하면 None."""
    try:
        if src.startswith("http"):
            last_err = None
            for url in bigger_versions(src):
                try:
                    r = requests.get(url, timeout=60, headers={"User-Agent": "Mozilla/5.0"})
                    r.raise_for_status()
                    im = Image.open(io.BytesIO(r.content))
                    break
                except Exception as e:
                    last_err = e
            else:
                raise last_err
        else:
            im = Image.open(resolve_path(src))
        return ImageOps.exif_transpose(im).convert("RGB")
    except Exception as e:
        print(f"  (소재 사진을 불러오지 못해 건너뜀: {src} → {e})")
        return None


PHOTO_EXT = {".jpg", ".jpeg", ".png", ".webp"}


def photo_root():
    """상품별 사진 폴더들이 들어 있는 상위 폴더 (기본: 프로그램 폴더 안의 '사진')."""
    custom = (os.getenv("PHOTO_DIR") or "").strip().strip('"')
    return pathlib.Path(custom) if custom else BASE / "사진"


def folder_name(name):
    """상품명을 윈도우 폴더 이름으로 쓸 수 있게 정리 (쉼표 뒤 옵션 제거, 금지 문자 제거)."""
    short = name.split(",")[0].strip() or name
    bad = '\\/:*?"<>|'
    return "".join(c for c in short if c not in bad).strip().rstrip(".")[:80] or "상품"


def images_in(folder):
    return sorted((f for f in folder.iterdir() if f.suffix.lower() in PHOTO_EXT),
                  key=lambda f: f.name.lower())


MAX_PHOTOS = 10  # 인스타 캐러셀 최대 장수


def _fingerprint(im):
    """사진이 같은지 비교하기 위한 작은 컬러 축소판 (다시 캡처해 몇 픽셀 달라도 같게 봄)."""
    g = ImageOps.exif_transpose(im).convert("RGB").resize((16, 16))
    return [v for px in g.getdata() for v in px], im.size[0] / max(im.size[1], 1)


def same_photo(a, b):
    """두 사진이 사실상 같은 사진인지 (fingerprint끼리 비교)."""
    (pa, ra), (pb, rb) = a, b
    if abs(ra - rb) > 0.05 * max(ra, rb):
        return False
    return sum(abs(x - y) for x, y in zip(pa, pb)) / len(pa) < 6


def is_duplicate(im, others):
    fp = _fingerprint(im)
    return any(same_photo(fp, _fingerprint(o)) for o in others)


def unique_photos(images):
    """같은 사진이 여러 번 들어 있으면 처음 것만 남긴다."""
    keep, fps = [], []
    for im in images:
        fp = _fingerprint(im)
        if any(same_photo(fp, f) for f in fps):
            continue
        keep.append(im)
        fps.append(fp)
    return keep


def dedupe_folder(folder):
    """폴더 안의 중복 사진을 '사진\\_중복사진\\폴더이름'으로 옮기고 01, 02...로 번호를 다시 붙인다.
    옮긴 장수를 돌려준다."""
    files = images_in(folder)
    keep, fps, dup = [], [], []
    for f in files:
        try:
            with Image.open(f) as im:
                fp = _fingerprint(im)
        except Exception:
            keep.append(f)
            continue
        if any(same_photo(fp, x) for x in fps):
            dup.append(f)
        else:
            keep.append(f)
            fps.append(fp)
    if not dup:
        return 0
    trash = photo_root() / "_중복사진" / folder.name
    trash.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d%H%M%S")
    for f in dup:
        f.rename(trash / f"{stamp}_{f.name}")
    # 번호 다시 붙이기 (이름 충돌을 피하려고 임시 이름을 거친다)
    tmp = [f.rename(f.with_name(f"__tmp{i:03d}{f.suffix.lower()}")) for i, f in enumerate(keep)]
    for i, f in enumerate(tmp, start=1):
        f.rename(f.with_name(f"{i:02d}{f.suffix}"))
    return len(dup)


def dedupe_all_folders():
    """사진 폴더 전체에서 중복 사진 정리. (정리한 폴더 수, 옮긴 사진 수)"""
    root = photo_root()
    if not root.is_dir():
        return 0, 0
    folders = moved = 0
    for d in root.iterdir():
        if d.is_dir() and not d.name.startswith("_"):
            try:
                n = dedupe_folder(d)
            except OSError:
                continue
            if n:
                folders += 1
                moved += n
    return folders, moved


def load_photos(field, name=None):
    """소재 사진 목록을 불러온다.
    - 칸에 '주소1 | 경로2'처럼 적으면 그 사진들
    - 칸에 폴더 경로를 적으면 그 폴더 안의 사진 전부
    - 칸이 비었으면 '사진\\상품명' 폴더 안의 사진 전부 (폴더가 있을 때)"""
    sources = [s.strip() for s in (field or "").split("|") if s.strip()]
    if not sources and name:
        auto = photo_root() / folder_name(name)
        if auto.is_dir():
            sources = [str(f) for f in images_in(auto)]
            if sources:
                print(f"  (사진 폴더에서 {len(sources)}장 사용: {auto})")
    photos = []
    for src in sources:
        if not src.startswith("http"):
            p = resolve_path(src)
            if p.is_dir():
                for f in images_in(p):
                    im = load_photo(str(f))
                    if im is not None:
                        photos.append(im)
                continue
        im = load_photo(src)
        if im is not None:
            photos.append(im)
    before = len(photos)
    photos = unique_photos(photos)
    if len(photos) < before:
        print(f"  (같은 사진 {before - len(photos)}장은 한 번만 사용)")
    if len(photos) > MAX_PHOTOS:
        print(f"  (사진이 {len(photos)}장이라 앞의 {MAX_PHOTOS}장만 사용)")
        photos = photos[:MAX_PHOTOS]
    return photos


# ---------------------------------------------------------------- 카드 이미지
CW, CH, PAD = 1080, 1350, 88  # 인스타 4:5


def _gradient(w, h, y0, y1, max_alpha):
    """y0부터 y1까지 점점 진해지는 검은 그라데이션 레이어."""
    col = Image.new("L", (1, h), 0)
    for y in range(h):
        if y >= y1:
            a = max_alpha
        elif y > y0:
            a = int(max_alpha * (y - y0) / (y1 - y0))
        else:
            a = 0
        col.putpixel((0, y), a)
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 255))
    layer.putalpha(col.resize((w, h)))
    return layer


def _rounded_paste(img, photo, box, radius=40):
    x0, y0, x1, y1 = box
    ph = cover(photo, x1 - x0, y1 - y0)
    mask = Image.new("L", ph.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, ph.size[0], ph.size[1]), radius=radius, fill=255)
    img.paste(ph, (x0, y0), mask)


def _footer(d, accent, fg):
    d.text((PAD, CH - 150), CTA, font=font(38), fill=accent)
    d.text((PAD, CH - 82), DISCLOSURE_SHORT, font=font(26), fill=fg)


def _env_int(key, default):
    try:
        return int((os.getenv(key) or "").strip() or default)
    except ValueError:
        return default


def add_ad_tag(img):
    """오른쪽 위 [광고] 표시 (카드 1080×1350 기준). .env의 CARD_AD_* 로 조정."""
    tag = (os.getenv("CARD_AD_TAG") or "").strip() or "[광고]"
    size = _env_int("CARD_AD_SIZE", 34)
    right, top = CW - _env_int("CARD_AD_RIGHT", 50), _env_int("CARD_AD_TOP", 50)
    d = ImageDraw.Draw(img, "RGBA")
    fnt = font(size)
    w = d.textlength(tag, font=fnt)
    h, px = int(size * 1.6), int(size * 0.5)
    d.rounded_rectangle((right - w - px * 2, top, right, top + h), radius=max(6, size // 3),
                        fill=(0, 0, 0, 150))
    d.text((right - px, top + h // 2), tag, font=fnt, fill="#FFFFFF", anchor="rm")
    return img


def pick_layout(photo):
    return random.choice(PHOTO_LAYOUTS if photo is not None else TEXT_LAYOUTS)


def render_cover(name, headline, photo, layout, pal, footer=True):
    """표지(단일 이미지 게시물이면 이것 하나)."""
    bg, accent, fg = pal
    img = Image.new("RGB", (CW, CH), bg)
    d = ImageDraw.Draw(img)
    W = CW - PAD * 2
    foot_fg, foot_accent = fg, accent

    if photo is None and layout == "center":
        d.rectangle((0, 0, CW, 24), fill=accent)
        lw = d.textlength(LABEL, font=font(40)) + 56
        pill(d, int((CW - lw) // 2), 230, LABEL, font(40), accent, bg)
        y = text_block(d, 0, 420, headline, font(92), fg, W, 122, 4, center_w=CW)
        y += 30
        d.rectangle((CW // 2 - 60, y, CW // 2 + 60, y + 10), fill=accent)
        text_block(d, 0, y + 50, name, font(48), fg, W, 66, 2, center_w=CW)
    elif photo is None:  # left
        pill(d, PAD, 110, LABEL, font(40), accent, bg)
        y = text_block(d, PAD, 300, headline, font(84), fg, W, 112, 4)
        y += 40
        d.rectangle((PAD, y, PAD + 120, y + 10), fill=accent)
        text_block(d, PAD, y + 60, name, font(50), fg, W, 70, 3)
    elif layout == "full":
        img.paste(cover(photo, CW, CH), (0, 0))
        img.paste(_gradient(CW, CH, 420, 1050, 225), (0, 0), _gradient(CW, CH, 420, 1050, 225))
        d = ImageDraw.Draw(img)
        pill(d, PAD, 70, LABEL, font(38), accent, bg)
        y = text_block(d, PAD, 760, headline, font(80), "#FFFFFF", W, 104, 2)
        text_block(d, PAD, y + 16, name, font(42), "#FFFFFF", W, 58, 1)
        foot_fg = "#FFFFFF"
    elif layout == "frame":
        pill(d, PAD, 70, LABEL, font(36), accent, bg)
        y = text_block(d, PAD, 170, headline, font(68), fg, W, 88, 2)
        top = max(y + 20, 360)
        _rounded_paste(img, photo, (PAD, top, CW - PAD, 1060))
        text_block(d, PAD, 1085, name, font(40), fg, W, 54, 1)
    else:  # split
        img.paste(cover(photo, CW, 780), (0, 0))
        pill(d, PAD, 60, LABEL, font(38), accent, bg)
        y = text_block(d, PAD, 836, headline, font(70), fg, W, 92, 2)
        text_block(d, PAD, y + 18, name, font(42), fg, W, 58, 2)

    d = ImageDraw.Draw(img)
    if footer:
        _footer(d, foot_accent, foot_fg)
    else:  # 캐러셀 표지: 광고 표시만
        d.text((PAD, CH - 82), "광고 · " + DISCLOSURE_SHORT, font=font(26), fill=foot_fg)
    return img


def render_point(i, total, text, photo, layout, pal):
    """장점 슬라이드."""
    bg, accent, fg = pal
    img = Image.new("RGB", (CW, CH), bg)
    W = CW - PAD * 2
    if photo is not None and layout == "full":
        img.paste(cover(photo, CW, CH), (0, 0))
        g = _gradient(CW, CH, 600, 1150, 230)
        img.paste(g, (0, 0), g)
        d = ImageDraw.Draw(img)
        d.text((PAD, 860), f"{i:02d}", font=font(120), fill=accent)
        text_block(d, PAD, 1010, text, font(72), "#FFFFFF", W, 94, 2)
    elif photo is not None:
        if layout == "frame":
            _rounded_paste(img, photo, (PAD, PAD, CW - PAD, 860), radius=36)
        else:
            img.paste(cover(photo, CW, 860), (0, 0))
        d = ImageDraw.Draw(img)
        d.text((PAD, 900), f"{i:02d}", font=font(110), fill=accent)
        text_block(d, PAD, 1040, text, font(70), fg, W, 92, 2)
    else:
        d = ImageDraw.Draw(img)
        d.text((PAD, 360), f"{i:02d}", font=font(220), fill=accent)
        text_block(d, PAD, 640, text, font(96), fg, W, 126, 3)
    d = ImageDraw.Draw(img)
    d.text((CW - PAD, CH - 70), f"{i + 1} / {total}", font=font(30),
           fill="#FFFFFF" if (photo is not None and layout == "full") else fg, anchor="rs")
    return img


def render_cta(name, photo, pal):
    """마지막 구매 안내 슬라이드."""
    bg, accent, fg = pal
    img = Image.new("RGB", (CW, CH), bg)
    txt = fg
    if photo is not None:
        img.paste(cover(photo, CW, CH), (0, 0))
        img.paste(Image.new("RGB", (CW, CH), "#000000"), (0, 0), Image.new("L", (CW, CH), 170))
        txt = "#FFFFFF"
    d = ImageDraw.Draw(img)
    y = text_block(d, 0, 420, name, font(70), txt, CW - 180, 92, 3, center_w=CW)
    y += 60
    bw = 760
    d.rounded_rectangle(((CW - bw) // 2, y, (CW + bw) // 2, y + 120), radius=60, fill=accent)
    d.text((CW // 2, y + 60), "구매 링크 확인하기", font=font(52), fill=bg, anchor="mm")
    text_block(d, 0, y + 180, CTA, font(42), txt, CW - 180, 58, 2, center_w=CW)
    d.text((CW // 2, CH - 90), DISCLOSURE_SHORT, font=font(28), fill=txt, anchor="ma")
    return img


def make_card(name, headline, photos=None, key="card"):
    """단일 이미지 게시물용 카드 1장 (디자인·색은 매번 무작위)."""
    OUT_DIR.mkdir(exist_ok=True)
    photo = photos[0] if photos else None
    img = add_ad_tag(render_cover(name, headline, photo, pick_layout(photo), random_palette()))
    path = OUT_DIR / f"{slug(key)}.jpg"
    img.save(path, quality=92)
    return path


def make_carousel(name, headline, points, photos=None, key="carousel"):
    """캐러셀(여러 장) 이미지: 표지 → 장점들 → 구매 안내. 파일 경로 목록을 돌려준다."""
    folder = OUT_DIR / slug(key)
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob("*.jpg"):
        old.unlink()
    photos = photos or []
    pal = random_palette()
    first = photos[0] if photos else None
    layout = pick_layout(first)

    def zoom(im, z, fx, fy):
        """사진의 일부를 확대해 잘라낸다 (fx, fy: 확대 중심 0~1)."""
        w, h = im.size
        cw, ch = int(w / z), int(h / z)
        x = int(min(max(fx * w - cw / 2, 0), w - cw))
        y = int(min(max(fy * h - ch / 2, 0), h - ch))
        return im.crop((x, y, x + cw, y + ch))

    def ph(i):
        if not photos:
            return None
        if len(photos) > 1:
            return photos[i % len(photos)]
        # 사진이 1장뿐이면 장마다 다르게: 확대(위) → 사진 없이 글자 → 확대(아래쪽)
        one = photos[0]
        return {1: zoom(one, 1.6, 0.5, 0.3), 2: None, 3: zoom(one, 1.4, 0.5, 0.7)}.get(i, one)

    points = [p for p in points if p][:3]
    total = len(points) + 2
    slides = [render_cover(name, headline, first, layout, pal, footer=False)]
    for i, pt in enumerate(points, start=1):
        slides.append(render_point(i, total, pt, ph(i), layout, pal))
    slides.append(render_cta(name, ph(len(points) + 1), pal))

    paths = []
    for n, im in enumerate(slides, start=1):
        p = folder / f"{n:02d}.jpg"
        add_ad_tag(im).save(p, quality=92)
        paths.append(p)
    return paths


# ---------------------------------------------------------------- 업로드
VIDEO_EXT = {".mp4", ".mov", ".m4v"}


def _cloudinary_upload(path, cfg):
    u = urllib.parse.urlparse(cfg)
    key = urllib.parse.unquote(u.username or "")
    secret = urllib.parse.unquote(u.password or "")
    cloud = u.netloc.rsplit("@", 1)[-1]
    if not (key and secret and cloud):
        raise RuntimeError("CLOUDINARY_URL 형식이 잘못됐습니다 (cloudinary://키:시크릿@클라우드이름).")
    kind = "video" if pathlib.Path(path).suffix.lower() in VIDEO_EXT else "image"
    ts = str(int(time.time()))
    folder = "coupang-autopost"
    sig = hashlib.sha1(f"folder={folder}&timestamp={ts}{secret}".encode()).hexdigest()
    with open(path, "rb") as f:
        r = requests.post(f"https://api.cloudinary.com/v1_1/{cloud}/{kind}/upload",
                          data={"api_key": key, "timestamp": ts, "folder": folder, "signature": sig},
                          files={"file": f}, timeout=600)
    if r.status_code >= 400:
        raise RuntimeError(f"Cloudinary 업로드 실패 ({r.status_code}): {r.text[:300]}")
    return r.json()["secure_url"]


def _imgbb_upload(path, key):
    data = base64.b64encode(pathlib.Path(path).read_bytes()).decode()
    r = requests.post("https://api.imgbb.com/1/upload", params={"key": key},
                      data={"image": data}, timeout=120)
    if r.status_code >= 400:
        raise RuntimeError(f"imgbb 업로드 실패 ({r.status_code}): {r.text[:300]}")
    return r.json()["data"]["url"]


def upload(path):
    """파일을 올리고 공개 주소를 돌려준다."""
    cfg = (os.getenv("CLOUDINARY_URL") or "").strip()
    if cfg:
        return _cloudinary_upload(path, cfg)
    if pathlib.Path(path).suffix.lower() in VIDEO_EXT:
        raise RuntimeError("영상을 올리려면 .env에 CLOUDINARY_URL이 필요합니다.")
    key = (os.getenv("IMGBB_API_KEY") or "").strip()
    if key:
        return _imgbb_upload(path, key)
    raise RuntimeError(".env에 CLOUDINARY_URL(또는 IMGBB_API_KEY)이 없어 업로드할 수 없습니다.")
