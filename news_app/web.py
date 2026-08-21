"""本機審批表單伺服器：寄信時附上網址，使用者用瀏覽器填寫並送出。

對應 n8n Outlook sendAndWait 的「customForm」體驗：
方向審批 = 單選 方向1/2/3/拒絕全部 + 意見文字區；
腳本審批 = 單選 反差型/數據型/判斷型/拒絕全部 + 意見文字區。
"""
from __future__ import annotations

import html
import hmac
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import pipeline, store


def approval_url(cfg, run_id: int) -> str:
    base = (cfg.form_public_url or f"http://127.0.0.1:{cfg.web_port}").rstrip("/")
    url = f"{base}/approve/{run_id}"
    if cfg.form_token:
        url += f"?token={cfg.form_token}"
    return url


def _page(title: str, body: str, refresh: int | None = None) -> str:
    meta = f'<meta http-equiv="refresh" content="{refresh}">' if refresh else ""
    return f"""<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{meta}
<title>{html.escape(title)}</title>
<style>
:root{{--bg:#f4f6f9;--card:#fff;--text:#0f172a;--muted:#64748b;--border:#e2e8f0;--accent:#2563eb;--accent-soft:#eff6ff;--danger:#dc2626;--ok:#15803d}}
*{{box-sizing:border-box}}
body{{font-family:"Segoe UI","Microsoft JhengHei","PingFang TC",sans-serif;background:var(--bg);margin:0;padding:24px 16px 48px;color:var(--text);line-height:1.65}}
.card{{background:var(--card);max-width:720px;margin:0 auto;border-radius:16px;padding:28px 24px 32px;box-shadow:0 1px 2px rgba(15,23,42,.06),0 8px 24px rgba(15,23,42,.04)}}
h1{{font-size:22px;margin:0 0 8px;letter-spacing:-.02em}}
.lead{{color:var(--muted);margin:0 0 20px;font-size:14px}}
.opt{{display:block;border:2px solid var(--border);border-radius:12px;padding:14px 16px;margin:0 0 12px;cursor:pointer;transition:border-color .15s,background .15s,box-shadow .15s}}
.opt:hover{{border-color:#93c5fd}}
.opt:has(input:checked){{border-color:var(--accent);background:var(--accent-soft);box-shadow:0 0 0 3px rgba(37,99,235,.15)}}
.opt.danger:has(input:checked){{border-color:var(--danger);background:#fef2f2;box-shadow:0 0 0 3px rgba(220,38,38,.12)}}
.opt input{{accent-color:var(--accent);margin-right:8px;width:18px;height:18px}}
.opt-title{{font-weight:650;font-size:15px}}
.src{{color:var(--muted);font-size:13px}}
.src a{{color:var(--accent);text-decoration:none}}
.src a:hover{{text-decoration:underline}}
label.field{{display:block;color:var(--muted);font-size:13px;margin:16px 0 6px}}
textarea{{width:100%;min-height:88px;border:1px solid var(--border);border-radius:10px;padding:10px 12px;font-family:inherit;font-size:15px}}
textarea:focus{{outline:none;border-color:var(--accent);box-shadow:0 0 0 3px rgba(37,99,235,.15)}}
.actions{{position:sticky;bottom:0;background:linear-gradient(transparent,var(--card) 28%);padding-top:16px;margin-top:8px}}
button{{background:var(--accent);color:#fff;border:0;border-radius:10px;padding:14px 20px;font-size:16px;font-weight:650;cursor:pointer;width:100%;min-height:48px}}
button:hover{{background:#1d4ed8}}
button:disabled{{opacity:.55;cursor:not-allowed}}
.badge{{display:inline-block;padding:3px 10px;border-radius:999px;font-size:12px;font-weight:600;color:#fff}}
.b-ok{{background:var(--ok)}}.b-wait{{background:#b45309}}.b-fail{{background:var(--danger)}}
pre{{background:#f8fafc;padding:12px 14px;border-radius:10px;white-space:pre-wrap;font-family:Consolas,ui-monospace,monospace;font-size:13.5px;max-height:280px;overflow:auto}}
</style></head><body><div class="card">{body}</div>
<script>
document.querySelectorAll("form").forEach(function(f){{
  f.addEventListener("submit",function(){{
    var b=f.querySelector("button[type=submit],button:not([type])");
    if(b){{b.disabled=true;b.textContent="送出中…";}}
  }});
}});
</script>
</body></html>"""


def _status_badge(status: str) -> str:
    labels = {
        pipeline.STATUS_AWAIT_DIRECTION: ("等待方向審批", "b-wait"),
        pipeline.STATUS_AWAIT_SCRIPT: ("等待腳本審批", "b-wait"),
        pipeline.STATUS_RUNNING: ("處理中…", "b-wait"),
        pipeline.STATUS_DONE: ("已完成", "b-ok"),
        pipeline.STATUS_FAILED: ("失敗", "b-fail"),
    }
    label, cls = labels.get(status, (status, "b-wait"))
    return f'<span class="badge {cls}">{html.escape(label)}</span>'


