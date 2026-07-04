# A 股数据源深度分析：华泰 vs 国信 vs AKShare

**Date**: 2026-07-04
**Status**: Phase 0 前置研究

---

## 一、三源能力矩阵

### 1.1 华泰证券 (HTSC) — 5 个 Claude Code Skill

| Skill | 接口类型 | 核心能力 |
|-------|---------|---------|
| `query-indicator` | NLP→Markdown | 实时/历史行情、财务估值指标、多标的对比 |
| `financial-analysis` | NLP→Markdown (2 tools) | `diagnosisStock` 个股诊断 + `marketInsight` 市场洞察（大盘/板块/宏观事件） |
| `select-stock` | NLP→Markdown | 自然语言条件选股（≤10 只） |
| `a-share-paper-trading` | CLI→JSON (7 tools) | 模拟交易全流程：行情/持仓/下单/撤单/成交 |
| `watchlist-management` | CLI→JSON (2 tools) | 自选股添加/查询 |

**认证**: `HT_APIKEY` + 后端 `https://ai.zhangle.com`

### 1.2 国信证券 (Guosen) — 6 个 Claude Code Skill

| Skill | 接口类型 | 核心能力 |
|-------|---------|---------|
| `gs-stock-market-query` | REST API→JSON (6 endpoints) | 实时行情、多股行情、资金流向、涨跌幅排名、关联板块、历史 K 线 |
| `gs-stock-financial-query` | REST API→JSON (6 endpoints) | A 股/港股三表（利润表/资产负债表/现金流量表），支持季度/年度/多期 |
| `gs-smart-stock-picking` | REST API→JSON | 自然语言条件选股（≤100 只），支持 stock/fund/HK/US/NEEQ/index |
| `gs-economy-query` | REST API→JSON | 全球宏观经济：GDP/CPI/PPI/M2/PMI/就业/贸易/大宗商品 |
| `gs-fund-compare` | REST API→JSON | 场外基金多维度对比 |
| `gs-etf-filter` | REST API→JSON | ETF 榜单筛选与多维分析 |

**认证**: `GS_API_KEY` + 后端 `https://dgzt.guosen.com.cn/skills`

### 1.3 AKShare — Python 开源库

| 能力 | 覆盖 |
|------|------|
| A 股全市场行情 | 日/周/月 K 线、实时分时、个股基本面 |
| 板块资金流 | 行业/概念板块资金净流入流出 |
| 龙虎榜 | 每日龙虎榜明细（营业部/机构买卖） |
| 北向资金 | 沪深股通每日额度/持仓 |
| 融资融券 | 每日两融余额/标的 |
| 新闻公告 | 个股公告、财经新闻 |
| 宏观数据 | 中国/全球宏观经济指标 |
| 期货/外汇/债券 | 多市场数据 |

**认证**: 无（免费开源） | **数据格式**: pandas DataFrame | **延迟**: 取决于数据源

---

## 二、关键差异（决定架构的关键发现）

### 2.1 接口范式差异

```
华泰:  用户自然语言 → LLM 解析 → 后端服务 → Markdown 答案
国信:  结构化参数 → REST API → 结构化 JSON
AKShare: Python 函数调用 → 网络请求 → pandas DataFrame
```

**这是最关键的差异**。华泰 skill 返回自由文本 Markdown，国信返回结构化 JSON，AKShare 返回 DataFrame。

| 维度 | 华泰 | 国信 | AKShare |
|------|------|------|---------|
| **可编程性** | ⚠️ 低（需要解析 Markdown） | ✅ 高（结构化 JSON） | ✅ 最高（DataFrame） |
| **数据确定性** | ⚠️ 中（NLP 可能遗漏/误解） | ✅ 高（固定 schema） | ✅ 高（固定 API） |
| **延迟** | 中等（NLP + LLM 处理） | 低（直接 API 查询） | 低-中（数据下载） |
| **回测可用性** | ❌ 不可用 | ✅ 可用 | ✅ 最佳 |
| **交互式使用** | ✅ 最佳（自然对话） | ⚠️ 中（需要精确参数） | ❌ 差（需要写代码） |

### 2.2 能力重叠矩阵

