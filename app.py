"""
AITrending Web Panel — Flask app with one page.
ponytail: single file, no blueprints, no auth, just works.
"""

import os
from flask import Flask, render_template, request, jsonify
from db import init_db, query_items, get_feeds_with_counts, get_years
from fetcher import fetch_all
from apscheduler.schedulers.background import BackgroundScheduler

app = Flask(__name__)

# ── Scheduler: fetch every 30 minutes ──
scheduler = BackgroundScheduler()
scheduler.add_job(fetch_all, "interval", minutes=30, id="fetch_rss")
scheduler.start()

# ── Routes ──

@app.route("/")
def index():
    # Default to 2026 for initial load, matching JS default
    feeds = get_feeds_with_counts(year_filter='2026')
    years = get_years()
    return render_template("index.html", feeds=feeds, years=years)


@app.route("/api/items")
def api_items():
    feed = request.args.get("feed") or None
    search = request.args.get("q") or None
    year = request.args.get("year") or None
    limit = int(request.args.get("limit", 3000))
    items = query_items(feed_filter=feed, search=search, year_filter=year, limit=limit)
    return jsonify(items)


@app.route("/api/feeds")
def api_feeds():
    year = request.args.get("year") or None
    return jsonify(get_feeds_with_counts(year_filter=year))


@app.route("/api/refresh")
def api_refresh():
    """Manual refresh trigger."""
    new, errs = fetch_all()
    return jsonify({"new": new, "errors": errs})


# ── Diagnostics (ponytail: useful for debugging, no auth needed for local) ──

@app.route("/health")
def health():
    from db import get_db
    conn = get_db()
    count = conn.execute("SELECT count(*) FROM items").fetchone()[0]
    conn.close()
    return f"OK — {count} items"


if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5003))
    print(f"AITrending starting at http://127.0.0.1:{port}")
    app.run(debug=True, port=port, use_reloader=False)
