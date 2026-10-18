# -*- coding: utf-8 -*-
"""블로그(네이버·티스토리) 글 자동 작성: 글감 고르기 → 최신 정보 검색 → 글 쓰기 → 이미지 → 스튜디오 패키지.

  python blog_auto.py --site 폴더           : blog_config.json의 블로그마다 posts_per_blog편씩 만들기
  python blog_auto.py --site 폴더 --blog naver2 --count 1
  python blog_auto.py --site 폴더 --dry-run : 기록(글감 이력)은 남기지 않고 만들어 보기
  python blog_auto.py --site 폴더 --drafts  : drafts/ 폴더의 초안(Claude가 쓴 글)에 사진만 붙여 패키지로
  python blog_auto.py --site 폴더 --scheduled : 예약 실행. 초안을 먼저 정리하고, 오늘 글이 없는 블로그만 제미나이로 채움

결과는 --site 폴더(서버에서는 blog-packages 브랜치)에 날짜/블로그-번호/ 로 쌓이고, index.json에 목록이 적힌다.
스튜디오의 '서버에서 불러오기'가 index.json을 읽어 content.json과 이미지를 그대로 불러온다.
발행은 사람이 직접 한다 (네이버·티스토리 모두 글쓰기 API가 없음).

글은 제미나이(무료 키, 구글 검색 사용)로 쓰고, 제미나이 키가 없거나 BLOG_WRITER=claude면 Claude(웹 검색)로 쓴다.
글감: 시트 '블로그글감' 탭(블로그·주제 칸, 위에서부터 아직 안 쓴 것) → 없으면 AI가 블로그 주제에 맞춰 고름.
"""
import argparse
import datetime
import json
import os
import pathlib
import re
import shutil
import sys

import main
from main import env, log

BASE = pathlib.Path(__file__).resolve().parent
STOCK = "stock"
CONFIG = BASE / "blog_config.json"
SHEET_TAB = "블로그글감"
WEEKDAYS = "월화수목금토일"

TONES = [
    "친근한 해요체 대화형. 독자가 궁금해할 질문을 던지고 바로 답하는 흐름.",
    "담백한 정리형. 짧은 문장 위주로 핵심부터 말하고 설명은 뒤에.",
    "비교·분석형. 장단점과 고르는 기준을 보여 주고, 표로 한눈에 비교.",
    "문제 해결형. 독자가 겪는 상황 → 왜 그런지 → 어떻게 하면 되는지 순서.",
    "체크리스트·Q&A형. 자주 묻는 질문을 소제목으로 삼아 하나씩 답.",
]

TOPIC_PROMPT = """오늘은 {today} 한국 날짜다. 너는 '{name}' {platform} 블로그 운영자를 돕는다.
블로그 주제: {theme}

구글 검색으로 최근 1~2주 안에 나온 소식이나, 지금 시기에 한국 사람들이 많이 찾아볼 정보를 확인한 뒤
오늘 쓸 블로그 글감 {count}개를 골라라.

조건
- 구체적인 글감: 서비스·제품·제도 이름, 날짜, 금액, 조건처럼 사실로 확인할 수 있는 내용이 있는 것.
- 이미 지난 일(출시, 신청 마감, 행사)을 앞으로 할 일처럼 고르지 마라. 날짜를 오늘과 꼭 비교해라.
- 최근에 쓴 글감과 겹치지 마라: {recent}
- 여러 개면 서로 다른 카테고리로.
- 특정 상품 광고·구매 권유 글감은 고르지 마라.
{fixed}
각 글감마다
  topic: 글감 한 줄
  category: {cats} 중 하나를 글자 그대로
  angle: 글에서 다룰 내용 한 줄 (독자가 얻는 것 위주)
  photo: 무료 사진 사이트에서 찾을 영어 검색어 2~3단어 (사람 얼굴보다 물건·장면, 상표 이름 금지)
  urgent: 빨리 올려야 의미 있는 글(신청 마감, 출시·행사 소식처럼 날짜가 지나면 쓸모가 줄어드는 글)이면 true, 언제 올려도 되는 글이면 false
  until: urgent가 true이고 날짜가 확인되면 그 글이 쓸모 있는 마지막 날 YYYY-MM-DD, 아니면 ""

다른 말 없이 JSON 배열만 출력: [{{"topic": "...", "category": "...", "angle": "...", "photo": "...", "urgent": true, "until": ""}}]"""

