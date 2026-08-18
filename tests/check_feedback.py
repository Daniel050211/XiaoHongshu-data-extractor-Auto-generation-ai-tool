"""診斷：新聞線目前會注入哪份「上週執行摘要」進腳本生成 prompt。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

from news_app import store

feedback = store.latest_feedback_from_xhs()
print("=== 注入的 feedback ===")
print(feedback[:1500] if feedback else "（空）—— 會改用「（暂无最新反馈）」")
