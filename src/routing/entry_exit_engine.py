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
    # P1-2 均线定方向 + MACD 定动能双层过滤
    GOLDEN_CROSS_MA_LONG = 50       # 金叉方向层: 要求 MA20 > MA50
    MA20_SLOPE_LOOKBACK = 5         # MA20 近 N 日斜率判断是否向上
    MACD_HIST_BOOST = 0.10          # MACD 柱状放大时金叉置信度加成
    # P1-2 破位质量
    BREAKDOWN_VOL_MULT = 1.3        # 放量破位量比阈值（> = 真出逃）
    # P1-3 MACD 顶背离联动
    TOP_DIVERGENCE_BOOST = 0.05     # 顶背离 + 破位时置信度加成
    TOP_DIVERGENCE_LOOKBACK = 40    # 顶背离窗口（价格新高、DIF 未新高比较）
    # P1-4 量价过滤器
    FAKE_BREAKOUT_CONFIRM_DAYS = 3  # 突破后确认窗口（不新高/回踩重新跌破检测）
    FAKE_BREAKOUT_SHADOW_PCT = 0.03 # 长上影阈值（放量不涨）
    FAKE_BREAKOUT_VOL_MULT = 1.3    # 假突破放量量比阈值
    SHRINK_VOL_MULT = 0.8           # 缩量反弹量比阈值（< = 缩量）
    SHRINK_REBOUND_DOWNGRADE = 0.7  # 缩量反弹降权系数（≠反转）

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

        # 1. 放量突破 (P1-4: 假突破否决过滤器 — 否决则不产生突破信号)
        bk = self._detect_breakout(close, high, volume)
        fake_reason = self._detect_fake_breakout(close, high, volume)
        if bk and not fake_reason:
            entry_signals.append(bk)

        # 2. 均线金叉 (P1-2: MA 方向 + MACD 动能双层过滤)
        gc = self._detect_golden_cross(close, volume)
        if gc:
            entry_signals.append(gc)

        # 3. 回踩支撑 (P1-4: 缩量反弹降权)
        ps = self._detect_pullback_support(close, low, volume)
        if ps:
            entry_signals.append(ps)

        # 4. 超卖反弹 (P1-4: 缩量反弹降权)
        ob = self._detect_oversold_bounce(close, volume)
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

        # 1. 跌破均线 (P1-2 破位质量: 放量=真出逃 / 缩量=洗盘; P1-3 顶背离联动)
        top_div = self._detect_top_divergence(close)
        mb = self._detect_ma_breakdown(close, volume, top_divergence=top_div)
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
        self, close: pd.DataFrame, volume: pd.DataFrame | None = None
    ) -> Optional[EntrySignal]:
        """MA5 上穿 MA20，伴随量能确认。

        P1-2 双层过滤:
          方向层 — 金叉须 MA20 > MA50 且 MA20 向上；MA50 数据不足时退化为仅要求 MA20 向上。
          动能层 — MACD 柱状图放大（动能增强）时置信度加成 0.10，收窄时回落 0.05。
        """
        if close.shape[0] < 21:
            return None

        ma5 = close.rolling(5).mean()
        ma20 = close.rolling(20).mean()
        latest_close = close.iloc[-1]

        # 方向层: 金叉须 MA20>MA50（至少 MA20 向上）
        base_crossed = (ma5.iloc[-1] > ma20.iloc[-1]) & (ma5.iloc[-2] <= ma20.iloc[-2])
        ma20_slope = ma20.iloc[-1] - ma20.iloc[-self.MA20_SLOPE_LOOKBACK]
        ma20_rising = ma20_slope > 0

        if close.shape[0] >= self.GOLDEN_CROSS_MA_LONG + 1:
            ma50 = close.rolling(self.GOLDEN_CROSS_MA_LONG).mean()
            long_ok = (ma20.iloc[-1] > ma50.iloc[-1]) & ma20_rising
        else:
            # MA50 数据不足，退化为仅要求 MA20 向上
            long_ok = ma20_rising

        crossed = base_crossed & long_ok
        cross_count = crossed.sum()

        if cross_count > 0:
            # 动能层: MACD 柱状放大加成
            hist_rising = self._macd_hist_rising(close)
            confidence = 0.65 + (self.MACD_HIST_BOOST if hist_rising else -0.05)
            confidence = min(0.8, max(0.4, confidence))

            cross_prices = latest_close[crossed]
            entry_price = float(cross_prices.mean()) if not cross_prices.empty else float(latest_close.mean())
            return EntrySignal(
                type="MA_GOLDEN_CROSS",
                description=(
                    f"MA5 上穿 MA20 金叉 + 方向确认 ({cross_count}只触发)"
                    + ("，MACD动能增强" if hist_rising else "")
                ),
                entry_zone_low=round(entry_price * 0.99, 2),
                entry_zone_high=round(entry_price * 1.02, 2),
                confidence=confidence,
                trigger_conditions=[
                    "MA20 > MA50 且 MA20 向上（均线定方向）",
                    "MACD 柱状图放大（动能确认）",
                    "MA5>MA20 持续 3 日确认",
                    "金叉当日成交量 > 20日均量 1.2倍",
                ],
            )
        return None

    def _detect_pullback_support(
        self,
        close: pd.DataFrame,
        low: pd.DataFrame,
        volume: pd.DataFrame | None = None,
    ) -> Optional[EntrySignal]:
        """回踩均线支撑位反弹。

        P1-4: 缩量反弹降权（缩量 ≠ 反转，置信度 × 0.7）。
        """
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
            confidence = 0.6
            shrink = self._is_shrink_volume(volume)
            if shrink:
                confidence *= self.SHRINK_REBOUND_DOWNGRADE

            support_prices = ma20[near_support & bounced]
            entry_price = float(support_prices.mean()) if not support_prices.empty else float(ma20.mean())
            return EntrySignal(
                type="PULLBACK_SUPPORT",
                description=(
                    f"回踩 MA20 支撑反弹 ({hits}只)，是低吸机会"
                    + ("（缩量反弹，非反转，降权）" if shrink else "")
                ),
                entry_zone_low=round(entry_price * 0.995, 2),
                entry_zone_high=round(entry_price * 1.005, 2),
                confidence=confidence,
                trigger_conditions=[
                    "收盘站稳 MA20 上方",
                    "次日不创新低",
                ],
            )
        return None

    def _detect_oversold_bounce(
        self, close: pd.DataFrame, volume: pd.DataFrame | None = None
    ) -> Optional[EntrySignal]:
        """RSI 超卖区反弹。

        P1-4: 缩量反弹降权（缩量 ≠ 反转，置信度 × 0.7）。
        """
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
            confidence = 0.55
            shrink = self._is_shrink_volume(volume)
            if shrink:
                confidence *= self.SHRINK_REBOUND_DOWNGRADE

            prices = latest_close[oversold & price_up]
            entry_price = float(prices.mean()) if not prices.empty else float(latest_close.mean())
            return EntrySignal(
                type="OVERSOLD_BOUNCE",
                description=(
                    f"RSI 超卖(<{self.OVERSOLD_RSI})反弹 ({signals}只)，短线抄底机会"
                    + ("（缩量反弹，非反转，降权）" if shrink else "")
                ),
                entry_zone_low=round(entry_price * 0.995, 2),
                entry_zone_high=round(entry_price * 1.005, 2),
                confidence=confidence,
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

    def _detect_ma_breakdown(
        self,
        close: pd.DataFrame,
        volume: pd.DataFrame | None = None,
        top_divergence: bool = False,
    ) -> Optional[ExitSignal]:
        """跌破关键均线。

        P1-2 破位质量: 放量破位 = 真出逃（更高权重），缩量破位 = 多为洗盘（降权）。
        P1-3 顶背离联动: 顶背离 + 破位 → 置信度加成 0.05，并升级为 URGENT。
        """
        if close.shape[0] < 21:
            return None

        latest_close = close.iloc[-1]
        ma20 = close.rolling(20).mean().iloc[-1]
        ma60 = close.rolling(60).mean().iloc[-1] if close.shape[0] >= 60 else ma20

        # 跌破 MA20 / MA60
        broke_ma20 = (latest_close < ma20 * 0.98).sum()
        broke_ma60 = (latest_close < ma60 * 0.97).sum()

        # 破位质量（放量=真出逃 / 缩量=洗盘）
        vol_ratio = self._volume_ratio(volume)
        heavy = vol_ratio is not None and vol_ratio >= self.BREAKDOWN_VOL_MULT
        shrink = vol_ratio is not None and vol_ratio < 1.0
        boost = self.TOP_DIVERGENCE_BOOST if top_divergence else 0.0
        div_tag = " + MACD顶背离" if top_divergence else ""

        if broke_ma60 > 0:
            if heavy:
                confidence = 0.75 + boost
            elif shrink:
                confidence = 0.50 + boost
            else:
                confidence = 0.65 + boost
            return ExitSignal(
                type="MA_BREAKDOWN",
                description=self._breakdown_desc(
                    "放量" if heavy else ("缩量" if shrink else ""),
                    f"MA60 ({broke_ma60}只)，趋势破坏", div_tag,
                ),
                exit_zone_low=round(float(latest_close.mean()) * 0.97, 2),
                exit_zone_high=round(float(latest_close.mean()), 2),
                confidence=min(0.85, confidence),
                urgency="URGENT" if (heavy or top_divergence) else "NORMAL",
            )
        elif broke_ma20 > 0:
            if heavy:
                confidence = 0.62 + boost
            elif shrink:
                confidence = 0.40 + boost
            else:
                confidence = 0.55 + boost
            return ExitSignal(
                type="MA_BREAKDOWN",
                description=self._breakdown_desc(
                    "放量" if heavy else ("缩量" if shrink else ""),
                    f"MA20 ({broke_ma20}只)，短线上涨节奏破坏", div_tag,
                ),
                exit_zone_low=round(float(latest_close.mean()) * 0.98, 2),
                exit_zone_high=round(float(latest_close.mean()) * 1.0, 2),
                confidence=min(0.8, confidence),
                urgency="URGENT" if top_divergence else "NORMAL",
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

    # ------------------------------------------------------------------
    # P1-2 / P1-3 / P1-4 辅助
    # ------------------------------------------------------------------

    @staticmethod
    def _breakdown_desc(quality: str, base: str, extra: str = "") -> str:
        """破位质量描述: 放量=真出逃，缩量=多为洗盘。"""
        tag = "放量" if quality == "放量" else ("缩量" if quality == "缩量" else "")
        if tag == "放量":
            note = "放量破位=真出逃"
        elif tag == "缩量":
            note = "缩量破位=多为洗盘"
        else:
            note = "破位"
        return f"{tag}跌破 {base}，{note}{extra}"

    @staticmethod
    def _volume_ratio(volume: pd.DataFrame | None) -> Optional[float]:
        """最新量比（今量 / 20日均量）。无 volume 帧或数据不足返回 None。"""
        if volume is None or volume.empty or volume.shape[0] < 20:
            return None
        latest = float(volume.iloc[-1].mean())
        avg = float(volume.iloc[-20:].mean().mean())
        if not np.isfinite(latest) or not np.isfinite(avg) or avg <= 0:
            return None
        return latest / avg

    @staticmethod
    def _vol_ratio_series(v: np.ndarray, window: int = 20) -> np.ndarray:
        """逐日量比序列（当日量 / 前 window 日均量），前段为 NaN。"""
        out = np.full(len(v), np.nan, dtype=float)
        for i in range(len(v)):
            lo = max(0, i - window)
            if i == 0:
                continue
            avg = v[lo:i].mean()
            if avg and avg > 0 and np.isfinite(v[i]):
                out[i] = v[i] / avg
        return out

    def _is_shrink_volume(self, volume: pd.DataFrame | None) -> bool:
        """是否缩量（量比 < SHRINK_VOL_MULT）— 缩量反弹 ≠ 反转。"""
        vr = self._volume_ratio(volume)
        return vr is not None and vr < self.SHRINK_VOL_MULT

    @staticmethod
    def _macd_hist_rising(close: pd.DataFrame) -> bool:
        """最新 bar MACD 柱状图是否放大（动能增强）— 供金叉动能层。"""
        if close is None or close.empty or close.shape[0] < 26:
            return False
        try:
            from src.alphas.macd_kdj import compute_macd
        except Exception:
            return False
        s = close.mean(axis=1).dropna()
        if len(s) < 26:
            return False
        dif, dea, hist = compute_macd(s)
        h0, h1 = hist.iloc[-1], hist.iloc[-2]
        if h0 != h0 or h1 != h1:  # NaN 检查
            return False
        return bool(h0 > h1)

    def _detect_top_divergence(self, close: pd.DataFrame) -> bool:
        """最近一 bar 是否出现 MACD 顶背离（价格创新高、DIF 未创新高）。

        使用 TOP_DIVERGENCE_LOOKBACK 窗口，捕捉中期的「价格新高、DIF 未新高」
        （默认 20 日窗口在价格创出新高时，窗口 DIF 峰值往往是当日自身，漏检）。
        """
        if close is None or close.empty or close.shape[0] < self.TOP_DIVERGENCE_LOOKBACK:
            return False
        try:
            from src.alphas.macd_kdj import compute_macd, detect_macd_top_divergence
        except Exception:
            return False
        for col in close.columns:
            s = close[col].dropna()
            if len(s) < self.TOP_DIVERGENCE_LOOKBACK:
                continue
            dif = compute_macd(s)[0]
            div = detect_macd_top_divergence(
                s, dif, lookback=self.TOP_DIVERGENCE_LOOKBACK
            )
            if bool(div.iloc[-1]):
                return True
        return False

    def _detect_fake_breakout(
        self,
        close: pd.DataFrame,
        high: pd.DataFrame,
        volume: pd.DataFrame | None = None,
    ) -> Optional[str]:
        """假突破否决过滤器 — 返回否决原因（命中任一检测）或 None。

        4 检测（作为 BREAKOUT 信号的否决项）:
          1. 盘中破位收盘跌回 — 最高价上破前 N 日高，但收盘跌回下方
          2. 放量不涨留长上影 — 收盘破前 N 日高但留长上影且放量
          3. 突破当天放量后续不新高 — 近 N 日放量突破后未再创新高
          4. 回踩放量重新跌破 — 突破后回踩放量重新跌破突破位
        """
        if close is None or high is None or close.empty or high.empty:
            return None
        if close.shape[0] < self.BREAKOUT_LOOKBACK + 2:
            return None
        try:
            for col in close.columns:
                if col not in high.columns:
                    continue
                reason = self._fake_breakout_col(
                    close[col].astype(float),
                    high[col].astype(float),
                    volume,
                    col,
                )
                if reason:
                    return reason
        except Exception:
            logger.debug("假突破检测跳过", exc_info=True)
        return None

    def _fake_breakout_col(
        self,
        c: pd.Series,
        h: pd.Series,
        volume: pd.DataFrame | None,
        col: object,
    ) -> Optional[str]:
        """单列假突破检测。"""
        lookback = self.BREAKOUT_LOOKBACK
        # 前 N 日最高（不含当日）
        level = h.shift(1).rolling(lookback, min_periods=1).max()

        latest_c = float(c.iloc[-1])
        latest_h = float(h.iloc[-1])
        latest_level = float(level.iloc[-1])
        if not np.isfinite(latest_level) or latest_level <= 0:
            return None

        # 检测 1: 盘中破位收盘跌回
        if latest_h > latest_level and latest_c < latest_level:
            return "盘中破位收盘跌回"

        # 逐日量比序列（用于检测 2/3/4 的放量确认）
        v_arr = None
        v_ratio = None
        if volume is not None and col in volume.columns:
            v_arr = volume[col].to_numpy(dtype=float)
            v_ratio = self._vol_ratio_series(v_arr)

        # 检测 2: 放量不涨留长上影（收盘确实破前高，但长上影 + 放量）
        if latest_c > latest_level:
            if v_ratio is not None and np.isfinite(v_ratio[-1]) \
                    and v_ratio[-1] >= self.FAKE_BREAKOUT_VOL_MULT:
                if latest_c > 0:
                    upper_shadow = (latest_h - latest_c) / latest_c
                    if upper_shadow >= self.FAKE_BREAKOUT_SHADOW_PCT:
                        return "放量不涨留长上影"

        # 检测 3/4: 近 CONFIRM_DAYS 窗口内的突破后续行为
        confirm = self.FAKE_BREAKOUT_CONFIRM_DAYS
        n = len(c)
        c_arr = c.to_numpy(dtype=float)
        h_arr = h.to_numpy(dtype=float)
        lev_arr = level.to_numpy(dtype=float)
        for d in range(max(1, n - confirm), n):
            ld = float(lev_arr[d])
            if not np.isfinite(ld) or ld <= 0:
                continue
            # 突破日（收盘站上前高）
            if c_arr[d] <= ld:
                continue
            # 突破日需放量
            if v_ratio is None or not np.isfinite(v_ratio[d]) \
                    or v_ratio[d] < self.FAKE_BREAKOUT_VOL_MULT:
                continue
            # 检测 3: 突破后未再创新高（今日是突破日则无法判断，跳过）
            if d < n - 1:
                later_high = float(np.nanmax(h_arr[d + 1:]))
                if np.isfinite(later_high) and later_high <= h_arr[d]:
                    return "突破后不新高"
                # 检测 4: 突破后回踩放量重新跌破突破位
                for j in range(d + 1, n):
                    if c_arr[j] < ld:
                        if v_ratio is not None and np.isfinite(v_ratio[j]) \
                                and v_ratio[j] >= self.FAKE_BREAKOUT_VOL_MULT:
                            return "回踩放量重新跌破"
                        break
        return None
