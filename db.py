"""
SQLite database for AITrending — items table + fetch_log table + FTS5 full-text search.
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

    # Fetch log table for monitoring (P1-4)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS fetch_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            feed_name TEXT NOT NULL,
            url TEXT NOT NULL,
            status TEXT NOT NULL,
            error TEXT,
            entry_count INTEGER DEFAULT 0,
            new_count INTEGER DEFAULT 0,
            fetched_at TEXT NOT NULL
        )
    """)

    # Indexes
    conn.execute("CREATE INDEX IF NOT EXISTS idx_items_published_ts ON items(published_ts DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_items_feed ON items(feed_name)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_items_feed_published ON items(feed_name, published_ts DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_items_year ON items(substr(published_ts, 1, 4))")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_fetch_log_feed ON fetch_log(feed_name, fetched_at DESC)")

    conn.commit()
    conn.close()


def get_years():
    """Return distinct years present in the database."""
    conn = get_db()
    try:
        return [
            row["year"]
            for row in conn.execute(
                "SELECT DISTINCT substr(published_ts, 1, 4) as year FROM items WHERE published_ts IS NOT NULL AND published_ts >= '2000-01-01' ORDER BY year DESC"
            ).fetchall()
        ]
    finally:
        conn.close()


def query_items(feed_filter=None, search=None, limit=100, year_filter=None, offset=0):
    """Get items with optional filters, pagination, and full-text search.
    
    Args:
        feed_filter: str (single feed) or list/tuple (multiple feeds for category).
        search: search query string.
        limit: max items to return.
        year_filter: year string to filter by.
        offset: pagination offset.
    
    Returns:
        List of item dicts.
    """
    conn = get_db()
    try:
        where = []
        params = []
        if feed_filter:
            if isinstance(feed_filter, (list, tuple)):
                placeholders = ",".join(["?"] * len(feed_filter))
                where.append(f"feed_name IN ({placeholders})")
                params.extend(feed_filter)
            else:
                where.append("feed_name = ?")
                params.append(feed_filter)
        if year_filter:
            where.append("substr(published_ts, 1, 4) = ?")
            params.append(str(year_filter))

        # Use FTS5 if available, otherwise fall back to LIKE
        if search:
            fts_available = _check_fts(conn)
            if fts_available:
                where.append("items.id IN (SELECT rowid FROM items_fts WHERE items_fts MATCH ?)")
                params.append(_build_fts_query(search))
            else:
                where.append("(title LIKE ? OR summary LIKE ?)")
                q = f"%{search}%"
                params.extend([q, q])

        sql = "SELECT items.* FROM items"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY COALESCE(items.published_ts, items.fetched_at, '1970-01-01') DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        return [dict(row) for row in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def count_items(feed_filter=None, search=None, year_filter=None):
    """Count total items matching the given filters (for pagination)."""
    conn = get_db()
    try:
        where = []
        params = []
        if feed_filter:
            if isinstance(feed_filter, (list, tuple)):
                placeholders = ",".join(["?"] * len(feed_filter))
                where.append(f"feed_name IN ({placeholders})")
                params.extend(feed_filter)
            else:
                where.append("feed_name = ?")
                params.append(feed_filter)
        if year_filter:
            where.append("substr(published_ts, 1, 4) = ?")
            params.append(str(year_filter))
        if search:
            fts_available = _check_fts(conn)
            if fts_available:
                where.append("id IN (SELECT rowid FROM items_fts WHERE items_fts MATCH ?)")
                params.append(_build_fts_query(search))
            else:
                where.append("(title LIKE ? OR summary LIKE ?)")
                q = f"%{search}%"
                params.extend([q, q])

        sql = "SELECT count(*) FROM items"
        if where:
            sql += " WHERE " + " AND ".join(where)
        return conn.execute(sql, params).fetchone()[0]
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


def get_feed_health():
    """Return feed health status based on recent fetch logs.
    
    For each feed in feeds.json, return:
    - last_status: 'ok' or 'error'
    - last_fetched: timestamp of last fetch
    - consecutive_errors: count of consecutive errors
    - last_error: error message if any
    """
    conn = get_db()
    try:
        # Get latest fetch status for each feed
        rows = conn.execute(
            """SELECT feed_name, url, status, error, fetched_at,
               ROW_NUMBER() OVER (PARTITION BY feed_name ORDER BY fetched_at DESC) as rn
               FROM fetch_log
            """,
        ).fetchall()

        health = {}
        for row in rows:
            if row["rn"] == 1:
                # Latest record for this feed
                health[row["feed_name"]] = {
                    "feed_name": row["feed_name"],
                    "last_status": row["status"],
                    "last_fetched": row["fetched_at"],
                    "last_error": row["error"],
                    "consecutive_errors": 0,
                }

        # Count consecutive errors for each feed
        for feed_name in health:
            recent = conn.execute(
                "SELECT status FROM fetch_log WHERE feed_name = ? ORDER BY fetched_at DESC LIMIT 5",
                (feed_name,),
            ).fetchall()
            consec = 0
            for r in recent:
                if r["status"] == "error":
                    consec += 1
                else:
                    break
            health[feed_name]["consecutive_errors"] = consec

        return list(health.values())
    finally:
        conn.close()


def _check_fts(conn):
    """Check if FTS5 virtual table exists."""
    try:
        result = conn.execute(
            "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='items_fts'"
        ).fetchone()
        return result[0] > 0
    except Exception:
        return False


def _build_fts_query(search):
    """Build a FTS5 MATCH query from a search string.
    
    Handles multi-word queries by quoting each term and joining with AND.
    Example: "transformer attention" -> '"transformer" "attention"'
    """
    terms = search.strip().split()
    quoted = [f'"{t}"' for t in terms if t]
    return " ".join(quoted)


def rebuild_fts_index():
    """Create or rebuild the FTS5 full-text search index."""
    conn = get_db()
    try:
        # Drop existing FTS table
        conn.execute("DROP TABLE IF EXISTS items_fts")
        # Create FTS5 virtual table
        conn.execute("""
            CREATE VIRTUAL TABLE items_fts USING fts5(
                title, summary, content='items', content_rowid='id'
            )
        """)
        # Populate from existing items
        conn.execute("""
            INSERT INTO items_fts(rowid, title, summary)
            SELECT id, COALESCE(title, ''), COALESCE(summary, '') FROM items
        """)
        conn.commit()
        count = conn.execute("SELECT count(*) FROM items_fts").fetchone()[0]
        return count
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


def update_fts_for_item(item_id, title, summary):
    """Update FTS index for a single item (called after insert/update)."""
    conn = get_db()
    try:
        # Delete old entry and insert new
        conn.execute("DELETE FROM items_fts WHERE rowid = ?", (item_id,))
        conn.execute(
            "INSERT INTO items_fts(rowid, title, summary) VALUES (?, ?, ?)",
            (item_id, title or "", summary or ""),
        )
        conn.commit()
    except Exception:
        conn.rollback()
    finally:
        conn.close()
