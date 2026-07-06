# 🦄 白泽 (Baize) — A 股智能投资决策系统

> **《山海经》有兽名白泽，通晓万物之情状，能人言。白泽看穿市场噪声、辨识各路玩家，把复杂世界翻译成你能听懂的话。**

> **投资不是赌博，是概率游戏。系统帮你算概率，军规帮你管住手。**

25,000+ 行 Python · 472 个测试用例 · 18 个模块 · 5 层路由管道 · 31 条军规

---

## 🌟 为什么白泽不一样？

### 🔍 Alpha Lens — 寻找真正的超额收益

A 股最致命的不是买贵了，是**追了已经被充分定价的"好故事"**。白泽独创三维 Alpha 评估引擎：

| 维度 | 核心问题 | 白泽做什么 |
|------|---------|-----------|
| **信息层级** | 这条消息还有 Alpha 空间吗？ | 区分一手/二手/三手信息，量化噪音比例 |
| **共识缺口** | 市场理解对了吗？还是夸大了？ | 检测市场叙事与基本面的偏离度，识别逻辑漏洞 |
| **叙事生命周期** | 我们处于故事的哪个阶段？ | 潜伏→兴起→扩散→共识→拥挤→消退，6 阶段精准定位 |

```
一条「新能源利好」到你这儿已经是第几手？
一手（产业链调研）→ Alpha 100%
二手（券商研报）  → Alpha 50%
三手（财经媒体）  → Alpha 20%
四手（股吧热帖）  → Alpha 0%（反向指标）
```

**用法**：`python -m src.cli alpha 600519` — 一键获取 Alpha 综合评分 + 信息来源诊断 + 叙事阶段 + 仓位建议

---

### 🧬 策略进化引擎 — 论文驱动的策略自我进化

投资策略不是一成不变的。白泽支持**投喂学术论文，自动进化策略**：

```
论文 URL → AI 分类(策略/架构) → 回测验证 → 模拟盘自动运行 → 达标确认 → 实战
                                    ↓ 不佳
                              自动优化 / 撤回
```

**9 状态全生命周期管理**：

```
EXTRACTED → CANDIDATE → TRIAL → ACTIVE
    ↓           ↓          ↓        ↓
  ERROR     REJECTED   DEGRADED  RETIRED
                           ↓
                      OPTIMIZING → CANDIDATE（循环进化）
```

**两类论文，两条路径**：

| 论文类型 | 输入 | 处理 | 验证 |
|---------|------|------|------|
| 🎯 **策略类** | "Fama-French 五因子在 A 股的改进" | 自动提取买卖条件 + 参数 | 回测 → 模拟盘 → 实战 |
| 🏗️ **架构类** | "基于知识图谱的产业链风险传导" | 生成改进提案 → 人工审核 | 旧管道 vs 新管道 A/B 对比 |

**用法**：
```bash
python -m src.cli evolution import https://arxiv.org/abs/2301.12345  # 导入论文
python -m src.cli evolution list                    # 查看所有策略状态
python -m src.cli evolution monitor                 # 监控面板
```

---

### 🧠 逆向思考 — 系统内置的怀疑论者

大多数投资工具告诉你"该买什么"。白泽先问 **"为什么不该买"**：

| 机制 | 位置 | 做什么 |
|------|------|--------|
| **反共识检验** | L2 Judge | 当市场一致看多时，自动触发反向论证，「假设市场错了」场景推演 |
| **共识缺口检测** | Alpha Lens | 量化"市场认为的" vs "基本面显示的"差距，识别过度乐观/悲观 |
| **恐慌套利引擎** | 情绪模块 | 极端恐慌时逆向触发买入信号（别人恐惧我贪婪的量化版） |
| **安全边际计算** | L1 Analyze | 基于 DCF + 资产重估 + 清算价值三重估值，算出真正的安全边际 |
| **军规拦截** | Doctrine | 31 条军规前置，在冲动发生前拦住你 |

