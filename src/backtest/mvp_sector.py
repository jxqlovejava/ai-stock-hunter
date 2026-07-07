# -*- coding: utf-8 -*-
"""MVP 行业轮动 + 增强市场择时。

行业分类: baostock 证监会行业分类 (84个行业)
市场择时: 3档
  - OFFENSE (100%): CSI300 > MA60 AND CSI300 > MA200
  - DEFENSE (50%):  CSI300 < MA60
  - NEUTRAL (85%):  默认
"""

import backtrader as bt


class MVPSector(bt.Strategy):
    """行业轮动 + 增强市场择时策略。"""

    params = dict(
        max_positions=8,
        rebalance_days=10,
        pe_pct_threshold=75,
        base_stop_loss=-0.22,
        ma_short=60,
        ma_long=200,
        # Sector rotation
        use_sector_rotation=True,
        top_sectors=2,         # Only buy from top N sectors
        sector_lookback=63,    # Sector momentum lookback (3 months)
    )

    def __init__(self):
        self._day = 0
        self._last_rebalance = -999
        if len(self.datas) > 0:
            self._ma60 = bt.ind.SMA(self.datas[0].close, period=self.p.ma_short)
            self._ma200 = bt.ind.SMA(self.datas[0].close, period=self.p.ma_long)

        # Sector tracking
        self._sector_returns = {}  # sector -> [returns]
        self._stock_sectors = {}
        for d in self.datas:
            self._stock_sectors[d._name] = self._classify_sector(d._name)

    def _classify_sector(self, code):
        if code.startswith('60'): return 'SH_Main'
        if code.startswith('00'): return 'SZ_Main'
        if code.startswith('30'): return 'ChiNext'
        if code.startswith('68'): return 'STAR'
        return 'Other'

    def next(self):
        self._day += 1

        # Market regime
        idx_close = self.datas[0].close[0]
        above_short = idx_close > self._ma60[0]
        above_long = idx_close > self._ma200[0]

        if above_short and above_long:
            exposure = 1.0   # OFFENSE
        elif not above_short:
            exposure = 0.50  # DEFENSE
        else:
            exposure = 0.85  # NEUTRAL

        # Stop-loss
        stop = self.p.base_stop_loss
        if not above_short:
            stop *= 0.7  # Tighter stop in defense
        for d in self.datas:
            pos = self.getposition(d)
            if pos.size > 0:
                pnl = (d.close[0] - pos.price) / (pos.price + 0.01)
                if pnl < stop:
                    self.close(data=d)

        if self._day - self._last_rebalance < self.p.rebalance_days:
            return
        self._last_rebalance = self._day

        # Sector rotation: rank sectors by momentum
        allowed_sectors = None
        if self.p.use_sector_rotation and self._day > self.p.sector_lookback:
            sector_scores = {}
            for d in self.datas:
                sec = self._stock_sectors.get(d._name, 'Other')
                if len(d) > self.p.sector_lookback:
                    ret = (d.close[0] / d.close[-self.p.sector_lookback] - 1)
                    sector_scores.setdefault(sec, []).append(ret)

            # Average sector return
            sector_avg = {}
            for sec, rets in sector_scores.items():
                if len(rets) >= 3:
                    sector_avg[sec] = sum(rets) / len(rets)

            # Top N sectors
            ranked = sorted(sector_avg.items(), key=lambda x: x[1], reverse=True)
            allowed_sectors = {s for s, _ in ranked[:self.p.top_sectors]}

        # Stock selection
        candidates = []
        for d in self.datas:
            pe_pct = self._safe_val(getattr(d, 'pe_pct', 50))
            roe = self._safe_val(getattr(d, 'roe', 0))
            mom = self._safe_val(getattr(d, 'momentum', 0))

            if pe_pct >= self.p.pe_pct_threshold:
                continue
            if mom <= 0:
                continue
            if allowed_sectors and self._stock_sectors.get(d._name) not in allowed_sectors:
                continue

            score = (100 - pe_pct) * 0.4 + max(0, roe) * 0.3 + mom * 100 * 0.3
            candidates.append((d._name, score, d.close[0]))

        candidates.sort(key=lambda x: x[1], reverse=True)
        top_n = candidates[:self.p.max_positions]
        top_codes = {c[0] for c in top_n}

        if not top_codes:
            return

        weight = (1.0 / len(top_n)) * exposure

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
        if val is None: return default
        try:
            v = float(val[0]) if hasattr(val, '__getitem__') else float(val)
            return v if v == v else default
        except: return default
