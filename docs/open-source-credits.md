# 开源项目参考清单

> 最后更新：2026-07-16 | 参考项目总数：17

---

## 一、核心参考（已融入系统架构）

### 1. ai-berkshire（9.4k★）

| 项目 | https://github.com/xbtlin/ai-berkshire |
|------|----------------------------------------------|
| **借鉴内容** | 四大师方法论（巴菲特/芒格/段永平/李录互相挑战）、7步研究流程、三情景估值、金融严谨性工具（Decimal精确计算、市值验算、交叉验证）、多Agent并行研究模式 |
| **解决的问题** | L1 分析师的基本面深度分析框架——从「看PE/ROE」升级为「看生意本质+护城河+逆向思考+文明趋势」 |
| **融入位置** | `src/routing/l1_analyze.py`、`src/company/` |
| **影响** | 把分析从纯量化升级为「量化+定性」双轨。四大师互相挑战机制确保分析不是单视角的SWOT |
| **不借鉴的部分** | 报告目录结构（reports/按公司名）、Codex prompts兼容层（只聚焦Claude Code） |

### 2. cyberagent（MIT）

| 项目 | https://pypi.org/project/cyberagent/ (`pip install cyberagent`) |
|------|----------------------------------------------------------------|
| **借鉴内容** | **物理瓶颈分析链**（资产定位→物理世界→人类发展→经济学→公司财务→行业龙头）、瓶颈分类（owner/adjacent/derivative/none）、两轴独立判断（瓶颈身份 ≠ 定价位置）、证据分级（Confirmed/Inferred/Weak/NeedsVerification）、Aschenbrenner SA瓶颈阶梯（电力>CoWoS/HBM>裸逻辑）、「诚实标晚了」纪律 |
| **解决的问题** | 传统因子分析（PE/ROE）在科技/制造赛道失效——看不出真正的护城河。瓶颈分析补上了「供应链定位」这个缺失的分析维度 |
| **融入位置** | `src/industry/bottleneck.py`、`src/industry/supply_chain.py`、L1分析师第3维度 |
| **影响** | 对科技/制造标的的分析深度质的提升——能从「这家公司PE贵不贵」升级为「它在AI/新能源供应链的哪一层、是不是卡住了物理瓶颈」 |
| **Phase 2待做** | 接入龙虎榜数据统计验证 playbook 假设 |

### 3. Backtrader（开源回测引擎）

| 项目 | https://github.com/mementum/backtrader |
|------|----------------------------------------|
| **借鉴内容** | Cerebro编排器、Strategy基类、Analyzer分析器、DataFeed抽象、PandasData批量注入 |
| **解决的问题** | 需要一个成熟的Python回测框架，不想从零写撮合引擎 |
| **融入位置** | `src/backtest/engine.py`、`src/backtest/mvp1_strategy.py`、`src/backtest/mvp2_strategy.py` |
| **影响** | 回测引擎的核心依赖。封装了A股专属约束（T+1、涨跌停、交易成本0.23%） |

### 4. AlphaEvo（ZhuLinsen系列）

| 项目 | https://github.com/ZhuLinsen/alphaevo |
|------|---------------------------------------|
| **借鉴内容** | 策略自我进化循环（backtest→reflect→mutate→save→repeat）、AntiFitMetrics（train/val/test分集+年一致性+参数敏感性+复杂度惩罚）、SelfCritic校验器、YAML策略DSL、DataAdapter接口隔离 |
| **解决的问题** | 策略过拟合是量化策略头号杀手。AntiFitMetrics提供了系统性的抗过拟合评估框架 |
| **融入位置** | `src/backtest/`（回测评估标准）、`src/learner/evolution.py`（策略自适应） |
| **影响** | 回测报告不再只看夏普——还要看年一致性、参数敏感性、复杂度惩罚 |

### 5. open-xquant（75★）

| 项目 | https://github.com/xingwudao/open-xquant |
|------|-------------------------------------------|
| **借鉴内容** | 可复现审计流水线（spec→validate→compile→backtest→audit→robustness→report）、假回测拒绝机制（spec_audit + runtime_audit双重校验）、实验管理（oxq experiment add） |
| **解决的问题** | 回测结果不可复现是量化领域的毒瘤。审计流水线确保每次回测可追溯、可复现 |
| **融入位置** | `src/backtest/`（回测审计设计）、计划Phase 2实现 |
| **不借鉴的部分** | Rust实现（我们全Python）、CLI/SDK分工（方向一致但实现不同） |

