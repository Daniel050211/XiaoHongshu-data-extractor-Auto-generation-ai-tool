"""Apify 小紅書抓取器包裝。"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from apify_client import ApifyClient

from .weeks import HKT_OFFSET

NOTE_ID_RE = re.compile(r"/(?:explore|item|note)/([0-9a-fA-F]{24})")


def _first(item: dict, *keys, default=None):
    for k in keys:
        if k in item and item[k] not in (None, ""):
            return item[k]
    return default


def _parse_ts(value) -> datetime | None:
    """接受 Unix 秒/毫秒或常見 ISO 字串，回傳 aware UTC datetime。"""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        ts = value / 1000.0 if value > 10**12 else float(value)
        try:
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        v = value.strip()
        if v.isdigit():
            return _parse_ts(int(v))
        for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(v, fmt)
                return dt.replace(tzinfo=timezone.utc) if v.endswith("Z") else dt.replace(tzinfo=HKT_OFFSET)
            except ValueError:
                continue
    return None


def _parse_id_from_url(url: str) -> str | None:
    m = NOTE_ID_RE.search(url or "")
    return m.group(1) if m else None


def note_id_from_url(url: str) -> str | None:
    """從帖文網址解析 note_id（用於判斷是否已完整、要不要跳過）。"""
    return _parse_id_from_url(url)


def _list_len(value) -> int:
    if isinstance(value, (list, tuple)):
        return len(value)
    return 0 if value in (None, "") else 1


def normalize_item(item: dict) -> dict | None:
    """把 actor 輸出的單一 item 標準化為 post record；不是帖文的 item 回傳 None。"""
    url = _first(item, "postUrl", "noteUrl", "note_url", "url", "shareUrl", "share_url", "note_url_share")
    note_id = _first(item, "postId", "noteId", "note_id", "id") or _parse_id_from_url(url)
    if not note_id:
        return None

    publish = _parse_ts(_first(item, "publishedAt", "publishTime", "publish_time", "createTime", "create_time", "createdAt", "postTime"))
    hkt = publish.astimezone(timezone.utc) + HKT_OFFSET if publish else None
    tags = _first(item, "tagList", "tags", "hashtags", "topics", default=[])
    if isinstance(tags, list):
        tags = [t.get("name") if isinstance(t, dict) else str(t) for t in tags]
    author = _first(item, "authorName", "author", "nickname", "username", default="")
    if not author and isinstance(item.get("author"), dict):
        author = item["author"].get("nickname", "")

    title = _first(item, "title", "noteTitle", "note_title", default="")
    content = _first(item, "desc", "description", "noteDesc", "note_desc", "content", default="")
    if not title and content:
        title = content.strip().splitlines()[0][:40]

    return {
        "note_id": str(note_id),
        "url": url or "",
        "title": title,
        "content": content,
        "author": author,
        "publish_time_utc": publish.isoformat() if publish else None,
        "publish_hkt": hkt.isoformat() if hkt else None,
        "publish_date": hkt.date().isoformat() if hkt else None,
        "publish_hour_hkt": hkt.hour if hkt else None,
        "like_count": int(_first(item, "likeCount", "like_count", "likedCount", "likes", default=0) or 0),
        "collect_count": int(_first(item, "saves", "collectedCount", "collectCount", "collected_count", "favCount", "favorites", default=0) or 0),
        "comment_count": int(_first(item, "commentCount", "comment_count", "commentsCount", "comments", default=0) or 0),
        "share_count": int(_first(item, "shareCount", "share_count", "shares", default=0) or 0),
        "view_count": int(_first(item, "viewCount", "view_count", "views", "watchCount", default=0) or 0),
        "tags": [str(t) for t in tags],
        "image_count": _list_len(_first(item, "imageList", "images", "imageUrls", default=[])),
        "video_count": 1 if (_first(item, "videoUrl", "isVideo", "video", default=False) or _first(item, "videoCount", default=0)) else 0,
        "raw_keys": sorted(item.keys()),
    }


def _metric_total(r: dict) -> int:
    return r["like_count"] + r["collect_count"] + r["comment_count"] + r["share_count"]


def _dedupe(records: list[dict]) -> list[dict]:
    best: dict[str, dict] = {}
    for r in records:
        prev = best.get(r["note_id"])
        if prev is None or _metric_total(r) > _metric_total(prev):
            best[r["note_id"]] = r
    return list(best.values())


def _build_input(cfg, post_urls: list[str] | None) -> dict:
    proxy = {"useApifyProxy": True}
    if cfg.apify_proxy:
        proxy["apifyProxyGroups"] = [cfg.apify_proxy]
    inp = {
        "mode": cfg.apify_mode,
        "maxResults": cfg.apify_max_results,
        "includeComments": False,
        "proxyConfiguration": proxy,
        "cookieString": cfg.apify_cookie_string or None,
        "concurrency": 2,
        "blockResources": False,
        "liteMode": False,
        "sentimentAnalysis": False,
        "deltaMode": False,
        "networkCapture": cfg.apify_network_capture,
    }
    if cfg.apify_mode == "post_details":
        inp["postUrls"] = post_urls or []
    else:
        inp["userUrl"] = (cfg.apify_user_urls or [None])[0]
        inp["userUrls"] = cfg.apify_user_urls
        inp["sortBy"] = "general"
        inp["filterByType"] = "all"
        inp["filterByMinLikes"] = 0
    return inp


def run_actor(cfg, post_urls: list[str] | None = None) -> list[dict]:
    """執行 actor 並回傳標準化 post records。"""
    if not cfg.apify_api_key:
        raise RuntimeError("未設定 APIFY_API_KEY（請填入 .env）")
    client = ApifyClient(cfg.apify_api_key)
    run = client.actor(cfg.apify_actor_id).call(run_input=_build_input(cfg, post_urls))
    run = run.model_dump() if hasattr(run, "model_dump") else run
    if run.get("status") != "SUCCEEDED":
        raise RuntimeError(f"Apify run 失敗: status={run.get('status')}，詳情見 https://console.apify.com/runs/{run.get('id')}")
    ds_id = run.get("defaultDatasetId") or run.get("default_dataset_id")
    items = list(client.dataset(ds_id).iterate_items())
    records = [r for r in (normalize_item(i) for i in items) if r]
    return _dedupe(records)


def load_fixture(path: str | Path) -> list[dict]:
    """從之前存下來的 actor 輸出 JSON 載入（離線測試用）。"""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        items = data
    else:
        items = data.get("items", [])
    records = [r for r in (normalize_item(i) for i in items) if r]
    return _dedupe(records)
