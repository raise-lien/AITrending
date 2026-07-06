"""
RSS fetcher — reads feeds.json, parses with feedparser, upserts into SQLite.
Features: timestamp validation, summary extraction, fetch logging & monitoring.
"""

import json
import os
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import feedparser
import httpx
from db import init_db, get_db, update_fts_for_item

FEEDS_PATH = os.path.join(os.path.dirname(__file__), "feeds.json")


def load_feeds():
    with open(FEEDS_PATH) as f:
        return json.load(f)


def _parse_ts(entry):
    """Extract ISO timestamp from feedparser entry. Returns None if unparseable or invalid."""
    ts = None
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        try:
            dt = time.struct_time(entry.published_parsed)
            ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", dt)
        except Exception:
            pass
    if not ts and hasattr(entry, "published") and entry.published:
        try:
            dt = parsedate_to_datetime(entry.published)
            ts = dt.isoformat()
        except Exception:
            pass
    # Validate: reject timestamps before 2000-01-01 (clearly invalid)
    # Also reject year 0001 which can be misparsed as 2001 by parsedate_to_datetime
    if ts:
        year_part = ts[:4]
        if ts < "2000-01-01" or year_part == "0001":
            return None
    return ts


def _extract_summary(entry):
    """Extract summary from entry, trying multiple fields."""
    summary = getattr(entry, "summary", None)
    if not summary:
        # Try content field as fallback
        content = getattr(entry, "content", None)
        if content and isinstance(content, list) and len(content) > 0:
            summary = content[0].get("value", "")
    if summary and len(summary) > 2000:
        summary = summary[:2000]
    return summary


def _log_fetch(conn, feed_name, url, status, error, entry_count, new_count):
    """Log fetch result to fetch_log table for monitoring."""
    conn.execute(
        """INSERT INTO fetch_log (feed_name, url, status, error, entry_count, new_count, fetched_at)
           VALUES (?, ?, ?, ?, ?, ?, datetime('now'))""",
        (feed_name, url, status, error, entry_count, new_count),
    )
    conn.commit()


def fetch_all():
    """Fetch all feeds, return (new_count, error_count). Also logs results for monitoring."""
    init_db()
    feeds = load_feeds()
    new_total = 0
    errors = 0

    for feed in feeds:
        try:
            new = fetch_one(feed["name"], feed["url"])
            new_total += new
        except Exception as e:
            print(f"[ERR] {feed['name']}: {e}")
            errors += 1
            # Log the error
            conn = get_db()
            try:
                _log_fetch(conn, feed["name"], feed["url"], "error", str(e), 0, 0)
            finally:
                conn.close()

    return new_total, errors


def fetch_one(feed_name, url):
    """Fetch one feed, upsert items. Returns count of new items. Logs result for monitoring."""
    try:
        resp = httpx.get(url, timeout=15, follow_redirects=True)
        resp.raise_for_status()
    except Exception as e:
        conn = get_db()
        try:
            _log_fetch(conn, feed_name, url, "error", str(e), 0, 0)
        finally:
            conn.close()
        raise

    d = feedparser.parse(resp.text)

    if d.bozo:
        print(f"[WARN] {feed_name}: bozo={d.bozo_exception}")

    new = 0
    for entry in d.entries:
        guid = entry.get("id") or entry.get("link") or ""
        if not guid:
            continue
        title = getattr(entry, "title", "(no title)")
        link = getattr(entry, "link", "")
        published = getattr(entry, "published", None)
        published_ts = _parse_ts(entry)
        summary = _extract_summary(entry)

        conn = get_db()
        try:
            existing = conn.execute(
                "SELECT id, title, summary, published_ts FROM items WHERE guid = ?", (guid,)
            ).fetchone()
            if existing:
                if (existing["title"] != title or
                    existing["summary"] != summary or
                    existing["published_ts"] != published_ts):
                    conn.execute(
                        """UPDATE items SET title=?, summary=?, published=?, published_ts=?
                           WHERE guid=?""",
                        (title, summary, published, published_ts, guid),
                    )
                    # Update FTS index
                    update_fts_for_item(existing["id"], title, summary)
            else:
                cursor = conn.execute(
                    """INSERT INTO items (feed_name, title, link, published, published_ts, summary, guid)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (feed_name, title, link, published, published_ts, summary, guid),
                )
                item_id = cursor.lastrowid
                new += 1
                # Update FTS index
                update_fts_for_item(item_id, title, summary)
            conn.commit()
        finally:
            conn.close()

    print(f"[OK] {feed_name}: {new} new / {len(d.entries)} total")

    # Log successful fetch
    conn = get_db()
    try:
        _log_fetch(conn, feed_name, url, "ok", None, len(d.entries), new)
    finally:
        conn.close()

    return new


# ponytail: __main__ self-check fetches one feed and reports
if __name__ == "__main__":
    import sys

    init_db()
    if len(sys.argv) > 1 and sys.argv[1] == "all":
        new, errs = fetch_all()
        print(f"Done: {new} new items, {errs} errors")
    elif len(sys.argv) > 1 and sys.argv[1] == "rebuild-fts":
        from db import rebuild_fts_index
        count = rebuild_fts_index()
        print(f"FTS5 index rebuilt: {count} rows indexed")
    elif len(sys.argv) > 1 and sys.argv[1] == "backfill":
        from db import get_db
        conn = get_db()
        rows = conn.execute("SELECT id, published FROM items WHERE published_ts IS NULL").fetchall()
        print(f"Backfilling {len(rows)} rows...")
        updated = 0
        for row in rows:
            try:
                dt = parsedate_to_datetime(row["published"])
                conn.execute("UPDATE items SET published_ts = ? WHERE id = ?", (dt.isoformat(), row["id"]))
                updated += 1
            except:
                pass
        conn.commit()
        conn.close()
        print(f"Updated {updated} rows")
    else:
        feeds = load_feeds()
        feed = feeds[0]
        print(f"Testing: {feed['name']}")
        n = fetch_one(feed["name"], feed["url"])
        print(f"Inserted {n} new items")
