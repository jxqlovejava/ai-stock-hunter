# -*- coding: utf-8 -*-
"""反操纵验证关卡 (AntiManipulationGate)。

回调入场前的必经关卡，结合三层信息判断回调真伪:
  1. ManipulationDetector — 日内 7 种操盘手法实时检测
  2. ManipulationHistoryStore — 标的操纵历史 (repeat_offender)
  3. SentimentManipulationNexus — 情绪-操纵联动分析

输出: ManipulationCheck (is_trap / is_shakeout / 置信度调整)
"""

from __future__ import annotations

import logging
from typing import Optional

from src.data.schema import Bar
from .schemas import ManipulationCheck, PullbackState

logger = logging.getLogger(__name__)


class AntiManipulationGate:
    """反操纵验证关卡。

    在回调入场前验证回调是否为庄家操纵的陷阱。

    用法:
        gate = AntiManipulationGate()
        check = gate.verify("002460", daily_bars, minute_df, pullback_state)
        if check.is_trap:
            print("禁止入场 — 操纵陷阱")
    """

    # ── 陷阱模式映射 ──
    # 这些 playbook 在回调场景中 = 诱多陷阱
    TRAP_PLAYBOOKS = {
        "lure_bull_dump": 0.9,       # 诱多出货 → 极高陷阱概率
        "fishing_line": 0.85,        # 钓鱼线 → 极高陷阱概率
        "wash_trade_pump": 0.7,      # 对倒拉升 → 高陷阱概率
        "closing_manipulation": 0.6, # 尾盘拉升 → 中高陷阱概率
    }

    # 这些 playbook 在回调场景中 = 可能是洗盘
    SHAKEOUT_PLAYBOOKS = {
        "lure_bear_accumulate": 0.7,  # 诱空吸筹 → 可能是洗盘
        "shakeout": 0.85,             # 洗盘震仓 → 大概率洗盘
    }

    def __init__(self):
        self._detector = None
        self._history_store = None
        self._sentiment_nexus = None
        self._initialized = False

    def _lazy_init(self):
        """延迟导入，避免循环依赖。"""
        if self._initialized:
            return
        try:
            from src.game_theory.manipulation import (
                ManipulationDetector,
                ManipulationHistoryStore,
                SentimentManipulationNexus,
            )
            self._detector = ManipulationDetector()
            self._history_store = ManipulationHistoryStore()
            self._sentiment_nexus = SentimentManipulationNexus()
        except ImportError as e:
            logger.warning("反操纵模块导入失败: %s，操纵检测将跳过", e)
        self._initialized = True

    def verify(
        self,
        symbol: str,
        daily_bars: list[Bar],
        minute_data,  # pd.DataFrame
        *,
        pullback_state: Optional[PullbackState] = None,
        sentiment_level: str = "NORMAL",
        sentiment_score: float = 50.0,
        name: str = "",
    ) -> ManipulationCheck:
        """执行反操纵验证。

        Args:
            symbol: 6 位股票代码
            daily_bars: 日线 Bar 列表
            minute_data: pd.DataFrame 分钟级数据
            pullback_state: 回调检测结果（可选，用于上下文）
            sentiment_level: 大盘情绪等级
            sentiment_score: 大盘情绪分 0-100
            name: 股票名称

        Returns:
            ManipulationCheck with is_trap, is_shakeout, risk_score, etc.
        """
        check = ManipulationCheck()

        self._lazy_init()

        # ── 层 1: 实时操纵检测 ──
        if self._detector is not None and minute_data is not None:
            try:
                result = self._detector.detect(symbol, minute_data, name=name)
                if result and result.signals:
                    check.risk_score = result.risk_score
                    check.risk_level = result.risk_level
                    for sig in result.signals:
                        check.signals_matched.append(
                            f"{sig.playbook_name} (置信度 {sig.confidence:.0%})"
                        )

                        # 判断是否为陷阱
                        if sig.playbook_id in self.TRAP_PLAYBOOKS:
                            if sig.confidence >= 0.6:
                                check.is_trap = True
                                check.suggestion = sig.suggestion

                        # 判断是否为洗盘
                        if sig.playbook_id in self.SHAKEOUT_PLAYBOOKS:
                            if sig.confidence >= 0.5:
                                check.is_shakeout = True
                                check.suggestion = sig.suggestion
            except Exception as e:
                logger.warning("实时操纵检测失败 [%s]: %s", symbol, e)

        # ── 层 2: 历史操纵记录 ──
        if self._history_store is not None:
            try:
                profile = self._history_store.load_profile(symbol)
                if profile and profile.repeat_offender:
                    check.repeat_offender = True
                    check.risk_score = max(check.risk_score, 60.0)
                    check.signals_matched.append(
                        f"⚠️ 历史 repeat_offender: {profile.total_incidents} 次操纵记录, "
                        f"最常见类型: {profile.most_common_type}"
                    )
                # 加历史风险
                if profile and profile.total_incidents > 0:
                    check.risk_score = max(
                        check.risk_score,
                        min(80.0, profile.avg_risk_score * 1.2),
                    )
            except Exception as e:
                logger.warning("历史操纵查询失败 [%s]: %s", symbol, e)

        # ── 层 3: 情绪-操纵联动 ──
        if self._sentiment_nexus is not None and check.signals_matched:
            try:
                # 提取 playbook IDs
                playbook_ids = []
                if self._detector is not None and minute_data is not None:
                    try:
                        result = self._detector.detect(symbol, minute_data, name=name)
                        if result and result.signals:
                            playbook_ids = [s.playbook_id for s in result.signals]
                    except Exception:
                        pass

                if playbook_ids:
                    nexus = self._sentiment_nexus.analyze(
                        sentiment_level, sentiment_score, playbook_ids
                    )
                    if nexus:
                        check.sentiment_context = nexus.pattern
                        check.confidence_adjustment = nexus.confidence_delta
                        check.risk_score += nexus.confidence_delta * 10
            except Exception as e:
                logger.warning("情绪-操纵联动分析失败 [%s]: %s", symbol, e)

        # ── 回调场景特有判断 ──
        # 回调场景中: 洗盘震仓 ≠ 陷阱（存量持仓可加仓）
        if check.is_shakeout and not check.is_trap:
            check.suggestion = (
                "⚠️ 疑似洗盘震仓 — "
                "庄家可能在回调中制造恐慌以便低吸。"
                "有持仓可持有/轻仓加仓，空仓建议再等 1 日确认方向。"
            )

        if check.is_trap:
            if check.repeat_offender:
                check.suggestion = (
                    f"🔴 高风险: 当前检测到操纵信号 + 该标的历史有 "
                    f"多次操纵记录。强烈建议回避，等待更长确认周期。"
                )
            check.risk_level = "high"

        return check
