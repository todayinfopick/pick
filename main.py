# -*- coding: utf-8 -*-
"""쿠팡파트너스 상품을 쓰레드·인스타그램에 자동 게시하는 스크립트.

사용법
  python main.py            : products.csv에서 다음 상품을 골라 게시
  python main.py --dry-run  : 게시하지 않고 글과 이미지/영상만 미리보기
  python main.py --count 3  : 이번 실행에서 3개 상품 게시
"""
import argparse
import csv
import datetime
import json
import os
import pathlib
import sys
import time
import urllib.parse

import requests
from dotenv import load_dotenv

import affiliates

BASE = pathlib.Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent  # exe면 exe 폴더
ENV_PATH = BASE / ".env"
load_dotenv(ENV_PATH)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

PRODUCTS = BASE / "products.csv"
POSTED = BASE / "posted.json"
LOG_DIR = BASE / "logs"
MAX_FAILS = 3  # 같은 상품·채널이 이만큼 실패하면 건너뜀

VIDEO_EXT = {".mp4", ".mov", ".m4v"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}

# 기본 대가성 문구 (실제로는 제휴처.csv에서 링크별로 정해짐)
DISCLOSURE = "이 포스팅은 쿠팡 파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다."
IG_LINK_TEXT_DEFAULT = "🔗 구매 링크는 프로필 링크에서 '{상품명}' 찾아주세요"


def env(key, default=""):
    return (os.getenv(key) or default).strip()


def log(msg):
    LOG_DIR.mkdir(exist_ok=True)
    line = f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line)
    with open(LOG_DIR / "run.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")


def check(r, what):
    if r.status_code >= 400:
        raise RuntimeError(f"{what} 실패 ({r.status_code}): {r.text[:500]}")


# ---------------------------------------------------------------- 상품 목록
def parse_when(text):
    """엑셀에서 흔히 나오는 날짜·시간 형식을 읽는다. 못 읽으면 ValueError."""
    s = " ".join(text.replace("오전", "AM").replace("오후", "PM").split())
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y.%m.%d %H:%M",
                "%Y. %m. %d. %H:%M", "%Y-%m-%d %p %I:%M", "%Y-%m-%d %I:%M %p",
                "%Y-%m-%d %p %I:%M:%S", "%Y/%m/%d %p %I:%M", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.datetime.strptime(s, fmt)
        except ValueError:
            continue
    raise ValueError(text)


def image_kind():
    """'이미지' 형식을 캐러셀(여러 장)로 올릴지 1장으로 올릴지 (.env CAROUSEL)."""
    return "image" if env("CAROUSEL", "1") == "0" else "carousel"


def kind_from_text(text):
    t = text.lower().replace(" ", "")
    if any(k in t for k in ("영상", "동영상", "릴스", "video", "reels")):
        return "video"
    if any(k in t for k in ("캐러셀", "카드뉴스", "여러장", "슬라이드", "carousel")):
        return "carousel"
    if any(k in t for k in ("1장", "한장", "단일", "single")):
        return "image"
    if any(k in t for k in ("이미지", "사진", "image", "photo")):
        return image_kind()
    return ""


def load_products():
    rows = None
    for enc in ("utf-8-sig", "cp949"):
        try:
            with open(PRODUCTS, encoding=enc, newline="") as f:
                rd = csv.DictReader(f)
                rows = [(rd.line_num, r) for r in rd]  # 엑셀 행 번호(빈 줄 포함)와 함께
            break
        except UnicodeDecodeError:
            continue
    if rows is None:
        raise SystemExit("products.csv를 읽을 수 없습니다. 엑셀에서 'CSV UTF-8'로 저장해 주세요.")

    items, seen = [], {}
    for n, r in rows:
        r = {(k or "").strip(): (v or "").strip() for k, v in r.items()}
        name, link = r.get("상품명", ""), r.get("파트너스링크", "")
        if not name or not link or "예시" in link:
            continue
        aff = affiliates.detect(link)
        if not link.lower().startswith("http"):
            log(f"  ! {n}번째 줄 '{name}': 파트너스링크 칸에 링크가 아닌 값이 있어 건너뜁니다 → {link}")
            log("    (제휴 링크는 '파트너스링크' 칸에, 사진 경로는 '소재이미지' 칸에 넣어 주세요)")
            continue
        if aff["plain"]:
            log(f"  ! {n}번째 줄 '{name}': {aff['name']} 제휴 링크가 아닌 일반 주소라 건너뜁니다"
                f"(수익 안 잡힘) → {link}")
            log("    (제휴 프로그램에서 만든 링크로 바꿔 주세요)")
            continue
        when, when_raw = None, r.get("게시시간", "")
        if when_raw:
            try:
                when = parse_when(when_raw)
            except ValueError:
                log(f"  ! {n}번째 줄 '{name}'의 게시시간을 읽을 수 없어 건너뜁니다: {when_raw} "
                    f"(예: 2026-10-20 19:00)")
                continue
        nk = product_key(name)
        if nk in seen:
            log(f"  ! {n}번째 줄 '{name}': {seen[nk]}번째 줄과 같은 상품이라 건너뜁니다 (링크나 컬러·수량 옵션만 다름)")
            continue
        seen[nk] = n
        items.append({
            "row": n,
            "name": name,
            # 화면 표시용 이름: 쿠팡 상품명의 쉼표 뒤 옵션(1개, 상세페이지 참조 등)을 뺀 앞부분
            "short": name.split(",")[0].strip() or name,
            "aff": aff,
            "link": link,
            "kind_pref": kind_from_text(r.get("형식", "")),
            # 완성된 이미지/영상 (비우면 자동 생성). 예전 '이미지' 칸도 인식
            "media": r.get("미디어", "") or r.get("이미지", "") or r.get("이미지URL", ""),
            # 자동 생성에 쓸 상품 사진 (여러 장은 | 로 구분)
            "source": r.get("소재이미지", ""),
            "when": when,
            "memo": r.get("특징메모", ""),
            "category": r.get("분류", ""),  # 계정 나누기용 (accounts.route)
        })
    return items


