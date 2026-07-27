# adata — A 股量化数据 SDK 参考分析

> 源码：https://github.com/1nchaos/adata  
> 定位：免费开源 A 股量化交易数据库 SDK，专注交易数据，多数据源融合  
> 许可证：MIT  
> 分析日期：2026-07-27

adata 是一个纯 Python A 股数据 SDK，核心理念是**"只有交易数据是真实的"**——专注行情、资金流、概念板块等交易产生的数据，不过度依赖滞后的财务数据。它通过整合东方财富、同花顺、新浪财经、腾讯理财、百度股市通等多个公开数据源，提供高可用的统一 API 接口。与白泽的 `data/aggregator.py` 多源聚合模式高度互补，其多源自动切换、模块化分层、代理 IP 池等设计思路可直接复用。

---

## 一、架构全景

```
┌─────────────────────────────────────────────────────┐
│  用户代码（Python SDK）                               │
│  import adata                                        │
│  adata.stock.market.get_market(...)                  │
└─────────────────────┬───────────────────────────────┘
                      │
  ┌───────────────────┴───────────────────┐
  │         adata 统一 API 层              │
  │  stock / fund / bond / sentiment       │
  │  info / market / finance / index       │
  └───────────────────┬───────────────────┘
                      │
  ┌───────────────────┴───────────────────┐
  │        多数据源融合引擎                │
  │  ├─ 东方财富 (eastmoney)              │
  │  ├─ 同花顺 (tonghuashun/ths)          │
  │  ├─ 新浪财经 (sina)                   │
  │  ├─ 腾讯理财 (tencent)                │
  │  ├─ 百度股市通 (baidu)                │
  │  └─ 自动切换 + 代理 IP 池              │
  └───────────────────────────────────────┘
```

| 维度 | adata | 白泽 (ai-stock-hunter) |
|------|-------|------------------------|
| 数据访问 | 实时 API 聚合，多源自动 fallback | 固定优先级链（华泰>国信>腾讯>mootdx>AKShare） |
| 数据源数 | 5+（东财/同花顺/新浪/腾讯/百度） | 5（华泰/国信/腾讯/mootdx/AKShare） |
| 代理机制 | 内置代理 IP 池，应对反爬 | 无统一代理层 |
| 异常处理 | 统一异常模块（`adata_http_error`） | 各 provider 各自处理 |
| 重试机制 | 内置重试 + 数据源自动切换 | `_akshare_call` 有限重试，无跨源自动切换 |
| 覆盖范围 | 行情/概念/北向/融资融券/龙虎榜/解禁 | 行情/财务/因子/宏观/主题/博弈 |
| 财务数据 | 有限（核心指标，侧重交易） | 丰富（PE/PB/ROE/盈利修正） |
| 部署方式 | pip install 即用 | 需配置多源 API Key |

---

## 二、核心设计原则

### 2.1 多数据源自动融合（最值得借鉴）

adata 最核心的设计：**对同一类数据维护多个数据源，调用时自动选择可用源，失败时自动 fallback**。

```python
# adata 的典型模式：多个数据源函数并列，上层统一调度
# 同花顺来源
stock.info.all_concept_code_ths()
stock.info.concept_constituent_ths()
# 东方财富来源  
stock.info.all_concept_code_east()
stock.info.concept_constituent_east()
```

白泽当前的 `aggregator.py` 用固定优先级链（guosen > mootdx > akshare），但缺少：
- **自动 fallback**：一个源失败后自动切换到下一个，而不是报错标记 `[DATA_GAP]`
- **请求重试 + 源切换整合**：重试 N 次失败后再切源
- **代理 IP 池**：统一应对公开 API 的反爬限制

> **借鉴建议**：在 `data/aggregator.py` 中引入 `MultiSourceFetcher` 概念——同类数据（如日 K 线）注册多个 Provider，调用时按优先级尝试，失败自动切换，全部失败才标记 `[DATA_GAP]`。

### 2.2 分层模块化设计

adata 的模块结构：

```
adata/
├── bond/          # 债券模块（可转债）
│   ├── info.py    #   代码信息
│   └── market.py  #   行情
├── common/        # 公共组件
│   ├── constant.py     # 常量定义
│   ├── request.py      # 统一 HTTP 请求封装
│   ├── headers.py      # 请求头管理
│   └── exception.py    # 统一异常体系
├── fund/          # 基金模块（ETF）
│   ├── info.py
│   └── market.py
├── sentiment/     # 舆情模块
│   ├── hot.py          # 龙虎榜、人气榜
│   ├── margin.py       # 融资融券
│   ├── north.py        # 北向资金
│   └── xiaojie.py      # 股票解禁
└── stock/         # 股票核心模块
    ├── finance/   # 财务
    ├── index/     # 指数
    ├── info/      # 基本信息（代码、概念、行业）
    └── market/    # 行情（K线、分时、实时、五档、分笔）
```

