# -*- coding: utf-8 -*-
"""쿠팡 자동게시 프로그램 (창 하나에 탭 4개).
  상품 등록 : 캡처 도우미 (링크·사진 캡처 → 시트·사진 폴더에 저장, 메모는 AI가 자동 작성)
  상품 목록 : 등록한 상품, 메모·사진·게시 여부 / 수정·메모 다시 쓰기·삭제
  게시      : 지금 게시·미리보기·토큰 연장 (깃허브 서버 실행), 최근 실행·게시 기록
  설정      : 예약 시각, 채널, 쓰레드 댓글, 메모, 키 등 모든 설정
실행: python app.py  (또는 CoupangAutopost.exe)
"""
import datetime
import os
import threading
import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk

import requests

import settings

APP_TITLE = "쿠팡 자동게시"
WORKFLOW = "post.yml"


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


def gh_dispatch(mode):
    r = requests.post(f"https://api.github.com/repos/{repo()}/actions/workflows/{WORKFLOW}/dispatches",
                      headers=gh_headers(), json={"ref": "main", "inputs": {"mode": mode}}, timeout=30)
    if r.status_code in (401, 403, 404):
        raise RuntimeError(f"깃허브 키를 확인해 주세요 ({r.status_code}). 키에 Actions 쓰기 권한이 있어야 해요.")
    if r.status_code >= 400:
        raise RuntimeError(f"깃허브 실행 요청 실패 ({r.status_code}): {r.text[:200]}")


def gh_runs(n=12):
    r = requests.get(f"https://api.github.com/repos/{repo()}/actions/workflows/{WORKFLOW}/runs",
                     headers=gh_headers(), params={"per_page": n}, timeout=30)
    r.raise_for_status()
    return r.json().get("workflow_runs", [])


def gh_posted():
    r = requests.get(f"https://raw.githubusercontent.com/{repo()}/main/posted.json",
                     params={"t": datetime.datetime.now().timestamp()}, timeout=30)
    return r.json() if r.ok else {}


