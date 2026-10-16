# -*- coding: utf-8 -*-
"""쓰레드에 최근 올라간 글 5개와 주소를 보여 준다."""
import sys
import requests

from main import env

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

tok = env("THREADS_ACCESS_TOKEN")
ver = env("THREADS_API_VERSION", "v1.0")
r = requests.get(f"https://graph.threads.net/{ver}/me/threads",
                 params={"fields": "id,permalink,timestamp,media_type,text", "limit": 5,
                         "access_token": tok}, timeout=60)
if not r.ok:
    print("✗ 조회 실패:", r.text[:300])
    sys.exit()
for p in r.json().get("data", []):
    first = (p.get("text") or "").replace("\n", " ")[45:85]
    print(f"- {p.get('timestamp')}  {p.get('media_type')}  {p.get('permalink')}")
    print(f"    {first}")
