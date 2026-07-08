# A 股价值投资本土化强化 — 设计文档

> 日期: 2026-07-08 | 方案: B (管道重构式)

## 目标

将宏观周期前置、反操纵信号、仓位联动嵌入诊断管道核心，实现五个维度的本土化强化。

## 管道架构（重构后）

```
1. 数据获取（+筹码/资金流）
2. 🆕 宏观象限判定（先于一切）
3. 军规（+r032/r033/r034 财务质量）
4. 准入检查
5. 🆕 反操纵扫描（筹码集中度+日级操纵+资金背离）
6. Alpha Lens
7. 多维诊断（⬅ 宏观权重+操纵降权）
8. 质量审查
9. 博弈论（⬅ 操纵检测注入）
10. 投资思维模型
11. 综合裁决（⬅ 宏观+操纵双重调整）
12. 仓位调度（⬅ 操纵感知Kelly折扣）
13. 风控执行（⬅ 操纵感知止损）
14. 🆕 持仓监控
```

## 文件改动清单

| # | 文件 | 类型 | 职责 |
|---|------|:--:|------|
| 1 | `src/doctrine/rules.py` | 修改 | 追加 r032/r033/r034 |
| 2 | `src/doctrine/checker.py` | 修改 | 财务质量检查逻辑 |
| 3 | `src/macro/monetary_credit.py` | 修改 | `get_regime_adjustments()` |
| 4 | `src/game_theory/chip_concentration.py` | 新建 | 筹码集中度分析 |
| 5 | `src/game_theory/daily_manipulation.py` | 新建 | 日级操纵模式检测 |
| 6 | `src/game_theory/capital_flow.py` | 重写 | 资金流分析 |
| 7 | `src/routing/orchestrator.py` | 修改 | 管道重排+注入点 |
| 8 | `src/routing/diagnosis.py` | 修改 | 动态权重调整 |
| 9 | `src/routing/verdict.py` | 修改 | 操纵风险折扣 |
| 10 | `src/routing/positioning.py` | 修改 | Kelly×操纵折扣 |
| 11 | `src/routing/risk_control.py` | 修改 | 操纵感知止损 |
| 12 | `src/routing/position_monitor.py` | 新建 | 持仓持续跟踪 |

## 各模块详细设计

### 1. 军规 r032-r034

- **r032 ROE 连续性**: 近 3 年 ROE 均 > 10% 且无年度亏损，否则 WARN
- **r033 现金流质量**: 经营现金流/净利润 > 0.8（近 3 年累计），否则 WARN
- **r034 分红门槛**: 近 3 年累计分红/净利润 > 30%，否则 INFO（提示铁公鸡风险）

### 2. 宏观象限前置

`MonetaryCreditAnalyzer.get_regime_adjustments()` 返回:

```python
@dataclass
class RegimeAdjustments:
    quadrant: Quadrant
    value_weight: float      # 价值维度权重调整
    growth_weight: float     # 成长维度权重调整
    quality_weight: float    # 质量维度权重调整
    position_cap: float      # 仓位上限调整
    sector_favor: list[str]  # 推荐板块
    sector_avoid: list[str]  # 规避板块
```

### 3. 反操纵扫描

三个分析器并行运行:
- `ChipConcentrationAnalyzer` — 筹码集中度评分
- `DailyManipulationDetector` — 日级操纵模式匹配
- `CapitalFlowAnalyzer` — 资金背离度

输出统一 `ManipulationScan`:
```python
@dataclass
class ManipulationScan:
    chip_risk: float          # 0-100 筹码集中风险
    daily_pattern: str | None # 检测到的操纵模式
    pattern_confidence: float
    capital_divergence: float # 资金背离度
    overall_risk: float       # 综合操纵风险 0-100
    recommendations: list[str]
```

### 4. 诊断权重动态调整

诊断各维度基础权重 × 宏观调整系数 × 操纵降权系数。

### 5. 仓位操纵折扣

Kelly 仓位 × (1 - overall_risk/100)，操纵风险 > 60 时不入场。

### 6. 操纵感知止损

| 模式 | 止损策略 |
|------|---------|
| 诱多出货 | 跌破当日均价即止损 |
| 洗盘震仓 | 放宽止损 2% |
| 钓鱼线 | 立即止损 |
| 尾盘操纵 | 次日开盘 15 分钟内未走强即止损 |
| 无操纵 | 标准 ATR 止损 |

### 7. 持仓监控

`PositionMonitor` 定期检查:
- 买入逻辑是否仍然成立
- 基本面是否恶化
- 宏观象限是否变化
- 操纵风险是否上升
- 是否触发重新评估
