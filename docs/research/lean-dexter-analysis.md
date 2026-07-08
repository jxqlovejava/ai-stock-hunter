# LEAN + Dexter 源码深度分析报告

> 2026-07-08 | 分析人：Claude Code | 源码位置：~/Documents/workspace/Lean-master、~/Documents/workspace/dexter-main

---

## 一、总览

两个项目从不同维度提供了可借鉴的设计：

| 维度 | LEAN (QuantConnect) | Dexter (virattt) |
|------|---------------------|------------------|
| 语言 | C# (主体) + Python (算法层) | TypeScript (Bun) |
| 规模 | 10k+★，工业级量化引擎 | 27.3k★，金融研究 Agent |
| 核心价值 | 事件驱动管道、模型化架构、回测/实盘统一 | Agent 循环、上下文管理、调试审计、输出抽象 |
| 最适用场景 | 回测引擎重构、仓位/风控模型化 | 编排管道重构、LLM 调用管理、输出系统升级 |

---

## 二、LEAN：10 个可借鉴模式

### 1. 框架管道模型（最高优先级）

LEAN 的五阶段管道通过接口实现可插拔：

```
UniverseSelection → Alpha → PortfolioConstruction → Risk → Execution
```

**我们当前的对应：**
```
军规(Doctrine) → 准入(Admission) → 诊断(Diagnosis) → 裁决(Verdict) → 仓位(Positioning) → 风控(Risk)
```

**差距**：当前 `orchestrator.py` 硬编码各阶段，无法插拔替换。

**建议行动**：
1. 为每个阶段定义 Python Protocol（`AlphaModel`, `PortfolioModel`, `RiskModel` 等）
2. `Orchestrator` 接受模型注入而非内部构造
3. 支持同一类型多模型组合（`CompositeRiskModel`）

**涉及文件**：`src/routing/orchestrator.py`、新增 `src/routing/models/` 子包

---

### 2. Insight 数据模型（信号载体）

LEAN 的 `Insight` 是统一的信号对象，只携带预测信息，不混合仓位决策：

```csharp
class Insight {
    Symbol, Direction, Magnitude, Confidence, Weight,
    Period, SourceModel, Score  // Score 跟踪预测准确度
}
```

**我们当前的对应**：`TradeSignal`（`src/routing/positioning.py`）混合了信号 + 仓位。

**建议行动**：
1. 新增 `Signal` dataclass：symbol, direction, magnitude, confidence, time_horizon, source_model
2. `PositioningEngine` 从 `Signal` 生成 `PositionTarget`（纯仓位对象）
3. 实现信号准确度追踪：`SignalTracker` 记录预测 vs 实际，用于置信度校准

**涉及文件**：`src/routing/verdict.py`、`src/routing/positioning.py`、新增 `src/routing/signal.py`

---

### 3. 组合模型模式

LEAN 的 `CompositeRiskManagementModel` 将多个风控模型链式组合：

```csharp
// 每个模型调整目标，后一个模型可覆盖前一个
foreach (var model in riskModels) {
    targets = model.ManageRisk(algorithm, targets)
        .Concat(targets).DistinctBy(t => t.Symbol).ToArray();
}
```

**建议行动**：
1. 将 31 条军规重构为 `DoctrineRule` Protocol 对象
2. `CompositeDoctrineChecker` 组合多条规则
3. 每条规则独立可测试、可启用/禁用

**涉及文件**：`src/doctrine/rules.py`、`src/doctrine/checker.py`

---

### 4. 数据馈送抽象

LEAN 的 `IDataFeed` 统一回测和实盘数据源：

```csharp
interface IDataFeed {
    Initialize(algorithm, packet, resultHandler);
    Subscription CreateSubscription(request);
    void RemoveSubscription(subscription);
}
```

**我们已有基础**：`DataAggregator` 已实现多源降级。缺少的是：
- **订阅概念**：追踪每个分析需要什么数据
- **前向填充**：填补日线数据间隙
- **时间提供者抽象**：`ITimeProvider` 解耦时间与数据

**涉及文件**：`src/data/aggregator.py`、`src/data/base.py`

---

### 5. 算法生命周期

LEAN 的 `QCAlgorithm` 提供清晰的生命周期钩子：

```
Constructor → Initialize() → OnData() → OnOrderEvent() → OnEndOfDay() → OnEndOfAlgorithm()
```

