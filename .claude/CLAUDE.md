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
| `backtest-engine` | 策略回测 |
| `stock-attribution` | 个股涨跌归因（3阶段强制workflow） |

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
| 3. 管道验证 | 对每支候选**并行**跑 `diagnose <code> --no-t0`（Alpha搜索跳过日内时机）→ 横向排名 | 并行 |

**无主题泛选股**（如"推荐几支适合现在建仓的股票"）：

| 阶段 | 执行模块 | 方式 |
|------|---------|------|
| 1. 偏好确认 | AskUserQuestion（风格/周期/估值容忍度/市值/行业）→ `idea-generation` 匹配预设 | 串行 |
| 2. 全市场扫描 | CLI `scan --preset` / `alpha-scan` → `admission` 批量过滤 | 串行 |
| 3. 管道验证 | 对 Top N **并行**跑 `diagnose <code>`（含T+0，这是建仓判断）→ 横向排名 | 并行 |

> ⚠️ **T+0 使用规则**：Alpha 搜索/选股用 `--no-t0` 跳过日内噪音；**建仓判断/买入决策必须保留 T+0**（默认行为）。
> ⚠️ **阶段三不可跳过**。PE 低≠值得买，PE 高≠不能买。管道暴露 Alpha 空间、叙事阶段、数据质量、博弈分歧、技术面信号。

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

直接触发 `diagnose <code>`（默认含 T+0，建仓判断必须评估日内时机）。**禁止传 `--no-t0`**。

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

设计决策、风控机制、回测逻辑时，优先查阅以下两个本地参考项目。重点借鉴其**业务逻辑设计**而非技术架构。

### 🛡️ RiskGuard — 风控机制参考 (`~/Documents/workspace/riskguard`)

#### 一、五条风控规则的业务逻辑

**1. 单笔仓位上限 (`MaxPositionLimit`)** — `rules/position_limit.py`

核心判断链：
```
订单方向 → 成交后持仓投影 → 判断是否"放大风险" → 计算是否越界 → 越界则缩单或拒单
```

关键业务点：
- **加仓/减仓判定不是简单的 `abs(projected) > abs(current)`**。项目内部工具 `_projection.py:project()` 定义了"放大敞口"的两种情形：(a) 同向加仓（成交后 |持仓| 变大）；(b) **反手**（持仓符号翻转，多变空或空变多）。反手即使新仓 |幅度| 不大于旧仓，也是不折不扣的新增方向性风险——早期版本只用绝对值比较导致反手绕过所有仓位规则，已被修复。这个 bug 在我们自己的仓位调度中也必须防范。
- **减仓 / reduce_only 单永远放行**，不依赖 equity 是否有效。权益归零（爆仓）时手动平仓的 reduce_only 单也必须能通过闸门。
- 权益 ≤ 0 时，风险放大类订单直接拒单（不能开新仓）。
- `on_position_breach` 控制越界行为：`resize`（缩到上限内继续）vs `reject`（直接拒单）。

**2. 回撤熔断 (`DrawdownCircuitBreaker`)** — `rules/drawdown.py`

核心判断链：
```
每次观测权益 → 更新 high-water mark → 计算 drawdown = 1 - equity/HWM → 触及阈值 → 熔断置位 → 新开仓全部拒单
```

关键业务点：
- 熔断状态由引擎在 `_observe_locked()` 中**自动置位**，不是在规则 evaluate 中判断——规则只读 `state.breaker_tripped` 做裁决。
- 熔断后**永远放行减仓/平仓单**（`reduce_only or not increasing`）。如果熔断反而拦下平仓，风险无法收敛，那是灾难而非保护。
- 熔断是**幂等**的：已触发则 `trip()` 原样返回。
- 人工复盘后 `reset_breaker()` 把 high-water mark 重置到当前权益，避免立刻二次触发。
- **权益观测的 NaN 防御**：`state.py:observe_equity()` 中，`math.isfinite(equity)` 为 False 时直接返回原状态不变。绝不能让 NaN 污染 `last_equity`——那会让 drawdown 恒算成 NaN、回撤熔断从此永不触发（fail-open）。

**3. 新策略隔离观察 (`StrategyQuarantine`)** — `rules/quarantine.py`

核心逻辑：
```
策略首次交易 → 自动登记入役时间 → 隔离期（默认90天）内适用更严格仓位上限（默认1%）→ 活过隔离期后恢复正常上限
```

