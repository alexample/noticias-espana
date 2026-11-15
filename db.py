import json
import os
import sqlite3

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id            INTEGER PRIMARY KEY,
    name          TEXT UNIQUE NOT NULL,
    feed_url      TEXT NOT NULL,
    weight        REAL NOT NULL DEFAULT 1.0,
    enabled       INTEGER NOT NULL DEFAULT 1,
    etag          TEXT,
    last_modified TEXT,
    last_fetch    REAL,
    last_status   TEXT,
    last_items    INTEGER
);

CREATE TABLE IF NOT EXISTS clusters (
    id               INTEGER PRIMARY KEY,
    created_at       REAL NOT NULL,
    updated_at       REAL NOT NULL,   -- última vez que entró un artículo
    first_published  REAL,
    last_published   REAL,
    n_articles       INTEGER NOT NULL DEFAULT 0,
    n_sources        INTEGER NOT NULL DEFAULT 0,
    relevance        REAL NOT NULL DEFAULT 0,
    status           TEXT NOT NULL DEFAULT 'active',  -- active | merged | closed
    merged_into      INTEGER,
    rep_article_id   INTEGER,
    image            TEXT,
    headline         TEXT,     -- redactado por IA
    lead             TEXT,
    body             TEXT,
    ai_written_at    REAL,
    ai_sources_count INTEGER,
    ai_error         TEXT
);
CREATE INDEX IF NOT EXISTS idx_clusters_status_rel ON clusters(status, relevance DESC);

CREATE TABLE IF NOT EXISTS articles (
    id           INTEGER PRIMARY KEY,
    url          TEXT UNIQUE NOT NULL,
    source       TEXT NOT NULL,
    title        TEXT NOT NULL,
    title_key    TEXT NOT NULL,
    summary      TEXT,
    image        TEXT,
    published_at REAL NOT NULL,
    fetched_at   REAL NOT NULL,
    features     TEXT NOT NULL,
    entities     TEXT NOT NULL,
    cluster_id   INTEGER REFERENCES clusters(id),
    match_score  REAL
);
CREATE INDEX IF NOT EXISTS idx_articles_cluster ON articles(cluster_id);
CREATE INDEX IF NOT EXISTS idx_articles_pub ON articles(published_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_articles_source_title ON articles(source, title_key);
"""


def connect(path=None):
    path = path or config.DB_PATH
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init(conn):
    conn.executescript(SCHEMA)
    conn.commit()


def sync_sources(conn, feeds_file=None):
    with open(feeds_file or config.FEEDS_FILE, encoding="utf-8") as f:
        feeds = json.load(f)
    names = []
    for feed in feeds:
        names.append(feed["name"])
        conn.execute(
            """INSERT INTO sources(name, feed_url, weight, enabled) VALUES (?,?,?,1)
               ON CONFLICT(name) DO UPDATE SET feed_url=excluded.feed_url,
                   weight=excluded.weight, enabled=1""",
            (feed["name"], feed["url"], float(feed.get("weight", 1.0))),
        )
    if names:
        q = ",".join("?" * len(names))
        conn.execute(f"UPDATE sources SET enabled=0 WHERE name NOT IN ({q})", names)
    conn.commit()
