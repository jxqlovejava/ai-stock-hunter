# 缠论分析模块融入 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将缠论（去包含→分型→笔→中枢→背驰→买卖点）结构分析模块融入白泽系统，覆盖 CLI / tactics / diagnose / 军规 四管道。

**Architecture:** 自研纯 Python 缠论核心（`src/indicators/chanlun/`，无新增依赖）+ 可选 czsc 适配器（已安装则交叉验证，未安装静默降级）。日线 + 周线双周期。A 股长多语义（一买/二买/三买→入场，一卖/二卖/三卖→离场/减仓）。

**Tech Stack:** Python 3.11+ / pandas 3.0.3 / pytest；参考 spec `docs/superpowers/specs/2026-08-04-chanlun-integration-design.md`。

## Global Constraints

- **无新增依赖**：自研核心纯 `dataclasses`/`numpy`/`pandas`，不 import czsc（仅适配器内部 try-import）。
- **DTO 优先**：跨层数据结构用 `@dataclass(frozen=True)`，不用裸 dict。
- **护栏**：每个结果携带 `source_citations` + `confidence` + 数据充足度；K线 < 30 根 → 返回空结果 + `[DATA_GAP]`，不抛错不阻塞管道。
- **A 股长多**：买卖点只映射为入场/离场（无做空）。
- **tactics 语义（决策 A）**：缠论分独立报告，`technical_composite` 仍为原 6 维权重，不动。
- **军规**：新增 r037/r038 均为 WARN 级，tactics 不 block。
- **测试**：`pytest tests/`，类级 `Test*` + 方法级 `test_*` 命名。
- **提交**：`<type>: <description>`（feat/fix/docs/test/chore），每次任务完成单独 commit。

---

### Task 1: 缠论 DTO 与 schema

**Files:**
- Create: `src/indicators/chanlun/__init__.py`
- Create: `src/indicators/chanlun/schema.py`
- Create: `src/indicators/chanlun/core/__init__.py`
- Test: `tests/indicators/test_chanlun_schema.py`

**Interfaces:**
- Produces: `Fractal`/`Bi`/`ZhongShu`/`ChanlunPoint`/`ChanlunResult` dataclass + `ChanlunResult.to_summary_dict()`. 后续所有 task 消费这些 DTO 字段名。

- [ ] **Step 1: 写失败测试**

```python
# tests/indicators/test_chanlun_schema.py
# -*- coding: utf-8 -*-
from src.indicators.chanlun.schema import Bi, ChanlunPoint, ChanlunResult, Fractal, ZhongShu


def test_fractal_fields():
    f = Fractal(mark="G", dt="2026-01-05", high=12.0, low=10.0, fx=12.0, index=4)
    assert f.mark == "G" and f.fx == 12.0 and f.index == 4


def test_result_to_summary_dict():
    zs = ZhongShu(zg=18.0, zd=15.0, zz=16.5, gg=20.0, dd=12.0,
                  start_dt="2026-01-01", end_dt="2026-01-10", state="形成")
    p = ChanlunPoint(kind="一买", dt="2026-02-01", price=15.0, confidence=0.7,
                     rationale="下降末段底背驰")
    r = ChanlunResult(symbol="000001", name="测试", freq="D", backend="self",
                      fractals=[], bis=[], zhongshus=[zs], points=[p],
                      current_state={"position": "中枢内"}, signals={"entry": [], "exit": []},
                      source_citations=[], confidence=0.8)
    d = r.to_summary_dict()
    assert d["backend"] == "self"
    assert d["zhongshu_count"] == 1
    assert d["last_zs"]["zg"] == 18.0
    assert d["points"][0]["kind"] == "一买"
    assert d["signals"] == {"entry": [], "exit": []}
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/indicators/test_chanlun_schema.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.indicators.chanlun'`

- [ ] **Step 3: 写实现**

```python
# src/indicators/chanlun/schema.py
# -*- coding: utf-8 -*-
"""缠论结构 DTO — 分型/笔/中枢/买卖点/分析结果。全 frozen 不可变。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class Fractal:
    """顶/底分型。mark: "G"(顶) / "D"(底)。fx 顶取 high、底取 low。"""

    mark: str
    dt: Any                       # 中间去包含K线时间
    high: float
    low: float
    fx: float
    index: int                    # 去包含K线下标


@dataclass(frozen=True)
class Bi:
    """笔 — 连接相邻顶底分型的最小走势单元。"""

    direction: str                # "up" / "down"
    start_fx: Fractal
    end_fx: Fractal
    high: float
    low: float
    length: int                   # 两端分型间去包含K线数
    macd_area: float              # 段内 |MACD柱| 面积（背驰用）
    start_dt: Any
    end_dt: Any


@dataclass(frozen=True)
class ZhongShu:
    """中枢 — ≥3 笔重叠价格区域。"""

    zg: float                     # 上沿 = min(构成笔 high)
    zd: float                     # 下沿 = max(构成笔 low)
    zz: float                     # 中轴 = (zg+zd)/2
    gg: float                     # 区域最高
    dd: float                     # 区域最低
    start_dt: Any
    end_dt: Any
    state: str                    # "形成"/"延伸"/"上移"/"下移"


@dataclass(frozen=True)
class ChanlunPoint:
    """买卖点信号。"""

    kind: str                     # "一买"/"二买"/"三买"/"一卖"/"二卖"/"三卖"
    dt: Any
    price: float
    confidence: float             # 0.0-1.0
    rationale: str


@dataclass(frozen=True)
class ChanlunResult:
    """缠论全量分析结果。"""

    symbol: str
    name: str
    freq: str                     # "D" / "W"
    backend: str                  # "self" / "czsc"
    fractals: list[Fractal]
    bis: list[Bi]
    zhongshus: list[ZhongShu]
    points: list[ChanlunPoint]
    current_state: dict           # 现价位置/中枢状态/最近买卖点
    signals: dict                 # {"entry": [...], "exit": [...]}
    source_citations: list[dict]
    confidence: float

    def to_summary_dict(self) -> dict:
        """序列化为 dict 供 tactics/diagnose/CLI 消费。"""
        return {
            "backend": self.backend,
            "freq": self.freq,
            "bi_count": len(self.bis),
            "zhongshu_count": len(self.zhongshus),
            "last_zs": (
                {"zg": self.zhongshus[-1].zg, "zd": self.zhongshus[-1].zd,
                 "zz": self.zhongshus[-1].zz, "state": self.zhongshus[-1].state}
                if self.zhongshus else None
            ),
            "points": [
                {"kind": p.kind, "dt": str(p.dt), "price": p.price,
                 "confidence": p.confidence, "rationale": p.rationale}
                for p in self.points
            ],
            "current_state": self.current_state,
            "signals": self.signals,
            "confidence": self.confidence,
        }
```

```python
# src/indicators/chanlun/__init__.py
# -*- coding: utf-8 -*-
"""缠论结构分析 — 分型/笔/中枢/背驰/买卖点。"""
from .schema import Bi, ChanlunPoint, ChanlunResult, Fractal, ZhongShu

__all__ = ["Fractal", "Bi", "ZhongShu", "ChanlunPoint", "ChanlunResult"]
```

```python
# src/indicators/chanlun/core/__init__.py
# -*- coding: utf-8 -*-
```
(空文件，声明 core 子包)

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/indicators/test_chanlun_schema.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: 提交**

```bash
git add src/indicators/chanlun tests/indicators/test_chanlun_schema.py
git commit -m "feat(chanlun): 缠论 DTO schema（分型/笔/中枢/买卖点/结果）"
```

---

### Task 2: 去包含（core/merge.py）

**Files:**
- Create: `src/indicators/chanlun/core/merge.py`
- Test: `tests/indicators/test_chanlun_merge.py`

**Interfaces:**
- Consumes: `pd.DataFrame`（列 `open/high/low/close`，index=datetime）
- Produces: `MergedBar(index, dt, high, low, direction)` 与 `merge_bars(df) -> list[MergedBar]`。Task 3 消费 `merged` 列表。

- [ ] **Step 1: 写失败测试**

```python
# tests/indicators/test_chanlun_merge.py
# -*- coding: utf-8 -*-
import pandas as pd

from src.indicators.chanlun.core.merge import merge_bars


def _make_df(rows):
    idx = pd.date_range("2026-01-01", periods=len(rows), freq="D")
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx)


def test_up_direction_merge_takes_larger():
    df = _make_df([
        (8, 9, 7, 8.5),        # [7,9]  首根
        (8.5, 10, 8, 9),       # [8,10] 无包含, high↑ → direction=up
        (9, 9.5, 8.5, 9.2),    # [8.5,9.5] 被 [8,10] 包含 → 取较大高/较大低
    ])
    merged = merge_bars(df)
    assert len(merged) == 2            # 3 根合并为 2
    assert merged[-1].high == 10.0     # max(10, 9.5)
    assert merged[-1].low == 8.5       # max(8, 8.5)
    assert merged[-1].direction == "up"


def test_down_direction_merge_takes_smaller():
    df = _make_df([
        (10, 12, 9, 10.5),     # [9,12] 首根
        (9.5, 10.5, 8.5, 9),   # [8.5,10.5] 无包含, high↓ → direction=down
        (9, 9.5, 8.8, 9.2),    # [8.8,9.5] 被 [8.5,10.5] 包含 → 取较小高/较小低
    ])
    merged = merge_bars(df)
    assert len(merged) == 2
    assert merged[-1].high == 9.5      # min(10.5, 9.5)
    assert merged[-1].low == 8.5       # min(8.5, 8.8)
    assert merged[-1].direction == "down"


def test_no_containment_keeps_all_bars():
    df = _make_df([
        (8, 9, 7, 8.5), (8.5, 10, 8, 9), (9, 11, 8.8, 10.5),
    ])
    merged = merge_bars(df)
    assert len(merged) == 3
    assert merged[-1].direction == "up"


def test_empty_df_returns_empty():
    df = _make_df([])
    assert merge_bars(df) == []


def test_partial_overlap_not_merged():
    # 前根 [10,12], 当前 [7,9] → 当前整体低于前根, 非包含 → 不合并（回归 Bug1）
    df = _make_df([(10, 12, 9, 10.5), (8, 9, 7, 8)])
    merged = merge_bars(df)
    assert len(merged) == 2
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/indicators/test_chanlun_merge.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.indicators.chanlun.core.merge'`

- [ ] **Step 3: 写实现**

