# AITrending UI 设计评审报告

> 评审人：UI Designer ｜ 日期：2026-07-07
> 评审对象：`templates/index.html`（Flask 版）、`templates/static.html`、`docs/index.html`（静态版）
> 三者 CSS 几乎 100% 重复，是同一套「深色阅读器」界面的两个部署形态。

---

## 一、总体结论

当前界面是一个**功能完整、风格统一、可用**的极简深色信息流阅读器。在「把 RSS 聚合内容展示清楚」这一目标上基本达成。但作为长期产品，它存在三类必须解决的问题：

1. **缺乏真正的设计系统**——样式靠散落的魔法数字和少量 CSS 变量，无法支撑后续扩展（新页面、light 模式、组件复用）。
2. **可访问性不达标（低于 WCAG AA）**——次级文本对比度不足、键盘 focus 不可见、无 `prefers-reduced-motion`、emoji 当图标。
3. **美学属于「泛 AI 套路」**——纯黑底 + 青绿高亮 + 发光阴影 + Inter 字体，正是需要规避的默认 AI 审美，缺乏品牌差异化。

**优先级建议**：P0（可访问性 + 结构）→ P1（设计系统化 + 组件统一）→ P2（美学个性 + 动效打磨）。

---

## 二、问题诊断清单

### 2.1 设计系统缺口（Design Tokens 不完整）

| 现状 | 问题 |
|------|------|
| 颜色仅有扁平几档（`--bg/surface/surface2/border/text/text2/text3/brand`），无层级 scale | 缺少 `primary-50→900` 体系，无法表达 hover/active/disabled 的状态梯度；`--surface #12121a` 与 `--surface2 #1a1a26` 对比仅 ~1.2:1，层次几乎靠 1px border 撑着 |
| `--accent: #6366f1` 定义后**从未使用** | 死变量，说明设计语言未规划完 |
| 间距全部硬编码（`20px / 24px / 16px / 18px / 6px` 散落） | 无 `--space-*` 体系，视觉节奏不统一，改版时易漂移 |
| 字号硬编码（`14px / 13px / 12px / 11px / 20px`） | 无 type scale，标题/正文/辅助缺乏数学关系 |
| 无 `--shadow` / elevation 系统 | 仅用 border 区分层次，缺乏深度；hover 仅靠背景微变 |
| 无 `--z-index` 层级变量 | topbar 写死 `z-index:50`，后续叠加层易冲突 |
| 单一 `--radius:10px` | 缺少 sm/md/lg 梯度，卡片与圆角按钮无法区分轻重 |

### 2.2 可访问性缺陷（低于 WCAG AA）—— **P0**

| 问题 | 实测影响 |
|------|---------|
| 次级文字 `--text3: #55556a` 用于 meta 时间、placeholder | 在 `--surface #12121a` 上对比度约 **2.5:1**，远低于 4.5:1（正文）与 3:1（大字）。**不达标** |
| `--text2: #8b8b9e` 用于来源标签、按钮文字 | 约 5.3:1，仅勉强达标，无余量 |
| 键盘 `:focus-visible` 缺失：`.btn / .cat-pill / .feed-select / .item-card` 仅有 `border-color` 变化 | 键盘用户难以察觉当前焦点，**导航不可用** |
| 无 `prefers-reduced-motion` | shimmer / spin 动画对前庭敏感用户有害 |
| emoji 当图标（📡 📭） | 跨平台渲染不一致、屏幕阅读器可能念出「信封」；无障碍语义弱 |
| 卡片整块是 `<a>`，无 `aria-label`，内部仅文本 | 屏幕阅读器逐字念标题+摘要，缺来源/时间的结构化播报 |
| 无 skip-link、无 `lang` 外的地标（`role="main"`/`search`） | 键盘跳转效率低 |
| 年份 select 复用 `.btn` 类并内联 style hack | 语义与视觉混淆，focus 态不一致 |

### 2.3 布局与信息架构

