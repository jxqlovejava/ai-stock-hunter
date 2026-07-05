# 凯利公式仓位管理 — 设计文档

**日期**: 2026-07-05
**状态**: 设计中

## 背景

当前 L3 仓位公式为固定比例线性映射 `base = (score - 50) / 50 * macro_cap`，未考虑胜率和盈亏比。TODO.md 已规划凯利公式集成。

## 目标

用凯利公式 `f* = (b × p - q) / b` 替换当前线性公式，结合 L4 风控硬约束联动，基于历史交易记录的胜率和盈亏比动态调整仓位。

## 设计决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| p/b 来源 | 交易记录追踪（用户录入） | 最真实反映实际交易能力 |
| 粒度 | 按个股 | 不同股票的胜率和盈亏比差异大 |
| Kelly 类型 | Half-Kelly（默认），可配置比例 | 标准凯利波动过大 |
| 冷启动 | 回退到当前线性公式 | 无历史数据时凯利无法计算 |

## 架构

### 新增模块

```
src/kelly/
├── __init__.py       # 导出 KellyPositionSizer, TradeTracker
├── tracker.py        # 交易记录 CRUD + 按 symbol 汇总 p/b
└── sizer.py          # 凯利仓位计算 (冷/热启动自适应)
```

### 数据流

```
用户录入交易 → TradeTracker.track() → 按 symbol 汇总 p, b, n_trades
                                              ↓
L3Trader.generate_signal()
  → KellyPositionSizer.calc(symbol, score, ...)
      ├── n_trades < 5: 回退线性公式
      └── n_trades >= 5: half-Kelly
                              ↓
                          f* = (b × p - q) / b
                          f  = kelly_fraction × f*
                          target = min(f, L4_caps)
```

### 修改现有模块

| 文件 | 变更 | 说明 |
|------|------|------|
| `src/routing/l3_trade.py` | UPDATE | 集成 KellyPositionSizer，保留回退逻辑 |
| `src/learner/preference/` | UPDATE | position_limits 新增 kelly_fraction |
| `src/routing/orchestrator.py` | UPDATE | 传入 kelly_sizer 实例 |
| `src/cli.py` | UPDATE | 新增 `trade-track` 子命令录入交易记录 |

### DTO 设计

```python
@dataclass
class TradeRecord:
    """单笔交易记录。"""
    symbol: str
    entry_date: datetime
    exit_date: datetime
    entry_price: float
    exit_price: float
    shares: int
    direction: str  # LONG / SHORT

@dataclass
class KellyParams:
    """个股凯利参数。"""
    symbol: str
    win_rate: float       # p = 胜率
    payoff_ratio: float   # b = 盈亏比 (avg_win / abs(avg_loss))
    n_trades: int         # 交易笔数
    kelly_fraction: float = 0.5
    kelly_position: float  # f* = 最终凯利仓位比例
```

### 冷启动策略

- `n_trades < 5`: 回退到 `(score - 50) / 50 * macro_cap`
- `n_trades >= 5`: 切换到凯利公式
- 切换时 `source_citation` 标记 `"kelly:n_trades={n}"`

### L4 联动

凯利输出后仍经过 L4 单票上限/行业上限/回撤熔断等硬约束裁剪。

## 测试计划

- `src/kelly/tests/test_tracker.py` — TradeTracker CRUD + p/b 计算
- `src/kelly/tests/test_sizer.py` — 冷/热启动切换 + Kelly 公式正确性
- `tests/test_routing/test_l3_kelly.py` — L3 集成测试

## 风险

- 交易记录手动录入有遗漏风险 → 后续可导入券商交割单
- 小样本凯利不稳定 → 最低 5 笔阈值 + 平滑处理
- f* 为负（负期望）→ 返回 0，不建仓
