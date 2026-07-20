# go-stock — AI 赋能股票分析桌面应用参考分析

> 源码：https://github.com/ArvinLovegood/go-stock（GNU GPLv3）  
> 本地：`~/Documents/workspace/go-stock-dev`  
> 定位：基于 Wails + NaiveUI 的 AI 大模型驱动桌面股票分析工具，支持 A 股/港股/美股

---

## 一、项目全景

### 1.1 核心命题

go-stock 是一个面向个人投资者的桌面端 AI 股票分析工具，核心思路是：**让大模型通过工具调用获取实时行情/财务/资讯数据，再生成分析结论**。与白泽的区别在于：

| 维度 | go-stock | 白泽 |
|------|---------|------|
| 形态 | 桌面 GUI（Wails） | CLI + Agent 管道 |
| 语言 | Go + Vue/NaiveUI | Python |
| Agent 框架 | CloudWeGo Eino | 自研多 Agent |
| 分析模式 | LLM tool-use 即时分析 | 多阶段管道（军规→准入→诊断→裁决→调度→风控） |
| 工具调用 | Agent 自主选择工具 | 各阶段固定工具集 |
| 决策输出 | AI 分析报告（人类阅读） | 交易信号 + 风控决策 |
| 角色 | **AI 辅助研究** | **AI 决策管道** |

### 1.2 技术栈

| 层 | 技术 | 说明 |
|----|------|------|
| 桌面框架 | Wails v2 | Go 后端 + Web 前端 → 桌面应用 |
| 后端 | Go 1.26 | 数据获取 / Agent 引擎 / MCP 客户端 |
| 前端 | Vue 3 + NaiveUI + Vite | 组件化 UI |
| 数据库 | SQLite（glebarez/sqlite） | 会话记忆 / 配置 / 交易记录 |
| Agent 框架 | CloudWeGo Eino | React / PlanExecute / DeepAgents |
| MCP | mark3labs/mcp-go | MCP 客户端/服务端 |
| K 线渲染 | 自研 Canvas K 线组件 | 技术指标 / 筹码分布 / 绘图工具 |
| 分词 | go-ego/gse | 中文分词（Go 原生） |
| 爬虫 | chromedp + goquery + resty | 浏览器自动化 + HTML 解析 |

### 1.3 LLM Provider 矩阵

go-stock 通过 Eino 的 ChatModel 抽象层接入了 10+ 大模型 provider：

| Provider | Eino 包 | 用途 |
|---------|---------|------|
| OpenAI | `eino-ext/components/model/openai` | 通用 / 兼容任何 OpenAI 接口 |
| DeepSeek | `eino-ext/components/model/deepseek` | deepseek-chat / deepseek-reasoner |
| Claude | `eino-ext/components/model/claude` | Anthropic Claude 系列 |
| Gemini | `eino-ext/components/model/gemini` | Google Gemini |
| Qwen (通义千问) | `eino-ext/components/model/qwen` | 阿里通义千问 |
| Ark (火山方舟) | `eino-ext/components/model/ark` | 字节火山引擎 |
| Ollama | `eino-ext/components/model/ollama` | 本地模型运行 |
| OpenRouter | `eino-ext/components/model/openrouter` | 模型聚合路由 |

对应白泽 LLM 调用统一入口的需求。

---

## 二、Agent 架构详解

### 2.1 多模式 Agent 引擎

go-stock 的 Agent 层（`backend/agent/`）支持三种运行模式，根据问题复杂度自动切换：

```go
type AgentMode string
const (
    AgentModeReact       AgentMode = "react"        // ReAct 循环（简单问答）
    AgentModePlanExecute AgentMode = "plan_execute" // 先计划后执行（复杂分析）
    AgentModeDeepAgents  AgentMode = "deepagents"   // 深度 Agent（最复杂场景）
)
```

**模式选择逻辑**（`classifyComplexity()`）：
1. 关键词检测 → `DetectQuestionIntent()` 返回 7 种意图之一
2. 问题字数 + 是否含多主体标记（"以及/并且/同时/对比"等）
3. 工具组分类 → `ClassifyQuestion()` 判断涉及工具组数量（≥5 组 → PlanExecute）

这完全基于规则，**零 LLM 调用成本**，速度快且确定性高。

### 2.2 意图检测系统

`DetectQuestionIntent()` 定义 7 种意图（优先级从高到低）：

