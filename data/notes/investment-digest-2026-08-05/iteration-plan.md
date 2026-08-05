# 白泽系统借鉴迭代计划 — 基于 synthesis.md（2026-08-05）

> 依据：`synthesis.md`（30 篇投资资讯精读汇总结论）+ 2026-08-05 全模块现状勘察（4 路 Explore）
> 原则：先修地基硬伤（P0）→ 再建战术信号链路（P1）→ 补 learner 闭环（P2）→ 完善归因/信息环境（P3）
> 每个迭代项给出：现状 → 目标 → 改动点（文件:函数）→ 工作量 → 验收标准

---

## 一、总览与依赖

```
P0 地基修复 ──────────► P1 战术信号链路 ──────────► P2 learner 闭环 ──► P3 归因/信息环境
(军规/风控/技术面硬伤)    (市场状态+双层过滤+量价)    (错误分类+反馈闭环)   (三层归因+传导时差)
```

- **依赖关系**：P1 的"均线定方向+MACD定动能+量价过滤"依赖 P0-1 修复技术六维空转；P2 的错误分类依赖 P1 的信号链路成型（有信号才有可归因的复盘）；P3 独立。
- **优先级定义**：P0 = 影响所有下游正确性的硬伤；P1 = 对应 synthesis 核心发现#2 的战术改进；P2 = 对应核心发现#3 的 learner 架构；P3 = 锦上添花。
- **工作量**：S ≤ 0.5 天；M = 1-2 天；L = 3-5 天。

---

## 二、P0 地基修复（最高优先）

### P0-1 修复 tactics 技术六维空转 【严重硬伤】【L】【前置依赖】

- **现状**：`src/routing/tactics.py:596 _dim_technical` 传给 `TechnicalAnalyzer().analyze()` 的 panel 只有原始 OHLCV 帧（619-624 行），未注入 17 个因子计算帧 → `technical.py:206 _compute_factor_scores` 对全部因子返回空 → **技术六维全部恒为 50 分，composite=50**，六维评分在 tactics 路径形同虚设。
- **目标**：tactics 路径下技术六维真实打分。
- **改动点**：在 `tactics.py _dim_technical` 内注入因子帧（复用 diagnose 主管道的 factor_pipeline 输出：macd_histogram/rsi_signal/volume_ratio/ma_* 等 17 帧），或让 `TechnicalAnalyzer` 支持自算（消费 OHLCV 内部调 factor 函数）。
- **验收**：tactics 对同一标的输出非全 50 的六维分，且与 diagnose 路径的六维分趋势一致。
- **来源**：synthesis 核心发现#2（技术信号必须先落地才谈改进）。

### P0-2 军规补齐三条硬规则 【M】【无依赖】

- **现状**：43 条军规中无「报复性加仓禁止」「信息面冲突禁开仓」；「r017 连续止损休整」是死规则（上下文键 `consecutive_stops` 全仓从未注入）。
- **目标**：三条规则生效（对应 synthesis 核心发现#1：风控纪律跨文档一致、可直接固化）。
- **改动点**：
  1. 新增军规「亏损后禁止报复性加仓」——`doctrine/rules.py` 加 Rule（trading 类，BLOCK），`checker.py _evaluate` 加判定（当日已止损后禁止追加仓位，需 ctx 注入当日 stop 记录）。
  2. 新增军规「信息面冲突即禁止开仓」——technical 信号与基本面/政策信号方向冲突时强制 hold/close（对应 doc 13 双信号源"不冲突才开仓"）。
  3. 激活 r017——在 risk_control/positioning 写入 `consecutive_stops` 上下文（交易平仓时累计连亏，达 3 次置位），让 checker 能读到。
- **验收**：`pytest tests/` 新增三规则用例通过；`doctrine.check` 对构造的冲突/报复场景正确 BLOCK。
- **来源**：synthesis 核心发现#1、#3；doc 12/13/25（0.7/0.6/0.7）。

### P0-3 风控对齐：6% 单日熔断 + 连亏冷却 + 单笔风险预算仓位 【M】【依赖 P0-2 的连亏上下文】

- **现状**：单日熔断 5%（`risk_control.py:103 BLACK_SWAN_THRESHOLD=-0.05`）非 6%；无实际生效的连续亏损冷却；`positioning.py` 无"风险预算=权益×2%÷(入场价−止损价)"反推仓位。
- **目标**：对齐 synthesis 共识（doc 15/25，0.7）：单日 6% 熔断、连亏冷却、单笔风险 ≤2% 前置到建仓。
- **改动点**：
  1. `risk_config.py`/`risk_control.py`：单日熔断参数 5%→6%（保留 T+1 下无法卖出的联动降级，见 P0-3 验收）。
  2. `risk_control.py` 加连亏计数冷却（达阈值暂停自动信号输出/降信任权重）。
  3. `positioning.py` 加 risk-budget sizing：`max_position = (equity × 2%) / (entry_price − stop_price)`，与现有乘数链（141-173 行）合并取 min。