def product_key(name):
    """같은 상품인지 판단하는 기준. 쿠팡 링크는 만들 때마다 바뀌므로 상품명으로 구분한다.
    SAME_PRODUCT=쉼표앞(기본): '맥 립밤, 457 페이보릿, 1개' → '맥 립밤' (컬러·수량 옵션은 같은 상품)
    SAME_PRODUCT=전체: 상품명 전체가 같아야 같은 상품 (컬러별로 따로 게시)"""
    name = name or ""
    if env("SAME_PRODUCT", "쉼표앞") != "전체":
        name = name.split(",")[0]
    return "".join(name.lower().split())


def posted_key(item):
    """게시 기록 키 (상품 기준)."""
    return "상품:" + product_key(item["name"])


def get_rec(posted, item):
    """상품명 기준 기록 → 예전 방식(링크 기준) 기록 → 기록 안의 상품명이 같은 것 순서로 찾는다."""
    rec = posted.get(posted_key(item)) or posted.get(item["link"])
    if rec:
        return rec
    nk = product_key(item["name"])
    for k, v in posted.items():
        if k != "_meta" and isinstance(v, dict) and product_key(str(v.get("name", ""))) == nk:
            return v
    return {}


def load_posted():
    if POSTED.exists():
        return json.loads(POSTED.read_text(encoding="utf-8"))
    return {}


def save_posted(data):
    POSTED.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def queue(items, now):
    """게시 순서: 게시시간이 지난 상품(이른 순) → 시간 미지정 상품(엑셀 순서).
    아직 시간이 안 된 상품은 제외."""
    due = sorted((i for i in items if i["when"] and i["when"] <= now), key=lambda i: i["when"])
    plain = [i for i in items if not i["when"]]
    return due + plain


# ---------------------------------------------------------------- 채널·형식 판단
def threads_on():
    return env("THREADS_ON", "1") != "0" and bool(env("THREADS_USER_ID") and env("THREADS_ACCESS_TOKEN"))


def ig_on():
    return env("IG_ON", "1") != "0" and bool(env("IG_USER_ID") and env("IG_ACCESS_TOKEN"))


def media_ext(src):
    path = urllib.parse.urlparse(src).path if src.startswith("http") else src.strip('"')
    return pathlib.Path(path).suffix.lower()


def media_list(item):
    """미디어 칸에 적은 파일·주소 목록 (| 로 여러 개)."""
    return [m.strip().strip('"') for m in item["media"].split("|") if m.strip()]


def folder_video(item):
    """상품 사진 폴더에 직접 넣어 둔 영상(있으면 첫 번째). 없으면 None."""
    if media_list(item) or item["source"]:
        return None
    import image_tools
    folder = image_tools.photo_root() / image_tools.folder_name(item["name"])
    if not folder.is_dir():
        return None
    vids = sorted((f for f in folder.iterdir() if f.suffix.lower() in VIDEO_EXT), key=lambda f: f.name.lower())
    return vids[0] if vids else None


def decide_kind(item, posted):
    """이번 게시물 형식: image(1장) / carousel(여러 장) / video."""
    files = media_list(item)
    # 폴더에 직접 찍은 영상이 있으면 그 영상을 릴스로 (형식 칸에 이미지/캐러셀을 적으면 사진 사용)
    if not files and item["kind_pref"] in ("", "video") and folder_video(item) and can_host("video"):
        return "video"
    if files:
        if len(files) > 1:
            return "carousel"
        ext = media_ext(files[0])
        if ext in VIDEO_EXT:
            return "video"
        if ext in IMAGE_EXT:
            return "image"
        return "video" if item["kind_pref"] == "video" else "image"
    kind = item["kind_pref"] or kind_from_text(env("DEFAULT_FORMAT", "번갈아"))
    if not kind:
        last = posted.get("_meta", {}).get("last_kind", "video")
        kind = image_kind() if last == "video" else "video"
    # 자동 영상인데 영상을 올릴 곳(CLOUDINARY_URL)이 없으면 이미지로 대신 올림
    if kind == "video" and not can_host("video") and can_host("image"):
        return image_kind()
    return kind


def can_host(kind):
    if env("CLOUDINARY_URL"):
        return True
    return kind != "video" and bool(env("IMGBB_API_KEY"))


def media_possible(item, kind):
    files = media_list(item)
    if files and all(f.startswith("http") for f in files):
        return True
    return can_host(kind)


def pending_channels(item, rec, kind):
    fails = rec.get("fails", {})
    ch = []
    if threads_on() and "threads" not in rec and fails.get("threads", 0) < MAX_FAILS:
        ch.append("threads")
    if ig_on() and media_possible(item, kind) and "instagram" not in rec \
            and fails.get("instagram", 0) < MAX_FAILS:
        ch.append("instagram")
    return ch


def never_posted(rec):
    return not any(c in rec for c in ("threads", "instagram"))


