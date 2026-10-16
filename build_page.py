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
THUMBS = OUT.parent / "thumbs"
THUMB_SIZE = 480

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
        out.append({"name": name, "full": str(rec.get("name", "")), "link": rec["link"], "at": max(times),
                    "key": rec["link"].rstrip("/").rsplit("/", 1)[-1]})
    return sorted(out, key=lambda i: i["at"], reverse=True)


def _small(path):
    try:
        from PIL import Image
        with Image.open(path) as im:
            return im.width < THUMB_SIZE
    except Exception:
        return True


def thumb(item):
    """상품 사진 폴더의 첫 장으로 작은 썸네일을 만든다(이미 있으면 그대로). 페이지에서 쓸 경로, 없으면 ''."""
    dest = THUMBS / f"{item['key']}.jpg"
    if not dest.exists() or _small(dest):
        try:
            import image_tools
            from PIL import Image, ImageOps
            folder = image_tools.photo_root() / image_tools.folder_name(item["full"] or item["name"])
            photos = image_tools.images_in(folder) if folder.is_dir() else []
            if not photos:
                return f"thumbs/{dest.name}" if dest.exists() else ""
            with Image.open(photos[0]) as im:
                im = ImageOps.fit(ImageOps.exif_transpose(im).convert("RGB"), (THUMB_SIZE, THUMB_SIZE))
                THUMBS.mkdir(parents=True, exist_ok=True)
                im.save(dest, "JPEG", quality=82, optimize=True)
        except Exception as e:
            print(f"  (썸네일을 만들지 못함: {item['name']} → {e})")
            return ""
    return f"thumbs/{dest.name}"


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
<meta name="theme-color" content="#fff4ee">
<title>{title}</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.min.css">
<style>
  :root {{ --bg:#fbf8f5; --card:#ffffff; --text:#1d1b1a; --muted:#8a817b; --accent:#ff6b4a; --accent2:#ff9a5a;
          --line:#efe8e2; --soft:#fff1ea; --shadow:0 6px 20px rgba(80,40,20,.07); }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg:#121110; --card:#1c1a19; --text:#f4efeb; --muted:#a39a94; --accent:#ff7d5c; --accent2:#ffaa6b;
            --line:#2c2826; --soft:#2a1f1b; --shadow:none; }}
  }}
  * {{ box-sizing:border-box; -webkit-tap-highlight-color:transparent; }}
  body {{ margin:0; background:var(--bg); color:var(--text);
         font-family:Pretendard,-apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Malgun Gothic",sans-serif; }}
  .hero {{ background:linear-gradient(160deg,var(--soft),var(--bg) 70%); padding:36px 16px 20px; text-align:center; }}
  .avatar {{ width:76px; height:76px; border-radius:50%; margin:0 auto 12px; display:grid; place-items:center;
            background:linear-gradient(135deg,var(--accent),var(--accent2)); color:#fff; font-size:30px; font-weight:800;
            box-shadow:0 8px 24px rgba(255,107,74,.35); }}
  h1 {{ font-size:22px; font-weight:800; margin:0; letter-spacing:-.02em; }}
  .handle {{ display:inline-block; margin-top:6px; color:var(--muted); font-size:14px; text-decoration:none; }}
  .count {{ display:inline-block; margin-top:12px; font-size:13px; font-weight:600; color:var(--accent);
           background:var(--card); border:1px solid var(--line); border-radius:999px; padding:6px 12px; }}
  main {{ max-width:620px; margin:0 auto; padding:0 16px 40px; }}
  .search {{ position:sticky; top:0; z-index:5; padding:12px 0; background:var(--bg); }}
  .search label {{ display:flex; align-items:center; gap:8px; background:var(--card); border:1px solid var(--line);
                  border-radius:14px; padding:0 14px; box-shadow:var(--shadow); }}
  .search svg {{ flex:none; color:var(--muted); }}
  input {{ flex:1; min-width:0; border:0; outline:0; background:transparent; color:var(--text);
          font:inherit; font-size:16px; padding:13px 0; }}
  .grid {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; }}
  a.item {{ display:flex; flex-direction:column; text-decoration:none; color:var(--text); background:var(--card);
           border:1px solid var(--line); border-radius:18px; overflow:hidden; box-shadow:var(--shadow);
           transition:transform .15s ease; }}
  a.item:active {{ transform:scale(.98); }}
  .pic {{ position:relative; aspect-ratio:1/1; background:var(--soft); }}
  .pic img {{ width:100%; height:100%; object-fit:cover; display:block; }}
  .pic .ph {{ width:100%; height:100%; display:grid; place-items:center; font-size:34px; font-weight:800;
             color:var(--accent); }}
  .new {{ position:absolute; top:10px; left:10px; background:var(--accent); color:#fff; font-size:11px; font-weight:800;
         letter-spacing:.04em; border-radius:999px; padding:4px 9px; }}
  .body {{ display:flex; flex-direction:column; gap:6px; padding:12px 12px 14px; flex:1; }}
  .name {{ font-size:14px; font-weight:700; line-height:1.4; word-break:keep-all; overflow-wrap:anywhere;
          display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; min-height:2.8em; }}
  .date {{ font-size:12px; color:var(--muted); }}
  .go {{ margin-top:auto; text-align:center; font-size:13px; font-weight:700; color:#fff; border-radius:12px; padding:10px 0;
        background:linear-gradient(135deg,var(--accent),var(--accent2)); }}
  .empty {{ color:var(--muted); text-align:center; padding:32px 0; display:none; }}
  .disc {{ max-width:460px; margin:14px auto 0; color:var(--muted); font-size:12px; line-height:1.6; }}
  @media (min-width:560px) {{ .grid {{ grid-template-columns:repeat(3,minmax(0,1fr)); }} }}
  @media (min-width:860px) {{ main {{ max-width:860px; }} .grid {{ grid-template-columns:repeat(4,minmax(0,1fr)); gap:14px; }} }}
</style>
</head>
<body>
<header class="hero">
  <div class="avatar">{initial}</div>
  <h1>{title}</h1>
  {handle}
  <div><span class="count">추천 상품 {count}개</span></div>
  <p class="disc">{notice}</p>
</header>
<main>
  <div class="search"><label>
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"
         stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>
    <input id="q" type="search" placeholder="게시물에서 본 상품 이름으로 찾기" autocomplete="off">
  </label></div>
  <div class="grid" id="list">
{rows}
  </div>
  <p class="empty" id="empty">찾는 상품이 없습니다. 이름 일부만 입력해 보세요.</p>
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
      <div class="pic">{img}{new}</div>
      <div class="body">
        <div class="name">{name}</div>
        <div class="date">{date}</div>
        <span class="go">쿠팡에서 보기</span>
      </div>
    </a>"""

NEW_DAYS = 3  # 게시 후 이 기간 동안 NEW 표시
HANDLE = (os.getenv("PAGE_HANDLE") or "aisidehustle_kr").strip().lstrip("@")


def build():
    import datetime
    rows = items()
    now = datetime.datetime.now()
    lines = []
    for r in rows:
        src = thumb(r)
        img = (f'<img src="{src}" alt="" loading="lazy">' if src
               else f'<div class="ph">{html.escape(r["name"][:1])}</div>')
        try:
            fresh = (now - datetime.datetime.fromisoformat(r["at"])).days < NEW_DAYS
        except ValueError:
            fresh = False
        lines.append(ROW.format(link=html.escape(r["link"], quote=True), name=html.escape(r["name"], quote=True),
                                date=r["at"][:10].replace("-", "."), img=img,
                                new='<span class="new">NEW</span>' if fresh else ""))
    handle = (f'<a class="handle" href="https://www.instagram.com/{html.escape(HANDLE)}/" '
              f'target="_blank" rel="noopener">@{html.escape(HANDLE)}</a>') if HANDLE else ""
    page = PAGE.format(title=html.escape(TITLE), rows="\n".join(lines), count=len(rows), handle=handle,
                       initial=html.escape(TITLE[:1]),
                       notice="<br>".join(html.escape(t) for t in disclosure(rows)))
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(page, encoding="utf-8")
    (OUT.parent / ".nojekyll").write_text("", encoding="utf-8")
    print(f"✓ 링크 페이지에 상품 {len(rows)}개를 넣었습니다: {OUT}")


if __name__ == "__main__":
    build()
