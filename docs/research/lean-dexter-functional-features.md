# LEAN + Dexter 功能层面可借鉴特性

> 2026-07-08 | 补充 `lean-dexter-analysis.md`（系统设计篇）的功能层面分析

---

## 一、来自 LEAN 的可移植功能

### 1. 技术指标库（87 个指标） 🔴 最高优先级

LEAN 有 87 个非 K 线的技术指标，我们目前只有约 17 个。以下是缺失且值得移植的：

#### 趋势类（高价值）

| 指标 | 用途 | 实现难度 |
|------|------|---------|
| **Hull Moving Average** | 超低延迟均线，适合短线交易 | 低 |
| **Kaufman Adaptive MA** | 市场效率自适应均线，震荡市自动减速 | 中 |
| **Ichimoku Kinko Hyo** | 一键看支撑/阻力/趋势/动量，A 股技术派核心工具 | 中 |
| **SuperTrend** | ATR 动态止损，A 股最常用跟庄指标之一 | 低 |
| **Parabolic SAR** | 趋势反转点，涨停板交易必备 | 低 |
| **Donchian Channel** | 突破通道，海龟交易法则核心 | 低 |
| **ZigZag** | 波段高低点识别，用于画线/波浪分析 | 中 |

#### 震荡类（高价值）

| 指标 | 用途 | 实现难度 |
|------|------|---------|
| **Stochastic RSI** | RSI 的随机化，更敏感的超买超卖 | 低 |
| **Ultimate Oscillator** | 三周期加权震荡，减少假信号 | 低 |
| **Awesome Oscillator** | 比尔·威廉姆斯的动量检测 | 低 |
| **Fisher Transform** | 将价格转为高斯分布，极致反转信号 | 中 |
| **Connors RSI** | 三因子综合（RSI+连涨连跌+相对强度），均值回归利器 | 中 |

#### 波动率/成交量类

| 指标 | 用途 | 实现难度 |
|------|------|---------|
| **Keltner Channels** | ATR 通道，比布林带更适合 A 股涨跌停 | 低 |
| **Choppiness Index** | 市场方向性强度判断（震荡还是趋势） | 低 |
| **Force Index** | 量价结合的趋势强度 | 低 |
| **Chaikin Money Flow** | 资金流向，A 股最重要的量价指标之一 | 低 |
| **Squeeze Momentum** | 布林带-肯特纳压缩检测，预示大波动 | 中 |

#### 市场结构类

| 指标 | 用途 | 实现难度 |
|------|------|---------|
| **Hurst Exponent** | 市场记忆性量化（趋势市 vs 均值回归市） | 中 |
| **ARIMA** | 时间序列预测，可用于短期价格预测 | 中 |
| **TD Sequential** | Tom DeMark 序列，A 股技术派常用 | 中 |

**移植方案**：创建 `src/indicators/` 包，每个指标一个文件，基类 `Indicator` 提供 `update(value)` + `is_ready` + `current_value`，使用 pandas/numpy 实现滚动计算。LEAN 的 `WindowIndicator` / `BarIndicator` 基类模型值得复制。

---

### 2. K 线形态识别（63 种形态）🔴 最高优先级

LEAN 内置 63 种日本蜡烛图形态检测，每种返回 `+1`=看涨 / `0`=无信号 / `-1`=看跌：

**高价值形态（A 股实战常用）**：

| 形态 | 信号 | 实战价值 |
|------|------|---------|
| **Morning Star / Evening Star** | 早晨之星/黄昏之星，三烛反转 | 极高 |
| **Engulfing** | 吞没形态，双烛反转 | 极高 |
| **Hammer / Hanging Man** | 锤子线/吊颈线 | 极高 |
| **Doji / Dragonfly Doji / Gravestone Doji** | 十字星系列 | 高 |
| **Three White Soldiers / Three Black Crows** | 三白兵/三乌鸦 | 高 |
| **Dark Cloud Cover / Piercing** | 乌云盖顶/刺透形态 | 高 |
| **Harami / Harami Cross** | 孕线/十字孕线 | 高 |
| **Shooting Star / Inverted Hammer** | 射击之星/倒锤子 | 高 |
| **Marubozu** | 光头光脚线 | 中 |
| **Abandoned Baby** | 弃婴形态 | 中（稀有但极强） |
| **Three Inside / Three Outside** | 三线反转 | 中 |

