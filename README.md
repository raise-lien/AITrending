# AITrending

AI 信息聚合面板 — 从公开 RSS 源采集、展示 AI 领域最新动态。

## 快速启动

```bash
pip install -r requirements.txt
python fetcher.py all       # 拉取所有源
python app.py               # 启动 web 面板，默认 http://127.0.0.1:5003
```

## 功能

- **9 个 RSS 源**：OpenAI、HuggingFace、ArXiv CS.AI、Anthropic、DeepMind、雷锋网等
- **年份筛选**：默认 2026 年，右上角下拉切换 2015-2026
- **源筛选**：点击源标签切换
- **实时搜索**：输入框过滤标题和摘要
- **自动刷新**：每 30 分钟自动拉取，去重

## 项目结构

| 文件 | 说明 |
|---|---|
| `app.py` | Flask Web 面板 + 定时拉取 |
| `db.py` | SQLite 操作 |
| `fetcher.py` | RSS 抓取 + 入库 |
| `feeds.json` | RSS 源配置 |
| `templates/index.html` | 前端面板 |

545 行代码，无框架依赖。
