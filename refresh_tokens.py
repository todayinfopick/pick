# -*- coding: utf-8 -*-
"""쓰레드·인스타그램 장기 토큰(60일)을 연장한다. 매주 자동 실행되도록 등록됨."""
import requests
from dotenv import set_key

from main import ENV_PATH, env, log


def refresh(name, url, grant, key):
    tok = env(key)
    if not tok:
        return
    r = requests.get(url, params={"grant_type": grant, "access_token": tok}, timeout=60)
    if not r.ok or not r.json().get("access_token"):
        log(f"✗ {name} 토큰 연장 실패: {r.text[:300]}")
        return
    set_key(str(ENV_PATH), key, r.json()["access_token"], quote_mode="never")
    log(f"✓ {name} 토큰 연장 완료")


if __name__ == "__main__":
    refresh("쓰레드", "https://graph.threads.net/refresh_access_token",
            "th_refresh_token", "THREADS_ACCESS_TOKEN")
    refresh("인스타그램", "https://graph.instagram.com/refresh_access_token",
            "ig_refresh_token", "IG_ACCESS_TOKEN")
