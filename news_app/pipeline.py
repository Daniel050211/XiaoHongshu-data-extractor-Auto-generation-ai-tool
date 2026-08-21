"""新聞線流程狀態機：收集 → 方向審批 → 深度分析 → 腳本審批 → Tagline/圖片 Prompt。"""
from __future__ import annotations

import json
from datetime import datetime

from . import ai, email as mailer, excel_export, serper, sheets_sync, store, web
from .config import NewsAccount
from .prompts import (
    build_enhanced_prompt,
    deep_analysis_system,
    deep_analysis_user,
    revised_direction_prompt,
    revised_script_prompt,
    script_system,
    script_user,
    select_directions_system,
    select_directions_user,
    tagline_system,
    tagline_user,
)

STATUS_AWAIT_DIRECTION = "awaiting_direction"
STATUS_AWAIT_SCRIPT = "awaiting_script"
STATUS_DONE = "done"
STATUS_FAILED = "failed"
STATUS_RUNNING = "running"


# ---------- 郵件格式（對應 n8n Format Email Message / Format Script Email） ----------
def format_direction_email(news_summary: str, directions: list[dict]) -> str:
    body = "<h2>📊 深度分析方向選擇</h2>\n"
    body += f"<p><strong>新聞全景摘要：</strong>{news_summary or '近期佛山產業動態'}</p>\n"
    body += "<p>請選擇您希望深度展開的分析方向（可多選）：</p>\n<hr>\n"
    for idx, d in enumerate(directions, start=1):
        body += f"<h3>{idx}. {d.get('title', '')}</h3>\n"
        body += f"<p>{d.get('description', '')}</p>\n"
        sources = d.get("sources") or []
        if sources:
            body += "<p><strong>相關新聞來源：</strong></p>\n<ul>\n"
            for s in sources:
                body += (f'<li><a href="{s.get("url", "")}" target="_blank">'
                         f'{s.get("title", "")}</a></li>\n')
            body += "</ul>\n"
        body += "<hr>\n"
    body += ("<p><strong>請到「小紅書新聞AI」桌面程式（或 CLI）中選擇要生成的分析方向：</strong></p>\n"
             "<p>方向1 / 方向2 / 方向3 / ❌ 拒绝全部</p>")
    return body


def format_script_email(versions: list[dict]) -> str:
    html = (
        "<h2>📱 小紅書帖子草稿（3個版本）</h2>\n"
        "<p><strong>請審核並選擇想要的版本，或告訴我需要修改哪裡：</strong></p>\n"
        "<hr>\n"
    )
    for i, v in enumerate(versions, start=1):
        style = v.get("style") or f"版本 {i}"
        content = (v.get("content") or "（內容為空）").replace("\n", "<br>")
        html += (
            f"<h3>{i}. {style}</h3>\n"
            '<div style="background:#f8f9fa; padding:20px; border-radius:10px; '
            'border-left:5px solid #00b96b; margin:20px 0; line-height:1.7;">'
            f"{content}</div>\n<hr>\n"
        )
    if not versions:
        html += '<p style="color:#d32f2f; font-weight:bold;">⚠️ 未偵測到有效版本，請檢查上游 Generation Agent 的輸出格式。</p>'
    html += (
        "<p><strong>請到「小紅書新聞AI」桌面程式（或 CLI）中選擇要發布的版本：</strong></p>\n"
        "<p>✅ 批准：反差型 / ✅ 批准：數據型 / ✅ 批准：判斷型 / ❌ 拒絕全部</p>"
    )
    return html


def final_email_body(run: dict, chosen: dict | None = None) -> str:
    chosen = chosen or {}
    return (
        "<h2>🎨 封面與圖片 Prompt</h2>"
        f"<p><strong>Tagline：</strong><br>{run.get('tagline') or ''}</p>"
        "<p><strong>Image Prompt：</strong><br>"
        f"<pre style='white-space:pre-wrap'>{run.get('image_prompt') or ''}</pre></p>"
        "<hr><p>腳本（已定稿）：</p>"
        f"<pre style='white-space:pre-wrap'>{chosen.get('content') or run.get('script_to_publish') or ''}</pre>"
    )


