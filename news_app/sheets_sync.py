"""可選：把結果同步到 Google Sheets（n8n 原使用的工作表）。"""
from __future__ import annotations

import gspread


def _client(cfg):
    if not cfg.google_service_account_json:
        raise RuntimeError("未設定 GOOGLE_SERVICE_ACCOUNT_JSON")
    return gspread.service_account(filename=cfg.google_service_account_json)


def _worksheet(cfg, gid: int):
    gc = _client(cfg)
    sh = gc.open_by_key(cfg.google_sheet_id)
    return sh.get_worksheet_by_id(gid)


def sync_run(cfg, run: dict, articles: list[dict], directions: list[dict],
             versions: list[dict]) -> None:
    if not cfg.google_enabled or not cfg.google_sheet_id:
        return
    try:
        ws = _worksheet(cfg, cfg.gid_articles)
        rows = [[a["id"], a["topic"], a["title"], a["url"], a["snippet"],
                 a["source"], a["date"], run.get("started_at") or ""] for a in articles]
        if rows:
            ws.append_rows(rows, value_input_option="USER_ENTERED")
    except Exception as e:  # noqa: BLE001
        print(f"[sheets] 文章同步失敗：{e}")

    try:
        ws = _worksheet(cfg, cfg.gid_analysis)
        if run.get("analysis"):
            ws.append_row([run["analysis"]], value_input_option="USER_ENTERED")
    except Exception as e:  # noqa: BLE001
        print(f"[sheets] 分析同步失敗：{e}")

    try:
        ws = _worksheet(cfg, cfg.gid_scripts)
        for v in versions:
            ws.append_row([v.get("content"), v.get("style")], value_input_option="USER_ENTERED")
    except Exception as e:  # noqa: BLE001
        print(f"[sheets] 腳本同步失敗：{e}")

    try:
        ws = _worksheet(cfg, cfg.gid_script_publish)
        if run.get("script_to_publish"):
            ws.append_row([run["script_to_publish"], run.get("style") or ""],
                          value_input_option="USER_ENTERED")
    except Exception as e:  # noqa: BLE001
        print(f"[sheets] 定稿同步失敗：{e}")