WRITE_PROMPT = """오늘은 {today} 한국 날짜다. '{name}' {platform} 블로그에 올릴 글을 한국어로 써라.
글감: {topic}
다룰 내용: {angle}
카테고리: {category}

먼저 검색으로 이 글감의 최신 사실(날짜, 금액, 조건, 기능, 요금제)을 확인하고, 확인한 사실만 써라.
확인하지 못한 숫자는 쓰지 마라. 이미 지난 일정은 지난 일로 써라.

길이: 공백을 뺀 글자 수로 {min}~{max}자 (표 안의 글자 포함). {min}자보다 짧으면 안 된다.
말투와 구성: {tone}

문체
- 사람이 쓴 블로그 글처럼 자연스럽게. 짧은 문장과 긴 문장을 섞고, 문단 첫머리를 매번 다르게 시작해라.
- 쓰지 말 것: "~에 대해 알아보겠습니다", "결론적으로", "~하는 것이 중요합니다", "도움이 되셨길 바랍니다",
  "다양한·효율적인·혁신적인" 남발, 소제목마다 끝에 요약 문장, 모든 목록을 3개로 맞추기.
- 직접 써 봤다는 경험담은 절대 지어내지 마라. "공식 안내를 보면", "찾아보니" 같은 표현은 괜찮다.
- 막연한 칭찬 대신 구체적인 숫자, 메뉴 이름, 요금, 날짜.
- 이모지와 해시태그는 본문에 쓰지 마라. 특정 상품 구매 권유도 하지 마라.

형식: 아래 표시만 써라. 마크다운 제목(#), 코드 블록(```), 굵은 소제목은 쓰지 마라.
@title: 제목 (검색할 핵심어를 앞쪽에, 25~40자)
@tags: 태그 8~10개, 쉼표로 구분, # 없이
(빈 줄 없이 바로 본문. 첫 문단은 소제목 없이 시작)
## 소제목              ← 3~5개
### 작은 소제목        ← 필요할 때만
문단은 한 줄에 하나
- 목록 한 줄
| 칸 | 칸 | 칸          ← 표 1개 이상, 첫 줄이 제목줄, 한 줄에 한 행, 칸을 비우지 말 것(없으면 -)
> 인용 상자에 넣을 한 줄 (1개)
! 강조 상자에 넣을 주의·팁 한 줄 (1~2개)
**핵심 문구**는 소제목마다 1~2개만
[사진: 영어 검색어 2~3단어 | 사진 설명]          ← 본문 중간에 1개
[카드: 카드 제목 | 줄1 / 줄2 / 줄3 / 줄4 | 이미지 설명]   ← 핵심 정리 카드 1개, 줄마다 20자 이내
출처: 참고한 기관·언론사 이름 (마지막 줄, 주소 말고 이름만)"""

FIX_PROMPT = """아래 블로그 글은 공백을 뺀 글자 수가 {n}자다. {need}
형식 표시(@title, @tags, ##, -, |, >, !, **, [사진: ...], [카드: ...], 출처:)와 사실은 그대로 두고,
확인되지 않은 새 숫자나 경험담은 넣지 마라. 고친 글 전체만 출력해라.

{text}"""


# ---------------------------------------------------------------- AI 호출
def ask(prompt, search=True, temperature=0.8):
    """글자 답을 돌려준다. 제미나이(구글 검색) 우선, BLOG_WRITER=claude거나 제미나이 키가 없으면 Claude(웹 검색)."""
    import memo_ai
    if env("BLOG_WRITER", "제미나이").lower() != "claude" and memo_ai.env("GEMINI_API_KEY"):
        return memo_ai.generate([{"text": prompt}], json_out=False, temperature=temperature, search=search)
    if not env("ANTHROPIC_API_KEY"):
        raise RuntimeError("제미나이 키나 Claude 키가 있어야 블로그 글을 쓸 수 있습니다.")
    payload = {"model": env("BLOG_CLAUDE_MODEL") or env("CLAUDE_MODEL", "claude-haiku-5-5"), "max_tokens": 8000,
               "messages": [{"role": "user", "content": prompt}]}
    if search:
        payload["tools"] = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 5,
                             "user_location": {"type": "approximate", "country": "KR", "timezone": "Asia/Seoul"}}]
    r = main._ask_ai(payload)
    main.check(r, "Claude 블로그 글")
    blocks = r.json().get("content", [])
    last = max([i for i, b in enumerate(blocks) if b.get("type") == "web_search_tool_result"], default=-1)
    return "".join(b.get("text", "") for b in blocks[last + 1:] if b.get("type") == "text")


