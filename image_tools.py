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
import sys
import random
import re
import time
import urllib.parse

import requests
from PIL import Image, ImageDraw, ImageFont, ImageOps

BASE = pathlib.Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent  # exe면 exe 폴더
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


COVER_NAMES = {"커버", "cover", "표지"}  # 이 이름의 사진은 릴스 커버로만 씀


def is_cover_file(f):
    return f.suffix.lower() in PHOTO_EXT and f.stem.strip().lower() in COVER_NAMES


def images_in(folder):
    return sorted((f for f in folder.iterdir() if f.suffix.lower() in PHOTO_EXT and not is_cover_file(f)),
                  key=lambda f: f.name.lower())


def cover_file_in(folder):
    """폴더에 직접 넣은 커버 사진(커버.jpg 등). 없으면 None."""
    if not folder.is_dir():
        return None
    found = [f for f in folder.iterdir() if is_cover_file(f)]
    return found[0] if found else None


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


# ---------------------------------------------------------------- 상세 이미지
DETAIL_DIR = "상세"  # 상품 사진 폴더 안: 상세페이지 이미지를 3:4로 자른 조각 (캐러셀·영상용)
DETAIL_MAX = 8      # 캐러셀 = 표지 + 상세 조각 최대 8장 + 구매 안내 (인스타 최대 10장)


def is_blank(im, limit=18):
    """글씨·그림이 거의 없는 한 색 조각(여백·띠)인지."""
    from PIL import ImageStat
    return ImageStat.Stat(im.convert("L").resize((64, 64))).stddev[0] < limit


def _quiet_rows(im, scale_w=200):
    """줄마다 얼마나 '비어 있는지' (작을수록 글씨·그림이 없는 줄). 원본 높이 기준 (줄 위치, 점수) 목록."""
    from PIL import ImageStat
    w, h = im.size
    sh = max(1, round(h * scale_w / w))
    g = im.convert("L").resize((scale_w, sh))
    out = []
    for y in range(sh):
        out.append((round(y * h / sh), ImageStat.Stat(g.crop((0, y, scale_w, y + 1))).stddev[0]))
    return out


def _trim_blank(piece, margin=0.04, quiet=4):
    """조각 위아래의 글씨·그림 없는 빈 줄을 잘라냄 (여백은 폭의 4%만 남김)."""
    rows = [y for y, score in _quiet_rows(piece) if score > quiet]
    if not rows:
        return piece
    m = int(piece.width * margin)
    return piece.crop((0, max(0, rows[0] - m), piece.width, min(piece.height, rows[-1] + m + 2)))