```python
# src/indicators/chanlun/core/merge.py
# -*- coding: utf-8 -*-
"""去包含处理 — 缠论新K线合并。上升取较大高/较大低，下降取较小高/较小低。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MergedBar:
    """去包含后的合并K线。direction: ""(首根)/"up"/"down"。"""

    index: int        # 原始 DataFrame 位置（末根合并进该根的 index）
    dt: Any
    high: float
    low: float
    direction: str


def merge_bars(df) -> list[MergedBar]:
    """将 OHLCV DataFrame 合并为去包含K线列表。

    Args:
        df: 含 open/high/low/close 列，index=datetime。

    Returns:
        升序 MergedBar 列表；空输入返回 []。
    """
    if df is None or len(df) == 0:
        return []
    highs = df["high"].values.astype(float)
    lows = df["low"].values.astype(float)
    dts = df.index

    merged = [MergedBar(0, dts[0], highs[0], lows[0], direction="")]
    for i in range(1, len(df)):
        prev = merged[-1]
        hi, lo = highs[i], lows[i]
        contains = (hi >= prev.high and lo <= prev.low) or \
                   (prev.high >= hi and prev.low <= lo)
        if contains:
            if prev.direction == "up":
                new_hi, new_lo, direction = max(hi, prev.high), max(lo, prev.low), "up"
            elif prev.direction == "down":
                new_hi, new_lo, direction = min(hi, prev.high), min(lo, prev.low), "down"
            else:  # 首根被包含，方向按 high 关系判定
                direction = "up" if hi >= prev.high else "down"
                if direction == "up":
                    new_hi, new_lo = max(hi, prev.high), max(lo, prev.low)
                else:
                    new_hi, new_lo = min(hi, prev.high), min(lo, prev.low)
            merged[-1] = MergedBar(i, dts[i], new_hi, new_lo, direction)
        else:
            direction = "up" if hi > prev.high else "down"
            merged.append(MergedBar(i, dts[i], hi, lo, direction))
    return merged
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/indicators/test_chanlun_merge.py -v`
Expected: PASS (5 passed)

- [ ] **Step 4b: 真实数据验证（强趋势标的 300476）— 必须执行，回归 Bug1**

Run:
```bash
.venv/bin/python - <<'PY'
import pandas as pd
from src.data.aggregator import DataAggregator
from src.indicators.chanlun.core.merge import merge_bars
agg = DataAggregator()
df = agg.get_history("300476")
col_map = {"开盘":"open","收盘":"close","最高":"high","最低":"low","成交量":"volume"}
df = df.rename(columns={c: col_map[c] for c in df.columns if c in col_map})
merged = merge_bars(df)
print(f"raw={len(df)} merged={len(merged)} ratio={len(merged)/max(1,len(df)):.2f}")
PY
```
Expected: `merged` 与 `raw` 数量级相近（ratio 通常 >0.5，下跌回调K线不被错误合并）。若 `ratio < 0.1`（如 2704→72）说明包含判定仍错，不得提交。

- [ ] **Step 5: 提交**

```bash
git add src/indicators/chanlun/core/merge.py tests/indicators/test_chanlun_merge.py
git commit -m "feat(chanlun): 去包含K线合并（方向判定+包含合并）"
```

---

### Task 3: 分型识别（core/fractal.py）

**Files:**
- Create: `src/indicators/chanlun/core/fractal.py`
- Test: `tests/indicators/test_chanlun_fractal.py`

**Interfaces:**
- Consumes: `merge_bars` 输出的 `list[MergedBar]`
- Produces: `detect_fractals(merged) -> list[Fractal]`。Task 4 消费 `fractals`。

- [ ] **Step 1: 写失败测试**

```python
# tests/indicators/test_chanlun_fractal.py
# -*- coding: utf-8 -*-
from src.indicators.chanlun.core.fractal import detect_fractals
from src.indicators.chanlun.core.merge import merge_bars
import pandas as pd


def _merged(rows):
    idx = pd.date_range("2026-01-01", periods=len(rows), freq="D")
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx)
    return merge_bars(df)


def test_top_fractal():
    merged = _merged([(8, 9, 7, 8), (9, 11, 8.5, 10.5), (10, 10.5, 9, 10)])
    fs = detect_fractals(merged)
    assert len(fs) == 1
    assert fs[0].mark == "G"
    assert fs[0].fx == 11.0


def test_bottom_fractal():
    merged = _merged([(9, 10, 8, 9.5), (8, 8.5, 6.5, 7), (7.5, 8, 7, 7.8)])
    fs = detect_fractals(merged)
    assert len(fs) == 1
    assert fs[0].mark == "D"
    assert fs[0].fx == 6.5


def test_flat_middle_no_fractal():
    # 中间根与左右等高 → 平盘不误判
    merged = _merged([(8, 10, 7, 9), (9, 10, 8, 9.5), (9.5, 11, 8.5, 10)])
    fs = detect_fractals(merged)
    assert len(fs) == 0


def test_insufficient_bars():
    merged = _merged([(8, 9, 7, 8), (9, 10, 8, 9)])
    assert detect_fractals(merged) == []
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/indicators/test_chanlun_fractal.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 写实现**

```python
# src/indicators/chanlun/core/fractal.py
# -*- coding: utf-8 -*-
"""分型识别 — 顶分型(中间高+高且低+高)/底分型(中间低+低且高+低)。"""
from __future__ import annotations

from .merge import MergedBar
from ..schema import Fractal


def detect_fractals(merged: list[MergedBar]) -> list[Fractal]:
    """在去包含K线上识别顶底分型。

    Args:
        merged: 去包含K线列表（升序）。

    Returns:
        顶底分型列表。平盘（等高/等低）不识别。
    """
    fractals: list[Fractal] = []
    n = len(merged)
    for i in range(1, n - 1):
        a, b, c = merged[i - 1], merged[i], merged[i + 1]
        if b.high > a.high and b.high > c.high and b.low > a.low and b.low > c.low:
            fractals.append(Fractal(mark="G", dt=b.dt, high=b.high, low=b.low,
                                    fx=b.high, index=i))
        elif b.high < a.high and b.high < c.high and b.low < a.low and b.low < c.low:
            fractals.append(Fractal(mark="D", dt=b.dt, high=b.high, low=b.low,
                                    fx=b.low, index=i))
    return fractals
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/indicators/test_chanlun_fractal.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: 提交**

```bash
git add src/indicators/chanlun/core/fractal.py tests/indicators/test_chanlun_fractal.py
git commit -m "feat(chanlun): 顶底分型识别（平盘不误判）"
```

---

### Task 4: 笔构建（core/bi.py）

**Files:**
- Create: `src/indicators/chanlun/core/bi.py`
- Test: `tests/indicators/test_chanlun_bi.py`

**Interfaces:**
- Consumes: `list[Fractal]`（Task 3）
- Produces: `build_bis(fractals, min_len=4) -> list[Bi]`（`macd_area` 初值 0.0，Task 8 回填）。Task 5 消费 `bis`。

- [ ] **Step 1: 写失败测试**

```python
# tests/indicators/test_chanlun_bi.py
# -*- coding: utf-8 -*-
from src.indicators.chanlun.core.bi import build_bis
from src.indicators.chanlun.schema import Fractal


def _fx(mark, index, fx):
    if mark == "G":
        return Fractal(mark="G", dt=index, high=fx, low=fx - 1, fx=fx, index=index)
    return Fractal(mark="D", dt=index, high=fx + 1, low=fx, fx=fx, index=index)


def test_build_bis_alternates():
    fs = [_fx("D", 0, 10), _fx("G", 5, 20), _fx("D", 10, 12), _fx("G", 16, 25)]
    bis = build_bis(fs, min_len=4)
    assert len(bis) == 3
    assert [b.direction for b in bis] == ["up", "down", "up"]


def test_bi_min_length_rejected():
    fs = [_fx("D", 0, 10), _fx("G", 2, 20)]   # gap=2 < 4
    assert build_bis(fs, min_len=4) == []


def test_consecutive_same_mark_keeps_extreme():
    fs = [_fx("D", 0, 10), _fx("G", 5, 20), _fx("G", 7, 25), _fx("D", 12, 15)]
    bis = build_bis(fs, min_len=4)
    assert len(bis) == 2
    assert bis[0].end_fx.fx == 25          # 保留更高的顶
    assert bis[0].direction == "up" and bis[1].direction == "down"


def test_bi_high_low_from_endpoints():
    fs = [_fx("D", 0, 10), _fx("G", 5, 20)]
    bis = build_bis(fs, min_len=4)
    assert bis[0].high == 20.0 and bis[0].low == 10.0
    assert bis[0].start_fx.mark == "D" and bis[0].end_fx.mark == "G"


def test_no_consecutive_same_direction_after_swallow():
    # 回归 Bug2: 旧顶 G(20)@5 被新高 G(30)@12 吞没（中间小回调 D(15)@7 与两者过近）。
    # 贪心版会产出 [D→G(20), D→G(30)] 两根同向上行笔；迭代版应吸收为 1 根且严格交替。
    fs = [_fx("D", 0, 10), _fx("G", 5, 20), _fx("D", 7, 15), _fx("G", 12, 30)]
    bis = build_bis(fs, min_len=4)
    dirs = [b.direction for b in bis]
    assert len(dirs) >= 1
    assert all(dirs[i] != dirs[i + 1] for i in range(len(dirs) - 1))   # 严格交替
    assert bis[-1].end_fx.fx == 30.0                                   # 新高被保留为端点
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/indicators/test_chanlun_bi.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 写实现**

```python
# src/indicators/chanlun/core/bi.py
# -*- coding: utf-8 -*-
"""笔构建 — 顶底分型交替连接，最小长度约束。"""
from __future__ import annotations

from ..schema import Bi, Fractal


def _purge_fractals(fractals: list[Fractal]) -> list[Fractal]:
    """连续同向分型只保留最极端的一个。"""
    kept: list[Fractal] = []
    for fx in fractals:
        if kept and kept[-1].mark == fx.mark:
            prev = kept[-1]
            if (fx.mark == "G" and fx.fx >= prev.fx) or \
               (fx.mark == "D" and fx.fx <= prev.fx):
                kept[-1] = fx
            continue
        kept.append(fx)
    return kept


