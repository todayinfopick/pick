# -*- coding: utf-8 -*-
"""캡처 도우미: 쿠팡 페이지 위에 떠 있는 작은 창.
- 파트너스 링크를 복사하면 링크 칸에, 상품명을 복사하면 상품명 칸에 자동 입력
- 📷 캡처(또는 Win+Shift+S)로 잘라낸 사진은 자동으로 사진 목록에 추가
- [저장 → 다음 상품]: products.csv에 한 줄 추가 + 사진\\상품명 폴더에 사진 저장
"""
import csv
import hashlib
import io
import json
import os
import queue
import subprocess
import threading
import time
import tkinter as tk
import webbrowser
from tkinter import messagebox

from PIL import Image, ImageGrab, ImageTk

import affiliates
import gcloud
import image_tools
from main import PRODUCTS, log, product_key

COLUMNS = ["상품명", "파트너스링크", "형식", "미디어", "소재이미지", "게시시간", "특징메모", "분류"]
POLL_MS = 500
BRIDGE_PORT = 27183  # 크롬 확장프로그램이 상품 페이지 내용을 보내는 PC 안 주소 (127.0.0.1만)
PAGE_TEXT_FILE = "페이지글.txt"  # 확장프로그램이 가져온 상세페이지 글 전체 (게시엔 안 씀, 메모용)
MAX_PHOTOS = image_tools.MAX_PHOTOS  # 한 줄 5장 × 2줄 (인스타 캐러셀 최대 장수와 같음)


# ---------------------------------------------------------------- products.csv
def read_rows():
    if gcloud.enabled():  # 구글 시트를 쓰는 경우 (폰·서버와 같은 목록)
        rows = gcloud.read_tab()
        if not rows:
            return COLUMNS[:], []
        header = [h.strip() for h in rows[0]]
        for col in COLUMNS:
            if col not in header:
                header.append(col)
        return header, rows[1:]
    if not PRODUCTS.exists():
        return COLUMNS[:], []
    for enc in ("utf-8-sig", "cp949"):
        try:
            with open(PRODUCTS, encoding=enc, newline="") as f:
                rows = list(csv.reader(f))
            break
        except UnicodeDecodeError:
            continue
    else:
        raise RuntimeError("products.csv를 읽을 수 없습니다. 엑셀에서 'CSV UTF-8'로 저장해 주세요.")
    if not rows:
        return COLUMNS[:], []
    header = [h.strip() for h in rows[0]]
    for col in COLUMNS:  # 예전 양식이면 빠진 칸을 뒤에 추가
        if col not in header:
            header.append(col)
    return header, rows[1:]


