"""OpenRouter 模型清單（預置常用 + 可從 API 更新）。"""
from __future__ import annotations

import json
from pathlib import Path

import requests

CACHE_PATH = Path(__file__).resolve().parent.parent / "data" / "openrouter_models.json"

# 常用預置（若離線或未更新清單時的選項）
CURATED = [
    "z-ai/glm-5.2",
    "z-ai/glm-4.6",
    "deepseek/deepseek-chat",
    "openai/gpt-4.1",
    "openai/gpt-4o-mini",
    "anthropic/claude-sonnet-4",
    "qwen/qwen3-235b-a22b",
    "google/gemini-2.5-flash",
    "meta-llama/llama-3.3-70b-instruct",
]


def fetch_models(timeout: int = 30) -> list[str] | None:
    """從 OpenRouter API 抓取全部模型 id；失敗回傳 None。"""
    try:
        r = requests.get("https://openrouter.ai/api/v1/models", timeout=timeout)
        r.raise_for_status()
        ids = [m.get("id") for m in r.json().get("data", []) if m.get("id")]
        return sorted(ids)
    except Exception:  # noqa: BLE001
        return None


def load_cached() -> list[str]:
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return []


def save_cached(ids: list[str]) -> None:
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(ids, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass


def model_options() -> list[str]:
    seen: set[str] = set()
    merged: list[str] = []
    for m in CURATED + load_cached():
        if m and m not in seen:
            seen.add(m)
            merged.append(m)
    return merged
