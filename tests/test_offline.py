"""離線測試：不需要 Apify / AI / 電郵，驗證週次邏輯與報告產生。"""
from __future__ import annotations

import glob
import json
import sys
from datetime import date
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from xhs_report import report, sheets, storage, weeks
from xhs_report.config import Config
from xhs_report.scrape import load_fixture


def test_weeks():
    anchor = date(2026, 7, 1)
    assert weeks.week_for_date(date(2026, 7, 1), anchor) == 1
    assert weeks.week_for_date(date(2026, 7, 7), anchor) == 1
    assert weeks.week_for_date(date(2026, 7, 8), anchor) == 2
    assert weeks.week_for_date(date(2026, 7, 21), anchor) == 3
    assert weeks.week_of(2, anchor).label == "W2（7/8–7/14）"
    assert weeks.latest_complete_week(date(2026, 7, 17), anchor) == 2
    assert weeks.latest_complete_week(date(2026, 7, 24), anchor) == 3


def test_excel():
    cfg = Config.load()
    urls = sheets.read_post_urls(cfg)
    assert len(urls) >= 3
    assert all(u.startswith("http") for u in urls)


def test_pipeline_offline(tmp_db="data/test_xhs.db"):
    cfg = Config.load()
    cfg.ai_api_key = ""          # 強制離線：不呼叫真實 AI
    cfg.resend_api_key = ""      # 強制離線：不寄信
    cfg.export_pdf = False       # 強制離線：不呼叫 Edge 轉 PDF
    records = load_fixture("data/fixtures/synthetic.json")
    assert len(records) == 6

    conn = storage.connect(tmp_db)
    for r in records:
        storage.upsert_post(conn, r, __import__("datetime").datetime.now().astimezone())
    conn.commit()

    from datetime import datetime
    from xhs_report import analysis

    anchor = date.fromisoformat(cfg.anchor)
    run_date = date(2026, 7, 17)
    run_at = datetime.now().astimezone()
    target_n, ref_n = 2, 1
    target_week = weeks.week_of(target_n, anchor)
    ref_week = weeks.week_of(ref_n, anchor)

    enriched = []
    for r in storage.all_posts(conn):
        age = None
        if r.get("publish_time_utc"):
            pub = datetime.fromisoformat(r["publish_time_utc"])
            age = max(0.0, (run_at - pub).total_seconds() / 3600.0)
        r["age_hours"] = age
        r["scrape_count"] = int(r.get("scrape_count") or 1)
        r["maturity"] = "complete" if r["scrape_count"] >= 2 else "preliminary"
        r["week_number"] = weeks.week_for_date(date.fromisoformat(r["publish_date"]), anchor)
        enriched.append(r)

    target_rows = [r for r in enriched if r["week_number"] == target_n]
    ref_rows = [r for r in enriched if r["week_number"] == ref_n]
    assert len(target_rows) == 3 and len(ref_rows) == 3

    ai = analysis.analyze(cfg, str(target_week), analysis.rows_for_ai(target_rows),
                          str(ref_week), analysis.rows_for_ai(ref_rows), "（無）")
    assert ai["status"] == "dry-run"

    stats = report.week_stats(target_rows)
    assert stats["likes_median"] > 0

    trend_rows = []
    for n in sorted({r["week_number"] for r in enriched}):
        s = report.week_stats([r for r in enriched if r["week_number"] == n])
        s["label"] = str(weeks.week_of(n, anchor))
        trend_rows.append(s)

    html_path, csv_path, pdf_path = report.generate(cfg, target_rows, ref_rows, target_week, ref_week, ai, trend_rows, run_date)
    assert pdf_path is None
    html = html_path.read_text(encoding="utf-8")
    assert "執行摘要" in html
    assert "AI 分析摘要" in html
    assert "本週 vs 基準週" in html
    assert "各週趨勢" in html
    assert "帖文明細" in html
    assert csv_path and csv_path.exists()
    storage.log_run(conn, run_at, run_date.isoformat(), target_n, ref_n, "ok")
    conn.close()
    print("OK: 全部離線測試通過")


if __name__ == "__main__":
    test_weeks()
    test_excel()
    test_pipeline_offline()