**移植方案**：创建 `src/indicators/candlestick.py`，每个形态一个类继承 `CandlestickPattern`，使用 LEAN 的 `CandleSettings`（体长/影线/位置阈值）配置。使用 pandas 的 `rolling(window=3)` 或 `rolling(window=5)` 实现多烛形态。

---

### 3. 投资组合优化器 🔴 最高优先级

LEAN 有 9 种组合构建方法，我们目前只有 4 种：

| 优化器 | 说明 | 我们已有? |
|--------|------|----------|
| `MaximumSharpeRatio` | 最大化夏普比率 | ✅ 有（mean_variance） |
| `MinimumVariance` | 最小化组合方差 | ❌ 缺 |
| `RiskParity` | 各资产风险贡献相等 | ✅ 有（risk_parity） |
| `BlackLitterman` | 贝叶斯融合市场均衡+主观观点 | ✅ 有（black_litterman） |
| `EqualWeighting` | 等权重 | ✅ 有（equal_weight） |
| `InsightWeighting` | 按 Alpha 信号强度分配 | ❌ 缺 |
| `ConfidenceWeighting` | 按信号置信度分配 | ❌ 缺 |
| `MeanReversion` | 逆向配置（买弱卖强） | ❌ 缺 |
| `SectorWeighting` | 行业等权分配 | ❌ 缺 |

**移植方案**：
- `MinimumVariance`：用 `scipy.optimize.minimize` 最小化 `w^T Σ w`
- `InsightWeighting` + `ConfidenceWeighting`：依赖 `Insight` 数据模型（见系统设计篇）
- `MeanReversion`：计算最近 N 日收益，做空赢家做多输家

涉及文件：`src/backtest/portfolio_optimizer.py`

---

### 4. Alpha 模型集 🟡 高优先级

LEAN 提供开箱即用的 Alpha 信号生成模型：

| 模型 | 逻辑 | 适用 A 股? |
|------|------|-----------|
| `EmaCrossAlphaModel` | 快慢均线交叉→方向信号 | ✅ 极其适用 |
| `MacdAlphaModel` | MACD 金叉死叉 | ✅ 极其适用 |
| `RsiAlphaModel` | RSI 超买>70 做空，超卖<30 做多 | ✅ 适用 |
| `HistoricalReturnsAlphaModel` | 近期收益动量方向 | ✅ 适用 |
| `PairsTradingAlphaModel` | 协整对交易：z-score 触发 | ✅ 适用 |
| `ConstantAlphaModel` | 固定方向信号 | ✅ 适用（基准） |

**移植方案**：创建 `src/alphas/` 包，`AlphaModel` 基类返回 `list[Insight]`：

```python
class AlphaModel(Protocol):
    def update(self, algorithm: "Orchestrator", data: Slice) -> list[Insight]:
        ...
```

每个模型 = 一个类文件，`CompositeAlphaModel` 链式组合多个模型。

---

### 5. 订单类型 + 滑点模型 🟡 高优先级

我们目前只支持市价单 + 固定 0.1% 滑点。LEAN 提供：

**订单类型**：
- `MarketOrder` — 已有
- `LimitOrder` — **A 股最重要**：涨跌停板交易必须用限价单
- `StopMarketOrder` — 止损市价单
- `StopLimitOrder` — 止损限价单
- `TrailingStopOrder` — 移动止损
- `MarketOnOpen` / `MarketOnClose` — 开盘/收盘执行

**滑点模型**：
- `VolumeShareSlippageModel` — 滑点 = priceImpact × (orderSize/barVolume)²，更真实
- `ConstantSlippageModel` — 固定滑点（我们已有 0.1%）
- `MarketImpactSlippageModel` — 基于市值的冲击成本

