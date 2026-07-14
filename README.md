# AITrending

AI 信息聚合面板 — 从多源采集、展示 AI 领域最新动态，并用 DeepSeek 生成「今日简报」。

## 快速启动

```bash
pip install -r requirements.txt
cp .env.example .env   # 填入 DEEPSEEK_API_KEY（摘要/简报需要）
python fetcher.py all  # 拉取所有源
python app.py          # http://127.0.0.1:5003
```

## 功能

- **40+ 数据源**，按类别分组（公司博客 / 学术论文 / 行业媒体 / 个人博客 / Newsletter / AI 安全 / 中文媒体 / 开源热榜）
- **非 RSS 源**：GitHub Trending、HuggingFace 热门论文、X AI 热帖（AttentionVC）
- **今日简报**：DeepSeek 中文摘要 + 要点排序（顶部切换「信息流 / 今日简报」）
- **分类 / 来源 / 年份筛选**、FTS5 全文搜索、新鲜度标签
- **自动刷新**：每 30 分钟抓取；可配置整点自动生成简报（`DIGEST_HOUR`）
- **工程能力**：`enabled` / `type` / `use_curl` 源配置、单源失败不拖垮、`python fetcher.py dry-run`

## 项目结构

| 文件 | 说明 |
|---|---|
| `app.py` | Flask Web + 定时调度 |
| `db.py` | SQLite（items / fetch_log / digests / FTS5） |
| `fetcher.py` | RSS / API / scrape 抓取 |
| `special_sources.py` | GitHub Trending / HF Papers / X AI |
| `llm.py` | DeepSeek 客户端 |
| `digest.py` | 每日简报生成 |
| `feeds.json` | 数据源配置 |
| `.env` | API key（勿提交） |

## API

| 路由 | 说明 |
|---|---|
| `GET /api/items` | 条目列表（`feed` / `category` / `q` / `year` / `limit` / `offset`） |
| `GET /api/feeds` | 数据源及计数 |
| `GET /api/categories` | 分类及计数 |
| `GET /api/refresh` | 手动抓取 |
| `GET /api/digest` | 今日简报 |
| `GET /api/digest/generate?force=1` | 生成/刷新简报 |
| `GET /api/enrich` | 为近期条目补中文摘要 |
| `GET /api/llm/status` | LLM 配置状态 |
| `GET /api/health/feeds` | 各源抓取健康度 |

## 常用命令

```bash
python fetcher.py all        # 抓取全部启用源
python fetcher.py dry-run    # 只验证连通性，不写库
python fetcher.py list       # 列出源及启用状态
python digest.py             # 生成今日简报
python digest.py enrich      # 补中文摘要
```

## 环境变量

见 `.env.example`：

- `DEEPSEEK_API_KEY` — 必填（简报/摘要）
- `LLM_MODEL` — 默认 `deepseek-chat`
- `LLM_BASE_URL` — 默认 `https://api.deepseek.com/v1`
- `DIGEST_HOUR` — 自动生成简报的小时（默认 8）

## 技术栈

Flask + SQLite + feedparser + httpx + APScheduler + DeepSeek API
