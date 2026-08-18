"""把 WF2 的 Execute Workflow 指向真實的 WF3 id。"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

files = {Path(p).name: Path(p) for p in glob.glob("data/restructured/*.json")}
print("restructured 檔案:", list(files.keys()))

wf3_path = next(p for name, p in files.items() if "WF3" in name)
wf2_path = next(p for name, p in files.items() if "WF2" in name)
wf3 = json.loads(wf3_path.read_text(encoding="utf-8"))
wf3_id = wf3["id"]

text = wf2_path.read_text(encoding="utf-8")
assert "REPLACE_WITH_WF3_ID" in text, "找不到佔位符"
text = text.replace("REPLACE_WITH_WF3_ID", wf3_id)
wf2_path.write_text(text, encoding="utf-8")

d = json.loads(text)
for n in d["nodes"]:
    if n.get("type") == "n8n-nodes-base.executeWorkflow":
        print(n["name"], "->", n["parameters"]["workflowId"]["value"])
print("WF3 id:", wf3_id)
