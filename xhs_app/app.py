"""小紅書每週分析系統 - 桌面應用程式（Tkinter，專業樣式）。

執行方式：
  python xhs_app/app.py
"""
from __future__ import annotations

import queue
import subprocess
import sys
import threading
import webbrowser
import ctypes
import contextlib
import io
import json
from pathlib import Path

import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk, simpledialog

# 啟用 DPI 感知，避免在高解析度螢幕上模糊
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:  # noqa: BLE001
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:  # noqa: BLE001
        pass

from links import read_urls, save_urls
from models import fetch_models, model_options, save_cached
from scheduler import DAY_LABELS, DAYS, apply_schedule, get_task_status, load_config, run_now, save_config
from settings import load_env, save_env
from xhs_report import storage
from xhs_report.config import Config

if getattr(sys, "frozen", False):
    # 打包成 exe 時：以「exe 所在資料夾」為專案根目錄（config/.env/data 都在旁邊）
    PROJECT_ROOT = Path(sys.executable).resolve().parent
else:
    PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_ROOT / ".env"
XLSX_PATH = PROJECT_ROOT / "data" / "posts.xlsx"
ACCOUNTS_FILE = PROJECT_ROOT / "data" / "accounts.json"
REPORTS_DIR = PROJECT_ROOT / "data" / "reports"
PYTHON = sys.executable


def load_accounts() -> list[dict]:
    if ACCOUNTS_FILE.exists():
        try:
            raw = json.loads(ACCOUNTS_FILE.read_text(encoding="utf-8")) or []
            if raw:
                return [
                    {"name": str(a.get("name") or "帳號"), "excel_path": str(a.get("excel_path") or "data/posts.xlsx")}
                    for a in raw
                ]
        except (json.JSONDecodeError, OSError):
            pass
    try:
        cfg_acc = Config.load().accounts
        if cfg_acc:
            return cfg_acc
    except Exception:  # noqa: BLE001
        pass
    return [{"name": "default", "excel_path": "data/posts.xlsx"}]


def save_accounts(accounts: list[dict]) -> None:
    ACCOUNTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    ACCOUNTS_FILE.write_text(json.dumps(accounts, ensure_ascii=False, indent=2), encoding="utf-8")

# ---------- 設計系統 ----------
ACCENT = "#ff2442"
ACCENT_DARK = "#d81b33"
ACCENT_SOFT = "#fff0f2"
BG = "#f4f4f7"
CARD = "#ffffff"
BORDER = "#e3e3e9"
TEXT = "#1f1f26"
MUTED = "#6d6d78"
SIDEBAR_BG = "#1e2027"
SIDEBAR_HOVER = "#2a2d37"
SIDEBAR_ACTIVE = "#323543"
SIDEBAR_TEXT = "#b9bcc6"
SUCCESS = "#1a7f37"
WARNING = "#b45309"
CONSOLE_BG = "#0f1115"
CONSOLE_FG = "#d8dee9"

FONT = ("Segoe UI", 10)
FONT_SMALL = ("Segoe UI", 9)
FONT_TITLE = ("Segoe UI", 17, "bold")
FONT_SUB = ("Segoe UI", 10)
FONT_MONO = ("Consolas", 10)

SETTING_GROUPS = [
    ("抓取與 AI 分析", [
        ("APIFY_API_KEY", "Apify API key（抓取小紅書）"),
        ("APIFY_COOKIE_STRING", "小紅書 Cookie（選填，解決抓取限流）"),
        ("AI_API_KEY", "OpenRouter API key（AI 分析）"),
        ("AI_MODEL", "AI 模型"),
    ]),
    ("寄信與收件人", [
        ("EMAIL_PROVIDER", "寄信方式（outlook / sendgrid）"),
        ("EMAIL_FROM", "寄件人 email"),
        ("EMAIL_TO", "收件人 email（多個用逗號）"),
        ("EMAIL_CC", "副本 email"),
        ("SENDGRID_API_KEY", "SendGrid key（選填）"),
        ("RESEND_API_KEY", "Resend key（選填）"),
    ]),
]


