"""產生 CSV 與 HTML 週報。"""
from __future__ import annotations

import csv
import re
import statistics
from collections import Counter
from datetime import date, datetime
from pathlib import Path

from jinja2 import Template

from . import pdf

REPORT_TEMPLATE = """<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ title }}</title>
<style>
  body { font-family: "Microsoft JhengHei", "PingFang TC", "Noto Sans TC", sans-serif; margin: 24px auto; padding: 0 12px; max-width: 980px; color: #222; line-height: 1.65; }
  h1 { font-size: 24px; margin-bottom: 4px; }
  h2 { font-size: 18px; margin-top: 34px; border-bottom: 2px solid #ff2e4d; padding-bottom: 6px; }
  .meta { color: #666; font-size: 13px; }
  table { border-collapse: collapse; width: 100%; margin-top: 12px; font-size: 14px; }
  th, td { border: 1px solid #ddd; padding: 8px 10px; text-align: left; vertical-align: top; }
  th { background: #f7f7f7; }
  .warn { background: #fff6e5; border: 1px solid #f0c36d; color: #7a5c00; padding: 12px; border-radius: 6px; margin-top: 16px; }
  .summary { background: #f0f7ff; border: 1px solid #b8d4f0; color: #1a3e6b; padding: 14px; border-radius: 6px; margin-top: 16px; white-space: pre-line; }
  .prelim { background: #fff0f2; }
  .up { color: #1a7f37; font-weight: bold; }
  .down { color: #c62828; font-weight: bold; }
  .flat { color: #666; }
  @media (max-width: 640px) {
    body { margin: 12px auto; padding: 0 6px; }
    h1 { font-size: 20px; }
    h2 { font-size: 16px; }
    th, td { padding: 6px 6px; font-size: 12px; }
    table { display: block; overflow-x: auto; }
  }
</style>
</head>
<body>
<h1>{{ report_title }}</h1>
<p class="meta">執行日期：{{ run_date }}｜本週：{{ target_label }}（{{ target_n }} 篇）｜基準週：{{ reference_label }}（{{ reference_n }} 篇）</p>
{% if preliminary_n %}
<div class="warn">⚠ 本週有 {{ preliminary_n }} 篇帖文為「初步」狀態（第一次被抓取，尚未隔週補抓）；相關結論請以數據成熟後的更新為準。</div>
{% endif %}

{% if exec_summary %}
<h2>執行摘要</h2>
<div class="summary">{{ exec_summary }}</div>
{% endif %}

<h2>AI 分析摘要</h2>
<table>
{% for key, value in ai_sections %}
  <tr><th style="width:190px">{{ key }}</th><td>{{ value|e }}</td></tr>
{% endfor %}
</table>

<h2>本週 vs 基準週（中位數比較）</h2>
<table>
  <tr><th>指標</th><th>本週（{{ target_short }}）</th><th>基準週（{{ reference_short }}）</th><th>變化</th></tr>
{% for m in comparisons %}
  <tr><td>{{ m.label }}</td><td>{{ m.target }}</td><td>{{ m.reference }}</td><td class="{{ m.cls }}">{{ m.change }}</td></tr>
{% endfor %}
</table>

{% if growth %}
<h2>初步 vs 完整（成長比較）</h2>
<p class="meta">同一批帖文第一次抓取（初步）與第二次抓取（完整）的數據變化，可作為新一週初步數據的校正參考。</p>
<table>
  <tr><th>週次</th><th>標題</th><th>發布日期</th><th>讚（初→完）</th><th>收藏（初→完）</th><th>留言（初→完）</th><th>分享（初→完）</th><th>總互動（初→完）</th><th>總互動成長</th></tr>
{% for g in growth %}
  <tr>
    <td>{{ g.week_label }}</td><td>{{ g.title|e }}</td><td>{{ g.publish_date }}</td>
    <td>{{ g.f_likes }} → {{ g.l_likes }}</td>
    <td>{{ g.f_collects }} → {{ g.l_collects }}</td>
    <td>{{ g.f_comments }} → {{ g.l_comments }}</td>
    <td>{{ g.f_shares }} → {{ g.l_shares }}</td>
    <td>{{ g.f_total }} → {{ g.l_total }}</td>
    <td class="{{ g.total_cls }}">{{ g.total_pct }}</td>
  </tr>
{% endfor %}
</table>
{% endif %}

<h2>發布時段與標籤（本週）</h2>
<table>
  <tr><th style="width:190px">最佳發布時段（HKT）</th><td>{{ best_hours }}</td></tr>
  <tr><th>熱門標籤 Top5</th><td>{{ top_tags }}</td></tr>
  <tr><th>標題平均長度</th><td>{{ title_len }}</td></tr>
</table>

<h2>各週趨勢（附錄，不影響主分析）</h2>
<table>
  <tr><th>週次</th><th>帖文數</th><th>讚中位數</th><th>收藏中位數</th><th>留言中位數</th><th>最佳時段</th></tr>
{% for w in trend %}
  <tr><td>{{ w.label }}</td><td>{{ w.n }}</td><td>{{ w.likes }}</td><td>{{ w.collects }}</td><td>{{ w.comments }}</td><td>{{ w.best_hours }}</td></tr>
{% endfor %}
</table>

<h2>帖文明細</h2>
<table>
  <tr><th>週次</th><th>發布日期</th><th>時段</th><th>標題</th><th>讚</th><th>收藏</th><th>留言</th><th>分享</th><th>數據年齡</th><th>狀態</th></tr>
{% for p in posts %}
  <tr class="{{ 'prelim' if p.maturity == 'preliminary' }}">
    <td>{{ p.week_label }}</td><td>{{ p.publish_date }}</td><td>{{ p.publish_hour }}時</td><td>{{ p.title|e }}</td>
    <td>{{ p.likes }}</td><td>{{ p.collects }}</td><td>{{ p.comments }}</td><td>{{ p.shares }}</td>
    <td>{{ p.age_hours }}h</td><td>{{ '⚠ 初步' if p.maturity == 'preliminary' else '完整' }}</td>
  </tr>
{% endfor %}
</table>
<p class="meta" style="margin-top:24px">自動產生：{{ generated_at }}｜樣本數較少時，建議累積 3–4 週再下結論。</p>
</body>
</html>
"""