# ---------------------------------------------------------------- AI 글 생성
PROMPT = """너는 한국 SNS 쇼핑 큐레이터다. 아래 상품을 소개하는 SNS 콘텐츠를 써라.

상품명: {name}
특징 메모: {memo}

공통 규칙
- 확인되지 않은 주장 금지: '최저가', '1위', '효과 보장', 의학적 효능 같은 표현 쓰지 마라.
- 특징 메모에 없는 성능·수치는 지어내지 마라.
- 가격은 자주 바뀌므로 언급하지 마라.
- 친구에게 추천하듯 자연스러운 말투. 단, 직접 써본 것처럼 읽히는 표현은 금지
  ('손이 가요', '써보니', '발라보니', '~한 느낌이라', '애정템' 등). 상품 특징을 소개하는 관점으로만 써라.
- 링크, 광고 문구, 구매 안내 문구는 넣지 마라(프로그램이 따로 붙인다).

headline: 이미지·영상 첫 화면에 크게 들어갈 한 줄. 18자 이내, 이모지·해시태그 없음.
  스크롤을 멈추게 하는 '고민·상황·질문형'으로 써라. 상품 설명이나 성분·기술 이름으로 시작하지 마라.
  좋은 예: "오후만 되면 들뜨는 파우더?", "세안 후 당김 싫다면", "입술 각질 매일 고민이라면"
  나쁜 예: "들뜸 적은 수분 윤광 파우더", "극저온 동결 건조 파우더"
points: 이미지·영상의 장점 3개. 각각 12자 이내 짧은 구절.
  성분·공법·기술 용어를 그대로 쓰지 말고, 그 덕분에 사용자가 느끼는 변화로 바꿔 써라.
  좋은 예: "덧발라도 안 두꺼워요", "오후에도 촉촉하게", "거품 하나로 메이크업까지"
  나쁜 예: "극저온 동결·진공 건조", "저분자 히알루론산 함유"
threads: 300자 이내. 쓰레드는 글이 주인공이고 사진·영상은 참고용일 뿐이다. 글만 읽어도 상품이 이해되고
  댓글로 이야기하고 싶어지게 써라. 친구한테 말하듯 반말을 섞은 편한 말투
  (예: "이거 알아?", "~더라", "~하면 딱이야", "~거든요"처럼 반말 위주에 존댓말 살짝).
  첫 문장은 눈길을 끄는 한 줄, 마지막은 읽는 사람에게 던지는 가벼운 질문 한 줄.
  이모지 0~2개, 해시태그 없음. 써본 척 금지 규칙은 그대로 지켜라.
threads_reply: 쓰레드 첫 댓글 맨 위 [광고] 뒤에 붙을 짧은 한 줄. 25자 이내, 반말 섞인 감탄·공감형.
  예: "나만 몰랐네..이 좋은 걸 ㅠㅠ", "이건 진짜 알려줘야 돼". 링크·광고 문구는 넣지 마라(프로그램이 붙인다).
instagram: 350자 이내 본문. 줄바꿈으로 읽기 쉽게. 해시태그 없음.
hashtags: 관련 해시태그 5~8개를 한 줄로 (#으로 시작, 띄어쓰기로 구분).

다른 말 없이 아래 JSON만 출력:
{{"headline": "...", "points": ["...", "...", "..."], "threads": "...", "threads_reply": "...", "instagram": "...", "hashtags": "..."}}"""


POST_TOOL = {
    "name": "write_post",
    "description": "완성한 SNS 콘텐츠를 제출한다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "headline": {"type": "string", "description": "첫 화면 문구, 18자 이내, 고민·상황·질문형"},
            "points": {"type": "array", "items": {"type": "string"}, "description": "장점 3개, 각 12자 이내, 기술 용어 대신 사용자가 느끼는 변화"},
            "threads": {"type": "string", "description": "쓰레드 본문, 300자 이내, 글이 주인공, 반말 섞인 말투, 끝은 가벼운 질문"},
            "threads_reply": {"type": "string", "description": "쓰레드 첫 댓글 한 줄, 25자 이내, 반말 섞인 감탄·공감형, 링크 없음"},
            "instagram": {"type": "string", "description": "인스타 본문, 350자 이내, 해시태그 없음"},
            "hashtags": {"type": "string", "description": "해시태그 5~8개, 띄어쓰기로 구분"},
        },
        "required": ["headline", "points", "threads", "threads_reply", "instagram", "hashtags"],
    },
}


def _ask_ai(payload):
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": env("ANTHROPIC_API_KEY"),
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json=payload,
        timeout=180,
    )
    return r


def _parse_text_json(body):
    blocks = body.get("content", [])
    text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        kinds = ",".join(b.get("type", "?") for b in blocks) or "없음"
        raise ValueError(f"stop_reason={body.get('stop_reason')}, blocks={kinds}: {text[:200]}")
    return json.loads(text[start:end + 1], strict=False)


RESEARCH_PROMPT = """아래 상품을 웹에서 검색해, 이 상품의 실제 특징을 정리해라.
상품명: {name}

규칙
- 이 상품(같은 브랜드·같은 제품)으로 확인되는 사실만 써라. 비슷한 다른 제품 정보는 섞지 마라.
- 가격, 할인, 순위, 평점, 리뷰 수는 빼라(자주 바뀜).
- 효능·효과는 제조사가 밝힌 표현 수준으로만 써라.
- 확인된 특징 3~6개를 쉼표로 구분한 한 줄로만 출력하라. 설명·출처·다른 말은 쓰지 마라.
- 상품을 특정할 수 없거나 정보가 없으면 정확히 '정보 부족'이라고만 출력하라."""