### 6. LEAN（QuantConnect，10k+★）

| 项目 | https://github.com/QuantConnect/Lean |
|------|--------------------------------------|
| **借鉴内容** | 事件驱动算法框架（`OnData`/`OnOrderEvent`/`OnEndOfDay` 事件模型）、多资产统一抽象（Equity/Options/Futures/Forex/Crypto/CFD）、DataFeed 抽象层（`IDataProvider` + `ISubscriptionDataSource`）、Brokerage 模型（`IBrokerage` 统一接口 — 回测/实盘同一套 API）、Algorithm Portfolio 管理（`SecurityHolding` + `SecurityPortfolioManager`）、Warmup 期（预热数据窗口） |
| **解决的问题** | 事件驱动回测架构的工业级参考——LEAN 是 Github 上最成熟的 C# 开源量化引擎，其 Algorithm→Portfolio→Risk→Execution 管道设计直接影响回测引擎的模块拆分思路 |
| **融入位置** | `src/backtest/engine.py`（事件循环设计）、`src/routing/positioning.py`（组合管理模型）、未来多资产扩展 |
| **不借鉴的部分** | C# 实现（LEAN 主体 C#，我们全 Python）、QuantConnect 云平台依赖、LEAN CLI/Cloud 部署工具链 |

### 7. Dexter（27.3k★）

| 项目 | https://github.com/virattt/dexter |
|------|-----------------------------------|
| **借鉴内容** | 自主金融研究 Agent 架构（任务规划→执行→自检→迭代循环）、智能任务分解（复杂查询→结构化研究步骤）、Self-Validation 自校验机制（检查自身工作并迭代至完成）、Scratchpad 调试日志（JSONL 格式记录 tool_call + LLM summary）、安全护栏（loop detection + step limits 防止失控执行） |
| **解决的问题** | AI 驱动的金融研究 Agent 如何做任务编排——Dexter 的 think→plan→execute→validate→iterate 循环为我们的 orchestrator 管道设计提供了参考范式 |
| **融入位置** | `src/routing/orchestrator.py`（编排管道设计）、Agent 自校验机制、调试日志格式 |
| **不借鉴的部分** | Bun/TypeScript 技术栈（我们全 Python）、美股数据源（我们聚焦 A 股数据源） |

---

## 二、数据层参考

### 6. daily_stock_analysis

| 项目 | https://github.com/ZhuLinsen/daily_stock_analysis |
|------|--------------------------------------------------|
| **借鉴内容** | 数据源策略模式（BaseFetcher + DataFetcherManager）、多源降级（Tushare→Efinance→AKShare→Pytdx→Baostock）、防封禁流控策略、统一数据接口设计 |
| **解决的问题** | 多数据源管理——优先级、降级、故障切换的工程模式 |
| **融入位置** | `src/data/base.py`（DataProvider ABC）、`src/data/aggregator.py`（聚合器） |
| **影响** | 数据聚合层的架构设计直接参考了其策略模式 |

### 7. TradingAgents

| 项目 | https://github.com/TauricResearch/TradingAgents |
|------|------------------------------------------------|
| **借鉴内容** | 多Agent交易系统架构、信号处理管道、结构化Agent输出模式、测试驱动开发（conftest.py） |
| **解决的问题** | 多Agent系统的测试策略——如何确保每个Agent的输出符合预期 |
| **融入位置** | 测试模式参考（pytest + conftest）、Phase 4多Agent编排设计 |

### 7b. TradingAgents-Astock（A 股 fork，主参考）

| 项目 | https://github.com/simonlin1212/TradingAgents-astock |
|------|-----------------------------------------------------|
| **借鉴内容** | 7 Analyst（+政策/游资/解禁）、Bull/Bear + 三方风险辩论、A 股 Trader 约束（T+1/涨跌停/手数）、免费数据源矩阵（mootdx/腾讯/东财/新浪/同花顺）、东财防封节流、LangGraph 拓扑、CSI 300 交易反思、双 LLM 分工、checkpoint 断点续跑 |
| **解决的问题** | 上游面向美股；A 股需要政策市/游资/解禁角色与交易制度硬约束贯穿决策链 |
| **融入位置** | `game_theory/`、`policy/`、`routing/` 辩论式输出、`data/aggregator` 补源与节流、`learner/` 反思校准 |
| **影响** | 把「多 Agent 投研」从通用模板落到 A 股可执行角色与数据；详细分析见 `docs/reference/tradingagents-astock-analysis.md` |
| **不借鉴的部分** | 用辩论结果覆盖军规/L4 硬 BLOCK；默认引入完整 LangGraph 运行时（可先借鉴拓扑思想） |

