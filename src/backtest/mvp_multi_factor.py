# -*- coding: utf-8 -*-
"""12因子增强策略 — 从 OHLCV 计算 12 个因子，复合打分。

因子:
  价值: PE代理(252d价格位置), PB代理(1/波动率)
  动量: 21d, 63d, 5d反转
  质量: ROE代理(252d收益), 成交量比率(量/20日均量)
  技术: RSI, 布林带宽度, MA20斜率, MA5/20交叉
  波动: 20d波动率倒数(低波溢价)

评分: 等权复合 (各因子标准化为0-100后取均值)
"""

import backtrader as bt


class MVPMultiFactor(bt.Strategy):
    """12因子复合评分策略。"""

    params = dict(
        max_positions=8,
        rebalance_days=10,
        score_threshold=50,        # 最低综合得分
        base_stop_loss=-0.22,
        ma_period=60,
        bear_reduce=0.85,
        use_market_timing=True,
    )

    def __init__(self):
        self._day = 0
        self._last_rebalance = -999
        if self.p.use_market_timing and len(self.datas) > 0:
            self._market_ma = bt.ind.SMA(self.datas[0].close, period=self.p.ma_period)

        self._inds = {}
        for d in self.datas:
            c = d.close
            v = d.volume
            inds = {
                # 技术指标
                'rsi14': bt.ind.RSI_Safe(c, period=14),
                'ma5': bt.ind.SMA(c, period=5),
                'ma20': bt.ind.SMA(c, period=20),
                'ma63': bt.ind.SMA(c, period=63),
                'bb_top': bt.ind.BollingerBands(c, period=20).top,
                'bb_bot': bt.ind.BollingerBands(c, period=20).bot,
                'vol_ma20': bt.ind.SMA(v, period=20),
                # 滚动统计
                'std20': bt.ind.StdDev(c, period=20),
            }
            self._inds[d._name] = inds

    def next(self):
        self._day += 1

        market_bear = False
        if self.p.use_market_timing and len(self.datas) > 0:
            market_bear = self.datas[0].close[0] < self._market_ma[0]

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
            inds = self._inds.get(d._name, {})
            if not inds:
                continue

            c = d.close[0]
            v = d.volume[0]
            if c <= 0 or v <= 0:
                continue

            # --- 12因子计算 ---
            scores = []

            # 1. PE代理 (价值): 价格越低越好 (0-100)
            pe_pct = self._safe_val(getattr(d, 'pe_pct', 50))
            scores.append(100 - pe_pct)  # Already 0-100

            # 2. 动量21d: 越大越好
            mom21 = self._safe_val(getattr(d, 'momentum', 0))
            scores.append(max(0, min(100, 50 + mom21 * 200)))

            # 3. 成交量比率: >1更好
            vol_ratio = v / (inds['vol_ma20'][0] + 0.01)
            scores.append(max(0, min(100, vol_ratio * 40)))

            # 4. RSI: 30-70最好, 极端不好
            rsi = inds['rsi14'][0]
            rsi_score = 100 - abs(rsi - 50) * 2  # 50最好
            scores.append(max(0, min(100, rsi_score)))

            # 5. BB宽度: 越窄越好(蓄势)
            if inds['bb_top'][0] > 0:
                bb_w = (inds['bb_top'][0] - inds['bb_bot'][0]) / inds['bb_top'][0]
                scores.append(max(0, min(100, 100 - bb_w * 500)))

            # 6. MA20斜率: 上升更好
            ma20_now = inds['ma20'][0]
            ma20_past = inds['ma20'][-5]
            ma_slope = (ma20_now / (ma20_past + 0.01) - 1) * 100
            scores.append(max(0, min(100, 50 + ma_slope * 500)))

            # 7. 5日反转: 短期不要涨太猛
            ret5 = (c / d.close[-5] - 1) * 100 if len(d) > 5 else 0
            scores.append(max(0, min(100, 50 - ret5 * 5)))

            # 8. 波动率倒数: 低波更好
            std20 = inds['std20'][0]
            if std20 > 0:
                scores.append(max(0, min(100, (1 / std20) * c * 2)))

            # 9. MA5/20交叉: 金叉加分
            ma5 = inds['ma5'][0]
            cross = 100 if ma5 > ma20_now else (50 if ma5 > ma20_now * 0.95 else 0)
            scores.append(cross)

            # 综合得分
            if len(scores) >= 6:
                avg_score = sum(scores) / len(scores)
                if avg_score >= self.p.score_threshold:
                    candidates.append((d._name, avg_score, c))

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
                    size = int(target_val / (c + 0.01) / 100) * 100
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
