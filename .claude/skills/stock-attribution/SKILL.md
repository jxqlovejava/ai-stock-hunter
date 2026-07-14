---
name: stock-attribution
description: 个股涨跌归因 — 回答"XX 为什么涨停/跌停/大涨/大跌"。强制 3 阶段 workflow：信息搜集(AttributionEngine 自动并行 7 通道)→多维归因(8 维度并行)→因果推断(信息源质量检查+主因排序)。输出格式严格遵守 guardrails.md 强制要求。触发词：为什么涨停、为什么跌停、为什么大涨、为什么大跌、涨跌原因、归因分析、attribute。
user-invocable: true
---

# 个股涨跌归因 (Stock Price Movement Attribution)

系统化回答"XX 股票为什么涨/跌"的完整分析管道。**强制 3 阶段，禁止跳过任何阶段。**

## 触发条件

当用户问以下问题时自动激活：
- "XX 为什么涨停 / 跌停"
- "XX 为什么大涨 / 大跌"
- "XX 涨跌原因"
- "分析 XX 近期走势"
- 任何包含"原因"+"股票代码/名称"+"涨/跌"的问法

## 工作流总览 (强制)

```
Phase 1: 信息搜集 (AttributionEngine 自动并行 — 7 通道)
  ├→ 资讯/新闻
  ├→ 公告 (巨潮)
  ├→ 行情/K线
  ├→ 资金面 (龙虎榜/北向/融资融券/大宗交易)
  ├→ 行业分类
  ├→ 🆕 周期品价格 (大宗商品/原材料) — 周期股自动拉取
  └→ 🆕 管理层指引 (投资者交流/业绩说明会/互动易)

Phase 2: 多维归因 (8 维度并行 AI 分析)
  ├→ macro-monitor (宏观背景)
  ├→ sector-research (板块联动)
  ├→ sentiment-analysis (情绪状态)
  ├→ topic-manager (主题生命周期)
  ├→ policy-tracker (行业政策)
  ├→ 资金面 + T+0 技术面
  ├→ 🆕 市场风格/资金主线 (板块热力图/主线在哪/板块被输血还是抽血)
  └→ 🆕 业务结构拆解 (各业务板块周期位置+利润贡献)

Phase 3: 因果推断 (串行，质量检查优先)
  ├→ 信息源质量检查 (T0-T3分级/时效性/STALE排除/交叉验证)
  ├→ 因果链推导 (8条传导通道)
  ├→ 主因→次因→噪音 排序
  └→ 强制格式输出 (guardrails.md 模板)
```

## Phase 1: AttributionEngine 自动数据搜集

```bash
python -m src attribute <code> [--date YYYY-MM-DD]
```

**AttributionEngine 自动完成：**
1. 并行搜集 7 个数据通道 (新闻/公告/行情/资金面/行业/周期品价格/管理层指引)
2. 每条数据点自动创建 `SourceCitation` (含 T0-T3 分级 + nature + freshness)
3. 新闻 > 12h 自动标记 `[STALE]`
4. 无法获取的维度自动标记 `[DATA_GAP]`
5. 输出 `QualitySummary` (各 tier 数量/质量分/示例)
6. 🆕 周期股自动拉取关联大宗商品/原材料价格走势 (行业→品种映射)
7. 🆕 强制搜索管理层投资者交流/业绩说明会/互动易回复

**AI 代理职责：**
- 审查 `raw_data_points`，确认数据完整性
- 识别引擎未覆盖的额外信息源 (如微博/知乎讨论)
- 补充 `last30days-cn` 搜索的社交媒体讨论
- 🆕 审查周期品价格数据：确认关联品种是否正确、价格趋势是否与归因逻辑一致
- 🆕 审查管理层指引：确认提取的关键判断是否准确、时效性是否有效

## Phase 2: 多维归因 (并行调用)

以下 6 个维度**必须全部覆盖**，缺失维度标记 `[DATA_GAP]` 并说明影响：

