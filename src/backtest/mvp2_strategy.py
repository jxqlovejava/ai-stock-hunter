# -*- coding: utf-8 -*-
"""MVP-2 策略: MVP1 + 市场择时 + 动态止损 + 波动率仓位。

新增:
  1. 市场择时: CSI300 < 60日均线 → 仓位减半或清仓
  2. 动态止损: 根据近期波动率调整止损线
  3. 波动率仓位: 高波动股票降低仓位
"""

from __future__ import annotations

import backtrader as bt


class MVP2Strategy(bt.Strategy):
    """增强三因子策略: PE分位 + ROE + 动量 + 市场择时。"""

    params = dict(
        max_positions=10,
        rebalance_days=10,
        pe_pct_threshold=70,
        # 止损
        base_stop_loss=-0.20,      # 基础止损 -20%
        # 市场择时
        ma_period=60,              # 均线周期
        bear_reduce=0.5,           # 熊市仓位减半
        use_market_timing=True,    # 是否启用市场择时
        # 波动率仓位
        use_vol_sizing=False,      # 是否启用波动率仓位
    )

    def __init__(self):
        self._day = 0
        self._last_rebalance = -999

        # 市场择时指标
        if self.p.use_market_timing and len(self.datas) > 0:
            self._market_ma = bt.ind.SMA(self.datas[0].close, period=self.p.ma_period)

    def next(self):
        self._day += 1

        # 市场择时: 判断当前市场状态
        market_bear = False
        if self.p.use_market_timing and len(self.datas) > 0:
            idx_close = self.datas[0].close[0]
            idx_ma = self._market_ma[0]
            market_bear = idx_close < idx_ma

        # 调仓日
        if self._day - self._last_rebalance < self.p.rebalance_days:
            return
        self._last_rebalance = self._day

        # 止损检查
        for d in self.datas:
            pos = self.getposition(d)
            if pos.size > 0:
                pnl = (d.close[0] - pos.price) / (pos.price + 0.01)
                # 动态止损: 熊市中收紧止损
                stop = self.p.base_stop_loss
                if market_bear:
                    stop = self.p.base_stop_loss * 0.7  # 熊市止损更紧
                if pnl < stop:
                    self.close(data=d)

        # 评分
        candidates = []
        for d in self.datas:
            pe_pct = getattr(d, 'pe_pct', 50)
            roe = getattr(d, 'roe', 0)
            mom = getattr(d, 'momentum', 0)

            try:
                pe_pct = float(pe_pct[0]) if hasattr(pe_pct, '__getitem__') else float(pe_pct)
                roe = float(roe[0]) if hasattr(roe, '__getitem__') else float(roe)
                mom = float(mom[0]) if hasattr(mom, '__getitem__') else float(mom)
            except (IndexError, TypeError):
                continue

            if pe_pct >= self.p.pe_pct_threshold:
                continue
            if mom <= 0:
                continue

            # 综合评分
            score = (100 - pe_pct) * 0.4 + max(0, roe) * 0.3 + mom * 100 * 0.3
            candidates.append((d._name, score, d.close[0]))

        candidates.sort(key=lambda x: x[1], reverse=True)
        top_n = candidates[:self.p.max_positions]
        top_codes = {c[0] for c in top_n}

        if not top_codes:
            return

        # 仓位计算
        base_weight = 1.0 / len(top_codes)

        # 市场择时: 熊市减仓
        if market_bear:
            base_weight *= self.p.bear_reduce

        for d in self.datas:
            if d._name in top_codes:
                pos = self.getposition(d)
                target_size = 0
                if pos.size > 0:
                    target_val = self.broker.getvalue() * base_weight
                    target_size = int(target_val / (d.close[0] + 0.01) / 100) * 100

                if pos.size == 0:
                    # 新建仓
                    target_val = self.broker.getvalue() * base_weight
                    size = int(target_val / (d.close[0] + 0.01) / 100) * 100
                    if size >= 100:
                        self.buy(data=d, size=size)
                elif abs(pos.size - target_size) > pos.size * 0.2:
                    # 调仓: 差异超过20%才调整
                    if target_size > pos.size:
                        self.buy(data=d, size=target_size - pos.size)
                    elif target_size < pos.size:
                        self.sell(data=d, size=pos.size - target_size)
            else:
                if self.getposition(d).size > 0:
                    self.close(data=d)