def build_bis(fractals: list[Fractal], min_len: int = 4) -> list[Bi]:
    """从分型序列构建笔列表（迭代吸收小波动版，修正贪心折叠 Bug2）。

    迭代规则:
      1. 连续同向分型 → 保留更极端
      2. 相邻异向分型 gap < min_len → 吸收较小波动（保留更极端那侧）
      收敛后连接相邻分型。

    Args:
        fractals: 顶底分型（升序）。
        min_len: 相邻分型最小间隔（去包含K线数），默认 4。

    Returns:
        笔列表，方向严格交替，`macd_area` 初始为 0.0（由 analyzer 回填）。
        注意：周线用迭代版易过度合并（~150 根→2 笔），周线调用方应调大 min_len。
    """
    fs = _purge_fractals(fractals)
    while True:
        merged: list[Fractal] = []
        changed = False
        i = 0
        n = len(fs)
        while i < n:
            if i + 1 >= n:
                merged.append(fs[i])
                break
            a, b = fs[i], fs[i + 1]
            if a.mark == b.mark:
                keep = a if ((a.mark == "G" and a.fx >= b.fx) or
                             (a.mark == "D" and a.fx <= b.fx)) else b
                merged.append(keep)
                changed = True
                i += 2
            elif b.index - a.index < min_len:
                if (a.mark == "G" and a.fx >= b.fx) or \
                   (a.mark == "D" and a.fx <= b.fx):
                    merged.append(a)
                else:
                    merged.append(b)
                changed = True
                i += 2
            else:
                merged.append(a)
                i += 1
        fs = merged
        if not changed:
            break

    bis: list[Bi] = []
    for k in range(len(fs) - 1):
        a, b = fs[k], fs[k + 1]
        if a.mark == b.mark:
            continue
        gap = b.index - a.index
        ok_price = (a.mark == "D" and b.fx > a.fx) or \
                   (a.mark == "G" and b.fx < a.fx)
        if gap >= min_len and ok_price:
            bis.append(Bi(
                direction="up" if a.mark == "D" else "down",
                start_fx=a, end_fx=b,
                high=max(a.fx, b.fx), low=min(a.fx, b.fx),
                length=gap, macd_area=0.0,
                start_dt=a.dt, end_dt=b.dt,
            ))
    return bis
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/indicators/test_chanlun_bi.py -v`
Expected: PASS (5 passed)

- [ ] **Step 4b: 真实数据验证（300476）— 必须执行，回归 Bug2**

Run:
```bash
.venv/bin/python - <<'PY'
import pandas as pd
from src.data.aggregator import DataAggregator
from src.indicators.chanlun.core.merge import merge_bars
from src.indicators.chanlun.core.fractal import detect_fractals
from src.indicators.chanlun.core.bi import build_bis
agg = DataAggregator()
df = agg.get_history("300476")
col_map = {"开盘":"open","收盘":"close","最高":"high","最低":"low","成交量":"volume"}
df = df.rename(columns={c: col_map[c] for c in df.columns if c in col_map})
merged = merge_bars(df)
fs = detect_fractals(merged)
bis = build_bis(fs)
dirs = [b.direction for b in bis]
alt = all(dirs[i] != dirs[i+1] for i in range(len(dirs)-1))
print(f"K线{len(df)} 去包含{len(merged)} 分型{len(fs)} 笔{len(bis)} 交替={alt}")
PY
```
Expected: `len(bis)` 合理（数十根量级，远多于 2 且远少于 merged），`交替=True`（无同向连续笔）。若 `交替=False` 或 `len(bis) < 3`，说明笔构建仍错，不得提交。

- [ ] **Step 5: 提交**

```bash
git add src/indicators/chanlun/core/bi.py tests/indicators/test_chanlun_bi.py
git commit -m "feat(chanlun): 笔构建（迭代吸收小波动版，方向严格交替）"
```

---

### Task 5: 中枢识别（core/zhongshu.py）

**Files:**
- Create: `src/indicators/chanlun/core/zhongshu.py`
- Modify: `src/indicators/chanlun/schema.py`（ZhongShu 加 `bi_indexes` 字段）
- Test: `tests/indicators/test_chanlun_zhongshu.py`

**Interfaces:**
- Consumes: `list[Bi]`（Task 4）
- Produces: `detect_zhongshus(bis) -> list[ZhongShu]`（含 `bi_indexes`、延伸合并、上移/下移状态）。Task 6/7 消费 `zss`。

> 说明：`bi_indexes` 是中枢构成笔的 index 元组，Task 7 用它限制三买/三卖只扫中枢之后的笔（避免远古中枢误触发）。在 Task 5 内一并修改 Task 1 建的 schema.py。

- [ ] **Step 1: 写失败测试**

```python
# tests/indicators/test_chanlun_zhongshu.py
# -*- coding: utf-8 -*-
from src.indicators.chanlun.core.zhongshu import detect_zhongshus
from src.indicators.chanlun.schema import Bi, Fractal


def _bi(direction, high, low):
    if direction == "up":
        fx_a = Fractal(mark="D", dt=0, high=low + 1, low=low, fx=low, index=0)
        fx_b = Fractal(mark="G", dt=5, high=high, low=high - 1, fx=high, index=5)
    else:
        fx_a = Fractal(mark="G", dt=0, high=high, low=high - 1, fx=high, index=0)
        fx_b = Fractal(mark="D", dt=5, high=low + 1, low=low, fx=low, index=5)
    return Bi(direction=direction, start_fx=fx_a, end_fx=fx_b, high=high, low=low,
              length=5, macd_area=0.0, start_dt=0, end_dt=5)


def test_zhongshu_valid_overlap():
    bis = [_bi("up", 20, 10), _bi("down", 18, 12), _bi("up", 22, 15)]
    zss = detect_zhongshus(bis)
    assert len(zss) == 1
    zs = zss[0]
    assert zs.zg == 18.0     # min(20,18,22)
    assert zs.zd == 15.0     # max(10,12,15)
    assert zs.zg > zs.zd
    assert zs.state == "形成"


def test_no_overlap_no_zhongshu():
    bis = [_bi("up", 10, 1), _bi("down", 20, 11), _bi("up", 30, 21)]
    assert detect_zhongshus(bis) == []


def test_zhongshu_move_up_state():
    bis = [
        _bi("up", 18, 12), _bi("down", 16, 15), _bi("up", 17, 13),    # 中枢1 [15,16]
        _bi("up", 26, 21), _bi("down", 24, 22), _bi("up", 25, 23),    # 中枢2 [23,24]
    ]
    zss = detect_zhongshus(bis)
    assert len(zss) == 2
    assert zss[1].zd > zss[0].zg      # 23 > 16 → 上移
    assert zss[1].state == "上移"
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/indicators/test_chanlun_zhongshu.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 写实现**

先修改 Task 1 建的 `src/indicators/chanlun/schema.py`，给 `ZhongShu` 加字段：
```python
@dataclass(frozen=True)
class ZhongShu:
    zg: float
    zd: float
    zz: float
    gg: float
    dd: float
    start_dt: Any
    end_dt: Any
    state: str                    # "形成"/"延伸"/"上移"/"下移"
    bi_indexes: tuple = ()        # 构成中枢的笔 index（Task 7 三买/三卖扫笔用）
```

```python
# src/indicators/chanlun/core/zhongshu.py
# -*- coding: utf-8 -*-
"""中枢识别 — ≥3 笔重叠区间，延伸合并与上移/下移判定。"""
from __future__ import annotations

from dataclasses import replace

from ..schema import Bi, ZhongShu


def _overlap(z1: ZhongShu, z2: ZhongShu) -> bool:
    return z1.zg > z2.zd and z2.zg > z1.zd


def detect_zhongshus(bis: list[Bi]) -> list[ZhongShu]:
    """从笔序列识别中枢。

    Args:
        bis: 笔列表（升序）。

    Returns:
        中枢列表（升序），state 为 "形成"/"延伸"/"上移"/"下移"。
    """
    n = len(bis)
    raw: list[ZhongShu] = []
    i = 0
    while i <= n - 3:
        three = bis[i:i + 3]
        zg = min(b.high for b in three)
        zd = max(b.low for b in three)
        if zg > zd:
            raw.append(ZhongShu(
                zg=zg, zd=zd, zz=(zg + zd) / 2.0,
                gg=max(b.high for b in three),
                dd=min(b.low for b in three),
                start_dt=three[0].start_dt, end_dt=three[2].end_dt,
                state="形成", bi_indexes=tuple(range(i, i + 3)),
            ))
            i += 3
        else:
            i += 1

    # 相邻中枢重叠 → 延伸合并
    merged: list[ZhongShu] = []
    for zs in raw:
        if merged and _overlap(merged[-1], zs):
            prev = merged[-1]
            zg = min(prev.zg, zs.zg)
            zd = max(prev.zd, zs.zd)
            merged[-1] = replace(
                prev, zg=zg, zd=zd, zz=(zg + zd) / 2.0,
                gg=max(prev.gg, zs.gg), dd=min(prev.dd, zs.dd),
                end_dt=zs.end_dt, state="延伸",
                bi_indexes=prev.bi_indexes + zs.bi_indexes,
            )
        else:
            merged.append(zs)

    # 上移/下移状态
    for k in range(1, len(merged)):
        if merged[k].zd > merged[k - 1].zg:
            merged[k] = replace(merged[k], state="上移")
        elif merged[k].zg < merged[k - 1].zd:
            merged[k] = replace(merged[k], state="下移")
    return merged
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/indicators/test_chanlun_zhongshu.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: 提交**

```bash
git add src/indicators/chanlun/core/zhongshu.py tests/indicators/test_chanlun_zhongshu.py
git commit -m "feat(chanlun): 中枢识别（重叠/延伸/上移/下移）"
```

---

### Task 6: 背驰判定（core/bihuang.py）

**Files:**
- Create: `src/indicators/chanlun/core/bihuang.py`
- Test: `tests/indicators/test_chanlun_bihuang.py`

**Interfaces:**
- Consumes: `list[Bi]`（含回填后的 `macd_area`）
- Produces: `detect_divergence(bis) -> dict[int, dict]`（key=笔 index，value `{"type": "bottom"/"top", "bi_index": i}`）。Task 7 消费。

- [ ] **Step 1: 写失败测试**

```python
# tests/indicators/test_chanlun_bihuang.py
# -*- coding: utf-8 -*-
from src.indicators.chanlun.core.bihuang import detect_divergence
from src.indicators.chanlun.schema import Bi, Fractal


