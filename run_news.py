"""小紅書新聞AI 系統主程式（n8n Schedule Trigger 線）。

用法：
  python run_news.py --run                       # 執行新一輪，停在方向審批並寄信通知
  python run_news.py --run --account 旅遊號        # 只跑指定帳號（預設跑全部帳號）
  python run_news.py --list-accounts             # 列出帳號設定（檢查 YAML 有沒有讀到）
  python run_news.py --cancel 5 6 7 8            # 取消未完成的執行
  python run_news.py --cancel-all                # 取消全部未完成執行
  python run_news.py --run --dry-run             # 不寄信、可離線跑（配 --from-json）
  python run_news.py --run --from-json data/fixtures/news_serper_sample.json
  python run_news.py --list                      # 列出最近執行
  python run_news.py --show 1                    # 看 run 1 細節
  python run_news.py --approve-direction 1 2 "改一下方向"     # 審批方向（1/2/3/reject）
  python run_news.py --approve-script 1 2                    # 審批腳本（1/2/3/reject）
  python run_news.py --retry-scripts 3                       # 腳本生成失敗時，用已存分析重試
  python run_news.py --resend-final 4                        # 補寄最終 Image Prompt 信
  python run_news.py --resend-direction 10                   # 補寄方向選擇信
  python run_news.py --resend-script 10                      # 補寄腳本審核信
  python run_news.py --serve                                 # 常駐本機審批表單伺服器
  python run_news.py --watch-mail                            # 常駐監看 Email 回覆
  python run_news.py --check-mail                            # 檢查一次 Email 回覆
  python run_news.py --app                        # 開啟桌面審批 App
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except AttributeError:
    pass

from news_app import pipeline, store
from news_app.config import NewsAccount, NewsConfig


def _print_run(r: dict) -> None:
    print(f"#{r['id']}  {r.get('account') or 'default'}  {r['run_date']}  [{r['status']}]  文章:{r['articles_count']}  "
          f"方向重試:{r['retry_direction']}  腳本重試:{r['retry_script']}")
    if r.get("style"):
        print(f"    定稿: {r['style']}  Tagline: {r.get('tagline') or ''}")
    if r.get("error"):
        print(f"    錯誤: {r['error']}")


def main():
    parser = argparse.ArgumentParser(description="小紅書新聞AI（n8n Schedule Trigger 線）")
    parser.add_argument("--run", action="store_true", help="執行新一輪")
    parser.add_argument("--account", default=None, help="只跑指定帳號（預設全部）")
    parser.add_argument("--skip-scheduled", action="store_true",
                        help="跳過有自己排程時間的帳號（預設排程用）")
    parser.add_argument("--dry-run", action="store_true", help="不寄信（測試用）")
    parser.add_argument("--from-json", help="用離線 Serper 資料（fixture）取代搜尋")
    parser.add_argument("--no-notify", action="store_true", help="不寄通知信")
    parser.add_argument("--list", action="store_true", help="列出最近執行")
    parser.add_argument("--list-accounts", action="store_true", help="列出帳號設定")
    parser.add_argument("--cancel", nargs="+", type=int, metavar="RUN", help="取消指定執行")
    parser.add_argument("--cancel-all", action="store_true", help="取消全部未完成執行")
    parser.add_argument("--show", type=int, help="顯示 run 細節")
    parser.add_argument("--approve-direction", nargs="+", metavar="RUN DECISION [comment]",
                        help="審批方向")
    parser.add_argument("--approve-script", nargs="+", metavar="RUN DECISION [comment]",
                        help="審批腳本")
    parser.add_argument("--retry-scripts", type=int, metavar="RUN", help="腳本生成失敗後重試")
    parser.add_argument("--resend-final", type=int, metavar="RUN", help="補寄最終 Image Prompt 信")
    parser.add_argument("--resend-direction", type=int, metavar="RUN", help="補寄方向選擇信")
    parser.add_argument("--resend-script", type=int, metavar="RUN", help="補寄腳本審核信")
    parser.add_argument("--export-history", nargs="?", const="all", metavar="RANGE",
                        help="把歷史 run 補進 Excel（例：18-21；省略=全部；已匯出的會自動跳過）")
    parser.add_argument("--serve", action="store_true", help="啟動本機審批表單伺服器（常駐）")
    parser.add_argument("--watch-mail", action="store_true", help="常駐監看 Email 回覆")
    parser.add_argument("--check-mail", action="store_true", help="檢查一次 Email 回覆")
    parser.add_argument("--app", action="store_true", help="開啟桌面審批 App")
    args = parser.parse_args()

    if args.app:
        from news_app.app import main as app_main
        app_main()
        return

    cfg = NewsConfig.load()
    conn = store.connect(cfg.db_path)

    if args.serve:
        from news_app import web as webmod
        httpd, thread = webmod.start_server(cfg)
        print("表單伺服器已啟動，Ctrl+C 結束。")
        try:
            thread.join()
        except KeyboardInterrupt:
            httpd.shutdown()
        return

    if args.watch_mail:
        from news_app import mailwatch
        mailwatch.start_watcher(cfg, interval=cfg.mail_watch_interval)
        print("Email 回覆監看中，Ctrl+C 結束。")
        try:
            import time
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            print("已停止 Email 監看")
        return

    if args.check_mail:
        from news_app import mailwatch
        done = mailwatch.watch_outlook_once(cfg, conn)
        if not done:
            done = mailwatch.watch_imap_once(cfg, conn)
        print(f"本次處理 Email 回覆：{done or '無'}")
        return

    if args.list_accounts:
        for a in cfg.accounts:
            eff = a.effective(cfg)
            fb = store.latest_feedback_from_xhs(eff.xhs_account)
            print(f"{'✅' if a.enabled else '⏸'} {a.name}")
            print(f"    地區：{eff.place}｜搜尋：{eff.query}")
            print(f"    受眾：{eff.audience}｜主題：{eff.topics}")
            print(f"    語氣：{eff.tone}｜標籤：{eff.hashtags or '（未設定）'}")
            print(f"    回饋：{'✅ 已連結 XHS 帳號「' + eff.xhs_account + '」' if fb else '⚠️ 未找到 XHS 帳號「' + eff.xhs_account + '」的回饋（將用預設）'}")
            print(f"    自訂 prompt：方向={'有' if a.prompt_directions else '—'} "
                  f"分析={'有' if a.prompt_analysis else '—'} "
                  f"腳本={'有' if a.prompt_scripts else '—'} "
                  f"Tagline={'有' if a.prompt_tagline else '—'}")
        return

    if args.cancel:
        for run_id in args.cancel:
            ok = pipeline.cancel_run(conn, run_id)
            print(f"run {run_id}：{'已取消' if ok else '已是終止狀態（done/failed/cancelled），跳過'}")
        return

    if args.cancel_all:
        ids = [r["id"] for r in store.list_runs(conn, limit=500)
               if r["status"] in ("running", "awaiting_direction", "awaiting_script")]
        if not ids:
            print("沒有未完成的執行")
            return
        for run_id in ids:
            pipeline.cancel_run(conn, run_id)
        print(f"已取消 {len(ids)} 筆：{ids}")
        return

    if args.run:
        accounts = cfg.enabled_accounts()
        if args.skip_scheduled:
            accounts = [a for a in accounts if not (a.schedule_time or "").strip()]
        if args.account:
            accounts = [a for a in cfg.accounts if a.name == args.account]
            if not accounts and args.account == "default":
                accounts = [NewsAccount(name="default")]
            if not accounts:
                print(f"找不到帳號：{args.account}")
                sys.exit(2)
        if not accounts:
            print("沒有啟用的帳號（config/news_accounts 中需有 enabled: true 的帳號），"
                  "或用 --account 指定單一帳號。")
            sys.exit(2)
        print(f"=== 新聞線（執行日 {datetime.now().strftime('%Y-%m-%d')}）| 共 {len(accounts)} 個帳號 ===")
        for acc in accounts:
            print(f"\n--- 帳號：{acc.name} ---")
            run_id = pipeline.start_run(
                cfg, conn,
                from_json=args.from_json,
                dry_run=args.dry_run,
                notify=not args.no_notify and not args.dry_run,
                account=acc.name,
            )
            r = store.get_run(conn, run_id)
            print(f"已建立 run #{run_id}（{r['account']}）")
            _print_run(r)
            print(f"等待方向審批。可用：python run_news.py --approve-direction {run_id} 1|2|3|reject \"意見\"")
        return

    if args.approve_direction:
        if len(args.approve_direction) < 2:
            parser.error("--approve-direction 需要 RUN 與決策（1|2|3|reject）")
        run_id = int(args.approve_direction[0])
        decision = args.approve_direction[1]
        comment = " ".join(args.approve_direction[2:])
        status = pipeline.decide_direction(
            cfg, conn, run_id, decision, comment,
            dry_run=args.dry_run, notify=not args.no_notify and not args.dry_run,
        )
        print(f"run {run_id} 目前狀態：{status}")
        return

    if args.approve_script:
        if len(args.approve_script) < 2:
            parser.error("--approve-script 需要 RUN 與決策（1|2|3|reject）")
        run_id = int(args.approve_script[0])
        decision = args.approve_script[1]
        comment = " ".join(args.approve_script[2:])
        status = pipeline.decide_script(
            cfg, conn, run_id, decision, comment,
            dry_run=args.dry_run, notify=not args.no_notify and not args.dry_run,
        )
        print(f"run {run_id} 目前狀態：{status}")
        return

    if args.retry_scripts:
        status = pipeline.retry_scripts(
            cfg, conn, args.retry_scripts,
            dry_run=args.dry_run, notify=not args.no_notify and not args.dry_run,
        )
        print(f"run {args.retry_scripts} 目前狀態：{status}")
        return

    if args.resend_final:
        ok = pipeline.resend_final_email(cfg, conn, args.resend_final)
        print(f"補寄結果：{'成功' if ok else '失敗（請檢查郵件設定或 Outlook）'}")
        return

    if args.resend_direction:
        ok = pipeline.resend_direction_email(cfg, conn, args.resend_direction)
        print(f"補寄結果：{'成功' if ok else '失敗（請檢查郵件設定或 Outlook）'}")
        return

    if args.resend_script:
        ok = pipeline.resend_script_email(cfg, conn, args.resend_script)
        print(f"補寄結果：{'成功' if ok else '失敗（請檢查郵件設定或 Outlook）'}")
        return

    if args.export_history is not None:
        from news_app import excel_export
        ids = [r["id"] for r in store.list_runs(conn, limit=100000)]
        if args.export_history != "all":
            try:
                a, _, b = args.export_history.partition("-")
                start, end = int(a), int(b or a)
                ids = [i for i in ids if start <= i <= end]
            except ValueError:
                print(f"範圍格式錯誤：{args.export_history}（例如 18-21）")
                sys.exit(2)
        art_done = excel_export.existing_run_ids(cfg, excel_export.ARTICLES_SHEET)
        fin_done = excel_export.existing_run_ids(cfg, excel_export.FINAL_SHEET)
        n_art = n_fin = 0
        for run_id in ids:
            run = store.get_run(conn, run_id)
            if not run:
                continue
            account = run.get("account") or "default"
            run_date = run.get("run_date") or ""
            articles = pipeline.store_articles(conn, run_id)
            if articles and run_id not in art_done:
                excel_export.save_articles(cfg, articles, run_id, run_date, account=account)
                n_art += 1
            if (run.get("status") == pipeline.STATUS_DONE and run.get("tagline")
                    and run_id not in fin_done):
                excel_export.save_final(
                    cfg, run_id, run_date=run_date, account=account,
                    chosen_direction=run.get("chosen_direction") or "",
                    style=run.get("style") or "",
                    script=run.get("script_to_publish") or "",
                    tagline=run.get("tagline") or "",
                    image_prompt=run.get("image_prompt") or "",
                )
                n_fin += 1
        print(f"補匯出完成：新聞 {n_art} 個 run，定稿 {n_fin} 個 run → {excel_export.export_path(cfg)}")
        return

    if args.show:
        r = store.get_run(conn, args.show)
        if not r:
            print(f"找不到 run {args.show}")
            return
        _print_run(r)
        if r.get("news_summary"):
            print(f"\n新聞摘要：{r['news_summary']}")
        for d in store.get_directions(conn, args.show):
            print(f"\n方向 {d['idx']}: {d['title']}\n  {d['description']}")
            for s in d.get("sources") or []:
                print(f"    - {s.get('title')}  {s.get('url')}")
        if r.get("analysis"):
            print(f"\n===== 深度分析 =====\n{r['analysis']}")
        for v in store.get_versions(conn, args.show):
            print(f"\n--- 版本 {v['idx']}（{v['style']}）---\n{v['content']}")
        if r.get("tagline"):
            print(f"\nTagline: {r['tagline']}\nImage Prompt: {r['image_prompt']}")
        print("\n===== 事件紀錄 =====")
        for e in store.run_events(conn, args.show):
            print(f"[{e['at']}] {e['message']}")
        return

    print("== 最近執行 ==")
    for r in store.list_runs(conn):
        _print_run(r)
    print("\n提示：python run_news.py --help 查看完整用法")


if __name__ == "__main__":
    main()
