"""
Data migration script for P0 fixes:
1. Fix timestamp dirty data (0001-01-01 -> NULL)
2. Fix feed name inconsistency (OpenAI Blog -> OpenAI, remove orphaned Hugging Face Blog)
3. Backfill missing summaries where possible

Run once: python3 migrate.py
"""

import sqlite3
import os
from email.utils import parsedate_to_datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "aitrending.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def fix_timestamps(conn):
    """Fix invalid timestamps (0001-01-01 or pre-1900)."""
    print("=== P0-1: Fixing timestamp dirty data ===")

    # Count bad timestamps
    bad = conn.execute(
        "SELECT count(*) FROM items WHERE published_ts IS NOT NULL AND published_ts < '1900-01-01'"
    ).fetchone()[0]
    print(f"  Found {bad} rows with invalid timestamps (< 1900-01-01)")

    # Set invalid timestamps to NULL
    conn.execute(
        "UPDATE items SET published_ts = NULL WHERE published_ts IS NOT NULL AND published_ts < '1900-01-01'"
    )

    # Also fix published text for those rows
    conn.execute(
        """UPDATE items SET published = NULL 
           WHERE published_ts IS NULL 
           AND published LIKE '%0001%'"""
    )

    conn.commit()
    print(f"  Fixed {bad} rows (set published_ts to NULL)")

    # Try to re-parse from published text for rows with NULL published_ts
    rows = conn.execute(
        "SELECT id, published FROM items WHERE published_ts IS NULL AND published IS NOT NULL"
    ).fetchall()
    print(f"  Attempting to re-parse {len(rows)} rows from published text...")
    updated = 0
    for row in rows:
        try:
            dt = parsedate_to_datetime(row["published"])
            ts = dt.isoformat()
            # Validate the parsed timestamp
            if ts and not ts.startswith("0001") and ts >= "1900-01-01":
                conn.execute(
                    "UPDATE items SET published_ts = ? WHERE id = ?", (ts, row["id"])
                )
                updated += 1
        except Exception:
            pass
    conn.commit()
    print(f"  Re-parsed {updated} rows from published text")

    remaining = conn.execute(
        "SELECT count(*) FROM items WHERE published_ts IS NULL"
    ).fetchone()[0]
    print(f"  Remaining NULL timestamps: {remaining}")


def fix_feed_names(conn):
    """Fix feed name inconsistency."""
    print("\n=== P0-2: Fixing feed name inconsistency ===")

    # OpenAI Blog -> OpenAI
    renamed = conn.execute(
        "UPDATE items SET feed_name = 'OpenAI' WHERE feed_name = 'OpenAI Blog'"
    )
    print(f"  Renamed 'OpenAI Blog' -> 'OpenAI': {renamed.rowcount} rows")

    # Hugging Face Blog is no longer in feeds.json — keep data but mark it
    # We'll keep the data since it has value, but the user should know it's orphaned
    hf_count = conn.execute(
        "SELECT count(*) FROM items WHERE feed_name = 'Hugging Face Blog'"
    ).fetchone()[0]
    print(f"  'Hugging Face Blog' has {hf_count} rows (no longer in feeds.json, keeping as orphan)")

    conn.commit()

    # Verify
    print("\n  Verification — feed names after migration:")
    for row in conn.execute(
        "SELECT feed_name, count(*) as cnt FROM items GROUP BY feed_name ORDER BY cnt DESC"
    ).fetchall():
        print(f"    {row['feed_name']}: {row['cnt']}")


def backfill_summaries(conn):
    """Backfill missing summaries."""
    print("\n=== P0-3: Backfilling missing summaries ===")

    # Check which feeds have missing summaries
    print("  Feeds with missing summaries:")
    for row in conn.execute(
        """SELECT feed_name, count(*) as cnt, 
           SUM(CASE WHEN summary IS NULL OR summary = '' THEN 1 ELSE 0 END) as null_cnt
           FROM items GROUP BY feed_name 
           HAVING null_cnt > 0 ORDER BY null_cnt DESC"""
    ).fetchall():
        print(f"    {row['feed_name']}: {row['null_cnt']}/{row['cnt']} null")

    # For Hugging Face Blog — summaries are genuinely absent from the RSS feed
    # Nothing we can do without re-fetching from a different source
    print("\n  Note: Hugging Face Blog summaries are absent from the RSS feed.")
    print("  These will remain NULL until a new source is added or AI summaries are implemented.")

    # For OpenAI Blog (now OpenAI) with null summaries — check if we can extract from link
    # Actually these are from the old OpenAI Blog feed which may have had full content
    # Let's check what the non-null summaries look like
    sample = conn.execute(
        "SELECT summary FROM items WHERE feed_name = 'OpenAI' AND summary IS NOT NULL AND summary != '' LIMIT 3"
    ).fetchall()
    if sample:
        print(f"\n  Sample OpenAI summary (first 200 chars): {sample[0]['summary'][:200]}")

    # Try to backfill from 'published' field for rows that have content but no summary
    # This won't help much, but let's check for any entry with content field
    null_with_link = conn.execute(
        "SELECT count(*) FROM items WHERE (summary IS NULL OR summary = '') AND link IS NOT NULL AND link != ''"
    ).fetchone()[0]
    print(f"\n  Rows with NULL summary but have a link: {null_with_link}")
    print("  (Links are available — AI summary generation in P2 can fill these)")


def add_indexes(conn):
    """Add composite index and optimize."""
    print("\n=== P1-1: Adding database indexes ===")

    # Composite index for feed_name + published_ts (common query pattern)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_items_feed_published ON items(feed_name, published_ts DESC)"
    )
    print("  Created index: idx_items_feed_published (feed_name, published_ts DESC)")

    # Index on guid for faster upserts (already UNIQUE, but let's be explicit)
    # UNIQUE constraint already creates an index, skip

    # Index for year filtering via substr
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_items_year ON items(substr(published_ts, 1, 4))"
    )
    print("  Created index: idx_items_year (substr(published_ts, 1, 4))")

    conn.commit()

    # VACUUM to reclaim space
    print("  Running VACUUM...")
    conn.execute("VACUUM")
    print("  VACUUM complete")

    # Show index list
    print("\n  Current indexes:")
    for row in conn.execute("PRAGMA index_list(items)").fetchall():
        print(f"    {row['name']}")


if __name__ == "__main__":
    conn = get_db()
    try:
        fix_timestamps(conn)
        fix_feed_names(conn)
        backfill_summaries(conn)
        add_indexes(conn)
        print("\n=== Migration complete ===")
    finally:
        conn.close()
