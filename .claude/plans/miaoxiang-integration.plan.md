# Plan: 妙想Skill 集成到白泽数据管道

**Source PRD**: 妙想Skill 能力分析 + 现有数据源结合方案
**Selected Milestone**: Phase 1 + Phase 2 + Phase 3（排除 mx-zixuan）
**Complexity**: Large

## Summary
将 5 个妙想 Skill（mx-data / mx-search / mx-xuangu / mx-moni / mx-poster）集成到白泽系统数据管道中。
核心思路：mx-data 作第三方数据源 Provider 加入聚合器优先级链、mx-search 增强资讯/政策/消息面、mx-xuangu 作全市场预筛选加速、mx-moni 补齐策略验证闭环、mx-poster 作可选的分析结果社区化输出。
排除 mx-zixuan（自选股管理），与其他 Skill 无依赖，对决策管道价值有限。

## Patterns to Mirror

| Category | Source | Pattern |
|---|---|---|
| Naming | `src/data/guosen.py:27` | `source_name = "xxx"` 类属性标识数据源 |
| Naming | `src/data/aggregator.py:36` | `_provider: ProviderType \| None = None` 懒加载属性 |
| Errors | `src/data/guosen.py:32-36` | 初始化时 `raise RuntimeError` 缺凭据；查询时 `return None` 静默降级 |
| Errors | `src/data/aggregator.py:56` | `try/except RuntimeError: pass` → 懒加载返回 None |
| Logging | `src/data/mootdx_tencent.py:24` | `logger = logging.getLogger(__name__)` 模块级 |
| Data access | `src/data/base.py:16-39` | `DataProvider(ABC)` 统一接口 + `return None` 降级 |
| Data access | `src/data/aggregator.py:35-39` | `self._cache: dict[str, tuple[datetime, object]]` + TTL |
| Schema | `src/data/schema.py:22-38` | `pydantic BaseModel` + `Optional[float]` + `source: str` 来源追踪 |
| Tests | `tests/` | `pytest` + `Test*` 类 + `test_*` 方法 |
| CLI | `src/cli.py:44-78` | `cmd_xxx(args)` 函数 + `argparse` |

## Files to Change

| File | Action | Why |
|---|---|---|
| `src/data/miaoxiang_provider.py` | CREATE | MiaoXiangProvider 实现 DataProvider 接口 |
| `src/data/miaoxiang_adapter.py` | CREATE | 封装 subprocess 调用 mx CLI 脚本的逻辑 |
| `src/data/schema.py` | UPDATE | 新增 NewsItem / RelatedParty / ScreeningResult DTO |
| `src/data/aggregator.py` | UPDATE | 注册 MiaoXiangProvider，升级 V4 优先级链 |
| `src/data/__init__.py` | UPDATE | 导出新 Provider |
| `src/paper_trading/__init__.py` | CREATE | 模拟交易模块 |
| `src/paper_trading/bridge.py` | CREATE | L3 Signal → mx-moni 模拟执行桥接 |
| `src/routing/orchestrator.py` | UPDATE | 注入 mx-search 资讯上下文 + mx-moni 闭环 |
| `src/routing/l4_risk.py` | UPDATE | 注入 mx-data 关联关系风险检查 |
| `src/cli.py` | UPDATE | 新增 search-news / screen / related / paper-trade 命令 |
| `tests/test_miaoxiang_provider.py` | CREATE | MiaoXiangProvider 单元测试 |
| `tests/test_paper_trading.py` | CREATE | 模拟交易桥接测试 |

## Tasks

### Task 1: Schema 扩展 — 新增 DTO 类型
- **Action**: 在 `src/data/schema.py` 新增 `NewsItem`、`RelatedParty`、`ScreeningResult` 三个 pydantic BaseModel
- **Mirror**: `src/data/schema.py:22-38` Quote 的字段设计模式（Optional + source + 描述）
- **Validate**: `python -c "from src.data.schema import NewsItem, RelatedParty, ScreeningResult; print('OK')"`

### Task 2: MiaoXiangAdapter — 封装 CLI subprocess 调用
- **Action**: 创建 `src/data/miaoxiang_adapter.py`，封装对 mx-data/mx-search/mx-xuangu Python 脚本的 subprocess 调用，含超时+重试+JSON 解析
- **Mirror**: `src/data/guosen.py:47-60` requests 调用的 try/except + return None 模式
- **Validate**: `python -c "from src.data.miaoxiang_adapter import MiaoXiangAdapter; a = MiaoXiangAdapter(); print(a.health_check())"`

### Task 3: MiaoXiangProvider — 实现 DataProvider 接口
- **Action**: 创建 `src/data/miaoxiang_provider.py`，实现 `get_quote()` / `get_financials()` / `health_check()`，以及独有方法 `search_news()` / `get_related_parties()` / `screen_stocks()`
- **Mirror**: `src/data/guosen.py:24-27` 类结构 + `source_name` + `__init__` 模式
- **Validate**: `pytest tests/test_miaoxiang_provider.py -v`

