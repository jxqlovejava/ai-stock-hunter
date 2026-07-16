---
name: serenity-bottleneck
description: Serenity 式供应链瓶颈研究 — 先层后票、研究优先级 scorecard、卡点挑战、A 股证据路径。触发词：Serenity、产业链卡点、瓶颈研究、先排层级、优先研究、挑战 thesis、深度调研主题。
---

# Serenity 瓶颈研究 (serenity-bottleneck)

把主题/热点变成**有证据的优先研究名单**（非买卖指令）。  
与 cyberagent 物理瓶颈身份分正交：身份分看「是否控制卡点」，研究优先级看「是否值得先挖」。

> 本地参考：`~/Documents/workspace/serenity-skill`  
> 代码：`src/industry/serenity_scorecard.py`、`src/industry/serenity_workflow.py`

## 请求路由

| 模式 | 触发 | 动作 |
|------|------|------|
| Theme scan | 主题/赛道/概念深研 | 完整先层后票 workflow |
| Single-company challenge | 挑战单票 / 是否核心供应商 | 卡点挑战小节 |
| Candidate comparison | 多票对比 | 五列表 + 研究优先级分 |
| Research partner | 陪练讨论 | 每轮一判断 + 一问 |
| Learning | 学方法 | 需求→系统变化→卡点→证据 |

## 强制 9 步（主题扫）

1. 定范围（市场/主题/时间窗 3–12 月）
2. 叙事 → 系统变化（物理约束：功率/带宽/良率/纯度…）
3. 画 8 层价值链
4. **先排稀缺层**（再排公司）
5. 建候选宇宙（深扫 ≥20）
6. 证据分级（深扫 ≥25 源；不够标初扫）
7. 双排名：层排名 + 公司排名
8. 失败条件
9. 下一步核验

## 强制输出格式

```
先排产业链层级，再排公司。我会优先看这几层：[L1]、[L2]、[L3]。原因是…

### 1. 产业链层排名
| 排名 | 产业链层级 | 排序原因 |

### 2. 优先研究公司
| 标的 | 卡住的环节 | 为什么排这里 | 关键证据 | 主要风险 |

### 3. 降级的热门方向（≥1 条）
### 4. 下一步核验
```

研究用语：优先研究名单 / 产业链卡点 / 什么情况说明判断错了。  
**禁止**保证收益、直接下单指令。

## 打分卡

```python
from src.industry.serenity_scorecard import score_from_ratings, estimate_from_bottleneck_type

# 完整 8 因子 0–5 + 惩罚
result = score_from_ratings(ticker="...", factors={...}, penalties={...})
# 或从 OWNER/ADJACENT 启发式
result = estimate_from_bottleneck_type("owner")
# final_score 0–100；verdict: Top/High/Track/Early lead
```

因子权重：需求拐点15 / 架构绑定10 / 卡点严重15 / 供应集中12 / 扩产难度12 / 证据15 / 估值错位11 / 催化10。  
惩罚（×2）：稀释/治理/地缘/流动性/炒作/会计/周期/替代路线。

## A 股证据 checklist

年报季报公告 · 问询函 · 互动易 · 招投标/认证 · 环评能评 · 专利标准 · 应收存货现金流 · 关联交易/定增/质押/商誉。

Red flag 降权：单客户传闻、纯社媒驱动、先融资后兑现、应收存货飞、毛利率不跟叙事。

## 与白泽管道

| 场景 | 接法 |
|------|------|
| 场景四主题 | 本 skill 格式覆盖综合输出 |
| diagnose | 瓶颈块含研究优先级 + 失败条件 + 下一步 |
| 荐股阶段三 | 管道分外并列 `research_priority_score` |
| L1 bottleneck | `BottleneckAnalysis.apply_serenity_defaults()` |

## 校验

```python
from src.industry.serenity_workflow import validate_theme_scan_completeness
gaps = validate_theme_scan_completeness(theme_result)  # 空=通过
```

## 引用

- `src/industry/serenity_scorecard.py`
- `src/industry/serenity_workflow.py`
- `src/industry/bottleneck.py`
- 依赖 skill: `sector-research`, `topic-manager`, `diagnosis`
