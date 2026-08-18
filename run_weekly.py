"""每週小紅書分析主程式（支援多帳號）。

用法：
  python run_weekly.py                                  # 處理全部帳號
  python run_weekly.py --account 帳號名                  # 只處理單一帳號
  python run_weekly.py --dry-run                        # 不寄信
  python run_weekly.py --run-date 2026-07-17            # 指定執行日期（測試用）
  python run_weekly.py --from-json data/fixtures/sample.json   # 從存檔的 actor 輸出跑（離線測試）
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

from xhs_report import analysis, emailer, report, scrape, sheets, storage, weeks
from xhs_report.config import Config

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except AttributeError:
    pass


def _format_previous_summary(s: dict | None) -> str:
    if not s:
        return "（無）"
    sections = s.get("sections")
    if isinstance(sections, str):
        return sections
    if isinstance(sections, dict):
        return "\n".join(f"{k}：{v}" for k, v in sections.items())
    return "（無）"


class _NoReferenceWeek:
    number = 0
    label = "（無，首次執行）"

    def __str__(self):
        return self.label


def _enrich(conn, run_at: datetime, anchor: date, cfg) -> list[dict]:
    """從資料庫讀出全部帖文，補上 age / maturity / week_number。"""
    enriched = []
    for r in storage.all_posts(conn):
        age = None
        if r.get("publish_time_utc"):
            try:
                pub = datetime.fromisoformat(r["publish_time_utc"])
                age = max(0.0, (run_at - pub).total_seconds() / 3600.0)
            except ValueError:
                pass
        r["age_hours"] = age
        r["scrape_count"] = int(r.get("scrape_count") or 1)
        r["maturity"] = "complete" if r["scrape_count"] >= 2 else "preliminary"
        if r.get("publish_date"):
            try:
                r["week_number"] = weeks.week_for_date(date.fromisoformat(r["publish_date"]), anchor, cfg.block_size_days)
            except ValueError:
                r["week_number"] = None
        enriched.append(r)
    return enriched


def _slug(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9\u4e00-\u9fa5]+", "_", str(name)).strip("_")
    return s or "account"


def run_account(cfg, conn, account: dict, args, run_date: date, run_at: datetime,
                anchor: date, target_week_n: int, ref_week_n: int,
                target_week, ref_week) -> tuple[str, str]:
    """處理單一帳號。回傳 (status, error_message)。status: ok | no_links | error。"""
    name = account.get("name") or "default"
    excel_path = account.get("excel_path") or cfg.excel_path
    print(f"\n=== {name} 小紅書週報（執行日 {run_date}）===")
    print(f"本週目標：{target_week}｜基準週：{ref_week}")

    try:
        # 1. 讀取帖文連結
        if args.skip_scrape:
            urls = []
            print("[1/6] --skip-scrape：跳過連結讀取與抓取")
        elif args.from_json:
            urls = []
            print("[1/6] 使用離線 JSON")
        else:
            urls = sheets.read_excel(excel_path)
            if not urls:
                print(f"[1/6] 帳號「{name}」沒有連結（{excel_path}），跳過此帳號")
                return "no_links", ""
            complete_ids = storage.complete_note_ids(conn)
            filtered, skipped = [], 0
            for u in urls:
                nid = scrape.note_id_from_url(u)
                if nid and nid in complete_ids:
                    skipped += 1
                else:
                    filtered.append(u)
            if skipped:
                print(f"[1/6] 已跳過 {skipped} 條「完整」狀態的連結（不重複抓取，節省費用）")
            urls = filtered
            if not urls:
                print("[1/6] 所有連結都已是「完整」狀態，將用現有資料重跑報告")
            else:
                print(f"[1/6] 讀到 {len(urls)} 個待抓連結")

        # 2. 抓取
        if args.skip_scrape:
            records = []
            print("[2/6] 跳過 Apify 抓取，使用資料庫現有資料")
        elif args.from_json:
            records = scrape.load_fixture(args.from_json)
        else:
            records = scrape.run_actor(cfg, urls) if urls else []
        if urls and not args.skip_scrape and not records:
            print("⚠ 本次沒有抓到新帖文（可能連結失效/額度不足），改用現有資料產生報告")
        if not args.skip_scrape and records:
            print(f"[2/6] 抓取並解析 {len(records)} 篇帖文")

        # 3. 儲存（標記帳號）+ 標記週次與成熟度
        if records:
            for rec in records:
                rec["account"] = name
                storage.upsert_post(conn, rec, run_at)
            conn.commit()

        enriched = [r for r in _enrich(conn, run_at, anchor, cfg) if (r.get("account") or "") == name]
        target_rows = [r for r in enriched if r.get("week_number") == target_week_n]
        ref_rows = [r for r in enriched if r.get("week_number") == ref_week_n]
        prelim_n = sum(1 for r in target_rows if r.get("maturity") == "preliminary")
        print(f"[3/6] 本週 {len(target_rows)} 篇（其中 {prelim_n} 篇初步）、基準週 {len(ref_rows)} 篇")
        if not target_rows:
            print("⚠ 本週沒有帖文，報告將只有基準週資料")

        # 4. AI 分析（帶上「上一週總結」與成長比較）
        prev_summary = storage.load_summary(conn, name, ref_week_n)
        growth_rows = []
        seen = set()
        for r in target_rows + ref_rows:
            if r["note_id"] in seen:
                continue
            seen.add(r["note_id"])
            snaps = storage.snapshot_series(conn, r["note_id"])
            if len(snaps) >= 2:
                growth_rows.append({
                    "week_number": r.get("week_number"),
                    "week_label": f"W{r.get('week_number')}" if r.get("week_number") else "?",
                    "title": r.get("title") or "",
                    "publish_date": r.get("publish_date"),
                    "first": {k: snaps[0].get(k, 0) for k in ("like_count", "collect_count", "comment_count", "share_count")},
                    "last": {k: snaps[-1].get(k, 0) for k in ("like_count", "collect_count", "comment_count", "share_count")},
                })
        ai_result = analysis.analyze(
            cfg,
            str(target_week),
            analysis.rows_for_ai(target_rows),
            str(ref_week),
            analysis.rows_for_ai(ref_rows),
            _format_previous_summary(prev_summary),
            growth_context=json.dumps(growth_rows, ensure_ascii=False) if growth_rows else "",
        )
        storage.save_summary(conn, name, target_week_n, ai_result, run_at)
        conn.commit()
        print(f"[4/6] AI 分析完成（{ai_result.get('status')}）")

        # 5. 報告
        trend_rows = []
        for n in sorted({r["week_number"] for r in enriched if r.get("week_number")}):
            wk_rows = [r for r in enriched if r.get("week_number") == n]
            stats = report.week_stats(wk_rows)
            stats["label"] = str(weeks.week_of(n, anchor, cfg.block_size_days))
            trend_rows.append(stats)
        html_path, csv_path, pdf_path = report.generate(
            cfg, target_rows, ref_rows, target_week, ref_week, ai_result, trend_rows,
            run_date, growth_rows=growth_rows, account_name=name,
        )
        print(f"[5/6] 報告已產生：{html_path}")
        if pdf_path:
            print(f"       PDF（手機版）：{pdf_path}")
        if csv_path:
            print(f"       CSV：{csv_path}")

        # 6. 寄信
        if args.dry_run:
            print("[6/6] --dry-run：不寄信")
        else:
            subject = f"{cfg.subject_prefix} {name} {target_week.label} vs {ref_week.label}（{run_date}）"
            attachments = [pdf_path or html_path] + ([csv_path] if csv_path else [])
            send_cfg = cfg
            if account.get("email_to"):
                send_cfg = dataclasses.replace(cfg, email_to=list(account["email_to"]))
            emailer.send(send_cfg, subject, html_path.read_text(encoding="utf-8"), attachments)

        storage.log_run(conn, run_at, run_date.isoformat(), target_week_n, ref_week_n, "ok", account=name)
        conn.commit()
        return "ok", ""
    except Exception as e:  # noqa: BLE001
        return "error", str(e)


def main():
    parser = argparse.ArgumentParser(description="小紅書每週數據分析與報告（多帳號）")
    parser.add_argument("--config", default=None, help="config.yaml 路徑")
    parser.add_argument("--run-date", default=None, help="執行日期 YYYY-MM-DD（預設今天）")
    parser.add_argument("--dry-run", action="store_true", help="不寄信")
    parser.add_argument("--from-json", default=None, help="從 actor 輸出 JSON 離線執行（不呼叫 Apify）")
    parser.add_argument("--skip-scrape", action="store_true", help="跳過抓取，直接用資料庫現有資料（省 Apify 額度）")
    parser.add_argument("--db", default=None, help="指定資料庫路徑（預設 data/xhs.db，測試用）")
    parser.add_argument("--account", default=None, help="只處理指定的帳號名稱")
    args = parser.parse_args()

    cfg = Config.load(args.config)
    if args.db:
        cfg.db_path = Path(args.db)
    run_date = date.fromisoformat(args.run_date) if args.run_date else date.today()
    run_at = datetime.now().astimezone()
    anchor = date.fromisoformat(cfg.anchor)
    conn = storage.connect(cfg.db_path)

    target_week_n = weeks.latest_complete_week(run_date, anchor, cfg.block_size_days)
    ref_week_n = target_week_n - 1
    target_week = weeks.week_of(target_week_n, anchor, cfg.block_size_days)
    ref_week = weeks.week_of(ref_week_n, anchor, cfg.block_size_days) if ref_week_n >= 1 else _NoReferenceWeek()

    if args.from_json:
        accounts = [{"name": "default", "excel_path": cfg.excel_path}]
    else:
        accounts = cfg.accounts or [{"name": "default", "excel_path": cfg.excel_path}]
    if args.account:
        accounts = [a for a in accounts if a.get("name") == args.account]
        if not accounts:
            print(f"找不到帳號：{args.account}")
            sys.exit(2)

    print(f"=== 小紅書週報（執行日 {run_date}）| 共 {len(accounts)} 個帳號 ===")
    results = []
    for acc in accounts:
        status, err = run_account(cfg, conn, acc, args, run_date, run_at, anchor,
                                  target_week_n, ref_week_n, target_week, ref_week)
        results.append((acc.get("name") or "default", status, err))
    conn.close()

    print("\n=== 執行總結 ===")
    ok_count = 0
    for name, status, err in results:
        if status == "ok":
            ok_count += 1
            print(f"  ✅ {name}：成功")
        elif status == "no_links":
            print(f"  ⏭ {name}：無連結（跳過）")
        else:
            print(f"  ❌ {name}：失敗 - {err}")
    if ok_count == 0 and any(s == "error" for _, s, _ in results):
        sys.exit(1)
    print("=== 完成 ===")


if __name__ == "__main__":
    main()
