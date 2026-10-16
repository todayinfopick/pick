# -*- coding: utf-8 -*-
"""PC의 products.csv를 구글 시트 '상품' 탭으로 올린다 (처음 한 번, 또는 PC에서 목록을 고친 뒤).

  python sheet_upload.py [시트 주소 또는 ID]
"""
import csv
import os
import pathlib
import re
import sys

from dotenv import load_dotenv, set_key

BASE = pathlib.Path(__file__).resolve().parent
ENV_PATH = BASE / ".env"
PRODUCTS = BASE / "products.csv"

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def main():
    load_dotenv(ENV_PATH)
    if len(sys.argv) > 1:
        m = re.search(r"/d/([\w-]+)", sys.argv[1])
        sid = m.group(1) if m else sys.argv[1].strip()
        ENV_PATH.touch()
        set_key(str(ENV_PATH), "GOOGLE_SHEET_ID", sid, quote_mode="never")
        os.environ["GOOGLE_SHEET_ID"] = sid
    import gcloud
    if not gcloud.enabled():
        raise SystemExit(".env에 GOOGLE_SHEET_ID가 없습니다.")
    with open(PRODUCTS, encoding="utf-8-sig", newline="") as f:
        rows = [r for r in csv.reader(f) if any(c.strip() for c in r)]
    gcloud.write_tab(rows)
    print(f"✓ 상품 {len(rows) - 1}개를 구글 시트 '상품' 탭에 올렸습니다.")


if __name__ == "__main__":
    main()