def json_array(text):
    s, e = text.find("["), text.rfind("]")
    if s < 0 or e < 0:
        raise RuntimeError(f"AI 답에서 글감 목록을 찾지 못했습니다: {text[:200]}")
    data = json.loads(text[s:e + 1], strict=False)
    return [d for d in data if isinstance(d, dict) and d.get("topic")]


# ---------------------------------------------------------------- 글감
def sheet_topics(blog):
    """시트 '블로그글감' 탭에서 이 블로그의 아직 안 쓴 주제 → [(행 번호, 주제)]."""
    try:
        import gcloud
        if not gcloud.enabled():
            return []
        rows = gcloud.read_tab(SHEET_TAB)
    except Exception:
        return []
    if not rows:
        return []
    head = [h.strip() for h in rows[0]]
    if "주제" not in head:
        return []
    ti = head.index("주제")
    bi = head.index("블로그") if "블로그" in head else None
    di = head.index("작성일") if "작성일" in head else None
    names = {blog["key"], blog["name"], blog["name"].replace(" ", "")}
    out = []
    for n, r in enumerate(rows[1:], start=2):
        r = r + [""] * (len(head) - len(r))
        if not r[ti].strip() or (di is not None and r[di].strip()):
            continue
        if bi is not None and r[bi].strip() and r[bi].strip().replace(" ", "") not in {x.replace(" ", "") for x in names}:
            continue
        if bi is None and blog["key"] != "tistory":
            continue  # '블로그' 칸이 없으면 첫 블로그(티스토리) 글감으로만 쓴다
        out.append((n, r[ti].strip()))
    return out


def mark_sheet(row, when):
    try:
        import gcloud
        rows = gcloud.read_tab(SHEET_TAB)
        head = [h.strip() for h in rows[0]]
        if "작성일" not in head:
            gcloud.write_cell(1, len(head) + 1, "작성일", SHEET_TAB)
            col = len(head) + 1
        else:
            col = head.index("작성일") + 1
        gcloud.write_cell(row, col, when, SHEET_TAB)
    except Exception as e:
        log(f"  (블로그글감 탭에 작성일을 적지 못했습니다: {e})")


def pick_topics(blog, count, recent, today):
    fixed = sheet_topics(blog)[:count]
    lines = "\n".join(f"- 이 글감은 꼭 넣어라: {t}" for _, t in fixed)
    text = ask(TOPIC_PROMPT.format(today=today, name=blog["name"], platform=platform_k(blog), theme=blog["theme"],
                                   count=count, recent=", ".join(recent[-30:]) or "없음", fixed=lines,
                                   cats=", ".join(blog["categories"])), temperature=0.9)
    topics = json_array(text)[:count]
    for t, (row, _) in zip(topics, fixed):
        t["sheet_row"] = row
    for t in topics:
        if t.get("category") not in blog["categories"]:
            t["category"] = blog["categories"][0]
    return topics


def platform_k(blog):
    return "티스토리" if blog["platform"] == "tistory" else "네이버"


# ---------------------------------------------------------------- 글
def clean(text):
    lines = []
    for ln in text.replace("\r", "").splitlines():
        s = ln.strip()
        if s.startswith("```") or not s:
            continue
        s = re.sub(r"^#{1,3}\s*(?=@)", "", s)
        s = re.sub(r"^\*\*(@\w+)\s*\*\*", r"\1", s)
        s = re.sub(r"^(@\w+)\s*[:：]\s*", r"\1: ", s)
        s = re.sub(r"^\*\*(##+ .+?)\*\*$", r"\1", s)
        s = re.sub(r"\[\d+(, ?\d+)*\]", "", s)  # 검색 인용 번호 [1] 지우기
        lines.append(s)
    return "\n".join(lines)


