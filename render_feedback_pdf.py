"""把 n8n 的回饋（summary / report / claims）轉成 PDF。

用法：
  python render_feedback_pdf.py --input data/feedback/feedback_latest.json [--output data/reports/feedback_xxx.pdf]
"""
from __future__ import annotations

import argparse
import html
import json
import sys
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

from xhs_report.pdf import html_to_pdf


def build_html(data: dict) -> str:
    summary = str(data.get("summary") or "").strip()
    report = str(data.get("report") or "").strip()
    claims = data.get("claims") or []

    claim_rows = ""
    for c in claims:
        claim_rows += (
            "<tr>"
            f"<td>{html.escape(str(c.get('claim_key') or ''))}</td>"
            f"<td>{html.escape(str(c.get('claim') or ''))}</td>"
            f"<td>{html.escape(str(c.get('dimension') or ''))}</td>"
            f"<td>{html.escape(str(c.get('direction') or ''))}</td>"
            f"<td>{html.escape(str(c.get('strength') or ''))}</td>"
            f"<td>{html.escape(str(c.get('sample_support') or ''))}</td>"
            "</tr>"
        )

    def esc(s: str) -> str:
        return html.escape(s).replace("\n", "<br>")

    return f"""<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<title>小紅書策略回饋</title>
<style>
  body {{ font-family: "Microsoft JhengHei", "PingFang TC", sans-serif; margin: 32px auto; max-width: 820px; color: #222; line-height: 1.7; }}
  h1 {{ font-size: 22px; border-bottom: 3px solid #ff2e4d; padding-bottom: 8px; }}
  h2 {{ font-size: 17px; margin-top: 26px; border-bottom: 1px solid #ddd; padding-bottom: 5px; }}
  table {{ border-collapse: collapse; width: 100%; margin-top: 10px; font-size: 13px; }}
  th, td {{ border: 1px solid #ddd; padding: 7px 9px; text-align: left; vertical-align: top; }}
  th {{ background: #f7f7f7; }}
  .summary {{ background: #f0f7ff; border: 1px solid #b8d4f0; padding: 14px; border-radius: 6px; }}
  .meta {{ color: #666; font-size: 12px; }}
</style>
</head>
<body>
<h1>小紅書策略回饋（執行摘要）</h1>
<p class="meta">產生時間：{datetime.now().strftime('%Y-%m-%d %H:%M')}（HKT）</p>
<div class="summary">{esc(summary)}</div>
<h2>詳細分析報告</h2>
<div>{esc(report)}</div>
<h2>策略假設（Claims）</h2>
<table>
  <tr><th>claim_key</th><th>claim</th><th>dimension</th><th>direction</th><th>strength</th><th>sample_support</th></tr>
  {claim_rows}
</table>
</body>
</html>"""


def main():
    parser = argparse.ArgumentParser(description="把 n8n 回饋轉成 PDF")
    parser.add_argument("--input", required=True, help="AI 輸出 JSON 檔（含 summary/report/claims）")
    parser.add_argument("--output", default=None, help="PDF 輸出路徑（預設與 input 同檔名 .pdf）")
    args = parser.parse_args()

    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    html_path = Path(args.input).with_suffix(".html")
    html_path.write_text(build_html(data), encoding="utf-8")
    pdf_path = Path(args.output) if args.output else html_path.with_suffix(".pdf")
    result = html_to_pdf(html_path, pdf_path)
    if result:
        print(f"[feedback-pdf] 已產生：{result}")
    else:
        print("[feedback-pdf] 轉 PDF 失敗")


if __name__ == "__main__":
    main()