def _load_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception:
        return {}


def research_path():
    """조사 결과 저장 파일. RESEARCH_FILE로 두 폴더가 같은 파일을 함께 쓸 수 있다."""
    custom = env("RESEARCH_FILE")
    if custom:
        p = pathlib.Path(custom.strip('"'))
        p.parent.mkdir(parents=True, exist_ok=True)
        return p
    return BASE / "research.json"


def name_key(name):
    return "".join(name.lower().split())


def save_research(cache):
    path = research_path()
    path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    # 사람이 엑셀로 보기 좋게 같은 내용을 CSV로도 저장
    try:
        with open(path.with_name("조사결과.csv"), "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["상품명", "특징", "출처", "저장일"])
            for v in sorted(cache.values(), key=lambda v: v.get("at", ""), reverse=True):
                w.writerow([v.get("name", ""), v.get("facts", "") or "(정보 부족)",
                            v.get("source", "AI 검색"), v.get("at", "")[:10]])
    except PermissionError:
        pass  # 엑셀로 열어 둔 상태면 다음 기회에 저장


def remember_memo(item):
    """엑셀에 직접 넣은 특징메모(채팅에서 받은 것 포함)도 저장해 두어, 다른 폴더·다음번에 재사용."""
    if not item["memo"]:
        return
    cache = _load_json(research_path())
    key = name_key(item["name"])
    old = cache.get(key, {})
    if old.get("facts") == item["memo"]:
        return
    cache[key] = {"name": item["name"], "facts": item["memo"], "link": item["link"],
                  "source": "직접 입력", "at": datetime.datetime.now().isoformat(timespec="seconds")}
    save_research(cache)


def gemini_memo(item):
    """제미나이(무료 키)가 사진 폴더의 캡처(_설명 폴더 포함)를 읽고 특징메모를 쓴다. 못 쓰면 ''."""
    import memo_ai
    if not memo_ai.enabled():
        return ""
    try:
        import image_tools
        from PIL import Image
        folder = image_tools.photo_root() / image_tools.folder_name(item["name"])
        files = []
        for d in (folder, folder / "_설명"):
            if d.is_dir():
                files += image_tools.images_in(d)
        images = []
        for f in files[:12]:
            with Image.open(f) as im:
                images.append(im.copy())
        try:
            page_text = (folder / "페이지글.txt").read_text(encoding="utf-8")  # 크롬 확장프로그램이 저장
        except OSError:
            page_text = ""
        if not images and not page_text:
            return ""
        return memo_ai.write_memo(images, item["name"], item["link"], page_text=page_text)["memo"]
    except Exception as e:
        log(f"  ! 제미나이 메모 작성 실패: {e}")
        return ""


def save_memo_to_sheet(item, memo):
    """서버에서 채운 메모를 시트 특징메모 칸에도 적어 둔다 (보고 고칠 수 있게). 실패해도 계속."""
    try:
        import gcloud
        if gcloud.enabled() and (gcloud.env("GOOGLE_SA_JSON") or gcloud.env("GOOGLE_SA_FILE")):
            gcloud.set_memo(item["name"], memo)
    except Exception as e:
        log(f"  (시트에 메모를 적지 못했습니다: {e})")


def research(item):
    """특징메모가 비었을 때 특징을 찾는다. 못 찾으면 빈 문자열.
    1) 저장해 둔 메모(research.json) 2) 제미나이가 캡처 읽기(무료) 3) Claude 웹 검색(유료, AUTO_RESEARCH=1일 때만)
    찾은 결과는 상품명 기준으로 저장해 두고 다시 쓴다."""
    cache = _load_json(research_path())
    hit = cache.get(name_key(item["name"]))
    if hit is not None and hit.get("facts"):
        return hit["facts"]
    facts = gemini_memo(item)
    if facts:
        cache[name_key(item["name"])] = {"name": item["name"], "facts": facts, "link": item["link"],
                                         "source": "제미나이(캡처)",
                                         "at": datetime.datetime.now().isoformat(timespec="seconds")}
        save_research(cache)
        save_memo_to_sheet(item, facts)
        return facts
    if hit is not None:
        return ""  # 예전에 유료 검색으로도 못 찾은 상품
    if env("AUTO_RESEARCH", "0") == "0" or not env("ANTHROPIC_API_KEY"):
        return ""

    r = _ask_ai({
        "model": env("CLAUDE_MODEL", "claude-haiku-5-5"),
        "max_tokens": 2000,
        "messages": [{"role": "user", "content": RESEARCH_PROMPT.format(name=item["name"])}],
        "tools": [{"type": "web_search_20250305", "name": "web_search", "max_uses": 3,
                   "user_location": {"type": "approximate", "country": "KR",
                                     "timezone": "Asia/Seoul"}}],
    })
    if not r.ok:
        log(f"  ! 자동 조사 실패({r.status_code}) → 상품명만으로 작성합니다: {r.text[:200]}")
        return ""
    blocks = r.json().get("content", [])
    last = max([i for i, b in enumerate(blocks) if b.get("type") == "web_search_tool_result"],
               default=-1)
    text = "".join(b.get("text", "") for b in blocks[last + 1:] if b.get("type") == "text").strip()
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    facts = lines[-1] if lines else ""
    if "정보 부족" in facts or len(facts) < 4:
        facts = ""
    cache[name_key(item["name"])] = {"name": item["name"], "facts": facts, "link": item["link"],
                                     "source": "AI 검색",
                                     "at": datetime.datetime.now().isoformat(timespec="seconds")}
    save_research(cache)
    return facts


def generate(item):
    """쇼핑 글 쓰기: Claude(유료 크레딧)로 쓰고, 키가 없거나 실패하면(크레딧 소진 등) 제미나이(무료)가 대신 쓴다."""
    prompt = PROMPT.format(name=item["name"], memo=item["memo"] or "(없음)")
    has_gemini = bool(env("GEMINI_API_KEY"))
    if not env("ANTHROPIC_API_KEY"):
        if not has_gemini:
            raise RuntimeError(".env 파일에 ANTHROPIC_API_KEY(또는 예비용 GEMINI_API_KEY)가 없습니다.")
        log("  ↪ Claude 키가 없어 제미나이로 글을 씁니다")
        return _post_fields(_gemini_post(prompt), item)
    try:
        return _post_fields(_claude_post(prompt), item)
    except Exception as e:
        if not has_gemini:
            raise
        log(f"  ↪ Claude 글 작성 실패, 제미나이로 대신 씁니다: {e}")
        return _post_fields(_gemini_post(prompt), item)


def _gemini_post(prompt):
    """예비: 제미나이로 같은 양식(POST_TOOL)의 글을 받는다."""
    import memo_ai
    fields = POST_TOOL["input_schema"]["properties"]
    spec = "\n".join(f'- "{k}": {v["description"]}' + (" (문자열 배열)" if v["type"] == "array" else "")
                     for k, v in fields.items())
    text = memo_ai.generate([{"text": f"{prompt}\n\n아래 키를 가진 JSON 하나만 출력하라.\n{spec}"}],
                            temperature=0.8)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        raise RuntimeError(f"제미나이 답을 해석하지 못했습니다: {text[:200]}")
    return json.loads(text[start:end + 1], strict=False)


def _claude_post(prompt):
    base = {"model": env("CLAUDE_MODEL", "claude-haiku-5-5"), "max_tokens": 4096,
            "messages": [{"role": "user", "content": prompt}]}

    # 1순위: 정해진 양식(도구)으로 받기 → 따옴표 등으로 깨질 일이 없음
    data = None
    r = _ask_ai({**base, "tools": [POST_TOOL], "tool_choice": {"type": "tool", "name": "write_post"}})
    if r.status_code in (401, 403, 429) or r.status_code >= 500:
        check(r, "AI 글 생성")
    if r.ok:
        for b in r.json().get("content", []):
            if b.get("type") == "tool_use" and isinstance(b.get("input"), dict):
                data = b["input"]

    # 2순위: 일반 글(JSON)로 받기, 깨지면 한 번 더 요청
    last_err = None
    for _ in range(2):
        if data is not None:
            break
        r = _ask_ai(base)
        check(r, "AI 글 생성")
        try:
            data = _parse_text_json(r.json())
        except ValueError as e:
            last_err = e
    if data is None:
        raise RuntimeError(f"AI 응답을 해석하지 못했습니다. 잠시 후 다시 시도해 주세요. ({last_err})")
    return data


def _post_fields(data, item):
    points = data.get("points", [])
    if isinstance(points, str):
        points = [p for p in points.replace("|", "\n").split("\n")]
    points = [str(p).strip() for p in points if str(p).strip()][:3]
    return {
        "headline": str(data.get("headline", "")).strip() or item["short"][:16],
        "points": points or [item["short"]],
        "threads": str(data["threads"]).strip(),
        "threads_reply": str(data.get("threads_reply", "")).strip(),
        "instagram": str(data["instagram"]).strip(),
        "hashtags": str(data.get("hashtags", "")).strip(),
    }


def link_in_reply():
    """THREADS_LINK_IN_REPLY=1(기본)이면 쓰레드 본문 대신 첫 댓글에 구매 링크를 넣는다.
    첫 댓글을 끈 경우(THREADS_REPLY=0)에는 링크가 사라지지 않게 본문에 넣는다."""
    return env("THREADS_LINK_IN_REPLY", "1") == "1" and env("THREADS_REPLY", "0") == "1"


def threads_media():
    """THREADS_MEDIA=1(기본)이면 쓰레드에 원본 사진·영상을 붙인다(자막·나레이션·소리 없이). 0이면 글만."""
    return env("THREADS_MEDIA", "1") == "1"


def compose_threads(body, link, disclosure=DISCLOSURE):
    head = f"{disclosure}\n\n"
    tail = "\n\n👇 구매 링크는 댓글에" if link_in_reply() else f"\n\n👉 {link}"
    room = 500 - len(head) - len(tail)  # 쓰레드 글자 수 제한 500자
    if len(body) > room:
        body = body[:room - 1].rstrip() + "…"
    return head + body + tail


def compose_threads_reply(text, link, disclosure=DISCLOSURE):
    """쓰레드 첫 댓글: [광고] 한 줄 + 대가성 문구 + 링크 여러 번(한 개가 죽을 때 대비).
    링크를 본문에 두는 설정이면 한 줄만. 쓸 내용이 없으면 ''(댓글을 달지 않음)."""
    if env("THREADS_REPLY", "0") != "1":
        return ""
    line = text.get("threads_reply", "").strip()
    if not link_in_reply():
        return line[:500]
    repeat = max(1, int(env("THREADS_LINK_REPEAT", "3") or 3))
    lines = [f"[광고] {line}".strip(), disclosure] + [link] * repeat
    return "\n".join(lines)[:500]


def compose_instagram(text, name, disclosure=DISCLOSURE):
    guide = env("IG_LINK_TEXT", IG_LINK_TEXT_DEFAULT).replace("{상품명}", name)
    parts = [disclosure, text["instagram"], guide]
    if text["hashtags"]:
        parts.append(text["hashtags"])
    return "\n\n".join(parts)[:2200]


# ---------------------------------------------------------------- 이미지·영상 준비
def local_media(item, kind, text):
    """수동 지정 파일이 있으면 그 경로들, 없으면 자동 생성한 파일 경로들."""
    import image_tools
    image_tools.DISCLOSURE_SHORT = item["aff"]["short"]  # 이미지·영상 속 대가성 문구를 제휴처에 맞게
    files = media_list(item)
    if files:
        out = []
        for m in files:
            if m.startswith("http"):
                out.append(m)
                continue
            p = image_tools.resolve_path(m)
            if not p.exists():
                raise RuntimeError(f"파일을 찾을 수 없습니다: {p}")
            out.append(p)
        return out
    key = item["link"].rsplit("/", 1)[-1]
    own = folder_video(item) if kind == "video" else None
    if own:
        import video_tools
        print(f"  (폴더에 넣은 영상 사용: {own.name})")
        return [video_tools.prepare_own_video(own, key)]
    photos = image_tools.load_photos(item["source"], item["name"])
    if kind == "video":
        import video_tools
        return [video_tools.make_video(item["short"], text["headline"], text["points"], photos, key)]
    if kind == "carousel":
        return image_tools.make_carousel(item["short"], text["headline"], text["points"], photos, key)
    return [image_tools.make_card(item["short"], text["headline"], photos, key)]


def threads_raw_media(item):
    """쓰레드용 원본 미디어 (파일 목록, 형식). 자동 카드·영상의 자막·[광고] 표시·소리는 넣지 않는다.
    - 미디어 칸에 직접 만든 완성본이 있으면 그대로
    - 사진 폴더에 영상이 있고 형식이 영상(또는 비움)이면 그 영상을 소리만 빼서
    - 아니면 상품 사진 원본 (1장=이미지, 여러 장=캐러셀)"""
    import image_tools
    files = media_list(item)
    if files:
        kind = "video" if media_ext(files[0]) in VIDEO_EXT else ("carousel" if len(files) > 1 else "image")
        return [m if m.startswith("http") else image_tools.resolve_path(m) for m in files], kind
    key = item["link"].rsplit("/", 1)[-1]
    own = folder_video(item)
    if own and item["kind_pref"] in ("", "video") and can_host("video"):
        import video_tools
        return [video_tools.mute_video(own, f"{key}_threads")], "video"
    photos = image_tools.load_photos(item["source"], item["name"])
    image_tools.OUT_DIR.mkdir(exist_ok=True)
    paths = []
    for i, im in enumerate(photos[:10], start=1):
        p = image_tools.OUT_DIR / f"{image_tools.slug(key)}_threads_{i:02d}.jpg"
        im.convert("RGB").save(p, quality=92)
        paths.append(p)
    return paths, ("carousel" if len(paths) > 1 else "image")


def resolve_threads_media(item):
    """쓰레드 원본 미디어 공개 주소와 형식. 없거나 실패하면 ([], 'text')."""
    if not threads_media():
        return [], "text"
    try:
        import image_tools
        files, kind = threads_raw_media(item)
        if not files or not can_host(kind):
            return [], "text"
        return [f if isinstance(f, str) else image_tools.upload(f) for f in files], kind
    except Exception as e:
        log(f"  ✗ 쓰레드 사진·영상 준비 실패, 글만 올립니다: {e}")
        return [], "text"


def resolve_media(item, kind, text):
    """게시에 쓸 공개 주소 목록."""
    import image_tools
    return [m if isinstance(m, str) and m.startswith("http") else image_tools.upload(m)
            for m in local_media(item, kind, text)]


def local_cover(item, text):
    """릴스 커버 이미지 파일. 폴더의 커버.jpg가 있으면 그것, 없으면 첫 사진(없으면 영상 1초 장면)으로 만든다."""
    import image_tools
    from PIL import Image
    key = item["link"].rsplit("/", 1)[-1]
    folder = image_tools.photo_root() / image_tools.folder_name(item["name"])
    own = image_tools.cover_file_in(folder)
    if own:
        print(f"  (폴더에 넣은 커버 사용: {own.name})")
        with Image.open(own) as im:
            return image_tools.make_reel_cover(item["short"], text["headline"], own=im.copy(), key=key)
    photos = [] if media_list(item) else image_tools.load_photos(item["source"], item["name"])
    photo = photos[0] if photos else None
    vid = folder_video(item)
    if photo is None and vid:
        import video_tools
        photo = video_tools.grab_frame(vid, key)
    return image_tools.make_reel_cover(item["short"], text["headline"], photo, key=key)


def resolve_cover(item, text):
    """릴스 커버 공개 주소. 만들거나 올리지 못하면 None(인스타가 첫 장면을 커버로 씀)."""
    try:
        import image_tools
        return image_tools.upload(local_cover(item, text))
    except Exception as e:
        log(f"  (커버를 만들지 못해 첫 장면을 커버로 씁니다: {e})")
        return None


# ---------------------------------------------------------------- 게시
def wait_container(url, params, field, ok, timeout):
    """게시물 준비(특히 영상 처리)가 끝날 때까지 기다린다."""
    waited = 0
    while waited < timeout:
        time.sleep(5)
        waited += 5
        s = requests.get(url, params=params, timeout=60)
        check(s, "처리 상태 확인")
        status = s.json().get(field)
        if status in ok:
            return
        if status in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"미디어 처리 실패({status}): {s.text[:300]}")
    raise RuntimeError("미디어 처리 시간이 너무 오래 걸립니다. 다음 실행 때 다시 시도합니다.")


