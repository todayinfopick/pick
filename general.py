# -*- coding: utf-8 -*-
"""일반 글(광고 아님) 자동 게시: 쓰레드에 링크 없는 소통용 글을 올린다.

  python general.py               : 지금 한 개 게시
  python general.py --dry-run     : 글만 만들어 보여 주기
  python general.py --slot "..."  : 예약 회차로 게시 (같은 회차를 다시 올리지 않게 기록)

글감: 시트 '일반글' 탭의 '주제' 칸(위에서부터, 아직 안 쓴 것) → 없으면 AI가 계정 주제(GENERAL_THEME)와
계절에 맞춰 직접 고름. 글은 제미나이(무료 키)로 쓰고, 키가 없으면 Claude로 씀(1회 약 1원).
"""
import argparse
import datetime
import json
import sys

import main
from main import env, log

PROMPT = """너는 쓰레드(Threads)에 글을 올리는 '{theme}' 계정 주인이다. 광고가 아닌 소통용 글을 하나 써라.

오늘: {today} ({season})
{topic_line}
최근에 쓴 글감(겹치지 않게): {recent}

규칙
- 280자 이내. 첫 줄은 눈길을 끄는 한 줄, 마지막 줄은 읽는 사람이 댓글을 달고 싶어지는 가벼운 질문.
- 친구한테 말하듯 반말을 섞은 편한 말투 ("~더라", "~하면 딱이야", "이거 알아?").
- 바로 써먹을 수 있는 구체적인 팁 1~3개. 뻔한 말만 늘어놓지 마라. 직접 써 본 척하는 상품 후기는 쓰지 마라.
- 특정 상품명·브랜드·링크·가격·구매 권유 금지. 광고처럼 읽히면 안 된다.
- 의학적 효과 단정, 과장 금지. 이모지 0~2개, 해시태그 없음.

photo: 함께 올릴 사진을 무료 사진 사이트에서 찾을 영어 검색어 2~4단어. 글 분위기에 맞고 사람 얼굴보다
  손·물건·장면 위주로. 상품·브랜드 이름 금지. 예: "knit sweater closeup", "lip balm hands"
card: 사진이 없을 때 쓸 글자 카드의 큰 한 줄 (16자 이내, 고민·질문형, 이모지 없음). 예: "니트 정전기 그만!"
card_sub: 글자 카드 아래쪽 작은 한 줄 (20자 이내). 예: "외출 전 1분이면 끝"

다른 말 없이 JSON만 출력: {{"topic": "글감 한 줄", "text": "본문", "photo": "...", "card": "...", "card_sub": "..."}}"""

SEASONS = {12: "겨울", 1: "겨울", 2: "겨울", 3: "봄", 4: "봄", 5: "봄", 6: "여름", 7: "여름", 8: "여름",
           9: "가을", 10: "가을", 11: "늦가을·초겨울"}


def sheet_topic():
    """시트 '일반글' 탭에서 아직 안 쓴 첫 주제 → (행 번호, 주제). 없으면 (None, '')."""
    try:
        import gcloud
        if not gcloud.enabled():
            return None, ""
        rows = gcloud.read_tab("일반글")
    except Exception as e:
        log(f"  (일반글 탭을 읽지 못해 AI가 글감을 고릅니다: {e})")
        return None, ""
    if not rows:
        return None, ""
    head = [h.strip() for h in rows[0]]
    if "주제" not in head:
        return None, ""
    ti = head.index("주제")
    di = head.index("게시일") if "게시일" in head else None
    for n, r in enumerate(rows[1:], start=2):
        topic = r[ti].strip() if len(r) > ti else ""
        done = r[di].strip() if di is not None and len(r) > di else ""
        if topic and not done:
            return n, topic
    return None, ""


def mark_sheet(row, when):
    """'일반글' 탭의 그 줄 '게시일' 칸에 날짜를 적는다 (칸이 없으면 만든다)."""
    try:
        import gcloud
        rows = gcloud.read_tab("일반글")
        head = [h.strip() for h in rows[0]]
        if "게시일" not in head:
            gcloud.write_cell(1, len(head) + 1, "게시일", "일반글")
            col = len(head) + 1
        else:
            col = head.index("게시일") + 1
        gcloud.write_cell(row, col, when, "일반글")
    except Exception as e:
        log(f"  (일반글 탭에 게시일을 적지 못했습니다: {e})")


