---
name: l3-trade
description: 交易信号生成 — 评分→动作→仓位→双创折扣→核心/交易仓区分。触发词：交易信号、生成信号、仓位、L3、trade。
---

# L3 交易员 (Signal Generator)

将 L2 裁决映射为可执行交易信号和仓位。

## 信号映射

| Score | Action | 操作 |
|-------|--------|------|
| ≥ 80 | OPEN | 建仓 |
| 75-79 | ADD | 加仓 |
| 50-74 | HOLD | 持有/观望 |
| 35-49 | REDUCE | 减仓 |
| < 35 | CLOSE | 清仓/回避 |

## 仓位公式

```
base = max(0, (score - 50) / 50 × macro_cap)
```

- `macro_cap`: 宏观仓位上限 (默认 0.80)
- 双创折扣: 科创板/创业板 ×0.8 (波动性更高)
- 核心仓/交易仓区分: 核心仓不因短期评分波动而清仓

## 输出

```python
TradeSignal(
    symbol="600519",
    action="ADD",
    target_weight=0.12,        # 12% 仓位
    is_core=False,
    limit=0.20,                 # L4 施加的上限
    source_citations=[...],     # 继承自 L1→L2 的引用链
    confidence=0.82,            # 继承自 L2 的信心度
)
```

## 护栏

- **不直接生成买卖建议** (需 L4 风控审批)
- **动作映射公开透明**
- **仓位公式参数可审计**

## 引用

- Python 实现: `src/routing/l3_trade.py`
- 依赖 Skill: `l2-judge`, `l4-risk`