```
系统不是告诉你「买什么能赚钱」
系统是阻止你「买什么会亏大钱」

A 股散户亏损的根因不是「不会选股」，是行为偏差——
追涨杀跌、不止损、仓位失控。
系统的第一优先级是阻止自毁行为，第二优先级才是捕捉机会。
```

---

### 🎲 博弈论全景 — 看清对手是谁

投资是零和博弈的叠加。不知道对手是谁，就是盲打：

| 模块 | 核心能力 |
|------|---------|
| **北向资金画像** | 分行业净流入、风格偏好(价值/成长)、流入加速度、大小盘偏好比 |
| **主导玩家分类** | 基于波动率/换手率/涨停结构判断定价权归属(游资/机构/量化/国家队) |
| **公募拥挤度** | 重仓股重叠度、行业拥挤度(基金持仓/流通市值)、新发基金趋势 |
| **龙虎榜席位** | 知名游资营业部识别、席位活跃度、跟买胜率、行业偏好 |
| **价格冲击模型** | 预估你的下单对市场的影响，大资金小票自动预警 |

---

### 🛡️ 数据护栏 — 没有来源的数字不进管道

```python
# 每一个数据点强制携带来源引用
SourceCitation(
    provider="guosen",       # 国信/mootdx/akshare/tencent/huatai
    confidence=0.90,         # 来源置信度
    data_freshness="5min",   # 数据新鲜度
)
```

| 规则 | 说明 |
|------|------|
| ≥2 源交叉验证 | 同一数据点差异 > 5% → 标记 DISPUTED，不进管道 |
| `[UNSOURCED]` 强制标注 | 无法追溯到数据源的数字必须标记 |
| `confidence < 0.6` | 阻止进入 L3 交易阶段 |
| 仅 SignalWriter 可写 | 所有分析 Agent 只读，唯一信号输出 Agent 有写权限 |

---

## 🏗️ 系统架构

### 5 层路由管道 + 军规前置

```
CLI → 军规(31条) → L0 Gate → L1 Analyze → L2 Judge → L3 Trade → L4 Risk
                     ↑  Phase 3: MacroRegime / Northbound / EarningsRevision / TopicLifecycle
```

| 层 | 名称 | 职责 | AI 参与度 |
|----|------|------|----------|
| **军规** | 投资军规 | 31 条硬性门禁（block/warn/info） | 0% |
| **L0** | 保安 | ST/\*ST 否决、次新股冷静、流动性过滤 | 0% |
| **L1** | 分析师 | 宏观+价值+质量+动量+情绪+瓶颈 6 维打分 | 30% |
| **L2** | 法官 | 加权评分 + 置信度 + **反共识检验** | 20% |
| **L3** | 交易员 | 信号→仓位映射（核心仓/交易仓分治） | 10% |
| **L4** | 风控官 | 单笔止损 2%、组合回撤 15%、**系统级熔断** | 0% |

> **设计原则**：规则引擎做主路径，AI 做分析增强。军规/L0/L4 纯规则（0% AI），L1/L2 量化为主 AI 为辅。

### Agent Worker 模式

| Agent | 职责 | 权限 |
|-------|------|------|
| `orchestrator-agent` | 全链路编排 | 只读协调 |
| `data-worker` | 数据获取（mootdx/腾讯/国信/AKShare） | 只读 |
| `analysis-worker` | 军规→L0→L1→L2 分析管道 | 只读分析 |
| `signal-writer` | L3→L4→最终输出 | **唯一写权限** |

---

## 📦 模块全景