def _send_and_log(cfg, conn, run_id: int, subject: str, body: str,
                  recipients: list[str] | None = None) -> bool:
    try:
        ok = mailer.send(cfg, subject, body, recipients=recipients)
        store.add_event(
            conn, run_id,
            f"已寄信：{subject}" if ok else f"寄信未送出（未設定寄件設定或信箱）：{subject}",
            level="info" if ok else "warn",
        )
        return ok
    except Exception as e:  # noqa: BLE001
        store.add_event(conn, run_id, f"寄信異常：{subject} - {e}", level="error")
        return False


def _resolve_account(cfg, name: str):
    name = name or "default"
    for a in cfg.accounts:  # 全部帳號（含停用），讓 --account 也能測試停用帳號
        if a.name == name:
            return a.effective(cfg)
    for a in cfg.enabled_accounts():
        if a.name == name:
            return a.effective(cfg)
    accs = cfg.enabled_accounts()
    if accs:
        return accs[0].effective(cfg)
    return (cfg.accounts[0] if cfg.accounts else NewsAccount(name="default")).effective(cfg)


# ---------- 流程步驟 ----------
def _direction_step(cfg, conn, run_id: int, run: dict, revised_prompt: str | None = None,
                    acc=None) -> dict:
    articles_text = run["articles_text"]
    user = select_directions_user(articles_text, revised_prompt)
    directions, news_summary = ai.chat_json(
        cfg, select_directions_system(acc), user, ai.parse_directions,
        temperature=0.5, max_tokens=8000)
    store.save_directions(conn, run_id, directions)
    store.update_run(conn, run_id, news_summary=news_summary)
    email_body = format_direction_email(news_summary, directions)
    email_body += (
        "<p>📝 <strong>填寫審批表單：</strong>"
        f'<a href="{web.approval_url(cfg, run_id)}">點此打開表單</a>'
        f"（{web.approval_url(cfg, run_id)}）</p>"
    )
    email_body += (
        "<p>📧 <strong>直接回覆 Email 也可以：</strong>"
        "回覆這封信，第一行寫 <strong>方向1 / 方向2 / 方向3 / 拒絕全部</strong>"
        "（或 1 / 2 / 3 / reject），第二行開始寫修改意見（拒絕時）。</p>"
    )
    store.update_run(conn, run_id, direction_email=email_body)
    store.add_event(conn, run_id, f"AI 已產出 {len(directions)} 個分析方向，等待審批")
    return {"directions": directions, "news_summary": news_summary, "email_body": email_body}


def _deep_analysis_step(cfg, conn, run_id: int, run: dict, direction: dict, acc=None) -> str:
    user = deep_analysis_user(direction, run["news_summary"], run["articles_text"])
    raw = ai.chat(cfg, deep_analysis_system(acc), user, temperature=0.5, max_tokens=6000)
    analysis = (raw or "").strip()
    store.update_run(conn, run_id, analysis=analysis)
    store.add_event(conn, run_id, "深度分析完成")
    return analysis


def _scripts_step(cfg, conn, run_id: int, run: dict, reject_comment: str | None = None,
                  acc=None) -> list[dict]:
    account = run.get("account") or "default"
    xhs_account = (acc.xhs_account if acc else None) or account
    latest_feedback = store.latest_feedback_from_xhs(xhs_account) or ""
    if latest_feedback:
        store.add_event(conn, run_id, f"已讀取 XHS 帳號「{xhs_account}」的週報回饋")
    else:
        latest_feedback = "（暂无最新反馈）"
        store.add_event(conn, run_id,
                        f"未找到 XHS 帳號「{xhs_account}」的週報回饋，使用預設（可到帳號設定綁定）",
                        level="warn")
    current_memory = store.latest_memory(conn, account) or "（暂无记忆）"
    enhanced = build_enhanced_prompt(latest_feedback, current_memory, reject_comment)
    store.update_run(conn, run_id, enhanced_prompt=enhanced)
    user = script_user(enhanced, run["analysis"])
    versions = ai.chat_json(
        cfg, script_system(acc), user, ai.parse_versions,
        temperature=(acc.temperature if acc else None) or 0.6, max_tokens=8000)
    store.save_versions(conn, run_id, versions)
    script_email = format_script_email(versions)
    script_email += (
        "<p>📝 <strong>填寫審批表單：</strong>"
        f'<a href="{web.approval_url(cfg, run_id)}">點此打開表單</a>'
        f"（{web.approval_url(cfg, run_id)}）</p>"
    )
    script_email += (
        "<p>📧 <strong>直接回覆 Email 也可以：</strong>"
        "回覆這封信，第一行寫 <strong>版本1 / 版本2 / 版本3 / 拒絕全部</strong>"
        "（或 1 / 2 / 3 / reject / 反差型 / 數據型 / 判斷型），第二行開始寫修改意見（拒絕時）。</p>"
    )
    store.update_run(conn, run_id, script_email=script_email)
    store.add_event(conn, run_id, f"AI 已產出 {len(versions)} 個腳本版本，等待審批")
    return versions


