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
import io
import json
import os
import pathlib
import random
import re
import shutil
import sys

import requests

import main
from image_tools import split_tall  # 긴 상세 이미지 → 3:4 조각 (쿠팡 쪽과 같이 씀)
from main import env, log

BASE = pathlib.Path(__file__).resolve().parent
STOCK = "stock"
MIN_VIDEO_PHOTOS = 3  # 영상만 만들 때 최소 사진 수
MIN_PRODUCT_PHOTOS = 1  # 서버는 1장만 남아도 글을 씀 (5장 이하는 확장에서 보내기를 막음, 사용자 결정 2026-10-21)
PRODUCT_PHOTOS_MAX = 40  # 상품 사진은 이만큼까지 받아서 관계없는 사진을 거름 (확장이 보내는 최대치)
PRODUCT_PHOTOS_USE = 40  # 상품 글에 넣는 사진: 모은 사진 모두 (확장이 보내는 최대 40장, 20장 제한은 상세 사진이 잘려서 없앰 2026-10-21)
PRODUCT = "product"  # drafts/product/*.json: 스튜디오 확장이 스마트스토어 상품 페이지에서 모아 올린 재료
VIDEO_REQ = "video"  # drafts/video/*.json: 스튜디오 '영상 다시 만들기' 요청 (패키지 id + 고른 사진)
VSRC = "vsrc"  # 패키지 안 영상 후보 사진 폴더
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
{keywords}{fixed}
각 글감마다
  topic: 글감 한 줄
  category: {cats} 중 하나를 글자 그대로
  angle: 글에서 다룰 내용 한 줄 (독자가 얻는 것 위주)
  photo: 무료 사진 사이트에서 찾을 영어 검색어 2~3단어 (사람 얼굴보다 물건·장면, 상표 이름 금지)
  keyword: 사람들이 네이버에서 실제로 검색할 핵심 키워드 하나 (2~4단어, 위 키워드 목록에 있으면 그대로)
  urgent: 빨리 올려야 의미 있는 글(신청 마감, 출시·행사 소식처럼 날짜가 지나면 쓸모가 줄어드는 글)이면 true, 언제 올려도 되는 글이면 false
  until: urgent가 true이고 날짜가 확인되면 그 글이 쓸모 있는 마지막 날 YYYY-MM-DD, 아니면 ""

다른 말 없이 JSON 배열만 출력: [{{"topic": "...", "category": "...", "angle": "...", "photo": "...", "keyword": "...", "urgent": true, "until": ""}}]"""

WRITE_PROMPT = """오늘은 {today} 한국 날짜다. '{name}' {platform} 블로그에 올릴 글을 한국어로 써라.
글감: {topic}
다룰 내용: {angle}
카테고리: {category}
{keyword_rule}
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

PRODUCT_PROMPT = """오늘은 {today} 한국 날짜다. '{name}' 네이버 블로그에 올릴 상품 소개 글을 한국어로 써라.
네이버 쇼핑커넥트 글이고, 상품 링크 카드와 대가성 안내 문구는 글쓴이가 따로 넣는다. 본문에 링크·안내 문구는 쓰지 마라.
상품명: {product}
가격(재료를 모은 날 페이지 기준): {price}
상품 페이지 주소: {url}
상품 페이지 글(판매자 설명이나 상품 정보, 일부):
{page}
함께 보낸 사진은 상품 페이지의 대표·상세 이미지다. 사진 속 글씨(성분, 용량, 사용법, 구성)도 읽어서 써라.
{keywords}
{facts} 의약품처럼 치료 효과를 단정하지 마라.
직접 써 봤다는 경험담은 절대 지어내지 마라. "판매 페이지를 보면", "상세 설명에 따르면" 같은 표현은 괜찮다.
누구에게 맞고 누구에게는 덜 맞는지, 고를 때 볼 점을 담백하게 정리해라. 과장 광고 말투는 쓰지 마라.

길이: 공백을 뺀 글자 수로 {min}~{max}자 (표 안의 글자 포함). {min}자보다 짧으면 안 된다.
말투와 구성: {tone}

문체
- 사람이 쓴 블로그 글처럼 자연스럽게. 짧은 문장과 긴 문장을 섞고, 문단 첫머리를 매번 다르게 시작해라.
- 쓰지 말 것: "~에 대해 알아보겠습니다", "결론적으로", "~하는 것이 중요합니다", "도움이 되셨길 바랍니다",
  "다양한·효율적인·혁신적인" 남발, 소제목마다 끝에 요약 문장, 모든 목록을 3개로 맞추기. 이모지와 해시태그도 쓰지 마라.

형식: 아래 표시만 써라. 마크다운 제목(#), 코드 블록(```), 굵은 소제목은 쓰지 마라.
@title: 제목 (상품 종류와 핵심 특징을 앞쪽에, 25~40자, 글자 수 표시 넣지 말 것)
@tags: 태그 8~10개, 쉼표로 구분, # 없이
@keyword: 이 글의 핵심 검색 키워드 하나 (사람들이 네이버에서 찾는 말, 제목 맨 앞쪽에 넣은 것)
@video: 짧은 상품 영상 표지 문구 (상품이 무엇인지 한눈에, 8~16자)
@clips: 영상 사진마다 넣을 자막 5개, 각각 15자 이내, ' / '로 구분 (구성·용량·특징·가격 같은 핵심만)
@videospot: 상품 영상을 넣기 가장 어울리는 소제목 하나 (아래 ## 소제목 중 하나를 글자 그대로. 영상은 그 소제목 바로 밑에 들어감)
(빈 줄 없이 바로 본문. 첫 문단은 소제목 없이 시작)
## 소제목              ← 3~5개
문단은 한 줄에 하나
- 목록 한 줄
| 칸 | 칸 | 칸          ← 구성·용량·가격 같은 정보 표 1개, 첫 줄이 제목줄, 칸을 비우지 말 것(없으면 -)
> 인용 상자에 넣을 한 줄 (1개)
! 강조 상자에 넣을 주의·팁 한 줄 (1~2개)
**핵심 문구**는 소제목마다 1~2개만
[사진: 상품 | 사진 설명]          ← 본문 곳곳에 9~10개, 문단 사이에 고르게 (상품 사진이 차례로 들어감)
[카드: 카드 제목 | 줄1 / 줄2 / 줄3 / 줄4 | 이미지 설명]   ← 핵심 정리 카드 1개, 줄마다 20자 이내"""

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