def _median(values) -> int:
    vals = [v for v in values if v is not None]
    return round(statistics.median(vals)) if vals else 0


def week_stats(rows: list[dict]) -> dict:
    likes = [r.get("like_count", 0) for r in rows]
    collects = [r.get("collect_count", 0) for r in rows]
    comments = [r.get("comment_count", 0) for r in rows]
    shares = [r.get("share_count", 0) for r in rows]
    hours = Counter(r.get("publish_hour_hkt") for r in rows if r.get("publish_hour_hkt") is not None)
    best_hours = [h for h, _ in hours.most_common(3)]
    tags = Counter(t for r in rows for t in (r.get("tags") or []))
    title_len = [len(r.get("title") or "") for r in rows]
    return {
        "n": len(rows),
        "likes_median": _median(likes),
        "collects_median": _median(collects),
        "comments_median": _median(comments),
        "shares_median": _median(shares),
        "total_likes": sum(likes),
        "best_hours": best_hours,
        "top_tags": tags.most_common(5),
        "title_len_avg": round(statistics.mean(title_len), 1) if title_len else 0,
        "preliminary_n": sum(1 for r in rows if r.get("maturity") == "preliminary"),
    }


def _fmt_change(target: float, ref: float) -> tuple[str, str]:
    if not ref:
        return "—", "flat"
    pct = (target - ref) / ref * 100
    if pct > 0.5:
        return f"+{pct:.0f}%", "up"
    if pct < -0.5:
        return f"{pct:.0f}%", "down"
    return "持平", "flat"


