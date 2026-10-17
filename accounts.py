# -*- coding: utf-8 -*-
"""계정 두 쌍(쓰레드+인스타) 나눠 쓰기.

1번 계정: 지금까지 쓰던 설정 이름 그대로 (THREADS_ACCESS_TOKEN, IG_USER_ID, GENERAL_THEME …)
2번 계정: 같은 이름 뒤에 _2 (THREADS_ACCESS_TOKEN_2, IG_USER_ID_2, GENERAL_THEME_2 …)

상품은 시트 '분류' 칸을 보고 계정을 정한다. ACCOUNT_CATEGORY_2(예: 생활)에 적힌 말이 들어 있으면 2번,
그 밖(비었거나 뷰티 등)은 1번. 2번 계정이 연결되지 않았으면 전부 1번.
"""
import os

# 계정마다 따로 쓰는 설정
KEYS = ["THREADS_ACCESS_TOKEN", "THREADS_USER_ID", "IG_ACCESS_TOKEN", "IG_USER_ID",
        "THREADS_ON", "IG_ON", "GENERAL_ON", "GENERAL_THEME", "ACCOUNT_CATEGORY", "ACCOUNT_NAME",
        "PAGE_TITLE", "PAGE_HANDLE"]
TOKEN_KEYS = ["THREADS_ACCESS_TOKEN", "THREADS_USER_ID", "IG_ACCESS_TOKEN", "IG_USER_ID"]
SHARED_SWITCHES = {"THREADS_ON", "IG_ON", "GENERAL_ON"}
_base = {}


def _get(key):
    return (os.getenv(key) or "").strip()


def suffix(n):
    return "" if n == 1 else f"_{n}"


def connected2():
    return bool(_get("THREADS_ACCESS_TOKEN_2") or _get("IG_ACCESS_TOKEN_2"))


def _fill_ids(sfx):
    """토큰만 넣고 사용자 ID를 비워 둔 경우 토큰으로 ID를 알아낸다."""
    import requests
    for idk, tk, url, fields in (("THREADS_USER_ID", "THREADS_ACCESS_TOKEN", "https://graph.threads.net/v1.0/me", "id"),
                                 ("IG_USER_ID", "IG_ACCESS_TOKEN", "https://graph.instagram.com/me", "user_id,id")):
        if _get(idk + sfx) or not _get(tk + sfx):
            continue
        try:
            r = requests.get(url, params={"fields": fields, "access_token": _get(tk + sfx)}, timeout=30)
            j = r.json() if r.ok else {}
            uid = str(j.get("user_id") or j.get("id") or "")
            if uid:
                os.environ[idk + sfx] = uid
        except Exception:
            pass


def whoami():
    """지금 계정(use 뒤)의 토큰이 맞는지: '쓰레드 @아이디 · 인스타 @아이디' (실패는 ✗ 이유)."""
    import requests
    out = []
    for label_, tk, url in (("쓰레드", "THREADS_ACCESS_TOKEN", "https://graph.threads.net/v1.0/me"),
                            ("인스타", "IG_ACCESS_TOKEN", "https://graph.instagram.com/me")):
        if not _get(tk):
            out.append(f"{label_} 없음")
            continue
        try:
            r = requests.get(url, params={"fields": "username", "access_token": _get(tk)}, timeout=30)
            out.append(f"{label_} @{r.json()['username']}" if r.ok else f"{label_} ✗ {r.text[:120]}")
        except Exception as e:
            out.append(f"{label_} ✗ {e}")
    return " · ".join(out)


def listing():
    """연결된 계정 번호 목록. 1번은 늘 포함."""
    return [1, 2] if connected2() else [1]


def use(n):
    """n번 계정 설정을 기본 이름(THREADS_ACCESS_TOKEN 등)에 덮어 쓴다. use(1)이면 원래대로."""
    if not _base:
        _base.update({k: os.environ.get(k) for k in KEYS})
    if n != 1:
        _fill_ids(suffix(n))
    for k in KEYS:
        v = _base[k] if n == 1 else os.environ.get(k + suffix(n))
        if n != 1 and not (v or "").strip() and k in SHARED_SWITCHES:
            v = _base[k]  # 켜기·끄기는 2번에 따로 없으면 1번 값을 따름
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def label(n):
    name = _get("ACCOUNT_NAME_2") if n == 2 else (_base.get("ACCOUNT_NAME") if _base else _get("ACCOUNT_NAME"))
    return (name or "").strip() or f"{n}번 계정"


def route(category):
    """상품 '분류' 칸 값 → 올릴 계정 번호."""
    c = "".join((category or "").split())
    if c and connected2():
        for word in _get("ACCOUNT_CATEGORY_2").replace(",", " ").split():
            if word and word in c:
                return 2
    return 1
