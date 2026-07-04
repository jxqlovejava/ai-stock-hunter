# -*- coding: utf-8 -*-
"""MVP-1 三因子选股策略。

因子:
  1. PE 分位 < 30%（价值因子）
  2. ROE 连续 3 年 > 12%（质量因子）
  3. 北向资金净流入 > 0（资金因子）

H₀: 三因子不能产生相对沪深 300 的超额收益。
目标: 用 2015-2024 数据回测，95% 置信度拒绝 H₀。
"""

from __future__ import annotations

import backtrader as bt


class MVP1Strategy(bt.Strategy):
    """三因子选股策略。

    参数:
      pe_percentile (int): PE 分位阈值，默认 30
      roe_threshold (float): ROE 最低阈值，默认 12.0
      northbound_required (bool): 是否要求北向资金净流入，默认 True
      rebalance_days (int): 调仓周期（交易日），默认 20
      max_positions (int): 最大持仓数，默认 20
      single_position_pct (float): 单票仓位占比，默认 0.05
      stop_loss_pct (float): 止损线，默认 -0.15
    """

    params = dict(
        pe_percentile=30,
        roe_threshold=12.0,
        northbound_required=True,
        rebalance_days=20,
        max_positions=20,
        single_position_pct=0.05,
        stop_loss_pct=-0.15,
    )

    def __init__(self):
        self.rebalance_day_counter = 0
        self.order_list = []

    def next(self):
        # 止损检查
        for data in self.datas:
            pos = self.getposition(data)
            if pos.size > 0:
                pnl_pct = (data.close[0] - pos.price) / pos.price
                if pnl_pct < self.params.stop_loss_pct:
                    self.close(data=data)
                    continue

        # 调仓日
        self.rebalance_day_counter += 1
        if self.rebalance_day_counter < self.params.rebalance_days:
            return
        self.rebalance_day_counter = 0

        # 筛选（由外部因子数据提供）
        candidates = self._filter_stocks()
        if not candidates:
            return

        # 等权分配
        target_weight = 1.0 / min(len(candidates), self.params.max_positions)
        target_weight = min(target_weight, self.params.single_position_pct)

        # 卖出不在候选池的持仓
        candidate_codes = {c[0] for c in candidates}
        for data in self.datas:
            if data._name not in candidate_codes:
                self.close(data=data)

        # 买入候选
        for code, _score in candidates[: self.params.max_positions]:
            data = self.getdatabyname(code)
            if data is None:
                continue
            pos = self.getposition(data)
            if pos.size == 0:
                size = (self.broker.getvalue() * target_weight) / data.close[0]
                self.buy(data=data, size=int(size))

    def _filter_stocks(self) -> list[tuple[str, float]]:
        """根据三因子筛选候选股票。

        子类或外部需提供因子数据。默认筛选逻辑：
        1. PE 分位 < pe_percentile
        2. ROE > roe_threshold
        3. 北向资金净流入 > 0（如果 northbound_required）

        Returns: [(code, score), ...] 按 score 降序
        """
        candidates = []
        for data in self.datas:
            # 从 data 的 lines 或属性中获取因子值
            pe_pct = getattr(data, "pe_percentile", 50)
            roe = getattr(data, "roe", 0)
            nb = getattr(data, "northbound", 0)

            if pe_pct >= self.params.pe_percentile:
                continue
            if roe <= self.params.roe_threshold:
                continue
            if self.params.northbound_required and nb <= 0:
                continue

            score = (30 - pe_pct) / 30 * 0.4 + (roe - 12) / 20 * 0.4 + (1 if nb > 0 else 0) * 0.2
            candidates.append((data._name, min(max(score, 0), 1)))

        candidates.sort(key=lambda x: x[1], reverse=True)
        return candidates

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status in [order.Completed]:
            pass  # 成交
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            pass  # 拒绝
        self.order_list = [o for o in self.order_list if o.ref != order.ref]
