"""呼叫 OpenRouter / OpenAI 相容 API，並做 JSON 解析與修復。"""
from __future__ import annotations

import json
import os
import re

import requests


def chat(cfg, system: str, user: str, temperature: float | None = None,
         max_tokens: int = 8000, retries: int = 1) -> str:
    """回傳模型原始文字。retries 為解析失敗時由呼叫端處理，這裡只做 API 層重試。"""
    if os.getenv("NEWS_AI_FAKE") == "1":
        return _fake_response(system)

    if not cfg.ai_api_key:
        raise RuntimeError("未設定 AI_API_KEY（.env）。")

    url = cfg.ai_base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": cfg.ai_model,
        "temperature": cfg.ai_temperature if temperature is None else temperature,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    headers = {
        "Authorization": f"Bearer {cfg.ai_api_key}",
        "Content-Type": "application/json",
    }
    last_err = None
    for attempt in range(retries + 1):
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=240)
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except (requests.RequestException, KeyError, IndexError, ValueError) as e:
            last_err = e
    raise RuntimeError(f"AI 呼叫失敗：{last_err}")


def chat_json(cfg, system: str, user: str, parser, temperature: float | None = None,
              max_tokens: int = 8000, attempts: int = 2):
    """呼叫 AI 並用 parser 解析 JSON；解析失敗時用提醒語重試一次。"""
    last_err: Exception | None = None
    for i in range(attempts):
        prompt = user
        if i > 0:
            prompt = (
                user
                + "\n\n【重要】上次輸出無法解析為有效 JSON。請只輸出一個完整的 JSON 物件："
                "不要加 markdown 程式碼塊，不要截斷內容，字串內部的引號請改用中文引號「」"
                "或正確跳脫 \\\"，所有欄位都要閉合。"
            )
        try:
            raw = chat(cfg, system, prompt, temperature=temperature, max_tokens=max_tokens)
            return parser(raw)
        except (ValueError, KeyError, IndexError) as e:
            last_err = e
    raise ValueError(f"AI 連續 {attempts} 次輸出無法解析：{last_err}")


def _fake_response(system: str) -> str:
    """離線測試用：依 system prompt 特徵回傳固定輸出。"""
    if "image_prompt" in system and "只輸出 JSON" in system:
        return ('{"tagline": "佛山造，正在改寫中國製造業的劇本", '
                '"image_prompt": "畫面唯一主題是抽象幾何光影，幕牆線條在黃昏光下折射，'
                '白色大字標題「佛山造」，優設標題圓，4:3"}')
    if "反差型" in system and "versions" in system:
        return ('{"versions": ['
                '{"style": "反差型", "content": "你可能不知道，佛山最缺的不是訂單，是懂機器人的打工人。#佛山 #機器人 #產業升級"},'
                '{"style": "數據型", "content": "2026年上半年，佛山工業機器人產量同比增長23%，每萬名工人對應機器人密度全國前三。#佛山 #數據"},'
                '{"style": "判斷型", "content": "佛山的新能源故事才剛開始，但真正的機會在供應鏈，不在終端。#佛山 #新能源"}]}')
    if "未來趨勢預測" in system:
        return ("核心觀點：佛山產業升級不是換機器，而是換打工人的技能。\n\n"
                "一、產業與就業分析：2026年佛山機器人產業鏈新增崗位集中在調試、運維與數據標註，"
                "傳統產線工人轉型窗口約3-5年。\n\n"
                "二、對打工人的啟示：別跟機器比力氣，要比會用機器。\n\n"
                "三、未來趨勢預測：AI+機器人將滲透到中小工廠，佛山將成為華南智能製造人才中轉站。")
    return ('{"news_summary": "近期佛山產業動態：AI與機器人密集落地，新能源與新材料持續擴產，低空經濟起步。",'
            '"directions": ['
            '{"id": "d1", "title": "機器人取代打工人？真實數據揭秘", '
            '"description": "從招聘與裁員新聞看佛山機器人行業對就業的真實影響", '
            '"sources": [{"title": "佛山發布首批AI與機器人創新成果", "url": "https://example.com/1"}]},'
            '{"id": "d2", "title": "新能源補貼退坡，打工人該慌嗎", '
            '"description": "結合政策與企業財報分析新能源產業鏈就業穩定性", '
            '"sources": [{"title": "佛山加速邁向智造強市", "url": "https://example.com/2"}]},'
            '{"id": "d3", "title": "佛山AI落地實況：哪些崗位正在被改造", '
            '"description": "從具體案例看AI在製造與物流的滲透速度", '
            '"sources": [{"title": "以AI與機器人之力", "url": "https://example.com/3"}]}]}')


