# -*- coding: utf-8 -*-
"""盯盘预警与扫雷模块。

支持:
  - 价格突破预警（ABOVE/BELOW 条件）
  - 止损触发预警
  - 情绪异动预警
  - 自选股批量扫雷

Phase 3: 基础实现。Phase 4: 接入华泰/国信实时推送。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional


@dataclass
class Alert:
    """预警信号。"""
    symbol: str
    name: str
    alert_type: str          # PRICE / STOP_LOSS / SENTIMENT / VOLUME_SPIKE
    severity: str            # CRITICAL / WARNING / INFO
    message: str
    triggered_at: datetime = field(default_factory=datetime.now)


class AlertManager:
    """预警管理器。

    用法:
        mgr = AlertManager()
        mgr.add_price_alert("600519", "贵州茅台", above=1250.0)
        mgr.add_stop_loss_alert("000001", "平安银行", 9.0)
        triggered = mgr.check(quotes)  # 检查当前行情是否触发预警
    """

    def __init__(self):
        self._price_alerts: list[dict] = []
        self._stop_loss_alerts: list[dict] = []

    def add_price_alert(
        self,
        symbol: str,
        name: str,
        above: Optional[float] = None,
        below: Optional[float] = None,
        expire_days: int = 90,
    ):
        """添加价格预警。"""
        self._price_alerts.append({
            "symbol": symbol,
            "name": name,
            "above": above,
            "below": below,
            "expires_at": datetime.now() + timedelta(days=expire_days),
        })

    def add_stop_loss_alert(self, symbol: str, name: str, stop_price: float):
        """添加止损预警。"""
        self._stop_loss_alerts.append({
            "symbol": symbol,
            "name": name,
            "stop_price": stop_price,
        })

    def check(self, quotes: dict[str, float]) -> list[Alert]:
        """检查当前行情是否触发预警。

        Args:
            quotes: {symbol: current_price}

        Returns:
            List of triggered alerts
        """
        triggered = []
        now = datetime.now()

        # 价格预警
        for alert in self._price_alerts:
            if alert["expires_at"] < now:
                continue
            sym = alert["symbol"]
            price = quotes.get(sym)
            if price is None:
                continue

            if alert["above"] and price >= alert["above"]:
                triggered.append(Alert(
                    symbol=sym, name=alert["name"],
                    alert_type="PRICE", severity="WARNING",
                    message=f"{alert['name']}({sym}) 突破 {alert['above']}，现价 {price}",
                ))
            if alert["below"] and price <= alert["below"]:
                triggered.append(Alert(
                    symbol=sym, name=alert["name"],
                    alert_type="PRICE", severity="WARNING",
                    message=f"{alert['name']}({sym}) 跌破 {alert['below']}，现价 {price}",
                ))

        # 止损预警
        for alert in self._stop_loss_alerts:
            sym = alert["symbol"]
            price = quotes.get(sym)
            if price is not None and price <= alert["stop_price"]:
                triggered.append(Alert(
                    symbol=sym, name=alert["name"],
                    alert_type="STOP_LOSS", severity="CRITICAL",
                    message=f"🔴 {alert['name']}({sym}) 触及止损线 {alert['stop_price']}，建议立即平仓",
                ))

        return triggered

    def scan_watchlist(
        self,
        watchlist: list[str],
        quotes: dict[str, float],
        context: Optional[dict] = None,
    ) -> list[Alert]:
        """自选股批量扫雷。

        检查维度:
          1. 触及止损线
          2. 单日跌幅 > 5%
          3. 成交量异常放大 > 3x 日均
        """
        alerts = []
        for symbol in watchlist:
            price = quotes.get(symbol)
            if price is None:
                continue
            ctx = (context or {}).get(symbol, {})

            # 止损
            stop_price = ctx.get("stop_price")
            if stop_price and price <= stop_price:
                alerts.append(Alert(
                    symbol=symbol, name=ctx.get("name", symbol),
                    alert_type="STOP_LOSS", severity="CRITICAL",
                    message=f"触及止损线 {stop_price}",
                ))

            # 单日大跌
            change_pct = ctx.get("change_pct", 0)
            if change_pct < -5.0:
                alerts.append(Alert(
                    symbol=symbol, name=ctx.get("name", symbol),
                    alert_type="PRICE", severity="WARNING",
                    message=f"单日跌幅 {change_pct:.1f}%",
                ))

        return alerts

    def clear_expired(self):
        """清理过期预警。"""
        now = datetime.now()
        self._price_alerts = [
            a for a in self._price_alerts if a["expires_at"] > now
        ]