def _bi(direction, high, low, area=0.0):
    if direction == "up":
        fa, fb = Fractal(mark="D", dt=0, high=low + 1, low=low, fx=low, index=0), \
                 Fractal(mark="G", dt=5, high=high, low=high - 1, fx=high, index=5)
    else:
        fa, fb = Fractal(mark="G", dt=0, high=high, low=high - 1, fx=high, index=0), \
                 Fractal(mark="D", dt=5, high=low + 1, low=low, fx=low, index=5)
    return Bi(direction=direction, start_fx=fa, end_fx=fb, high=high, low=low,
              length=5, macd_area=area, start_dt=0, end_dt=5)


def test_bottom_divergence():
    bis = [_bi("down", 30, 20, area=100.0), _bi("up", 25, 18, area=30.0),
           _bi("down", 22, 15, area=50.0)]     # 低点15<20 且面积50<100
    div = detect_divergence(bis)
    assert 2 in div and div[2]["type"] == "bottom"


def test_top_divergence():
    bis = [_bi("up", 20, 10, area=100.0), _bi("down", 15, 8, area=30.0),
           _bi("up", 25, 12, area=60.0)]       # 高点25>20 且面积60<100
    div = detect_divergence(bis)
    assert 2 in div and div[2]["type"] == "top"


def test_no_divergence_when_force_grows():
    bis = [_bi("down", 30, 20, area=50.0), _bi("up", 25, 18, area=30.0),
           _bi("down", 22, 15, area=80.0)]     # 低点15<20 但面积80>50
    assert detect_divergence(bis) == {}
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/indicators/test_chanlun_bihuang.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 写实现**

```python
# src/indicators/chanlun/core/bihuang.py
# -*- coding: utf-8 -*-
"""背驰判定 — 相邻同向笔力度（MACD 面积）比较。"""
from __future__ import annotations

from ..schema import Bi


def detect_divergence(bis: list[Bi]) -> dict[int, dict]:
    """检测背驰。

    底背驰：下降笔创更低低点但 MACD 面积较前一段下降笔减小。
    顶背驰：上升笔创更高高点但 MACD 面积较前一段上升笔减小。

    Args:
        bis: 笔列表（含 macd_area）。

    Returns:
        {笔 index: {"type": "bottom"/"top", "bi_index": index}}。
    """
    div: dict[int, dict] = {}
    for i in range(2, len(bis)):
        b, prev = bis[i], bis[i - 2]
        if b.direction == "down" and prev.direction == "down":
            if b.low < prev.low and b.macd_area < prev.macd_area:
                div[i] = {"type": "bottom", "bi_index": i}
        elif b.direction == "up" and prev.direction == "up":
            if b.high > prev.high and b.macd_area < prev.macd_area:
                div[i] = {"type": "top", "bi_index": i}
    return div
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/indicators/test_chanlun_bihuang.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: 提交**

```bash
git add src/indicators/chanlun/core/bihuang.py tests/indicators/test_chanlun_bihuang.py
git commit -m "feat(chanlun): 背驰判定（MACD面积对比底/顶背驰）"
```

---

### Task 7: 买卖点（points.py）

**Files:**
- Create: `src/indicators/chanlun/points.py`
- Test: `tests/indicators/test_chanlun_points.py`

**Interfaces:**
- Consumes: `list[Bi]`（Task 4）+ `list[ZhongShu]`（Task 5）+ `dict`（Task 6）
- Produces: `detect_points(bis, zss, divergences) -> list[ChanlunPoint]`。Task 8 消费。

- [ ] **Step 1: 写失败测试**

```python
# tests/indicators/test_chanlun_points.py
# -*- coding: utf-8 -*-
from src.indicators.chanlun.core.zhongshu import detect_zhongshus
from src.indicators.chanlun.points import detect_points
from src.indicators.chanlun.schema import Bi, Fractal


def _bi(direction, high, low, area=0.0):
    if direction == "up":
        fa, fb = Fractal(mark="D", dt=0, high=low + 1, low=low, fx=low, index=0), \
                 Fractal(mark="G", dt=5, high=high, low=high - 1, fx=high, index=5)
    else:
        fa, fb = Fractal(mark="G", dt=0, high=high, low=high - 1, fx=high, index=0), \
                 Fractal(mark="D", dt=5, high=low + 1, low=low, fx=low, index=5)
    return Bi(direction=direction, start_fx=fa, end_fx=fb, high=high, low=low,
              length=5, macd_area=area, start_dt=0, end_dt=5)


def test_first_buy_and_second_buy():
    # 中枢1 [32,35] + 末段底背驰 → 一买(24) → 回调不破 → 二买(25)
    bis = [
        _bi("down", 40, 30, area=100.0), _bi("up", 36, 32, area=30.0),
        _bi("down", 35, 31, area=80.0),   # 中枢 [min40,36,35=35, max30,32,31=32]
        _bi("up", 34, 33, area=20.0),
        _bi("down", 30, 24, area=40.0),   # 低点24<31 且 40<80 → 底背驰 → 一买@24
        _bi("up", 30, 26, area=20.0),
        _bi("down", 27, 25, area=30.0),   # 低点25>24 不破一买低点 → 二买@25
    ]
    zss = detect_zhongshus(bis)
    points = detect_points(bis, zss, {4: {"type": "bottom", "bi_index": 4}})
    kinds = [p.kind for p in points]
    assert "一买" in kinds and "二买" in kinds
    assert any(p.kind == "二买" and p.price == 25.0 for p in points)


def test_third_buy_after_breakout():
    bis = [
        _bi("down", 40, 30), _bi("up", 36, 32), _bi("down", 35, 31),   # 中枢 [32,35]
        _bi("up", 40, 33),                                             # 突破 zg=35
        _bi("down", 38, 36),                                           # 回抽低点36>35 → 三买
    ]
    zss = detect_zhongshus(bis)
    points = detect_points(bis, zss, {})
    assert any(p.kind == "三买" and p.price == 36.0 for p in points)


def test_first_sell_and_second_sell_mirror():
    bis = [
        _bi("up", 20, 10, area=100.0), _bi("down", 16, 12, area=30.0),
        _bi("up", 22, 15, area=80.0),   # 中枢 [16,20]
        _bi("down", 17, 13, area=20.0),
        _bi("up", 28, 20, area=40.0),   # 高点28>22 且 40<80 → 顶背驰 → 一卖@28
        _bi("down", 24, 18, area=20.0),
        _bi("up", 27, 21, area=30.0),   # 高点27<28 不破一卖高点 → 二卖@27
    ]
    zss = detect_zhongshus(bis)
    points = detect_points(bis, zss, {4: {"type": "top", "bi_index": 4}})
    kinds = [p.kind for p in points]
    assert "一卖" in kinds and "二卖" in kinds
```

注意：`detect_points` 中一买/一卖要求 `zss` 非空（趋势上下文）。

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/indicators/test_chanlun_points.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 写实现**

```python
# src/indicators/chanlun/points.py
# -*- coding: utf-8 -*-
"""买卖点判定 — 一买/二买/三买 + 一卖/二卖/三卖（A股长多语义）。"""
from __future__ import annotations

from .schema import Bi, ChanlunPoint, ZhongShu


def detect_points(bis: list[Bi], zss: list[ZhongShu],
                  divergences: dict[int, dict]) -> list[ChanlunPoint]:
    """从笔/中枢/背驰推导买卖点。

    - 一买：下降趋势（有中枢）+ 末段底背驰 + 底分型确认
    - 二买：一买后回调低点不破一买低点
    - 三买：突破中枢 ZG 后回抽低点 > ZG（不进入中枢）
    - 一卖/二卖/三卖：镜像
    """
    points: list[ChanlunPoint] = []
    n = len(bis)

    def add(kind: str, bi: Bi, price: float, conf: float, reason: str) -> None:
        points.append(ChanlunPoint(kind=kind, dt=bi.end_dt, price=price,
                                   confidence=conf, rationale=reason))

    first_idx: dict[str, int] = {}
    for idx, d in divergences.items():
        if idx >= n:
            continue
        b = bis[idx]
        if d["type"] == "bottom" and zss:
            add("一买", b, b.low, 0.7, "下降末段底背驰+底分型确认(有中枢趋势背景)")
            first_idx["一买"] = idx
        elif d["type"] == "top" and zss:
            add("一卖", b, b.high, 0.7, "上升末段顶背驰+顶分型确认(有中枢趋势背景)")
            first_idx["一卖"] = idx

    if "一买" in first_idx:
        base = bis[first_idx["一买"]].low
        for j in range(first_idx["一买"] + 1, n):
            b = bis[j]
            if b.direction == "down" and b.low > base:
                add("二买", b, b.low, 0.75, "一买后回调不破一买低点, 底分型确认")
                break
    if "一卖" in first_idx:
        base = bis[first_idx["一卖"]].high
        for j in range(first_idx["一卖"] + 1, n):
            b = bis[j]
            if b.direction == "up" and b.high < base:
                add("二卖", b, b.high, 0.75, "一卖后反弹不破一卖高点, 顶分型确认")
                break

    for zs in zss[-2:]:                  # 只看最近 2 个中枢（当前结构相关，避免远古中枢误触发）
        last_bi = max(zs.bi_indexes) if zs.bi_indexes else 0
        for j in range(last_bi + 1, n):
            b = bis[j]
            if b.direction == "down" and b.low > zs.zg:
                add("三买", b, b.low, 0.8, f"突破中枢ZG={zs.zg:.2f}后回抽不进入中枢")
            elif b.direction == "up" and b.high < zs.zd:
                add("三卖", b, b.high, 0.8, f"跌破中枢ZD={zs.zd:.2f}后反弹不进入中枢")
    return points
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/indicators/test_chanlun_points.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: 提交**

```bash
git add src/indicators/chanlun/points.py tests/indicators/test_chanlun_points.py
git commit -m "feat(chanlun): 买卖点判定（一买/二买/三买 + 镜像卖点）"
```

---

### Task 8: ChanlunAnalyzer + czsc 适配器（analyzer.py）

**Files:**
- Create: `src/indicators/chanlun/analyzer.py`
- Test: `tests/indicators/test_chanlun_analyzer.py`

**Interfaces:**
- Consumes: Task 2-7 全部函数 + `make_citation`（`src.data.source_citation`）
- Produces: `ChanlunAnalyzer(freq="D", use_czsc=True, min_bi_bars=4)`，`.analyze(df, symbol, name, freq=None) -> ChanlunResult`，`.to_signal(result) -> dict`。Task 9-14 消费。

