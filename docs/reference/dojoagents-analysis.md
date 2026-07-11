# DojoAgents 参考分析

> 源码：`~/Documents/workspace/DojoAgents-main`
> 分析日期：2026-07-11

DojoAgents 是一个面向个人量化投资的全市场 AI Agent 框架（A 股/美股/港股），定位为"认知型组合代理"：把持仓、行情、基本面、跨市场数据连接成持续推理的 loop。

本文档从**架构设计**和**功能模块**两个维度分析可借鉴到白泽（ai-stock-hunter）的机制。

---

## 一、架构设计借鉴

### 1.1 Agent 编排与通信

| 机制 | 来源文件 | 要点 |
|------|---------|------|
| **Runtime 统一 wiring** | `agent/runtime.py:33-44` | config、agent、session、extension、scheduler、task manager 组装成单一 `Runtime`；`from_config_store()` 是启动入口 |
| **Agent Loop + Tool Bridge** | `agent/loop.py:72-144` | LLM streaming/tool-call 协议 → 内部 `ToolCall`/`ToolResult` |
| **Multi-agent Pool + 工具白名单** | `multi_agent/pool.py:15-62` | 按 `AgentSpec` 懒创建 worker，可配 allow/disallow 工具列表和模型覆盖 |
| **极简编排器 prompt** | `multi_agent/orchestrator.py:8-39` | 编排器只拆子任务，不自己产出分析 |

### 1.2 任务护栏与状态机

| 机制 | 来源文件 | 要点 |
|------|---------|------|
| **TaskHarness 抽象** | `agent/harness.py:129-167` | 匹配请求、拦截/修复 tool call、验证进度、生成恢复 prompt |
| **Portfolio 写操作拦截** | `agent/harnesses/portfolio.py:73-200` | 阻止只读 run 修改组合 — 对应"仅 SignalWriter 可写" |
| **PortfolioEval 可证伪验证** | `agent/harnesses/portfolio_eval.py:7-200` | agent 显式提交 `success_criteria`，再调 `portfolio_read_detail` 验证 |
| **ToolCallGuardrailController** | `agent/guardrails.py:66-180` | 项目级硬拦截（terminal、portfolio_write_*） |

### 1.3 Memory 与 Skill

| 机制 | 来源文件 | 要点 |
|------|---------|------|
| **MemoryProvider 协议** | `memory/provider.py:6-29` | 统一接口：initialize / prefetch / sync_turn / save_memory / retrieve_memory |
| **Composite MemoryManager** | `memory/manager.py:8-71` | 聚合多 provider、fan-out、prompt 注入 |
| **Skill-summary memory** | `memory/skill_summary.py:8-62` | 成功会话 → `~/.dojo/skills/generated/SKILL.md` |
| **Skill loader** | `skills/manager.py:15-161` | YAML frontmatter + 平台/工具需求过滤 + 懒加载 catalog |

### 1.4 Plan 引擎与配置

| 机制 | 来源文件 | 要点 |
|------|---------|------|
| **PlanExecutionEngine** | `planning/engine.py:12-91` | DAG + 死锁保护（`max_iterations = len(steps) * 2 + 1`） |
| **Typed frozen ConfigStore** | `config/models.py:11-217` + `config/loader.py:282-344` | 全部配置 frozen dataclass，快照缓存，`redacted()` 脱敏 |
| **Plugin registry + hooks** | `plugins/registry.py:73-299` | 自动发现、Claude 风格 hooks 映射 |

### 1.5 Quant 工作流原语

| 类型 | 来源文件 | 要点 |
|------|---------|------|
| **QuantContext** | `quant/context.py:7-24` | market / symbols / timeframe / currency / data_freshness |
| **RiskSnapshot** | `quant/risk.py:7-10` | summary + metrics dict |
| **ArtifactRef / AnalysisResult** | `quant/workflow.py:7-28` | 分析结果引用链 + provenance |

---

## 二、功能模块复用

### 2.1 多平台通知网关 (`gateway/adapters/`)

DojoAgents 实现了完整的多平台消息适配器层（`gateway/adapters/base.py:99` 的 `BaseGatewayAdapter`）。

