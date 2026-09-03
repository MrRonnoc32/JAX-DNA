"""SQLite storage for JAX DNA.

Only post text, timestamp, source, and a source-assigned ID are stored.
No author names or handles are kept.
"""
import os
import sqlite3
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
    id            TEXT PRIMARY KEY,        -- source-prefixed id, e.g. reddit:t3_abc or bsky:at://...
    source        TEXT NOT NULL,           -- reddit | bluesky | google | x
    subsource     TEXT,                    -- subreddit name, search term, place id
    kind          TEXT,                    -- submission | comment | post | review
    created_utc   INTEGER NOT NULL,
    text          TEXT NOT NULL,
    url           TEXT,
    engagement    INTEGER DEFAULT 0,       -- upvotes / likes, for optional weighting
    collected_utc INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_posts_created ON posts(created_utc);
CREATE INDEX IF NOT EXISTS idx_posts_source ON posts(source);

CREATE TABLE IF NOT EXISTS scores (
    post_id       TEXT PRIMARY KEY REFERENCES posts(id) ON DELETE CASCADE,
    vader         REAL,                    -- compound score, -1..1
    roberta       REAL,                    -- P(positive) - P(negative), -1..1
    roberta_label TEXT,
    scored_utc    INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS post_topics (
    post_id       TEXT REFERENCES posts(id) ON DELETE CASCADE,
    topic         TEXT NOT NULL,
    PRIMARY KEY (post_id, topic)
);

CREATE TABLE IF NOT EXISTS collection_log (
    run_utc       INTEGER NOT NULL,
    source        TEXT NOT NULL,
    subsource     TEXT,
    fetched       INTEGER,
    inserted      INTEGER,
    note          TEXT
);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


def connect(path):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    return conn


def insert_posts(conn, rows):
    """rows: iterable of dicts with keys matching posts columns. Returns count inserted."""
    now = int(time.time())
    before = conn.total_changes
    conn.executemany(
        """INSERT OR IGNORE INTO posts
           (id, source, subsource, kind, created_utc, text, url, engagement, collected_utc)
           VALUES (:id, :source, :subsource, :kind, :created_utc, :text, :url, :engagement, :collected_utc)""",
        [dict(r, collected_utc=now, engagement=r.get("engagement", 0), url=r.get("url"), kind=r.get("kind")) for r in rows],
    )
    conn.commit()
    return conn.total_changes - before


def log_run(conn, source, subsource, fetched, inserted, note=""):
    conn.execute(
        "INSERT INTO collection_log (run_utc, source, subsource, fetched, inserted, note) VALUES (?,?,?,?,?,?)",
        (int(time.time()), source, subsource, fetched, inserted, note),
    )
    conn.commit()


def set_meta(conn, key, value):
    conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?,?)", (key, str(value)))
    conn.commit()


def get_meta(conn, key, default=None):
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def unscored_posts(conn):
    return conn.execute(
        "SELECT p.id, p.text FROM posts p LEFT JOIN scores s ON s.post_id = p.id WHERE s.post_id IS NULL"
    ).fetchall()


def latest_created(conn, source, subsource=None):
    if subsource is None:
        row = conn.execute("SELECT MAX(created_utc) m FROM posts WHERE source=?", (source,)).fetchone()
    else:
        row = conn.execute(
            "SELECT MAX(created_utc) m FROM posts WHERE source=? AND subsource=?", (source, subsource)
        ).fetchone()
    return row["m"] or 0