def _pad_to(piece, w, h):
    """조각을 w×h(3:4)로 맞춤: 내용은 가운데, 모자란 위아래는 가장자리 배경색으로 채움."""
    if piece.height >= h:
        return piece
    edge = piece.convert("RGB").crop((0, piece.height - 1, max(1, w // 50), piece.height))  # 맨 아래 줄 왼쪽 끝(배경색)
    color = edge.resize((1, 1)).getpixel((0, 0))
    canvas = Image.new("RGB", (w, h), color)
    canvas.paste(piece.convert("RGB"), (0, (h - piece.height) // 2))
    return canvas


def split_tall(im, max_pieces=6, pad=True):
    """세로로 긴 상세 이미지 → 가로:세로 3:4 조각들. 글씨·사진 중간이 잘리지 않게 3:4 길이 안에서
    가장 빈 줄(여백)을 골라 자르고, 짧아진 조각은 아래를 같은 색으로 채워 3:4로 맞춘다.
    글씨·그림이 거의 없는 조각(여백·띠)은 뺀다."""
    w, h = im.size
    step = int(w * 4 / 3)
    rows = _quiet_rows(im)
    pieces, top = [], 0
    while top < h:
        bottom = min(top + step, h)
        if bottom < h:  # 3:4 길이의 뒤쪽 절반 안에서 가장 조용한 줄에서 자름 (같으면 아래쪽)
            cand = [(round(score), -y, y) for y, score in rows if top + step * 0.5 <= y <= bottom]
            if cand:
                bottom = min(cand)[2]
        if bottom - top < w * 0.5:  # 끝에 남은 짧은 띠
            break
        piece = im.crop((0, top, w, bottom))
        top = bottom
        if is_blank(piece):
            continue
        piece = _trim_blank(piece)
        if piece.height < step * 0.3:  # 빈 여백을 빼고 나니 내용이 조금뿐인 조각은 뺌
            continue
        pieces.append(_pad_to(piece, w, step) if pad else piece)  # pad=False(블로그): 빈 여백 없이 내용 크기 그대로
        if len(pieces) >= max_pieces:
            break
    return pieces or [im]


def detail_pieces(images, limit=DETAIL_MAX):
    """상세페이지 이미지들 → 캐러셀에 쓸 조각들. 작은 이미지·가로 띠(배너)·빈 이미지는 빼고, 긴 이미지는 3:4로 자른다."""
    out = []
    for im in images:
        w, h = im.size
        if min(w, h) < 300 or w > h * 3:
            continue
        for piece in (split_tall(im, limit) if h > w * 1.6 else [im]):
            if not is_blank(piece) and not is_duplicate(piece, out):
                out.append(piece)
        if len(out) >= limit:
            break
    return out[:limit]


# 상세페이지에 섞여 있는 상품과 관계없는 조각(배송·교환·반품 안내, 쿠폰·이벤트, 판매자 공지)을 알아보는 말.
# 시트 '_설정'의 DETAIL_SKIP_WORDS(띄어쓰기로 구분)로 더 넣을 수 있다.
NOTICE_WORDS = ("배송안내 배송정보 배송기간 택배 출고 영업일 교환안내 교환반품 교환/반품 교환및반품 반품 환불 고객센터 상담시간 A/S AS안내 "
                "주의사항 유의사항 공지 쿠폰 이벤트 적립금 리뷰이벤트 포토리뷰 상품정보제공고시 판매자정보 "
                "함께구매 추천상품 다른상품 브랜드관")
_notice_cache = {}


def is_notice(im, key=None):
    """상품 설명이 아닌 안내·광고 조각인지 (OCR). 확인할 수 없으면 False(그대로 씀)."""
    if key in _notice_cache:
        return _notice_cache[key]
    found = False
    if _ocr_ready():
        import pytesseract
        g = im.convert("L")
        if max(g.size) > 1400:
            g = ImageOps.contain(g, (1400, 1400))
        try:
            text = re.sub(r"\s+", "", pytesseract.image_to_string(g, lang="kor+eng", config="--psm 11", timeout=30)).upper()
        except Exception:
            text = ""
        words = (NOTICE_WORDS + " " + (os.getenv("DETAIL_SKIP_WORDS") or "")).replace(",", " ").split()
        found = next((w for w in words if w.upper() in text), False)
        if found:
            print(f"  (상세 조각 1장은 상품과 관계없는 안내라 뺐습니다: '{found}')")
            found = True
    if key is not None:
        _notice_cache[key] = found
    return found


def detail_photos(name):
    """사진 폴더/상세 의 조각들 (없으면 빈 목록). 배송·교환 안내, 쿠폰 같은 조각은 뺀다."""
    folder = photo_root() / folder_name(name) / DETAIL_DIR
    if not folder.is_dir():
        return []
    out = []
    for f in images_in(folder):
        im = load_photo(str(f))
        if im is None or is_notice(im, key=(str(f), f.stat().st_mtime)):
            continue
        out.append(im)
        if len(out) >= DETAIL_MAX:
            break
    return out


# ---------------------------------------------------------------- 글자 없는 사진 고르기
# 인스타·쓰레드 사진 위에는 우리가 자막을 얹으므로, 원래 글자가 박힌 사진(상세페이지 설명, 광고 문구)은 피한다.
# 서버(GitHub Actions)에는 tesseract(한국어)가 깔려 있어 OCR로 확인. 없으면(PC 등) 대표 사진은 그대로 쓰고 상세 조각은 안 쓴다.
_OCR = {"ok": None}


def _ocr_ready():
    if _OCR["ok"] is None:
        try:
            import pytesseract
            _OCR["ok"] = "kor" in pytesseract.get_languages(config="")
        except Exception:
            _OCR["ok"] = False
        if not _OCR["ok"]:
            print("  (글자 확인(OCR)을 쓸 수 없어 사진 글자 검사를 건너뜁니다)")
    return _OCR["ok"]


def has_text(im):
    """사진에 글자가 있는지 (한국어·영어 OCR). 확인할 수 없으면 None.
    상품 포장에 작게 찍힌 글씨 정도는 넘어가고, 글자가 OCR_WORDS(기본 3)개 이상이거나
    글자 영역이 사진의 OCR_AREA(기본 1.5)% 이상이면 '글자 있음'."""
    if not _ocr_ready():
        return None
    import pytesseract
    g = im.convert("L")
    if max(g.size) > 1200:
        g = ImageOps.contain(g, (1200, 1200))
    try:
        data = pytesseract.image_to_data(g, lang="kor+eng", config="--psm 11",
                                         output_type=pytesseract.Output.DICT, timeout=30)
    except Exception:
        return None
    words, area = 0, 0
    for txt, conf, w, h in zip(data["text"], data["conf"], data["width"], data["height"]):
        t = re.sub(r"[^0-9A-Za-z가-힣]", "", txt or "")
        if len(t) >= 2 and float(conf) >= 70:
            words += 1
            area += w * h
    max_words = _env_int("OCR_WORDS", 3)
    max_area = float(os.getenv("OCR_AREA") or 1.5) / 100
    return words >= max_words or area >= g.width * g.height * max_area


def pick_photos(photos, details, need, strict=False):
    """게시에 쓸 사진: 글자 없는 대표·썸네일 → (모자라면) 글자 없는 상세 조각.
    strict=False(인스타): 그래도 모자라면 글자 있는 대표 사진으로 채움. strict=True(쓰레드): 글자 없는 것만.
    상세 조각은 글자가 있으면 절대 쓰지 않는다."""
    flags = [has_text(im) for im in photos]
    clean = [im for im, f in zip(photos, flags) if not f]
    texty = [im for im, f in zip(photos, flags) if f]
    out = clean[:need]
    for im in details:
        if len(out) >= need:
            break
        if has_text(im) is False:  # 확인해서 글자 없다고 나온 조각만
            out.append(im)
    if not strict:
        out += texty[:max(0, need - len(out))]
    if texty or len(clean) < len(photos):
        print(f"  (글자 있는 대표 사진 {len(texty)}장은 {'뺐습니다' if strict else '뒤로 미뤘습니다'})")
    return out


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


def make_tip_card(title, sub="", label="", key="tip"):
    """일반 글(광고 아님)용 글자 카드 1장. 광고 표시·구매 안내 없이 제목만 크게."""
    OUT_DIR.mkdir(exist_ok=True)
    bg, accent, fg = random_palette()
    W = CW - PAD * 2

    def draw(top):
        img = Image.new("RGB", (CW, CH), bg)
        d = ImageDraw.Draw(img)
        d.rectangle((0, 0, CW, 24), fill=accent)
        y = top
        if label:
            lw = d.textlength(label, font=font(40)) + 56
            pill(d, int((CW - lw) // 2), y, label, font(40), accent, bg)
            y += 190
        y = text_block(d, 0, y, title, font(96), fg, W, 126, 4, center_w=CW) + 34
        d.rectangle((CW // 2 - 60, y, CW // 2 + 60, y + 10), fill=accent)
        y += 10
        if sub:
            y = text_block(d, 0, y + 44, sub, font(46), fg, W, 64, 3, center_w=CW)
        return img, y

    _, end = draw(0)  # 글 높이를 재서 세로 가운데에 오게
    img, _ = draw(max(120, (CH - end) // 2))
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


def make_reel_cover(name, headline, photo=None, own=None, key="cover"):
    """릴스 커버(1080×1920). own(직접 넣은 커버 사진)이 있으면 그대로 9:16으로 맞추고,
    없으면 카드(4:5)를 가운데에 두고 위아래를 사진을 흐리게 깔아 채운다.
    프로필 격자에서는 가운데 4:5만 보이므로 카드가 그대로 보인다."""
    from PIL import ImageFilter
    OUT_DIR.mkdir(exist_ok=True)
    RW, RH = 1080, 1920
    if own is not None:
        img = cover(own.convert("RGB"), RW, RH)
    else:
        pal = random_palette()
        card = add_ad_tag(render_cover(name, headline, photo, pick_layout(photo), pal))
        if photo is not None:
            img = cover(photo.convert("RGB"), RW, RH).filter(ImageFilter.GaussianBlur(40))
        else:
            img = Image.new("RGB", (RW, RH), pal[0])
        img.paste(card, (0, (RH - CH) // 2))
    path = OUT_DIR / f"{slug(key)}_cover.jpg"
    img.save(path, "JPEG", quality=90)
    return path
