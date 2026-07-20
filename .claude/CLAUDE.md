# 白泽 (Baize) — A 股智能投资决策系统

面向 A 股投资者的全栈量化分析管道。覆盖选股、择时、风控、回测全链路。

## 架构概览

```
CLI (src/cli.py) → Orchestrator → 军规 → 准入检查 → 多维诊断 → 综合裁决 → 仓位调度 → 风控执行
                                      ↑ Phase 3 注入: MacroRegime / Northbound / EarningsRevision / TopicLifecycle
```

## 核心原则

- **DTO 优先**：跨层数据使用 `@dataclass`，不用裸 dict
- **完整 Workflow**：单票分析必须跑全 军规 → 准入检查 → 宏观/Alpha → 多维诊断 → 质量审查 → 博弈论 → 投资思维模型 → 综合裁决 → 仓位调度 → 风控执行 → 投资者校验，禁止跳过阶段
- **护栏内置**：每个分析输出携带 `source_citations` + `confidence` + `data_freshness`
- **数据溯源三要素**：每个 citation 必须标注 `tier`（primary/secondary/tertiary）与 `nature`（fact/interpretation/speculation）
- **质量加权**：多维诊断/综合裁决阶段必须按数据新鲜度、来源级别、事实/推测性质对评分和 confidence 进行加权或降权
- **[UNSOURCED]**：无法验证的声明必须标记
- **[DATA_GAP]**：数据源缺失/失败必须显式说明并下调对应维度权重
- **[STALE]**：新闻事件超过时效限制（>12h）必须排除出当日归因，仅可作为背景铺垫
- **[SPECULATION]**：推测性数据必须显式标注，置信度 ≤ 0.5
- **时效性校验**：所有归因分析前必须对每条信息做时效性检查，禁止用过期新闻解释当日涨跌
- **交叉验证**：关键盘面数据 ≥ 2 个独立来源，单源标注 `⚠️ 单源未验证`
- **分制统一**：评分 0-100，信心度 0.0-1.0，情绪 -1.0 到 +1.0
- **仅 SignalWriter 可写**：所有分析 Agent 只读，仅信号输出 Agent 有写权限
- **数据源优先级**：华泰(HT_APIKEY) > 国信(GS_API_KEY) > 腾讯(免费) > mootdx(TCP) > AKShare
- **可移植优先**：不要依赖本地项目记忆/记录来约束行为，所有配置与规则写入代码仓库，确保他人 fork 后能达到同等效果

详见 `.claude/rules/guardrails.md` 与 `docs/data-provenance.md`。

## 模块地图

| 层 | 模块 | 职责 |
|----|------|------|
| 路由 | `routing/orchestrator.py` | 全链路编排 |
| 路由 | `routing/admission.py` | 准入检查（原 L0 Gate） |
| 路由 | `routing/diagnosis.py` | 多维诊断（原 L1 Analyze） |
| 路由 | `routing/verdict.py` | 综合裁决（原 L2 Judge） |
| 路由 | `routing/positioning.py` | 仓位调度（原 L3 Trade） |
| 路由 | `routing/risk_control.py` | 风控执行（原 L4 Risk） |
| 军规 | `doctrine/` | 31 条军规（4 级严重度） |
| 数据 | `data/aggregator.py` | 多源聚合器（华泰/国信/腾讯/mootdx/AKShare） |
| 数据 | `data/factor_pipeline.py` | 因子计算管道（PE/ROE/北向） |
| 数据 | `data/earnings_revision.py` | 盈利修正因子 |
| 宏观 | `macro/monetary_credit.py` | 货币-信用双象限框架 |
| 行业 | `industry/bottleneck.py` | 实体瓶颈分析 + Serenity 研究轴字段 |
| 行业 | `industry/supply_chain.py` | 供应链映射 |
| 行业 | `industry/serenity_scorecard.py` | 研究优先级打分（与身份分正交） |
| 行业 | `industry/serenity_workflow.py` | 先层后票 DTO / 证据映射 / 输出契约 |
| 博弈 | `game_theory/` | 主导玩家/席位/北向/拥挤度 |
| 政策 | `policy/` | 政策 NLP + 跟踪 |
| 信息 | `information/` | 主题管理/互动易/速度监控 |
| 情绪 | `sentiment/` | 市场情绪/恐慌套利 |
| 回测 | `backtest/` | 策略回测/优化/比较 |
| 学习 | `learner/` | 反馈/进化/校准 |