def flat_button(parent, text, fg, bg, hover_bg, command, font=None, padx=14, pady=7, activefg=None, border=None):
    btn = tk.Button(
        parent, text=text, font=font or FONT, fg=fg, bg=bg,
        activebackground=hover_bg, activeforeground=activefg or fg,
        relief="flat", bd=0, cursor="hand2", padx=padx, pady=pady,
        highlightthickness=1, highlightbackground=border or bg, command=command,
    )
    return btn


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("小紅書每週分析系統")
        dpi_scale = self.winfo_fpixels("1i") / 96.0
        self.geometry(f"{int(980 * dpi_scale)}x{int(680 * dpi_scale)}")
        self.minsize(860, 600)
        self.configure(bg=BG)

        self.log_queue: queue.Queue = queue.Queue()
        self.sched_q: queue.Queue = queue.Queue()
        self.model_q: queue.Queue = queue.Queue()
        self.running = False
        self.pages: dict[str, tk.Frame] = {}
        self.nav_bars: dict[str, tk.Frame] = {}
        self.nav_buttons: dict[str, tk.Button] = {}
        self.accounts = load_accounts()
        self.account_var = tk.StringVar(value=self.accounts[0]["name"] if self.accounts else "default")

        self._build_sidebar()
        self._build_content()
        self._build_run_page()
        self._build_schedule_page()
        self._build_settings_page()
        self._build_links_page()
        self._build_help_page()

        self.after(200, self._drain_log)
        self.after(200, self._drain_sched)
        self.after(200, self._drain_models)
        self.after(20000, self._periodic_refresh)
        self._refresh_links()
        self._refresh_report_info()
        self._refresh_schedule_status()
        self._show_page("run")

    # ---------------- 版面架構 ----------------
    def _build_sidebar(self):
        self.sidebar = tk.Frame(self, bg=SIDEBAR_BG, width=210)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        brand = tk.Frame(self.sidebar, bg=SIDEBAR_BG)
        brand.pack(fill="x", pady=(26, 18))
        tk.Label(brand, text="小紅書週報", font=("Segoe UI", 16, "bold"),
                 fg="#ffffff", bg=SIDEBAR_BG).pack()
        tk.Label(brand, text="XHS WEEKLY ANALYTICS", font=("Segoe UI", 8, "bold"),
                 fg=ACCENT, bg=SIDEBAR_BG).pack()
        tk.Frame(self.sidebar, bg="#33363f", height=1).pack(fill="x", padx=18, pady=14)

        nav = [
            ("run", "  運行"),
            ("schedule", "  排程"),
            ("settings", "  設定"),
            ("links", "  連結"),
            ("help", "  說明"),
        ]
        for key, label in nav:
            item = tk.Frame(self.sidebar, bg=SIDEBAR_BG)
            item.pack(fill="x", pady=1)
            bar = tk.Frame(item, bg=SIDEBAR_BG, width=3)
            bar.pack(side="left", fill="y")
            btn = tk.Button(
                item, text=label, font=("Segoe UI", 11), fg=SIDEBAR_TEXT,
                bg=SIDEBAR_BG, activebackground=SIDEBAR_HOVER, activeforeground="#ffffff",
                relief="flat", bd=0, cursor="hand2", anchor="w", padx=18, pady=11,
                command=lambda k=key: self._show_page(k),
            )
            btn.pack(side="left", fill="x", expand=True)
            self.nav_bars[key] = bar
            self.nav_buttons[key] = btn
            btn.bind("<Enter>", lambda e, b=btn, k=key: self._nav_hover(b, k, True))
            btn.bind("<Leave>", lambda e, b=btn, k=key: self._nav_hover(b, k, False))

        tk.Label(self.sidebar, text="v1.0", font=FONT_SMALL, fg="#5a5d68",
                 bg=SIDEBAR_BG).pack(side="bottom", pady=12)

    def _nav_hover(self, btn, key, entering):
        if self.current_page == key:
            return
        btn.configure(bg=SIDEBAR_HOVER if entering else SIDEBAR_BG)

    def _build_content(self):
        self.content = tk.Frame(self, bg=BG)
        self.content.pack(side="left", fill="both", expand=True)

    def _show_page(self, key):
        self.current_page = key
        for k, page in self.pages.items():
            page.pack_forget()
        self.pages[key].pack(fill="both", expand=True, padx=22, pady=18)
        for k, bar in self.nav_bars.items():
            active = k == key
            bar.configure(bg=ACCENT if active else SIDEBAR_BG)
            self.nav_buttons[k].configure(
                bg=SIDEBAR_ACTIVE if active else SIDEBAR_BG,
                fg="#ffffff" if active else SIDEBAR_TEXT,
            )
        if key == "run":
            self._refresh_report_info()

    def _periodic_refresh(self):
        self._refresh_report_info()
        self.after(20000, self._periodic_refresh)

    def page_header(self, parent, title, subtitle):
        tk.Label(parent, text=title, font=FONT_TITLE, fg=TEXT, bg=BG).pack(anchor="w")
        tk.Label(parent, text=subtitle, font=FONT_SUB, fg=MUTED, bg=BG).pack(anchor="w", pady=(2, 0))
        tk.Frame(parent, bg=ACCENT, height=2).pack(fill="x", pady=(10, 14))

    def card(self, parent, padding=16):
        c = tk.Frame(parent, bg=CARD, highlightthickness=1, highlightbackground=BORDER)
        c.pack(fill="x", pady=(0, 14))
        inner = tk.Frame(c, bg=CARD)
        inner.pack(fill="x", padx=padding, pady=padding)
        return inner

    # ---------------- 運行頁 ----------------
    def _build_run_page(self):
        page = tk.Frame(self.content, bg=BG)
        self.pages["run"] = page
        self.page_header(page, "運行", f"執行全部 {len(self.accounts)} 個帳號的每週分析，並查看最新報告")

        card = self.card(page)
        tk.Label(card, text="一鍵執行", font=("Segoe UI", 12, "bold"), fg=TEXT, bg=CARD).pack(anchor="w")
        btn_row = tk.Frame(card, bg=CARD)
        btn_row.pack(fill="x", pady=(10, 0))

        self.btn_test = flat_button(btn_row, "測試執行（不寄信）", "#ffffff", ACCENT, ACCENT_DARK,
                                    lambda: self._run(["--dry-run"]), font=("Segoe UI", 10, "bold"))
        self.btn_test.pack(side="left", padx=(0, 8))
        self.btn_run = flat_button(btn_row, "正式執行", "#ffffff", "#111318", "#262a33",
                                   lambda: self._run([]), font=("Segoe UI", 10, "bold"))
        self.btn_run.pack(side="left", padx=8)
        self.btn_skip = flat_button(btn_row, "跳過抓取重跑", TEXT, CARD, "#f0f0f4",
                                    lambda: self._run(["--skip-scrape"]), border=BORDER)
        self.btn_skip.pack(side="left", padx=8)

        self.status_pill = tk.Label(card, text="● 就緒", font=("Segoe UI", 9, "bold"),
                                    fg=SUCCESS, bg="#eaf6ee", padx=10, pady=4)
        self.status_pill.pack(anchor="w", pady=(12, 0))

        card3 = self.card(page)
        tk.Label(card3, text="最新報告", font=("Segoe UI", 12, "bold"), fg=TEXT, bg=CARD).pack(anchor="w")
        self.report_info = tk.Label(card3, text="尚未產生報告", font=FONT, fg=MUTED, bg=CARD)
        self.report_info.pack(anchor="w", pady=(8, 0))
        rrow = tk.Frame(card3, bg=CARD)
        rrow.pack(anchor="w", pady=(8, 0))
        flat_button(rrow, "開啟 HTML 報告", TEXT, CARD, "#f0f0f4",
                    self._open_latest_report, border=BORDER).pack(side="left", padx=(0, 8))
        flat_button(rrow, "開啟 PDF", TEXT, CARD, "#f0f0f4",
                    self._open_latest_pdf, border=BORDER).pack(side="left")
        flat_button(rrow, "重新整理", TEXT, CARD, "#f0f0f4",
                    self._refresh_report_info, border=BORDER).pack(side="left", padx=(8, 0))

        card2 = self.card(page)
        tk.Label(card2, text="執行日誌", font=("Segoe UI", 12, "bold"), fg=TEXT, bg=CARD).pack(anchor="w")
        self.log_box = scrolledtext.ScrolledText(
            card2, height=9, font=FONT_MONO, bg=CONSOLE_BG, fg=CONSOLE_FG,
            insertbackground=CONSOLE_FG, relief="flat", padx=10, pady=8,
            highlightthickness=1, highlightbackground=BORDER,
        )
        self.log_box.configure(state="disabled")
        self.log_box.pack(fill="both", expand=True, pady=(10, 0))

    def _run(self, extra_args):
        if self.running:
            messagebox.showinfo("提示", "已有執行正在進行，請稍候。")
            return
        self.running = True
        self._set_status("執行中…", WARNING)
        for b in (self.btn_test, self.btn_run, self.btn_skip):
            b.configure(state="disabled")
        self._append_log(f"\n>>> python run_weekly.py {' '.join(extra_args)}\n")
        threading.Thread(target=self._run_pipeline, args=(extra_args,), daemon=True).start()

    def _run_pipeline(self, extra_args):
        if getattr(sys, "frozen", False):
            self._run_in_process(extra_args)
            return
        cmd = [PYTHON, "run_weekly.py"] + extra_args
        try:
            proc = subprocess.Popen(
                cmd, cwd=str(PROJECT_ROOT), stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
            )
            assert proc.stdout is not None
            for line in proc.stdout:
                self.log_queue.put(line)
            proc.wait()
            self.log_queue.put(None)
        except Exception as e:  # noqa: BLE001
            self.log_queue.put(f"執行失敗：{e}\n")
            self.log_queue.put(None)

    def _run_in_process(self, extra_args):
        """打包成 exe 時，直接在程式內執行 run_weekly（不需外部 Python）。"""
        import run_weekly

        class _Q(io.TextIOBase):
            def __init__(self, q):
                super().__init__()
                self.q = q

            def write(self, s):
                self.q.put(s)
                return len(s)

            def flush(self):
                pass

        old_argv = sys.argv
        sys.argv = ["run_weekly.py"] + extra_args
        writer = _Q(self.log_queue)
        try:
            with contextlib.redirect_stdout(writer), contextlib.redirect_stderr(writer):
                try:
                    run_weekly.main()
                except SystemExit:
                    pass
        finally:
            sys.argv = old_argv
        self.log_queue.put(None)

    def _drain_log(self):
        try:
            while True:
                item = self.log_queue.get_nowait()
                if item is None:
                    self.running = False
                    self._set_status("完成", SUCCESS)
                    for b in (self.btn_test, self.btn_run, self.btn_skip):
                        b.configure(state="normal")
                    self._append_log(">>> 完成\n")
                    self._refresh_report_info()
                    continue
                self._append_log(item)
        except queue.Empty:
            pass
        self.after(200, self._drain_log)

    def _set_status(self, text, color):
        self.status_pill.configure(text=f"● {text}", fg=color,
                                   bg={"#1a7f37": "#eaf6ee", "#b45309": "#fdf3e3"}.get(color, "#eef0f4"))

    def _append_log(self, text):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", text)
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _latest_file(self, suffix):
        files = sorted(REPORTS_DIR.glob(f"*{suffix}"), key=lambda p: p.stat().st_mtime)
        return files[-1] if files else None

    def _refresh_report_info(self):
        from datetime import datetime

        try:
            from pathlib import Path as _P
            dbg = _P("data/app_debug.log")
            dbg.parent.mkdir(parents=True, exist_ok=True)
            with open(dbg, "a", encoding="utf-8") as f:
                f.write(f"[{datetime.now().strftime('%H:%M:%S')}] refresh report_info\n")
        except Exception:  # noqa: BLE001
            pass
        html = self._latest_file(".html")
        pdf = self._latest_file(".pdf")
        if html:
            t = datetime.fromtimestamp(html.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            text = f"HTML：{html.name}（{t}）"
            if pdf:
                tp = datetime.fromtimestamp(pdf.stat().st_mtime).strftime("%H:%M")
                text += f"\nPDF：{pdf.name}（{tp}）"
        else:
            text = "尚未產生報告"
        self.report_info.configure(text=text)

    def _open_latest_report(self):
        f = self._latest_file(".html")
        if f:
            webbrowser.open(f.as_uri())
        else:
            messagebox.showinfo("提示", "尚未產生報告")

    def _open_latest_pdf(self):
        f = self._latest_file(".pdf")
        if f:
            webbrowser.open(f.as_uri())
        else:
            messagebox.showinfo("提示", "尚未產生 PDF")

    # ---------------- 設定頁 ----------------
    def _build_settings_page(self):
        page = tk.Frame(self.content, bg=BG)
        self.pages["settings"] = page
        self.page_header(page, "設定", "管理 API 金鑰、寄件人與收件人")
        self.env_vars: dict[str, tk.StringVar] = {}

        for group_title, fields in SETTING_GROUPS:
            card = self.card(page)
            tk.Label(card, text=group_title, font=("Segoe UI", 12, "bold"), fg=TEXT, bg=CARD).pack(anchor="w")
            for key, label in fields:
                row = tk.Frame(card, bg=CARD)
                row.pack(fill="x", pady=5)
                tk.Label(row, text=label, width=30, anchor="w", font=FONT, fg=TEXT, bg=CARD).pack(side="left")
                var = tk.StringVar()
                if key == "AI_MODEL":
                    combo = ttk.Combobox(row, textvariable=var, values=model_options(),
                                         width=36, font=FONT)
                    combo.pack(side="left", fill="x", expand=True, ipady=2)
                    flat_button(row, "更新清單", TEXT, CARD, "#f0f0f4",
                                self._refresh_models, border=BORDER).pack(side="left", padx=6)
                    self.model_combo = combo
                else:
                    entry = tk.Entry(row, textvariable=var, font=FONT, relief="flat", bg="#f7f7fa",
                                     highlightthickness=1, highlightbackground=BORDER,
                                     show="*" if ("KEY" in key or "COOKIE" in key) else "")
                    entry.pack(side="left", fill="x", expand=True, ipady=4)
                self.env_vars[key] = var

        bottom = tk.Frame(page, bg=BG)
        bottom.pack(fill="x", pady=(2, 0))
        flat_button(bottom, "儲存設定", "#ffffff", ACCENT, ACCENT_DARK,
                    self._save_settings, font=("Segoe UI", 10, "bold")).pack(side="left")
        flat_button(bottom, "重新載入", TEXT, CARD, "#f0f0f4",
                    self._load_settings, border=BORDER).pack(side="left", padx=8)
        tk.Label(bottom, text="⚠ 設定含機密金鑰，請勿分享此檔案。", font=FONT_SMALL,
                 fg=WARNING, bg=BG).pack(side="left", padx=14)
        self.settings_status = tk.Label(page, text="", font=("Segoe UI", 9, "bold"),
                                        fg=SUCCESS, bg=BG)
        self.settings_status.pack(anchor="w", pady=(2, 0))
        self._load_settings()

    def _load_settings(self):
        env = load_env(ENV_PATH)
        for key, var in self.env_vars.items():
            var.set(env.get(key, ""))
        set_keys = [k for k, v in env.items() if v]
        status = " | ".join(k for k in ("APIFY_API_KEY", "AI_API_KEY", "EMAIL_FROM", "EMAIL_TO") if k in set_keys)
        self.settings_status.configure(
            text=f"目前已設定：{status}" if status else "目前未設定任何金鑰"
        )

    def _save_settings(self):
        values = {k: v.get().strip() for k, v in self.env_vars.items()}
        save_env(ENV_PATH, values)
        messagebox.showinfo("完成", "設定已儲存（下次執行生效）")

    def _refresh_models(self):
        threading.Thread(target=self._fetch_models_thread, daemon=True).start()

    def _fetch_models_thread(self):
        ids = fetch_models()
        if ids:
            save_cached(ids)
        self.model_q.put(ids)

    def _drain_models(self):
        try:
            while True:
                ids = self.model_q.get_nowait()
                if ids:
                    self.model_combo.configure(values=model_options())
                    messagebox.showinfo("完成", f"已更新模型清單（共 {len(ids)} 個模型）")
                else:
                    messagebox.showwarning("提示", "無法連上 OpenRouter 更新模型清單（請檢查網路），將沿用預置清單。")
        except queue.Empty:
            pass
        self.after(200, self._drain_models)

    # ---------------- 連結頁 ----------------
    # ---------------- 排程頁 ----------------
    def _build_schedule_page(self):
        page = tk.Frame(self.content, bg=BG)
        self.pages["schedule"] = page
        self.page_header(page, "排程", "設定每週自動執行時間（Windows 工作排程）")

        cfg = load_config()
        self.sched_enabled = tk.BooleanVar(value=bool(cfg.get("enabled", True)))
        self.sched_day = tk.StringVar(
            value=DAY_LABELS[DAYS.index(cfg["day"])] if cfg.get("day") in DAYS else "星期五"
        )
        self.sched_hour = tk.StringVar(value=f"{int(cfg.get('hour', 9)):02d}")
        self.sched_minute = tk.StringVar(value=f"{int(cfg.get('minute', 0)):02d}")

        card = self.card(page)
        tk.Label(card, text="自動執行設定", font=("Segoe UI", 12, "bold"), fg=TEXT, bg=CARD).pack(anchor="w")
        row1 = tk.Frame(card, bg=CARD)
        row1.pack(fill="x", pady=(10, 0))
        tk.Checkbutton(
            row1, text="啟用每週自動執行", variable=self.sched_enabled, font=FONT,
            bg=CARD, fg=TEXT, activebackground=CARD, activeforeground=TEXT,
            highlightthickness=0, selectcolor="#ffffff",
        ).pack(side="left")
        row2 = tk.Frame(card, bg=CARD)
        row2.pack(fill="x", pady=(8, 0))
        tk.Label(row2, text="每週", font=FONT, bg=CARD, fg=TEXT).pack(side="left")
        ttk.Combobox(row2, textvariable=self.sched_day, values=DAY_LABELS,
                     state="readonly", width=8, font=FONT).pack(side="left", padx=4)
        tk.Label(row2, text="的", font=FONT, bg=CARD, fg=TEXT).pack(side="left")
        ttk.Combobox(row2, textvariable=self.sched_hour,
                     values=[f"{h:02d}" for h in range(24)], state="readonly",
                     width=4, font=FONT).pack(side="left", padx=4)
        tk.Label(row2, text=":", font=FONT, bg=CARD, fg=TEXT).pack(side="left")
        ttk.Combobox(row2, textvariable=self.sched_minute,
                     values=[f"{m:02d}" for m in range(0, 60, 5)], state="readonly",
                     width=4, font=FONT).pack(side="left", padx=4)
        tk.Label(row2, text="自動執行", font=FONT, bg=CARD, fg=TEXT).pack(side="left", padx=(6, 0))
        row3 = tk.Frame(card, bg=CARD)
        row3.pack(anchor="w", pady=(12, 0))
        flat_button(row3, "儲存並套用", "#ffffff", ACCENT, ACCENT_DARK,
                    self._save_schedule, font=("Segoe UI", 10, "bold")).pack(side="left")
        flat_button(row3, "立即執行一次", TEXT, CARD, "#f0f0f4",
                    self._run_schedule_now, border=BORDER).pack(side="left", padx=8)
        tk.Label(card, text="提示：電腦關機時錯過的執行，會在下次開機登入後自動補跑。",
                 font=FONT_SMALL, fg=MUTED, bg=CARD).pack(anchor="w", pady=(10, 0))

        card2 = self.card(page)
        tk.Label(card2, text="目前排程狀態", font=("Segoe UI", 12, "bold"), fg=TEXT, bg=CARD).pack(anchor="w")
        self.sched_state_label = tk.Label(card2, text="讀取中…", font=FONT, fg=MUTED, bg=CARD)
        self.sched_state_label.pack(anchor="w", pady=(6, 0))
        self.sched_last_label = tk.Label(card2, text="", font=FONT, fg=MUTED, bg=CARD)
        self.sched_last_label.pack(anchor="w")
        self.sched_next_label = tk.Label(card2, text="", font=FONT, fg=MUTED, bg=CARD)
        self.sched_next_label.pack(anchor="w")
        self.sched_result_label = tk.Label(card2, text="", font=FONT, fg=MUTED, bg=CARD)
        self.sched_result_label.pack(anchor="w")
        row4 = tk.Frame(card2, bg=CARD)
        row4.pack(anchor="w", pady=(8, 0))
        flat_button(row4, "重新整理狀態", TEXT, CARD, "#f0f0f4",
                    self._refresh_schedule_status, border=BORDER).pack(side="left")

    def _save_schedule(self):
        cfg = {
            "enabled": bool(self.sched_enabled.get()),
            "day": DAYS[DAY_LABELS.index(self.sched_day.get())],
            "hour": int(self.sched_hour.get()),
            "minute": int(self.sched_minute.get()),
        }
        try:
            msg = apply_schedule(cfg)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("錯誤", f"套用排程失敗：\n{e}")
            return
        messagebox.showinfo("完成", msg)
        self._refresh_schedule_status()

    def _run_schedule_now(self):
        try:
            msg = run_now()
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("錯誤", f"觸發失敗：\n{e}")
            return
        messagebox.showinfo("完成", msg)

    def _refresh_schedule_status(self):
        threading.Thread(target=self._load_sched_thread, daemon=True).start()

    def _load_sched_thread(self):
        try:
            st = get_task_status()
        except Exception as e:  # noqa: BLE001
            st = {"STATE": f"ERROR {e}"}
        self.sched_q.put(st)

    def _drain_sched(self):
        try:
            while True:
                st = self.sched_q.get_nowait()
                self._apply_sched_status(st)
        except queue.Empty:
            pass
        self.after(200, self._drain_sched)

    def _apply_sched_status(self, st: dict):
        state = st.get("STATE", "?")
        if state == "MISSING":
            self.sched_state_label.configure(text="排程狀態：尚未建立（請先儲存設定）", fg=WARNING)
            self.sched_last_label.configure(text="")
            self.sched_next_label.configure(text="")
            self.sched_result_label.configure(text="")
            return
        if state.startswith("ERROR"):
            self.sched_state_label.configure(text=f"排程狀態：讀取失敗（{state}）", fg=WARNING)
            return
        self.sched_state_label.configure(
            text=f"排程狀態：{state}", fg=SUCCESS if state == "Ready" else TEXT
        )
        self.sched_last_label.configure(text=f"上次執行：{st.get('LAST') or '—'}")
        self.sched_next_label.configure(text=f"下次執行：{st.get('NEXT') or '—'}")
        res = st.get("RESULT")
        self.sched_result_label.configure(
            text=f"上次結果：{res}（0 = 成功）" if res else "上次結果：—"
        )

    # ---------------- 連結頁 ----------------
    def _build_links_page(self):
        page = tk.Frame(self.content, bg=BG)
        self.pages["links"] = page
        self.page_header(page, "連結", "管理帖文連結（每行一個，只放本週 + 前一週）")

        card = self.card(page)
        arow = tk.Frame(card, bg=CARD)
        arow.pack(fill="x", pady=(0, 6))
        tk.Label(arow, text="帳號：", font=FONT, fg=TEXT, bg=CARD).pack(side="left")
        self.account_combo = ttk.Combobox(
            arow, textvariable=self.account_var, values=[a["name"] for a in self.accounts],
            state="readonly", width=24, font=FONT,
        )
        self.account_combo.pack(side="left", padx=4)
        self.account_combo.bind("<<ComboboxSelected>>", lambda e: self._refresh_links())
        flat_button(arow, "＋新增帳號", TEXT, CARD, "#f0f0f4",
                    self._add_account, border=BORDER).pack(side="left", padx=4)
        flat_button(arow, "改名", TEXT, CARD, "#f0f0f4",
                    self._rename_account, border=BORDER).pack(side="left", padx=4)
        flat_button(arow, "刪除帳號", TEXT, CARD, "#f0f0f4",
                    self._remove_account, border=BORDER).pack(side="left")
        self.links_count = tk.Label(card, text="", font=("Segoe UI", 9, "bold"), fg=MUTED, bg=CARD)
        self.links_count.pack(anchor="w")
        self.links_box = scrolledtext.ScrolledText(
            card, height=18, font=FONT_MONO, relief="flat", bg="#fbfbfd",
            highlightthickness=1, highlightbackground=BORDER, padx=10, pady=8,
        )
        self.links_box.pack(fill="both", expand=True, pady=(8, 0))
        row = tk.Frame(card, bg=CARD)
        row.pack(anchor="w", pady=(10, 0))
        flat_button(row, "儲存連結", "#ffffff", ACCENT, ACCENT_DARK,
                    self._save_links, font=("Segoe UI", 10, "bold")).pack(side="left")
        flat_button(row, "重新整理", TEXT, CARD, "#f0f0f4",
                    self._refresh_links, border=BORDER).pack(side="left", padx=8)
        tk.Label(card, text="提示：xsec_token 會過期，過期後需從 App 重新分享連結。",
                 font=FONT_SMALL, fg=MUTED, bg=CARD).pack(anchor="w", pady=(8, 0))

    def _refresh_links(self):
        acc = self._current_account()
        urls = read_urls(acc["excel_path"])
        self.links_box.delete("1.0", "end")
        self.links_box.insert("1.0", "\n".join(urls))
        self.links_count.configure(text=f"帳號「{acc['name']}」目前 {len(urls)} 條連結")

    def _save_links(self):
        acc = self._current_account()
        text = self.links_box.get("1.0", "end")
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        urls = [ln for ln in lines if ln.startswith("http")]
        skipped = [ln for ln in lines if not ln.startswith("http")]
        if not urls:
            detail = "\n".join(skipped[:5]) if skipped else "請確認每行都是完整網址。"
            messagebox.showwarning("警告", f"沒有有效的連結（需以 http 開頭）。\n\n被忽略的行：\n{detail}")
            return
        try:
            save_urls(acc["excel_path"], urls)
        except PermissionError:
            messagebox.showerror(
                "錯誤",
                "無法寫入 posts.xlsx——檔案可能正被 Excel 開啟。\n請關閉 Excel 後再重試。",
            )
            return
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("錯誤", f"儲存失敗：{e}")
            return
        self._refresh_links()
        msg = f"已儲存 {len(urls)} 條連結"
        if skipped:
            msg += f"\n\n已忽略 {len(skipped)} 行（不是 http 開頭）"
        messagebox.showinfo("完成", msg)

    def _current_account(self) -> dict:
        name = self.account_var.get()
        for a in self.accounts:
            if a.get("name") == name:
                return a
        return {"name": name, "excel_path": str(XLSX_PATH)}

    def _reload_account_combo(self):
        self.account_combo.configure(values=[a["name"] for a in self.accounts])

    def _add_account(self):
        name = simpledialog.askstring("新增帳號", "輸入帳號名稱（例如：佛山科創觀察）：", parent=self)
        if not name or not name.strip():
            return
        name = name.strip()
        if any(a["name"] == name for a in self.accounts):
            messagebox.showwarning("警告", "這個帳號已存在")
            return
        path = str(PROJECT_ROOT / "data" / "accounts" / f"{name}.xlsx")
        save_urls(path, [])
        self.accounts.append({"name": name, "excel_path": path})
        save_accounts(self.accounts)
        # 同步更新資料庫中的帳號名稱（讓該帳號的分析數據跟著改名）
        try:
            db_cfg = Config.load()
            db_conn = storage.connect(db_cfg.db_path)
            db_conn.execute("UPDATE posts SET account=? WHERE account=?", (new, old))
            db_conn.execute("UPDATE summaries SET account=? WHERE account=?", (new, old))
            db_conn.execute("UPDATE runs SET account=? WHERE account=?", (new, old))
            db_conn.commit()
            db_conn.close()
        except Exception:  # noqa: BLE001
            pass
        self._reload_account_combo()
        self.account_var.set(name)
        self._refresh_links()
        messagebox.showinfo("完成", f"已新增帳號「{name}」，請在右邊貼入它的帖文連結後儲存")

    def _remove_account(self):
        name = self.account_var.get()
        if not messagebox.askyesno("刪除帳號", f"確定從系統移除「{name}」？（Excel 檔案會保留）"):
            return
        self.accounts = [a for a in self.accounts if a["name"] != name]
        save_accounts(self.accounts)
        self._reload_account_combo()
        if self.accounts:
            self.account_var.set(self.accounts[0]["name"])
        self._refresh_links()

    def _rename_account(self):
        old = self.account_var.get()
        new = simpledialog.askstring(
            "重新命名帳號", f"把「{old}」改名為：", initialvalue=old, parent=self
        )
        if not new or not new.strip():
            return
        new = new.strip()
        if new == old:
            return
        if any(a["name"] == new for a in self.accounts):
            messagebox.showwarning("警告", "這個帳號名稱已存在")
            return
        for a in self.accounts:
            if a["name"] == old:
                a["name"] = new
                p = Path(a["excel_path"])
                if p.parent.name == "data" and p.name == "posts.xlsx":
                    # legacy 預設檔：搬進帳號自己的 Excel
                    new_path = PROJECT_ROOT / "data" / "accounts" / f"{new}.xlsx"
                    if p.exists() and not new_path.exists():
                        new_path.parent.mkdir(parents=True, exist_ok=True)
                        p.rename(new_path)
                    a["excel_path"] = str(new_path)
                elif p.parent.name == "accounts" and p.stem == old and p.exists():
                    new_path = p.parent / f"{new}.xlsx"
                    p.rename(new_path)
                    a["excel_path"] = str(new_path)
                break
        save_accounts(self.accounts)
        self._reload_account_combo()
        self.account_var.set(new)
        self._refresh_links()
        messagebox.showinfo("完成", f"已改名為「{new}」")

    # ---------------- 說明頁 ----------------
    def _build_help_page(self):
        page = tk.Frame(self.content, bg=BG)
        self.pages["help"] = page
        self.page_header(page, "說明", "快速上手")
        card = self.card(page)
        tk.Label(card, text=(
            "運行\n"
            "  • 測試執行（不寄信）：先確認流程正常\n"
            "  • 正式執行：抓取 → AI 分析 → PDF → 寄信\n"
            "  • 跳過抓取重跑：用現有資料重跑，省 Apify 費用\n\n"
            "設定\n"
            "  填入 API 金鑰、寄件人與收件人後按「儲存設定」。\n\n"
            "連結\n"
            "  每行一個帖文連結，只放本週 + 前一週。\n\n"
            "更多部署細節請見專案根目錄 DEPLOYMENT.md。"
        ), font=FONT, fg=TEXT, bg=CARD, justify="left").pack(anchor="w")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--run":
        # 無視窗模式：供 Windows 排程呼叫（exe --run）
        import run_weekly

        sys.argv = ["run_weekly.py"] + sys.argv[2:]
        try:
            run_weekly.main()
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else 1
            sys.exit(code)
        sys.exit(0)
    try:
        App().mainloop()
    except Exception:  # noqa: BLE001
        import traceback

        try:
            from pathlib import Path

            Path("data/app_error.log").write_text(traceback.format_exc(), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
        raise
