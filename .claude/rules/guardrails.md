---
description: 统一护栏规则 — 所有分析和交易输出必须遵守的数据质量与安全标准
---

# 统一护栏规则 (Unified Guardrails)

## 数据来源规则

### 强制标注来源
每条分析数据点必须携带 `SourceCitation`，包含：
- `provider` — 数据来源（guosen / mootdx / akshare / tencent / huatai / eastmoney）
- `field` — 数据字段名
- `fetch_timestamp` — 获取时间戳
- `data_freshness` — 有效期（timedelta）
- `confidence` — 来源置信度 0.0–1.0

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

### 数据新鲜度上限
| 数据类型 | 最长老化 | 超期处理 |
|---------|---------|---------|
| 实时行情 | 5 分钟 | 标记 STALE |
| 日线/因子 | 1 小时 | 标记 STALE |
| 财务数据 | 24 小时 | 标记 STALE |
| 主题/政策 | 12 小时 | 标记 STALE |
| 分析师报告 | 7 天 | 标记 STALE |

## 输出护栏

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
- [ ] confidence 已计算并标注
- [ ] 无 [UNSOURCED] 漏标
- [ ] data_freshness 未过期
- [ ] 无禁止内容
- [ ] A 股排除规则已执行
