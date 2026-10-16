# -*- coding: utf-8 -*-
"""인스타 프로필에 걸어 둘 '구매 링크 모음' 페이지(docs/index.html)를 만든다.

posted.json에서 실제로 게시된 상품만 골라 최신 게시순으로 보여 준다.
GitHub Pages(저장소 Settings → Pages → main 브랜치 /docs)로 공개된다.

  python build_page.py
"""
import html
import json
import os
import pathlib
import sys

import affiliates

BASE = pathlib.Path(__file__).resolve().parent
POSTED = BASE / "posted.json"
OUT = BASE / "docs" / "index.html"

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

TITLE = (os.getenv("PAGE_TITLE") or "오늘의 추천 상품").strip()


def items():
    data = json.loads(POSTED.read_text(encoding="utf-8")) if POSTED.exists() else {}
    out = []
    for key, rec in data.items():
        if key == "_meta" or not isinstance(rec, dict) or not rec.get("link"):
            continue
        times = [rec[c]["at"] for c in ("threads", "instagram") if isinstance(rec.get(c), dict)]
        if not times:
            continue  # 아직 어디에도 올라가지 않은 상품은 페이지에 넣지 않음
        name = str(rec.get("name", "")).split(",")[0].strip() or rec["link"]
        out.append({"name": name, "link": rec["link"], "at": max(times)})
    return sorted(out, key=lambda i: i["at"], reverse=True)


def disclosure(rows):
    texts = []
    for r in rows:
        t = affiliates.detect(r["link"])["disclosure"]
        if t not in texts:
            texts.append(t)
    return texts or [affiliates.detect("https://link.coupang.com/")["disclosure"]]


PAGE = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>{title}</title>
<style>
  :root {{ --bg:#f6f5f2; --card:#fff; --text:#1f2328; --muted:#6b7280; --accent:#e4572e; --line:#e7e5e0; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg:#141414; --card:#1f1f1f; --text:#f1f1f1; --muted:#a1a1aa; --accent:#ff7a50; --line:#2e2e2e; }}
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--text);
         font-family:-apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Malgun Gothic",sans-serif; }}
  main {{ max-width:560px; margin:0 auto; padding:24px 16px 48px; }}
  h1 {{ font-size:22px; margin:0 0 8px; }}
  .notice {{ font-size:13px; color:var(--muted); background:var(--card); border:1px solid var(--line);
            border-radius:12px; padding:12px 14px; margin:12px 0 16px; line-height:1.5; }}
  input {{ width:100%; font-size:16px; padding:12px 14px; border-radius:12px; border:1px solid var(--line);
          background:var(--card); color:var(--text); margin-bottom:14px; }}
  a.item {{ display:flex; justify-content:space-between; align-items:center; gap:12px; text-decoration:none;
           color:var(--text); background:var(--card); border:1px solid var(--line); border-radius:14px;
           padding:16px; margin-bottom:10px; }}
  a.item:active {{ transform:scale(.99); }}
  .item > div {{ min-width:0; }}
  .name {{ font-weight:600; line-height:1.4; word-break:keep-all; overflow-wrap:anywhere; }}
  .date {{ font-size:12px; color:var(--muted); margin-top:4px; }}
  .go {{ flex:none; font-size:14px; font-weight:700; color:#fff; background:var(--accent);
        border-radius:999px; padding:8px 14px; }}
  .empty {{ color:var(--muted); text-align:center; padding:24px 0; display:none; }}
</style>
</head>
<body>
<main>
  <h1>{title}</h1>
  <div class="notice">{notice}</div>
  <input id="q" type="search" placeholder="상품 이름으로 찾기" autocomplete="off">
  <div id="list">
{rows}
  </div>
  <p class="empty" id="empty">찾는 상품이 없습니다.</p>
</main>
<script>
  const q = document.getElementById('q'), list = document.querySelectorAll('a.item'),
        empty = document.getElementById('empty');
  const norm = s => s.toLowerCase().replace(/\\s+/g, '');
  q.addEventListener('input', () => {{
    const k = norm(q.value); let shown = 0;
    list.forEach(a => {{ const ok = norm(a.dataset.name).includes(k); a.style.display = ok ? '' : 'none'; shown += ok; }});
    empty.style.display = shown ? 'none' : 'block';
  }});
</script>
</body>
</html>
"""

ROW = """    <a class="item" href="{link}" target="_blank" rel="sponsored noopener" data-name="{name}">
      <div><div class="name">{name}</div><div class="date">{date}</div></div>
      <span class="go">구매하기</span>
    </a>"""


def build():
    rows = items()
    body = "\n".join(ROW.format(link=html.escape(r["link"], quote=True), name=html.escape(r["name"], quote=True),
                                date=r["at"][:10].replace("-", ".")) for r in rows)
    page = PAGE.format(title=html.escape(TITLE), rows=body,
                       notice="<br>".join(html.escape(t) for t in disclosure(rows)))
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(page, encoding="utf-8")
    (OUT.parent / ".nojekyll").write_text("", encoding="utf-8")
    print(f"✓ 링크 페이지에 상품 {len(rows)}개를 넣었습니다: {OUT}")


if __name__ == "__main__":
    build()