## Skill 参考

| Skill | 用途 |
|-------|------|
| `stock-hunter` | 顶级入口 |
| `admission` | 准入检查 |
| `diagnosis` | 多维诊断 |
| `verdict` | 综合裁决 |
| `positioning` | 仓位调度 |
| `risk-control` | 风控执行 |
| `doctrine` | 31 条军规 |
| `game-theory` | 博弈论分析 |
| `macro-monitor` | 宏观货币信用监控 |
| `policy-tracker` | 政策跟踪与 NLP |
| `sentiment-analysis` | 市场情绪分析 |
| `topic-manager` | 主题生命周期管理 |
| `idea-generation` | 选股筛选预设 |
| `earnings-analysis` | A 股财报分析 |
| `sector-research` | 行业与供应链研究 |
| `serenity-bottleneck` | Serenity 先层后票/卡点挑战/研究优先级 |
| `backtest-engine` | 策略回测 |
| `stock-attribution` | 个股涨跌归因（3阶段强制workflow） |

## CLI

> ⚠️ macOS 无 `python` 命令，必须用 `.venv/bin/python` 或先 `source .venv/bin/activate`。

```bash
# macOS：使用 venv Python
.venv/bin/python -m src <command> [args]

# 或激活 venv 后直接用 python（CI/其他平台）
python -m src <command> [args]

# 核心分析
analyze <code>     # 全链路分析
diagnose <code>    # 一键诊断（小白入口）
alpha <code>       # Alpha Lens 三维评估
alpha-scan         # 高 Alpha 股票扫描
scan --preset <p>  # 全市场选股扫描

# 市场监控
market             # 大盘市场全景快照 (美股隔夜 + 情绪 + 宏观)
macro              # 宏观快照
sentiment          # 情绪信号检测
game-theory        # 博弈论概览
search-news <q>    # 金融资讯搜索
screen <conds>     # 条件选股

# 盯盘 & 预警
sweep              # 自选股扫雷
alert watch-add    # 加入自选股
attribute <code>   # 个股涨跌归因
alert list         # 查看自选股

# 交易 & 风控
backtest           # 运行回测
paper-trade        # 模拟交易管理
trade-track        # 交易追踪（凯利）

# 学习 & 进化
evolution <sub>    # 策略进化（10 个子命令）
calibrate          # 置信度校准
learn report       # 学习报告
profile            # 用户画像
preference         # 投资者偏好管理
feedback add       # 添加交易反馈
```

## 用户交互 Workflow 调度（强制）

当用户提出以下四类请求时，必须按对应的完整 workflow 执行，**禁止跳过任何阶段**。初步筛选只能产生候选，最终结论必须基于管道打分。

### 场景一：荐股（有主题 / 无主题）

**触发词**: 推荐股票、选股、荐股、有什么票可以买、帮我挑几支、适合建仓、现在买什么

**有主题选股**（如"国产AI算力扩容方向推荐几支股票"）：

| 阶段 | 执行模块 | 方式 |
|------|---------|------|
| 1. 信息搜集 | `last30days-cn` + `topic-manager` + `sector-research` + `policy-tracker` | 并行 |
| 2. 数据初筛 | `a-stock-data` 拉行情/财务 → `admission` 批量过滤 → `doctrine` 扫雷 | 串行 |
| 3. 管道验证 | 对每支候选**并行**跑 `diagnose <code> --no-t0`（Alpha搜索跳过日内时机）→ 横向排名（管道分 **+** `research_priority_score`） | 并行 |

