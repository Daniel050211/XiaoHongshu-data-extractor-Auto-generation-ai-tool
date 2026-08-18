"""Email 回覆監看：使用者直接回覆審批信，系統自動解析並繼續流程。

優先使用本機已登入的 Outlook（COM，讀取收件匣）；若 .env 有設定
EMAIL_IMAP_HOST / USER / PASSWORD，則改用 IMAP（適合 Gmail / 個人 Outlook）。
"""
from __future__ import annotations

import email
import imaplib
import re
import threading
import time
from email.header import decode_header

from . import pipeline, store

SUBJECT_RUN_RE = re.compile(r"#(\d+)")
FIRST_LINE_RE = re.compile(
    r"^(方向\s*[123]|版本\s*[123]|[123]\s*[、.．,，]?$|"
    r"拒絕全部|拒绝全部|reject|反差型|數據型|数据型|判斷型|判断型)",
    re.I,
)

REJECT_WORDS = ("拒絕", "拒绝", "reject")
QUOTE_MARKERS = (
    "-----Original Message-----", "-----原始郵件-----", "From:", "寄件者:", "收件者:",
    "Sent:", "傳送日期:", "Date:", "To:", "Cc:", "回覆:", "Reply:", "----- Forwarded",
    "發件人:", "主題:", "Subject:",
)


def clean_body(text: str) -> str:
    """去掉引文、簽名檔、HTML 標籤，只留回覆本文。"""
    if not text:
        return ""
    if text.lstrip().startswith("<"):
        text = re.sub(r"<[^>]+>", "\n", text)
    lines = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith(">"):
            continue
        if any(line.startswith(m) for m in QUOTE_MARKERS):
            break
        if line in ("--", "---"):
            break
        lines.append(line)
    return "\n".join(lines)


def parse_reply(subject: str, body: str) -> dict | None:
    """從主旨與內文解析出 (run_id, decision, comment)。回傳 None 表示無法識別。"""
    m = SUBJECT_RUN_RE.search(subject or "")
    if not m:
        return None
    run_id = int(m.group(1))
    text = clean_body(body or "")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return None
    first = lines[0].strip().lower()
    m = FIRST_LINE_RE.match(first)
    if not m:
        return None
    token = m.group(1)
    token = token.strip(" 、.．,，")
    if any(w in token for w in REJECT_WORDS):
        decision = "reject"
    else:
        decision = {
            "方向1": "1", "方向2": "2", "方向3": "3",
            "版本1": "1", "版本2": "2", "版本3": "3",
            "1": "1", "2": "2", "3": "3",
            "反差型": "1", "數據型": "2", "数据型": "2",
            "判斷型": "3", "判断型": "3",
        }.get(token, "")
        if not decision:
            return None
    comment = "\n".join(lines[1:]).strip()
    return {"run_id": run_id, "decision": decision, "comment": comment}


def is_self_sent_approval(body: str, run: dict) -> bool:
    """自己寄出的審批信會同時出現在自己的收件匣，不能當成回覆。"""
    if not run:
        return False
    stored = run.get("direction_email") or run.get("script_email") or ""
    if not stored:
        return False
    return clean_body(body) == clean_body(stored)


def _process_reply(cfg, conn, parsed: dict) -> int | None:
    """依 run 狀態執行審批。回傳 run_id 或 None（無法處理）。"""
    run_id = parsed["run_id"]
    run = store.get_run(conn, run_id)
    if not run:
        return None
    try:
        if run["status"] == pipeline.STATUS_AWAIT_DIRECTION:
            pipeline.decide_direction(cfg, conn, run_id, parsed["decision"],
                                      parsed["comment"], notify=True)
        elif run["status"] == pipeline.STATUS_AWAIT_SCRIPT:
            pipeline.decide_script(cfg, conn, run_id, parsed["decision"],
                                   parsed["comment"], notify=True)
        else:
            return None
        store.add_event(conn, run_id,
                        f"Email 回覆已處理：{parsed['decision']}（comment={parsed['comment'] or '無'}）")
        return run_id
    except Exception as e:  # noqa: BLE001
        store.add_event(conn, run_id, f"Email 回覆處理失敗：{e}", level="error")
        return None


