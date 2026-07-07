# -*- coding: utf-8 -*-
"""盯盘引擎 — 定时拉取行情，检测预警条件，输出 Alert 列表。

主入口: Watchdog.run_once() 执行单次扫描；Watchdog.run_loop() 持续运行。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from src.monitor.opportunity_detector import OpportunityDetector
from src.monitor.risk_monitor import RiskMonitor
from src.output.alert import Alert, AlertManager, AlertType

logger = logging.getLogger(__name__)


@dataclass
class WatchdogConfig:
    """盯盘配置。"""
    symbols: list[str] = field(default_factory=list)         # 监控标的列表
    interval_seconds: int = 60                                # 扫描间隔
    enable_opportunity: bool = True                           # 启用机会发现
    enable_risk: bool = True                                  # 启用风险监控
    quiet_hours_start: str = ""                               # "22:00"
    quiet_hours_end: str = ""                                 # "08:00"
    min_interval_per_symbol: int = 60                         # 同一标的最短重复预警间隔


class Watchdog:
    """盯盘主引擎。

    用法:
        config = WatchdogConfig(symbols=["000001", "000002"], interval_seconds=60)
        dog = Watchdog(config)
        alerts = dog.run_once(quotes)  # 单次扫描
        # dog.run_loop(get_quotes_fn)  # 持续运行 (阻塞)
    """

    def __init__(self, config: WatchdogConfig):
        self._config = config
        self._alert_mgr = AlertManager()
        self._opportunity = OpportunityDetector() if config.enable_opportunity else None
        self._risk_monitor = RiskMonitor() if config.enable_risk else None
        self._last_alert_time: dict[str, dict[str, float]] = {}  # {symbol: {type: timestamp}}
        self._running = False

    @property
    def config(self) -> WatchdogConfig:
        return self._config

    def run_once(
        self, quotes: dict[str, dict], market_context: dict | None = None
    ) -> list[Alert]:
        """执行单次扫描，返回触发预警列表。

        Args:
            quotes: {symbol: {price, volume, change_pct, high, low, turnover, ...}}
            market_context: {zt_count, zb_count, break_rate, hs300_change, northbound_net, ...}

        Returns:
            触发的 Alert 列表
        """
        all_alerts: list[Alert] = []

        # 静默时段检查
        if self._is_quiet_hours():
            return all_alerts

        # 价格预警
        triggered = self._alert_mgr.check(
            {s: q.get("price", 0) or 0 for s, q in quotes.items()}
        )
        all_alerts.extend(triggered)

        # 机会发现
        if self._opportunity:
            opp_alerts = self._opportunity.detect(quotes, market_context or {})
            all_alerts.extend(opp_alerts)

        # 风险监控
        if self._risk_monitor:
            risk_alerts = self._risk_monitor.detect(quotes, market_context or {})
            all_alerts.extend(risk_alerts)

        # 去重+节流
        filtered = self._throttle(all_alerts)

        if filtered:
            logger.info("盯盘触发 %d 条预警", len(filtered))

        return filtered

    def run_loop(
        self,
        get_quotes_fn,
        get_market_context_fn=None,
        max_iterations: int = 0,
    ) -> None:
        """持续运行盯盘循环（阻塞）。

        Args:
            get_quotes_fn: () -> dict[str, dict] 获取最新行情
            get_market_context_fn: () -> dict 获取市场上下文
            max_iterations: 最大循环次数，0=无限
        """
        self._running = True
        iteration = 0
        logger.info(
            "盯盘启动: %d 标的, 间隔 %ds",
            len(self._config.symbols), self._config.interval_seconds,
        )

        while self._running:
            if max_iterations > 0 and iteration >= max_iterations:
                break

            try:
                quotes = get_quotes_fn()
                market = get_market_context_fn() if get_market_context_fn else None
                alerts = self.run_once(
                    {s: q for s, q in quotes.items() if s in self._config.symbols},
                    market,
                )

                for alert in alerts:
                    self._print_alert(alert)

            except Exception:
                logger.exception("盯盘扫描异常")

            iteration += 1
            if self._running:
                time.sleep(self._config.interval_seconds)

        logger.info("盯盘停止: %d 次扫描", iteration)

    def stop(self) -> None:
        """停止盯盘循环。"""
        self._running = False

    def add_price_alert(self, symbol: str, name: str, above=None, below=None) -> None:
        """添加价格预警。"""
        self._alert_mgr.add_price_alert(symbol, name, above=above, below=below)

    def add_stop_loss_alert(self, symbol: str, name: str, stop_price: float) -> None:
        """添加止损预警。"""
        self._alert_mgr.add_stop_loss_alert(symbol, name, stop_price)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _is_quiet_hours(self) -> bool:
        """检测是否在静默时段。"""
        cfg = self._config
        if not cfg.quiet_hours_start or not cfg.quiet_hours_end:
            return False
        now = datetime.now().strftime("%H:%M")
        return cfg.quiet_hours_start <= now or now <= cfg.quiet_hours_end

    def _throttle(self, alerts: list[Alert]) -> list[Alert]:
        """节流：同标的同类型预警在 min_interval 内不重复。"""
        now = time.time()
        min_interval = self._config.min_interval_per_symbol
        result = []
        for alert in alerts:
            key = f"{alert.symbol}:{alert.alert_type.value if hasattr(alert.alert_type, 'value') else alert.alert_type}"
            last = self._last_alert_time.get(alert.symbol, {}).get(key, 0)
            if now - last >= min_interval:
                result.append(alert)
                self._last_alert_time.setdefault(alert.symbol, {})[key] = now
        return result

    @staticmethod
    def _print_alert(alert: Alert) -> None:
        emoji_map = {
            "CRITICAL": "🔴",
            "WARNING": "🟡",
            "INFO": "🔵",
        }
        emoji = emoji_map.get(alert.severity, "⚪")
        print(
            f"  {emoji} [{alert.alert_type}] {alert.name}({alert.symbol}): "
            f"{alert.message}"
        )
