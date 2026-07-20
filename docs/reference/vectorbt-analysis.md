# VectorBT — 回测机制参考

> 本地：`~/Documents/workspace/vectorbt`
> 定位：Python 量化回测框架 — 三层仿真模式、交易记录模型、回撤分析、信号枚举配置、声明式指标

## 一、三种仿真模式的分层设计 (`portfolio/base.py`)

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

## 二、交易记录的三层模型 (`portfolio/trades.py`)

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

## 三、回撤分析的完整生命周期 (`generic/drawdowns.py`)

每个回撤记录包含五个时间点：
```
Peak（高点） → Start（开始下跌） → Valley（最低点） → End（恢复/至今） → Status（Recovered/Active）
```

关键业务点：
- **Active vs Recovered 分离**：默认指标（max_dd, avg_dd, max_dd_duration, avg_dd_duration）**不包含活跃回撤**。`incl_active=True` 才纳入。这避免了"还没恢复就计入最大回撤"的偏差。
- 指标包括：Coverage（回撤占比）、Recovery Return（恢复期收益）、Recovery Duration（恢复耗时）、Duration Ratio（恢复耗时/下跌耗时）。
- 这对应我们 `backtest/` 和 L4 风控的回撤计算——当前只算了一个简单的峰值回撤百分比，远不够诊断策略质量。

## 四、信号处理的关键枚举配置 (`portfolio/enums.py`)

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

## 五、统计构建器的声明式指标 (`generic/stats_builder.py`)

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

## 六、可直接借鉴到本项目的业务机制清单

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