**无主题泛选股**（如"推荐几支适合现在建仓的股票"）：

| 阶段 | 执行模块 | 方式 |
|------|---------|------|
| 1. 偏好确认 | AskUserQuestion（风格/周期/估值容忍度/市值/行业）→ `idea-generation` 匹配预设 | 串行 |
| 2. 全市场扫描 | CLI `scan --preset` / `alpha-scan` → `admission` 批量过滤 | 串行 |
| 3. 管道验证 | 对 Top N **并行**跑 `diagnose <code>`（含T+0，这是建仓判断）→ 横向排名（管道分 **+** 研究优先级） | 并行 |

> ⚠️ **T+0 使用规则**：Alpha 搜索/选股用 `--no-t0` 跳过日内噪音；**建仓判断/买入决策必须保留 T+0**（默认行为）。
> ⚠️ **阶段三不可跳过**。PE 低≠值得买，PE 高≠不能买。管道暴露 Alpha 空间、叙事阶段、数据质量、博弈分歧、技术面信号。
> ⚠️ **有主题时阶段 1 先输出层排名**，阶段 3 公司表用五列（卡住的环节/排序原因/证据/风险）；研究优先级分与管道分并列、互不覆盖。

### 场景二：个股涨跌归因

**触发词**: XX股票为什么涨停/跌停/大涨/大跌、XX涨跌原因

**强制使用 `stock-attribution` skill**，该 skill 内嵌完整 3 阶段 workflow + CHECKLIST + 强制输出格式。

| 阶段 | 执行模块 | 方式 |
|------|---------|------|
| 0. 启动引擎 | `python -m src attribute <code>` — AttributionEngine 自动并行搜集 Phase 1 数据，生成 T0-T3 分级 + QualitySummary | 自动 |
| 1. 信息搜集 | 审查引擎输出的 `raw_data_points` → `last30days-cn`（搜个股相关新闻/传闻）+ `policy-tracker`（行业政策）+ `a-stock-data`（龙虎榜/北向/大宗交易/融资融券/公告） | 并行 |
| 2. 多维归因 | `macro-monitor`（宏观背景）+ `sector-research`（板块联动）+ `sentiment-analysis`（情绪状态）+ `topic-manager`（主题生命周期）+ 资金面分析 + T+0 技术面 | 并行 |
| 3. 因果推断 | **信息源质量检查**（T0-T3分级/时效性校验/STALE排除/交叉验证）→ macro event causality chain（8条传导通道）→ 主因→次因→噪音 排序 → 区分事实/解读/推测 → **强制输出 `📋 信息源质量总览` + `归因权重` 表** | 串行 |

> ⚠️ **Phase 3 信息源质量检查必须在归因之前完成。** 新闻事件 > 12h 标记 `[STALE]` 并排除出主要归因。输出必须包含 guardrails.md 强制格式。详见 `stock-attribution` skill CHECKLIST。

### 场景三：大盘涨跌归因

**触发词**: 今天A股为什么大跌/大涨/波动、大盘怎么了、市场暴跌原因

| 阶段 | 执行模块 | 方式 |
|------|---------|------|
| 1. 信息搜集 | `macro-monitor` + `sentiment-analysis` + `policy-tracker` + `last30days-cn` + 东财全球资讯（7×24快讯） | 并行 |
| 2. 结构分析 | 行业板块排名 + 北向资金 + 涨跌家数 + 成交量 + 涨停/跌停池 | 并行 |
| 3. 因果推断 | **信息源质量检查**（T0-T3分级/时效性校验/STALE排除/交叉验证）→ macro event causality chain（8通道）→ 区分触发因素/放大机制/噪音 → 对标历史 | 串行 |
| 4. 应对建议 | 情绪极端→恐慌套利 / 政策驱动→持续性评估 / 流动性冲击→央行窗口 | 串行 |

