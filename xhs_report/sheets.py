"""從 Excel 或 Google Sheets 讀取帖文連結。"""
from __future__ import annotations

import csv
import io
import re
from pathlib import Path

import requests

URL_HINTS = ("url", "連結", "鏈接", "link", "網址")
URL_RE = re.compile(r"https?://\S+", re.I)


def _looks_like_url(s: str) -> bool:
    return bool(s and URL_RE.match(str(s).strip()))


def _url_column(headers: list) -> int:
    for i, h in enumerate(headers):
        hl = str(h or "").strip().lower()
        if any(k in hl for k in URL_HINTS):
            return i
    return 0


def _extract_urls(rows: list[list]) -> list[str]:
    if not rows:
        return []
    col = _url_column(rows[0])
    urls = []
    for row in rows[1:]:
        if col < len(row) and _looks_like_url(row[col]):
            urls.append(str(row[col]).strip())
    return urls


def read_excel(path: str | Path, sheet_name: str | None = None) -> list[str]:
    import openpyxl

    if not Path(path).exists():
        return []
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb[sheet_name] if sheet_name else wb.active
    rows = [[c for c in row] for row in ws.iter_rows(values_only=True)]
    wb.close()
    return _extract_urls(rows)


def read_google_public(sheet_id: str, gid: int = 0) -> list[str]:
    """公開（知道連結即可檢視）的 Google Sheet：直接匯出 CSV，不需金鑰。"""
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"
    if gid:
        url += f"&gid={gid}"
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    text = resp.content.decode("utf-8-sig", errors="replace")
    rows = list(csv.reader(io.StringIO(text)))
    return _extract_urls(rows)


def read_google_private(sheet_id: str, creds_json_path: str, gid: int = 0) -> list[str]:
    """私人 Google Sheet：需要 service account JSON，並把該帳號加入分享名單。"""
    import gspread

    gc = gspread.service_account(filename=creds_json_path)
    sh = gc.open_by_key(sheet_id)
    ws = sh.get_worksheet(gid) if gid else sh.sheet1
    rows = ws.get_all_values()
    return _extract_urls(rows)


def read_post_urls(cfg) -> list[str]:
    if cfg.link_type == "excel":
        return read_excel(cfg.excel_path)
    if cfg.link_type == "google":
        if cfg.google_service_account_json:
            return read_google_private(cfg.google_sheet_id, cfg.google_service_account_json, cfg.google_gid)
        if cfg.google_sheet_id:
            return read_google_public(cfg.google_sheet_id, cfg.google_gid)
        raise ValueError("link_source.type=google 但未設定 google_sheet_id")
    raise ValueError(f"不支援的 link_source.type: {cfg.link_type}")
