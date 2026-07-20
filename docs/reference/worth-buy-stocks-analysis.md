# worth-buy-stocks — 美股趋势跟踪纪律评分系统

> 源码：https://github.com/starriv/worth-buy-stocks（MIT）
> 定位：把趋势交易纪律落成可复现的美股评分流程——Codex Skill 形态的 Python 量化管道，回答"按当前价量结构、市场环境和风险约束，现在是否适合参与"

## 一、核心评分管道

```
数据采集（SQLite 缓存 + Alpaca 行情 + 新闻/Finnhub + 账户持仓 + AI 第二意见）
       ↓
确定性评分（四层单向流，绝不回溯）
  ① ALPHA 加权（动量 55 + 相对强度 35 + 趋势效率 10）→ 形成排名分
  ② 风险否决（MA60/MA200/周线结构/大盘 risk-off）→ 封顶或否决
  ③ 技术确认（MACD/RSI/KDJ/量价/趋势质量 ADX）→ 只拦截买入，不给排名加分
  ④ 入场时机（过热降级/回调拐点/超跌反转）→ 调整入场结论，不改排名分
       ↓
独立约束层（事件风险只降级 + 账户敞口调整建议 + AI 意见仅对照）
       ↓
最终结论（是/观察/否/持仓需减风险/无法评分）+ 交易计划（入场/止损/2R-3R 止盈/追价上限）
```

**评分合约核心字段**（`scoring/engine.py:score()`）：

| 字段 | 含义 | 规则 |
|------|------|------|
| `composite` | 最终纪律评分 0-100 | `min(raw, price_gate_cap, llm_news_cap)` |
| `verdict` | 是/观察/否/持仓需减风险/无法评分 | ALPHA 分 + 风险否决 + 技术确认 + 入场时机四层逐级调整 |
| `factor_breakdown` | 动量/相对强度/效率 逐因子得分+权重 | 按可用权重归一到 0-100 |
| `risk_gates` | 价格/趋势闸门否决原因 | MA60/MA200/周线/大盘 |
| `entry_timing.classification` | pullback_reversal / recovery_reversal / trend_continuation / pullback_no_trigger / overextended / trend_broken | 过热降级、拐点替代趋势热度确认 |
| `trade_plan` | 入场/回踩入场/止损/2R 止盈/3R 止盈/追价上限/移动止损 | 来自 ATR/均线/近30日结构 |
| `llm_overlay` | 新闻面封顶（cap+downgrade_reasons+red_flags） | 只降级不加分 |

**关键业务逻辑**：

- **入场时机层不参与 composite**（保持 IC 校准的排名分）：过热只降 verdict→观察并给出回踩计划价，不是降分。拐点替代 technical/trend_quality 确认（回调处定义性偏低），但 volume 必须明确可算且达标。
- **超跌反转恢复路径**（`recovery_reversal`）：长期趋势资格通过 + 周线未空头排列 + 无核心数据缺失 + 无新闻红旗 → 允许 15% 受限试仓（`RECOVERY_POSITION_CAP_PCT`）。排名分保持原值。
- **持仓保护退出**：`overextended_reversal`（过热后放量弱收盘）或 `trend_break`（跌破下行 MA60）→ `exit_next_open`。
- **新闻面非对称**：`severity=high`（会计造假/停牌/退市）封顶 50 → 结论最多 `否`；`severity=medium`（增发/诉讼/监管/财报临近≤7天）封顶 74 → `是` 降 `观察`；利好、目标价、估值叙事不改评分。
- **账户敞口只读 overlay**：不参与 composite 计算，只调整操作建议（已持仓超目标→`reduce_risk`，禁止新增仓位）。

## 二、因子计算引擎

**ALPHA 因子（进排名分）** — `scoring/factors.py`：

| 因子 | 权重 | 核心指标 | 变换 |
|------|:--:|------|------|
| `momentum` | 55 | risk_adj_6m（Sharpe-like）、m12_1_pct | logistic squashing（x0=0.5, k=3.0 / x0=5.0, k=0.08） |
| `rel_strength` | 35 | 相对 SPY/QQQ 的 3m/6m 超额 + consistency ratio | logistic + weighted |
| `efficiency` | 10 | Kaufman Efficiency Ratio (ER = \|ΔP\| / Σ\|ΔPi\|) | 直接 0-1 |

**确认因子（不进排名分，IC≈0，只拦截买入）**：

| 因子 | 作用 | 最低阈值 |
|------|------|:--:|
| `technical` | MACD/RSI/KDJ 综合 | 0.55 |
| `volume` | 量价配合 | 0.50 |
| `trend_quality` | ADX 趋势强度 | 0.40 |

