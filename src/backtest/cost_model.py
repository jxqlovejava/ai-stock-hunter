# -*- coding: utf-8 -*-
"""A 股交易成本模型 — 提取 ChinaAEngine 成本逻辑为独立可复用模块。

支持:
  - 事前预估: estimate_cost() / estimate_cost_pct()
  - 事后结算: calc_roundtrip_cost() / calc_buy_cost() / calc_sell_cost()
  - 换手率估算: estimate_annual_turnover_cost()
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CostBreakdown:
    """单笔交易成本明细。"""
    symbol: str = ""
    price: float = 0.0
    quantity: int = 0
    notional: float = 0.0          # 名义成交金额
    commission: float = 0.0         # 佣金（含最低 5 元）
    stamp_tax: float = 0.0          # 印花税（卖出单向千1→千0.5, 2023.8.28起）
    transfer_fee: float = 0.0       # 过户费（万0.2，双向）
    slippage: float = 0.0           # 预估滑点
    total_cost: float = 0.0         # 总成本
    net_proceeds: float = 0.0       # 扣除成本后净额
    cost_pct: float = 0.0           # 成本占名义金额比例

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol, "price": self.price,
            "quantity": self.quantity, "notional": round(self.notional, 2),
            "commission": round(self.commission, 4),
            "stamp_tax": round(self.stamp_tax, 4),
            "transfer_fee": round(self.transfer_fee, 4),
            "slippage": round(self.slippage, 4),
            "total_cost": round(self.total_cost, 4),
            "net_proceeds": round(self.net_proceeds, 2),
            "cost_pct": round(self.cost_pct, 6),
        }


class AShareCostCalculator:
    """A 股交易成本计算器。

    参数 (可覆盖):
      - commission_rate: 佣金费率（默认万3）
      - commission_min: 最低佣金（默认 5 元）
      - stamp_tax_rate: 印花税率（卖出单向，默认千0.5，2023.8.28起）
      - transfer_fee_rate: 过户费率（双向，默认十万1）
      - slippage_rate: 滑点率（默认千1）

    用法:
        calc = AShareCostCalculator()
        cost = calc.estimate_cost("000001", price=10.0, quantity=1000, direction=1, is_open=True)
        print(f"买入成本: {cost.total_cost:.2f} ({cost.cost_pct*100:.2f}%)")
    """

    # A 股默认费率 (2024年起)
    DEFAULT_COMMISSION_RATE = 0.00025   # 万 2.5（行业平均，部分券商可低至万1.5）
    DEFAULT_COMMISSION_MIN = 5.0        # 最低 5 元
    DEFAULT_STAMP_TAX_RATE = 0.0005     # 千 0.5（卖出单向，2023.8.28 起减半）
    DEFAULT_TRANSFER_FEE_RATE = 0.00001 # 万 0.1（十万1，双向）
    DEFAULT_SLIPPAGE_RATE = 0.001       # 千 1（非冲击性小额订单）

    def __init__(
        self,
        commission_rate: float | None = None,
        commission_min: float | None = None,
        stamp_tax_rate: float | None = None,
        transfer_fee_rate: float | None = None,
        slippage_rate: float | None = None,
    ):
        self.commission_rate = commission_rate or self.DEFAULT_COMMISSION_RATE
        self.commission_min = commission_min or self.DEFAULT_COMMISSION_MIN
        self.stamp_tax_rate = stamp_tax_rate or self.DEFAULT_STAMP_TAX_RATE
        self.transfer_fee_rate = transfer_fee_rate or self.DEFAULT_TRANSFER_FEE_RATE
        self.slippage_rate = slippage_rate or self.DEFAULT_SLIPPAGE_RATE

    # ------------------------------------------------------------------
    # 单笔成本计算
    # ------------------------------------------------------------------

    def estimate_cost(
        self,
        symbol: str = "",
        price: float = 0.0,
        quantity: int = 0,
        direction: int = 1,       # 1=买入, -1=卖出 (deprecated, 保留向后兼容)
        is_open: bool = True,     # True=开仓(买入), False=平仓(卖出)
    ) -> CostBreakdown:
        """预估单笔交易成本。

        Args:
            symbol: 股票代码
            price: 成交价格
            quantity: 成交数量（股）
            direction: 1=买入, -1=卖出（保留向后兼容，优先使用 is_open）
            is_open: True=开仓买入, False=平仓卖出
        """
        notional = price * quantity

        # 佣金：max(名义金额 × 万2.5, 5元)
        commission = max(notional * self.commission_rate, self.commission_min)

        # 印花税：仅卖出（平仓）时收取，名义金额 × 千0.5
        is_buy = is_open if direction == 1 else False
        stamp_tax = 0.0 if is_buy else notional * self.stamp_tax_rate

        # 过户费：双向，名义金额 × 万0.1
        transfer_fee = notional * self.transfer_fee_rate

        # 滑点：买入方向价格上浮，卖方向下浮
        slippage_dir = 1 if is_buy else -1
        slippage = notional * self.slippage_rate * slippage_dir

        total_cost = commission + stamp_tax + transfer_fee + abs(slippage)

        return CostBreakdown(
            symbol=symbol,
            price=price,
            quantity=quantity,
            notional=notional,
            commission=commission,
            stamp_tax=stamp_tax,
            transfer_fee=transfer_fee,
            slippage=slippage,
            total_cost=total_cost,
            net_proceeds=notional - total_cost if is_buy else notional - total_cost,
            cost_pct=total_cost / notional if notional > 0 else 0.0,
        )

    def calc_buy_cost(self, symbol: str, price: float, quantity: int) -> CostBreakdown:
        """计算买入成本（开仓）。"""
        return self.estimate_cost(symbol, price, quantity, direction=1, is_open=True)

    def calc_sell_cost(self, symbol: str, price: float, quantity: int) -> CostBreakdown:
        """计算卖出成本（平仓）。含印花税。"""
        return self.estimate_cost(symbol, price, quantity, direction=-1, is_open=False)

    def calc_roundtrip_cost(
        self, symbol: str, entry_price: float, exit_price: float, quantity: int,
    ) -> dict:
        """计算完整买卖往返成本。"""
        buy = self.calc_buy_cost(symbol, entry_price, quantity)
        sell = self.calc_sell_cost(symbol, exit_price, quantity)
        return {
            "buy_cost": buy,
            "sell_cost": sell,
            "total_roundtrip": buy.total_cost + sell.total_cost,
            "roundtrip_pct": (
                (buy.total_cost + sell.total_cost) / (entry_price * quantity)
                if entry_price > 0 and quantity > 0 else 0.0
            ),
        }

    # ------------------------------------------------------------------
    # 换手率估算
    # ------------------------------------------------------------------

    def estimate_annual_turnover_cost(
        self,
        annual_turnover: float,          # 年换手率（如5.0=500%）
        avg_notional_per_trade: float = 100000.0,
    ) -> float:
        """估算年化换手成本率。

        对于平均每笔 10 万的交易：
          - 买入成本 ~0.135%（万2.5 佣金 + 万0.1 过户费 + 千1 滑点）
          - 卖出成本 ~0.185%（同上 + 千0.5 印花税）
          - 往返成本 ~0.32%

        Args:
            annual_turnover: 年换手率（双边）
            avg_notional_per_trade: 平均每笔名义金额（用于最低佣金判断）

        Returns:
            年化成本率（相对于总资产的百分比）
        """
        cost_per_side = max(
            avg_notional_per_trade * self.commission_rate,
            self.commission_min,
        ) + avg_notional_per_trade * self.transfer_fee_rate + avg_notional_per_trade * self.slippage_rate

        buy_side = cost_per_side
        sell_side = cost_per_side + avg_notional_per_trade * self.stamp_tax_rate

        roundtrip = (buy_side + sell_side) / avg_notional_per_trade
        return roundtrip * annual_turnover

    # ------------------------------------------------------------------
    # 成本调整收益
    # ------------------------------------------------------------------

    @staticmethod
    def adjust_return(gross_return: float, cost_pct: float) -> float:
        """从毛收益扣除成本。

        Args:
            gross_return: 毛收益率（如 0.10 = 10%）
            cost_pct: 成本率（如 0.0032 = 0.32%）

        Returns:
            净收益率
        """
        return gross_return - cost_pct

    @staticmethod
    def breakeven_move(cost_pct: float) -> float:
        """计算覆盖交易成本所需的最小价格变动%。

        Args:
            cost_pct: 往返成本率

        Returns:
            需要的最小价格变动（如 0.0032 = 0.32%）
        """
        return cost_pct


# ------------------------------------------------------------------
# 便捷函数
# ------------------------------------------------------------------

def default_cost_calculator() -> AShareCostCalculator:
    """获取默认 A 股成本计算器。"""
    return AShareCostCalculator()


def quick_roundtrip_cost(
    entry_price: float, exit_price: float, quantity: int, symbol: str = "",
) -> dict:
    """快速计算往返成本。"""
    calc = AShareCostCalculator()
    return calc.calc_roundtrip_cost(symbol, entry_price, exit_price, quantity)
