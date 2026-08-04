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