| 模块 | 路径 | 核心能力 |
|------|------|---------|
| 🔍 Alpha Lens | `src/alpha/` | 信息层级判定、共识-现实缺口检测、叙事生命周期定位、Alpha 衰减追踪 |
| 🧬 策略进化 | `src/evolution/` | 论文导入与分类、回测→模拟盘→实战全生命周期、自动监控降级、撤回机制 |
| 🗄️ 数据层 | `src/data/` | 5 源聚合（国信/mootdx/AKShare/腾讯/华泰）+ 妙想 Skill、交叉验证、TTL 缓存 |
| 📜 军规 | `src/doctrine/` | 31 条 A 股专属军规 + 232 个 Munger 思维模型动态匹配 |
| 🛤️ 路由 | `src/routing/` | 5 层管道编排 + Agent-Worker 模式 + 护栏执行器 |
| 📊 回测 | `src/backtest/` | Backtrader 引擎 + 网格/贝叶斯优化 + 策略注册中心 + 防过拟合 |
| 🎲 博弈论 | `src/game_theory/` | 北向资金多维画像、公募拥挤度、龙虎榜席位识别、主导玩家分类 |
| 📈 宏观 | `src/macro/` | 货币-信用双象限框架（社融/M1-M2/DR007/LPR） |
| 😱 情绪 | `src/sentiment/` | 恐慌套利引擎、大盘/板块情绪信号、过度反应检测 |
| 🏭 行业 | `src/industry/` | 物理瓶颈分析链、供应链映射、SA 瓶颈阶梯 |
| 📰 政策 | `src/policy/` | NLP 关键词追踪、政策→板块传导映射 |
| 📡 信息 | `src/information/` | 主题生命周期管理、互动易问答、信息速度监控 |
| 🧠 学习 | `src/learner/` | 反馈闭环、策略进化飞轮、用户能力画像、信号质量追踪 |
| 💰 模拟交易 | `src/paper_trading/` | L3 信号→mx-moni 模拟账户、批量执行、反馈录入 |

---

## 🚀 快速开始

### 安装

```bash
git clone https://github.com/jxqlovejava/ai-stock-hunter.git
cd ai-stock-hunter
pip install -r requirements.txt
```

### 常用命令

```bash
# 🔍 Alpha 视角分析
python -m src.cli alpha 600519

# 📄 全市场选股扫描
python -m src.cli scan --preset value

# 📊 单只股票全链路分析
python -m src.cli analyze 600519

# 🏥 一键诊断（小白入口）
python -m src.cli diagnose 000858

# 🌍 宏观快照
python -m src.cli macro

# 🧬 策略进化 — 导入论文
python -m src.cli evolution import https://arxiv.org/abs/2301.12345

# 🧬 策略进化 — 查看状态
python -m src.cli evolution list

# 📊 回测
python -m src.cli backtest

# 👤 用户画像
python -m src.cli profile
```

完整 CLI 参考：[`src/cli.py`](src/cli.py)

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
- 🔴 **专业**：自定义筛选 · 策略回测 · 论文驱动进化

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

## 🗺️ 开发路线图

| Phase | 主题 | 状态 |
|-------|------|------|
| Phase 1 | MVP：3 因子 + 回测 + 军规 + 护栏体系 | ✅ 完成 |
| Phase 2 | 数据聚合层（国信/mootdx/AKShare/腾讯/华泰）+ 龙虎榜验证 | ✅ 完成 |
| Phase 3 | 宏观货币信用 + 北向多维 + 盈利修正 + 主题生命周期 + 博弈论全景 | ✅ 完成 |
| Phase 4 | Alpha Lens + 策略进化 + 用户反馈闭环 + 政策 NLP + 信息速度监控 | ✅ 完成 |
| Phase 5 | Web 可视界面 + 实盘券商 API 对接 + 跨资产信号 + 组合优化 | 🔜 规划中 |

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

完整借鉴清单：[`docs/open-source-credits.md`](docs/open-source-credits.md)

---

## 📖 进一步阅读

| 文档 | 内容 |
|------|------|
| [`.claude/CLAUDE.md`](.claude/CLAUDE.md) | 项目架构 & 开发工作流 |
| [`.claude/plans/strategy-evolution-module-design.md`](.claude/plans/strategy-evolution-module-design.md) | 策略进化模块完整设计 |
| [`.claude/plans/ai-stock-hunter.plan.md`](.claude/plans/ai-stock-hunter.plan.md) | 完整系统设计计划（含 16 轮毒辣拷打） |
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
