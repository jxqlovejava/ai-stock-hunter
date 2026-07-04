# 🦄 白泽 (Baize) — A 股智能投资决策系统

> **《山海经》有兽名白泽，通晓万物之情状，能人言。白泽看穿市场噪声、辨识各路玩家，把复杂世界翻译成你能听懂的话。**

> **投资不是赌博，是概率游戏。系统帮你算概率，军规帮你管住手。**

面向 A 股投资者的全栈量化分析管道——覆盖**选股、择时、风控、回测**全链路。既是分析工具，也是投资教练。

---

## 🎯 一句话定位

帮你在 A 股活下来、赚到钱、最终不再需要系统。

---

## 🧠 核心理念

```
系统不是告诉你「买什么能赚钱」
系统是阻止你「买什么会亏大钱」
```

A 股散户亏损的根因不是「不会选股」，是**行为偏差**——追涨杀跌、不止损、仓位失控。系统的第一优先级是**阻止自毁行为**，第二优先级才是捕捉机会。

---

## 🏗️ 架构：5 层路由 + 军规前置

```
CLI → 军规(31条) → L0 Gate → L1 Analyze → L2 Judge → L3 Trade → L4 Risk
                     ↑  Phase 3: MacroRegime / Northbound / EarningsRevision / TopicLifecycle
```

| 层 | 名称 | 职责 | AI 参与度 |
|----|------|------|----------|
| **军规** | 投资军规 | 31 条硬性门禁，block/warn/info 三级 | 0% |
| **L0** | 保安 | ST/\*ST 否决、次新股冷静、流动性过滤 | 0% |
| **L1** | 分析师 | 宏观+价值+质量+动量+情绪+瓶颈 6 维打分 | 30% |
| **L2** | 法官 | 加权评分 + 置信度计算 + 反共识检验 | 20% |
| **L3** | 交易员 | 信号→仓位映射（核心仓/交易仓分治） | 10% |
| **L4** | 风控官 | 单笔止损 2%、组合回撤 15%、系统级熔断 | 0% |

> **设计原则**：规则引擎做主路径，AI 做分析增强。军规/L0/L4 纯规则（0% AI），L1/L2 量化为主 + AI 为辅。

---

## 📦 模块全景

| 模块 | 路径 | 核心能力 |
|------|------|---------|
| 🗄️ 数据层 | `src/data/` | 5 源聚合（国信/mootdx/AKShare/腾讯/华泰）、交叉验证、TTL 缓存 |
| 📜 军规 | `src/doctrine/` | 31 条 A 股专属军规 + 232 个 Munger 思维模型动态匹配 |
| 🛤️ 路由 | `src/routing/` | 5 层管道编排 + Agent-Worker 模式 + 护栏执行器 |
| 📊 回测 | `src/backtest/` | Backtrader 引擎 + 网格/贝叶斯优化 + 多策略对比 + 防过拟合 |
| 🎲 博弈论 | `src/game_theory/` | 北向资金多维画像、公募拥挤度、龙虎榜席位识别、主导玩家分类 |
| 📈 宏观 | `src/macro/` | 货币-信用双象限框架（社融/M1-M2/DR007/LPR） |
| 😱 情绪 | `src/sentiment/` | 恐慌套利引擎、大盘/板块情绪信号、过度反应检测 |
| 🏭 行业 | `src/industry/` | 物理瓶颈分析链、供应链映射、SA 瓶颈阶梯 |
| 📰 政策 | `src/policy/` | NLP 关键词追踪、政策→板块传导映射 |
| 📡 信息 | `src/information/` | 主题生命周期管理、互动易问答、信息速度监控 |
| 🧠 学习 | `src/learner/` | 反馈闭环、策略进化飞轮、用户能力画像、信号质量追踪 |

16,500+ 行 Python 源码，322 个测试用例，覆盖率 80%+。

---

## 🚀 快速开始

### 安装

