# TradingAgents-Astock 参考分析

> 本地：`~/Documents/workspace/TradingAgents-astock`  
> 源码：https://github.com/simonlin1212/TradingAgents-astock  
> 上游：https://github.com/TauricResearch/TradingAgents  
> 论文：https://arxiv.org/abs/2412.20138  
> 许可证：Apache 2.0  
> 分析日期：2026-07-16

基于 TradingAgents 的 **A 股深度特化 fork**：数据源（mootdx/东财/新浪/同花顺等）、分析师角色（+政策/游资/解禁）、交易规则（T+1/涨跌停/手数）三维改造。全 Apache 2.0，pip 可装，零外部付费数据依赖。

上游 TradingAgents 已在 `docs/open-source-credits.md` 登记；**角色、数据、交易约束以本 A 股 fork 为主参考**。

---

## 一、架构概览

```
┌─────────────────────────────────────────────────────────┐
│  7 Analyst 研报（各带工具循环）                            │
│  Market → Social → News → Fundamentals                   │
│  → Policy → Hot Money → Lockup                           │
├─────────────────────────────────────────────────────────┤
│  Bull vs Bear 投研辩论（最多 N 轮）                        │
├─────────────────────────────────────────────────────────┤
│  Research Manager 综合研判（deep_think_llm）              │
├─────────────────────────────────────────────────────────┤
│  Trader 交易方案（A 股：T+1 / 涨跌停 / 手数）              │
├─────────────────────────────────────────────────────────┤
│  Aggressive ↔ Conservative ↔ Neutral 三方风险辩论         │
├─────────────────────────────────────────────────────────┤
│  Portfolio Manager 最终决策（Buy/Hold/Sell + 仓位）       │
└─────────────────────────────────────────────────────────┘
```

**双 LLM**：

| 角色 | 模型配置 | 用途 |
|------|---------|------|
| Analyst / Researcher / Trader / Risk Debater | `quick_think_llm` | 工具调用、快速生成 |
| Research Manager / Portfolio Manager | `deep_think_llm` | 全局综合、最终裁决 |

白泽对照：分析 worker 轻量、裁决/调度更重；confidence 门禁对应「综合前需足够分析输出」。

---

## 二、7 个 Analyst 角色

### 原版 4 角色（A 股适配）

| 角色 | 职责 | 白泽对应 |
|------|------|---------|
| 市场分析师 | K 线、技术指标、量价 | L1 动量 / T+0 |
| 舆情分析师 | 社媒情绪、散户热度 | `sentiment/` |
| 新闻分析师 | 行业新闻、公告、宏观 | 归因 / 信息层 |
| 基本面分析师 | 三表、盈利、估值 | L1 价值/质量 |

### A 股特化 3 角色（新增）

| 角色 | 职责 | 白泽对应 |
|------|------|---------|
| 政策分析师 | 监管/产业政策/窗口指导 | `policy/` + policy-tracker |
| 游资追踪师 | 龙虎榜、大单、主力 | `game_theory/` |
| 解禁监控师 | 限售解禁、减持、质押 | 风险提示 + 数据层 |

---

## 三、数据源矩阵

| 来源 | 协议 | 内容 |
|------|------|------|
| mootdx | TCP 7709 | OHLCV、财务快照、F10 |
| 腾讯财经 | HTTP | PE/PB/市值/换手 |
| 东方财富 | HTTP | 龙虎榜、解禁、板块、新闻 |
| 新浪财经 | HTTP | K 线历史、三表 |
| 同花顺 | HTTP | EPS 一致预期 |
| 财联社 | HTTP | 全球快讯 |
| 百度股市通 | HTTP | 概念板块、资金流 |

**工程要点（v0.2.11+）**：

- 行情/K 线/市值/财务优先 mootdx 或腾讯  
- 东财只用于独有数据（龙虎榜/解禁/资金流等）  
- 东财统一 `_em_get()`：串行限流 + 抖动 + Keep-Alive  
- 不依赖 Tushare 积分墙  

与白泽数据优先级（华泰 > 国信 > 腾讯 > mootdx > AKShare）可对照补洞。

---

## 四、关键目录

```
tradingagents/
├── agents/
│   ├── analysts/          # 7 分析师
│   ├── researchers/       # Bull / Bear
│   ├── risk_mgmt/         # 激进/保守/中立
│   ├── managers/          # Research + Portfolio Manager
│   ├── trader/            # A 股交易约束
│   └── utils/
├── dataflows/
│   ├── a_stock.py         # A 股 vendor
│   └── interface.py       # 数据接口抽象
└── graph/
    ├── trading_graph.py   # 主入口
    ├── setup.py           # LangGraph 拓扑
    ├── propagation.py     # 状态传播
    ├── reflection.py      # 交易反思（CSI 300）
    └── conditional_logic.py
```

---

## 五、可迁移机制清单

| # | 机制 | 来源 | 应用到本项目 |
|---|------|------|------------|
| 1 | 多空辩论 | `agents/researchers/` | L2 前对立观点 |
| 2 | 三方风险辩论 | `agents/risk_mgmt/` | L4 前多视角风控叙事 |
| 3 | A 股 Trader 约束 | `agents/trader/` | L3 硬约束 |
| 4 | 政策/游资/解禁角色 | analysts/* | 已有模块补全 workflow |
| 5 | 免费数据源矩阵 | `dataflows/a_stock.py` | aggregator 补源 |
| 6 | 东财防封节流 | `_em_get` | 东财统一入口 |
| 7 | LangGraph 拓扑 | `graph/setup.py` | orchestrator DAG |
| 8 | CSI 300 反思 | `graph/reflection.py` | learner 校准 |
| 9 | checkpoint 断点续跑 | config | 长链路恢复 |
| 10 | 12 阶段可展开报告 | web progress | CLI 分层输出 |
| 11 | 双 LLM 分工 | config | 分析/裁决模型分流 |
| 12 | 内部英文辩论+中文输出 | 文档约定 | 质量与可读性平衡 |

---

## 六、与白泽 pipeline 对照

| TradingAgents-Astock | 白泽 |
|---------------------|------|
| 7 Analyst | 军规 + 准入 + L1 多维诊断 + 博弈/政策/情绪 |
| Bull/Bear 辩论 | 可增强 L2 前「对立论点」 |
| Research Manager | L2 综合裁决 |
| Trader | L3 仓位调度 |
| 三方风险辩论 | L4 风控 + 军规 |
| Portfolio Manager | SignalWriter（唯一可写） |
| reflection | learner / calibrate |

白泽优势：硬编码军规、准入、风控、数据溯源护栏。  
TradingAgents-Astock 优势：显式辩论图、A 股角色完整、Web 进度与报告导出。

---

## 七、不直接借鉴 / 边界

- **不替代**白泽军规/L4 硬约束（辩论不能 override BLOCK）  
- **不默认**引入完整 LangGraph 运行时依赖（可借鉴拓扑思想）  
- LLM 每轮 30–50 次调用成本高——批量扫描需配额与缓存策略  
- 空报告/弱 tool-call 模型问题：需质量门控（对齐白泽 confidence 与 DATA_GAP）  

---

## 八、建议落地优先级

1. **P0**：主题/个股报告增加「多空要点 + 风险三视角」小节（不必上完整辩论图）  
2. **P1**：东财请求统一节流（若尚未集中）  
3. **P2**：解禁/质押作为显式数据通道接入准入或风险提示  
4. **P3**：评估 LangGraph/checkpoint 用于长链路 diagnose 中断恢复  
