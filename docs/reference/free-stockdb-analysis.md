# free-stockdb — 本地量化数据引擎参考分析

> 源码：https://github.com/hello245m/free-stockdb  
> 定位：面向 A 股的本地量化数据引擎，将数据工程与策略研究解耦
> 许可证：MIT  
> 分析日期：2026-07-26

free-stockdb 是一个 A 股本地量化数据引擎，核心理念是**将数据工程与策略研究完全解耦**：数据更新在同步层完成，策略只读本地数据集。所有行情数据（日/分钟/ETF 分笔/tick）通过增量同步存储到本地 LevelDB，经 C++ 服务暴露给 Python SDK / HTTP API / Excel / MCP 等接口。与白泽当前高度依赖实时 API 调用的模式形成**互补**：白泽可以从 free-stockdb 借鉴本地优先的数据架构，大幅加速全市场扫描和回测。

---

## 一、架构全景

```
数据源（可配置同步节点）
   ↓ manifest + SHA-256 验证
[LevelDB LSM-Tree 存储]  ← 增量同步器
   ↑
[C++ 本地服务 (127.0.0.1:7899)]  ← Rust 计算核心（39+ 技术指标）
   ↓
┌──────────────────────────────┐
│ Python SDK │ HTTP │ Excel/MCP │
└──────────────────────────────┘
```

| 维度 | free-stockdb | 白泽 |
|------|-------------|------|
| 数据访问 | 本地优先，同步后离线可用 | 实时 API 调用为主（华泰/国信/腾讯/AKShare） |
| 存储引擎 | LevelDB（LSM-Tree）+ Zstd 压缩 | JSON/CSV 文件（interaction_log/sentiment_history） |
| 数据验证 | SHA-256 + manifest + 断点续传 | 无统一校验 |
| 复权模式 | 查询时计算（原始价与因子分开存储） | 消费 API 调整后数据 |
| 计算核心 | C++ 服务 + Rust 指标（39+ 指标） | Python（pandas/numpy） |
| 接口形式 | Python SDK / HTTP / Excel / HTML / MCP | CLI 为主 |
| 数据源弹性 | 可配置同步节点，不绑定供应商 | 固定数据源优先级链 |

---

## 二、核心设计原则

### 2.1 数据/策略完全解耦

最根本的架构决策。数据工程与策略研究各自独立演进：

```
非解耦模式（白泽目前的模式）：
  实时 API 调用 → 策略

free-stockdb 模式：
  增量同步器 → LevelDB 缓存层 → 策略（读取缓存）
                                      ↓
                                  仅当缓存未命中时走实时 API
```

白泽的全市场扫描和回测是当前最耗时的操作，引入本地缓存层可将 5000+ 股票的重复查询降为本地 I/O。

### 2.2 查询时复权（On-Query Adjustment）

原始价格与复权因子分开存储，查询时用 `bisect.bisect_right` O(log n) 计算：

```
FactorRecord:
  - date, song_zhuan（送转股比例）, pai_xi（派息金额）
  - peigu_jia（配股价）, peigu_li（配股比例）

查询时动态计算：前复权 / 后复权 / 不复权三模式，无数据重复
```

白泽目前直接消费 API 的调整后价格，丢失了审计原始价格的能⼒。free-stockdb 的模式让同一 K 线数据可同时支持三种复权视角。

### 2.3 增量同步 + 内容验证

同步协议通过 manifest.txt（SHA-256 + 文件大小）逐文件验证完整性：

```
manifest.txt:
  <sha256> <size-in-bytes> <relative-path>

流程：manifest 拉取 → SHA-256 验证 → 增量拉取变更 → 验证已同步文件
```

这比白泽当前基于时间戳的 data_freshness 检查多了一层内容校验，可直接用于数据完整性门禁。

### 2.4 紧凑二进制存储

所有 K 线数据用 32 字节对齐的紧凑结构（支持内存映射零拷贝优化）：

| 字段 | 类型 | 说明 |
|------|------|------|
| datetime | uint32_t | YYYYMMDD 或 YYYYMMDDHHMM |
| open/high/low/close | float | 4×4=16 字节 |
| volume | double | 成交量 |
| amount | double | 成交额 |

LevelDB 的 LSM-Tree + Zstd 压缩 + Snappy 压缩，日线约 5GB，完整分钟级约 20GB。白泽的 JSON/CSV 存储相比之下没有压缩也没有结构化存储引擎。

### 2.5 自实现 MCP 协议

从头实现 JSON-RPC 2.0 over stdio，而非依赖外部的 `mcp` Python SDK。装饰器风格的 API：

```python
@tool()
def get_market_kline(code, start, end, frequency, fields, limit):
    ...
```

这展示了如何在金融数据场景下轻量构建 MCP 接口，白泽可直接为 `diagnose` / `tactics` 等 CLI 命令添加 MCP 暴露层，使 AI 工具可直接调用。

### 2.6 多接口统一协议

五种调用方式（Python SDK、HTTP API、Excel/WPS、HTML、MCP）均通过一个本地 C++ 服务作为单一数据源。白泽可参考这种架构，将计算能力通过 HTTP API 和 MCP 暴露出去，而不局限于 CLI。

---

## 三、数据存储与查询模型