def generate(cfg, target_rows, reference_rows, target_week, reference_week, ai_result, trend_rows, run_date: date, growth_rows: list | None = None, account_name: str = "") -> tuple[Path, Path | None, Path | None]:
    """產出 HTML、CSV 與 PDF，回傳 (html_path, csv_path, pdf_path)。"""
    out_dir = Path(cfg.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    t_stats, r_stats = week_stats(target_rows), week_stats(reference_rows)
    comparisons = []
    for label, tk, rk in (
        ("讚數", "likes_median", "likes_median"),
        ("收藏數", "collects_median", "collects_median"),
        ("留言數", "comments_median", "comments_median"),
        ("分享數", "shares_median", "shares_median"),
    ):
        change, cls = _fmt_change(t_stats[tk], r_stats[rk])
        comparisons.append({"label": label, "target": t_stats[tk], "reference": r_stats[rk], "change": change, "cls": cls})

    posts = []
    for r in target_rows + reference_rows:
        week_n = r.get("week_number")
        label = f"W{week_n}" if week_n else "?"
        posts.append({
            "week_label": label,
            "publish_date": r.get("publish_date"),
            "publish_hour": r.get("publish_hour_hkt"),
            "title": r.get("title") or "(無標題)",
            "likes": r.get("like_count", 0),
            "collects": r.get("collect_count", 0),
            "comments": r.get("comment_count", 0),
            "shares": r.get("share_count", 0),
            "age_hours": round(r.get("age_hours") or 0, 1),
            "maturity": r.get("maturity", "preliminary"),
        })

    trend = []
    for t in trend_rows:
        trend.append({
            "label": t["label"],
            "n": t["n"],
            "likes": t["likes_median"],
            "collects": t["collects_median"],
            "comments": t["comments_median"],
            "best_hours": "、".join(str(h) for h in t["best_hours"]) or "—",
        })

    growth = []
    for g in growth_rows or []:
        f, l = g.get("first", {}), g.get("last", {})
        keys = ("like_count", "collect_count", "comment_count", "share_count")
        f_total = sum(f.get(k, 0) for k in keys)
        l_total = sum(l.get(k, 0) for k in keys)
        if f_total:
            diff = l_total - f_total
            if diff == 0:
                total_pct, total_cls = "持平", "flat"
            else:
                total_pct = f"{'+' if diff > 0 else ''}{round(diff / f_total * 100)}%"
                total_cls = "up" if diff > 0 else "down"
        else:
            total_pct, total_cls = "—", "flat"

        growth.append({
            "week_label": g.get("week_label", "?"),
            "title": g.get("title") or "(無標題)",
            "publish_date": g.get("publish_date"),
            "f_likes": f.get("like_count", 0), "f_collects": f.get("collect_count", 0),
            "f_comments": f.get("comment_count", 0), "f_shares": f.get("share_count", 0),
            "l_likes": l.get("like_count", 0), "l_collects": l.get("collect_count", 0),
            "l_comments": l.get("comment_count", 0), "l_shares": l.get("share_count", 0),
            "f_total": f_total, "l_total": l_total,
            "total_pct": total_pct, "total_cls": total_cls,
        })

    sections = dict(ai_result.get("sections") or {})
    raw_summary = sections.pop("摘要", "") or ""
    if isinstance(raw_summary, list):
        exec_summary = "\n".join(str(x) for x in raw_summary)
    else:
        exec_summary = str(raw_summary)
    ai_sections = list(sections.items())
    ref_short = f"W{reference_week.number}" if getattr(reference_week, "number", 0) else "—"
    report_title = f"{account_name} 小紅書週報" if account_name else "小紅書週報"
    slug = re.sub(r"[^A-Za-z0-9\u4e00-\u9fa5]+", "_", account_name).strip("_") if account_name else "account"
    ctx = {
        "title": f"{report_title} {target_week.label} vs {reference_week.label}",
        "report_title": report_title,
        "run_date": run_date.isoformat(),
        "target_label": str(target_week),
        "target_short": f"W{target_week.number}",
        "target_n": len(target_rows),
        "reference_label": str(reference_week),
        "reference_short": ref_short,
        "reference_n": len(reference_rows),
        "preliminary_n": t_stats["preliminary_n"],
        "min_window_hours": cfg.min_window_hours,
        "exec_summary": exec_summary,
        "ai_sections": ai_sections,
        "comparisons": comparisons,
        "growth": growth,
        "best_hours": "、".join(str(h) + " 時" for h in t_stats["best_hours"]) or "—",
        "top_tags": "、".join(f"#{t}" for t, _ in t_stats["top_tags"]) or "—",
        "title_len": f"{t_stats['title_len_avg']} 字" if t_stats["title_len_avg"] else "—",
        "trend": trend,
        "posts": posts,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    html = Template(REPORT_TEMPLATE).render(**ctx)

    html_path = out_dir / f"report_{ts}_{slug}_{target_week.number}vs{reference_week.number}.html"
    html_path.write_text(html, encoding="utf-8")

    csv_path = None
    if cfg.export_csv:
        csv_path = out_dir / f"posts_{ts}_{slug}_{target_week.number}vs{reference_week.number}.csv"
        with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["週次", "note_id", "發布日期(HKT)", "發布時段", "標題", "讚", "收藏", "留言", "分享", "標籤", "數據年齡(h)", "狀態"])
            for r in target_rows + reference_rows:
                writer.writerow([
                    r.get("week_number"),
                    r.get("note_id"),
                    r.get("publish_date"),
                    r.get("publish_hour_hkt"),
                    r.get("title"),
                    r.get("like_count", 0),
                    r.get("collect_count", 0),
                    r.get("comment_count", 0),
                    r.get("share_count", 0),
                    "、".join(r.get("tags") or []),
                    round(r.get("age_hours") or 0, 1),
                    r.get("maturity"),
                ])
    pdf_path = None
    if cfg.export_pdf:
        pdf_path = out_dir / f"report_{ts}_{slug}_{target_week.number}vs{reference_week.number}.pdf"
        pdf_path = pdf.html_to_pdf(html_path, pdf_path)
    return html_path, csv_path, pdf_path
