"""帳號 YAML 檔的讀寫層（給 GUI 用，非技術使用者不必手動編輯）。"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from .config import PROJECT_ROOT

ACCOUNTS_DIR = PROJECT_ROOT / "config" / "news_accounts"

FIELDS = [
    "name", "enabled", "place", "xhs_account", "query", "num", "gl", "hl", "tbs",
    "audience", "topics", "tone", "hashtags", "email_to",
    "prompt_directions", "prompt_analysis", "prompt_scripts", "prompt_tagline",
]

INVALID_NAME = re.compile(r'[\\/:*?"<>|]')


def _dir(path: str | Path | None) -> Path:
    return Path(path) if path else ACCOUNTS_DIR


def validate_name(name: str) -> str:
    name = str(name or "").strip()
    if not name:
        raise ValueError("帳號名稱不能為空")
    if INVALID_NAME.search(name):
        raise ValueError("帳號名稱不能包含 \\ / : * ? \" < > | 等字元")
    return name


def list_accounts(path: str | Path | None = None) -> list[dict]:
    d = _dir(path)
    out = []
    if not d.exists():
        return out
    for f in sorted(d.glob("*.yaml")):
        try:
            data = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
            if isinstance(data, dict) and data.get("name"):
                out.append(data)
            else:
                out.append({"name": f.stem, "enabled": False, "_error": "檔案內容缺少 name"})
        except Exception:  # noqa: BLE001
            out.append({"name": f.stem, "enabled": False, "_error": "無法解析"})
    return out


def account_path(name: str, path: str | Path | None = None) -> Path:
    return _dir(path) / f"{validate_name(name)}.yaml"


def save_account(data: dict, path: str | Path | None = None) -> Path:
    """寫入單一帳號檔（不存在的欄位不寫，讓預設值生效）。"""
    name = validate_name(data.get("name"))
    payload = {k: data.get(k) for k in FIELDS if k in data and data.get(k) is not None}
    payload["name"] = name
    payload.setdefault("enabled", True)
    for k in list(payload):
        v = payload[k]
        if v == "" or v == []:
            payload.pop(k)
    p = account_path(name, path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return p


def delete_account(name: str, path: str | Path | None = None) -> bool:
    p = account_path(name, path)
    if p.exists():
        p.unlink()
        return True
    return False


def toggle_enabled(name: str, enabled: bool, path: str | Path | None = None) -> Path:
    d = _dir(path)
    p = account_path(name, d)
    data = {}
    if p.exists():
        try:
            data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except Exception:  # noqa: BLE001
            data = {}
    data["name"] = name
    data["enabled"] = bool(enabled)
    return save_account(data, d)


def templates() -> dict[str, dict]:
    """新增帳號的快速範本。"""
    return {
        "自訂": {},
        "佛山產業": {
            "place": "佛山",
            "query": "佛山 人工智能 新能源 新材料 无人机",
            "audience": "佛山90後中國打工人",
            "topics": "佛山AI、佛山機器人、佛山新能源、佛山新材料",
            "tone": "專業、接地氣、克制且有溫度",
            "hashtags": "#佛山經濟 #智能制造 #具身智能",
        },
        "旅遊": {
            "place": "佛山",
            "query": "佛山 旅遊 美食 週末 景點",
            "audience": "想週末出門玩的年輕人",
            "topics": "佛山旅遊、美食、週邊遊、親子景點",
            "tone": "輕鬆、有畫面感、實用",
            "hashtags": "#佛山旅遊 #週末去哪玩 #佛山美食",
        },
        "美食": {
            "place": "台北",
            "query": "台北 美食 夜市 小吃 新餐廳",
            "audience": "愛吃宵夜的年輕人",
            "topics": "台北夜市、小吃、老店、新餐廳",
            "tone": "熱情、有畫面、接地氣",
            "hashtags": "#台北美食 #夜市人生 #宵夜",
        },
        "大學生學習": {
            "place": "香港",
            "query": "大學生 學習 讀書方法 考試 升學 實習",
            "audience": "大學生和準備考試的學生",
            "topics": "大學生活、讀書方法、考試、升學、實習",
            "tone": "親切、務實、有共鳴",
            "hashtags": "#大學生 #讀書方法 #考試攻略 #實習",
        },
    }