def body_chars(text):
    """공백을 뺀 본문 글자 수 (표시 기호·이미지 줄·제목·태그 제외, 표 글자 포함)."""
    n = 0
    for ln in text.splitlines():
        if ln.startswith(("@", "[사진", "[카드")):
            continue
        ln = re.sub(r"^(###|##|>|!|-)\s*", "", ln).replace("**", "").replace("|", "")
        n += len(re.sub(r"\s", "", ln))
    return n


def write_post(blog, topic, tone, cfg, today):
    lo, hi = cfg.get("min_chars", 1500), cfg.get("max_chars", 2000)
    text = clean(ask(WRITE_PROMPT.format(today=today, name=blog["name"], platform=platform_k(blog),
                                         topic=topic["topic"], angle=topic.get("angle", ""),
                                         category=topic["category"], min=lo, max=hi, tone=tone)))
    for _ in range(2):
        n = body_chars(text)
        if lo <= n <= hi + 300:
            break
        need = (f"{lo + 150}자 정도가 되게 내용을 늘려라. 이미 쓴 사실을 더 자세히 풀거나, 독자가 실제로 해 볼 순서·주의점을 더해라."
                if n < lo else f"{hi - 100}자 정도가 되게 줄여라. 겹치는 설명부터 빼라.")
        log(f"    글자 수 {n}자 → 다시 쓰기")
        fixed = clean(ask(FIX_PROMPT.format(n=n, need=need, text=text), search=False, temperature=0.6))
        if "@title" in fixed and body_chars(fixed) > 200:
            text = fixed
    return text


