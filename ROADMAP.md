# AITrending Roadmap

> 最近更新：2026-07-14  
> 评分方法：RICE（Reach × Impact × Confidence / Effort）— Effort 用相对量级（S/M/L），不用日历工期。

---

## 项目现状（相对 2026-07-06）

| 维度 | 现状 |
|------|------|
| **定位** | AI 垂直信息聚合 + DeepSeek「今日简报」+ Idea Sparks |
| **数据源** | 41 个启用源（RSS / API / scrape），9 个分类 |
| **能力** | 信息流筛选搜索 · 每日 Digest · GH Pages 定时部署 |
| **技术栈** | Flask + SQLite + feedparser + httpx + APScheduler + DeepSeek |
| **部署** | 本地 Flask（`:5003`）+ GitHub Actions → Pages |

### 已完成（从旧 Roadmap / DailyBrief 接入）

| 项 | 状态 |
|----|------|
| 时间戳校验（拒绝 1900 前脏数据） | ✅ |
| Feed name 对齐 / 迁移脚本 | ✅ |
| 分页 + IntersectionObserver | ✅ |
| FTS5 全文搜索（代码就绪） | ✅ 需确认线上 `rebuild-fts` |
| fetch_log + `/api/health/feeds` | ✅ API 有，**前端未展示** |
| 复合索引 `(feed_name, published_ts)` | ✅ |
| GitHub Trending / HF Papers / X AI | ✅ |
| DeepSeek 今日简报 + 静态站导出 | ✅ |
| Idea Sparks（信号→机会→方案→MVP） | ✅ |
| `enabled` / `type` / `use_curl` / dry-run | ✅ |
| UI：信息流 / 简报双视图、light/dark | ✅ 部分落地 |

### 仍存在的关键缺口

| # | 问题 | 严重度 |
|---|------|--------|
| 1 | **大量条目无 summary**（本地库约半数为空，ArXiv 等源常见） | 🟡 |
| 2 | **`zh_summary` 几乎未批量回填**（仅 Digest 批量摘要，信息流仍偏英文） | 🟡 |
| 3 | **源健康 API 未上 UI** — 失效源用户不可见 | 🟡 |
| 4 | **FTS 索引可能未随库初始化** — 需显式 `rebuild-fts` / 启动时自检 | 🟡 |
| 5 | **零自动化测试** | 🟡 |
| 6 | **公网敏感 API 无鉴权**（`/api/refresh`、`/api/digest/generate`） | 🟢（Pages 无此问题；Flask 公网需注意） |
| 7 | **简报历史无可浏览归档**（`/api/digest/list` 有，UI 无） | 🟢 |
| 8 | **跨源重复报道未去重** | 🟢 |

---

## 下一步（值得做、尚未做）

### P0 — 数据质量与可感知可靠性

#### 1. 空 Summary 补全策略
- **为什么**：信息流卡片与搜索都依赖摘要；ArXiv / 部分 scrape 源经常空白。
- **方案**：
  - ArXiv：优先 `summary`/`description`/`content` 多字段回退，必要时抓 abstract 页（限流）
  - GitHub Trending / X：保证 meta 行写入 summary
  - 抓取后统计「无摘要率」，在 `/api/health/feeds` 暴露
- **RICE 直觉**：高 Reach · 中 Impact · Effort **M**

#### 2. 源健康状态上前端
- **为什么**：API 已有，失效源仍静默；用户只能干等空结果。
- **方案**：
  - 顶栏或设置抽屉展示「异常源」徽章
  - 连续失败 ≥3 的源在来源下拉里标红
  - 可选：Actions 构建日志汇总失败源列表到 `meta.json`
- **RICE**：中 Reach · 高 Impact · Effort **S**

#### 3. FTS 启动自检 / 构建时重建
- **为什么**：新库或 Pages 构建后 FTS 表可能不存在，搜索 silently fallback 到 LIKE。
- **方案**：`init_db()` 检测无 `items_fts` 则自动 `rebuild_fts_index()`；`build.py` 导出前重建一次。
- **RICE**：高 Reach · 中 Impact · Effort **S**

---

### P1 — 简报与中文体验

#### 4b. Idea Sparks 深化（已落地基础版）
- **已做**：简报二阶段调用，输出 5 条结构化项目 idea（Product Trio 视角 + OST 链路 + MVP / 假设）。
- **下一步（可选）**：按用户画像过滤（研究者 / indie hacker）、跨日 idea 去重、一键复制 Markdown。
- **RICE**：高 Reach · 高 Impact · Effort **S–M**

#### 4. 信息流条目级中文摘要（enrich 流水线）
- **为什么**：Digest 是「一天一份」；刷信息流时英文原文仍难扫读。
- **方案**：
  - Actions / 本地定时对「近 N 条且无 `zh_summary`」调用 `digest.enrich_recent_items`
  - 卡片优先展示 `zh_summary`（已接好展示字段）
  - 控制日调用量（例如最多 60 条/构建），避免成本失控
