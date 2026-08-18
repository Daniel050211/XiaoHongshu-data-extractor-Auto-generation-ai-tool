"""寄信：重用 xhs_report.emailer（Outlook / SendGrid / Brevo / Resend / SMTP）。"""
from __future__ import annotations

import dataclasses
from pathlib import Path

from xhs_report.config import Config as XhsConfig
from xhs_report import emailer


def send(cfg, subject: str, html_body: str, attachments: list[Path | str] | None = None,
         recipients: list[str] | None = None) -> bool:
    """以既有寄信設定送出郵件。回傳是否寄出。"""
    try:
        xcfg = XhsConfig.load()
    except Exception:
        xcfg = None
    if xcfg is None:
        return False
    if not cfg.email_to and not xcfg.email_to:
        return False
    if not cfg.email_to:
        cfg.email_to = xcfg.email_to
    if recipients:
        xcfg = dataclasses.replace(xcfg, email_to=list(recipients))
    try:
        return emailer.send(xcfg, subject, html_body, [Path(p) for p in (attachments or [])])
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"寄信失敗：{e}") from e
