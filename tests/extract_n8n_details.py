"""提取 n8n 工作流關鍵設定（token 遮罩）。"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

data = json.loads(Path("data/n8n_workflow.json").read_text(encoding="utf-8"))


def mask(s: str, keep=12) -> str:
    """把網址中的 token 參數遮罩。"""
    return re.sub(r"(token=)[^&\"'\s]+", lambda m: m.group(1) + "***", str(s))


for n in data["nodes"]:
    t = n.get("type", "")
    name = n.get("name", "")
    p = n.get("parameters", {})
    if t == "n8n-nodes-base.googleSheets":
        doc = p.get("documentId", {})
        sheet = p.get("sheetName", {})
        print(f"[SHEET] {name} | doc={doc.get('value')} | gid={sheet.get('value')} | sheetName={sheet.get('cachedResultName')} | op={p.get('operation')}")
    if n.get("credentials"):
        print(f"[CRED] {name} | {json.dumps(n['credentials'], ensure_ascii=False)}")
    if name == "HTTP Request1":
        print(f"[SERPER] url={p.get('url')} | method={p.get('method')} | sendBody={p.get('sendBody')}")
        print(f"[SERPER] body={json.dumps(p.get('bodyParametersJson') or p.get('bodyParameters'), ensure_ascii=False)[:400]}")
        print(f"[SERPER] auth={json.dumps(p.get('authentication'), ensure_ascii=False)[:200]}")
    if name in ("Start Actor", "Check Run Status", "Fetch Dataset"):
        url = mask(p.get("url", ""))
        print(f"[APIFY] {name} | method={p.get('method')} | url={url[:150]}")
        if p.get("bodyParametersJson"):
            body = mask(json.dumps(p["bodyParametersJson"], ensure_ascii=False))
            print(f"[APIFY] {name} body={body[:300]}")
    if "microsoftOutlook" in t:
        print(f"[OUTLOOK] {name} | params={json.dumps(p, ensure_ascii=False)[:500]}")
    if t == "n8n-nodes-base.scheduleTrigger":
        print(f"[SCHEDULE] {name} | {json.dumps(p.get('rule', {}), ensure_ascii=False)}")
    if name == "Get Post URLs":
        print(f"[POSTURL-SHEET] doc={p.get('documentId', {}).get('value')} gid={p.get('sheetName', {}).get('value')} name={p.get('sheetName', {}).get('cachedResultName')}")