def _esc(s) -> str:
    return html.escape(str(s or ""))


def _direction_form(cfg, run) -> str:
    conn = store.connect_from_cfg(cfg)
    run_id = run["id"]
    directions = store.get_directions(conn, run_id)
    conn.close()
    action = f"/approve/{run_id}" + (f"?token={cfg.form_token}" if cfg.form_token else "")
    body = (
        f"<h1>選擇分析方向</h1>"
        f"<p>{_status_badge(run['status'])}　run #{run_id}</p>"
        f'<p class="lead" style="margin-top:8px"><strong>新聞全景摘要</strong><br>'
        f"{_esc(run.get('news_summary'))}</p>"
        f'<p class="lead">點選一張卡片，再按下方送出。</p>'
    )
    for d in directions:
        srcs = "".join(
            f'<li><a href="{_esc(s.get("url"))}" target="_blank">{_esc(s.get("title"))}</a></li>'
            for s in d.get("sources") or []
        )
        body += (
            f'<label class="opt"><span class="opt-title">'
            f'<input type="radio" name="decision" value="{d["idx"]}"> '
            f'方向 {d["idx"]}：{_esc(d["title"])}</span>'
            f'<div>{_esc(d.get("description"))}</div>'
            f'<div class="src"><ul>{srcs}</ul></div></label>'
        )
    body += (
        '<label class="opt danger"><span class="opt-title">'
        '<input type="radio" name="decision" value="reject"> 拒絕全部，請 AI 重做</span></label>'
        '<label class="field">修改意見（拒絕時填寫）</label>'
        '<textarea name="comment" placeholder="例如：方向太散，請聚焦新能源…"></textarea>'
        '<div class="actions"><button type="submit">送出審批</button></div>'
    )
    return _page("方向選擇", f'<form method="post" action="{action}">{body}</form>')


def _script_form(cfg, run) -> str:
    conn = store.connect_from_cfg(cfg)
    run_id = run["id"]
    versions = store.get_versions(conn, run_id)
    conn.close()
    action = f"/approve/{run_id}" + (f"?token={cfg.form_token}" if cfg.form_token else "")
    body = (
        f"內容審核：小紅書草稿</h1>"
        f"<p>{_status_badge(run['status'])}　run #{run_id}</p>"
        f'<p class="lead">點選要發布的版本，再按送出。拒絕時請填修改意見。</p>'
    )
    # keep leading h1 — the line above accidentally dropped it; reconstruct cleanly
    body = (
        f"<h1>內容審核：小紅書草稿</h1>"
        f"<p>{_status_badge(run['status'])}　run #{run_id}</p>"
        f'<p class="lead">點選要發布的版本，再按送出。拒絕時請填修改意見。</p>'
    )
    for v in versions:
        body += (
            f'<label class="opt"><span class="opt-title">'
            f'<input type="radio" name="decision" value="{v["idx"]}"> '
            f'版本 {v["idx"]}：{_esc(v["style"])}</span>'
            f'<pre>{_esc(v["content"])}</pre></label>'
        )
    body += (
        '<label class="opt danger"><span class="opt-title">'
        '<input type="radio" name="decision" value="reject"> 拒絕全部，請 AI 重做</span></label>'
        '<label class="field">修改意見（拒絕時填寫）</label>'
        '<textarea name="comment" placeholder="例如：語氣太硬，請更生活化…"></textarea>'
        '<div class="actions"><button type="submit">送出審批</button></div>'
    )
    return _page("腳本審核", f'<form method="post" action="{action}">{body}</form>')


def _status_page(cfg, run) -> str:
    run_id = run.get("id") or 0
    qs = f"?token={cfg.form_token}" if cfg.form_token else ""
    lines = [f"<h1>審批結果（run #{run_id}）</h1>", f"<p>{_status_badge(run.get('status', ''))}</p>"]
    status = run.get("status")
    if status == pipeline.STATUS_AWAIT_DIRECTION:
        lines.append('<p>還在等方向審批——請回到上一頁填寫表單，或重新整理。</p>')
    elif status == pipeline.STATUS_AWAIT_SCRIPT:
        lines.append('<p>方向已批准，AI 正在生成深度分析與腳本…（通常 4–6 分鐘）</p>')
        lines.append(f'<p><a href="/approve/{run_id}{qs}">刷新表單</a>，完成後會變成「腳本審批」。</p>')
    elif status == pipeline.STATUS_DONE:
        lines.append(f"<p><strong>Tagline：</strong>{_esc(run.get('tagline'))}</p>")
        lines.append(f"<p><strong>Image Prompt：</strong></p><pre>{_esc(run.get('image_prompt'))}</pre>")
        lines.append("<p>最終「Image Prompt」信已寄出。</p>")
    elif status == pipeline.STATUS_FAILED:
        lines.append(f"<p class='src'>錯誤：{_esc(run.get('error'))}</p>")
    else:
        lines.append("<p>處理中…請稍候（頁面將自動重新整理）。</p>")
    return _page("審批結果", "".join(lines), refresh=5 if status == pipeline.STATUS_RUNNING else None)


