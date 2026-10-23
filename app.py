# -*- coding: utf-8 -*-
"""쿠팡 자동게시 프로그램 (창 하나에 탭 5개).
  상품 등록 : 캡처 도우미 (링크·사진 캡처 → 시트·사진 폴더에 저장, 메모는 AI가 자동 작성)
  상품 목록 : 등록한 상품, 메모·사진·게시 여부 / 수정·메모 다시 쓰기·삭제
  게시      : 지금 게시·미리보기·토큰 연장 (깃허브 서버 실행), 최근 실행·게시 기록
  블로그    : 네이버·티스토리 글 지금 쓰기 (깃허브 서버 실행), 서버가 만든 글 목록
  설정      : 예약 시각, 채널, 쓰레드 댓글, 메모, 키 등 모든 설정
실행: python app.py  (또는 CoupangAutopost.exe)
"""
import datetime
import json
import os
import re
import threading
import tkinter as tk
import webbrowser
from tkinter import filedialog, messagebox, ttk

import requests

import settings

APP_TITLE = "쿠팡 자동게시"
WORKFLOW = "post.yml"
BLOG_WORKFLOW = "blog.yml"
# 블로그 이름 → blog_config.json의 key
BLOGS = {"전체": "", "티스토리": "tistory", "남다른 오늘": "naver1", "알뜰한 오늘": "naver2", "쓸모있는 오늘": "naver3"}


def apply_env(vals):
    """설정값을 이 프로그램 안에서 바로 쓰도록 환경에 반영."""
    for k, v in vals.items():
        if v is not None and k in settings.BY_KEY:
            os.environ[k] = str(v)


# ---------------------------------------------------------------- 깃허브
def repo():
    return (os.getenv("GITHUB_REPO") or "todayinfopick/pick").strip()


def gh_headers():
    h = {"Accept": "application/vnd.github+json"}
    tok = (os.getenv("GITHUB_TOKEN") or "").strip()
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    return h


def gh_dispatch(mode, workflow=WORKFLOW, inputs=None):
    r = requests.post(f"https://api.github.com/repos/{repo()}/actions/workflows/{workflow}/dispatches",
                      headers=gh_headers(), json={"ref": "main", "inputs": inputs or {"mode": mode}}, timeout=30)
    if r.status_code in (401, 403, 404):
        raise RuntimeError(f"깃허브 키를 확인해 주세요 ({r.status_code}). 키에 Actions 쓰기 권한이 있어야 해요.")
    if r.status_code >= 400:
        raise RuntimeError(f"깃허브 실행 요청 실패 ({r.status_code}): {r.text[:200]}")


def gh_runs(n=12, workflow=WORKFLOW):
    r = requests.get(f"https://api.github.com/repos/{repo()}/actions/workflows/{workflow}/runs",
                     headers=gh_headers(), params={"per_page": n}, timeout=30)
    r.raise_for_status()
    return r.json().get("workflow_runs", [])


def gh_put_file(path, text, message, branch="blog-packages", sha=None):
    """저장소 branch에 텍스트 파일 하나를 올린다 (깃허브 키에 Contents 쓰기 권한 필요). 있던 파일을 바꿀 땐 sha를 줌."""
    import base64
    body = {"message": message, "branch": branch, "content": base64.b64encode(text.encode("utf-8")).decode()}
    if sha:
        body["sha"] = sha
    r = requests.put(f"https://api.github.com/repos/{repo()}/contents/{path}", headers=gh_headers(), timeout=30,
                     json=body)
    if r.status_code in (401, 403, 404):
        raise RuntimeError(f"깃허브 키를 확인해 주세요 ({r.status_code}). 키에 Contents 쓰기 권한이 있어야 해요.")
    if r.status_code >= 400:
        raise RuntimeError(f"서버에 올리지 못했어요 ({r.status_code}): {r.text[:200]}")


def gh_delete_file(path, message, branch="blog-packages"):
    """저장소 branch의 파일 하나를 지운다. 이미 없으면 그냥 넘어감."""
    r = requests.get(f"https://api.github.com/repos/{repo()}/contents/{path}", headers=gh_headers(),
                     params={"ref": branch}, timeout=30)
    if r.status_code == 404:
        return
    r.raise_for_status()
    r = requests.delete(f"https://api.github.com/repos/{repo()}/contents/{path}", headers=gh_headers(), timeout=30,
                        json={"message": message, "branch": branch, "sha": r.json()["sha"]})
    if r.status_code in (401, 403):
        raise RuntimeError(f"깃허브 키를 확인해 주세요 ({r.status_code}). 키에 Contents 쓰기 권한이 있어야 해요.")
    r.raise_for_status()


def blog_delete(ids):
    """서버 글 패키지를 지운다: index.json 목록에서 빼고 폴더 파일도 지움 (스튜디오 목록에서도 사라짐)."""
    import base64
    r = requests.get(f"https://api.github.com/repos/{repo()}/contents/index.json", headers=gh_headers(),
                     params={"ref": "blog-packages"}, timeout=30)
    r.raise_for_status()
    index = json.loads(base64.b64decode(r.json()["content"]).decode("utf-8"))
    gone = [p for p in index["packages"] if p["id"] in ids]
    index["packages"] = [p for p in index["packages"] if p["id"] not in ids]
    gh_put_file("index.json", json.dumps(index, ensure_ascii=False, indent=1), f"글 {len(gone)}개 지움",
                sha=r.json()["sha"])
    for p in gone:
        for name in (p.get("files") or ["content.json"]) + (p.get("videos") or []):
            gh_delete_file(f"{p['id']}/{name}", f"글 지움: {p['id']}")


def blog_done():
    """발행 완료로 표시한 글 (blog-packages/done.json) → ({id: 표시한 때}, sha). 없으면 빈 것."""
    r = requests.get(f"https://api.github.com/repos/{repo()}/contents/done.json", headers=gh_headers(),
                     params={"ref": "blog-packages", "t": datetime.datetime.now().timestamp()}, timeout=30)
    if not r.ok:
        return {}, None
    import base64
    data = json.loads(base64.b64decode(r.json()["content"]).decode("utf-8") or "{}")
    return data.get("done", {}), r.json()["sha"]


def draft_check(text):
    """붙여 넣은 초안 → (블로그 key, 제목, 공백 뺀 본문 글자 수, 문제 목록)."""
    meta, n = {}, 0
    for ln in text.splitlines():
        if ln.startswith("@") and ":" in ln:
            k, v = ln[1:].split(":", 1)
            meta[k.strip()] = v.strip()
        elif not ln.startswith(("[사진", "[카드")):
            n += len("".join(ln.lstrip("#>!- ").replace("**", "").replace("|", "").split()))
    want = meta.get("blog", "")
    key = BLOGS.get(want) or (want if want in BLOGS.values() and want else "")
    problems = []
    if not key:
        problems.append("@blog 줄이 없거나 블로그를 알 수 없어요 (tistory, naver1, naver2, naver3)")
    if not meta.get("title"):
        problems.append("@title 줄이 없어요")
    if n < 1500:
        problems.append(f"본문이 공백 빼고 {n}자예요 (1,500자 이상 권장)")
    return key, meta.get("title", ""), n, problems


def gh_posted():
    r = requests.get(f"https://raw.githubusercontent.com/{repo()}/main/posted.json",
                     params={"t": datetime.datetime.now().timestamp()}, timeout=30)
    return r.json() if r.ok else {}


def kst(iso):
    """깃허브 시간(UTC 'Z') → 한국 시간 'MM/DD HH:MM'. 시간대 없는 값(posted.json)은 이미 한국 시간."""
    try:
        t = datetime.datetime.fromisoformat(iso.replace("Z", "+00:00"))
        if t.tzinfo:
            t = t.astimezone(datetime.timezone.utc).replace(tzinfo=None) + datetime.timedelta(hours=9)
        return t.strftime("%m/%d %H:%M")
    except Exception:
        return iso or ""