def write_rows(header, rows):
    rows = [r + [""] * (len(header) - len(r)) for r in rows]
    if gcloud.enabled():
        gcloud.write_tab([header] + rows)
        return
    with open(PRODUCTS, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def name_key(name):
    return product_key(name)  # 같은 상품 판단 기준은 게시 프로그램과 동일 (.env SAME_PRODUCT)


def find_product(link=None, name=None):
    """등록된 상품 찾기: 링크가 같거나, 상품명이 같으면(쿠팡 링크는 만들 때마다 바뀜) 그 상품.
    찾으면 {'name', 'memo', 'link', 'category'}, 없으면 None."""
    header, rows = read_rows()
    li, ni, mi = header.index("파트너스링크"), header.index("상품명"), header.index("특징메모")
    ci = header.index("분류")
    nk = name_key(name) if name else None
    for r in rows:
        cell = lambda i: r[i].strip() if len(r) > i else ""
        if (link and cell(li) == link.strip()) or (nk and name_key(cell(ni)) == nk):
            return {"name": cell(ni), "memo": cell(mi), "link": cell(li), "category": cell(ci)}
    return None


def find_by_link(link):
    return find_product(link=link)


def update_product(old_link, name, memo, new_link=None, category=None):
    """등록된 상품(old_link로 찾음)의 상품명·특징메모·링크·분류를 고친다. 바뀌기 전 상품명을 돌려준다."""
    header, rows = read_rows()
    li, ni, mi = header.index("파트너스링크"), header.index("상품명"), header.index("특징메모")
    old = None
    for r in rows:
        if len(r) > li and r[li].strip() == old_link:
            r.extend([""] * (len(header) - len(r)))
            old = r[ni].strip()
            r[ni] = name
            r[mi] = memo
            if new_link:
                r[li] = new_link
            if category is not None:
                r[header.index("분류")] = category
            break
    write_rows(header, rows)
    return old


def merge_duplicates():
    """같은 상품(상품명 기준)이 여러 줄이면 첫 줄 하나로 합친다.
    링크는 가장 나중 줄의 것으로, 빈 칸은 다른 줄의 내용으로 채운다. 합친 줄 수를 돌려준다."""
    header, rows = read_rows()
    ni, li = header.index("상품명"), header.index("파트너스링크")
    keep, first = [], {}
    merged = 0
    for r in rows:
        r = r + [""] * (len(header) - len(r))
        name = r[ni].strip()
        if not name:
            if any(c.strip() for c in r):
                keep.append(r)
            continue  # 완전히 빈 줄은 정리
        k = product_key(name)
        if k not in first:
            first[k] = r
            keep.append(r)
            continue
        base = first[k]
        if r[li].strip():
            base[li] = r[li].strip()  # 최신 링크
        for i, v in enumerate(r):
            if i not in (ni, li) and v.strip() and not base[i].strip():
                base[i] = v
        merged += 1
    if merged or len(keep) != len(rows):
        write_rows(header, keep)
    return merged


def move_photos(old_name, new_name):
    """상품명이 바뀌면 사진 폴더도 새 이름으로 옮긴다."""
    root = image_tools.photo_root()
    src = root / image_tools.folder_name(old_name)
    dst = root / image_tools.folder_name(new_name)
    if src == dst or not src.is_dir():
        return
    dst.mkdir(parents=True, exist_ok=True)
    start = len(image_tools.images_in(dst))
    for n, f in enumerate(image_tools.images_in(src), start=start + 1):
        f.rename(dst / f"{n:02d}{f.suffix.lower()}")
    try:
        src.rmdir()
    except OSError:
        pass


def append_product(name, link, memo, category=""):
    header, rows = read_rows()
    li = header.index("파트너스링크")
    if any(len(r) > li and r[li].strip() == link for r in rows):
        raise ValueError("이미 등록된 링크입니다.")
    row = [""] * len(header)
    row[header.index("상품명")] = name
    row[li] = link
    row[header.index("특징메모")] = memo
    row[header.index("분류")] = category
    rows.append(row)
    write_rows(header, rows)


def category_choices():
    """분류 선택지: 1번 계정 분류(ACCOUNT_CATEGORY, 기본 '뷰티 건강') + 2번 계정 분류(ACCOUNT_CATEGORY_2, 기본 '생활 식품')."""
    import os
    out = []
    for key, dflt in (("ACCOUNT_CATEGORY", "뷰티 건강"), ("ACCOUNT_CATEGORY_2", "생활 식품")):
        for w in (os.getenv(key) or dflt).replace(",", " ").split():
            if w not in out:
                out.append(w)
    return out


def photo_folder(name):
    return image_tools.photo_root() / image_tools.folder_name(name)


def load_saved_photos(name):
    """이미 저장된 상품 사진을 불러온다 (수정 모드에서 화면에 보여주기 위해)."""
    folder = photo_folder(name)
    if not folder.is_dir():
        return []
    out = []
    for f in image_tools.images_in(folder):
        try:
            with Image.open(f) as im:
                out.append(im.copy())
        except Exception:
            continue
    return out


def save_photos(name, images, replace=False):
    """사진 저장.
    replace=True: 폴더를 지금 화면의 사진들로 통째로 바꾼다 (수정 모드, 기존 사진을 불러와 보여준 경우).
    replace=False: 폴더에 없는 사진만 뒤에 추가한다 (같은 사진은 건너뜀)."""
    folder = photo_folder(name)
    folder.mkdir(parents=True, exist_ok=True)
    old = image_tools.images_in(folder)
    if replace:
        tmp = []
        for i, im in enumerate(images, start=1):
            t = folder / f"__new{i:03d}.jpg"
            im.convert("RGB").save(t, quality=92)
            tmp.append(t)
        for f in old:
            f.unlink()
        for i, t in enumerate(tmp, start=1):
            t.rename(folder / f"{i:02d}.jpg")
        return folder
    existing = []
    for f in old:
        try:
            with Image.open(f) as im:
                existing.append(im.copy())
        except Exception:
            continue
    n = len(old)
    for im in image_tools.unique_photos(images):
        if image_tools.is_duplicate(im, existing):
            continue
        n += 1
        im.convert("RGB").save(folder / f"{n:02d}.jpg", quality=92)
        existing.append(im)
    return folder


def is_link(text):
    """게시에 쓸 수 있는 제휴 링크인지 (제휴처.csv 기준, 목록에 없는 링크는 '기타'로 허용)."""
    return affiliates.looks_like_link(text) and affiliates.detect(text)["ok"]


def is_plain_store(text):
    """제휴 링크가 아닌 일반 쇼핑몰 주소인지 (수익이 안 잡힘)."""
    return affiliates.looks_like_link(text) and affiliates.detect(text)["plain"]


def save_page_text(name, text):
    if not text:
        return
    folder = photo_folder(name)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / PAGE_TEXT_FILE).write_text(text, encoding="utf-8")


def load_page_text(name):
    f = photo_folder(name) / PAGE_TEXT_FILE
    try:
        return f.read_text(encoding="utf-8")
    except OSError:
        return ""


# ---------------------------------------------------------------- 크롬 확장프로그램 연결
def is_product_photo(im):
    """띠 모양 배너·작은 아이콘 같은 건 빼고 상품 사진만."""
    if im is None:
        return False
    w, h = im.size
    return min(w, h) >= 200 and max(w, h) <= 3 * min(w, h)