def ask_with_photos(prompt, photos, temperature=0.8, search=False):
    """사진을 함께 보고 쓰기 (제미나이). 제미나이 키가 없으면 글자만으로 Claude. search=True면 검색으로 보충."""
    import memo_ai
    if env("BLOG_WRITER", "제미나이").lower() == "claude" or not memo_ai.env("GEMINI_API_KEY"):
        return ask(prompt, search=search, temperature=temperature)
    parts = [{"text": prompt}]
    for label, b64 in memo_ai._pieces(photos):
        parts += [{"text": label}, {"inline_data": {"mime_type": "image/jpeg", "data": b64}}]
    return memo_ai.generate(parts, json_out=False, temperature=temperature, search=search)


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


def pick_topics(blog, count, recent, today, rep=None):
    fixed = sheet_topics(blog)[:count]
    lines = "\n".join(f"- 이 글감은 꼭 넣어라: {t}" for _, t in fixed)
    text = ask(TOPIC_PROMPT.format(today=today, name=blog["name"], platform=platform_k(blog), theme=blog["theme"],
                                   count=count, recent=", ".join(recent[-30:]) or "없음", fixed=lines,
                                   cats=", ".join(blog["categories"]), keywords=keyword_block(rep, blog)),
               temperature=0.9)
    topics = json_array(text)[:count]
    for t, (row, _) in zip(topics, fixed):
        t["sheet_row"] = row
    for t in topics:
        if t.get("category") not in blog["categories"]:
            t["category"] = blog["categories"][0]
        if t.get("keyword"):
            t["kw"] = keyword_info(t["keyword"], rep)
    return topics


def keyword_block(rep, blog):
    """글감 고르기에 넣을 인기 검색어·검색량 키워드 (keywords.json, 없으면 빈 글자)."""
    import blog_keywords
    text = blog_keywords.prompt_block(rep or {}, blog["key"])
    if text and "생활정보" in blog["categories"]:  # 주제 밖이어도 많이 찾는 생활 키워드는 생활정보로 씀
        text += "블로그 주제와 조금 달라도 검색량이 많은 생활 키워드면 '생활정보' 카테고리로 1개쯤 골라도 된다.\n"
    return text


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


def keyword_rule(kw):
    """검색 노출용 핵심 키워드 안내 (없으면 빈 글자)."""
    if not kw:
        return ""
    return (f"핵심 검색 키워드: {kw}\n"
            f"- 이 키워드를 제목 맨 앞쪽, 첫 문단, 소제목 1~2개, 태그 첫 자리에 자연스럽게 넣어라. 본문 전체에 3~5번이면 충분하다(억지 반복 금지).\n"
            f"- 검색한 사람이 바로 답을 얻게 첫 문단에서 핵심을 먼저 말해라.\n")


def keyword_info(kw, rep=None):
    """키워드 → 검색량·경쟁도 (keywords.json에 있으면 그 값, 없으면 검색광고 API로 확인)."""
    import blog_keywords
    if not kw:
        return {}
    n = blog_keywords._norm(kw)
    for c in (rep or {}).get("trending", []) + sum((rep or {}).get("blogs", {}).values(), []) + (rep or {}).get("products", []):
        if blog_keywords._norm(c.get("keyword")) == n and c.get("volume"):
            return {k: c[k] for k in ("keyword", "volume", "docs", "level") if c.get(k) is not None}
    try:
        return blog_keywords.describe(kw)
    except Exception as e:
        log(f"    (키워드 검색량을 확인하지 못했습니다: {e})")
        return {"keyword": kw}


def write_post(blog, topic, tone, cfg, today):
    lo, hi = cfg.get("min_chars", 1500), cfg.get("max_chars", 2000)
    text = clean(ask(WRITE_PROMPT.format(today=today, name=blog["name"], platform=platform_k(blog),
                                         topic=topic["topic"], angle=topic.get("angle", ""),
                                         category=topic["category"], min=lo, max=hi, tone=tone,
                                         keyword_rule=keyword_rule(topic.get("keyword")))))
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
    title = re.sub(r"\s+\(?[12],?[0-9]00\s*자?\s*(이상)?\)?$", "", title)  # 채팅 AI가 글자 수 요청을 제목 끝에 붙인 것
    tags = [t.strip().lstrip("#") for t in re.split(r"[,，]", meta.get("tags", "")) if t.strip()][:10]
    return title, tags, blocks, images


