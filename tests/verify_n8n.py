"""驗證修改後的 n8n 檔案內容。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

data = json.loads(Path("data/n8n_workflow_modified.json").read_text(encoding="utf-8"))
by_name = {n["name"]: n for n in data["nodes"]}

ai = by_name["AI Analysis"]["parameters"]
sm = ai["options"]["systemMessage"]
checks = [
    ("systemMessage 含執行摘要", "執行摘要" in sm),
    ("systemMessage 含資料基礎", "資料基礎" in sm),
    ("systemMessage 含下週行動建議", "下週行動建議" in sm),
    ("systemMessage 含下週驗證重點", "下週驗證重點" in sm),
    ("systemMessage 含忽略 views", "忽略 views" in sm),
    ("systemMessage 含初步不得下結論", "初步數據下結論" in sm or "不得僅憑初步數據下結論" in sm),
    ("systemMessage 含上一週策略結論", "上一週的策略結論" in sm),
]
for label, ok in checks:
    print(("OK " if ok else "MISS ") + label)

tl = by_name["Transform & Label"]["parameters"]["jsCode"]
prep = by_name["Prepare for AI analysis"]["parameters"]["jsCode"]
ext = by_name["Extract analysis result"]["parameters"]["jsCode"]
pt3 = by_name["Prepare Third AI Input"]["parameters"]["jsCode"]
code_checks = [
    ("Transform 含 saves", "saves: saves" in tl),
    ("Transform 含 week_number", "week_number: weekNumber" in tl),
    ("Transform 含 maturity", "maturity: maturity" in tl),
    ("Prepare 含資料概況", "資料概況" in prep),
    ("Prepare 含本週區塊", "【本週 W" in prep),
    ("Prepare 含基準週區塊", "【基準週 W" in prep),
    ("Prepare 含初步/完整計數", "（初步 " in prep and "、完整 " in prep),
    ("Prepare 含週對週比較", "週對週比較" in prep),
    ("Extract 含 summary 輸出", "summary || report" in ext),
    ("ThirdInput 含上一週執行摘要", "上一週執行摘要" in pt3),
]
for label, ok in code_checks:
    print(("OK " if ok else "MISS ") + label)