def threads_post(text, urls=None, kind="image", reply_to=None):
    ver = env("THREADS_API_VERSION", "v1.0")
    uid, tok = env("THREADS_USER_ID"), env("THREADS_ACCESS_TOKEN")
    base = f"https://graph.threads.net/{ver}"
    urls = urls or []

    def create(data, timeout=120):
        r = requests.post(f"{base}/{uid}/threads", data={**data, "access_token": tok}, timeout=60)
        check(r, "쓰레드 게시물 준비")
        cid = r.json()["id"]
        wait_container(f"{base}/{cid}", {"fields": "status,error_message", "access_token": tok},
                       "status", ("FINISHED",), timeout)
        return cid

    if kind == "carousel" and len(urls) > 1:
        children = [create({"media_type": "IMAGE", "image_url": u, "is_carousel_item": "true"})
                    for u in urls[:20]]
        cid = create({"media_type": "CAROUSEL", "children": ",".join(children), "text": text})
    elif urls and kind == "video":
        cid = create({"media_type": "VIDEO", "video_url": urls[0], "text": text}, 600)
    elif urls:
        cid = create({"media_type": "IMAGE", "image_url": urls[0], "text": text})
    elif reply_to:
        cid = create({"media_type": "TEXT", "text": text, "reply_to_id": reply_to})
    else:
        cid = create({"media_type": "TEXT", "text": text})
    r = requests.post(f"{base}/{uid}/threads_publish",
                      data={"creation_id": cid, "access_token": tok}, timeout=60)
    check(r, "쓰레드 게시")
    return r.json()["id"]