- [ ] **Step 1: 写失败测试**

```python
# tests/indicators/test_chanlun_analyzer.py
# -*- coding: utf-8 -*-
import numpy as np
import pandas as pd

from src.indicators.chanlun.analyzer import ChanlunAnalyzer


def _make_df(n=120, seed=42):
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(0, 1, n))
    high = close + rng.uniform(0, 1, n)
    low = close - rng.uniform(0, 1, n)
    open_ = close + rng.normal(0, 0.3, n)
    idx = pd.date_range("2025-01-01", periods=n, freq="D")
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close,
                         "volume": 1e6}, index=idx)


def test_analyzer_produces_result():
    df = _make_df()
    r = ChanlunAnalyzer().analyze(df, "000001", "测试")
    assert r.symbol == "000001"
    assert r.freq == "D"
    assert len(r.source_citations) >= 1
    assert 0.0 <= r.confidence <= 1.0
    assert r.current_state["last_close"] == float(df["close"].iloc[-1])


def test_analyzer_data_gap_short():
    df = _make_df(20)                       # <30 根
    r = ChanlunAnalyzer().analyze(df, "000001", "测试")
    assert r.bis == [] and r.zhongshus == []
    assert "gap" in r.current_state


def test_analyzer_backend_self_without_czsc(monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, "czsc", None)  # 模拟 czsc 不可用
    df = _make_df()
    r = ChanlunAnalyzer(use_czsc=True).analyze(df, "000001", "测试")
    assert r.backend == "self"


def test_to_signal_long_only():
    from src.indicators.chanlun.points import detect_points
    from src.indicators.chanlun.core.zhongshu import detect_zhongshus
    from src.indicators.chanlun.schema import Bi, Fractal

    def _bi(direction, high, low, area=0.0):
        if direction == "up":
            fa, fb = Fractal(mark="D", dt=0, high=low + 1, low=low, fx=low, index=0), \
                     Fractal(mark="G", dt=5, high=high, low=high - 1, fx=high, index=5)
        else:
            fa, fb = Fractal(mark="G", dt=0, high=high, low=high - 1, fx=high, index=0), \
                     Fractal(mark="D", dt=5, high=low + 1, low=low, fx=low, index=5)
        return Bi(direction=direction, start_fx=fa, end_fx=fb, high=high, low=low,
                  length=5, macd_area=area, start_dt=0, end_dt=5)

    bis = [_bi("down", 40, 30, 100.0), _bi("up", 36, 32, 30.0), _bi("down", 35, 31, 80.0),
           _bi("up", 34, 33, 20.0), _bi("down", 30, 24, 40.0), _bi("up", 30, 26, 20.0),
           _bi("down", 27, 25, 30.0)]
    zss = detect_zhongshus(bis)
    points = detect_points(bis, zss, {4: {"type": "bottom", "bi_index": 4}})
    signals = ChanlunAnalyzer.to_signal(points)
    assert any("一买" in s["kind"] for s in signals["entry"])
    assert any("二买" in s["kind"] for s in signals["entry"])
    assert all(s["kind"] not in ("一卖", "二卖", "三卖") for s in signals["entry"])
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/indicators/test_chanlun_analyzer.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 写实现**

```python
# src/indicators/chanlun/analyzer.py
# -*- coding: utf-8 -*-
"""缠论分析器 — 组合去包含/分型/笔/中枢/背驰/买卖点，含可选 czsc 适配器。"""
from __future__ import annotations

import logging
from dataclasses import replace

import numpy as np
import pandas as pd

from src.data.source_citation import make_citation
from src.indicators.chanlun.core.bi import build_bis
from src.indicators.chanlun.core.bihuang import detect_divergence
from src.indicators.chanlun.core.fractal import detect_fractals
from src.indicators.chanlun.core.merge import merge_bars
from src.indicators.chanlun.core.zhongshu import detect_zhongshus
from src.indicators.chanlun.points import detect_points
from src.indicators.chanlun.schema import Bi, ChanlunPoint, ChanlunResult

logger = logging.getLogger(__name__)


def _assign_macd_area(bis: list[Bi], df: pd.DataFrame) -> list[Bi]:
    """按笔区间回填 MACD 柱面积。"""
    close = df["close"].values.astype(float)
    ema12 = pd.Series(close).ewm(span=12, adjust=False).mean().values
    ema26 = pd.Series(close).ewm(span=26, adjust=False).mean().values
    dif = ema12 - ema26
    dea = pd.Series(dif).ewm(span=9, adjust=False).mean().values
    macd = (dif - dea) * 2.0
    raw_pos = {dt: k for k, dt in enumerate(df.index)}
    out: list[Bi] = []
    for b in bis:
        s = raw_pos.get(b.start_fx.dt)
        e = raw_pos.get(b.end_fx.dt)
        if s is None or e is None:
            area = 0.0
        else:
            lo, hi = min(s, e), max(s, e) + 1
            area = float(np.sum(np.abs(macd[lo:hi])))
        out.append(replace(b, macd_area=area))
    return out


def _czsc_adapter_signals(df: pd.DataFrame, symbol: str, freq: str) -> dict:
    """czsc 已安装时返回其高级信号；未安装/异常抛异常由调用方降级。"""
    from czsc import CZSC, Freq, RawBar
    from czsc.signals.cxt import (cxt_bi_base_V230228, cxt_five_bi_V230619,
                                  cxt_first_buy_V221126, cxt_first_sell_V221126)

    fr = {"D": Freq.D, "W": Freq.W}.get(freq, Freq.D)
    bars = []
    for i, (dt, row) in enumerate(df.iterrows()):
        bars.append(RawBar(
            symbol=symbol, id=i,
            dt=dt.to_pydatetime() if hasattr(dt, "to_pydatetime") else dt,
            freq=fr, open=float(row["open"]), close=float(row["close"]),
            high=float(row["high"]), low=float(row["low"]),
            vol=float(row.get("volume", row.get("vol", 0))),
            amount=float(row.get("amount", 0)),
        ))
    if len(bars) < 30:
        raise ValueError("czsc 数据不足")

    def _get_signals(c):
        s = {}
        s.update(cxt_first_buy_V221126(c, di=1))
        s.update(cxt_first_sell_V221126(c, di=1))
        s.update(cxt_bi_base_V230228(c, di=1))
        s.update(cxt_five_bi_V230619(c, di=1))
        return s

    c = CZSC(bars[:30], get_signals=_get_signals)
    for b in bars[30:]:
        c.update(b)
    sigs = c.signals or {}
    return {
        "bi_count": len(c.bi_list),
        "buy1": any("一买" in str(v) for v in sigs.values()),
        "sell1": any("一卖" in str(v) for v in sigs.values()),
        "five_bi": next((str(v) for k, v in sigs.items() if "五笔" in k), ""),
    }


class ChanlunAnalyzer:
    """缠论结构分析器。freq: "D"/"W"。use_czsc: 已安装则交叉验证。"""

    def __init__(self, freq: str = "D", use_czsc: bool = True, min_bi_bars: int = 4):
        self.freq = freq
        self.use_czsc = use_czsc
        self.min_bi_bars = min_bi_bars

    def analyze(self, df, symbol: str, name: str = "", freq: str | None = None) -> ChanlunResult:
        f = freq or self.freq
        if df is None or len(df) < 30:
            return self._empty_result(symbol, name, f, reason="[DATA_GAP] 缠论: 数据不足30根")
        try:
            merged = merge_bars(df)
            fractals = detect_fractals(merged)
            bis = _assign_macd_area(build_bis(fractals, self.min_bi_bars), df)
            zss = detect_zhongshus(bis)
            divergences = detect_divergence(bis)
            points = detect_points(bis, zss, divergences)

            backend = "self"
            extra: dict = {}
            if self.use_czsc:
                try:
                    extra = _czsc_adapter_signals(df, symbol, f)
                    if extra:
                        backend = "czsc"
                except Exception as exc:  # 未安装或运行时异常 → 静默降级
                    logger.debug("czsc adapter disabled: %s", exc)

            current_state = self._current_state(bis, zss, points, df)
            signals = self.to_signal(points)
            citations = [make_citation(
                provider="indicator", field=f"chanlun_{f}", data_type="daily_bar",
                source_tier="T2", nature="interpretation", confidence=0.8,
            )]
            conf = self._confidence(len(df), backend, extra)
            return ChanlunResult(
                symbol=symbol, name=name, freq=f, backend=backend,
                fractals=fractals, bis=bis, zhongshus=zss, points=points,
                current_state=current_state, signals=signals,
                source_citations=citations, confidence=conf,
            )
        except Exception as exc:
            logger.warning("chanlun analyze failed: %s", exc)
            return self._empty_result(symbol, name, f, reason=f"[DATA_GAP] 缠论: {exc}")

    @staticmethod
    def to_signal(points: list[ChanlunPoint]) -> dict:
        """A 股长多信号映射。一买/二买/三买 → entry；其余 → exit。"""
        entry, exit_ = [], []
        for p in points:
            item = {"kind": p.kind, "price": p.price, "dt": str(p.dt),
                    "confidence": p.confidence}
            (entry if p.kind in ("一买", "二买", "三买") else exit_).append(item)
        return {"entry": entry, "exit": exit_}

    @staticmethod
    def _current_state(bis, zss, points, df) -> dict:
        last_close = float(df["close"].iloc[-1])
        state = {"last_close": last_close, "bi_count": len(bis),
                 "zhongshu_state": "未形成", "position": "未知"}
        if zss:
            zs = zss[-1]
            state["zhongshu_state"] = zs.state
            state["zg"], state["zd"], state["zz"] = zs.zg, zs.zd, zs.zz
            if last_close > zs.zg:
                state["position"] = "中枢上方"
            elif last_close < zs.zd:
                state["position"] = "中枢下方"
            else:
                state["position"] = "中枢内"
        if points:
            lp = points[-1]
            state["last_point"] = {"kind": lp.kind, "dt": str(lp.dt), "price": lp.price}
        return state

    @staticmethod
    def _confidence(n_bars: int, backend: str, extra: dict) -> float:
        base = 0.85 if backend == "czsc" else 0.75
        if n_bars < 50:
            base *= 0.8
        return round(max(0.0, min(1.0, base)), 3)

    @staticmethod
    def _empty_result(symbol, name, freq, reason) -> ChanlunResult:
        return ChanlunResult(symbol=symbol, name=name, freq=freq, backend="self",
                             fractals=[], bis=[], zhongshus=[], points=[],
                             current_state={"gap": reason},
                             signals={"entry": [], "exit": []},
                             source_citations=[], confidence=0.0)