- **验收**：构造"单日浮亏+已实现 ≥6%"场景被 REJECT；连亏 N 次后信号被冷却；风险预算计算的仓位 ≤ 现乘数链结果。
- **来源**：synthesis 核心发现#1；doc 15/25（0.7）。

### P0-4 军规清理：编号冲突 + 空实现补全 【M】【无依赖】

- **现状**：r03x 与 R03x 大小写编号冲突；43 条中约半数 `_evaluate` 无判定逻辑（默认返回 False，形同虚设）。
- **目标**：军规成为可靠硬约束（这是所有下游的信任基础）。
- **改动点**：统一编号规范（重排冲突项）；为无实现的规则补判定或标注"仅信息类"并接入应有上下文；同步更新 `CLAUDE.md` 军规总数 41→43 的过时说明。
- **验收**：`pytest tests/doctrine*` 通过；每条军规在 checker 中可被触发。
- **来源**：synthesis 风险警示（事实错误/不可采信清单提示了对规则的严谨性要求）。

---

## 三、P1 战术信号链路（对应 synthesis 核心发现#2）

> 前置：P0-1。本组目标是把 tactics 从"空转六维 + 单点信号"升级为"趋势优先 + 多层过滤"的完整链路。

### P1-1 市场状态前置判定 【M】

- **现状**：tactics 无趋势市/震荡市分流；`RegimeClassifier`（`src/macro/market_regime.py`）只在 diagnose 主管道用（orchestrator.py:722）；`HurstExponent`/`ChoppinessIndex` 已存在未接入。
- **目标**：doc 22/28（0.65/0.55）"先分趋势市/震荡市，仅趋势市启用金叉/死叉/均线突破信号，震荡市降权或忽略"。
- **改动点**：`tactics.py` 新增 `_classify_market_state()`，复用 RegimeClassifier + Hurst/Choppiness + 缠论中枢（chanlun 已有 freq="D"，position 字段可用），输出 BULL_TRENDING/BEAR_TRENDING/RANGE 三态，注入 `TacticalSnapshot` 并作为后续信号的门控。
- **验收**：同一标的在趋势市 vs 震荡市给出不同的信号门控结果。
- **来源**：synthesis 技术分析节；doc 22（0.65）。

### P1-2 均线定方向 + MACD 定动能双层过滤 【M】

- **现状**：均线仅 MA5/10/20/60（缺 MA120/250 中长期方向）；`macd_histogram.py` 只出单值 rank，无柱状方向独立维度；`macd_kdj.py` 五法 M1/M4 有 0 轴上下判定。
- **目标**：doc 21（0.65）"MACD 金叉须 MA20/50 多头才计入买入；死叉不直接卖出，须均线走弱联动确认"。
- **改动点**：
  1. `factors/zoo/ashare/technical/` 新增 MA120/MA250 因子（中长期方向），补 `ma_support/ma_alignment` 周期。
  2. `macd_histogram.py` 或 macd_kdj 增加 `macd_hist_rising`（柱状放大/收窄布尔位，doc 13 的结构化快照思想）。
  3. `entry_exit_engine.py _detect_golden_cross`（255）加前置条件：金叉须 MA20>MA50（至少 MA20 向上）；`_detect_ma_breakdown`（412）加"缩量 vs 放量"质量区分。
- **验收**：逆趋势金叉不再触发买入信号；金叉/死叉均含方向过滤。
- **来源**：synthesis 技术分析节；doc 21/28/13。

### P1-3 MACD 顶背离维度纳入正式评分 【S-M】

- **现状**：顶背离仅 `macd_kdj.py:164` 简易版（作五法 M4 门，confidence 封顶 0.5）和缠论 `bihuang.py:8 detect_divergence`（未并入技术 composite）。
- **目标**：doc 28（0.55）"价格创新高 + MACD/DIF 未同步新高 = 顶背离 = 上涨减速预警，降仓/收紧止损；真正卖出以跌破 MA 为准"。
- **改动点**：把顶背离作为 tactics 出场/减仓的降权信号并入 `TechnicalSignal`（不直接触发卖出，与均线破位联动）。
- **验收**：构造价格新高+MACD 未新高的 panel，signal 标记顶背离并降仓。
- **来源**：synthesis 技术分析节；doc 28（0.55）。

### P1-4 量价过滤器增强 【M】

