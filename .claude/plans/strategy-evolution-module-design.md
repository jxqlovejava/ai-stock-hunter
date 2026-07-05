# Design: Strategy Evolution Module (策略进化模块)

**Date**: 2026-07-05
**Status**: APPROVED
**Complexity**: LARGE

## Summary

构建策略进化模块 (`src/evolution/`)，支持：
1. 论文URL输入 → 自动提取策略或架构改进
2. 策略类：回测验证 → 模拟盘 → 实战的全生命周期管理
3. 架构类：生成改进提案 → 人工审核 → 实施 → A/B对比验证
4. 灵活可配置的性能阈值
5. 表现不佳时的自动优化/人工打回/撤回机制

## Architecture

```
src/evolution/
├── __init__.py              # 模块导出
├── schema.py                # DTO: StrategyPaper, ImproveProposal, LifecycleState 等
├── paper_importer.py        # URL→论文文本→AI 分类(策略/架构)
├── strategy_extractor.py    # 策略类论文→结构化策略定义
├── architecture_analyzer.py # 架构类论文→系统改进提案
├── backtest_validator.py    # 回测门禁 (可配置阈值)
├── trial_runner.py          # 模拟盘自动运行 (桥接 PaperTradingBridge)
├── trial_monitor.py         # 模拟盘监控 + 性能评估
├── pipeline_comparator.py   # 管道A/B对比 (架构论文验证)
├── lifecycle.py             # 统一状态机 + 策略全生命周期
├── rollback.py              # 撤回机制 + 版本回退
├── proposal.py              # 改进提案 DTO + 审批工作流
├── config.py                # 可配置阈值 (YAML)
└── cli.py                   # CLI 子命令扩展
```

## Strategy Lifecycle State Machine

```
论文URL
  │
  ▼
EXTRACTED ──(回测通过)──▶ CANDIDATE ──(模拟盘达标)──▶ TRIAL ──(人工确认)──▶ ACTIVE
  │                          │                         │                      │
  ▼                          ▼                         ▼                      ▼
ERROR                    REJECTED                  DEGRADED               DEGRADED
  │                          │                    ┌───┴───┐             ┌───┴───┐
  │                          │                    ▼       ▼             ▼       ▼
  │                    手动调整参数           OPTIMIZING  人工打回     RETIRED  RETIRED
  │                          │                    │    到 TRIAL
  │                          ▼                    │       │
  │                      EXTRACTED                ▼       │
  │                                     CANDIDATE (重新入池) │
  └──────────────────────────────────────────────────────────┘
```

### State Table

| State | Meaning | Allowed Transitions |
|-------|---------|-------------------|
| `EXTRACTED` | 论文已解析，待回测 | CANDIDATE, REJECTED, ERROR |
| `CANDIDATE` | 回测通过，候选池 | TRIAL, REJECTED, EXTRACTED |
| `TRIAL` | 模拟盘运行中 | ACTIVE, DEGRADED, CANDIDATE |
| `ACTIVE` | 实战中 | DEGRADED, RETIRED |
| `DEGRADED` | 表现不佳 | OPTIMIZING, TRIAL, RETIRED |
| `OPTIMIZING` | 自动优化中 | CANDIDATE |
| `REJECTED` | 未通过 | EXTRACTED, RETIRED |
| `RETIRED` | 已退役 | (terminal) |
| `ERROR` | 解析异常 | EXTRACTED, RETIRED |

## Two Paper Types

### Type A: Strategy Paper (策略类)

论文提出具体买卖规则、因子组合、择时信号。

**Pipeline**: URL → 提取策略定义 → 回测验证 → 模拟盘 → 实战

**Output**: 一个新策略实体加入候选池，走完整生命周期。

### Type B: Architecture Paper (架构类)

论文提出新的分析框架、风控体系、评分方法论、管道架构改进。

**Pipeline**: URL → 生成改进提案 → 人工审核 → 实施变更 → A/B对比 (旧管道 vs 新管道)

**Output**: 系统改进提案，审核通过后修改管道代码，验证后合入。

**Paper Classifier**: 用 AI 自动判类别，也可人工覆盖。

## Key Design Decisions

### DTO-First (遵循项目惯例)

所有跨模块数据使用 `@dataclass`，不用裸 dict。

### Read-Only Analysis, SignalWriter Only (遵循项目护栏)

- `paper_importer` / `strategy_extractor` / `architecture_analyzer` — 只读
- `backtest_validator` / `trial_monitor` / `pipeline_comparator` — 分析
- `lifecycle` / `rollback` — 状态变更 (有副作用)
- 仅 `trial_runner` 可触发模拟盘下单

### Configurable Thresholds (YAML)

```yaml
# data/evolution_config.yaml
backtest:
  min_sharpe_ratio: 0.5
  min_total_return: 0.1
  max_max_drawdown: 0.25
  min_trades: 20
  benchmark: "000300.SH"  # 沪深300

trial:
  min_duration_days: 30
  min_trades: 10
  sharpe_superiority: 0.1  # 需超基准 Sharpe 0.1
  max_drawdown_limit: 0.20
  benchmark: "000300.SH"

monitoring:
  check_interval_hours: 24
  degradation_window_days: 14  # 连续14天低于阈值触发 DEGRADED
  auto_optimize_on_degrade: true
```

