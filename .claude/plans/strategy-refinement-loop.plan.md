# Plan: 操盘手法持续完善系统（Strategy Refinement Loop）

**Source**: 用户需求 — 通过系统回测学习 + 用户反馈，持续完善操盘手法，降低交易风险
**Complexity**: Large（涉及 6 个新模块 + 2 个现有模块改造）

## Summary

构建一个「策略持续进化闭环」：回测结果驱动参数自动优化，用户对每笔信号的反馈（赞同/反对/调整）被结构化记录并反向校准策略权重，最终形成「回测→实盘→反馈→优化→回测」的飞轮，让操盘手法随数据和经验持续精进，交易风险逐步收敛。

## Current State

| 模块 | 已有能力 | 缺失 |
|------|---------|------|
| `src/backtest/` | 单策略回测、因子反转测试 | 参数自动优化、多策略对比、优化历史 |
| `src/learner/` | 用户能力画像 (4维)、决策日志 | 反馈闭环、策略权重校准、学习报告 |
| `src/routing/` | 5层流水线 (L0-L4) | 策略版本管理、信号质量追踪 |
| `src/doctrine/` | 31条静态军规 | 规则权重动态调整 |

## Patterns to Mirror

| Category | Source | Pattern |
|----------|--------|---------|
| Naming | `src/backtest/engine.py:1` | `snake_case` modules, `PascalCase` classes, Chinese docstrings |
| Errors | `src/backtest/engine.py:115` | `raise RuntimeError("中文消息")` with explicit checks |
| Dataclasses | `src/backtest/engine.py:21` | `@dataclass` with `field(default_factory=...)` |
| Tests | `tests/test_phase3_4.py` | pytest classes grouped by module, AAA pattern |
| Type hints | `src/routing/orchestrator.py` | `from __future__ import annotations`, `Optional[Type]` |
| Logging | `src/learner/__init__.py:17` | Method-based logging with `datetime.now().isoformat()` |

## Files to Change

### Phase 1: 回测优化引擎（Backtest Optimizer）

| File | Action | Why |
|------|--------|-----|
| `src/backtest/optimizer.py` | CREATE | 参数网格搜索 + 贝叶斯优化，自动发现最优策略参数 |
| `src/backtest/strategy_registry.py` | CREATE | 策略注册中心，支持多策略版本管理与对比 |
| `src/backtest/comparator.py` | CREATE | 多策略横向对比（Sharpe/回撤/胜率/波动率） |
| `tests/test_optimizer.py` | CREATE | 优化器单元测试 |

### Phase 2: 用户反馈闭环（Feedback Loop）

| File | Action | Why |
|------|--------|------|
| `src/learner/feedback.py` | CREATE | 结构化用户反馈收集（信号评价/调整原因/结果标注） |
| `src/learner/calibrator.py` | CREATE | 基于反馈数据校准策略权重与规则阈值 |
| `src/learner/report.py` | CREATE | 周度/月度学习报告（策略优化历史 + 用户成长曲线） |
| `tests/test_feedback.py` | CREATE | 反馈系统单元测试 |

### Phase 3: 策略进化飞轮（Evolution Pipeline）

| File | Action | Why |
|------|--------|------|
| `src/learner/evolution.py` | CREATE | 进化编排器：回测→分析→校准→验证→部署 |
| `src/learner/signal_tracker.py` | CREATE | 信号质量追踪（信号→成交→结果全链路） |
| `tests/test_evolution.py` | CREATE | 进化管线集成测试 |

### Phase 4: 现有模块改造

| File | Action | Why |
|------|--------|------|
| `src/learner/__init__.py` | UPDATE | 导出新模块，DecisionJournal 增加反馈关联 |
| `src/learner/profile.py` | UPDATE | ProfileTracker 增加策略贡献度维度 |
| `src/routing/orchestrator.py` | UPDATE | 支持策略版本参数注入 |
| `src/cli.py` | UPDATE | 新增 `backtest-optimize`、`feedback`、`evolve` 命令 |

## Tasks

### Task 1: 回测优化引擎
- **Action**: 创建 `src/backtest/optimizer.py`，实现 `GridSearchOptimizer` 和 `BayesianOptimizer`
  - `GridSearchOptimizer`: 参数网格搜索，遍历 pe_percentile/roe_threshold/stop_loss_pct/rebalance_days 组合
  - `BayesianOptimizer`: 基于 `scikit-optimize` 的 BayesSearchCV 模式，25 轮迭代收敛
  - `OptimizationResult`: 记录每次优化的参数组合 + 绩效指标 + 时间戳
- **Mirror**: `src/backtest/engine.py` 的 `BacktestResult` dataclass 模式
- **Validate**: `pytest tests/test_optimizer.py -v`

### Task 2: 策略注册与对比
- **Action**: 创建 `src/backtest/strategy_registry.py` 和 `comparator.py`
  - `StrategyRegistry`: 注册策略版本（name + version + params + created_at）
  - `StrategyComparator`: 同周期多策略横向对比，输出排名表
  - 支持保存/加载优化历史到 `data/strategy_history.json`
- **Mirror**: `src/data/aggregator.py` 的多源聚合模式
- **Validate**: `pytest tests/test_optimizer.py -v -k "registry or comparator"`

### Task 3: 用户反馈系统
- **Action**: 创建 `src/learner/feedback.py`
  - `FeedbackCollector`: 收集用户对每笔信号的反馈
    - `agree(signal_id, reason)` — 赞同系统信号
    - `disagree(signal_id, reason, user_action)` — 反对并记录实际决策
    - `adjust(signal_id, param, old_value, new_value, reason)` — 调整参数
    - `annotate_outcome(signal_id, actual_return, lesson)` — 结果标注
  - `FeedbackSummary`: 按策略/时间段聚合反馈统计
