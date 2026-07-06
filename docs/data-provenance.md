# 数据溯源与质量加权规范

> 本规范是 `.claude/rules/guardrails.md` 的配套文档，供 fork 本项目的开发者/使用者参考。
> 目的是保证任何人运行分析时，都能清楚看到：数据从哪来、是事实还是推测、置信度多少、以及数据质量如何影响最终评分。

## 1. 数据溯源三要素

每个被分析引用的数据点，都必须携带 `SourceCitation`，并至少包含：

```python
from src.data.source_citation import SourceCitation

SourceCitation(
    provider="mootdx",           # 数据源标识
    field="pe_ttm",              # 字段名
    fetch_timestamp=...,         # 获取时间
    data_freshness=...,          # 有效期
    confidence=0.85,             # 来源基准置信度
    tier="secondary",            # 数据级别：primary / secondary / tertiary
    nature="fact",               # 数据性质：fact / interpretation / speculation
)
```

### 1.1 数据级别（tier）

| 级别 | 含义 | 示例 | 典型置信度调整 |
|------|------|------|----------------|
| `primary` | 一手来源：交易所、公司公告、央行/统计局官方 | 巨潮公告、交易所实时行情 | +0.10 |
| `secondary` | 二手来源：券商、财经数据商直接整理 | mootdx、tonghuashun、guosen | 0.00 |
| `tertiary` | 三手来源：聚合、爬虫、模型推断、媒体报道 | akshare 聚合、LLM 情感得分、资讯 NLP | -0.10 |

### 1.2 数据性质（nature）

| 性质 | 含义 | 使用规则 |
|------|------|----------|
| `fact` | 可直接验证的原始数值 | 可直接进入评分模型 |
| `interpretation` | 基于事实的加工、计算或行业理解 | 必须说明推导逻辑，方可进入评分 |
| `speculation` | 无法验证的前瞻、传闻、模型猜测 | 必须标记 `[SPECULATION]`，置信度 ≤ 0.5，不直接参与评分，仅作风险参考 |

## 2. 数据质量加权规则

L1 / L2 必须按数据质量对子评分和最终 `confidence` 进行调整。

### 2.1 数据新鲜度

`SourceCitation.is_fresh` 为 `False` 时：

- 对应维度 confidence 乘以 `0.7`
- 输出中标记 `[STALE]`

### 2.2 数据级别

```textneffective_confidence = base_confidence
if tier == "tertiary":
    effective_confidence *= 0.85
elif tier == "primary":
    effective_confidence = min(1.0, effective_confidence * 1.10)
```

### 2.3 数据性质

- `fact`：直接使用
- `interpretation`：confidence 乘以 `0.90`
- `speculation`：不参与评分，仅出现在风险/可证伪条件中

### 2.4 数据缺失

如果关键数据源失败（例如 AKShare 社融、DR007 拉取失败）：

- 标记 `[DATA_GAP]`
- 说明缺失字段对哪个维度产生影响
- 该维度最高得分不超过 55，confidence 乘以 `0.85`

### 2.5 综合 confidence 原则

最终 `confidence` 应反映最差维度的数据质量：

```python
confidence = min(
    dimension_confidences,
    overall_data_quality_score
)
```

## 3. 完整分析 Workflow

**默认情况下，单只股票分析必须依次输出以下全部阶段。** 只有当用户明确指定只看某个步骤（例如"只做 Alpha 分析"、"只做军规校验"）或进入深度主题研究时，才可以聚焦该步骤。

标准阶段：

1. **数据获取** — 行情、财务、宏观、高管、主题
2. **军规校验** — `DoctrineChecker`
3. **L0 门禁** — `L0Gate`
4. **宏观 / 北向 / 盈利修正 / 主题生命周期** — 增强上下文
5. **Alpha Lens** — 叙事生命周期、共识-现实缺口
6. **L1 多维分析** — 宏观/价值/质量/动量/情绪/瓶颈
7. **质量审查** — `MultiAgentQualityChecker`
8. **博弈论分析** — 主导玩家、拥挤度、杠杆、席位、价格冲击
9. **投资思维模型匹配** — 风险偏好、能力圈、行为偏差
10. **L2 法官裁决** — 加权评分 + 置信度 + 可证伪条件
11. **L3 交易员** — 信号→仓位映射
12. **L4 风控官** — 硬约束裁剪
13. **投资者偏好 / 能力圈校验** — 仓位约束、行业能力匹配

每一层输出都应包含本层使用的 `SourceCitation` 列表，以及受数据质量影响的说明。

## 4. 输出示例

```markdown
- 宏观评分：60/100（confidence 0.70）
  - M1-M2 剪刀差 1.66 `[fact, primary, akshare]`
  - 社融增速 `[DATA_GAP]`，因 AKShare SSL 失败，宏观权重下调
- 动量评分：41/100（confidence 0.75）
  - 北向净流入 -40.38 亿 `[fact, secondary, mootdx]`
  - 日内趋势 neutral `[interpretation, tertiary, model]`
```

## 5. 开发者 checklist

新增数据源或修改评分逻辑时，请确认：

- [ ] 每条新数据都有 `SourceCitation`
- [ ] `tier` 和 `nature` 已正确填写
- [ ] 推测性数据不会直接进入评分
- [ ] 数据缺失时标记 `[DATA_GAP]` 并下调权重
- [ ] L2 最终 `confidence` 反映了最差维度
- [ ] 运行 `pytest tests/` 通过

## 6. 相关文件

- `.claude/rules/guardrails.md` — 护栏总纲
- `src/data/source_citation.py` — `SourceCitation` 数据类型
- `src/quality/checker.py` — 质量审查器
- `src/routing/orchestrator.py` — 完整 workflow 编排
