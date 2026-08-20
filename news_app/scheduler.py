"""管理 Windows 排程：預設排程跑「沒有自己排程」的帳號；每個帳號可有獨立排程。"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

TASK_NAME = "佛山新聞 AI"
# exe 模式：專案根目錄 = exe 所在資料夾，排程設定才會持久化
if getattr(sys, "frozen", False):
    PROJECT_ROOT = Path(sys.executable).resolve().parent
else:
    PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "data" / "news_schedule_config.json"

DAY_MAP = {
    "mon": "Monday", "monday": "Monday",
    "tue": "Tuesday", "tuesday": "Tuesday",
    "wed": "Wednesday", "wednesday": "Wednesday",
    "thu": "Thursday", "thursday": "Thursday",
    "fri": "Friday", "friday": "Friday",
    "sat": "Saturday", "saturday": "Saturday",
    "sun": "Sunday", "sunday": "Sunday",
}

CN_DAY = {"一": "mon", "二": "tue", "三": "wed", "四": "thu",
          "五": "fri", "六": "sat", "日": "sun", "天": "sun"}
CODE_CN = {"mon": "一", "tue": "二", "wed": "三", "thu": "四",
           "fri": "五", "sat": "六", "sun": "日"}


def normalize_days(days) -> str:
    """把「一,三 / 周一,周三 / mon,wed」統一成 mon,wed；空則回 ""。"""
    out: list[str] = []
    text = str(days or "").replace("；", ",").replace("、", ",").replace(";", ",")
    for d in text.split(","):
        d = d.strip().lower()
        d = d.replace("星期", "").replace("週", "").replace("周", "")
        if d in CN_DAY:
            d = CN_DAY[d]
        if d in DAY_MAP and d not in out:
            out.append(d)
    return ",".join(out)


def display_days(days) -> str:
    """把 mon,wed 顯示成「一、三」，方便非技術使用者閱讀。"""
    return "、".join(CODE_CN.get(d, d) for d in normalize_days(days).split(",") if d)


def parse_days(days) -> list[str]:
    """把 mon,wed 轉成 Windows 用的 Monday,Wednesday；空則回 []（表示每天）。"""
    return [DAY_MAP[d] for d in normalize_days(days).split(",") if d]


def has_own_schedule(acc: dict) -> bool:
    return bool(str(acc.get("schedule_time") or "").strip())


def scheduled_accounts(accounts: list[dict]) -> list[dict]:
    """啟用且有自己排程時間的帳號（各自建立獨立任務）。"""
    return [a for a in accounts if a.get("enabled", True) and has_own_schedule(a)]


def default_accounts(accounts: list[dict]) -> list[dict]:
    """啟用但沒有自己排程的帳號（歸預設排程管）。"""
    return [a for a in accounts if a.get("enabled", True) and not has_own_schedule(a)]


def default_config() -> dict:
    return {"enabled": True, "hour": 14, "minute": 0}


def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            cfg.setdefault("enabled", True)
            cfg.setdefault("hour", 14)
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
    script = f"""$t = Get-ScheduledTask -TaskName '{TASK_NAME}' -ErrorAction SilentlyContinue
