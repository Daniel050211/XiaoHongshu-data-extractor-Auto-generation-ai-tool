"""呼叫 LLM 進行分析（OpenAI 相容 API）。"""
from __future__ import annotations

import json
import re

import requests

from . import prompts


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _try_parse(text: str) -> dict:
    text = _strip_code_fence(text)
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            data = json.loads(text[start:end + 1])
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass
    return {"原始輸出": text[:2000]}


def rows_for_ai(rows: list[dict]) -> list[dict]:
    """把 post records 轉成給 AI 的精簡 JSON。"""
    out = []
    for r in rows:
        out.append({
            "publish_date": r.get("publish_date"),
            "publish_hour_hkt": r.get("publish_hour_hkt"),
            "likes": r.get("like_count"),
            "collects": r.get("collect_count"),
            "comments": r.get("comment_count"),
            "shares": r.get("share_count"),
            "title": (r.get("title") or "")[:40],
            "content_len": len(r.get("content") or ""),
            "tags": r.get("tags") or [],
            "age_hours": round(r.get("age_hours") or 0, 1),
            "maturity": r.get("maturity"),
        })
    return out


def analyze(cfg, target_label: str, target_rows: list[dict], reference_label: str,
            reference_rows: list[dict], previous_summary: str, growth_context: str = "") -> dict:
    if not cfg.ai_api_key:
        return {
            "status": "dry-run",
            "sections": {
                "摘要": "（尚未設定 AI API key，本報告為乾跑模式，未進行 AI 分析）",
                "目標受眾": "（尚未設定 AI API key，本報告為乾跑模式，未進行 AI 分析）",
                "最佳發帖時間_UTC8": "—",
                "標題_開頭結構": "—",
                "帖子長度": "—",
                "語氣風格": "—",
                "標籤策略": "—",
                "週對週比較": "—",
                "下週建議": "—",
                "信心與限制": "—",
            },
        }

    def _overview(label: str, rows: list[dict]) -> str:
        n = len(rows)
        complete = sum(1 for r in rows if r.get("maturity") == "complete")
        return f"{label}：{n} 篇（完整 {complete} 篇、初步 {n - complete} 篇）"

    data_overview = f"{_overview('目標週', target_rows)}；{_overview('基準週', reference_rows)}；比較指標：點讚、收藏、留言、分享"

    payload = {
        "model": cfg.ai_model,
        "temperature": cfg.ai_temperature,
        "messages": [
            {"role": "system", "content": prompts.SYSTEM_PROMPT},
            {
                "role": "user",
                "content": prompts.USER_TEMPLATE.format(
                    target_label=target_label,
                    target_count=len(target_rows),
                    target_json=json.dumps(target_rows, ensure_ascii=False),
                    reference_label=reference_label,
                    reference_count=len(reference_rows),
                    reference_json=json.dumps(reference_rows, ensure_ascii=False),
                    previous_summary=previous_summary or "（無）",
                    growth_context=growth_context or "（無）",
                    data_overview=data_overview,
                ),
            },
        ],
    }
    headers = {"Authorization": f"Bearer {cfg.ai_api_key}", "Content-Type": "application/json"}
    resp = requests.post(cfg.ai_base_url.rstrip("/") + "/chat/completions", headers=headers, json=payload, timeout=180)
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    return {"status": "ok", "sections": _try_parse(content)}