| 维度 | Skill | 要回答的问题 | 输出字段 |
|------|-------|-------------|---------|
| 宏观背景 | `macro-monitor` | 当前货币-信用象限？利好/利空成长股？美股隔夜走势对A股开盘影响？ | `macro_assessment` |
| 板块联动 | `sector-research` | 同行业其他股票是否联动？板块资金流向？ | `sector_assessment` |
| 情绪状态 | `sentiment-analysis` | 大盘恐慌/贪婪？个股情绪极端？A股实时市场数据（涨跌家数/成交额/涨跌停池）？ | `sentiment_assessment` |
| 主题周期 | `topic-manager` | 相关主题处于什么生命周期？拥挤度？ | `topic_assessment` |
| 行业政策 | `policy-tracker` | 近期有无行业政策变化？影响方向？ | 合并入 `sector_assessment` |
| 资金面 | a-stock-data | 北向/龙虎榜/融资融券/大宗交易 具体数据 | `capital_flow_assessment` |
| 技术面 | a-stock-data | T+0 盘中信号/量价关系/均线位置 | `technical_assessment` |
| 🆕 市场风格/资金主线 | `python -m src market` 板块热力图 + 涨停池 + 连板高度 + 主力资金行业流向 | 当前市场主线在什么板块？本标的所在板块是被输血还是被抽血？是否存在"买预期卖事实"的利好兑现？ | `style_assessment` |
| 🆕 业务结构拆解 | 财报数据 + 周期品价格 + 管理层指引 + 研报 | 公司有哪些业务板块？各自处于什么周期位置？哪个板块是主要拖累/驱动？各板块利润贡献占比？ | `business_structure_assessment` |

**并行执行**: 8 个维度可同时进行，互不依赖。

> **数据基础**: Phase 1 的 AttributionEngine 自动获取并注入 `enriched_macro`（含美股隔夜快照 S&P500/Nasdaq/Dow 和 A 股市场情绪数据）。AI Agent 在执行多维归因前，可运行 `python -m src market` 查看统一数据基础（美股隔夜 + A 股情绪 + 宏观象限）。

## Phase 3: 因果推断 (串行，质量检查优先)

### Step 3.0 — 信息源质量检查 (强制，不可跳过)

**必须在归因之前完成，禁止用过期新闻解释当日涨跌。**

执行以下检查：

1. **T0-T3 分级统计**: 用 `format_quality_table(result.quality)` 生成质量总览表
2. **时效性校验**: 
   - 新闻事件 > 6h → 标记 `[STALE]`，排除出主要归因
   - 政策/主题 > 12h → confidence × 0.7
   - 基本面 > 24h → confidence × 0.7
3. **STALE 排除**: 过期新闻只能作为"背景情绪铺垫"，不得作为当日直接驱动因素
4. **交叉验证**: 关键盘面数据 (涨跌幅/成交额/北向) 必须 ≥ 2 个独立来源
5. **标记要求**:
   - 无法验证的声明 → `[UNSOURCED]`
   - 推测性数据 → `[SPECULATION]`，confidence ≤ 0.5
   - 数据缺失 → `[DATA_GAP]`

### Step 3.1 — 因果链推导

使用 `src/macro/event_analyzer.py` 的 8 条传导通道：

| 通道 | 传导逻辑 |
|------|---------|
| 利率通道 | 货币政策 → 利率 → 贴现率 → 估值 |
| 信用通道 | 社融 → 信贷 → 企业融资 → 盈利预期 |
| 汇率通道 | 汇率 → 外资流动 → 北向资金 → 权重股 |
| 政策通道 | 产业政策 → 行业预期 → 估值重估 |
| 情绪通道 | 事件 → 情绪传染 → 追涨杀跌 → 超调 |
| 资金通道 | 龙虎榜/北向 → 主力动向 → 跟风盘 |
| 行业通道 | 板块联动 → 比价效应 → 板块内轮动 |
| 事件通道 | 公告/业绩/合同 → 基本面变化 → 重新定价 |

### Step 3.2 — 驱动因素排序

