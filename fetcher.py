"""
RSS fetcher — reads feeds.json, parses with feedparser, upserts into SQLite.
ponytail: feedparser handles RSS/Atom, httpx for better timeout handling.
"""

import json
import os
import time
from email.utils import parsedate_to_datetime
import feedparser
import httpx
from db import init_db, get_db

FEEDS_PATH = os.path.join(os.path.dirname(__file__), "feeds.json")


def load_feeds():
    with open(FEEDS_PATH) as f:
        return json.load(f)


def _parse_ts(entry):
    """Extract ISO timestamp from feedparser entry. Returns None if unparseable."""
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        try:
            dt = time.struct_time(entry.published_parsed)
            return time.strftime("%Y-%m-%dT%H:%M:%SZ", dt)
        except:
            pass
    if hasattr(entry, "published") and entry.published:
        try:
            dt = parsedate_to_datetime(entry.published)
            return dt.isoformat()
        except:
            pass
    return None


def fetch_all():
    """Fetch all feeds, return (new_count, error_count)."""
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

    return new_total, errors


def fetch_one(feed_name, url):
    """Fetch one feed, upsert items. Returns count of new items."""
    resp = httpx.get(url, timeout=15, follow_redirects=True)
    resp.raise_for_status()
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
        summary = getattr(entry, "summary", None)
        if summary and len(summary) > 2000:
            summary = summary[:2000]

        # ponytail: on re-fetch, update title/summary/ts if the entry already exists
        # (RSS feeds sometimes update old entries with newer metadata)
        conn = get_db()
        try:
            existing = conn.execute(
                "SELECT id, title, summary, published_ts FROM items WHERE guid = ?", (guid,)
            ).fetchone()
            if existing:
                # Update if title, summary, or timestamp changed
                if (existing["title"] != title or
                    existing["summary"] != summary or
                    existing["published_ts"] != published_ts):
                    conn.execute(
                        """UPDATE items SET title=?, summary=?, published=?, published_ts=?
                           WHERE guid=?""",
                        (title, summary, published, published_ts, guid),
                    )
            else:
                conn.execute(
                    """INSERT INTO items (feed_name, title, link, published, published_ts, summary, guid)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (feed_name, title, link, published, published_ts, summary, guid),
                )
                new += 1
            conn.commit()
        finally:
            conn.close()

    print(f"[OK] {feed_name}: {new} new / {len(d.entries)} total")
    return new


# ponytail: __main__ self-check fetches one feed and reports
if __name__ == "__main__":
    import sys

    init_db()
    if len(sys.argv) > 1 and sys.argv[1] == "all":
        new, errs = fetch_all()
        print(f"Done: {new} new items, {errs} errors")
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