| 适配器 | 文件 | 能力 | 白泽可复用场景 |
|--------|------|------|---------------|
| **微信** | `gateway/adapters/wechat.py` | iLink 协议、轮询、上下文 token、消息去重、1900字分块 | A 股预警推送 |
| **飞书** | `gateway/adapters/feishu.py` | Webhook 消息发送 | 投资笔记/日报/周报 |
| **Telegram** | `gateway/adapters/telegram.py` | Bot 轮询 | 个人盯盘通知 |
| **企业微信** | `gateway/adapters/wecom.py` | Webhook 发送 | 团队协作 |
| **Slack / Discord** | `gateway/adapters/slack.py` `discord.py` | 标准消息发送 | 社区/海外用户 |

> 白泽当前 `src/output/alert.py` 只有基础通知。微信适配器（含 iLink 协议）是最复杂的平台实现，DojoAgents 提供了完整、测试过的版本。

### 2.2 组合绩效与风控指标 (`dashboard/services/portfolio_performance.py`)

纯函数，可直接移植：

| 函数 | 位置 | 能力 |
|------|------|------|
| `compute_risk_stats(nav)` | `:12` | Sharpe 比率、年化波动率、最大回撤、Calmar 比率 |
| `rebase_nav(values)` | `:49` | NAV 序列归一化到 100 |
| `build_market_performance(...)` | `:129` | 成交订单 + K线 → NAV 曲线 + 基准对比 |
| `build_candidate_index_performance(...)` | `:102` | 候选票等权指数 vs 基准 |

> 白泽 `src/backtest/analyzer.py` 有类似指标，但 DojoAgents 版更简洁且包含完整的 NAV 构建 pipeline（订单 → 前向填充 → NAV → 基准对比）。

### 2.3 模拟订单执行引擎 (`dashboard/services/portfolio_order_execution.py`)

完整的纸上交易订单撮合逻辑：

| 函数 | 位置 | 能力 |
|------|------|------|
| `try_fill_order()` | `:317` | 限价单验证、K线日内价格范围撮合、滑点模拟 |
| `process_pending_orders()` | `:396` | 批量处理挂单，按时间顺序 + 现金约束 |
| `aggregate_positions()` | `:418` | 成交订单 → 持仓聚合 + 成本基计算 |
| `replay_market_balance()` | `:787` | 回放到任意日期的现金+持仓状态 |
| `sanitize_invalid_filled_orders()` | `:650` | 清理违反现金/股数约束的订单 |
| `evaluate_order_fill_failure()` | `:183` | 诊断订单为什么成交失败 |

### 2.4 行业板块分析 (`dashboard/services/`)

| 功能 | 文件 | 要点 |
|------|------|------|
| 板块涨跌榜 | `market_sector_lead.py:51` | 每市场板块涨跌榜 + 成分股数 + 样本票 |
| 板块热力图 | `market_sector_lead.py:177` | 单市场热力图 |
| 跨市场对比 | `market_sector_lead.py:207` | A/美/港板块对比 |
| 板块指数曲线 | `sector_scope_performance.py:245` | 市值加权的 L1/L2/L3 板块指数 |
| 三级行业树 | `sector_store.py:125` | 中英文双语匹配 |
| 股票→板块映射 | `stock_sector_store.py` | 反向映射 |

### 2.5 内置量化分析任务 (`tasks/built_in/`)

#### 板块异动归因 (`sector-attribution/TASK.md` + `contract.yaml`)

工作流：识别异常板块（涨跌幅 ≥ 3% / 涨跌榜 Top 3 / 跨市场共振 / 大市值 ≥ 1.5%）→ 搜索新闻 → 结构化 JSON 输出。

白泽可结合 `src/industry/` + `a-stock-data` skill 数据源，自动生成每日板块异动归因报告。

#### 全球市场异动事件分类 (`event-trigger/TASK.md` + `contract.yaml`)

读入板块归因输出 → 合并新闻为独立事件 → 归入 15 个类别：

| 类别 | 说明 |
|------|------|
| `geo_military` | 地缘/军事 |
| `macro_data` | 宏观数据 |
| `corporate_earnings` | 企业盈利 |
| `central_bank` | 央行/利率 |
| `trade_tariff` | 贸易/关税 |
| `regulatory` | 监管/法律 |
| `energy_commodity` | 能源/大宗 |
| `tech_disruption` | 技术颠覆 |
| `financial_stress` | 金融压力 |
| `public_health` | 公共卫生 |
| `climate_disaster` | 气候/灾害 |
| `industry_policy` | 产业政策 |
| `market_structure` | 市场结构 |
| `sovereign_credit` | 主权信用 |
| `other` | 其他 |

