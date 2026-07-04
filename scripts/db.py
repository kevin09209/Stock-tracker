"""Shared storage helpers for the stock tracker.

SQLite schema:
  posts(id TEXT PK, date TEXT 'YYYY-MM-DD' in account tz, ts TEXT ISO8601, text TEXT, url TEXT)
  mentions(post_id TEXT, ticker TEXT, stance TEXT)   -- stance: bull | bear | neutral | background
  prices(ticker TEXT, date TEXT, close REAL)         -- daily closes, PK (ticker, date)
"""
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "tracker.db"
CONFIG_PATH = ROOT / "config.json"


def load_config():
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def connect(db_path=None):
    path = Path(db_path) if db_path else DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS posts (
            id   TEXT PRIMARY KEY,
            date TEXT NOT NULL,
            ts   TEXT NOT NULL,
            text TEXT NOT NULL,
            url  TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS mentions (
            post_id TEXT NOT NULL REFERENCES posts(id),
            ticker  TEXT NOT NULL,
            stance  TEXT NOT NULL,
            PRIMARY KEY (post_id, ticker)
        );
        CREATE TABLE IF NOT EXISTS prices (
            ticker TEXT NOT NULL,
            date   TEXT NOT NULL,
            close  REAL NOT NULL,
            PRIMARY KEY (ticker, date)
        );
        CREATE INDEX IF NOT EXISTS idx_mentions_ticker ON mentions(ticker);
        CREATE INDEX IF NOT EXISTS idx_posts_date ON posts(date);
        """
    )
    return con


def close_on_or_before(con, ticker, date):
    """Latest known close on or before `date` (handles weekends/holidays)."""
    row = con.execute(
        "SELECT close, date FROM prices WHERE ticker=? AND date<=? ORDER BY date DESC LIMIT 1",
        (ticker, date),
    ).fetchone()
    return (row["close"], row["date"]) if row else (None, None)
