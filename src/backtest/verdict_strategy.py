# -*- coding: utf-8 -*-
"""Verdict 回测策略 — 基于 VerdictEngine 多维加权评分。

从预计算的 vb_score / vb_rec 列读取评分，按分排名选股。

与实盘 VerdictEngine 对应:
  - 6 维加权评分 (same weights)
  - BUY/ADD/HOLD/REDUCE/SELL 阈值 (same thresholds)
  - 跳过不可回测: Alpha Lens / 博弈论 / 思维模型 / 辩论
"""

from __future__ import annotations

import backtrader as bt


class VerdictBacktestStrategy(bt.Strategy):
    """白泽裁决回测策略。

    每月调仓，选 vb_score 最高的 N 只等权持有。
    """

    params = dict(
        max_positions=10,
        rebalance_days=21,         # 月调
        min_score=60,              # 至少 ADD 才买入
        stop_loss_pct=-0.25,
        use_market_timing=True,    # vb_macro < 40 跳过买
    )

    def __init__(self):
        self._day = 0
        self._last_rebalance = -999

    def next(self):
        self._day += 1

        # ---- 止损 ----
        for d in self.datas:
            pos = self.getposition(d)
            if pos.size > 0:
                pnl = (d.close[0] - pos.price) / (pos.price + 0.01)
                if pnl < self.p.stop_loss_pct:
                    self.close(data=d)

        # ---- 调仓日判断 ----
        if self._day - self._last_rebalance < self.p.rebalance_days:
            return
        self._last_rebalance = self._day

        # ---- 评分 + 排序 ----
        candidates = []
        for d in self.datas:
            score = self._safe_val(getattr(d, "vb_score", None), default=50.0)
            rec = self._safe_rec(getattr(d, "vb_rec", None))
            macro = self._safe_val(getattr(d, "vb_macro", None), default=50.0)

            # 市场择时
            if self.p.use_market_timing and macro < 40:
                continue

            # 推荐过滤: BUY/ADD/HOLD (分数足够即可)
            if rec == "SELL":
                continue
            if score < self.p.min_score:
                continue

            candidates.append((d._name, score, d.close[0]))

        if not candidates:
            return

        candidates.sort(key=lambda x: x[1], reverse=True)
        top_n = candidates[: self.p.max_positions]
        top_codes = {c[0] for c in top_n}

        weight = 1.0 / len(top_n)

        # ---- 调仓 ----
        for d in self.datas:
            if d._name in top_codes:
                pos = self.getposition(d)
                if pos.size == 0:
                    target_val = self.broker.getvalue() * weight
                    size = int(target_val / (d.close[0] + 0.01) / 100) * 100
                    if size >= 100:
                        self.buy(data=d, size=size)
            else:
                if self.getposition(d).size > 0:
                    self.close(data=d)

    # ---- helpers ----

    @staticmethod
    def _safe_val(val, default=50.0):
        if val is None:
            return default
        try:
            v = float(val[0]) if hasattr(val, "__getitem__") else float(val)
            return v if v == v else default
        except (IndexError, TypeError, ValueError):
            return default

    @staticmethod
    def _safe_rec(val):
        if val is None:
            return "HOLD"
        try:
            r = val[0] if hasattr(val, "__getitem__") else str(val)
            return r if r in ("BUY", "ADD", "HOLD", "REDUCE", "SELL") else "HOLD"
        except (IndexError, TypeError):
            return "HOLD"