关键业务点：
- 策略入役时间可自动登记（`auto_register_strategies=True`）或显式登记（`register_strategy()`）。
- 已存在策略不覆盖入役时间（保留最早）。
- 隔离期内同样遵循"减仓永远放行"原则。
- 这对应我们系统中"新策略先用小资金验证"的需求——不是人工判断，而是系统强制。

**4. 组合层敞口上限 (`GrossExposureLimit` / `NetExposureLimit`)** — `rules/exposure.py`

核心业务点：
- `GrossExposureLimit`：全组合总名义敞口（多空绝对值之和）≤ `max_gross_exposure_pct × equity`。防止"一堆各自合规的小仓位累加成过度杠杆"。默认 1.0（不加杠杆）。
- `NetExposureLimit`：全组合净敞口（多头市值 − 空头市值）≤ `±max_net_exposure_pct × equity`。管的是方向性风险。多空对冲组合可能 gross 很大但 net 接近 0。`max_net_exposure_pct=None` 时此规则是空操作。
- NetExposureLimit 有个关键判断：**使 |净敞口| 变小的单永远放行**（`abs(projected_net) <= abs(current_net)`）。这不同于简单地检查 reduce_only——一个多单在净空头组合里可能是减仓方向。

#### 二、仓位算法的业务逻辑 (`sizing/`)

**Sizer 与 Rule 两层严格分离**：Sizer 只负责"下多大注"，Rule 负责"能不能下、要不要缩、该不该全停"。AI 可以做研究、写代码、挑毛病，但**每一笔真实指令都必须先过写死的风控规则**。

三种仓位法的业务含义：

| Sizer | 公式 | 适用场景 | 本项目可用处 |
|-------|------|---------|------------|
| `KellySizer` | `f* = (b×p − q)/b`，乘以 `kelly_fraction`（0.25~0.5） | 有明确胜率/盈亏比估计的策略 | L3 仓位调度 `routing/positioning.py` |
| `VolatilityTargetSizer` | `weight = target_vol / realized_vol` | 多标的组合，按风险预算（非资金）分配 | 多票推荐时的仓位差异化 |
| `FixedFractionalSizer` | `weight = max_position_pct`（固定比例） | 最朴素、最难被自己骗 | 默认仓位法 |

关键业务细节：
- Kelly 判据 `f* ≤ 0`（无正期望）→ **返回 0，不下注**。`size()` 方法中 `quantity ≤ 0` 返回 `None`，"不下注就是最好的下注"。
- 波动率目标法有 `_MIN_VOL = 1e-6` 防止除零导致爆炸性权重。
- 所有 sizer 输出的权重被 `max_sizing_leverage` 夹住，再被下游仓位上限规则二次约束。

#### 三、风控状态机的业务逻辑 (`state.py`)

```
权益观测 → 更新 HWM → 计算 drawdown → 达到阈值 → 熔断（幂等）
                                                    ↓
                                          新开仓/加仓 REJECT
                                          减仓/平仓 APPROVE
                                                    ↓
                                          人工复盘 → reset → HWM 归位到当前权益
```

关键业务点：
- 状态全不可变（`frozen=True`），每次变更返回新对象。历史状态永远可追溯、可回放。
- `strategy_age_days()`：从入役时间戳计算天数，用于隔离观察期判断。
- `observe_equity()` 的 NaN 防御是防卫性编程的典范——feed 抖动、除零、坏 tick 产生的 NaN 会直接**忽略**而非污染状态。

#### 四、引擎裁决聚合逻辑 (`engine.py:_aggregate()`)

```
所有规则 eval → 聚合：
  任一 REJECT → 整体 REJECT
  多个 RESIZE → 取最保守（最小）的缩量
  全部 APPROVE → 放行
```

关键业务点：
- 审计写入与风控裁决严格解耦：`_safe_audit()` 中 try/except 包裹所有审计操作，**磁盘满/IO异常绝不能让风控裁决带崩**。
- `update_equity()` 可在下单流程之外周期性调用（供监控守护进程），每个 bar 至少观测一次权益。

#### 五、回测叠加层的业务逻辑 (`backtest/overlay.py`)

核心翻译：**策略的"目标持仓" → 风控批准的"下一步订单"**

```
策略 say "想满仓做多"(target_weight=+1.0)
  → overlay 算出 delta = target_qty - current_qty
  → 构造差额 Order（朝零收敛的标 reduce_only）
  → 过风控引擎 check()
  → 返回批准/缩量/拒单后的订单
```