| 问题 | 影响 |
|------|------|
| 固定 `max-width:960px` 单列 | ≥1280px 宽屏两侧大片空白，信息密度低、滚动成本高 |
| 无日期/时间分组（按「今天 / 本周 / 更早」分节） | 用户无法快速建立时间心智模型，长列表难扫描 |
| 卡片 `gap:6px` 几乎相连 | 视觉上像「列表」而非「卡片」，缺少呼吸感与可点击暗示 |
| 分类（pills）+ 来源（select）占两行纵向空间 | 首屏被筛选项挤压，内容曝光不足 |
| 无排序选项（最新 / 热门 / 来源） | 用户无法主动控制信息优先级 |
| 空状态文案笼统（「暂无数据 / 点击刷新」） | 缺乏有意义引导，尤其静态站无刷新按钮时更困惑 |

### 2.4 组件一致性与交互细节

| 问题 | 说明 |
|------|------|
| `.btn-brand` 定义但**从未使用** | 主操作（刷新）视觉权重不足，与次要按钮无区分 |
| hover 用 `transform: translateX(2px)` | 整列卡片 hover 时轻微「跳动」，长列表下显躁动 |
| 卡片 hover 标题变 `--brand` 青绿 | 青绿在深底对部分色弱用户对比不足 |
| 「加载更多」按钮 + 无限滚动**同时启用** | 静态版 `IntersectionObserver` 同步调用 `loadMore()`，大数据集可能卡顿 / 双重触发 |
| 时间用客户端 `new Date(publishedTs)` | 跨时区「今日 / NEW」判定不严谨；`published_ts` 格式若非 ISO 会错位 |

### 2.5 工程与性能

| 问题 | 风险 |
|------|------|
| 三套模板 CSS 几乎完全重复 | 改一处需改三处，设计漂移与维护成本 |
| 全部样式/脚本内联在单 HTML | 无法复用，违反「设计系统一次定义多次使用」 |
| 标题/摘要经 `escapeHtml` 但 `link`、`feed` 直接拼接 | 理论上存在 XSS / 注入面（feed 名若含恶意字符） |
| Google Fonts `<link>` 阻塞渲染 | 无 `preconnect` 已加，但无字体 `preload`/`font-display` 微调 |
| 无 light 模式 | 白天 / 户外场景可读性差，且失去一半用户偏好 |

### 2.6 美学与品牌（AI Slop 风险）—— **P2**

当前配色 = 纯黑底 + 青绿高亮 + 发光阴影 + Inter，正是需要规避的「默认 AI 审美三件套」。优点是有清晰品牌色，缺点是**缺乏记忆点与差异化**。favicon（单字母 A + 不同渐变）与 logo（AI 方块）视觉不一致，削弱品牌识别。

---

## 三、优化方案（分级落地）

### P0 — 可访问性 & 结构（必须做，先做）

1. **重建对比度梯度**：将 `--text2` 提亮至 `#9ca3b0`+、`--text3` 提亮至 `#6b6b80`+；meta 时间至少用 `--text2` 并确保 ≥4.5:1（或放大至 12px+ 走 3:1 大字线）。
2. **统一 focus-visible**：所有可交互元素加 `outline: 2px solid var(--brand); outline-offset: 2px;`，移除仅靠 border 的弱反馈。
3. **加 `prefers-reduced-motion`**：在 `@media (prefers-reduced-motion: reduce)` 中关闭 shimmer/spin/transition。
4. **去 emoji，用内联 SVG 图标**（信号、空盒、搜索、刷新），统一 1.5px 描边风格。
5. **语义化地标**：`<main>`、搜索区 `role="search"`、卡片 `aria-label="来源 · 时间 · 标题"`。
6. **加 skip-link**：「跳到内容」锚点，键盘首屏可达。

### P1 — 设计系统化（建立可扩展基础）

7. **抽离共享设计 token**（见下方示例），并拆分为独立 `styles/tokens.css` + `styles/base.css`，三模板 `@import` 复用，消除重复。
8. **建立 spacing / type / radius / elevation 四套 scale**，全站改用变量。
9. **死变量清理**：`--accent` 要么用于分类色编码，要么删除。
10. **组件 API 统一**：按钮 `.btn / .btn--primary / .btn--ghost`，分类用统一 chip，来源筛选统一 select 样式，移除 `.btn` 复用到 select 的 hack。
11. **分类色编码**：用 `--accent` 及一组语义色为 8 个分类分配稳定色点（仅作小圆点/左边线，不喧宾夺主）。

