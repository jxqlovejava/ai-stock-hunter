# -*- coding: utf-8 -*-
"""MVP2+ 策略: 加动量强度阈值 + 反转动量退出。"""

import backtrader as bt


class MVP2Plus(bt.Strategy):
    """增强 MVP2: 动量强度过滤 + 动量反转退出 + 波动率仓位。"""

    params = dict(
        max_positions=10,
        rebalance_days=10,
        pe_pct_threshold=75,
        base_stop_loss=-0.22,
        ma_period=60,
        bear_reduce=0.85,
        use_market_timing=True,
        # 动量强度
        min_momentum_pct=0.0,      # 最小动量阈值 (0=只要正动量, 2=至少2%)
        momentum_exit=False,        # 动量转负时退出
        # 动态仓位
        use_dynamic_sizing=False,   # 波动率倒数加权
    )

    def __init__(self):
        self._day = 0
        self._last_rebalance = -999
        if self.p.use_market_timing and len(self.datas) > 0:
            self._market_ma = bt.ind.SMA(self.datas[0].close, period=self.p.ma_period)

    def next(self):
        self._day += 1
        market_bear = False
        if self.p.use_market_timing and len(self.datas) > 0:
            market_bear = self.datas[0].close[0] < self._market_ma[0]

        # 动量反转退出
        if self.p.momentum_exit:
            for d in self.datas:
                pos = self.getposition(d)
                if pos.size > 0:
                    mom = self._safe_val(getattr(d, 'momentum', None))
                    if mom is not None and mom < 0:
                        self.close(data=d)

        # 止损
        stop = self.p.base_stop_loss
        if market_bear:
            stop *= 0.7
        for d in self.datas:
            pos = self.getposition(d)
            if pos.size > 0:
                pnl = (d.close[0] - pos.price) / (pos.price + 0.01)
                if pnl < stop:
                    self.close(data=d)

        if self._day - self._last_rebalance < self.p.rebalance_days:
            return
        self._last_rebalance = self._day

        candidates = []
        for d in self.datas:
            pe_pct = self._safe_val(getattr(d, 'pe_pct', None), 100)
            roe = self._safe_val(getattr(d, 'roe', None))
            mom = self._safe_val(getattr(d, 'momentum', None))
            close = self._safe_val(getattr(d, 'close', None))
            vol = self._safe_val(getattr(d, 'roe', None), 10)  # proxy

            if pe_pct >= self.p.pe_pct_threshold:
                continue
            if mom <= self.p.min_momentum_pct:
                continue

            score = (100 - pe_pct) * 0.4 + max(0, roe) * 0.3 + mom * 100 * 0.3
            # 波动率惩罚
            if self.p.use_dynamic_sizing and vol > 0:
                score = score / (vol / 10 + 1)
            candidates.append((d._name, score, close))

        if not candidates:
            return

        candidates.sort(key=lambda x: x[1], reverse=True)
        top_n = candidates[:self.p.max_positions]
        top_codes = {c[0] for c in top_n}

        base_weight = 1.0 / len(top_n)
        if market_bear:
            base_weight *= self.p.bear_reduce

        for d in self.datas:
            if d._name in top_codes:
                pos = self.getposition(d)
                if pos.size == 0:
                    target_val = self.broker.getvalue() * base_weight
                    size = int(target_val / (d.close[0] + 0.01) / 100) * 100
                    if size >= 100:
                        self.buy(data=d, size=size)
            else:
                if self.getposition(d).size > 0:
                    self.close(data=d)

    @staticmethod
    def _safe_val(val, default=0.0):
        if val is None:
            return default
        try:
            v = float(val[0]) if hasattr(val, '__getitem__') else float(val)
            return v if v == v else default  # NaN check
        except (IndexError, TypeError, ValueError):
            return default
