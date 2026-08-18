"""用真實 actor schema 重新產生測試資料（UTF-8 安全，避免主控台編碼問題）。"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass


def ts(y, m, d, h, mi=0) -> int:
    hk = datetime(y, m, d, h, mi, tzinfo=timezone(timedelta(hours=8)))
    return int(hk.timestamp() * 1000)


items = []
demo = [
    ("6a0000000000000000000001", "夏日護膚三步驟", "早晚都要做的保濕流程", ts(2026, 7, 1, 10), 120, 45, 12, 4, ["護膚", "保濕"], "Alice"),
    ("6a0000000000000000000002", "油皮救星！清潔泥膜實測", "實測三款泥膜", ts(2026, 7, 3, 20, 30), 210, 88, 20, 9, ["油皮", "泥膜", "實測"], "Alice"),
    ("6a0000000000000000000003", "一週護膚計畫表", "懶人也能做", ts(2026, 7, 6, 12), 95, 30, 8, 2, ["護膚", "計畫"], "Alice"),
    ("6a0000000000000000000004", "晚上8點發文實驗", "調整發布時間後", ts(2026, 7, 9, 20), 260, 99, 25, 12, ["護膚", "實驗"], "Alice"),
    ("6a0000000000000000000005", "開頭改用問句測試", "你也有這個困擾嗎？", ts(2026, 7, 11, 21), 180, 70, 18, 7, ["護膚", "問句"], "Alice"),
    ("6a0000000000000000000006", "昨天剛發的短影片", "標籤策略測試", ts(2026, 7, 14, 19), 15, 4, 1, 0, ["短影片", "測試"], "Alice"),
]
for i, (pid, title, content, pub, likes, saves, comments, shares, tags, author) in enumerate(demo):
    items.append({
        "postId": pid,
        "postUrl": "https://www.xiaohongshu.com/explore/" + pid,
        "title": title,
        "content": content,
        "publishedAt": pub,
        "likes": likes,
        "saves": saves,
        "comments": comments,
        "shares": shares,
        "tags": tags,
        "authorName": author,
        "author": {"userId": f"u{i}", "nickname": author},
        "images": ["https://example.com/img.jpg"],
        "videoUrl": None,
        "mode": "post_details",
        "type": "normal",
        "language": "zh-CN",
    })

out = Path("data/fixtures/synthetic.json")
out.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
print("已重新產生:", out, "| 篇數:", len(items))