def in_thread(root, work, done):
    """오래 걸리는 일(인터넷)은 뒤에서 하고, 끝나면 화면에서 done(결과, 오류)."""
    def run():
        try:
            res, err = work(), None
        except Exception as e:
            res, err = None, e
        root.after(0, lambda: done(res, err))
    threading.Thread(target=run, daemon=True).start()


# ---------------------------------------------------------------- 상품 목록 탭
class ListTab:
    COLS = [("name", "상품명", 80), ("cat", "분류", 34), ("memo", "메모", 30), ("photos", "사진", 30),
            ("threads", "쓰레드", 48), ("instagram", "인스타", 48)]

    def __init__(self, app, frame):
        self.app, self.root = app, app.root
        bar = tk.Frame(frame)
        bar.pack(fill="x", padx=10, pady=8)
        tk.Button(bar, text="↻", command=self.refresh).pack(side="left")
        tk.Button(bar, text="✎ 수정", command=self.edit).pack(side="left", padx=2)
        tk.Button(bar, text="✨ 메모", command=self.rememo).pack(side="left")
        tk.Button(bar, text="🗑", command=self.delete).pack(side="left", padx=2)
        tk.Button(bar, text="게시됨", command=self.select_done).pack(side="left")
        tk.Button(bar, text="🎬", command=self.remake_shorts).pack(side="left", padx=2)
        tk.Button(bar, text="📁", command=self.open_folder).pack(side="right")

        box = tk.Frame(frame)
        box.pack(fill="both", expand=True, padx=10)
        self.tree = ttk.Treeview(box, columns=[c[0] for c in self.COLS], show="headings", selectmode="extended")
        for key, title, w in self.COLS:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=w, minwidth=30, anchor="w" if key == "name" else "center", stretch=False)
        sb = ttk.Scrollbar(box, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=sb.set, xscrollcommand=hsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        hsb.pack(fill="x", padx=10)
        self.tree.bind("<Double-1>", lambda e: self.edit())
        self.tree.tag_configure("done", foreground="#888")
        self.tree.tag_configure("nomemo", foreground="#B45309")

        self.detail = tk.Label(frame, text="", anchor="w", justify="left", wraplength=250, fg="#333")
        self.detail.pack(fill="x", padx=10, pady=4)
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.show_detail())
        self.status = tk.Label(frame, text="", anchor="w", fg="#555", justify="left", wraplength=260)
        self.status.pack(fill="x", padx=10, pady=(0, 8))
        self.items = {}

    def refresh(self):
        import helper
        self.status.config(text="불러오는 중…")

        def work():
            header, rows = helper.read_rows()
            try:
                posted = gh_posted()
            except Exception:
                posted = {}
            return header, rows, posted

        in_thread(self.root, work, self.fill)

    def fill(self, res, err):
        import helper
        import image_tools
        import main
        if err:
            self.status.config(text=f"⚠ 목록을 읽지 못했습니다: {err}")
            return
        header, rows, posted = res
        idx = {c: header.index(c) for c in ("상품명", "파트너스링크", "특징메모", "분류") if c in header}
        self.tree.delete(*self.tree.get_children())
        self.items = {}
        waiting = 0
        for n, r in enumerate(rows, start=2):
            cell = lambda c: r[idx[c]].strip() if c in idx and len(r) > idx[c] else ""
            name, link, memo = cell("상품명"), cell("파트너스링크"), cell("특징메모")
            if not name:
                continue
            item = {"name": name, "link": link, "memo": memo, "row": n, "done": False}
            rec = main.get_rec(posted, item)
            folder = helper.photo_folder(name)
            try:
                nphotos = len(image_tools.images_in(folder)) if folder.is_dir() else 0
            except OSError:
                nphotos = 0
            when = {ch: kst(rec[ch]["at"])[:11] if ch in rec else "" for ch in ("threads", "instagram")}
            done = bool(when["threads"] or when["instagram"])
            waiting += not done
            item["done"] = done
            iid = self.tree.insert("", "end", values=(name.split(",")[0], cell("분류") or "—",
                                                      "✓" if memo else "—", nphotos,
                                                      when["threads"] or "대기", when["instagram"] or "대기"),
                                   tags=("done",) if done else (() if memo else ("nomemo",)))
            self.items[iid] = item
        self.status.config(text=f"상품 {len(self.items)}개 · 게시 대기 {waiting}개 · "
                                f"주황색 = 메모 없음(게시 전에 AI가 채움) · 회색 = 게시됨 · "
                                f"Ctrl·Shift+클릭으로 여러 개 선택")

    def selected(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("상품 목록", "목록에서 상품을 먼저 골라 주세요.")
            return None
        return self.items.get(sel[0])

    def show_detail(self):
        sel = self.tree.selection()
        item = self.items.get(sel[0]) if sel else None
        if item:
            self.detail.config(text=f"{item['name']}\n메모: {item['memo'] or '(없음)'}\n링크: {item['link']}")

    def edit(self):
        item = self.selected()
        if item:
            self.app.notebook.select(self.app.reg_frame)
            self.app.helper.take_text(item["link"])  # 링크를 넣으면 등록된 상품을 불러와 수정 모드

    def rememo(self):
        import helper
        import memo_ai
        item = self.selected()
        if not item:
            return
        folder = helper.photo_folder(item["name"])
        images = helper.load_saved_photos(item["name"])
        if (folder / "_설명").is_dir():
            images += self._load_dir(folder / "_설명")
        page_text = helper.load_page_text(item["name"])
        if not images and not page_text:
            messagebox.showinfo("메모 다시 쓰기", "이 상품의 사진 폴더에 캡처가 없습니다.")
            return
        self.status.config(text=f"✨ '{item['name'][:20]}' 메모를 쓰는 중…")

        def work():
            res = memo_ai.write_memo(images, item["name"], item["link"], page_text=page_text)
            if res["memo"]:
                helper.update_product(item["link"], item["name"], res["memo"])
            return res

        def done(res, err):
            if err:
                self.status.config(text=f"⚠ {err}")
            elif not res["memo"]:
                self.status.config(text="⚠ 캡처에서 특징을 찾지 못했습니다. 상세 설명을 캡처해 넣어 보세요.")
            else:
                self.status.config(text="✓ 메모를 새로 썼습니다.")
                self.refresh()

        in_thread(self.root, work, done)

    @staticmethod
    def _load_dir(folder):
        import image_tools
        from PIL import Image
        out = []
        for f in image_tools.images_in(folder):
            with Image.open(f) as im:
                out.append(im.copy())
        return out

    def remake_shorts(self):
        """고른 상품의 쇼츠를 서버에서 다시 만든다 (잘못된 사진은 먼저 사진 폴더에서 지움)."""
        item = self.selected()
        if not item or not messagebox.askyesno(
                "쇼츠 다시 만들기", f"'{item['name'][:30]}' 쇼츠를 다시 만들까요?\n\n"
                                 "잘못 들어간 사진이 있으면 먼저 📁 사진 폴더(상세 폴더 포함)에서 지우고,\n"
                                 "구글 드라이브에 올라간 뒤(1~2분) 눌러 주세요.\n\n"
                                 "5분쯤 뒤 휴대폰 쇼츠 받기 페이지에 새 영상이 올라와요."):
            return

        def done(_, err):
            self.status.config(text=f"⚠ {err}" if err else "✓ 쇼츠 다시 만들기를 요청했어요. 5분쯤 뒤 받기 페이지를 새로고침하세요.")

        in_thread(self.root, lambda: gh_dispatch(None, inputs={"mode": "쇼츠 다시 만들기", "product": item["link"]}), done)

    def select_done(self):
        """게시된 상품을 모두 선택 (한 번에 지울 때)."""
        done = [iid for iid, it in self.items.items() if it.get("done")]
        self.tree.selection_set(done)
        if done:
            self.tree.see(done[0])
        self.status.config(text=f"게시된 상품 {len(done)}개를 골랐습니다. 🗑을 누르면 한꺼번에 지웁니다.")

    def delete(self):
        import shutil
        import helper
        import image_tools
        items = [self.items[i] for i in self.tree.selection() if i in self.items]
        if not items:
            messagebox.showinfo("상품 목록", "목록에서 상품을 먼저 골라 주세요.")
            return
        what = f"'{items[0]['name'][:30]}'" if len(items) == 1 else f"상품 {len(items)}개"
        if not messagebox.askyesno("삭제", f"{what}을(를) 목록에서 지울까요?\n"
                                         "(게시된 상품은 링크 페이지에 그대로 남습니다)"):
            return
        # 사진 폴더는 구글 드라이브 폴더라 지워도 드라이브 휴지통에서 30일 동안 되살릴 수 있음
        folders = [helper.photo_folder(it["name"]) for it in items]
        root = image_tools.photo_root().resolve()
        folders = [f for f in folders if f.is_dir() and f.resolve().parent == root]  # 상품 폴더만 (사진 폴더 전체는 절대 안 지움)
        others = {helper.photo_folder(it["name"]) for it in self.items.values() if it not in items}
        folders = [f for f in folders if f not in others]  # 남는 상품과 같이 쓰는 폴더는 둠
        drop_photos = bool(folders) and messagebox.askyesno(
            "사진 폴더", f"사진 폴더 {len(folders)}개도 같이 지울까요?\n(구글 드라이브 휴지통에서 되살릴 수 있어요)")
        links = {it["link"] for it in items}

        def work():
            header, rows = helper.read_rows()
            li = header.index("파트너스링크")
            keep = [r for r in rows if not (len(r) > li and r[li].strip() in links)]
            helper.write_rows(header, keep)
            failed = 0
            for f in folders if drop_photos else []:
                try:
                    shutil.rmtree(f)
                except OSError:
                    failed += 1
            return failed

        def done(failed, e):
            if e:
                self.status.config(text=f"⚠ {e}")
                return
            self.refresh()
            if failed:
                messagebox.showwarning("사진 폴더", f"사진 폴더 {failed}개는 지우지 못했습니다. (열려 있는 파일이 있으면 닫고 직접 지워 주세요)")

        in_thread(self.root, work, done)

    def open_folder(self):
        import helper
        import image_tools
        item = self.items.get((self.tree.selection() or [None])[0])
        path = helper.photo_folder(item["name"]) if item else image_tools.photo_root()
        if not path.is_dir():
            path = image_tools.photo_root()
        path.mkdir(parents=True, exist_ok=True)
        os.startfile(path)


# ---------------------------------------------------------------- 게시 탭
class PostTab:
    def __init__(self, app, frame):
        self.app, self.root = app, app.root
        self.info = tk.Label(frame, text="", anchor="w", justify="left", font=("", 9), wraplength=260)
        self.info.pack(fill="x", padx=12, pady=(12, 6))

        bar = tk.Frame(frame)  # 좁은 창이라 2줄로
        bar.pack(fill="x", padx=10, pady=4)
        tk.Button(bar, text="▶ 지금 게시", bg="#2563EB", fg="white", width=9, height=2,
                  command=lambda: self.run("지금 게시")).grid(row=0, column=0, padx=(0, 6), pady=2)
        tk.Button(bar, text="👁 미리보기", width=9, height=2,
                  command=lambda: self.run("미리보기")).grid(row=0, column=1, pady=2)
        tk.Button(bar, text="✍ 일반 글 게시", width=9, height=2,
                  command=lambda: self.run("일반 글 게시")).grid(row=1, column=0, padx=(0, 6), pady=2)
        tk.Button(bar, text="🔑 토큰 연장", width=9, height=2,
                  command=lambda: self.run("토큰 연장")).grid(row=1, column=1, pady=2)


        links = tk.Frame(frame)
        links.pack(fill="x", padx=10, pady=4)
        tk.Button(links, text="↻", command=self.refresh).pack(side="left", padx=(0, 4))
        for text, url in (("실행 기록", lambda: f"https://github.com/{repo()}/actions"),
                          ("링크 페이지", lambda: "https://{}.github.io/{}/".format(*repo().split("/"))),
                          ("키 안내", None)):
            tk.Button(links, text=text, relief="flat", fg="#2563EB", cursor="hand2", padx=1,
                      command=(lambda u=url: webbrowser.open(u())) if url else self.key_help).pack(side="left")

        tk.Label(frame, text="최근 서버 실행", anchor="w", font=("", 10, "bold")).pack(fill="x", padx=12, pady=(10, 0))
        self.runs = ttk.Treeview(frame, columns=("at", "what", "result"), show="headings", height=6)
        for k, t, w in (("at", "시각", 70), ("what", "종류", 60), ("result", "결과", 130)):
            self.runs.heading(k, text=t)
            self.runs.column(k, width=w, anchor="w")
        self.runs.pack(fill="x", padx=10)
        self.runs.bind("<Double-1>", self.open_run)
        self.run_urls = {}

        tk.Label(frame, text="최근 게시", anchor="w", font=("", 10, "bold")).pack(fill="x", padx=12, pady=(10, 0))
        self.posts = ttk.Treeview(frame, columns=("at", "name", "where"), show="headings", height=7)
        for k, t, w in (("at", "시각", 70), ("name", "상품", 120), ("where", "채널", 70)):
            self.posts.heading(k, text=t)
            self.posts.column(k, width=w, anchor="w")
        self.posts.pack(fill="both", expand=True, padx=10)
        self.status = tk.Label(frame, text="", anchor="w", fg="#555")
        self.status.pack(fill="x", padx=10, pady=8)

    def show_info(self):
        vals = self.app.values
        auto = vals.get("AUTO_POST", "1") != "0"
        try:
            times = settings.post_times(vals.get("POST_TIMES", ""))
        except ValueError:
            times = []
        now = datetime.datetime.now()
        nxt = next((now.replace(hour=h, minute=m, second=0) for h, m in times
                    if now.replace(hour=h, minute=m, second=0) > now), None)
        if nxt is None and times:
            nxt = (now + datetime.timedelta(days=1)).replace(hour=times[0][0], minute=times[0][1], second=0)
        tlist = ", ".join(f"{h:02d}:{m:02d}" for h, m in times) or "(없음)"
        if vals.get("GENERAL_ON", "1") != "0":
            tlist += f"\n일반 글: {vals.get('GENERAL_TIMES', '')}"
        self.info.config(text=(f"자동 게시: {'켜짐' if auto else '꺼짐'} (한국 시간)\n상품 글: {tlist}\n"
                               + (f"다음 회차: {nxt:%m/%d %H:%M} (보통 조금 늦게 올라가요)"
                                  if auto and nxt else "설정 탭에서 바꿀 수 있어요")))

    def refresh(self):
        self.show_info()
        self.status.config(text="불러오는 중…")
        in_thread(self.root, lambda: (gh_runs(), gh_posted()), self.fill)

    def fill(self, res, err):
        if err:
            self.status.config(text=f"⚠ 기록을 읽지 못했습니다: {err}")
            return
        runs, posted = res
        self.runs.delete(*self.runs.get_children())
        self.run_urls = {}
        event = {"schedule": "예약 확인", "workflow_dispatch": "버튼 실행", "push": "저장"}
        result = {"success": "✓ 완료", "failure": "✗ 실패 (더블클릭해서 보기)", "cancelled": "취소됨",
                  "skipped": "건너뜀"}
        for r in runs:
            res_text = result.get(r.get("conclusion"), "진행 중…" if r.get("status") != "completed" else "")
            iid = self.runs.insert("", "end", values=(kst(r.get("created_at", "")),
                                                     event.get(r.get("event"), r.get("event")), res_text))
            self.run_urls[iid] = r.get("html_url")
        self.posts.delete(*self.posts.get_children())
        rows = []
        for k, v in posted.items():
            if k == "_meta" or not isinstance(v, dict):
                continue
            for ch, label in (("threads", "쓰레드"), ("instagram", "인스타")):
                if isinstance(v.get(ch), dict):
                    rows.append((v[ch].get("at", ""), str(v.get("name", "")).split(",")[0], label))
        for g in posted.get("_general", []):
            where = "·".join(n for k, n in (("id", "쓰레드"), ("ig_id", "인스타")) if g.get(k)) or "쓰레드"
            rows.append((g.get("at", ""), "💬 " + g.get("topic", ""), where + "(일반 글)"))
        rows.sort(reverse=True)
        for at, name, ch in rows[:20]:
            self.posts.insert("", "end", values=(at[5:16].replace("T", " ").replace("-", "/"), name, ch))
        last = posted.get("_meta", {}).get("last_slot", "")
        self.status.config(text=f"마지막 예약 회차: {last or '없음'}")

    def open_run(self, _e):
        sel = self.runs.selection()
        if sel and self.run_urls.get(sel[0]):
            webbrowser.open(self.run_urls[sel[0]])

    def run(self, mode):
        if not (os.getenv("GITHUB_TOKEN") or "").strip():
            if messagebox.askyesno(APP_TITLE, "버튼으로 서버를 실행하려면 깃허브 키가 필요해요.\n"
                                              "(키 탭 → 변경 → 깃허브 키)\n\n"
                                              "지금은 깃허브 화면을 열어 직접 실행할까요?"):
                webbrowser.open(f"https://github.com/{repo()}/actions/workflows/{WORKFLOW}")
            return
        msg = {"지금 게시": "다음 상품 1개를 지금 바로 게시할까요?",
               "미리보기": "게시하지 않고 글·이미지만 만들어 볼까요?\n(결과는 실행 기록에서 확인)",
               "일반 글 게시": "쓰레드에 일반 글(광고 아님) 1개를 지금 올릴까요?",
               "토큰 연장": "쓰레드·인스타 토큰을 지금 연장할까요?"}[mode]
        if not messagebox.askyesno(APP_TITLE, msg):
            return
        self.status.config(text=f"'{mode}' 요청 중…")

        def done(_r, err):
            if err:
                self.status.config(text=f"⚠ {err}")
                return
            self.status.config(text=f"✓ '{mode}'를 서버에 요청했습니다. 1~3분 뒤 새로고침해 보세요.")
            self.root.after(8000, self.refresh)

        in_thread(self.root, lambda: gh_dispatch(mode), done)

    def key_help(self):
        messagebox.showinfo("깃허브 키 만드는 법", (
            "1. 확인을 누르면 깃허브 키 만들기 화면이 열려요.\n"
            "2. Token name: 아무 이름 (예: 쿠팡 프로그램)\n"
            "3. Expiration: No expiration (또는 1년)\n"
            f"4. Repository access: Only select repositories → {repo().split('/')[-1]}\n"
            "5. Permissions → Repository permissions → Actions: Read and write\n"
            "6. 맨 아래 Generate token → 나온 키를 복사\n"
            "7. 이 프로그램 키 탭 → 변경 → 깃허브 키에 붙여넣고 저장"))
        webbrowser.open("https://github.com/settings/personal-access-tokens/new")


# ---------------------------------------------------------------- 블로그 탭
def blog_index(name="index.json", empty=None):
    """서버가 만든 블로그 글 목록 (blog-packages 브랜치의 index.json). 아직 없으면 빈 목록.
    raw 주소는 몇 분씩 옛 목록을 주므로(지운 글이 남아 보임) 깃허브 API로 먼저 읽는다."""
    empty = {"packages": []} if empty is None else empty
    try:
        r = requests.get(f"https://api.github.com/repos/{repo()}/contents/{name}", headers=gh_headers(),
                         params={"ref": "blog-packages"}, timeout=30)
        if r.ok:
            import base64
            return json.loads(base64.b64decode(r.json()["content"]).decode("utf-8"))
    except Exception:
        pass
    r = requests.get(f"https://raw.githubusercontent.com/{repo()}/blog-packages/{name}",
                     params={"t": datetime.datetime.now().timestamp()}, timeout=30)
    return r.json() if r.ok else empty


def fmt_vol(v):
    return f"{v / 10000:.1f}만".replace(".0만", "만") if v >= 10000 else f"{v:,}"


class KeywordWindow:
    """🛍 상품 키워드: 서버가 주기적으로 모으는 상품 추천 키워드(keywords.json의 products)를 보고
    복사하거나 쿠팡·네이버쇼핑 검색으로 바로 열어 올릴 상품을 고른다. 쿠팡 등록·블로그 쇼핑커넥트 둘 다에 씀."""

    def __init__(self, root):
        old = getattr(root, "_kw_win", None)
        if old is not None and old.winfo_exists():
            old.lift()
            return
        self.win = win = tk.Toplevel(root)
        root._kw_win = win
        win.title("🛍 오늘의 상품 키워드")
        win.geometry("570x520")
        self.note = tk.Label(win, text="불러오는 중…", anchor="w", justify="left", wraplength=540)
        self.note.pack(fill="x", padx=8, pady=(8, 2))
        cols = ("kw", "vol", "lv", "reason")
        self.tree = ttk.Treeview(win, columns=cols, show="headings", height=16)
        for c, t, w in zip(cols, ("키워드", "월 검색량", "경쟁", "추천 이유"), (190, 90, 65, 175)):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor="w" if c == "kw" else "center")
        self.tree.pack(fill="both", expand=True, padx=8)
        self.tree.bind("<Double-1>", lambda _e: self.open("coupang"))
        btns = tk.Frame(win)
        btns.pack(fill="x", padx=8, pady=8)
        tk.Button(btns, text="복사", command=self.copy).pack(side="left")
        tk.Button(btns, text="쿠팡에서 보기", command=lambda: self.open("coupang")).pack(side="left", padx=4)
        tk.Button(btns, text="네이버쇼핑에서 보기", command=lambda: self.open("naver")).pack(side="left")
        tk.Button(btns, text="새로고침", command=self.load).pack(side="right")
        self.collect_btn = tk.Button(btns, text="지금 새 수집", command=self.collect_now)
        self.collect_btn.pack(side="right", padx=(0, 6))
        tk.Label(win, text="더블클릭하면 쿠팡 검색이 열려요. 경쟁 낮은 것부터 위에 있어요.", fg="#666").pack(anchor="w", padx=8, pady=(0, 8))
        self.load()

    def collect_now(self):
        """GitHub Actions 키워드 전용 실행 요청. 글 생성·발행은 하지 않는다."""
        if not (os.getenv("GITHUB_TOKEN") or "").strip():
            if messagebox.askyesno("새 키워드 수집", "깃허브 키가 없어 자동 실행할 수 없습니다.\nGitHub Actions 화면을 열어 'Run workflow' → '키워드'로 실행할까요?", parent=self.win):
                webbrowser.open(f"https://github.com/{repo()}/actions/workflows/{BLOG_WORKFLOW}")
            return
        if not messagebox.askyesno("새 키워드 수집", "키워드·인기 이슈·상품 추천을 지금 다시 수집할까요?\n글쓰기와 발행은 실행하지 않습니다.", parent=self.win):
            return
        self.collect_btn.config(state="disabled")
        self.note.config(text="새 수집을 GitHub 서버에 요청하는 중…")

        def finished(_result, err):
            if not self.win.winfo_exists():
                return
            self.collect_btn.config(state="normal")
            if err:
                self.note.config(text=f"새 수집 요청 실패: {err}")
            else:
                self.note.config(text="✓ 새 수집 실행을 요청했습니다. GitHub Actions 완료 후 '새로고침'을 누르면 최신 결과가 표시됩니다.")

        in_thread(self.win, lambda: gh_dispatch("", BLOG_WORKFLOW, {"mode": "키워드", "blog": "", "count": "0"}), finished)

    def load(self):
        self.note.config(text="불러오는 중…")
        in_thread(self.win, lambda: blog_index("keywords.json", {}), self.fill)

    def fill(self, rep, err):
        if not self.win.winfo_exists():
            return
        self.tree.delete(*self.tree.get_children())
        items = (rep or {}).get("products") or []
        if err or not items:
            self.note.config(text="상품 키워드가 아직 없어요. 키 탭에 네이버 검색광고 키가 있어야 주기적으로 모아요." if not err else f"불러오지 못했어요: {err}")
            return
        for x in items:
            self.tree.insert("", "end", values=(x.get("keyword", ""), fmt_vol(x.get("volume") or 0), x.get("level") or "-", x.get("recommend_reason") or "-"))
        when = str(rep.get("updated", "")).replace("T", " ")
        self.note.config(text=f"{when} 갱신 · 검색량 많고 경쟁 낮은 상품 키워드 {len(items)}개 (신규 우선·강력한 상품만 조건부 재추천)")

    def keyword(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("상품 키워드", "키워드를 먼저 고르세요.", parent=self.win)
            return ""
        return self.tree.item(sel[0], "values")[0]

    def copy(self):
        kw = self.keyword()
        if kw:
            self.win.clipboard_clear()
            self.win.clipboard_append(kw)
            self.note.config(text=f"'{kw}' 복사했어요.")

    def open(self, where):
        kw = self.keyword()
        if not kw:
            return
        from urllib.parse import quote
        url = (f"https://www.coupang.com/np/search?q={quote(kw)}" if where == "coupang"
               else f"https://search.shopping.naver.com/search/all?query={quote(kw)}")
        webbrowser.open(url)


def kw_note(p):
    """목록 제목 뒤에 붙일 검색량 표시: ' · 🔍월 1.2만 경쟁 낮음'."""
    k = p.get("keyword") or {}
    v = k.get("volume")
    if not v:
        return ""
    return f" · 🔍월 {fmt_vol(v)}" + (f" 경쟁 {k['level']}" if k.get("level") else "")


class BlogTab:
    def __init__(self, app, frame):
        self.app, self.root = app, app.root
        self.info = tk.Label(frame, text="", anchor="w", justify="left", font=("", 9), wraplength=260)
        self.info.pack(fill="x", padx=12, pady=(12, 6))

        pick = tk.Frame(frame)
        pick.pack(fill="x", padx=10, pady=2)
        self.blog = tk.StringVar(value="전체")
        ttk.Combobox(pick, textvariable=self.blog, values=list(BLOGS), state="readonly", width=12) \
            .pack(side="left")
        self.count = tk.StringVar(value="1")
        tk.Spinbox(pick, from_=1, to=3, textvariable=self.count, width=3).pack(side="left", padx=(8, 2))
        tk.Label(pick, text="편씩").pack(side="left")
        tk.Button(frame, text="✍ 지금 글 쓰기", bg="#2563EB", fg="white", height=2,
                  command=self.run).pack(fill="x", padx=10, pady=(6, 2))
        tk.Button(frame, text="📋 초안 붙여넣기 (GPT·제미나이 글 → 서버)",
                  command=self.paste).pack(fill="x", padx=10, pady=(2, 6))

        links = tk.Frame(frame)
        links.pack(fill="x", padx=10, pady=2)
        tk.Button(links, text="↻", command=self.refresh).pack(side="left", padx=(0, 4))
        sheet = (os.getenv("GOOGLE_SHEET_ID") or "").strip()
        for text, url in (("실행 기록", lambda: f"https://github.com/{repo()}/actions/workflows/{BLOG_WORKFLOW}"),
                          ("글감 시트", (lambda: f"https://docs.google.com/spreadsheets/d/{sheet}/edit") if sheet else None)):
            if url:
                tk.Button(links, text=text, relief="flat", fg="#2563EB", cursor="hand2", padx=1,
                          command=lambda u=url: webbrowser.open(u())).pack(side="left")

        head = tk.Frame(frame)
        head.pack(fill="x", padx=10, pady=(10, 0))
        tk.Label(head, text="서버가 만든 글", anchor="w", font=("", 10, "bold")).pack(side="left")
        self.show_done = tk.BooleanVar(value=False)
        tk.Checkbutton(head, text="완료 글도 보기", variable=self.show_done, command=self.refresh).pack(side="right")
        self.posts = ttk.Treeview(frame, columns=("kind", "at", "blog", "title"), show="headings", height=12)
        for k, t, w in (("kind", "구분", 46), ("at", "날짜", 40), ("blog", "블로그", 76), ("title", "제목", 130)):
            self.posts.heading(k, text=t)
            self.posts.column(k, width=w, anchor="w")
        self.posts.pack(fill="both", expand=True, padx=10)
        self.posts.bind("<Double-1>", self.open_post)
        self.ids = {}
        self.pkgs = {}
        self.done = {}
        acts = tk.Frame(frame)
        acts.pack(fill="x", padx=10, pady=(4, 0))
        tk.Button(acts, text="✅ 발행 완료 표시/취소", command=self.mark_done).pack(side="left", fill="x", expand=True)
        tk.Button(acts, text="🎬 영상 받기", command=self.save_videos).pack(side="left", padx=(4, 0))
        tk.Button(acts, text="🗑 지우기", fg="#c0392b", command=self.delete).pack(side="left", padx=(4, 0))
        tk.Label(frame, text="가져오기: 크롬 AI Blog Studio → '서버에서 불러오기'. 발행은 직접 눌러요. 완료 표시는 스튜디오 목록에도 보여요.",
                 fg="#666", anchor="w", justify="left", wraplength=260).pack(fill="x", padx=10, pady=(6, 0))
        self.status = tk.Label(frame, text="", anchor="w", fg="#555", justify="left", wraplength=260)
        self.status.pack(fill="x", padx=10, pady=8)

    def show_info(self):
        vals = self.app.values
        on = vals.get("BLOG_ON", "1") != "0"
        n = vals.get("BLOG_POSTS_PER_BLOG", "2")
        self.info.config(text=(f"블로그 자동 작성: {'켜짐' if on else '꺼짐'}\n"
                               f"매일 새벽 4시쯤 블로그 4곳에 {n}편씩\n"
                               f"글 쓰는 AI: {vals.get('BLOG_WRITER', '제미나이')} · 설정 탭에서 바꿔요"))

    def refresh(self):
        self.show_info()
        self.status.config(text="불러오는 중…")
        in_thread(self.root, lambda: (blog_index(), gh_runs(1, BLOG_WORKFLOW), blog_done()[0]), self.fill)

    def fill(self, res, err):
        if err:
            self.status.config(text=f"⚠ 목록을 읽지 못했습니다: {err}")
            return
        index, runs, self.done = res
        self.posts.delete(*self.posts.get_children())
        self.ids = {}
        self.pkgs = {p.get("id"): p for p in index.get("packages", [])}
        today = datetime.date.today().isoformat()

        def rank(p):  # 급한 글(마감이 가까운 순) → 상시 글 → 기한 지난 글 → 발행 완료한 글
            if p.get("id") in self.done:
                return (3, "")
            if p.get("stock"):  # 비상용: 사진까지 붙어 있어 바로 써도 됨. 상시 글 아래
                return (1, "~")
            if not p.get("urgent"):
                return (1, "")
            until = p.get("until") or ""
            return (2, "") if until and until < today else (0, until or "9999")
        pkgs = [p for p in index.get("packages", [])[:60] if self.show_done.get() or rank(p)[0] < 3]
        for p in sorted(pkgs, key=rank):
            short = "⚠ " if (p.get("chars") or 0) < 1500 else ""
            r = rank(p)[0]
            kind = ("급함" + (" ~" + p["until"][5:].replace("-", "/") if p.get("until") else "")) if r == 0 else \
                ("비상용" if p.get("stock") else "상시", "지남", "✅완료")[r - 1]
            iid = self.posts.insert("", "end", values=(kind, p.get("date", "")[5:].replace("-", "/"), p.get("blogName", ""),
                                                      short + ("🎬 " if p.get("videos") else "") + p.get("title", "") + kw_note(p)))
            self.ids[iid] = p.get("id")
        last = ""
        if runs:
            r = runs[0]
            res_text = {"success": "✓ 완료", "failure": "✗ 실패 (실행 기록에서 보기)", "cancelled": "취소됨"}.get(
                r.get("conclusion"), "진행 중…" if r.get("status") != "completed" else "")
            last = f"마지막 실행: {kst(r.get('created_at', ''))} {res_text}"
        self.status.config(text=last or "아직 서버에서 글을 쓴 적이 없어요.")

    def mark_done(self):
        """고른 글을 발행 완료로 표시(이미 완료면 취소)해 서버 done.json에 저장. 스튜디오 목록도 이걸 읽음."""
        ids = [self.ids[i] for i in self.posts.selection() if self.ids.get(i)]
        if not ids:
            messagebox.showinfo(APP_TITLE, "목록에서 글을 먼저 고르세요 (Ctrl·Shift로 여러 개).")
            return
        if not (os.getenv("GITHUB_TOKEN") or "").strip():
            messagebox.showwarning(APP_TITLE, "서버에 저장하려면 깃허브 키가 필요해요. (키 탭 → 깃허브 키)")
            return
        self.status.config(text="저장하는 중…")

        def work():
            runs = gh_runs(1, BLOG_WORKFLOW)
            if runs and runs[0].get("status") != "completed":
                raise RuntimeError("지금 서버 블로그 작업이 도는 중이에요. 끝난 뒤 다시 눌러 주세요.")
            done, sha = blog_done()
            now = datetime.datetime.now().isoformat(timespec="seconds")
            for pid in ids:
                if pid in done:
                    done.pop(pid)
                else:
                    done[pid] = now
            gh_put_file("done.json", json.dumps({"done": done}, ensure_ascii=False, indent=1) + "\n",
                        f"발행 완료 표시 {len(ids)}개", sha=sha)

        in_thread(self.root, work, lambda _r, err: self.status.config(text=f"⚠ {err}") if err else self.refresh())

    def delete(self):
        """고른 글을 서버에서 지운다 (중복·잘못 올린 글). 되돌릴 수 없음."""
        sel = [i for i in self.posts.selection() if self.ids.get(i)]
        if not sel:
            messagebox.showinfo(APP_TITLE, "목록에서 지울 글을 먼저 고르세요 (Ctrl·Shift로 여러 개).")
            return
        titles = "\n".join("· " + str(self.posts.item(i, "values")[3])[:40] for i in sel)
        if not messagebox.askyesno(APP_TITLE, f"이 글 {len(sel)}개를 서버에서 지울까요? 되돌릴 수 없어요.\n\n{titles}"):
            return
        ids = [self.ids[i] for i in sel]
        self.status.config(text="지우는 중…")

        def work():
            runs = gh_runs(1, BLOG_WORKFLOW)
            if runs and runs[0].get("status") != "completed":
                raise RuntimeError("지금 서버 블로그 작업이 도는 중이에요. 끝난 뒤 다시 눌러 주세요.")
            blog_delete(ids)

        in_thread(self.root, work, lambda _r, err: self.status.config(text=f"⚠ {err}") if err else self.refresh())

    def save_videos(self):
        """고른 상품 글의 짧은 영상(가로·세로)을 내 컴퓨터 폴더에 받는다. 네이버 글쓰기 서론 뒤에 끌어다 넣으면 됨."""
        pkgs = [self.pkgs.get(self.ids[i]) for i in self.posts.selection() if self.ids.get(i)]
        pkgs = [p for p in pkgs if p and p.get("videos")]
        if not pkgs:
            messagebox.showinfo(APP_TITLE, "영상이 있는 글(제목 앞 🎬)을 목록에서 먼저 고르세요.")
            return
        down = os.path.join(os.path.expanduser("~"), "Downloads")
        folder = filedialog.askdirectory(title="영상을 저장할 폴더", initialdir=down if os.path.isdir(down) else None)
        if not folder:
            return
        self.status.config(text="영상 받는 중…")

        def work():
            saved = []
            for p in pkgs:
                base = re.sub(r'[\\/:*?"<>|]', "", p.get("title") or p["id"])[:40].strip()
                for name in p["videos"]:
                    r = requests.get(f"https://raw.githubusercontent.com/{repo()}/blog-packages/{p['id']}/{name}", timeout=120)
                    r.raise_for_status()
                    out = os.path.join(folder, f"{base}_{'세로' if 'vertical' in name else '가로'}.mp4")
                    with open(out, "wb") as f:
                        f.write(r.content)
                    saved.append(out)
            return saved

        def done(saved, err):
            if err:
                self.status.config(text=f"⚠ 영상을 받지 못했습니다: {err}")
                return
            self.status.config(text=f"🎬 영상 {len(saved)}개 저장: {folder}")
            try:
                os.startfile(folder)  # 윈도우: 폴더 열기
            except Exception:
                pass

        in_thread(self.root, work, done)

    def open_post(self, _e):
        sel = self.posts.selection()
        if sel and self.ids.get(sel[0]):
            webbrowser.open(f"https://github.com/{repo()}/tree/blog-packages/{self.ids[sel[0]]}")

    def paste(self):
        """채팅 AI가 쓴 초안(안내서 '서버 초안' 형식)을 blog-packages/drafts/에 올린다. 이미지는 서버가 붙임."""
        if not (os.getenv("GITHUB_TOKEN") or "").strip():
            messagebox.showwarning(APP_TITLE, "서버에 올리려면 깃허브 키가 필요해요. (키 탭 → 깃허브 키)")
            return
        win = tk.Toplevel(self.root)
        win.title("초안 붙여넣기")
        win.geometry("560x620")
        tk.Label(win, text="GPT·제미나이가 쓴 초안을 @blog 줄부터 그대로 붙여 넣으세요. 사진·카드는 서버가 붙여요.",
                 anchor="w", justify="left", wraplength=520).pack(fill="x", padx=10, pady=(10, 4))
        box = tk.Text(win, wrap="word", undo=True, font=("", 10))
        box.pack(fill="both", expand=True, padx=10)
        kind = tk.StringVar(value="today")
        row = tk.Frame(win)
        row.pack(fill="x", padx=10, pady=6)
        tk.Radiobutton(row, text="오늘 글 (바로 패키지로)", variable=kind, value="today").pack(side="left")
        tk.Radiobutton(row, text="비상용 (빈 날에 꺼내 씀)", variable=kind, value="stock").pack(side="left", padx=8)
        msg = tk.Label(win, text="", anchor="w", justify="left", fg="#555", wraplength=520)
        msg.pack(fill="x", padx=10)

        def pick_use(_e=None):
            """초안 머리 '@use: 오늘/비상용'(GPT·제미나이 지시문)을 보고 오늘 글/비상용을 알아서 고른다."""
            use = re.search(r"^@use:\s*(\S+)", box.get("1.0", "end"), re.M)
            if use:
                kind.set("stock" if "비상" in use.group(1) else "today")
        box.bind("<KeyRelease>", lambda e: win.after(50, pick_use))
        box.bind("<<Paste>>", lambda e: win.after(50, pick_use))

        def send():
            text = box.get("1.0", "end").strip().replace("```", "").strip()
            key, title, n, problems = draft_check(text)
            if not key or not title:
                messagebox.showwarning(APP_TITLE, "\n".join(problems), parent=win)
                return
            if problems and not messagebox.askyesno(APP_TITLE, "\n".join(problems) + "\n\n그래도 올릴까요?", parent=win):
                return
            now = datetime.datetime.now()
            pick_use()
            stock = kind.get() == "stock"
            folder = "stock" if stock else now.strftime("%Y-%m-%d")
            path = f"drafts/{folder}/{key}-chat-{now:%H%M%S}.txt"
            msg.config(text="올리는 중…")

            def work():  # 서버 작업이 도는 중에 올려도 서버가 저장할 때 옮겨 담음 → 연달아 올려도 됨
                gh_put_file(path, text + "\n", f"초안 붙여넣기: {title[:40]}")
                gh_dispatch("", BLOG_WORKFLOW, {"mode": "초안 정리", "blog": "", "count": "0"})  # 비상용도 바로 사진을 붙임

            def done(_r, err):
                if err:
                    msg.config(text=f"⚠ {err}", fg="#c0392b")
                    return
                box.delete("1.0", "end")
                msg.config(fg="#1e7e34", text=f"✓ {'비상용으로 ' if stock else ''}올리고 서버 작업을 시작했어요 ({n}자). "
                                              "몇 분 뒤 목록과 스튜디오 '서버에서 불러오기'에 나와요.")
                self.root.after(20000, self.refresh)

            in_thread(self.root, work, done)

        def send_files():
            """초안 파일(.txt/.md)을 여러 개 골라 하나씩 올린다. 한 파일에 @blog 줄로 시작하는 글이 여러 편이어도 나눠 올림.
            오늘 글/비상용은 각 글의 @use 줄을 따르고, 없으면 위에서 고른 쪽."""
            names = filedialog.askopenfilenames(parent=win, title="초안 파일 고르기 (여러 개 가능)",
                                                filetypes=[("초안", "*.txt *.md"), ("모든 파일", "*.*")])
            if not names:
                return
            drafts, bad = [], []
            for name in names:
                try:
                    raw = open(name, encoding="utf-8-sig").read().replace("```", "")
                except UnicodeDecodeError:
                    raw = open(name, encoding="cp949").read().replace("```", "")
                parts = [p.strip() for p in re.split(r"(?m)^(?=@blog:)", raw) if p.strip().startswith("@blog:")]
                for text in parts or [raw.strip()]:
                    key, title, n, problems = draft_check(text)
                    if key and title:
                        use = re.search(r"^@use:\s*(\S+)", text, re.M)
                        stock = ("비상" in use.group(1)) if use else kind.get() == "stock"
                        drafts.append((key, title, text, stock))
                    else:
                        bad.append(f"{os.path.basename(name)}: {problems[0] if problems else '형식 확인'}")
            if not drafts:
                messagebox.showwarning(APP_TITLE, "올릴 수 있는 초안이 없어요.\n" + "\n".join(bad[:8]), parent=win)
                return
            n_stock = sum(d[3] for d in drafts)
            if not messagebox.askyesno(APP_TITLE, f"초안 {len(drafts)}편을 올릴까요? (오늘 글 {len(drafts) - n_stock} · 비상용 {n_stock})"
                                       + ("\n\n못 올리는 것:\n" + "\n".join(bad[:8]) if bad else ""), parent=win):
                return
            msg.config(text=f"올리는 중… 0/{len(drafts)}", fg="#555")

            def work():
                now = datetime.datetime.now()
                for i, (key, title, text, stock) in enumerate(drafts, 1):
                    folder = "stock" if stock else now.strftime("%Y-%m-%d")
                    gh_put_file(f"drafts/{folder}/{key}-chat-{now:%H%M%S}-{i:02d}.txt", text + "\n", f"초안 파일 올리기: {title[:40]}")
                    self.root.after(0, lambda i=i: msg.config(text=f"올리는 중… {i}/{len(drafts)}"))
                gh_dispatch("", BLOG_WORKFLOW, {"mode": "초안 정리", "blog": "", "count": "0"})

            def done(_r, err):
                if err:
                    msg.config(text=f"⚠ 올리다 멈췄어요: {err}", fg="#c0392b")
                    return
                msg.config(fg="#1e7e34", text=f"✓ {len(drafts)}편 올리고 서버 작업을 시작했어요. 몇 분 뒤 목록에 나와요."
                                              + (f" (못 올린 것 {len(bad)}개)" if bad else ""))
                self.root.after(20000, self.refresh)

            in_thread(self.root, work, done)

        btns = tk.Frame(win)
        btns.pack(fill="x", padx=10, pady=(4, 10))
        tk.Button(btns, text="⬆ 서버로 올리기", bg="#2563EB", fg="white", height=2, command=send) \
            .pack(side="left", fill="x", expand=True)
        tk.Button(btns, text="📂 파일로 올리기 (여러 개)", height=2, command=send_files).pack(side="left", padx=(6, 0))

    def run(self):
        if not (os.getenv("GITHUB_TOKEN") or "").strip():
            if messagebox.askyesno(APP_TITLE, "버튼으로 서버를 실행하려면 깃허브 키가 필요해요.\n"
                                              "(설정 → 계정·키 → 깃허브 키)\n\n"
                                              "지금은 깃허브 화면을 열어 직접 실행할까요?"):
                webbrowser.open(f"https://github.com/{repo()}/actions/workflows/{BLOG_WORKFLOW}")
            return
        blog, count = self.blog.get(), self.count.get().strip()
        if not count.isdigit() or not 1 <= int(count) <= 3:
            messagebox.showwarning(APP_TITLE, "편수는 1~3 사이 숫자로 적어 주세요.")
            return
        where = "블로그 4곳" if blog == "전체" else f"'{blog}'"
        if not messagebox.askyesno(APP_TITLE, f"{where}에 {count}편씩 지금 글을 쓸까요?\n"
                                              "(서버에서 몇 분 걸려요. 발행은 하지 않아요)"):
            return
        self.status.config(text="요청 중…")

        def done(_r, err):
            if err:
                self.status.config(text=f"⚠ {err}")
                return
            self.status.config(text="✓ 서버에 요청했어요. 5~10분 뒤 새로고침해 보세요.")
            self.root.after(15000, self.refresh)

        in_thread(self.root, lambda: gh_dispatch("", BLOG_WORKFLOW, {"blog": BLOGS[blog], "count": count}), done)


# ---------------------------------------------------------------- 설정 탭
class SettingsTab:
    """'설정' 탭과 '키' 탭. 키 탭(locked)은 처음엔 잠겨 있고 '변경'을 눌러야 고칠 수 있다."""

    def __init__(self, app, frame, tab="설정", locked=False):
        self.app, self.root = app, app.root
        self.tab, self.locked = tab, locked
        self.inputs = []  # 잠글 입력칸
        top = tk.Frame(frame)
        top.pack(fill="x", padx=10, pady=8)
        self.save_btn = tk.Button(top, text="💾 저장", bg="#2563EB", fg="white", width=9, command=self.save)
        self.save_btn.pack(side="left")
        if locked:
            self.lock_btn = tk.Button(top, text="🔓 변경", width=8, command=self.toggle_lock)
            self.lock_btn.pack(side="left", padx=6)
        else:
            tk.Button(top, text="↺ 다시 불러오기", command=self.reload).pack(side="left", padx=6)
        self.status = tk.Label(frame, text="", fg="#555", anchor="w", justify="left", wraplength=260)
        self.status.pack(fill="x", padx=10)

        canvas = tk.Canvas(frame, highlightthickness=0)
        sb = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas)
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        win = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(win, width=e.width))
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True, padx=(10, 0))
        sb.pack(side="right", fill="y")
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-e.delta / 120), "units")
                        if self.app.notebook.select() == str(frame) else None, add="+")

        self.vars = {}
        for group in settings.groups(tab):
            box = tk.LabelFrame(inner, text=group, padx=8, pady=6, font=("", 10, "bold"))
            box.pack(fill="x", pady=6, padx=(0, 8))
            box.columnconfigure(0, weight=1)
            for row, spec in enumerate(s for s in settings.SPEC if s["group"] == group and s["tab"] == tab):
                self.add_field(box, row, spec)
        tk.Label(inner, text="공용 설정은 구글 시트 '_설정' 탭에 저장되어 다음 서버 실행부터 적용돼요. "
                             "PC 설정(사진 폴더, 깃허브 키)은 이 PC에만 저장돼요.",
                 fg="#666", justify="left", wraplength=240).pack(anchor="w", pady=8)
        if locked:
            self.set_locked(True)

    def set_locked(self, on):
        self.locked = on
        for w in self.inputs:
            w.config(state="disabled" if on else "normal")
        self.save_btn.config(state="disabled" if on else "normal")
        self.lock_btn.config(text="🔓 변경" if on else "🔒 잠그기")
        self.status.config(text="잠겨 있어요. 고치려면 '변경'을 누르세요." if on else "고친 뒤 저장을 누르세요.")

    def toggle_lock(self):
        if self.locked and not messagebox.askyesno("키 변경", "키·토큰을 고치면 게시가 멈출 수 있어요.\n변경할까요?"):
            return
        if not self.locked:
            self.fill()  # 저장 안 한 변경은 되돌린다
        self.set_locked(not self.locked)

    def add_field(self, box, row, spec):
        tk.Label(box, text=spec["label"], anchor="w", font=("", 9, "bold")) \
            .grid(row=row * 3, column=0, sticky="w", pady=(6, 0))
        var = tk.StringVar()
        kind = spec["kind"]
        if kind == "bool":
            w = tk.Checkbutton(box, variable=var, onvalue="1", offvalue="0", text="켜기")
        elif kind == "choice":
            w = ttk.Combobox(box, textvariable=var, values=spec["choices"], state="readonly", width=12)
        elif kind == "secret":
            w = tk.Frame(box)
            e = tk.Entry(w, textvariable=var, show="•")
            e.pack(side="left", fill="x", expand=True)
            self.inputs.append(e)
            tk.Button(w, text="보기", command=lambda e=e: e.config(show="" if e.cget("show") else "•")) \
                .pack(side="left", padx=4)
        else:
            w = tk.Entry(box, textvariable=var, width=8 if kind == "int" else 18)
            self.inputs.append(w)
        w.grid(row=row * 3 + 1, column=0, sticky="w" if kind in ("bool", "choice", "int") else "we", padx=(8, 0))
        if spec.get("help"):
            tk.Label(box, text=spec["help"], fg="#888", anchor="w", justify="left", wraplength=220) \
                .grid(row=row * 3 + 2, column=0, sticky="w", padx=8)
        self.vars[spec["key"]] = var

    def fill(self):
        for k, var in self.vars.items():
            var.set(self.app.values.get(k, settings.BY_KEY[k]["default"]) or "")

    def reload(self):
        self.status.config(text="불러오는 중…")
        self.app.load_settings(then=lambda: self.status.config(text="✓ 불러왔어요."))

    def save(self):
        new = {k: v.get().strip() for k, v in self.vars.items()}
        for k in (k for k in self.vars if settings.BY_KEY[k]["kind"] == "times"):
            try:
                settings.post_times(new[k])
            except ValueError:
                messagebox.showwarning("설정", f"'{settings.BY_KEY[k]['label']}'을(를) '07:00 12:00 19:00'처럼 적어 주세요.")
                return
        for k in (k for k in self.vars if settings.BY_KEY[k]["kind"] == "int"):
            if not new[k].isdigit():
                messagebox.showwarning("설정", f"'{settings.BY_KEY[k]['label']}'은(는) 숫자로 적어 주세요.")
                return
        changes = {k: v for k, v in new.items() if v != (self.app.values.get(k) or "")}
        if not changes:
            self.status.config(text="바뀐 내용이 없어요.")
            return
        self.status.config(text="저장 중…")

        def done(_r, err):
            if err:
                messagebox.showerror("설정 저장", f"PC에는 저장했지만 시트 저장에 실패했어요.\n{err}")
                self.status.config(text="⚠ 시트 저장 실패")
                return
            self.app.values.update(changes)
            apply_env(changes)
            self.app.post.show_info()
            self.app.blog.show_info()
            names = ", ".join(settings.BY_KEY[k]["label"] for k in changes)
            self.status.config(text=f"✓ 저장했어요: {names[:60]}")
            if self.tab == "키":
                self.set_locked(True)
                self.status.config(text=f"✓ 저장하고 다시 잠갔어요: {names[:50]}")

        in_thread(self.root, lambda: settings.save(changes), done)