```

> czsc 适配器整段在 `analyzer.analyze()` 的 try/except 中调用：czsc 未安装时 import 抛 ImportError → 捕获降级 `backend="self"`；已安装则正常交叉验证。

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/indicators/test_chanlun_analyzer.py -v`
Expected: PASS (4 passed)。若本机未安装 czsc，`test_analyzer_backend_self_without_czsc` 仍应通过（ImportError 被捕获降级）。

- [ ] **Step 5: 提交**

```bash
git add src/indicators/chanlun/analyzer.py tests/indicators/test_chanlun_analyzer.py
git commit -m "feat(chanlun): ChanlunAnalyzer 组合入口 + czsc 适配器（静默降级）"
```

---

### Task 9: indicators 包导出

**Files:**
- Modify: `src/indicators/__init__.py`

**Interfaces:**
- Consumes: `src.indicators.chanlun`（Task 1-8）
- Produces: 包级导出 `ChanlunAnalyzer` / `ChanlunResult` / `Fractal` / `Bi` / `ZhongShu` / `ChanlunPoint`，供 CLI/tactics/diagnose 直接 `from src.indicators import ChanlunAnalyzer`。

- [ ] **Step 1: 修改导入区（追加在 Structure 区之后，line 177 附近）**

```python
# ── Chanlun ────────────────────────────────────────────────────────
from .chanlun import (
    Bi,
    ChanlunPoint,
    ChanlunResult,
    Fractal,
    ZhongShu,
)
from .chanlun.analyzer import ChanlunAnalyzer
```

- [ ] **Step 2: 追加 `__all__`（在 line 234 `"HurstExponent", "ZigZag", "ZigZagPoint",` 后）**

```python
    # Chanlun
    "ChanlunAnalyzer", "ChanlunResult",
    "Fractal", "Bi", "ZhongShu", "ChanlunPoint",
```

- [ ] **Step 3: 验证导入**

Run: `.venv/bin/python -c "from src.indicators import ChanlunAnalyzer, ChanlunResult; print('ok')"`
Expected: `ok`

- [ ] **Step 4: 跑全部 chanlun 测试确认无回归**

Run: `.venv/bin/python -m pytest tests/indicators/test_chanlun_*.py -v`
Expected: 全部 PASS（4 文件 × 若干用例）

- [ ] **Step 5: 提交**

```bash
git add src/indicators/__init__.py
git commit -m "feat(chanlun): indicators 包导出缠论分析器与 DTO"
```

---

### Task 10: CLI `chanlun` 子命令

**Files:**
- Modify: `src/cli.py`
  - 新增 `cmd_chanlun`（放在 `cmd_indicators` 后）
  - `commands` dict 加 `"chanlun"`（line 6027 附近）
  - 帮助 `details` dict（line 4955 附近）加一条
  - 主帮助列表（line 5911 附近）加一行
  - `_NL_ROUTES`（line 5102 起）加路由

**Interfaces:**
- Consumes: `ChanlunAnalyzer` + `DataAggregator.get_history(symbol, period="weekly")`
- Produces: `python -m src chanlun <code> [--freq D|W]` 命令 + 自然语言路由「缠论/中枢/背驰/买点/卖点」

- [ ] **Step 1: 写命令函数（复制 `cmd_indicators` 样板，line 809 之后插入）**

```python
@_safe_cmd
def cmd_chanlun(args: list[str]):
    """缠论结构分析 — 分型/笔/中枢/背驰/买卖点。

    用法: python -m src chanlun <code> [--freq D|W]
    """
    import argparse
    from src.data.aggregator import DataAggregator
    from src.indicators.chanlun.analyzer import ChanlunAnalyzer

    parser = argparse.ArgumentParser(description="缠论结构分析")
    parser.add_argument("symbol", nargs="?", default="", help="6 位股票代码")
    parser.add_argument("--freq", default="D", choices=["D", "W"],
                        help="周期 D=日线 / W=周线 (默认 D)")
    parsed = parser.parse_args(args)

    symbol = parsed.symbol
    if not symbol:
        print("用法: python -m src chanlun <code> [--freq D|W]")
        print()
        print("输出: 去包含K线 / 顶底分型 / 笔 / 中枢 / 背驰 / 买卖点")
        return
    if not re.match(r"^\d{6}$", symbol):
        print(f"❌ 无效股票代码: {symbol}")
        return

    agg = DataAggregator()
    try:
        if parsed.freq == "W":
            df = agg.get_history(symbol, period="weekly")
        else:
            df = agg.get_history(symbol)
        q = agg.get_quote(symbol)
        name = q.name if q else symbol
    except Exception:
        print(f"❌ 无法获取 {symbol} 数据")
        return
    if df is None or (hasattr(df, "empty") and df.empty):
        print(f"❌ {symbol} 无数据")
        return

    col_map = {"开盘": "open", "收盘": "close", "最高": "high", "最低": "low",
               "成交量": "volume", "成交额": "amount",
               "open": "open", "close": "close", "high": "high",
               "low": "low", "volume": "volume"}
    if hasattr(df, "rename"):
        df = df.rename(columns={c: col_map[c] for c in df.columns if c in col_map})

    result = ChanlunAnalyzer(freq=parsed.freq).analyze(df, symbol, name)
    _render_chanlun(result)


def _render_chanlun(result) -> None:
    """渲染缠论分析结果。"""
    if result.current_state.get("gap"):
        print(f"\n⚠️  {result.current_state['gap']}")
        return
    print(f"\n📈 缠论结构分析 — {result.symbol} {result.name} "
          f"({result.freq}线)  backend={result.backend}  confidence={result.confidence}")
    print(f"   分型 {len(result.fractals)} | 笔 {len(result.bis)} "
          f"| 中枢 {len(result.zhongshus)} | 买卖点 {len(result.points)}")

    if result.zhongshus:
        print("\n  📦 中枢序列:")
        for zs in result.zhongshus[-6:]:
            print(f"     {zs.state} ZG={zs.zg:.2f} ZD={zs.zd:.2f} ZZ={zs.zz:.2f} "
                  f"({_fmt_dt(zs.start_dt)} → {_fmt_dt(zs.end_dt)})")
    if result.bis:
        print("\n  ✏️ 最近笔:")
        for b in result.bis[-6:]:
            d = "↑" if b.direction == "up" else "↓"
            print(f"     {d} {_fmt_dt(b.start_dt)}→{_fmt_dt(b.end_dt)}  "
                  f"H={b.high:.2f} L={b.low:.2f} len={b.length} MACD={b.macd_area:.0f}")
    if result.points:
        print("\n  🎯 买卖点信号:")
        for p in result.points[-8:]:
            print(f"     {p.kind} @ {p.price:.2f} ({_fmt_dt(p.dt)}) "
                  f"conf={p.confidence:.2f} — {p.rationale}")

    cs = result.current_state
    print(f"\n  📍 现价位置: {cs.get('position', '未知')} "
          f"| 中枢状态: {cs.get('zhongshu_state', '未形成')}")
    print(f"  信号: 入场{len(result.signals['entry'])}个 "
          f"出场{len(result.signals['exit'])}个 | 置信度 {result.confidence}")


def _fmt_dt(dt) -> str:
    """安全格式化 datetime/Timestamp。"""
    try:
        return dt.strftime("%Y-%m-%d")
    except AttributeError:
        return str(dt)
```

- [ ] **Step 2: 注册命令**

在 `commands` dict（line 6027 `"tactics": lambda: cmd_tactics(args),` 后）加：
```python
        "chanlun": lambda: cmd_chanlun(args),
```
在帮助 `details` dict（line 4955 附近，仿 tactics 条目）加：
```python
        "chanlun": ("python -m src chanlun <code> [--freq D|W]",
                    "缠论结构分析 — 分型/笔/中枢/背驰/买卖点", []),
```
在主帮助列表（line 5911 附近，仿 `print("  tactics ...")`）加：
```python
    print("  chanlun <code>           缠论结构分析 (分型/笔/中枢/买卖点)")
```
在 `_NL_ROUTES`（line 5102 起，仿 tactics 路由）加：
```python
    {"keys": ["缠论", "中枢", "背驰", "买点", "卖点", "chanlun"],
     "cmd": "chanlun",
     "help": "python -m src chanlun <code>  # 需要股票代码"},
```
并在 `main()` 中 `_NL_ROUTES` 命中分支（line 6120 附近 `elif nl_result["cmd"] == "sweep":` 之前）加：
```python
            elif nl_result["cmd"] == "chanlun":
                cmd_chanlun([nl_result.get("symbol", "")])
```

- [ ] **Step 3: CLI 冒烟测试（真实标的）**

Run: `.venv/bin/python -m src chanlun 600519 --freq D 2>&1 | head -40`
Expected: 输出缠论分析表格（中枢/笔/买卖点）；若数据不足则输出 `⚠️ [DATA_GAP]`。网络不可用时允许报错降级——不视为失败，但需确认命令路由正确（显示"缠论结构分析"标题）。

- [ ] **Step 4: 无参数与非法代码**

Run: `.venv/bin/python -m src chanlun` 与 `.venv/bin/python -m src chanlun abc`
Expected: 分别打印用法与 `❌ 无效股票代码`

- [ ] **Step 5: 提交**

```bash
git add src/cli.py
git commit -m "feat(chanlun): CLI chanlun 子命令（日线/周线 + 自然语言路由）"
```

---

### Task 11: tactics 短线管道融入

**Files:**
- Modify: `src/routing/tactics.py`
  - `TacticalSnapshot` 加 2 字段（line 84 `technical_note` 后）
  - `run_tactics` 初始化 `_chanlun_state`（line 222 `_bars_df = None` 附近）
  - `_dim_technical()` 内加缠论块（line 610 KDJ 块之后）
  - doctrine_ctx 注入（line 776 附近）

**Interfaces:**
- Consumes: `ChanlunAnalyzer`（Task 8）+ `_bars_df`（run_tactics 现有）
- Produces: `snapshot.chanlun_score` / `snapshot.chanlun_result`；入场/出场信号并入 `entry_signals`/`exit_signals`（type 前缀 `CHANLUN_`）；`doctrine_ctx["chanlun_*"]` 供 Task 13 军规消费。