# ---------------------------------------------------------------- 패키지
def parse(text, blog, topic):
    """글(표시 기호)을 스튜디오 content.json 블록으로. 이미지 자리는 images에 계획만 적는다."""
    meta, blocks, images, table = {}, [], [], None
    prefix = "b" if blog["platform"] == "tistory" else "n"

    def add(btype, text=None, **extra):
        b = {"id": f"{prefix}{len(blocks) + 1:03d}", "type": btype}
        if text is not None:
            marks = [m for m in re.findall(r"\*\*(.+?)\*\*", text) if m.strip()]
            b["text"] = text.replace("**", "").strip()
            if marks:
                b["marks"] = marks[:3]
        b.update(extra)
        blocks.append(b)

    def flush():
        nonlocal table
        if table and len(table) > 1:
            width = len(table[0])
            add("TABLE", headers=table[0],  # 빈 칸은 '-'로: 네이버에 붙일 때 끝의 빈 칸이 빠져 표가 깨짐
                rows=[[c or "-" for c in (r + [""] * width)[:width]] for r in table[1:]])
        table = None

    for line in text.splitlines():
        if line.startswith("|"):
            cells = [c.strip().replace("**", "") for c in line.strip().strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                continue  # 마크다운 표의 구분 줄
            table = (table or []) + [cells]
            continue
        flush()
        m = re.match(r"^\[(사진|카드)\s*[:：]\s*(.+)\]$", line)
        if line.startswith("@") and ":" in line:
            k, v = line[1:].split(":", 1)
            meta[k.strip()] = v.strip()
        elif m:
            parts = [p.strip() for p in m.group(2).split("|")]
            img = {"kind": "photo" if m.group(1) == "사진" else "card", "parts": parts,
                   "after": blocks[-1]["id"] if blocks else None}
            images.append(img)
        elif line.startswith("### "):
            add("H3", line[4:])
        elif line.startswith("## "):
            add("H2", line[3:])
        elif line.startswith("> "):
            add("QUOTE", line[2:])
        elif line.startswith("!"):
            add("HIGHLIGHT", line[1:].strip())
        elif line.startswith(("- ", "• ", "* ")):
            add("PARAGRAPH", "• " + line[2:].strip())
        elif line.startswith("출처"):
            add("PARAGRAPH", line, size="small")
        else:
            add("PARAGRAPH", line)
    flush()
    title = meta.get("title") or topic["topic"]
    tags = [t.strip().lstrip("#") for t in re.split(r"[,，]", meta.get("tags", "")) if t.strip()][:10]
    return title, tags, blocks, images


def build_package(folder, blog, topic, text, used_photos):
    import blog_images
    title, tags, blocks, plan = parse(text, blog, topic)
    if not any(b["type"] == "H2" for b in blocks):
        raise RuntimeError("AI가 쓴 글에 소제목이 없어 형식이 깨진 것 같습니다.")
    folder.mkdir(parents=True, exist_ok=True)
    h2 = [b["id"] for b in blocks if b["type"] == "H2"]
    if not any(p["kind"] == "photo" for p in plan):  # 사진 자리가 없으면 두 번째 소제목 앞에
        at = [b["id"] for b in blocks].index(h2[1] if len(h2) > 1 else h2[0])
        plan.append({"kind": "photo", "parts": [topic.get("photo", ""), topic["topic"]],
                     "after": blocks[max(0, at - 1)]["id"]})
    order = [b["id"] for b in blocks]
    plan.sort(key=lambda p: order.index(p["after"]) if p["after"] in order else -1)
    images = []

    def get_photo(query):
        try:
            return blog_images.find_photo(query, used_photos)
        except Exception as e:
            log(f"    (사진을 찾지 못했습니다: {e})")
            return None, None

    im, pid = get_photo(topic.get("photo", ""))
    if pid:
        used_photos.append(pid)
    blog_images.cover(folder / "01-cover.jpg", title, topic["category"], im)
    images.append({"id": "img1", "file": "01-cover.jpg", "alt": title, "role": "COVER"})
    n = 1
    for p in plan:
        if not p["after"]:
            continue
        n += 1
        if p["kind"] == "photo":
            im, pid = get_photo(p["parts"][0] if p["parts"] else topic.get("photo", ""))
            if im is None:
                n -= 1
                continue
            used_photos.append(pid)
            name = f"{n:02d}-photo.jpg"
            blog_images.photo(folder / name, im)
            alt = p["parts"][1] if len(p["parts"]) > 1 else topic["topic"]
        else:
            ctitle = p["parts"][0] if p["parts"] else title
            lines = [s.strip() for s in (p["parts"][1] if len(p["parts"]) > 1 else "").split("/")]
            name = f"{n:02d}-card.png"
            blog_images.card(folder / name, ctitle, lines)
            alt = p["parts"][2] if len(p["parts"]) > 2 else ctitle
        images.append({"id": f"img{n}", "file": name, "alt": alt, "anchorBlockId": p["after"],
                       "position": "after_block"})
        if n >= 3:
            break
    pkg = {"schemaVersion": 1, "platform": blog["platform"], "blogName": blog["name"],
           "category": topic["category"], "title": title, "tags": tags, "blocks": blocks, "images": images}
    (folder / "content.json").write_text(json.dumps(pkg, ensure_ascii=False, indent=1), encoding="utf-8")
    return pkg


# ---------------------------------------------------------------- 실행
def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def prune(site, index, keep_days):
    cutoff = (datetime.date.today() - datetime.timedelta(days=keep_days)).isoformat()
    for d in site.iterdir():
        if d.is_dir() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", d.name) and d.name < cutoff:
            shutil.rmtree(d)
    index["packages"] = [p for p in index["packages"] if p["date"] >= cutoff]


def quota_hit(e):
    """제미나이 무료 한도(분당·하루)에 걸렸는지. 걸렸으면 남은 글은 쓰지 않고 멈춘다 (쿠팡 자동화 몫을 남기려고)."""
    return "한도" in str(e)


def find_blog(cfg, name):
    n = name.replace(" ", "")
    return next((b for b in cfg["blogs"] if n in (b["key"], b["name"].replace(" ", ""))), None)


def next_id(index, date, key):
    existing = {p["id"] for p in index["packages"]}
    k = 1
    while f"{date}/{key}-{k}" in existing:
        k += 1
    return f"{date}/{key}-{k}"


def urgency(topic):
    """급함(날짜가 지나면 쓸모가 줄어드는 글)인지와 그 마지막 날. 시간 여유가 있는 글은 (False, "")."""
    u = topic.get("urgent", False)
    if isinstance(u, str):
        u = u.strip().lower() in ("true", "1", "yes", "급함", "급", "신속")
    until = str(topic.get("until") or "").strip()
    return bool(u), until if re.fullmatch(r"\d{4}-\d{2}-\d{2}", until) else ""


def add_to_index(index, pid, date, blog, pkg, text, writer, now, topic=None):
    chars = body_chars(text)
    urgent, until = urgency(topic or {})
    index["packages"].insert(0, {"id": pid, "date": date, "blogKey": blog["key"], "blogName": blog["name"],
                                 "platform": blog["platform"], "category": pkg["category"],
                                 "title": pkg["title"], "chars": chars, "writer": writer,
                                 "urgent": urgent, "until": until,
                                 "files": ["content.json"] + [i["file"] for i in pkg["images"]],
                                 "createdAt": now.isoformat(timespec="seconds")})
    log(f"  ✓ {pkg['title']} (공백 제외 {chars}자, 이미지 {len(pkg['images'])}장)")


def draft_package(path, site, cfg, index, hist, used_photos, now, date=None):
    """초안 파일 하나에 사진·카드를 붙여 패키지로 만들고 지운다. 성공하면 True.
    초안 머리: @blog(key 또는 이름) @category @topic @photo(대표 사진 영어 검색어) @title @tags, 그 아래는 본문 형식 그대로.
    @urgent: 급함(빨리 올릴 글)이면 급함, 아니면 상시(생략해도 상시). @until: 급한 글이 쓸모 있는 마지막 날 YYYY-MM-DD."""
    text = clean(path.read_text(encoding="utf-8"))
    meta = dict(ln[1:].split(": ", 1) for ln in text.splitlines() if ln.startswith("@") and ": " in ln)
    blog = find_blog(cfg, meta.get("blog", ""))
    if not blog:
        log(f"  ! 초안 {path.name}: 블로그 '{meta.get('blog')}'를 blog_config.json에서 찾지 못했습니다")
        return False
    if not date:
        date = path.parent.name if re.fullmatch(r"\d{4}-\d{2}-\d{2}", path.parent.name) else now.strftime("%Y-%m-%d")
    cat = meta.get("category", "")
    topic = {"topic": meta.get("topic") or meta.get("title", path.stem),
             "category": cat if cat in blog["categories"] else blog["categories"][0],
             "photo": meta.get("photo", ""), "urgent": meta.get("urgent", ""), "until": meta.get("until", "")}
    pid = next_id(index, date, blog["key"])
    log(f"[{blog['name']}] 초안 정리: {path.parent.name}/{path.name}")
    try:
        pkg = build_package(site / pid, blog, topic, text, used_photos)
    except Exception as e:
        log(f"  ! 초안을 패키지로 만들지 못했습니다: {e}")
        shutil.rmtree(site / pid, ignore_errors=True)
        return False
    add_to_index(index, pid, date, blog, pkg, text, "Claude", now, topic)
    h = hist.setdefault(blog["key"], {"topics": [], "tone": -1})
    h["topics"] = (h["topics"] + [topic["topic"]])[-60:]
    path.unlink()
    return True


def process_drafts(site, cfg, index, hist, used_photos, now):
    """drafts/날짜/*.txt (Claude가 쓴 그날 글)를 패키지로 만든다. drafts/stock/은 비상용이라 여기서는 건드리지 않는다."""
    made = failed = 0
    for path in sorted((site / "drafts").glob("**/*.txt")):
        if STOCK in path.parts:
            continue
        if draft_package(path, site, cfg, index, hist, used_photos, now):
            made += 1
        else:
            failed += 1
    for d in sorted((site / "drafts").glob("*"), reverse=True):
        if d.is_dir() and d.name != STOCK and not any(d.iterdir()):
            d.rmdir()
    return made, failed


def use_stock(site, blog, n, cfg, index, hist, used_photos, now):
    """오늘 글이 빈 블로그에 비상용 글(drafts/stock/<key>-*.txt, 날짜와 상관없는 글)을 n편까지 꺼내 쓴다."""
    made = 0
    for path in sorted((site / "drafts" / STOCK).glob(f"{blog['key']}-*.txt"))[:n]:
        if draft_package(path, site, cfg, index, hist, used_photos, now, now.strftime("%Y-%m-%d")):
            made += 1
    return made


def run(site, only=None, count=None, dry=False, scheduled=False, drafts_only=False):
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    if env("BLOG_GEMINI_API_KEY"):  # 블로그 전용 제미나이 키(다른 구글 계정)가 있으면 쿠팡 자동화와 한도를 나눠 쓰지 않음
        os.environ["GEMINI_API_KEY"] = env("BLOG_GEMINI_API_KEY")
    site.mkdir(parents=True, exist_ok=True)
    hist_path, index_path = site / "history.json", site / "index.json"
    hist = load_json(hist_path, {})
    index = load_json(index_path, {"packages": []})
    now = datetime.datetime.now()
    date = now.strftime("%Y-%m-%d")
    today = f"{now:%Y년 %m월 %d일} ({WEEKDAYS[now.weekday()]})"
    used_photos = hist.setdefault("_photos", [])
    made, failed = process_drafts(site, cfg, index, hist, used_photos, now)
    stop = drafts_only
    for blog in cfg["blogs"]:
        if only and blog["key"] not in only:
            continue
        if stop and not scheduled:
            break
        if scheduled and any(p["date"] == date and p["blogKey"] == blog["key"] for p in index["packages"]):
            log(f"[{blog['name']}] 오늘 글이 이미 있어 건너뜁니다")
            continue
        h = hist.setdefault(blog["key"], {"topics": [], "tone": -1})
        n_posts = count or int(env("BLOG_POSTS_PER_BLOG") or cfg.get("posts_per_blog", 2))
        if scheduled:  # 새벽 글이 빠진 날: 쌓아 둔 비상용 글이 있으면 그것부터 (제미나이 한도를 아낌)
            got = use_stock(site, blog, n_posts, cfg, index, hist, used_photos, now)
            made += got
            n_posts -= got
            if n_posts <= 0:
                continue
        if stop:  # 제미나이 한도에 걸린 뒤로는 비상용 글만 꺼냄
            continue
        log(f"[{blog['name']}] 글감 고르는 중")
        try:
            topics = pick_topics(blog, n_posts, h["topics"], today)
        except Exception as e:
            log(f"  ! 글감을 고르지 못했습니다: {e}")
            failed += 1
            stop = quota_hit(e)
            continue
        for t in topics:
            h["tone"] = (h["tone"] + 1) % len(TONES)
            pid = next_id(index, date, blog["key"])
            log(f"  글 쓰는 중: {t['topic']} ({t['category']})")
            try:
                text = write_post(blog, t, TONES[h["tone"]], cfg, today)
                pkg = build_package(site / pid, blog, t, text, used_photos)
            except Exception as e:
                log(f"  ! 글을 만들지 못했습니다: {e}")
                shutil.rmtree(site / pid, ignore_errors=True)
                failed += 1
                if quota_hit(e):
                    log("  제미나이 무료 한도에 걸려 남은 글은 내일 씁니다.")
                    stop = True
                    break
                continue
            add_to_index(index, pid, date, blog, pkg, text, "제미나이" if "claude" not in env("BLOG_WRITER").lower() else "Claude", now, t)
            made += 1
            if not dry:
                h["topics"].append(t["topic"])
                h["topics"] = h["topics"][-60:]
                if t.get("sheet_row"):
                    mark_sheet(t["sheet_row"], date)
    hist["_photos"] = used_photos[-500:]
    prune(site, index, cfg.get("keep_days", 14))
    index["updated"] = now.isoformat(timespec="seconds")
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    if not dry:
        hist_path.write_text(json.dumps(hist, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"블로그 글 {made}편 완성, 실패 {failed}건")
    return 1 if failed and not made else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", default="blog_out", help="패키지를 쌓을 폴더 (서버: blog-packages 브랜치)")
    ap.add_argument("--blog", default="", help="이 블로그만 (쉼표로 여러 개, 예: naver1,tistory)")
    ap.add_argument("--count", type=int, default=0, help="블로그마다 몇 편 (기본: 설정의 posts_per_blog)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--scheduled", action="store_true",
                    help="예약 실행: 설정에서 껐으면 쉼. 초안 정리 후 오늘 글이 없는 블로그만 씀")
    ap.add_argument("--drafts", action="store_true", help="초안(drafts/)만 패키지로 만들고 새 글은 쓰지 않음")
    a = ap.parse_args()
    if a.scheduled and env("BLOG_ON", "1") == "0":
        log("블로그 자동 작성이 꺼져 있어 쉽니다 (프로그램 설정 → 블로그).")
        sys.exit(0)
    sys.exit(run(pathlib.Path(a.site), [b for b in a.blog.split(",") if b] or None, a.count or None, a.dry_run,
                 a.scheduled, a.drafts))