```bash
git clone https://github.com/jxqlovejava/ai-stock-hunter.git
cd ai-stock-hunter
pip install -r requirements.txt
```

### 一行命令

```bash
# 全市场选股扫描
python -m src.cli scan --preset value

# 单只股票全链路分析
python -m src.cli analyze 600519

# 一键诊断（小白入口）
python -m src.cli diagnose 000858

# 宏观快照
python -m src.cli macro

# 运行回测
python -m src.cli backtest

# 策略进化
python -m src.cli evolve
```

完整 CLI 命令参考：[`.claude/CLAUDE.md`](.claude/CLAUDE.md#cli)

---

## 🔐 数据护栏体系

每个分析数据点强制携带 `SourceCitation`——**没有来源的数字不进分析管道**：

```python
SourceCitation(
    provider="guosen",       # 国信/mootdx/akshare/tencent/huatai
    confidence=0.90,         # 来源置信度
    data_freshness="5min",   # 数据新鲜度
)
```

| 规则 | 说明 |
|------|------|
| ≥2 源交叉验证 | 同一数据点差异 > 5% → 标记 DISPUTED，不进管道 |
| [UNSOURCED] 强制标注 | 无法追溯到数据源的数字必须标记 |
| confidence < 0.6 | 阻止进入 L3 交易阶段 |
| 仅 SignalWriter 可写 | 所有分析 Agent 只读，仅信号输出 Agent 有写权限 |

详见：[`.claude/rules/guardrails.md`](.claude/rules/guardrails.md)

---

## 🎓 用户成长路径

系统设计目标是**让你最终不再需要它**：

```
依赖期(0-3月)  →  理解期(3-6月)  →  协作期(6-12月)  →  独立期(12月+)
完全跟单          有自己的判断       系统做对手方        系统=风控安全带
```

三种模式一个内核：
- 🟢 **小白**：一键诊断 · ✅/⚠️/🔴 三色信号 · 白话解释
- 🟡 **进阶**：多维对比 · 因子深潜 · 雷达图
- 🔴 **专业**：自定义筛选 · 策略回测 · 红队攻击

---

## 📚 31 条投资军规

分为 7 大类，严重度 block/warn/info 三级：

| 类别 | 数量 | 示例 |
|------|------|------|
| 仓位资金 | 5 条 | 单票 ≤ 20%、总仓位 ≤ 80%、永不满仓 |
| 选股估值 | 6 条 | ST/\*ST 一票否决、不懂不投、商誉雷预警 |
| 买卖纪律 | 5 条 | 不追涨停、不接飞刀、不赌财报 |
| 情绪纪律 | 5 条 | 不在恐慌中决策、拒绝爱上持仓 |
| 信息纪律 | 3 条 | 小作文零信任、信源交叉验证 |
| 风控止盈 | 4 条 | 单笔止损 2%、组合回撤熔断 15% |
| 元风控 | 1 条 | 系统整体连续犯错 → 全局静默 |

详见：[`src/doctrine/rules.py`](src/doctrine/rules.py)

---

## 🔄 策略进化飞轮

```
回测优化 → 最优参数 → 策略注册中心
                          ↓
用户反馈 → 反馈收集 → 权重校准 → 策略进化
                          ↓
信号追踪 → 质量报告 → 进化编排 → 回测验证 → 部署
```

内置 5 个反馈环：因子权重自适应、风控参数动态调整、策略有效性监控、用户反馈驱动修正、市场结构变迁检测。

详见：[`.claude/plans/strategy-refinement-loop.plan.md`](.claude/plans/strategy-refinement-loop.plan.md)

---

## 🧩 Claude Code 集成

系统深度集成 Claude Code Agent 体系：

### Agent Worker 模式
| Agent | 职责 | 权限 |
|-------|------|------|
| `orchestrator-agent` | 全链路编排 | 只读协调 |
| `data-worker` | 数据获取 | 只读 |
| `analysis-worker` | 军规→L0→L1→L2 | 只读分析 |
| `signal-writer` | L3→L4→输出 | 唯一写权限 |

### Skills（16 个）
`stock-hunter` · `l0-gate` · `l1-analyze` · `l2-judge` · `l3-trade` · `l4-risk` · `doctrine` · `game-theory` · `macro-monitor` · `policy-tracker` · `sentiment-analysis` · `topic-manager` · `idea-generation` · `earnings-analysis` · `sector-research` · `backtest-engine`

---

## 🗺️ 开发路线图

| Phase | 主题 | 状态 |
|-------|------|------|
| Phase 1 | MVP：3 因子 + 回测 + 军规 | ✅ 完成 |
| Phase 2 | 数据聚合层、华泰/国信适配器、龙虎榜验证 | 🚧 进行中 |
| Phase 3 | 宏观货币信用、北向多维、盈利修正、主题生命周期 | 🔜 规划中 |
| Phase 4 | 多 Agent 并行研究、策略自我进化、Web UI | 📋 远期 |

完整规划与设计决策：[`.claude/plans/ai-stock-hunter.plan.md`](.claude/plans/ai-stock-hunter.plan.md)（含 16 轮毒辣拷打与回应）

---

## 🙏 致敬

本项目深度借鉴了以下开源项目的思想与设计：

| 项目 | Stars | 借鉴要点 |
|------|-------|---------|
| [ai-berkshire](https://github.com/ai-berkshire/ai-berkshire) | 9.4k | 四大师方法论、7 步研究流程 |
| [FinceptTerminal](https://github.com/FinceptTerminal/FinceptTerminal) | 27.9k | 宏观/公司研究数据模型 |
| [OpenStock](https://github.com/OpenStock/OpenStock) | 13.6k | 跨源情绪聚合 |
| [Backtrader](https://github.com/mementum/backtrader) | — | 回测引擎核心 |
| [cyberagent](https://github.com/CyberK13/cyberagent) | — | 物理瓶颈分析链 |
| [AlphaEvo](https://github.com/ZhuLinsen/AlphaEvo) | — | 策略自我进化 + 防过拟合 |
| [open-xquant](https://github.com/open-xquant/open-xquant) | 75 | 可复现回测审计流水线 |
| [PanWatch](https://github.com/PanWatch/PanWatch) | 648 | 盯盘 + 多 Agent 调度 |

完整借鉴清单与许可证信息：[`docs/open-source-credits.md`](docs/open-source-credits.md)

---

## 📖 进一步阅读

| 文档 | 内容 |
|------|------|
| [`.claude/CLAUDE.md`](.claude/CLAUDE.md) | 项目架构 & 开发工作流 |
| [`.claude/plans/ai-stock-hunter.plan.md`](.claude/plans/ai-stock-hunter.plan.md) | 完整系统设计计划（含毒辣拷打） |
| [`.claude/plans/strategy-refinement-loop.plan.md`](.claude/plans/strategy-refinement-loop.plan.md) | 策略进化闭环设计 |
| [`.claude/rules/guardrails.md`](.claude/rules/guardrails.md) | 统一护栏规则 |
| [`docs/data-source-analysis.md`](docs/data-source-analysis.md) | 华泰 vs 国信 vs AKShare 数据源深度分析 |
| [`docs/open-source-credits.md`](docs/open-source-credits.md) | 开源项目参考清单 |
| [`TODO.md`](TODO.md) | 系统迭代备忘录（三大底层问题驱动） |

---

## ⚠️ 免责声明

本系统仅提供数据分析和决策辅助，**不构成任何投资建议**。所有交易决策由用户自行做出并承担相应风险。A 股有风险，投资需谨慎。

---

## 📄 许可证

MIT License

---

<p align="center">
  <b>安全边际 + 能力圈 + 概率思维 + 逆向思考 = 活下来，赚到钱</b>
</p>
