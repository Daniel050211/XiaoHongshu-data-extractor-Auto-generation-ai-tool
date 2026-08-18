"""Serper 搜尋 API 用戶端。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

import requests


def search(cfg, query: str | None = None, num: int | None = None,
           from_json: str | Path | None = None) -> list[dict]:
    """搜尋並回傳扁平化的新聞/搜尋結果清單。

    每個元素欄位：title / link / snippet / source / date。
    """
    if from_json:
        path = Path(from_json)
        data = json.loads(path.read_text(encoding="utf-8"))
        return _flatten(data)

    if not cfg.serper_api_key:
        raise RuntimeError(
            "未設定 SERPER_API_KEY（.env）。請到 https://serper.dev 申請，"
            "或改用 --from-json 離線資料。"
        )

    url = "https://google.serper.dev/search"
    headers = {
        "X-API-KEY": cfg.serper_api_key,
        "Content-Type": "application/json",
    }
    payload = {
        "q": query or cfg.search_query,
        "num": num or cfg.search_num,
        "gl": cfg.search_gl,
        "hl": cfg.search_hl,
        "tbs": cfg.search_tbs,
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=60)
    resp.raise_for_status()
    return _flatten(resp.json())


def _flatten(data: dict) -> list[dict]:
    articles = []
    for block in ("organic", "news"):
        rows = data.get(block) or []
        if not isinstance(rows, list):
            continue
        for n in rows:
            if not isinstance(n, dict):
                continue
            articles.append({
                "title": n.get("title") or "",
                "url": n.get("link") or n.get("url") or "",
                "snippet": n.get("snippet") or "",
                "source": n.get("source") or "",
                "date": n.get("date") or "",
            })
    # 已扁平化的資料也接受（title + url 直接存在）
    if not articles:
        for n in data.get("items") or []:
            if isinstance(n, dict):
                articles.append({
                    "title": n.get("title") or "",
                    "url": n.get("link") or n.get("url") or "",
                    "snippet": n.get("snippet") or "",
                    "source": n.get("source") or "",
                    "date": n.get("date") or "",
                })
    return articles


def merge_and_label(items: Iterable[dict]) -> list[dict]:
    """對應 n8n Merge Articles：扁平化 + 主題分類 + 唯一 id。"""
    def get_topic(title: str, snippet: str) -> str:
        text = f"{title} {snippet}".lower()
        if any(k in text for k in ("机器人", "robot", "机械臂")):
            return "机器人"
        if any(k in text for k in ("ai", "人工智能", "大模型", "智能")):
            return "AI"
        if any(k in text for k in ("新能源", "电池", "光伏", "锂电")):
            return "新能源"
        if any(k in text for k in ("新材料", "半导体", "芯片")):
            return "新材料"
        if any(k in text for k in ("低空", "无人机", "飞行")):
            return "低空经济"
        return "其他产业"

    out = []
    for i, item in enumerate(items, start=1):
        out.append({
            "id": f"a{i}",
            "topic": get_topic(item.get("title", ""), item.get("snippet", "")),
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "snippet": item.get("snippet", ""),
            "source": item.get("source", ""),
            "date": item.get("date", ""),
        })
    return out


def prepare_articles_text(articles: list[dict]) -> str:
    """對應 n8n Prepare Articles for AI。"""
    parts = []
    for d in articles:
        parts.append(f"[{d['id']}] {d['title']}")
        parts.append(f"摘要: {d['snippet']}")
        parts.append(f"來源: {d['source']}  日期: {d['date']}")
        parts.append("")
        parts.append(f"連結: {d['url']}")
        parts.append("")
    return "\n".join(parts)