def _tagline_step(cfg, conn, run_id: int, run: dict, acc=None) -> tuple[str, str]:
    user = tagline_user(run["script_to_publish"])
    tagline, image_prompt = ai.chat_json(
        cfg, tagline_system(acc), user, ai.parse_tagline,
        temperature=0.5, max_tokens=4000)
    store.update_run(conn, run_id, tagline=tagline, image_prompt=image_prompt)
    store.add_event(conn, run_id, "Tagline 與圖片 Prompt 已產出")
    return tagline, image_prompt


# ---------- 對外 API ----------
def start_run(cfg, conn, run_date: str | None = None, from_json=None,
              dry_run: bool = False, notify: bool = True, account: str = "default") -> int:
    """建立新一輪並跑完「收集 + 方向選擇」，停在方向審批。回傳 run_id。"""
    run_date = run_date or datetime.now().strftime("%Y-%m-%d")
    acc = _resolve_account(cfg, account)
    run_id = store.create_run(conn, run_date, acc.query, account=acc.name)
    store.add_event(conn, run_id, f"開始新一輪（{run_date}）帳號：{acc.name}")
    try:
        items = serper.search(cfg, query=acc.query, num=acc.num, from_json=from_json)
        if not items:
            raise RuntimeError("搜尋沒有回傳任何結果")
        articles = serper.merge_and_label(items)
        store.save_articles(conn, run_id, articles)
        try:
            excel_export.save_articles(cfg, articles, run_id, run_date, account=acc.name)
        except Exception as e:  # noqa: BLE001
            store.add_event(conn, run_id, f"Excel 新聞匯出失敗（可忽略）：{e}", level="warn")
        articles_text = serper.prepare_articles_text(articles)
        store.update_run(conn, run_id, articles_count=len(articles), articles_text=articles_text)
        store.add_event(conn, run_id, f"搜尋到 {len(articles)} 條新聞")

        result = _direction_step(cfg, conn, run_id, store.get_run(conn, run_id), acc=acc)
        store.set_run_status(conn, run_id, STATUS_AWAIT_DIRECTION)
        if notify and not dry_run:
            subject = f"AI分析方向選擇 - {run_date}（#{run_id}）"
            _send_and_log(cfg, conn, run_id, subject, result["email_body"], recipients=acc.email_to)
        store.add_event(conn, run_id, "狀態：等待方向審批" + ("（dry-run 不寄信）" if dry_run else ""))
        return run_id
    except Exception as e:  # noqa: BLE001
        store.set_run_status(conn, run_id, STATUS_FAILED, str(e))
        store.add_event(conn, run_id, f"失敗：{e}", level="error")
        raise