### Source Citations (遵循项目护栏)

所有分析输出携带 `SourceCitation`，论文提取的内容标记 `[PAPER_SOURCED]`，AI 推测的内容标记 `[UNSOURCED]`。

## Integration Points

| Module | Integration |
|--------|------------|
| `src/backtest/engine.py` | 回测执行 |
| `src/backtest/strategy_registry.py` | 策略版本注册 |
| `src/backtest/comparator.py` | 策略对比 |
| `src/paper_trading/bridge.py` | 模拟盘执行 |
| `src/learner/evolution.py` | 现有进化管线 (参数优化) |
| `src/learner/feedback.py` | 反馈数据收集 |
| `src/learner/calibrator.py` | 策略权重校准 |
| `src/routing/orchestrator.py` | 全链路管道 |
| `src/cli.py` | CLI 命令扩展 |

## CLI Commands (New)

```bash
# 论文导入
python -m src.cli evolution import <url>            # 导入论文URL
python -m src.cli evolution import --type manual <desc>  # 手动描述

# 策略生命周期
python -m src.cli evolution list                     # 列出所有进化策略
python -m src.cli evolution status <id>              # 查看策略状态
python -m src.cli evolution promote <id>             # 手动推进状态
python -m src.cli evolution degrade <id> --reason    # 手动打回
python -m src.cli evolution retire <id>              # 退役策略
python -m src.cli evolution optimize <id>            # 触发自动优化

# 架构提案
python -m src.cli evolution proposals list            # 列出改进提案
python -m src.cli evolution proposals review <id>    # 审核提案
python -m src.cli evolution proposals apply <id>     # 实施提案
python -m src.cli evolution proposals compare <id>   # A/B对比

# 监控
python -m src.cli evolution monitor                   # 查看所有试验/实战策略状态
python -m src.cli evolution report <id>              # 详细报告
```

## Patterns to Mirror

| Category | Source | Pattern |
|----------|--------|---------|
| Naming | `src/backtest/strategy_registry.py:1` | `StrategyRegistry` — PascalCase classes, snake_case files |
| DTOs | `src/learner/evolution.py:51` | `@dataclass` for all cross-module data |
| State machine | `src/learner/evolution.py:40` | `EvolutionStatus(Enum)` — Enum-based state management |
| CLI | `src/cli.py:707` | `main()` dispatch pattern with subcommands |
| Error handling | `src/learner/evolution.py:214` | try/except → `EvolutionStatus.ERROR` |
| Persistence | `src/backtest/strategy_registry.py:182` | JSON file-based persistence |
| Config | `src/learner/preference/model.py` | YAML-based configuration |
| Logging | `src/paper_trading/bridge.py:19` | `logger = logging.getLogger(__name__)` |

## Files to Change

| File | Action | Why |
|------|--------|-----|
| `src/evolution/__init__.py` | CREATE | Module exports |
| `src/evolution/schema.py` | CREATE | DTOs: StrategyPaper, LifecycleState, TrialMetrics, etc. |
| `src/evolution/config.py` | CREATE | YAML config loader |
| `src/evolution/paper_importer.py` | CREATE | URL fetch + AI classification |
| `src/evolution/strategy_extractor.py` | CREATE | Strategy paper → structured strategy |
| `src/evolution/architecture_analyzer.py` | CREATE | Architecture paper → improvement proposal |
| `src/evolution/backtest_validator.py` | CREATE | Backtest gating with configurable thresholds |
| `src/evolution/trial_runner.py` | CREATE | Paper trading auto-execution |
| `src/evolution/trial_monitor.py` | CREATE | Trial performance monitoring |
| `src/evolution/pipeline_comparator.py` | CREATE | A/B pipeline comparison |
| `src/evolution/lifecycle.py` | CREATE | State machine + lifecycle manager |
| `src/evolution/rollback.py` | CREATE | Strategy rollback + version restore |
| `src/evolution/proposal.py` | CREATE | Improvement proposal DTO + approval workflow |
| `src/evolution/cli.py` | CREATE | CLI subcommand handlers |
| `data/evolution_config.yaml` | CREATE | Default configurable thresholds |
| `src/cli.py` | UPDATE | Add `evolution` command dispatch |

## Risks

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| AI 策略提取不准确 | HIGH | 人工审核环节 + [UNSOURCED] 标记 |
| 回测过拟合 (paper only looks good in backtest) | MEDIUM | 强制 walk-forward 验证 + 模拟盘阶段 |
| mx-moni API 不稳定 | MEDIUM | 重试 + 降级到纯跟踪模式 |
| 论文URL失效/无法访问 | LOW | 本地缓存论文全文 |
| 架构论文修改后管道退化 | LOW | A/B对比必须有改善才合入 |