- **现状**：已有量比/换手率/OBV/MFI + `entry_exit_engine.py _detect_volume_stall`（放量滞涨出场，量比阈值 1.3）。缺"假突破 4 检测"与"缩量反弹≠反转"降权。
- **目标**：doc 19（0.65）量价过滤三规则：放量下跌禁抄底、缩量反弹非反转、放量突破+缩量回踩确认真突破。
- **改动点**：`entry_exit_engine.py` 新增假突破否决过滤器（盘中破位收盘跌回/放量不涨留长上影/突破当天放量后续不新高/回踩放量重新跌破）；突破信号叠加"真突破三条件"（收盘站稳/后续续涨/回踩缩量守）二次确认。
- **验收**：突破信号在假突破形态下被否决；新增军规"放量下跌禁盲目抄底"（并入 P0-2 或此处）。
- **来源**：synthesis 技术分析节；doc 19（0.65）。

### P1-5 跨周期过滤 + 收线确认 【S】

- **现状**：tactics 仅日线；chanlun 支持 freq="W" 未用；无"收线确认"规则。
- **目标**：doc 07（0.35）"信号级与过滤级分层 + 等 K 线收线后再决策"。
- **改动点**：`tactics.py` 加日线信号 + 周线/60min 过滤的双层确认；T+0 分时判断加"待分时 K 线收线"规则。
- **验收**：日线信号在周线方向相反时被过滤。
- **来源**：synthesis 技术分析节；doc 07（0.35）。

### P1-6 MM 等距投影止盈位 【S】

- **现状**：无目标位设定工具（仅 ATR/时间/移动止损）。
- **目标**：doc 06（0.4）"震荡区间/推动段高度向下一方向翻一倍作止盈参考区，目标位附近分批止盈 + 不追单，盈亏比 ≥1:1"。
- **改动点**：`tactics.py` 或 `entry_exit_engine.py` 加 MM 投影目标位计算，并入止盈设定与 `suggested_stop` 逻辑。
- **验收**：对含明确区间的行情输出投影目标位，且触发"目标位附近不追单"。
- **来源**：synthesis 技术分析节；doc 06（0.4）。

---

## 四、P2 learner 闭环（对应 synthesis 核心发现#3）

> 前置：P1 信号链路成型。本组目标是把 learner 从"死代码 + 关键词启发式"升级为 doc 13 的五阶段闭环。

### P2-1 错误类型分类标签体系 【M】

- **现状**：无结构化错误标签；`backtest/review.py` deviation_reason 是自由文本。
- **目标**：doc 13（0.6）七类错误标签 `chased_move / ignored_news_conflict / stop_too_tight / stop_too_wide / overleveraged / held_too_long / none`。
- **改动点**：`src/learner/feedback.py` 加 `MistakeType` 枚举；`backtest/review.py` 的 deviation_reason 改为枚举；`alpha/attribution.py` 的 mistakes 洞察映射到标签。
- **验收**：复盘输出可按错误标签聚合统计。
- **来源**：synthesis 核心发现#3；doc 13（0.6）。

### P2-2 激活反馈采集闭环 【M】【依赖 P2-1】

- **现状**：`data/feedback.json` 从未写入；CLI `feedback add` 是 stub（「交互式反馈录入开发中」）；FeedbackCollector 有代码未接线。
- **目标**：打通"交易 → 反馈 → 复盘 → 进化"数据流。
- **改动点**：实现 CLI `feedback add` 交互；把 `paper_trading/reporter.py` 周/月复盘接入 FeedbackCollector + DecisionJournal；接 cron 调度。
- **验收**：`feedback add` 后 feedback.json 有数据；周报包含错误标签聚合。
- **来源**：synthesis 核心发现#3；doc 13（0.6）。

### P2-3 复盘事件驱动触发 【S-M】【依赖 P2-2】

- **现状**：复盘仅日历触发（周五/月末）。
- **目标**：doc 13"仅当一笔完整交易结束才生成教训" + doc 15/25"连续亏损/回撤超标触发"。
- **改动点**：`paper_trading/engine.py` 在平仓事件/连亏/回撤超标时触发即时复盘（复用 `_maybe_trigger_review` 模式，加事件分支）。
- **验收**：平仓即生成单笔复盘，教训必须具体（禁止"操作失误/行情不好"空话）。
- **来源**：synthesis 核心发现#3；doc 13/15。

### P2-4 置信度校准闭环 【S-M】【依赖 P2-2】

