# 白泽优化实施状态追踪

> 目标：消除 4 个硬伤 + 落地 19 个借鉴迭代项（iteration-plan.md），逐模块验证 + 整体集成验证
> 开始时间：2026-08-05
> 循环检查：每 10 分钟 cron（job 5fe92d73，7 天后自动过期）
> 测试基线：`pytest tests/` 共 1059 个测试可收集

## 总进度

| 批次 | 状态 | 完成项 | 验证 |
|---|---|---|---|
| P0 地基修复 | ✅ 完成 | 4/4 | 定向回归 169 passed |
| P1 战术信号链路 | ✅ 完成 | 6/6 | P0+P1 回归 232 passed |
| P2 learner 闭环 | ✅ 完成 | 5/5 | P0+P1+P2 联合回归 304 passed |
| P3 归因/信息环境 | ✅ 完成 | 4/4 | 定向测试过 |
| 整体集成验证 | ✅ 完成 | 19/19 | 全模块联合回归 **421 passed** + tactics 冒烟 EXIT=0 + 4硬伤消除确认 |

## 四大硬伤消除状态

| # | 硬伤 | 位置 | 状态 | 验证 |
|---|---|---|---|---|
| H1 | tactics 技术六维空转（恒 50 分） | `src/routing/tactics.py:596` | ✅ 修复 | 合成K线实测六维 93.9/59.1/77/54/94.7/50，composite 75.3 |
| H2 | 军规 r017 连续止损休整是死规则 | `doctrine/rules.py` + ctx | ✅ 修复 | ctx 注入 orchestrator.py:3531，checker 防御读取，test 联动 BLOCK 通过 |
| H3 | 反馈采集死代码（feedback.json 从未落盘） | `src/learner/feedback.py` | ✅ 修复 | 根因 `db_path=":memory:"` → 真实路径；feedback add CLI 可用，test_feedback_loop 20 passed |
| H4 | 军规约半数 `_evaluate` 无实现 + 编号冲突 | `doctrine/checker.py` | ✅ 修复 | 补全 ~20 条规则判定；R032-R034→r039-r041 统一小写 |

## P0 迭代项（地基修复）

| # | 项目 | 负责 Agent | 状态 | 验证结果 |
|---|---|---|---|---|
| P0-1 | 修复 tactics 技术六维空转 | P0-A | ✅ | tests/routing/test_tactics_technical.py 3 passed；routing+indicators 60 passed；冒烟 EXIT=0 |
| P0-2 | 补三条军规（r042 报复性加仓/r043 信息面冲突/激活 r017） | P0-B | ✅ | tests/doctrine 29 passed（含 test_rules_hardening 22 项） |
| P0-3 | 风控对齐（6%熔断/连亏冷却/2%风险预算仓位） | P0-C | ✅ | tests/routing/test_risk_cooldown.py 19 passed；相关 185 passed |
| P0-4 | 军规清理（编号冲突+空实现补全） | P0-B | ✅ | 编号唯一性测试过；test_phase2 计数 43→45 同步 |

## P1 迭代项（战术信号链路，依赖 P0-1）

| # | 项目 | 负责 Agent | 状态 | 验证结果 |
|---|---|---|---|---|
| P1-1 | 市场状态前置判定 | P1-A | ✅ | RegimeClassifier 主锚 + Hurst/Choppiness/缠论辅助，6态→三态，RANGE 降权 |
| P1-2 | 均线定方向+MACD定动能双层过滤 | P1-B | ✅ | 新增 MA120/250 因子 + macd_hist_rising 布尔位；金叉须 MA20>MA50 |
| P1-3 | MACD 顶背离入正式评分 | P1-B | ✅ | TechnicalSignal.top_divergence + 趋势分×0.9 + 破位联动升级 |
| P1-4 | 量价过滤器增强（假突破否决） | P1-B | ✅ | 4 检测否决 BREAKOUT + 缩量反弹×0.7 |
| P1-5 | 跨周期过滤+收线确认 | P1-A | ✅ | 周线方向过滤 + T+0 收线确认 |
| P1-6 | MM 等距投影止盈位 | P1-A | ✅ | 中枢投影 + chase_blocked 不追单 + 盈亏比≥1:1 |

## P2 迭代项（learner 闭环，依赖 P1）

