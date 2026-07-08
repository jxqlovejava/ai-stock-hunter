---
name: game-theory
description: A 股博弈论 — 5 类玩家识别、龙虎榜席位、北向资金画像、公募拥挤度、涨停连板池。触发词：博弈论、筹码、主力、游资、龙虎榜、北向、game-theory。
---

# 博弈论分析 (Game Theory)

识别 A 股市场的边际定价者，理解当前市场由谁主导。

## 5 类市场参与者

| 玩家 | 特征 | 策略风格 |
|------|------|---------|
| 游资 (Hot Money) | 高换手、追逐热点、快进快出 | 打板/接力/龙头战法 |
| 机构 (Institutional) | 基本面驱动、中长线持有 | 价值发现/趋势跟踪 |
| 量化 (Quant) | 程序化交易、高频 | 统计套利/因子轮动 |
| 国家队 (National Team) | 稳定市场、逆周期操作 | 托底/护盘 |
| 北向资金 (Northbound) | 外资视角、偏好蓝筹 | 配置型/交易型 |

## 分析维度

### 1. 主导玩家识别 (Dominance)
- 根据换手率/波动率/小盘股强度/ETF 成交量/北向流量判断当前主导玩家
- 输出: `DominanceProfile` (dominant_player, confidence, recommended_strategy)

### 2. 龙虎榜席位追踪 (Seats)
- 30 个已知游资席位 + 声誉评分 (60-90)
- 涨停/炸板/跌停连板池统计
- 输出: `SeatActivity`, `LimitUpSnapshot`

### 3. 北向资金画像 (Northbound)
- 同花顺 hsgtApi 分钟级数据 (262 点/天)
- 总净流入/流出 + 加速度 + 连续天数 + 日内趋势
- 输出: `NorthboundProfile` (score 0-100)

### 4. 公募拥挤度 (Fund Positioning)
- 重仓股重叠率 + 行业拥挤度 + 新基发行趋势
- >70 分 = 拥挤
- 输出: `FundCrowdingSignal` (score 0-100)

### 5. 策略手册 (Playbooks)
- 游资主导 → 打板策略
- 机构主导 → 趋势跟踪
- 量化主导 → 因子轮动
- 国家队主导 → 逢低吸纳

## 输出

```python
DominanceProfile(
    dominant_player=PlayerType.HOT_MONEY,
    confidence=0.75,
    recommended_strategy="打板/龙头战法",
)
```

## 护栏

- **席位数据可能有延迟** (T+1 披露)
- **北向资金含假外资** (部分内地资金绕道)
- **公募持仓数据滞后** (季报/年报)

## 引用

- Python 实现: `src/game_theory/dominance.py`, `src/game_theory/seats.py`, `src/game_theory/northbound.py`, `src/game_theory/fund_positioning.py`
- 数据源: 东财 datacenter (龙虎榜), 同花顺 hsgtApi (北向), AKShare (公募)
- 依赖 Skill: `diagnosis`, `sentiment-analysis`