| 意图 | 触发关键词 | 推荐模式 |
|------|----------|:---:|
| `IntentComprehensiveReport` | 全面分析/深度分析/投资建议/风险评估/产业链 | PlanExecute |
| `IntentScreening` | 筛选/选股/条件选股/MACD金叉/热门策略 | PlanExecute（>50字） |
| `IntentNewsResearch` | 新闻/资讯/公告/研报/龙虎榜/互动易 | React（≤80字） |
| `IntentMoneyFlow` | 资金/流入/流出/主力/北向 | React（≤80字） |
| `IntentMarketOverview` | 大盘/市场/指数/涨跌分布/宏观/GDP/PMI | React（≤80字） |
| `IntentCodeLookup` | 代码/简称/是哪只（不含行情词） | React |
| `IntentQuoteLookup` | 股价/行情/涨跌/实时 | React |
| `IntentGeneral` | 其他 | 按工具组数量判断 |

### 2.3 工具分组与动态过滤

~100+ 工具分为 7 组，按问题关键词动态加载：

| 工具组 | 工具数 | 触发关键词示例 |
|--------|:-----:|------|
| `base`（基础） | ~10 | 始终加载（股票代码/时间/自选股） |
| `stock_analysis`（个股分析） | ~30 | 股价/行情/K线/财务/ROE/PE/股东/融资融券 |
| `market`（市场） | ~15 | 大盘/指数/涨跌分布/全球指数/宏观/期货 |
| `screening`（选股） | ~15 | 筛选/选股/选ETF/选港股/形态选股/热门策略 |
| `money_flow`（资金） | ~5 | 资金/流入/流出/主力/北向 |
| `news_research`（资讯） | ~20 | 新闻/资讯/公告/研报/龙虎榜/互动易/华尔街见闻 |
| `ai_analysis`（AI分析） | ~4 | AI分析/AI推荐/历史分析 |
| `operations`（操作） | ~30 | 预警/钉钉/飞书/分组管理/概念标签 |

**核心理念**：不同问题场景只加载相关工具，减少 prompt 中工具描述占用的 token，提高 Agent 工具选择准确率。这对应白泽各分析阶段的工具集裁剪。

### 2.4 工具输出元数据标记

每个工具调用输出自动添加元数据行：

```
[as_of=2026-05-20 14:30:00] [tool=GetStockInfo] [status=ok]
... 工具实际输出 ...
```

`status` 自动检测：`ok` / `empty`（无数据/未找到） / `error`（异常）。

这对应白泽 guardrails 的数据溯源三要素要求（`source_citations` + `data_freshness` + `tier/nature`）。

### 2.5 时间上下文注入

`buildAgentTimeContext()` 在每次 Agent 调用前注入：
- 当前本地时间 + 星期
- 全球指数实时状态（道琼斯/纳斯达克/恒生等）
- A 股交易日提醒
- 数据时效性强制声明（"不得直接引用历史数字或训练记忆"）

这解决了 LLM 训练数据时间偏差问题。

---

## 三、MCP 与 Skill 系统

### 3.1 MCP 客户端/服务端

基于 `mark3labs/mcp-go` 实现，支持：
- **MCP Client**：连接外部 MCP Server（SSE / Streamable HTTP），动态发现工具
- **MCP Server 管理**：CRUD + 健康检查 + 启用/禁用
- **Tool 代理**：MCP 工具自动包装为 Eino `tool.BaseTool`，无缝接入 Agent 工具列表

### 3.2 Skill（技能模板）系统

Skill 是用户可配置的 AI 分析模板：

```go
type Skill struct {
    Name             string   // 技能名称
    Description      string   // 描述
    Category         string   // 分类
    SystemPrompt     string   // 系统提示词
    Examples         string   // 示例
    TriggerKeywords  string   // 触发关键词
    MCPServerIDs     string   // 绑定的 MCP 服务器 ID 列表
    Enable           bool     // 启用状态
}
```

这比白泽的 Markdown Skill 文件更结构化——支持数据库持久化、MCP 绑定、触发关键词匹配。白泽 Skill 体系可借鉴这种结构化存储 + 触发匹配机制。

### 3.3 飞书 Bot 集成

`backend/agent/feishu_bot.go` 实现了飞书 IM 接入，支持：
- 消息接收 / 回复
- 与 Agent 引擎联动（用户消息 → Agent 分析 → 返回结果）

---

## 四、数据源架构

### 4.1 数据提供者矩阵