- **RICE**：高 Reach · 高 Impact · Effort **M** · 有 API 成本

#### 5. 简报历史归档页
- **为什么**：Digest 按日落库，但 UI 只能看「今天」；错过就找不回。
- **方案**：简报视图增加日期切换；静态站导出 `data/digests/*.json` + 列表。
- **RICE**：中 Reach · 中 Impact · Effort **M**

#### 6. Digest / 条目 Markdown 导出
- **为什么**：便于贴到 Notion / 飞书 / 个人笔记；DailyBrief 同款能力。
- **方案**：`OUTPUT_MARKDOWN=true` 或 `/api/digest.md`；静态站提供「复制 Markdown」按钮。
- **RICE**：中 Reach · 中 Impact · Effort **S**

#### 7. 跨源近重复折叠
- **为什么**：同一新闻常出现在 TechCrunch + Latent Space + X；刷流噪音大。
- **方案**：标题相似度（简单 normalize + token overlap）或 link canonical；UI 折叠为「另有 N 个来源」。
- **RICE**：中 Reach · 中 Impact · Effort **L**

---

### P2 — 工程与产品化

#### 8. 最小测试集
- **覆盖**：`special_sources` 解析 fixture、`llm.extract_json`、`select_candidates` round-robin、`fetcher` dry-run mock。
- **Effort**：M；对后续改源/改 prompt 很关键。

#### 9. 抓取重试与并发
- **方案**：单源失败指数退避 1–2 次；`httpx`/`asyncio` 有限并发（如 6）缩短 Actions 构建时间。
- **Effort**：M

#### 10. Flask 写操作鉴权
- **方案**：`REFRESH_TOKEN` / Basic Auth；未配置时本地放行，公网拒绝。
- **Effort**：S

#### 11. PR 上跑 `fetcher.py dry-run` + `sources` schema 校验
- **方案**：GitHub Action on pull_request，失败源不阻断 merge 但标 warning。
- **Effort**：S

#### 12. 可插拔多 LLM 后端（产品化）
- **现状**：`LLM_BASE_URL` 已可接兼容接口，但文档与错误提示仍偏 DeepSeek。
- **方案**：显式支持 `LLM_BACKEND=openai|anthropic|deepseek`，启动时校验配对；用量记入简单日志。
- **Effort**：M

#### 13. UI 设计债（摘自 ui-audit，仍开放）
- 宽屏信息密度（>1280 双列或加宽 max-width）
- 排序：最新 / 仅今日 / 按来源
- 品牌字体去 Inter 默认感（与现有设计系统协调推进）
- **Effort**：按项 S–M

#### 14. 本地收藏（localStorage）
- **方案**：卡片「稍后读」，不建账号；与 non-goals「不多用户」不冲突。
- **Effort**：S

---

## 优先级总览

| 优先级 | 任务 | Effort | 依赖 |
|--------|------|--------|------|
| **P0** | 源健康上 UI | S | 已有 API |
| **P0** | FTS 启动自检 | S | 已有 rebuild |
| **P0** | 空 Summary 补全 | M | fetcher |
| **P1** | 条目级中文 enrich | M | DeepSeek 配额 |
| **P1** | 简报历史归档 | M | digests 表 |
| **P1** | Markdown 导出 | S | — |
| **P1** | 跨源去重折叠 | L | — |
| **P2** | 测试 / 重试并发 / 鉴权 / PR dry-run | S–M | — |
| **P2** | 多 LLM 后端文档化 | M | — |
| **P2** | UI 债 / 本地收藏 | S–M | — |

### 建议推进顺序

```
P0 可感知可靠性（健康 UI + FTS 自检 + 空摘要）
  → P1 中文体验（enrich + 归档 + MD 导出）
  → P2 工程护栏（测试 / 鉴权 / 并发）与体验打磨
```

---

## Non-goals（明确不做）

| 不做 | 原因 |
|------|------|
| 评论 / 社交 | 聚合工具，不养社区 |
| 个性化推荐算法 | 主动筛选源 > 黑盒投喂 |
| 原生移动 App | 响应式 Web 足够 |
| **原创内容生产** | 只做聚合、摘要、编排；不写「伪原创」长文 |
| 付费墙 / SaaS 计费 | 保持个人/小团队开源工具 |
| 多用户账号体系 | 单人/自托管优先；收藏用本地存储即可 |
| Chrome 扩展 | 先把 Web / Pages 体验做透 |
| 财经行情 / 时政大而全 | 坚持 **AI 垂直**，不稀释定位 |
| 用静态日报替换实时信息流 | 简报是增量视图，不是唯一形态 |

> 邮件/推送「订阅今日简报」：暂不作为承诺项；若有强需求可单独立项（仍属可选，非核心）。

---

## 参考

- 产品演示：https://raise-lien.github.io/AITrending/
- UI 评审：`ui-audit/REVIEW.md`
- 灵感对照：[DailyBrief](https://github.com/leiting-eric/DailyBrief)（已吸收：热榜源、LLM 摘要、静态日报；明确不吸收：行情/时政）
