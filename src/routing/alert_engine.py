# -*- coding: utf-8 -*-
"""价位预警引擎 — 借鉴 go-stock 价位线预警系统。

独立于风控熔断机制，提供 5 种持仓/自选价位预警：
  1. 涨跌幅预警 — |change_pct| ≥ 设定阈值
  2. 股价预警   — 当前价触及设定价格
  3. 成本盈亏预警 — |盈亏%| ≥ 设定阈值
  4. 止盈触及   — 当前价 ≥ 止盈价
  5. 止损触及   — 当前价 ≤ 止损价

防抖机制：同一价格不重复提醒，两次通知间隔 ≥ 60s。
存储：data/price_alerts.json（JSON 持久化）。
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# 存储路径
_ALERTS_PATH = Path("data/price_alerts.json")
_POSITIONS_PATH = Path("data/positions.json")
_WATCHLIST_PATH = Path("data/watchlist.json")

# 防抖间隔（秒）
_DEBOUNCE_SECONDS = 60


# ── 数据模型 ────────────────────────────────────────────────────────────


class AlertType(str, Enum):
    CHANGE_PCT = "change_pct"        # 涨跌幅预警
    PRICE = "price"                  # 股价预警
    PNL = "pnl"                      # 成本盈亏预警
    TAKE_PROFIT = "take_profit"      # 止盈触及
    STOP_LOSS = "stop_loss"          # 止损触及


class AlertPriority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


ALERT_PRIORITY_MAP: dict[AlertType, AlertPriority] = {
    AlertType.CHANGE_PCT: AlertPriority.MEDIUM,
    AlertType.PRICE: AlertPriority.HIGH,
    AlertType.PNL: AlertPriority.MEDIUM,
    AlertType.TAKE_PROFIT: AlertPriority.HIGH,
    AlertType.STOP_LOSS: AlertPriority.CRITICAL,
}


@dataclass
class PriceAlert:
    """单条价位预警配置。"""
    symbol: str
    name: str = ""
    alert_type: AlertType = AlertType.PRICE
    priority: AlertPriority = AlertPriority.MEDIUM
    threshold: float = 0.0   # 阈值（% 或 价格）
    direction: str = "above"  # above / below / cross
    enabled: bool = True
    last_triggered_at: Optional[str] = None
    last_triggered_price: float = 0.0
    triggered_count: int = 0


@dataclass
class AlertCheckResult:
    """预警检查结果。"""
    symbol: str
    name: str = ""
    alert: Optional[PriceAlert] = None
    triggered: bool = False
    current_price: float = 0.0
    current_change_pct: float = 0.0
    message: str = ""
    timestamp: str = ""


# ── 预警引擎 ────────────────────────────────────────────────────────────


class AlertEngine:
    """价位预警引擎。

    用法:
        engine = AlertEngine()
        results = engine.check_all(price_provider=my_price_func)
        for r in results:
            if r.triggered:
                print(f"⚠️ {r.message}")
    """

    def __init__(self):
        self._alerts: dict[str, list[PriceAlert]] = {}
        self._load()

    # ------------------------------------------------------------------
    # 持久化
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """从 JSON 文件加载预警配置。"""
        if not _ALERTS_PATH.exists():
            return
        try:
            raw = json.loads(_ALERTS_PATH.read_text(encoding="utf-8"))
            self._alerts = {}
            for symbol, alert_list in raw.items():
                self._alerts[symbol] = [
                    PriceAlert(
                        symbol=a.get("symbol", symbol),
                        name=a.get("name", ""),
                        alert_type=AlertType(a["alert_type"]),
                        priority=AlertPriority(a.get("priority", "medium")),
                        threshold=a.get("threshold", 0.0),
                        direction=a.get("direction", "above"),
                        enabled=a.get("enabled", True),
                        last_triggered_at=a.get("last_triggered_at"),
                        last_triggered_price=a.get("last_triggered_price", 0.0),
                        triggered_count=a.get("triggered_count", 0),
                    )
                    for a in alert_list
                ]
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning(f"加载 price_alerts.json 失败: {e}")
            self._alerts = {}

    def _save(self) -> None:
        """持久化预警配置到 JSON 文件。"""
        _ALERTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        data: dict[str, list[dict]] = {}
        for symbol, alert_list in self._alerts.items():
            data[symbol] = [
                {
                    "symbol": a.symbol,
                    "name": a.name,
                    "alert_type": a.alert_type.value,
                    "priority": a.priority.value,
                    "threshold": a.threshold,
                    "direction": a.direction,
                    "enabled": a.enabled,
                    "last_triggered_at": a.last_triggered_at,
                    "last_triggered_price": a.last_triggered_price,
                    "triggered_count": a.triggered_count,
                }
                for a in alert_list
            ]
        _ALERTS_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def add_alert(self, alert: PriceAlert) -> None:
        """添加一条预警。同 symbol + type 去重（覆盖）。"""
        existing = self._alerts.get(alert.symbol, [])
        # 去重：相同类型覆盖
        existing = [a for a in existing if a.alert_type != alert.alert_type]
        existing.append(alert)
        self._alerts[alert.symbol] = existing
        self._save()

    def remove_alert(self, symbol: str, alert_type: AlertType) -> bool:
        """移除指定预警。"""
        if symbol not in self._alerts:
            return False
        before = len(self._alerts[symbol])
        self._alerts[symbol] = [
            a for a in self._alerts[symbol] if a.alert_type != alert_type
        ]
        if not self._alerts[symbol]:
            del self._alerts[symbol]
        if len(self._alerts.get(symbol, [])) != before:
            self._save()
            return True
        return False

    def list_alerts(self, symbol: Optional[str] = None) -> list[PriceAlert]:
        """列出预警配置。"""
        if symbol:
            return self._alerts.get(symbol, [])
        return [a for alerts in self._alerts.values() for a in alerts]

    # ------------------------------------------------------------------
    # 从持仓/自选股自动生成预警
    # ------------------------------------------------------------------

    def sync_from_positions(self) -> int:
        """从 positions.json 同步止损/止盈预警。"""
        if not _POSITIONS_PATH.exists():
            return 0

        try:
            positions = json.loads(_POSITIONS_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"读取 positions.json 失败: {e}")
            return 0

        added = 0
        for symbol, pos in positions.items():
            if not isinstance(pos, dict):
                continue
            name = pos.get("name", "")
            entry_price = pos.get("entry_price", 0)
            stop_price = pos.get("stop_price", 0)
            quantity = pos.get("quantity", 0)

            if stop_price and stop_price > 0:
                self.add_alert(PriceAlert(
                    symbol=symbol,
                    name=name,
                    alert_type=AlertType.STOP_LOSS,
                    priority=AlertPriority.CRITICAL,
                    threshold=stop_price,
                    direction="below",
                ))
                added += 1

            # 止盈价 = 成本价 + 20%（默认，可手动调整）
            if entry_price and entry_price > 0 and quantity > 0:
                take_profit = round(entry_price * 1.20, 2)
                self.add_alert(PriceAlert(
                    symbol=symbol,
                    name=name,
                    alert_type=AlertType.TAKE_PROFIT,
                    priority=AlertPriority.HIGH,
                    threshold=take_profit,
                    direction="above",
                ))
                added += 1

            # 涨跌幅预警（±5%）
            self.add_alert(PriceAlert(
                symbol=symbol,
                name=name,
                alert_type=AlertType.CHANGE_PCT,
                priority=AlertPriority.MEDIUM,
                threshold=5.0,
                direction="cross",
            ))
            added += 1

        if added:
            self._save()
        return added

    # ------------------------------------------------------------------
    # 检查
    # ------------------------------------------------------------------

    def check_all(
        self,
        price_provider,
    ) -> list[AlertCheckResult]:
        """检查所有已启用预警。

        Args:
            price_provider: callable(symbol) → dict with
                price, change_pct, name

        Returns:
            所有预警的检查结果列表
        """
        results: list[AlertCheckResult] = []
        now = datetime.now().isoformat()

        for symbol, alerts in self._alerts.items():
            # 获取实时价格
            try:
                quote = price_provider(symbol)
                if not quote:
                    continue
                price = float(quote.get("price", 0))
                change_pct = float(quote.get("change_pct", 0))
                name = str(quote.get("name", ""))
            except Exception as e:
                logger.debug(f"获取 {symbol} 行情失败: {e}")
                continue

            for alert in alerts:
                if not alert.enabled:
                    continue

                triggered = False
                message = ""

                if alert.alert_type == AlertType.CHANGE_PCT:
                    if abs(change_pct) >= alert.threshold:
                        triggered = True
                        direction = "上涨" if change_pct > 0 else "下跌"
                        message = (
                            f"📊 {name}({symbol}) {direction}{abs(change_pct):.1f}%，"
                            f"触发涨跌幅预警（阈值 ±{alert.threshold}%）"
                        )

                elif alert.alert_type == AlertType.PRICE:
                    if alert.direction == "above" and price >= alert.threshold:
                        triggered = True
                        message = f"📈 {name}({symbol}) 现价 {price:.2f} ≥ 预警价 {alert.threshold:.2f}"
                    elif alert.direction == "below" and price <= alert.threshold:
                        triggered = True
                        message = f"📉 {name}({symbol}) 现价 {price:.2f} ≤ 预警价 {alert.threshold:.2f}"

                elif alert.alert_type == AlertType.TAKE_PROFIT:
                    if price >= alert.threshold:
                        triggered = True
                        message = (
                            f"🎯 止盈触发！{name}({symbol}) 现价 {price:.2f} ≥ "
                            f"止盈价 {alert.threshold:.2f}，建议分批兑现盈利"
                        )

                elif alert.alert_type == AlertType.STOP_LOSS:
                    if price <= alert.threshold:
                        triggered = True
                        message = (
                            f"🛑 止损触发！{name}({symbol}) 现价 {price:.2f} ≤ "
                            f"止损价 {alert.threshold:.2f}，建议立即减仓/清仓"
                        )

                elif alert.alert_type == AlertType.PNL:
                    # PNL 需要成本价，从 positions.json 获取
                    pnl_pct = _get_pnl_pct(symbol, price)
                    if pnl_pct is not None and abs(pnl_pct) >= alert.threshold:
                        triggered = True
                        direction = "盈利" if pnl_pct > 0 else "亏损"
                        message = (
                            f"💰 {name}({symbol}) {direction}{abs(pnl_pct):.1f}%，"
                            f"触发盈亏预警（阈值 ±{alert.threshold}%）"
                        )

                # 防抖检查
                if triggered:
                    should_fire = _check_debounce(alert)
                    if should_fire:
                        alert.last_triggered_at = now
                        alert.last_triggered_price = price
                        alert.triggered_count += 1
                    else:
                        triggered = False

                results.append(AlertCheckResult(
                    symbol=symbol,
                    name=name,
                    alert=alert,
                    triggered=triggered,
                    current_price=price,
                    current_change_pct=change_pct,
                    message=message,
                    timestamp=now,
                ))

        # 持久化更新后的触发状态
        self._save()
        return results

    def get_triggered(self, price_provider) -> list[AlertCheckResult]:
        """仅返回已触发的预警。"""
        return [r for r in self.check_all(price_provider) if r.triggered]


# ── 辅助函数 ────────────────────────────────────────────────────────────


def _check_debounce(alert: PriceAlert) -> bool:
    """防抖检查：同一价格不重复提醒，60s 内不重复。"""
    if alert.last_triggered_at is None:
        return True
    try:
        last = datetime.fromisoformat(alert.last_triggered_at)
        elapsed = (datetime.now() - last).total_seconds()
        return elapsed >= _DEBOUNCE_SECONDS
    except (ValueError, TypeError):
        return True


def _get_pnl_pct(symbol: str, current_price: float) -> Optional[float]:
    """从 positions.json 计算当前盈亏百分比。"""
    if not _POSITIONS_PATH.exists():
        return None
    try:
        positions = json.loads(_POSITIONS_PATH.read_text(encoding="utf-8"))
        pos = positions.get(symbol)
        if not pos or not isinstance(pos, dict):
            return None
        entry = pos.get("entry_price", 0)
        if entry <= 0:
            return None
        return (current_price - entry) / entry * 100
    except (json.JSONDecodeError, OSError):
        return None


def get_alert_summary(results: list[AlertCheckResult]) -> str:
    """生成预警结果摘要文本。"""
    triggered = [r for r in results if r.triggered]
    if not triggered:
        return "✅ 所有预警正常，无触发项"

    lines = ["⚠️ 预警触发汇总:"]
    for r in sorted(triggered, key=lambda x: x.alert.priority.value if x.alert else "low", reverse=True):
        priority_icon = {
            AlertPriority.CRITICAL: "🔴",
            AlertPriority.HIGH: "🟠",
            AlertPriority.MEDIUM: "🟡",
            AlertPriority.LOW: "🟢",
        }.get(r.alert.priority if r.alert else AlertPriority.LOW, "⚪")
        lines.append(f"  {priority_icon} {r.message}")
    return "\n".join(lines)
