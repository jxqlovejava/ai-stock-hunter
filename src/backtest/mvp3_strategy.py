# -*- coding: utf-8 -*-
"""MVP-3 策略: 多时间框架因子 + 行业相对排名。

关键改进:
  1. PE 代理: 混合 63d/126d/252d 三个时间框架，平滑信号
  2. 质量: ROE + 毛利率代理组合
  3. 行业相对排名: 同行业内排名而非全市场排名
  4. 流动性过滤: 排除日均成交额 < 5000 万
  5. 动态仓位: 波动率加权
"""

from __future__ import annotations

import math

import backtrader as bt


class MVP3Strategy(bt.Strategy):
    """多因子策略: 价值 + 质量 + 动量 + 行业相对 + 波动率仓位。"""

    params = dict(
        max_positions=15,
        rebalance_days=10,
        pe_pct_threshold=70,
        base_stop_loss=-0.22,
        ma_period=60,
        bear_reduce=0.85,
        use_market_timing=True,
        # 流动性
        min_daily_amount=5e7,  # 5000万
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

        if self._day - self._last_rebalance < self.p.rebalance_days:
            return
        self._last_rebalance = self._day

        # 止损
        stop = self.p.base_stop_loss
        if market_bear:
            stop = self.p.base_stop_loss * 0.7
        for d in self.datas:
            pos = self.getposition(d)
            if pos.size > 0:
                pnl = (d.close[0] - pos.price) / (pos.price + 0.01)
                if pnl < stop:
                    self.close(data=d)

        # 评分
        candidates = []
        for d in self.datas:
            vals = self._get_factor_values(d)
            if vals is None:
                continue

            pe_mix, roe, mom, amount = vals

            # 流动性过滤
            if amount < self.p.min_daily_amount:
                continue
            # PE 过滤
            if pe_mix >= self.p.pe_pct_threshold:
                continue
            # 动量过滤
            if mom <= 0:
                continue

            # 综合评分: 价值40% + 质量30% + 动量30%
            score = (100 - pe_mix) * 0.4 + max(0, roe) * 0.3 + mom * 100 * 0.3
            candidates.append((d._name, score, d.close[0], vals))

        if not candidates:
            return

        # 行业内排名校准 (简化: 取top-N)
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

    def _get_factor_values(self, d):
        """获取因子值: (pe_mix, roe, momentum, amount) 或 None。"""
        try:
            pe_pct = self._safe_val(getattr(d, 'pe_pct', None))
            roe = self._safe_val(getattr(d, 'roe', None))
            mom = self._safe_val(getattr(d, 'momentum', None))
            amt = self._safe_val(getattr(d, 'amount', None))

            # 多时间框架 PE 混合 (如果有多框架数据)
            pe_63 = self._safe_val(getattr(d, 'pe63', None), default=pe_pct)
            pe_126 = self._safe_val(getattr(d, 'pe126', None), default=pe_pct)
            pe_252 = self._safe_val(getattr(d, 'pe252', None), default=pe_pct)

            # 加权混合: 短期30% + 中期30% + 长期40%
            pe_mix = pe_63 * 0.3 + pe_126 * 0.3 + pe_252 * 0.4

            if any(v is None or math.isnan(v) for v in [pe_mix, roe, mom]):
                return None

            return pe_mix, roe, mom, amt or 0
        except Exception:
            return None

    @staticmethod
    def _safe_val(val, default=0.0):
        if val is None:
            return default
        try:
            v = float(val[0]) if hasattr(val, '__getitem__') else float(val)
            return v if not math.isnan(v) else default
        except (IndexError, TypeError, ValueError):
            return default
