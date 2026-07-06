"""
AITrending Web Panel — Flask app with pagination, FTS5 search, and feed monitoring.
"""

import json
import os
from flask import Flask, render_template, request, jsonify
from db import (
    init_db, query_items, count_items, get_feeds_with_counts, get_years,
    get_feed_health, rebuild_fts_index,
)
from fetcher import fetch_all, load_feeds as load_feeds_json
from apscheduler.schedulers.background import BackgroundScheduler

app = Flask(__name__)

# ── Scheduler: fetch every 30 minutes ──
scheduler = BackgroundScheduler()
scheduler.add_job(fetch_all, "interval", minutes=30, id="fetch_rss")
scheduler.start()


# ── Helpers ──

def _get_feeds_lookup():
    """Return {name: {category, url}, ...} from feeds.json."""
    feeds = load_feeds_json()
    return {f["name"]: f for f in feeds}


def _get_category_map():
    """Return {category: [feed_name, ...], ...} from feeds.json."""
    feeds = load_feeds_json()
    m = {}
    for f in feeds:
        m.setdefault(f.get("category", "未分类"), []).append(f["name"])
    return m


def _enrich_feeds(feeds):
    """Merge category info from feeds.json into feeds-with-counts list."""
    lookup = _get_feeds_lookup()
    for f in feeds:
        info = lookup.get(f["feed_name"], {})
        f["category"] = info.get("category", "")
    return feeds


# ── Routes ──

@app.route("/")
def index():
    cats = _get_category_map()
    categories = [{"name": k, "count": 0} for k in cats]
    feeds = _enrich_feeds(get_feeds_with_counts(year_filter="2026"))
    years = get_years()
    return render_template("index.html", feeds=feeds, years=years, categories=categories)


@app.route("/api/items")
def api_items():
    feed = request.args.get("feed") or None
    category = request.args.get("category") or None
    search = request.args.get("q") or None
    year = request.args.get("year") or None
    limit = min(int(request.args.get("limit", 50)), 200)
    offset = int(request.args.get("offset", 0))

    # If category is given, filter by all feeds in that category
    feed_filter = None
    if category:
        cat_map = _get_category_map()
        names = cat_map.get(category, [])
        if names:
            feed_filter = names
    if feed_filter is None and feed:
        feed_filter = feed

    items = query_items(
        feed_filter=feed_filter, search=search, year_filter=year,
        limit=limit, offset=offset,
    )
    total = count_items(feed_filter=feed_filter, search=search, year_filter=year)
    return jsonify({"items": items, "total": total, "limit": limit, "offset": offset})


@app.route("/api/feeds")
def api_feeds():
    year = request.args.get("year") or None
    feeds = get_feeds_with_counts(year_filter=year)
    return jsonify(_enrich_feeds(feeds))


@app.route("/api/categories")
def api_categories():
    """Return categories with item counts (optionally filtered by year)."""
    year = request.args.get("year") or None
    cat_map = _get_category_map()
    feeds_with_counts = get_feeds_with_counts(year_filter=year)
    feed_cnt = {f["feed_name"]: f["cnt"] for f in feeds_with_counts}
    result = []
    for cat, names in cat_map.items():
        total = sum(feed_cnt.get(n, 0) for n in names)
        result.append({"name": cat, "count": total})
    return jsonify(result)


@app.route("/api/refresh")
def api_refresh():
    """Manual refresh trigger."""
    new, errs = fetch_all()
    return jsonify({"new": new, "errors": errs})


@app.route("/api/health/feeds")
def api_feed_health():
    """Return feed health status based on recent fetch logs."""
    feeds_json = load_feeds_json()
    health = get_feed_health()
    health_map = {h["feed_name"]: h for h in health}

    result = []
    for f in feeds_json:
        h = health_map.get(f["name"], {
            "feed_name": f["name"],
            "last_status": "unknown",
            "last_fetched": None,
            "last_error": None,
            "consecutive_errors": 0,
        })
        h["url"] = f["url"]
        h["category"] = f.get("category", "")
        result.append(h)

    return jsonify(result)


# ── Diagnostics ──

@app.route("/health")
def health():
    from db import get_db
    conn = get_db()
    count = conn.execute("SELECT count(*) FROM items").fetchone()[0]
    conn.close()
    return f"OK — {count} items"


@app.route("/api/rebuild-fts")
def api_rebuild_fts():
    """Rebuild the FTS5 full-text search index."""
    try:
        count = rebuild_fts_index()
        return jsonify({"status": "ok", "indexed": count})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ── Favicon ──

@app.route("/favicon.ico")
def favicon():
    return (
        b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\xdac\x60\x00\x00\x00\x02\x00\x01\xe2!\xbc3\x00\x00\x00\x00IEND\xaeB`\x82',
        200,
        {"Content-Type": "image/png"},
    )


if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5003))
    print(f"AITrending starting at http://127.0.0.1:{port}")
    app.run(debug=True, port=port, use_reloader=False)