**移植方案**：创建 `src/orders/`（`Order`, `MarketOrder`, `LimitOrder`, `StopOrder`, `StopLimitOrder`, `TrailingStopOrder`） + `src/slippage/`（`VolumeShareSlippage`, `ConstantSlippage`）。对 A 股回测最重要的两样：限价单 + VolumeShare 滑点。

涉及文件：`src/backtest/engine.py`（`ChinaAEngine`）

---

### 6. 股票筛选模型（Universe Selection）🟡 高优先级

LEAN 的选股模型框架：

| 模型 | 逻辑 | 适用 A 股? |
|------|------|-----------|
| `EmaCrossUniverseSelection` | 按 EMA 交叉幅度排名，选 Top N | ✅ |
| `ScheduledUniverseSelection` | 定时（周/月/季）重新选股 | ✅ |
| `QC500UniverseSelection` | 动量+流动性双层筛选（粗筛 1000→细筛 500） | ✅ 可改造 |
| `FundamentalUniverseSelection` | 基本面条件筛选（PE/ROE/市值等） | ✅ |

**移植方案**：创建 `src/universe/`（`UniverseSelectionModel` 基类返回 `list[Symbol]` + schedule）。A 股版 QC500：粗筛 = 日均成交额 > 5000 万 + 非 ST + 非次新 → 细筛 = 动量排名 Top N。

---

### 7. 数据聚合器（Consolidators）🟢 中优先级

LEAN 将低级别数据聚合成高级别：

| 类型 | 用途 |
|------|------|
| `TradeBarConsolidator` | 分笔→分钟→日线 |
| `RenkoConsolidator` | 砖形图（价格触发，非时间触发） |
| `VolumeRenkoConsolidator` | 成交量砖形图 |
| `Calendar` | 周/月/季定时触发 |

**移植方案**：`TradeBarConsolidator` 用 `pd.DataFrame.resample(rule).agg()` 即可。`RenkoConsolidator` 需自定义循环。适用于高频分钟数据的降采样分析。

---

### 8. 绩效分析套件 🟢 中优先级

LEAN 有 15 种回测绩效分析，我们缺以下：

| 分析 | 说明 | 价值 |
|------|------|------|
| **Monte Carlo 模拟** | Block-bootstrap 重抽样回测收益，检测"运气好"策略 | 高 |
| **危机事件分析** | 8 个历史危机期的最大回撤检测 | 高 |
| **统计显著性** | t 检验判断超额收益是否显著 > 0 | 高 |
| **参数数量检查** | 超参数 > 200 则警告（过拟合风险） | 中 |

**移植方案**：`src/analytics/monte_carlo.py`（`np.random.choice` 分块重抽样）、`src/analytics/crisis_events.py`（A 股版危机日期表：2015 股灾、2016 熔断、2018 去杠杆、2020 疫情、2022 大跌、2024 量化危机）、`src/analytics/significance.py`（`scipy.stats.ttest_1samp`）。

---

## 二、来自 Dexter 的可移植功能

### 1. 技能系统（Skills）🔴 最高优先级

Dexter 最创新的特性：热插拔的分析技能，每个技能是一个 `SKILL.md` 文件（YAML 头 + Markdown 正文），LLM 按需调用。

**Dexter 现有 3 个技能**：

| 技能 | 说明 |
|------|------|
| `dcf-valuation` | 完整 DCF 估值流程：自由现金流历史→增长率→WACC→5 年预测→终值→敏感性分析 |
| `write-memo` | 8 步投资备忘录生成：交易框架→数据收集→情景→DCF→起草→自我批评→HTML 渲染 |
| `x-research` | Twitter 话题研究：查询分解→搜索→关注→综合 |

**移植方案**：

```
src/workflows/
├── types.py          # SkillMetadata, Skill (Pydantic)
├── registry.py       # discover_skills(), get_skill(name)
├── loader.py         # 解析 YAML frontmatter + Markdown body
└── skills/
    ├── dcf_valuation.md   # DCF 估值
    ├── write_memo.md      # 投资备忘录
    ├── sentiment_research.md  # 情绪研究（微博/雪球替代 Twitter）
    ├── peer_comparison.md # 同行对比
    └── sector_deep_dive.md # 行业深度分析
```