## 三、行情缓存架构

```
SQLite (data/market-data.sqlite3)
  ├── final 日线（已完成 session，split-adjusted）
  ├── latest snapshot（盘中/盘前/周末优先，缺失由最近 final bar 合成）
  ├── 交易日历（NYSE/NASDAQ，__MARKET_CALENDAR_XNYS__ 伪 symbol）
  ├── 资产目录（Alpaca active US equity，按 UTC 日期缓存，保留消失历史）
  └── sync_ranges 断点续传（按 symbol + feed + adjustment 粒度）
```

三种缓存模式：

| 模式 | 行为 | 适用场景 |
|------|------|---------|
| `auto`（默认） | 完整覆盖不联网；冷启动/缺口补缺失范围 | 日常评分与扫描 |
| `refresh` | 强制刷新请求范围 | 复权修订或手工修复 |
| `off` | 仅 Alpaca，不读写 SQLite | 故障排查 |

预热与对账工具链：

| 命令 | 用途 | 关键约束 |
|------|------|---------|
| `cache_admin.py warm-market` | 全市场三年日线预热 | 120 RPM 限速（Alpaca Basic=200），同 DB 单实例，可中断并复跑 |
| `cache_admin.py sync-assets` | 同步 Alpaca 当前活跃美股目录 | 每 UTC 日期最多远端刷新一次 |
| `cache_admin.py reconcile-market` | 以资产目录为基准查漏补缺 | 只处理 tradable 且 Basic IEX 可覆盖的主流交易所标的 |
| `cache_admin.py status` | 查看覆盖率和资产目录时间 | 只读 |
| `cache_admin.py integrity-check` | SQLite 数据库完整性校验 | 只读 |

## 四、回测与验证体系

**单标的历史回测**（`backtest.py single`）：
- `cache-only` 严格只读边界：只消费 SQLite 中 TICKER/SPY/QQQ 的 final 日线，不补网、不迁移。
- 输出 canonical JSON + 自包含 HTML：21/63 日事件研究、非重叠推断样本、rank-only vs disciplined-verdict 固定研究窗口、managed 持仓管理仿真（含单边成本/最大回撤/SPY buy-and-hold 对比）。
- 验证结论三级：`supports`（支持冻结条件）/ `inconclusive`（证据不足）/ `contradicts`（方向相反）。**禁止外推为宽市场 alpha**。

**回测模块化架构**（`scripts/backtesting/`）：

| 模块 | 职责 |
|------|------|
| `replay.py` | 逐交易日评分回放引擎 |
| `event_study.py` | 21/63 日固定窗口事件研究 |
| `simulation.py` | managed 持仓管理仿真（建议仓位/初始止损/1R 保本/移动止损/下一开盘退出） |
| `statistics.py` | 推断统计与置信区间 |
| `cross_sectional.py` | 截面因子 IC 分析 |
| `panel.py` | 面板统计 |
| `rotation.py` | 轮动组合研究 |
| `visualization.py` | 自包含 HTML 报告渲染 |

**轮动组合名单**（`rotation_list.py`）：
- 148 只冻结研究 universe，63 交易日调仓、Top-20 等权、SPY 破 200 日线全现金。
- 经**预注册 dev/holdout 双门槛验证**（holdout 净收益与回撤均优于 QQQ），但 acknowledge 幸存者偏差和 holdout 期较短。
- `--record` 固化为前瞻记录；`--evaluate` 结算满 63 日的记录，报告等权毛收益与相对 QQQ/SPY 超额。

## 五、多 Agent 编排契约

主 agent 保留：意图解析、安全边界、最终评分运行、artifact 校验与合并、最终回复组织。

可委派角色（`references/agent-contracts.md`）：

| 角色 | 产出 artifact | 约束 |
|------|-------------|------|
| Market data agent | `bars` | snapshot 已由脚本自动拉取，无需单独采集 |
| News/event-risk agent | `news_context` | 只识别风险，不写买入结论 |
| Account overlay agent | `account_context` | 只读，失败返回 unavailable |
| Finnhub context agent | `finnhub_context` | 无 key/限流返回结构化状态 |
| Chart agent | K 线图 | 评分产出 result.json 后才能画价位线 |
| QA agent | 合规检查 | 只检查最终回复是否遵守 skill，不改评分 |

