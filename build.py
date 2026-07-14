"""
Static site builder for GitHub Pages deployment.
- Fetches all RSS feeds
- Exports data as static JSON files
- Generates a self-contained index.html (no Flask, no backend)
- Designed to run in GitHub Actions cron

Usage:
    python build.py          # fetch + export + generate HTML
    python build.py --no-fetch  # skip fetching, use existing DB data
"""

import json
import os
import re
import html as html_module
from datetime import datetime, timezone
from collections import defaultdict

# Reuse existing fetcher and db modules
from fetcher import fetch_all, load_feeds
from db import init_db, get_db

# Output directory for static site
DIST_DIR = os.path.join(os.path.dirname(__file__), "docs")
DATA_DIR = os.path.join(DIST_DIR, "data")


def ensure_dirs():
    """Create output directories."""
    os.makedirs(DATA_DIR, exist_ok=True)


def fetch_data():
    """Fetch all RSS feeds into the database."""
    print("=== Fetching RSS feeds ===")
    init_db()
    new, errs = fetch_all()
    print(f"Done: {new} new items, {errs} errors")
    return new, errs


def export_items_json():
    """Export all items as a JSON file for the frontend to consume."""
    print("=== Exporting items JSON ===")
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT id, feed_name, title, link, published, published_ts, summary, zh_summary
            FROM items
            ORDER BY COALESCE(published_ts, fetched_at, '1970-01-01') DESC
        """).fetchall()
        items = [dict(r) for r in rows]
        for it in items:
            if it.get("zh_summary"):
                it["display_summary"] = it["zh_summary"]
        print(f"Exported {len(items)} items")

        # Write full data
        out_path = os.path.join(DATA_DIR, "items.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, separators=(",", ":"))
        return items
    finally:
        conn.close()


def export_meta_json(items):
    """Export metadata: feeds, categories, years, stats."""
    print("=== Exporting metadata JSON ===")
    feeds_json = load_feeds()

    # Build category map
    cat_map = {}
    feed_lookup = {}
    for f in feeds_json:
        cat = f.get("category", "未分类")
        cat_map.setdefault(cat, []).append(f["name"])
        feed_lookup[f["name"]] = f

    # Count items per feed
    feed_counts = defaultdict(int)
    year_set = set()
    for item in items:
        feed_counts[item["feed_name"]] += 1
        ts = item.get("published_ts") or ""
        if ts and len(ts) >= 4:
            year_set.add(ts[:4])

    # Feeds with counts
    feeds = []
    for f in feeds_json:
        feeds.append({
            "name": f["name"],
            "url": f["url"],
            "category": f.get("category", ""),
            "count": feed_counts.get(f["name"], 0),
        })

    # Categories with counts
    categories = []
    for cat, names in cat_map.items():
        total = sum(feed_counts.get(n, 0) for n in names)
        categories.append({"name": cat, "count": total})

    # Years (sorted desc)
    years = sorted(year_set, reverse=True)

    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_items": len(items),
        "feeds": feeds,
        "categories": categories,
        "years": years,
    }

    out_path = os.path.join(DATA_DIR, "meta.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, separators=(",", ":"))
    print(f"Meta: {len(feeds)} feeds, {len(categories)} categories, {len(years)} years")


def generate_and_export_digest():
    """Generate today's digest via DeepSeek (if configured) and export JSON."""
    print("=== Generating daily digest ===")
    from llm import is_configured
    out_path = os.path.join(DATA_DIR, "digest.json")

    if not is_configured():
        print("DEEPSEEK_API_KEY not set — writing empty digest.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump({"exists": False}, f)
        return None

    try:
        from digest import generate_daily_digest
        data = generate_daily_digest(force=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
        print(f"Digest: {data.get('hero_headline', '')[:60]}")
        print(f"Idea sparks: {len(data.get('idea_sparks') or [])}")
        return data
    except Exception as e:
        print(f"[WARN] digest generation failed: {e}")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump({"exists": False, "error": str(e)}, f)
        return None


def generate_html():
    """Generate a self-contained static index.html in docs/.

    Uses templates/static.html directly — no regex substitution needed,
    which avoids backslash mangling in JS regex literals.
    """
    print("=== Generating static index.html ===")

    template_path = os.path.join(os.path.dirname(__file__), "templates", "static.html")
    with open(template_path, "r", encoding="utf-8") as f:
        html = f.read()

    # Copy favicon + shared stylesheet to docs/
    import shutil
    favicon_src = os.path.join(os.path.dirname(__file__), "static", "favicon.svg")
    if os.path.exists(favicon_src):
        shutil.copy(favicon_src, os.path.join(DIST_DIR, "favicon.svg"))

    css_src = os.path.join(os.path.dirname(__file__), "static", "styles", "app.css")
    if os.path.exists(css_src):
        os.makedirs(os.path.join(DIST_DIR, "styles"), exist_ok=True)
        shutil.copy(css_src, os.path.join(DIST_DIR, "styles", "app.css"))

    out_path = os.path.join(DIST_DIR, "index.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Generated {out_path}")


def main():
    import sys
    no_fetch = "--no-fetch" in sys.argv

    ensure_dirs()

    if not no_fetch:
        fetch_data()
    else:
        print("Skipping fetch (--no-fetch)")
        init_db()

    items = export_items_json()
    export_meta_json(items)
    generate_and_export_digest()
    generate_html()

    print("\n=== Build complete ===")
    print(f"Output: {DIST_DIR}/")
    print(f"  index.html")
    print(f"  styles/app.css")
    print(f"  data/items.json ({len(items)} items)")
    print(f"  data/meta.json")
    print(f"  data/digest.json")
    print(f"  favicon.svg")


if __name__ == "__main__":
    main()