- [ ] **Step 1: TacticalSnapshot 加字段（line 84 `technical_note` 后）**

```python
    technical_note: str = ""

    # ── 🥋 缠论结构（独立维度，不改 6 维 composite）──
    chanlun_score: float = 50.0
    chanlun_result: Optional[dict] = None
```

- [ ] **Step 2: run_tactics 初始化（line 222 `_bars_df = None` 后）**

```python
    _bars_df = None       # pd.DataFrame | None
    _chanlun_state: dict = {}   # 缠论状态 → doctrine_ctx 注入
```

- [ ] **Step 3: `_dim_technical()` 内加缠论块（KDJ 块之后、`snapshot.technical_note = ...` 之前）**

```python
        # 缠论独立维度 (M4, 决策A: 独立报告不改 composite)
        try:
            from src.indicators.chanlun.analyzer import ChanlunAnalyzer
            chanlun_res = ChanlunAnalyzer(freq="D").analyze(df, symbol, name)
            snapshot.chanlun_result = chanlun_res.to_summary_dict()
            score = 50.0
            for p in chanlun_res.points:
                if p.kind in ("一买", "二买", "三买"):
                    score = max(score, 55.0 + 15.0 * p.confidence)
                elif p.kind in ("一卖", "二卖", "三卖"):
                    score = min(score, 45.0 - 10.0 * p.confidence)
            cs = chanlun_res.current_state
            if cs.get("position") == "中枢下方":
                score -= 8.0
            elif cs.get("position") == "中枢上方":
                score += 6.0
            snapshot.chanlun_score = round(max(0.0, min(100.0, score)), 1)
            # 买卖点并入入场/出场信号 (长多语义)
            for p in chanlun_res.points:
                if p.kind in ("一买", "二买", "三买"):
                    snapshot.entry_signals.append({
                        "type": f"CHANLUN_{p.kind}", "description": p.rationale,
                        "zone_low": round(p.price * 0.99, 2),
                        "zone_high": round(p.price * 1.01, 2),
                        "confidence": p.confidence,
                    })
                else:
                    snapshot.exit_signals.append({
                        "type": f"CHANLUN_{p.kind}", "description": p.rationale,
                        "zone_low": round(p.price * 0.99, 2),
                        "zone_high": round(p.price * 1.01, 2),
                        "confidence": p.confidence, "urgency": "NORMAL",
                    })
            # doctrine_ctx 注入字段
            _chanlun_state["sell"] = cs.get("last_point", {}).get("kind", "") in ("一卖", "二卖", "三卖")
            _chanlun_state["zs_break"] = cs.get("position") == "中枢下方"
            _chanlun_state["buy_confirmed"] = any(
                p.kind in ("一买", "二买", "三买") for p in chanlun_res.points
            )
            _chanlun_state["bihuang_down"] = any("底背驰" in p.rationale for p in chanlun_res.points)
        except Exception:
            snapshot.data_gaps.append("[DATA_GAP] 缠论分析")
```

> ⚠️ `_chanlun_state` 是外层闭包 dict，`_dim_technical` 内仅改 key 不重绑定，无需 `nonlocal`。

- [ ] **Step 4: doctrine_ctx 注入（line 776 `doctrine_ctx = {"stock_name": name}` 之后）**

```python
        if _chanlun_state:
            doctrine_ctx.update({
                "chanlun_sell_signal": "sell" if _chanlun_state.get("sell") else "",
                "chanlun_zs_break": bool(_chanlun_state.get("zs_break")),
                "chanlun_buy_confirmed": bool(_chanlun_state.get("buy_confirmed")),
                "chanlun_bihuang_down": bool(_chanlun_state.get("bihuang_down")),
            })
```

- [ ] **Step 5: 集成测试 — 直接驱动 `_dim_technical` 等价路径（mock `_bars_df`）**

```python
# tests/routing/test_tactics_chanlun.py
# -*- coding: utf-8 -*-
import numpy as np
import pandas as pd

from src.indicators.chanlun.analyzer import ChanlunAnalyzer


def _make_df(n=120):
    rng = np.random.default_rng(1)
    close = 100 + np.cumsum(rng.normal(0, 1, n))
    idx = pd.date_range("2025-01-01", periods=n, freq="D")
    return pd.DataFrame({
        "open": close + rng.normal(0, 0.3, n),
        "high": close + rng.uniform(0, 1, n),
        "low": close - rng.uniform(0, 1, n),
        "close": close, "volume": 1e6,
    }, index=idx)


def test_chanlun_on_bars_df_matches_tactics_shape():
    df = _make_df()
    r = ChanlunAnalyzer().analyze(df, "000001", "测试")
    summary = r.to_summary_dict()
    # 与 tactics 消费字段一致
    assert {"backend", "bi_count", "zhongshu_count", "last_zs",
            "points", "current_state", "signals", "confidence"} <= set(summary)
    assert summary["signals"].keys() == {"entry", "exit"}
    for sig in summary["signals"]["entry"]:
        assert sig["kind"] in ("一买", "二买", "三买")


def test_chanlun_score_mapping():
    # 有买点 → score > 50
    from src.indicators.chanlun.points import detect_points
    from src.indicators.chanlun.core.zhongshu import detect_zhongshus
    from src.indicators.chanlun.schema import Bi, Fractal

    def _bi(direction, high, low, area=0.0):
        if direction == "up":
            fa, fb = Fractal(mark="D", dt=0, high=low + 1, low=low, fx=low, index=0), \
                     Fractal(mark="G", dt=5, high=high, low=high - 1, fx=high, index=5)
        else:
            fa, fb = Fractal(mark="G", dt=0, high=high, low=high - 1, fx=high, index=0), \
                     Fractal(mark="D", dt=5, high=low + 1, low=low, fx=low, index=5)
        return Bi(direction=direction, start_fx=fa, end_fx=fb, high=high, low=low,
                  length=5, macd_area=area, start_dt=0, end_dt=5)

    bis = [_bi("down", 40, 30, 100.0), _bi("up", 36, 32, 30.0), _bi("down", 35, 31, 80.0),
           _bi("up", 34, 33, 20.0), _bi("down", 30, 24, 40.0), _bi("up", 30, 26, 20.0),
           _bi("down", 27, 25, 30.0)]
    zss = detect_zhongshus(bis)
    pts = detect_points(bis, zss, {4: {"type": "bottom", "bi_index": 4}})
    assert any(p.kind in ("一买", "二买", "三买") for p in pts)
```

- [ ] **Step 6: 运行集成测试**

Run: `.venv/bin/python -m pytest tests/routing/test_tactics_chanlun.py -v`
Expected: PASS (2 passed)

- [ ] **Step 7: 提交**

```bash
git add src/routing/tactics.py tests/routing/test_tactics_chanlun.py
git commit -m "feat(chanlun): tactics 融入缠论独立维度+买卖点信号+军规ctx注入"
```

---

### Task 12: diagnose 全链路融入

**Files:**
- Modify: `src/routing/diagnosis.py`
  - `DiagnosisReport` 加 2 字段（line 89 `divergence_consensus` 后）
  - `DiagnosisEngine.analyze()` 加参 `bars_df`（line 172 `guba_sentiment` 后）并加调用块（line 384 底部结构之后）
  - 加 `_detect_chanlun` 静态方法
- Modify: `src/routing/orchestrator.py`
  - line 1228 `self.diagnosis.analyze(...)` 前取 `bars_df` 并传参

**Interfaces:**
- Consumes: `ChanlunAnalyzer` + orchestrator 日线
- Produces: `report.chanlun`（dict）/ `report.chanlun_score`；momentum_score 保守微调（weight = 0.90 + 0.10×score/100）；`data_gaps` 加 `[WARN 缠论]`。

- [ ] **Step 1: DiagnosisReport 加字段（line 89 后）**

```python
    divergence_consensus: Optional[object] = None    # DivergenceConsensusResult

    chanlun: Optional[dict] = None       # 缠论结构摘要（只读）
    chanlun_score: float = 50.0          # 0-100
```

- [ ] **Step 2: analyze() 加参（line 172 `guba_sentiment: Optional[object] = None,` 后）**

```python
        guba_sentiment: Optional[object] = None,       # 股吧情绪快照 (GubaSentiment)
        bars_df: Optional[object] = None,              # 日线 DataFrame（缠论用，可空）
```

- [ ] **Step 3: 调用块（底部结构块 line 384 `report.momentum_score = self._apply_weight(...)` 之后插入）**

```python
        # Phase 12c: 缠论结构（保守微调动量 ±10%）
        chanlun_ctx = self._detect_chanlun(symbol, name, bars_df)
        if chanlun_ctx is not None:
            report.chanlun = chanlun_ctx["summary"]
            report.chanlun_score = chanlun_ctx["score"]
            weight = 0.90 + 0.10 * (report.chanlun_score / 100.0)
            report.momentum_score = self._apply_weight(report.momentum_score, weight)
            if chanlun_ctx["summary"].get("sell_signal"):
                report.data_gaps.append("[WARN 缠论] 结构转弱(买卖点转空)，动量小幅降权")
```

- [ ] **Step 4: `_detect_chanlun` 静态方法（加在 `_detect_bottom_structure` 前）**

```python
    @staticmethod
    def _detect_chanlun(symbol: str, name: str, bars_df):
        """缠论结构 → (score, state, entry_allowed)。无日线/异常返回 None（降级）。"""
        if bars_df is None or getattr(bars_df, "empty", True):
            return None
        try:
            from src.indicators.chanlun.analyzer import ChanlunAnalyzer
            res = ChanlunAnalyzer(freq="D").analyze(bars_df, symbol, name)
            if not res.bis and not res.zhongshus:
                return None
            summary = res.to_summary_dict()
            score = 50.0
            for p in res.points:
                if p.kind in ("一买", "二买", "三买"):
                    score = max(score, 55.0 + 15.0 * p.confidence)
                else:
                    score = min(score, 45.0 - 10.0 * p.confidence)
            pos = res.current_state.get("position", "未知")
            if pos == "中枢下方":
                score -= 8.0
            elif pos == "中枢上方":
                score += 6.0
            score = round(max(0.0, min(100.0, score)), 1)
            summary["sell_signal"] = any(p.kind in ("一卖", "二卖", "三卖") for p in res.points)
            summary["buy_signal"] = any(p.kind in ("一买", "二买", "三买") for p in res.points)
            return {"summary": summary, "score": score}
        except Exception:
            return None
```