> **数据基础**: 运行 `python -m src market` 可直接获取 Phase 1 所需的全部数据（美股隔夜 + A 股市场情绪 + 宏观货币信用象限），无需手动分别运行 macro + sentiment 再拼接。

### 场景四：主题分析 / 单票深度分析

**4a. 纯主题分析**（不一定要荐股）:

**触发词**: 分析XX主题/赛道/板块/概念、用 Serenity 方式看、产业链卡点、深度调研XX

| 阶段 | 执行模块 | 方式 |
|------|---------|------|
| 1. 信息搜集 | `last30days-cn` + `topic-manager` + `sector-research` + `policy-tracker` + A 股证据 checklist（公告/问询函/互动易/招投标/环评） | 并行 |
| 2. 量化分析 | `a-stock-data` 拉代表标的行情/估值 → 行业板块排名 → 北向/融资融券；建候选宇宙（深扫 ≥20） | 串行 |
| 3. 综合输出 | **Serenity 强制格式**（`serenity-bottleneck` skill） | 串行 |

> ⚠️ **阶段三强制格式（先层后票）** — 禁止直接甩热门 ticker 列表：
> 1. 开场：`先排产业链层级，再排公司…`
> 2. **层排名表**（≥3 层）→ **公司五列表**（卡住的环节/为什么排这里/证据/主要风险）
> 3. **≥1 条降级热门方向** + 失败条件 + 下一步核验
> 4. 深扫标准：≥25 信源且 ≥20 候选；否则标「初扫」+ DATA_GAP  
> 代码：`format_theme_scan_report` / `validate_theme_scan_completeness`

**4b. 单票深度分析**（建仓判断）:

**触发词**: XX股票现在值得建仓吗、XX股票能买吗、分析一下XX、挑战XX是不是核心供应商

直接触发 `diagnose <code>`（默认含 T+0，建仓判断必须评估日内时机）。**禁止传 `--no-t0`**。  
输出必须含 **卡点挑战（Serenity）** 块：卡住的环节 / 研究优先级分 / 失败条件 / 下一步核验（非买卖指令）。

### 场景五：持仓/自选股信息记录（强制）

**触发词**: 我持有/买入/卖出/加仓/减仓了XX股票、我的持仓、我有XX股、成本价XX、自选股加了XX、我的股份

**触发即执行，不等用户追问"记了吗"。**

| 信息类型 | 写入目标 | 关键字段 |
|---------|---------|------|
| 持仓（代码+方向+数量+成本价） | `data/positions.json` | symbol, direction, entry_price, quantity, name, stop_price |
| 自选股（代码+名称） | `data/watchlist.json` | symbol, name, stop_price, alert_above |
| 能力圈变更（行业熟悉度变化） | `data/portfolio.yaml` | circle_of_competence |

> ⚠️ **主动记录**：用户告知上述信息时，立即写入对应文件，不需要先问"要记录吗"。写入后简要告知写入了哪个文件。

### 管道验证教训（2026-07-08）

对国产AI算力主题的5支候选标的，初步 PE 对比判断与管道评分出现了系统性偏差：

| 标的 | PE | 初步判断 | 管道评分 | 偏差根因 |
|------|-----|:---:|:---:|------|
| 润泽科技 | 25x | 推荐 | 36 REDUCE | 数据质量0.55/日内-35/能力圈外 |
| 浪潮信息 | 45x | 推荐 | 51 HOLD | 价值仅25/涨停日/无Alpha |
| 中际旭创 | 85x | 推荐 | 60 ADD | ROE 66.5%驱动/Alpha正贡献 |
| 澜起科技 | 120x | 推荐 | 41 HOLD | CONSENSUS降权/PB-ROE偏离746% |
| 沪电股份 | 58x | 推荐 | 30 REDUCE | CROWDED乘数0.7/四大师polarized |

结论：PE 对比产生的初步判断有 80% 的误判率。**必须跑完管道再下结论。**

