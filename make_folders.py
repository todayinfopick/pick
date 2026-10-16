# -*- coding: utf-8 -*-
"""products.csv의 상품마다 '사진\상품명' 폴더를 만들고 탐색기로 연다.
캡처한 상품 사진을 각 폴더에 넣어 두면 자동으로 카드·영상에 쓰인다."""
import os

import image_tools
from main import load_products

root = image_tools.photo_root()
root.mkdir(parents=True, exist_ok=True)
made = 0
for item in load_products():
    folder = root / image_tools.folder_name(item["name"])
    if not folder.exists():
        folder.mkdir()
        made += 1
    n = len(image_tools.images_in(folder))
    print(f"  {'✓' if n else '·'} {folder.name}  (사진 {n}장)")
print(f"\n새로 만든 폴더 {made}개. 각 폴더에 상품 사진을 넣어 주세요 → {root}")
if os.name == "nt":
    os.startfile(root)
