"""
Daily AI digest: pick candidates (round-robin across feeds), call LLM, persist.
"""

from __future__ import annotations

import json
import os
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from html import unescape

from db import get_db, init_db, save_digest, get_digest, list_digests
from llm import generate_digest_from_candidates, is_configured, enrich_zh_summaries


def _strip_html(text: str | None) -> str:
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _today_key() -> str:
    # Prefer Asia/Shanghai-ish local date via TZ env, else system local
    tz_name = os.environ.get("REPORT_TZ") or os.environ.get("TZ")
    if tz_name:
        try:
            from zoneinfo import ZoneInfo
            return datetime.now(ZoneInfo(tz_name)).strftime("%Y-%m-%d")
        except Exception:
            pass
    return datetime.now().strftime("%Y-%m-%d")


def select_candidates(
    hours: int = 48,
    per_category_limit: int = 8,
    total_limit: int = 40,
) -> list[dict]:
    """
    Round-robin select recent items across feed_names so no single source
    monopolizes the digest quota.
    """
    init_db()
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    conn = get_db()
    try:
        rows = conn.execute(
            """
            SELECT id, feed_name, title, link, summary, zh_summary, published_ts, fetched_at
            FROM items
            WHERE COALESCE(published_ts, fetched_at) >= ?
            ORDER BY COALESCE(published_ts, fetched_at) DESC
            LIMIT 500
            """,
            (cutoff,),
        ).fetchall()
    finally:
        conn.close()

    by_feed: dict[str, list] = defaultdict(list)
    for r in rows:
        by_feed[r["feed_name"]].append(dict(r))

    # Round-robin
    buckets = [list(v) for v in by_feed.values()]
    selected: list[dict] = []
    made_progress = True
    while len(selected) < total_limit and made_progress:
        made_progress = False
        for b in buckets:
            if not b:
                continue
            selected.append(b.pop(0))
            made_progress = True
            if len(selected) >= total_limit:
                break

    out = []
    for it in selected:
        out.append({
            "id": it["id"],
            "title": it["title"],
            "url": it["link"],
            "link": it["link"],
            "source": it["feed_name"],
            "feed_name": it["feed_name"],
            "excerpt": it.get("zh_summary") or _strip_html(it.get("summary")),
            "summary": it.get("summary"),
            "published_ts": it.get("published_ts"),
        })
    return out


def generate_daily_digest(date: str | None = None, force: bool = False) -> dict:
    """Generate (or return cached) digest for date (YYYY-MM-DD)."""
    date = date or _today_key()
    if not force:
        cached = get_digest(date)
        if cached:
            return cached

    if not is_configured():
        raise RuntimeError("DEEPSEEK_API_KEY 未配置，无法生成简报")

    candidates = select_candidates()
    if len(candidates) < 3:
        # Fall back to whatever is newest in DB
        conn = get_db()
        try:
            rows = conn.execute(
                """SELECT id, feed_name, title, link, summary, zh_summary, published_ts
                   FROM items ORDER BY COALESCE(published_ts, fetched_at) DESC LIMIT 40"""
            ).fetchall()
        finally:
            conn.close()
        candidates = [{
            "id": r["id"],
            "title": r["title"],
            "url": r["link"],
            "link": r["link"],
            "source": r["feed_name"],
            "feed_name": r["feed_name"],
            "excerpt": r["zh_summary"] or _strip_html(r["summary"]),
            "summary": r["summary"],
            "published_ts": r["published_ts"],
        } for r in rows]

    if not candidates:
        raise RuntimeError("数据库中没有条目，请先抓取数据源")

    digest = generate_digest_from_candidates(candidates)
    digest["date"] = date
    digest["candidate_count"] = len(candidates)
    model = digest.pop("_model", None)
    save_digest(date, digest, model=model)
    return get_digest(date) or {"date": date, **digest}


def enrich_recent_items(limit: int = 30) -> int:
    """Generate zh_summary for recent items missing one. Returns count updated."""
    if not is_configured():
        return 0
    init_db()
    conn = get_db()
    try:
        rows = conn.execute(
            """
            SELECT id, title, link, summary FROM items
            WHERE (zh_summary IS NULL OR zh_summary = '')
              AND summary IS NOT NULL AND length(summary) > 40
            ORDER BY COALESCE(published_ts, fetched_at) DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        return 0

    items = [dict(r) for r in rows]
    mapping = enrich_zh_summaries(items)
    updated = 0
    conn = get_db()
    try:
        for it in items:
            zh = mapping.get(it["link"])
            if not zh:
                continue
            conn.execute(
                "UPDATE items SET zh_summary = ? WHERE id = ?",
                (zh, it["id"]),
            )
            updated += 1
        conn.commit()
    finally:
        conn.close()
    return updated


if __name__ == "__main__":
    import sys
    init_db()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "generate"
    if cmd == "enrich":
        n = enrich_recent_items()
        print(f"Enriched {n} items")
    elif cmd == "list":
        print(json.dumps(list_digests(), ensure_ascii=False, indent=2))
    else:
        force = "--force" in sys.argv
        d = generate_daily_digest(force=force)
        print(json.dumps({
            "date": d.get("date"),
            "hero_headline": d.get("hero_headline"),
            "briefs": len(d.get("briefs") or []),
            "idea_sparks": len(d.get("idea_sparks") or []),
        }, ensure_ascii=False, indent=2))
