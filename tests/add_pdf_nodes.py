"""在修改後的工作流中加入「回饋轉 PDF」節點（api2pdf），輸出新檔案。"""
from __future__ import annotations

import json
import subprocess
import sys
import uuid
from copy import deepcopy
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

SRC = Path("data/n8n_workflow_modified.json")
DST = Path("data/n8n_workflow_modified_pdf.json")
API_KEY = "5f711a16-50f1-48f2-8dc0-f72df64753a4"

data = json.loads(SRC.read_text(encoding="utf-8"))


def nid() -> str:
    return uuid.uuid4().hex[:24]


def code_node(name: str, code: str) -> dict:
    return {"parameters": {"jsCode": code}, "id": nid(), "name": name,
            "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [0, 0]}


def http_node(name: str, params: dict) -> dict:
    return {"parameters": params, "id": nid(), "name": name,
            "type": "n8n-nodes-base.httpRequest", "typeVersion": 4.2, "position": [0, 0]}


def sticky(name: str, content: str) -> dict:
    return {"parameters": {"content": content, "height": 260, "width": 400, "color": 6},
            "id": nid(), "name": name, "type": "n8n-nodes-base.stickyNote",
            "typeVersion": 1, "position": [0, 0]}


BUILD_HTML_CODE = r"""const item = $input.first().json;
const esc = (s) => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const nl = (s) => esc(s).replace(/\n/g, '<br>');
const claims = Array.isArray(item.claims) ? item.claims : [];
const claimRows = claims.map(c =>
  `<tr><td>${esc(c.claim_key)}</td><td>${esc(c.claim)}</td><td>${esc(c.dimension)}</td><td>${esc(c.strength)}</td></tr>`
).join('');
const html = `<html lang="zh-Hant"><head><meta charset="utf-8">
<style>
body{font-family:"Microsoft JhengHei","PingFang TC",sans-serif;margin:32px;line-height:1.7}
h1{font-size:22px;border-bottom:3px solid #ff2e4d;padding-bottom:8px}
h2{font-size:17px;margin-top:26px;border-bottom:1px solid #ddd}
table{border-collapse:collapse;width:100%;font-size:13px;margin-top:10px}
th,td{border:1px solid #ddd;padding:7px 9px;text-align:left;vertical-align:top}
th{background:#f7f7f7}
.summary{background:#f0f7ff;border:1px solid #b8d4f0;padding:14px;border-radius:6px}
</style></head><body>
<h1>小紅書策略回饋（執行摘要）</h1>
<div class="summary">${nl(item.summary || item.feedback || '')}</div>
<h2>詳細分析報告</h2>${nl(item.report || '')}
<h2>策略假設（Claims）</h2>
<table><tr><th>claim_key</th><th>claim</th><th>dimension</th><th>strength</th></tr>${claimRows}</table>
</body></html>`;
return [{ json: { html } }];
"""

build_html = code_node("Build Feedback HTML", BUILD_HTML_CODE)
pdf_submit = http_node("PDF Submit", {
    "method": "POST",
    "url": "https://v2018.api2pdf.com/chrome/pdf/html?outputBinary=true",
    "sendHeaders": True,
    "headerParameters": {"parameters": [
        {"name": "Authorization", "value": API_KEY},
        {"name": "Content-Type", "value": "application/json"},
    ]},
    "sendBody": True,
    "specifyBody": "json",
    "jsonBody": "={{ JSON.stringify({ html: $json.html }) }}",
    "responseFormat": "file",
    "options": {},
})

note = sticky("PDF 說明", (
    "回饋轉 PDF（api2pdf）\n"
    "流程：Build Feedback HTML → PDF Submit（outputBinary=true，直接回傳 PDF binary）\n"
    "● 若要寄出：在 Outlook 寄信節點 Attachments 選「PDF Submit」的 binary\n"
    "● 安全建議：api2pdf key 目前寫在節點 Header，建議移到 HTTP Request Credentials"
))

data["nodes"].append(build_html)
data["nodes"].append(pdf_submit)
data["nodes"].append(note)

conns = data.setdefault("connections", {})
# Extract analysis result：原輸出維持，並行新增 PDF 分支
extract_conns = conns.get("Extract analysis result", {}).setdefault("main", [])
if not extract_conns:
    extract_conns.append([])
extract_conns[0].append({"node": "Build Feedback HTML", "type": "main", "index": 0})
conns[build_html["name"]] = {"main": [[{"node": pdf_submit["name"], "type": "main", "index": 0}]]}

DST.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

# 驗證
new_data = json.loads(DST.read_text(encoding="utf-8"))
names = {n["name"] for n in new_data["nodes"]}
assert len(names) == len(new_data["nodes"]), "節點名稱重複"
for src, targets in new_data.get("connections", {}).items():
    assert src in names, f"連線來源不存在: {src}"
    for ctype, arr in targets.items():
        for conn in arr:
            for t in conn:
                assert t.get("node") in names, f"連線目標不存在: {t.get('node')}"

node_bin = Path(r"C:\Users\DanielHau\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe")
tmp = Path("data/js_check/feedback_html.js")
tmp.parent.mkdir(exist_ok=True)
tmp.write_text(BUILD_HTML_CODE, encoding="utf-8")
r = subprocess.run([str(node_bin), "--check", str(tmp)], capture_output=True, text=True)
assert r.returncode == 0, f"JS 語法錯誤: {r.stderr.strip()[:300]}"

print("已輸出:", DST, f"({DST.stat().st_size} bytes)")
print(f"節點數: {len(new_data['nodes'])}")
print("Extract analysis result 分支:", [t.get('node') for t in extract_conns[0]])
print("JS 語法: OK")
