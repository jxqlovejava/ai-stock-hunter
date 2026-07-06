# Vibe-Trading 源码级参考报告

> 分析对象：`reference/Vibe-Trading`（本地副本）  
> 目的：识别可借鉴到 ai-stock-hunter A 股量化管道的架构、模块与机制。

---

## 1. 项目定位与高层架构

Vibe-Trading 是一个“自然语言 → 可运行金融分析”的开源 Agent。核心能力包括：

- 自然语言发起行情获取、策略生成、回测、因子研究
- 多 Agent 协同（swarm）
- 交易日志诊断（shadow account）
- 可导出产物（Pine Script、TDX、MT5、HTML/PDF 报告）
- 提供 FastAPI REST、SSE、MCP 三种对外接口

高层架构（Python 后端）：

```
CLI / REST / MCP
   |
   v
src.agent.loop.AgentLoop  (ReAct, 50 轮上限, 5 层上下文压缩)
   |
   v
ToolRegistry  (BaseTool 子类)
   |
   +-- get_market_data / factor_analysis / backtest
   +-- alpha_bench / alpha_zoo
   +-- shadow_account / trade_journal
   +-- swarm / channels / connectors
   |
   v
backtest.loaders.registry  (18 数据源 + fallback 链)
   |
   v
backtest.engines.base.BaseEngine  (bar-by-bar 执行)
```

前端 `frontend/` 是 React + Vite SPA，代理到 FastAPI。

---

## 2. 目录/模块职责

| 路径 | 职责 |
|------|------|
| `agent/api_server.py` | FastAPI REST、SSE 流式、`/run`、`/session`、`/goal` |
| `agent/mcp_server.py` | MCP stdio server，暴露 ToolRegistry |
| `agent/cli/` | 交互 TUI 与子命令（`vibe-trading`、`vibe-trading serve`） |
| `agent/src/agent/` | ReAct loop、memory、tool registry、progress、trace |
| `agent/src/tools/` | 45+ 工具实现（行情、回测、因子、shadow、swarm 等） |
| `agent/src/providers/` | LLM provider 封装、流式、内容过滤处理 |
| `agent/backtest/` | 回测引擎、loader、metrics、optimizer、validation |
| `agent/src/factors/` | Alpha Zoo 因子注册表与算子库 |
| `agent/src/swarm/` | 多 Agent 预设 YAML、worker runtime、task store |
| `agent/src/skills/` | Markdown 技能库（79 个），`load_skill_tool` 加载 |
| `agent/src/channels/` | IM 适配（Telegram/Slack/Discord/微信/飞书等） |
| `agent/src/shadow_account/` | 交易日志解析、规则抽取、回测、HTML/PDF 报告 |
| `agent/src/hypotheses/` | 研究假设注册与生命周期追踪 |
| `agent/src/core/` | 子进程执行器 `Runner` 与运行状态存储 |
| `agent/src/config/` | 配置加载与 Pydantic schema |

---

## 3. 关键入口

| 入口 | 位置 |
|------|------|
| `vibe-trading` | `agent/cli/main.py` → `main()` |
| `vibe-trading serve` | `agent/api_server.py` → FastAPI (8899) |
| `vibe-trading-mcp` | `agent/mcp_server.py` → `main()` |
| 回测直接运行 | `agent/backtest/runner.py` → `main(run_dir)` |
| ReAct loop | `agent/src/agent/loop.py` → `AgentLoop.run()` |
| Tool 基类 | `agent/src/agent/tools.py` → `BaseTool`, `ToolRegistry` |
| 行情数据 | `agent/src/market_data.py` → `fetch_market_data()` |
| Loader registry | `agent/backtest/loaders/registry.py` |
| 因子注册表 | `agent/src/factors/registry.py` |
| 因子计算 | `agent/src/factors/factor_analysis_core.py` |
| 回测引擎基类 | `agent/backtest/engines/base.py` → `BaseEngine.run_backtest()` |

---

## 4. 典型分析数据流

### 自然语言回测流程

1. 用户通过 CLI/REST/MCP 发送 prompt。
2. `AgentLoop.run()` 创建运行目录，调用 `ContextBuilder`。
3. LLM 接收 system prompt + tools（`agent/src/providers/chat.py`）。
4. LLM 发出 tool call：
   - `get_market_data` → `market_data_tool.py` → `fetch_market_data_json()` → loader registry。
   - `write_file` 写入 `config.json` 与 `code/signal_engine.py`。
   - `backtest` → `backtest_tool.py` → `run_backtest()`。