**建议行动**：
1. 将 `Orchestrator` 重构为生命周期明确的类
2. 分拆 `orchestrator.py`（1348 行）为 `pipeline.py` + `workers.py` + `context.py`
3. 每个阶段产生 `StageResult` 而非直接修改全局状态

**涉及文件**：`src/routing/orchestrator.py`（拆分为 3-4 个文件）

---

### 6. 组合目标解析（Signal → Action）

`PortfolioConstructionModel` 将 `Insight[]` 转换为 `PortfolioTarget[]`：

- 获取活跃 insights → 确定目标百分比 → 创建 `PortfolioTarget.Percent()` → 处理过期信号
- 支持再平衡调度（`IsRebalanceDue()`）

**建议行动**：
1. 拆分 `PositioningEngine` 为 `PositionSizer` + `SignalGenerator`
2. 新增 `PortfolioTarget` dataclass（纯 {symbol, quantity}）
3. Kelly sizer 变为可插拔的 `IPositionSizer`

**涉及文件**：`src/routing/positioning.py`、`src/kelly/sizer.py`

---

### 7. Insight 评分与反馈循环

`InsightManager` 管理信号生命周期：
- 存储活跃信号 → `Step(utcNow)` 评分 → `Expire()` 过期 → 追踪方向/幅度准确度

**建议行动**：
1. 新增 `SignalTracker` 归档管道产生的信号
2. 对比预测 vs 实现价格，计算方向正确率、幅度误差
3. 回馈到 `VerdictEngine` 权重校准（贝叶斯更新）

**涉及文件**：`src/routing/verdict.py`、`src/kelly/tracker.py`

---

### 8. 证券变更事件

`OnFrameworkSecuritiesChanged()` 通知所有模型当股票进入/退出 universe：

**建议行动**：
- 单票分析场景下暂不需要
- 多股票组合分析时必须实现（Phase 3-4）

**涉及文件**：`src/routing/orchestrator.py`

---

### 9. Python 桥接模式

LEAN 用 `*PythonWrapper.cs` 桥接 Python 算法到 C# 基类。

**我们不需要**（全 Python），但"委托给可插拔实现"的模式已体现在建议 1、2、3 中。

---

### 10. 分部类组织

`QCAlgorithm` 拆分为 5 个文件：`.cs` / `.Framework.cs` / `.History.cs` / `.Indicators.cs` / `.Plotting.cs`

**建议行动**：同上第 5 点，拆分 1348 行的 `orchestrator.py`。

---

## 三、Dexter：14 个可借鉴模式

### 1. 事件驱动 Agent 循环（最高优先级）

Dexter 的 `Agent.run()` 是 `AsyncGenerator<AgentEvent>`，产生类型化事件供消费者消费：

```typescript
type AgentEvent = 
  | { type: 'thinking', text: string }
  | { type: 'tool_start', toolName: string, id: string }
  | { type: 'tool_end', toolName: string, id: string, result: any }
  | { type: 'compaction', summary: string }
  | { type: 'done', result: string }
```

**建议行动**：
1. 将 `Orchestrator.run()` 改为 async generator，yield `StageEvent`
2. 新增 `src/routing/events.py` — 类型化事件 dataclass
3. CLI 消费事件流进行增量渲染

**涉及文件**：`src/routing/orchestrator.py`、新增 `src/routing/events.py`、`src/cli.py`

---

### 2. Scratchpad 审计日志

Dexter 的 scratchpad 是 JSONL 追加日志，记录每个 tool_call + result + thinking：

```jsonl
{"type":"init","query":"分析贵州茅台"}
{"type":"tool_result","toolName":"get_income_statements","args":{...},"result":{...},"llmSummary":"..."}
{"type":"thinking","text":"从财报看，茅台..."}
```

**建议行动**：
1. 新增 `AnalysisScratchpad` 类，写入 `output/scratchpad/{symbol}_{timestamp}.jsonl`
2. 每个管道阶段追加：stage_name, inputs_summary, outputs_summary, warnings
3. 增加查询去重：检测重复 API 调用
4. 支持中断恢复：`get_stage_results()` 返回已完成的分析

**涉及文件**：新增 `src/routing/scratchpad.py`、`src/routing/orchestrator.py`

---

### 3. 上下文压缩（LLM 摘要）

Dexter 用快速 LLM 将大量工具结果压缩为 9 段结构化摘要：

```
## Query | ## Key Concepts | ## Data Retrieved | ## Errors | 
## Progress | ## Important Numbers | ## Data Gaps | 
## Current State | ## Suggested Next Steps
```