def write(theme, topic, recent):
    now = datetime.datetime.now()
    prompt = PROMPT.format(theme=theme, today=f"{now:%m월 %d일}", season=SEASONS[now.month],
                           topic_line=f"글감: {topic}" if topic else "글감: 계정 주제 안에서 지금 계절에 맞게 네가 골라라.",
                           recent=", ".join(recent[-12:]) or "없음")
    import memo_ai
    if memo_ai.env("GEMINI_API_KEY"):
        text = memo_ai.generate([{"text": prompt}], temperature=0.9)
    else:
        if not env("ANTHROPIC_API_KEY"):
            raise RuntimeError("제미나이 키나 Claude 키가 있어야 일반 글을 쓸 수 있습니다.")
        r = main._ask_ai({"model": env("CLAUDE_MODEL", "claude-haiku-5-5"), "max_tokens": 1200,
                          "messages": [{"role": "user", "content": prompt}]})
        main.check(r, "AI 일반 글 생성")
        text = "".join(b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text")
    data = json.loads(text[text.find("{"):text.rfind("}") + 1], strict=False)
    body = str(data.get("text", "")).strip()
    if len(body) < 20:
        raise RuntimeError(f"AI가 쓴 글이 너무 짧습니다: {body!r}")
    return {"topic": str(data.get("topic", topic)).strip() or topic, "text": body[:500],
            "photo": str(data.get("photo", "")).strip()[:60],
            "card": str(data.get("card", "")).strip()[:24], "card_sub": str(data.get("card_sub", "")).strip()[:30]}


def pexels_photo(query, used):
    """Pexels(무료 사진)에서 검색어에 맞는 세로 사진 한 장 → (저장한 파일, 사진 id). 없으면 (None, None)."""
    import random
    import requests
    import image_tools
    key = env("PEXELS_API_KEY")
    if not key or not query:
        return None, None
    r = requests.get("https://api.pexels.com/v1/search", headers={"Authorization": key}, timeout=30,
                     params={"query": query, "orientation": "portrait", "per_page": 15, "size": "medium"})
    main.check(r, "Pexels 사진 검색")
    photos = [p for p in r.json().get("photos", []) if str(p["id"]) not in used] or r.json().get("photos", [])
    if not photos:
        return None, None
    p = random.choice(photos[:8])
    img = requests.get(p["src"].get("large2x") or p["src"]["original"], timeout=60)
    img.raise_for_status()
    image_tools.OUT_DIR.mkdir(exist_ok=True)
    path = image_tools.OUT_DIR / "general.jpg"
    path.write_bytes(img.content)
    return path, str(p["id"])


def post_image(post, used, dry):
    """일반 글에 붙일 이미지 → (파일 경로, 공개 주소, 사진 id).
    사진: Pexels 키가 있으면 글감에 맞는 사진 / 카드: 글자 카드 / 없음. 실패하면 글만."""
    mode = env("GENERAL_IMAGE", "사진")
    try:
        import image_tools
        path, pid = None, None
        if mode == "사진":
            if not env("PEXELS_API_KEY"):
                log("  (Pexels 키가 없어 사진 없이 글만 올립니다. 설정 → 일반 글에서 넣어 주세요)")
                return None, None, None
            path, pid = pexels_photo(post["photo"], used)
        elif mode == "카드" and post["card"]:
            path = image_tools.make_tip_card(post["card"], post["card_sub"], env("GENERAL_THEME", ""), key="general")
        if not path:
            return None, None, None
        return path, (None if dry else image_tools.upload(path)), pid
    except Exception as e:
        log(f"  (일반 글 이미지를 준비하지 못해 글만 올립니다: {e})")
        return None, None, None


def run(dry=False, slot=""):
    posted = main.load_posted()
    meta = posted.setdefault("_meta", {})
    if slot:
        meta["last_general_slot"] = slot
        main.save_posted(posted)  # 실패해도 같은 회차를 매시간 다시 시도하지 않도록 먼저 기록
    if not dry and not main.threads_on():
        log("일반 글: 쓰레드 연결 정보가 없거나 꺼져 있어 건너뜁니다.")
        return 0
    history = posted.setdefault("_general", [])
    row, topic = sheet_topic()
    try:
        post = write(env("GENERAL_THEME", "뷰티·생활 꿀팁"), topic, [h.get("topic", "") for h in history])
    except Exception as e:
        log(f"일반 글 ✗ {e}")
        return 1
    topic, body = post["topic"], post["text"]
    log(f"일반 글: {topic}")
    path, url, photo_id = post_image(post, {h.get("photo_id") for h in history}, dry)
    if dry:
        print("\n========== 일반 글 미리보기 ==========\n" + body + "\n")
        if path:
            what = f"Pexels 사진 '{post['photo']}' (id {photo_id})" if photo_id else f"글자 카드 {post['card']}"
            print(f"이미지: {what} → {path}\n")
        else:
            print(f"이미지 없음 (사진 검색어였던 것: {post['photo']})\n")
        return 0
    try:
        pid = main.threads_post(body, [url], "image") if url else main.threads_post(body)
    except Exception as e:
        log(f"  ✗ threads 일반 글: {e}")
        return 1
    log(f"  ✓ threads 일반 글 완료 (id {pid})")
    history.append({"topic": topic, "id": pid, "photo_id": photo_id,
                    "at": datetime.datetime.now().isoformat(timespec="seconds")})
    posted["_general"] = history[-60:]
    main.save_posted(posted)
    if row:
        mark_sheet(row, f"{datetime.datetime.now():%Y-%m-%d %H:%M}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--slot", default="")
    a = ap.parse_args()
    sys.exit(run(a.dry_run, a.slot))