每个 artifact 喂入前用 `validate_agent_contract.py --kind <kind> <file>` 预检；`indicators.py` 加载时自动复检。可选 overlay 校验失败则丢弃并在 stderr 警告；核心 `bars` 校验失败则输出 `无法评分` 退出。

## 六、输出格式工程纪律

7 段强制格式（图→结论→关键证据→风控过滤条件→评分拆解→账户敞口与交易计划→新闻面风控→建议），风控过滤条件表固定 8 行（大盘 regime / 个股趋势闸门 / 相对强度 / 30日结构与追价 / 技术与量价确认 / 流动性数据质量 / 新闻事件红旗 / 账户敞口），**没有触发风险的行也要填写"通过"或"未发现"**。全文禁止机制性否定句（"未影响评分""不构成降级"等）和免责声明。结论为 `否` 或 `观察` 时必须附正式条件句的重评触发条件。

## 七、可直接借鉴到本项目的业务机制

| # | 机制 | 来源 | 应用到本项目 |
|---|------|------|------------|
| 1 | **四层评分单向流**（ALPHA→风险否决→技术确认→入场时机，不改排名分） | `scoring/engine.py` | L1 多维诊断→L2 裁决的分层不可逆设计 |
| 2 | **新闻面非对称 overlay**（只降级不加分，利好/目标价/估值叙事不改评分） | `scoring/gates.py:_llm_overlay()` | guardrails 新闻时效性规则的形式化执行 |
| 3 | **入场时机独立层**（过热降 verdict 不改 composite，拐点替代技术确认但 volume 必须达标） | `scoring/engine.py:score()` | L3 仓位调度的入场时机判断 |
| 4 | **超跌反转受限试仓**（深度回撤+放量强反转+长期趋势通过→15% 上限） | `scoring/engine.py:recovery_entry_ok` | L3/L4 特殊场景仓位管理 |
| 5 | **SQLite 读穿缓存 + 断点续传**（auto/refresh/off 三模式 + sync_ranges 粒度续传） | `market_data_cache.py` + `cache_admin.py` | `data/aggregator.py` 行情缓存层 |
| 6 | **资产目录 + 对账**（每日同步 Alpaca 活跃标的 + 以目录为基准查漏补缺） | `asset_catalog.py` + `market_reconcile.py` | 全市场扫描的 universe 管理 |
| 7 | **cache-only 回测边界**（严格只读 SQLite final 日线，不补网不迁移） | `backtest.py single --data-source cache-only` | `backtest/` 回测数据隔离 |
| 8 | **canonical JSON + 自包含 HTML 回测报告**（semantic hash 复现、21/63 日事件研究、managed 仿真） | `backtesting/` | `backtest/` 输出标准化 |
| 9 | **轮动组合预注册验证**（冻结 universe + dev/holdout 双门槛 + 限制说明） | `backtesting/rotation.py` | 策略进化 `learner/` 的验证框架 |
| 10 | **Agent 契约 + 预检**（artifact JSON schema + validate_agent_contract.py 门禁） | `references/agent-contracts.md` | 多 Agent 子任务输出的 schema 校验 |
| 11 | **硬性纪律写入 Skill**（8 条不可违反规则内置 SKILL.md，QA agent 只检查不评分） | `SKILL.md` 硬性纪律 §1-8 | 军规/guardrails 的 .skill 文件化 |
| 12 | **持仓保护退出信号**（过热反转/趋势破位→exit_next_open，普通持有→hold） | `scoring/engine.py:position_exit` | L4 风控的持仓退出信号 |
| 13 | **7 段强制输出格式**（结论/关键证据/风控过滤条件/评分拆解/账户敞口/新闻面/建议） | `SKILL.md` 输出格式 | L2 综合裁决输出模板 |
| 14 | **strict 日志通道分离**（stdout=业务JSON，stderr=structlog JSONL/console） | `scripts/skill_logging.py` | 分析管道日志与结果解耦 |

> ⚠️ **注意**：worth-buy-stocks 仅支持 Alpaca 覆盖的美股，核心价量数据不足时返回 `无法评分`。其评分权重来自样本内回测和逐因子 IC 分析，扩展到规则化宽票池后排名优势未达统计显著——分数用于统一执行纪律，不理解为已验证的选股 alpha。其核心价值在于 **(1) 四层评分单向流 + 非对称 overlay 的分层设计**、(2) **SQLite 缓存架构 + 资产目录 + 对账的本地数据工程**、(3) **cache-only 回测 + canonical artifact 的严格验证体系**、(4) **新闻面风控的规则化执行模式**、(5) **Agent 契约 + 预检门禁的多 Agent 编排质量保障**。
