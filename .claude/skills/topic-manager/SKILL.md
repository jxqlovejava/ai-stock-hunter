---
name: topic-manager
description: 主题生命周期管理 — 4 阶段状态机 (EMERGING/SPREADING/CONSENSUS/CROWDED→FADING)、拥挤度监测、L2 权重调整。触发词：主题、热点、题材、概念、topic、生命周期。
---

# 主题生命周期管理 (Topic Manager)

管理 A 股市场主题/热点的完整生命周期，驱动 L2 权重动态调整。

## 生命周期阶段

```
EMERGING (出现) → SPREADING (扩散) → CONSENSUS (共识) → CROWDED (拥挤)
                                                              ↓
                                                          FADING (消退)
```

| 阶段 | 特征 | L2 调整 | 操作建议 |
|------|------|---------|---------|
| EMERGING | 少数人关注, 同花顺 reason tag 初现 | +10% | 深入研究, 早期布局 |
| SPREADING | 卖方研报增多, 社交媒体热议 | ±0% | 正常参与 |
| CONSENSUS | 普遍认可, 基金开始配置 | -10% | 谨慎持有 |
| CROWDED | 拥挤交易, 散户大量涌入 | -20% | 逐步减仓 |
| FADING | 成交量萎缩, 新主题替代 | 中性化到 50 | 清仓/回避 |

## 阶段转换阈值

```python
LIFECYCLE_THRESHOLDS = {
    "emerging_to_spreading": 30,   # 热度指数
    "spreading_to_consensus": 60,
    "consensus_to_crowded": 80,
    "crowded_to_fading": 30,       # 回落到 30
}
```

## 主题发现

- 同花顺 reason tag 自动提取
- 东财行业研报关键词
- 社交媒体情绪峰值

## 拥挤度计算

```
crowding_score = 
  基金重仓重叠率 (0.4) + 散户参与度 (0.3) + 媒体热度 (0.2) + 换手率异常 (0.1)
```

## 输出

```python
# L2 权重调整
topic_adjustments = {
    "AI+": +0.10,     # EMERGING
    "新能源": -0.10,  # CONSENSUS
    "芯片": -0.20,    # CROWDED
}
```

### 主题深扫输出（与 serenity-bottleneck 对齐）

当用户要「分析某主题/赛道」而非仅生命周期阶段时，在阶段标签之外强制：

1. **先排产业链层级**（≥3 层）再排代表公司  
2. 公司表：卡住的环节 / 为什么排这里 / 证据 / 主要风险  
3. **CONSENSUS/CROWDED 主题默认写入「降级热门」**并说明原因  
4. 下一步核验清单（公告/订单/毛利率/认证）  

## 护栏

- **不追逐 FADING 阶段主题**
- **CROWDED 阶段降权 20% 不可豁免**
- **单一主题相关仓位不超过 30%**
- **研究优先级不替代管道 diagnose 评分**

## 引用

- Python 实现: `src/information/topic_manager.py`, `src/information/schema.py`, `src/industry/serenity_workflow.py`
- 数据源: 同花顺 reason tag, 东财行业研报
- 依赖 Skill: `verdict`, `game-theory`, `serenity-bottleneck`