def extract_json(text: str):
    """盡可能從模型輸出中抽出 JSON 物件，並嘗試修復常見問題。"""
    if text is None:
        raise ValueError("模型沒有輸出")
    cleaned = str(text).strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\s*```\s*$", "", cleaned, flags=re.I).strip()

    candidates = []
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start != -1 and end > start:
        candidates.append(cleaned[start:end + 1])
    start, end = cleaned.find("["), cleaned.rfind("]")
    if start != -1 and end > start:
        candidates.append(cleaned[start:end + 1])
    candidates.append(cleaned)

    for cand in candidates:
        try:
            parsed = json.loads(cand)
            if isinstance(parsed, (dict, list)):
                return parsed
        except json.JSONDecodeError:
            pass

    # 修復：把字串內未跳脫的換行換成 \n、去掉尾隨逗號
    for cand in candidates:
        repaired = _repair_json(cand)
        try:
            parsed = json.loads(repaired)
            if isinstance(parsed, (dict, list)):
                return parsed
        except json.JSONDecodeError:
            continue

    raise ValueError(f"無法解析 AI JSON 輸出：{str(text)[:400]}")


def _repair_json(text: str) -> str:
    out = text
    # 字串內真正的換行 -> \n
    out = re.sub(r'"([^"\\]|\\.)*"', lambda m: m.group(0).replace("\n", "\\n"), out)
    out = out.replace("\n", " ").replace("\r", " ")
    out = re.sub(r"\s+", " ", out)
    out = re.sub(r",\s*([}\]])", r"\1", out)   # 尾隨逗號
    out = re.sub(r'}\s*,\s*"', '}, "', out)     # }," 間距
    out = out.replace('"""', '"')
    return out


def parse_directions(text: str) -> tuple[list[dict], str]:
    """回傳 (directions, news_summary)。"""
    data = extract_json(text)
    if not isinstance(data, dict):
        raise ValueError("方向選擇輸出不是 JSON 物件")
    directions = []
    for d in data.get("directions") or []:
        directions.append({
            "id": str(d.get("id") or ""),
            "title": str(d.get("title") or ""),
            "description": str(d.get("description") or ""),
            "sources": [
                {"title": str(s.get("title") or ""), "url": str(s.get("url") or "")}
                for s in (d.get("sources") or [])
                if isinstance(s, dict)
            ],
        })
    if not directions:
        raise ValueError("AI 沒有回傳任何方向")
    news_summary = data.get("news_summary") or ""
    return directions, news_summary


def parse_versions(text: str) -> list[dict]:
    """解析腳本 versions；對應 n8n Split Versions + Parse Scripts 的防護邏輯。"""
    data = extract_json(text)
    versions = []
    if isinstance(data, dict):
        versions = data.get("versions") or []
    elif isinstance(data, list):
        versions = data
    if not isinstance(versions, list) or not versions:
        raise ValueError("AI 沒有回傳任何腳本版本")

    out = []
    for idx, v in enumerate(versions):
        if not isinstance(v, dict):
            continue
        style = str(v.get("style") or f"版本 {idx + 1}")
        content = str(v.get("content") or v.get("text") or "").strip()
        if content:
            out.append({"style": style, "content": content})
    if not out:
        raise ValueError("腳本版本內容為空")
    return out


def parse_tagline(text: str) -> tuple[str, str]:
    data = extract_json(text)
    if not isinstance(data, dict):
        raise ValueError("Tagline 輸出不是 JSON 物件")
    return str(data.get("tagline") or "").strip(), str(data.get("image_prompt") or "").strip()
