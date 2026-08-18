"""診斷：印出每個帳號目前實際使用的四段 system prompt 開頭，確認帳號差異。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

from news_app import prompts
from news_app.config import NewsConfig


def head(text: str, n: int = 260) -> str:
    return text[:n] + ("…" if len(text) > n else "")


cfg = NewsConfig.load()
for acc in cfg.accounts:
    eff = acc.effective(cfg)
    print(f"\n{'=' * 70}\n帳號：{eff.name}（enabled={acc.enabled}）")
    print(f"[方向選擇] {head(prompts.select_directions_system(eff))}")
    print(f"[深度分析] {head(prompts.deep_analysis_system(eff))}")
    print(f"[腳本生成] {head(prompts.script_system(eff))}")
    print(f"[Tagline ] {head(prompts.tagline_system(eff))}")
