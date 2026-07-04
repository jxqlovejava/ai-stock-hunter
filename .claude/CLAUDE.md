# ai-stock-hunter — A 股智能投资决策系统

面向 A 股投资者的全栈量化分析管道。覆盖选股、择时、风控、回测全链路。

## 架构概览

```
CLI (src/cli.py) → Orchestrator → 军规 → L0Gate → L1Analyzer → L2Judge → L3Trader → L4RiskOfficer
                                      ↑ Phase 3 注入: MacroRegime / Northbound / EarningsRevision / TopicLifecycle
```

## 核心原则

- **DTO 优先**：跨层数据使用 `@dataclass`，不用裸 dict
- **护栏内置**：每个分析输出携带 `source_citations` + `confidence` + `data_freshness`
- **[UNSOURCED]**：无法验证的声明必须标记
- **分制统一**：评分 0-100，信心度 0.0-1.0，情绪 -1.0 到 +1.0
- **仅 SignalWriter 可写**：所有分析 Agent 只读，仅信号输出 Agent 有写权限
- **数据源优先级**：已核实缓存 > 国信 > mootdx > AKShare > 腾讯

## 模块地图

| 层 | 模块 | 职责 |
|----|------|------|
| 路由 | `routing/orchestrator.py` | 全链路编排 |
| 路由 | `routing/l0_gate.py` | 硬性门禁（0% AI） |
| 路由 | `routing/l1_analyze.py` | 多维分析（宏观/价值/质量/动量/情绪/瓶颈） |
| 路由 | `routing/l2_judge.py` | 加权评分 + 裁决 |
| 路由 | `routing/l3_trade.py` | 信号→仓位映射 |
| 路由 | `routing/l4_risk.py` | 硬性风控约束 |
| 军规 | `doctrine/` | 31 条军规（4 级严重度） |
| 数据 | `data/aggregator.py` | 多源聚合器（mootdx/腾讯/国信/AKShare） |
| 数据 | `data/factor_pipeline.py` | 因子计算管道（PE/ROE/北向） |
| 数据 | `data/earnings_revision.py` | 盈利修正因子 |
| 宏观 | `macro/monetary_credit.py` | 货币-信用双象限框架 |
| 行业 | `industry/bottleneck.py` | 实体瓶颈分析 |
| 行业 | `industry/supply_chain.py` | 供应链映射 |
| 博弈 | `game_theory/` | 主导玩家/席位/北向/拥挤度 |
| 政策 | `policy/` | 政策 NLP + 跟踪 |
| 信息 | `information/` | 主题管理/互动易/速度监控 |
| 情绪 | `sentiment/` | 市场情绪/恐慌套利 |
| 回测 | `backtest/` | 策略回测/优化/比较 |
| 学习 | `learner/` | 反馈/进化/校准 |

## Skill 参考

| Skill | 用途 |
|-------|------|
| `stock-hunter` | 顶级入口 |
| `l0-gate` | 安全门禁检查 |
| `l1-analyze` | 多维股票分析 |
| `l2-judge` | 加权评分与裁决 |
| `l3-trade` | 交易信号生成 |
| `l4-risk` | 风控约束检查 |
| `doctrine` | 31 条军规 |
| `game-theory` | 博弈论分析 |
| `macro-monitor` | 宏观货币信用监控 |
| `policy-tracker` | 政策跟踪与 NLP |
| `sentiment-analysis` | 市场情绪分析 |
| `topic-manager` | 主题生命周期管理 |
| `idea-generation` | 选股筛选预设 |
| `earnings-analysis` | A 股财报分析 |
| `sector-research` | 行业与供应链研究 |
| `backtest-engine` | 策略回测 |

## CLI

```bash
python -m src.cli <command> [args]

# 主要命令
analyze <code>     # 全链路分析
scan --preset <p>  # 全市场选股扫描
macro              # 宏观快照
backtest           # 运行回测
diagnose <code>    # 诊断分析（军规 + 分析）
game-theory        # 博弈论概览
calibrate          # 信心度校准
profile            # 用户画像
feedback add       # 添加交易反馈
evolve             # 策略进化
```

## 开发工作流

- **测试**：`pytest tests/`（类级 Test* 命名 + 方法级 test_* 命名）
- **新增数据源**：实现 `src/data/base.py` 的 `DataProvider`，在 `aggregator.py` 注册
- **新增路由阶段**：在 `__init__.py` 导出 + `orchestrator.py` 的 `run()` 挂接
- **Commit**：`<type>: <description>`（feat/fix/refactor/docs/test/chore）
- **数据新鲜度**：行情 5min / 因子 1h / 基本面 24h / 主题 12h
- **自动提交**：完整实现一个功能或 fix 解决问题后，自动调用 `/gcp` 命令提交并推送。无需等待用户确认，直接执行。