| 数据维度 | 华泰 | 国信 | AKShare | 推荐主源 |
|---------|------|------|---------|---------|
| 实时行情 | ✅ NLP | ✅ 结构化 API | ✅ DataFrame | **国信**（结构化） |
| 历史 K 线 | ✅ NLP | ✅ 结构化 API | ✅ DataFrame | **国信**（结构化） |
| 财务三表 | ✅ NLP | ✅ 结构化 API | ✅ DataFrame | **国信**（结构化） |
| PE/PB/ROE 等估值指标 | ✅ NLP | ❌ | ✅ DataFrame | **AKShare**（全市场扫描） |
| 资金流向 | ❌ | ✅ 结构化 API | ✅ DataFrame | **国信**（实时） |
| 涨跌幅排名 | ❌ | ✅ 结构化 API | ✅ DataFrame | **国信**（实时） |
| 板块分析 | ✅ NLP | ✅ 关联板块 API | ✅ DataFrame | 国信（数据）+ 华泰（解读） |
| 条件选股 | ✅ NLP（≤10 只） | ✅ NLP（≤100 只） | ✅ 自定义 | **国信**（量更大） |
| 个股诊断 | ✅ **独有** | ❌ | ❌ | **华泰**（独有能力） |
| 市场洞察 | ✅ **独有** | ❌ | ❌ | **华泰**（独有能力） |
| 宏观数据 | ❌ | ✅ 结构化 API | ✅ DataFrame | **国信**（结构化） |
| 龙虎榜 | ❌ | ❌ | ✅ **独有** | **AKShare**（独有能力） |
| 两融数据 | ❌ | ❌ | ✅ **独有** | **AKShare**（独有能力） |
| 北向资金明细 | ❌ | ✅ 资金流向 | ✅ DataFrame | 国信（实时）+ AKShare（历史） |
| 模拟交易 | ✅ **独有** | ❌ | ❌ | **华泰**（独有能力） |
| 自选股管理 | ✅ **独有** | ❌ | ❌ | **华泰**（独有能力） |
| 美股/港股行情 | ❌ | ✅ 结构化 API | ✅ 部分 | **国信** |
| 基金/ETF | ❌ | ✅ | ✅ | **国信** |

### 2.3 独有能力（不可替代）

| 源 | 独有能力 | 系统价值 |
|----|---------|---------|
| **华泰** | 个股诊断 (diagnosisStock) | L1 分析师 AI 增强——AI 写的诊断报告 |
| **华泰** | 市场洞察 (marketInsight) | 宏观事件→A 股影响分析 |
| **华泰** | 模拟交易 | Phase 3+ 回测之外的实盘模拟验证 |
| **AKShare** | 龙虎榜 | game_theory 模块的游资操盘手法数据源 |
| **AKShare** | 两融数据 | 杠杆资金情绪指标 |
| **国信** | 美股/港股行情 | 跨市场传导模块 |

---

## 三、华泰 skill 的致命限制（必须正视）

### 3.1 华泰 select-stock 不能作为系统选股引擎

原因：
- 返回 ≤10 只股票，无法做全市场扫描
- 内部是黑盒 NLP → 无法审计选股逻辑
- 无法复现结果（同样的 query 不同时间可能返回不同结果）
- **违反计划的核心原则**：「回测与实盘使用同一信号生成代码路径」

### 3.2 华泰 query-indicator/financial-analysis 不能用于回测数据管道

原因：
- 返回 Markdown 自由文本，无法可靠地提取结构化数据
- 每个 query 的延迟不可控（NLP 处理时间）
- 每次调用都是黑盒，无法做数据一致性校验

### 3.3 华泰 skill 的正确定位

**华泰 = 交互式 AI 分析师，不是数据管道。**

- ✅ 适用：用户对话中的「帮我看看这只股票」← 直接透传 Markdown 回答
- ✅ 适用：L1 分析师中的 AI 增强——NLP 解读基本面，补充量化因子看不到的定性信息
- ❌ 不适用：回测数据管道、因子计算、全市场扫描、信号生成

---

## 四、推荐架构：数据聚合层设计

### 4.1 分层模型

```
┌─────────────────────────────────────────────────────┐
│                   System Consumers                   │
│   L0保安 │ L1分析师 │ L2法官 │ L3交易员 │ 回测引擎      │
│   game_theory │ macro │ sentiment │ factors         │
├─────────────────────────────────────────────────────┤
│                 DataAggregator                       │
│  统一查询接口 · 多源降级 · 交叉验证 · 缓存            │
├──────────┬──────────────┬───────────────────────────┤
│ 国信适配器 │  华泰适配器   │  AKShare 适配器            │
│ REST→Model│ NLP→Model    │  DataFrame→Model          │
├──────────┼──────────────┼───────────────────────────┤
│ 国信 API  │  华泰 Skills  │  AKShare Library           │
│ GS_API_KEY│  HT_APIKEY   │  (no auth)                │
└──────────┴──────────────┴───────────────────────────┘
```

### 4.2 统一数据模型 (Pydantic)

```python
# src/data/schema.py
class Quote(BaseModel):
    symbol: str
    name: str
    price: float
    change_pct: float
    volume: int
    turnover: float
    source: Literal["guosen", "huatai", "akshare"]
    fetched_at: datetime

class Financials(BaseModel):
    symbol: str
    report_period: str       # "2025Q4"
    revenue: float
    net_profit: float
    total_assets: float
    operating_cash_flow: float
    # ... more standardized fields
    source: Literal["guosen", "akshare"]

class FundamentalMetrics(BaseModel):
    symbol: str
    pe_ttm: float | None
    pb: float | None
    roe: float | None
    debt_to_equity: float | None
    source: list[str]  # multi-source
    cross_validated: bool
    dispute: bool  # True if sources disagree >5%
```

