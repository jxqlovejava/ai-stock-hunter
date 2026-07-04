"""Tests for SlippageModel."""

from decimal import Decimal

from oxq.core.types import Order
from oxq.trade.slippage import PercentageSlippage, SlippageModel


def test_percentage_slippage_satisfies_protocol() -> None:
    assert isinstance(PercentageSlippage(), SlippageModel)


def test_slippage_buy_price_increases() -> None:
    model = PercentageSlippage(rate=Decimal("0.001"))
    order = Order(symbol="AAPL", side="BUY", shares=100)
    adjusted = model.adjust(order, Decimal("150"))
    assert adjusted == Decimal("150") * (1 + Decimal("0.001"))
    assert adjusted > Decimal("150")


def test_slippage_sell_price_decreases() -> None:
    model = PercentageSlippage(rate=Decimal("0.001"))
    order = Order(symbol="AAPL", side="SELL", shares=100)
    adjusted = model.adjust(order, Decimal("150"))
    assert adjusted == Decimal("150") * (1 - Decimal("0.001"))
    assert adjusted < Decimal("150")
