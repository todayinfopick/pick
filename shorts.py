# -*- coding: utf-8 -*-
"""유튜브 쇼츠용 상품 영상 (세로 1080x1920, 20~35초).
장면: 표지 → 상품 사진(천천히 확대·이동) 위에 AI 목소리 설명 + 큰 자막 → 구매 안내 카드.
- 대본: 제미나이(무료)가 상품명·특징메모로 짧은 말 5~6줄을 쓴다. 실패하면 게시 글의 제목·장점으로 대신.
- 목소리: edge-tts (무료, 마이크로소프트 한국어 음성). SHORTS_VOICE로 바꿀 수 있음 (기본 ko-KR-SunHiNeural, 남자 ko-KR-InJoonNeural).
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
COVER_SEC, END_SEC, GAP = 1.6, 2.4, 0.25
VOICE = os.environ.get("SHORTS_VOICE", "ko-KR-SunHiNeural")

SCRIPT_PROMPT = """너는 쿠팡 상품을 소개하는 유튜브 쇼츠 대본 작가다.
상품: {name}
특징 메모: {memo}

규칙
- 소리 내어 읽을 문장 5~6개. 한 문장은 25자 안팎, 친구에게 말하듯 자연스러운 존댓말(~요).
- 첫 문장은 시청자의 고민이나 질문으로 시작하는 훅 (예: "김장 통, 아직도 작은 거 여러 개 쓰세요?").
- 가운데는 실제로 쓸 때 좋은 점을 하나씩. 과장·최저가·효과 보장 표현 금지, 메모에 없는 수치 지어내지 않기.
- 마지막 문장은 "구매 링크는 프로필 링크에서 확인하세요" 같은 안내 (쇼츠 설명란 링크는 눌리지 않음).
- 이모지·해시태그·따옴표 없이.
JSON 하나만 출력: {{"title": "표지에 크게 넣을 12자 이내 문구", "lines": ["문장1", "문장2", ...]}}"""


def write_script(item, text=None):
    """대본: {"title": 표지 문구, "lines": [읽을 문장들]}."""
    try:
        import memo_ai
        out = memo_ai.generate([{"text": SCRIPT_PROMPT.format(name=item["name"], memo=item.get("memo") or "(없음)")}],
                               temperature=0.8)
        data = json.loads(out[out.find("{"):out.rfind("}") + 1], strict=False)
        lines = [re.sub(r"\s+", " ", str(x)).strip() for x in data.get("lines", []) if str(x).strip()]
        if len(lines) >= 3:
            return {"title": str(data.get("title") or item["short"])[:16], "lines": lines[:7]}
    except Exception as e:
        print(f"  (쇼츠 대본을 제미나이로 못 써서 게시 글로 대신: {e})")
    text = text or {"headline": item["short"][:16], "points": []}
    lines = [text["headline"]] + [p for p in text["points"] if p] + ["구매 링크는 프로필 링크에서 확인하세요"]
    return {"title": text["headline"][:16], "lines": lines}


async def _speak(line, path):
    import edge_tts
    await edge_tts.Communicate(line, VOICE, rate="+8%").save(str(path))


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
            if foot is not None:
                frame = frame.copy()
                frame.paste(foot, (0, H - foot.height), foot)
            proc.stdin.write(frame.tobytes())
    finally:
        proc.stdin.close()
        proc.wait()
    if proc.returncode != 0 or not pathlib.Path(out).exists():
        raise RuntimeError("쇼츠 영상 만들기에 실패했습니다 (ffmpeg 오류).")
    return out


def main():
    """시험용: 상품명 일부를 주면 그 상품으로 쇼츠 하나를 만든다."""
    import main as m
    want = (sys.argv[1] if len(sys.argv) > 1 else "").replace(" ", "")
    items = m.load_products()
    items = sorted(items, key=lambda i: want not in i["name"].replace(" ", ""))  # 고른 상품 먼저, 없으면 아무 상품
    for item in items:
        photos = it.load_photos(item["source"], item["name"])
        photos = it.pick_photos(photos, it.detail_photos(item["name"]), 6)
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
    main()
