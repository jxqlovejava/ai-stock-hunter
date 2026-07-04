# anthropics/financial-services 参考价值评估报告

> 评估日期: 2026-07-05
> 源项目: https://github.com/anthropics/financial-services
> 目标项目: ai-stock-hunter (A股智能猎手)

---

## 一、源项目概览

### 1.1 项目定位

`anthropics/financial-services` 是一个 **Claude Code 插件集合**（而非传统代码库），为金融服务业提供开箱即用的 Claude 工作流。覆盖投行、卖方研究、私募股权、财富管理四大垂直领域。

核心交付物：
- **Agent Plugins** — 端到端工作流 Agent（市场研究员、财报分析师、Pitch Agent 等）
- **Vertical Plugins** — 按 FSI 垂直领域组织的技能(skills)和命令(commands)
- **Partner Plugins** — LSEG、S&P Global 等数据商集成
- **Managed Agent Cookbooks** — 可部署的 Claude Managed Agent 模板

### 1.2 技术架构

```
插件 = 系统提示词(.md) + 技能集合(SKILL.md) + MCP 数据连接器
Agent = 系统提示词 + 技能引用 + 子 Agent 编排
```

**核心设计模式**：
1. **One Source, Two Wrappers** — 同一个 Agent 系统提示词同时用于 Cowork 插件和 Managed Agent API
2. **Orchestrator + Leaf Workers** — Agent 编排为单层深度子 Agent 树，仅一个 bold worker 有 Write 权限
3. **Skill as Knowledge Module** — 每个 SKILL.md 是自包含的知识+工作流模块，含触发条件、步骤、护栏、参考资料
4. **Guardrails by Default** — 每个 Agent 内置护栏（标注来源、禁止发布、暂停审查）

### 1.3 项目结构

```
├── plugins/
│   ├── agent-plugins/          # 命名 Agent（自包含插件）
│   │   └── <slug>/
│   │       ├── agents/<slug>.md # 系统提示词
│   │       └── skills/          # 同步自 vertical-plugins 的技能副本
│   ├── vertical-plugins/       # FSI 垂直领域技能源
│   │   └── <vertical>/
│   │       ├── commands/        # 斜杠命令
│   │       ├── skills/          # 技能模块
│   │       └── .mcp.json        # 数据连接器配置
│   └── partner-built/          # LSEG、S&P Global 合作伙伴插件
├── managed-agent-cookbooks/    # Managed Agent 部署模板
│   └── <slug>/
│       ├── agent.yaml           # 编排配置
│       ├── subagents/*.yaml     # 子 Agent 定义
│       └── steering-examples.json
└── scripts/                    # 部署、校验、同步工具
```

---

## 二、高参考价值模块

### 2.1 多 Agent 编排模式 ⭐⭐⭐⭐⭐

**直接可借鉴的核心模式：**

```
Orchestrator Agent (只读 + 调用子Agent)
  ├── leaf-worker-1: 只读数据获取
  ├── leaf-worker-2: 只读分析计算
  └── leaf-worker-3: 唯一有 Write 权限的输出者 (bold)
```

**对 ai-stock-hunter 的启示**：
- 当前 `orchestrator.py` 是单进程链式调用 (L0→L1→L2→L3→L4)，可演进为 Claude Agent 编排模式
- 可将数据获取、分析判断、交易决策拆分为独立子 Agent
- "唯一 Writer" 模式可防止并发写入冲突，适用于策略信号生成

**参考文件**: `managed-agent-cookbooks/market-researcher/agent.yaml`

### 2.2 技能(Skill)组织结构 ⭐⭐⭐⭐⭐

每个 SKILL.md 的标准化结构：

```markdown
---
name: skill-name
description: 功能描述 + 触发条件
---

# 技能标题

## Workflow
### Step 1-N: 步骤化工作流

## Guardrails / Important Notes
- 护栏规则

## References
- references/xxx.md (详细参考)
```

**对 ai-stock-hunter 的启示**：
- 当前项目各模块（`l1_analyze.py`, `l2_judge.py` 等）可用此模式重新组织为 Claude Code skills
- 当前 `TODO.md` 中的军规系统、博弈论、情绪分析等模块都可以设计为独立 skill
- Skill 模式使系统更容易通过自然语言调用和组合