### Task 4: DataAggregator V4 升级
- **Action**: 在 `aggregator.py` 中懒加载注册 MiaoXiangProvider，升级优先级链（行情交叉验证、搜索委托、选股委托），新增 `search_news()` / `screen_stocks()` / `get_related_parties()` 代理方法
- **Mirror**: `src/data/aggregator.py:35-58` 懒加载属性 + cache 模式
- **Validate**: `python -c "from src.data.aggregator import DataAggregator; a = DataAggregator(); print(a.source_status())"`

### Task 5: CLI 命令扩展
- **Action**: 新增 `cmd_search_news` / `cmd_screen` / `cmd_related` 命令 + argparse
- **Mirror**: `src/cli.py:44-78` cmd_scan 的函数签名 + argparse 模式
- **Validate**: `python -m src.cli screen --help` / `python -m src.cli search-news --help`

### Task 6: Orchestrator 资讯上下文注入
- **Action**: 在 `orchestrator.py` 的 `run()` 中新增 Step 0.5 调用 `self.data.search_news()` 获取资讯上下文，传入 L1Analyzer
- **Mirror**: `src/routing/orchestrator.py:127-131` Phase 3 增强上下文注入模式
- **Validate**: `pytest tests/ -k "orchestrator" -v`

### Task 7: L4 关联关系风险检查
- **Action**: 在 `l4_risk.py` 中新增关联关系风险检查项（商誉/质押/关联交易），数据来源 mx-data
- **Mirror**: `src/routing/l4_risk.py` 现有 check() 方法的逐项检查模式
- **Validate**: `pytest tests/ -k "risk" -v`

### Task 8: 模拟交易桥接
- **Action**: 创建 `src/paper_trading/bridge.py`，实现 L3 TradeSignal → mx-moni 模拟下单 → 跟踪盈亏 → learner 反馈的闭环
- **Mirror**: `src/routing/orchestrator.py:352-396` Signal Writer 的 agent 边界模式
- **Validate**: `pytest tests/test_paper_trading.py -v`

### Task 9: mx-poster 可选输出
- **Action**: 在 CLI 新增 `cmd_poster` 命令，支持将 L2 裁决结果格式化为社区帖子并发布
- **Mirror**: `src/cli.py:44-78` cmd_scan 函数模式
- **Validate**: `python -m src.cli poster --help`

### Task 10: 集成测试 + 文档更新
- **Action**: 编写端到端集成测试，验证全链路：mx-xuangu 预筛选 → L0→L4 → mx-moni 模拟执行
- **Mirror**: `tests/` 现有测试的组织方式
- **Validate**: `pytest tests/ --cov=src --cov-report=term-missing`

## Validation

```bash
# 单元测试
pytest tests/test_miaoxiang_provider.py tests/test_paper_trading.py -v

# 全量回归
pytest tests/ -v

# Schema 验证
python -c "
from src.data.schema import Quote, Financials, FundamentalMetrics, NewsItem, RelatedParty
print('All schemas OK')
"

# Provider 注册验证
python -c "
from src.data.aggregator import DataAggregator
agg = DataAggregator()
status = agg.source_status()
assert 'miaoxiang' in status, f'miaoxiang not in {status}'
print('Provider registered:', status)
"

# CLI 命令可用
python -m src.cli search-news --help
python -m src.cli screen --help
python -m src.cli related --help
```

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| mx CLI subprocess 调用超时/失败 | HIGH | 3次重试 + 5s超时 + 降级到现有数据源 |
| 每日调用次数限制 (code=113) | HIGH | 本地缓存 TTL 对齐数据新鲜度，请求合并 |
| mx-data 输出 JSON 格式变更 | MEDIUM | 解析时用 try/except + schema 校验 |
| mx-moni 模拟账户未创建 | MEDIUM | 引导用户到妙想页面绑定账户 |
| 两套数据源数值不一致 | MEDIUM | dispute 标记 >5% 差异，人工审查 |
| mx-poster 授权未完成 | LOW | 前置检测，未授权时跳过社区功能 |

## Acceptance
- [ ] MiaoXiangProvider 实现 DataProvider 接口且通过单元测试
- [ ] DataAggregator V4 优先级链正确降级
- [ ] mx-search 资讯注入 L1Analyzer 消息面维度
- [ ] mx-xuangu 预筛选集成到 scan 命令
- [ ] mx-data 关联关系注入 L4 风控
- [ ] mx-moni 模拟交易桥接可用
- [ ] CLI 新命令全部可执行
- [ ] 现有测试全部回归通过
- [ ] 覆盖率 ≥ 80%
