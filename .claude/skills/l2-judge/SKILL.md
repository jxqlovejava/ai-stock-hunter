---
name: l2-judge
description: 加权评分与裁决 — 融合基本面/动量/宏观/行业/情绪 5 维权重，主题生命周期调整，置信度校准。触发词：评分、裁决、judge、L2、判断。
---

# L2 法官 (Weighted Judge)

融合 L1 的 7 维度评分，进行加权综合裁决。核心机制：主题生命周期调整 + 可证伪条件 + 置信度校准。

## 评分权重

| 维度 | 权重 | 来源 |
|------|------|------|
| 基本面 (价值+质量) | 40% | L1 value_score + quality_score |
| 技术面 (动量) | 20% | L1 momentum_score |
| 宏观 | 15% | L1 macro_score |
| 行业景气 | 10% | sector_score |
| 情绪 | 15% | sentiment 映射 (PANIC→30, NORMAL→50, GREED→40, EXTREME→90) |

## 主题生命周期调整

| 阶段 | 调整 | 逻辑 |
|------|------|------|
| EMERGING | +10% | 主题刚出现，有 alpha |
| SPREADING | ±0% | 正常扩散 |
| CONSENSUS | -10% | 共识形成，拥挤风险 |
| CROWDED | -20% | 过度拥挤 |
| FADING | 中性化到 50 | 主题消退，行业评分失效 |

## 裁决映射

| Score | 建议 | 含义 |
|-------|------|------|
| ≥ 75 | BUY | 可建仓 |
| 60-74 | ADD | 可加仓 |
| 40-59 | HOLD | 持有/观望 |
| 25-39 | REDUCE | 减仓 |
| < 25 | SELL | 清仓 |

## 置信度校准

```
confidence = 0.5 + 0.3 × (min(fundamental, macro, sector) / 50)
```
- 各维度评分均衡 → 置信度更高
- 单一维度突出但其他维度低 → 置信度惩罚

## 可证伪条件

每项裁决附带可证伪条件：
- "如果宏观 PMI < 48，建议失效"
- "如果标的 PE 超过历史 70% 分位，建议失效"

## 护栏

- **confidence < 0.6 → 阻止进入 L3** (MIN_CONFIDENCE)
- **主题拥挤时降权 20%**
- **主题消退时中性化行业评分**

## 引用

- Python 实现: `src/routing/l2_judge.py`
- 主题管理: `src/information/topic_manager.py`
- 依赖 Skill: `l1-analyze`, `l3-trade`, `topic-manager`