if (-not $t) {{ Write-Output 'STATE=MISSING' }} else {{
$i = Get-ScheduledTaskInfo -TaskName '{TASK_NAME}'
Write-Output "STATE=$($t.State)"
Write-Output "LAST=$($i.LastRunTime)"
Write-Output "NEXT=$($i.NextRunTime)"
Write-Output "RESULT=$($i.LastTaskResult)"
}}
$accs = Get-ScheduledTask | Where-Object {{ $_.TaskName -like '{TASK_NAME} - *' }} | Sort-Object TaskName
$accOut = foreach ($a in $accs) {{
  $ai = Get-ScheduledTaskInfo -TaskName $a.TaskName
  "$($a.TaskName)|$($a.State)|$($ai.NextRunTime)"
}}
Write-Output "ACCTASKS=$($accOut -join ';')"
"""
    r = _run_ps(script)
    out: dict[str, str] = {}
    for line in (r.stdout or "").splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip()
    return out


def apply_schedule(cfg: dict) -> str:
    save_config(cfg)
    proj = str(PROJECT_ROOT)
    if getattr(sys, "frozen", False):
        action_exec = sys.executable
        default_args = "--run --skip-scheduled"
    else:
        action_exec = sys.executable
        default_args = "run_news.py --run --skip-scheduled"

    settings = ("$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable "
                "-ExecutionTimeLimit (New-TimeSpan -Hours 6)")
    principal = ("$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME "
                 "-LogonType Interactive -RunLevel Limited")

    parts: list[str] = []
    summary: list[str] = []

    # 1) 預設排程（只跑「沒有自己排程」的啟用帳號）
    if not cfg.get("enabled"):
        parts.append(
            f"Unregister-ScheduledTask -TaskName '{TASK_NAME}' -Confirm:$false -ErrorAction SilentlyContinue"
        )
        summary.append("預設排程已停用")
    else:
        time_str = f"{int(cfg.get('hour', 14)):02d}:{int(cfg.get('minute', 0)):02d}"
        parts.append(
            f"$action = New-ScheduledTaskAction -Execute '{action_exec}' -Argument '{default_args}' -WorkingDirectory '{proj}'\n"
            f"$trigger = New-ScheduledTaskTrigger -Daily -At '{time_str}'\n"
            f"{settings}\n{principal}\n"
            f"Register-ScheduledTask -TaskName '{TASK_NAME}' -Action $action -Trigger $trigger "
            f"-Settings $settings -Principal $principal -Force | Out-Null"
        )
        summary.append(f"預設排程：每天 {time_str}")

    # 2) 每個帳號自己的排程
    try:
        from . import account_store
        accounts = account_store.list_accounts()
    except Exception:  # noqa: BLE001
        accounts = []
    desired: set[str] = set()
    for acc in scheduled_accounts(accounts):
        name = str(acc.get("name") or "")
        tname = f"{TASK_NAME} - {name}"
        desired.add(tname)
        time_str = str(acc.get("schedule_time") or "").strip()
        if ":" not in time_str:
            continue
        days = parse_days(acc.get("schedule_days"))
        if days:
            trigger = f"New-ScheduledTaskTrigger -Weekly -DaysOfWeek {','.join(days)} -At '{time_str}'"
            day_label = "、".join(days)
        else:
            trigger = f"New-ScheduledTaskTrigger -Daily -At '{time_str}'"
            day_label = "每天"
        account_args = f"--run --account {name}"
        parts.append(
            f"$action = New-ScheduledTaskAction -Execute '{action_exec}' -Argument '{account_args}' -WorkingDirectory '{proj}'\n"
            f"$trigger = {trigger}\n"
            f"{settings}\n{principal}\n"
            f"Register-ScheduledTask -TaskName '{tname}' -Action $action -Trigger $trigger "
            f"-Settings $settings -Principal $principal -Force | Out-Null"
        )
        summary.append(f"「{name}」：{day_label} {time_str}")

    # 3) 清掉已刪除/停用帳號的舊任務
    keep = "', '".join(sorted(desired))
    parts.append(
        f"$keep = @('{keep}')\n"
        f"Get-ScheduledTask | Where-Object {{ $_.TaskName -like '{TASK_NAME} - *' -and $keep -notcontains $_.TaskName }} "
        "| ForEach-Object { Unregister-ScheduledTask -TaskName $_.TaskName -Confirm:$false }"
    )

    r = _run_ps("\n".join(parts))
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout or "").strip()[:300])
    return "排程已套用：" + "；".join(summary)


def run_now() -> str:
    script = f"Start-ScheduledTask -TaskName '{TASK_NAME}'"
    r = _run_ps(script)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout or "").strip()[:300])
    return "已觸發執行"
