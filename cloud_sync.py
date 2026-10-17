# -*- coding: utf-8 -*-
"""서버(GitHub Actions)에서 게시 전후로 구글 시트·드라이브와 주고받는다.

  python cloud_sync.py pull : 비밀값 ENV_FILE(PC .env 통째) → .env, 시트 → products.csv,
                             드라이브 사진 → 사진\\, 저장된 (연장된) 토큰 → .env
  python cloud_sync.py push : .env의 (연장된) 토큰 → 시트 '_설정' 탭
  python cloud_sync.py memo : research.json의 메모 → 시트의 빈 특징메모 칸,
                             아직 메모 없는 상품 → memo_todo.json (Claude가 조사해 채울 목록)
"""
import csv
import json
import os
import pathlib
import sys

from dotenv import dotenv_values, set_key

import gcloud

BASE = pathlib.Path(__file__).resolve().parent
ENV_PATH = BASE / ".env"
PRODUCTS = BASE / "products.csv"
# PC 전용 경로라 서버에서는 쓰지 않는 설정
PC_ONLY = {"PHOTO_DIR", "BGM_DIR", "FONT_PATH", "RESEARCH_FILE", "GOOGLE_SA_FILE"}
TOKEN_KEYS = ["THREADS_ACCESS_TOKEN", "THREADS_USER_ID", "IG_ACCESS_TOKEN", "IG_USER_ID"]

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def write_env():
    """GitHub 비밀값 ENV_FILE(PC의 .env 내용을 통째로 붙여 넣은 것)을 서버의 .env로 쓴다."""
    raw = os.getenv("ENV_FILE", "")
    if not raw.strip():
        return
    keep = [ln for ln in raw.splitlines()
            if ln.split("=", 1)[0].strip() not in PC_ONLY]
    ENV_PATH.write_text("\n".join(keep) + "\n", encoding="utf-8")
    print("✓ 설정(.env)을 준비했습니다.")


def pull():
    write_env()
    rows = gcloud.read_tab()
    if not rows:
        raise SystemExit("구글 시트 '상품' 탭이 비어 있습니다.")
    with open(PRODUCTS, "w", encoding="utf-8-sig", newline="") as f:
        csv.writer(f).writerows(rows)
    print(f"✓ 상품 목록 {len(rows) - 1}줄을 시트에서 받았습니다.")

    # 토큰: 시트에 저장된 (연장된) 값이 우선, 없으면 처음 넣어 둔 비밀값(INIT_...)
    saved = gcloud.read_settings()
    ENV_PATH.touch()
    for key in TOKEN_KEYS:
        val = saved.get(key) or os.getenv("INIT_" + key, "")
        if val:
            set_key(str(ENV_PATH), key, val.strip(), quote_mode="never")

    folder = gcloud.env("GOOGLE_PHOTO_FOLDER_ID")
    if folder:
        import image_tools
        ni = rows[0].index("상품명") if "상품명" in rows[0] else 0
        wanted = {image_tools.folder_name(r[ni]) for r in rows[1:] if len(r) > ni and r[ni].strip()}
        n = gcloud.download_photo_folders(folder, image_tools.photo_root(), wanted)
        print(f"✓ 드라이브에서 사진 폴더 {n}개를 받았습니다.")


def memo():
    rows = gcloud.read_tab()
    if not rows:
        raise SystemExit("구글 시트 '상품' 탭이 비어 있습니다.")
    head = [h.strip() for h in rows[0]]
    if "특징메모" not in head:
        raise SystemExit("시트에 '특징메모' 칸이 없습니다.")
    ni, mi = head.index("상품명"), head.index("특징메모")
    li = head.index("파트너스링크") if "파트너스링크" in head else None
    path = BASE / "research.json"
    cache = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    todo, filled = [], 0
    for n, r in enumerate(rows[1:], start=2):
        cell = lambda i: r[i].strip() if i is not None and len(r) > i else ""
        name = cell(ni)
        if not name or cell(mi):
            continue
        facts = cache.get("".join(name.lower().split()), {}).get("facts", "")
        if facts:
            gcloud.write_cell(n, mi + 1, facts)
            filled += 1
        else:
            todo.append({"row": n, "name": name, "link": cell(li)})
    (BASE / "memo_todo.json").write_text(json.dumps(todo, ensure_ascii=False, indent=2) + "\n",
                                         encoding="utf-8")
    print(f"✓ 특징메모 {filled}개를 시트에 채웠습니다. 아직 메모 없는 상품 {len(todo)}개.")


def push():
    vals = dotenv_values(ENV_PATH) if ENV_PATH.exists() else {}
    keep = {k: vals[k] for k in TOKEN_KEYS if vals.get(k)}
    if keep:
        gcloud.write_settings(keep)
        print("✓ 토큰을 시트 '_설정' 탭에 저장했습니다.")


if __name__ == "__main__":
    {"pull": pull, "push": push, "memo": memo}[sys.argv[1] if len(sys.argv) > 1 else "pull"]()