5. `run_backtest()` 用 `BacktestConfigSchema` 校验配置，调用 `src.core.runner.Runner.execute()` 启动子进程 `python -m backtest.runner <run_dir>`。
6. `backtest.runner.main()` 通过 `FALLBACK_CHAINS` 加载数据，实例化 `BaseEngine` 子类，调用 `BaseEngine.run_backtest()`。
7. 引擎内部：
   - `loader.fetch()` → `_maybe_enrich_fundamentals()` / `_maybe_enrich_events()` → `_sanitize_data_map()`。
   - `signal_engine.generate(data_map)` → `_align()`（信号后移 1 bar，防止未来函数）。
   - `_execute_bars()` 通过 `can_execute`、`round_size`、`calc_commission`、`apply_slippage` 执行市场规则。
   - `calc_metrics()` + 可选 `run_validation()` + `write_run_card()`。
8. 结果 JSON 返回 Agent，最终答案渲染到 CLI/Web。

### 因子分析流程

1. 调用 `alpha_bench` 或 `factor_analysis` 工具。
2. Alpha Zoo：`Registry.get(alpha_id)` 懒加载 `src/factors/zoo/<zoo>/<id>.py`。
3. Alpha 模块接收宽面板（`dict[str, pd.DataFrame]`），返回因子 DataFrame。
4. `compute_ic_series()` 计算日度 Spearman IC；`compute_group_equity()` 构建分位数 NAV。
5. HTML 报告写入 `~/.vibe-trading/reports/`。

---

## 5. 值得借鉴的设计模式

### Tool 模式
- `BaseTool` 定义 `name`、`description`、`parameters`、`repeatable`、`is_readonly`、`execute()`。
- `ToolRegistry` 将 tools 转为 OpenAI function schema 并按名执行。

### Loader registry + fallback chains
- `@register` 装饰器填充 `LOADER_REGISTRY`。
- `FALLBACK_CHAINS` 按市场按被封风险排序数据源：
  - A 股：`tencent → mootdx → eastmoney → baostock → akshare → tushare → local`
  - 美股：`yahoo → stooq → sina → eastmoney → yfinance → tiingo → fmp → finnhub → alphavantage → akshare → local`
- `resolve_loader(market)` 遍历链并返回第一个 `is_available()` 的 loader。
- `source="local"` 永不回退到网络。

### 回测引擎模板方法
- `BaseEngine` 定义市场规则钩子：`can_execute()`、`round_size()`、`calc_commission()`、`apply_slippage()`、`on_bar()`。
- 具体引擎：`ChinaAEngine`、`GlobalEquityEngine`、`CryptoEngine`、`ChinaFuturesEngine`、`GlobalFuturesEngine`、`ForexEngine`、`CompositeEngine`。
- `_align()` 将信号后移一根 bar，并将权重缩放到 `sum(abs(weights)) <= 1.0`。

### Agent loop 上下文压缩
- 五层压缩：`_microcompact()`、`_context_collapse()`、`_auto_compact()`、显式 compact tool、迭代 summary。
- 只读工具批量并发执行。
- 心跳事件每 3 秒一次。

### Swarm 多 Agent 团队
- 预设 YAML 在 `agent/src/swarm/presets/`，如 `investment_committee.yaml` 定义 bull/bear/risk/pm 角色。
- `run_swarm` 工具在 `agent/src/tools/swarm_tool.py`。

### Skills 库
- `agent/src/skills/<skill>/SKILL.md`，YAML frontmatter。
- `load_skill_tool.py` 将 skill 文本作为上下文返回给 Agent。

### 安全/沙箱
- 生成代码在子进程运行：`Runner.execute()` 仅复制 allowlist 环境变量（`agent/src/core/runner.py`）。
- `signal_engine.py` AST 预检（`agent/backtest/runner.py`）。
- `safe_run_dir()` 限制运行目录到允许根路径。
- 实盘 broker MCP 工具受 mandate 与 kill switch 控制。

---

## 6. 依赖与外部 API

### 核心 Python 栈
- Web：`fastapi`、`uvicorn[standard]`、`sse-starlette`、`websockets`、`pydantic>=2`
- LLM/编排：`langchain>=1.3.9,<2`、`langgraph>=1.2.5,<1.3`、`langchain-openai`、`httpx`
- 计算：`pandas>=2.0,<3.0`、`numpy`、`scipy`、`bottleneck`、`duckdb`、`scikit-learn`
- 文档/报告：`openpyxl`、`python-docx`、`python-pptx`、`pypdfium2`、`jinja2`、`matplotlib`、`weasyprint`
- 搜索：`ddgs`
- MCP：`fastmcp>=2.14.0`
- CLI/UI：`rich`、`prompt_toolkit`、`pyyaml`

### 数据源
- A 股：腾讯、mootdx（通达信 TCP）、东方财富、BaoStock、AKShare、Tushare
- 美股：Yahoo、Stooq、Sina、Eastmoney、yfinance、Finnhub、Alpha Vantage、Tiingo、FMP
- 港股：Eastmoney、Yahoo、Futu、yfinance、AKShare
- 数字货币：OKX、CCXT
- 期货/外汇/宏观：Tushare、AKShare
- 本地：CSV / Parquet / DuckDB（`local:` 前缀）

