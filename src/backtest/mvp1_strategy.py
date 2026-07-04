# -*- coding: utf-8 -*-
"""MVP-1 三因子选股策略（简化版）。

因子:
  1. PE 分位代理: 当前价格在过去252日区间中的相对位置（越低越便宜）
  2. ROE 代理: 过去252日涨跌幅
  3. 动量过滤: 过去21日涨跌幅 > 0

策略逻辑:
  - 每月调仓（21个交易日）
  - 选 PE分位最低 + ROE最高 的 top-N 只
  - 等权配置，止损 -25%
"""

from __future__ import annotations

import backtrader as bt


class MVP1Strategy(bt.Strategy):
    """动态三因子选股策略。

    因子在 pandas 中预计算，作为额外列传入 Backtrader。
    """

    params = dict(
        max_positions=20,
        rebalance_days=21,
        stop_loss_pct=-0.25,
        pe_pct_threshold=70,
    )

    def __init__(self):
        self._day = 0
        self._last_month = -1

    def next(self):
        self._day += 1

        # 止损
        for d in self.datas:
            pos = self.getposition(d)
            if pos.size > 0:
                pnl = (d.close[0] - pos.price) / (pos.price + 0.01)
                if pnl < self.p.stop_loss_pct:
                    self.close(data=d)

        # 月调仓
        current_month = self._day // self.p.rebalance_days
        if current_month == self._last_month:
            return
        self._last_month = current_month

        # 评分：基于预计算的因子列
        candidates = []
        for d in self.datas:
            # 因子数据在预计算时已加入 DataFrame 的额外列中
            pe_pct = getattr(d, 'pe_pct', 50.0)
            roe = getattr(d, 'roe', 0.0)
            mom = getattr(d, 'momentum', 0.0)

            # 获取当前值（Backtrader 的额外列也可以按 index 访问）
            try:
                pe_pct = float(pe_pct) if not hasattr(pe_pct, '__getitem__') else pe_pct[0]
                roe = float(roe) if not hasattr(roe, '__getitem__') else roe[0]
                mom = float(mom) if not hasattr(mom, '__getitem__') else mom[0]
            except (IndexError, TypeError):
                continue

            if pe_pct >= self.p.pe_pct_threshold:
                continue
            if mom <= 0:
                continue

            score = (100 - pe_pct) * 0.5 + max(0, roe) * 0.3 + mom * 100 * 0.2
            candidates.append((d._name, score))

        candidates.sort(key=lambda x: x[1], reverse=True)
        top_n = candidates[:self.p.max_positions]
        top_codes = {c[0] for c in top_n}

        if not top_codes:
            return

        weight = 1.0 / len(top_codes)

        # 调仓
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