- **现状**：`calibrator.py:403 Calibrator` 分桶校准存在但未反哺信号 confidence。
- **目标**：校准结果反哺 `Signal.confidence`（synthesis 数据护栏节）。
- **改动点**：把 Calibrator 输出接到 `signal.py target_from_signal` / `positioning.py` 的 confidence 使用处。
- **验收**：历史校准后，低置信度信号仓位/权重下降。
- **来源**：synthesis 核心发现#3、数据护栏节；doc 13（0.6）。

### P2-5 运气/幸存者偏差校准 【S】

- **现状**：仅 `alpha/attribution.py:399` 单笔级"正收益 Alpha 负=运气"识别。
- **目标**：doc 24（0.75）"对高收益样本的运气成分识别 + 可证伪条件约束"。
- **改动点**：`calibrator.py` 加聚合运气调整（按策略聚合高收益样本，标记幸存者偏差风险）；进化部署门禁加可证伪条件。
- **验收**：进化合入前显示运气/样本偏差提示。
- **来源**：synthesis 量化节；doc 24（0.75）。

---

## 五、P3 归因与信息环境（锦上添花）

### P3-1 三层归因分层（执行/配置/逻辑） 【M】

- **现状**：`attribution.py` 按 Phase1/2/3 组织，无三层归因分层。
- **目标**：doc 29（0.55）"下跌先分执行层（买法）/配置层（仓位排队）/逻辑层（核心假设），越往上推翻所需证据越多"。
- **改动点**：`attribution_types.py AttributionResult` 加三层归因字段，`attribution.py` 归因结论时分层输出。
- **验收**：归因报告对每类下跌给出分层判断。
- **来源**：synthesis 理念节；doc 29（0.55）。

### P3-2 跨市场传导时间差建模 【M】

- **现状**：`us_sector_transmission.py` 仅当日传导，无 lag/lead。
- **目标**：doc 04（0.3，理念可借鉴）"上游现货异动 → 海外龙头 → A 股对标，滞后 2-4 周"。
- **改动点**：`us_sector_transmission.py` 加滞后窗口建模，`sector-research/supply_chain` 消费（标 [SPECULATION]）。
- **验收**：对已知传导事件输出领先信号时间窗。
- **来源**：synthesis 基本面/宏观节；doc 04（0.3）。

### P3-3 情绪 0-100 整合评分维 【S】

- **现状**：sentiment 只有 level + 股吧热度，无整合 0-100 情绪维（诊断六维中情绪缺失）。
- **目标**：把 `sentiment/signals.py` 的 0-100 情绪分整合进 `diagnosis.py` 六维，参与复合评分。
- **改动点**：`diagnosis.py` 加 `_score_sentiment`，复用 signals.py 评分。
- **验收**：诊断输出含情绪维 0-100。
- **来源**：synthesis 综述（六维缺情绪维）。

### P3-4 数据新鲜度参与诊断评分加权 【S】

- **现状**：新鲜度只记录时间戳（diagnosis.py:504），不参与评分加权（强制在 guardrails/quality）。
- **目标**：新鲜度过期维度降权（synthesis 数据护栏 + guardrails 原则）。
- **改动点**：`diagnosis.py` 各维度评分按 freshness 乘 0.7 降权。
- **验收**：过期数据的维度分下降。
- **来源**：synthesis 数据护栏节。

---

## 六、建议执行顺序

| 批次 | 内容 | 预计耗时 | 交付物 |
|---|---|---|---|
| **批次 1**（P0） | P0-1 技术六维修复 → P0-2 三条军规 → P0-3 风控对齐 → P0-4 军规清理 | 5-7 天 | 军规/风控/技术面正确性修复，全测试过 |
| **批次 2**（P1） | P1-1→P1-6 战术信号链路 | 5-8 天 | tactics 多层过滤完整链路 |
| **批次 3**（P2） | P2-1→P2-5 learner 闭环 | 4-7 天 | 反馈/复盘/校准闭环 |
| **批次 4**（P3） | P3-1→P3-4 归因与信息环境 | 3-5 天 | 归因分层 + 传导时差 |

> 每批次结束跑 `pytest tests/` + 一次 `diagnose <code>` 冒烟验证；P1 批次需在批次 1 后先确认六维真实打分。

## 七、验证方式

- **单元测试**：每条新军规/新过滤器/新校准逻辑有 `pytest` 用例（类级 Test* + 方法级 test_*）。
- **冒烟验证**：每批次跑 `python -m src diagnose <code>` 与 `python -m src tactics <code>`，比对六维分/信号与修复前差异。
- **回归**：`pytest tests/` 全量通过；军规总数、裁决输出格式不破坏下游。

---

*本计划所有改动点均基于 2026-08-05 代码现状勘察；实施前对每个具体文件仍需按 CLAUDE.md 规矩 Read 源码确认签名，不凭记忆改代码。*