**建议行动**：
1. 新增 `Compactor` 类，用廉价模型（deepseek-v4-flash）做摘要
2. 定义 5 段股票分析专用格式：(1) 标的基础信息 (2) 技术数据 (3) 基本面数据 (4) 分析进展 (5) 待解决问题
3. 在 LLM 密集阶段（诊断、裁决、辩论）前触发

**涉及文件**：新增 `src/llm/compactor.py`、`src/routing/orchestrator.py`

---

### 4. 微压缩

每轮 LLM 调用前清除旧的只读工具结果，保留最近 4 个：

**算法**：
- 计数触发：8+ 个可压缩消息
- Token 触发：估算 token > 80k
- 保留结构（tool_call_id），替换内容为 `[cleared]`

**建议行动**：
- 当前管道架构下不直接适用（无 tool-calling loop）
- 概念可用于 LLM 分析阶段：清除旧分析结果，保留最近上下文

**涉及文件**：新增 `src/utils/context_budget.py`

---

### 5. 渠道配置文件

Dexter 的 `ChannelProfile` 控制不同输出渠道的格式和行为：

```typescript
interface ChannelProfile {
  label: string;        // "CLI", "WhatsApp", "API"
  preamble: string;     // 渠道特定前缀
  behavior: string[];   // 行为约束
  responseFormat: string[]; // 格式规则
  tables: string;       // 表格渲染规则
}
```

**建议行动**：
1. 新增 `OutputProfile` dataclass：`CLIProfile`, `WeChatProfile`, `APIProfile`
2. 每个 profile 定义：table_style, markdown_allowed, max_length, language, tone
3. `src/output/formatter.py` 改为 profile-aware

**涉及文件**：新增 `src/output/profiles.py`、`src/output/formatter.py`

---

### 6. 流式输出与模式检测

Dexter 实时检测 LLM 输出内容类型：`thinking → responding → tool-input → tool-use`

**建议行动**：
1. 所有 LLM 分析阶段支持流式输出
2. 新增 `StreamResult` namedtuple: `text_delta, mode, structured_data`
3. CLI 根据 mode 显示不同状态指示器

**涉及文件**：`src/routing/l1_analyze.py`、`src/routing/l2_judge.py`、`src/cli.py`

---

### 7. RunContext — 可变查询状态

Dexter 用单个 `RunContext` 对象携带所有查询状态，避免参数层层传递：

```typescript
interface RunContext {
  query: string;
  scratchpad: Scratchpad;
  tokenCounter: TokenCounter;
  startTime: number;
  iteration: number;
  lastApiInputTokens: number;
  memoryFlushState: MemoryFlushState;
}
```

**建议行动**：
1. 新增 `AnalysisContext` dataclass：symbol, market, query, scratchpad, token_counter, start_time, iteration, current_stage, warnings[], data_gaps[]
2. 每个管道阶段接收并变更 context
3. 最终 `OrchestratorResult` 从 context 生成

**涉及文件**：新增 `src/routing/context.py`、`src/routing/orchestrator.py`

---

### 8. 工具执行器 — 安全/非安全分区

Dexter 将工具调用分为并发安全（只读查询）和串行（写操作），安全工具批量并行执行：

**建议行动**：
1. 定义并发组：`DATA_TOOLS`（行情、财报、宏观、新闻）可并行；`ANALYSIS_TOOLS`（诊断、估值、博弈论）部分并行
2. `DataFetcher` 类：安全/非安全分区、最大并发限制、进度回调

**涉及文件**：`src/data/aggregator.py`、新增 `src/data/fetcher.py`

---

### 9. Token 计数器

Dexter 追踪每次查询的总 token 消耗，支持 `getTokensPerSecond()` 速率显示：

**建议行动**：
1. 新增 `TokenCounter` 类
2. 注入所有 LLM 调用点
3. 在 `OrchestratorResult` 和最终报告中展示

**涉及文件**：新增 `src/utils/token_counter.py`、`src/output/formatter.py`

---

### 10. Provider 注册表

Dexter 的 `PROVIDERS` 数组是 LLM 提供商的单一元数据源，模块通过前缀匹配自动路由：

**建议行动**：
1. 新增 `ProviderRegistry`：`deepseek-*` → DeepSeek, `qwen-*` → Qwen, `gpt-*` → OpenAI
2. 包含 `context_window`、`fast_model`、API key 解析
3. 支持 model 前缀自动路由

