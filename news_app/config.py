"""載入新聞線設定：config.yaml 的 news 段落 + .env。"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

if getattr(sys, "frozen", False):
    PROJECT_ROOT = Path(sys.executable).resolve().parent
else:
    PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _as_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [v.strip() for v in value.replace(";", ",").split(",") if v.strip()]
    return [str(v).strip() for v in value if str(v).strip()]


@dataclass
class NewsAccount:
    """新聞線單一帳號設定：搜尋、受眾、主題、語氣、標籤、收件人。"""
    name: str
    enabled: bool = True
    place: str = ""
    xhs_account: str = ""
    query: str = ""
    num: int = 10
    gl: str = "cn"
    hl: str = "zh-cn"
    tbs: str = "qdr:w"
    audience: str = ""
    topics: str = ""
    tone: str = ""
    hashtags: str = ""
    email_to: list[str] = field(default_factory=list)
    temperature: float | None = None
    schedule_time: str = ""
    prompt_directions: str = ""
    prompt_analysis: str = ""
    prompt_scripts: str = ""
    prompt_tagline: str = ""

    def effective(self, cfg: "NewsConfig") -> "NewsAccount":
        """以帳號設定為主，缺的欄位回落到 cfg 的全域預設。"""
        return NewsAccount(
            name=self.name,
            enabled=self.enabled,
            place=self.place or "佛山",
            xhs_account=self.xhs_account or self.name,
            query=self.query or cfg.search_query,
            num=self.num or cfg.search_num,
            gl=self.gl or cfg.search_gl,
            hl=self.hl or cfg.search_hl,
            tbs=self.tbs or cfg.search_tbs,
            audience=self.audience or "佛山90後中國打工人",
            topics=self.topics or "佛山AI、佛山機器人、佛山新能源、佛山新材料",
            tone=self.tone or "專業、接地氣、克制且有溫度",
            hashtags=self.hashtags,
            email_to=self.email_to or cfg.email_to,
            temperature=self.temperature if self.temperature is not None else cfg.ai_temperature,
            schedule_time=self.schedule_time,
            prompt_directions=self.prompt_directions,
            prompt_analysis=self.prompt_analysis,
            prompt_scripts=self.prompt_scripts,
            prompt_tagline=self.prompt_tagline,
        )


@dataclass
class NewsConfig:
    root: Path
    data_dir: Path
    db_path: Path
    fixtures_dir: Path

    # 排程
    schedule_time: str = "14:00"
    schedule_daily: bool = True

    # Serper 搜尋
    serper_api_key: str = ""
    search_query: str = "佛山 人工智能 新能源 新材料 无人机"
    search_num: int = 10
    search_gl: str = "cn"
    search_hl: str = "zh-cn"
    search_tbs: str = "qdr:w"

    # AI
    ai_api_key: str = ""
    ai_base_url: str = "https://openrouter.ai/api/v1"
    ai_model: str = "z-ai/glm-5.2"
    ai_temperature: float = 0.4

    # 審批重試上限
    direction_max_retries: int = 2
    script_max_retries: int = 2

    # 本機審批表單伺服器
    web_enabled: bool = True
    web_port: int = 18765

    # Email 回覆監看
    mail_watch_enabled: bool = False
    mail_watch_interval: int = 45
    mail_imap_host: str = ""
    mail_imap_user: str = ""
    mail_imap_password: str = ""

    # 多帳號：news.accounts 未設定時，使用單一 default 帳號
    accounts: list[NewsAccount] = field(default_factory=list)
    accounts_dir: str = ""

    # 電子郵件
    email_from: str = ""
    email_to: list[str] = field(default_factory=list)
    email_cc: list[str] = field(default_factory=list)
    subject_prefix: str = "[佛山產業AI]"

    # Google Sheets 同步（可選）
    google_enabled: bool = False
    google_sheet_id: str = ""
    google_service_account_json: str = ""
    gid_articles: int = 1683679047      # 工作表3
    gid_analysis: int = 1088287865       # 工作表4
    gid_scripts: int = 717831188         # 工作表5
    gid_script_publish: int = 811493070  # Scripts

    @classmethod
    def load(cls, config_path: str | Path | None = None) -> "NewsConfig":
        load_dotenv(PROJECT_ROOT / ".env")
        yaml_path = Path(config_path) if config_path else PROJECT_ROOT / "config.yaml"
        raw = {}
        if yaml_path.exists():
            with open(yaml_path, "r", encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}

        def g(*keys, default=None):
            node = raw.get("news") if isinstance(raw, dict) else None
            for k in keys:
                if not isinstance(node, dict):
                    return default
                node = node.get(k)
                if node is None:
                    return default
            return node

        root = PROJECT_ROOT
        data_dir = root / "data"
        cfg = cls(
            root=root,
            data_dir=data_dir,
            db_path=data_dir / "news.db",
            fixtures_dir=data_dir / "fixtures",
            schedule_time=str(g("schedule", "run_time", default="14:00")),
            serper_api_key=os.getenv("SERPER_API_KEY", ""),
            search_query=os.getenv("NEWS_SEARCH_QUERY", str(g("search", "query", default=cfg_defaults.search_query))),
            search_num=int(g("search", "num", default=10)),
            search_gl=str(g("search", "gl", default="cn")),
            search_hl=str(g("search", "hl", default="zh-cn")),
            search_tbs=str(g("search", "tbs", default="qdr:w")),
            ai_api_key=os.getenv("AI_API_KEY", ""),
            ai_base_url=os.getenv("AI_BASE_URL", "https://openrouter.ai/api/v1"),
            ai_model=os.getenv("NEWS_AI_MODEL", os.getenv("AI_MODEL", "z-ai/glm-5.2")),
            ai_temperature=float(g("ai", "temperature", default=0.4)),
            direction_max_retries=int(g("retries", "direction_max", default=2)),
            script_max_retries=int(g("retries", "script_max", default=2)),
            web_enabled=bool(g("web", "enabled", default=True)),
            web_port=int(g("web", "port", default=18765)),
            mail_watch_enabled=bool(g("mail", "watch", default=False)),
            mail_watch_interval=int(g("mail", "watch_interval_sec", default=45)),
            mail_imap_host=os.getenv("EMAIL_IMAP_HOST", ""),
            mail_imap_user=os.getenv("EMAIL_IMAP_USER", ""),
            mail_imap_password=os.getenv("EMAIL_IMAP_PASSWORD", ""),
            accounts=cls._load_accounts(g("accounts", default=[]) or []),
            accounts_dir=str(g("accounts_dir", default="")),
            email_from=os.getenv("EMAIL_FROM", "") or os.getenv("SMTP_USER", ""),
            email_to=_as_list(os.getenv("EMAIL_TO", "")) or _as_list(g("email", "to", default=[])),
            email_cc=_as_list(os.getenv("EMAIL_CC", "")),
            subject_prefix=str(g("email", "subject_prefix", default="[佛山產業AI]")),
            google_enabled=bool(g("google", "enabled", default=False)),
            google_sheet_id=str(g("google", "sheet_id", default="")),
            google_service_account_json=os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", ""),
            gid_articles=int(g("google", "gid_articles", default=1683679047)),
            gid_analysis=int(g("google", "gid_analysis", default=1088287865)),
            gid_scripts=int(g("google", "gid_scripts", default=717831188)),
            gid_script_publish=int(g("google", "gid_script_publish", default=811493070)),
        )
        # 合併 accounts_dir 下「每個帳號一個 yaml」的設定（改一個檔不影響其他帳號）
        if cfg.accounts_dir:
            cfg.accounts += cls._load_accounts_from_dir(cfg.root / cfg.accounts_dir)
        if not cfg.accounts:
            cfg.accounts = [NewsAccount(name="default")]
        return cfg

    @staticmethod
    def _load_accounts(raw: list) -> list[NewsAccount]:
        out = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            acc = cls._parse_account(item)
            if acc:
                out.append(acc)
        return out

    @staticmethod
    def _parse_account(item: dict) -> NewsAccount | None:
        name = str(item.get("name") or "").strip()
        if not name:
            return None
        return NewsAccount(
            name=name,
            enabled=bool(item.get("enabled", True)),
            place=str(item.get("place") or ""),
            xhs_account=str(item.get("xhs_account") or ""),
            query=str(item.get("query") or ""),
            num=int(item.get("num") or 10),
            gl=str(item.get("gl") or "cn"),
            hl=str(item.get("hl") or "zh-cn"),
            tbs=str(item.get("tbs") or "qdr:w"),
            audience=str(item.get("audience") or ""),
            topics=str(item.get("topics") or ""),
            tone=str(item.get("tone") or ""),
            hashtags=str(item.get("hashtags") or ""),
            email_to=_as_list(item.get("email_to")),
            temperature=float(item["temperature"]) if item.get("temperature") is not None else None,
            schedule_time=str(item.get("schedule_time") or ""),
            prompt_directions=str(item.get("prompt_directions") or ""),
            prompt_analysis=str(item.get("prompt_analysis") or ""),
            prompt_scripts=str(item.get("prompt_scripts") or ""),
            prompt_tagline=str(item.get("prompt_tagline") or ""),
        )

    @classmethod
    def _load_accounts_from_dir(cls, path: Path) -> list[NewsAccount]:
        """讀取資料夾下每個 *.yaml / *.yml 當作一個帳號；單一檔案壞掉只跳過該帳號。"""
        out = []
        if not path.exists() or not path.is_dir():
            return out
        for f in sorted(list(path.glob("*.yaml")) + list(path.glob("*.yml"))):
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    data = yaml.safe_load(fh) or {}
                if not isinstance(data, dict):
                    continue
                data.setdefault("name", f.stem)
                acc = cls._parse_account(data)
                if acc:
                    out.append(acc)
            except Exception as e:  # noqa: BLE001
                print(f"[config] 帳號檔 {f.name} 解析失敗，已跳過：{e}")
        return out

    def enabled_accounts(self) -> list[NewsAccount]:
        if not self.accounts:
            return [NewsAccount(name="default")]
        return [a for a in self.accounts if a.enabled]


class _Defaults:
    search_query = "佛山 人工智能 新能源 新材料 无人机"


cfg_defaults = _Defaults()
