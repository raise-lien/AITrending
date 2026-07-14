# AITrending

**AI 垂直信息雷达** — 把公司博客、论文、Newsletter、开源热榜和 X 上的 AI 讨论收进一个面板，再用 DeepSeek 压成一份可读的「今日简报」。

[![Pages](https://img.shields.io/badge/demo-GitHub%20Pages-2088ff?logo=github)](https://raise-lien.github.io/AITrending/)
[![Python](https://img.shields.io/badge/python-3.12+-3776AB?logo=python&logoColor=white)](requirements.txt)
[![License](https://img.shields.io/badge/license-see%20repo-lightgrey)](#)

**Live：** [raise-lien.github.io/AITrending](https://raise-lien.github.io/AITrending/)

---

## 这是什么 / 解决什么问题

AI 领域每天都在更新：模型发布、论文、开源项目、从业者讨论散落在几十个站点。你很难同时盯住 ArXiv、公司博客、HF、GitHub 和 X，更难用中文快速抓住「今天真正重要的事」。

AITrending 做两件事：

| 模式 | 适合 | 做什么 |
|------|------|--------|
| **信息流** | 深挖、检索、回溯 | 多源入库，按分类 / 来源 / 年份筛选，全文搜索 |
| **今日简报** | 通勤 / 晨间 5 分钟 | DeepSeek 从候选里 round-robin 选稿，输出中文头条 + 要点 + **Idea Sparks** |

它**不是**通用新闻站，也**不是**财经行情面板——只服务「跟 AI 相关的人」：研究者、工程师、产品、投资看行业的人。

---

## 功能一览

- **41 个数据源 · 9 类**：公司博客、学术论文、学术研究、行业媒体、个人博客、Newsletter、AI 安全、中文媒体、开源热榜
- **非 RSS 信号**：GitHub Trending、HuggingFace 热门论文、X AI 热帖（公开 API，无需 Twitter key）
- **今日简报**：中文 headline / overview / briefs / keywords；并附带 **Idea Sparks**（信号→机会→方案→MVP）；本地可随时重生，Pages 随 Actions 更新
- **可读体验**：分类色点、新鲜度（NEW / 今日）、今天·本周·更早分组、深浅色主题
- **工程向**：源可 `enabled` / `type` / `use_curl`；单源失败不拖垮；`dry-run` 验活；抓取日志与健康 API

---

## 信源地图

| 分类 | 代表源 |
|------|--------|
| AI 公司博客 | OpenAI · Anthropic · Google AI · DeepMind · Meta · NVIDIA · HF Blog · … |
| 学术论文 | ArXiv CS.AI / LG / CL / CV · HF Trending Papers |
| 行业媒体 | MIT Tech Review · TechCrunch AI · TLDR AI · Smol AI · Latent Space · … |
| 个人博客 / Newsletter | Lilian Weng · Sebastian Raschka · Chip Huyen · Ben's Bites · … |
| AI 安全 | LessWrong · Alignment Forum |
| 中文媒体 | 雷锋网 · 36氪 · 少数派 · 阮一峰 |
| 开源热榜 | GitHub Trending · X AI 热帖 |

完整列表见 [`feeds.json`](feeds.json)；本地可用 `python fetcher.py list` 查看启用状态。

---

## 两种使用方式

### A. 在线看（零安装）

打开 [GitHub Pages 演示](https://raise-lien.github.io/AITrending/)。  
数据由 Actions 约每 2 小时抓取；配置了 `DEEPSEEK_API_KEY` 时会同时生成今日简报。

### B. 本地面板（可手动刷新 / 重生简报）

```bash
git clone https://github.com/raise-lien/AITrending.git
cd AITrending
pip install -r requirements.txt
cp .env.example .env          # 填入 DEEPSEEK_API_KEY
python fetcher.py all         # 首次拉全量
python app.py                 # http://127.0.0.1:5003
```

顶部切换 **信息流 / 今日简报**；简报页可点「生成 / 刷新简报」。

---

## 架构（很短）

```
feeds.json ──► fetcher / special_sources ──► SQLite (items, fetch_log, digests)
                      │                              │
                      │                              ├── Flask API + 实时面板
                      │                              └── build.py → docs/ → GitHub Pages
                      └── digest.py ←── llm.py (DeepSeek)
```

| 文件 | 职责 |
|------|------|
| `feeds.json` | 源配置唯一入口 |
| `fetcher.py` | RSS + 调度入口；支持 dry-run |
| `special_sources.py` | GitHub / HF Papers / X |
| `db.py` | SQLite · FTS5 · digest 存取 |
| `llm.py` / `digest.py` | 模型调用、选稿简报、Idea Sparks 产品发现 |
| `app.py` | 本地 Web + 定时任务 |
| `build.py` | Actions 用静态站点构建 |
| `templates/` · `static/` | Flask 页与 Pages 静态页（共享 CSS） |

---

## API（本地 Flask）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/items` | 列表：`feed` `category` `q` `year` `limit` `offset` |
| GET | `/api/feeds` · `/api/categories` | 源 / 分类及计数 |
| GET | `/api/refresh` | 触发抓取 |
| GET | `/api/digest` | 当日简报 |
| GET | `/api/digest/generate?force=1` | 生成 / 强制重生 |
| GET | `/api/digest/list` | 历史简报元数据 |
| GET | `/api/enrich` | 回填条目中文摘要 |
| GET | `/api/llm/status` | 模型是否已配置 |
| GET | `/api/health/feeds` | 各源最近抓取状态 |
| GET | `/health` | 存活探针 |

静态站没有这些写接口：数据来自 `docs/data/*.json`。

---

## 常用命令

```bash
python fetcher.py all        # 抓取全部启用源
python fetcher.py dry-run    # 只验连通，不写库
python fetcher.py list       # 列出源与启用状态
python digest.py             # 生成今日简报
python digest.py enrich      # 为近期条目补中文摘要
python digest.py list        # 已存简报
python build.py              # 本地打静态包（需 key 才会写 digest）
```

---

## 环境变量

复制 [`.env.example`](.env.example)：

| 变量 | 说明 |
|------|------|
| `DEEPSEEK_API_KEY` | 简报 / 摘要必填（本地 `.env` 或 Actions Secret） |
| `LLM_MODEL` | 默认 `deepseek-chat` |
| `LLM_BASE_URL` | 默认 `https://api.deepseek.com/v1`；可换兼容中转 |
| `DIGEST_HOUR` | 本地自动生成简报的小时（默认 `8`） |
| `PORT` | Flask 端口（默认 `5003`） |

GitHub Pages：在仓库 **Settings → Secrets and variables → Actions** 配置 `DEEPSEEK_API_KEY`。  
workflow 见 [`.github/workflows/deploy.yml`](.github/workflows/deploy.yml)。

---

## 产品原则

1. **AI 垂直** — 不扩成综合资讯或行情站  
2. **双模态** — 实时流负责「全」，简报负责「少而精」，Idea Sparks 负责「可动手」  
3. **自托管友好** — SQLite、无强制云服务；LLM 可换成兼容 API  
4. **源可配置** — 改 JSON 即可加减源，不必改业务代码  

简报第二阶段会把今日信号映射为项目方向，方法参考 Product Trio 多视角头脑风暴与 Opportunity Solution Tree（信号 → 机会 → 方案 → MVP / 待验证假设）。

更多规划与明确不做的事项见 [`ROADMAP.md`](ROADMAP.md)。

---

## License

以仓库内许可证文件为准。