**涉及文件**：新增 `src/llm/providers.py`、`src/config.py`

---

### 11. 内存刷新（三级上下文管理）

Dexter 的三级升级策略：内存刷新 → 压缩 → 截断：

**建议行动**：
1. Level 1：中间结果持久化到磁盘（`output/analysis/{symbol}/`）
2. Level 2：LLM 摘要压缩
3. Level 3：上下文截断（仅保留最近 N 阶段）

**涉及文件**：新增 `src/llm/context_manager.py`

---

### 12. SOUL.md 身份系统

Dexter 的 `SOUL.md` 定义 agent 哲学基础，加载后注入系统 prompt：

**建议行动**：
1. 新增 `src/doctrine/DOCTRINE.md`：系统投资哲学和分析原则
2. `IdentityLoader` 加载并注入 LLM prompt
3. 支持用户自定义 `DOCTRINE.user.md`

**涉及文件**：新增 `src/doctrine/identity_loader.py`、`src/routing/l1_analyze.py`

---

### 13. 工具审批流

Dexter 对敏感操作（文件写）触发交互式审批：`allow-once | allow-session | deny`

**建议行动**：
1. 新增 `ApprovalGate` 类
2. 应用于：交易信号生成、组合修改、外部 API 写操作
3. CLI 集成审批提示

**涉及文件**：`src/routing/guardrails.py`、`src/cli.py`

---

### 14. Skills 系统

Dexter 的 skills 是 YAML/markdown 工作流文件，LLM 按需调用：

**建议行动**：
1. 新增 `src/workflows/` 目录，YAML 格式工作流
2. `WorkflowLoader` 加载并暴露给分析引擎
3. Orchestrator 可按股票类型动态加载适用工作流

**涉及文件**：新增 `src/workflows/`、`src/workflows/loader.py`

---

## 四、优先级排序（按投入产出比）

### 立即实施（本周）

| # | 模式 | 来源 | 工作量 | 影响 |
|---|------|------|--------|------|
| 1 | Scratchpad 审计日志 | Dexter | 小 | 调试效率翻倍 |
| 2 | RunContext / AnalysisContext | Dexter | 小 | 清理参数传递 |
| 3 | Signal vs PositionTarget 分离 | LEAN | 中 | 仓位模型可插拔 |
| 4 | 事件驱动管道 | Dexter | 大 | CLI 实时进度 |

### 短期（1-2 周）

| # | 模式 | 来源 | 工作量 | 影响 |
|---|------|------|--------|------|
| 5 | 组合模型（CompositeRisk） | LEAN | 中 | 风控规则可插拔 |
| 6 | Provider 注册表 | Dexter | 小 | LLM 调用统一 |
| 7 | Token 计数器 | Dexter | 小 | 成本透明 |
| 8 | 渠道配置文件 | Dexter | 中 | 多输出格式 |

### 中期（Phase 2-3）

| # | 模式 | 来源 | 工作量 | 影响 |
|---|------|------|--------|------|
| 9 | 框架管道接口化 | LEAN | 大 | 架构升级 |
| 10 | 上下文压缩 | Dexter | 中 | 长分析不丢信息 |
| 11 | Skills/Workflows 系统 | Dexter | 中 | 分析类型可扩展 |
| 12 | Insight 评分反馈循环 | LEAN | 中 | 置信度真实校准 |

### 远期（Phase 3-4）

| # | 模式 | 来源 | 
|---|------|------|
| 13 | 数据馈送抽象（Subscription/Fill-Forward） | LEAN |
| 14 | 流式输出 + 模式检测 | Dexter |
| 15 | 工具执行器安全分区 | Dexter |
| 16 | 三级上下文管理 | Dexter |

---

## 五、不借鉴的部分

| 项目 | 不借鉴 | 原因 |
|------|--------|------|
| LEAN | C# 实现 | 我们全 Python |
| LEAN | QuantConnect 云平台 | 不依赖外部平台 |
| LEAN | 多资产（期权/期货/外汇） | A 股聚焦 |
| LEAN | LEAN CLI 工具链 | 有自己的 CLI |
| Dexter | Bun/TypeScript 技术栈 | 我们全 Python |
| Dexter | 美股数据源 | 聚焦 A 股数据源 |
| Dexter | WhatsApp/群聊渠道 | 不适用 |
| Dexter | Ink/React TUI 组件 | Python rich/textual 替代 |