# ---------------------------------------------------------------- 창
def set_icon(root):
    """창·작업 표시줄 아이콘 (exe 안에 묶인 icon.ico, 없으면 기본 아이콘)."""
    import sys
    path = os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))), "icon.ico")
    try:
        root.iconbitmap(default=path)
    except Exception:
        pass


class App:
    def __init__(self, root):
        import helper
        self.root = root
        self.values = {}
        root.title(APP_TITLE)
        set_icon(root)
        # 쿠팡 페이지를 보면서 쓰도록 좁고 낮게, 화면 오른쪽 아래(작업 표시줄 위)에 붙여서 연다
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        width, height = 290, min(640, sh - 120)
        root.geometry(f"{width}x{height}+{sw - width - 16}+{max(sh - height - 90, 0)}")
        root.minsize(270, 400)

        head = tk.Frame(root)
        head.pack(fill="x", padx=10, pady=(6, 0))
        tk.Label(head, text=APP_TITLE, font=("", 11, "bold")).pack(side="left")
        self.topmost = tk.BooleanVar(value=False)
        tk.Checkbutton(head, text="항상 위", variable=self.topmost,
                       command=lambda: root.attributes("-topmost", self.topmost.get())).pack(side="right")
        tk.Button(head, text="🛍 상품 키워드", command=lambda: KeywordWindow(root)).pack(side="right", padx=6)

        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill="both", expand=True, padx=6, pady=6)
        self.reg_frame = tk.Frame(self.notebook)
        frames = {}
        # 탭 글씨를 키운다 (탭이 6개라 좁은 창에 다 들어가게 옆 여백은 줄임)
        ttk.Style(root).configure("TNotebook.Tab", font=("", 11, "bold"), padding=(3, 4))
        for title in ("목록", "게시", "블로그", "설정", "키"):
            frames[title] = tk.Frame(self.notebook)
        self.notebook.add(self.reg_frame, text="등록")
        for title, f in frames.items():
            self.notebook.add(f, text=title)

        self.helper = helper.Helper(root, self.reg_frame)
        self.list = ListTab(self, frames["목록"])
        self.post = PostTab(self, frames["게시"])
        self.blog = BlogTab(self, frames["블로그"])
        self.settings = SettingsTab(self, frames["설정"])
        self.keys = SettingsTab(self, frames["키"], tab="키", locked=True)
        self.notebook.bind("<<NotebookTabChanged>>", self.on_tab)
        self.loaded = set()
        self.load_settings()

    def load_settings(self, then=None):
        def done(vals, err):
            self.values = vals or {s["key"]: s["default"] for s in settings.SPEC}
            apply_env({k: v for k, v in self.values.items() if v})
            self.settings.fill()
            self.keys.fill()
            self.post.show_info()
            self.blog.show_info()
            if then:
                then()
        in_thread(self.root, settings.load, done)

    def on_tab(self, _e):
        cur = self.notebook.index(self.notebook.select())
        if cur == 1 and "list" not in self.loaded:
            self.loaded.add("list")
            self.list.refresh()
        elif cur == 2 and "post" not in self.loaded:
            self.loaded.add("post")
            self.post.refresh()
        elif cur == 3 and "blog" not in self.loaded:
            self.loaded.add("blog")
            self.blog.refresh()


def main():
    root = tk.Tk()
    try:
        App(root)
    except Exception as e:
        root.withdraw()
        messagebox.showerror(APP_TITLE, f"프로그램을 시작하지 못했습니다.\n{e}\n\n"
                                        "이 프로그램이 .env, google-key.json과 같은 폴더에 있는지 확인해 주세요.")
        raise SystemExit(1)
    root.report_callback_exception = lambda *a: messagebox.showerror(APP_TITLE, explain_error(a[1]))
    root.mainloop()


def explain_error(e):
    """자주 나는 오류를 알아듣기 쉬운 말로."""
    import image_tools
    root = image_tools.photo_root()
    drive = root.anchor
    if isinstance(e, OSError) and drive and not os.path.exists(drive):
        return (f"사진 폴더가 있는 {drive.rstrip(chr(92))} 드라이브가 보이지 않아요.\n\n"
                "구글 드라이브 앱(Google Drive)이 꺼져 있거나 로그인이 풀린 것 같아요.\n"
                "구글 드라이브 앱을 켜고, 탐색기에 G 드라이브가 보이면 다시 해 주세요.\n\n"
                f"(사진 폴더: {root})")
    return str(e)


if __name__ == "__main__":
    main()
