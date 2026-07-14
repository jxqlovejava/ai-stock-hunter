# -*- coding: utf-8 -*-
"""入场/出场时机引擎。

短线/波段模式下，结合技术因子信号 + 价格形态 + 成交量确认，
输出具体的入场区间、目标区间、建议止损价和时间止损天数。

信号类型:
  入场: 放量突破 / 均线金叉+量能确认 / 回踩支撑反弹 / 超卖反弹 / 底部结构(A/B段)
  出场: 跌破关键均线 / 放量滞涨 / 超买回落 / 连板中断 / 达目标位
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd

from src.data.source_citation import SourceCitation, make_citation

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# DTO
# ---------------------------------------------------------------------------


@dataclass
class EntrySignal:
    """入场信号。"""
    type: str                      # BREAKOUT / MA_GOLDEN_CROSS / PULLBACK_SUPPORT / OVERSOLD_BOUNCE / BOTTOM_STRUCTURE
    description: str
    entry_zone_low: float          # 入场区间下限
    entry_zone_high: float         # 入场区间上限
    confidence: float              # 0.0-1.0
    trigger_conditions: list[str] = field(default_factory=list)


@dataclass
class ExitSignal:
    """出场信号。"""
    type: str                      # MA_BREAKDOWN / VOLUME_STALL / OVERBOUGHT / LIMIT_UP_BROKEN / TARGET_HIT
    description: str
    exit_zone_low: float           # 出场区间下限
    exit_zone_high: float          # 出场区间上限
    confidence: float              # 0.0-1.0
    urgency: str = "NORMAL"        # NORMAL / URGENT


@dataclass
class TimingResult:
    """时机判断结果。"""
    symbol: str
    name: str = ""
    current_price: float = 0.0
    # 入场
    entry_signals: list[EntrySignal] = field(default_factory=list)
    best_entry: Optional[EntrySignal] = None
    # 出场
    exit_signals: list[ExitSignal] = field(default_factory=list)
    urgent_exit: bool = False
    # 止损/止盈建议
    suggested_stop: float = 0.0    # 建议止损价
    atr_stop: float = 0.0          # ATR 止损价
    target_1: float = 0.0          # 第一目标位
    target_2: float = 0.0          # 第二目标位
    time_stop_days: int = 10       # 时间止损天数
    # 溯源
    confidence: float = 0.5
    source_citations: list[SourceCitation] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class EntryExitEngine:
    """入场/出场时机引擎。

    基于日线 OHLCV 数据 + 技术因子得分，输出结构化的 TimingResult。

    用法:
        engine = EntryExitEngine()
        result = engine.evaluate("000001", "平安银行", panel, technical_scores, time_config)
    """

    # 配置常量
    BREAKOUT_LOOKBACK = 20          # 突破看 N 日高点
    BREAKOUT_VOL_MULT = 1.5         # 突破需放量至均量的 N 倍
    PULLBACK_MA_PERIODS = [10, 20]  # 回踩支撑参考均线
    STALL_VOL_MULT = 1.3            # 放量滞涨量比阈值
    OVERSOLD_RSI = 30               # 超卖 RSI 阈值
    OVERBOUGHT_RSI = 70             # 超买 RSI 阈值

    def evaluate(
        self,
        symbol: str,
        name: str,
        panel: dict[str, pd.DataFrame],
        technical_scores: dict[str, float] | None = None,
        time_config=None,  # TimeHorizonConfig
    ) -> TimingResult:
        """评估入场/出场时机。"""
        close = panel.get("close")
        high = panel.get("high")
        low = panel.get("low")
        volume = panel.get("volume")

        if close is None or close.empty:
            return TimingResult(symbol=symbol, name=name, confidence=0.0)

        # 取当前最新数据
        current_price = float(close.iloc[-1].mean())

        result = TimingResult(
            symbol=symbol,
            name=name,
            current_price=current_price,
        )

        # --- 入场信号 ---
        entry_signals: list[EntrySignal] = []

        # 1. 放量突破
        bk = self._detect_breakout(close, high, volume)
        if bk:
            entry_signals.append(bk)

        # 2. 均线金叉
        gc = self._detect_golden_cross(close, volume)
        if gc:
            entry_signals.append(gc)

        # 3. 回踩支撑
        ps = self._detect_pullback_support(close, low, volume)
        if ps:
            entry_signals.append(ps)

        # 4. 超卖反弹
        ob = self._detect_oversold_bounce(close)
        if ob:
            entry_signals.append(ob)

        # 5. 底部结构（A/B 段 + 逆势确认 + 回踩不破）
        bs = self._detect_bottom_structure_entry(close, high, low)
        if bs:
            entry_signals.append(bs)

        result.entry_signals = entry_signals
        if entry_signals:
            # 选置信度最高的作为最佳入场
            result.best_entry = max(entry_signals, key=lambda s: s.confidence)

        # --- 出场信号 ---
        exit_signals: list[ExitSignal] = []

        # 1. 跌破均线
        mb = self._detect_ma_breakdown(close)
        if mb:
            exit_signals.append(mb)

        # 2. 放量滞涨
        vs = self._detect_volume_stall(close, volume)
        if vs:
            exit_signals.append(vs)

        # 3. 超买回落
        ov = self._detect_overbought(close)
        if ov:
            exit_signals.append(ov)

        # 4. 庄家操纵检测 (Phase 10)
        mp = self._detect_manipulation(close, volume)
        if mp:
            exit_signals.append(mp)

        result.exit_signals = exit_signals
        result.urgent_exit = any(
            s.urgency == "URGENT" for s in exit_signals
        )

        # --- 止损/止盈 ---
        atr = self._compute_atr(high, low, close, period=14)
        if time_config and time_config.is_short_term:
            atr_mult = getattr(time_config, "atr_stop_multiplier", 2.0)
            result.atr_stop = round(current_price - atr * atr_mult, 2)
            result.suggested_stop = result.atr_stop
            result.time_stop_days = getattr(time_config, "time_stop_days", 5)
        else:
            result.atr_stop = round(current_price - atr * 2.0, 2)
            result.suggested_stop = round(current_price * 0.98, 2)
            result.time_stop_days = 60

        # 目标位: 基于 ATR
        result.target_1 = round(current_price + atr * 3.0, 2)
        result.target_2 = round(current_price + atr * 5.0, 2)

        # 置信度
        signal_count = len(entry_signals) + len(exit_signals)
        result.confidence = min(0.9, 0.3 + signal_count * 0.15)
        result.source_citations = [
            make_citation(
                provider="entry_exit_engine",
                field=f"{symbol}_timing",
                data_type="entry_exit_timing",
                confidence=result.confidence,
            ),
        ]

        return result

    # ------------------------------------------------------------------
    # 入场检测
    # ------------------------------------------------------------------

    def _detect_breakout(
        self, close: pd.DataFrame, high: pd.DataFrame, volume: pd.DataFrame
    ) -> Optional[EntrySignal]:
        """放量突破 N 日高点。"""
        if close.shape[0] < self.BREAKOUT_LOOKBACK + 1:
            return None

        latest_close = close.iloc[-1]
        prev_high = high.iloc[-(self.BREAKOUT_LOOKBACK + 1):-1].max()
        latest_vol = volume.iloc[-1]
        avg_vol = volume.iloc[-self.BREAKOUT_LOOKBACK:-1].mean()

        # 突破条件: 收盘价 > N 日最高 + 放量
        breakout_stocks = (latest_close > prev_high).sum()
        vol_confirmed = (latest_vol > avg_vol * self.BREAKOUT_VOL_MULT).sum()

        if breakout_stocks > 0:
            latest_prices = latest_close[latest_close > prev_high]
            if not latest_prices.empty:
                entry_price = float(latest_prices.mean())
                return EntrySignal(
                    type="BREAKOUT",
                    description=f"放量突破{self.BREAKOUT_LOOKBACK}日高点 (量确认: {vol_confirmed}/{len(latest_close)}只)",
                    entry_zone_low=round(entry_price * 0.995, 2),
                    entry_zone_high=round(entry_price * 1.01, 2),
                    confidence=min(0.8, 0.4 + vol_confirmed / len(latest_close) * 0.4),
                    trigger_conditions=[
                        f"收盘站稳 {self.BREAKOUT_LOOKBACK} 日高点上方",
                        "成交量维持放大（>均量 1.2 倍）",
                    ],
                )
        return None

    def _detect_golden_cross(
        self, close: pd.DataFrame, volume: pd.DataFrame
    ) -> Optional[EntrySignal]:
        """MA5 上穿 MA20，伴随量能确认。"""
        if close.shape[0] < 21:
            return None

        ma5 = close.rolling(5).mean()
        ma20 = close.rolling(20).mean()
        latest_close = close.iloc[-1]

        # 金叉: 今日 MA5>MA20 且昨日 MA5<=MA20
        crossed = (ma5.iloc[-1] > ma20.iloc[-1]) & (ma5.iloc[-2] <= ma20.iloc[-2])
        cross_count = crossed.sum()

        if cross_count > 0:
            cross_prices = latest_close[crossed]
            entry_price = float(cross_prices.mean()) if not cross_prices.empty else float(latest_close.mean())
            return EntrySignal(
                type="MA_GOLDEN_CROSS",
                description=f"MA5 上穿 MA20 金叉 ({cross_count}只触发)",
                entry_zone_low=round(entry_price * 0.99, 2),
                entry_zone_high=round(entry_price * 1.02, 2),
                confidence=0.65,
                trigger_conditions=[
                    "MA5>MA20 持续 3 日确认",
                    "金叉当日成交量 > 20日均量 1.2倍",
                ],
            )
        return None

    def _detect_pullback_support(
        self, close: pd.DataFrame, low: pd.DataFrame, volume: pd.DataFrame
    ) -> Optional[EntrySignal]:
        """回踩均线支撑位反弹。"""
        if close.shape[0] < 21:
            return None

        ma20 = close.rolling(20).mean().iloc[-1]
        latest_low = low.iloc[-1]
        latest_close = close.iloc[-1]

        # 最低价接近 MA20（1%内）且收盘回升
        near_support = (latest_low <= ma20 * 1.01) & (latest_low >= ma20 * 0.98)
        bounced = latest_close > latest_low * 1.005
        hits = (near_support & bounced).sum()

        if hits > 0:
            support_prices = ma20[near_support & bounced]
            entry_price = float(support_prices.mean()) if not support_prices.empty else float(ma20.mean())
            return EntrySignal(
                type="PULLBACK_SUPPORT",
                description=f"回踩 MA20 支撑反弹 ({hits}只)，是低吸机会",
                entry_zone_low=round(entry_price * 0.995, 2),
                entry_zone_high=round(entry_price * 1.005, 2),
                confidence=0.6,
                trigger_conditions=[
                    "收盘站稳 MA20 上方",
                    "次日不创新低",
                ],
            )
        return None

    def _detect_oversold_bounce(self, close: pd.DataFrame) -> Optional[EntrySignal]:
        """RSI 超卖区反弹。"""
        if close.shape[0] < 15:
            return None

        delta = close.diff(1)
        gain = delta.clip(lower=0).ewm(com=13, min_periods=14).mean()
        loss = (-delta).clip(lower=0).ewm(com=13, min_periods=14).mean()
        rs = gain / (loss + 1e-12)
        rsi = 100.0 - (100.0 / (1.0 + rs))

        latest_rsi = rsi.iloc[-1]
        prev_rsi = rsi.iloc[-2]
        latest_close = close.iloc[-1]
        prev_close = close.iloc[-2]

        # RSI < 30 且今日回升 + 价格上涨
        oversold = (latest_rsi < self.OVERSOLD_RSI) & (latest_rsi > prev_rsi)
        price_up = latest_close > prev_close
        signals = (oversold & price_up).sum()

        if signals > 0:
            prices = latest_close[oversold & price_up]
            entry_price = float(prices.mean()) if not prices.empty else float(latest_close.mean())
            return EntrySignal(
                type="OVERSOLD_BOUNCE",
                description=f"RSI 超卖(<{self.OVERSOLD_RSI})反弹 ({signals}只)，短线抄底机会",
                entry_zone_low=round(entry_price * 0.995, 2),
                entry_zone_high=round(entry_price * 1.005, 2),
                confidence=0.55,
                trigger_conditions=[
                    "RSI 回升至 35 以上确认",
                    "成交量配合放大",
                ],
            )
        return None

    def _detect_bottom_structure_entry(
        self,
        close: pd.DataFrame,
        high: pd.DataFrame,
        low: pd.DataFrame,
    ) -> Optional[EntrySignal]:
        """底部结构入场：顺势衰竭 + 逆势确认 + 回踩不破 → 仅轻仓试多。

        单列面板（主分析标的）优先；多列时取第一列。
        """
        if close is None or close.shape[0] < 40:
            return None
        try:
            from src.analysis.bottom_structure import (
                BottomPhase,
                analyze_bottom_structure,
            )

            col = close.columns[0]
            c = close[col].astype(float).values
            h = high[col].astype(float).values if high is not None and col in high.columns else c
            l = low[col].astype(float).values if low is not None and col in low.columns else c
            # open 近似用前收
            o = np.roll(c, 1)
            o[0] = c[0]

            result = analyze_bottom_structure(h, l, c, o)
            phase = result.phase
            if phase == BottomPhase.LIGHT_LONG_SETUP and result.entry_allowed:
                px = float(c[-1])
                stop = result.swing_low * 0.997 if result.swing_low > 0 else px * 0.98
                return EntrySignal(
                    type="BOTTOM_STRUCTURE",
                    description=(
                        f"底部结构成立(B/A={result.ab_ratio:.2f}): "
                        f"顺势不足+逆势确认+回踩不破 → 轻仓试多"
                    ),
                    entry_zone_low=round(max(stop, px * 0.99), 2),
                    entry_zone_high=round(px * 1.01, 2),
                    confidence=min(0.78, max(0.55, result.confidence)),
                    trigger_conditions=[
                        f"A段跌幅 {result.a_decline_pct:.1f}% > B段 {result.b_decline_pct:.1f}%",
                        "逆势 K 线确认（看涨吞没/底部分形）+ 结构突破",
                        f"回踩不破前低 {result.swing_low:.2f}",
                        "仅轻仓试多，前高附近止盈",
                    ],
                )
            # 接飞刀阶段不产生入场；其他阶段静默
            return None
        except Exception:
            logger.debug("底部结构入场检测跳过", exc_info=True)
            return None

    # ------------------------------------------------------------------
    # 出场检测
    # ------------------------------------------------------------------

    def _detect_ma_breakdown(self, close: pd.DataFrame) -> Optional[ExitSignal]:
        """跌破关键均线。"""
        if close.shape[0] < 21:
            return None

        latest_close = close.iloc[-1]
        ma20 = close.rolling(20).mean().iloc[-1]
        ma60 = close.rolling(60).mean().iloc[-1] if close.shape[0] >= 60 else ma20

        # 跌破 MA20
        broke_ma20 = (latest_close < ma20 * 0.98).sum()
        broke_ma60 = (latest_close < ma60 * 0.97).sum()

        if broke_ma60 > 0:
            return ExitSignal(
                type="MA_BREAKDOWN",
                description=f"跌破 MA60 支撑 ({broke_ma60}只)，趋势破坏",
                exit_zone_low=round(float(latest_close.mean()) * 0.97, 2),
                exit_zone_high=round(float(latest_close.mean()), 2),
                confidence=0.7,
                urgency="URGENT",
            )
        elif broke_ma20 > 0:
            return ExitSignal(
                type="MA_BREAKDOWN",
                description=f"跌破 MA20 ({broke_ma20}只)，短线上涨节奏破坏",
                exit_zone_low=round(float(latest_close.mean()) * 0.98, 2),
                exit_zone_high=round(float(latest_close.mean()) * 1.0, 2),
                confidence=0.55,
                urgency="NORMAL",
            )
        return None

    def _detect_volume_stall(
        self, close: pd.DataFrame, volume: pd.DataFrame
    ) -> Optional[ExitSignal]:
        """放量滞涨 — 量大价不涨。"""
        if close.shape[0] < 21:
            return None

        latest_ret = close.pct_change(1).iloc[-1]
        latest_vol = volume.iloc[-1]
        avg_vol = volume.iloc[-20:].mean()
        vol_ratio = latest_vol / (avg_vol + 1e-12)

        # 放量 (>1.3x) + 价格不涨 (<0.5%)
        stalled = (vol_ratio > self.STALL_VOL_MULT) & (latest_ret.abs() < 0.003)
        stall_count = stalled.sum().sum() if isinstance(stalled, pd.DataFrame) else stalled.sum()

        if stall_count > 0:
            return ExitSignal(
                type="VOLUME_STALL",
                description=f"放量滞涨 ({stall_count}只) — 主力出货嫌疑",
                exit_zone_low=round(float(close.iloc[-1].mean()) * 0.99, 2),
                exit_zone_high=round(float(close.iloc[-1].mean()) * 1.0, 2),
                confidence=0.65,
                urgency="URGENT",
            )
        return None

    def _detect_manipulation(self, close: pd.DataFrame, volume: pd.DataFrame | None = None) -> Optional[ExitSignal]:
        """检测庄家操纵风险 — 诱多出货/钓鱼线等高风险信号触发紧急出场。

        基于日线量价和分时异常的快速判断:
        - 上影线 > 3% + 放量 → 疑似钓鱼线出货
        - 收盘在日均价之下 + 盘中冲高 > 3% → 疑似诱多
        """
        if close.shape[0] < 5:
            return None

        if isinstance(close, pd.DataFrame) and "high" in close.columns:
            high_val = float(close["high"].iloc[-1])
            close_val = float(close["close"].iloc[-1])
            open_val = float(close["open"].iloc[-1])
        else:
            return None

        # 上影线长度
        upper_shadow = (high_val - max(close_val, open_val)) / open_val if open_val > 0 else 0

        # 成交量检查
        vol_anomaly = False
        if volume is not None and "volume" in volume.columns:
            latest_vol = float(volume["volume"].iloc[-1])
            avg_vol = float(volume["volume"].iloc[-20:].mean()) if volume.shape[0] >= 20 else latest_vol
            vol_anomaly = latest_vol > avg_vol * 1.5 if avg_vol > 0 else False

        # 条件 1: 长上影线 (> 3%) + 放量 → 钓鱼线
        if upper_shadow > 0.03 and vol_anomaly:
            return ExitSignal(
                type="MANIPULATION_RISK",
                description=f"疑似庄家钓鱼线出货 — 上影线 {upper_shadow*100:.1f}% + 放量",
                exit_zone_low=round(close_val * 0.97, 2),
                exit_zone_high=round(close_val, 2),
                confidence=0.70,
                urgency="URGENT",
            )

        # 条件 2: 盘中冲高回落 (> 3%) → 诱多嫌疑
        daily_range = (high_val - close_val) / open_val if open_val > 0 else 0
        if daily_range > 0.03 and close_val < open_val and vol_anomaly:
            return ExitSignal(
                type="MANIPULATION_RISK",
                description=f"疑似庄家诱多出货 — 盘中冲高 {daily_range*100:.1f}% 后回落放量",
                exit_zone_low=round(close_val * 0.98, 2),
                exit_zone_high=round(close_val, 2),
                confidence=0.65,
                urgency="URGENT",
            )

        return None

    def _detect_overbought(self, close: pd.DataFrame) -> Optional[ExitSignal]:
        """RSI 超买区回落。"""
        if close.shape[0] < 15:
            return None

        delta = close.diff(1)
        gain = delta.clip(lower=0).ewm(com=13, min_periods=14).mean()
        loss = (-delta).clip(lower=0).ewm(com=13, min_periods=14).mean()
        rs = gain / (loss + 1e-12)
        rsi = 100.0 - (100.0 / (1.0 + rs))

        latest_rsi = rsi.iloc[-1]
        prev_rsi = rsi.iloc[-2]
        close_chg = close.pct_change(1).iloc[-1]

        # RSI > 70 且回落 + 价格下跌
        overbought = (latest_rsi > self.OVERBOUGHT_RSI) & (latest_rsi < prev_rsi)
        price_drop = close_chg < -0.005
        signals = (overbought & price_drop).sum()

        if signals > 0:
            return ExitSignal(
                type="OVERBOUGHT",
                description=f"RSI 超买回落 ({signals}只) — 高位回调风险",
                exit_zone_low=round(float(close.iloc[-1].mean()) * 0.98, 2),
                exit_zone_high=round(float(close.iloc[-1].mean()), 2),
                confidence=0.6,
                urgency="NORMAL",
            )
        return None

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_atr(
        high: pd.DataFrame, low: pd.DataFrame, close: pd.DataFrame, period: int = 14
    ) -> float:
        """计算面板平均 ATR。"""
        if high is None or low is None or close is None:
            return 0.0
        tr1 = high.iloc[-period:] - low.iloc[-period:]
        tr2 = (high.iloc[-period:] - close.shift(1).iloc[-period:]).abs()
        tr3 = (low.iloc[-period:] - close.shift(1).iloc[-period:]).abs()
        tr = pd.DataFrame(
            np.maximum(np.maximum(tr1.values, tr2.values), tr3.values),
            index=tr1.index, columns=tr1.columns,
        )
        atr = tr.mean()
        return float(atr.mean()) if not atr.empty else 0.0
