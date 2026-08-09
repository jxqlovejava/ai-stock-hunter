# TradingAgents 参考分析

> 本地：`.references/TradingAgents`  
> 源码：https://github.com/TauricResearch/TradingAgents  
> 论文：https://arxiv.org/abs/2412.20138  
> 许可证：Apache 2.0  
> 分析日期：2026-08-09

**TradingAgents**（TauricResearch，76k+ star）是 TradingAgents-Astock 的**上游原版**。核心价值不在"多 Agent 会说话"，而在其**多维度讨论协作 → 交易决策的确定性收敛机制**：四维分析师产出 → 两级辩论 → 三层收敛 → 结构化输出契约 → 复盘学习闭环。白泽（ai-stock-hunter）借鉴的是这套**协作编排与反幻觉护栏**，而非绑定其 yfinance 美股数据栈。

> ⚠️ A 股特化 fork（数据源/分析师角色/T+1 交易规则）见 [tradingagents-astock-analysis.md](tradingagents-astock-analysis.md)。本文聚焦**原版协作机制**，与 fork 分析互补。

---

## 一、总体架构：四级流水线

```
四维分析师(各自工具循环) ──► 牛熊辩论 ──► 研究经理裁决 ──► 交易员 ──► 风险三方辩论 ──► 组合经理终裁
  market / sentiment / news / fundamentals   (deep LLM)     (quick LLM)   (risk debate)      (deep LLM)
```

图结构在 `tradingagents/graph/setup.py`，用 LangGraph `StateGraph` 定义节点与条件边。核心是**两级"辩论-收敛"嵌套结构** + **结构化输出** + **确定性事实锚点**。

## 二、四维数据收集层

四个分析师**串行执行**（`plan.specs` 顺序），但每个分析师内部是独立的工具循环（`LLM → 工具 → 回到 LLM`，直到不再调用工具）。条件逻辑 `should_continue_*`（`graph/conditional_logic.py`）控制循环：有 `tool_calls` 就回到工具节点，否则进入 `Msg Clear` 清消息节点 → 下一个分析师。

| 维度 | Agent | 工具集 | 产出（存 state） | 设计要点 |
|------|-------|--------|-----------------|---------|
| **技术** | `market_analyst` | `get_stock_data` + `get_indicators`（≤8 个互补指标：MA/MACD/RSI/Boll/ATR/VWMA） | `market_report` | **强制性数据真相锚点**：写报告前必须调 `get_verified_market_snapshot`，以它为准核验 OHLCV/指标值，冲突要标注而不编造 |
| **情绪** | `sentiment_analyst` | 无 tool-call，**预取** 新闻 + StockTwits + Reddit 三源注入 prompt | `sentiment_report` | 结构化输出 `SentimentReport`（`overall_band` / `overall_score` 0-10 / `confidence` / `narrative`） |
| **新闻** | `news_analyst` | `get_news` + `get_global_news` + `get_macro_indicators`(FRED) + `get_prediction_markets` | `news_report` | 宏观 + 个股 + **前瞻事件概率**（如"Fed 降息概率"）三档覆盖 |
| **基本面** | `fundamentals_analyst` | `get_fundamentals` + `get_balance_sheet` + `get_cashflow` + `get_income_statement` | `fundamentals_report` | 完整财务报表视角 |

### 反幻觉护栏（三个关键设计）

1. **确定性真相源**：`get_verified_market_snapshot` 被技术分析师 prompt 强制调用，任何精确 OHLCV/价格/指标值必须与快照核验一致，冲突标注而非编造。
2. **预取注入防编造**：情绪分析师**不用 tool-call**，而是先把 新闻/StockTwits/Reddit 三源数据**预取结构化注入 prompt**（源码 docstring 明确记载，见 `sentiment_analyst.py`）。旧版让 LLM 自己调新闻工具却要求分析 Reddit/X，导致 prompt pressure 下**编造帖子内容**（issue #557/#796）。现在数据第 0 轮就在 prompt 里，杜绝编造。
3. **`Msg Clear` 清消息**：每个分析师结束后清掉中间工具消息，防止多轮工具调用的消息把上下文撑爆。

## 三、两级辩论机制

### 第一级：牛熊投研辩论（Bull vs Bear）
- `Bull Researcher` ↔ `Bear Researcher` 交替发言（`researchers/bull_researcher.py` / `bear_researcher.py`）。
- 双方 prompt 都要求：**以四份报告为证据**、反驳对方论点、对话式交锋。
- 状态累积：`history`（全量）+ `bull_history`/`bear_history`（各自立场）+ `current_response`（当前发言）。
- 终止：`should_continue_debate` — `count >= 2 * max_debate_rounds`（默认 1 轮 = 牛熊各 1 次发言）→ Research Manager；否则按"当前发言者是 Bull 就轮到 Bear"轮换。

