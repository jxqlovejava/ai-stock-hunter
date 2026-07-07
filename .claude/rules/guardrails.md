---
description: 统一护栏规则 — 所有分析和交易输出必须遵守的数据质量与安全标准
---

# 统一护栏规则 (Unified Guardrails)

## 完整分析 Workflow（强制）

**默认情况下，任何单只股票分析都必须跑完全部阶段。** 只有在用户明确指定某个特定步骤（如"只看 Alpha Lens"、"只做军规校验"）或明确进入某个深度主题（如"对某公司做深度行业分析"）时，才允许聚焦该步骤。

标准 workflow：

1. **数据获取** — DataWorker 拉取行情/财务/宏观/高管数据
2. **军规校验** — DoctrineChecker 硬规则过滤
3. **L0 门禁** — ST/次新/流动性/涨跌停/停牌检查
4. **宏观 / 北向 / 盈利修正 / 主题生命周期** — 增强上下文注入
5. **Alpha Lens** — 三维 Alpha 评估与叙事生命周期
6. **L1 多维分析** — 宏观/价值/质量/动量/情绪/瓶颈
7. **质量审查** — 新鲜度/一致性/泄露/可解释性/安全/溯源
8. **博弈论分析** — 主导玩家/拥挤度/杠杆/席位/价格冲击
9. **投资思维模型匹配** — 风险偏好/能力圈/行为偏差校验
10. **L2 法官裁决** — 加权评分 + 置信度 + 可证伪条件
11. **L3 交易员** — 信号→仓位映射
12. **L4 风控官** — 硬约束裁剪
13. **投资者偏好 / 能力圈校验** — 仓位约束与能力圈匹配

每一层结果必须可独立查看，禁止只输出最终结论。

## 数据来源规则

### 强制标注来源
每条分析数据点必须携带 `SourceCitation`，包含：
- `provider` — 数据来源（guosen / mootdx / akshare / tencent / huatai / eastmoney）
- `field` — 数据字段名
- `fetch_timestamp` — 获取时间戳
- `data_freshness` — 有效期（timedelta）
- `confidence` — 来源置信度 0.0–1.0
- `tier` — 数据级别：`primary`（一手）/ `secondary`（二手）/ `tertiary`（三手/推断）
- `nature` — 数据性质：`fact`（事实）/ `interpretation`（解释）/ `speculation`（推测）

### 来源置信度标准
| Provider | 基准置信度 | 条件 |
|----------|-----------|------|
| guosen | 0.90 | 券商官方 API |
| mootdx | 0.85 | 通达信标准行情 |
| eastmoney | 0.80 | 东财 datacenter |
| huatai | 0.80 | 华泰市场洞察 |
| akshare | 0.70 | 爬虫聚合，可能延迟 |
| tencent | 0.75 | 腾讯行情 |
| cninfo (巨潮) | 0.90 | 官方公告 |
| tonghuashun | 0.80 | 同花顺 iFinD |

### 数据级别（tier）与性质（nature）标准

| 级别 | 定义 | 示例 | 基准置信度调整 | 代码常量 |
|------|------|------|----------------|----------|
| `primary` | 一手来源：交易所、公司公告、央行/统计局官方 | 巨潮公告、交易所行情 | +0.10 | `T0` |
| `secondary` | 二手来源：券商、财经数据商直接整理 | mootdx、tonghuashun、guosen | 0.00 | `T1` |
| `tertiary` | 三手来源：聚合、爬虫、模型推断、媒体报道 | akshare 聚合、LLM 推导、资讯 NLP | -0.10 | `T2`/`T3` |

> **术语对照**: guardrails.md 使用 `primary/secondary/tertiary`，代码使用 `T0/T1/T2/T3`。
> - `T0` = primary（一手官方） — cninfo、exchange、pboc
> - `T1` = secondary（权威数据商） — mootdx、guosen、tonghuashun、eastmoney
> - `T2` = tertiary（聚合/爬虫） — tencent、akshare、miaoxiang
> - `T3` = tertiary（推测/未验证） — llm_derived、unsourced、game_theory

| 性质 | 定义 | 处理规则 |
|------|------|----------|
| `fact` | 可直接验证的原始数值 | 直接使用 |
| `interpretation` | 基于事实的加工/计算/行业理解 | 需说明推导逻辑 |
| `speculation` | 无法验证的前瞻/传闻/模型猜测 | 必须标记 `[SPECULATION]`，置信度 ≤ 0.5 |

### 数据质量加权

L1/L2 必须按数据质量对评分进行加权或降权：

-  freshness 过期 → 对应维度 confidence 乘 0.7
-  `tier=tertiary` → confidence 乘 0.85
-  `nature=speculation` → 该数据点不进入评分，仅作风险参考
-  关键数据缺失（如宏观社融、DR007）→ 标记 `[DATA_GAP]`，并在对应维度降低权重
-  单一维度依赖的数据源置信度 < 0.6 → 该维度最高得分不超过 55

最终 `confidence` 必须反映最差维度的数据质量。

### 强制 confidence
每个综合评分/结论必须携带 `confidence: float`（0.0–1.0）。
- `confidence >= 0.8` → 高置信度，可直接使用
- `0.6 <= confidence < 0.8` → 中等置信度，需标注风险
- `confidence < 0.6` → 低置信度，阻止进入 L3 交易阶段

### [UNSOURCED] 标记
以下情况必须标记 `[UNSOURCED]`：
- 无法追溯到具体数据源的数字
- LLM 推测的数值
- 未经验证的市场传闻
- 非公开渠道获取的信息

### 禁止内容
- 禁止输出具体买卖建议（"建议买入 X 股 Y 股票"）
- 禁止输出未经人工审核的交易信号
- 禁止引用未经验证的"内幕消息"

## Agent 权限护栏

### 角色权限矩阵
| Agent | Read | Analyze | Write Signal | Write File |
|-------|------|---------|-------------|------------|
| orchestrator-agent | ✅ | ✅ | ❌ | ❌ |
| data-worker | ✅ | ❌ | ❌ | ❌ |
| analysis-worker | ✅ | ✅ | ❌ | ❌ |
| signal-writer | ✅ | ✅ | ✅ | ✅ |

### 关键规则
1. **仅 signal-writer 可生成交易信号**
2. **所有信号必须经过 L4 风控检查**
3. **confidence < 0.6 的分析不得进入 L3**
4. **关键决策节点要求人工审批后继续**

## A 股特定护栏

### 排除规则（硬性）
- ST / *ST 股票一律排除
- 上市不满 60 个自然日的新股排除
- 日成交额低于 5000 万的低流动性股票排除
- 连续跌停股票排除
- 有退市风险的股票提示

### 风险提示（软性）
- 商誉占比超过净资产 30% — 提示减值风险
- 近 12 个月有违规记录 — 标记 FLAGGED
- 市盈率超过行业均值 2 倍 — 标记估值偏高
- 前 5 大客户集中度 > 80% — 标记客户风险

## 验证清单

分析输出前检查：
- [ ] 所有数字有 source_citation
- [ ] 每个 citation 标注 `tier` 与 `nature`
- [ ] 推测性数据已标记 `[SPECULATION]` 或 `[UNSOURCED]`
- [ ] 缺失/失败数据源已标记 `[DATA_GAP]` 并说明影响
- [ ] confidence 已计算并标注，且反映数据质量加权
- [ ] 无 [UNSOURCED] 漏标
- [ ] data_freshness 未过期
- [ ] 完整 workflow 各阶段输出均已展示
- [ ] 无禁止内容
- [ ] A 股排除规则已执行