def kst(iso):
    """깃허브 시간(UTC 'Z') → 한국 시간 'MM/DD HH:MM'."""
    try:
        t = datetime.datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return (t + datetime.timedelta(hours=9)).strftime("%m/%d %H:%M")
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
    COLS = [("name", "상품명", 170), ("cat", "분류", 40), ("memo", "메모", 36), ("photos", "사진", 36),
            ("threads", "쓰레드", 70), ("instagram", "인스타", 70)]

    def __init__(self, app, frame):
        self.app, self.root = app, app.root
        bar = tk.Frame(frame)
        bar.pack(fill="x", padx=10, pady=8)
        tk.Button(bar, text="↻ 새로고침", command=self.refresh).pack(side="left")
        tk.Button(bar, text="✎ 수정", command=self.edit).pack(side="left", padx=4)
        tk.Button(bar, text="✨ 메모 다시", command=self.rememo).pack(side="left")
        tk.Button(bar, text="🗑 삭제", command=self.delete).pack(side="left", padx=4)
        tk.Button(bar, text="📁 폴더", command=self.open_folder).pack(side="right")

        box = tk.Frame(frame)
        box.pack(fill="both", expand=True, padx=10)
        self.tree = ttk.Treeview(box, columns=[c[0] for c in self.COLS], show="headings", selectmode="browse")
        for key, title, w in self.COLS:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=w, anchor="w" if key == "name" else "center", stretch=key == "name")
        sb = ttk.Scrollbar(box, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", lambda e: self.edit())
        self.tree.tag_configure("done", foreground="#888")
        self.tree.tag_configure("nomemo", foreground="#B45309")

        self.detail = tk.Label(frame, text="", anchor="w", justify="left", wraplength=420, fg="#333")
        self.detail.pack(fill="x", padx=10, pady=4)
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.show_detail())
        self.status = tk.Label(frame, text="", anchor="w", fg="#555")
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
            item = {"name": name, "link": link, "memo": memo, "row": n}
            rec = main.get_rec(posted, item)
            folder = helper.photo_folder(name)
            try:
                nphotos = len(image_tools.images_in(folder)) if folder.is_dir() else 0
            except OSError:
                nphotos = 0
            when = {ch: kst(rec[ch]["at"])[:11] if ch in rec else "" for ch in ("threads", "instagram")}
            done = bool(when["threads"] or when["instagram"])
            waiting += not done
            iid = self.tree.insert("", "end", values=(name.split(",")[0], cell("분류") or "—",
                                                      "✓" if memo else "—", nphotos,
                                                      when["threads"] or "대기", when["instagram"] or "대기"),
                                   tags=("done",) if done else (() if memo else ("nomemo",)))
            self.items[iid] = item
        self.status.config(text=f"상품 {len(self.items)}개 · 게시 대기 {waiting}개 · "
                                f"주황색 = 메모 없음(게시 전에 AI가 채움) · 회색 = 게시됨")

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
        if not images:
            messagebox.showinfo("메모 다시 쓰기", "이 상품의 사진 폴더에 캡처가 없습니다.")
            return
        self.status.config(text=f"✨ '{item['name'][:20]}' 메모를 쓰는 중…")

        def work():
            res = memo_ai.write_memo(images, item["name"], item["link"])
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

    def delete(self):
        import helper
        item = self.selected()
        if not item or not messagebox.askyesno(
                "삭제", f"'{item['name']}'을(를) 목록에서 지울까요?\n(사진 폴더는 그대로 둡니다)"):
            return

        def work():
            header, rows = helper.read_rows()
            li = header.index("파트너스링크")
            keep = [r for r in rows if not (len(r) > li and r[li].strip() == item["link"])]
            helper.write_rows(header, keep)

        in_thread(self.root, work, lambda r, e: (self.status.config(text=f"⚠ {e}") if e else self.refresh()))

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
        self.info = tk.Label(frame, text="", anchor="w", justify="left", font=("", 10), wraplength=430)
        self.info.pack(fill="x", padx=12, pady=(12, 6))

        bar = tk.Frame(frame)  # 좁은 창이라 2줄로
        bar.pack(fill="x", padx=10, pady=4)
        tk.Button(bar, text="▶ 지금 게시", bg="#2563EB", fg="white", width=13, height=2,
                  command=lambda: self.run("지금 게시")).grid(row=0, column=0, padx=(0, 6), pady=2)
        tk.Button(bar, text="👁 미리보기", width=13, height=2,
                  command=lambda: self.run("미리보기")).grid(row=0, column=1, pady=2)
        tk.Button(bar, text="✍ 일반 글 게시", width=13, height=2,
                  command=lambda: self.run("일반 글 게시")).grid(row=1, column=0, padx=(0, 6), pady=2)
        tk.Button(bar, text="🔑 토큰 연장", width=13, height=2,
                  command=lambda: self.run("토큰 연장")).grid(row=1, column=1, pady=2)
        tk.Button(bar, text="↻ 새로고침", command=self.refresh).grid(row=0, column=2, sticky="ne", padx=(6, 0))

        links = tk.Frame(frame)
        links.pack(fill="x", padx=10, pady=4)
        for text, url in (("실행 기록 (깃허브)", lambda: f"https://github.com/{repo()}/actions"),
                          ("링크 페이지", lambda: "https://{}.github.io/{}/".format(*repo().split("/"))),
                          ("깃허브 키 만드는 법", None)):
            tk.Button(links, text=text, relief="flat", fg="#2563EB", cursor="hand2",
                      command=(lambda u=url: webbrowser.open(u())) if url else self.key_help).pack(side="left")

        tk.Label(frame, text="최근 서버 실행", anchor="w", font=("", 10, "bold")).pack(fill="x", padx=12, pady=(10, 0))
        self.runs = ttk.Treeview(frame, columns=("at", "what", "result"), show="headings", height=6)
        for k, t, w in (("at", "시각", 90), ("what", "종류", 90), ("result", "결과", 240)):
            self.runs.heading(k, text=t)
            self.runs.column(k, width=w, anchor="w")
        self.runs.pack(fill="x", padx=10)
        self.runs.bind("<Double-1>", self.open_run)
        self.run_urls = {}

        tk.Label(frame, text="최근 게시", anchor="w", font=("", 10, "bold")).pack(fill="x", padx=12, pady=(10, 0))
        self.posts = ttk.Treeview(frame, columns=("at", "name", "where"), show="headings", height=7)
        for k, t, w in (("at", "시각", 90), ("name", "상품", 220), ("where", "채널", 110)):
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
                               + (f"다음 회차: {nxt:%m/%d %H:%M} (서버가 15분마다 확인해서 보통 곧 올라가요)"
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
                                              "(설정 → 계정·키 → 깃허브 키)\n\n"
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
            "7. 이 프로그램 설정 → 계정·키 → 깃허브 키에 붙여넣고 저장"))
        webbrowser.open("https://github.com/settings/personal-access-tokens/new")