### 第二级：风险三方辩论（Aggressive / Conservative / Neutral）
- 交易员出提案后，**激进/保守/中性三方**围绕 trader decision 辩论，每方 prompt 都要求：针对另外两方的论点逐条数据反驳。
- 关键点：**每个风险辩论者都能看到四份原始报告**（`market_report/sentiment_report/news_report/fundamentals_report` 全部注入 prompt），所以辩论不是空转，而是基于同一批证据从不同风险偏好出发重新加权。
- 终止：`count >= 3 * max_risk_discuss_rounds`（默认 1 轮 = 三方各 1 次）。

## 四、三层收敛：从讨论到决策

| 层 | Agent | 输入 | 输出（结构化） | 说明 |
|----|-------|------|---------------|------|
| 1 | **Research Manager**（deep LLM） | 牛熊辩论 history | `ResearchPlan`（评级 Buy/Overweight/Hold/Underweight/Sell + 理由 + 风险评估） | 作为"辩论主持人"收敛牛熊分歧 |
| 2 | **Trader**（quick LLM） | investment_plan | `TraderProposal`（动作 + 仓位 + 理由） | 把研究计划落成可执行交易提案 |
| 3 | **Portfolio Manager**（deep LLM） | 研究计划 + 交易提案 + **历史教训** + 风险辩论 history | `PortfolioDecision`（`rating` + `executive_summary` + `investment_thesis` + `price_target` + `time_horizon`） | 终裁；`signal_processing.py` 用确定性启发式从结构化输出提取 5-tier rating（**无需第二次 LLM 调用**） |

**结构化输出是贯穿全链路的强制契约**（`agents/schemas.py`）：`PortfolioRating` / `TraderAction` / `SentimentBand` 全是 Enum，字段描述兼作 LLM 输出指令。provider 不支持原生 structured output 时优雅降级为自由文本（`agents/utils/structured.py` 的 `invoke_structured_or_freetext`）。

## 五、复盘学习闭环

`agents/utils/memory.py` + `graph/trading_graph.py::_resolve_pending_entries` 构成**决策-结果-反思**闭环：

1. 每次运行 `store_decision` 记录 `final_trade_decision`（标记 `outcome: pending`）。
2. 下次**同标的**运行时，`_resolve_pending_entries` 拉取该决策的实际回报：`raw_return` + **`alpha_return`（相对 benchmark，默认 SPY）**。
3. `Reflector.reflect_on_final_decision` 让 LLM 生成复盘（decision vs 实际结果）。
4. 更新记忆后，`get_past_context` 在下次运行注入：**同标的的历史 5 条 + 跨标的教训 3 条**，作为 Portfolio Manager 的 `lessons_line` 上下文。

> 设计要点：**alpha（相对基准）而非绝对回报**作为复盘标的；同标的决策延迟到"价格数据可用"才结算；教训跨标的复用但同标的优先。

## 六、其他值得注意的设计

- **双 LLM 分工**：`deep_thinking_llm`（研究经理/组合经理 — 收敛判断）+ `quick_thinking_llm`（分析师/交易员/辩论者 — 生成内容），成本与推理深度分层。
- **instrument context 锚定**：`resolve_instrument_context` 用确定性 yfinance 查询解析标的真实身份，注入所有 agent 防幻觉（issue #814）。
- **provider 无关**：`llm_clients/create_llm_client` 抽象支持 Anthropic/OpenAI/Gemini/OpenRouter 等，thinking level / reasoning effort 按 provider 透传。

---

## 七、对白泽的借鉴落地映射

| TradingAgents 机制 | 白泽落点 | 状态 |
|------|---------|------|
| `get_verified_market_snapshot` 确定性快照锚定 | `src/data/verified_snapshot.py` + technical/tactics 报告锚定，冲突标注不编造 | ✅ 已落地（含展示） |
| 情绪预取注入防编造 | `src/information/guba_sentiment_llm.py` 预取注入 + `GubaSentimentResult` DTO；orchestrator `GUBA_LLM_ENHANCE=1` opt-in 接入 | ✅ 已落地（opt-in 接入） |
| `schemas.py` 结构化输出 + provider 降级 | `src/llm/structured.py` `invoke_structured_or_freetext` + dataclass→JSON Schema | ✅ 已落地 |
| alpha 相对基准复盘 + 跨标的教训注入 | `src/learner/signal_tracker.py` 记 `alpha_return_pct` + `get_lessons`；`learn report` 渲染 `lessons` | ✅ 已落地（报告接线） |
| `get_past_context` 历史结论注入终裁 | `conclusion_ledger` 历史结论注入 `verdict`（`history_context` + 置信度微调 + 分歧风险），`print_verdict` 展示 | ✅ 已落地（含展示） |
| 牛熊辩论 + 风险三方辩论分层收敛 | 白泽已有四大师辩论 + 军规门禁 | 参考 |
| `Msg Clear` 防上下文膨胀 | 白泽 Compactor 压缩 | 参考 |

> 注：M2/M4 为"能力 + 消费点接线"，数据随运行累积（opt-in 开关 / 信号跟踪数据）。观测层原则不变——任何注入均为只读背景，不回填策略参数。