# 제휴 링크를 복사하면 그 페이지를 크롬에서 열고, 확장프로그램이 스스로 끝까지 내려 수집한 뒤 창을 닫는다.
# 확장프로그램은 상품 페이지가 열릴 때 /auto 로 '이번 페이지는 자동 수집인가'를 물어본다 (한 번 답하면 끝).
AUTO_WAIT = 90  # 링크를 연 뒤 이 시간(초) 안에 열린 쿠팡 상품 페이지만 자동 수집
_auto = {"until": 0.0}


def open_for_collect(link):
    _auto["until"] = time.time() + AUTO_WAIT
    webbrowser.open(link)


def start_bridge(inbox):
    """127.0.0.1:BRIDGE_PORT에서 확장프로그램이 보낸 상품 페이지 내용을 받아 inbox에 넣는다.
    사진은 여기(뒤쪽)에서 미리 받아 둔다. 이미 다른 창이 쓰고 있으면 False."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            # 확장프로그램만 받는다: 일반 웹페이지는 이 머리글을 붙이면 브라우저가 막는다(CORS 사전 확인)
            if self.path != "/page" or self.headers.get("X-Pick") != "1":
                self.send_error(403)
                return
            try:
                size = int(self.headers.get("Content-Length") or 0)
                data = json.loads(self.rfile.read(min(size, 5_000_000)).decode("utf-8"))
                urls = [u for u in data.get("images") or [] if isinstance(u, str) and u.startswith("http")]
                photos = [im for im in (image_tools.load_photo(u) for u in urls[:MAX_PHOTOS]) if is_product_photo(im)]
                inbox.put({"name": " ".join(str(data.get("name") or "").split())[:200],
                           "text": str(data.get("text") or "").strip(),
                           "url": str(data.get("url") or ""), "images": photos})
                body, code = {"ok": True, "photos": len(photos)}, 200
            except Exception as e:
                body, code = {"ok": False, "error": str(e)}, 400
            out = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        def do_GET(self):  # 확장프로그램이 '프로그램 켜져 있나' 확인용, /auto: 자동 수집할 페이지인지
            out = b'{"ok": true}'
            if self.path == "/auto":
                if self.headers.get("X-Pick") != "1":
                    self.send_error(403)
                    return
                auto = time.time() < _auto["until"]
                _auto["until"] = 0.0
                out = json.dumps({"ok": True, "auto": auto}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        def log_message(self, *a):
            pass

    try:
        server = ThreadingHTTPServer(("127.0.0.1", BRIDGE_PORT), Handler)
    except OSError:
        return False
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return True


# ---------------------------------------------------------------- 화면
class Helper:
    def __init__(self, root, parent=None):
        """parent를 주면 그 안에 그린다(통합 프로그램의 '상품 등록' 탭). 없으면 작은 창 하나."""
        self.root = root
        self.standalone = parent is None
        box = root if parent is None else parent
        self.ai_done = False  # 이번 저장에서 제미나이 메모 작성을 이미 했는지
        self.info_idx = []  # 제미나이가 '설명 캡처'라고 본 사진 번호 (게시에 안 씀)
        self.images = []
        self.last_text = None
        self.last_img_hash = None
        self.watch = tk.BooleanVar(value=True)
        self.auto_collect = tk.BooleanVar(value=True)  # 쿠팡 링크 복사 → 페이지 열어 자동 수집
        self.target = tk.StringVar(value="auto")
        self.name_replace_next = False
        self.editing = None  # 수정 중인 등록 상품 {'name','memo','link'}
        self.photos_loaded = False  # 수정 모드에서 저장된 사진을 불러왔는지 (저장 시 폴더를 통째로 교체)
        self.photos_dirty = False  # 저장하지 않은 사진 변경이 있는지
        self.page_text = ""  # 확장프로그램이 보낸 상세페이지 글
        self.inbox = queue.Queue()
        start_bridge(self.inbox)

        if self.standalone:
            root.title("쿠팡 캡처 도우미 — 새 상품 등록")
            root.attributes("-topmost", True)
            root.resizable(False, False)
            sw = root.winfo_screenwidth()
            root.geometry(f"+{sw - 420}+40")  # 높이는 사진 수에 맞춰 자동
            root.minsize(400, 0)

        pad = {"padx": 10, "pady": 3}
        pick = tk.Frame(box, bg="#EEF2FF")
        pick.pack(fill="x", padx=10, pady=(8, 2))
        tk.Label(pick, text="복사→", bg="#EEF2FF").pack(side="left", padx=4)
        for val, txt in (("auto", "자동"), ("name", "상품명"), ("memo", "메모")):
            tk.Radiobutton(pick, text=txt, value=val, variable=self.target, bg="#EEF2FF",
                           command=self.on_target).pack(side="left")
        tk.Label(box, text="① 제휴 링크 (복사하면 자동)", anchor="w").pack(fill="x", **pad)
        self.link = tk.Entry(box)
        self.link.pack(fill="x", padx=10)

        tk.Label(box, text="② 상품명 (복사하면 자동)", anchor="w").pack(fill="x", **pad)
        self.name = tk.Entry(box)
        self.name.pack(fill="x", padx=10)

        tk.Label(box, text="③ 특징메모 (비우면 AI가 작성)", anchor="w").pack(fill="x", **pad)
        self.memo = tk.Text(box, height=2, wrap="word")
        self.memo.pack(fill="x", padx=10)

        cat = tk.Frame(box)
        cat.pack(fill="x", padx=10, pady=(4, 0))
        tk.Label(cat, text="분류:").grid(row=0, column=0, sticky="w")
        self.category = tk.StringVar(value="")
        for i, (val, txt) in enumerate([("", "AI")] + [(c, c) for c in category_choices()]):
            tk.Radiobutton(cat, text=txt, value=val, variable=self.category) \
                .grid(row=i // 3, column=1 + i % 3, sticky="w")  # 좁은 창이라 3개씩 줄바꿈

        bar = tk.Frame(box)
        bar.pack(fill="x", padx=10, pady=8)
        tk.Button(bar, text="📷 캡처", command=self.capture).pack(side="left")
        tk.Button(bar, text="↩ 취소", command=self.undo_image).pack(side="left", padx=3)
        tk.Button(bar, text="✨ 메모", command=lambda: self.run_ai(None)).pack(side="left")

        # 캡처한 사진 미리보기 (클릭하면 삭제)
        self.thumbs = tk.Frame(box, bg="#F1F5F9")
        self.thumbs.pack(fill="x", padx=10)
        self.thumb_refs = []
        self.empty_thumb = tk.Label(self.thumbs, text="(캡처한 사진이 여기에 표시됩니다)", bg="#F1F5F9",
                                    fg="#999", height=3)
        self.empty_thumb.grid(row=0, column=0, columnspan=5, sticky="we")
        hint = tk.Frame(box)
        hint.pack(fill="x", padx=10)
        tk.Label(hint, text="사진을 누르면 지워져요", fg="#888").pack(side="left")
        self.count = tk.Label(hint, text=f"0/{MAX_PHOTOS}장")
        self.count.pack(side="right")

        self.save_btn = tk.Button(box, text="저장 → 다음 상품", command=self.save, height=2,
                                  bg="#2563EB", fg="white", activebackground="#1D4ED8")
        self.save_btn.pack(fill="x", padx=10, pady=4)

        bottom = tk.Frame(box)
        bottom.pack(fill="x", padx=10)
        tk.Checkbutton(bottom, text="복사 감지", variable=self.watch).pack(side="left")
        tk.Checkbutton(bottom, text="자동 수집", variable=self.auto_collect).pack(side="left")
        tk.Button(bottom, text="새 상품", command=self.new_product).pack(side="left", padx=4)
        tk.Button(bottom, text="📁 폴더", command=self.open_folder).pack(side="right")

        self.status = tk.Label(box, text="제휴 링크(쿠팡 파트너스 등)를 복사해 보세요.\n"
                                         "상세 설명 부분도 캡처해 두면 AI가 읽고 메모를 씁니다(게시엔 안 씀).", fg="#555",
                               anchor="w", justify="left", wraplength=250)
        self.status.pack(fill="x", padx=10, pady=6)

        self.prime_clipboard()
        self.tidy_photos()
        self.tidy_sheet()
        root.after(POLL_MS, self.poll)

    # 시작 시 이미 클립보드에 있던 내용은 무시
    def prime_clipboard(self):
        try:
            self.last_text = self.root.clipboard_get()
        except tk.TclError:
            self.last_text = ""
        img = self.grab_image()
        self.last_img_hash = self.hash_image(img) if img is not None else None

    @staticmethod
    def grab_image():
        try:
            data = ImageGrab.grabclipboard()
        except Exception:
            return None
        return data if hasattr(data, "size") else None

    @staticmethod
    def hash_image(img):
        buf = io.BytesIO()
        img.convert("RGB").resize((64, 64)).save(buf, "PNG")
        return hashlib.md5(buf.getvalue()).hexdigest()

    def say(self, msg):
        self.status.config(text=msg)

    # ------------------------------------------------ 클립보드 감지
    def poll(self):
        try:
            self._poll_once()
        except Exception as e:  # 한 번 실패해도 복사 감지는 계속 (멈추면 링크가 안 들어감)
            log(f"캡처 도우미: 복사 감지 오류 {e}")
        self.root.after(POLL_MS, self.poll)

    def _poll_once(self):
        while not self.inbox.empty():
            self.take_page(self.inbox.get())
        if self.watch.get():
            img = self.grab_image()
            if img is not None:
                h = self.hash_image(img)
                if h != self.last_img_hash:
                    self.last_img_hash = h
                    self.add_image(img)
            else:
                try:
                    text = self.root.clipboard_get()
                except tk.TclError:
                    text = None
                if text is not None and text != self.last_text:
                    self.last_text = text
                    self.take_text(text.strip())

    def take_text(self, text):
        if not text:
            return
        if not affiliates.looks_like_link(text):
            # 제휴 링크 복사 기능이 '상품명 + 링크'처럼 여러 줄로 복사하는 경우: 링크만 꺼내 쓴다
            found = [w for w in text.split() if w.startswith("http") and is_link(w)]
            if found:
                text = found[0]
        if is_plain_store(text):
            name = affiliates.detect(text)["name"]
            self.say(f"⚠ {name} 제휴 링크가 아닌 일반 주소라 넣지 않았습니다. 수익이 잡히지 않아요!\n"
                     "제휴 프로그램에서 만든 링크를 복사하세요.")
            self.root.bell()
            return
        if is_link(text):
            if self.link.get().strip() and text.strip() != self.link.get().strip():
                # 다른 링크 = 새 상품: 이전 내용을 비운다 (저장 안 한 사진이 있으면 확인)
                if self.photos_dirty and self.images and not messagebox.askyesno(
                        "새 상품", f"저장하지 않은 사진 {len(self.images)}장이 있습니다.\n"
                                 "버리고 새 상품을 시작할까요?\n\n(아니오: 지금 상품을 계속 편집)"):
                    self.say("새 링크를 무시했습니다. 지금 상품을 저장한 뒤 다시 링크를 복사하세요.")
                    return
                self.reset_fields()
            self.link.delete(0, "end")
            self.link.insert(0, text)
            try:
                found = find_by_link(text)
            except Exception:
                found = None
            aff = affiliates.detect(text)["name"]
            if found is not None:
                self.editing = found
                self.name.delete(0, "end")
                self.name.insert(0, found["name"])
                self.memo.delete("1.0", "end")
                self.memo.insert("1.0", found["memo"])
                self.category.set(found.get("category", ""))
                self.name_replace_next = True  # 다음에 복사한 글은 상품명을 바꿈
                self.set_mode(edit_name=found["name"])
                self.load_existing_photos(found["name"])
                bad = (found["name"] and found["name"] == found["memo"]) or len(found["name"]) > 80
                if bad:
                    self.say("⚠ 이미 등록된 상품인데 상품명이 잘못 저장된 것 같습니다.\n"
                             "쿠팡 상품명을 복사하면 상품명이 바뀝니다. 고친 뒤 저장하세요.")
                else:
                    self.say("✎ 이미 등록된 상품을 불러왔습니다.\n"
                             "상품명을 복사하면 바뀌고, 그다음 복사한 글은 특징메모에 붙습니다.")
            else:
                self.name_replace_next = False
                if aff == "쿠팡파트너스" and self.auto_collect.get():
                    open_for_collect(text)
                    self.say("✓ 링크 입력됨. 쿠팡 페이지를 열어 상품명·사진·상세 글을 자동으로 가져옵니다…\n"
                             "(확장프로그램이 끝까지 내려 수집한 뒤 창을 닫아요)")
                else:
                    self.say(f"✓ 링크 입력됨 ({aff}). 이제 상품명을 드래그해서 복사하세요.")
            return
        if text.startswith("http"):
            return
        one_line = " ".join(text.split())
        # 창 안에서 칸 내용을 복사한 경우(이미 들어 있는 글)는 무시
        if one_line == self.name.get().strip() or one_line in " ".join(self.memo.get("1.0", "end").split()):
            return
        mode = self.target.get()
        to_name = (mode == "name" or
                   (mode == "auto" and (not self.name.get().strip() or self.name_replace_next)))
        if to_name:
            self.name.delete(0, "end")
            self.name.insert(0, one_line[:200])
            self.name_replace_next = False
            if self.editing is None:
                try:
                    same = find_product(name=one_line)
                except Exception:
                    same = None
                if same is not None:
                    self.editing = same
                    if not self.memo.get("1.0", "end").strip():
                        self.memo.insert("1.0", same["memo"])
                    self.set_mode(edit_name=same["name"])
                    self.load_existing_photos(same["name"])
                    self.say("✎ 이미 등록된 상품입니다(링크만 새로 만든 경우).\n"
                             "수정 모드로 바꿨습니다. 저장하면 링크도 새 링크로 바뀝니다.")
                    return
            self.say("✓ 상품명 입력됨. 이제 복사하는 글은 특징메모에 붙습니다. 📷 사진도 캡처하세요.")
            return
        cur = self.memo.get("1.0", "end").strip()
        self.memo.delete("1.0", "end")
        self.memo.insert("1.0", f"{cur}, {one_line}" if cur else one_line)
        self.say("✓ 특징메모에 추가됨. (상품명을 바꾸려면 위 '상품명'을 고르고 복사하세요)")

    def take_page(self, data):
        """확장프로그램에서 받은 상품 페이지 내용: 상품명·사진·상세페이지 글."""
        name, cur = data["name"], self.name.get().strip()
        if cur and name and name_key(cur) != name_key(name) and not self.editing:
            if not messagebox.askyesno("새 상품", f"지금 입력 중인 상품과 다른 상품입니다.\n\n"
                                                f"지금: {cur[:40]}\n받은 것: {name[:40]}\n\n지우고 새로 시작할까요?"):
                self.say("확장프로그램에서 받은 내용을 무시했습니다.")
                return
            self.reset_fields()
        if name and (not self.name.get().strip() or self.name_replace_next):
            self.name.delete(0, "end")
            self.name.insert(0, name)
            self.name_replace_next = False
        if data["text"]:
            self.page_text = data["text"]
            self.ai_done = False
        added = 0
        for im in data["images"]:
            if len(self.images) >= MAX_PHOTOS:
                break
            if not image_tools.is_duplicate(im, self.images):
                self.images.append(im)
                added += 1
        if added:
            self.photos_dirty = True
            self.ai_done = False
            self.refresh_thumbs()
        self.root.bell()
        need_link = "" if self.link.get().strip() else "\n이제 파트너스 링크를 복사하세요."
        self.say(f"✓ 확장프로그램: 상품명, 사진 {added}장, 상세 글 {len(data['text']):,}자를 받았습니다.{need_link}")

    def on_target(self):
        msg = {"auto": "자동: 상품명이 비어 있으면 상품명, 아니면 특징메모에 넣습니다.",
               "name": "복사한 글이 상품명을 바꿉니다.",
               "memo": "복사한 글이 특징메모에 이어 붙습니다."}
        self.say(msg[self.target.get()])

    def load_existing_photos(self, name):
        """수정 모드: 저장돼 있던 사진을 목록에 불러온다. 이미 캡처한 사진은 뒤에 붙인다(같은 사진 제외)."""
        try:
            saved = load_saved_photos(name)
        except Exception:
            saved = []
        captured = [im for im in self.images if not image_tools.is_duplicate(im, saved)]
        merged = image_tools.unique_photos(saved + captured)
        cut = max(len(merged) - MAX_PHOTOS, 0)
        self.images = merged[:MAX_PHOTOS]
        self.photos_loaded = True
        self.photos_dirty = bool(captured) or len(merged) != len(saved)
        self.refresh_thumbs()
        if cut:
            self.root.bell()
            messagebox.showwarning("사진 개수", f"사진이 {len(merged)}장이라 앞의 {MAX_PHOTOS}장만 남겼습니다.")

    def add_image(self, img):
        if image_tools.is_duplicate(img, self.images):
            self.root.bell()
            self.say("⚠ 이미 목록에 있는 사진이라 추가하지 않았습니다.")
            return
        if len(self.images) >= MAX_PHOTOS:
            self.root.bell()
            self.say(f"⚠ 사진은 최대 {MAX_PHOTOS}장까지입니다. 필요 없는 사진을 클릭해 지운 뒤 캡처하세요.")
            return
        self.images.append(img.copy())
        self.photos_dirty = True
        self.ai_done = False  # 새 캡처가 생겼으니 저장할 때 메모를 다시 읽을 수 있게
        self.refresh_thumbs()
        self.say(f"✓ 사진 추가 ({img.size[0]}×{img.size[1]}). 잘못 찍었으면 사진을 클릭해 지우세요.")

    def refresh_thumbs(self):
        for w in self.thumbs.winfo_children():
            if w is not self.empty_thumb:
                w.destroy()
        self.thumb_refs = []
        if not self.images:
            self.empty_thumb.grid(row=0, column=0, columnspan=5, sticky="we")
        else:
            self.empty_thumb.grid_remove()
        per_row = 5  # 낮은 창에 10장이 두 줄로 들어가게
        for i, im in enumerate(self.images):
            t = im.convert("RGB").copy()
            t.thumbnail((40, 40))
            ph = ImageTk.PhotoImage(t)
            self.thumb_refs.append(ph)
            cell = tk.Frame(self.thumbs, bg="#F1F5F9")
            cell.grid(row=i // per_row, column=i % per_row, padx=1, pady=1)
            lb = tk.Label(cell, image=ph, cursor="hand2", bd=1, relief="solid", width=42, height=42)
            lb.pack()
            num = tk.Label(cell, text=f"{i + 1}  ✕", bg="#F1F5F9", fg="#555", cursor="hand2")
            num.pack()
            for w in (lb, num):
                w.bind("<Button-1>", lambda e, idx=i: self.remove_image(idx))
        self.count.config(text=f"{len(self.images)}/{MAX_PHOTOS}장")

    def remove_image(self, idx):
        if 0 <= idx < len(self.images):
            del self.images[idx]
            self.info_idx = [i - (i > idx) for i in self.info_idx if i != idx]
            self.photos_dirty = True
            self.refresh_thumbs()
            self.say(f"사진 {idx + 1}번을 지웠습니다. (남은 사진 {len(self.images)}장)")

    def undo_image(self):
        if self.images:
            self.remove_image(len(self.images) - 1)
        else:
            self.say("지울 사진이 없습니다.")

    # ------------------------------------------------ 버튼
    def capture(self):
        try:
            subprocess.Popen(["explorer", "ms-screenclip:"])  # 윈도우 캡처 도구 (Win+Shift+S와 같음)
            self.say("상품 사진 부분을 드래그하세요. 잘라낸 사진은 자동으로 추가됩니다.")
        except Exception:
            self.say("Win + Shift + S 를 눌러 상품 사진 부분을 드래그하세요.")

    def open_folder(self):
        root = image_tools.photo_root()
        root.mkdir(parents=True, exist_ok=True)
        os.startfile(root)

    def new_product(self):
        if ((self.photos_dirty and self.images) or self.name.get().strip()) and not messagebox.askyesno(
                "초기화", "입력 중인 내용을 모두 지우고 새 상품을 시작할까요?"):
            return
        self.reset_fields()
        self.say("초기화했습니다. 다음 상품의 링크를 복사하세요.")

    def set_mode(self, edit_name=None):
        """새 등록(파란 버튼) / 수정 중(주황 버튼) 표시."""
        title = (lambda t: self.root.title(t)) if self.standalone else (lambda t: None)
        if edit_name is None:
            title("쿠팡 캡처 도우미 — 새 상품 등록")
            self.save_btn.config(text="저장 → 다음 상품", bg="#2563EB", activebackground="#1D4ED8")
        else:
            short = edit_name if len(edit_name) <= 24 else edit_name[:24] + "…"
            title(f"쿠팡 캡처 도우미 — 수정 중: {short}")
            self.save_btn.config(text="✎ 수정 내용 저장 (이미 등록된 상품)", bg="#EA580C",
                                 activebackground="#C2410C")

    def tidy_sheet(self):
        """엑셀의 중복 상품을 한 줄로 정리 (엑셀이 열려 있으면 다음 기회에)."""
        try:
            n = merge_duplicates()
        except PermissionError:
            return
        except Exception:
            return
        if n:
            log(f"캡처 도우미: 중복 상품 {n}줄을 합쳐 정리")
            self.say(f"✓ 엑셀에서 같은 상품 {n}줄을 한 줄로 합쳤습니다 (최신 링크로).")

    def tidy_photos(self):
        """사진 폴더의 중복 사진 정리 (시작할 때 한 번)."""
        try:
            folders, moved = image_tools.dedupe_all_folders()
        except Exception:
            return
        if moved:
            log(f"캡처 도우미: 중복 사진 {moved}장을 _중복사진 폴더로 옮김")
            self.say(f"✓ 중복 사진 {moved}장을 정리했습니다 (사진\\_중복사진 폴더로 옮김).")

    def reset_fields(self):
        self.editing = None
        self.set_mode()
        self.target.set("auto")
        self.name_replace_next = False
        self.link.delete(0, "end")
        self.name.delete(0, "end")
        self.memo.delete("1.0", "end")
        self.category.set("")
        self.images.clear()
        self.photos_loaded = False
        self.photos_dirty = False
        self.ai_done = False
        self.info_idx = []
        self.page_text = ""
        self.refresh_thumbs()

    # ------------------------------------------------ 제미나이 메모 자동 작성
    def run_ai(self, then):
        """캡처를 제미나이에 보내 상품명·특징메모를 채운다. then이 있으면 끝난 뒤 호출(저장 계속)."""
        import threading
        import memo_ai
        if not memo_ai.env("GEMINI_API_KEY"):
            if then is None:
                messagebox.showinfo("메모 자동 작성", "설정 → 특징메모에서 제미나이 키를 넣어 주세요 (무료).")
            self.ai_done = True
            if then:
                then()
            return
        if not self.images and not self.page_text:
            self.say("⚠ 캡처한 사진이 없어 메모를 쓸 수 없습니다. 상품 사진·설명을 캡처해 주세요.")
            return
        images, name, link = list(self.images), self.name.get().strip(), self.link.get().strip()
        page_text = self.page_text
        cats = category_choices()
        self.save_btn.config(state="disabled")
        self.say("✨ AI가 캡처를 읽고 메모를 쓰는 중… (10~20초)")

        def work():
            try:
                res, err = memo_ai.write_memo(images, name, link, cats, page_text), None
            except Exception as e:
                res, err = None, e
            self.root.after(0, lambda: done(res, err))

        def done(res, err):
            self.save_btn.config(state="normal")
            self.ai_done = True
            if err is not None:
                self.say(f"⚠ 메모 자동 작성 실패: {err}")
                if then and not messagebox.askyesno("메모 자동 작성 실패",
                                                    f"{err}\n\n메모 없이 저장할까요? (게시 전에 서버가 한 번 더 시도해요)"):
                    return
            else:
                if res["name"] and not self.name.get().strip():
                    self.name.insert(0, res["name"][:200])
                if res["memo"] and (then is None or not self.memo.get("1.0", "end").strip()):
                    self.memo.delete("1.0", "end")
                    self.memo.insert("1.0", res["memo"])
                self.info_idx = res["info"]
                if res.get("category") in cats and not self.category.get():
                    self.category.set(res["category"])
                extra = f"\n설명 캡처 {len(self.info_idx)}장은 메모용으로만 저장합니다." if self.info_idx else ""
                self.say(("✓ 메모를 채웠습니다. 확인하고 고칠 수 있어요." if res["memo"]
                          else "⚠ 캡처에서 특징을 찾지 못했습니다. 상세 설명을 캡처해 보세요.") + extra)
            if then:
                then()

        threading.Thread(target=work, daemon=True).start()

    def split_images(self):
        """(게시용 사진, 설명 캡처) 나누기."""
        post = [im for i, im in enumerate(self.images) if i not in self.info_idx]
        info = [im for i, im in enumerate(self.images) if i in self.info_idx]
        return post, info

    def save_info(self, name, info):
        """설명 캡처는 사진 폴더 안 _설명 폴더에 (게시에는 안 쓰고, 메모 다시 쓸 때 읽음)."""
        if not info:
            return
        folder = photo_folder(name) / "_설명"
        folder.mkdir(parents=True, exist_ok=True)
        n = len(image_tools.images_in(folder))
        for im in info:
            n += 1
            im.convert("RGB").save(folder / f"{n:02d}.jpg", quality=90)

    def save(self):
        link = self.link.get().strip()
        name = self.name.get().strip()
        memo = " ".join(self.memo.get("1.0", "end").split())
        if not is_link(link):
            extra = "\n\n일반 쇼핑몰 주소는 수익이 잡히지 않습니다." if is_plain_store(link) else ""
            messagebox.showwarning("확인", "제휴 링크(예: https://link.coupang.com/a/...)를 넣어 주세요." + extra)
            return
        import memo_ai
        if ((not memo or not name or not self.category.get()) and (self.images or self.page_text) and memo_ai.enabled()
                and not self.ai_done):
            self.run_ai(self.save)  # 메모(또는 상품명)를 AI가 채운 뒤 저장 계속
            return
        if not name:
            messagebox.showwarning("확인", "상품명을 넣어 주세요.")
            return
        existing = self.editing
        if existing is None:
            try:
                existing = find_product(link=link, name=name)
            except Exception as e:
                messagebox.showerror("읽기 실패", str(e))
                return
        if existing is not None:
            changes = []
            if name != existing["name"]:
                changes.append(f"상품명: {existing['name']} → {name}")
            if memo != existing["memo"]:
                changes.append("특징메모 수정")
            if link != existing["link"]:
                changes.append("링크를 새 링크로 교체")
            category = self.category.get()
            if category != existing.get("category", ""):
                changes.append(f"분류: {existing.get('category') or '없음'} → {category or '없음'}")
            if self.photos_dirty:
                changes.append(f"사진을 지금 목록({len(self.images)}장)으로 저장" if self.photos_loaded
                               else f"사진 {len(self.images)}장 추가")
            if self.page_text and self.page_text != load_page_text(existing["name"]):
                changes.append(f"상세 글 {len(self.page_text):,}자 저장")
            if not changes:
                messagebox.showinfo("변경 없음", "이미 등록된 상품이고 바뀐 내용이 없습니다.")
                return
            if not messagebox.askyesno("업데이트", "이미 등록된 상품입니다. 아래 내용으로 업데이트할까요?\n\n"
                                       + "\n".join("• " + c for c in changes)):
                return
            try:
                old = update_product(existing["link"], name, memo, new_link=link, category=category)
            except PermissionError:
                messagebox.showerror("저장 실패", "products.csv가 엑셀에 열려 있습니다. 엑셀을 닫고 다시 눌러 주세요.")
                return
            if old and old != name:
                move_photos(old, name)
            if self.photos_dirty:
                post, info = self.split_images()
                save_photos(name, post, replace=self.photos_loaded)
                self.save_info(name, info)
            save_page_text(name, self.page_text)
            log(f"캡처 도우미: '{name}' 업데이트 ({', '.join(changes)})")
            self.reset_fields()
            self.say(f"✓ 업데이트 완료: {name}\n다음 상품의 링크를 복사하세요.")
            return
        try:
            append_product(name, link, memo, self.category.get())
        except PermissionError:
            messagebox.showerror("저장 실패", "products.csv가 엑셀에 열려 있습니다. 엑셀을 닫고 다시 눌러 주세요.")
            return
        except Exception as e:
            messagebox.showerror("저장 실패", str(e))
            return
        post, info = self.split_images()
        n = len(post)
        folder = save_photos(name, post) if n else None
        self.save_info(name, info)
        save_page_text(name, self.page_text)
        log(f"캡처 도우미: '{name}' 추가 (사진 {n}장)")
        self.tidy_sheet()

        self.reset_fields()
        where = f" → {folder.name} 폴더" if folder else ""
        self.say(f"✓ 저장 완료: {name} (사진 {n}장{where})\n다음 상품의 링크를 복사하세요.")


if __name__ == "__main__":
    root = tk.Tk()
    try:
        Helper(root)
    except Exception as e:  # 창 없이 실행되므로 오류는 알림 창으로 보여줌
        root.withdraw()
        messagebox.showerror("캡처 도우미 오류", f"{e}\n\n(setup.bat을 실행했는지 확인해 주세요)")
        raise SystemExit(1)
    root.report_callback_exception = lambda *a: messagebox.showerror("캡처 도우미 오류", str(a[1]))
    root.mainloop()
