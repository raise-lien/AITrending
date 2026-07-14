"""
RSS / API / scrape fetcher — reads feeds.json, upserts into SQLite.
Supports: enabled flag, type=rss|api|scrape, use_curl for Cloudflare bypass,
per-source non-fatal errors, dry-run mode.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from email.utils import parsedate_to_datetime

import feedparser
import httpx

from db import init_db, get_db, update_fts_for_item

FEEDS_PATH = os.path.join(os.path.dirname(__file__), "feeds.json")
UA = "Mozilla/5.0 (compatible; AITrending/1.0)"


def load_feeds(include_disabled: bool = False):
    with open(FEEDS_PATH, encoding="utf-8") as f:
        feeds = json.load(f)
    if include_disabled:
        return feeds
    return [f for f in feeds if f.get("enabled", True) is not False]


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
    if ts:
        year_part = ts[:4]
        if ts < "2000-01-01" or year_part == "0001":
            return None
    return ts


def _extract_summary(entry):
    """Extract summary from entry, trying multiple fields."""
    summary = getattr(entry, "summary", None)
    if not summary:
        content = getattr(entry, "content", None)
        if content and isinstance(content, list) and len(content) > 0:
            summary = content[0].get("value", "")
    if summary and len(summary) > 2000:
        summary = summary[:2000]
    return summary


def _log_fetch(conn, feed_name, url, status, error, entry_count, new_count):
    conn.execute(
        """INSERT INTO fetch_log (feed_name, url, status, error, entry_count, new_count, fetched_at)
           VALUES (?, ?, ?, ?, ?, ?, datetime('now'))""",
        (feed_name, url, status, error, entry_count, new_count),
    )
    conn.commit()


def _http_get(url: str, use_curl: bool = False) -> str:
    """GET url text; optionally via curl subprocess (Cloudflare TLS fingerprint)."""
    if use_curl:
        result = subprocess.run(
            [
                "curl", "-fsSL",
                "-A", UA,
                "-H", "Accept: application/rss+xml, application/xml, text/xml, */*",
                "--max-time", "20",
                url,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or f"curl exit {result.returncode}")
        return result.stdout

    with httpx.Client(timeout=20, follow_redirects=True, headers={"User-Agent": UA}) as client:
        resp = client.get(url)
        resp.raise_for_status()
        return resp.text


def upsert_item(feed_name: str, item: dict) -> bool:
    """
    Upsert one item dict with keys: title, link, guid, summary, published, published_ts.
    Returns True if newly inserted.
    """
    guid = item.get("guid") or item.get("link") or ""
    if not guid:
        return False
    title = item.get("title") or "(no title)"
    link = item.get("link") or ""
    published = item.get("published")
    published_ts = item.get("published_ts")
    summary = item.get("summary")

    conn = get_db()
    try:
        existing = conn.execute(
            "SELECT id, title, summary, published_ts FROM items WHERE guid = ?", (guid,)
        ).fetchone()
        if existing:
            if (
                existing["title"] != title
                or existing["summary"] != summary
                or existing["published_ts"] != published_ts
            ):
                conn.execute(
                    """UPDATE items SET title=?, summary=?, published=?, published_ts=?
                       WHERE guid=?""",
                    (title, summary, published, published_ts, guid),
                )
                update_fts_for_item(existing["id"], title, summary)
            conn.commit()
            return False

        cursor = conn.execute(
            """INSERT INTO items (feed_name, title, link, published, published_ts, summary, guid)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (feed_name, title, link, published, published_ts, summary, guid),
        )
        update_fts_for_item(cursor.lastrowid, title, summary)
        conn.commit()
        return True
    finally:
        conn.close()


def fetch_rss_feed(feed: dict) -> int:
    """Fetch one RSS feed. Returns new item count."""
    feed_name = feed["name"]
    url = feed["url"]
    use_curl = bool(feed.get("use_curl") or feed.get("useCurl"))

    try:
        text = _http_get(url, use_curl=use_curl)
    except Exception as e:
        conn = get_db()
        try:
            _log_fetch(conn, feed_name, url, "error", str(e), 0, 0)
        finally:
            conn.close()
        raise

    d = feedparser.parse(text)
    if d.bozo:
        print(f"[WARN] {feed_name}: bozo={d.bozo_exception}")

    new = 0
    for entry in d.entries:
        guid = entry.get("id") or entry.get("link") or ""
        if not guid:
            continue
        item = {
            "title": getattr(entry, "title", "(no title)"),
            "link": getattr(entry, "link", ""),
            "guid": guid,
            "published": getattr(entry, "published", None),
            "published_ts": _parse_ts(entry),
            "summary": _extract_summary(entry),
        }
        if upsert_item(feed_name, item):
            new += 1

    print(f"[OK] {feed_name}: {new} new / {len(d.entries)} total")
    conn = get_db()
    try:
        _log_fetch(conn, feed_name, url, "ok", None, len(d.entries), new)
    finally:
        conn.close()
    return new


