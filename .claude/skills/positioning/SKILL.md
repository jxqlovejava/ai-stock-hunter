---
name: positioning
description: 仓位调度 — 评分→动作→仓位→双创折扣→核心/交易仓区分。触发词：交易信号、生成信号、仓位、调度、positioning。
---

# 仓位调度 (Position Sizing)

将综合裁决映射为可执行交易信号和仓位。

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
PositionSignal(
    symbol="600519",
    action="ADD",
    target_weight=0.12,        # 12% 仓位
    is_core=False,
    limit=0.20,                 # 风控施加的上限
    source_citations=[...],     # 继承自诊断→裁决的引用链
    confidence=0.82,            # 继承自裁决的信心度
)
```

## 护栏

- **不直接生成买卖建议** (需风控审批)
- **动作映射公开透明**
- **仓位公式参数可审计**

## 引用

- Python 实现: `src/routing/positioning.py`
- 依赖 Skill: `verdict`, `risk-control`