投资回报极高：新增分析类型 = 新增一个 Markdown 文件，无需改代码。

---

### 2. 财务数据元工具 🔴 最高优先级

Dexter 的 4 个元工具将 15+ 个子工具统一在一个自然语言接口后：

```
get_financials("compare 茅台 vs 五粮液 revenue growth last 5 years")
  → 内部路由到 get_income_statements("600519","000858", period="annual", limit=5)
  → 格式化输出为紧凑表格
```

**A 股适配子工具**：

| 元工具 | A 股子工具 |
|--------|-----------|
| `get_financials` | 利润表、资产负债表、现金流量表、关键比率（PE/PB/ROE/ROIC）、杜邦分解、营收拆分 |
| `get_market_data` | 股票行情（快照+历史K线）、公司新闻（东财）、北向资金、两融数据、龙虎榜、大宗交易、解禁 |
| `get_sentiment` | 雪球热帖、股吧情绪、互动易问答、研报标题 |
| `stock_screener` | 条件选股（PE<行业均值 & ROE>15% & 市值>100亿 等） |

**移植方案**：创建 `src/finance/meta_tool.py`，用一次小 LLM 调用（DeepSeek Flash）做 NL→子工具→参数 的路由。格式化器用 `rich` 表格替代 Dexter 的标记化格式化器。

---

### 3. 记忆系统 🔴 最高优先级

Dexter 的记忆系统是 AI 研究助手最关键的特性：

- **存储**：Markdown 文件（`MEMORY.md` + 每日 `YYYY-MM-DD.md`）在 `.dexter/memory/`
- **索引**：SQLite FTS5 + 向量嵌入（cosine similarity + keyword 混合搜索）
- **时间衰减** + **MMR 去重**
- **工具**：`memory_search` / `memory_get` / `memory_update`

**移植方案**：

```
src/memory/
├── store.py       # MemoryStore: 读写 .baize/memory/ 目录
├── database.py    # SQLite FTS5 索引管理
├── embeddings.py  # sentence-transformers（本地模型，中文友好，无需 API key）
├── search.py      # 混合搜索：余弦距离 + FTS5 rank + MMR 去重
├── chunker.py     # Markdown → 段落块切分
└── types.py       # MemoryEntry, SearchResult
```

记忆内容可以是：用户偏好（"不喜欢银行股"）、分析观察（"茅台 PE 30 以下通常买入"）、研究结论等。跨会话持久化。

---

### 4. 定时任务系统（Cron）🟡 高优先级

Dexter 的后台 cron 比简单的时间触发器更强大：

- **3 种计划**：`at`（一次性）、`every`（间隔）、`cron`（表达式 + 时区）
- **3 种履行**：`keep`（每次跑）、`once`（一次后停）、`ask`（跑前确认）
- **去重抑制** + **错误阈值**（连续 5 错自动停）
- **活跃时间窗口**（只在特定时段跑）

**A 股适用场景**：
- 每日 15:05 收盘总结
- 每季财报周扫雷
- 价格预警（涨跌停触发）
- 北向资金日报（18:00）
- 打新提醒（9:15）
- 每月组合再平衡（最后交易日）

**移植方案**：`src/cron/` 使用 `apscheduler` + SQLite 状态管理。

---

### 5. 投资备忘录生成 🟡 高优先级

Dexter 的 `write-memo` 技能产生机构级投资报告：

- 8 步工作流（交易框架→数据→情景→DCF→草拟→自批评→HTML→报告）
- Jinja2 模板变量注入（`{{thesis_bullets}}`, `{{scenario_table}}`, `{{risk_table}}`）
- HTML 输出含 CSS 样式

**移植方案**：`src/reporting/memo_renderer.py` + `src/reporting/templates/memo.html`。投资备忘录是投研体系对外展示的第一窗口，结构化报告比终端文本输出有价值得多。

---

### 6. 上下文压缩 🟡 高优先级

Dexter 的三级上下文管理：