def threads_reply(rec, text, item):
    """방금 올린 쓰레드 글에 첫 댓글을 단다. 실패해도 본글은 그대로 둔다."""
    body = compose_threads_reply(text, item["link"], item["aff"]["disclosure"])
    if not body:
        return
    time.sleep(int(env("THREADS_REPLY_DELAY", "20") or 20))  # 본글이 반영될 시간을 조금 준다
    try:
        rec["reply"] = threads_post(body, reply_to=rec["id"])
        log(f"  ✓ threads 댓글 완료 (id {rec['reply']})")
    except Exception as e:
        log(f"  ✗ threads 댓글: {e} (메타 앱 권한에 threads_manage_replies가 있는지 확인)")


def instagram_post(urls, caption, kind="image", cover=None):
    ver = env("IG_API_VERSION", "v23.0")
    uid, tok = env("IG_USER_ID"), env("IG_ACCESS_TOKEN")
    host = f"https://graph.instagram.com/{ver}"

    def create(data, timeout=120):
        r = requests.post(f"{host}/{uid}/media", data={**data, "access_token": tok}, timeout=60)
        check(r, "인스타그램 게시물 준비")
        cid = r.json()["id"]
        wait_container(f"{host}/{cid}", {"fields": "status_code", "access_token": tok},
                       "status_code", ("FINISHED",), timeout)
        return cid

    if kind == "carousel" and len(urls) > 1:
        children = [create({"image_url": u, "is_carousel_item": "true"}) for u in urls[:10]]
        cid = create({"media_type": "CAROUSEL", "children": ",".join(children), "caption": caption})
    elif kind == "video":
        data = {"media_type": "REELS", "video_url": urls[0], "share_to_feed": "true", "caption": caption}
        if cover:
            data["cover_url"] = cover
        cid = create(data, 600)
    else:
        cid = create({"image_url": urls[0], "caption": caption})
    r = requests.post(f"{host}/{uid}/media_publish",
                      data={"creation_id": cid, "access_token": tok}, timeout=60)
    check(r, "인스타그램 게시")
    return r.json()["id"]


