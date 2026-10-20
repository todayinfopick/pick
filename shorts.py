# -*- coding: utf-8 -*-
"""유튜브 쇼츠용 상품 영상 (세로 1080x1920, 20~35초).
장면: 표지 → 상품 사진(천천히 확대·이동) 위에 AI 목소리 설명 + 큰 자막 → 구매 안내 카드.
- 대본: 제미나이(무료)가 상품명·특징메모로 짧은 말 5~6줄을 쓴다. 실패하면 게시 글의 제목·장점으로 대신.
- 목소리: edge-tts (무료, 마이크로소프트 한국어 음성). SHORTS_VOICE로 바꿀 수 있음 (기본 ko-KR-SunHiNeural, 남자 ko-KR-InJoonNeural), 빠르기 SHORTS_RATE (기본 +20% = 1.2배).
- 장면 길이는 그 줄을 읽는 시간에 맞춘다. 배경음악(bgm/)은 목소리 밑에 아주 작게.
python shorts.py "상품명 일부"  → out/쇼츠_*.mp4 (시험용)"""
import asyncio
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile

from PIL import Image, ImageDraw

import blog_video as bv
import image_tools as it
from video_tools import _ffmpeg

W, H = 1080, 1920
COVER_SEC, END_SEC, GAP = 1.4, 2.2, 0.15
VOICE = os.environ.get("SHORTS_VOICE", "ko-KR-SunHiNeural")
RATE = os.environ.get("SHORTS_RATE", "+20%")  # 쇼핑 쇼츠는 보통 1.2배 정도로 빠르게
MARK = os.environ.get("SHORTS_MARK", "@오늘의픽쇼핑")  # 영상 위쪽에 옅게 넣는 채널 이름 (퍼가기 방지). 비우면 없음

SCRIPT_PROMPT = """너는 쿠팡 상품을 소개하는 유튜브 쇼츠 대본 작가다.
상품: {name}
특징 메모: {memo}

규칙
- 소리 내어 읽을 문장 5~6개. 한 문장은 25자 안팎, 친구에게 말하듯 자연스러운 존댓말(~요).
- 첫 문장은 시청자의 고민이나 질문으로 시작하는 훅 (예: "김장 통, 아직도 작은 거 여러 개 쓰세요?").
- 가운데는 실제로 쓸 때 좋은 점을 하나씩. 과장·최저가·효과 보장 표현 금지, 메모에 없는 수치 지어내지 않기.
- 마지막 문장은 "구매 링크는 프로필 링크에서 확인하세요" 같은 안내 (쇼츠 설명란 링크는 눌리지 않음).
- 이모지·해시태그·따옴표 없이.
JSON 하나만 출력: {{"title": "표지에 크게 넣을 12자 이내 문구", "lines": ["문장1", "문장2", ...],
 "yt_title": "유튜브 제목 (40자 이내, 궁금하게 만드는 한 줄, 상품 종류가 드러나게)", "tags": ["해시태그 단어 4~6개, # 없이"]}}"""


def write_script(item, text=None):
    """대본: {"title": 표지 문구, "lines": [읽을 문장들]}."""
    try:
        import memo_ai
        out = memo_ai.generate([{"text": SCRIPT_PROMPT.format(name=item["name"], memo=item.get("memo") or "(없음)")}],
                               temperature=0.8)
        data = json.loads(out[out.find("{"):out.rfind("}") + 1], strict=False)
        lines = [re.sub(r"\s+", " ", str(x)).strip() for x in data.get("lines", []) if str(x).strip()]
        if len(lines) >= 3:
            tags = [re.sub(r"[#\s]", "", str(t)) for t in data.get("tags") or []]
            return {"title": str(data.get("title") or item["short"])[:16], "lines": lines[:7],
                    "yt_title": str(data.get("yt_title") or "").strip()[:60], "tags": [t for t in tags if t][:6]}
    except Exception as e:
        print(f"  (쇼츠 대본을 제미나이로 못 써서 게시 글로 대신: {e})")
    text = text or {"headline": item["short"][:16], "points": []}
    lines = [text["headline"]] + [p for p in text["points"] if p] + ["구매 링크는 프로필 링크에서 확인하세요"]
    return {"title": text["headline"][:16], "lines": lines, "yt_title": "", "tags": []}


async def _speak(line, path):
    import edge_tts
    await edge_tts.Communicate(line, VOICE, rate=RATE).save(str(path))


