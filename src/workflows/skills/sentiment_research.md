---
name: sentiment-research
description: 社交媒体情绪研究工作流 — 从查询分解到情绪合成
version: 1.0.0
author: Dexter
category: sentiment
requires:
  - search-tools
---

# 社交媒体情绪研究工作流

## 概述

通过社交媒体（微博 / 雪球 / 股吧）获取个体投资者情绪，用于辅助判断市场预期与短期波动方向。本工作流由 4 步构成。

## 步骤一：查询分解

### 1.1 核心实体识别

将原始分析需求拆解为可搜索的最小单元：

| 维度 | 示例 |
|------|------|
| 股票代码/名称 | 300750 / 宁德时代 |
| 行业标签 | 新能源 / 锂电 / 动力电池 |
| 事件关键词 | 定增 / 减持 / 业绩预告 / 涨价 |
| 情绪锚点 | 利空出尽 / 利好兑现 / 恐高 / 抄底 |
| 时间范围 | 近 1 周 / 近 1 月 / 中报窗口期 |

### 1.2 生成查询组合

对所有实体进行笛卡尔积组合，排除无意义或冗余组合：

```
query_pool = [
  "宁德时代 业绩预告",
  "300750 定增",
  "新能源 锂电 产能",
  "宁德时代 动力电池 竞争",
  ...
]
```

### 1.3 查询优化

- 每条查询控制在 4-6 个词
- 太宽泛 → 加限定词（如"2025 年 宁德 竞争格局"）
- 太狭窄 → 去掉低区分度词（如"公司"、"我们认为"）

## 步骤二：多源搜索

### 2.1 来源渠道

| 渠道 | 特征 | 权重 | 适用场景 |
|------|------|------|----------|
| 微博 | 最及时，情绪极化 | 0.30 | 事件驱动、散户情绪 |
| 雪球 | 偏理性，长文多 | 0.40 | 基本面讨论、估值分歧 |
| 股吧 | 噪声大，高频 | 0.20 | 短期情绪温度、换手信号 |
| 公众号 | 慢但深度 | 0.10 | 行业趋势、长期预期 |

### 2.2 搜索执行

对每条查询，逐一搜索各渠道：

```python
for query in query_pool:
    for source in sources:
        results = search(source, query, time_range=...)
        deduplicated = dedup(results)   # 按 URL / 内容相似度去重
        scored = score_results(deduplicated)  # 按赞评数/影响力加权
        all_collected.extend(scored)
```

### 2.3 去重策略

- 完全重复（相同文本）→ 保留一条，合并互动数据
- 高度相似（>85% 语义相似度）→ 保留影响力较高的一条
- 跨平台相同事件报道 → 标注交叉验证标志

## 步骤三：情绪提取

### 3.1 单条文本情绪分析

每条内容提取以下维度：

| 维度 | 取值 | 说明 |
|------|------|------|
| polarity | -1.0 ~ +1.0 | 整体情感极性（负/正） |
| arousal | 0.0 ~ 1.0 | 情绪唤醒度（平静/激动） |
| conviction | 0.0 ~ 1.0 | 表达确定性（不确定/确信） |
| topic_tags | list[str] | 提及的主题标签 |
| influence | 0.0 ~ 1.0 | 综合影响力（粉丝 + 互动归一化） |

### 3.2 情绪时间序列

将单条情绪按日聚合，生成日度情绪指标：

```
daily_sentiment = weighted_avg(
    scores = [s.polarity for s in day_posts],
    weights = [s.influence * s.arousal for s in day_posts],
)
```

### 3.3 异常检测

- 单日情绪偏离 20 日均值 > 2σ → 标记为情绪异常日
- 情绪在 3 日内连续异向 → 标记为情绪反转信号

## 步骤四：情绪合成与报告

### 4.1 跨源合成

按权重合并三个渠道的情绪：

```
consensus = (
    0.30 * weibo_signals.daily_sentiment
    + 0.40 * xueqiu_signals.daily_sentiment
    + 0.20 * stockbar_signals.daily_sentiment
    + 0.10 * wechat_signals.daily_sentiment
)
```

### 4.2 输出结构

```json
{
  "symbol": "300750",
  "report_date": "2026-07-08",
  "consensus_sentiment": 0.12,
  "sentiment_trend": "mildly_bullish",
  "data_quality": {
    "total_posts": 2840,
    "influential_posts": 132,
    "sources_available": ["weibo", "xueqiu", "guba", "wechat"],
    "coverage_score": 0.85
  },
  "key_topics": [
    {"topic": "产能过剩", "volume": 0.35, "sentiment": -0.42},
    {"topic": "海外订单", "volume": 0.28, "sentiment": 0.55},
    {"topic": "技术路线", "volume": 0.18, "sentiment": 0.22},
    {"topic": "高管增持", "volume": 0.12, "sentiment": 0.68}
  ],
  "anomalies": [],
  "signals": [
    {"type": "divergence", "strength": 0.6, "description": "股价下跌但情绪企稳"}
  ],
  "caveats": [
    "[DATA_GAP] 雪球近 3 日接口限流，数据量偏少",
    "[SPECULATION] 2 篇提及定增目标价的内容来源不明"
  ],
  "confidence": 0.75
}
```

### 4.3 注意事项

- 社交媒体数据不能独立作为交易依据
- 异常情绪日需要人工核实是否由刷屏/水军导致
- 小市值股票样本量天然偏少，confidence 需相应下调
- 重大事项（财报、政策等）窗口期情绪波动不具持续性

## 全局检查清单

- [ ] 查询覆盖至少 3 个维度（个股 + 行业 + 事件）
- [ ] 来源渠道 ≥ 2 个
- [ ] 单条情绪分析记录 polarity / arousal / conviction
- [ ] 每日情绪已按影响力加权聚合
- [ ] 异常日已标记并说明原因
- [ ] 跨源一致性已检查
- [ ] [DATA_GAP] / [SPECULATION] 标注完整
- [ ] 最终 confidence 反映样本量与数据质量
- [ ] 报告未输出具体买卖建议
