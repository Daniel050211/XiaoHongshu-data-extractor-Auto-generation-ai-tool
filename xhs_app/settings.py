"""讀寫 .env 設定檔。"""
from __future__ import annotations

from pathlib import Path


def load_env(path: str | Path) -> dict[str, str]:
    result: dict[str, str] = {}
    p = Path(path)
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                result[k.strip()] = v.strip()
    return result


def save_env(path: str | Path, values: dict[str, str]) -> None:
    """更新 .env：保留註解與未修改的欄位，覆寫有變更的欄位。"""
    p = Path(path)
    lines = p.read_text(encoding="utf-8").splitlines() if p.exists() else []
    keys = set(values)
    out: list[str] = []
    written: set[str] = set()
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            k = stripped.split("=", 1)[0].strip()
            if k in keys:
                out.append(f"{k}={values[k]}")
                written.add(k)
                continue
        out.append(line)
    for k, v in values.items():
        if k not in written:
            out.append(f"{k}={v}")
    p.write_text("\n".join(out) + "\n", encoding="utf-8")
