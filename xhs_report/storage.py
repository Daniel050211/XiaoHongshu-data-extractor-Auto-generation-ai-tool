"""SQLite 儲存層。"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

POST_FIELDS = [
    "note_id", "url", "title", "content", "author",
    "publish_time_utc", "publish_hkt", "publish_date", "publish_hour_hkt",
    "like_count", "collect_count", "comment_count", "share_count", "view_count",
    "tags", "image_count", "video_count",
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
    note_id TEXT PRIMARY KEY,
    account TEXT DEFAULT '',
    url TEXT,
    title TEXT,
    content TEXT,
    author TEXT,
    publish_time_utc TEXT,
    publish_hkt TEXT,
    publish_date TEXT,
    publish_hour_hkt INTEGER,
    like_count INTEGER DEFAULT 0,
    collect_count INTEGER DEFAULT 0,
    comment_count INTEGER DEFAULT 0,
    share_count INTEGER DEFAULT 0,
    view_count INTEGER DEFAULT 0,
    tags TEXT,
    image_count INTEGER DEFAULT 0,
    video_count INTEGER DEFAULT 0,
    first_seen_at TEXT,
    last_seen_at TEXT
);
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    note_id TEXT NOT NULL,
    scraped_at TEXT,
    age_hours REAL,
    like_count INTEGER,
    collect_count INTEGER,
    comment_count INTEGER,
    share_count INTEGER,
    view_count INTEGER,
    FOREIGN KEY(note_id) REFERENCES posts(note_id)
);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at TEXT,
    run_date TEXT,
    account TEXT DEFAULT '',
    target_week INTEGER,
    reference_week INTEGER,
    status TEXT,
    notes TEXT
);
CREATE TABLE IF NOT EXISTS summaries (
    account TEXT NOT NULL DEFAULT '',
    week_number INTEGER NOT NULL,
    summary_json TEXT,
    created_at TEXT,
    PRIMARY KEY (account, week_number)
);
"""


def connect(db_path: str | Path):
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


def _migrate(conn):
    """把舊資料庫遷移到支援多帳號的結構。"""
    posts_cols = [r[1] for r in conn.execute("PRAGMA table_info(posts)")]
    if "account" not in posts_cols:
        conn.execute("ALTER TABLE posts ADD COLUMN account TEXT DEFAULT ''")
    runs_cols = [r[1] for r in conn.execute("PRAGMA table_info(runs)")]
    if "account" not in runs_cols:
        conn.execute("ALTER TABLE runs ADD COLUMN account TEXT DEFAULT ''")
    sum_cols = [r[1] for r in conn.execute("PRAGMA table_info(summaries)")]
    if "account" not in sum_cols:
        conn.execute("""
            CREATE TABLE summaries_new (
                account TEXT NOT NULL DEFAULT '',
                week_number INTEGER NOT NULL,
                summary_json TEXT,
                created_at TEXT,
                PRIMARY KEY (account, week_number)
            )
        """)
        conn.execute(
            "INSERT INTO summaries_new (account, week_number, summary_json, created_at) "
            "SELECT '', week_number, summary_json, created_at FROM summaries"
        )
        conn.execute("DROP TABLE summaries")
        conn.execute("ALTER TABLE summaries_new RENAME TO summaries")
    # 舊資料（多帳號前抓的）帳號為空 → 歸入 default 帳號
    conn.execute("UPDATE posts SET account='default' WHERE account='' OR account IS NULL")
    # 若 default 已有同週摘要，刪除舊的空帳號版本（避免唯一鍵衝突）
    conn.execute(
        "DELETE FROM summaries WHERE account='' AND week_number IN "
        "(SELECT week_number FROM summaries WHERE account='default')"
    )
    conn.execute("UPDATE summaries SET account='default' WHERE account='' OR account IS NULL")
    conn.execute("UPDATE runs SET account='default' WHERE account='' OR account IS NULL")
    conn.commit()


