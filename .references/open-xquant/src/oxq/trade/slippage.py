"""Slippage models for simulated trading."""

from __future__ import annotations

from decimal import Decimal
from typing import Protocol, runtime_checkable

from oxq.core.types import Order


@runtime_checkable
class SlippageModel(Protocol):
    """Protocol for price slippage simulation.

    Implementations adjust the raw fill price to simulate market
    impact. BUY orders typically receive a higher price (worse fill),
    SELL orders a lower price.
    """

    def adjust(self, order: Order, price: Decimal) -> Decimal:
        """Adjust the fill price to account for slippage.

        Parameters
        ----------
        order : Order
            The order being filled.
        price : Decimal
            The raw price (e.g. bar close) before slippage.

        Returns
        -------
        Decimal
            Adjusted fill price.
        """
        ...


class PercentageSlippage:
    """Slippage as a fixed percentage of price.

    BUY orders are filled at ``price * (1 + rate)`` (worse),
    SELL orders at ``price * (1 - rate)`` (worse).

    Parameters
    ----------
    rate : Decimal
        Slippage rate as a decimal fraction.
        Default is Decimal("0.001") (0.1%).

    Examples
    --------
    >>> broker = SimBroker(slippage_model=PercentageSlippage())
    """

    def __init__(self, rate: Decimal = Decimal("0.001")) -> None:
        self.rate = rate

    def adjust(self, order: Order, price: Decimal) -> Decimal:
        """Adjust price: BUY gets worse (higher), SELL gets worse (lower)."""
        if order.side == "BUY":
            return price * (1 + self.rate)
        return price * (1 - self.rate)
