"""小紅書新聞AI - 桌面審批 App（Tkinter）。

執行：python news_app/app.py  或  python run_news.py --app
"""
from __future__ import annotations

import contextlib
import io
import os
import queue
import sys
import threading
import webbrowser
from datetime import datetime
from pathlib import Path

import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

try:
    import ctypes
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:  # noqa: BLE001
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:  # noqa: BLE001
        pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from news_app import account_store, mailwatch, pipeline, prompts, scheduler, store, web  # noqa: E402
from news_app.config import NewsAccount, NewsConfig  # noqa: E402

# exe 模式：一律以「exe 所在資料夾」為專案根目錄，避免 .env / data 寫進
# PyInstaller 的暫存解壓資料夾（關閉 App 後會被刪除，導致設定每次都要重填）
if getattr(sys, "frozen", False):
    PROJECT_ROOT = Path(sys.executable).resolve().parent
else:
    PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_ROOT / ".env"
DB_PATH = PROJECT_ROOT / "data" / "news.db"

# ---------- 設計系統 ----------
ACCENT = "#2563eb"
ACCENT_DARK = "#1d4ed8"
ACCENT_SOFT = "#eff6ff"
BG = "#f4f6f9"
CARD = "#ffffff"
BORDER = "#e2e8f0"
TEXT = "#0f172a"
MUTED = "#64748b"
SIDEBAR_BG = "#0f172a"
SIDEBAR_HOVER = "#1e293b"
SIDEBAR_ACTIVE = "#1e3a5f"
SIDEBAR_TEXT = "#94a3b8"
SUCCESS = "#15803d"
SUCCESS_BG = "#dcfce7"
WARNING = "#b45309"
WARNING_BG = "#fef3c7"
DANGER = "#dc2626"
DANGER_BG = "#fee2e2"
CONSOLE_BG = "#0f1115"
CONSOLE_FG = "#d8dee9"

FONT = ("Segoe UI", 10)
FONT_SMALL = ("Segoe UI", 9)
FONT_TITLE = ("Segoe UI", 18, "bold")
FONT_SUB = ("Segoe UI", 10)
FONT_MONO = ("Consolas", 10)
FONT_BTN = ("Segoe UI", 10, "bold")

ENV_FIELDS = [
    ("SERPER_API_KEY", "Serper API key（新聞搜尋）"),
    ("AI_API_KEY", "OpenRouter API key（AI）"),
    ("NEWS_AI_MODEL", "AI 模型（預設 z-ai/glm-5.2）"),
    ("NEWS_SEARCH_QUERY", "搜尋關鍵字"),
    ("EMAIL_FROM", "寄件人 email"),
    ("EMAIL_TO", "收件人 email（逗號分隔）"),
]

FORM_ENV_FIELDS = [
    ("FORM_PUBLIC_URL", "公開網址（ngrok）"),
    ("FORM_TOKEN", "表單安全碼（必填）"),
]

STATUS_LABELS = {
    pipeline.STATUS_AWAIT_DIRECTION: "等待方向",
    pipeline.STATUS_AWAIT_SCRIPT: "等待腳本",
    pipeline.STATUS_RUNNING: "處理中",
    pipeline.STATUS_DONE: "已完成",
    pipeline.STATUS_FAILED: "失敗",
}
DETAIL_MAX = 3500
LOG_MAX_LINES = 1800


def _truncate(text: str, limit: int = DETAIL_MAX) -> tuple[str, bool]:
    raw = text or ""
    if len(raw) <= limit:
        return raw, False
    return raw[:limit].rstrip() + "\n\n…（已截斷以保持流暢）", True


class _Tee(io.TextIOBase):
    def __init__(self, stream, q: queue.Queue):
        self.stream = stream
        self.q = q

    def write(self, s):
        self.q.put(s)
        try:
            self.stream.write(s)
        except Exception:  # noqa: BLE001
            pass
        return len(s)

    def flush(self):
        try:
            self.stream.flush()
        except Exception:  # noqa: BLE001
            pass


def make_button(parent, text, command, kind="secondary", font=None, padx=16, pady=8):
    """Primary / secondary / danger / ghost. Min ~44px tall via padding."""
    palettes = {
        "primary": ("#ffffff", ACCENT, ACCENT_DARK, "#ffffff", ACCENT),
        "secondary": (TEXT, CARD, "#eef2f7", TEXT, BORDER),
        "danger": ("#ffffff", DANGER, "#b91c1c", "#ffffff", DANGER),
        "ghost": (MUTED, BG, "#e8eaf0", MUTED, BG),
        "success": ("#ffffff", SUCCESS, "#166534", "#ffffff", SUCCESS),
    }
    fg, bg, hover, activefg, border = palettes.get(kind, palettes["secondary"])
    btn = tk.Button(
        parent, text=text, font=font or FONT_BTN if kind in ("primary", "success") else FONT,
        fg=fg, bg=bg, activebackground=hover, activeforeground=activefg,
        relief="flat", bd=0, cursor="hand2", padx=padx, pady=pady,
        highlightthickness=1, highlightbackground=border, command=command,
        disabledforeground="#94a3b8",
    )

    def on_enter(_e, b=btn, h=hover):
        if str(b["state"]) != "disabled":
            b.configure(bg=h)

    def on_leave(_e, b=btn, c=bg):
        if str(b["state"]) != "disabled":
            b.configure(bg=c)

    btn.bind("<Enter>", on_enter)
    btn.bind("<Leave>", on_leave)
    btn._rest_bg = bg  # type: ignore[attr-defined]
    return btn


def status_pill(parent, text, tone="muted"):
    colors = {
        "ok": (SUCCESS, SUCCESS_BG),
        "wait": (WARNING, WARNING_BG),
        "fail": (DANGER, DANGER_BG),
        "run": (ACCENT, ACCENT_SOFT),
        "muted": (MUTED, "#eef2f7"),
    }
    fg, bg = colors.get(tone, colors["muted"])
    return tk.Label(parent, text=text, font=("Segoe UI", 9, "bold"),
                    fg=fg, bg=bg, padx=10, pady=4)


class NewsApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("小紅書新聞AI")
        dpi = self.winfo_fpixels("1i") / 96.0
        self.geometry(f"{int(1180 * dpi)}x{int(740 * dpi)}")
        self.minsize(960, 600)
        self.configure(bg=BG)

        self.cfg = NewsConfig.load()
        self.conn = store.connect(self.cfg.db_path)
        self.log_q: queue.Queue = queue.Queue()
        self.current_run_id: int | None = None
        self.current_page = "approve"
        self._busy = False
        self._choice: str | None = None
        self._pending_items: list[dict] = []
        self._accounts_by_name: dict = {}
        self._detail_full = ""
        self._option_cards: dict[str, tk.Frame] = {}
        self._rendered_sig: str | None = None
        self.pages: dict[str, tk.Frame] = {}
        self.nav_bars: dict[str, tk.Frame] = {}
        self.nav_buttons: dict[str, tk.Button] = {}

        if self.cfg.web_enabled:
            try:
                self.web_server, self.web_thread = web.start_server(self.cfg)
            except OSError as e:
                print(f"[form] 表單伺服器啟動失敗（可能已啟動）：{e}")
        if self.cfg.mail_watch_enabled:
            try:
                self.mail_thread = mailwatch.start_watcher(
                    self.cfg, interval=self.cfg.mail_watch_interval)
            except Exception as e:  # noqa: BLE001
                print(f"[mailwatch] 啟動失敗：{e}")

        self._setup_style()
        self._build_sidebar()
        self._build_content()
        self._build_status_bar()
        self._build_approve_page()
        self._build_run_page()
        self._build_accounts_page()
        self._build_schedule_page()
        self._build_settings_page()
        self._build_log_page()

        self.refresh_runs()
        self.refresh_pending()
        self.refresh_accounts()
        self._show_page("approve")
        self._select_first_pending()
        self._poll_queue()
        self.after(8000, self._periodic_refresh)
        self.bind("<Key>", self._on_hotkey)

    def _setup_style(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "App.Treeview", background=CARD, fieldbackground=CARD, foreground=TEXT,
            rowheight=30, font=FONT, borderwidth=0,
        )
        style.configure(
            "App.Treeview.Heading", font=("Segoe UI", 9, "bold"),
            background="#f1f5f9", foreground=MUTED, relief="flat", padding=(6, 8),
        )
        style.map(
            "App.Treeview",
            background=[("selected", ACCENT_SOFT)],
            foreground=[("selected", TEXT)],
        )
        style.configure("App.TCombobox", padding=4)

    # ---------------- 版面架構 ----------------
    def _build_sidebar(self):
        self.sidebar = tk.Frame(self, bg=SIDEBAR_BG, width=196)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        brand = tk.Frame(self.sidebar, bg=SIDEBAR_BG)
        brand.pack(fill="x", pady=(22, 8))
        tk.Label(brand, text="新聞審批", font=("Segoe UI", 16, "bold"),
                 fg="#ffffff", bg=SIDEBAR_BG).pack(anchor="w", padx=20)
        tk.Label(brand, text="FOSHAN NEWS AI", font=("Segoe UI", 8, "bold"),
                 fg=ACCENT, bg=SIDEBAR_BG).pack(anchor="w", padx=20, pady=(2, 0))
        tk.Frame(self.sidebar, bg="#1e293b", height=1).pack(fill="x", padx=16, pady=14)

        nav = [
            ("approve", "審批"),
            ("runs", "執行紀錄"),
            ("accounts", "帳號"),
            ("schedule", "排程"),
            ("settings", "設定"),
            ("log", "日誌"),
        ]
        for key, label in nav:
            item = tk.Frame(self.sidebar, bg=SIDEBAR_BG)
            item.pack(fill="x", pady=1)
            bar = tk.Frame(item, bg=SIDEBAR_BG, width=3)
            bar.pack(side="left", fill="y")
            row = tk.Frame(item, bg=SIDEBAR_BG)
            row.pack(side="left", fill="x", expand=True)
            btn = tk.Button(
                row, text=f"  {label}", font=("Segoe UI", 11), fg=SIDEBAR_TEXT,
                bg=SIDEBAR_BG, activebackground=SIDEBAR_HOVER, activeforeground="#ffffff",
                relief="flat", bd=0, cursor="hand2", anchor="w", padx=14, pady=11,
                command=lambda k=key: self._show_page(k),
            )
            btn.pack(side="left", fill="x", expand=True)
            self.nav_bars[key] = bar
            self.nav_buttons[key] = btn
            btn.bind("<Enter>", lambda e, b=btn, k=key: self._nav_hover(b, k, True))
            btn.bind("<Leave>", lambda e, b=btn, k=key: self._nav_hover(b, k, False))
            if key == "approve":
                self.nav_badge = tk.Label(
                    row, text="", font=("Segoe UI", 8, "bold"),
                    fg="#ffffff", bg=DANGER, padx=6, pady=1,
                )

        tk.Label(self.sidebar, text="點方案卡片即可選擇", font=FONT_SMALL,
                 fg="#475569", bg=SIDEBAR_BG).pack(side="bottom", pady=12)

    def _nav_hover(self, btn, key, entering):
        if self.current_page == key:
            return
        btn.configure(bg=SIDEBAR_HOVER if entering else SIDEBAR_BG)

    def _build_content(self):
        self.content = tk.Frame(self, bg=BG)
        self.content.pack(side="left", fill="both", expand=True)

    def _build_status_bar(self):
        bar = tk.Frame(self, bg="#eef2f7", highlightthickness=1, highlightbackground=BORDER)
        bar.pack(side="bottom", fill="x")
        self.status_dot = tk.Label(bar, text="●", fg=SUCCESS, bg="#eef2f7", font=FONT_SMALL)
        self.status_dot.pack(side="left", padx=(12, 4), pady=6)
        self.status_lbl = tk.Label(bar, text="就緒", bg="#eef2f7", fg=MUTED, font=FONT_SMALL)
        self.status_lbl.pack(side="left")
        self.status_hint = tk.Label(bar, text="", bg="#eef2f7", fg=MUTED, font=FONT_SMALL)
        self.status_hint.pack(side="right", padx=12)

    def _show_page(self, key):
        self.current_page = key
        for k, page in self.pages.items():
            page.pack_forget()
        self.pages[key].pack(fill="both", expand=True, padx=22, pady=16)
        for k, bar in self.nav_bars.items():
            active = k == key
            bar.configure(bg=ACCENT if active else SIDEBAR_BG)
            self.nav_buttons[k].configure(
                bg=SIDEBAR_ACTIVE if active else SIDEBAR_BG,
                fg="#ffffff" if active else SIDEBAR_TEXT,
            )
        if key == "runs":
            self.refresh_runs()
        elif key == "approve":
            self.refresh_pending()

    def page_header(self, parent, title, subtitle):
        head = tk.Frame(parent, bg=BG)
        head.pack(fill="x")
        left = tk.Frame(head, bg=BG)
        left.pack(side="left", fill="x", expand=True)
        tk.Label(left, text=title, font=FONT_TITLE, fg=TEXT, bg=BG).pack(anchor="w")
        tk.Label(left, text=subtitle, font=FONT_SUB, fg=MUTED, bg=BG).pack(anchor="w", pady=(2, 0))
        actions = tk.Frame(head, bg=BG)
        actions.pack(side="right")
        tk.Frame(parent, bg=ACCENT, height=2).pack(fill="x", pady=(10, 14))
        return actions

    def card(self, parent, padding=16, fill="x", expand=False):
        c = tk.Frame(parent, bg=CARD, highlightthickness=1, highlightbackground=BORDER)
        c.pack(fill=fill, expand=expand, pady=(0, 12))
        inner = tk.Frame(c, bg=CARD)
        inner.pack(fill="both", expand=True, padx=padding, pady=padding)
        return inner

    def _scrollable(self, parent, bg=BG):
        wrap = tk.Frame(parent, bg=bg)
        canvas = tk.Canvas(wrap, bg=bg, highlightthickness=0)
        sb = ttk.Scrollbar(wrap, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg=bg)
        win = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _sync(_e=None):
            canvas.configure(scrollregion=canvas.bbox("all"))
            width = canvas.winfo_width()
            if width > 1:
                canvas.itemconfigure(win, width=width)

        inner.bind("<Configure>", _sync)
        canvas.bind("<Configure>", _sync)
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        def on_wheel(e):
            canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")

        def bind_wheel(_e):
            canvas.bind_all("<MouseWheel>", on_wheel)

        def unbind_wheel(_e):
            canvas.unbind_all("<MouseWheel>")

        canvas.bind("<Enter>", bind_wheel)
        canvas.bind("<Leave>", unbind_wheel)
        inner.bind("<Enter>", bind_wheel)
        return wrap, inner, canvas

    # ---------------- 審批頁（主畫面） ----------------
    def _build_approve_page(self):
        page = tk.Frame(self.content, bg=BG)
        self.pages["approve"] = page
        actions = self.page_header(page, "審批", "點選方案卡片，再按批准。拒絕時請填寫修改意見。")
        self.btn_run_approve = make_button(actions, "立即執行新一輪", self.start_new_run, kind="primary")
        self.btn_run_approve.pack(side="left", padx=(0, 8))
        make_button(actions, "重新整理", self.refresh_pending, kind="secondary").pack(side="left")

        body = tk.Frame(page, bg=BG)
        body.pack(fill="both", expand=True)

        queue_card = tk.Frame(body, bg=CARD, highlightthickness=1, highlightbackground=BORDER, width=240)
        queue_card.pack(side="left", fill="y", padx=(0, 12))
        queue_card.pack_propagate(False)
        q_head = tk.Frame(queue_card, bg=CARD)
        q_head.pack(fill="x", padx=14, pady=(12, 6))
        tk.Label(q_head, text="待處理", font=("Segoe UI", 11, "bold"), fg=TEXT, bg=CARD).pack(side="left")
        self.queue_count = tk.Label(q_head, text="0", font=("Segoe UI", 9, "bold"),
                                    fg=MUTED, bg="#eef2f7", padx=8, pady=1)
        self.queue_count.pack(side="right")
        q_wrap, self.pending_list, _ = self._scrollable(queue_card, bg=CARD)
        q_wrap.pack(fill="both", expand=True, padx=8, pady=(0, 10))

        right = tk.Frame(body, bg=BG)
        right.pack(side="left", fill="both", expand=True)

        self.approve_banner = tk.Frame(right, bg=ACCENT_SOFT, highlightthickness=1, highlightbackground="#bfdbfe")
        self.approve_banner.pack(fill="x", pady=(0, 10))
        banner_in = tk.Frame(self.approve_banner, bg=ACCENT_SOFT)
        banner_in.pack(fill="x", padx=14, pady=10)
        self.approve_hint = tk.Label(banner_in, text="選擇左邊一筆等待審批的執行",
                                     bg=ACCENT_SOFT, fg=TEXT, font=FONT, wraplength=640, justify="left")
        self.approve_hint.pack(anchor="w")

        workspace, self.approve_inner, self.approve_canvas = self._scrollable(right, bg=BG)
        workspace.pack(fill="both", expand=True)

        footer = tk.Frame(right, bg=CARD, highlightthickness=1, highlightbackground=BORDER)
        footer.pack(fill="x", pady=(10, 0))
        fin = tk.Frame(footer, bg=CARD)
        fin.pack(fill="x", padx=14, pady=12)
        tk.Label(fin, text="修改意見（拒絕時填寫）", bg=CARD, fg=MUTED, font=FONT_SMALL).pack(anchor="w")
        self.comment_var = tk.StringVar()
        self.comment_entry = tk.Entry(
            fin, textvariable=self.comment_var, font=FONT, relief="flat", bg="#f8fafc",
            highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT,
        )
        self.comment_entry.pack(fill="x", ipady=7, pady=(4, 10))
        btnrow = tk.Frame(fin, bg=CARD)
        btnrow.pack(fill="x")
        self.btn_reject = make_button(btnrow, "拒絕並重做", lambda: self.approve("reject"), kind="danger")
        self.btn_reject.pack(side="left")
        self.btn_approve = make_button(btnrow, "批准所選方案", self._approve_selected, kind="success", padx=20)
        self.btn_approve.pack(side="right")
        self.choice_lbl = tk.Label(btnrow, text="尚未選擇方案", bg=CARD, fg=MUTED, font=FONT_SMALL)
        self.choice_lbl.pack(side="right", padx=12)

    def _approve_selected(self):
        if not self._choice:
            messagebox.showinfo("提示", "請先點選一個方案卡片，再按批准。")
            return
        self.approve(self._choice)

    def _on_hotkey(self, event):
        if self.current_page != "approve" or self._busy:
            return
        if event.widget == self.comment_entry:
            return
        if event.char in self._option_cards:
            self._select_choice(event.char)

    def _select_choice(self, decision: str):
        self._choice = decision
        for key, card in self._option_cards.items():
            on = key == decision
            card.configure(highlightbackground=ACCENT if on else BORDER,
                           highlightthickness=2 if on else 1,
                           bg=ACCENT_SOFT if on else CARD)
            for child in card.winfo_children():
                try:
                    child.configure(bg=ACCENT_SOFT if on else CARD)
                except tk.TclError:
                    pass
                for g in child.winfo_children():
                    try:
                        if g.winfo_class() != "Text":
                            g.configure(bg=ACCENT_SOFT if on else CARD)
                    except tk.TclError:
                        pass
        labels = {"reject": "將拒絕全部"}
        if decision in self._option_cards and decision != "reject":
            self.choice_lbl.config(text=f"已選方案 {decision}  ·  快捷鍵 1 / 2 / 3", fg=SUCCESS)
        else:
            self.choice_lbl.config(text=labels.get(decision, "尚未選擇方案"), fg=MUTED)

    def refresh_pending(self, keep_selection: int | None = None):
        try:
            pending = []
            for st, label in ((pipeline.STATUS_AWAIT_DIRECTION, "方向審批"),
                              (pipeline.STATUS_AWAIT_SCRIPT, "腳本審批")):
                for r in store.pending_runs(self.conn, st):
                    item = dict(r)
                    item["_wait"] = label
                    pending.append(item)
            self._pending_items = pending
            selected = keep_selection if keep_selection is not None else self.current_run_id
            self._render_pending_queue(selected)
            n = len(pending)
            self.queue_count.config(text=str(n), fg="#ffffff" if n else MUTED,
                                    bg=DANGER if n else "#eef2f7")
            if n:
                self.nav_badge.config(text=str(n))
                self.nav_badge.pack(side="right", padx=(0, 12))
            else:
                self.nav_badge.pack_forget()
            if not pending:
                self._render_empty_approve()
        except Exception as e:  # noqa: BLE001
            self.approve_hint.config(text=f"讀取失敗：{e}")

    def _approval_sig(self, run) -> str:
        """目前 run 的審批內容指紋：狀態/重試/方向或版本有變就回傳不同值。"""
        parts = [run.get("status"), run.get("retry_direction"), run.get("retry_script")]
        rid = run["id"]
        if run.get("status") == pipeline.STATUS_AWAIT_DIRECTION:
            parts.append([(d["idx"], d["title"]) for d in store.get_directions(self.conn, rid)])
        elif run.get("status") == pipeline.STATUS_AWAIT_SCRIPT:
            parts.append([(v["idx"], v["style"], len(v["content"]))
                          for v in store.get_versions(self.conn, rid)])
        return repr(parts)

    def _render_pending_queue(self, selected_id):
        for child in self.pending_list.winfo_children():
            child.destroy()
        if not self._pending_items:
            tk.Label(self.pending_list, text="目前沒有待審批項目",
                     bg=CARD, fg=MUTED, font=FONT_SMALL, wraplength=200,
                     justify="left").pack(anchor="w", padx=8, pady=12)
            return
        for r in self._pending_items:
            rid = int(r["id"])
            on = selected_id == rid
            row = tk.Frame(self.pending_list, bg=ACCENT_SOFT if on else CARD,
                           highlightthickness=1,
                           highlightbackground=ACCENT if on else BORDER,
                           cursor="hand2")
            row.pack(fill="x", pady=4, padx=2)
            bar = tk.Frame(row, bg=ACCENT if on else CARD, width=3)
            bar.pack(side="left", fill="y")
            inner = tk.Frame(row, bg=ACCENT_SOFT if on else CARD)
            inner.pack(fill="x", padx=8, pady=8)
            tk.Label(inner, text=f"#{rid}  {r.get('account') or 'default'}",
                     bg=inner["bg"], fg=TEXT, font=("Segoe UI", 10, "bold"),
                     anchor="w").pack(fill="x")
            tk.Label(inner, text=f"{r['_wait']}  ·  {r.get('run_date') or ''}",
                     bg=inner["bg"], fg=MUTED, font=FONT_SMALL, anchor="w").pack(fill="x")

            def bind_all(w, rid=rid):
                w.bind("<Button-1>", lambda _e, i=rid: self._open_pending(i))
                for c in w.winfo_children():
                    bind_all(c, rid)

            bind_all(row)

    def _open_pending(self, run_id: int):
        if self._busy:
            return
        self.current_run_id = run_id
        self._choice = None
        self._render_pending_queue(run_id)
        self._render_approve_workspace(run_id)

    def _select_first_pending(self):
        if self._pending_items:
            self._open_pending(int(self._pending_items[0]["id"]))
        else:
            self._render_empty_approve()

    def _clear_approve_inner(self):
        for child in self.approve_inner.winfo_children():
            child.destroy()
        self._option_cards = {}
        self._choice = None
        self.choice_lbl.config(text="尚未選擇方案", fg=MUTED)

    def _render_empty_approve(self):
        self._clear_approve_inner()
        self.approve_hint.config(text="目前沒有等待審批的內容。執行新一輪後，方案會出現在這裡。")
        box = tk.Frame(self.approve_inner, bg=CARD, highlightthickness=1, highlightbackground=BORDER)
        box.pack(fill="x", pady=8)
        inner = tk.Frame(box, bg=CARD)
        inner.pack(padx=24, pady=32)
        tk.Label(inner, text="沒有待審批項目", font=("Segoe UI", 14, "bold"),
                 bg=CARD, fg=TEXT).pack()
        tk.Label(inner, text="按右上角「立即執行新一輪」，AI 會搜尋新聞並產出 3 個方向供你選擇。",
                 bg=CARD, fg=MUTED, font=FONT, wraplength=480, justify="center").pack(pady=(8, 14))
        make_button(inner, "立即執行新一輪", self.start_new_run, kind="primary").pack()

    def _render_approve_workspace(self, run_id: int):
        self._clear_approve_inner()
        r = store.get_run(self.conn, run_id)
        if not r:
            self.approve_hint.config(text="找不到這筆執行")
            return
        status = r["status"]
        acct = r.get("account") or "default"
        if status == pipeline.STATUS_AWAIT_DIRECTION:
            self.approve_hint.config(
                text=f"方向審批  ·  #{r['id']}  {acct}  {r['run_date']}    點卡片選擇方向，再按「批准所選方案」"
            )
            summary = (r.get("news_summary") or "").strip()
            if summary:
                self._section_label("新聞全景摘要")
                self._static_text(summary, height=5)
            directions = store.get_directions(self.conn, run_id)
            self._section_label("選擇一個方向")
            for d in directions:
                idx = str(d["idx"])
                src_lines = []
                for s in d.get("sources") or []:
                    src_lines.append((s.get("title") or s.get("url") or "", s.get("url") or ""))
                self._option_card(
                    idx,
                    f"方向 {idx}  ·  {d.get('title') or ''}",
                    d.get("description") or "",
                    sources=src_lines,
                )
            if not directions:
                tk.Label(self.approve_inner, text="尚未產生方向，請稍候或查看日誌。",
                         bg=BG, fg=MUTED).pack(anchor="w", pady=8)
        elif status == pipeline.STATUS_AWAIT_SCRIPT:
            self.approve_hint.config(
                text=f"腳本審批  ·  #{r['id']}  {acct}  {r['run_date']}    點卡片選擇要發布的版本"
            )
            self._section_label("選擇一個腳本版本")
            for v in store.get_versions(self.conn, run_id):
                idx = str(v["idx"])
                self._option_card(idx, f"版本 {idx}  ·  {v.get('style') or '未命名樣式'}",
                                  v.get("content") or "", is_script=True)
        else:
            self.approve_hint.config(text=f"#{r['id']} 目前是「{STATUS_LABELS.get(status, status)}」，不需審批")
            self._static_text(f"此筆狀態：{STATUS_LABELS.get(status, status)}\n可到「執行紀錄」查看明細。", height=4)
        self._rendered_sig = self._approval_sig(r)

    def _section_label(self, text):
        tk.Label(self.approve_inner, text=text, font=("Segoe UI", 11, "bold"),
                 bg=BG, fg=TEXT).pack(anchor="w", pady=(8, 6))

    def _static_text(self, text, height=6):
        box = tk.Frame(self.approve_inner, bg=CARD, highlightthickness=1, highlightbackground=BORDER)
        box.pack(fill="x", pady=(0, 8))
        t = tk.Text(box, wrap="word", font=FONT, bg=CARD, fg=TEXT, relief="flat",
                    height=height, padx=12, pady=10, highlightthickness=0)
        shown, _ = _truncate(text, 1800)
        t.insert("1.0", shown)
        t.configure(state="disabled")
        t.pack(fill="x")

    def _option_card(self, idx: str, title: str, body: str, sources=None, is_script=False):
        card = tk.Frame(self.approve_inner, bg=CARD, highlightthickness=1,
                        highlightbackground=BORDER, cursor="hand2")
        card.pack(fill="x", pady=(0, 10))
        inner = tk.Frame(card, bg=CARD)
        inner.pack(fill="x", padx=14, pady=12)
        head = tk.Frame(inner, bg=CARD)
        head.pack(fill="x")
        tk.Label(head, text=f"{idx}", font=("Segoe UI", 11, "bold"), fg=ACCENT, bg=CARD,
                 width=2).pack(side="left")
        tk.Label(head, text=title, font=("Segoe UI", 11, "bold"), fg=TEXT, bg=CARD,
                 wraplength=560, justify="left", anchor="w").pack(side="left", fill="x", expand=True)
        tk.Label(head, text="點此選擇", font=FONT_SMALL, fg=MUTED, bg=CARD).pack(side="right")

        if is_script:
            t = tk.Text(inner, wrap="word", font=FONT, bg="#f8fafc", fg=TEXT, relief="flat",
                        height=10, padx=10, pady=8, highlightthickness=1, highlightbackground=BORDER)
            shown, clipped = _truncate(body, 2200)
            t.insert("1.0", shown)
            t.configure(state="disabled")
            t.pack(fill="x", pady=(8, 0))
            if clipped:
                tk.Label(inner, text="內容較長，已先顯示前段", bg=CARD, fg=MUTED,
                         font=FONT_SMALL).pack(anchor="w", pady=(4, 0))
        elif body:
            tk.Label(inner, text=body, font=FONT, fg=TEXT, bg=CARD, wraplength=620,
                     justify="left", anchor="w").pack(fill="x", pady=(8, 0))

        if sources:
            src_box = tk.Frame(inner, bg=CARD)
            src_box.pack(fill="x", pady=(8, 0))
            for title_s, url in sources[:4]:
                def open_src(_e=None, u=url):
                    if u:
                        webbrowser.open(u)
                link = tk.Label(src_box, text=f"來源  {title_s}", fg=ACCENT, bg=CARD,
                                font=FONT_SMALL, cursor="hand2", anchor="w", wraplength=600)
                link.pack(fill="x")
                link.bind("<Button-1>", open_src)

        def pick(_e=None, i=idx):
            self._select_choice(i)

        def bind_pick(w):
            if w.winfo_class() == "Text":
                w.bind("<Button-1>", pick)
                return
            w.bind("<Button-1>", pick)
            for c in w.winfo_children():
                bind_pick(c)

        bind_pick(card)
        self._option_cards[idx] = card

    # ---------------- 執行紀錄 ----------------
    def _build_run_page(self):
        page = tk.Frame(self.content, bg=BG)
        self.pages["runs"] = page
        actions = self.page_header(page, "執行紀錄", "最近的產出路徑。點一列即可在下方預覽，不必一次載入全部長文。")
        self.btn_run_main = make_button(actions, "立即執行新一輪", self.start_new_run, kind="primary")
        self.btn_run_main.pack(side="left", padx=(0, 8))
        make_button(actions, "重新整理", self.refresh_runs, kind="secondary").pack(side="left")
        self.run_status_lbl = tk.Label(actions, text="", bg=BG, fg=MUTED, font=FONT_SMALL)
        self.run_status_lbl.pack(side="left", padx=12)

        tree_card = self.card(page, padding=8)
        cols = ("id", "acct", "date", "status", "count", "style", "error")
        self.tree = ttk.Treeview(tree_card, columns=cols, show="headings", height=12, style="App.Treeview")
        widths = {"id": 48, "acct": 110, "date": 100, "status": 100, "count": 56, "style": 110, "error": 280}
        heads = {"id": "#", "acct": "帳號", "date": "日期", "status": "狀態",
                 "count": "文章", "style": "定稿樣式", "error": "錯誤"}
        for c in cols:
            self.tree.heading(c, text=heads[c])
            self.tree.column(c, width=widths[c],
                             anchor="w" if c in ("acct", "style", "error") else "center")
        vsb = ttk.Scrollbar(tree_card, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self.tree.tag_configure("wait", foreground=WARNING)
        self.tree.tag_configure("ok", foreground=SUCCESS)
        self.tree.tag_configure("fail", foreground=DANGER)
        self.tree.tag_configure("run", foreground=ACCENT)

        preview = self.card(page, padding=10, fill="both", expand=True)
        phead = tk.Frame(preview, bg=CARD)
        phead.pack(fill="x")
        tk.Label(phead, text="預覽", bg=CARD, fg=TEXT, font=("Segoe UI", 11, "bold")).pack(side="left")
        self.detail_more_btn = make_button(phead, "顯示完整內容", self._show_full_detail, kind="ghost", pady=4)
        self.detail_more_btn.pack(side="right")
        self.detail_more_btn.pack_forget()
        self.detail = tk.Text(preview, wrap="word", font=FONT_MONO, bg="#f8fafc", fg=TEXT,
                              relief="flat", height=12, padx=8, pady=8,
                              highlightthickness=1, highlightbackground=BORDER)
        self.detail.pack(fill="both", expand=True, pady=(8, 0))
        self.detail.configure(state="disabled")

    def _on_tree_select(self, _evt):
        sel = self.tree.selection()
        if not sel:
            return
        self.current_run_id = int(sel[0])
        self.show_run_detail(self.current_run_id)

    def show_run_detail(self, run_id: int):
        r = store.get_run(self.conn, run_id)
        if not r:
            return
        lines = [
            f"#{r['id']}  {r.get('account') or 'default'}  {r['run_date']}  [{STATUS_LABELS.get(r['status'], r['status'])}]",
            f"文章 {r['articles_count']}  ·  方向重試 {r['retry_direction']}  ·  腳本重試 {r['retry_script']}",
            f"開始 {r['started_at']}  ·  更新 {r['updated_at']}",
        ]
        if r.get("news_summary"):
            lines.append(f"\n新聞摘要\n{r['news_summary']}")
        for d in store.get_directions(self.conn, run_id):
            lines.append(f"\n方向 {d['idx']}: {d['title']}\n  {d['description']}")
            for s in d.get("sources") or []:
                lines.append(f"    - {s.get('title')}  {s.get('url')}")
        if r.get("analysis"):
            lines.append(f"\n===== 深度分析 =====\n{r['analysis']}")
        for v in store.get_versions(self.conn, run_id):
            lines.append(f"\n--- 版本 {v['idx']}（{v['style']}）---\n{v['content']}")
        if r.get("tagline"):
            lines.append(f"\nTagline: {r['tagline']}\nImage Prompt: {r['image_prompt']}")
        if r.get("error"):
            lines.append(f"\n錯誤：{r['error']}")
        lines.append("\n===== 事件 =====")
        for e in store.run_events(self.conn, run_id):
            lines.append(f"[{e['at']}] {e['message']}")
        self._detail_full = "\n".join(lines)
        shown, clipped = _truncate(self._detail_full)
        self._set_detail(shown)
        if clipped:
            self.detail_more_btn.pack(side="right")
        else:
            self.detail_more_btn.pack_forget()

    def _set_detail(self, text: str):
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        self.detail.insert("1.0", text)
        self.detail.configure(state="disabled")

    def _show_full_detail(self):
        if self._detail_full:
            self._set_detail(self._detail_full)
            self.detail_more_btn.pack_forget()

    def refresh_runs(self):
        try:
            for row in self.tree.get_children():
                self.tree.delete(row)
            for r in store.list_runs(self.conn):
                st = r["status"]
                tag = "run"
                if st in (pipeline.STATUS_AWAIT_DIRECTION, pipeline.STATUS_AWAIT_SCRIPT):
                    tag = "wait"
                elif st == pipeline.STATUS_DONE:
                    tag = "ok"
                elif st == pipeline.STATUS_FAILED:
                    tag = "fail"
                self.tree.insert("", "end", iid=str(r["id"]), tags=(tag,), values=(
                    r["id"], r["account"], r["run_date"],
                    STATUS_LABELS.get(st, st), r["articles_count"],
                    r["style"] or "", r["error"] or "",
                ))
        except Exception as e:  # noqa: BLE001
            self.run_status_lbl.config(text=f"讀取失敗：{e}")

    # ---------------- 帳號 ----------------
    def _build_accounts_page(self):
        page = tk.Frame(self.content, bg=BG)
        self.pages["accounts"] = page
        actions = self.page_header(page, "帳號", "每個帳號獨立搜尋與語氣。儲存後下一輪立即生效，不必改檔案。")
        make_button(actions, "新增帳號", self.new_account, kind="primary").pack(side="left")

        body = tk.Frame(page, bg=BG)
        body.pack(fill="both", expand=True)

        left = tk.Frame(body, bg=CARD, highlightthickness=1, highlightbackground=BORDER, width=280)
        left.pack(side="left", fill="y", padx=(0, 12))
        left.pack_propagate(False)
        tk.Label(left, text="帳號清單", bg=CARD, fg=TEXT, font=("Segoe UI", 11, "bold")).pack(
            anchor="w", padx=14, pady=(12, 6))
        cols = ("name", "enabled", "place")
        self.acc_tree = ttk.Treeview(left, columns=cols, show="headings", height=16, style="App.Treeview")
        for c, h, w in (("name", "帳號", 140), ("enabled", "狀態", 56), ("place", "地區", 60)):
            self.acc_tree.heading(c, text=h)
            self.acc_tree.column(c, width=w, anchor="w" if c == "name" else "center")
        self.acc_tree.pack(fill="both", expand=True, padx=10, pady=(0, 8))
        self.acc_tree.bind("<<TreeviewSelect>>", self._on_account_select)
        lbtns = tk.Frame(left, bg=CARD)
        lbtns.pack(fill="x", padx=10, pady=(0, 12))
        make_button(lbtns, "啟用 / 停用", self.toggle_selected_account, kind="secondary", pady=6).pack(
            side="left", padx=(0, 6))
        make_button(lbtns, "刪除", self.delete_selected_account, kind="danger", pady=6).pack(side="left")

        right = tk.Frame(body, bg=CARD, highlightthickness=1, highlightbackground=BORDER)
        right.pack(side="left", fill="both", expand=True)
        tk.Label(right, text="帳號設定", bg=CARD, fg=TEXT,
                 font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=16, pady=(12, 4))
        form_wrap, form, _ = self._scrollable(right, bg=CARD)
        form_wrap.pack(fill="both", expand=True, padx=4, pady=(0, 4))
        self.acc_vars = {}
        row_specs = [
            ("name", "帳號名稱 *"), ("enabled", "啟用此帳號"),
            ("place", "地區"), ("xhs_account", "回饋來源（XHS 帳號）"),
            ("query", "搜尋關鍵字"),
            ("audience", "目標讀者"), ("topics", "關注主題"),
            ("tone", "語氣風格"), ("hashtags", "常用標籤"),
            ("email_to", "收件人（逗號分隔）"),
        ]
        for key, label in row_specs:
            r = tk.Frame(form, bg=CARD)
            r.pack(fill="x", padx=12, pady=5)
            tk.Label(r, text=label, width=18, anchor="w", bg=CARD, fg=MUTED, font=FONT_SMALL).pack(side="left")
            if key == "enabled":
                var = tk.BooleanVar(value=True)
                tk.Checkbutton(r, variable=var, bg=CARD, activebackground=CARD).pack(side="left")
            else:
                var = tk.StringVar()
                tk.Entry(r, textvariable=var, font=FONT, relief="flat", bg="#f8fafc",
                         highlightthickness=1, highlightbackground=BORDER).pack(
                    side="left", fill="x", expand=True, ipady=6)
            self.acc_vars[key] = var

        trow = tk.Frame(form, bg=CARD)
        trow.pack(fill="x", padx=12, pady=(8, 4))
        tk.Label(trow, text="快速範本", width=18, anchor="w", bg=CARD, fg=MUTED, font=FONT_SMALL).pack(side="left")
        self.tpl_var = tk.StringVar(value="自訂")
        ttk.Combobox(trow, textvariable=self.tpl_var, values=list(account_store.templates().keys()),
                     state="readonly", width=16, style="App.TCombobox").pack(side="left")
        make_button(trow, "套用", self.apply_template, kind="secondary", pady=5, padx=12).pack(side="left", padx=8)

        action = tk.Frame(right, bg=CARD)
        action.pack(fill="x", padx=16, pady=(6, 14))
        make_button(action, "儲存帳號", self.save_account_form, kind="primary").pack(side="left", padx=(0, 8))
        make_button(action, "預覽 AI Prompt", self.preview_account_prompt, kind="secondary").pack(side="left", padx=4)
        make_button(action, "自訂 Prompt", self.edit_prompts_dialog, kind="secondary").pack(side="left", padx=4)
        self.acc_hint = tk.Label(action, text="點左邊帳號即可編輯", bg=CARD, fg=MUTED, font=FONT_SMALL)
        self.acc_hint.pack(side="left", padx=12)

    def refresh_accounts(self):
        for row in self.acc_tree.get_children():
            self.acc_tree.delete(row)
        accounts = account_store.list_accounts()
        self._accounts_by_name = {a.get("name"): a for a in accounts}
        for a in accounts:
            self.acc_tree.insert("", "end", iid=str(a.get("name", "?")), values=(
                a.get("name", "?"), "啟用" if a.get("enabled", True) else "停用",
                a.get("place") or "",
            ))
        self._clear_account_form()
        self.refresh_account_schedules()

    def _clear_account_form(self):
        for key, var in self.acc_vars.items():
            if key == "enabled":
                var.set(False)
            else:
                var.set("")
        self._prompt_edits = {"prompt_directions": "", "prompt_analysis": "",
                              "prompt_scripts": "", "prompt_tagline": ""}
        self.acc_hint.config(text="點左邊帳號即可編輯，或按「新增帳號」。")

    def _on_account_select(self, _evt):
        sel = self.acc_tree.selection()
        if not sel:
            return
        name = sel[0]
        a = self._accounts_by_name.get(name)
        if not a:
            return
        for key, var in self.acc_vars.items():
            if key == "enabled":
                var.set(bool(a.get("enabled", True)))
            elif key == "email_to":
                var.set(", ".join(a.get("email_to") or []))
            else:
                var.set(str(a.get(key) or ""))
        self._prompt_edits = {k: str(a.get(k) or "") for k in
                              ("prompt_directions", "prompt_analysis",
                               "prompt_scripts", "prompt_tagline")}
        self.acc_hint.config(text=f"正在編輯：{name}")

    def collect_account_form(self) -> dict:
        data = {}
        for key, var in self.acc_vars.items():
            if key == "enabled":
                data[key] = bool(var.get())
            elif key == "email_to":
                data[key] = [e.strip() for e in str(var.get()).split(",") if e.strip()]
            else:
                data[key] = str(var.get()).strip()
        for k, v in self._prompt_edits.items():
            data[k] = str(v or "").strip()
        return data

    def save_account_form(self):
        try:
            data = self.collect_account_form()
            account_store.save_account(data)
            self.cfg = NewsConfig.load()
            self.refresh_accounts()
            self.acc_hint.config(text=f"已儲存：{data['name']}（下一輪立即生效）")
            messagebox.showinfo("已儲存", f"帳號「{data['name']}」已儲存，下一輪執行即生效。")
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("儲存失敗", str(e))

    def new_account(self):
        self._clear_account_form()
        self.acc_vars["enabled"].set(True)
        self._show_page("accounts")
        self.acc_hint.config(text="填寫右邊欄位後按「儲存帳號」。")

    def delete_selected_account(self):
        sel = self.acc_tree.selection()
        if not sel:
            messagebox.showinfo("提示", "請先在左邊選一個帳號。")
            return
        name = sel[0]
        if messagebox.askyesno("刪除帳號", f"確定刪除「{name}」？歷史執行紀錄會保留。"):
            account_store.delete_account(name)
            self.cfg = NewsConfig.load()
            self.refresh_accounts()

    def toggle_selected_account(self):
        sel = self.acc_tree.selection()
        if not sel:
            messagebox.showinfo("提示", "請先在左邊選一個帳號。")
            return
        name = sel[0]
        a = self._accounts_by_name.get(name) or {}
        current = bool(a.get("enabled", True))
        account_store.toggle_enabled(name, not current)
        self.cfg = NewsConfig.load()
        self.refresh_accounts()

    def apply_template(self):
        tpl = account_store.templates().get(self.tpl_var.get(), {})
        for key, value in tpl.items():
            if key in self.acc_vars:
                self.acc_vars[key].set(value)
        self.acc_hint.config(text=f"已套用範本：{self.tpl_var.get()}，可再修改後儲存。")

    def _account_from_form(self) -> NewsAccount:
        data = self.collect_account_form()
        return NewsAccount(
            name=data.get("name") or "未命名",
            enabled=bool(data.get("enabled", True)),
            place=str(data.get("place") or ""),
            query=str(data.get("query") or ""),
            audience=str(data.get("audience") or ""),
            topics=str(data.get("topics") or ""),
            tone=str(data.get("tone") or ""),
            hashtags=str(data.get("hashtags") or ""),
            email_to=data.get("email_to") or [],
            xhs_account=str(data.get("xhs_account") or ""),
            prompt_directions=str(data.get("prompt_directions") or ""),
            prompt_analysis=str(data.get("prompt_analysis") or ""),
            prompt_scripts=str(data.get("prompt_scripts") or ""),
            prompt_tagline=str(data.get("prompt_tagline") or ""),
        )

    def preview_account_prompt(self):
        try:
            acc = self._account_from_form().effective(self.cfg)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("錯誤", str(e))
            return
        win = tk.Toplevel(self)
        win.title(f"Prompt 預覽：{acc.name}")
        win.geometry("820x640")
        win.configure(bg=BG)
        txt = scrolledtext.ScrolledText(win, wrap="word", font=FONT_MONO,
                                        bg=CONSOLE_BG, fg=CONSOLE_FG)
        txt.pack(fill="both", expand=True, padx=10, pady=10)
        sections = [
            ("【方向選擇】Select Articles Agent", prompts.select_directions_system(acc)),
            ("【深度分析】Generate Full Analysis Agent", prompts.deep_analysis_system(acc)),
            ("【腳本生成】Generate Social Script", prompts.script_system(acc)),
            ("【Tagline / 圖片 Prompt】AI Agent", prompts.tagline_system(acc)),
        ]
        txt.insert("1.0", "\n\n".join(f"{t}\n{'=' * 40}\n{s}" for t, s in sections))

    def edit_prompts_dialog(self):
        if not hasattr(self, "_prompt_edits"):
            self._prompt_edits = {"prompt_directions": "", "prompt_analysis": "",
                                  "prompt_scripts": "", "prompt_tagline": ""}
        win = tk.Toplevel(self)
        win.title("自訂 AI Prompt")
        win.geometry("860x700")
        win.configure(bg=BG)
        self._prompt_widgets = {}
        keys = [
            ("prompt_directions", "方向選擇（Select Articles Agent）"),
            ("prompt_analysis", "深度分析（Generate Full Analysis Agent）"),
            ("prompt_scripts", "腳本生成（Generate Social Script）"),
            ("prompt_tagline", "Tagline / 圖片 Prompt（AI Agent）"),
        ]
        for key, label in keys:
            tk.Label(win, text=label + "（留空 = 用上面的受眾/主題自動產生）",
                     font=FONT_SMALL, fg=MUTED, bg=BG).pack(anchor="w", padx=10, pady=(8, 0))
            w = scrolledtext.ScrolledText(win, wrap="word", font=FONT_MONO, height=8)
            w.insert("1.0", self._prompt_edits.get(key, ""))
            w.pack(fill="both", expand=True, padx=10, pady=(2, 4))
            self._prompt_widgets[key] = w

        def save():
            for key, w in self._prompt_widgets.items():
                self._prompt_edits[key] = w.get("1.0", "end").strip()
            win.destroy()
            self.acc_hint.config(text="自訂 prompt 已記住，按「儲存帳號」寫入。")

        make_button(win, "確定", save, kind="primary").pack(pady=10)

    # ---------------- 排程 / 設定 / 日誌 ----------------
    def _build_schedule_page(self):
        page = tk.Frame(self.content, bg=BG)
        self.pages["schedule"] = page
        self.page_header(
            page, "排程",
            "預設排程只跑「沒有自己排程」的帳號；有設定的帳號只照自己的時間跑。",
        )
        card = self.card(page)
        self.sched_enabled = tk.BooleanVar(value=True)
        tk.Checkbutton(card, text="啟用預設排程", variable=self.sched_enabled,
                       bg=CARD, fg=TEXT, font=FONT, activebackground=CARD).pack(anchor="w")
        row = tk.Frame(card, bg=CARD)
        row.pack(fill="x", pady=(12, 4))
        tk.Label(row, text="預設每日時間", bg=CARD, fg=MUTED, font=FONT_SMALL).pack(side="left")
        self.sched_hour = tk.StringVar(value="14")
        self.sched_min = tk.StringVar(value="00")
        tk.Spinbox(row, from_=0, to=23, textvariable=self.sched_hour, width=4, font=FONT).pack(side="left", padx=(12, 4))
        tk.Label(row, text=":", bg=CARD).pack(side="left")
        tk.Spinbox(row, from_=0, to=59, textvariable=self.sched_min, width=4, font=FONT).pack(side="left", padx=4)
        self.sched_status = tk.Label(card, text="", bg=CARD, fg=MUTED, font=FONT_SMALL, justify="left")
        self.sched_status.pack(anchor="w", pady=(12, 8))
        btns = tk.Frame(card, bg=CARD)
        btns.pack(anchor="w")
        make_button(btns, "套用排程", self.apply_schedule, kind="primary").pack(side="left", padx=(0, 8))
        make_button(btns, "立即觸發一次", self.trigger_now, kind="secondary").pack(side="left")

        acc_card = self.card(page)
        tk.Label(acc_card, text="各帳號排程（選填）", bg=CARD, fg=TEXT,
                 font=("Segoe UI", 12, "bold")).pack(anchor="w")
        tk.Label(acc_card, text="有設定的帳號只照自己的時間/星期跑；留空的帳號用上面的預設排程。"
                                "時間從下拉選單選，星期用勾選的（都不勾=每天）。",
                 bg=CARD, fg=MUTED, font=FONT_SMALL, justify="left", wraplength=680).pack(anchor="w", pady=(4, 8))
        self.acc_sched_frame = tk.Frame(acc_card, bg=CARD)
        self.acc_sched_frame.pack(fill="x")
        self.refresh_account_schedules()

    def refresh_account_schedules(self):
        for w in self.acc_sched_frame.winfo_children():
            w.destroy()
        self.acc_sched_vars = {}
        time_presets = ["09:00", "10:00", "11:00", "12:00", "13:00", "14:00",
                        "15:00", "16:00", "17:00", "18:00", "19:00", "20:00",
                        "21:00", "22:00", "23:00"]
        day_buttons = [("一", "mon"), ("二", "tue"), ("三", "wed"), ("四", "thu"),
                       ("五", "fri"), ("六", "sat"), ("日", "sun")]
        for a in account_store.list_accounts():
            name = str(a.get("name") or "")
            row = tk.Frame(self.acc_sched_frame, bg=CARD)
            row.pack(fill="x", pady=3)
            tk.Label(row, text=name, width=14, anchor="w", bg=CARD, fg=TEXT,
                     font=FONT_SMALL).pack(side="left")
            tvar = tk.StringVar(value=str(a.get("schedule_time") or ""))
            ttk.Combobox(row, textvariable=tvar, values=time_presets, width=6,
                         state="normal", style="App.TCombobox").pack(side="left", padx=(8, 2))
            tk.Label(row, text="時間", bg=CARD, fg=MUTED, font=FONT_SMALL).pack(side="left")
            tk.Label(row, text="星期", bg=CARD, fg=MUTED, font=FONT_SMALL).pack(side="left", padx=(8, 0))
            day_vars: dict[str, tk.BooleanVar] = {}
            codes = set(scheduler.normalize_days(a.get("schedule_days")).split(","))
            for cn, code in day_buttons:
                var = tk.BooleanVar(value=code in codes)
                tk.Checkbutton(row, text=cn, variable=var, bg=CARD, activebackground=CARD,
                               font=FONT_SMALL).pack(side="left", padx=1)
                day_vars[code] = var
            make_button(
                row, "儲存",
                lambda n=name, tv=tvar, dv=day_vars: self.save_account_schedule(n, tv, dv),
                kind="secondary", pady=3, padx=10,
            ).pack(side="left", padx=8)
            self.acc_sched_vars[name] = (tvar, day_vars)

    def save_account_schedule(self, name: str, tvar, dvar):
        time_str = tvar.get().strip()
        if time_str and ":" not in time_str:
            messagebox.showerror("時間格式錯誤", f"「{name}」的時間格式不對，請從下拉選單選擇，例如 11:00。")
            return
        days_code = ",".join(code for code, var in dvar.items() if var.get())
        data = {}
        for a in account_store.list_accounts():
            if a.get("name") == name:
                data = dict(a)
                break
        data["name"] = name
        if time_str:
            data["schedule_time"] = time_str
        else:
            data.pop("schedule_time", None)
        if days_code:
            data["schedule_days"] = days_code
        else:
            data.pop("schedule_days", None)
        account_store.save_account(data)
        self.cfg = NewsConfig.load()
        self.refresh_account_schedules()
        self.sched_status.config(text=f"已儲存「{name}」的排程，記得按「套用排程」生效。")

    def _add_env_fields(self, card, fields, env: dict):
        for key, label in fields:
            row = tk.Frame(card, bg=CARD)
            row.pack(fill="x", pady=6)
            tk.Label(row, text=label, width=32, anchor="w", bg=CARD, fg=MUTED, font=FONT_SMALL).pack(side="left")
            var = tk.StringVar(value=env.get(key, ""))
            show = "*" if ("KEY" in key or "TOKEN" in key) else ""
            tk.Entry(row, textvariable=var, font=FONT, relief="flat", bg="#f8fafc",
                     highlightthickness=1, highlightbackground=BORDER, show=show).pack(
                side="left", fill="x", expand=True, ipady=6)
            self.env_vars[key] = var

    def _build_settings_page(self):
        page = tk.Frame(self.content, bg=BG)
        self.pages["settings"] = page
        self.page_header(page, "設定", "機密放在 .env。此頁只改常用欄位。")
        wrap, body, _ = self._scrollable(page, bg=BG)
        wrap.pack(fill="both", expand=True)
        env = self._read_env()
        self.env_vars = {}

        card = self.card(body)
        tk.Label(card, text="API 與寄信", font=("Segoe UI", 12, "bold"), fg=TEXT, bg=CARD).pack(anchor="w")
        self._add_env_fields(card, ENV_FIELDS, env)

        form_card = self.card(body)
        tk.Label(form_card, text="手機審批表單（ngrok）", font=("Segoe UI", 12, "bold"), fg=TEXT, bg=CARD).pack(anchor="w")
        tk.Label(
            form_card,
            text="讓同事用手機點 email 裡的連結填表單。先跑 start-ngrok.cmd，把 ngrok 網址填進「公開網址」。留空則只用本機。",
            font=FONT_SMALL, fg=MUTED, bg=CARD, wraplength=720, justify="left",
        ).pack(anchor="w", pady=(4, 6))
        self._add_env_fields(form_card, FORM_ENV_FIELDS, env)
        tk.Label(
            form_card,
            text="公開網址例如 https://你的名字.ngrok-free.dev。Authtoken（登入金鑰）必填，表單網址必須帶 ?token=… 才能開啟/送出。",
            font=FONT_SMALL, fg=MUTED, bg=CARD, wraplength=720, justify="left",
        ).pack(anchor="w", pady=(2, 0))

        make_button(body, "儲存設定", self.save_settings, kind="primary").pack(anchor="w", pady=(4, 0))

    def _build_log_page(self):
        page = tk.Frame(self.content, bg=BG)
        self.pages["log"] = page
        actions = self.page_header(page, "日誌", "執行過程會寫在這裡。長時間運行會自動清掉舊行，避免越跑越慢。")
        make_button(actions, "清空日誌", self._clear_log, kind="secondary").pack(side="left")
        self.log_text = scrolledtext.ScrolledText(
            page, wrap="word", font=FONT_MONO, bg=CONSOLE_BG, fg=CONSOLE_FG,
            relief="flat", padx=10, pady=8, highlightthickness=1, highlightbackground=BORDER,
        )
        self.log_text.pack(fill="both", expand=True)
        self.log_text.configure(state="disabled")

    def _clear_log(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    # ---------------- 資料載入 ----------------
    def _read_env(self) -> dict:
        out = {}
        if ENV_PATH.exists():
            for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
                if line.strip() and not line.strip().startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    out[k.strip()] = v.strip()
        return out

    def _periodic_refresh(self):
        if not self._busy:
            keep = self.current_run_id
            self.refresh_pending(keep_selection=keep)
            # 若目前 run 的審批內容有變（例如 Email/表單處理了拒絕或批准），自動重繪工作區
            if keep and any(int(r["id"]) == keep for r in self._pending_items):
                run = store.get_run(self.conn, keep)
                if run and self._approval_sig(run) != self._rendered_sig:
                    self._open_pending(keep)
        self.after(8000, self._periodic_refresh)

    # ---------------- 動作（worker 執行，回主執行緒更新 UI） ----------------
    def _set_busy(self, busy: bool, message: str | None = None):
        self._busy = busy
        state = "disabled" if busy else "normal"
        for btn in (getattr(self, "btn_approve", None), getattr(self, "btn_reject", None),
                    getattr(self, "btn_run_approve", None), getattr(self, "btn_run_main", None)):
            if btn is not None:
                btn.configure(state=state)
                if not busy:
                    rest = getattr(btn, "_rest_bg", None)
                    if rest:
                        btn.configure(bg=rest)
        if busy:
            self.status_dot.config(fg=WARNING)
            self.status_lbl.config(text=message or "處理中…")
        else:
            self.status_dot.config(fg=SUCCESS)
            self.status_lbl.config(text=message or "就緒")

    def _run_worker(self, fn, on_done=None, busy_msg="處理中…"):
        self._set_busy(True, busy_msg)

        def work():
            q = self.log_q
            tee = _Tee(sys.stdout, q)
            with contextlib.redirect_stdout(tee), contextlib.redirect_stderr(tee):
                try:
                    result = fn()
                    if on_done:
                        self.after(0, lambda r=result: self._finish_worker(on_done, r))
                    else:
                        self.after(0, lambda: self._set_busy(False, "完成"))
                except Exception as e:  # noqa: BLE001
                    q.put(f"\n[錯誤] {e}\n")
                    self.after(0, lambda err=e: self._set_busy(False, f"錯誤：{err}"))
                finally:
                    q.put("\n[完成]\n")

        threading.Thread(target=work, daemon=True).start()

    def _finish_worker(self, on_done, result):
        try:
            on_done(result)
        finally:
            self._set_busy(False)

    def start_new_run(self):
        if self._busy:
            messagebox.showinfo("提示", "已有工作在進行，請稍候。")
            return
        self.run_status_lbl.config(text="執行中…（搜尋新聞 → AI 生成方向）")
        self.status_hint.config(text="通常需要 1–2 分鐘")
        cfg = NewsConfig.load()
        db_path = cfg.db_path

        def do():
            conn = store.connect(db_path)
            try:
                return pipeline.start_run(cfg, conn, dry_run=False, notify=True)
            finally:
                conn.close()

        def done(run_id):
            self.run_status_lbl.config(text=f"run #{run_id} 已停在方向審批")
            self.status_hint.config(text="")
            self.refresh_runs()
            self.refresh_pending()
            self._show_page("approve")
            if run_id:
                self._open_pending(int(run_id))

        self._run_worker(do, done, busy_msg="正在搜尋新聞並生成方向…")

    def approve(self, decision: str):
        if self._busy:
            messagebox.showinfo("提示", "正在處理上一筆審批，請稍候。")
            return
        if not self.current_run_id:
            messagebox.showinfo("提示", "請先在左邊選擇一筆等待審批的執行")
            return
        run = store.get_run(self.conn, self.current_run_id)
        if not run:
            return
        comment = self.comment_var.get().strip()
        cfg = NewsConfig.load()
        run_id = self.current_run_id
        db_path = cfg.db_path

        def do():
            conn = store.connect(db_path)
            try:
                fresh = store.get_run(conn, run_id)
                if fresh["status"] == pipeline.STATUS_AWAIT_DIRECTION:
                    return pipeline.decide_direction(cfg, conn, run_id, decision, comment, notify=True)
                if fresh["status"] == pipeline.STATUS_AWAIT_SCRIPT:
                    return pipeline.decide_script(cfg, conn, run_id, decision, comment, notify=True)
                return fresh["status"]
            finally:
                conn.close()

        def done(status):
            self.comment_var.set("")
            self._choice = None
            self.refresh_runs()
            self.refresh_pending()
            if status == pipeline.STATUS_AWAIT_SCRIPT:
                self._open_pending(run_id)
                self.approve_hint.config(text=f"方向已通過。run #{run_id} 正在等腳本審批。")
            elif status == pipeline.STATUS_AWAIT_DIRECTION:
                self._open_pending(run_id)
                self.approve_hint.config(text="已拒絕，等待新一輪方向。")
            elif status == pipeline.STATUS_DONE:
                self._select_first_pending()
                messagebox.showinfo("完成", f"run #{run_id} 已定稿，Tagline 與圖片 Prompt 已寄出。")
            elif status == pipeline.STATUS_FAILED:
                self._select_first_pending()
                messagebox.showwarning("已中止", f"run #{run_id} 重試次數用盡，已標記失敗。")
            else:
                self.approve_hint.config(text=f"結果：{STATUS_LABELS.get(status, status)}")

        wait = "正在生成深度分析與腳本，約需數分鐘…" if decision != "reject" else "正在處理拒絕…"
        self.approve_hint.config(text=wait)
        self.status_hint.config(text="請勿重複點擊")
        self._run_worker(do, done, busy_msg=wait)

    # ---------------- 設定 / 排程 ----------------
    def save_settings(self):
        env = self._read_env()
        for key, var in self.env_vars.items():
            env[key] = var.get().strip()
            os.environ[key] = env[key]
        lines = [f"{k}={v}" for k, v in env.items()]
        ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
        self.cfg = NewsConfig.load()
        messagebox.showinfo("已儲存", "設定已寫入 .env，已重新載入。")

    def apply_schedule(self):
        cfg = scheduler.load_config()
        cfg["enabled"] = bool(self.sched_enabled.get())
        cfg["hour"] = int(self.sched_hour.get())
        cfg["minute"] = int(self.sched_min.get())
        try:
            msg = scheduler.apply_schedule(cfg)
            self.sched_status.config(text=msg)
            messagebox.showinfo("排程", msg)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("排程失敗", str(e))
        self.refresh_schedule_status()

    def trigger_now(self):
        try:
            msg = scheduler.run_now()
            self.sched_status.config(text=msg)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("觸發失敗", str(e))

    def refresh_schedule_status(self):
        try:
            st = scheduler.get_task_status()
            text = (f"工作排程狀態：{st.get('STATE', '?')}\n"
                    f"上次執行：{st.get('LAST', '-')}\n"
                    f"下次執行：{st.get('NEXT', '-')}\n"
                    f"上次結果碼：{st.get('RESULT', '-')}")
            acctasks = st.get("ACCTASKS", "")
            if acctasks:
                text += "\n\n各帳號排程："
                for row in acctasks.split(";"):
                    if not row:
                        continue
                    name, state, nxt = row.split("|", 2)
                    text += f"\n  {name.replace('小紅書新聞AI - ', '')}｜{state}｜下次 {nxt}"
        except Exception as e:  # noqa: BLE001
            text = f"無法讀取排程：{e}"
        self.sched_status.config(text=text)

    def _poll_queue(self):
        chunks = []
        try:
            while True:
                chunks.append(self.log_q.get_nowait())
                if len(chunks) >= 50:
                    break
        except queue.Empty:
            pass
        if chunks:
            self.log_text.configure(state="normal")
            self.log_text.insert("end", "".join(chunks))
            try:
                line_count = int(float(self.log_text.index("end-1c")))
            except (tk.TclError, ValueError):
                line_count = 0
            if line_count > LOG_MAX_LINES:
                self.log_text.delete("1.0", f"{line_count - LOG_MAX_LINES + 200}.0")
            self.log_text.see("end")
            self.log_text.configure(state="disabled")
        self.after(150, self._poll_queue)


def main():
    app = NewsApp()
    app.after(400, app.refresh_schedule_status)
    app.mainloop()


if __name__ == "__main__":
    main()