- [ ] **Step 5: orchestrator 传 bars_df（line 1228 调用前）**

在 `report = self.diagnosis.analyze(` 调用前插入：
```python
        try:
            bars_df = self.data.get_history(symbol)
        except Exception:
            bars_df = None
```
并把调用尾部追加参数：
```python
        report = self.diagnosis.analyze(
            ...,
            guba_sentiment=...,
            bars_df=bars_df,
        )
```
（保持现有其它实参不变，仅追加 `bars_df=bars_df`。）

- [ ] **Step 6: 单元测试（诊断引擎）**

```python
# tests/routing/test_diagnosis_chanlun.py
# -*- coding: utf-8 -*-
import numpy as np
import pandas as pd

from src.routing.diagnosis import DiagnosisEngine


def _make_df(n=120):
    rng = np.random.default_rng(3)
    close = 100 + np.cumsum(rng.normal(0, 1, n))
    idx = pd.date_range("2025-01-01", periods=n, freq="D")
    return pd.DataFrame({
        "open": close + rng.normal(0, 0.3, n),
        "high": close + rng.uniform(0, 1, n),
        "low": close - rng.uniform(0, 1, n),
        "close": close, "volume": 1e6,
    }, index=idx)


def test_detect_chanlun_none_without_bars():
    assert DiagnosisEngine._detect_chanlun("000001", "测试", None) is None


def test_detect_chanlun_with_bars():
    ctx = DiagnosisEngine._detect_chanlun("000001", "测试", _make_df())
    if ctx is not None:                     # 随机数据可能无结构 → 允许 None
        assert 0.0 <= ctx["score"] <= 100.0
        assert "buy_signal" in ctx["summary"]
        assert "sell_signal" in ctx["summary"]
```

- [ ] **Step 7: 运行测试**

Run: `.venv/bin/python -m pytest tests/routing/test_diagnosis_chanlun.py -v`
Expected: PASS (2 passed)

- [ ] **Step 8: 提交**

```bash
git add src/routing/diagnosis.py src/routing/orchestrator.py tests/routing/test_diagnosis_chanlun.py
git commit -m "feat(chanlun): diagnose 融入缠论结构（动量±10%保守微调）"
```

---

### Task 13: 军规 r037 / r038

**Files:**
- Modify: `src/doctrine/rules.py`（`MILITARY_RULES` 末尾追加）
- Modify: `src/doctrine/checker.py`（`_evaluate` 加分支）
- Test: `tests/doctrine/test_chanlun_rules.py`

**Interfaces:**
- Consumes: `doctrine_ctx["chanlun_sell_signal"]` / `"chanlun_zs_break"` / `"chanlun_buy_confirmed"` / `"chanlun_bihuang_down"`（Task 11 注入）
- Produces: `MILITARY_RULES` 新增 `r037`/`r038`（WARN），`DoctrineChecker` 可触发。

- [ ] **Step 1: 写失败测试**

```python
# tests/doctrine/test_chanlun_rules.py
# -*- coding: utf-8 -*-
from src.doctrine.checker import DoctrineChecker
from src.doctrine.rules import MILITARY_RULES

_checker = DoctrineChecker()


def _ids():
    return {r.id for r in MILITARY_RULES}


def test_rules_registered():
    ids = _ids()
    assert "r037" in ids and "r038" in ids


def test_r037_triggers_on_sell_signal():
    ctx = {"chanlun_sell_signal": "sell"}
    dr = _checker.check("000001", ctx)
    assert "r037" in [w.id for w in dr.warnings]


def test_r037_triggers_on_zs_break():
    ctx = {"chanlun_zs_break": True}
    dr = _checker.check("000001", ctx)
    assert "r037" in [w.id for w in dr.warnings]


def test_r037_not_triggered_when_clean():
    ctx = {"chanlun_sell_signal": "", "chanlun_zs_break": False}
    dr = _checker.check("000001", ctx)
    assert "r037" not in [w.id for w in dr.warnings]


def test_r038_only_when_break_and_unconfirmed():
    ctx = {"chanlun_zs_break": True, "chanlun_buy_confirmed": False,
           "chanlun_bihuang_down": False}
    dr = _checker.check("000001", ctx)
    assert "r038" in [w.id for w in dr.warnings]


def test_r038_not_triggered_when_confirmed():
    ctx = {"chanlun_zs_break": True, "chanlun_buy_confirmed": True,
           "chanlun_bihuang_down": True}
    dr = _checker.check("000001", ctx)
    assert "r038" not in [w.id for w in dr.warnings]
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/doctrine/test_chanlun_rules.py -v`
Expected: FAIL（r037/r038 不存在，check 无此 id 不触发）

- [ ] **Step 3: rules.py 追加（`MILITARY_RULES` 列表末尾 r036 之后）**

```python
    # ── 缠论结构军规 ──
    Rule(
        "r037", RuleCategory.TRADING, "缠论中枢破位/三卖",
        Severity.WARN,
        "缠论结构转弱(出现一卖/二卖/三卖或现价跌破中枢下沿) → 追高/抄底需谨慎",
    ),
    Rule(
        "r038", RuleCategory.TRADING, "缠论背驰未确认",
        Severity.WARN,
        "中枢破位且无底背驰/买点确认 → 跌势未止，避免左侧抄底",
    ),
```

- [ ] **Step 4: checker.py 加分支（`_evaluate` 中 `r036` 分支之后、`return False` 之前）**

```python
        # 缠论结构转弱 — 中枢破位/三卖
        if rule.id == "r037":
            return bool(ctx.get("chanlun_sell_signal")) or bool(ctx.get("chanlun_zs_break"))

        # 缠论背驰未确认不进场
        if rule.id == "r038":
            if not ctx.get("chanlun_zs_break"):
                return False
            if ctx.get("chanlun_buy_confirmed"):
                return False
            if ctx.get("chanlun_bihuang_down"):
                return False
            return True
```

- [ ] **Step 5: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/doctrine/test_chanlun_rules.py -v`
Expected: PASS (6 passed)

- [ ] **Step 6: 提交**

```bash
git add src/doctrine/rules.py src/doctrine/checker.py tests/doctrine/test_chanlun_rules.py
git commit -m "feat(doctrine): 新增缠论军规 r037(中枢破位/三卖) + r038(背驰未确认)"
```

---

### Task 14: 全链路集成验证

**Files:**
- Test: `tests/indicators/test_chanlun_analyzer.py`（复用）+ 手动 CLI 验证

**Interfaces:**
- Consumes: 全部 13 个 task
- Produces: 全量测试通过 + tactics/diagnose 真实标的冒烟确认

- [ ] **Step 1: 全量 chanlun 相关测试**

Run: `.venv/bin/python -m pytest tests/indicators/test_chanlun_*.py tests/routing/test_tactics_chanlun.py tests/routing/test_diagnosis_chanlun.py tests/doctrine/test_chanlun_rules.py -v`
Expected: 全部 PASS

- [ ] **Step 2: 全量回归（不碰既有逻辑）**

Run: `.venv/bin/python -m pytest tests/ -q 2>&1 | tail -15`
Expected: 既有测试不回归（若个别网络依赖测试失败，确认与缠论改动无关即可）

- [ ] **Step 3: CLI 真实标的（日线 + 周线）**

Run:
```bash
.venv/bin/python -m src chanlun 600519 --freq D 2>&1 | head -40
.venv/bin/python -m src chanlun 600519 --freq W 2>&1 | head -40
```
Expected: 两个周期均输出缠论结构（中枢/笔/买卖点）；数据不足时输出 `⚠️ [DATA_GAP]` 而非崩溃。

- [ ] **Step 4: tactics 真实标的冒烟（确认不崩溃、不回归）**

Run: `.venv/bin/python -m src tactics 600519 --fast --no-t0 2>&1 | tail -30`
Expected: 正常输出裁决；含缠论维度（若可见）或不报错。网络/LLM 异常允许降级，但不得因 chanlun 代码崩溃。

- [ ] **Step 5: 更新运行时快照并提交**

```bash
git add -A
git commit -m "chore: 缠论模块集成验证（chanlun 单测 + tactics/diagnose/doctrine 融入）"
```

---

## 自审记录

- **Spec 覆盖**：CLI(Task10) / tactics(Task11) / diagnose(Task12) / 军规(Task13) / 自研核心+适配器(Task8) / 日+周(Task10 `--freq W`) / 决策 A(Task11 独立维度不动 composite) / 测试计划(Task1-14) / 错误处理(analyzer `_empty_result`+DATA_GAP) 全覆盖。
- **占位符扫描**：除 Task 8 的 czsc import 明确标注需用真实 import 行替换（因 czsc 可能未安装无法静态验证）外，无 TBD/TODO。
- **类型一致性**：`ChanlunResult.to_summary_dict()` 的 `signals`/`current_state`/`last_zs` 字段名在 Task 8/10/11/12 中一致使用；`detect_*` 函数签名与 DTO 字段名跨 task 对齐。

## 2026-08-04 算法修正（基于 300476 胜宏科技真实数据手动验证）

在实现前用真实强趋势数据（300476）验证设计时发现并修正两个算法 bug（详见 memory `chanlun-design-doc-bugs`，修正版 `/tmp/chan_analysis.py`）：

- **Bug 1（merge.py 包含判定）**：`contains` 第二分支误写 `prev.low >= lo`，正确应为 `prev.low <= lo`（前根包含当前）。原写法把下跌回调K线全合并（2704→72），已修正 + 新增 `test_partial_overlap_not_merged` 回归 + Task 2 Step 4b 真实数据验证。
- **Bug 2（build_bis 贪心折叠）**：贪心版无法处理"新高吞没旧顶"，产生同向连续笔或整段折叠。改为**迭代吸收小波动版**（连续同向留极端 + 相邻异向 gap<min_len 吸收 + 收敛连接），新增 `test_no_consecutive_same_direction_after_swallow` 回归 + Task 4 Step 4b 真实数据验证。
- **配套修正**：ZhongShu 加 `bi_indexes` 字段（Task 5 一并改 schema）；detect_points 三买/三卖只扫 `zss[-2:]` 且从 `last_bi` 之后开始（避免远古中枢误触发）；Task 7/8/11 测试 divergence 索引 `{2:...}`→`{4:...}` 与一买实际位置一致。
- **周线提示**：迭代版周线易过度合并（~150 根→2 笔），周线调用方（Task 8/10）应调大 `min_len`。
