"""블로그 작업이 도는 동안 스튜디오·프로그램이 index.json에서 바꾼 것(검수완료 표시 등)을 지금 목록에 합친다.

2026-11-27 사용자: 서버 작업 중에 '검수 저장'을 하면 글은 남는데 목록의 검수완료 표시가 사라짐.
예전엔 결과 저장 때 index.json을 통째로 이 작업 것으로 덮어써서 그 사이 바뀐 목록 정보가 빠졌음.
쓰는 법: python merge_index.py base.json theirs.json index.json
  base   = 이 작업이 시작할 때의 index.json
  theirs = 지금 서버(blog-packages)의 index.json
  index  = 이 작업이 만든 index.json (여기에 합쳐 저장)
글마다, 작업 시작 뒤 서버에서 바뀐 칸만 옮긴다. 이 작업도 같은 칸을 바꿨으면 이 작업 것을 둔다.
서버에만 새로 생긴 글은 글 폴더가 있으면 목록에 넣는다.
"""
import json
import os
import sys


def load(p):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return {"packages": []}


base, theirs, mine = (load(p) for p in sys.argv[1:4])
b = {x.get("id"): x for x in base.get("packages", [])}
t = {x.get("id"): x for x in theirs.get("packages", [])}
moved = 0
mine_ids = {x.get("id") for x in mine.get("packages", [])}
for x in mine.get("packages", []):
    pid = x.get("id")
    if pid not in t:
        continue
    old, new = b.get(pid, {}), t[pid]
    for k in set(old) | set(new):
        if old.get(k) == new.get(k):
            continue  # 서버에서 안 바뀐 칸
        if k in old and x.get(k) != old.get(k):
            continue  # 이 작업도 바꾼 칸 → 이 작업 것
        if k in new:
            x[k] = new[k]
        else:
            x.pop(k, None)
        moved += 1
for pid, p in t.items():  # 작업 중에 서버에만 생긴 글
    if pid not in b and pid not in mine_ids and os.path.isfile(f"{pid}/content.json"):
        mine.setdefault("packages", []).append(p)
        moved += 1
json.dump(mine, open(sys.argv[3], "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"목록 정보 {moved}칸 합침")