### 7c. Serenity.skill（白毛股神 / 供应链瓶颈投研）

| 项目 | https://github.com/muxuuu/serenity-skill |
|------|------------------------------------------|
| **借鉴内容** | 热点→系统变化→8 层价值链→稀缺卡点→公司宇宙→证据阶梯→优先研究排序；A 股证据路径（问询函/互动易/环评能评/招投标）；瓶颈 scorecard；失败条件与下一步核验；研究非交易边界 |
| **解决的问题** | 热点主题「全网都在说」时缺少系统筛选：分不清蹭主题与真卡点、缺少证据与失败条件 |
| **融入位置** | `industry/serenity_scorecard.py`、`industry/serenity_workflow.py`、`industry/bottleneck.py`（Serenity 字段）、`routing/diagnosis.py`、formatter/step_output、`.claude/skills/serenity-bottleneck/`、场景四强制格式 |
| **影响** | 与 cyberagent 物理瓶颈链互补：身份分 + 研究优先级双轴；主题扫强制先层后票；详见 `docs/reference/serenity-skill-analysis.md` |
| **不借鉴的部分** | 买卖指令与收益承诺；把社媒 KOL 当最终证据 |

### 7d. GS Quant（高盛量化工具包）

| 项目 | https://github.com/goldmansachs/gs-quant |
|------|------------------------------------------|
| **借鉴内容** | 机构级模块分层（risk / timeseries / backtests / markets / analytics / workflow）、风险度量分层（单票→组合→情景）、时序算子可组合、Session/Context 统一配置、强类型 instrument 边界 |
| **解决的问题** | 个人项目风控/因子/回测容易「函数散落」；需要工业级抽象语言与分层参照 |
| **融入位置** | L4 组合风险语言、`factor_pipeline` 算子化、`backtest/` 分层、配置 Session |
| **影响** | 设计决策级参考；详见 `docs/reference/gs-quant-analysis.md` |
| **不借鉴的部分** | 依赖 Marquee 机构 API 的定价/数据；衍生品全产品线；作为默认运行时重依赖 |

---

## 三、功能层参考

### 8. PanWatch（648★）

| 项目 | https://github.com/TNT-Likely/PanWatch |
|------|--------------------------------------|
| **借鉴内容** | 持仓管理（多账户汇总+成本均价+盈亏百分比）、技术指标共振（MACD/RSI/KDJ同框）、AI评分选股（5Agent自动运行）、通知渠道（Apprise多通道）、APScheduler定时调度 |
| **解决的问题** | Phase 3盯盘模块和通知系统的设计参考 |
| **融入位置** | `src/output/alert.py`、CLI调度 |
| **不借鉴的部分** | React前端Web UI（MVP阶段CLI优先） |

### 9. FinceptTerminal（27.9k★）

| 项目 | https://github.com/Fincept-Corporation/FinceptTerminal |
|------|---------------------------------------------------|
| **借鉴内容** | 宏观数据维度分类（收益率曲线/货币供应/信用条件/金融压力/消费者信心）、公司研究9维度框架（估值/盈利能力/增长/财务健康/动量/效率/股息/规模/波动） |
| **解决的问题** | 因子体系的分类框架——怎么组织几十个因子 |
| **融入位置** | `src/macro/`、`src/factors/` |
| **不借鉴的部分** | C++ Qt6桌面应用架构（太重）、50个服务微服务架构 |

### 10. OpenStock（13.6k★）

| 项目 | https://github.com/Open-Dev-Society/OpenStock |
|------|--------------------------------------|
| **借鉴内容** | 跨源情绪聚合（Reddit/X/News/Polymarket四源统配器+Buzz Score+看涨百分比）、价格提醒系统（ABOVE/BELOW条件+90天过期+5分钟cron检查） |
| **解决的问题** | 情绪信号的多源聚合模式 |
| **融入位置** | `src/sentiment/` |

---

## 四、工程架构参考

### 13. anthropics/financial-services（33k★）

