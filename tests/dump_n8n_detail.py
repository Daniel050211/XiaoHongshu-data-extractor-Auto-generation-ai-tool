"""匯出指定 n8n 節點的完整內容。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

data = json.loads(Path("data/n8n_workflow.json").read_text(encoding="utf-8"))

for name in [
    "AI Analysis",
    "Feedback generation",
    "Append row in sheet1",
]:
    node = next((n for n in data["nodes"] if n.get("name") == name), None)
    print(f"\n{'='*70}\n### {name}")
    print(json.dumps(node.get("parameters", {}), ensure_ascii=False, indent=1))
