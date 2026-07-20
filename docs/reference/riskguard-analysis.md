# RiskGuard — 风控机制参考

> 本地：`~/Documents/workspace/riskguard`
> 定位：Python 风控规则引擎 — 单笔仓位上限、回撤熔断、策略隔离、组合敞口、仓位算法

## 一、五条风控规则的业务逻辑

### 1. 单笔仓位上限 (`MaxPositionLimit`) — `rules/position_limit.py`

核心判断链：
```
订单方向 → 成交后持仓投影 → 判断是否"放大风险" → 计算是否越界 → 越界则缩单或拒单
```

关键业务点：
- **加仓/减仓判定不是简单的 `abs(projected) > abs(current)`**。项目内部工具 `_projection.py:project()` 定义了"放大敞口"的两种情形：(a) 同向加仓（成交后 |持仓| 变大）；(b) **反手**（持仓符号翻转，多变空或空变多）。反手即使新仓 |幅度| 不大于旧仓，也是不折不扣的新增方向性风险——早期版本只用绝对值比较导致反手绕过所有仓位规则，已被修复。这个 bug 在我们自己的仓位调度中也必须防范。
- **减仓 / reduce_only 单永远放行**，不依赖 equity 是否有效。权益归零（爆仓）时手动平仓的 reduce_only 单也必须能通过闸门。
- 权益 ≤ 0 时，风险放大类订单直接拒单（不能开新仓）。
- `on_position_breach` 控制越界行为：`resize`（缩到上限内继续）vs `reject`（直接拒单）。

### 2. 回撤熔断 (`DrawdownCircuitBreaker`) — `rules/drawdown.py`

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

### 3. 新策略隔离观察 (`StrategyQuarantine`) — `rules/quarantine.py`

核心逻辑：
```
策略首次交易 → 自动登记入役时间 → 隔离期（默认90天）内适用更严格仓位上限（默认1%）→ 活过隔离期后恢复正常上限
```

关键业务点：
- 策略入役时间可自动登记（`auto_register_strategies=True`）或显式登记（`register_strategy()`）。
- 已存在策略不覆盖入役时间（保留最早）。
- 隔离期内同样遵循"减仓永远放行"原则。
- 这对应我们系统中"新策略先用小资金验证"的需求——不是人工判断，而是系统强制。

### 4. 组合层敞口上限 (`GrossExposureLimit` / `NetExposureLimit`) — `rules/exposure.py`

核心业务点：
- `GrossExposureLimit`：全组合总名义敞口（多空绝对值之和）≤ `max_gross_exposure_pct × equity`。防止"一堆各自合规的小仓位累加成过度杠杆"。默认 1.0（不加杠杆）。
- `NetExposureLimit`：全组合净敞口（多头市值 − 空头市值）≤ `±max_net_exposure_pct × equity`。管的是方向性风险。多空对冲组合可能 gross 很大但 net 接近 0。`max_net_exposure_pct=None` 时此规则是空操作。
- NetExposureLimit 有个关键判断：**使 |净敞口| 变小的单永远放行**（`abs(projected_net) <= abs(current_net)`）。这不同于简单地检查 reduce_only——一个多单在净空头组合里可能是减仓方向。

## 二、仓位算法的业务逻辑 (`sizing/`)

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

## 三、风控状态机的业务逻辑 (`state.py`)

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

## 四、引擎裁决聚合逻辑 (`engine.py:_aggregate()`)

```
所有规则 eval → 聚合：
  任一 REJECT → 整体 REJECT
  多个 RESIZE → 取最保守（最小）的缩量
  全部 APPROVE → 放行
```

关键业务点：
- 审计写入与风控裁决严格解耦：`_safe_audit()` 中 try/except 包裹所有审计操作，**磁盘满/IO异常绝不能让风控裁决带崩**。
- `update_equity()` 可在下单流程之外周期性调用（供监控守护进程），每个 bar 至少观测一次权益。

## 五、回测叠加层的业务逻辑 (`backtest/overlay.py`)

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

## 六、可直接借鉴到本项目的业务机制清单

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