| 项目 | https://github.com/anthropics/financial-services |
|------|--------------------------------------------------|
| **借鉴内容** | Claude Code 金融垂直插件架构、Skill/Command 模块化设计模式、11 数据连接器抽象（Bloomberg/FactSet/CapIQ/Intex/ICE等）、多Agent编排（pitch-agent/gl-reconciler/market-researcher）、Managed Agent Cookbook 模板、7 个垂直插件划分（financial-analysis/investment-banking/equity-research/private-equity/wealth-management/fund-admin/operations） |
| **解决的问题** | 大型金融AI系统如何做模块拆分——不是一个大skill做所有事，而是多个垂直插件各司其职。数据连接器的统一抽象模式 |
| **融入位置** | 整体架构设计：`src/` 目录按功能域拆分（data/doctrine/routing/sentiment/game_theory/backtest/learner）、Claude Code Skill 入口（`.claude/skills/stock-hunter/SKILL.md`）、华泰/国信/AKShare 三源适配器设计 |
| **影响** | 验证了我们的模块化方向是正确的——与 Anthropic 官方的设计理念一致。数据源的 adapter 模式直接参考了其 connector 设计 |

---

## 五、间接参考（未直接融入，但影响了设计思路）

### 11. ai-gold-miner

| 途径 | Claude Code Skill（已安装） |
|------|--------------------------|
| **借鉴内容** | 投资者画像设计（定性画像+定量持仓）、核心仓/交易仓分治、画像匹配校验、Munger 232模型库 |
| **解决的思路** | 「投资系统应该有用户画像约束」——所有建议必须在用户约束范围内 |
| **融入位置** | `src/profile/`（画像加载+匹配）、`src/doctrine/`（军规设计） |

### 12. FinGPT / UZI-Skill

| 途径 | Claude Code Skill（数据校验层参考） |
|------|----------------------------------|
| **借鉴内容** | 多源事实性交叉验证、T0-T3信源标注、数据缺口标注 |
| **解决的思路** | 金融数据不可盲信——必须标注来源、时效、可信度 |
| **融入位置** | `src/data/cross_validator.py` |

---

## 五、各模块借鉴来源速查

| 模块 | 主要参考项目 |
|------|------------|
| **数据聚合层** | daily_stock_analysis、PanWatch、TradingAgents-Astock（A 股数据矩阵/东财节流） |
| **回测引擎** | Backtrader、open-xquant、AlphaEvo、LEAN、GS Quant（抽象分层）、VectorBT |
| **因子体系** | FinceptTerminal、OpenStock、GS Quant（时序算子） |
| **L1 分析师** | ai-berkshire、cyberagent、Serenity.skill（主题→卡点 workflow） |
| **基本面深度分析** | ai-berkshire（四大师、7步研究、三情景估值） |
| **物理瓶颈分析** | cyberagent（瓶颈链、SA阶梯、两轴判定）、Serenity.skill（稀缺层/证据阶梯/scorecard） |
| **博弈论知识库** | cyberagent（瓶颈分类、证据分级）+ 自主设计（15条A股规则）+ TradingAgents-Astock（游资/解禁角色） |
| **军规引擎** | ai-gold-miner（投资者约束设计）+ 自主设计（30条A股专属） |
| **情绪/恐慌套利** | OpenStock（跨源情绪聚合） |
| **多Agent编排** | ai-berkshire、TradingAgents / TradingAgents-Astock、Dexter、DojoAgents |
| **策略进化** | AlphaEvo（自我进化循环+AntiFitMetrics） |
| **测试框架** | TradingAgents（pytest + conftest） |
| **风控/组合风险** | RiskGuard、GS Quant（组合/情景风险语言） |
| **政策/主题研究** | TradingAgents-Astock（政策分析师）、Serenity.skill（主题扫描） |

---

## 六、未借鉴但调研过的项目

| 项目 | 调研结果 | 不借鉴原因 |
|------|---------|-----------|
| **FinGPT** | 轻量级金融LLM框架 | 聚焦NLP；我们不依赖LLM做核心分析 |
| **qlib**（微软） | 量化投资AI平台 | 太重（需要自有数据仓库）；我们不跑高频 |
| **vnpy** | 量化交易系统 | 聚焦实盘交易；我们聚焦分析决策 |

---

## 七、借鉴原则

1. **方法论借鉴 > 代码复制** — 理解其设计思路，用我们的架构重实现
2. **标注出处** — 每个模块的docstring标注参考来源
3. **渐进集成** — Phase 1只集成核心模块，Phase 2-4逐步扩展
4. **尊重许可证** — 所有参考项目均为MIT/Apache 2.0等允许商用许可