### 4.3 数据源优先级策略

```python
# src/data/aggregator.py
SOURCE_PRIORITY = {
    # 结构化数据优先用国信
    "quote":          ["guosen", "akshare"],
    "financials":     ["guosen", "akshare"],
    "fund_flow":      ["guosen", "akshare"],
    "ranking":        ["guosen", "akshare"],
    "history_kline":  ["guosen", "akshare"],
    "macro":          ["guosen", "akshare"],

    # AI 分析能力优先用华泰
    "stock_diagnosis":   ["huatai"],           # 独有
    "market_insight":    ["huatai"],           # 独有

    # 全市场扫描用 AKShare
    "universe_scan":     ["akshare", "guosen"],
    "factor_calculation": ["akshare"],          # 需要 DataFrame 操作
    "dragon_tiger":      ["akshare"],           # 独有
    "margin_trading":    ["akshare"],           # 独有
    "northbound_detail": ["akshare", "guosen"],
}
```

### 4.4 交叉验证规则

```python
CROSS_VALIDATE_FIELDS = [
    "pe_ttm", "pb", "roe", "revenue", "net_profit",
    "total_assets", "operating_cash_flow"
]

DISPUTE_THRESHOLD = 0.05  # 5% discrepancy → DISPUTED
```

### 4.5 文件结构

```
src/data/
├── __init__.py
├── base.py              # DataProvider ABC
├── schema.py            # 统一 Pydantic 模型
├── guosen.py            # 国信适配器（REST → Model）
├── huatai.py            # 华泰适配器（NLP Skill → Model）
├── akshare.py           # AKShare 适配器（DataFrame → Model）
├── aggregator.py        # 多源聚合 + 优先级 + 降级
├── cache.py             # TTL 缓存层
└── cross_validator.py   # 交叉验证 + 差异检测
```

---

## 五、关键设计决策

### 决策 1: 回测与实盘必须走同一数据管道

```
❌ 回测用 AKShare DataFrame 直接算，实盘用华泰 NLP
✅ 所有消费者通过 DataAggregator.get_financials() → 统一返回 Financials model
   底层自动路由到国信→AKShare（fallback）
```

### 决策 2: 华泰只用于「人类可读」的输出增强

```
❌ 用华泰 select-stock 做全市场选股
✅ 系统用自己的因子引擎 + AKShare 做全市场扫描
   华泰 financial-analysis 只用于 L1 报告中的 AI 解读段落
```

### 决策 3: 至少 2 源验证才进入分析管道

```
❌ 单一来源的 PE/PB/ROE 直接送入 L1
✅ ≥2 源交叉验证通过 → L1
   仅 1 源 → 标注 SINGLE_SOURCE，置信度打折
   2 源差异 > 5% → 标注 DISPUTED，不进入管道
```

### 决策 4: Phase 1 先用 AKShare + 国信 IPO

```
Phase 1: AKShare（全面但需编程） + 国信（结构化但需要 GS_API_KEY）
Phase 2: 加入华泰 AI 增强层
这样可以先跑通回测管道，不依赖华泰 NLP 的延迟和不确定性
```

---

## 六、Phase 1 数据聚合层最小实现

```
src/data/              # 7 个文件
├── __init__.py        # 导出
├── base.py            # DataProvider ABC (~60 行)
├── schema.py          # Quote, Financials, FundamentalMetrics (~100 行)
├── guosen.py          # 国信适配器 (~200 行)
├── akshare.py         # AKShare 适配器 (~150 行)
├── aggregator.py      # 聚合器 (~200 行)
└── cache.py           # 简单内存缓存 (~40 行)
```

Phase 1 **不做**华泰适配器（huatai.py）——华泰 NLP skill 的价值在交互式对话场景，不是数据管道。Phase 2 再加。

---

## 七、结论

**需要数据聚合层吗？✅ 必须加。** 原因：

1. 三个源的接口范式完全不同（NLP→Markdown vs REST→JSON vs Python→DataFrame），不统一就无法在回测和实盘之间共享代码路径
2. 计划中早已承诺「同一数据点 ≥2 源交叉验证」，没有聚合层这是空话
3. 国信和 AKShare 的能力大量重叠但各有独有数据，需要优先级和降级策略
4. 华泰的 NLP skill 是黑盒，不能作为系统核心数据管道，必须隔离在 AI 增强层

**三个源的定位：**
- **国信** = 结构化数据主干（行情、财务、宏观）
- **AKShare** = 全市场扫描引擎 + 独有数据（龙虎榜、两融）+ 兜底
- **华泰** = AI 增强层（个股诊断、市场洞察），不进入数据管道
