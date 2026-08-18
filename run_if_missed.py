"""登入補跑：若最近一次週五的報告還沒跑，就執行 run_weekly.py。"""
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except AttributeError:
    pass

from xhs_report import storage
from xhs_report.config import Config


def last_friday(today: date) -> date:
    # Python weekday: Monday=0 ... Friday=4
    days_since_friday = (today.weekday() - 4) % 7
    return today - timedelta(days=days_since_friday)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-only", action="store_true", help="只檢查是否需要補跑，不執行")
    args = parser.parse_args()

    cfg = Config.load()
    conn = storage.connect(cfg.db_path)
    row = conn.execute("SELECT MAX(run_date) AS m FROM runs").fetchone()
    conn.close()
    last_run = date.fromisoformat(row["m"]) if row and row["m"] else None
    target = last_friday(date.today())

    if last_run and last_run >= target:
        print(f"[catch-up] 最近執行 {last_run} 已涵蓋週五 {target}，不需補跑")
        return

    print(f"[catch-up] 最近執行 {last_run} 早於週五 {target}，需要補跑")
    if args.check_only:
        return
    subprocess.run([sys.executable, "run_weekly.py"], cwd=str(Path(__file__).resolve().parent))


if __name__ == "__main__":
    main()