# ---------------------------------------------------------------- 실행
KIND_LABEL = {"video": "영상(릴스)", "carousel": "캐러셀(여러 장)", "image": "이미지 1장"}


def preview(item, kind, text):
    print("\n========== 쓰레드 미리보기 ==========")
    print(compose_threads(text["threads"], item["link"], item["aff"]["disclosure"]))
    reply = compose_threads_reply(text, item["link"], item["aff"]["disclosure"])
    if reply:
        print("\n---------- 쓰레드 첫 댓글 ----------")
        print(reply)
    print("\n========== 인스타그램 미리보기 ==========")
    print(compose_instagram(text, item["short"], item["aff"]["disclosure"]))
    print(f"\n========== {KIND_LABEL[kind]} ==========")
    if kind == "video" and not item["media"]:
        print("(영상 만드는 중… 10~30초)")
    paths = local_media(item, kind, text)
    for p in paths:
        print(f"  {p}")
    if kind == "video":
        print(f"  릴스 커버: {local_cover(item, text)}")
    local = [p for p in paths if not isinstance(p, str)]
    if os.name == "nt" and local:
        # 캐러셀은 폴더를, 그 외에는 파일을 바로 열어 보여줌
        os.startfile(local[0].parent if kind == "carousel" and len(local) > 1 else local[0])
    if not media_possible(item, kind):
        print("※ 업로드 키(CLOUDINARY_URL)가 없어 실제 게시 때는 인스타그램을 건너뜁니다.")
    print()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="게시하지 않고 미리보기만")
    ap.add_argument("--count", type=int, default=int(env("POSTS_PER_RUN", "1") or 1))
    ap.add_argument("--slot", default="", help="예약 회차(예: 2026-10-17 07:00). 게시 기록에 남겨 같은 회차를 다시 올리지 않게")
    args = ap.parse_args()
    if args.slot:
        posted = load_posted()
        posted.setdefault("_meta", {})["last_slot"] = args.slot
        save_posted(posted)  # 실패해도 같은 회차를 매시간 다시 시도하지 않도록 먼저 기록

    now = datetime.datetime.now()
    items = load_products()
    posted = load_posted()
    import accounts
    nums = accounts.listing()
    code = 0
    for n in nums:
        accounts.use(n)
        mine = [i for i in items if accounts.route(i["category"]) == n]
        if len(nums) > 1 or args.dry_run:
            log(f"[{accounts.label(n)}] 상품 {len(mine)}개 · 연결: {accounts.whoami()}")
        code = post_items(mine, posted, args, now, n) or code
    accounts.use(1)
    return code


