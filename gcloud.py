# -*- coding: utf-8 -*-
"""구글 시트(상품 목록)·구글 드라이브(상품 사진) 연결.

.env 설정
  GOOGLE_SA_FILE=google-key.json      : 서비스 계정 키 파일 (PC). 서버에서는 GOOGLE_SA_JSON(내용 자체)을 씀
  GOOGLE_SHEET_ID=...                 : 상품 목록 구글 시트 주소의 /d/ 와 /edit 사이 글자
  GOOGLE_PHOTO_FOLDER_ID=...          : (서버용) 상품별 사진 폴더들이 들어 있는 드라이브 폴더 주소 끝 글자

시트 구성
  '상품' 탭  : 1행 제목(상품명, 파트너스링크, 형식, 미디어, 소재이미지, 게시시간, 특징메모)
  '_설정' 탭 : A열 이름, B열 값 (서버가 연장한 토큰을 여기 저장)
"""
import json
import os
import pathlib
import urllib.parse

BASE = pathlib.Path(__file__).resolve().parent
SCOPES = ["https://www.googleapis.com/auth/spreadsheets",
          "https://www.googleapis.com/auth/drive.readonly"]
PRODUCT_TAB = "상품"
SETTINGS_TAB = "_설정"
SHEETS = "https://sheets.googleapis.com/v4/spreadsheets"
DRIVE = "https://www.googleapis.com/drive/v3/files"
FOLDER_MIME = "application/vnd.google-apps.folder"


def env(key, default=""):
    return (os.getenv(key) or default).strip().strip('"')


def enabled():
    return bool(env("GOOGLE_SHEET_ID"))


_session = None


def session():
    global _session
    if _session is None:
        from google.oauth2 import service_account
        from google.auth.transport.requests import AuthorizedSession
        raw = env("GOOGLE_SA_JSON")
        if raw:
            info = json.loads(raw)
        else:
            path = pathlib.Path(env("GOOGLE_SA_FILE", "google-key.json"))
            if not path.is_absolute():
                path = BASE / path
            if not path.exists():
                raise RuntimeError(f"구글 서비스 계정 키 파일이 없습니다: {path}")
            info = json.loads(path.read_text(encoding="utf-8"))
        creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
        _session = AuthorizedSession(creds)
    return _session


def _check(r, what):
    if r.status_code >= 400:
        raise RuntimeError(f"{what} 실패 ({r.status_code}): {r.text[:300]}")
    return r


def _rng(tab, cells=""):
    name = "'" + tab.replace("'", "''") + "'"
    return urllib.parse.quote(name + ("!" + cells if cells else ""), safe="")


# ---------------------------------------------------------------- 시트
def read_tab(tab=PRODUCT_TAB):
    """탭 전체를 2차원 목록으로. 탭이 없으면 빈 목록."""
    r = session().get(f"{SHEETS}/{env('GOOGLE_SHEET_ID')}/values/{_rng(tab)}",
                      params={"valueRenderOption": "FORMATTED_VALUE"}, timeout=60)
    if r.status_code == 400 and "Unable to parse range" in r.text:
        return []
    _check(r, f"구글 시트 '{tab}' 읽기")
    return r.json().get("values", [])


def ensure_tab(tab):
    sid = env("GOOGLE_SHEET_ID")
    meta = _check(session().get(f"{SHEETS}/{sid}", params={"fields": "sheets.properties.title"},
                                timeout=60), "구글 시트 정보 읽기").json()
    if any(s["properties"]["title"] == tab for s in meta.get("sheets", [])):
        return
    _check(session().post(f"{SHEETS}/{sid}:batchUpdate", timeout=60,
                          json={"requests": [{"addSheet": {"properties": {"title": tab}}}]}),
           f"구글 시트 '{tab}' 탭 만들기")


def write_tab(rows, tab=PRODUCT_TAB):
    """탭 내용을 rows로 통째로 바꾼다 (남는 아래 칸은 지움)."""
    ensure_tab(tab)
    sid = env("GOOGLE_SHEET_ID")
    width = max((len(r) for r in rows), default=1)
    rows = [[str(c) for c in r] + [""] * (width - len(r)) for r in rows]
    _check(session().post(f"{SHEETS}/{sid}/values/{_rng(tab)}:clear", timeout=60),
           f"구글 시트 '{tab}' 지우기")
    if rows:
        _check(session().put(f"{SHEETS}/{sid}/values/{_rng(tab, 'A1')}",
                             params={"valueInputOption": "RAW"}, json={"values": rows}, timeout=60),
               f"구글 시트 '{tab}' 저장")


def write_cell(row, col, value, tab=PRODUCT_TAB):
    """칸 하나만 바꾼다. row·col은 1부터 (1행=제목)."""
    letters = ""
    while col:
        col, rem = divmod(col - 1, 26)
        letters = chr(65 + rem) + letters
    _check(session().put(f"{SHEETS}/{env('GOOGLE_SHEET_ID')}/values/{_rng(tab, f'{letters}{row}')}",
                         params={"valueInputOption": "RAW"}, json={"values": [[value]]}, timeout=60),
           f"구글 시트 '{tab}' {letters}{row} 저장")


def read_settings():
    return {r[0].strip(): (r[1] if len(r) > 1 else "") for r in read_tab(SETTINGS_TAB) if r and r[0].strip()}


def write_settings(values):
    cur = read_settings()
    cur.update(values)
    write_tab([["이름", "값"]] + [[k, v] for k, v in cur.items() if k != "이름"], SETTINGS_TAB)


# ---------------------------------------------------------------- 드라이브
def list_children(folder_id):
    out, token = [], None
    while True:
        params = {"q": f"'{folder_id}' in parents and trashed = false",
                  "fields": "nextPageToken, files(id, name, mimeType, modifiedTime, size)",
                  "pageSize": 1000, "supportsAllDrives": "true", "includeItemsFromAllDrives": "true"}
        if token:
            params["pageToken"] = token
        data = _check(session().get(DRIVE, params=params, timeout=60), "구글 드라이브 목록 읽기").json()
        out += data.get("files", [])
        token = data.get("nextPageToken")
        if not token:
            return out


def download(file_id, dest):
    r = _check(session().get(f"{DRIVE}/{file_id}", params={"alt": "media", "supportsAllDrives": "true"},
                             timeout=120), "구글 드라이브 파일 받기")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(r.content)


def download_photo_folders(folder_id, dest_root, wanted=None):
    """드라이브 사진 폴더 안의 상품별 하위 폴더(사진·영상)를 dest_root/폴더이름/ 으로 받는다.
    wanted가 있으면 그 폴더 이름들만. 받은 폴더 수를 돌려준다."""
    n = 0
    for f in list_children(folder_id):
        if f["mimeType"] != FOLDER_MIME or f["name"].startswith("_"):
            continue
        if wanted is not None and f["name"] not in wanted:
            continue
        for p in list_children(f["id"]):
            if p["mimeType"].startswith(("image/", "video/")):
                download(p["id"], dest_root / f["name"] / p["name"])
        n += 1
    return n
