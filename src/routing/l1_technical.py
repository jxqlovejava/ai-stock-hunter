# -*- coding: utf-8 -*-
"""L1 技术分析器 — 短线/波段专用 6 维技术评分。

当 trading_style ∈ {SWING, SHORT_TERM} 时，由 Orchestrator 注入运行。
评分维度:
  1. 趋势 (Trend)       — MACD / DMI / MA 乖离
  2. 反转 (Reversal)     — RSI / KDJ / 威廉 / 短期反转
  3. 量价 (Volume)       — OBV / MFI / 量比 / 换手率异常
  4. 波动 (Volatility)   — ATR / 布林带位置 / 历史波动率
  5. 均线系统 (MA)        — 排列 / 交叉 / 支撑距离
  6. 打板情绪 (LimitUp)   — 涨停/炸板/连板数据 (来自 game_theory/seats.py)
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
class TechnicalReport:
    """L1 技术分析报告。"""
    symbol: str
    name: str = ""
    # 6 维子评分 (0-100)
    trend_score: float = 50.0
    reversal_score: float = 50.0
    volume_score: float = 50.0
    volatility_score: float = 50.0
    ma_score: float = 50.0
    limit_up_score: float = 50.0
    # 综合
    composite_score: float = 50.0
    # 打板快照
    limit_up_snapshot: Optional[dict] = None
    # 信号清单 (entry/exit)
    signals: list[TechnicalSignal] = field(default_factory=list)
    # 溯源
    source_citations: list[SourceCitation] = field(default_factory=list)
    data_gaps: list[str] = field(default_factory=list)
    confidence: float = 0.7
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class TechnicalSignal:
    """技术信号 — 来自单一指标的判断。"""
    indicator: str           # RSI / MACD / MA_CROSS / etc.
    direction: str           # BULLISH / BEARISH / NEUTRAL
    strength: float          # 信号强度 0.0-1.0
    description: str         # 人类可读
    is_entry: bool = False   # 是否可作为入场参考
    is_exit: bool = False    # 是否可作为出场参考


# ---------------------------------------------------------------------------
# 维度权重
# ---------------------------------------------------------------------------

DEFAULT_WEIGHTS = {
    "trend": 0.20,
    "reversal": 0.15,
    "volume": 0.18,
    "volatility": 0.10,
    "ma": 0.22,
    "limit_up": 0.15,
}


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------


class L1TechnicalAnalyzer:
    """短线技术分析器。

    消费 factor registry 中的 technical category 因子，
    聚合为 6 维评分 + 信号清单。

    用法:
        analyzer = L1TechnicalAnalyzer(registry)
        report = analyzer.analyze("000001", "平安银行", panel)
    """

    def __init__(self, registry=None, weights: dict | None = None):
        self._registry = registry
        self._weights = weights or DEFAULT_WEIGHTS.copy()

    def analyze(
        self,
        symbol: str,
        name: str,
        panel: dict[str, pd.DataFrame],
        limit_up_snapshot: dict | None = None,
    ) -> TechnicalReport:
        """从面板数据生成技术分析报告。"""
        report = TechnicalReport(symbol=symbol, name=name)

        scores: dict[str, float] = {}
        gaps: list[str] = []
        all_signals: list[TechnicalSignal] = []

        # --- 1. 趋势维度 ---
        trend_factors = ["macd_histogram", "dmi_direction", "ma_bias"]
        trend_scores = self._compute_factor_scores(panel, trend_factors)
        if trend_scores:
            scores["trend"] = float(np.mean(trend_scores))
            all_signals.extend(self._interpret_trend(trend_scores, panel))
        else:
            scores["trend"] = 50.0
            gaps.append("trend_factors")

        # --- 2. 反转维度 ---
        reversal_factors = ["rsi_signal", "kdj_signal", "williams_r", "short_term_reversal"]
        rev_scores = self._compute_factor_scores(panel, reversal_factors)
        if rev_scores:
            scores["reversal"] = float(np.mean(rev_scores))
            all_signals.extend(self._interpret_reversal(rev_scores, panel))
        else:
            scores["reversal"] = 50.0
            gaps.append("reversal_factors")

        # --- 3. 量价维度 ---
        volume_factors = ["obv_divergence", "mfi_signal", "volume_ratio", "turnover_anomaly"]
        vol_scores = self._compute_factor_scores(panel, volume_factors)
        if vol_scores:
            scores["volume"] = float(np.mean(vol_scores))
            all_signals.extend(self._interpret_volume(vol_scores, panel))
        else:
            scores["volume"] = 50.0
            gaps.append("volume_factors")

        # --- 4. 波动维度 ---
        vola_factors = ["atr_percentile", "bollinger_position", "hv_percentile"]
        vola_scores = self._compute_factor_scores(panel, vola_factors)
        if vola_scores:
            scores["volatility"] = float(np.mean(vola_scores))
        else:
            scores["volatility"] = 50.0
            gaps.append("volatility_factors")

        # --- 5. 均线系统 ---
        ma_factors = ["ma_alignment", "ma_cross", "ma_support"]
        ma_scores = self._compute_factor_scores(panel, ma_factors)
        if ma_scores:
            scores["ma"] = float(np.mean(ma_scores))
            all_signals.extend(self._interpret_ma(ma_scores, panel))
        else:
            scores["ma"] = 50.0
            gaps.append("ma_factors")

        # --- 6. 打板情绪 ---
        if limit_up_snapshot:
            scores["limit_up"] = self._score_limit_up(limit_up_snapshot)
            all_signals.extend(self._interpret_limit_up(limit_up_snapshot, symbol))
        else:
            scores["limit_up"] = 50.0
            gaps.append("limit_up_data")

        # --- 聚合 ---
        composite = sum(
            scores.get(k, 50.0) * self._weights.get(k, 0.15)
            for k in self._weights
        )
        # 把打板维度权重放进去 (不在默认 weights 中时)
        if "limit_up" not in self._weights:
            composite = composite * 0.85 + scores.get("limit_up", 50.0) * 0.15

        # 置信度: 数据缺口越多越低
        confidence = max(0.3, 1.0 - len(gaps) * 0.15)

        # --- 填充报告 ---
        report.trend_score = scores.get("trend", 50.0)
        report.reversal_score = scores.get("reversal", 50.0)
        report.volume_score = scores.get("volume", 50.0)
        report.volatility_score = scores.get("volatility", 50.0)
        report.ma_score = scores.get("ma", 50.0)
        report.limit_up_score = scores.get("limit_up", 50.0)
        report.composite_score = float(composite)
        report.signals = all_signals
        report.data_gaps = gaps
        report.confidence = confidence
        report.limit_up_snapshot = limit_up_snapshot
        report.source_citations = self._make_citations(symbol)

        return report

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _compute_factor_scores(
        self, panel: dict[str, pd.DataFrame], factor_ids: list[str]
    ) -> list[float]:
        """从 panel 中提取已计算的因子最新值。"""
        scores = []
        for fid in factor_ids:
            df = panel.get(fid)
            if df is not None and not df.empty:
                last_row = df.iloc[-1]
                if not last_row.isna().all():
                    scores.append(float(last_row.mean()))
        return scores

    def _interpret_trend(
        self, scores: list[float], panel: dict[str, pd.DataFrame]
    ) -> list[TechnicalSignal]:
        signals = []
        avg = float(np.mean(scores)) if scores else 50.0
        if avg > 65:
            signals.append(TechnicalSignal(
                indicator="TREND_COMPOSITE", direction="BULLISH", strength=avg / 100.0,
                description="趋势因子综合偏多 — MACD/MA/DMI 方向一致向上",
                is_entry=True,
            ))
        elif avg < 35:
            signals.append(TechnicalSignal(
                indicator="TREND_COMPOSITE", direction="BEARISH", strength=(100 - avg) / 100.0,
                description="趋势因子综合偏空 — 动能减弱，建议观望或减仓",
                is_exit=True,
            ))
        return signals

    def _interpret_reversal(
        self, scores: list[float], panel: dict[str, pd.DataFrame]
    ) -> list[TechnicalSignal]:
        signals = []
        avg = float(np.mean(scores)) if scores else 50.0
        if avg > 70:
            signals.append(TechnicalSignal(
                indicator="REVERSAL_COMPOSITE", direction="BULLISH", strength=avg / 100.0,
                description="反转因子显示超卖反弹机会 — RSI/KDJ/威廉%R 低位企稳",
                is_entry=True,
            ))
        elif avg < 30:
            signals.append(TechnicalSignal(
                indicator="REVERSAL_COMPOSITE", direction="BEARISH", strength=(100 - avg) / 100.0,
                description="反转因子超买 — RSI>70/KDJ高位，回调风险",
                is_exit=True,
            ))
        return signals

    def _interpret_volume(
        self, scores: list[float], panel: dict[str, pd.DataFrame]
    ) -> list[TechnicalSignal]:
        signals = []
        avg = float(np.mean(scores)) if scores else 50.0
        if avg > 65:
            signals.append(TechnicalSignal(
                indicator="VOLUME_COMPOSITE", direction="BULLISH", strength=avg / 100.0,
                description="量价因子偏多 — 放量温和+资金流入，量价配合良好",
                is_entry=True,
            ))
        elif avg < 35:
            signals.append(TechnicalSignal(
                indicator="VOLUME_COMPOSITE", direction="BEARISH", strength=(100 - avg) / 100.0,
                description="量价因子偏空 — 缩量或异常放量，资金参与度不足",
                is_exit=True,
            ))
        return signals

    def _interpret_ma(
        self, scores: list[float], panel: dict[str, pd.DataFrame]
    ) -> list[TechnicalSignal]:
        signals = []
        avg = float(np.mean(scores)) if scores else 50.0
        if avg > 70:
            signals.append(TechnicalSignal(
                indicator="MA_SYSTEM", direction="BULLISH", strength=avg / 100.0,
                description="均线系统多头排列+金叉 — MA5>MA10>MA20>MA60",
                is_entry=True,
            ))
        elif avg < 30:
            signals.append(TechnicalSignal(
                indicator="MA_SYSTEM", direction="BEARISH", strength=(100 - avg) / 100.0,
                description="均线空头排列或死叉 — 短期趋势走弱",
                is_exit=True,
            ))
        return signals

    def _interpret_limit_up(
        self, snapshot: dict, symbol: str
    ) -> list[TechnicalSignal]:
        signals = []
        zt_count = snapshot.get("zt_count", 0)
        zb_count = snapshot.get("zb_count", 0)
        break_rate = snapshot.get("break_rate", 0)

        if zt_count > 100 and break_rate < 0.3:
            signals.append(TechnicalSignal(
                indicator="LIMIT_UP_SENTIMENT", direction="BULLISH", strength=0.7,
                description=f"市场打板情绪活跃: {zt_count}家涨停，炸板率{break_rate:.0%}",
                is_entry=True,
            ))
        elif break_rate > 0.5:
            signals.append(TechnicalSignal(
                indicator="LIMIT_UP_SENTIMENT", direction="BEARISH", strength=0.6,
                description=f"打板情绪退潮: 炸板率{break_rate:.0%}，追高风险大",
                is_exit=True,
            ))

        # 标的是否在连板梯队中
        ladder = snapshot.get("ladder", {})
        for height_str, count in ladder.items():
            try:
                if int(height_str) >= 3 and count > 5:
                    signals.append(TechnicalSignal(
                        indicator="LIMIT_UP_LADDER", direction="BULLISH", strength=0.5,
                        description=f"连板梯队完整: {height_str}板有{count}家，短线情绪延续",
                    ))
            except (ValueError, TypeError):
                pass
            break

        return signals

    @staticmethod
    def _score_limit_up(snapshot: dict) -> float:
        """打板情绪评分 0-100。"""
        zt = snapshot.get("zt_count", 0)
        zb = snapshot.get("zb_count", 0)
        br = snapshot.get("break_rate", 0.5)
        max_h = snapshot.get("max_height", 0)

        # 涨停多 + 炸板低 + 有高度板 = 高分
        zt_score = min(zt / 150.0, 1.0) * 40.0     # 涨停家数贡献最多40分
        br_score = max(0, (1.0 - br * 2.0)) * 30.0  # 炸板率低贡献30分
        h_score = min(max_h / 5.0, 1.0) * 30.0      # 连板高度贡献30分
        return zt_score + br_score + h_score

    @staticmethod
    def _make_citations(symbol: str) -> list[SourceCitation]:
        return [
            make_citation(
                provider="factor_registry",
                field="l1_technical",
                data_type="technical_analysis",
                confidence=0.75,
            ),
        ]
