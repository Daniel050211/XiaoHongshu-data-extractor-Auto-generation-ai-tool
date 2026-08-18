"""載入 config.yaml 與 .env。"""
from __future__ import annotations

import os
import sys
import json
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv

if getattr(sys, "frozen", False):
    # 打包成 exe 時，專案根目錄 = exe 所在資料夾（config/.env/data 放在 exe 旁邊）
    PROJECT_ROOT = Path(sys.executable).resolve().parent
else:
    PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _as_list(value) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [v.strip() for v in value.replace(";", ",").split(",") if v.strip()]
    return [str(v).strip() for v in value if str(v).strip()]


@dataclass
class Config:
    root: Path
    data_dir: Path
    db_path: Path
    reports_dir: Path
    fixtures_dir: Path

    run_day: str
    run_time: str
    anchor: str
    block_size_days: int
    min_window_hours: float

    link_type: str
    excel_path: str
    google_sheet_id: str
    google_gid: int
    google_service_account_json: str
    accounts: list[dict]

    apify_api_key: str
    apify_actor_id: str
    apify_mode: str
    apify_max_results: int
    apify_proxy: str
    apify_network_capture: bool
    apify_user_urls: list[str]
    apify_cookie_string: str

    ai_api_key: str
    ai_base_url: str
    ai_model: str
    ai_temperature: float

    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    email_provider: str
    resend_api_key: str
    sendgrid_api_key: str
    brevo_api_key: str
    email_from: str
    email_use_tls: bool
    email_to: list[str]
    email_cc: list[str]
    subject_prefix: str

    export_csv: bool
    export_pdf: bool
    output_dir: str

    @classmethod
    def load(cls, config_path: str | Path | None = None) -> "Config":
        load_dotenv(PROJECT_ROOT / ".env")
        yaml_path = Path(config_path) if config_path else PROJECT_ROOT / "config.yaml"
        with open(yaml_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

        def g(*keys, default=None):
            node = raw
            for k in keys:
                if not isinstance(node, dict):
                    return default
                node = node.get(k)
                if node is None:
                    return default
            return node

        root = PROJECT_ROOT
        data_dir = root / "data"
        return cls(
            root=root,
            data_dir=data_dir,
            db_path=data_dir / "xhs.db",
            reports_dir=data_dir / "reports",
            fixtures_dir=data_dir / "fixtures",
            run_day=str(g("schedule", "run_day", default="friday")).lower(),
            run_time=str(g("schedule", "run_time", default="09:00")),
            anchor=str(g("weeks", "anchor", default="2026-07-01")),
            block_size_days=int(g("weeks", "block_size_days", default=7)),
            min_window_hours=float(g("weeks", "min_window_hours", default=48)),
            link_type=str(g("link_source", "type", default="excel")).lower(),
            excel_path=str(g("link_source", "excel_path", default="data/posts.xlsx")),
            google_sheet_id=str(g("link_source", "google_sheet_id", default="")),
            google_gid=int(g("link_source", "google_gid", default=0)),
            google_service_account_json=str(g("link_source", "google_service_account_json", default="")),
            accounts=cls._load_accounts(g("accounts", default=[]) or []),
            apify_api_key=os.getenv("APIFY_API_KEY", ""),
            apify_actor_id=str(g("apify", "actor_id", default="svGBZz6n79YbeA3uS")),
            apify_mode=str(g("apify", "mode", default="post_details")).lower(),
            apify_max_results=int(g("apify", "max_results", default=100)),
            apify_proxy=str(g("apify", "proxy", default="RESIDENTIAL")).upper(),
            apify_network_capture=bool(g("apify", "network_capture", default=False)),
            apify_user_urls=_as_list(g("apify", "user_urls", default=[])),
            apify_cookie_string=os.getenv("APIFY_COOKIE_STRING", "") or str(g("apify", "cookie_string", default="")),
            ai_api_key=os.getenv("AI_API_KEY", ""),
            ai_base_url=os.getenv("AI_BASE_URL", str(g("ai", "base_url", default="https://api.openai.com/v1"))),
            ai_model=os.getenv("AI_MODEL", str(g("ai", "model", default="gpt-4o-mini"))),
            ai_temperature=float(g("ai", "temperature", default=0.3)),
            smtp_host=os.getenv("SMTP_HOST", str(g("email", "smtp_host", default="smtp.gmail.com"))),
            smtp_port=int(os.getenv("SMTP_PORT", str(g("email", "smtp_port", default=465)))),
            smtp_user=os.getenv("SMTP_USER", ""),
            smtp_password=os.getenv("SMTP_PASSWORD", ""),
            email_provider=os.getenv("EMAIL_PROVIDER", "").strip().lower(),
            resend_api_key=os.getenv("RESEND_API_KEY", ""),
            sendgrid_api_key=os.getenv("SENDGRID_API_KEY", ""),
            brevo_api_key=os.getenv("BREVO_API_KEY", ""),
            email_from=os.getenv("EMAIL_FROM", "") or str(g("email", "from", default="")),
            email_use_tls=str(g("email", "use_tls", default=True)).lower() in ("true", "1", "yes"),
            email_to=_as_list(os.getenv("EMAIL_TO", "") or g("email", "to", default=[])),
            email_cc=_as_list(os.getenv("EMAIL_CC", "") or g("email", "cc", default=[])),
            subject_prefix=str(g("email", "subject_prefix", default="[小紅書週報]")),
            export_csv=bool(g("report", "export_csv", default=True)),
            export_pdf=bool(g("report", "export_pdf", default=True)),
            output_dir=str(g("report", "output_dir", default="data/reports")),
        )

    @staticmethod
    def _load_accounts(yaml_accounts: list) -> list[dict]:
        def _acc(a: dict, i: int) -> dict:
            out = {"name": str(a.get("name") or f"帳號{i + 1}"),
                   "excel_path": str(a.get("excel_path") or "data/posts.xlsx")}
            if a.get("email_to"):
                out["email_to"] = [str(e).strip() for e in a["email_to"] if str(e).strip()]
            return out

        accounts = [_acc(a, i) for i, a in enumerate(yaml_accounts)]
        if accounts:
            return accounts
        acc_file = PROJECT_ROOT / "data" / "accounts.json"
        if acc_file.exists():
            try:
                raw = json.loads(acc_file.read_text(encoding="utf-8")) or []
                return [_acc(a, i) for i, a in enumerate(raw)]
            except (json.JSONDecodeError, OSError):
                pass
        return []