### P2 — 美学个性 & 体验打磨

12. **宽屏多列 + 时间分组**：≥1024px 用 2 列卡片网格（容器查询 `@container`），并按「今天 / 本周 / 更早」插入分隔标题；保留单列移动端。
13. **更克制的深度**：用分层 elevation 替代发光 box-shadow；hover 用背景 + 左边线（保留但去掉 translateX 跳动，改为轻微背景提升）。
14. **Light 模式**：基于 `light-dark()` 或 `data-theme` 提供切换，默认跟随系统。
15. **有意义的空状态**：区分「无数据 / 搜索无结果 / 加载失败」三态，给出可操作引导。
16. **品牌统一**：favicon 与 logo 共用同一图形语言；可选为 logo 设计更具识别度的标记。
17. **动效克制**：状态变化用 `ease-out-quart` 指数缓动，时长 200–300ms，只动 opacity/transform 单属性。

---

## 四、优化后设计 Token 示例（草案）

```css
:root {
  /* 间距 scale（4px 基准） */
  --space-1:4px; --space-2:8px; --space-3:12px; --space-4:16px;
  --space-5:20px; --space-6:24px; --space-8:32px; --space-10:40px;

  /* 字阶（1.2 比例 + 流体） */
  --fs-xs:12px; --fs-sm:13px; --fs-base:14px; --fs-md:16px;
  --fs-lg:20px; --fs-xl:24px; --fs-2xl:30px;

  /* 圆角梯度 */
  --r-sm:6px; --r-md:10px; --r-lg:14px; --r-pill:999px;

  /* 语义色（深/浅由 light-dark 或 data-theme 切换） */
  --c-text:        light-dark(#1a1a24, #e8e8f0);
  --c-text-muted:  light-dark(#5b5b6b, #9ca3b0);  /* 已提亮，确保 ≥4.5:1 */
  --c-surface:     light-dark(#ffffff, #12121a);
  --c-surface-2:   light-dark(#f4f4f8, #1a1a26);
  --c-border:      light-dark(#e4e4ec, #1e1e2e);
  --c-brand:       #00c8a0;   /* 略降饱和，更沉稳 */
  --c-brand-ink:   #04332a;   /* 品牌色上的文字 */
  --c-accent:      #6366f1;   /* 分类色编码启用 */

  /* 深度（替代发光） */
  --shadow-1: 0 1px 2px rgb(0 0 0 / .06), 0 1px 1px rgb(0 0 0 / .04);
  --shadow-2: 0 4px 12px rgb(0 0 0 / .10);
  --shadow-3: 0 12px 28px rgb(0 0 0 / .14);

  /* 焦点（P0） */
  --focus: 0 0 0 2px var(--c-surface), 0 0 0 4px var(--c-brand);

  /* 层级 */
  --z-topbar:100; --z-popover:200; --z-toast:300;

  /* 动效 */
  --ease-out: cubic-bezier(.22,1,.36,1);
  --dur: 220ms;
}

/* P0：键盘焦点处处可见 */
:focus-visible { outline: none; box-shadow: var(--focus); border-radius: var(--r-sm); }

/* P0：尊重减少动效偏好 */
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation: none !important; transition: none !important; }
}
```

---

## 五、落地路径建议

| 阶段 | 动作 | 产出 |
|------|------|------|
| 1（P0） | 修复对比度、focus、reduced-motion、去 emoji、语义地标 | 可访问性达 AA |
| 2（P1） | 抽离 `tokens.css`/`base.css`，三模板复用；建立 spacing/type/radius/elevation scale；统一组件 API；分类色编码 | 设计系统就绪 |
| 3（P2） | 宽屏多列 + 时间分组；light 模式；空状态三态；品牌统一；动效打磨 | 差异化与体验升级 |

> 配套交付：`prototype.html` —— 一个可交互的优化原型，演示上述 P0/P1/P2 关键改进（token 系统、focus、light/dark、时间分组、多列响应式、去 emoji、统一组件）。可直接在浏览器打开预览。

---

**UI Designer 评审完成。下一步可直接进入 P0 实施，或先用 `prototype.html` 对齐视觉方向。**
