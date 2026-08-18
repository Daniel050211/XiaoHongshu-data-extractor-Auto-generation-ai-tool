"""新聞線 SQLite 儲存層。"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

# exe 模式：專案根目錄 = exe 所在資料夾，避免 data/ 指到 PyInstaller 暫存夾
if getattr(sys, "frozen", False):
    PROJECT_ROOT = Path(sys.executable).resolve().parent
else:
    PROJECT_ROOT = Path(__file__).resolve().parent.parent

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account TEXT DEFAULT 'default',
    run_date TEXT,
    started_at TEXT,
    updated_at TEXT,
    status TEXT DEFAULT 'running',
    query TEXT DEFAULT '',
    articles_count INTEGER DEFAULT 0,
    retry_direction INTEGER DEFAULT 0,
    retry_script INTEGER DEFAULT 0,
    news_summary TEXT DEFAULT '',
    articles_text TEXT DEFAULT '',
    chosen_direction TEXT DEFAULT '',
    analysis TEXT DEFAULT '',
    enhanced_prompt TEXT DEFAULT '',
    versions_json TEXT DEFAULT '[]',
    script_to_publish TEXT DEFAULT '',
    style TEXT DEFAULT '',
    tagline TEXT DEFAULT '',
    image_prompt TEXT DEFAULT '',
    direction_email TEXT DEFAULT '',
    script_email TEXT DEFAULT '',
    error TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS articles (
    id TEXT NOT NULL,
    run_id INTEGER NOT NULL,
    idx INTEGER NOT NULL,
    topic TEXT DEFAULT '',
    title TEXT DEFAULT '',
    url TEXT DEFAULT '',
    snippet TEXT DEFAULT '',
    source TEXT DEFAULT '',
    date TEXT DEFAULT '',
    saved_at TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS directions (
    run_id INTEGER NOT NULL,
    idx INTEGER NOT NULL,
    title TEXT DEFAULT '',
    description TEXT DEFAULT '',
    sources_json TEXT DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS versions (
    run_id INTEGER NOT NULL,
    idx INTEGER NOT NULL,
    style TEXT DEFAULT '',
    content TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    at TEXT,
    level TEXT DEFAULT 'info',
    message TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS news_memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account TEXT DEFAULT 'default',
    run_id INTEGER NOT NULL,
    created_at TEXT,
    memory_text TEXT DEFAULT ''
);
"""


def connect(db_path: str | Path):
    conn = sqlite3.connect(str(db_path), timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    has_runs = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='runs'"
    ).fetchone()
    if not has_runs:
        conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


def _migrate(conn):
    cols = [r[1] for r in conn.execute("PRAGMA table_info(runs)")]
    if "account" not in cols:
        conn.execute("ALTER TABLE runs ADD COLUMN account TEXT DEFAULT 'default'")
        conn.execute("UPDATE runs SET account='default' WHERE account IS NULL OR account=''")
        conn.commit()


def connect_from_cfg(cfg) -> sqlite3.Connection:
    """由 NewsConfig 開連線（供多執行緒各自使用）。"""
    return connect(cfg.db_path)


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def create_run(conn, run_date: str, query: str = "", account: str = "default") -> int:
    ts = now_iso()
    cur = conn.execute(
        "INSERT INTO runs (account, run_date, started_at, updated_at, status, query) VALUES (?,?,?,?,?,?)",
        (account or "default", run_date, ts, ts, "running", query),
    )
    conn.commit()
    return cur.lastrowid


def set_run_status(conn, run_id: int, status: str, error: str = ""):
    conn.execute(
        "UPDATE runs SET status=?, error=?, updated_at=? WHERE id=?",
        (status, error, now_iso(), run_id),
    )
    conn.commit()


def update_run(conn, run_id: int, **fields):
    if not fields:
        return
    keys = ", ".join(f"{k}=?" for k in fields)
    conn.execute(f"UPDATE runs SET {keys}, updated_at=? WHERE id=?", (*fields.values(), now_iso(), run_id))
    conn.commit()


def add_event(conn, run_id: int, message: str, level: str = "info"):
    conn.execute("INSERT INTO events (run_id, at, level, message) VALUES (?,?,?,?)",
                 (run_id, now_iso(), level, message))
    conn.commit()


