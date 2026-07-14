"""
Non-RSS source fetchers: GitHub Trending, HuggingFace Papers, X AI viral posts.
Each returns a list of dicts compatible with fetcher.upsert_item().
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any

import httpx

UA = "Mozilla/5.0 (compatible; AITrending/1.0; +https://github.com/raise-lien/AITrending)"


def _client() -> httpx.Client:
    return httpx.Client(
        timeout=20,
        follow_redirects=True,
        headers={"User-Agent": UA, "Accept": "*/*"},
    )


# ── GitHub Trending (HTML scrape) ──────────────────────────────────────────


class _GitHubTrendingParser(HTMLParser):
    """Minimal parser for github.com/trending article.Box-row blocks."""

    def __init__(self, limit: int = 25):
        super().__init__()
        self.limit = limit
        self.items: list[dict[str, Any]] = []
        self._in_article = False
        self._depth = 0
        self._capture_href = False
        self._capture_desc = False
        self._capture_lang = False
        self._capture_stars_today = False
        self._buf = ""
        self._cur: dict[str, Any] | None = None
        self._a_href = ""
        self._in_h2 = False
        self._in_p = False
        self._pending_stars_today = False

    def handle_starttag(self, tag, attrs):
        attrs_d = dict(attrs)
        cls = attrs_d.get("class", "")

        if tag == "article" and "Box-row" in cls:
            if len(self.items) >= self.limit:
                return
            self._in_article = True
            self._depth = 1
            self._cur = {"title": "", "link": "", "summary": "", "meta": []}
            return

        if not self._in_article or not self._cur:
            return

        if tag == "article":
            self._depth += 1

        if tag == "h2":
            self._in_h2 = True
        if self._in_h2 and tag == "a":
            href = (attrs_d.get("href") or "").strip()
            if href.startswith("/") and href.count("/") >= 2:
                self._a_href = href
                self._capture_href = True
                self._buf = ""

        if tag == "p" and "col-9" in cls or (tag == "p" and self._in_article and not self._cur.get("summary")):
            # Prefer the description paragraph
            if "color-fg-muted" in cls or "col-9" in cls or True:
                self._in_p = True
                self._buf = ""
                self._capture_desc = True

        if attrs_d.get("itemprop") == "programmingLanguage":
            self._capture_lang = True
            self._buf = ""

        if tag == "span" and "float-sm-right" in cls:
            self._pending_stars_today = True
            self._buf = ""

    def handle_endtag(self, tag):
        if not self._in_article:
            return

        if self._capture_href and tag == "a":
            repo = self._a_href.strip().lstrip("/")
            if repo and not self._cur["title"]:
                self._cur["title"] = re.sub(r"\s+", "", self._buf) or repo
                self._cur["link"] = f"https://github.com/{repo}"
                self._cur["guid"] = self._cur["link"]
            self._capture_href = False

        if self._in_h2 and tag == "h2":
            self._in_h2 = False

        if self._capture_desc and tag == "p":
            desc = re.sub(r"\s+", " ", self._buf).strip()
            if desc and not self._cur.get("summary"):
                self._cur["summary"] = desc[:500]
            self._capture_desc = False
            self._in_p = False

        if self._capture_lang and tag in ("span", "a"):
            lang = self._buf.strip()
            if lang:
                self._cur["meta"].append(lang)
            self._capture_lang = False

        if self._pending_stars_today and tag == "span":
            text = re.sub(r"\s+", " ", self._buf).strip()
            if "star" in text.lower():
                self._cur["meta"].append(text)
            self._pending_stars_today = False

        if tag == "article":
            self._depth -= 1
            if self._depth <= 0 and self._cur:
                if self._cur.get("link"):
                    meta = " · ".join(self._cur["meta"])
                    summary = self._cur.get("summary") or ""
                    if meta:
                        summary = f"{meta}\n{summary}".strip() if summary else meta
                    self.items.append({
                        "title": self._cur["title"],
                        "link": self._cur["link"],
                        "guid": self._cur["guid"],
                        "summary": summary[:2000],
                        "published": None,
                        "published_ts": None,  # keep trending order
                    })
                self._cur = None
                self._in_article = False

    def handle_data(self, data):
        if self._capture_href or self._capture_desc or self._capture_lang or self._pending_stars_today:
            self._buf += data


def fetch_github_trending(limit: int = 25) -> list[dict]:
    """Scrape https://github.com/trending?since=daily."""
    with _client() as client:
        resp = client.get(
            "https://github.com/trending?since=daily",
            headers={"Accept": "text/html,application/xhtml+xml"},
        )
        resp.raise_for_status()
        html = resp.text

    # Fast path: regex extract Box-row articles (more reliable than fragile HTMLParser nesting)
    items: list[dict] = []
    articles = re.findall(
        r'<article class="Box-row".*?</article>',
        html,
        flags=re.DOTALL,
    )
    for block in articles[:limit]:
        href_m = re.search(r'<h2[^>]*>\s*<a[^>]*href="(/[^"]+)"', block)
        if not href_m:
            continue
        repo = href_m.group(1).strip().strip("/")
        # Clean whitespace inside repo path text
        repo = re.sub(r"\s+", "", repo)
        if not repo or "/" not in repo:
            continue

        desc_m = re.search(
            r'<p class="[^"]*col-9[^"]*"[^>]*>(.*?)</p>',
            block,
            flags=re.DOTALL,
        )
        desc = ""
        if desc_m:
            desc = re.sub(r"<[^>]+>", "", desc_m.group(1))
            desc = re.sub(r"\s+", " ", desc).strip()

        lang_m = re.search(
            r'itemprop="programmingLanguage"[^>]*>([^<]+)',
            block,
        )
        lang = lang_m.group(1).strip() if lang_m else ""

        stars_today_m = re.search(
            r'(\d[\d,]*)\s+stars?\s+today',
            block,
            flags=re.IGNORECASE,
        )
        stars_today = stars_today_m.group(0).strip() if stars_today_m else ""

        meta_parts = [p for p in (lang, stars_today) if p]
        summary = desc
        if meta_parts:
            summary = (" · ".join(meta_parts) + ("\n" + desc if desc else "")).strip()

        link = f"https://github.com/{repo}"
        items.append({
            "title": repo,
            "link": link,
            "guid": link,
            "summary": summary[:2000],
            "published": None,
            "published_ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        })

    if not items:
        # Fallback to HTMLParser if regex failed (markup changed)
        parser = _GitHubTrendingParser(limit=limit)
        parser.feed(html)
        items = parser.items

    return items


# ── HuggingFace Daily Papers ───────────────────────────────────────────────


def fetch_huggingface_papers(limit: int = 30, keywords: list[str] | None = None) -> list[dict]:
    """Fetch https://huggingface.co/api/daily_papers ranked by upvotes."""
    with _client() as client:
        resp = client.get(
            "https://huggingface.co/api/daily_papers",
            headers={"Accept": "application/json"},
        )
        resp.raise_for_status()
        papers = resp.json()

    kw = [k.lower() for k in (keywords or [])]
    filtered = []
    for p in papers:
        paper = p.get("paper") or {}
        title = paper.get("title") or ""
        summary = paper.get("summary") or ""
        if kw:
            hay = " ".join([title, summary, " ".join(paper.get("ai_keywords") or [])]).lower()
            if not any(k in hay for k in kw):
                continue
        filtered.append(p)

    filtered.sort(key=lambda p: (p.get("paper") or {}).get("upvotes") or 0, reverse=True)

    items = []
    for p in filtered[:limit]:
        paper = p["paper"]
        pid = paper.get("id") or ""
        if not pid:
            continue
        upvotes = paper.get("upvotes") or 0
        summary = (paper.get("summary") or "")[:1800]
        if upvotes:
            summary = f"👍 {upvotes}\n{summary}".strip()
        published = paper.get("publishedAt")
        published_ts = None
        if published:
            try:
                published_ts = datetime.fromisoformat(
                    published.replace("Z", "+00:00")
                ).strftime("%Y-%m-%dT%H:%M:%SZ")
            except Exception:
                published_ts = None
        link = f"https://huggingface.co/papers/{pid}"
        items.append({
            "title": paper.get("title") or pid,
            "link": link,
            "guid": link,
            "summary": summary,
            "published": published,
            "published_ts": published_ts,
        })
    return items


# ── AttentionVC X AI viral posts ───────────────────────────────────────────

AVC_BASE = (
    "https://reply-vc-90459984647.us-central1.run.app/v1/articles/leaderboard"
)


def _compact(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def fetch_x_ai_viral(limit: int = 20) -> list[dict]:
    """Fetch AI-category viral X posts from AttentionVC public API."""
    url = f"{AVC_BASE}?window=3d&category=ai&lang=en&limit=30"
    with _client() as client:
        resp = client.get(url, headers={"Accept": "application/json"})
        resp.raise_for_status()
        data = resp.json()

    entries = data.get("entries") or []
    items = []
    for e in entries:
        # Prefer English / non-linguistic (image/code) posts
        langs = e.get("langsDetected") or []
        lang = e.get("lang") or ""
        if langs:
            if "en" not in langs and "zxx" not in langs:
                continue
        elif lang not in ("en", "zxx", ""):
            continue

        author = e.get("author") or {}
        handle = author.get("handle") or "unknown"
        tweet_id = e.get("tweetId") or ""
        if not tweet_id:
            continue

        meta_parts = [f"@{handle}"]
        if isinstance(author.get("followers"), int):
            meta_parts.append(f"{_compact(author['followers'])} 粉丝")
        if isinstance(e.get("viewCount"), int):
            meta_parts.append(f"{_compact(e['viewCount'])} 阅")
        if isinstance(e.get("likeCount"), int):
            meta_parts.append(f"{_compact(e['likeCount'])} 赞")

        preview = (e.get("previewText") or "").replace("\n", " ").strip()[:500]
        summary = " · ".join(meta_parts)
        if preview:
            summary = f"{summary}\n{preview}"

        published = e.get("tweetCreatedAt")
        published_ts = None
        if published:
            try:
                published_ts = datetime.fromisoformat(
                    published.replace("Z", "+00:00")
                ).strftime("%Y-%m-%dT%H:%M:%SZ")
            except Exception:
                published_ts = None

        link = f"https://x.com/{handle}/status/{tweet_id}"
        items.append({
            "title": e.get("title") or preview[:80] or f"@{handle}",
            "link": link,
            "guid": link,
            "summary": summary[:2000],
            "published": published,
            "published_ts": published_ts,
        })
        if len(items) >= limit:
            break

    return items


def fetch_special(feed: dict) -> list[dict]:
    """Dispatch by feed id / type."""
    fid = feed.get("id") or ""
    if fid == "github-trending" or feed.get("type") == "scrape" and "github.com/trending" in feed.get("url", ""):
        return fetch_github_trending()
    if fid == "huggingface-papers":
        return fetch_huggingface_papers(keywords=feed.get("keywords") or [])
    if fid == "x-ai-viral" or fid == "attentionvc-ai":
        return fetch_x_ai_viral()
    raise ValueError(f"Unknown special source: {fid or feed.get('name')}")
