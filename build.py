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
            SELECT id, feed_name, title, link, published, published_ts, summary
            FROM items
            ORDER BY COALESCE(published_ts, fetched_at, '1970-01-01') DESC
        """).fetchall()
        items = [dict(r) for r in rows]
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


def generate_html():
    """Generate a self-contained static index.html in docs/."""
    print("=== Generating static index.html ===")

    # Read the template
    template_path = os.path.join(os.path.dirname(__file__), "templates", "index.html")
    with open(template_path, "r", encoding="utf-8") as f:
        template = f.read()

    html = build_static_html(template)

    out_path = os.path.join(DIST_DIR, "index.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Generated {out_path}")


def build_static_html(template):
    """Transform the Flask template into a self-contained static page.

    Key changes:
    1. Replace Flask template variables with static defaults
    2. Replace all /api/* fetch calls with local JSON file reads
    3. Implement client-side search, filtering, pagination
    4. Remove the refresh button (data is baked at build time)
    5. Add a "last updated" indicator
    """
    # Remove Flask template blocks: {% for y in years %}...{% endfor %}
    # Replace year select options with a static set (will be populated by JS)
    template = re.sub(
        r'\{% for y in years %\}.*?\{% endfor %\}',
        '',
        template,
        flags=re.DOTALL,
    )

    # Remove Flask template blocks: {% for c in categories %}...{% endfor %}
    template = re.sub(
        r'\{% for c in categories %\}.*?\{% endfor %\}',
        '',
        template,
        flags=re.DOTALL,
    )

    # Remove Flask template blocks: {% for f in feeds %}...{% endfor %}
    template = re.sub(
        r'\{% for f in feeds %\}.*?\{% endfor %\}',
        '',
        template,
        flags=re.DOTALL,
    )

    # Replace the entire <script> section with our static version
    new_script = """  <script>
    // ── Static site: all data loaded from local JSON files ──
    // Detect base path for GitHub Pages subdirectory deployment
    const BASE_URL = window.location.pathname.replace(/\\/[^\\/]*$/, '/') ;
    let ALL_ITEMS = [];
    let META = {};
    let currentFeed = '';
    let currentCategory = '';
    let currentSearch = '';
    let currentYear = '2026';
    let debounceTimer;
    let filteredItems = [];
    let currentOffset = 0;
    const PAGE_SIZE = 50;

    // ── Fetch data on load ──
    async function initData() {
      try {
        const [itemsRes, metaRes] = await Promise.all([
          fetch(BASE_URL + 'data/items.json'),
          fetch(BASE_URL + 'data/meta.json')
        ]);
        ALL_ITEMS = await itemsRes.json();
        META = await metaRes.json();
      } catch(e) {
        console.error('Failed to load data:', e);
        document.getElementById('items').innerHTML =
          '<div style="color:var(--red);text-align:center;padding:40px;">数据加载失败，请稍后刷新</div>';
        return;
      }

      // Populate year select
      const yearSelect = document.getElementById('year-select');
      yearSelect.innerHTML = '<option value="">全部年份</option>' +
        META.years.map(y => `<option value="${y}">${y}</option>`).join('');
      yearSelect.value = currentYear;

      // Populate category pills
      const catPills = document.querySelector('.cat-pills');
      catPills.innerHTML = '<button class="cat-pill active" data-cat="" onclick="setCategory(\\'\\')">全部</button>' +
        META.categories.map(c =>
          `<button class="cat-pill" data-cat="${c.name}" onclick="setCategory(\\'${c.name}\\')">${c.name}</button>`
        ).join('');

      // Populate feed select
      const feedSelect = document.getElementById('feed-select');
      feedSelect.innerHTML = '<option value="">全部来源</option>' +
        META.feeds.map(f =>
          `<option value="${f.name}">${f.name} (${f.count})</option>`
        ).join('');

      // Update stats
      updateStats();

      // Render items
      render(true);
    }

    function stripHtml(html) {
      if (!html) return '';
      const tmp = document.createElement('div');
      tmp.innerHTML = html;
      return tmp.textContent || tmp.innerText || '';
    }

    function escapeHtml(text) {
      if (!text) return '';
      const div = document.createElement('div');
      div.textContent = text;
      return div.innerHTML;
    }

    // ── Client-side filtering ──
    function getFilteredItems() {
      return ALL_ITEMS.filter(item => {
        // Year filter
        if (currentYear) {
          const ts = item.published_ts || '';
          if (!ts.startsWith(currentYear)) return false;
        }
        // Feed filter
        if (currentFeed && item.feed_name !== currentFeed) return false;
        // Category filter
        if (currentCategory) {
          const feed = META.feeds.find(f => f.name === item.feed_name);
          if (!feed || feed.category !== currentCategory) return false;
        }
        // Search filter (case-insensitive, checks title + summary)
        if (currentSearch) {
          const q = currentSearch.toLowerCase();
          const title = (item.title || '').toLowerCase();
          const summary = stripHtml(item.summary || '').toLowerCase();
          if (!title.includes(q) && !summary.includes(q)) return false;
        }
        return true;
      });
    }

    function render(reset = true) {
      const itemsEl = document.getElementById('items');
      const emptyEl = document.getElementById('empty');
      const countEl = document.getElementById('result-count');
      const loadMoreWrap = document.getElementById('load-more-wrap');

      if (reset) {
        filteredItems = getFilteredItems();
        currentOffset = 0;
        itemsEl.innerHTML = '';
        loadMoreWrap.classList.add('hidden');
      }

      const total = filteredItems.length;
      const pageItems = filteredItems.slice(currentOffset, currentOffset + PAGE_SIZE);

      countEl.textContent = total ? `${total} 条结果` : '';

      if (!filteredItems.length) {
        emptyEl.classList.remove('hidden');
        itemsEl.innerHTML = '';
        return;
      }
      emptyEl.classList.add('hidden');

      const searchTerm = currentSearch.toLowerCase();
      const now = Date.now();

      const html = pageItems.map(item => {
        const title = item.title || '(no title)';
        const feed = item.feed_name || '';
        const summaryRaw = stripHtml(item.summary || '');
        const summary = summaryRaw ? summaryRaw.slice(0, 240) : '';
        const link = item.link || '#';
        const published = item.published || '';
        const publishedTs = item.published_ts || '';

        let freshBadge = '';
        if (publishedTs) {
          const pubTime = new Date(publishedTs).getTime();
          const diffH = (now - pubTime) / 3600000;
          if (diffH < 6) { freshBadge = '<span class="fresh-badge new">NEW</span>'; }
          else if (diffH < 24) { freshBadge = '<span class="fresh-badge today">今日</span>'; }
        }

        let timeStr = '';
        if (publishedTs) {
          const d = new Date(publishedTs);
          const now2 = new Date();
          const isThisYear = d.getFullYear() === now2.getFullYear();
          timeStr = isThisYear
            ? d.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })
            : d.toLocaleDateString('zh-CN', { year: 'numeric', month: 'short', day: 'numeric' });
        } else if (published) {
          try { timeStr = new Date(published).toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' }); } catch(e) {}
        }

        const hl = (text) => {
          const escaped = escapeHtml(text);
          if (!searchTerm) return escaped;
          const re = new RegExp(`(${searchTerm.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\\\$&')})`, 'gi');
          return escaped.replace(re, '<mark class="keyword-hl">$1</mark>');
        };

        return `
          <a href="${link}" target="_blank" rel="noopener" class="item-card">
            <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:12px;">
              <div style="flex:1;min-width:0;">
                <div class="item-title">${hl(title)}</div>
                ${summary ? `<div class="item-summary" style="margin-top:4px;">${hl(summary)}</div>` : ''}
              </div>
            </div>
            <div class="item-meta" style="margin-top:8px;">
              <span class="item-meta-source">${feed}</span>
              ${timeStr ? `<span class="item-meta-time">${timeStr}</span>` : ''}
              ${freshBadge}
            </div>
          </a>
        `;
      }).join('');

      if (reset) {
        itemsEl.innerHTML = html;
      } else {
        itemsEl.insertAdjacentHTML('beforeend', html);
      }

      // Show/hide "load more" button
      if (currentOffset + PAGE_SIZE < total) {
        loadMoreWrap.classList.remove('hidden');
      } else {
        loadMoreWrap.classList.add('hidden');
      }
    }

    function debounceRender() {
      clearTimeout(debounceTimer);
      currentSearch = document.getElementById('search').value.trim();
      debounceTimer = setTimeout(() => render(true), 300);
    }

    function setFeed(val) {
      currentFeed = val;
      currentCategory = '';
      document.querySelectorAll('.cat-pill').forEach(b => b.classList.toggle('active', b.dataset.cat === ''));
      render(true);
    }

    function setCategory(cat) {
      currentCategory = cat;
      currentFeed = '';
      document.getElementById('feed-select').value = '';
      document.querySelectorAll('.cat-pill').forEach(b => b.classList.toggle('active', b.dataset.cat === cat));
      render(true);
    }

    function setYear(year) {
      currentYear = year;
      document.getElementById('year-select').value = year;
      updateStats();
      render(true);
    }

    function loadMore() {
      currentOffset += PAGE_SIZE;
      render(false);
    }

    function updateStats() {
      const total = META.total_items || 0;
      const yearFiltered = currentYear
        ? ALL_ITEMS.filter(i => (i.published_ts || '').startsWith(currentYear)).length
        : total;
      document.getElementById('stat-total').textContent = yearFiltered.toLocaleString();
      document.getElementById('stat-feeds').textContent = META.feeds ? META.feeds.length : '—';

      // Update last updated time
      const updatedEl = document.getElementById('last-updated');
      if (updatedEl && META.generated_at) {
        const d = new Date(META.generated_at);
        updatedEl.textContent = d.toLocaleString('zh-CN', { dateStyle: 'short', timeStyle: 'short' });
      }
    }

    // ── Infinite scroll via IntersectionObserver ──
    const sentinel = document.createElement('div');
    sentinel.id = 'sentinel';
    sentinel.style.height = '1px';
    document.querySelector('.layout').appendChild(sentinel);

    let isLoadingMore = false;
    const observer = new IntersectionObserver((entries) => {
      if (entries[0].isIntersecting && currentOffset + PAGE_SIZE < filteredItems.length && !isLoadingMore) {
        isLoadingMore = true;
        loadMore();
        isLoadingMore = false;
      }
    }, { rootMargin: '200px' });
    observer.observe(sentinel);

    // ── Init ──
    initData();
  </script>"""

    # Replace everything between <script> and </script>
    template = re.sub(
        r'<script>.*?</script>',
        new_script,
        template,
        flags=re.DOTALL,
    )

    # Replace the refresh button with a "last updated" indicator
    template = template.replace(
        """        <button class="btn" id="btn-refresh" onclick="refresh()">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 2v6h-6"/><path d="M3 12a9 9 0 0 1 15-6.7L21 8"/><path d="M3 22v-6h6"/><path d="M21 12a9 9 0 0 1-15 6.7L3 16"/></svg>
          刷新
        </button>""",
        """        <div class="stat-chip" title="数据更新时间">
          更新于 <span id="last-updated">—</span>
        </div>"""
    )

    # Copy favicon to docs/
    favicon_src = os.path.join(os.path.dirname(__file__), "static", "favicon.svg")
    if os.path.exists(favicon_src):
        import shutil
        shutil.copy(favicon_src, os.path.join(DIST_DIR, "favicon.svg"))

    # Update favicon link to point to local file
    template = template.replace(
        'href="data:image/svg+xml,%3Csvg',
        'href="favicon.svg"><!--'
    )
    # Clean up the old inline favicon data
    template = re.sub(
        r'favicon\.svg"><!--[^"]*" type="image/svg\+svg">',
        'favicon.svg" type="image/svg+xml">',
        template,
    )

    return template


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
    generate_html()

    print("\n=== Build complete ===")
    print(f"Output: {DIST_DIR}/")
    print(f"  index.html")
    print(f"  data/items.json ({len(items)} items)")
    print(f"  data/meta.json")
    print(f"  favicon.svg")


if __name__ == "__main__":
    main()