def decide_direction(cfg, conn, run_id: int, decision: str, comment: str = "",
                     dry_run: bool = False, notify: bool = True) -> str:
    """審批方向。decision: 1/2/3 或 reject。回傳新的狀態。"""
    run = store.get_run(conn, run_id)
    if not run:
        raise ValueError(f"找不到 run {run_id}")
    if run["status"] != STATUS_AWAIT_DIRECTION:
        raise ValueError(f"run {run_id} 目前狀態是 {run['status']}，不是等待方向審批")

    idx, rejected = _normalize_direction(decision)
    directions = store.get_directions(conn, run_id)
    if not rejected and (idx is None or idx >= len(directions)):
        raise ValueError(f"無效的方向選擇：{decision}")

    if rejected:
        acc = _resolve_account(cfg, run.get("account"))
        max_retry = cfg.direction_max_retries
        retry = int(run["retry_direction"] or 0)
        if retry >= max_retry:
            msg = f"方向建議已達最大重試次數（{max_retry}）。意見: {comment or '（無）'}"
            store.set_run_status(conn, run_id, STATUS_FAILED, msg)
            store.add_event(conn, run_id, msg, level="error")
            return STATUS_FAILED
        retry += 1
        store.update_run(conn, run_id, retry_direction=retry)
        store.add_event(conn, run_id, f"方向被拒絕（第 {retry} 次），依意見重新生成：{comment or '（無具體意見）'}")
        revised = revised_direction_prompt(comment or "無具體意見", run["articles_text"])
        result = _direction_step(cfg, conn, run_id, run, revised_prompt=revised, acc=acc)
        store.set_run_status(conn, run_id, STATUS_AWAIT_DIRECTION)
        if notify and not dry_run:
            _send_and_log(cfg, conn, run_id,
                          f"AI分析方向選擇（重試 {retry}）- {run['run_date']}（#{run_id}）",
                          result["email_body"], recipients=acc.email_to)
        return STATUS_AWAIT_DIRECTION

    # 批准：進入深度分析
    acc = _resolve_account(cfg, run.get("account"))
    store.set_run_status(conn, run_id, STATUS_RUNNING)
    store.add_event(conn, run_id, f"批准方向：{directions[idx]['title']}")
    chosen = directions[idx]
    store.update_run(conn, run_id, chosen_direction=json.dumps(chosen, ensure_ascii=False))
    try:
        analysis = _deep_analysis_step(cfg, conn, run_id, run, chosen, acc=acc)
        versions = _scripts_step(cfg, conn, run_id, store.get_run(conn, run_id), acc=acc)
        store.set_run_status(conn, run_id, STATUS_AWAIT_SCRIPT)
        if notify and not dry_run:
            subject = f"內容審核 - {datetime.now().strftime('%Y-%m-%d %H:%M')}（#{run_id}）"
            _send_and_log(cfg, conn, run_id, subject,
                          store.get_run(conn, run_id)["script_email"], recipients=acc.email_to)
        store.add_event(conn, run_id, "狀態：等待腳本審批" + ("（dry-run 不寄信）" if dry_run else ""))
        return STATUS_AWAIT_SCRIPT
    except Exception as e:  # noqa: BLE001
        store.set_run_status(conn, run_id, STATUS_FAILED, str(e))
        store.add_event(conn, run_id, f"失敗：{e}", level="error")
        raise