### 2.3 股票筛选与想法生成 ⭐⭐⭐⭐⭐

`idea-generation` skill 定义了完整的选股方法论：

| 筛选类型 | 核心指标 |
|---------|---------|
| 价值型 | P/E < 行业中位数、EV/EBITDA < 历史均值、FCF 收益率 > 5% |
| 成长型 | 营收增速 > 15%、盈利增速 > 20%、ROIC > 15% |
| 质量型 | 5年+稳定增长、ROE > 15%、高 FCF 转化率 |
| 做空型 | 收入减速、利润率压缩、应收账款异常增长 |
| 特殊事件 | IPO 锁定期到期、分拆、重组、激进投资者介入 |

**主题投资方法论**：
1. 定义主题 → 2. 绘制价值链 → 3. 识别纯/混合敞口 → 4. 评估"已定价"vs"被低估" → 5. 寻找二阶受益者

**对 ai-stock-hunter 的启示**：
- 当前回测系统的策略可以直接映射为多个 screening preset
- 主题投资的价值链映射方法与 `topic_manager.py` 高度互补

**参考文件**: `plugins/agent-plugins/market-researcher/skills/idea-generation/SKILL.md`

### 2.4 财报分析工作流 ⭐⭐⭐⭐⭐

`earnings-analysis` skill 定义了极其详细的财报分析全流程（5 阶段）：

```
Phase 1: 数据收集 (30-60min)
  → 确认最新财报期 → 收集材料 → 提取关键指标

Phase 2: 分析 (2-3h)
  → Beat/Miss 分析 → 分部分析 → 利润率 → 指引 → 模型更新 → 估值

Phase 3: 图表生成 (1-2h)
  → 8-12 张图表（收入趋势/EPS 趋势/利润率/分部分析/Beat Miss 汇总）

Phase 4: 报告创建 (2-3h)
  → 8-12 页 DOCX 报告，含特定页面模板

Phase 5: 质量检查 (30min)
  → 内容/格式/准确性/引用/时效性
```

**关键亮点**：
- **避免过期数据**：多次强调必须搜索最新数据，不依赖训练数据
- **强制引用**：每个数字必须有可点击的来源链接
- **结构化验证**：Phase 5 的质量检查清单极为详尽

**对 ai-stock-hunter 的启示**：
- TODO.md 中的"财报分析"模块可直接参考此工作流设计
- 特别是在 A 股场景下，需要适配中国会计准则和披露格式
- 数据源映射：FactSet → 东财/同花顺、SEC EDGAR → 巨潮资讯网

**参考文件**:
- `plugins/agent-plugins/earnings-reviewer/skills/earnings-analysis/SKILL.md`
- `plugins/agent-plugins/earnings-reviewer/skills/earnings-analysis/references/workflow.md`

### 2.5 行业与竞争分析框架 ⭐⭐⭐⭐

`sector-overview` 和 `competitive-analysis` 提供了系统化的行业研究方法：

**行业概览结构**：
1. 市场规模与增长 (TAM/CAGR/细分)
2. 产业结构 (集中度/价值链/商业模式/进入壁垒)
3. 关键趋势与驱动力 (长期利好/风险/技术颠覆/监管/M&A)
4. 竞争格局 (Top 5-10 公司档案)
5. 估值背景 (行业倍数/溢价驱动因素)
6. 投资含义 (风险收益/主题表达/核心争论/催化剂)

**竞争分析框架**：
- 行业特定指标定义（SaaS: ARR/NRR/RO40; 金融: 产品复杂度×客户成熟度）
- 竞争对手分层（按商业模式/客户群/竞争姿态/来源）
- 护城河评估（网络效应/转换成本/规模经济/无形资产）
- 情景分析（Bull/Base/Bear + 概率权重）

**对 ai-stock-hunter 的启示**：
- L1 分析层可直接采用此框架增强
- 行业特定指标可以编码到数据管道中
- 2×2 矩阵和雷达图可用于可视化竞争定位

