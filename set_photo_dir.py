# -*- coding: utf-8 -*-
"""캡처도우미가 사진을 구글 드라이브(데스크톱용) 쿠팡사진 폴더에 저장하도록 .env의 PHOTO_DIR을 바꾼다."""
import pathlib
import sys

from dotenv import set_key

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE = pathlib.Path(__file__).resolve().parent
target = sys.argv[1] if len(sys.argv) > 1 else r"G:\내 드라이브\쿠팡사진"
if not pathlib.Path(target).is_dir():
    raise SystemExit(f"폴더를 찾을 수 없습니다: {target}  (구글 드라이브 프로그램이 켜져 있는지 확인하세요)")
set_key(str(BASE / ".env"), "PHOTO_DIR", target, quote_mode="never")
print(f"✓ 사진 폴더를 {target} 으로 설정했습니다.")