白泽可将此分类体系作为 `src/routing/attribution.py` 的归因模板。

### 2.6 DuckDuckGo 搜索与网页抽取 (`tools/web_searcher.py`)

| 功能 | 能力 |
|------|------|
| `web_search` | DuckDuckGo HTML 抓取搜索 |
| `web_extract` | 下载网页 → 去 HTML → 截断（含 URL 安全检查：内网 IP、密钥参数屏蔽） |

白泽 `src/information/sources/` 对各平台有专门抓取，但缺通用搜索+网页抽取工具。

### 2.7 其他可参考模块

| 功能 | 文件 | 要点 |
|------|------|------|
| 市值加权配置 | `portfolio_allocation.py:93` | 按持仓市值权重分配资金 |
| 市值/PE 聚合 | `market_stats.py:21` | 加权 PE、总市值 |
| 板块上榜筛选 | `sector_movers_ranking.py:9` | 按最小成分股数过滤 |
| K线对齐工具 | `portfolio_performance.py` | `_forward_fill_on_or_before()`、`_align_series_to_dates()` |
| 中文意图检测 | `portfolio_task_intent.py:55` | 中英文正则匹识别清算/建仓意图 |
| Dojo SDK 数据网关 | `dojo_data_gateway.py:110` | 17 个 API 端点类型化封装（A/美/港行情/K线/财务/事件/行业/外汇） |

> ⚠️ Dojo SDK 数据网关依赖 `dojo` Python 包。若不引入 Dojo SDK 作为数据源，此模块仅作为多源网关的架构参考。

---

## 三、复用优先级排序

按对白泽的价值排序：

| 优先级 | 模块 | 复用方式 | 理由 |
|--------|------|---------|------|
| **P0** | 通知推送（微信/飞书/Telegram） | 直接移植 | `alert.py` 有内存告警但零推送通道 |
| **P0** | 通用网页搜索 | 直接集成 | A 股特化搜索完备，缺开放互联网搜索 |
| **P0** | 订单撮合引擎（限价单/部分成交/滑点） | 参考实现 | `paper_trading/` 只有 buy/sell + 参考价成交 |
| **P1** | 板块热力图/轮动检测 | 参考实现 | `industry/` 有深度学习框架但缺每日排行/热力图 |
| **P1** | 组合绩效指标（Calmar/Sortino/VaR/Info Ratio） | 移植纯函数 | `backtest/analyzer.py` 有基础指标，缺标准风险指标 |
| **P2** | 事件 15 类分类体系 | 归因模板 | `AttributionEngine` T0-T3 已完善，分类体系可增强 |
| **P2** | 板块异动归因工作流 | 参考逻辑 | 可对接白泽数据源 |
| **P2** | 飞书/Telegram 适配器 | 按需移植 | 需要对应平台时才用 |
| **P2** | 事件归因定时扫描 | 参考实现 | 白泽 cron 已完善，自动化触发非刚需 |
| **P3** | NAV 构建 pipeline | 参考架构 | 白泽已有类似链路 |
| **P3** | 市值加权配置 | 参考算法 | 简单，随手可写 |
| **P3** | ConfigStore 冻结/嵌套/热加载 | 架构参考 | 当前 env-var dataclass 够用 |
| **P3** | Plan 引擎 / Harness | 架构参考 | 与 Strands 耦合，需适配 |

---

## 四、P1 差距详细分析

### 4.1 板块热力图 / 轮动检测

**白泽现有** (`src/industry/`)：

| 模块 | 文件 | 能力 |
|------|------|------|
| `SectorClassifier` | `classifier.py` | 申万一/二级分类（28 行业），东方财富 fallback |
| `SectorResearchReporter` | `research.py` | 6+1 步深度学习框架，综合评分 0-100 |
| `CompetitionAnalyzer` | `competition.py` | 波特五力、CR5、HHI、壁垒 |
| `SectorValuationFramework` | `valuation.py` | PE/PB 分位数、行业适配估值法 |
| `SupplyChainDeepMapper` | `supply_chain.py` | 供应链映射 |
| `BottleneckAnalyzer` | `bottleneck.py` | 实体瓶颈 OWNER/ADJACENT/DERIVATIVE/NONE |