这和白泽的模块划分思路一致（`data/`、`sentiment/`、`game_theory/`、`policy/` 等），但 adata 的每个模块文件更小、职责更聚焦。白泽的 `data/aggregator.py` 目前是一个 1500+ 行的文件，可参考 adata 拆分为 `data/stock/`、`data/fund/`、`data/bond/` 等多文件。

### 2.3 统一异常与重试体系

adata 的 `common/exception.py` 定义了专业化的异常层次：

```
BaseError
├── AdataHttpError      # HTTP 层面的错误（状态码、超时）
├── AdataNetError       # 网络层面的错误（DNS、连接）
├── AdataDataError      # 数据解析层面的错误
└── AdataParamsError    # 参数校验错误
```

配合统一的重试逻辑：捕获 `AdataHttpError` → 重试 N 次 → 切数据源 → 全部失败抛异常向上层报 `[DATA_GAP]`。

白泽目前各 provider 自行处理异常，缺少统一的异常层次和重试+切源整合机制。可直接引入类似体系。

### 2.4 概念板块双源架构

adata 对概念板块同时维护**同花顺**和**东方财富**两个来源，函数名通过 `_ths` / `_east` 后缀区分。这让概念板块数据天然具有交叉验证能力。

白泽当前的概念板块数据来自 `sector_ranking_cache.json`，缺少多源交叉验证。可以直接引入 adata 的概念板块数据作为第二源。

---

## 三、数据覆盖与 API 设计

### 3.1 行情数据

| API | 功能 | 数据源 | 可比白泽模块 |
|-----|------|--------|------------|
| `stock.market.get_market()` | 日/周/月 K 线 | 多源融合 | `DataAggregator.get_daily_bars()` |
| `stock.market.get_market_min()` | 分钟 K 线 | 多源融合 | T+0 日内时机 |
| `stock.market.list_market_current()` | 实时行情（批量） | 腾讯/新浪 | `get_realtime_quotes()` |
| `stock.market.get_market_five()` | 五档行情 | 百度 | — |
| `stock.market.get_market_bar()` | 分笔成交（Tick） | 百度 | — |

### 3.2 概念板块

| API | 功能 | 数据源 |
|-----|------|--------|
| `stock.info.all_concept_code_ths()` | 同花顺概念列表 | 同花顺 |
| `stock.info.concept_constituent_ths()` | 同花顺概念成分股 | 同花顺 |
| `stock.info.all_concept_code_east()` | 东财概念列表 | 东方财富 |
| `stock.info.concept_constituent_east()` | 东财概念成分股 | 东方财富 |
| `stock.market.get_market_concept_ths()` | 概念 K 线行情 | 同花顺 |
| `stock.market.get_market_concept_east()` | 概念 K 线行情 | 东方财富 |

### 3.3 舆情与资金

| API | 功能 | 数据源 |
|-----|------|--------|
| `sentiment.north.north_flow_current()` | 北向资金当前流向 | 东方财富 |
| `sentiment.north.north_flow_min()` | 北向资金分时流向 | 东方财富 |
| `sentiment.north.north_flow()` | 北向资金历史流向 | 东方财富 |
| `sentiment.margin.margin_all()` | 融资融券余额 | 东方财富 |
| `sentiment.hot.pop_rank_100_east()` | 人气榜 Top 100 | 东方财富 |
| `sentiment.hot.dragon_list()` | 龙虎榜 | 东方财富 |
| `sentiment.xiaojie.xiaojie_stock_date()` | 股票解禁 | 东方财富 |

### 3.4 ETF 与可转债

| API | 功能 | 数据源 |
|-----|------|--------|
| `fund.info.all_etf_code()` | ETF 代码列表 | 东方财富 |
| `fund.market.get_market_etf()` | ETF 行情（K 线） | 东方财富 |
| `bond.info.all_convert_code()` | 可转债代码列表 | 东方财富 |

### 3.5 DataFrames 适配

adata 所有 API 均返回 pandas DataFrame，与白泽的数据处理管道天然兼容，不需要额外适配层。

---

## 四、可迁移机制清单

