"""寄信：SendGrid / Brevo / Resend API（走 443），SMTP 作為備用。"""
from __future__ import annotations

import base64
import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate
from pathlib import Path

import requests


def _send_outlook(cfg, subject: str, html_body: str, attachments: list[Path]) -> bool:
    """直接用本機 Outlook（COM）寄信，繞過被封鎖的 SMTP 埠。"""
    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    if not cfg.email_to:
        print("[email] 未設定 EMAIL_TO，跳過寄信")
        return False
    try:
        outlook = win32com.client.Dispatch("Outlook.Application")
        mail = outlook.CreateItem(0)  # olMailItem

        sender = (cfg.email_from or cfg.smtp_user or "").lower()
        for acc in outlook.Session.Accounts:
            if sender and acc.SmtpAddress.lower() == sender:
                mail.SendUsingAccount = acc
                break

        mail.To = ";".join(cfg.email_to)
        if cfg.email_cc:
            mail.CC = ";".join(cfg.email_cc)
        mail.Subject = subject
        mail.HTMLBody = html_body
        for p in attachments:
            p = Path(p)
            if p.exists():
                mail.Attachments.Add(str(p.resolve()))
        mail.Send()
        print(f"[email] 已寄出（Outlook）：{subject} → {', '.join(cfg.email_to)}")
        return True
    finally:
        pythoncom.CoUninitialize()


def _send_sendgrid(cfg, subject: str, html_body: str, attachments: list[Path]) -> bool:
    key = cfg.sendgrid_api_key
    if not key:
        return False
    if not cfg.email_to:
        print("[email] 未設定 EMAIL_TO，跳過寄信")
        return False
    payload = {
        "personalizations": [{"to": [{"email": e} for e in cfg.email_to]}],
        "from": {"email": cfg.email_from or cfg.smtp_user or "danielhau@k11byac.com"},
        "subject": subject,
        "content": [{"type": "text/html", "value": html_body}],
    }
    atts = []
    for p in attachments:
        p = Path(p)
        if p.exists():
            atts.append({
                "content": base64.b64encode(p.read_bytes()).decode("ascii"),
                "filename": p.name,
                "type": "text/html" if p.suffix == ".html" else "text/csv",
                "disposition": "attachment",
            })
    if atts:
        payload["attachments"] = atts
    resp = requests.post(
        "https://api.sendgrid.com/v3/mail/send",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json=payload,
        timeout=60,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"SendGrid 寄信失敗 ({resp.status_code}): {resp.text[:300]}")
    print(f"[email] 已寄出（SendGrid）：{subject} → {', '.join(cfg.email_to)}")
    return True


def _send_brevo(cfg, subject: str, html_body: str, attachments: list[Path]) -> bool:
    key = cfg.brevo_api_key
    if not key:
        return False
    if not cfg.email_to:
        print("[email] 未設定 EMAIL_TO，跳過寄信")
        return False
    payload = {
        "sender": {"email": cfg.email_from or cfg.smtp_user or "danielhau@k11byac.com"},
        "to": [{"email": e} for e in cfg.email_to],
        "subject": subject,
        "htmlContent": html_body,
    }
    atts = []
    for p in attachments:
        p = Path(p)
        if p.exists():
            atts.append({
                "content": base64.b64encode(p.read_bytes()).decode("ascii"),
                "name": p.name,
            })
    if atts:
        payload["attachment"] = atts
    resp = requests.post(
        "https://api.brevo.com/v3/smtp/email",
        headers={"api-key": key, "Content-Type": "application/json"},
        json=payload,
        timeout=60,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"Brevo 寄信失敗 ({resp.status_code}): {resp.text[:300]}")
    print(f"[email] 已寄出（Brevo）：{subject} → {', '.join(cfg.email_to)}")
    return True


def _send_resend(cfg, subject: str, html_body: str, attachments: list[Path]) -> bool:
    key = cfg.resend_api_key
    if not key:
        return False
    if not cfg.email_to:
        print("[email] 未設定 EMAIL_TO，跳過寄信")
        return False
    payload = {
        "from": cfg.email_from or cfg.smtp_user or "onboarding@resend.dev",
        "to": cfg.email_to,
        "subject": subject,
        "html": html_body,
    }
    atts = []
    for p in attachments:
        p = Path(p)
        if p.exists():
            atts.append({
                "filename": p.name,
                "content": base64.b64encode(p.read_bytes()).decode("ascii"),
            })
    if atts:
        payload["attachments"] = atts
    resp = requests.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json=payload,
        timeout=60,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"Resend 寄信失敗 ({resp.status_code}): {resp.text[:300]}")
    print(f"[email] 已寄出（Resend）：{subject} → {', '.join(cfg.email_to)}")
    return True


def _send_smtp(cfg, subject: str, html_body: str, attachments: list[Path]) -> bool:
    if not (cfg.smtp_user and cfg.smtp_password):
        print("[email] 未設定 SMTP_USER/SMTP_PASSWORD，跳過寄信")
        return False
    if not cfg.email_to:
        print("[email] 未設定 EMAIL_TO，跳過寄信")
        return False

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg.smtp_user
    msg["To"] = ", ".join(cfg.email_to)
    if cfg.email_cc:
        msg["Cc"] = ", ".join(cfg.email_cc)
    msg["Date"] = formatdate(localtime=True)
    msg.set_content("請用支援 HTML 的郵件客戶端開啟本郵件。")
    msg.add_alternative(html_body, subtype="html")
    for p in attachments:
        p = Path(p)
        if p.exists():
            msg.add_attachment(p.read_bytes(), maintype="application", subtype="octet-stream", filename=p.name)

    context = ssl.create_default_context()
    if cfg.email_use_tls:
        with smtplib.SMTP_SSL(cfg.smtp_host, cfg.smtp_port, context=context, timeout=60) as server:
            server.login(cfg.smtp_user, cfg.smtp_password)
            server.send_message(msg)
    else:
        with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=60) as server:
            server.starttls(context=context)
            server.login(cfg.smtp_user, cfg.smtp_password)
            server.send_message(msg)
    print(f"[email] 已寄出（SMTP）：{subject} → {', '.join(cfg.email_to)}")
    return True


def send(cfg, subject: str, html_body: str, attachments: list[Path]) -> bool:
    """依 EMAIL_PROVIDER 或自動偵測選擇寄信服務（443 API 優先，SMTP 備用）。"""
    provider = (cfg.email_provider or "").strip().lower()
    if not provider:
        for p, fn in (("sendgrid", _send_sendgrid), ("brevo", _send_brevo), ("resend", _send_resend)):
            if getattr(cfg, f"{p}_api_key"):
                provider = p
                break
        if not provider:
            provider = "smtp"

    dispatch = {
        "outlook": _send_outlook,
        "sendgrid": _send_sendgrid,
        "brevo": _send_brevo,
        "resend": _send_resend,
        "smtp": _send_smtp,
    }
    fn = dispatch.get(provider)
    if fn is None:
        raise ValueError(f"不支援的 EMAIL_PROVIDER: {provider}")
    ok = fn(cfg, subject, html_body, attachments)
    if not ok:
        raise RuntimeError(f"EMAIL_PROVIDER={provider} 但未設定對應的 API key/密碼")
    return ok
