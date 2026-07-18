# -*- coding: utf-8 -*-
"""短线机会发现器 — 检测技术突破/金叉/板块联动/游资异动。

每种机会类型输出一个 Alert，携带 severity + confidence。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from src.output.alert import Alert, AlertType

logger = logging.getLogger(__name__)


class OpportunityDetector:
    """短线机会发现器。

    检测类型:
      - TECH_BREAK: 放量突破关键阻力位
      - MA_GOLDEN_CROSS: MA5 上穿 MA20
      - VOLUME_SURGE: 成交量异常放大（主力介入）
      - SECTOR_LEADER: 板块龙头领涨
    """

    # 阈值常量
    BREAKOUT_VOL_MULT = 1.5      # 突破放量倍率
    MA_CROSS_DAYS = 3            # 金叉确认天数
    VOL_SURGE_MULT = 2.5         # 异常放量倍率
    SECTOR_LEAD_MIN_GAP = 2.0    # 龙头领先板块最小百分点

    def detect(
        self, quotes: dict[str, dict], market: dict
    ) -> list[Alert]:
        """从实时行情中检测机会信号。

        Args:
            quotes: {symbol: {price, volume, change_pct, high, low, ma5, ma20, avg_vol_20, ...}}
            market: {zt_count, zb_count, break_rate, sector_perf: {sector: change_pct}, ...}

        Returns:
            检测到的机会 Alert 列表
        """
        alerts: list[Alert] = []

        for symbol, q in quotes.items():
            name = q.get("name", symbol)
            price = q.get("price", 0) or 0
            if price <= 0:
                continue

            # 1. 放量突破
            breakout = self._check_breakout(symbol, name, q)
            if breakout:
                alerts.append(breakout)

            # 2. 均线金叉
            cross = self._check_golden_cross(symbol, name, q)
            if cross:
                alerts.append(cross)

            # 3. 异常放量
            surge = self._check_volume_surge(symbol, name, q)
            if surge:
                alerts.append(surge)

            # 4. 板块龙头
            leader = self._check_sector_leader(symbol, name, q, market)
            if leader:
                alerts.append(leader)

            # 5. 分歧/一致 多头机会
            consensus_forming = self._check_consensus_forming(symbol, name, q)
            if consensus_forming:
                alerts.append(consensus_forming)

            # 6. 分歧/一致 空头风险
            consensus_breaking = self._check_consensus_breaking(symbol, name, q)
            if consensus_breaking:
                alerts.append(consensus_breaking)

        return alerts

    def _check_breakout(
        self, symbol: str, name: str, q: dict
    ) -> Optional[Alert]:
        """检测放量突破。"""
        price = q.get("price", 0) or 0
        high_20d = q.get("high_20d", 0) or 0
        avg_vol_20 = q.get("avg_vol_20", 0) or 0
        volume = q.get("volume", 0) or 0

        if price > high_20d > 0 and avg_vol_20 > 0:
            vol_ratio = volume / avg_vol_20
            if vol_ratio >= self.BREAKOUT_VOL_MULT:
                return Alert(
                    symbol=symbol,
                    name=name,
                    alert_type=AlertType.TECH_BREAK,
                    severity="WARNING",
                    message=(
                        f"放量突破20日高点 {high_20d:.2f}，"
                        f"现价 {price:.2f} (+{((price - high_20d) / high_20d * 100):.1f}%)，"
                        f"量比 {vol_ratio:.1f}x"
                    ),
                    triggered_at=datetime.now(),
                )
        return None

    def _check_golden_cross(
        self, symbol: str, name: str, q: dict
    ) -> Optional[Alert]:
        """检测均线金叉。"""
        ma5 = q.get("ma5", 0) or 0
        ma20 = q.get("ma20", 0) or 0
        price = q.get("price", 0) or 0

        # 金叉确认: MA5 > MA20 且价格在两者上方
        if ma5 > ma20 > 0 and price > ma5:
            gap_pct = (ma5 - ma20) / ma20 * 100
            return Alert(
                symbol=symbol,
                name=name,
                alert_type=AlertType.MA_CROSS,
                severity="INFO",
                message=(
                    f"MA5({ma5:.2f}) 上穿 MA20({ma20:.2f}) 金叉，"
                    f"乖离 {gap_pct:.1f}%，现价 {price:.2f}"
                ),
                triggered_at=datetime.now(),
            )
        return None

    def _check_volume_surge(
        self, symbol: str, name: str, q: dict
    ) -> Optional[Alert]:
        """检测异常放量。"""
        avg_vol_20 = q.get("avg_vol_20", 0) or 0
        volume = q.get("volume", 0) or 0
        change_pct = q.get("change_pct", 0) or 0

        if avg_vol_20 > 0:
            vol_ratio = volume / avg_vol_20
            if vol_ratio >= self.VOL_SURGE_MULT:
                direction = "拉升" if change_pct > 0 else "下跌"
                return Alert(
                    symbol=symbol,
                    name=name,
                    alert_type=AlertType.VOL_SPIKE,
                    severity="WARNING",
                    message=(
                        f"异常放量{vol_ratio:.1f}x，{direction} {change_pct:+.2f}%，"
                        f"主力资金可能介入"
                    ),
                    triggered_at=datetime.now(),
                )
        return None

    def _check_sector_leader(
        self, symbol: str, name: str, q: dict, market: dict
    ) -> Optional[Alert]:
        """检测板块龙头领涨。"""
        change_pct = q.get("change_pct", 0) or 0
        sector = q.get("sector", "")

        if not sector or change_pct <= 0:
            return None

        sector_perf = market.get("sector_perf", {})
        sector_avg = sector_perf.get(sector, 0) or 0

        if sector_avg > 0 and change_pct - sector_avg >= self.SECTOR_LEAD_MIN_GAP:
            return Alert(
                symbol=symbol,
                name=name,
                alert_type=AlertType.TECH_BREAK,
                severity="INFO",
                message=(
                    f"板块龙头领涨: {name} +{change_pct:.2f}% "
                    f"vs {sector}板块 +{sector_avg:.2f}%，领先 {change_pct - sector_avg:.1f}pp"
                ),
                triggered_at=datetime.now(),
            )
        return None

    def _check_consensus_forming(
        self, symbol: str, name: str, q: dict
    ) -> Optional[Alert]:
        """检测一致/分歧转一致状态 → 多头机会。"""
        dc_state = q.get("divergence_consensus_state", "")
        dc_score = q.get("divergence_consensus_score", 50.0)

        if dc_state == "CONSENSUS" and dc_score >= 65:
            return Alert(
                symbol=symbol, name=name,
                alert_type=AlertType.DIVERGENCE_CONSENSUS,
                severity="INFO",
                message=(
                    f"缩量上涨一致状态: 卖盘枯竭，"
                    f"评分{dc_score:.0f}，趋势有望延续"
                ),
                triggered_at=datetime.now(),
            )
        elif dc_state == "FORMING_CONSENSUS" and dc_score >= 60:
            return Alert(
                symbol=symbol, name=name,
                alert_type=AlertType.DIVERGENCE_CONSENSUS,
                severity="WARNING",
                message=(
                    f"分歧转一致: 放量突破+缩量承接，"
                    f"评分{dc_score:.0f}，短线入场窗口"
                ),
                triggered_at=datetime.now(),
            )
        return None

    def _check_consensus_breaking(
        self, symbol: str, name: str, q: dict
    ) -> Optional[Alert]:
        """检测一致转分歧 → 空头警告。"""
        dc_state = q.get("divergence_consensus_state", "")

        if dc_state == "CONSENSUS_BREAKING":
            return Alert(
                symbol=symbol, name=name,
                alert_type=AlertType.DIVERGENCE_CONSENSUS,
                severity="WARNING",
                message=f"放量分歧/一致转分歧: 冲高回落，短线注意回调风险",
                triggered_at=datetime.now(),
            )
        return None