def post_items(items, posted, args, now, account=1):
    """한 계정(쓰레드+인스타)에 올릴 상품들 중 다음 상품을 게시한다."""
    if not args.dry_run and not threads_on() and not ig_on():
        log("게시할 채널 정보가 없습니다. .env 파일의 쓰레드/인스타그램 항목을 채워 주세요.")
        return 1

    done = 0
    for item in queue(items, now):
        if done >= args.count:
            break
        rec = get_rec(posted, item)
        kind = decide_kind(item, posted)
        if args.dry_run:
            if not never_posted(rec):
                continue
            channels = ["미리보기"]
        else:
            channels = pending_channels(item, rec, kind)
        if not channels:
            continue

        label = KIND_LABEL[kind]
        log(f"상품: {item['name']} [{label}] → {', '.join(channels)}")
        if item["memo"]:
            remember_memo(item)
        else:
            facts = research(item)
            if facts:
                item["memo"] = facts
                log(f"  🔎 자동 조사한 특징: {facts}")
            else:
                log("  🔎 자동 조사로 특징을 찾지 못해 상품명만으로 작성합니다 "
                    "(상품명에 브랜드·제품명을 정확히 넣으면 잘 찾습니다)")
        try:
            text = generate(item)
        except Exception as e:
            log(f"  ✗ {e}")
            return 1

        if args.dry_run:
            try:
                preview(item, kind, text)
            except Exception as e:
                log(f"  ✗ 미리보기 실패: {e}")
            done += 1
            continue

        urls = []
        if media_possible(item, kind) and "instagram" in channels:
            try:
                urls = resolve_media(item, kind, text)
            except Exception as e:
                log(f"  ✗ {label} 준비 실패: {e}")
        cover = resolve_cover(item, text) if urls and kind == "video" and "instagram" in channels else None

        ok = False
        for ch in channels:
            try:
                if ch == "threads":
                    t_urls, t_kind = resolve_threads_media(item)
                    pid = threads_post(compose_threads(text["threads"], item["link"], item["aff"]["disclosure"]),
                                       t_urls, t_kind)
                else:
                    if not urls:
                        raise RuntimeError(f"{label}이(가) 없어 인스타그램에 올릴 수 없습니다.")
                    pid = instagram_post(urls, compose_instagram(text, item["short"], item["aff"]["disclosure"]),
                                         kind, cover)
                used = (t_kind if t_urls else "text") if ch == "threads" else (kind if urls else "text")
                rec[ch] = {"id": pid, "kind": used,
                           "at": datetime.datetime.now().isoformat(timespec="seconds")}
                ok = True
                log(f"  ✓ {ch} 게시 완료 (id {pid})")
                if ch == "threads":
                    threads_reply(rec[ch], text, item)
            except Exception as e:
                fails = rec.setdefault("fails", {})
                fails[ch] = fails.get(ch, 0) + 1
                log(f"  ✗ {ch}: {e}")

        rec["name"] = item["name"]
        rec["link"] = item["link"]
        rec["account"] = account
        for k in [k for k, v in posted.items() if v is rec and k != posted_key(item)]:
            posted.pop(k)  # 예전 링크 기준 기록은 상품명 기준으로 옮김
        posted[posted_key(item)] = rec
        if ok and urls:
            posted.setdefault("_meta", {})["last_kind"] = "video" if kind == "video" else "image"
        save_posted(posted)
        done += 1

    if done == 0:
        upcoming = [i for i in items if i["when"] and i["when"] > now
                    and never_posted(get_rec(posted, i))]
        if upcoming:
            nxt = min(upcoming, key=lambda i: i["when"])
            log(f"지금 올릴 상품이 없습니다. 다음 예약: {nxt['when']:%m/%d %H:%M} '{nxt['name']}'")
        else:
            log("새로 올릴 상품이 없습니다. products.csv에 상품을 추가해 주세요.")
    elif not args.dry_run:
        left = sum(1 for i in items if never_posted(get_rec(posted, i)))
        log(f"남은 상품: {left}개" + (" — 상품을 더 추가해 주세요." if left < 3 else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