**白泽缺少**：

| 能力 | DojoAgents 来源 | 白泽对接方案 |
|------|---------------|------------|
| 每日板块涨跌排行 | `market_sector_lead.py:51` `build_market_sectors()` | 新增 `src/industry/daily_ranking.py`，用 mootdx 板块数据 + 申万分类 |
| 板块热力图 | `market_sector_lead.py:177` `compute_market_sector_lead()` | 基于排行生成矩阵，rich/matplotlib 输出 |
| 跨市场对比（A/美/港） | `market_sector_lead.py:207` `compute_all_market_sector_leads()` | 初期仅 A 股，后续扩展 |
| 板块轮动检测 | 动量切换识别（领先板块变化 > X%） | 新增 `detect_rotation()` 对比连续 N 日排行变化 |
| 市值加权板块指数 | `sector_scope_performance.py:245` `compute_sector_scope_performance()` | 白泽有成分股数据可直接算 |
| 中英双语板块匹配 | `sector_store.py:125` `SectorStore.find_resolved_path()` | 非刚需，按需加 |

### 4.2 组合绩效指标

**白泽现有** (`src/backtest/analyzer.py`)：

| 分析器 | 已有指标 |
|--------|---------|
| `SharpeAnalyzer` | 年化 Sharpe、年化收益、年化波动率、日均收益 |
| `DrawDownAnalyzer` | 最大回撤（已恢复/进行中）、平均回撤 |
| `TradeAnalyzer` | 总交易数、胜率、平均盈亏、盈亏比、最大连胜/连亏 |
| `SQNAnalyzer` | System Quality Number (Van Tharp) + 质量分档 |
| `TimeReturnAnalyzer` | 逐 bar 收益、累计收益、正/负日计数 |

**白泽缺少**（DojoAgents `portfolio_performance.py` 提供）：

| 指标 | 公式/含义 | 优先级 | 实现位置建议 |
|------|----------|--------|------------|
| **Calmar Ratio** | CAGR / max_drawdown | 高 | `analyzer.py` 新增 `CalmarAnalyzer` |
| **Sortino Ratio** | (收益-无风险利率) / 下行标准差 | 高 | 新增 `SortinoAnalyzer` |
| **信息比率** | 超额收益 / 跟踪误差 (vs 基准) | 高 | 新增 `InfoRatioAnalyzer` |
| **VaR (历史/参数/蒙特卡洛)** | 置信度 α 下的最大损失 | 中 | 新增 `VaRAnalyzer` |
| **CVaR** | 超过 VaR 的尾部期望损失 | 中 | 同上 |
| **Alpha / Beta** | CAPM 回归分解 | 中 | 新增 `CAPMAnalyzer` |
| **Up/Down Capture** | 上涨/下跌市相对基准的捕获率 | 低 | 可选 |
| **滚动 Sharpe / 回撤** | 时间序列滚动窗口指标 | 低 | 可选 |
| **偏度 / 峰度** | 收益分布的形态指标 | 低 | 可选 |

> DojoAgents 的 `compute_risk_stats(nav)` 是纯函数（`portfolio_performance.py:12`），输入 NAV 序列即输出 Sharpe/波动率/回撤/Calmar，可直接移植核心逻辑。

---

## 五、注意事项

1. **无真实历史回测**：DojoAgents 只有组合诊断、模拟 watchlist 和绩效缓存。回测设计仍以 VectorBT 为主参考。
2. **Dojo SDK 耦合**：数据网关、板块存储等依赖 `dojo` Python 包。移植到白泽需替换为 mootdx/AKShare/东财等已有数据源。
3. **Strands 框架耦合**：Agent loop、harness 等核心与 `strands-agents` 框架紧耦合。参考其设计模式而非代码。
4. **多 Agent 非默认开启**：`MultiAgentConfig.enabled` 默认 `False`，编排器是 prompt + `delegate_task`，无复杂共识机制。
5. **Memory provider 吞异常**：`LocalMemoryProvider` 等 silent pass 了 IOError/Exception，生产环境需要显式错误处理。
