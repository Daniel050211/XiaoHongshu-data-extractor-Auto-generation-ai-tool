"""週次標籤與數據成熟度邏輯。

週次是「固定 7 天區塊」，由 anchor 起算：
  W1 = anchor .. anchor+6, W2 = anchor+7 .. anchor+13, ...
例如 anchor=2026-07-01：W1 = 7/1–7/7，W2 = 7/8–7/14。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

HKT_OFFSET = timedelta(hours=8)


@dataclass(frozen=True)
class Week:
    number: int
    start: date
    end: date

    @property
    def label(self) -> str:
        return f"W{self.number}（{self.start.month}/{self.start.day}–{self.end.month}/{self.end.day}）"

    def __str__(self) -> str:
        return self.label


def week_for_date(d: date, anchor: date, block_size: int = 7) -> int:
    delta = (d - anchor).days
    if delta < 0:
        raise ValueError(f"日期 {d} 早於週次起點 {anchor}")
    return delta // block_size + 1


def week_range(number: int, anchor: date, block_size: int = 7) -> tuple[date, date]:
    start = anchor + timedelta(days=(number - 1) * block_size)
    return start, start + timedelta(days=block_size - 1)


def week_of(number: int, anchor: date, block_size: int = 7) -> Week:
    start, end = week_range(number, anchor, block_size)
    return Week(number, start, end)


def latest_complete_week(run_date: date, anchor: date, block_size: int = 7) -> int:
    """回傳 run_date 之前最後一個「完整結束」的週次（本週目標）。"""
    n = 1
    while True:
        _, end = week_range(n, anchor, block_size)
        if end >= run_date:
            break
        n += 1
    latest = n - 1
    if latest < 1:
        raise ValueError(f"{run_date} 之前還沒有完整的一週（anchor={anchor}）")
    return latest


def age_hours(publish_utc: datetime, scrape_utc: datetime) -> float | None:
    if publish_utc is None or scrape_utc is None:
        return None
    return max(0.0, (scrape_utc - publish_utc).total_seconds() / 3600.0)