# ---------------------------------------------------------------- 설정 탭
class SettingsTab:
    def __init__(self, app, frame):
        self.app, self.root = app, app.root
        top = tk.Frame(frame)
        top.pack(fill="x", padx=10, pady=8)
        tk.Button(top, text="💾 저장", bg="#2563EB", fg="white", width=12, command=self.save).pack(side="left")
        tk.Button(top, text="↺ 다시 불러오기", command=self.reload).pack(side="left", padx=6)
        self.status = tk.Label(top, text="", fg="#555", anchor="w")
        self.status.pack(side="left", fill="x", padx=8)

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
                        if self.app.notebook.select() == str(frame) else None)

        self.vars = {}
        for group in settings.GROUPS:
            box = tk.LabelFrame(inner, text=group, padx=8, pady=6)
            box.pack(fill="x", pady=6, padx=(0, 8))
            box.columnconfigure(0, weight=1)
            for row, spec in enumerate(s for s in settings.SPEC if s["group"] == group):
                self.add_field(box, row, spec)
        if group:
            tk.Label(inner, text="공용 설정은 구글 시트 '_설정' 탭에 저장되어 다음 서버 실행부터 적용돼요.\n"
                                 "PC 설정(사진 폴더, 깃허브 키)은 이 PC에만 저장돼요.",
                     fg="#666", justify="left").pack(anchor="w", pady=8)

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
            tk.Button(w, text="보기", command=lambda e=e: e.config(show="" if e.cget("show") else "•")) \
                .pack(side="left", padx=4)
        else:
            w = tk.Entry(box, textvariable=var, width=8 if kind == "int" else 30)
        w.grid(row=row * 3 + 1, column=0, sticky="w" if kind in ("bool", "choice", "int") else "we", padx=(8, 0))
        if spec.get("help"):
            tk.Label(box, text=spec["help"], fg="#888", anchor="w", justify="left", wraplength=360) \
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
        for k in (s["key"] for s in settings.SPEC if s["kind"] == "times"):
            try:
                settings.post_times(new[k])
            except ValueError:
                messagebox.showwarning("설정", f"'{settings.BY_KEY[k]['label']}'을(를) '07:00 12:00 19:00'처럼 적어 주세요.")
                return
        for k in ("POSTS_PER_RUN", "THREADS_LINK_REPEAT", "THREADS_REPLY_DELAY"):
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
            names = ", ".join(settings.BY_KEY[k]["label"] for k in changes)
            self.status.config(text=f"✓ 저장했어요: {names[:60]}")

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
        # 쿠팡 페이지를 보면서 쓰도록 좁게, 화면 오른쪽에 붙여서 연다
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        width, height = 470, min(860, sh - 80)
        root.geometry(f"{width}x{height}+{sw - width - 16}+0")
        root.minsize(400, 480)

        head = tk.Frame(root)
        head.pack(fill="x", padx=10, pady=(6, 0))
        tk.Label(head, text=APP_TITLE, font=("", 13, "bold")).pack(side="left")
        self.topmost = tk.BooleanVar(value=False)
        tk.Checkbutton(head, text="창 항상 위에", variable=self.topmost,
                       command=lambda: root.attributes("-topmost", self.topmost.get())).pack(side="right")

        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill="both", expand=True, padx=6, pady=6)
        self.reg_frame = tk.Frame(self.notebook)
        frames = {}
        for title in ("상품 목록", "게시", "설정"):
            frames[title] = tk.Frame(self.notebook)
        self.notebook.add(self.reg_frame, text="  상품 등록  ")
        for title, f in frames.items():
            self.notebook.add(f, text=f"  {title}  ")

        self.helper = helper.Helper(root, self.reg_frame)
        self.list = ListTab(self, frames["상품 목록"])
        self.post = PostTab(self, frames["게시"])
        self.settings = SettingsTab(self, frames["설정"])
        self.notebook.bind("<<NotebookTabChanged>>", self.on_tab)
        self.loaded = set()
        self.load_settings()

    def load_settings(self, then=None):
        def done(vals, err):
            self.values = vals or {s["key"]: s["default"] for s in settings.SPEC}
            apply_env({k: v for k, v in self.values.items() if v})
            self.settings.fill()
            self.post.show_info()
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


def main():
    root = tk.Tk()
    try:
        App(root)
    except Exception as e:
        root.withdraw()
        messagebox.showerror(APP_TITLE, f"프로그램을 시작하지 못했습니다.\n{e}\n\n"
                                        "이 프로그램이 .env, google-key.json과 같은 폴더에 있는지 확인해 주세요.")
        raise SystemExit(1)
    root.report_callback_exception = lambda *a: messagebox.showerror(APP_TITLE, str(a[1]))
    root.mainloop()


if __name__ == "__main__":
    main()