| 数据源 | 文件 | 数据类型 | 协议 |
|--------|------|------|------|
| 东方财富 | `eastmoney_api.go` / `eastmoney_kline_api.go` | 行情/K线/资金流向/板块排名 | HTTP API |
| 新浪 | `sina_kline_api.go` | K线/分时 | HTTP API |
| 通达信 (TDX) | `tdx_kline_api.go` | K线（TCP 协议） | TCP（gotdx） |
| Tushare | `tushare_data_api.go` | 基本面/财务/宏观 | HTTP API |
| 华尔街见闻 | `wallstreetcn_api.go` | 全球快讯/日历/行情 | HTTP API |
| 雪球 | `xueqiu_chromedp.go` | 行情页数据 | chromedp 浏览器 |
| 同花顺问财 | `iwencai_api.go` | 自然语言选股/查询 | HTTP API（需 API Key） |
| 东财妙想 | `openai_api.go` → tool_* | AI 财报点评/行业研究/金融问答 | HTTP API（需 API Key） |

### 4.2 工具注册中心

`tool_registry.go` 实现统一的工具注册与 API Key 关联：
- `registerToolHandler(name, handler)` — 注册工具处理函数
- `toolRequiredKey` — 工具→所需 API Key 映射（IwencaiApiKey / EmApiKey / QgqpBId 等）
- 运行时检查 API Key 是否配置，未配置的工具自动标记不可用

这比白泽 `.env` 散落的 API Key 检查更系统化。

---

## 五、可直接借鉴到本项目的业务机制

| # | 机制 | 来源文件 | 应用到本项目 |
|---|------|---------|------------|
| 1 | **Eino Agent 多模式**（React/PlanExecute/DeepAgents 按复杂度自动切换） | `agent/agent.go:classifyComplexity()` | `routing/orchestrator.py` 按问题类型选择 Agent 深度 |
| 2 | **规则路由意图检测**（关键词→7 种意图→工具组，零 LLM 成本） | `agent/tools/intent.go` | 替代 LLM 做分析阶段路由，减少成本 |
| 3 | **工具分组+动态过滤**（7 组×关键词映射→按需加载工具，减少 token） | `agent/tools/tool_groups.go` | 各分析阶段裁剪工具集，减少 Agent prompt 上下文 |
| 4 | **工具输出元数据标记**（`[as_of=][tool=][status=]` 标准化） | `agent/agent_tool_meta.go` | guardrails 数据溯源标准化格式 |
| 5 | **时间上下文注入**（当前时间+全球指数+交易日+过期警告） | `agent/agent_context.go` | 分析启动前的环境上下文注入 |
| 6 | **MCP Client 集成**（mark3labs/mcp-go，SSE/Streamable HTTP） | `data/mcp_server_api.go` | 为白泽接入外部 MCP 工具服务 |
| 7 | **结构化 Skill 系统**（DB 持久化 + 触发关键词 + MCP 绑定） | `data/skill_api.go` | 白泽 skill 体系的结构化升级 |
| 8 | **多 Provider ChatModel 工厂**（10+ LLM provider 统一接口） | `agent/chat_model_factory.go` | 白泽 LLM 调用统一入口 |
| 9 | **定时任务 AI 分析**（cron + Agent 自动执行） | `agent/cron_task_api.go` | 自动盯盘 / 定时分析报告 / 盘前简报 |
| 10 | **SQLite 会话记忆**（session-based，可配置轮数） | `agent/chat_memory.go` | 替代 `interaction_log.jsonl` 的临时方案 |
| 11 | **Wails 桌面应用架构**（Go backend + Vue/NaiveUI frontend） | `app.go` + `frontend/` | CLI → 桌面 GUI 的升级参考 |
| 12 | **iwencai (问财) 自然语言查询**（NL→选股/数据查询） | `data/iwencai_api.go` | 与白泽 CLI scan/preset 互补 |
| 13 | **东财妙想 AI 工具**（财报点评/行业研究/可比公司/热点发现） | `data/tool_agent_*.go` | L1 多维诊断的 AI 辅助维度 |
| 14 | **工具可用性运行时检查**（API Key 未配置→工具自动标记不可用） | `data/tool_registry.go` | 替代散落的 `.env` 检查，集中管理 |
| 15 | **自研 K 线 Canvas 组件**（技术指标/筹码分布/绘图工具） | `frontend/src/components/kline/` | 前端可视化参考 |
| 16 | **飞书/钉钉 Bot 集成**（IM → Agent → 推送分析结果） | `agent/feishu_bot.go` | 告警/分析结果推送渠道 |

> ⚠️ **注意**：go-stock 是面向个人投资者的 AI 辅助分析桌面工具，不是全自动交易决策系统。其核心价值在于 **(1) Eino Agent 多模式架构 + 规则路由**、(2) **工具分组+动态过滤的 prompt 优化策略**、(3) **MCP + Skill 的扩展体系**、(4) **桌面应用的工程实践**。白泽可直接借鉴其 Agent 路由、工具管理、MCP 集成和数据结构化存储的工程方案。