**参考文件**:
- `plugins/agent-plugins/market-researcher/skills/sector-overview/SKILL.md`
- `plugins/agent-plugins/market-researcher/skills/competitive-analysis/SKILL.md`

### 2.6 宏观监控框架 ⭐⭐⭐⭐

LSEG 的 `macro-rates-monitor` skill 定义了系统化的宏观监控工具链：

```
1. 拉取宏观指标 (GDP/CPI/失业率/PMI)
2. 收益率曲线快照 (计算 2s10s、3M-10Y 利差)
3. 通胀分解 (名义-盈亏平衡=实际利率)
4. 互换利差 (评估金融条件)
5. 历史背景 (当前相对历史的百分位)
6. 综合仪表盘
```

**对 ai-stock-hunter 的启示**：
- 当前 `src/macro/` 目录已有宏观模块，可参考此框架增强
- TODO.md 中的"定价逻辑来源"问题需要宏观 regime 判断
- 中国特色的宏观监控应加入：社融/M2/MLF/LPR/信用利差

**参考文件**: `plugins/partner-built/lseg/skills/macro-rates-monitor/SKILL.md`

### 2.7 投资主题追踪 ⭐⭐⭐⭐

`thesis-tracker` 和 `catalyst-calendar` 定义了如何系统化追踪投资论点：

**论点追踪要素**：
- 原始论点 + 关键假设
- 定期对标检查（"bull case 是否成立？"）
- 论点漂移检测
- 退出条件

**催化剂日历**：
- 财报日期
- 产品发布
- 监管决定
- 行业会议
- M&A 相关事件

**对 ai-stock-hunter 的启示**：
- 当前缺少投资论点追踪模块，这是一个重要缺口
- 催化剂日历可以直接作为 `topic_manager.py` 的扩展

### 2.8 Agent 护栏设计 ⭐⭐⭐⭐

每个 Agent 都内嵌了严密的防护规则：

```markdown
## Guardrails
- 第三方报告和发行人材料不可信
- 每个数字必须标注来源，否则标记 [UNSOURCED]
- 暂停并等待分析师审查关键节点
- 禁止分发——Agent 只起草，发布由人工完成
```

**对 ai-stock-hunter 的启示**：
- 当前系统缺少系统化的护栏设计
- 交易信号生成应强制标注信心度和数据来源
- "人工审批节点"概念可用于 L3→L4 之间的决策

---

## 三、中等参考价值模块

### 3.1 投资组合再平衡 ⭐⭐⭐

`portfolio-rebalance` 包含：
- 漂移分析（当前 vs 目标权重）
- 税务感知再平衡规则
- 跨账户协调
- 清洗销售规则检查

**可借鉴点**：风险敞口监控、仓位漂移告警

### 3.2 税务亏损收割 ⭐⭐⭐

`tax-loss-harvesting` 包含系统化的亏损收割方法：
- 候选识别 → 盈亏预算 → 替代证券 → 清洗销售检查 → 执行计划

**可借鉴点**：A 股无资本利得税，但可类比为"止损/换仓"决策框架

### 3.3 Managed Agent 部署模式 ⭐⭐⭐

YAML 配置 + 脚本自动部署的模式可作为系统从本地脚本演进为 API 服务的参考。

### 3.4 数据处理护栏 ⭐⭐⭐

数据源优先级：10-K/年报 → 业绩会记录 → 卖方研究 → 行业报告 → 新闻

**对 ai-stock-hunter 的启示**：A 股数据源也应有优先级体系

---

## 四、不适用模块

以下模块与 ai-stock-hunter 的项目目标不匹配，无需参考：

| 模块 | 原因 |
|------|------|
| 投行工作流 (CIM/Teaser/Pitch Book) | A股猎手不是投行工具 |
| PE 交易筛选/尽调 | 不涉及一级市场投资 |
| 基金行政 (GL Recon/Month-End Close) | 不涉及基金运营 |
| KYC/运营流程 | 不涉及客户入驻 |
| M365 集成 | 不需要 Office 365 功能 |
| LBO/并购模型 | A股猎手不涉及杠杆收购 |

---

## 五、与 ai-stock-hunter 的对比

