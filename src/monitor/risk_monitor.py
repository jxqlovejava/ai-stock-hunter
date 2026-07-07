# -*- coding: utf-8 -*-
"""短线风险监控器 — 连板中断/天地板/流动性枯竭/北向突变/黑天鹅速报。"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from src.output.alert import Alert, AlertType

logger = logging.getLogger(__name__)


class RiskMonitor:
    """短线风险监控器。

    检测类型:
      - LIMIT_UP_BROKEN: 涨停炸板/连板中断
      - HEAVEN_HELL: 天地板（涨停→跌停）
      - LIQUIDITY_DRY: 流动性枯竭（成交额骤降）
      - NORTHBOUND_SURGE: 北向资金突变（大幅流出）
      - BLACK_SWAN: 指数异常波动
      - SUDDEN_DROP: 盘中急跌
    """

    # 阈值常量
    BREAK_RATE_ALERT = 0.45            # 炸板率 > 45% 预警
    NORTHBOUND_OUTFLOW_ALERT = -5.0    # 北向单日净流出 > 5B 预警
    HS300_DROP_ALERT = -2.0            # 沪深300 单日跌 > 2% 预警
    SUDDEN_DROP_PCT = -5.0             # 个股急跌 > 5% 预警
    VOLUME_COLLAPSE_RATIO = 0.15       # 成交额 < 20日均量15% = 枯竭

    def detect(
        self, quotes: dict[str, dict], market: dict
    ) -> list[Alert]:
        """从实时行情中检测风险信号。

        Args:
            quotes: {symbol: {price, volume, change_pct, limit_up, limit_down, avg_vol_20, ...}}
            market: {zt_count, zb_count, break_rate, hs300_change, northbound_net, ...}

        Returns:
            检测到的风险 Alert 列表
        """
        alerts: list[Alert] = []

        # 1. 打板情绪风险 (全局)
        limit_up_alerts = self._check_limit_up_sentiment(market)
        alerts.extend(limit_up_alerts)

        # 2. 北向突变 (全局)
        nb_alert = self._check_northbound_surge(market)
        if nb_alert:
            alerts.append(nb_alert)

        # 3. 指数异常 (全局)
        index_alert = self._check_index_anomaly(market)
        if index_alert:
            alerts.append(index_alert)

        # 4. 个股级别风险
        for symbol, q in quotes.items():
            name = q.get("name", symbol)

            # 天地板/连板中断
            heaven_hell = self._check_heaven_hell(symbol, name, q)
            if heaven_hell:
                alerts.append(heaven_hell)

            # 流动性枯竭
            liquidity = self._check_liquidity_dry(symbol, name, q)
            if liquidity:
                alerts.append(liquidity)

            # 盘中急跌
            sudden = self._check_sudden_drop(symbol, name, q)
            if sudden:
                alerts.append(sudden)

        return alerts

    def _check_limit_up_sentiment(self, market: dict) -> list[Alert]:
        """检查打板情绪退潮。"""
        alerts = []
        break_rate = market.get("break_rate", 0) or 0
        zt_count = market.get("zt_count", 0) or 0
        dt_count = market.get("dt_count", 0) or 0

        if break_rate > self.BREAK_RATE_ALERT:
            alerts.append(Alert(
                symbol="*",
                name="全市场",
                alert_type=AlertType.LIMIT_UP_BREAK,
                severity="CRITICAL" if break_rate > 0.6 else "WARNING",
                message=(
                    f"炸板潮预警: 涨停{zt_count}家/炸板{break_rate:.0%}/跌停{dt_count}家，"
                    "打板情绪退潮，追高风险极大"
                ),
                triggered_at=datetime.now(),
            ))

        # 跌停家数异常
        if dt_count > 50:
            alerts.append(Alert(
                symbol="*",
                name="全市场",
                alert_type=AlertType.RISK_FLASH,
                severity="CRITICAL",
                message=f"跌停潮: {dt_count}家跌停，恐慌情绪蔓延",
                triggered_at=datetime.now(),
            ))

        return alerts

    def _check_northbound_surge(self, market: dict) -> Optional[Alert]:
        """检查北向资金突变。"""
        nb_net = market.get("northbound_net", 0) or 0  # 亿元

        if nb_net <= self.NORTHBOUND_OUTFLOW_ALERT:
            return Alert(
                symbol="*",
                name="北向资金",
                alert_type=AlertType.NORTHBOUND_SURGE,
                severity="CRITICAL" if nb_net < -10.0 else "WARNING",
                message=f"北向资金大幅流出 {nb_net:.0f}亿，外资撤离信号",
                triggered_at=datetime.now(),
            )
        return None

    def _check_index_anomaly(self, market: dict) -> Optional[Alert]:
        """检查指数异常波动。"""
        hs300 = market.get("hs300_change", 0) or 0

        if hs300 <= self.HS300_DROP_ALERT:
            return Alert(
                symbol="*",
                name="沪深300",
                alert_type=AlertType.RISK_FLASH,
                severity="CRITICAL" if hs300 < -4.0 else "WARNING",
                message=f"沪深300急跌 {hs300:+.2f}%，系统性风险警报",
                triggered_at=datetime.now(),
            )
        return None

    def _check_heaven_hell(
        self, symbol: str, name: str, q: dict
    ) -> Optional[Alert]:
        """检测天地板/连板中断。"""
        is_limit_up = q.get("is_limit_up", False)
        was_limit_up = q.get("was_limit_up_prev", False)
        is_limit_down = q.get("is_limit_down", False)

        # 涨停→跌停 (天地板)
        if was_limit_up and is_limit_down:
            return Alert(
                symbol=symbol,
                name=name,
                alert_type=AlertType.LIMIT_UP_BREAK,
                severity="CRITICAL",
                message=f"天地板: {name} 昨日涨停→今日跌停，极端风险",
                triggered_at=datetime.now(),
            )

        # 涨停炸板
        if was_limit_up and not is_limit_up and q.get("change_pct", -10) < 5:
            return Alert(
                symbol=symbol,
                name=name,
                alert_type=AlertType.LIMIT_UP_BREAK,
                severity="WARNING",
                message=f"涨停炸板: {name} 开板回落，封板失败",
                triggered_at=datetime.now(),
            )

        return None

    def _check_liquidity_dry(
        self, symbol: str, name: str, q: dict
    ) -> Optional[Alert]:
        """检测流动性枯竭。"""
        volume = q.get("volume", 0) or 0
        avg_vol_20 = q.get("avg_vol_20", 0) or 0

        if avg_vol_20 > 0 and volume / avg_vol_20 < self.VOLUME_COLLAPSE_RATIO:
            return Alert(
                symbol=symbol,
                name=name,
                alert_type=AlertType.VOL_SPIKE,
                severity="WARNING",
                message=f"流动性枯竭: 成交额仅均量的 {volume / avg_vol_20:.0%}",
                triggered_at=datetime.now(),
            )
        return None

    def _check_sudden_drop(
        self, symbol: str, name: str, q: dict
    ) -> Optional[Alert]:
        """检测盘中急跌。"""
        change_pct = q.get("change_pct", 0) or 0

        if change_pct <= self.SUDDEN_DROP_PCT:
            return Alert(
                symbol=symbol,
                name=name,
                alert_type=AlertType.RISK_FLASH,
                severity="CRITICAL" if change_pct < -8.0 else "WARNING",
                message=f"盘中急跌 {change_pct:+.2f}%，注意风险",
                triggered_at=datetime.now(),
            )
        return None