def decide_script(cfg, conn, run_id: int, decision: str, comment: str = "",
                  dry_run: bool = False, notify: bool = True) -> str:
    """審批腳本。decision: 1/2/3 或 reject。回傳新的狀態。"""
    run = store.get_run(conn, run_id)
    if not run:
        raise ValueError(f"找不到 run {run_id}")
    if run["status"] != STATUS_AWAIT_SCRIPT:
        raise ValueError(f"run {run_id} 目前狀態是 {run['status']}，不是等待腳本審批")

    idx, rejected = _normalize_script(decision)
    versions = store.get_versions(conn, run_id)
    if not rejected and (idx is None or idx >= len(versions)):
        raise ValueError(f"無效的腳本選擇：{decision}")

    if rejected:
        acc = _resolve_account(cfg, run.get("account"))
        max_retry = cfg.script_max_retries
        retry = int(run["retry_script"] or 0)
        if retry >= max_retry:
            msg = f"腳本已達最大重試次數（{max_retry}）。意見: {comment or '（無）'}"
            store.set_run_status(conn, run_id, STATUS_FAILED, msg)
            store.add_event(conn, run_id, msg, level="error")
            return STATUS_FAILED
        retry += 1
        store.update_run(conn, run_id, retry_script=retry)
        store.add_event(conn, run_id, f"腳本被拒絕（第 {retry} 次），依意見重新生成：{comment or '（無具體意見）'}")
        versions = _scripts_step(cfg, conn, run_id, run,
                                 reject_comment=comment or "無具體意見", acc=acc)
        store.set_run_status(conn, run_id, STATUS_AWAIT_SCRIPT)
        if notify and not dry_run:
            subject = f"內容審核（重試 {retry}）- {datetime.now().strftime('%Y-%m-%d %H:%M')}（#{run_id}）"
            _send_and_log(cfg, conn, run_id, subject,
                          store.get_run(conn, run_id)["script_email"], recipients=acc.email_to)
        return STATUS_AWAIT_SCRIPT

    chosen = versions[idx]
    acc = _resolve_account(cfg, run.get("account"))
    store.set_run_status(conn, run_id, STATUS_RUNNING)
    store.add_event(conn, run_id, f"批准腳本：{chosen['style']}")
    store.update_run(conn, run_id, script_to_publish=chosen["content"], style=chosen["style"])
    try:
        tagline, image_prompt = _tagline_step(cfg, conn, run_id, store.get_run(conn, run_id), acc=acc)
        store.set_run_status(conn, run_id, STATUS_DONE)
        store.add_event(conn, run_id, f"完成！Tagline：{tagline}")
        try:
            chosen_dir = {}
            if run.get("chosen_direction"):
                chosen_dir = json.loads(run["chosen_direction"])
            memory_text = (f"[{run.get('run_date')}] 新聞摘要：{run.get('news_summary') or ''}\n"
                           f"選用方向：{chosen_dir.get('title', '')}\n"
                           f"定稿腳本樣式：{chosen.get('style', '')}\n"
                           f"Tagline：{tagline}")
            store.save_memory(conn, run_id, run.get("account") or "default", memory_text)
        except Exception as e:  # noqa: BLE001
            store.add_event(conn, run_id, f"記憶寫入失敗：{e}", level="warn")

        try:
            excel_export.save_final(
                cfg, run_id,
                run_date=run.get("run_date") or "",
                account=run.get("account") or "default",
                chosen_direction=run.get("chosen_direction") or "",
                style=chosen.get("style", ""),
                script=chosen.get("content", ""),
                tagline=tagline,
                image_prompt=image_prompt,
            )
        except Exception as e:  # noqa: BLE001
            store.add_event(conn, run_id, f"Excel 定稿匯出失敗（可忽略）：{e}", level="warn")

        if notify and not dry_run:
            _send_and_log(cfg, conn, run_id, "Image Prompt",
                          final_email_body(store.get_run(conn, run_id), chosen),
                          recipients=acc.email_to)

        try:
            sheets_sync.sync_run(cfg, store.get_run(conn, run_id),
                                 store_articles(conn, run_id),
                                 store.get_directions(conn, run_id),
                                 versions)
        except Exception as e:  # noqa: BLE001
            store.add_event(conn, run_id, f"Google Sheets 同步失敗（可忽略）：{e}", level="warn")
        return STATUS_DONE
    except Exception as e:  # noqa: BLE001
        store.set_run_status(conn, run_id, STATUS_FAILED, str(e))
        store.add_event(conn, run_id, f"失敗：{e}", level="error")
        raise


def resend_final_email(cfg, conn, run_id: int) -> bool:
    """補寄最終「Image Prompt」信（run 已完成時）。"""
    run = store.get_run(conn, run_id)
    if not run:
        raise ValueError(f"找不到 run {run_id}")
    if run["status"] != STATUS_DONE or not run.get("tagline"):
        raise ValueError(f"run {run_id} 尚未完成（或沒有 Tagline），無法補寄")
    versions = store.get_versions(conn, run_id)
    chosen = versions[0] if versions else None
    acc = _resolve_account(cfg, run.get("account"))
    return _send_and_log(cfg, conn, run_id, "Image Prompt", final_email_body(run, chosen),
                         recipients=acc.email_to)


def resend_direction_email(cfg, conn, run_id: int) -> bool:
    """補寄方向選擇信（run 已停在方向審批、但信漏寄時用）。"""
    run = store.get_run(conn, run_id)
    if not run:
        raise ValueError(f"找不到 run {run_id}")
    if not run.get("direction_email"):
        raise ValueError(f"run {run_id} 沒有已儲存的方向選擇信，無法補寄")
    acc = _resolve_account(cfg, run.get("account"))
    subject = f"AI分析方向選擇 - {run['run_date']}（#{run_id}）"
    return _send_and_log(cfg, conn, run_id, subject, run["direction_email"],
                         recipients=acc.email_to)


