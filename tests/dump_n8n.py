"""匯出 n8n 工作流中回饋循環相關節點的內容，方便檢視（不修改原檔）。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

data = json.loads(Path("data/n8n_workflow.json").read_text(encoding="utf-8"))
nodes = {n["id"]: n for n in data.get("nodes", [])}

FOCUS = [
    "Transform & Label",
    "Prepare for AI analysis",
    "Attach Existing Claims",
    "Match & Update Claims",
    "Extract analysis result",
    "Feedback generation",
    "Read Latest Analysis",
    "Read Current Memory1",
    "Read Latest Feedback1",
    "Prepare Memory Agent Input1",
    "Format Memory Row1",
    "Collapse Claims for Memory",
    "Filter Claims for Upsert",
    "Read Existing Claims for Prompt",
    "Prepare Third AI Input",
    "AI Analysis",
    "OpenRouter Chat Model Analysis2",
    "Get Post URLs",
    "Code in JavaScript",
    "Read Strategy Hypotheses",
    "Upsert Strategy Hypotheses",
    "Append row in sheet1",
]


def short_params(params, limit=400):
    s = json.dumps(params, ensure_ascii=False, indent=1)
    return s if len(s) <= limit else s[:limit] + " ...[截斷]"


for name in FOCUS:
    node = next((n for n in data["nodes"] if n.get("name") == name), None)
    if not node:
        print(f"\n### 找不到節點: {name}")
        continue
    print(f"\n{'='*70}\n### {name} | type={node.get('type')}")
    params = node.get("parameters", {})
    print("parameters:", short_params(params, 900))
    if node.get("type") == "n8n-nodes-base.code":
        code = params.get("jsCode") or params.get("functionCode") or params.get("code") or ""
        print(f"--- code ({len(code)} chars) ---")
        print(code[:2500])
    # agent 節點的提示詞
    if "agent" in node.get("type", ""):
        for k in ("promptType", "text", "systemMessage"):
            v = params.get(k)
            if v:
                print(f"{k}: {str(v)[:1200]}")
    # 模型節點
    if "lmChat" in node.get("type", ""):
        print("model:", params.get("model"), "| baseURL:", params.get("baseURL"), "| options:", json.dumps(params.get("options", {}), ensure_ascii=False)[:300])
