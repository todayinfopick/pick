# -*- coding: utf-8 -*-
"""서버(GitHub Actions)에서 게시 전후로 구글 시트·드라이브와 주고받는다.

  python cloud_sync.py pull : 비밀값 ENV_FILE(PC .env 통째) → .env, 시트 → products.csv,
                             드라이브 사진 → 사진\\, 저장된 (연장된) 토큰 → .env
  python cloud_sync.py push : .env의 (연장된) 토큰 → 시트 '_설정' 탭
  python cloud_sync.py due  : 예약 회차가 됐는지 확인 → GitHub 출력 due=1/0, slot=회차
                             (서버는 15분마다 이것만 확인하고, 회차가 됐을 때만 게시)
"""
import csv
import datetime
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
TOKEN_KEYS += [k + "_2" for k in TOKEN_KEYS]  # 두 번째 계정 (accounts.py)

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

    # 프로그램 설정 화면에서 바꾼 값(시트 '_설정' 탭)이 .env보다 우선.
    # 토큰은 시트에 저장된 (연장된) 값, 없으면 처음 넣어 둔 비밀값(INIT_...)
    saved = gcloud.read_settings()
    ENV_PATH.touch()
    for key in TOKEN_KEYS:
        val = saved.get(key) or os.getenv("INIT_" + key, "")
        if val:
            set_key(str(ENV_PATH), key, val.strip(), quote_mode="never")
    n = 0
    for key, val in saved.items():
        if key in TOKEN_KEYS or key in PC_ONLY or not key.replace("_", "").isalnum() or not key.isupper():
            continue
        set_key(str(ENV_PATH), key, " ".join(str(val).split()), quote_mode="never")
        n += 1
    if n:
        print(f"✓ 프로그램에서 바꾼 설정 {n}개를 적용했습니다.")

    folder = gcloud.env("GOOGLE_PHOTO_FOLDER_ID")
    if folder:
        import image_tools
        ni = rows[0].index("상품명") if "상품명" in rows[0] else 0
        wanted = {image_tools.folder_name(r[ni]) for r in rows[1:] if len(r) > ni and r[ni].strip()}
        n = gcloud.download_photo_folders(folder, image_tools.photo_root(), wanted)
        print(f"✓ 드라이브에서 사진 폴더 {n}개를 받았습니다.")


def due_slot(now, times, last):
    """지금(now)까지 지난 가장 최근 예약 회차. 이미 올린 회차(last)면 None.
    times: [(시, 분)]. 오늘 회차가 아직 없으면 어제 마지막 회차. 반환 'YYYY-MM-DD HH:MM'."""
    if not times:
        return None
    today = [now.replace(hour=h, minute=m, second=0, microsecond=0) for h, m in times]
    past = [t for t in today if t <= now]
    if past:
        slot = past[-1]
    else:
        h, m = times[-1]
        slot = (now - datetime.timedelta(days=1)).replace(hour=h, minute=m, second=0, microsecond=0)
    if now - slot > datetime.timedelta(hours=20):
        return None  # 너무 오래된 회차는 건너뜀
    key = slot.strftime("%Y-%m-%d %H:%M")
    return None if last and last >= key else key


def due():
    """상품 글(POST_TIMES)과 일반 글(GENERAL_TIMES) 각각 게시할 회차가 됐는지."""
    import settings
    saved = gcloud.read_settings()
    get = lambda k: (saved.get(k) or os.getenv(k) or settings.BY_KEY[k]["default"]).strip()
    posted = BASE / "posted.json"
    meta = json.loads(posted.read_text(encoding="utf-8")).get("_meta", {}) if posted.exists() else {}
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).replace(tzinfo=None)

    def check(label, on_key, times_key, last_key):
        if get(on_key) == "0":
            print(f"{label}: 꺼져 있음")
            return None
        try:
            times = settings.post_times(get(times_key))
        except ValueError:
            print(f"! {label} 시각을 읽을 수 없어 기본값을 씁니다: {get(times_key)}")
            times = settings.post_times(settings.BY_KEY[times_key]["default"])
        last = meta.get(last_key, "")
        slot = due_slot(now, times, last)
        print(f"{label}: 지금 {now:%m/%d %H:%M}, 마지막 회차 {last or '없음'} → "
              + (f"{slot} 회차 게시" if slot else "게시할 회차 없음"))
        return slot

    slot = check("상품 글", "AUTO_POST", "POST_TIMES", "last_slot")
    gslot = check("일반 글", "GENERAL_ON", "GENERAL_TIMES", "last_general_slot")
    out = os.getenv("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"due={1 if slot else 0}\nslot={slot or ''}\n"
                    f"gdue={1 if gslot else 0}\ngslot={gslot or ''}\n"
                    f"any={1 if slot or gslot else 0}\n")


def push():
    vals = dotenv_values(ENV_PATH) if ENV_PATH.exists() else {}
    keep = {k: vals[k] for k in TOKEN_KEYS if vals.get(k)}
    if keep:
        gcloud.write_settings(keep)
        print("✓ 토큰을 시트 '_설정' 탭에 저장했습니다.")


if __name__ == "__main__":
    {"pull": pull, "push": push, "due": due}[sys.argv[1] if len(sys.argv) > 1 else "pull"]()
