---
name: l0-gate
description: 安全门禁 — 硬性规则过滤，0% AI。检查 ST/*ST、新股、涨跌停、停牌、流动性。触发词：门禁、安全检查、gate、L0、可交易性。
---

# L0 安全门禁 (Security Gate)

纯规则引擎，0% AI 参与。在进入 L1 分析前过滤掉不可交易的标的。

## 规则

### 硬性排除 (REJECTED)
| 规则 | 条件 | 严重度 |
|------|------|--------|
| ST 股票 | 名称含 `ST` 或 `*ST` | FATAL |
| 新股未满 | 上市天数 < 60 个自然日 | FATAL |
| 涨停封板 | 涨停且封单 > 0 (买不到) | FATAL |
| 跌停封板 | 跌停且封单 > 0 (卖不掉) | FATAL |
| 停牌 | 当前处于停牌状态 | FATAL |

### 软性标记 (FLAGGED)
| 规则 | 条件 | 严重度 |
|------|------|--------|
| 低流动性 | 日均成交额 < 5000 万 | WARNING |
| 违规记录 | 近 12 个月有交易所处罚 | WARNING |
| 高质押 | 大股东质押 > 80% | INFO |

## 工作流

1. 接收股票代码和名称
2. 检查 ST 标记 → 命中则 REJECTED
3. 检查上市天数 → < 60 天则 REJECTED
4. 检查涨跌停状态 → 封板则 REJECTED
5. 检查停牌状态 → 停牌则 REJECTED
6. 检查流动性 → < 5000 万则 FLAGGED
7. 返回 `SecurityPass` (status + flags)

## 输出

```python
SecurityPass(
    status=GateStatus.REJECTED,  # or PASSED / FLAGGED
    flags=["ST 股票禁止交易"],
    blocked_by=["rule_st_stock"],
)
```

## A 股特定

- 涨停/跌停判断使用 10% (主板) / 20% (科创/创业板)
- ST 股票涨跌幅限制为 5%
- 新股上市首日涨跌幅 44% (主板), 无限制 (科创/创业板前 5 日)

## 护栏

- **0% AI**: 该阶段不使用任何 AI/LLM
- **先于 L1**: L0 拒绝的标的绝不进入后续分析
- **可审计**: 每条拒绝原因可追溯到具体规则

## 引用

- Python 实现: `src/routing/l0_gate.py`
- 依赖 Skill: `l1-analyze`
