# -*- coding: utf-8 -*-
"""토큰으로 계정 ID를 확인해 .env에 채워 넣고, 연결이 되는지 점검한다.
THREADS_APP_SECRET이 있으면 쓰레드 단기 토큰을 장기 토큰(60일)으로 바꿔 준다."""
import requests
from dotenv import set_key

from main import ENV_PATH, env, log


def save(key, value):
    set_key(str(ENV_PATH), key, value, quote_mode="never")


def threads():
    tok = env("THREADS_ACCESS_TOKEN")
    if not tok:
        print("· 쓰레드: 토큰이 비어 있어 건너뜀")
        return
    secret = env("THREADS_APP_SECRET")
    if secret:
        r = requests.get("https://graph.threads.net/access_token",
                         params={"grant_type": "th_exchange_token",
                                 "client_secret": secret, "access_token": tok}, timeout=60)
        if r.ok and r.json().get("access_token"):
            tok = r.json()["access_token"]
            save("THREADS_ACCESS_TOKEN", tok)
            print("· 쓰레드: 장기 토큰으로 교환 완료")
    ver = env("THREADS_API_VERSION", "v1.0")
    r = requests.get(f"https://graph.threads.net/{ver}/me",
                     params={"fields": "id,username", "access_token": tok}, timeout=60)
    if not r.ok:
        print(f"✗ 쓰레드 연결 실패: {r.text[:300]}")
        return
    d = r.json()
    save("THREADS_USER_ID", d["id"])
    print(f"✓ 쓰레드 연결됨: @{d.get('username')} (ID {d['id']})")


def instagram():
    tok = env("IG_ACCESS_TOKEN")
    if not tok:
        print("· 인스타그램: 토큰이 비어 있어 건너뜀")
        return
    ver = env("IG_API_VERSION", "v23.0")
    r = requests.get(f"https://graph.instagram.com/{ver}/me",
                     params={"fields": "user_id,username", "access_token": tok}, timeout=60)
    if not r.ok:
        print(f"✗ 인스타그램 연결 실패: {r.text[:300]}")
        return
    d = r.json()
    uid = d.get("user_id") or d.get("id")
    save("IG_USER_ID", uid)
    print(f"✓ 인스타그램 연결됨: @{d.get('username')} (ID {uid})")


if __name__ == "__main__":
    threads()
    instagram()
    log("연결 점검 실행")
