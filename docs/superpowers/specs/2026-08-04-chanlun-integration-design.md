# 缠论分析模块融入 — 设计文档

> 日期: 2026-08-04 | 方案: 自研核心 + czsc 适配器 | 周期: 日线 + 周线 | tactics 语义: A（独立报告，保守）

## 目标

将缠论（缠中说禅）结构分析模块融入白泽系统，覆盖：分型 → 笔 → 中枢 → 背驰 → 买卖点。定位为**技术面结构增强**，不替代军规→准入→诊断→裁决→仓位→风控主链。

- 自研纯 Python 核心（无新增依赖），对齐 `src/indicators/` LEAN 架构与『可移植优先』原则。
- 可选 czsc 适配器：已安装则交叉验证 + 提升置信度；未安装静默降级自研，永不因 czsc 崩溃。
- 融入四管道：CLI 子命令、tactics 短线管道、diagnose 全链路、军规风控。
- A 股长多语义：一买/二买/三买 → 入场信号；一卖/二卖/三卖 → 离场/减仓/止盈信号。

## 模块结构 — `src/indicators/chanlun/`

```
src/indicators/chanlun/
├── __init__.py        # 导出 ChanlunAnalyzer / ChanlunResult / DTOs
├── schema.py          # 不可变 DTO: Fractal / Bi / ZhongShu / ChanlunPoint / ChanlunResult
├── core/
│   ├── __init__.py
│   ├── merge.py       # 去包含（新K线处理）
│   ├── fractal.py     # 顶底分型识别
│   ├── bi.py          # 笔构建（方向交替 + 最小长度）
│   ├── zhongshu.py    # 中枢识别（≥3笔重叠区间 + 延伸/上移/下移）
│   └── bihuang.py     # 背驰判定（MACD 面积 / 价格力度）
├── points.py          # 一买/二买/三买 + 一卖/二卖/三卖
└── analyzer.py        # ChanlunAnalyzer 组合入口 + czsc 适配器
```

- 周期通过 `freq="D"|"W"` 参数实例化，日/周线复用同一管道。
- 新增 `src/indicators/__init__.py` 导出：`ChanlunAnalyzer`、`ChanlunResult`、`Fractal`、`Bi`、`ZhongShu`、`ChanlunPoint`。

## 核心算法链路

`原始K线 → 去包含(merge) → 分型(fractal) → 笔(bi) → 中枢(zhongshu) → 背驰(bihuang) → 买卖点(points)`

| 阶段 | 规则 |
|---|---|
| **去包含** | 相邻K线高低完全覆盖→合并。上升方向取较大高/较大低；下降方向取较小高/较小低。方向由合并K线与前一K线相对位置确定 |
| **分型** | 去包含后相邻三根：`k1.h<k2.h>k3.h 且 k1.l<k2.l>k3.l`→顶分型(G)；反之底分型(D)。平盘不误判 |
| **笔** | 顶底分型严格交替；相邻分型间隔 ≥ 4 根去包含K线（最小长度）；上升笔顶>底、下降笔底<顶 |
| **中枢** | ≥3 笔重叠：`zg=min(前3笔high)`，`zd=max(前3笔low)`，`zg>zd` 有效。识别延伸（新笔回中枢）、上移（新 zd > 旧 zg）、下移（新 zg < 旧 zd） |
| **背驰** | 相邻同向段比较力度（MACD 柱面积 / 价格幅度）：创更低低点但力度减小→底背驰；创更高高点但力度减小→顶背驰 |
| **买卖点** | 一买=下降趋势（≥2 中枢）+ 最后一段底背驰 + 底分型确认；二买=一买后反弹回调不破一买低点 + 底分型；三买=突破中枢 ZG 后回调低点 > ZG 不回中枢 + 底分型。一卖/二卖/三卖镜像（A 股仅作离场/减仓） |

## 数据流与 DTO

输入：`pd.DataFrame`（列 `open/high/low/close/volume`，index=datetime）→ 与 tactics `_dim_technical` 现成的 `_bars_df` 完全同构。

```python
@dataclass(frozen=True)
class Fractal:      mark: str          # "G"(顶) / "D"(底)
                    dt, high, low, fx: float
                    index: int
@dataclass(frozen=True)
class Bi:           direction: str     # "up" / "down"
                    start_fx, end_fx: Fractal
                    high, low, length: int
                    macd_area: float   # 段内 MACD 柱面积（背驰用）
                    start_dt, end_dt: datetime
@dataclass(frozen=True)
class ZhongShu:     zg, zd, zz, gg, dd: float
                    start_dt, end_dt: datetime
                    state: str         # "形成"/"延伸"/"上移"/"下移"
@dataclass(frozen=True)
class ChanlunPoint: kind: str          # "一买"/"二买"/"三买"/"一卖"/"二卖"/"三卖"
                    dt, price, confidence: float
                    rationale: str
@dataclass(frozen=True)
class ChanlunResult:
    symbol, freq: str
    backend: str                      # "self" / "czsc" / "hybrid"
    fractals: list[Fractal]
    bis: list[Bi]
    zhongshus: list[ZhongShu]
    points: list[ChanlunPoint]
    current_state: dict               # 现价 vs 最近中枢位置 / 最近买卖点
    signals: dict                     # {entry: [...], exit: [...]} 长多语义
    source_citations: list[dict]
    confidence: float
```

接口：
- `ChanlunAnalyzer.analyze(df, symbol, name, freq="D") -> ChanlunResult`
- `ChanlunAnalyzer.to_signal(result) -> dict`（A 股长多：一买/二买/三买 → entry；一卖/二卖/三卖 → exit）