关键业务点：
- **坏 tick 防御**：`price ≤ 0 or equity ≤ 0` → 直接返回无动作，**不触碰引擎、不改统计**。坏 tick 绝不能被当成"清仓"意图去下平仓单。
- 目标已在位（`abs(delta) < EPS`）→ 只推进熔断状态，不下单。
- `reduce_only` 判定：朝零收敛（同向减小或清仓）→ reduce_only=True，任何时候都放行。
- 累计回测统计：orders / resized / rejected / breaker_trips / halted_bars。

#### 六、可直接借鉴到本项目的业务机制清单

| # | 机制 | 来源文件 | 应用到本项目 |
|---|------|---------|------------|
| 1 | **反手检测逻辑** (多头→空头 / 空头→多头 = 放大风险) | `_projection.py:project()` | `routing/risk_control.py` 仓位变更判断 |
| 2 | **减仓单永不拦截** (熔断/上限/隔离 一律放行平仓) | 5 条规则共同的 `reduce_only or not increasing` | L4 风控 + 31 条军规 |
| 3 | **高水位回撤熔断** (HWM → drawdown → 自动熔断 → 人工复位) | `state.py` + `drawdown.py` | L4 风控执行 |
| 4 | **新策略隔离观察** (入役登记 → 90天小仓位 → 自动放行) | `quarantine.py` | `learner/` 策略进化验证 |
| 5 | **组合层双重敞口** (gross 管杠杆 + net 管方向) | `exposure.py` | `routing/positioning.py` 组合约束 |
| 6 | **Kelly/VolTarget 仓位算法** (公式算注码，不让情绪决定) | `sizing/kelly.py` `sizing/volatility.py` | L3 仓位调度 |
| 7 | **权益 NaN 防御** (坏读数直接忽略，绝不污染状态) | `state.py:observe_equity()` | 所有涉及权益计算的模块 |
| 8 | **审计与风控解耦** (审计失败不得阻断风控裁决) | `engine.py:_safe_audit()` | 信号日志写入 |
| 9 | **目标→差额订单翻译** (策略说目标权重，overlay 算差额) | `backtest/overlay.py` | `backtest/` 回测框架 |
| 10 | **三档配置预设** (保守5%/均衡10%/激进20%，每项单调不减) | `presets.py` | 投资者偏好 `preference` |

### 📊 VectorBT — 回测机制参考 (`~/Documents/workspace/vectorbt`)

#### 一、三种仿真模式的分层设计 (`portfolio/base.py`)

VectorBT 提供三层抽象，从简单到灵活递增：

| 模式 | 入口 | 业务含义 | 本项目可借鉴 |
|------|------|---------|------------|
| `from_orders` | 直接给 size + price 数组 | "已知每笔订单的量和价，算结果" | 交易追踪回放 |
| `from_signals` | entries/exits 信号数组 | "知道何时进出，自动生成订单、防重复开仓" | 信号→回测的标准路径 |
| `from_order_func` | 任意 Numba JIT 回调 | "每个 bar 跑自定义逻辑，可查当前持仓 PnL" | 复杂策略的事件驱动回测 |

关键业务点：
- `from_signals` 默认**不允许在已有持仓时再次入场**（`accumulate=False`），防止信号重复触发。设 `accumulate=True` 可逐步加仓/减仓。
- `from_order_func` 的 flexible 模式允许**每 bar 多笔订单**，对应真实场景中的拆单执行。
- 三种模式共享同一套订单记录、交易分析、统计输出——**分析层与仿真层解耦**。

#### 二、交易记录的三层模型 (`portfolio/trades.py`)

```
订单 (Orders)
   ↓ 重构视角
Entry Trades（每笔买入 + 分摊卖出的份额）
Exit Trades（每笔卖出 + 分摊买入的成本）
Positions（时间序列上连续的 entry/exit 聚合）
```

关键业务点：
- **Entry Trades PnL == Exit Trades PnL == Positions PnL**。不同视角看同一组数据，总和一致。这保证了无论从哪个角度分析策略都不会出现"账对不上"的情况。
- 加仓场景：1 笔大买单 + 100 笔小卖单 → 1 个 Entry Trade（入口信息来自买单，出口信息是卖单的加权平均）。**做 T 的收益可以精确归属到每一笔开仓**。
- 减仓场景：100 笔小买单 + 1 笔大卖单 → 100 个 Entry Trade（每笔独立评估）。可以看清**分批建仓中哪几笔拖了后腿**。
- **Open trades 始终包含在结果中**——如果需要只看已平仓交易，必须显式 `.closed` 过滤。否则会把未平仓浮盈/浮亏混入统计。
- 这对应我们系统中**交易追踪 (`trade-track`) 的需求**——每笔开仓的盈亏归属、做 T 效果评估、分批建仓的绩效分解。