### LLM 供应商
OpenRouter、OpenAI、DeepSeek、Gemini、Groq、DashScope/Qwen、Zhipu、Moonshot/Kimi、MiniMax、Xiaomi MIMO、Z.ai、Ollama、OpenAI Codex。

---

## 7. 优点与风险

### 优点
- 多市场数据源广，fallback 链明确，A 股/美股/币圈可零 API key 起步。
- Agent loop、tool registry、loader registry、回测引擎职责清晰。
- Alpha Zoo 因子库完整，含算子级未来函数禁令、IC/IR 评估、HTML 报告。
- 生成回测代码在子进程沙箱运行，带 AST 预检。
- 多 Agent swarm、skill library 数据驱动（YAML/Markdown）。
- 回归测试规模大（4700+ 测试），CI、CORS/鉴权/路径遍历等安全加固。

### 风险
- **数据溯源粒度不足**：只记录运行卡中的有效 source，缺少 ai-stock-hunter 要求的逐数据点 `SourceCitation`、`confidence`、`[UNSOURCED]` 标记， verified 与 inferred 数据易混。
- **生成代码执行仍有风险**：AST 只拦截明显危险模式，Agent 仍可在子进程写入并导入任意 Python。
- **fallback 链可能掩盖数据质量**：从 Tushare 自动降级到 Eastmoney/AKShare 时不会显式警告用户。
- **单体膨胀**：channels、connectors、shadow account、Alpha Zoo、hypothesis registry 都在一个仓库，依赖面大。
- **Tool 结果截断**：大输出被 `cap_rows`、2000 字符 stdout/stderr 切片截断，可能丢弃严谨分析所需上下文。

---

## 8. 可直接借鉴到 ai-stock-hunter 的组件

| 组件 | 可借鉴内容 | 位置 |
|------|-----------|------|
| **Loader registry + fallback chains** | 按市场解析数据源，A 股/美股/港股/币圈 fallback，支持 `source="auto"` 与 `local:` 前缀 | `agent/backtest/loaders/registry.py` |
| **行情数据获取** | 归一化 `fetch_market_data()`，返回 JSON-safe records，带行数上限 | `agent/src/market_data.py` |
| **Alpha Zoo 算子** | 截面/时序因子算子（`rank`、`scale`、`ts_rank`、`ts_corr` 等），NaN 与未来函数处理 | `agent/src/factors/base.py` |
| **因子注册表** | `__alpha_meta__` AST 提取、懒加载、IC/IR bench、HTML 报告 | `agent/src/factors/registry.py`、`factor_analysis_core.py` |
| **回测引擎模板** | `BaseEngine` 市场规则钩子、`_align()` 下一 bar 开盘语义、optimizer 集成 | `agent/backtest/engines/base.py` |
| **信号校验** | `_validate_signal_engine_source()` AST 检查、`BacktestConfigSchema` Pydantic 校验 | `agent/backtest/runner.py` |
| **ReAct loop + 上下文压缩** | 如需增加 LLM 研究层，可参考 `AgentLoop` 五层压缩与只读工具并发 | `agent/src/agent/loop.py` |
| **Skill 库格式** | Markdown + YAML frontmatter skill 可替代/补充 ai-stock-hunter skill 清单 | `agent/src/skills/<skill>/SKILL.md` |
| **Shadow account 流水诊断** | 券商流水解析 → 行为诊断 → 规则抽取 → 回测 → HTML/PDF 报告 | `agent/src/shadow_account/`、`shadow_account_tool.py` |
| **假设注册表** | 研究想法、证据、关联回测追踪 | `agent/src/hypotheses/registry.py` |
| **IM 通道运行** | 通过 Telegram/Slack/飞书/微信推送研究报告/信号 | `agent/src/channels/` |

### 对 ai-stock-hunter 最优先的三项

1. **A 股 loader fallback 链**  
   与现有 `data/aggregator.py` 数据源优先级（已核实缓存 > 国信 > mootdx > AKShare > 腾讯）对齐，显式处理降级与置信度。

2. **Alpha Zoo 因子算子/注册表**  
   直接接入 `data/factor_pipeline.py`，补充截面 alpha 构建与 IC 评估。

3. **`BaseEngine` 市场规则抽象**  
   用于 L3 回测与 L4 风控官在持仓层面的规则检查（涨跌停、T+1、手续费、滑点）。

> **注意**：任何借鉴代码都需要先包装 ai-stock-hunter 的 `SourceCitation`/`confidence`/`[UNSOURCED]` 护栏，再投入生产使用。
