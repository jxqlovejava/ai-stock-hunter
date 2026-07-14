# -*- coding: utf-8 -*-
"""多波洗盘→拉升 生命周期分析 (WashCycleAnalyzer)。

来源提炼（短视频「主力洗盘/等散户割完再拉」）:
  1. 连续下杀制造恐慌
  2. **后半段** 散户割肉最猛
  3. 第一次反弹后可能 **再洗第二遍**
  4. 可能借 **中报/业绩叙事** 做空头掩护
  5. 洗到「砸不走」筹码后才进入 **主升**

与现有模式关系（去重策略）:
  - **不重复** 检测单日急跌/高开低走等形态（仍由 WashoutDetector 负责）
  - **本模块只做日线级多波生命周期状态机** + 持仓操作提示
  - 与 ``washout_consecutive_yin`` / ``washout_small_rise_big_drop`` 互补：
    它们报「形态」，本模块报「处在第几波、后半段风险、是否疑似洗完」
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

import numpy as np


class WashCyclePhase(str, Enum):
    """多波洗盘生命周期阶段。"""

    QUIET = "quiet"                       # 无明显洗盘序列
    WAVE1_DECLINE = "wave1_decline"       # 第一波连续下杀
    FALSE_BOUNCE = "false_bounce"         # 弱反弹（诱多/喘息）
    WAVE2_DECLINE = "wave2_decline"       # 第二波再洗
    LATTER_HALF_CAPITULATION = "latter_half_capitulation"  # 连续下跌后半段（割肉高峰）
    WASH_EXHAUSTION = "wash_exhaustion"   # 量能枯竭 / 砸不动
    MARKUP_CANDIDATE = "markup_candidate" # 疑似洗完进入拉升候选
    FAILED_WASHOUT = "failed_washout"     # 更像真出货/崩盘（跌幅过大或放量长跌）


@dataclass
class WashCycleResult:
    """多波洗盘生命周期结果。"""

    symbol: str = ""
    name: str = ""
    phase: WashCyclePhase = WashCyclePhase.QUIET
    confidence: float = 0.0
    wave_count: int = 0
    decline_days: int = 0
    cumulative_drop_pct: float = 0.0
    latter_half_cut_risk: bool = False      # 是否处于「后半段割肉」高风险
    second_wave_active: bool = False
    earnings_cover_flag: bool = False       # 调用方注入：是否在财报窗口
    retail_action_hint: str = ""            # 对持仓者的操作提示
    evidence: list[str] = field(default_factory=list)
    related_playbook_ids: list[str] = field(default_factory=list)
    summary: str = ""
    created_at: datetime = field(default_factory=datetime.now)

    def to_manipulation_signal_dict(self) -> dict:
        """转为与 ManipulationSignal 兼容的 dict（便于 CLI 打印）。"""
        return {
            "playbook_id": "wash_then_markup",
            "playbook_name": "多波洗盘后拉升 (连续下杀→后半段割肉→再洗→洗不动才拉)",
            "confidence": self.confidence,
            "risk_level": "high" if self.latter_half_cut_risk else "medium",
            "detected_at": self.phase.value,
            "evidence": self.evidence,
            "suggestion": self.retail_action_hint,
            "scene": "daily",
            "phase": self.phase.value,
            "wave_count": self.wave_count,
            "latter_half_cut_risk": self.latter_half_cut_risk,
        }


# 阈值（与 washout 日级阈值对齐，避免两套标准）
_MIN_DECLINE_DAYS = 4
_MAX_CUM_DROP_WASHOUT = 0.22          # >22% 更像真出货
_MIN_CUM_DROP = 0.05
_WAVE_BOUNCE_MIN = 0.015              # 弱反弹至少 1.5%
_WAVE_BOUNCE_MAX = 0.06              # 反弹 >6% 可能不是假反弹
_VOLUME_DRY_RATIO = 0.65             # 近 3 日均量 / 下跌前 5 日均量
_MARKUP_DAY_MIN_RISE = 0.02          # 止跌后放量阳线 ≥2%
# 后半段: decline_days>=6 或 (第二波 and days>=5)


class WashCycleAnalyzer:
    """日线多波洗盘生命周期分析器。"""

    def analyze(
        self,
        symbol: str,
        daily_bars: list[dict],
        *,
        name: str = "",
        earnings_window: bool = False,
    ) -> WashCycleResult:
        """分析日线序列上的多波洗盘生命周期。

        Args:
            daily_bars: 按时间升序 [{open,high,low,close,volume,date}, ...]，建议 ≥15 根
            earnings_window: 是否处于财报/中报披露前后（调用方注入，本模块不做公告解析）
        """
        if not daily_bars or len(daily_bars) < 8:
            return WashCycleResult(
                symbol=symbol,
                name=name,
                summary="日线不足 8 根，无法做多波洗盘生命周期判断",
            )

        closes = np.array([float(b.get("close") or 0) for b in daily_bars], dtype=float)
        opens = np.array([float(b.get("open") or b.get("close") or 0) for b in daily_bars], dtype=float)
        volumes = np.array([float(b.get("volume") or 0) for b in daily_bars], dtype=float)
        if np.any(closes <= 0):
            return WashCycleResult(symbol=symbol, name=name, summary="价格数据异常")

        # 1) 从末段回溯连续下跌段（允许少量阳线噪声）
        decline_start, decline_days, cum_drop = self._find_recent_decline(closes)
        evidence: list[str] = []
        related = ["washout_consecutive_yin", "shakeout", "washout_small_rise_big_drop"]

        if decline_days < _MIN_DECLINE_DAYS or cum_drop < _MIN_CUM_DROP:
            # 检查是否刚出现止跌放量阳线（前一段有下跌）
            markup = self._detect_markup_after_wash(closes, volumes)
            if markup:
                return WashCycleResult(
                    symbol=symbol,
                    name=name,
                    phase=WashCyclePhase.MARKUP_CANDIDATE,
                    confidence=markup["confidence"],
                    wave_count=markup.get("waves", 1),
                    decline_days=markup.get("decline_days", 0),
                    cumulative_drop_pct=markup.get("cum_drop", 0.0),
                    latter_half_cut_risk=False,
                    earnings_cover_flag=earnings_window,
                    evidence=markup["evidence"],
                    related_playbook_ids=related + ["wash_then_markup"],
                    retail_action_hint=(
                        "🟢 疑似洗盘结束后的拉升候选：连跌后出现缩量企稳/放量阳线。"
                        "若持仓未被洗出，可观察跟风确认；未持仓勿盲目追高。"
                    ),
                    summary=markup["summary"],
                )
            return WashCycleResult(
                symbol=symbol,
                name=name,
                phase=WashCyclePhase.QUIET,
                confidence=0.2,
                summary="未识别到足够长的多日洗盘序列",
            )

        evidence.append(
            f"近段连续偏弱 {decline_days} 日，累计跌幅 {cum_drop:.1%}"
            f"（起点索引 {decline_start}）"
        )

        # 2) 真出货过滤：跌幅过大
        if cum_drop > _MAX_CUM_DROP_WASHOUT:
            return WashCycleResult(
                symbol=symbol,
                name=name,
                phase=WashCyclePhase.FAILED_WASHOUT,
                confidence=0.7,
                wave_count=1,
                decline_days=decline_days,
                cumulative_drop_pct=cum_drop,
                latter_half_cut_risk=True,
                earnings_cover_flag=earnings_window,
                evidence=evidence + [f"累计跌幅 {cum_drop:.1%} > 22%，更像真出货/趋势破位"],
                related_playbook_ids=["washout_consecutive_yin"],
                retail_action_hint="🔴 跌幅过大，不宜按「洗盘别割」处理；优先风控/止损纪律。",
                summary="多日长跌且跌幅过大，排除经典「洗完再拉」假设",
            )

        # 3) 识别波次：下跌中的假反弹
        waves, bounce_info = self._count_waves(closes[decline_start:])
        second_wave = waves >= 2
        if bounce_info:
            evidence.extend(bounce_info)

        # 4) 后半段割肉风险：连弱 ≥6 日，或第二波进行中且累计偏弱 ≥5 日
        latter_half = decline_days >= 6 or (second_wave and decline_days >= 5)

        phase = WashCyclePhase.WAVE1_DECLINE
        if second_wave:
            phase = WashCyclePhase.WAVE2_DECLINE
            evidence.append("识别到 ≥2 波「跌→弱反弹→再跌」，符合再洗第二遍")
        if latter_half:
            phase = WashCyclePhase.LATTER_HALF_CAPITULATION
            evidence.append(
                "处于连续下跌后半段：视频经验上散户割肉最集中，"
                "主力常等到此处才考虑结束洗盘"
            )

        # 5) 量能枯竭（砸不动）
        vol_dry, vol_ev = self._volume_exhaustion(volumes, decline_start)
        if vol_dry:
            phase = WashCyclePhase.WASH_EXHAUSTION
            evidence.append(vol_ev)
            related = related + ["wash_then_markup"]

        # 6) 财报窗口
        if earnings_window:
            evidence.append("处于财报/中报窗口：可能用业绩叙事掩护洗盘（需结合公告核验）")
            related = list(dict.fromkeys(related + ["wash_then_markup"]))

        # 7) 置信度
        conf = 0.45
        conf += min(0.15, (decline_days - 3) * 0.03)
        conf += min(0.15, (cum_drop - 0.05) * 1.5)
        if second_wave:
            conf += 0.12
        if vol_dry:
            conf += 0.12
        if earnings_window:
            conf += 0.05
        conf = min(0.88, conf)

        # 8) 操作提示（持仓 overlay 可引用）
        if phase == WashCyclePhase.WASH_EXHAUSTION:
            hint = (
                "🟡 量能枯竭、疑似「砸不走」：洗盘或近尾声。"
                "持仓者避免在最后一跌恐慌清仓；新仓仍须管道评分+风控，禁止裸追。"
            )
        elif phase == WashCyclePhase.LATTER_HALF_CAPITULATION:
            hint = (
                "🟠 连续下跌后半段=割肉高峰：主力叙事常在此处逼出最后筹码。"
                "若管道仍 HOLD 且止损未破系统硬线，避免「后半段割肉」；"
                "若破止损/真出货特征，仍执行纪律。"
            )
        elif phase == WashCyclePhase.WAVE2_DECLINE:
            hint = (
                "🟠 第二波再洗：第一次反弹后的再杀最易洗掉回补盘。"
                "勿把弱反弹当反转满仓回补；滚动仓遵守 overlay 禁越跌越加。"
            )
        else:
            hint = (
                "🟡 第一波下杀进行中：区分洗盘与出货——看量能是否递减、跌幅是否失控。"
                "单票纪律优先于「扛洗盘」口号。"
            )

        summary = (
            f"多波洗盘生命周期: {phase.value} | 波次≈{waves} | "
            f"连弱{decline_days}日 | 累计{cum_drop:.1%} | "
            f"后半段割肉风险={'是' if latter_half else '否'}"
        )

        return WashCycleResult(
            symbol=symbol,
            name=name,
            phase=phase,
            confidence=round(conf, 2),
            wave_count=waves,
            decline_days=decline_days,
            cumulative_drop_pct=round(cum_drop, 4),
            latter_half_cut_risk=latter_half and phase != WashCyclePhase.WASH_EXHAUSTION,
            second_wave_active=second_wave,
            earnings_cover_flag=earnings_window,
            retail_action_hint=hint,
            evidence=evidence,
            related_playbook_ids=list(dict.fromkeys(related + ["wash_then_markup"])),
            summary=summary,
        )

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _find_recent_decline(self, closes: np.ndarray) -> tuple[int, int, float]:
        """从末尾向前找「整体向下」的区间，返回 (start_idx, days, cum_drop)."""
        n = len(closes)
        end = n - 1
        # 允许最多 30% 阳线噪声
        start = end
        down_days = 0
        for i in range(end, 0, -1):
            if closes[i] <= closes[i - 1] * 1.005:
                start = i - 1
                down_days += 1
            else:
                # 小反弹：若后续仍创新低可延续
                if i < end and closes[end] < closes[i] * 0.99:
                    start = i - 1
                    continue
                break
        days = end - start + 1
        peak = float(np.max(closes[start : end + 1])) if days > 0 else closes[end]
        cum = (peak - closes[end]) / peak if peak > 0 else 0.0
        return start, days, cum

    def _count_waves(self, seg: np.ndarray) -> tuple[int, list[str]]:
        """在下跌段中数「跌→反弹→再跌」波次。"""
        if len(seg) < 5:
            return 1, []
        evidence: list[str] = []
        waves = 1
        i = 1
        while i < len(seg) - 2:
            # local trough then bounce
            if seg[i] <= seg[i - 1] and seg[i] <= seg[i + 1]:
                trough = seg[i]
                # look ahead bounce
                j = i + 1
                peak = trough
                while j < len(seg) and seg[j] >= seg[j - 1] * 0.998:
                    peak = max(peak, seg[j])
                    j += 1
                bounce = (peak - trough) / trough if trough > 0 else 0
                if _WAVE_BOUNCE_MIN <= bounce <= _WAVE_BOUNCE_MAX:
                    # then resume decline
                    if j < len(seg) and seg[-1] < peak * 0.99:
                        waves += 1
                        evidence.append(f"波内弱反弹 {bounce:.1%} 后继续下探")
                        i = j
                        continue
            i += 1
        return max(1, waves), evidence

    def _volume_exhaustion(
        self, volumes: np.ndarray, decline_start: int
    ) -> tuple[bool, str]:
        if decline_start < 5 or len(volumes) - decline_start < 3:
            return False, ""
        pre = volumes[max(0, decline_start - 5) : decline_start]
        recent = volumes[-3:]
        pre_m = float(np.mean(pre)) if len(pre) else 0.0
        rec_m = float(np.mean(recent)) if len(recent) else 0.0
        if pre_m <= 0:
            return False, ""
        ratio = rec_m / pre_m
        if ratio <= _VOLUME_DRY_RATIO:
            return True, f"近3日均量仅为下跌前的 {ratio:.0%}，卖压衰竭/疑似砸不动"
        return False, ""

    def _detect_markup_after_wash(self, closes: np.ndarray, volumes: np.ndarray) -> Optional[dict]:
        """检测：前段下跌 + 近日缩量 + 今日放量阳线。"""
        if len(closes) < 12:
            return None
        pre = closes[-12:-2]
        last = closes[-1]
        prev = closes[-2]
        peak = float(np.max(pre))
        trough = float(np.min(pre))
        if peak <= 0:
            return None
        cum = (peak - trough) / peak
        if cum < 0.05 or cum > _MAX_CUM_DROP_WASHOUT:
            return None
        # last day green and rise
        rise = (last - prev) / prev if prev > 0 else 0
        if rise < _MARKUP_DAY_MIN_RISE:
            return None
        vol_pre = float(np.mean(volumes[-12:-4])) if len(volumes) >= 12 else 0
        vol_last = float(volumes[-1])
        vol_mid = float(np.mean(volumes[-5:-1])) if len(volumes) >= 5 else vol_pre
        dry = vol_pre > 0 and vol_mid / vol_pre <= 0.8
        if not dry and not (vol_pre > 0 and vol_last / vol_pre >= 1.2):
            return None
        return {
            "confidence": 0.62 if dry else 0.55,
            "waves": 1,
            "decline_days": 10,
            "cum_drop": cum,
            "evidence": [
                f"前段累计回撤 {cum:.1%}",
                f"近日相对缩量后出现涨幅 {rise:.1%} 阳线",
            ],
            "summary": "连跌后缩量企稳/放量阳线，标记为拉升候选（需管道确认）",
        }