| # | 机制 | 来源 | 应用到本项目 |
|---|------|------|------------|
| 1 | **多数据源自动融合 + 失败 fallback** | 核心设计 | `data/aggregator.py` 引入 `MultiSourceFetcher`，同类数据注册多个 Provider，失败自动切源 |
| 2 | **统一异常层次（AdataHttpError / NetError / DataError）** | `common/exception.py` | 引入 `BaizeError` 异常体系，统一各 provider 的错误处理 |
| 3 | **代理 IP 池机制** | 公共组件 | 为 aggregator 暴露的公开 API 调用添加统一代理层，降低反爬风险 |
| 4 | **概念板块双源（同花顺+东财）** | `stock.info` | 为 `sector_ranking_cache.json` 引入同花顺概念作为交叉验证第二源 |
| 5 | **分笔成交数据（Tick）** | `stock.market.get_market_bar()` | 白泽缺少的 Tick 级数据，可用于 T+0 日内分析和主力资金流计算 |
| 6 | **分时北向资金流向** | `sentiment.north.north_flow_min()` | 白泽目前只有日级别北向数据，分时北向可增强博弈论分析 |
| 7 | **批量实时行情** | `stock.market.list_market_current()` | 替代多次 `get_realtime_quotes` 单次调用，批量自选股扫雷性能优化 |
| 8 | **龙虎榜结构化数据** | `sentiment.hot.dragon_list()` | 直接接入白泽的 `game_theory/` 博弈论模块，替代目前间接获取方式 |
| 9 | **ETF 行情数据** | `fund.market.get_market_etf()` | 白泽目前缺少 ETF 数据分析能力，可作为新增数据维度 |
| 10 | **可转债数据** | `bond.info/` / `bond.market/` | 白泽目前缺少可转债数据，新增转债-正股联动分析维度 |

---

## 五、与白泽现有数据源对比

| 数据维度 | 白泽当前源 | adata 源 | 互补程度 |
|---------|-----------|----------|---------|
| 日 K 线 | guosen / mootdx / akshare | 多源融合 | **高** — adata 可作为额外备用源 |
| 分笔成交(Tick) | 无 | 百度 | **高** — 填补 Tick 空白 |
| 概念板块 | 缓存 JSON 文件 | 同花顺+东财双源 | **高** — 实时交叉验证 |
| 北向资金 | eastmoney (间接) | eastmoney（结构化 API） | **中** — adata 更结构化 |
| 融资融券 | 有限 | eastmoney（结构化） | **中** — 可直接替换 |
| 龙虎榜 | 有限 | eastmoney（结构化） | **高** — 直接接入博弈论模块 |
| ETF / 可转债 | 无 | 完整 | **高** — 全新数据维度 |
| 五档行情 | 有限 | 百度 | **低** — 非当前核心需求 |
| 财务数据 | 丰富（华泰/国信） | 有限（核心指标） | **低** — adata 不够深 |

---

## 六、不直接借鉴 / 边界

| 项 | 原因 |
|----|------|
| 纯实时 API 模式（无本地缓存） | adata 每次调用走 HTTP，白泽已经意识到本地缓存（free-stockdb LevelDB）的重要性，adata 的架构可与之互补而非替代 |
| 财务数据覆盖有限 | adata 理念是"只关心交易数据"，但白泽的 Alpha Lens / 多维诊断需要深度财务分析 |
| 无因子计算管道 | adata 定位在数据层，不涉及 PE/PB/ROE 等衍生因子计算，白泽的 `factor_pipeline.py` 是独立的 |
| 无宏观/政策数据 | adata 缺失货币信用、社融、DR007 等宏观数据，白泽的 `macro/` 模块独立覆盖 |
| Python 纯同步调用（无异步） | 批量 5000+ 股票场景下可能成为性能瓶颈，白泽可考虑用 asyncio + aiohttp 包装 |
| 不涉及交易信号生成 | adata 纯粹是数据获取层，不涉及诊断/裁决/风控等白泽核心能力 |

---

## 七、建议落地优先级

| 优先级 | 项目 | 预期收益 |
|:------:|------|---------|
| **P0** | `aggregator.py` 引入多数据源自动 fallback 机制 | 数据可靠性提升，单源故障不中断分析管道 |
| **P0** | 接入 adata 分笔成交（Tick）数据 | T+0 日内分析和资金流强度计算的新维度 |
| **P1** | 引入 adata 概念板块（同花顺+东财）作为 `sector_ranking_cache` 的实时验证源 | 概念板块数据的交叉验证和实时性提升 |
| **P1** | 接入 adata 龙虎榜数据到 `game_theory/` 模块 | 博弈论分析的龙虎榜维度增强 |
| **P1** | 建立统一异常体系（借鉴 `AdataHttpError` 分层） | 各 provider 错误处理标准化，方便归因和告警 |
| **P2** | 接入 adata 分时北向、ETF、可转债数据 | 新增数据维度扩展分析广度 |
| **P2** | 接入 adata 批量实时行情替代单次实时报价 | 自选股批量扫雷性能优化 |
| **P3** | 代理 IP 池机制 | 高频调用场景下反爬保护 |

> ⚠️ **注意**：adata 最核心的借鉴价值在于**多数据源自动融合的设计模式**。白泽的 `aggregator.py` 目前使用固定优先级链且缺少跨源自动 fallback，引入 adata 模式后可显著提升数据可用性。同时 adata 的**分笔成交（Tick）**和**龙虎榜结构化数据**填补了白泽目前的数据空白，与 free-stockdb 的本地缓存方案形成"本地缓存 + 实时多源"的完整数据架构。
