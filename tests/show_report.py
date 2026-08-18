"""顯示最新一份報告的重點內容（純檢查用）。"""
from __future__ import annotations

import glob
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

html = max(glob.glob("data/reports/*.html"), key=lambda p: Path(p).stat().st_mtime)
text = Path(html).read_text(encoding="utf-8")
print("報告:", Path(html).name)
print("表格數:", text.count("<table>"))
print("含乾跑模式:", "乾跑模式" in text)

m = re.search(r"<h2>執行摘要</h2>\s*<div class=\"summary\">(.*?)</div>", text, re.S)
if m:
    print("執行摘要:")
    print(re.sub(r"<[^>]+>", "", m.group(1)).strip())
else:
    print("執行摘要: （無）")

m = re.search(r"<h2>AI 分析摘要</h2>\s*<table>(.*?)</table>", text, re.S)
rows = re.findall(r"<tr>(.*?)</tr>", m.group(1), re.S) if m else []
print("AI 摘要段落數:", len(rows))
for r in rows[:9]:
    cells = [re.sub(r"<[^>]+>", "", c).strip() for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, re.S)]
    print("  ", cells[0], "=>", cells[1][:110] if len(cells) > 1 else "")

m = re.search(r"<h2>初步 vs 完整（成長比較）</h2>.*?<table>(.*?)</table>", text, re.S)
rows = re.findall(r"<tr[^>]*>(.*?)</tr>", m.group(1), re.S) if m else []
print("成長比較列數(含表頭):", len(rows))
for r in rows[:8]:
    cells = [re.sub(r"<[^>]+>", "", c).strip() for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, re.S)]
    print("  ", " | ".join(cells)[:180])

m = re.search(r"<h2>帖文明細</h2>\s*<table>(.*?)</table>", text, re.S)
rows = re.findall(r"<tr[^>]*>(.*?)</tr>", m.group(1), re.S) if m else []
print("帖文明細列數:", len(rows))
for r in rows[:6]:
    cells = [re.sub(r"<[^>]+>", "", c).strip() for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, re.S)]
    print("  ", " | ".join(cells)[:170])
