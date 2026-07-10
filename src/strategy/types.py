"""Strategy engine type definitions — shared contract for all sub-engines."""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class StrategySignal:
    """Unified signal produced by strategy sub-engines.

    Attributes:
        symbol: stock code
        action: ENTER / EXIT / ADD / REDUCE / HOLD
        direction: LONG / SHORT
        strength: 0.0-1.0 confidence
        quantity: suggested shares (0 = to be sized)
        weight_pct: target portfolio weight %
        reason: human-readable rationale
        urgency: HIGH (must act today) / NORMAL / LOW (can wait)
    """

    symbol: str
    action: str  # ENTER | EXIT | ADD | REDUCE | HOLD
    direction: str = "LONG"
    strength: float = 0.5
    quantity: int = 0
    weight_pct: float = 0.0
    reason: str = ""
    urgency: str = "NORMAL"

    @property
    def is_entry(self) -> bool:
        return self.action == "ENTER"

    @property
    def is_exit(self) -> bool:
        return self.action == "EXIT"

    @property
    def is_add(self) -> bool:
        return self.action == "ADD"

    @property
    def is_reduce(self) -> bool:
        return self.action == "REDUCE"


@dataclass
class PositionSize:
    """Calculated position size for a trade."""

    quantity: int           # shares (rounded to board lot)
    weight_pct: float       # % of total portfolio
    risk_pct: float         # % of portfolio at risk if stopped out
    kelly_fraction: float   # raw Kelly f* (for reference)
    sizing_method: str      # "kelly" | "vol_target" | "fixed_fractional" | "equal_weight"


@dataclass
class ExitCheckResult:
    """Result of checking a single position against exit rules."""

    symbol: str
    should_exit: bool
    reason: str
    urgency: str = "NORMAL"       # HIGH / NORMAL
    exit_pct: float = 100.0       # % of position to exit
    rule_triggered: str = ""      # which rule fired
    current_pnl_pct: float = 0.0
    atr: float = 0.0


@dataclass
class AddCheckResult:
    """Result of checking if a position should be added to."""

    symbol: str
    should_add: bool
    reason: str = ""
    add_method: str = ""          # "pyramid" | "equal" | "signal"
    add_fraction: float = 0.0     # fraction of original position size to add


@dataclass
class PortfolioSnapshot:
    """Minimal portfolio state for strategy decisions."""

    total_equity: float
    cash: float
    positions: dict = field(default_factory=dict)  # {symbol: {shares, entry_price, current_price, pnl_pct, stop_price}}
    timestamp: str = ""