def save_articles(conn, run_id: int, articles: list[dict]):
    for i, a in enumerate(articles, start=1):
        conn.execute(
            "INSERT INTO articles (id, run_id, idx, topic, title, url, snippet, source, date, saved_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (a.get("id"), run_id, i, a.get("topic"), a.get("title"), a.get("url"),
             a.get("snippet"), a.get("source"), a.get("date"), now_iso()),
        )
    conn.commit()


def save_directions(conn, run_id: int, directions: list[dict]):
    conn.execute("DELETE FROM directions WHERE run_id=?", (run_id,))
    for i, d in enumerate(directions, start=1):
        conn.execute(
            "INSERT INTO directions (run_id, idx, title, description, sources_json) VALUES (?,?,?,?,?)",
            (run_id, i, d.get("title"), d.get("description"), json.dumps(d.get("sources") or [], ensure_ascii=False)),
        )
    conn.commit()


def get_directions(conn, run_id: int) -> list[dict]:
    rows = conn.execute("SELECT * FROM directions WHERE run_id=? ORDER BY idx", (run_id,)).fetchall()
    out = []
    for r in rows:
        out.append({
            "idx": r["idx"],
            "title": r["title"],
            "description": r["description"],
            "sources": json.loads(r["sources_json"] or "[]"),
        })
    return out


def save_versions(conn, run_id: int, versions: list[dict]):
    conn.execute("DELETE FROM versions WHERE run_id=?", (run_id,))
    for i, v in enumerate(versions, start=1):
        conn.execute(
            "INSERT INTO versions (run_id, idx, style, content) VALUES (?,?,?,?)",
            (run_id, i, v.get("style"), v.get("content")),
        )
    conn.commit()


def get_versions(conn, run_id: int) -> list[dict]:
    rows = conn.execute("SELECT * FROM versions WHERE run_id=? ORDER BY idx", (run_id,)).fetchall()
    return [{"idx": r["idx"], "style": r["style"], "content": r["content"]} for r in rows]


def get_run(conn, run_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
    if not row:
        return None
    return dict(row)


def list_runs(conn, limit: int = 50) -> list[dict]:
    rows = conn.execute(
        "SELECT id, account, run_date, started_at, status, articles_count, retry_direction, retry_script, "
        "style, tagline, error FROM runs ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def pending_runs(conn, status: str) -> list[dict]:
    rows = conn.execute(
        "SELECT id, account, run_date, started_at, status, retry_direction, retry_script FROM runs "
        "WHERE status=? ORDER BY id DESC",
        (status,),
    ).fetchall()
    return [dict(r) for r in rows]


def run_events(conn, run_id: int) -> list[dict]:
    rows = conn.execute("SELECT at, level, message FROM events WHERE run_id=? ORDER BY id", (run_id,)).fetchall()
    return [dict(r) for r in rows]


def latest_feedback_from_xhs(account: str = "") -> str:
    """從既有 XHS 報表資料庫讀指定帳號的最新摘要，作為發布策略依據；讀不到就回傳空字串。"""
    db = PROJECT_ROOT / "data" / "xhs.db"
    if not db.exists():
        return ""
    try:
        conn = sqlite3.connect(str(db))
        conn.row_factory = sqlite3.Row
        if account:
            row = conn.execute(
                "SELECT summary_json, created_at FROM summaries WHERE account=? "
                "ORDER BY week_number DESC LIMIT 1",
                (account,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT summary_json, created_at FROM summaries ORDER BY week_number DESC LIMIT 1"
            ).fetchone()
        conn.close()
        if not row:
            return ""
        data = json.loads(row["summary_json"] or "{}")
        sections = data.get("sections") or {}
        if isinstance(sections, dict):
            return str(sections.get("摘要") or sections.get("执行摘要") or "")
        if isinstance(sections, str):
            return sections
    except Exception:
        return ""
    return ""


def save_memory(conn, run_id: int, account: str, memory_text: str):
    conn.execute(
        "INSERT INTO news_memory (account, run_id, created_at, memory_text) VALUES (?,?,?,?)",
        (account or "default", run_id, now_iso(), memory_text),
    )
    conn.commit()


def latest_memory(conn, account: str) -> str:
    row = conn.execute(
        "SELECT memory_text FROM news_memory WHERE account=? ORDER BY id DESC LIMIT 1",
        (account or "default",),
    ).fetchone()
    return row["memory_text"] if row else ""
