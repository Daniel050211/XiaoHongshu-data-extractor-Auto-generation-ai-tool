"""管理 Windows 排程（每週自動執行）。"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

TASK_NAME = "XHS Weekly Report"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "data" / "schedule_config.json"

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
DAY_LABELS = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]


def default_config() -> dict:
    return {"enabled": True, "day": "Friday", "hour": 9, "minute": 0}


def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            cfg.setdefault("enabled", True)
            cfg.setdefault("day", "Friday")
            cfg.setdefault("hour", 9)
            cfg.setdefault("minute", 0)
            return cfg
        except (json.JSONDecodeError, OSError):
            pass
    return default_config()


def save_config(cfg: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def _run_ps(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90,
    )


def get_task_status() -> dict:
    """回傳排程狀態：STATE / LAST / NEXT / RESULT。"""
    script = f"""$t = Get-ScheduledTask -TaskName '{TASK_NAME}' -ErrorAction SilentlyContinue
if (-not $t) {{ Write-Output 'STATE=MISSING'; exit }}
$i = Get-ScheduledTaskInfo -TaskName '{TASK_NAME}'
Write-Output "STATE=$($t.State)"
Write-Output "LAST=$($i.LastRunTime)"
Write-Output "NEXT=$($i.NextRunTime)"
Write-Output "RESULT=$($i.LastTaskResult)"
"""
    r = _run_ps(script)
    out: dict[str, str] = {}
    for line in (r.stdout or "").splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip()
    return out


def apply_schedule(cfg: dict) -> str:
    """依設定建立/更新或移除排程，回傳訊息。"""
    save_config(cfg)
    if not cfg.get("enabled"):
        script = f"Unregister-ScheduledTask -TaskName '{TASK_NAME}' -Confirm:$false -ErrorAction SilentlyContinue"
        _run_ps(script)
        return "已停用（移除每週自動執行）"

    proj = str(PROJECT_ROOT)
    time_str = f"{int(cfg.get('hour', 9)):02d}:{int(cfg.get('minute', 0)):02d}"
    day = cfg.get("day", "Friday")
    if getattr(sys, "frozen", False):
        action_exec = sys.executable
        action_args = "--run"
    else:
        action_exec = sys.executable
        action_args = "run_weekly.py"
    script = f"""$action = New-ScheduledTaskAction -Execute '{action_exec}' -Argument '{action_args}' -WorkingDirectory '{proj}'
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek {day} -At '{time_str}'
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 3)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName '{TASK_NAME}' -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
"""
    r = _run_ps(script)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout or "").strip()[:300])
    label = DAY_LABELS[DAYS.index(day)] if day in DAYS else day
    return f"已設定：每週{label} {time_str} 自動執行"


def run_now() -> str:
    script = f"Start-ScheduledTask -TaskName '{TASK_NAME}'"
    r = _run_ps(script)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout or "").strip()[:300])
    return "已觸發執行"
