# -*- coding: utf-8 -*-
"""상품 숏폼 영상(9:16 슬라이드형) 자동 생성.
장면: 후킹 문구 → 포인트 3개 → 구매 안내. 소재 사진이 있으면 사진이 천천히 움직이고(줌·이동),
없으면 색 배경에 자막만 나온다. 장면 사이는 부드럽게 겹쳐 전환된다.
ffmpeg은 imageio-ffmpeg 패키지에 들어 있는 것을 사용한다(따로 설치 필요 없음)."""
import os
import pathlib
import random
import subprocess

from PIL import Image, ImageDraw

import image_tools as it

W, H, FPS = 1080, 1920, 30
FADE = 0.35          # 장면 전환 시간(초)
HOOK_SEC, POINT_SEC, CTA_SEC = 2.8, 2.4, 2.8
AUDIO_EXT = {".mp3", ".m4a", ".wav", ".aac"}


def _ffmpeg():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def _hex(c, a=255):
    c = c.lstrip("#")
    return (int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16), a)


def _gradient(top_alpha, bottom_alpha, y0=0, y1=H):
    """위→아래로 진해지는 검은 그라데이션 (글자 가독성용)."""
    g = Image.new("L", (1, H), 0)
    for y in range(H):
        if y < y0:
            a = top_alpha
        elif y > y1:
            a = bottom_alpha
        else:
            a = int(top_alpha + (bottom_alpha - top_alpha) * (y - y0) / max(1, y1 - y0))
        g.putpixel((0, y), a)
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    layer.putalpha(g.resize((W, H)))
    return layer


class Scene:
    def __init__(self, duration, overlay, photo=None, bg=None, zoom=(1.0, 1.08), pan=(0.5, 0.5, 0.5, 0.5)):
        self.duration = duration
        self.overlay = overlay      # 글자 레이어 (RGBA)
        self.bg = bg
        self.zoom = zoom
        self.pan = pan              # (시작x, 시작y, 끝x, 끝y) 0~1
        self.base = it.cover(photo, W, H) if photo is not None else None

    def render(self, t):
        if self.base is None:
            frame = Image.new("RGB", (W, H), self.bg)
        else:
            p = min(1.0, max(0.0, t / self.duration))
            z = self.zoom[0] + (self.zoom[1] - self.zoom[0]) * p
            cw, ch = int(W / z), int(H / z)
            px = self.pan[0] + (self.pan[2] - self.pan[0]) * p
            py = self.pan[1] + (self.pan[3] - self.pan[1]) * p
            x, y = int((W - cw) * px), int((H - ch) * py)
            frame = self.base.crop((x, y, x + cw, y + ch)).resize((W, H), Image.BILINEAR)
        frame.paste(self.overlay, (0, 0), self.overlay)
        return frame


def _env_int(key, default):
    try:
        return int((os.getenv(key) or "").strip() or default)
    except ValueError:
        return default


