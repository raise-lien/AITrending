"""
AITrending Web Panel — Flask app with pagination, FTS5 search,
feed monitoring, and DeepSeek-powered daily digest.
"""

import os
from datetime import datetime

from flask import Flask, render_template, request, jsonify
from apscheduler.schedulers.background import BackgroundScheduler

from db import (
    init_db, query_items, count_items, get_feeds_with_counts, get_years,
    get_feed_health, rebuild_fts_index, get_digest, list_digests,
)
from fetcher import fetch_all, load_feeds as load_feeds_json
from llm import is_configured, get_model

app = Flask(__name__)

# ── Scheduler ──
scheduler = BackgroundScheduler()
scheduler.add_job(fetch_all, "interval", minutes=30, id="fetch_rss")


def _maybe_generate_digest():
    """Run once around DIGEST_HOUR if LLM is configured."""
    if not is_configured():
        return
    hour = int(os.environ.get("DIGEST_HOUR", "8"))
    if datetime.now().hour != hour:
        return
    try:
        from digest import generate_daily_digest
        generate_daily_digest(force=False)
        print("[digest] daily digest ready")
    except Exception as e:
        print(f"[digest] skipped/failed: {e}")


scheduler.add_job(_maybe_generate_digest, "interval", minutes=30, id="digest_tick")
scheduler.start()


# ── Helpers ──

def _get_feeds_lookup():
    feeds = load_feeds_json(include_disabled=True)
    return {f["name"]: f for f in feeds}


def _get_category_map():
    feeds = load_feeds_json()
    m = {}
    for f in feeds:
        m.setdefault(f.get("category", "未分类"), []).append(f["name"])
    return m


def _enrich_feeds(feeds):
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
    return render_template(
        "index.html",
        feeds=feeds,
        years=years,
        categories=categories,
        llm_ready=is_configured(),
    )


@app.route("/api/items")
def api_items():
    feed = request.args.get("feed") or None
    category = request.args.get("category") or None
    search = request.args.get("q") or None
    year = request.args.get("year") or None
    limit = min(int(request.args.get("limit", 50)), 200)
    offset = int(request.args.get("offset", 0))

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
    # Prefer zh_summary in API response for display
    for it in items:
        if it.get("zh_summary"):
            it["display_summary"] = it["zh_summary"]
        else:
            it["display_summary"] = it.get("summary")
    total = count_items(feed_filter=feed_filter, search=search, year_filter=year)
    return jsonify({"items": items, "total": total, "limit": limit, "offset": offset})


@app.route("/api/feeds")
def api_feeds():
    year = request.args.get("year") or None
    feeds = get_feeds_with_counts(year_filter=year)
    return jsonify(_enrich_feeds(feeds))


@app.route("/api/categories")
def api_categories():
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
    new, errs = fetch_all()
    return jsonify({"new": new, "errors": errs})


@app.route("/api/health/feeds")
def api_feed_health():
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
        h["type"] = f.get("type", "rss")
        h["enabled"] = f.get("enabled", True) is not False
        result.append(h)

    return jsonify(result)


# ── Digest ──

@app.route("/api/digest")
def api_digest():
    """Get digest for a date (default today)."""
    date = request.args.get("date") or datetime.now().strftime("%Y-%m-%d")
    data = get_digest(date)
    if not data:
        return jsonify({"date": date, "exists": False, "llm_ready": is_configured()}), 404
    data["exists"] = True
    data["llm_ready"] = is_configured()
    return jsonify(data)


@app.route("/api/digest/list")
def api_digest_list():
    return jsonify(list_digests(limit=int(request.args.get("limit", 30))))


@app.route("/api/digest/generate", methods=["GET", "POST"])
def api_digest_generate():
    """Generate (or regenerate) today's digest via DeepSeek."""
    if not is_configured():
        return jsonify({
            "status": "error",
            "message": "DEEPSEEK_API_KEY 未配置。请在 .env 中设置后重启服务。",
        }), 400

    force = request.args.get("force", "0") in ("1", "true", "yes")
    if request.method == "POST":
        body = request.get_json(silent=True) or {}
        force = bool(body.get("force", force))
        date = body.get("date")
    else:
        date = request.args.get("date")

    try:
        from digest import generate_daily_digest
        data = generate_daily_digest(date=date, force=force)
        return jsonify({"status": "ok", "digest": data, "model": get_model()})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/enrich", methods=["GET", "POST"])
def api_enrich():
    """Backfill zh_summary for recent items missing Chinese summaries."""
    if not is_configured():
        return jsonify({"status": "error", "message": "DEEPSEEK_API_KEY 未配置"}), 400
    limit = int(request.args.get("limit", 30))
    try:
        from digest import enrich_recent_items
        n = enrich_recent_items(limit=limit)
        return jsonify({"status": "ok", "updated": n})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/llm/status")
def api_llm_status():
    return jsonify({
        "configured": is_configured(),
        "model": get_model() if is_configured() else None,
    })


# ── Diagnostics ──

@app.route("/health")
def health():
    from db import get_db
    conn = get_db()
    count = conn.execute("SELECT count(*) FROM items").fetchone()[0]
    conn.close()
    return f"OK — {count} items · llm={'yes' if is_configured() else 'no'}"


@app.route("/api/rebuild-fts")
def api_rebuild_fts():
    try:
        count = rebuild_fts_index()
        return jsonify({"status": "ok", "indexed": count})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


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
    print(f"LLM: {'ready (' + get_model() + ')' if is_configured() else 'not configured'}")
    app.run(debug=True, port=port, use_reloader=False)
