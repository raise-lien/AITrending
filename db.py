"""
SQLite database for AITrending — one table, simple operations.
ponytail: sqlite3 stdlib, no ORM needed.
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "aitrending.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            feed_name TEXT NOT NULL,
            title TEXT NOT NULL,
            link TEXT NOT NULL,
            published TEXT,
            published_ts TEXT,
            summary TEXT,
            guid TEXT UNIQUE NOT NULL,
            fetched_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    # Add published_ts to existing tables (safe if it already exists)
    try:
        conn.execute("ALTER TABLE items ADD COLUMN published_ts TEXT")
    except:
        pass
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_items_published_ts ON items(published_ts DESC)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_items_feed ON items(feed_name)
    """)
    conn.commit()
    conn.close()


def get_years():
    """Return distinct years present in the database."""
    conn = get_db()
    try:
        return [
            row["year"]
            for row in conn.execute(
                "SELECT DISTINCT substr(published_ts, 1, 4) as year FROM items WHERE published_ts IS NOT NULL ORDER BY year DESC"
            ).fetchall()
        ]
    finally:
        conn.close()


def query_items(feed_filter=None, search=None, limit=100, year_filter=None):
    """Get items, optionally filtered by feed_name, year, or full-text search on title+summary."""
    conn = get_db()
    try:
        where = []
        params = []
        if feed_filter:
            where.append("feed_name = ?")
            params.append(feed_filter)
        if year_filter:
            where.append("substr(published_ts, 1, 4) = ?")
            params.append(str(year_filter))
        if search:
            where.append("(title LIKE ? OR summary LIKE ?)")
            q = f"%{search}%"
            params.extend([q, q])
        sql = "SELECT * FROM items"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY COALESCE(published_ts, CAST(strftime('%s', fetched_at) AS REAL), 0) DESC LIMIT ?"
        params.append(limit)
        return [dict(row) for row in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def get_feeds_with_counts(year_filter=None):
    """Return distinct feed names with their item counts, optionally filtered by year."""
    conn = get_db()
    try:
        if year_filter:
            return [
                dict(row)
                for row in conn.execute(
                    "SELECT feed_name, count(*) as cnt FROM items WHERE substr(published_ts, 1, 4) = ? GROUP BY feed_name ORDER BY cnt DESC",
                    (str(year_filter),),
                ).fetchall()
            ]
        else:
            return [
                dict(row)
                for row in conn.execute(
                    "SELECT feed_name, count(*) as cnt FROM items GROUP BY feed_name ORDER BY cnt DESC"
                ).fetchall()
            ]
    finally:
        conn.close()
