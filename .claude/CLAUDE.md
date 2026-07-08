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
- **分制统一**：评分 0-100，信心度 0.0-1.0，情绪 -1.0 到 +1.0
- **仅 SignalWriter 可写**：所有分析 Agent 只读，仅信号输出 Agent 有写权限
- **数据源优先级**：华泰(HT_APIKEY) > 国信(GS_API_KEY) > 腾讯(免费) > mootdx(TCP) > AKShare

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
| 行业 | `industry/bottleneck.py` | 实体瓶颈分析 |
| 行业 | `industry/supply_chain.py` | 供应链映射 |
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
| `l0-gate` | 安全门禁检查 |
| `l1-analyze` | 多维股票分析 |
| `l2-judge` | 加权评分与裁决 |
| `l3-trade` | 交易信号生成 |
| `l4-risk` | 风控约束检查 |
| `doctrine` | 31 条军规 |
| `game-theory` | 博弈论分析 |
| `macro-monitor` | 宏观货币信用监控 |
| `policy-tracker` | 政策跟踪与 NLP |
| `sentiment-analysis` | 市场情绪分析 |
| `topic-manager` | 主题生命周期管理 |
| `idea-generation` | 选股筛选预设 |
| `earnings-analysis` | A 股财报分析 |
| `sector-research` | 行业与供应链研究 |
| `backtest-engine` | 策略回测 |

## CLI

```bash
python -m src <command> [args]

# 核心分析
analyze <code>     # 全链路分析
diagnose <code>    # 一键诊断（小白入口）
alpha <code>       # Alpha Lens 三维评估
alpha-scan         # 高 Alpha 股票扫描
scan --preset <p>  # 全市场选股扫描

# 市场监控
macro              # 宏观快照
sentiment          # 情绪信号检测
game-theory        # 博弈论概览
search-news <q>    # 金融资讯搜索
screen <conds>     # 条件选股

# 盯盘 & 预警
sweep              # 自选股扫雷
alert watch-add    # 加入自选股
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
| 2. 数据初筛 | `a-stock-data` 拉行情/财务 → `l0-gate` 批量过滤 → `doctrine` 扫雷 | 串行 |
| 3. 管道验证 | 对每支候选**并行**跑 `stock-hunter` 全链路（军规→L0→L1→Alpha→质量→辩论→博弈→L2→T+0→L4） | 并行 |

**无主题泛选股**（如"推荐几支适合现在建仓的股票"）：

| 阶段 | 执行模块 | 方式 |
|------|---------|------|
| 1. 偏好确认 | AskUserQuestion（风格/周期/估值容忍度/市值/行业）→ `idea-generation` 匹配预设 | 串行 |
| 2. 全市场扫描 | CLI `scan --preset` / `alpha-scan` → `l0-gate` 批量过滤 | 串行 |
| 3. 管道验证 | 对 Top N **并行**跑 `stock-hunter` 全链路 → 横向排名输出 | 并行 |

> ⚠️ **阶段三不可跳过**。PE 低≠值得买，PE 高≠不能买。管道暴露 Alpha 空间、叙事阶段、数据质量、博弈分歧、技术面信号。

### 场景二：个股涨跌归因

**触发词**: XX股票为什么涨停/跌停/大涨/大跌、XX涨跌原因

| 阶段 | 执行模块 | 方式 |
|------|---------|------|
| 1. 信息搜集 | `last30days-cn`（搜个股相关新闻/传闻）+ `policy-tracker`（行业政策）+ `a-stock-data`（龙虎榜/北向/大宗交易/融资融券/公告） | 并行 |
| 2. 多维归因 | `macro-monitor`（宏观背景）+ `sector-research`（板块联动）+ `sentiment-analysis`（情绪状态）+ `topic-manager`（主题生命周期）+ 资金面分析 + T+0 技术面 | 并行 |
| 3. 因果推断 | macro event causality chain（8条传导通道）→ 主因→次因→噪音 排序 → 区分事实/解读/推测 | 串行 |

### 场景三：大盘涨跌归因

**触发词**: 今天A股为什么大跌/大涨/波动、大盘怎么了、市场暴跌原因

| 阶段 | 执行模块 | 方式 |
|------|---------|------|
| 1. 信息搜集 | `macro-monitor` + `sentiment-analysis` + `policy-tracker` + `last30days-cn` + 东财全球资讯（7×24快讯） | 并行 |
| 2. 结构分析 | 行业板块排名 + 北向资金 + 涨跌家数 + 成交量 + 涨停/跌停池 | 并行 |
| 3. 因果推断 | macro event causality chain（8通道）→ 区分触发因素/放大机制/噪音 → 对标历史 | 串行 |
| 4. 应对建议 | 情绪极端→恐慌套利 / 政策驱动→持续性评估 / 流动性冲击→央行窗口 | 串行 |

### 场景四：主题分析 / 单票深度分析

**4a. 纯主题分析**（不一定要荐股）:

**触发词**: 分析XX主题/赛道/板块/概念

| 阶段 | 执行模块 | 方式 |
|------|---------|------|
| 1. 信息搜集 | `last30days-cn` + `topic-manager` + `sector-research` + `policy-tracker` | 并行 |
| 2. 量化分析 | `a-stock-data` 拉代表标的行情/估值 → 行业板块排名 → 北向/融资融券 | 串行 |
| 3. 综合输出 | 生命周期阶段+拥挤度 → 产业链全景 → 代表标的对比 → 后续关注点 | 串行 |

**4b. 单票深度分析**（建仓判断）:

**触发词**: XX股票现在值得建仓吗、XX股票能买吗、分析一下XX

直接触发 `stock-hunter` 全链路管道（军规→L0→L1→Alpha→质量→辩论→博弈→L2→T+0→L4），无需经过阶段一/二。

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