按以下规则排序：
1. **主因 (1个)**: 质量分最高 + 与股价变动时间最吻合 + fact 性质
2. **次因 (2-3个)**: 质量分中等 + 有一定解释力
3. **噪音**: 质量分低 / 推测 / 过期 / 相关性弱

### Step 3.3 — 区分事实/解读/推测

每个归因因素必须标注：
- `fact`: 可直接验证的数值/事件
- `interpretation`: 基于事实的分析推导
- `speculation`: 无法验证的猜测 → confidence ≤ 0.5

## 强制输出格式

**必须包含以下全部段落，不可省略：**

```
📋 信息源质量总览
| Tier | 数量 | 平均质量分 | 示例 |

🚫 过期信息（已排除）: [列出所有 STALE 条目]
⚠️ [DATA_GAP]: [列出数据缺口及影响]
整体 confidence: X.XX

📊 多维归因摘要
[宏观/板块/情绪/主题/资金面/技术面 各 1-2 句]

归因权重（按质量分加权）:
| 驱动因素 | 权重 | Tier | 性质 | 时效 |

🥇 主因: ...
🥈 次因: ...
🔊 噪音: ...
🔗 因果链: ...
📐 归因置信度: X%
```

## 执行 CHECKLIST (强制)

在输出归因结论前，逐项确认：

- [ ] Phase 1: `AttributionEngine.collect()` 已完成？raw_data_points 已审查？
  - [ ] 🆕 周期品价格数据已获取？（周期股必查——硅料/碳酸锂/螺纹钢/动力煤等）
  - [ ] 🆕 管理层近期投资者交流/业绩说明会/互动易已搜索？
- [ ] Phase 2: 8 个维度 (宏观/板块/情绪/主题/政策/资金+技术/市场风格/业务结构) 全部覆盖？
  - [ ] 缺失维度已标记 `[DATA_GAP]`？
  - [ ] 🆕 市场风格/资金主线已分析？（本板块是输血还是抽血？是否存在"买预期卖事实"？）
  - [ ] 🆕 业务结构已拆解？（各板块周期位置+利润贡献）
- [ ] Phase 3.0 — 信息源质量检查:
  - [ ] `📋 信息源质量总览` 表已输出？
  - [ ] 所有 citation 标注了 `tier` (T0-T3) 与 `nature` (fact/interpretation/speculation)？
  - [ ] 新闻事件 > 12h 已标记 `[STALE]` 并排除出主要归因？
  - [ ] `[DATA_GAP]` 已声明并说明影响？
  - [ ] `[UNSOURCED]` / `[SPECULATION]` 已标记？
  - [ ] 关键盘面数据 ≥ 2 源交叉验证？
- [ ] Phase 3.1 — 因果链已推导（至少覆盖 3 条传导通道）？
- [ ] Phase 3.2 — 驱动因素已按质量加权排序？
- [ ] Phase 3.3 — 每个因素已区分 fact/interpretation/speculation？
- [ ] `归因权重` 表已输出？
- [ ] 主因/次因/噪音 已明确标注？
- [ ] 整体 confidence 已计算？

## 护栏

- **禁止跳过信息源质量检查直接出结论**
- **禁止用 > 12h 的旧闻解释当日涨跌**
- **禁止输出无 source_citation 的断言**
- **归因结论必须区分 fact/interpretation/speculation**
- **confidence < 0.5 的归因必须明确告知用户"结论不确定"**
- **信息可得性 C 级标的 (冷门股)** → "查不到解释"本身也是信息，可能是技术面/资金面驱动

## 引用

- Python 实现: `src/routing/attribution.py` (AttributionEngine), `src/routing/attribution_types.py` (DTO), `src/routing/attribution_formatter.py` (格式器)
- CLI 入口: `python -m src attribute <code> [--date YYYY-MM-DD]`
- 依赖 Skill: `last30days-cn`, `a-stock-data`, `macro-monitor`, `sector-research`, `sentiment-analysis`, `policy-tracker`, `topic-manager`
- 输出标准: `.claude/rules/guardrails.md` §归因输出强制格式
- 因果链: `src/macro/event_analyzer.py`