def build_package(folder, blog, topic, text, used_photos, photos=None):
    """photos: 상품 페이지에서 받은 사진(PIL) 목록. 주면 Pixabay 대신 이 사진을 차례로 씀."""
    import blog_images
    photos = list(photos or [])
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
        if photos:
            return photos.pop(0), None
        if topic.get("own_photos"):  # 상품 글: 상품과 상관없는 무료 사진은 넣지 않음
            return None, None
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
            if pid:
                used_photos.append(pid)
            name = f"{n:02d}-photo.jpg"
            blog_images.photo(folder / name, im, keep=bool(topic.get("own_photos")))
            alt = p["parts"][1] if len(p["parts"]) > 1 else topic["topic"]
        else:
            ctitle = p["parts"][0] if p["parts"] else title
            lines = [s.strip() for s in (p["parts"][1] if len(p["parts"]) > 1 else "").split("/")]
            name = f"{n:02d}-card.png"
            blog_images.card(folder / name, ctitle, lines)
            alt = p["parts"][2] if len(p["parts"]) > 2 else ctitle
        images.append({"id": f"img{n}", "file": name, "alt": alt, "anchorBlockId": p["after"],
                       "position": "after_block"})
        if n >= (14 if topic.get("own_photos") else 3):
            break
    if topic.get("own_photos"):  # 상품 글: 모은 상품 사진을 모두 넣음: 빈 문단 뒤에 고르게, 문단이 모자라면 같은 문단 뒤에 이어서
        used = {i.get("anchorBlockId") for i in images}
        spots = [b["id"] for b in blocks if b["type"] == "PARAGRAPH" and b["id"] not in used]
        want = len(photos)
        free = spots[:] or [b["id"] for b in blocks if b["type"] == "PARAGRAPH"]
        for k in range(want):
            if not free:
                break
            at = spots[min(len(spots) - 1, (k + 1) * len(spots) // (want + 1))] if spots else free[k % len(free)]
            if at in spots:
                spots.remove(at)
            n += 1
            name = f"{n:02d}-photo.jpg"
            blog_images.photo(folder / name, photos.pop(0))
            images.append({"id": f"img{n}", "file": name, "alt": f"{topic['topic']} 상품 사진", "anchorBlockId": at,
                           "position": "after_block"})
        images.sort(key=lambda i: -1 if i.get("role") == "COVER" else order.index(i["anchorBlockId"]))
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
    # 비상용 글은 꺼내 쓸 때까지 남겨 둠. 꺼내 쓴 글은 폴더 날짜가 옛날이어도 목록 날짜로 판단
    index["packages"] = [p for p in index["packages"] if p.get("stock") or p["date"] >= cutoff]
    keep = {p["id"].split("/")[0] for p in index["packages"]}
    for d in site.iterdir():
        if d.is_dir() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", d.name) and d.name < cutoff and d.name not in keep:
            shutil.rmtree(d)
    index["packages"] = [p for p in index["packages"] if (site / p["id"]).is_dir()]  # 깃허브에서 직접 지운 글은 목록에서도 뺌
    done = load_json(site / "done.json", {})  # 발행 완료 표시(프로그램·스튜디오가 씀): 목록에서 빠진 글은 정리
    ids = {p["id"] for p in index["packages"]}
    if done.get("done"):
        done["done"] = {k: v for k, v in done["done"].items() if k in ids}
        (site / "done.json").write_text(json.dumps(done, ensure_ascii=False, indent=1), encoding="utf-8")


def quota_hit(e):
    """제미나이 무료 한도(분당·하루)에 걸렸는지. 걸렸으면 남은 글은 쓰지 않고 멈춘다 (쿠팡 자동화 몫을 남기려고)."""
    return "한도" in str(e)


def find_blog(cfg, name):
    n = name.replace(" ", "")
    return next((b for b in cfg["blogs"] if n in (b["key"], b["name"].replace(" ", ""))), None)


def next_id(index, date, key):
    """지운 글의 번호는 다시 쓰지 않는다 (스튜디오·프로그램의 발행 완료 표시가 번호로 남아 새 글이 완료로 보이므로)."""
    used = set(index.setdefault("used", []))
    existing = {p["id"] for p in index["packages"]} | used
    k = 1
    while f"{date}/{key}-{k}" in existing:
        k += 1
    pid = f"{date}/{key}-{k}"
    index["used"] = (index["used"] + [pid])[-500:]
    return pid


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
    if (topic or {}).get("kw"):
        index["packages"][0]["keyword"] = topic["kw"]
    log(f"  ✓ {pkg['title']} (공백 제외 {chars}자, 이미지 {len(pkg['images'])}장)")


def draft_package(path, site, cfg, index, hist, used_photos, now, date=None, stock=False):
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
    if meta.get("keyword"):  # 초안 머리 @keyword: 검색 키워드 → 목록에 검색량 표시
        topic["kw"] = keyword_info(meta["keyword"], KEYWORDS)
    pid = next_id(index, date, blog["key"])
    log(f"[{blog['name']}] 초안 정리: {path.parent.name}/{path.name}")
    try:
        pkg = build_package(site / pid, blog, topic, text, used_photos)
    except Exception as e:
        log(f"  ! 초안을 패키지로 만들지 못했습니다: {e}")
        shutil.rmtree(site / pid, ignore_errors=True)
        return False
    add_to_index(index, pid, date, blog, pkg, text, "채팅" if "-chat-" in path.name else "Claude", now, topic)
    if stock:  # 비상용: 사진까지 붙여 목록에 보이고, 오늘 글이 빈 날 새벽에 오늘 글로 꺼내 씀
        index["packages"][0]["stock"] = True
        index["packages"][0]["urgent"] = ""
    h = hist.setdefault(blog["key"], {"topics": [], "tone": -1})
    h["topics"] = (h["topics"] + [topic["topic"]])[-60:]
    path.unlink()
    return True


def product_image_urls(urls):
    """사진 주소 정리: 브랜드커넥트 썸네일(dthumb-phinf ?src="원본")은 원본 주소로 풀고, 크기 지정(?type=)은 떼고,
    구매자 리뷰 사진(checkout.phinf)·네이버 배너(ssl.pstatic.net)·다른 상품 추천 썸네일(shopping-phinf main_)·라이브 영상 썸네일(image.nmv)은 이 상품 사진이 아니라 뺀다. 같은 사진은 한 번만."""
    out, seen = [], set()
    for u in urls:
        u = str(u or "").strip()
        m = re.search(r"[?&]src=([^&]+)", u)
        if "dthumb" in u and m:
            u = requests.utils.unquote(m.group(1)).strip('"\'')
        if u.startswith("//"):
            u = "https:" + u
        if not u.startswith("http") or re.search(r"checkout\.phinf|ssl\.pstatic\.net|/static/|shopping-phinf\.pstatic\.net/main_|image\.nmv", u):
            continue
        u = re.sub(r"\?type=[^&]*$", "", u)
        key = re.sub(r"^https?:", "", u).split("?")[0]
        if key not in seen:
            seen.add(key)
            out.append(u)
    return out


def product_photos(urls, limit=14):
    """상품 페이지 사진 주소 → PIL 이미지 목록 (작은 아이콘·받지 못한 사진은 뺌)."""
    from PIL import Image
    out = []
    for u in product_image_urls(urls):
        try:
            r = requests.get(u, timeout=30, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://smartstore.naver.com/"})
            r.raise_for_status()
            im = Image.open(io.BytesIO(r.content)).convert("RGB")
        except Exception as e:
            log(f"    (상품 사진을 받지 못했습니다: {e})")
            continue
        if min(im.size) < 300:
            continue
        out += split_tall(im, pad=False) if im.height > im.width * 1.6 else [im]  # 긴 상세 이미지는 화면 한 장 크기로 잘라 여러 장
        if len(out) >= limit:
            break
    return out[:limit]


def drop_other_products(name, photos):
    """상세페이지 안에 섞인 판매자의 다른 상품·홍보 배너·안내문 사진을 제미나이(무료)가 골라 뺀다.
    쿠팡 쪽(memo_ai.unrelated_photos)과 같은 판정. 키가 없거나 실패하면 그대로 둔다."""
    import memo_ai
    if not name or not photos or not memo_ai.env("GEMINI_API_KEY"):
        return photos
    try:
        drop = memo_ai.unrelated_photos(name, photos)
    except Exception as e:
        log(f"    (관계없는 사진 거르기를 건너뜁니다: {e})")
        return photos
    if drop:
        log(f"    상품과 관계없는 사진 {len(drop)}장 뺌 (제미나이 판정)")
    return [im for k, im in enumerate(photos) if k not in drop]


def product_keyword_block(cands):
    if not cands:
        return ""
    return ("네이버에서 이 상품과 관련해 많이 찾는 검색어(월 검색량): " + ", ".join(f"{c['keyword']}({c['volume']:,})" for c in cands[:8])
            + "\n이 가운데 상품에 맞는 것 하나를 핵심 키워드로 골라 제목 맨 앞쪽, 첫 문단, 소제목 하나, 태그에 자연스럽게 넣어라. "
              "상품명만 쓰기보다 '종류 + 추천·비교' 같은 검색어가 노출에 유리하다.\n")


def _blank_strip(im):
    """빈 조각(여백·띠)인지. 흰 바탕의 연한 색 상품 사진은 명암 차이가 작아 image_tools.is_blank에 걸리므로,
    바탕색과 다른 점이 8% 넘게 있으면 빈 조각으로 보지 않는다."""
    import image_tools
    if not image_tools.is_blank(im):
        return False
    hist = im.convert("L").resize((64, 64)).histogram()
    base = max(range(256), key=lambda v: sum(hist[max(0, v - 4):v + 5]))
    return sum(hist[:max(0, base - 25)]) + sum(hist[base + 26:]) < 64 * 64 * 0.08


def video_shots(photos, need=6):
    """영상에 넣을 사진 검수: 같은 사진·빈 조각은 빼고, 글자가 박힌 사진(상세페이지 설명·표·광고 문구)은
    영상 자막과 겹쳐 지저분하므로 글자 없는 사진을 먼저 고른다. 모자랄 때만 글자 있는 사진으로 채운다.
    첫 장은 대표(표지) 사진이라 뒤로 미룬다."""
    import image_tools
    pool = image_tools.unique_photos(photos[1:] + photos[:1])
    pool = [im for im in pool if not _blank_strip(im) and max(im.size) <= min(im.size) * 2.2]  # 길쭉한 띠·배너 제외
    flags = [image_tools.has_text(im) for im in pool]
    clean = [im for im, f in zip(pool, flags) if f is False or f is None]
    texty = [im for im, f in zip(pool, flags) if f]
    shots = clean[:need] + texty[:max(0, 4 - len(clean))]  # 영상은 최소 4장
    log(f"    영상 사진 검수: 후보 {len(pool)}장 중 글자 없는 {len(clean)}장, 글자 있는 {len(texty)}장 → {len(shots)}장 사용")
    return shots


def short_title(text, limit=26):
    """영상 표지 문구: 단어 중간에서 잘리지 않게 limit 글자 안쪽 띄어쓰기에서 자른다."""
    text = re.sub(r"\s+", " ", str(text)).strip()
    if len(text) > limit:
        cut = text[:limit + 1].rsplit(" ", 1)[0]
        text = cut if len(cut) >= limit // 2 else text[:limit]
    return text or "오늘의 상품"


def product_videos(folder, text, name, photos):
    """상품 사진으로 짧은 영상 두 개(가로 video.mp4, 세로 video_vertical.mp4)를 패키지 폴더에 만든다.
    표지 문구·자막은 글 머리의 @video, @clips (없으면 상품명과 소제목). 실패해도 글은 그대로 둔다."""
    meta = dict(ln[1:].split(": ", 1) for ln in text.splitlines() if ln.startswith("@") and ": " in ln)
    title = short_title(meta.get("video") or re.sub(r"\[.*?\]|\(.*?\)", "", name))
    lines = [x.strip() for x in re.split(r"\s*/\s*", meta.get("clips", "")) if x.strip()]
    if len(lines) < 4:  # 자막이 없으면 소제목으로
        lines = [ln[3:].replace("**", "").strip() for ln in text.splitlines() if ln.startswith("## ")]
    lines = [x if len(x) <= 18 else x[:17] + "…" for x in lines]
    shots = video_shots(photos)
    out = make_videos(folder, title, shots, lines)
    if out:  # 스튜디오 '영상 다시 만들기'용: 후보 사진(vsrc/)과 표지 문구·자막을 남겨 둠
        try:
            import image_tools
            src = folder / VSRC
            src.mkdir(exist_ok=True)
            names, used = [], []
            for k, im in enumerate(image_tools.unique_photos(photos[1:] + photos[:1])[:16], 1):
                name = f"{VSRC}/{k:02d}.jpg"
                im.convert("RGB").save(folder / name, quality=85)
                names.append(name)
                if any(im is x for x in shots):
                    used.append(name)
            (folder / "video.json").write_text(json.dumps({"title": title, "lines": lines, "photos": names, "used": used},
                                                          ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception as e:
            log(f"    (영상 후보 사진을 남기지 못했습니다: {e})")
    return out


def make_videos(folder, title, shots, lines, keep_cover=False):
    """가로 video.mp4, 세로 video_vertical.mp4를 만든다. 만든 파일 이름 목록.
    표지 화면은 vsrc/cover-가로x세로.jpg로 남겨 두고, keep_cover면 남겨 둔 표지를 그대로 다시 씀 (영상 다시 만들기)."""
    import blog_video
    from PIL import Image
    out = []
    style, pal = random.choice(blog_video.STYLES), random.choice(blog_video.PALETTES)  # 가로·세로 같은 표지
    for fname, size in (("video.mp4", (1920, 1080)), ("video_vertical.mp4", (1080, 1920))):
        try:
            saved = folder / VSRC / f"cover-{size[0]}x{size[1]}.jpg"
            if keep_cover and saved.is_file():
                img = Image.open(saved).convert("RGB")
            else:
                img = blog_video._cover(*size, title, blog_video._cover_photo(shots), style, pal)
                saved.parent.mkdir(exist_ok=True)
                img.save(saved, quality=90)
            blog_video.make(folder / fname, title, shots, lines, *size, cover_img=img)
            out.append(fname)
        except Exception as e:
            log(f"    (영상 {fname}을 만들지 못했습니다: {e})")
    if out:
        log(f"    영상 {len(out)}개 만듦: {', '.join(out)}")
    return out


def remake_video(path, site, index, now):
    """drafts/video/*.json (스튜디오 '영상 다시 만들기'): {"id": 패키지, "photos": [패키지 안 사진 파일, 순서대로]}
    고른 사진으로 영상을 새로 만들어 같은 이름으로 덮어쓰고, 목록에 videoVer(새 영상 표시)를 적는다. 성공하면 True."""
    from PIL import Image
    req = json.loads(path.read_text(encoding="utf-8"))
    pkg = next((p for p in index.get("packages", []) if p.get("id") == req.get("id")), None)
    folder = site / str(req.get("id", ""))
    if not pkg or not folder.is_dir():
        log(f"  ! 영상 다시 만들기: 패키지 {req.get('id')}를 찾지 못해 요청을 지웁니다")
        path.unlink()
        return None
    log(f"[영상 다시 만들기] {pkg.get('title', '')[:40]}")
    meta = {}
    if (folder / "video.json").exists():
        meta = json.loads((folder / "video.json").read_text(encoding="utf-8"))
    title = meta.get("title") or short_title(re.sub(r"\[.*?\]|\(.*?\)", "", pkg.get("title", "")))
    lines = meta.get("lines")
    if not lines and (folder / "content.json").exists():  # 예전 패키지: 소제목을 자막으로
        blocks = json.loads((folder / "content.json").read_text(encoding="utf-8")).get("blocks", [])
        lines = [b.get("text", "")[:17] for b in blocks if b.get("type") == "H2"]
    shots = []
    for name in req.get("photos") or []:
        f = (folder / name).resolve()
        if folder.resolve() in f.parents and f.is_file():
            shots.append(Image.open(f).convert("RGB"))
    if len(shots) < 4:
        log(f"  ! 사진이 {len(shots)}장뿐이라 영상을 다시 만들지 않습니다 (최소 4장)")
        path.unlink()
        return None
    out = make_videos(folder, title, shots[:6], lines or [], keep_cover=True)  # 표지는 원래 영상 그대로 (남겨 둔 게 없으면 새로)
    if not out:
        return False
    if meta:
        meta["used"] = list(req["photos"])[:6]
        (folder / "video.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    pkg["videos"] = out
    pkg["videoVer"] = now.strftime("%Y%m%d%H%M%S")
    path.unlink()
    return True


def video_only_package(d, blog, site, index, now, photos):
    """사진이 글 쓰기엔 모자란 상품: 영상(가로·세로)만 담은 패키지. 목록에는 '영상'으로 나오고 영상 받기만 됨."""
    pid = next_id(index, now.strftime("%Y-%m-%d"), blog["key"])
    (site / pid).mkdir(parents=True, exist_ok=True)
    name = d.get("name", "")
    videos = product_videos(site / pid, "", name, photos)
    if not videos:
        shutil.rmtree(site / pid, ignore_errors=True)
        return False
    index["packages"].insert(0, {"id": pid, "date": pid.split("/")[0], "blogKey": blog["key"], "blogName": blog["name"],
                                 "platform": blog["platform"], "category": "영상", "kind": "영상",
                                 "title": re.sub(r"\s+", " ", name).strip()[:60] or "상품 영상", "chars": 0,
                                 "files": [], "videos": videos, "link": d.get("link", ""), "source": d.get("url", ""), "createdAt": now.isoformat(timespec="seconds")})
    return True


def writer_photos(d, photos, n_gal_keep=2, n_detail=10):
    """글을 쓸 때 보여 줄 사진: 대표·썸네일은 앞 2장만, 나머지는 상세페이지 사진(구성·사양·설명)에서 고르게 10장.
    썸네일이 13장처럼 많으면 앞 8장이 다 썸네일이라 상세 정보를 못 읽었음 (2026-10-21)."""
    kinds = d.get("img_kinds") or {}
    n_gal = sum(1 for u in d.get("images") or [] if kinds.get(u) == "gallery")
    if not n_gal or len(photos) <= n_gal_keep + n_detail:
        return photos[:n_gal_keep + n_detail]
    detail = photos[n_gal:] or photos[n_gal_keep:]
    if len(detail) > n_detail:
        detail = [detail[k * len(detail) // n_detail] for k in range(n_detail)]
    return photos[:n_gal_keep] + detail


def shop_notice(index, now, d, reason):
    """상품 글을 못 만든 까닭을 index.json 'notices'에 남긴다 (스튜디오 목록 맨 위에 빨간 줄로 보임, 최근 20건)."""
    index["notices"] = ([{"at": now.isoformat(timespec="seconds"), "blog": d.get("blog", ""), "name": re.sub(r"\s+", " ", d.get("name", "")).strip()[:60],
                          "reason": reason}] + [n for n in index.get("notices", []) if isinstance(n, dict)])[:20]


def product_package(path, site, cfg, index, hist, now):
    """상품 재료(json) 하나로 상품 소개 글을 써서 패키지를 만들고 재료를 지운다. 성공하면 True.
    재료: blog(key), name, price, url, link(쇼핑커넥트 링크), text(페이지 글), images(글·영상에 쓸 사진 주소), ref_images(내용 참고용 사진 주소, 글에는 안 넣음)."""
    d = json.loads(path.read_text(encoding="utf-8"))
    blog = find_blog(cfg, d.get("blog", "")) or find_blog(cfg, "naver2")
    cat = blog.get("shop_category") or blog["categories"][0]  # 쇼핑 카테고리는 일반 글감에서 고르지 않게 따로 둠
    log(f"[{blog['name']}] 상품 글: {d.get('name', '')[:40]}")
    photos = drop_other_products(d.get("name", ""), product_photos(d.get("images") or [], limit=PRODUCT_PHOTOS_MAX))
    photos = photos[:PRODUCT_PHOTOS_USE]
    n_photos = len(photos)
    if n_photos < MIN_PRODUCT_PHOTOS:  # 쓸 만한 사진이 하나도 없을 때만 건너뜀
        if len(photos) >= MIN_VIDEO_PHOTOS and d.get("video", True):  # 사진이 적어도 영상은 만들어 둠 (보내기 화면에서 끌 수 있음)
            log(f"  상품 사진이 {len(photos)}장이라 글은 쓰지 않고 영상만 만듭니다 (글은 최소 {MIN_PRODUCT_PHOTOS}장)")
            ok = video_only_package(d, blog, site, index, now, photos)
            if not ok:
                shop_notice(index, now, d, f"사진 {len(photos)}장으로 영상을 만들지 못했어요.")
        else:
            log(f"  ! 쓸 만한 상품 사진이 {len(photos)}장뿐이라 글도 영상도 만들지 않고 재료를 지웁니다")
            ok = None  # 실패가 아니라 건너뜀 (서버 작업을 빨간불로 만들지 않음)
            shop_notice(index, now, d, f"쓸 만한 상품 사진이 {len(photos)}장뿐이라 글·영상을 만들지 않았어요. 사진이 다 뜬 뒤 다시 보내 주세요.")
        path.unlink()
        return ok
    lo, hi = cfg.get("min_chars", 1500), cfg.get("max_chars", 2000)
    h = hist.setdefault(blog["key"], {"topics": [], "tone": -1})
    h["tone"] = (h["tone"] + 1) % len(TONES)
    try:
        import blog_keywords
        cands = blog_keywords.product_keywords(d.get("name", ""))
    except Exception as e:
        log(f"    (상품 키워드를 찾지 못했습니다: {e})")
        cands = []
    today = f"{now:%Y년 %m월 %d일} ({WEEKDAYS[now.weekday()]})"
    prompt = PRODUCT_PROMPT.format(today=today, name=blog["name"], product=d.get("name", ""), price=d.get("price") or "-",
                                   url=d.get("url", ""), page=(d.get("text") or "")[:8000], min=lo, max=hi,
                                   tone=TONES[h["tone"]], keywords=product_keyword_block(cands),
                                   facts=("재료에 상세 설명이 거의 없다. 상품명으로 검색해 판매처·제조사의 공식 정보(구성, 용량, 성분, 사용법)를 확인하고, "
                                          "확인한 사실과 재료만 써라. 확인하지 못한 숫자·효능·인증은 지어내지 마라." if d.get("search") else
                                          "이 재료에 있는 사실만 써라. 재료에 없는 숫자·효능·인증은 지어내지 마라."))
    written = (d.get("body") or "").strip()  # Claude가 미리 써서 넣은 본문이 있으면 제미나이를 부르지 않음
    # 참고 사진(ref_images): 사용자가 '내용 참고용'으로 고른 사진. 글·영상에는 넣지 않고 제미나이가 내용을 읽는 데만 씀
    refs = [] if written or not d.get("ref_images") else product_photos(d["ref_images"], limit=8)
    if refs:
        prompt += f"\n(사진 중 뒤쪽 {len(refs)}장은 상세 설명·성분표 같은 참고 자료다. 내용 확인에만 쓰고 '사진에 보이는' 식으로 소개하지 마라.)\n"
    text = clean(written) if written else clean(ask_with_photos(prompt, writer_photos(d, photos) + refs, search=bool(d.get("search"))))
    for _ in range(0 if written else 2):
        n = body_chars(text)
        if lo <= n <= hi + 300:
            break
        need = (f"{lo + 150}자 정도가 되게 늘려라. 재료에 있는 구성·사용법·고를 때 볼 점을 더 자세히 풀어라."
                if n < lo else f"{hi - 100}자 정도가 되게 줄여라. 겹치는 설명부터 빼라.")
        log(f"    글자 수 {n}자 → 다시 쓰기")
        fixed = clean(ask(FIX_PROMPT.format(n=n, need=need, text=text), search=False, temperature=0.6))
        if "@title" in fixed and body_chars(fixed) > 200:
            text = fixed
    date = now.strftime("%Y-%m-%d")
    topic = {"topic": d.get("name", ""), "category": cat, "photo": "", "own_photos": True}
    kw = dict(ln[1:].split(": ", 1) for ln in text.splitlines() if ln.startswith("@") and ": " in ln).get("keyword", "").strip()
    if kw:
        topic["kw"] = keyword_info(kw, {"products": cands})
    pid = next_id(index, date, blog["key"])
    try:
        pkg = build_package(site / pid, blog, topic, text, [], photos)
    except Exception:
        shutil.rmtree(site / pid, ignore_errors=True)
        raise
    add_to_index(index, pid, date, blog, pkg, text, "Claude" if written or "claude" in env("BLOG_WRITER").lower() else "제미나이",
                 now, topic)
    index["packages"][0].update({"kind": "쇼핑", "link": d.get("link", ""), "source": d.get("url", "")})
    videos = product_videos(site / pid, text, d.get("name", ""), photos) if d.get("video", True) and n_photos >= MIN_VIDEO_PHOTOS else []
    spot = dict(ln[1:].split(": ", 1) for ln in text.splitlines() if ln.startswith("@") and ": " in ln).get("videospot", "")
    heads = [ln[3:].replace("**", "").strip() for ln in text.splitlines() if ln.startswith("## ")]
    spot = next((h for h in heads if spot.strip() and (h == spot.strip() or spot.strip() in h)), "")
    if videos and spot:  # 스튜디오가 네이버에 영상을 이 소제목 바로 밑에 넣음 (없으면 서론 뒤)
        index["packages"][0]["videoSpot"] = spot
    if videos:
        index["packages"][0]["videos"] = videos
    h["topics"] = (h["topics"] + [d.get("name", "")[:60]])[-60:]
    nm = re.sub(r"\s+", " ", d.get("name", "")).strip()[:60]  # 같은 상품 글이 만들어졌으니 예전 '못 만든 상품' 안내는 지움
    index["notices"] = [n for n in index.get("notices", []) if not (isinstance(n, dict) and n.get("blog") == d.get("blog", "") and n.get("name") == nm)]
    path.unlink()
    return True


def split_drafts(path):
    """한 파일에 글이 여러 편이면(@title 줄이 2개 이상) 글마다 파일로 나눈다. 뒤 글에 없는 머리 줄(@blog·@category·@use 등)은
    첫 글 것을 이어 받는다. 나눈 파일 경로 목록을 돌려준다 (한 편이면 그대로)."""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    starts = []  # 글마다 머리(@ 줄 묶음)가 시작하는 줄
    for i, ln in enumerate(lines):
        if ln.startswith("@title:"):
            j = i
            while j > 0 and lines[j - 1].startswith("@"):
                j -= 1
            starts.append(j)
    if len(starts) < 2:
        return [path]
    parts = [lines[a:b] for a, b in zip(starts, starts[1:] + [len(lines)])]
    first = {ln.split(":", 1)[0] for ln in parts[0] if ln.startswith("@")}
    base = [ln for ln in parts[0] if ln.startswith("@") and ln.split(":", 1)[0] not in ("@title", "@tags", "@topic", "@keyword", "@photo")]
    out = []
    for k, part in enumerate(parts):
        own = {ln.split(":", 1)[0] for ln in part if ln.startswith("@")}
        head = [ln for ln in base if ln.split(":", 1)[0] not in own] if k else []
        q = path.with_name(f"{path.stem}-{k + 1:02d}{path.suffix}")
        q.write_text("\n".join(head + part).strip() + "\n", encoding="utf-8")
        out.append(q)
    path.unlink()
    log(f"  초안 한 파일에 글이 {len(parts)}편이라 나눔: {path.name}")
    return out


def process_drafts(site, cfg, index, hist, used_photos, now):
    """drafts/날짜/*.txt (그날 글)와 drafts/stock/*.txt (비상용)를 패키지로 만든다. 비상용은 stock 표시를 달아 둔다."""
    made = failed = 0
    for path in [q for p in sorted((site / "drafts").glob("**/*.txt")) for q in split_drafts(p)]:
        stock = STOCK in path.parts
        if draft_package(path, site, cfg, index, hist, used_photos, now, now.strftime("%Y-%m-%d") if stock else None, stock):
            made += 1
        else:
            failed += 1
    for path in sorted((site / "drafts" / PRODUCT).glob("*.json")):
        try:
            ok = product_package(path, site, cfg, index, hist, now)
        except Exception as e:  # 제미나이 한도 등: 재료는 남겨 두고 다음 실행 때 다시
            log(f"  ! 상품 글을 만들지 못했습니다 (재료는 남겨 둠): {e}")
            ok = False
            try:  # 왜 안 됐는지 재료에 적어 둠 (스튜디오·Claude가 확인)
                d = json.loads(path.read_text(encoding="utf-8"))
                d["error"] = f"{now:%m-%d %H:%M} {type(e).__name__}: {e}"[:500]
                path.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
                shop_notice(index, now, d, f"이번엔 못 만들었어요 ({type(e).__name__}). 재료는 남아 있어 다음 서버 작업 때 다시 시도해요.")
            except Exception:
                pass
        if ok is not None:
            made, failed = (made + 1, failed) if ok else (made, failed + 1)
    for path in sorted((site / "drafts" / VIDEO_REQ).glob("*.json")):
        try:
            ok = remake_video(path, site, index, now)
        except Exception as e:
            log(f"  ! 영상을 다시 만들지 못했습니다 (요청은 남겨 둠): {e}")
            ok = False
        if ok is not None:
            made, failed = (made + 1, failed) if ok else (made, failed + 1)
    for d in sorted((site / "drafts").glob("*"), reverse=True):
        if d.is_dir() and d.name != STOCK and not any(d.iterdir()):
            d.rmdir()
    return made, failed


def use_stock(site, blog, n, cfg, index, hist, used_photos, now):
    """오늘 글이 빈 블로그에 비상용 글을 n편까지 꺼내 쓴다: 이미 패키지가 된 비상용(오래된 것부터)을 오늘 글로 바꾸고,
    남은 drafts/stock/<key>-*.txt가 있으면 패키지로 만든다."""
    made = 0
    date = now.strftime("%Y-%m-%d")
    for p in sorted((p for p in index["packages"] if p.get("stock") and p["blogKey"] == blog["key"]),
                    key=lambda p: p.get("createdAt", ""))[:n]:
        p["stock"], p["fromStock"], p["date"] = False, p["date"], date
        log(f"  비상용 글을 오늘 글로 꺼냄: {p['title']}")
        made += 1
    n -= made
    for path in sorted((site / "drafts" / STOCK).glob(f"{blog['key']}-*.txt"))[:max(n, 0)]:
        if draft_package(path, site, cfg, index, hist, used_photos, now, now.strftime("%Y-%m-%d")):
            made += 1
    return made


KEYWORDS = {}


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
    import blog_keywords
    global KEYWORDS
    KEYWORDS = blog_keywords.load(site)  # 새벽 3시 25분 예약(또는 이 실행 앞 단계)이 모아 둔 인기 검색어·검색량
    made, failed = process_drafts(site, cfg, index, hist, used_photos, now)
    stop = drafts_only
    for blog in cfg["blogs"]:
        if only and blog["key"] not in only:
            continue
        if stop and not scheduled:
            break
        h = hist.setdefault(blog["key"], {"topics": [], "tone": -1})
        n_posts = count or int(env("BLOG_POSTS_PER_BLOG") or cfg.get("posts_per_blog", 2))
        if scheduled:  # 쇼핑커넥트·영상 글은 세지 않음: 일반 글만 하루 몫을 채운다
            have = sum(1 for p in index["packages"] if p["date"] == date and p["blogKey"] == blog["key"]
                       and p.get("kind") not in ("쇼핑", "영상") and not p.get("stock"))
            n_posts -= have
            if n_posts <= 0:
                log(f"[{blog['name']}] 오늘 일반 글이 이미 있어 건너뜁니다")
                continue
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
            topics = pick_topics(blog, n_posts, h["topics"], today, KEYWORDS)
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
            add_to_index(index, pid, date, blog, pkg, text, "Claude" if written or "claude" in env("BLOG_WRITER").lower() else "제미나이", now, t)
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