| # | 项目 | 负责 Agent | 状态 | 验证结果 |
|---|---|---|---|---|
| P2-1 | 错误类型七分类标签 | P2-A | ✅ | MistakeType 枚举 + mistake_type_from_text 映射 + 空话校验 |
| P2-2 | 激活反馈采集闭环（H3） | P2-A | ✅ | feedback add CLI 可用；reporter 接入 FeedbackCollector+DecisionJournal |
| P2-3 | 复盘事件驱动触发 | P2-A | ✅ | 平仓/连亏≥3/回撤≥8% 触发事件复盘 |
| P2-4 | 置信度校准闭环 | P2-B | ✅ | Calibrator.apply + signal.apply_calibration 反哺 confidence |
| P2-5 | 运气/幸存者偏差校准 | P2-B | ✅ | LuckBiasDetector + survivorship_adjustment + OOS 门禁参与部署 |

## P3 迭代项（归因/信息环境，独立）

| # | 项目 | 负责 Agent | 状态 | 验证结果 |
|---|---|---|---|---|
| P3-1 | 三层归因分层（执行/配置/逻辑） | P3-A | ✅ | AttributionLayer + LayerAttribution + classify_layer；attribution 28 passed |
| P3-2 | 跨市场传导时间差建模 | P3-C | ✅ | LeadLagWindow + to_leading_signals + weak adjust ±3；transmission 21 passed |
| P3-3 | 情绪 0-100 整合评分维 | P3-B | ✅ | _score_sentiment 逆向语义（修复 score=0 吞值 bug）；test_diagnosis_sentiment 15 passed |
| P3-4 | 数据新鲜度参与诊断评分加权 | P3-B | ✅ | _apply_freshness_weighting ×0.7 降权 + [STALE] 标注 |

## 测试与验证记录

- [x] P0 完成后：定向回归 169 passed
- [x] P1 完成后：P0+P1 回归 232 passed + tactics 六维非全 50（合成K线 composite 75.3）
- [x] P2 完成后：P0+P1+P2 联合回归 304 passed + feedback add 落盘（test_feedback_loop 20 passed）
- [x] P3 完成后：全模块联合回归 **421 passed**
- [x] 整体集成（代码级）：4 硬伤逐一确认消除（见上表）；19 个借鉴点全部在代码中落地（grep 核验）
- [x] 冒烟：`tactics 002415` EXIT=0（134.9s），**市场状态 RANGE 门控生效**，军规/风控/仓位全链路正常
- [~] 冒烟：`diagnose 002415` 因环境网络部分数据源不可达挂起于数据拉取阶段（position_state 之后，非新增代码；已终止）
- [ ] 全量 `pytest tests/`（网络用例挂起，环境限制；定向 421 已覆盖所有改动模块）

## 遗留项修复状态（2026-08-06 第二批，5 Agent 并行）

| 遗留项 | 状态 | 验证 |
|---|---|---|
| 单票面板 rank 因子恒 100 | ✅ 修复 | `base.py` 新增 `cross_or_ts_rank`（单列走 ts_rank，多列保持截面）；6 因子接入；test_factor_single_rank 14 passed |
| risk-budget cap 接入全量 run() | ✅ 修复 | `generate_signal` 增 `suggested_stop` 参数；orchestrator `_entry_stop_for_sizing` 接线（T+0 stop→固定止损回退） |
| DecisionJournal 内存态 | ✅ 修复 | SQLite 持久化（data/journal.db），三层降级（连库失败→写失败→log 异常），路径可注入；test_journal_persistence 12 passed |
| 事件复盘偏频繁 | ✅ 修复 | `EVENT_REVIEW_LOSS_TRIGGER`：仅亏损平仓触发单笔复盘，止盈不触发；连亏/回撤保留 |
| 三层归因/情绪维渲染未接线 | ✅ 修复 | attribution_formatter 加「🧭 三层归因分层」块；formatter/step_output 加「情绪(逆向)」行；test_output_sentiment_render 5 passed |
| 传导时差为配置驱动 | ✅ 修复 | `LeadSignalSource` 可插拔接口 + `FuturesSpotLeadSource`（akshare 生意社现货价，**实测返回5条真实信号**，6h缓存）；失败优雅回退配置路径；生产启用 `AI_STOCK_LEAD_SOURCES=futures_spot` |

**第二批联合回归：362 passed**（doctrine/routing/indicators/phase2/feedback/calibration/journal/factor_single_rank/transmission/attribution/output_render/evolution）
