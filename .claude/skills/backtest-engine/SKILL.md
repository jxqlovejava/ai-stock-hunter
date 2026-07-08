---
name: backtest-engine
description: 策略回测 — 因子即列模式、MVP 策略族、参数优化、多策略比较。触发词：回测、backtest、优化、参数搜索、策略比较。
---

# 策略回测引擎 (Backtest Engine)

基于 backtrader 的 A 股策略回测系统。支持因子列扩展、参数网格搜索、多策略比较。

## 策略族

| 策略 | 因子 | 特点 |
|------|------|------|
| MVP1 | PE 分位 + ROE + 动量 | 三因子基础策略 |
| MVP2 | MVP1 + 北向 + 质量 | 五因子增强 |
| MVP2+ | MVP2 + 盈利修正 | 加入基本面因子 |
| MVP3 | 全面因子整合 | 含宏观 regime 调整 |

## 工作流

### Step 1: 策略注册
- 在 `src/backtest/strategy_registry.py` 注册策略
- 配置：因子权重、调仓频率、基准指数

### Step 2: 数据准备
- K 线缓存 (`data/kline_cache/`)
- 因子管道计算因子列 (`src/data/factor_pipeline.py`)
- 自动附加为 backtrader 额外数据线

### Step 3: 回测运行
```bash
python -m src.cli backtest --strategy mvp2 --start 20200101 --end 20251231
```

### Step 4: 性能指标

| 指标 | 含义 | 目标 |
|------|------|------|
| 年化收益率 | 复利年化收益 | > 15% |
| 夏普比率 | 风险调整后收益 | > 1.0 |
| 最大回撤 | 最大峰谷跌幅 | < 25% |
| 胜率 | 盈利交易占比 | > 55% |
| 盈亏比 | 平均盈利/平均亏损 | > 2.0 |
| 换手率 | 年度换手 | < 300% |
| Calmar 比率 | 年化收益/最大回撤 | > 0.5 |

### Step 5: 参数优化
```bash
python -m src.cli backtest-optimize --strategy mvp2
```
- 网格搜索最优参数组合
- 过拟合检测 (样本外验证)

### Step 6: 多策略比较
```bash
python -m src.cli backtest-compare
```
- 同时间段多策略对比
- 相关性分析 (策略多样化)

## A 股特定配置

| 参数 | 值 |
|------|-----|
| 印花税 | 0.05% (卖方) |
| 佣金 | 0.025% |
| 过户费 | 0.001% |
| 总成本 | ~0.23% (来回) |
| 初始资金 | 1,000,000 |
| 基准 | 沪深300 (000300) |
| 涨跌停限制 | 10% / 20% |

## 护栏

- **至少 3 年回测数据才有统计意义**
- **必须样本外验证** (最后 1 年不参与优化)
- **过拟合警告**: 参数数 > sqrt(交易次数)
- **实盘前小资金验证 3 个月**

## 引用

- Python 实现: `src/backtest/engine.py`, `src/backtest/strategy_registry.py`
- 数据: `src/data/factor_pipeline.py`, `data/kline_cache/`
- 依赖 Skill: `diagnosis`, `risk-control`
