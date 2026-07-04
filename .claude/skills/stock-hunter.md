---
name: stock-hunter
description: AI Stock Hunter — A 股智能投资决策系统。触发词：分析股票、选股、回测、大盘、情绪、诊断。提供全链路分析（军规→L0→L1→L2→L3→L4），支持一键诊断、条件选股、情绪检测、策略回测。
user-invocable: true
depends_on:
  - doctrine
  - l0-gate
  - l1-analyze
  - l2-judge
  - l3-trade
  - l4-risk
  - macro-monitor
  - game-theory
  - policy-tracker
  - sentiment-analysis
  - idea-generation
  - topic-manager
  - earnings-analysis
  - sector-research
  - backtest-engine
---

# AI Stock Hunter — A 股智能投资助手

面向 A 股个人投资者的 AI 辅助决策系统。核心理念：**阻止致命亏损 > 捕捉机会 > 教育用户**。

## 能力概览

### 1. 分析 (analyze)
对单只股票执行全链路分析：军规门禁 → L0 保安 → L1 分析师 → L2 法官 → L3 交易员 → L4 风控官。

```
/stock-hunter analyze 600519
/stock-hunter analyze 宁德时代
```

### 2. 诊断 (diagnose)
一键诊断（小白入口）——先过军规，再做简要分析，输出三色信号。

```
/stock-hunter diagnose 600519
```

### 3. 选股 (scan)
按条件筛选股票。

```
/stock-hunter scan --condition "PE<20, ROE>15%, 北向增持"
```

### 4. 情绪 (sentiment)
检测当前 A 股大盘情绪（恐慌/贪婪/正常）。

```
/stock-hunter sentiment
```

### 5. 宏观 (macro)
宏观环境快照。

```
/stock-hunter macro
```

### 6. 博弈论 (game-theory)
查看 A 股博弈论知识库（15 条规则、6 类玩家、3 种操盘手法）。

```
/stock-hunter game-theory
```

### 7. 回测 (backtest)
运行 MVP-1 三因子策略回测。

```
/stock-hunter backtest
```

### 8. 校准 (calibrate)
查看系统置信度校准报告（需 ≥20 笔交易样本）。

```
/stock-hunter calibrate
```

### 9. 画像 (profile)
查看用户投资能力画像。

```
/stock-hunter profile
```

## 实现方式

本 skill 通过调用 `python -m src.cli <command>` 执行对应功能。

## 数据源

- **国信证券**: 实时行情、财务三表、宏观经济 (GS_API_KEY)
- **AKShare**: 全市场扫描、龙虎榜、两融、北向资金
- **华泰证券**: AI 诊断、市场洞察 (HT_APIKEY)

## 风控参数

| 参数 | 值 |
|------|-----|
| 单票上限 | 20% |
| 单行业上限 | 40% |
| 单笔止损 | 2% |
| 组合熔断 | -15% |
| 恐慌仓位上限 | 25% |
| 系统熔断 | 滚动 3 月胜率 < 40% |

## 注意事项

- 本系统不构成投资建议
- 所有分析结果仅供参考
- 实盘前请充分验证策略在回测中的表现
