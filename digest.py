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


def _feed_weights() -> dict[str, float]:
    """Map feed_name -> weight (from feeds.json `weight`, default 1)."""
    try:
        from fetcher import load_feeds
        feeds = load_feeds(include_disabled=True)
    except Exception:
        return {}
    w: dict[str, float] = {}
    for f in feeds:
        try:
            val = float(f.get("weight", 1) or 1)
        except (TypeError, ValueError):
            val = 1.0
        if val <= 0:
            val = 1.0
        w[f["name"]] = val
    return w


def _title_trigrams(text: str) -> set[str]:
    t = re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", (text or "").lower())
    if len(t) < 6:
        return set()
    return {t[i : i + 3] for i in range(len(t) - 2)}


def _dedup_items(items: list[dict], weights: dict[str, float]) -> list[dict]:
    """Cluster near-duplicate headlines (same event across sources) and keep the
    highest-weight source's item as the representative, freeing quota for
    heterogeneous signals."""
    sigs = [_title_trigrams(it.get("title") or "") for it in items]
    used = [False] * len(items)
    keep: list[dict] = []
    order = sorted(
        range(len(items)),
        key=lambda i: -weights.get(items[i].get("feed_name", ""), 1.0),
    )
    for i in order:
        if used[i]:
            continue
        used[i] = True
        cluster = [i]
        for j in range(len(items)):
            if used[j] or not sigs[i] or not sigs[j]:
                continue
            union = sigs[i] | sigs[j]
            if union and len(sigs[i] & sigs[j]) / len(union) >= 0.55:
                used[j] = True
                cluster.append(j)
        keep.append(items[cluster[0]])
    return keep


def _weighted_round_robin(
    by_feed: dict[str, list], weights: dict[str, float], total_limit: int
) -> list[dict]:
    """Allocate the quota across feeds proportionally to their weight, then
    interleave so each feed's items land near their ideal evenly-spaced
    positions (no long runs, good mixing).

    Two steps:
      1. target count per feed = weight / sum(weights) * total_limit
         (largest-remainder rounding), capped by how many items the feed has.
      2. place each feed's items at their ideal slot via a greedy
         "least-behind-ideal-position" scan — deterministic and well spread."""
    feeds = [n for n, b in by_feed.items() if b]
    if not feeds:
        return []
    w = {n: max(float(weights.get(n, 1.0)), 1e-4) for n in feeds}
    total_w = sum(w.values())

    # 1) proportional target counts (largest remainder)
    raw = {n: w[n] / total_w * total_limit for n in feeds}
    counts = {n: min(int(raw[n]), len(by_feed[n])) for n in feeds}
    # give any leftover quota to feeds that still have items, by fractional part
    rem = total_limit - sum(counts.values())
    order_extra = sorted(feeds, key=lambda n: (raw[n] - counts[n], w[n]), reverse=True)
    idx = 0
    while rem > 0:
        n = order_extra[idx % len(order_extra)]
        if counts[n] < len(by_feed[n]):
            counts[n] += 1
            rem -= 1
        idx += 1
        if all(counts[n] >= len(by_feed[n]) for n in feeds):
            break

    # 2) interleave by ideal position
    placed = {n: 0 for n in feeds}
    total = sum(counts.values())
    selected: list[dict] = []
    for k in range(total):
        best, best_ideal = None, None
        for n in feeds:
            if placed[n] >= counts[n]:
                continue
            j = placed[n]  # index of the next item to place
            ideal = (j + 0.5) * total / counts[n] if counts[n] else 0
            if best is None or ideal < best_ideal:
                best, best_ideal = n, ideal
        if best is None:
            break
        selected.append(by_feed[best].pop(0))
        placed[best] += 1
    return selected


def select_candidates(
    hours: int = 48,
    per_category_limit: int = 8,
    total_limit: int = 40,
) -> list[dict]:
    """
    Select recent items: drop cross-source duplicates, then weighted
    round-robin across feed_names so authoritative sources get more slots
    without monopolizing the digest quota.
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

    items = [dict(r) for r in rows]
    weights = _feed_weights()

    # 1) Collapse the same event reported by multiple sources
    deduped = _dedup_items(items, weights)

    # 2) Group by feed, then weighted round-robin
    by_feed: dict[str, list] = defaultdict(list)
    for it in deduped:
        by_feed[it["feed_name"]].append(it)
    selected = _weighted_round_robin(by_feed, weights, total_limit)

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
