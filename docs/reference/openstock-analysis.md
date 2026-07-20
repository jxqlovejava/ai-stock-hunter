# OpenStock — 开源股票市场看板

> 源码：https://github.com/Open-Dev-Society/OpenStock（AGPL-3.0）
> 定位：Next.js 全栈开源股票行情与自选跟踪 Web 应用——替代昂贵市场平台的免费方案

## 一、技术架构

```
Next.js 15 (App Router) + React 19 + TypeScript
  ├── MongoDB + Mongoose（用户/自选/提醒持久化）
  ├── Finnhub API（行情/搜索/公司档案/新闻）
  ├── TradingView Widgets（图表/热力图/报价/技术指标嵌入）
  ├── Better Auth（邮箱密码认证 + MongoDB Adapter）
  ├── Inngest（事件驱动后台作业 + Cron + AI 推理）
  │     ├── app/user.created → Gemini AI 个性化欢迎邮件
  │     ├── Cron 0 12 * * * → 每日/每周新闻摘要
  │     ├── Cron */5 * * * * → 价格提醒检测（ABOVE/BELOW）
  │     └── Cron 0 10 * * * → 30天不活跃用户再激活
  ├── Nodemailer（Gmail 传输）+ Kit（邮件广播）
  ├── shadcn/ui + Radix UI + Tailwind CSS v4
  └── cmdk 命令面板（⌘K 全局股票搜索）
```

## 二、核心功能模块

### 2a. 数据层 — Finnhub 集成

| 端点 | 用途 | 缓存策略 |
|------|------|---------|
| `/quote` | 实时报价 (c, d, dp) | 不缓存（实时） |
| `/stock/profile2` | 公司档案（名称/交易所/Logo/市值） | 24h 缓存 |
| `/search` | 股票搜索（符号/描述/类型） | 30min 缓存 |
| `/company-news` | 个股新闻（5天窗口，round-robin 最多6条） | 5min 缓存 |
| `/news?category=general` | 市场综合新闻（fallback） | 5min 缓存 |

关键业务点：
- **round-robin 新闻聚合**：多标的时对每只取公司新闻，逐轮取一条，最多6条 → 按时间倒序。避免单票霸占新闻列表。
- **缓存分层**：`fetchJSON()` 支持 `revalidateSeconds` 参数，利用 Next.js `fetch` 内置 ISR 缓存。实时报价 `revalidate=0`；档案 `86400`；搜索 `1800`。
- **交换所后缀识别**：44 个 Finnhub 后缀集合自动判定交易所标签（如 `.NS`→印度 NSE）。
- **优雅降级**：未配 API Key 时搜索返回空数组、日志记录而不抛异常。

### 2b. 后台作业 — Inngest

| 作业 | 触发 | 流程 |
|------|------|------|
| `sendSignUpEmail` | `app/user.created` 事件 | 取用户画像（国家/目标/风险/行业）→ Gemini 生成个性化欢迎语 → Nodemailer 发送 |
| `sendWeeklyNewsSummary` | 每周一 9AM + 手动事件 | 取综合新闻 → Gemini 摘要 → Kit 广播给所有订阅者 |
| `checkStockAlerts` | 每 5 分钟 | 查有效未触发 alert → 批量取报价 → 比对 ABOVE/BELOW 条件 → 标记已触发 |
| `checkInactiveUsers` | 每天 10AM | 查 30 天未活跃 + 未发过召回的用户 → 发再激活邮件 → 防重复标记 |

关键业务点：
- **AI Provider 多路 fallback**：Gemini → MiniMax → Siray 三级回退，每层异常不阻断作业。
- **Kit 广播约束**：批量邮件通过 Kit API 给全体订阅者发送；单用户事务邮件（如再激活）当前仅对测试用户真实发送，其余用 mock（Kit Broadcast 无原生单用户发送能力）。
- **防重复**：`lastReengagementSentAt` 字段确保 30 天内不对同一用户重复召回。

### 2c. 前端体验

- **⌘K 命令面板** (`SearchCommand.tsx`)：空闲时显示热门股票（`POPULAR_STOCK_SYMBOLS` Top 10），输入时 debounced 搜索 Finnhub，结果标 watchlist 状态。
- **TradingView 嵌入** (`TradingViewWidget.tsx`)：symbol info / candlestick / advanced charts / technicals / heatmap / quotes / timeline，统一通过 custom hook `useTradingViewWidget` 管理脚本加载。
- **Sentiment 卡片**（可选）：Adanos API 提供跨 Reddit/X/News/Polymarket 情绪快照。
- **个性化 onboarding**：收集国家、投资目标、风险容忍度、偏好行业后触发生成 AI 欢迎邮件。

## 三、可直接借鉴到本项目的业务机制

| # | 机制 | 来源 | 应用到本项目 |
|---|------|------|------------|
| 1 | **新闻 round-robin 聚合**（多标的分轮取，避免单票霸占） | `lib/actions/finnhub.actions.ts:getNews()` | `data/aggregator.py` 多票新闻拉取去偏 |
| 2 | **ISR 缓存分层**（实时不缓存/搜索 30min/档案 24h） | `lib/actions/finnhub.actions.ts` | `data/aggregator.py` 数据源 TTL 策略 |
| 3 | **事件驱动后台作业**（用户注册→AI 邮件 / cron→新闻摘要 / cron→价格提醒） | `lib/inngest/functions.ts` | 自动盯盘/定时简报（对齐 go-stock #9）+ L4 价格预警引擎 |
| 4 | **AI Provider 多路 fallback**（Gemini→MiniMax→Siray 三级） | `lib/ai-provider.ts` | LLM 调用统一入口（对齐 go-stock #8） |
| 5 | **防重复召回**（30 天内不对同一用户重复发再激活邮件） | `lib/inngest/functions.ts:checkInactiveUsers` | 防骚扰限频机制 |
| 6 | **⌘K 全局搜索**（空闲热门+输入 debounced 搜索+watchlist 标记） | `components/SearchCommand.tsx` | CLI `screen` / `search-news` 交互优化 |
| 7 | **TradingView Widget 嵌入**（symbol info/candlestick/technicals/heatmap） | `components/TradingViewWidget.tsx` | 回测/诊断可视化的轻量备选方案 |
| 8 | **个性化 onboarding**（投资目标/风险/偏好行业→AI 欢迎） | `app/(auth)/sign-up` | 投资者偏好 `preference` 初始化流程 |
| 9 | **交易所后缀自动识别**（44 个 Finnhub 后缀集合） | `lib/actions/finnhub.actions.ts` | A 股市场标识标准化（沪/深/北） |
| 10 | **批量告警检测**（每 5 分钟，按 symbol 分组取价后批量比对） | `lib/inngest/functions.ts:checkStockAlerts` | 价位预警引擎批量轮询优化 |

> ⚠️ **注意**：OpenStock 是面向全球个人投资者的行情看板与自选跟踪工具，**不涉及交易决策、策略回测、A 股数据**。其核心价值在于 **(1) Next.js 全栈开源架构参考**、(2) **Inngest 事件驱动后台作业模式**（AI 邮件/新闻摘要/价格提醒/用户召回）、(3) **Finnhub 数据源集成模式**（缓存分层+降级策略）、(4) **前端体验设计**（⌘K 搜索/TradingView 嵌入/个性化 onboarding）。
