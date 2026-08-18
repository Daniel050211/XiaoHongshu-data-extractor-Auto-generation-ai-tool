"""匯出指定節點的完整 jsCode。"""
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
    "Prepare for AI analysis",
    "Extract analysis result",
    "Match & Update Claims",
    "Prepare Third AI Input",
    "Attach Existing Claims",
]:
    node = next((n for n in data["nodes"] if n.get("name") == name), None)
    code = (node or {}).get("parameters", {}).get("jsCode", "")
    print(f"\n{'='*70}\n### {name} ({len(code)} chars)\n{code}")