def resend_script_email(cfg, conn, run_id: int) -> bool:
    """補寄腳本審核信（run 已停在腳本審批、但信漏寄時用）。"""
    run = store.get_run(conn, run_id)
    if not run:
        raise ValueError(f"找不到 run {run_id}")
    if not run.get("script_email"):
        raise ValueError(f"run {run_id} 沒有已儲存的腳本審核信，無法補寄")
    acc = _resolve_account(cfg, run.get("account"))
    subject = f"內容審核（補寄）- {datetime.now().strftime('%Y-%m-%d %H:%M')}（#{run_id}）"
    return _send_and_log(cfg, conn, run_id, subject, run["script_email"],
                         recipients=acc.email_to)


def cancel_run(conn, run_id: int, reason: str = "使用者取消") -> bool:
    """取消一筆尚未完成的執行（running / 等待審批）。"""
    run = store.get_run(conn, run_id)
    if not run:
        raise ValueError(f"找不到 run {run_id}")
    if run["status"] in ("done", "failed", "cancelled"):
        return False
    store.set_run_status(conn, run_id, "cancelled")
    store.add_event(conn, run_id, f"已取消（{reason}）", level="warn")
    return True


def retry_scripts(cfg, conn, run_id: int, dry_run: bool = False, notify: bool = True) -> str:
    """從失敗點復原：用已儲存的深度分析重新生成腳本。"""
    run = store.get_run(conn, run_id)
    if not run:
        raise ValueError(f"找不到 run {run_id}")
    if not run["analysis"]:
        raise ValueError(f"run {run_id} 沒有已儲存的深度分析，無法重試腳本")
    store.set_run_status(conn, run_id, STATUS_RUNNING)
    store.add_event(conn, run_id, "重新生成腳本（復原失敗點）")
    try:
        acc = _resolve_account(cfg, run.get("account"))
        versions = _scripts_step(cfg, conn, run_id, run, acc=acc)
        store.set_run_status(conn, run_id, STATUS_AWAIT_SCRIPT)
        if notify and not dry_run:
            subject = f"內容審核（重試）- {datetime.now().strftime('%Y-%m-%d %H:%M')}（#{run_id}）"
            _send_and_log(cfg, conn, run_id, subject,
                          store.get_run(conn, run_id)["script_email"], recipients=acc.email_to)
        store.add_event(conn, run_id, "狀態：等待腳本審批" + ("（dry-run 不寄信）" if dry_run else ""))
        return STATUS_AWAIT_SCRIPT
    except Exception as e:  # noqa: BLE001
        store.set_run_status(conn, run_id, STATUS_FAILED, str(e))
        store.add_event(conn, run_id, f"失敗：{e}", level="error")
        raise


def store_articles(conn, run_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT id, topic, title, url, snippet, source, date FROM articles WHERE run_id=? ORDER BY idx",
        (run_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def _normalize_direction(decision: str) -> tuple[int | None, bool]:
    d = str(decision or "").strip()
    if d in ("reject", "rejectall", "拒绝", "拒絕", "拒绝全部", "❌ 拒绝全部"):
        return None, True
    mapping = {
        "1": 0, "方向1": 0, "方向一": 0,
        "2": 1, "方向2": 1, "方向二": 1,
        "3": 2, "方向3": 2, "方向三": 2,
    }
    return mapping.get(d), False


def _normalize_script(decision: str) -> tuple[int | None, bool]:
    d = str(decision or "").strip()
    if d in ("reject", "rejectall", "拒绝", "拒絕", "拒绝全部", "❌ 拒绝全部"):
        return None, True
    mapping = {
        "1": 0, "反差型": 0, "✅ 批准：反差型": 0,
        "2": 1, "數據型": 1, "数据型": 1, "✅ 批准：數據型": 1, "✅ 批准：数据型": 1,
        "3": 2, "判斷型": 2, "判断型": 2, "✅ 批准：判斷型": 2, "✅ 批准：判断型": 2,
    }
    return mapping.get(d), False
