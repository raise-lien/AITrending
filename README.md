# AITrending

AI 信息聚合面板 — 从 34 个高质量 RSS 源采集、展示 AI 领域最新动态。

## 快速启动

```bash
pip install -r requirements.txt
python fetcher.py all       # 拉取所有源
python app.py               # 启动 web 面板，默认 http://127.0.0.1:5003
```

## 功能

- **34 个 RSS 源**，按 8 个类别分组：
  - **AI 公司博客**：OpenAI、Google AI、Microsoft Research、NVIDIA、AWS ML、Meta Engineering、GitHub Engineering
  - **学术论文**：ArXiv CS.AI / CS.LG / CS.CL / CS.CV
  - **学术研究**：BAIR Blog（伯克利 AI）、Distill
  - **行业媒体**：TechCrunch AI、VentureBeat AI、MIT Tech Review、MarkTechPost
  - **个人博客**：Lilian Weng、Sebastian Raschka、Chip Huyen、Jay Alammar、Tim Dettmers、ML Mastery
  - **Newsletter**：Ben's Bites、The AI Edge
  - **AI 安全**：LessWrong、Alignment Forum
  - **中文媒体**：36氪、少数派、阮一峰的网络日志
- **分类筛选**：点击分类标签快速切换数据源范围
- **来源筛选**：下拉菜单选择具体 feed
- **年份筛选**：默认 2026 年，支持 2015-2026
- **实时搜索**：输入框过滤标题和摘要，关键词高亮
- **新鲜度标签**：6 小时内显示 NEW，当天显示「今日」
- **自动刷新**：每 30 分钟自动拉取，自动去重

## 项目结构

| 文件 | 说明 |
|---|---|
| `app.py` | Flask Web 服务 + 定时抓取调度 |
| `db.py` | SQLite 数据库操作（支持分类筛选查询） |
| `fetcher.py` | RSS 抓取 + 入库（feedparser + httpx） |
| `feeds.json` | RSS 源配置（含 name / url / category） |
| `templates/index.html` | 前端面板（暗色科技风，单文件） |
| `static/favicon.svg` | 站点图标 |

## API 端点

| 路由 | 说明 |
|---|---|
| `GET /` | 主页面 |
| `GET /api/items` | 条目列表，支持 `feed` / `category` / `q` / `year` / `limit` 参数 |
| `GET /api/feeds` | 数据源列表及条目计数 |
| `GET /api/categories` | 分类列表及条目计数 |
| `GET /api/refresh` | 手动触发抓取 |

## 技术栈

- **后端**：Flask + SQLite + feedparser + httpx + APScheduler
- **前端**：原生 HTML/CSS/JS（无框架），Inter + JetBrains Mono 字体
- **架构**：单文件，无构建步骤，开箱即用