def _disclosure(d, fg):
    """오른쪽 위 [광고] 표시. 위치·크기는 .env에서 조정 (영상 크기 1080×1920 기준 픽셀).
    VIDEO_AD_RIGHT: 오른쪽 끝에서 떨어진 거리, VIDEO_AD_TOP: 위쪽 끝에서 떨어진 거리, VIDEO_AD_SIZE: 글자 크기"""
    tag = (os.getenv("VIDEO_AD_TAG") or "").strip() or "[광고]"
    size = _env_int("VIDEO_AD_SIZE", 34)
    margin_r = _env_int("VIDEO_AD_RIGHT", 60)
    margin_t = _env_int("VIDEO_AD_TOP", 60)
    fnt = it.font(size)
    w = d.textlength(tag, font=fnt)
    h, px = int(size * 1.6), int(size * 0.5)
    right, top = W - margin_r, margin_t
    d.rounded_rectangle((right - w - px * 2, top, right, top + h), radius=max(6, size // 3),
                        fill=(0, 0, 0, 140))
    d.text((right - px, top + h // 2), tag, font=fnt, fill="#FFFFFF", anchor="rm")


def _hook_overlay(name, headline, has_photo, bg, accent, fg):
    ov = _gradient(0, 235, 760, 1450) if has_photo else Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    txt = "#FFFFFF" if has_photo else fg
    _disclosure(d, txt)
    pad = 90
    it.pill(d, pad, 1020 if has_photo else 760, it.LABEL, it.font(44), accent, bg, h=80)
    y = 1140 if has_photo else 900
    y = it.text_block(d, pad, y, headline, it.font(104), txt, W - pad * 2, 132, 3)
    it.text_block(d, pad, y + 30, name, it.font(46), txt, W - pad * 2, 62, 2)
    return ov


def _point_overlay(i, text, has_photo, bg, accent, fg):
    ov = _gradient(0, 235, 820, 1500) if has_photo else Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    txt = "#FFFFFF" if has_photo else fg
    _disclosure(d, txt)
    pad = 90
    num_y = 1060 if has_photo else 780
    d.text((pad, num_y), f"{i:02d}", font=it.font(150), fill=accent)
    it.text_block(d, pad, num_y + 200, text, it.font(92), txt, W - pad * 2, 120, 3)
    return ov


def _cta_overlay(name, has_photo, bg, accent, fg):
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 165) if has_photo else (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    txt = "#FFFFFF" if has_photo else fg
    _disclosure(d, txt)
    y = 640 if has_photo else 760
    y = it.text_block(d, 0, y, name, it.font(76), txt, W - 180, 100, 3, center_w=W)
    y += 60
    bw = 820
    d.rounded_rectangle(((W - bw) // 2, y, (W + bw) // 2, y + 130), radius=65, fill=accent)
    d.text((W // 2, y + 65), "구매 링크 확인하기", font=it.font(56), fill=bg, anchor="mm")
    y += 200
    it.text_block(d, 0, y, it.CTA, it.font(46), txt, W - 180, 62, 2, center_w=W)
    # 마지막 장면에는 대가성 문구 전체도 작게 표시
    d.text((W // 2, H - 420), it.DISCLOSURE_SHORT, font=it.font(32), fill=txt, anchor="ma")
    return ov


def _pick_bgm():
    folder = (os.getenv("BGM_DIR") or "").strip()
    if not folder:
        return None
    p = it.resolve_path(folder)
    files = [f for f in p.glob("*") if f.suffix.lower() in AUDIO_EXT] if p.is_dir() else []
    return str(random.choice(files)) if files else None


def make_video(name, headline, points, photos=None, key="video"):
    """숏폼 영상을 만들고 파일 경로를 돌려준다."""
    it.OUT_DIR.mkdir(exist_ok=True)
    photos = photos or []
    bg, accent, fg = it.random_palette()
    has = bool(photos)

    def ph(i):
        return photos[i % len(photos)] if photos else None

    pans = [(0.2, 0.5, 0.8, 0.5), (0.8, 0.3, 0.2, 0.6), (0.5, 0.2, 0.5, 0.8)]
    scenes = [Scene(HOOK_SEC, _hook_overlay(name, headline, has, bg, accent, fg), ph(0), bg, (1.0, 1.1))]
    for i, pt in enumerate([p for p in points if p][:3], start=1):
        scenes.append(Scene(POINT_SEC, _point_overlay(i, pt, has, bg, accent, fg),
                            ph(i), bg, (1.12, 1.04), pans[(i - 1) % 3]))
    scenes.append(Scene(CTA_SEC, _cta_overlay(name, has, bg, accent, fg), ph(len(scenes)), bg, (1.05, 1.12)))
    total = sum(s.duration for s in scenes)

    out = it.OUT_DIR / f"{it.slug(key)}.mp4"
    bgm = _pick_bgm()
    cmd = [_ffmpeg(), "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-"]
    if bgm:
        cmd += ["-stream_loop", "-1", "-i", bgm]
    else:
        cmd += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]
    cmd += ["-map", "0:v", "-map", "1:a", "-t", f"{total:.2f}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k", "-ar", "44100"]
    if bgm:
        cmd += ["-af", f"volume=0.8,afade=t=out:st={max(0, total - 1.2):.2f}:d=1.2"]
    cmd += ["-movflags", "+faststart", str(out)]

    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, creationflags=flags)
    first_frames = {}
    n_frames = int(round(total * FPS))
    start = 0.0
    k = 0
    try:
        for f in range(n_frames):
            t_abs = f / FPS
            while k < len(scenes) - 1 and t_abs >= start + scenes[k].duration:
                start += scenes[k].duration
                k += 1
            sc, t = scenes[k], t_abs - start
            frame = sc.render(t)
            if k < len(scenes) - 1 and t > sc.duration - FADE:
                if k + 1 not in first_frames:
                    first_frames[k + 1] = scenes[k + 1].render(0)
                a = (t - (sc.duration - FADE)) / FADE
                frame = Image.blend(frame, first_frames[k + 1], a)
            proc.stdin.write(frame.tobytes())
    finally:
        proc.stdin.close()
        proc.wait()
    if proc.returncode != 0 or not out.exists():
        raise RuntimeError("영상 만들기에 실패했습니다 (ffmpeg 오류).")
    return out