- **Mirror**: `src/learner/profile.py` 的 `ProfileTracker.record_trade()` 模式
- **Validate**: `pytest tests/test_feedback.py -v`

### Task 4: 策略权重校准
- **Action**: 创建 `src/learner/calibrator.py`
  - `RuleCalibrator`: 基于反馈数据调整规则权重
    - 统计每条军规/博弈论规则的误报率（正常交易被拦截）和漏报率（问题交易未被拦截）
    - 动态下调高误报规则权重，上调高漏报规则权重
  - `FactorCalibrator`: 基于回测+反馈调整因子权重
    - PE/ROE/北向资金三因子的权重从固定 (0.4, 0.4, 0.2) 变为贝叶斯后验
- **Mirror**: `src/doctrine/checker.py` 的 `DoctrineChecker.check()` 返回值模式
- **Validate**: `pytest tests/test_feedback.py -v -k "calibrat"`

### Task 5: 进化编排管线
- **Action**: 创建 `src/learner/evolution.py`
  - `EvolutionPipeline`: 编排完整进化流程
    1. `collect_evidence()` — 汇总回测结果 + 用户反馈
    2. `analyze_gaps()` — 识别策略弱点（哪些市场环境表现差）
    3. `propose_changes()` — 生成参数调整建议
    4. `backtest_validate()` — 回测验证新参数
    5. `deploy()` — 更新策略版本
  - `EvolutionRecord`: 记录每次进化的输入/输出/决策
- **Mirror**: `src/routing/orchestrator.py` 的 `Orchestrator.run()` 多步流水线模式
- **Validate**: `pytest tests/test_evolution.py -v`

### Task 6: 信号质量追踪
- **Action**: 创建 `src/learner/signal_tracker.py`
  - `SignalTracker`: 追踪信号全生命周期
    - `signal_emitted(signal)` — 信号生成
    - `signal_executed(signal_id, execution_price)` — 成交
    - `signal_outcome(signal_id, return_pct, holding_days)` — 结果
  - `SignalQualityReport`: 按策略/时段/市场环境统计信号质量
    - 信号准确率、平均收益、最大回撤、持仓天数分布
- **Mirror**: `src/learner/__init__.py` 的 `DecisionJournal.log()` 模式
- **Validate**: `pytest tests/test_evolution.py -v -k "signal"`

### Task 7: CLI 集成
- **Action**: 更新 `src/cli.py`
  - `backtest-optimize` — 运行参数优化
  - `backtest-compare` — 多策略对比
  - `feedback add` — 添加交易反馈
  - `feedback summary` — 查看反馈统计
  - `evolve` — 运行进化管线
  - `learn report` — 生成学习报告
- **Mirror**: 现有 CLI 的 `information` 子命令风格
- **Validate**: `python -m src.cli --help` 显示新命令

### Task 8: 现有模块修补
- **Action**: 
  - `src/learner/__init__.py`: 导出 `FeedbackCollector`, `EvolutionPipeline`, `SignalTracker`
  - `src/learner/profile.py`: `UserProfile` 增加 `strategy_contribution` 维度
  - `src/routing/orchestrator.py`: `Orchestrator.run()` 接受 `strategy_version` 参数
  - 所有新模块增加 `__init__.py` 导出
- **Validate**: `pytest tests/ -v --cov=src/learner --cov=src/backtest`

## Data Flow

```
回测优化 ──→ 最优参数 ──→ 策略注册中心
                              │
                              ▼
用户反馈 ──→ 反馈收集器 ──→ 权重校准器 ──→ 策略进化
                              │
                              ▼
信号追踪 ──→ 信号质量报告 ──→ 进化编排器 ──→ 新策略版本
                                               │
                                               ▼
                                          回测验证 ──→ 部署
```

## Validation

```bash
# 单元测试
pytest tests/test_optimizer.py tests/test_feedback.py tests/test_evolution.py -v

# 全量回归
pytest tests/ -v

# 覆盖率
pytest tests/ --cov=src/learner --cov=src/backtest --cov-report=term-missing

# CLI 可用性
python -m src.cli --help
```

## Risks

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| 过度优化（过拟合历史数据） | HIGH | 留出验证期（最后2年），优化只用训练期；Bayesian 优化用交叉验证 |
| 用户反馈稀疏（用户不反馈） | MEDIUM | 每笔交易自动生成反馈请求；支持批量反馈；默认假设「赞同」 |
| 策略进化引入回撤 | MEDIUM | 新策略必须通过回测验证 + 纸交易期；保留旧版本便于回滚 |
| 校准器误调权重 | LOW | 校准只做小幅调整（±10%），需 5+ 条反馈才触发调整 |
| backtrader 性能瓶颈 | LOW | 参数搜索用多进程并行 (joblib)；限制搜索空间 |

## Acceptance

- [ ] `GridSearchOptimizer` 能从 4 个参数的网格中找到最优组合
- [ ] `BayesianOptimizer` 25 轮内收敛到与网格搜索接近的结果
- [ ] `FeedbackCollector` 支持赞同/反对/调整/标注 4 种反馈类型
- [ ] `RuleCalibrator` 能根据反馈上下调规则权重
- [ ] `EvolutionPipeline` 端到端跑通：收集→分析→建议→验证
- [ ] `SignalTracker` 追踪信号全生命周期并生成质量报告
- [ ] CLI 新增 6 个命令均可正常执行
- [ ] 所有测试通过，覆盖率 80%+
- [ ] 现有回测和路由功能不受影响（回归测试通过）