class _Handler(BaseHTTPRequestHandler):
    server_version = "FoshanNewsForm/1.0"

    def _cfg(self):
        return self.server.cfg  # type: ignore[attr-defined]

    def _token_ok(self, parsed) -> bool:
        cfg = self._cfg()
        if not cfg.form_token:
            return True
        qs = parse_qs(parsed.query)
        got = (qs.get("token") or [""])[0]
        return hmac.compare_digest(got, cfg.form_token)

    def _send(self, status: int, body: str):
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802
        parsed = urlparse(self.path)
        parts = parsed.path.strip("/").split("/")
        if len(parts) == 2 and parts[0] == "approve" and parts[1].isdigit():
            if not self._token_ok(parsed):
                self._send(403, _page("無權限", "<h1>連結無效</h1><p>網址缺少或帶錯安全碼，請從 Email 重新點開。</p>"))
                return
            run_id = int(parts[1])
            conn = store.connect_from_cfg(self._cfg())
            run = store.get_run(conn, run_id)
            conn.close()
            if not run:
                self._send(404, _page("找不到", "<h1>找不到該執行</h1>"))
                return
            if run["status"] == pipeline.STATUS_AWAIT_DIRECTION:
                self._send(200, _direction_form(self._cfg(), run))
            elif run["status"] == pipeline.STATUS_AWAIT_SCRIPT:
                self._send(200, _script_form(self._cfg(), run))
            else:
                self._send(200, _status_page(self._cfg(), run))
            return
        self._send(200, _page("小紅書新聞AI", "<h1>小紅書新聞AI</h1><p>審批表單伺服器運作中。</p>"))

    def do_POST(self):  # noqa: N802
        parsed = urlparse(self.path)
        parts = parsed.path.strip("/").split("/")
        if not (len(parts) == 2 and parts[0] == "approve" and parts[1].isdigit()):
            self._send(404, _page("找不到", "<h1>找不到該執行</h1>"))
            return
        if not self._token_ok(parsed):
            self._send(403, _page("無權限", "<h1>連結無效</h1><p>網址缺少或帶錯安全碼，請從 Email 重新點開。</p>"))
            return
        run_id = int(parts[1])
        length = int(self.headers.get("Content-Length") or 0)
        form = parse_qs(self.rfile.read(length).decode("utf-8", errors="replace"))
        decision = (form.get("decision") or [""])[0].strip()
        comment = (form.get("comment") or [""])[0].strip()
        if not decision:
            self._send(400, _page("錯誤", "<h1>請選擇一個選項</h1>"))
            return

        cfg = self._cfg()
        threading.Thread(target=self._apply, args=(cfg, run_id, decision, comment), daemon=True).start()
        conn = store.connect_from_cfg(cfg)
        run = store.get_run(conn, run_id)
        conn.close()
        self._send(200, _status_page(self._cfg(), run or {}))

    @staticmethod
    def _apply(cfg, run_id: int, decision: str, comment: str):
        conn = store.connect_from_cfg(cfg)
        try:
            run = store.get_run(conn, run_id)
            if run["status"] == pipeline.STATUS_AWAIT_DIRECTION:
                pipeline.decide_direction(cfg, conn, run_id, decision, comment, notify=True)
            elif run["status"] == pipeline.STATUS_AWAIT_SCRIPT:
                pipeline.decide_script(cfg, conn, run_id, decision, comment, notify=True)
            else:
                print(f"[form] run {run_id} 狀態 {run['status']}，跳過")
        except Exception as e:  # noqa: BLE001
            print(f"[form] 審批失敗：{e}")
        finally:
            conn.close()

    def log_message(self, fmt, *args):  # 安靜一點
        print("[form] " + (fmt % args))


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, addr, handler, cfg):
        super().__init__(addr, handler)
        self.cfg = cfg


def start_server(cfg) -> tuple[ThreadingHTTPServer, threading.Thread]:
    """啟動本機表單伺服器（背景執行緒）。"""
    httpd = _Server(("127.0.0.1", cfg.web_port), _Handler, cfg)
    t = threading.Thread(target=httpd.serve_forever, daemon=True, name="news-form-server")
    t.start()
    print(f"[form] 審批表單伺服器：http://127.0.0.1:{cfg.web_port}/approve/<run_id>")
    return httpd, t
