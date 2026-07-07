# -*- coding: utf-8 -*-
"""借鉴 AlphaEvo 因子的增强策略。

新增因子:
  1. 成交量比率 (volume/20日均量 > 1.2)
  2. RSI 过滤 (RSI < 70, 不过热)
  3. 布林带压缩 (BB宽度 < 0.14, 低波动蓄势)
  4. MA20 斜率 (趋势向上确认)
"""

import backtrader as bt


class MVPAlphaEvo(bt.Strategy):
    """PE代理 + 动量 + AlphaEvo增强因子。"""

    params = dict(
        max_positions=8,
        rebalance_days=10,
        pe_pct_threshold=75,
        base_stop_loss=-0.22,
        ma_period=60,
        bear_reduce=0.85,
        use_market_timing=True,
        # AlphaEvo factors
        min_volume_ratio=1.2,       # 成交量/20日均量
        max_rsi=70,                 # RSI上限
        max_bb_width=0.14,          # 布林带宽度上限
        require_ma20_up=True,       # 要求MA20上升
    )

    def __init__(self):
        self._day = 0
        self._last_rebalance = -999
        if self.p.use_market_timing and len(self.datas) > 0:
            self._market_ma = bt.ind.SMA(self.datas[0].close, period=self.p.ma_period)

        # Pre-compute indicators for each stock
        self._indicators = {}
        for d in self.datas:
            close = d.close
            volume = d.volume
            inds = {
                'rsi': bt.ind.RSI_Safe(close, period=14),
                'ma20': bt.ind.SMA(close, period=20),
                'vol_ma20': bt.ind.SMA(volume, period=20),
                'bb_top': bt.ind.BollingerBands(close, period=20).top,
                'bb_bot': bt.ind.BollingerBands(close, period=20).bot,
            }
            self._indicators[d._name] = inds

    def next(self):
        self._day += 1

        market_bear = False
        if self.p.use_market_timing and len(self.datas) > 0:
            market_bear = self.datas[0].close[0] < self._market_ma[0]

        # Stop loss
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
            pe_pct = self._safe_val(getattr(d, 'pe_pct', 50))
            roe = self._safe_val(getattr(d, 'roe', 0))
            mom = self._safe_val(getattr(d, 'momentum', 0))
            inds = self._indicators.get(d._name, {})

            if pe_pct >= self.p.pe_pct_threshold:
                continue
            if mom <= 0:
                continue

            # AlphaEvo filters
            if inds:
                # Volume ratio
                vol_ratio = d.volume[0] / (inds['vol_ma20'][0] + 0.01)
                if vol_ratio < self.p.min_volume_ratio:
                    continue

                # RSI filter
                if inds['rsi'][0] > self.p.max_rsi:
                    continue

                # Bollinger Band compression
                if inds['bb_top'][0] > 0 and inds['bb_bot'][0] > 0:
                    bb_width = (inds['bb_top'][0] - inds['bb_bot'][0]) / inds['bb_top'][0]
                    if bb_width > self.p.max_bb_width:
                        continue

                # MA20 rising
                if self.p.require_ma20_up:
                    if inds['ma20'][0] <= inds['ma20'][-5]:
                        continue

            score = (100 - pe_pct) * 0.4 + max(0, roe) * 0.3 + mom * 100 * 0.3
            candidates.append((d._name, score, d.close[0]))

        candidates.sort(key=lambda x: x[1], reverse=True)
        top_n = candidates[:self.p.max_positions]
        top_codes = {c[0] for c in top_n}

        if not top_codes:
            return

        weight = 1.0 / len(top_n)
        if market_bear:
            weight *= self.p.bear_reduce

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

    @staticmethod
    def _safe_val(val, default=0.0):
        if val is None:
            return default
        try:
            v = float(val[0]) if hasattr(val, '__getitem__') else float(val)
            return v if v == v else default
        except:
            return default