- **微压缩**（microcompact）：每轮 LLM 前清理旧工具结果（保留最近 4 个），但保留结构（`tool_call_id`）
- **全压缩**（compact）：用快速模型将大量工具结果压缩为 9 段结构化摘要
- **截断**（truncation）：最后手段，只保留最近消息

**移植方案**：`src/llm/compactor.py`。当诊断/裁决/辩论阶段要传大量分析结果给 LLM 时，先压缩为 5 段摘要（标的基础信息→技术数据→基本面→进展→待解决），避免上下文溢出。

---

### 7. 网络搜索回退链 🟢 中优先级

Dexter 的多提供商回退：先试首选 → 失败则试第二个 → 再失败试第三个 → 全失败则报错。

**A 股版提供商链**：
```
首选: 百度新闻 API (中文财经新闻)
→ 回退: DuckDuckGo (免费，无 API key)
→ 回退: SerpAPI (付费，可靠)
```

**移植方案**：`src/tools/search_providers.py`，`SearchProvider` Protocol，`chain_search(query, providers)` 函数。

---

### 8. 渠道配置文件 🟢 中优先级

Dexter 的 `ChannelProfile` 控制不同输出场景的格式：

```
CLI: 长报告、Markdown 表格、详细分析
微信: 精简结论、无表格、300 字以内
API: JSON 结构化输出
邮件: HTML 富文本、图表嵌入
```

**移植方案**：`src/output/profiles.py`（`CLIProfile`, `WeChatProfile`, `EmailProfile`, `APIProfile`），格式化器变为 profile-aware。

---

## 三、优先级总排序

### 🔴 立即实施（本周即可完成，每项 < 1 天）

| # | 功能 | 来源 | 文件 | 价值 |
|---|------|------|------|------|
| 1 | K 线形态识别（63 种） | LEAN | `src/indicators/candlestick.py` | 技术分析质的飞跃 |
| 2 | 技能系统框架 | Dexter | `src/workflows/` | 新分析类型无需改代码 |
| 3 | 3 个移植技能（DCF/Memo/情绪研究） | Dexter | `src/workflows/skills/` | 立刻可用 |
| 4 | 记忆系统 | Dexter | `src/memory/` | 跨会话知识积累 |
| 5 | 财务元工具 | Dexter | `src/finance/meta_tool.py` | NL→数据一步到位 |

### 🟡 短期（1-2 周）

| # | 功能 | 来源 | 文件 |
|---|------|------|------|
| 6 | 技术指标库（20-30 个核心指标） | LEAN | `src/indicators/` |
| 7 | 4 个 Alpha 模型（EMA/MACD/RSI/动量） | LEAN | `src/alphas/` |
| 8 | 投资备忘录生成 | Dexter | `src/reporting/memo_renderer.py` |
| 9 | 定时任务系统 | Dexter | `src/cron/` |
| 10 | 上下文压缩 | Dexter | `src/llm/compactor.py` |

### 🟢 中期（Phase 2-3）

| # | 功能 | 来源 |
|---|------|------|
| 11 | 投资组合优化器（5 种新方法） | LEAN |
| 12 | 限价单 + VolumeShare 滑点 | LEAN |
| 13 | Universe Selection 模型 | LEAN |
| 14 | 绩效分析套件（Monte Carlo + 危机） | LEAN |
| 15 | 数据聚合器（Renko / 砖形图） | LEAN |

---

## 四、"不借鉴"清单

| 功能 | 来源 | 原因 |
|------|------|------|
| C# 指标体系直接翻译 | LEAN | 用 pandas/numpy 重写更 Pythonic |
| SEC 文件阅读工具 | Dexter | A 股用巨潮公告，非 SEC |
| 期权相关（Delta/Theta/Vega/Gamma） | LEAN | A 股期权市场太小，暂不需要 |
| Twitter/X 情绪研究 | Dexter | 替换为微博/雪球情绪 |
| WhatsApp/群聊渠道 | Dexter | 不适用 |
| React/Ink TUI 组件 | Dexter | 我们用 `rich` 包 |
