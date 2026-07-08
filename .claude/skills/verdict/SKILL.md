---
name: verdict
description: 综合裁决 — 融合基本面/动量/宏观/行业/情绪 5 维权重，主题生命周期调整，置信度校准。触发词：评分、裁决、judge、判断、综合。
---

# 综合裁决 (Comprehensive Verdict)

融合诊断的 7 维度评分，进行加权综合裁决。核心机制：主题生命周期调整 + 可证伪条件 + 置信度校准。

## 评分权重

| 维度 | 权重 | 来源 |
|------|------|------|
| 基本面 (价值+质量) | 40% | diagnosis value_score + quality_score |
| 技术面 (动量) | 20% | diagnosis momentum_score |
| 宏观 | 15% | diagnosis macro_score |
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

- **confidence < 0.6 → 阻止进入仓位调度** (MIN_CONFIDENCE)
- **数据质量加权**：按诊断各维度 source_citation 的质量分对维度评分降权（T3 → ×0.70，非 fresh → ×0.70，speculation → 不进入评分）
- **主题拥挤时降权 20%**
- **主题消退时中性化行业评分**
- **最终 confidence 必须反映最差维度的数据质量**

## 引用

- Python 实现: `src/routing/verdict.py`
- 主题管理: `src/information/topic_manager.py`
- 依赖 Skill: `diagnosis`, `positioning`, `topic-manager`