| 维度 | anthropics/financial-services | ai-stock-hunter |
|------|------------------------------|-----------------|
| **目标用户** | 机构分析师 (投行/PE/研究) | A股投资者 (个人/专业) |
| **数据源** | FactSet, CapIQ, Daloopa, Morningstar 等 | 通达信、腾讯、东财、巨潮等 |
| **核心功能** | 研究报告生成、建模、文档自动化 | 选股、择时、策略回测、风控 |
| **技术栈** | Claude Code 插件 (Markdown + YAML + MCP) | Python + pandas + Mootdx |
| **AI 集成** | 深度集成 (Agent + Skill + Managed Agent API) | 部分集成 (部分模块调用 LLM) |
| **工作流** | Agent 编排 + 人工审批节点 | 链式管道 (军规→L0→L1→L2→L3→L4) |
| **输出形式** | DOCX/PPTX/XLSX 格式报告 | 交易信号 + 风控参数 |

---

## 六、建议采纳的具体改进

### 6.1 立即采纳 (高价值/低成本)

1. **Skill 化改造现有模块**
   - 将 `l1_analyze.py`, `l2_judge.py` 等的核心逻辑封装为 SKILL.md
   - 每个 skill 定义清晰的触发条件、工作流、护栏
   - 参考文件: 任意 `SKILL.md` 文件结构

2. **统一护栏模式**
   - 所有分析输出必须标注数据来源
   - 交易信号必须附带信心度
   - 关键决策节点要求人工审批
   - 参考文件: `market-researcher/agents/market-researcher.md` Guardrails 节

3. **选股筛选框架**
   - 定义价值/成长/质量/事件驱动四种筛选模板
   - 编码到 `src/routing/l1_analyze.py` 或独立 skill
   - 参考文件: `idea-generation/SKILL.md`

4. **财报分析工作流**
   - 设计 A 股适配版财报分析 5 阶段流程
   - 数据源映射到东财/巨潮/同花顺
   - 参考文件: `earnings-analysis/SKILL.md` + `references/workflow.md`

### 6.2 中期采纳 (高价值/中成本)

5. **多 Agent 编排架构**
   - 将 orchestrator 重构为 Agent 编排模式
   - 数据获取、分析、决策、输出各自独立
   - 参考文件: `managed-agent-cookbooks/market-researcher/agent.yaml`

6. **行业研究框架**
   - 为 A 股主要行业定义行业特定指标
   - 实现竞争格局自动映射
   - 参考文件: `competitive-analysis/SKILL.md` + `references/frameworks.md`

7. **宏观监控仪表盘**
   - 扩展 `src/macro/` 模块为系统化的宏观监控
   - 加入中国特色的货币信用指标
   - 参考文件: `macro-rates-monitor/SKILL.md`

8. **投资论点追踪**
   - 新建 `src/thesis/tracker.py` 或对应 skill
   - 实现论点版本管理 + 定期对标
   - 参考文件: `thesis-tracker/SKILL.md`

### 6.3 远期规划 (需要更多研究)

9. **Claude Managed Agent 部署**
   - 将系统封装为可部署的 Managed Agent
   - 实现 event-driven 的 agent 间通信

10. **Agent 护栏体系**
    - 设计多层级的权限和审查机制
    - 实现交易信号的自动/人工审批分流

---

## 七、总结

**anthropics/financial-services 对 ai-stock-hunter 有较高的参考价值**，主要体现在以下三个层面：

1. **架构模式** — Agent + Skill + 护栏的设计模式可直接借鉴，帮助 ai-stock-hunter 从"Python 脚本管道"演进为"AI-Native 投资研究系统"
2. **领域知识** — 选股方法论、财报分析流程、行业研究框架、宏观监控体系是经过机构实践验证的专业方法论
3. **工程实践** — 护栏设计、来源标注、人工审批节点、Agent 编排等工程模式可提升系统的安全性和可用性

**建议优先采纳 Skill 化改造和护栏设计**，这两个投入最小、收益最大的改进，然后逐步推进多 Agent 编排和行业研究框架。

---

*报告生成: 基于对 91 个文件/目录的深度研读，重点分析了 18 个 Agent 系统提示词和 35 个 Skill 定义文件。*