护栏：`source_citations` 携带 provider/field/confidence/tier/nature（结构计算类 nature=`interpretation`，tier=`T2`）；`confidence` = 数据源置信度 × 数据充足度，K线 < 50 根降权；数据不足返回空结果而非报错。

## 四管道融入点（最小侵入）

| 管道 | 文件 | 改动 |
|---|---|---|
| **CLI** | `src/cli.py` | 新增 `cmd_chanlun(args)`（argparse `--freq D\|W`，默认 D），`commands` dict 加 `"chanlun"`，`_NL_ROUTES` 加 `["缠论","中枢","背驰","买点","卖点"]`。输出：分型/笔/中枢明细表 + 买卖点列表 + 现价相对中枢位置 + 信号汇总 |
| **tactics** | `src/routing/tactics.py` | ① `TacticalSnapshot` 加 `chanlun_result: Optional[dict]` + `chanlun_score: float`（默认 50，独立维度，不改 `technical_composite`）；② `_dim_technical()` 内用 `_bars_df` 调 `ChanlunAnalyzer`，缠论买卖点并入 `entry_signals`/`exit_signals`（`type` 前缀 `CHANLUN_`，如 `CHANLUN_一买`）；③ 缠论状态注入 `doctrine_ctx`（`chanlun_*` 字段）供军规消费 |
| **diagnose** | `src/routing/diagnosis.py` | 仿 `_detect_bottom_structure` 加 `_detect_chanlun()` → 返回 `(score, state, entry_allowed)` 微调 `momentum_score`（范围 ±10，保守）；`DiagnosisReport` 加 `chanlun: Optional[dict]` 只读输出 |
| **军规** | `src/doctrine/rules.py` + `checker.py` | 加 `r037`(WARN) + `r038`(WARN)；`_evaluate` 加 `if rule.id == "r037"` / `"r038"` 分支读 `ctx["chanlun_*"]` |

**tactics 评分语义（已确认 A）**：缠论分独立报告，仅买卖点并入入场/出场信号；`technical_composite` 仍为原 6 维权重，不动。

### 军规 r037 / r038 触发条件（精确）

`tactics`/`diagnose` 把缠论结果写入 `doctrine_ctx` 以下字段：

| 字段 | 来源 |
|---|---|
| `chanlun_sell_signal` | 最近出现的一卖/二卖/三卖（`"sell"` 或 `""`） |
| `chanlun_zs_break` | 现价跌破最近有效中枢 `zd` 或升破 `zg` 后回落（bool） |
| `chanlun_buy_confirmed` | 最近 5 根K线内出现一买/二买/三买（bool） |
| `chanlun_bihuang_down` | 最后一段下跌出现底背驰（bool） |

- **r037（WARN，中枢破位/三卖不追）**：`chanlun_sell_signal == "sell"` 或 `chanlun_zs_break == True` → 提示"缠论结构转弱，追高/抄底需谨慎"。
- **r038（WARN，背驰未确认不进场）**：`chanlun_zs_break == True` 且 `chanlun_buy_confirmed == False` 且 `chanlun_bihuang_down == False` → 提示"中枢破位且无底背驰/买点确认，跌势未止，避免左侧抄底"。

两军规均为 WARN 级（短线 tactics 不 block，仅警告累积进 `doctrine_warnings`；全链路 diagnose 同）。

## 错误处理与护栏

- K线 < 30 根 → 返回空 `ChanlunResult` + `[DATA_GAP]` 标注，不阻塞管道
- 无有效中枢 / 无买卖点 → `current_state={"zhongshu": "未形成"}`，signals 全空
- MACD 面积计算 → `np.isfinite` 防御 NaN；分母为 0 → fallback 0
- 未知 freq / 缺列（无 volume）→ 显式 `ValueError`，调用方 `except` 降级 `[DATA_GAP]`
- czsc 适配器任何异常 → `logger.debug` + 回退自研，结果标注 `backend="self"`
- 不输出具体买卖建议（沿用 guardrails 禁止内容条款）；信号只描述结构状态

## 测试计划（`tests/indicators/test_chanlun*.py`）

1. `test_merge`：包含合并方向（上升取大 / 下降取小）、无包含不变
2. `test_fractal`：标准顶/底分型、平盘不误判
3. `test_bi`：交替约束、最小长度边界（恰好 4 根 / 不足 4 根）
4. `test_zhongshu`：有效/无效中枢、上移/下移判定
5. `test_bihuang`：底/顶背驰、假突破不误判、NaN 防御
6. `test_points`：合成下降趋势 → 一买/二买/三买；镜像一卖
7. `test_adapter`：czsc 缺失时 `backend="self"` 静默降级
8. 集成：tactics `_dim_technical` 单测（mock `_bars_df` 注入）+ CLI `chanlun` smoke test

## 里程碑

- **M1** 核心：`schema.py` + `core/merge` + `core/fractal` + `core/bi` + `core/zhongshu` + 单测
- **M2** 背驰 + 买卖点 + `analyzer` + czsc 适配器 + 单测
- **M3** CLI `chanlun` 子命令 + `_NL_ROUTES`
- **M4** tactics 融入（`TacticalSnapshot` + `_dim_technical` + `doctrine_ctx` 注入）
- **M5** diagnose 融入 + 军规 r037/r038 + 集成测试

## 不做（YAGNI）

- 不接入 60min/30min 日内缠论（数据源未接入，留待后续）
- 不引入 czsc 为硬依赖（依赖树过重 + pandas 3.0.3 兼容未验证）
- 不改 7/9/11 笔形态分类（czsc 有，自研核心暂不实现，适配器可用时透传）
- 不做缠论可视化图表（仅文本表格，TradingView 渲染留待 Web 前端）
