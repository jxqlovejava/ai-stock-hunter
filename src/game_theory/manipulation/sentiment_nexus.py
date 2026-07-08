# -*- coding: utf-8 -*-
"""情绪-操纵联动分析 (Sentiment-Manipulation Nexus)。

将市场情绪与庄家操纵检测信号关联，根据情绪场景调整操纵检测置信度。
典型应用场景:
  - 恐慌洗盘 (panic_shakeout) — 极度恐慌 + 诱空/洗盘 → 置信度提升
  - 贪婪派发 (greed_distribution) — 极度贪婪 + 诱多钓鱼线 → 置信度提升
  - 恐惧收盘 (fear_closing) — 低位恐慌 + 尾盘异动 → 轻微提升

用法:
    nexus = SentimentManipulationNexus()
    ctx = nexus.analyze("PANIC", 25, signals)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional


# ── 数据模型 ──

@dataclass
class SentimentManipulationContext:
    """情绪-操纵关联分析结果。"""

    date: str = ""
    sentiment_level: str = "NORMAL"
    sentiment_score: int = 50
    nexus_patterns: list[str] = field(default_factory=list)
    confidence_adjustments: dict[str, float] = field(default_factory=dict)
    amplified_signals: list[dict] = field(default_factory=list)
    nexus_summary: str = ""
    data_quality: float = 1.0


# ── 联动检测常量 ──

# 情绪-操纵模式映射: (sentiment_level, {match_playbook_ids}) → nexus_pattern
_NEXUS_RULES: list[tuple[tuple[str, ...], tuple[str, ...], str]] = [
    # 恐慌盘面 + 诱空/洗盘 → 恐慌洗盘
    (("PANIC", "EXTREME_PANIC"), ("lure_bear_accumulate", "shakeout"), "panic_shakeout"),
    # 恐慌盘面 + 诱多出货 → 恐慌中的诱多陷阱（反常）
    (("PANIC", "EXTREME_PANIC"), ("lure_bull_dump",), "panic_bull_trap"),
    # 贪婪盘面 + 诱多/钓鱼线 → 贪婪派发
    (("GREED", "EXTREME_GREED"), ("lure_bull_dump", "fishing_line"), "greed_distribution"),
    # 贪婪盘面 + 尾盘拉升 → 贪婪收盘推高
    (("GREED", "EXTREME_GREED"), ("closing_manipulation",), "greed_closing_pump"),
]

# 情绪分数 FEAR 逻辑（NORMAL 但分数 < 40 + 尾盘 = 恐惧收盘）
_FEAR_CLOSING_SCORE_THRESHOLD = 40

# 各 nexus 对应的置信度调整表 (playbook_id -> delta)
_NEXUS_ADJUSTMENTS: dict[str, dict[str, float]] = {
    "panic_shakeout": {
        "lure_bear_accumulate": 0.15,
        "shakeout": 0.15,
    },
    "panic_bull_trap": {
        "lure_bull_dump": 0.10,
    },
    "greed_distribution": {
        "lure_bull_dump": 0.15,
        "fishing_line": 0.15,
    },
    "greed_closing_pump": {
        "closing_manipulation": 0.10,
    },
    "fear_closing": {
        "closing_manipulation": 0.05,
    },
}

# 调整值上下限
_ADJUSTMENT_CAP = 0.20
_MAX_FINAL_CONFIDENCE = 0.95


# ── Nexus 分析器 ──

class SentimentManipulationNexus:
    """情绪-操纵联动分析器。

    将市场情绪状态与已检测到的操纵手法做交叉匹配，
    识别经典的联动模式（如恐慌洗盘、贪婪派发），
    并对匹配的操纵信号做置信度调整。
    """

    def analyze(
        self,
        sentiment_level: str,
        sentiment_score: int,
        manipulation_signals: list[dict],
        panic_signals: Optional[list[str]] = None,
        greed_signals: Optional[list[str]] = None,
    ) -> SentimentManipulationContext:
        """执行情绪-操纵联动分析。

        Args:
            sentiment_level: 情绪等级 "EXTREME_PANIC"/"PANIC"/"NORMAL"/"GREED"/"EXTREME_GREED"
            sentiment_score: 情绪评分 0-100
            manipulation_signals: 操纵检测信号列表，每个 dict 包含
                playbook_id, playbook_name, confidence, risk_level
            panic_signals: 恐慌信号文字列表（来自 MarketSentiment）
            greed_signals: 贪婪信号文字列表（来自 MarketSentiment）

        Returns:
            SentimentManipulationContext 包含联动模式、调整、摘要
        """
        today_str = date.today().isoformat()
        panic_signals = panic_signals or []
        greed_signals = greed_signals or []

        # 检测联动模式
        nexus_patterns = self._detect_nexus(sentiment_level, manipulation_signals)

        # 特殊情况: FEAR 检测（NORMAL 级别但分数偏低 + 尾盘操纵）
        if "neutral" not in nexus_patterns and "fear_closing" not in nexus_patterns:
            if self._check_fear_closing(sentiment_level, sentiment_score, manipulation_signals):
                nexus_patterns.append("fear_closing")

        # 如果没有任何模式匹配，标记 neutral
        if not nexus_patterns:
            nexus_patterns.append("neutral")

        # 计算置信度调整
        adjustments = self._calc_adjustments(nexus_patterns)

        # 应用调整
        amplified_signals = self.apply_adjustments(manipulation_signals, adjustments, nexus_patterns)

        # 数据质量: 基于信号数量和覆盖度
        data_quality = self._calc_data_quality(manipulation_signals, nexus_patterns)

        # 构建 context
        ctx = SentimentManipulationContext(
            date=today_str,
            sentiment_level=sentiment_level,
            sentiment_score=sentiment_score,
            nexus_patterns=nexus_patterns,
            confidence_adjustments=adjustments,
            amplified_signals=amplified_signals,
            data_quality=round(data_quality, 2),
        )
        ctx.nexus_summary = self._generate_summary(ctx, panic_signals, greed_signals)

        return ctx

    # ────────────────────────────────────────────────────
    # 联动模式检测
    # ────────────────────────────────────────────────────

    def _detect_nexus(
        self,
        sentiment_level: str,
        manipulation_signals: list[dict],
    ) -> list[str]:
        """检测情绪与操纵信号之间的联动模式。

        对照 _NEXUS_RULES 逐条匹配，返回所有命中的 nexus 模式列表。
        如果情绪为 NORMAL 且没有任何匹配，返回 ["neutral"]。
        """
        patterns: list[str] = []

        # 提取当前信号中的 playbook_id 集合
        signal_ids = {s.get("playbook_id", "") for s in manipulation_signals if s.get("playbook_id")}

        for (levels, playbook_ids, nexus_pattern) in _NEXUS_RULES:
            if sentiment_level in levels:
                # 检查是否有匹配的 playbook_id
                matched_ids = signal_ids & set(playbook_ids)
                if matched_ids:
                    patterns.append(nexus_pattern)

        return patterns

    def _check_fear_closing(
        self,
        sentiment_level: str,
        sentiment_score: int,
        manipulation_signals: list[dict],
    ) -> bool:
        """检测恐惧收盘模式: NORMAL 级别但分数 < 40 + 尾盘操纵。

        Args:
            sentiment_level: 情绪等级
            sentiment_score: 情绪评分
            manipulation_signals: 操纵信号列表

        Returns:
            是否匹配恐惧收盘模式
        """
        if sentiment_level == "NORMAL" and sentiment_score < _FEAR_CLOSING_SCORE_THRESHOLD:
            for sig in manipulation_signals:
                if sig.get("playbook_id") == "closing_manipulation":
                    return True
        return False

    # ────────────────────────────────────────────────────
    # 置信度调整计算
    # ────────────────────────────────────────────────────

    def _calc_adjustments(self, nexus_patterns: list[str]) -> dict[str, float]:
        """根据联动模式计算各 playbook_id 的置信度调整值。

        Args:
            nexus_patterns: 联动模式名称列表

        Returns:
            dict[playbook_id, adjustment_delta]，所有调整值在 ±0.20 之间
        """
        adjustments: dict[str, float] = {}

        for pattern in nexus_patterns:
            if pattern == "neutral":
                continue
            playbook_deltas = _NEXUS_ADJUSTMENTS.get(pattern, {})
            for playbook_id, delta in playbook_deltas.items():
                # 累积调整（同一 playbook 可能被多个 nexus 命中）
                current = adjustments.get(playbook_id, 0.0)
                new_val = current + delta
                # 截断到 ±0.20
                new_val = max(-_ADJUSTMENT_CAP, min(_ADJUSTMENT_CAP, new_val))
                adjustments[playbook_id] = round(new_val, 2)

        return adjustments

    # ────────────────────────────────────────────────────
    # 调整应用
    # ────────────────────────────────────────────────────

    def apply_adjustments(
        self,
        manipulation_signals: list[dict],
        adjustments: dict[str, float],
        nexus_patterns: Optional[list[str]] = None,
    ) -> list[dict]:
        """对操纵信号应用置信度调整。

        遍历每个信号，如果其 playbook_id 在调整表中，则：
          - 在原 confidence 上叠加 delta
          - 最终置信度上限 0.95
          - 向 evidence 追加调整说明

        Args:
            manipulation_signals: 原始操纵信号列表
            adjustments: playbook_id -> delta 映射
            nexus_patterns: 联动模式列表（用于 evidence 备注）

        Returns:
            添加了 adjusted_confidence 字段的调整后信号列表
        """
        nexus_str = ", ".join(p for p in (nexus_patterns or []) if p != "neutral")

        amplified: list[dict] = []
        for sig in manipulation_signals:
            sig_copy = dict(sig)
            playbook_id = sig_copy.get("playbook_id", "")
            base_conf = float(sig_copy.get("confidence", 0.0))

            if playbook_id in adjustments:
                delta = adjustments[playbook_id]
                new_conf = base_conf + delta
                new_conf = min(new_conf, _MAX_FINAL_CONFIDENCE)
                new_conf = max(0.0, new_conf)
                sig_copy["adjusted_confidence"] = round(new_conf, 2)

                # 追加 evidence 备注
                evidence = list(sig_copy.get("evidence", []))
                if nexus_str:
                    evidence.append(f"sentiment_amplified: {nexus_str} (delta={delta:+.2f})")
                else:
                    evidence.append(f"sentiment_amplified (delta={delta:+.2f})")
                sig_copy["evidence"] = evidence
            else:
                # 未调整的信号仍保持原样
                sig_copy["adjusted_confidence"] = round(base_conf, 2)

            amplified.append(sig_copy)

        return amplified

    # ────────────────────────────────────────────────────
    # 数据质量评估
    # ────────────────────────────────────────────────────

    def _calc_data_quality(
        self,
        manipulation_signals: list[dict],
        nexus_patterns: list[str],
    ) -> float:
        """评估输入数据的整体质量。

        基于因素:
          - 至少 1 个操纵信号 → 满质量
          - 至少 1 个 nexus 模式命中 → +0.1（有意义的联动）
          - 无信号 → 0.3（几乎无意义）

        Returns:
            0.0-1.0 质量分数
        """
        if not manipulation_signals:
            return 0.3

        base = 0.8
        effective_patterns = [p for p in nexus_patterns if p != "neutral"]

        if effective_patterns:
            base += 0.1

        if len(manipulation_signals) >= 3:
            base += 0.1

        return min(1.0, base)

    # ────────────────────────────────────────────────────
    # 摘要生成
    # ────────────────────────────────────────────────────

    def _generate_summary(
        self,
        context: SentimentManipulationContext,
        panic_signals: Optional[list[str]] = None,
        greed_signals: Optional[list[str]] = None,
    ) -> str:
        """根据 context 生成中文自然语言摘要。

        Args:
            context: 已完成分析的 SentimentManipulationContext
            panic_signals: 恐慌信号文字列表
            greed_signals: 贪婪信号文字列表

        Returns:
            一句话或一小段中文描述
        """
        effective = [p for p in context.nexus_patterns if p != "neutral"]
        if not effective:
            return "无情绪-操纵联动信号，维持原始置信度。无调整。"

        parts: list[str] = []
        panic_count = len(panic_signals or [])
        greed_count = len(greed_signals or [])
        adj_count = sum(
            1 for sig in context.amplified_signals
            if sig.get("adjusted_confidence", 0.0) != sig.get("confidence", 0.0)
            and abs(sig.get("adjusted_confidence", 0.0) - sig.get("confidence", 0.0)) > 0.001
        )

        for pattern in effective:
            if pattern == "panic_shakeout":
                parts.append(
                    f"市场{context.sentiment_level}+检测到诱空吸筹/洗盘 → "
                    f"恐慌洗盘经典组合，置信度+0.15"
                )
            elif pattern == "panic_bull_trap":
                parts.append(
                    f"市场{context.sentiment_level}+诱多出货 → "
                    f"恐慌中诱多陷阱（反常行为），置信度+0.10"
                )
            elif pattern == "greed_distribution":
                parts.append(
                    f"市场{context.sentiment_level}+诱多/钓鱼线 → "
                    f"贪婪派发经典组合，置信度+0.15"
                )
            elif pattern == "greed_closing_pump":
                parts.append(
                    f"市场{context.sentiment_level}+尾盘拉升 → "
                    f"贪婪收盘推高，置信度+0.10"
                )
            elif pattern == "fear_closing":
                parts.append(
                    f"市场偏恐惧(score={context.sentiment_score})+尾盘异动 → "
                    f"恐惧收盘，置信度+0.05"
                )

        # 附加统计
        stat_parts: list[str] = []
        if panic_count:
            stat_parts.append(f"{panic_count} 个恐慌信号")
        if greed_count:
            stat_parts.append(f"{greed_count} 个贪婪信号")
        if adj_count:
            stat_parts.append(f"调整 {adj_count} 个信号")
        stats = "，".join(stat_parts)

        summary = "；".join(parts)
        if stats:
            summary += f"（{stats}）"

        return summary
