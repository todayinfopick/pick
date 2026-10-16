# -*- coding: utf-8 -*-
"""서버(GitHub Actions)에서 게시 전후로 구글 시트·드라이브와 주고받는다.

  python cloud_sync.py pull : 시트 → products.csv, 드라이브 사진 → 사진\\, 저장된 토큰 → .env
  python cloud_sync.py push : .env의 (연장된) 토큰 → 시트 '_설정' 탭
"""
import csv
import os
import pathlib
import sys

from dotenv import dotenv_values, set_key

import gcloud

BASE = pathlib.Path(__file__).resolve().parent
ENV_PATH = BASE / ".env"
PRODUCTS = BASE / "products.csv"
TOKEN_KEYS = ["THREADS_ACCESS_TOKEN", "THREADS_USER_ID", "IG_ACCESS_TOKEN", "IG_USER_ID"]

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def pull():
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


def push():
    vals = dotenv_values(ENV_PATH) if ENV_PATH.exists() else {}
    keep = {k: vals[k] for k in TOKEN_KEYS if vals.get(k)}
    if keep:
        gcloud.write_settings(keep)
        print("✓ 토큰을 시트 '_설정' 탭에 저장했습니다.")


if __name__ == "__main__":
    {"pull": pull, "push": push}[sys.argv[1] if len(sys.argv) > 1 else "pull"]()