def fetch_special_feed(feed: dict) -> int:
    """Fetch non-RSS source via special_sources."""
    from special_sources import fetch_special

    feed_name = feed["name"]
    url = feed.get("url", "")
    try:
        items = fetch_special(feed)
    except Exception as e:
        conn = get_db()
        try:
            _log_fetch(conn, feed_name, url, "error", str(e), 0, 0)
        finally:
            conn.close()
        raise

    new = 0
    for it in items:
        if upsert_item(feed_name, it):
            new += 1

    print(f"[OK] {feed_name}: {new} new / {len(items)} total")
    conn = get_db()
    try:
        _log_fetch(conn, feed_name, url, "ok", None, len(items), new)
    finally:
        conn.close()
    return new


def fetch_one(feed_name: str, url: str) -> int:
    """Back-compat: fetch by name+url looking up feeds.json, else treat as RSS."""
    feeds = load_feeds(include_disabled=True)
    for f in feeds:
        if f["name"] == feed_name:
            return fetch_feed(f)
    return fetch_rss_feed({"name": feed_name, "url": url, "type": "rss"})


def fetch_feed(feed: dict) -> int:
    """Dispatch a single feed config by type."""
    ftype = (feed.get("type") or "rss").lower()
    if ftype in ("api", "scrape"):
        return fetch_special_feed(feed)
    return fetch_rss_feed(feed)


def fetch_all(dry_run: bool = False):
    """
    Fetch all enabled feeds.
    dry_run=True: validate connectivity / parse counts without writing to DB
      (still logs to stdout; does not upsert).
    Returns (new_count, error_count).
    """
    init_db()
    feeds = load_feeds()
    new_total = 0
    errors = 0

    for feed in feeds:
        name = feed["name"]
        try:
            if dry_run:
                n = _dry_run_one(feed)
                print(f"[DRY] {name}: {n} items visible")
            else:
                n = fetch_feed(feed)
                new_total += n
        except Exception as e:
            print(f"[ERR] {name}: {e}")
            errors += 1
            if not dry_run:
                conn = get_db()
                try:
                    _log_fetch(conn, name, feed.get("url", ""), "error", str(e), 0, 0)
                finally:
                    conn.close()

    return new_total, errors


def _dry_run_one(feed: dict) -> int:
    """Fetch+parse without DB writes; return item count."""
    ftype = (feed.get("type") or "rss").lower()
    if ftype in ("api", "scrape"):
        from special_sources import fetch_special
        return len(fetch_special(feed))

    text = _http_get(feed["url"], use_curl=bool(feed.get("use_curl") or feed.get("useCurl")))
    d = feedparser.parse(text)
    return len(d.entries)


if __name__ == "__main__":
    import sys

    init_db()
    if len(sys.argv) > 1 and sys.argv[1] == "all":
        new, errs = fetch_all()
        print(f"Done: {new} new items, {errs} errors")
    elif len(sys.argv) > 1 and sys.argv[1] == "dry-run":
        new, errs = fetch_all(dry_run=True)
        print(f"Dry-run done: {errs} errors (no DB writes)")
    elif len(sys.argv) > 1 and sys.argv[1] == "rebuild-fts":
        from db import rebuild_fts_index
        count = rebuild_fts_index()
        print(f"FTS5 index rebuilt: {count} rows indexed")
    elif len(sys.argv) > 1 and sys.argv[1] == "backfill":
        conn = get_db()
        rows = conn.execute(
            "SELECT id, published FROM items WHERE published_ts IS NULL"
        ).fetchall()
        print(f"Backfilling {len(rows)} rows...")
        updated = 0
        for row in rows:
            try:
                dt = parsedate_to_datetime(row["published"])
                conn.execute(
                    "UPDATE items SET published_ts = ? WHERE id = ?",
                    (dt.isoformat(), row["id"]),
                )
                updated += 1
            except Exception:
                pass
        conn.commit()
        conn.close()
        print(f"Updated {updated} rows")
    elif len(sys.argv) > 1 and sys.argv[1] == "list":
        for f in load_feeds(include_disabled=True):
            en = "ON " if f.get("enabled", True) is not False else "OFF"
            print(f"  [{en}] {(f.get('type') or 'rss'):7} {f['name']}  ({f.get('category','')})")
    else:
        feeds = load_feeds()
        feed = feeds[0]
        print(f"Testing: {feed['name']}")
        n = fetch_feed(feed)
        print(f"Inserted {n} new items")
