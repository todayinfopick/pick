# -*- coding: utf-8 -*-
"""제휴처 구분: 링크 주소를 보고 어느 제휴 프로그램인지 알아내고, 그에 맞는 대가성 문구를 돌려준다.
설정은 '제휴처.csv'(엑셀로 편집)에 있다. 없으면 기본값으로 만든다."""
import csv
import pathlib
import sys

BASE = pathlib.Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent  # exe면 exe 폴더
CONFIG = BASE / "제휴처.csv"

HEADER = ["제휴처", "제휴링크_주소", "일반주소_경고", "대가성문구", "짧은문구"]
DEFAULTS = [
    ["쿠팡파트너스", "link.coupang.com/ | coupa.ng/", "coupang.com",
     "이 포스팅은 쿠팡 파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다.",
     "쿠팡 파트너스 활동의 일환으로 수수료를 제공받습니다"],
    ["기타", "*", "",
     "이 포스팅은 제휴 마케팅 활동의 일환으로, 구매 시 일정액의 수수료를 제공받습니다.",
     "제휴 마케팅 활동의 일환으로 수수료를 제공받습니다"],
]
IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".mp4", ".mov")

_cache = None


def _split(cell):
    return [p.strip().lower() for p in (cell or "").split("|") if p.strip()]


def load():
    global _cache
    if _cache is not None:
        return _cache
    if not CONFIG.exists():
        with open(CONFIG, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(HEADER)
            w.writerows(DEFAULTS)
    rows = None
    for enc in ("utf-8-sig", "cp949"):
        try:
            with open(CONFIG, encoding=enc, newline="") as f:
                rows = list(csv.DictReader(f))
            break
        except UnicodeDecodeError:
            continue
    rules, fallback = [], None
    for r in rows or []:
        r = {(k or "").strip(): (v or "").strip() for k, v in r.items()}
        if not r.get("제휴처") or not r.get("대가성문구"):
            continue
        rule = {"name": r["제휴처"], "links": _split(r.get("제휴링크_주소")),
                "plain": _split(r.get("일반주소_경고")), "disclosure": r["대가성문구"],
                "short": r.get("짧은문구") or r["대가성문구"]}
        if "*" in rule["links"]:
            fallback = rule
        else:
            rules.append(rule)
    if fallback is None:
        d = DEFAULTS[-1]
        fallback = {"name": d[0], "links": ["*"], "plain": [], "disclosure": d[3], "short": d[4]}
    _cache = (rules, fallback)
    return _cache


def detect(link):
    """링크를 보고 제휴처 정보를 돌려준다.
    결과: name, disclosure, short, ok(게시 가능), plain(제휴 링크가 아닌 일반 쇼핑몰 주소)"""
    rules, fallback = load()
    low = (link or "").strip().lower()
    base = {"ok": False, "plain": False}
    if not low.startswith("http"):
        return {**fallback, **base}
    for rule in rules:
        if any(p in low for p in rule["links"]):
            return {**rule, "ok": True, "plain": False}
    for rule in rules:
        if any(p in low for p in rule["plain"]):
            return {**rule, "ok": False, "plain": True}
    return {**fallback, "ok": True, "plain": False}


def looks_like_link(text):
    """클립보드 글이 제휴 링크처럼 보이는지 (이미지·영상 파일 주소는 제외)."""
    low = (text or "").strip().lower()
    if not low.startswith("http") or " " in low or "\n" in low:
        return False
    path = low.split("?")[0]
    return not path.endswith(IMAGE_EXT)