def upsert_post(conn, rec: dict, run_at: datetime):
    """寫入/更新帖文，並記錄一次數據快照。"""
    now = run_at.isoformat()
    account = rec.get("account") or ""
    values = [rec.get(f) for f in POST_FIELDS]
    values[POST_FIELDS.index("tags")] = json.dumps(rec.get("tags") or [], ensure_ascii=False)
    exists = conn.execute("SELECT 1 FROM posts WHERE note_id=?", (rec["note_id"],)).fetchone()
    if exists:
        conn.execute(
            f"UPDATE posts SET {', '.join(f'{f}=?' for f in POST_FIELDS)}, account=?, last_seen_at=? WHERE note_id=?",
            values + [account, now, rec["note_id"]],
        )
    else:
        conn.execute(
            f"INSERT INTO posts ({', '.join(POST_FIELDS)}, account, first_seen_at, last_seen_at) "
            f"VALUES ({', '.join('?' * (len(POST_FIELDS) + 3))})",
            values + [account, now, now],
        )
    age = None
    if rec.get("publish_time_utc"):
        try:
            pub = datetime.fromisoformat(rec["publish_time_utc"])
            age = max(0.0, (run_at - pub).total_seconds() / 3600.0)
        except ValueError:
            pass
    conn.execute(
        "INSERT INTO snapshots (note_id, scraped_at, age_hours, like_count, collect_count, comment_count, share_count, view_count) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (rec["note_id"], now, age, rec.get("like_count"), rec.get("collect_count"),
         rec.get("comment_count"), rec.get("share_count"), rec.get("view_count")),
    )


def all_posts(conn) -> list[dict]:
    rows = conn.execute(
        "SELECT p.*, "
        "(SELECT COUNT(DISTINCT date(s.scraped_at)) FROM snapshots s WHERE s.note_id = p.note_id) AS scrape_count "
        "FROM posts p"
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["tags"] = json.loads(d.get("tags") or "[]")
        out.append(d)
    return out


def posts_between(conn, start_date: str, end_date: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM posts WHERE publish_date >= ? AND publish_date <= ?",
        (start_date, end_date),
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["tags"] = json.loads(d.get("tags") or "[]")
        out.append(d)
    return out


def complete_note_ids(conn) -> set[str]:
    """回傳已達「完整」狀態（在不同日期被抓取 ≥2 次）的 note_id 集合。"""
    rows = conn.execute(
        "SELECT p.note_id FROM posts p WHERE "
        "(SELECT COUNT(DISTINCT date(s.scraped_at)) FROM snapshots s WHERE s.note_id = p.note_id) >= 2"
    ).fetchall()
    return {r["note_id"] for r in rows}


def snapshot_series(conn, note_id: str) -> list[dict]:
    """回傳某篇帖文從第一次到最近一次的快照（依抓取時間排序）。"""
    rows = conn.execute(
        "SELECT * FROM snapshots WHERE note_id=? ORDER BY scraped_at ASC",
        (note_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def log_run(conn, run_at: datetime, run_date: str, target_week: int, reference_week: int, status: str, notes: str = "", account: str = ""):
    conn.execute(
        "INSERT INTO runs (run_at, run_date, account, target_week, reference_week, status, notes) VALUES (?,?,?,?,?,?,?)",
        (run_at.isoformat(), run_date, account, target_week, reference_week, status, notes),
    )


def save_summary(conn, account: str, week_number: int, summary: dict, run_at: datetime):
    conn.execute(
        "INSERT INTO summaries (account, week_number, summary_json, created_at) VALUES (?,?,?,?) "
        "ON CONFLICT(account, week_number) DO UPDATE SET summary_json=excluded.summary_json, created_at=excluded.created_at",
        (account or "", week_number, json.dumps(summary, ensure_ascii=False), run_at.isoformat()),
    )


def load_summary(conn, account: str, week_number: int) -> dict | None:
    row = conn.execute(
        "SELECT summary_json FROM summaries WHERE account=? AND week_number=?",
        (account or "", week_number),
    ).fetchone()
    if not row:
        return None
    try:
        return json.loads(row["summary_json"])
    except json.JSONDecodeError:
        return None