#### 三、回撤分析的完整生命周期 (`generic/drawdowns.py`)

每个回撤记录包含五个时间点：
```
Peak（高点） → Start（开始下跌） → Valley（最低点） → End（恢复/至今） → Status（Recovered/Active）
```

关键业务点：
- **Active vs Recovered 分离**：默认指标（max_dd, avg_dd, max_dd_duration, avg_dd_duration）**不包含活跃回撤**。`incl_active=True` 才纳入。这避免了"还没恢复就计入最大回撤"的偏差。
- 指标包括：Coverage（回撤占比）、Recovery Return（恢复期收益）、Recovery Duration（恢复耗时）、Duration Ratio（恢复耗时/下跌耗时）。
- 这对应我们 `backtest/` 和 L4 风控的回撤计算——当前只算了一个简单的峰值回撤百分比，远不够诊断策略质量。

#### 四、信号处理的关键枚举配置 (`portfolio/enums.py`)

| 枚举 | 选项 | 业务含义 |
|------|------|---------|
| `Direction` | longonly / shortonly / both | 限制策略方向，做多策略不会因信号误触而开空仓 |
| `AccumulationMode` | Disabled / Both / AddOnly / RemoveOnly | 仓位累积模式：禁用/双向/只加/只减 |
| `CallSeqType` | Default / Reversed / Random / Auto | 同 bar 多标的的成交顺序（影响资金分配） |
| `ConflictMode` | 多种 | 同一 bar 出现 entry+exit 信号时如何处理 |
| `StopExitMode` | 多种 | 止损/止盈触发后的平仓方式 |
| `SizeType` | 多种 | 下单量的含义：股数/金额/权重/目标百分比 |

关键业务点：
- `Auto` 调用顺序：按订单金额动态排序，大单优先成交——这对资金有限的场景很重要。
- `AccumulationMode.AddOnly`：允许加仓但不允许减仓（适合定投策略）；`RemoveOnly`：只允许减仓（适合退出策略）。
- 这些枚举对应我们回测系统中需要支持的配置项——当前 `backtest/` 模块缺少这些维度。

#### 五、统计构建器的声明式指标 (`generic/stats_builder.py`)

每个指标声明为一个配置条目：
```python
"max_drawdown": dict(
    title="Max Drawdown [%]",
    calc_func=lambda self: ...,
    tags=["drawdown", "risk"],
    apply_to_timedelta=False,
)
```

关键业务点：
- `group_by=True` 可以跨列/跨标的聚合——例如把所有持仓作为一个组合来统计（而非逐标的）。
- `tags` 机制允许按类别筛选指标（例如只输出 risk 类指标）。
- 这对应我们每个分析阶段输出的数据——可以用声明式指标替代硬编码的 print/日志，使输出可配置、可组合。

#### 六、可直接借鉴到本项目的业务机制清单

| # | 机制 | 来源文件 | 应用到本项目 |
|---|------|---------|------------|
| 1 | **三层仿真模式** (orders/signals/order_func 逐级灵活) | `portfolio/base.py` | `backtest/` 回测引擎设计 |
| 2 | **Entry/Exit/Position 三层交易视角** (PnL 总和一致) | `portfolio/trades.py` | `trade-track` 交易追踪 |
| 3 | **回撤五阶段生命周期** (Peak→Start→Valley→End→Status) | `generic/drawdowns.py` | L4 风控回撤计算 |
| 4 | **Active/Recovered 分离统计** (未恢复回撤不污染指标) | `generic/drawdowns.py` | `backtest/` 绩效报告 |
| 5 | **Direction/Accumulation 限制** (策略方向约束 + 仓位累积模式) | `portfolio/enums.py` | 回测配置参数 |
| 6 | **Auto 调用顺序** (大单优先，按金额动态排序) | `portfolio/enums.py:CallSeqType` | 多标的资金分配 |
| 7 | **声明式指标配置** (指标=calc_func+tags+group_by) | `generic/stats_builder.py` | 分析输出标准化 |
| 8 | **信号自动防重复** (已有持仓不再入场，除非 accumulate=True) | `portfolio/base.py:from_signals` | `backtest/` 信号处理 |
| 9 | **分批建仓绩效分解** (每笔 entry 独立计算 PnL + Return) | `portfolio/trades.py` | 交易追踪 `trade-track` |
| 10 | **Stop Loss / Take Profit 内置** | `portfolio/base.py:from_signals` | `backtest/` + L4 风控 |

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