## 参考项目

设计决策、风控机制、回测逻辑、Agent 编排、产业链研究时，优先查阅以下参考项目。重点借鉴其**业务逻辑设计**而非技术架构。详细分析见 `docs/reference/`。

| # | 项目 | 类型 | 主借鉴面 | 详细分析 |
|---|------|------|---------|---------|
| 1 | RiskGuard | 本地 | 风控规则 / 仓位 / 熔断 | [分析](docs/reference/riskguard-analysis.md) |
| 2 | VectorBT | 本地 | 回测仿真 / 交易视角 / 回撤 | [分析](docs/reference/vectorbt-analysis.md) |
| 3 | DojoAgents | 本地 | Agent Runtime / Harness / Memory | [分析](docs/reference/dojoagents-analysis.md) |
| 4 | Serenity.skill | 本地+GitHub | 供应链瓶颈 / 证据链 / 主题扫描 | [分析](docs/reference/serenity-skill-analysis.md) |
| 5 | GS Quant | 本地+GitHub | 机构级风险 / 时序 / 回测抽象 | [分析](docs/reference/gs-quant-analysis.md) |
| 6 | TradingAgents-Astock | 本地+GitHub | A 股多 Agent 辩论 / 数据源 / 角色 | [分析](docs/reference/tradingagents-astock-analysis.md) |
| 7 | Investment-News | 本地+GitHub | 全球产业链资讯看板 / RSS 多源聚合 / AI 摘要管道 | [分析](docs/reference/investment-news-analysis.md) |
| 8 | go-stock | 本地+GitHub | AI Agent 多模式 / 工具分组路由 / MCP+Skill 扩展 | [分析](docs/reference/go-stock-dev-analysis.md) |
| 9 | OpenStock | 本地+GitHub | Next.js 全栈参考 / Inngest 后台作业 / Finnhub 集成模式 | [分析](docs/reference/openstock-analysis.md) |
| 10 | worth-buy-stocks | 本地+GitHub | 分层评分引擎 / SQLite 缓存架构 / cache-only 回测 / Agent 契约门禁 | [分析](docs/reference/worth-buy-stocks-analysis.md) |

## 开发工作流

- **测试**：`pytest tests/`（类级 Test* 命名 + 方法级 test_* 命名）
- **新增数据源**：实现 `src/data/base.py` 的 `DataProvider`，在 `aggregator.py` 注册
- **新增路由阶段**：在 `__init__.py` 导出 + `orchestrator.py` 的 `run()` 挂接
- **Commit**：`<type>: <description>`（feat/fix/refactor/docs/test/chore）
- **数据新鲜度**：行情 5min / 因子 1h / 基本面 24h / 主题 12h
- **自动提交**：完整实现一个功能或 fix 解决问题后，按以下流程自动提交并推送：
  1. 运行 `/code-review` 审查代码
  2. 发现的问题自动修复
  3. 修复后重新验证（测试通过）
  4. 调用 `/gcp` 提交并推送
  无需等待用户确认，直接执行。
- **报错自愈（强制）**：任何 Bash 命令、Python 脚本、管道命令执行报错（exit code ≠ 0），必须：
  1. 分析错误原因（语法错误/数据缺失/边界条件/API变更/网络超时）
  2. 自动修复代码后重新执行
  3. 修复 3 次仍失败 → 报告根因 + 影响范围 + 给用户的替代方案
  4. 常见模式防御：
     - `.format()` / f-string 中的 `None` → 加 `is not None` 守卫或 fallback 值
     - pandas `sort_values('datetime')` 与 index 重名 → `drop(columns=['datetime'])` 后再操作
     - API 返回空 DataFrame → `len(df) > 0` 检查
     - 数学运算前 → `np.isfinite()` 防御 NaN
     - 权重/百分比计算 → 分母为 0 检查
  **禁止**：报错后假装没看见继续输出结论；报错后让用户手动修。