def watch_outlook_once(cfg, conn) -> list[int]:
    """用本機 Outlook 讀取未讀回覆並處理。"""
    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    processed = []
    try:
        outlook = win32com.client.Dispatch("Outlook.Application")
        ns = outlook.GetNamespace("MAPI")
        inbox = ns.GetDefaultFolder(6)  # olFolderInbox
        items = inbox.Items
        items.Sort("[ReceivedTime]", True)
        for i in range(1, min(80, items.Count) + 1):
            try:
                msg = items.Item(i)
                if not getattr(msg, "UnRead", False):
                    continue
                parsed = parse_reply(str(getattr(msg, "Subject", "") or ""),
                                     str(getattr(msg, "Body", "") or ""))
                if not parsed:
                    continue
                run = store.get_run(conn, parsed["run_id"])
                if is_self_sent_approval(str(getattr(msg, "Body", "") or ""), run):
                    msg.UnRead = False  # 自己寄的信，標已讀並跳過
                    continue
                if _process_reply(cfg, conn, parsed):
                    processed.append(parsed["run_id"])
                    msg.UnRead = False
            except Exception as e:  # noqa: BLE001
                print(f"[mailwatch] 處理郵件失敗：{e}")
    finally:
        pythoncom.CoUninitialize()
    return processed


def watch_imap_once(cfg, conn) -> list[int]:
    """用 IMAP 讀取未讀回覆（需 .env 設定 EMAIL_IMAP_*）。"""
    host = cfg.mail_imap_host
    user = cfg.mail_imap_user
    password = cfg.mail_imap_password
    if not (host and user and password):
        return []
    processed = []
    try:
        mail = imaplib.IMAP4_SSL(host, 993)
        mail.login(user, password)
        mail.select("INBOX")
        _, data = mail.search(None, "UNSEEN")
        for num in data[0].split():
            _, msg_data = mail.fetch(num, "(RFC822)")
            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)
            subject = _decode_mime_header(msg.get("Subject", ""))
            body = _get_text(msg)
            parsed = parse_reply(subject, body)
            if not parsed:
                continue
            run = store.get_run(conn, parsed["run_id"])
            if is_self_sent_approval(body, run):
                mail.store(num, "+FLAGS", "\\Seen")
                continue
            if _process_reply(cfg, conn, parsed):
                processed.append(parsed["run_id"])
                mail.store(num, "+FLAGS", "\\Seen")
        mail.logout()
    except Exception as e:  # noqa: BLE001
        print(f"[mailwatch] IMAP 讀取失敗：{e}")
    return processed


def _decode_mime_header(value: str) -> str:
    parts = decode_header(value or "")
    return "".join(
        part.decode(charset or "utf-8", errors="replace") if isinstance(part, bytes) else part
        for part, charset in parts
    )


def _get_text(msg) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                try:
                    return part.get_content()
                except Exception:  # noqa: BLE001
                    continue
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                try:
                    return part.get_content()
                except Exception:  # noqa: BLE001
                    continue
    try:
        return msg.get_content()
    except Exception:  # noqa: BLE001
        return str(msg.get_payload() or "")


def start_watcher(cfg, interval: int = 45, stop_event: threading.Event | None = None):
    """背景執行緒：每隔 interval 秒檢查一次信箱。"""

    def loop():
        conn = store.connect(cfg.db_path)
        try:
            while not (stop_event and stop_event.is_set()):
                try:
                    done = watch_outlook_once(cfg, conn)
                    if not done:
                        done = watch_imap_once(cfg, conn)
                    if done:
                        print(f"[mailwatch] 已處理 Email 回覆：run {done}")
                except Exception as e:  # noqa: BLE001
                    print(f"[mailwatch] 檢查失敗：{e}")
                stop_event.wait(interval) if stop_event else time.sleep(interval)
        finally:
            conn.close()

    t = threading.Thread(target=loop, daemon=True, name="news-mail-watcher")
    t.start()
    print(f"[mailwatch] Email 回覆監看已啟動（每 {interval} 秒）")
    return t