### 3.1 LevelDB 配置

| 参数 | 值 | 说明 |
|------|-----|------|
| cache_size | 500MB | 查询缓存 |
| write_buffer_size | 16MB | 写入缓冲 |
| block_size | 32KB | 块大小 |
| compaction_speed | 1000 | 压缩速度 |
| compression | Snappy | SST 文件压缩 |

LSM-Tree 的键字典序排列天然适合时序数据的范围扫描。

### 3.2 QueryOptions 参数模型

```cpp
struct QueryOptions {
    string code;
    KType ktype;        // DAY / WEEK / MONTH / 1MIN / 5MIN / 15MIN / 30MIN
    uint32_t start_date; // 0 = 不限
    uint32_t end_date;   // 99999999 = 不限
    AdjustType adjust;   // NONE / FORWARD / BACKWARD
};
```

这个参数模型覆盖了白泽行情查询的所有场景，可以作为 `DataProvider` 统一查询接口的参考。

### 3.3 分钟级 K 线聚合

正确的 A 股交易会话模型：

```
早盘：09:30 – 11:30
午盘：13:00 – 15:00
聚合：1min → 5/15/30/60min
```

白泽的 T+0 日内时机模块可直接复用这个会话模型。

### 3.4 行业板块映射

- 申万 1/2/3 级行业分类
- 1200+ 概念板块
- 通过 `bk.get(code/name)` 查询

与白泽当前 `sector_ranking_cache.json` 的板块分类可以互通。

---

## 四、可迁移机制清单

| # | 机制 | 来源 | 应用到本项目 |
|---|------|------|------------|
| 1 | **本地 LevelDB 缓存层** | 核心数据存储 | `data/aggregator.py` 增加 LevelDB 缓存，全市场扫描减速本地 I/O |
| 2 | **增量同步 + manifest 验证** | 同步协议 | 为行情数据增加 SHA-256 完整性校验，补充现有 data_freshness 时间检查 |
| 3 | **查询时复权** | 复权计算 | `data/factor_pipeline.py` 原始价与因子分开存储，支持三模式复权 |
| 4 | **32 字节紧凑 KRecord** | K 线数据结构 | 大规模回测场景的内存布局参考 |
| 5 | **自实现 MCP 协议** | ai_mcp/ 目录 | 为 `diagnose` / `tactics` 输出添加 MCP 暴露层 |
| 6 | **A 股交易会话模型** | 分钟聚合 | T+0 日内时机模块复用 09:30-11:30 / 13:00-15:00 会话模型 |
| 7 | **可配置数据源** | sync_url.txt 机制 | aggregator.py 的数据源优先级链增加外部同步节点配置 |
| 8 | **HTTP API + Excel 宏** | 本地服务 | 白泽 CLI 能力通过 HTTP 暴露给非技术用户 |
| 9 | **Rust 技术指标计算** | zb.get() | 高频回测场景下 Python→Rust 的性能优化路径 |
| 10 | **LevelDB 配置模板** | 数据库配置 | LevelDB 500MB cache / 16MB buffer / 32KB block 作为时序缓存的推荐配置 |

---

## 五、不直接借鉴 / 边界

| 项 | 原因 |
|----|------|
| Windows 原生为主 | 白泽主力部署在 macOS/Linux，移植需额外工程 |
| 单一 GET HTTP 端点（`日k:600702:20260623`） | 自由格式参数脆弱不易扩展，白泽应用结构化 REST |
| Python SDK 中静默 Exception 捕获 | `except Exception: pass` 隐藏故障，白泽要求明确标记 `[DATA_GAP]` |
| 不支持基本面/财务数据源 | free-stockdb 聚焦高频行情，白泽的财报分析需另辟来源 |
| C++ 构建依赖（CMake + libcurl + OpenSSL） | 增加 CI/CD 和开发者入场成本，适合独立数据服务层而非嵌入主项目 |
| 离线优先 vs 实时交易 | free-stockdb 定位是研究引擎，白泽 T+0 日内判断仍需实时行情 |

---

## 六、建议落地优先级

| 优先级 | 项目 | 预期收益 |
|:------:|------|---------|
| **P0** | aggregator.py 增加 LevelDB 行情缓存层 | 全市场扫描加速 10-100x，离线回测可行 |
| **P1** | 原始价/因子分离存储 → 三模式复权 | 审计能力增强，分析多一个视角 |
| **P1** | 为 diagnose/tactics 添加 MCP 暴露层 | AI 工具可直接调用白泽分析管道 |
| **P2** | HTTP API（`diagnose <code>` 输出 via REST） | 非技术用户/Web 前端接入 |
| **P2** | A 股交易会话模型复用 | T+0 日内分析准确性提升 |
| **P3** | Rust 指标计算（MA/MACD/KDJ/RSI/BOLL 等） | 大规模回测性能优化路径预留 |
| **P3** | SHA-256 + manifest 内容验证 | 补充 data_freshness 的完整性校验 |

> ⚠️ **注意**：free-stockdb 最核心的借鉴价值在于**本地优先的数据架构**。白泽当前 gating factor 是全市场扫描时的实时 API 依赖——引入 LevelDB 缓存层后，5000+ 股票的初筛/回测可在秒级完成。这是单一变更收益最大的参考点。