def _duration(path):
    """ffmpeg가 알려 주는 길이(초)."""
    r = subprocess.run([_ffmpeg(), "-i", str(path)], capture_output=True, text=True)
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", r.stderr)
    if not m:
        raise RuntimeError(f"목소리 파일 길이를 알 수 없습니다: {path}")
    return int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])


def _wrap_words(d, text, fnt, max_w):
    """띄어쓰기 단위로 줄바꿈 (낱말 중간에서 안 끊기게). 한 낱말이 너무 길면 글자 단위로."""
    lines, cur = [], ""
    for word in text.split():
        cand = f"{cur} {word}".strip()
        if cur and d.textlength(cand, font=fnt) > max_w:
            lines.append(cur)
            cur = word
        else:
            cur = cand
    if cur:
        lines.append(cur)
    out = []
    for line in lines:
        out += it.wrap(d, line, fnt, max_w) if d.textlength(line, font=fnt) > max_w else [line]
    return out


class Talk(bv.Photo):
    """사진 장면 + 두 줄까지 들어가는 큰 자막 (읽는 문장 그대로)."""

    def _caption(self, text):
        w, h = self.w, self.h
        ov = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        if not text:
            return ov
        d = ImageDraw.Draw(ov)
        size = int(w * 0.068)
        while True:
            fnt = bv._heavy(size)
            lines = _wrap_words(d, text, fnt, w * 0.84)
            if len(lines) <= 2 or size <= 48:
                break
            size -= 4
        lines = lines[:2]
        lh = int(size * 1.3)
        y0 = int(h * 0.70)
        sw = max(4, size // 12)
        for i, line in enumerate(lines):
            d.text((w // 2, y0 + i * lh), line, font=fnt, fill=(255, 255, 255), anchor="mt",
                   stroke_width=sw, stroke_fill=(0, 0, 0))
        return ov


def _mark(text):
    """왼쪽 위 옅은 채널 이름. 쇼츠 화면의 버튼(오른쪽·아래)과 안 겹치는 자리."""
    size = int(W * 0.034)
    fnt = bv._heavy(size)
    d = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    tw = int(d.textlength(text, font=fnt))
    ov = Image.new("RGBA", (tw + size, int(size * 1.6)), (0, 0, 0, 0))
    ImageDraw.Draw(ov).text((size // 2, ov.height // 2), text, font=fnt, fill=(255, 255, 255, 150), anchor="lm",
                            stroke_width=2, stroke_fill=(0, 0, 0, 90))
    return ov


def make(out, item, photos, script=None, footer=""):
    """쇼츠 영상 하나를 out(mp4)에 만든다. photos: PIL 이미지 3장 이상 (모자라면 돌려 씀)."""
    if len(photos) < 3:
        raise RuntimeError("쇼츠에 쓸 상품 사진이 3장보다 적습니다.")
    script = script or write_script(item)
    lines = script["lines"]
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="shorts_"))
    voices = []
    for i, line in enumerate(lines):
        p = tmp / f"{i:02d}.mp3"
        asyncio.run(_speak(line, p))
        voices.append((p, _duration(p)))

    scenes = [(COVER_SEC, bv.Still(bv._title_card(W, H, script["title"])))]
    for k, (line, (_, sec)) in enumerate(zip(lines, voices)):
        scenes.append((sec + GAP, Talk(W, H, photos[k % len(photos)], line, k)))
    scenes.append((END_SEC, bv.Still(bv._title_card(W, H, "구매 링크는 프로필에", "쿠팡 파트너스 · 수수료를 받을 수 있어요"))))
    total = sum(s for s, _ in scenes)

    # 목소리: 각 장면이 시작하는 시각에 그 줄을 놓는다
    inputs, mix = [], []
    t = COVER_SEC
    for i, (p, sec) in enumerate(voices):
        inputs += ["-i", str(p)]
        ms = int((t + 0.1) * 1000)
        mix.append(f"[{i + 1}:a]adelay={ms}|{ms}[v{i}]")
        t += sec + GAP
    labels = "".join(f"[v{i}]" for i in range(len(voices)))
    filt = ";".join(mix) + f";{labels}amix=inputs={len(voices)}:normalize=0[voice]"
    bgm = bv._bgm()
    if bgm:
        inputs += ["-stream_loop", "-1", "-i", bgm]
        filt += (f";[{len(voices) + 1}:a]volume=0.08,afade=t=out:st={max(0, total - 1.5):.2f}:d=1.5[bg]"
                 f";[voice][bg]amix=inputs=2:normalize=0:duration=first[a]")
    else:
        filt += ";[voice]anull[a]"

    foot = bv._footer(W, H, footer) if footer else None
    mark = _mark(MARK) if MARK else None
    cmd = [_ffmpeg(), "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
           "-r", str(bv.FPS), "-i", "-"] + inputs
    cmd += ["-filter_complex", filt, "-map", "0:v", "-map", "[a]", "-t", f"{total:.2f}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-movflags", "+faststart", str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    try:
        start, k, nxt = 0.0, 0, {}
        for f in range(int(round(total * bv.FPS))):
            t = f / bv.FPS
            while k < len(scenes) - 1 and t >= start + scenes[k][0]:
                start += scenes[k][0]
                k += 1
            dur, sc = scenes[k]
            frame = sc.render(min(1.0, (t - start) / dur))
            if k < len(scenes) - 1 and t - start > dur - bv.FADE:
                if k + 1 not in nxt:
                    nxt[k + 1] = scenes[k + 1][1].render(0)
                frame = Image.blend(frame, nxt[k + 1], (t - start - (dur - bv.FADE)) / bv.FADE)
            if foot is not None or mark is not None:
                frame = frame.copy()
            if foot is not None:
                frame.paste(foot, (0, H - foot.height), foot)
            if mark is not None and 0 < k < len(scenes) - 1:  # 표지·마무리 카드엔 안 넣음
                frame.paste(mark, (int(W * 0.04), int(H * 0.055)), mark)
            proc.stdin.write(frame.tobytes())
    finally:
        proc.stdin.close()
        proc.wait()
    if proc.returncode != 0 or not pathlib.Path(out).exists():
        raise RuntimeError("쇼츠 영상 만들기에 실패했습니다 (ffmpeg 오류).")
    return out


# ---------------------------------------------------------------- 매일 자동 (반자동 업로드)
# 게시한 상품으로 하루 SHORTS_PER_DAY개까지 쇼츠를 만들어 GitHub 릴리스 'shorts'에 올리고,
# 휴대폰용 페이지(docs/shorts/)에 영상 받기 + 제목·설명 복사 버튼을 만든다. 사람이 유튜브 앱으로 올린다.
# (유튜브는 심사 안 받은 프로그램으로 올린 영상을 비공개로 막아서 업로드는 사람이 함)
BASE = pathlib.Path(__file__).resolve().parent
PAGE = BASE / "docs" / "shorts" / "index.html"
TAG = "shorts"
KEEP_DAYS = 14
DISCLOSURE_FULL = "이 영상은 쿠팡 파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다."


def _gh(method, url, **kw):
    import requests
    token = os.environ.get("SHORTS_GH_TOKEN") or os.environ.get("GITHUB_TOKEN", "")
    h = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    h.update(kw.pop("headers", {}))
    r = requests.request(method, url, headers=h, timeout=300, **kw)
    if r.status_code >= 400 and not (method == "GET" and r.status_code == 404):
        raise RuntimeError(f"GitHub {method} {url.split('?')[0]} → {r.status_code} {r.text[:200]}")
    return r


def _release(repo):
    r = _gh("GET", f"https://api.github.com/repos/{repo}/releases/tags/{TAG}")
    if r.status_code == 404:
        r = _gh("POST", f"https://api.github.com/repos/{repo}/releases",
                json={"tag_name": TAG, "name": "유튜브 쇼츠 (자동)", "make_latest": "false",
                      "body": "쇼츠 받기 페이지: https://todayinfopick.github.io/pick/shorts/"})
    return r.json()


def upload(path, name):
    """릴리스에 영상을 올리고 받기 주소를 돌려준다 (같은 이름이 있으면 바꿈)."""
    repo = os.environ.get("GITHUB_REPOSITORY", "todayinfopick/pick")
    rel = _release(repo)
    for a in rel.get("assets", []):
        if a["name"] == name:
            _gh("DELETE", a["url"])
    up = rel["upload_url"].split("{")[0]
    with open(path, "rb") as f:
        _gh("POST", f"{up}?name={name}", data=f, headers={"Content-Type": "video/mp4"})
    return f"https://github.com/{repo}/releases/download/{TAG}/{name}"


def prune(keep_names):
    """오래된 쇼츠 영상은 릴리스에서 지운다."""
    repo = os.environ.get("GITHUB_REPOSITORY", "todayinfopick/pick")
    for a in _release(repo).get("assets", []):
        if a["name"] not in keep_names:
            _gh("DELETE", a["url"])


def yt_text(item, script):
    title = (script.get("yt_title") or script["title"] or item["short"]).strip()
    title = f"{title} #shorts"[:100]
    tags = " ".join("#" + t for t in (script.get("tags") or []) + ["쿠팡추천", "살림템"])
    desc = "\n".join([DISCLOSURE_FULL, "", *script["lines"][:-1], "",
                      "🛒 구매 링크는 채널 프로필 링크에서 확인하세요.", "", tags])
    return title, desc


def daily():
    import datetime
    import main as m  # .env를 불러옴
    global VOICE, RATE, MARK
    VOICE = os.environ.get("SHORTS_VOICE", VOICE)
    RATE = os.environ.get("SHORTS_RATE", RATE)
    MARK = os.environ.get("SHORTS_MARK", MARK)
    if m.env("SHORTS_ON", "0") != "1":
        print("쇼츠 만들기가 꺼져 있습니다 (설정 SHORTS_ON).")
        return
    per_day = int(m.env("SHORTS_PER_DAY", "2") or 2)
    today = datetime.date.today().isoformat()
    posted = m.load_posted()
    made = sum(1 for k, v in posted.items() if k != "_meta" and isinstance(v, dict)
               and str((v.get("shorts") or {}).get("at", ""))[:10] == today)
    for item in m.load_products():
        if made >= per_day:
            break
        rec = m.get_rec(posted, item)
        times = [rec[ch]["at"] for ch in ("threads", "instagram") if isinstance(rec.get(ch), dict)]
        if not times or "shorts" in rec or max(times)[:10] != today:  # 오늘 게시한 상품만, 한 번만
            continue
        photos = it.pick_photos(it.load_photos(item["source"], item["name"]), it.detail_photos(item["name"]), 6,
                                name=item["name"])
        if len(photos) < 3:
            print(f"  쇼츠: 사진이 모자라 건너뜀 ({item['short']})")
            continue
        it.OUT_DIR.mkdir(exist_ok=True)
        key = it.slug(item["link"].rstrip("/").rsplit("/", 1)[-1])
        name = f"shorts_{today}_{key}.mp4"
        out = it.OUT_DIR / name
        script = write_script(item)
        make(out, item, photos, script, footer="광고 · " + item["aff"]["short"])
        url = upload(out, name)
        title, desc = yt_text(item, script)
        rec["shorts"] = {"at": datetime.datetime.now().isoformat(timespec="seconds"), "file": name, "url": url,
                         "title": title, "desc": desc, "sec": round(_duration(out), 1)}
        made += 1
        print(f"✓ 쇼츠: {item['short']} → {url}")
        m.save_posted(posted)
    build_page(posted)


def build_page(posted=None):
    """휴대폰에서 여는 쇼츠 받기 페이지 (docs/shorts/index.html)."""
    import datetime
    import html
    if posted is None:
        posted = json.loads((BASE / "posted.json").read_text(encoding="utf-8"))
    since = (datetime.date.today() - datetime.timedelta(days=KEEP_DAYS)).isoformat()
    rows = sorted((v for k, v in posted.items() if k != "_meta" and isinstance(v, dict)
                   and str((v.get("shorts") or {}).get("at", "")) >= since), key=lambda v: v["shorts"]["at"], reverse=True)
    if os.environ.get("SHORTS_GH_TOKEN") or os.environ.get("GITHUB_TOKEN"):
        try:
            prune({v["shorts"]["file"] for v in rows})
        except Exception as e:
            print(f"  (오래된 쇼츠 정리 실패: {e})")
    cards = []
    for i, v in enumerate(rows):
        s = v["shorts"]
        e = html.escape
        cards.append(f"""<section class="card" data-id="{e(s['file'])}">
  <div class="top"><b>{e(str(v.get('name', '')).split(',')[0])}</b><span>{e(s['at'][:16].replace('T', ' '))} · {s.get('sec', '')}초</span></div>
  <video src="{e(s['url'])}" controls playsinline preload="none"></video>
  <a class="btn main" href="{e(s['url'])}">① 영상 받기</a>
  <label>② 제목</label><textarea id="t{i}" rows="2" readonly>{e(s['title'])}</textarea>
  <button class="btn" onclick="cp('t{i}',this)">제목 복사</button>
  <label>③ 설명</label><textarea id="d{i}" rows="7" readonly>{e(s['desc'])}</textarea>
  <button class="btn" onclick="cp('d{i}',this)">설명 복사</button>
  <label class="done"><input type="checkbox" onchange="mark(this)"> 유튜브에 올렸어요</label>
</section>""")
    body = "\n".join(cards) or '<p class="empty">아직 만든 쇼츠가 없어요. 상품이 게시되면 하루 2개씩 여기에 생겨요.</p>'
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    PAGE.write_text(f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">
<title>쇼츠 올리기</title><style>
body{{margin:0;background:#f4f5f7;font-family:-apple-system,'Apple SD Gothic Neo','Malgun Gothic',sans-serif;color:#111}}
header{{background:#0b0e1d;color:#ffe27a;padding:16px;font-weight:800;font-size:20px}}
header small{{display:block;color:#cfd3e0;font-weight:400;font-size:13px;margin-top:4px}}
.card{{background:#fff;margin:12px;padding:14px;border-radius:14px;box-shadow:0 1px 3px rgba(0,0,0,.08)}}
.card.ok{{opacity:.45}} .top{{display:flex;justify-content:space-between;gap:8px;font-size:15px}} .top span{{color:#777;font-size:12px;white-space:nowrap}}
video{{width:100%;max-height:60vh;background:#000;border-radius:10px;margin:10px 0}}
label{{display:block;font-size:13px;color:#555;margin:10px 0 4px}} textarea{{width:100%;box-sizing:border-box;font-size:14px;border:1px solid #ddd;border-radius:8px;padding:8px}}
.btn{{display:block;width:100%;box-sizing:border-box;text-align:center;padding:12px;margin-top:6px;border:0;border-radius:10px;background:#e8eaf0;font-size:15px;color:#111;text-decoration:none}}
.btn.main{{background:#d9415f;color:#fff;font-weight:700}} .done{{font-size:15px;color:#111}} .empty{{padding:24px;text-align:center;color:#666}}
</style></head><body>
<header>오늘의 픽 · 쇼츠 올리기<small>① 영상 받기 → 유튜브 앱 + → 동영상 업로드 → ② 제목·③ 설명 붙여넣기 → '유료 프로모션 포함' 켜기</small></header>
{body}
<script>
function cp(id,b){{const t=document.getElementById(id);t.select();navigator.clipboard?navigator.clipboard.writeText(t.value):document.execCommand('copy');b.dataset.l=b.dataset.l||b.textContent;b.textContent='✓ 복사됨';setTimeout(()=>b.textContent=b.dataset.l,1500)}}
function mark(c){{const s=c.closest('.card');s.classList.toggle('ok',c.checked);try{{const d=JSON.parse(localStorage.getItem('up')||'{{}}');d[s.dataset.id]=c.checked;localStorage.setItem('up',JSON.stringify(d))}}catch(e){{}}}}
try{{const d=JSON.parse(localStorage.getItem('up')||'{{}}');document.querySelectorAll('.card').forEach(s=>{{if(d[s.dataset.id]){{s.classList.add('ok');s.querySelector('input').checked=true}}}})}}catch(e){{}}
</script></body></html>""", encoding="utf-8")


def main():
    """시험용: 상품명 일부를 주면 그 상품으로 쇼츠 하나를 만든다."""
    import main as m
    want = (sys.argv[1] if len(sys.argv) > 1 else "").replace(" ", "")
    items = m.load_products()
    items = sorted(items, key=lambda i: want not in i["name"].replace(" ", ""))  # 고른 상품 먼저, 없으면 아무 상품
    for item in items:
        photos = it.load_photos(item["source"], item["name"])
        photos = it.pick_photos(photos, it.detail_photos(item["name"]), 6, name=item["name"])
        if len(photos) < 3:
            print(f"  사진이 모자라 건너뜀: {item['short']}")
            continue
        it.OUT_DIR.mkdir(exist_ok=True)
        out = it.OUT_DIR / f"쇼츠_{it.slug(item['short'])[:30]}.mp4"
        script = write_script(item)
        print(json.dumps(script, ensure_ascii=False, indent=1))
        make(out, item, photos, script, footer="광고 · " + item["aff"]["short"])
        print(f"✓ {out} ({_duration(out):.1f}초)")
        return
    raise SystemExit("사진이 3장 이상 있는 상품을 찾지 못했습니다.")


if __name__ == "__main__":
    if sys.argv[1:2] == ["--daily"]:
        daily()
    elif sys.argv[1:2] == ["--page"]:
        build_page()
    else:
        main()
