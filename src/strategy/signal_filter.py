# -*- coding: utf-8 -*-
"""信号质量过滤器 — 入场信号交叉验证，检测 A 股常见操纵模式。

每个 ENTER 信号在通过前必须经过以下检查:
  1. Bull Trap 检测   — 价格涨+主力流出 = 拉高出货
  2. 席位对倒检测     — 同席位买卖抵消 = 虚假成交量
  3. 封板诱多检测     — 涨停但封单薄弱 = 次日低开
  4. 量价背离检测     — 放量但价格不动 = 出货
  5. 劣迹席位检测     — 低信誉游资 = 跟风风险

FilterResult: {pass: bool, adjusted_strength: float, warnings: list[str]}
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from .types import StrategySignal

logger = logging.getLogger(__name__)


@dataclass
class FilterResult:
    """Result of signal quality filtering."""

    passed: bool
    original_strength: float
    adjusted_strength: float
    warnings: list[str] = field(default_factory=list)
    blocked_by: str = ""

    @property
    def is_blocked(self) -> bool:
        return not self.passed


class SignalQualityFilter:
    """Cross-validate entry signals against A-share manipulation patterns.

    Usage::

        f = SignalQualityFilter()
        result = f.check(signal, market_data)
        if not result.passed:
            print(f"信号被拦截: {result.blocked_by}")
    """

    # ── 拦截阈值 ──
    MIN_STRENGTH_FOR_ENTRY = 0.30      # 低于此强度的信号直接丢弃
    BULL_TRAP_PENALTY = 0.30           # Bull Trap 时强度乘数
    SEAT_WASH_PENALTY = 0.0            # 对倒 → 直接拦截
    WEAK_SEAL_PENALTY = 0.50           # 弱封板乘数
    VOL_DIVERGENCE_PENALTY = 0.50      # 量价背离乘数
    BAD_SEAT_PENALTY = 0.60            # 劣迹席位乘数

    def __init__(self, **overrides):
        for k, v in overrides.items():
            if hasattr(self, k):
                setattr(self, k, v)

    # ------------------------------------------------------------------
    # public
    # ------------------------------------------------------------------

    def check(self, signal: StrategySignal, market_data: dict) -> FilterResult:
        """Run all quality checks against a signal. Returns FilterResult."""
        if signal.action != "ENTER":
            return FilterResult(passed=True, original_strength=signal.strength, adjusted_strength=signal.strength)

        warnings: list[str] = []
        multiplier = 1.0
        blocked = False
        blocked_by = ""

        # 1. Bull Trap — 拉高出货
        bt_mult, bt_warn, bt_block = self._check_bull_trap(signal, market_data)
        multiplier *= bt_mult
        if bt_warn:
            warnings.append(bt_warn)
        if bt_block:
            blocked = True
            blocked_by = "Bull Trap: 价格涨但主力资金流出，疑似拉高出货"

        # 2. 席位对倒 — 虚假成交量
        sw_mult, sw_warn, sw_block = self._check_seat_wash(signal, market_data)
        multiplier *= sw_mult
        if sw_warn:
            warnings.append(sw_warn)
        if sw_block:
            blocked = True
            blocked_by = "席位对倒: 买卖同席位且净额接近零，虚假成交量"

        # 3. 封板诱多 — 弱封板
        ws_mult, ws_warn, _ = self._check_weak_seal(signal, market_data)
        multiplier *= ws_mult
        if ws_warn:
            warnings.append(ws_warn)

        # 4. 量价背离 — 放量不涨
        vd_mult, vd_warn, _ = self._check_vol_divergence(signal, market_data)
        multiplier *= vd_mult
        if vd_warn:
            warnings.append(vd_warn)

        # 5. 劣迹席位 — 低信誉游资
        bs_mult, bs_warn, _ = self._check_bad_seats(signal, market_data)
        multiplier *= bs_mult
        if bs_warn:
            warnings.append(bs_warn)

        adjusted = signal.strength * multiplier
        passed = not blocked and adjusted >= self.MIN_STRENGTH_FOR_ENTRY

        return FilterResult(
            passed=passed,
            original_strength=signal.strength,
            adjusted_strength=round(adjusted, 3),
            warnings=warnings,
            blocked_by=blocked_by,
        )

    # ------------------------------------------------------------------
    # check #1: Bull Trap — 价格涨 + 主力流出
    # ------------------------------------------------------------------

    def _check_bull_trap(self, signal: StrategySignal, mkt: dict) -> tuple[float, str, bool]:
        price_chg = mkt.get("change_pct", 0)
        main_net = mkt.get("main_net_wan", 0)
        super_large_net = mkt.get("super_large_net", 0)
        large_net = mkt.get("large_net", 0)
        total_net = super_large_net + large_net

        # 价格涨 但主力(超大单+大单) 在卖
        if price_chg > 0.01 and total_net < 0:
            return self.BULL_TRAP_PENALTY, f"Bull Trap: 涨{price_chg:.1%}但主力净流出{total_net:.0f}万", False
        # 严重: 涨超3% 且 主力大幅流出
        if price_chg > 0.03 and main_net < -500:
            return self.BULL_TRAP_PENALTY, f"Bull Trap(Severe): 涨{price_chg:.1%}但主力净流出{main_net:.0f}万", True
        # 弱信号: 涨但主力参与度低
        if price_chg > 0 and main_net < 0:
            return 0.70, f"主力参与度低: 涨{price_chg:.1%}但主力净流出{main_net:.0f}万", False
        return 1.0, "", False

    # ------------------------------------------------------------------
    # check #2: 席位对倒 — 同席位买卖抵消
    # ------------------------------------------------------------------

    def _check_seat_wash(self, signal: StrategySignal, mkt: dict) -> tuple[float, str, bool]:
        """检测龙虎榜中同席位既有大量买入又有大量卖出 (对倒做量)。"""
        lhb_seats_detail = mkt.get("lhb_seats_detail", [])
        if not lhb_seats_detail:
            return 1.0, "", False

        wash_count = 0
        for seat in lhb_seats_detail:
            buy = seat.get("buy_amount", 0) or 0
            sell = seat.get("sell_amount", 0) or 0
            if buy > 100 and sell > 100:
                ratio = min(buy, sell) / max(buy, sell)
                if ratio > 0.5:  # 买卖金额接近 → 对倒嫌疑
                    wash_count += 1

        if wash_count >= 2:
            return self.SEAT_WASH_PENALTY, f"席位对倒: {wash_count}个席位买卖金额接近", True
        if wash_count >= 1:
            return 0.50, f"席位对倒嫌疑: {wash_count}个席位", False
        return 1.0, "", False

    # ------------------------------------------------------------------
    # check #3: 封板诱多 — 涨停但封单薄弱
    # ------------------------------------------------------------------

    def _check_weak_seal(self, signal: StrategySignal, mkt: dict) -> tuple[float, str, bool]:
        seal = mkt.get("lhb_seal_strength", 0)
        is_zt = mkt.get("is_limit_up", 0) or mkt.get("change_pct", 0) > 0.095

        if is_zt and seal <= 0:
            # 涨停了但没有封板数据 → 可能是炸板或没封住
            return self.WEAK_SEAL_PENALTY, "封板数据缺失: 涨停但无法确认封板强度", False
        if is_zt and 0 < seal < 0.02:
            return self.WEAK_SEAL_PENALTY, f"弱封板: 封单强度仅{seal:.1%}，次日低开风险高", False
        if is_zt and seal < 0.05:
            return 0.75, f"封板偏弱: 强度{seal:.1%}", False
        return 1.0, "", False

    # ------------------------------------------------------------------
    # check #4: 量价背离 — 放量但价格不涨
    # ------------------------------------------------------------------

    def _check_vol_divergence(self, signal: StrategySignal, mkt: dict) -> tuple[float, str, bool]:
        vol = mkt.get("volume", 0)
        avg_vol = mkt.get("avg_volume_20d", 0)
        price_chg = mkt.get("change_pct", 0)

        if avg_vol <= 0 or vol <= 0:
            return 1.0, "", False

        vol_ratio = vol / avg_vol
        # 放量2倍以上但涨幅不到1% → 出货
        if vol_ratio > 2.0 and abs(price_chg) < 0.01:
            return self.VOL_DIVERGENCE_PENALTY, f"量价背离: 放量{vol_ratio:.1f}x但涨幅仅{price_chg:.1%}，疑似出货", False
        # 放量1.5倍涨不动
        if vol_ratio > 1.5 and 0 < price_chg < 0.015:
            return 0.70, f"量价弱: 放量{vol_ratio:.1f}x仅涨{price_chg:.1%}", False
        return 1.0, "", False

    # ------------------------------------------------------------------
    # check #5: 劣迹席位 — 低信誉游资
    # ------------------------------------------------------------------

    def _check_bad_seats(self, signal: StrategySignal, mkt: dict) -> tuple[float, str, bool]:
        top_seats = mkt.get("lhb_top_seats", [])
        seat_scores = mkt.get("lhb_seat_scores", {})
        if not top_seats:
            return 1.0, "", False

        bad_count = 0
        for seat_name in top_seats:
            score = seat_scores.get(seat_name, 5.0)
            if score < 3.0:
                bad_count += 1

        if bad_count >= 2:
            return self.BAD_SEAT_PENALTY, f"劣迹席位: {bad_count}个席位信誉分<3", False
        if bad_count >= 1:
            return 0.75, f"含低信誉席位: 1个", False
        return 1.0, "", False
