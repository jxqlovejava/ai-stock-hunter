# -*- coding: utf-8 -*-
"""买点/卖点 — 技术时机 × 博弈论融合。

纯技术入场/出场不够：同一「突破」在游资主导 vs 机构主导下含义不同。
本模块把 EntryExitEngine 信号与 GameTheoryProfile 叠成可执行建议：

  买点：谁在买、是否拥挤、席位方向、玩家风格是否匹配该技术形态
  卖点：谁在出、拥挤踩踏、游资出货、杠杆过热

轻路径(light)与全链路共用，不拉重辩论。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class GTTimingAdvice:
    """买/卖点博弈融合结论。"""

    action: str = "WAIT"  # ENTER / WAIT / HOLD / REDUCE / EXIT
    buy_point: str = ""
    sell_point: str = ""
    entry_allowed: bool = False
    exit_urgency: str = "none"  # none / normal / high / urgent
    size_hint: float = 1.0  # 0~1 仓位折扣建议
    dominant_player: str = ""
    gt_score: int = 50
    seat_signal: str = "unknown"
    crowding_score: int = 50
    tech_entry_type: str = ""
    tech_exit_type: str = ""
    confidence: float = 0.4
    rationale: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "action": self.action,
            "buy_point": self.buy_point,
            "sell_point": self.sell_point,
            "entry_allowed": self.entry_allowed,
            "exit_urgency": self.exit_urgency,
            "size_hint": self.size_hint,
            "dominant_player": self.dominant_player,
            "gt_score": self.gt_score,
            "seat_signal": self.seat_signal,
            "crowding_score": self.crowding_score,
            "tech_entry_type": self.tech_entry_type,
            "tech_exit_type": self.tech_exit_type,
            "confidence": self.confidence,
            "rationale": list(self.rationale),
            "risks": list(self.risks),
        }


# 玩家中文
_PLAYER_CN = {
    "hot_money": "游资",
    "institutional": "机构",
    "quant": "量化",
    "national_team": "国家队",
    "northbound": "北向",
    "retail": "散户",
    "manipulator": "庄家/控盘",
}

# 技术买点与玩家风格匹配度 (1.0 匹配 / <1 不匹配)
_ENTRY_PLAYER_FIT = {
    # entry_type: {player: mult}
    "BREAKOUT": {
        "hot_money": 1.15,
        "quant": 1.05,
        "institutional": 0.75,  # 机构少追突破
        "national_team": 0.6,
    },
    "MA_GOLDEN_CROSS": {
        "institutional": 1.1,
        "northbound": 1.05,
        "hot_money": 0.9,
    },
    "PULLBACK_SUPPORT": {
        "institutional": 1.2,
        "northbound": 1.15,
        "national_team": 1.1,
        "hot_money": 0.85,  # 游资不爱阴跌回踩
    },
    "OVERSOLD_BOUNCE": {
        "quant": 1.1,
        "hot_money": 0.95,
        "institutional": 0.85,
    },
    "BOTTOM_STRUCTURE": {
        "institutional": 1.15,
        "national_team": 1.1,
        "northbound": 1.05,
        "hot_money": 0.8,
    },
}


def fuse_timing_with_game_theory(
    timing: Any = None,
    gt: Any = None,
    *,
    held: bool = False,
    current_price: float = 0.0,
    position_loss_pct: float = 0.0,
    bottom_phase: str = "",
) -> GTTimingAdvice:
    """融合技术时机与博弈论，输出买/卖点建议。

    Args:
        timing: TimingResult 或 None
        gt: GameTheoryProfile 或 dict 或 None
        held: 是否已持仓
        current_price: 现价
        position_loss_pct: 浮亏比例（ratio，如 -0.1）
        bottom_phase: 底部结构阶段字符串
    """
    advice = GTTimingAdvice()
    reasons: list[str] = []
    risks: list[str] = []

    # --- 解析 GT ---
    if gt is None:
        advice.rationale.append("[DATA_GAP] 无博弈论画像，仅技术面")
        gt_score = 50
        player = ""
        seat = "unknown"
        crowding = 50
        nb = 50
        margin = 50
        gt_risks: list[str] = []
    else:
        if isinstance(gt, dict):
            gt_score = int(gt.get("score", 50) or 50)
            player = str(gt.get("dominant_player", "") or "")
            seat = str(gt.get("seat_signal", "unknown") or "unknown")
            crowding = int(gt.get("crowding_score", 50) or 50)
            nb = int(gt.get("northbound_score", 50) or 50)
            margin = int(gt.get("margin_score", 50) or 50)
            gt_risks = list(gt.get("risks") or [])
        else:
            gt_score = int(getattr(gt, "score", 50) or 50)
            player = str(getattr(gt, "dominant_player", "") or "")
            seat = str(getattr(gt, "seat_signal", "unknown") or "unknown")
            crowding = int(getattr(gt, "crowding_score", 50) or 50)
            nb = int(getattr(gt, "northbound_score", 50) or 50)
            margin = int(getattr(gt, "margin_score", 50) or 50)
            gt_risks = list(getattr(gt, "risks", None) or [])

    advice.gt_score = gt_score
    advice.dominant_player = player
    advice.seat_signal = seat
    advice.crowding_score = crowding
    player_cn = _PLAYER_CN.get(player, player or "未知")
    reasons.append(f"主导玩家: {player_cn}  博弈分{gt_score}  拥挤{crowding}  席位{seat}")

    # --- 解析技术 ---
    best_entry = None
    best_exit = None
    entry_conf = 0.0
    exit_conf = 0.0
    urgent_exit = False
    if timing is not None:
        best_entry = getattr(timing, "best_entry", None)
        exits = list(getattr(timing, "exit_signals", None) or [])
        if exits:
            best_exit = max(exits, key=lambda s: (
                2 if getattr(s, "urgency", "") == "URGENT" else 0,
                float(getattr(s, "confidence", 0) or 0),
            ))
            urgent_exit = any(getattr(s, "urgency", "") == "URGENT" for s in exits)
        if best_entry:
            advice.tech_entry_type = getattr(best_entry, "type", "") or ""
            entry_conf = float(getattr(best_entry, "confidence", 0) or 0)
        if best_exit:
            advice.tech_exit_type = getattr(best_exit, "type", "") or ""
            exit_conf = float(getattr(best_exit, "confidence", 0) or 0)

    # --- 玩家×形态匹配 ---
    fit = 1.0
    if advice.tech_entry_type and player:
        fit = _ENTRY_PLAYER_FIT.get(advice.tech_entry_type, {}).get(player, 1.0)
        if fit >= 1.1:
            reasons.append(f"形态{advice.tech_entry_type} 匹配 {player_cn} 风格 (+)")
        elif fit <= 0.85:
            reasons.append(f"形态{advice.tech_entry_type} 与 {player_cn} 风格不匹配 (−)")
            risks.append(f"style_mismatch: {advice.tech_entry_type}×{player}")

    adj_entry = entry_conf * fit
    adj_exit = exit_conf

    # --- 席位 ---
    if seat == "bullish":
        adj_entry *= 1.12
        reasons.append("龙虎榜席位净买入，买点加分")
    elif seat == "bearish":
        adj_entry *= 0.7
        adj_exit = max(adj_exit, 0.55)
        reasons.append("龙虎榜席位净卖出，卖点/减仓优先")
        risks.append("seat_distribution_sell")

    # --- 拥挤 ---
    size_hint = 1.0
    if crowding >= 70:
        adj_entry *= 0.45
        adj_exit = max(adj_exit, 0.65)
        size_hint = min(size_hint, 0.3)
        reasons.append("公募拥挤≥70：禁止追高，持仓警惕踩踏")
        risks.append("sector_crowded")
    elif crowding >= 55:
        adj_entry *= 0.8
        size_hint = min(size_hint, 0.7)
        reasons.append("拥挤偏高，新开仓减半")

    # --- 游资专项 ---
    if player == "hot_money":
        if advice.tech_entry_type == "BREAKOUT":
            reasons.append("游资主导+突破：只跟龙头短线，设紧止损")
            size_hint = min(size_hint, 0.5)
            if not held:
                risks.append("hot_money_chase: 游资突破追单易成接盘")
        if advice.tech_exit_type in ("VOLUME_STALL", "OVERBOUGHT", "LIMIT_UP_BROKEN"):
            adj_exit = max(adj_exit, 0.75)
            reasons.append("游资主导+滞涨/超买/开板：优先兑现")
        if margin >= 75:
            adj_exit = max(adj_exit, 0.6)
            reasons.append("融资情绪过热，游资行情反转风险上升")

    # --- 机构专项 ---
    if player == "institutional":
        if advice.tech_entry_type in ("PULLBACK_SUPPORT", "BOTTOM_STRUCTURE", "MA_GOLDEN_CROSS"):
            adj_entry *= 1.08
            reasons.append("机构主导：回踩/底部/金叉类买点更可靠")
        if crowding >= 70 and held:
            adj_exit = max(adj_exit, 0.7)
            reasons.append("机构抱团拥挤：瓦解踩踏优先卖点")

    # --- 北向/杠杆 ---
    if nb >= 65 and seat != "bearish":
        adj_entry *= 1.05
        reasons.append(f"北向偏多({nb})，支撑中长线买点")
    if margin <= 35:
        reasons.append("融资偏空/去杠杆，买点需更苛刻")
        adj_entry *= 0.85
    elif margin >= 80:
        risks.append("leverage_greedy")
        adj_entry *= 0.75

    # --- 底部结构纪律 ---
    if bottom_phase == "CATCHING_KNIFE":
        adj_entry = 0.0
        reasons.append("底部结构 B≥A：禁止抄底（接飞刀）")
        risks.append("catching_knife")
    elif bottom_phase == "LIGHT_LONG_SETUP" and player != "hot_money":
        adj_entry = max(adj_entry, 0.55)
        reasons.append("底部结构轻仓试多 setup + 非游资主导")

    # --- 浮亏/持仓 ---
    if held and position_loss_pct <= -0.08:
        adj_exit = max(adj_exit, 0.7)
        reasons.append(f"浮亏 {position_loss_pct:.1%}，卖点/止损优先级上升")

    # 紧急技术出场
    if urgent_exit:
        adj_exit = max(adj_exit, 0.8)
        reasons.append("技术面紧急出场信号")

    advice.size_hint = round(max(0.0, min(1.0, size_hint)), 2)

    # --- 裁决动作 ---
    # 卖点文本
    if best_exit is not None:
        ez_lo = getattr(best_exit, "exit_zone_low", 0) or 0
        ez_hi = getattr(best_exit, "exit_zone_high", 0) or 0
        zone = f"[{ez_lo:.2f}-{ez_hi:.2f}]" if ez_lo or ez_hi else ""
        advice.sell_point = (
            f"{advice.tech_exit_type} {zone} | 博弈:{player_cn}/席位{seat}/拥挤{crowding}"
        ).strip()
    elif seat == "bearish" or crowding >= 70:
        advice.sell_point = f"博弈卖压（席位{seat}/拥挤{crowding}）— 即使无技术破位也宜减"
    elif held and position_loss_pct <= -0.02:
        advice.sell_point = f"持仓浮亏 {position_loss_pct:.1%} — 守纪律止损位"
    else:
        advice.sell_point = "暂无明确卖点"

    # 买点文本
    if best_entry is not None and adj_entry >= 0.35:
        el = getattr(best_entry, "entry_zone_low", 0) or 0
        eh = getattr(best_entry, "entry_zone_high", 0) or 0
        zone = f"[{el:.2f}-{eh:.2f}]" if el or eh else (
            f"~{current_price:.2f}" if current_price else ""
        )
        advice.buy_point = (
            f"{advice.tech_entry_type} {zone} | 匹配{player_cn} 调整置信{adj_entry:.0%}"
        ).strip()
    elif gt_score >= 60 and seat == "bullish" and crowding < 55 and not held:
        advice.buy_point = f"博弈偏多但缺技术触发 — 等回踩/金叉再动手（{player_cn}）"
    else:
        advice.buy_point = "暂无合格买点（技术×博弈未共振）"

    # action
    entry_ok = (
        not held
        and adj_entry >= 0.45
        and crowding < 70
        and bottom_phase != "CATCHING_KNIFE"
        and seat != "bearish"
    )
    # 游资突破：仅 adj 更高才允许
    if player == "hot_money" and advice.tech_entry_type == "BREAKOUT":
        entry_ok = entry_ok and adj_entry >= 0.55

    advice.entry_allowed = entry_ok

    if held:
        if adj_exit >= 0.75 or urgent_exit or (seat == "bearish" and crowding >= 60):
            advice.action = "EXIT"
            advice.exit_urgency = "urgent" if (urgent_exit or adj_exit >= 0.8) else "high"
        elif adj_exit >= 0.55 or seat == "bearish" or crowding >= 70:
            advice.action = "REDUCE"
            advice.exit_urgency = "high" if crowding >= 70 else "normal"
        elif position_loss_pct <= -0.08:
            advice.action = "REDUCE"
            advice.exit_urgency = "high"
        else:
            advice.action = "HOLD"
            advice.exit_urgency = "none"
    else:
        if entry_ok:
            advice.action = "ENTER"
            advice.exit_urgency = "none"
        else:
            advice.action = "WAIT"
            advice.exit_urgency = "none"

    # 置信
    base_c = 0.35
    if timing is not None:
        base_c += 0.15
    if gt is not None:
        base_c += 0.15
    if best_entry or best_exit:
        base_c += 0.1
    if seat in ("bullish", "bearish"):
        base_c += 0.05
    advice.confidence = round(min(0.85, base_c + abs(adj_entry - 0.5) * 0.1), 2)

    # 风险合并
    for r in gt_risks[:5]:
        if r not in risks:
            risks.append(r)
    advice.rationale = reasons
    advice.risks = risks
    return advice


def print_gt_timing(advice: GTTimingAdvice) -> None:
    """CLI 友好打印。"""
    action_emoji = {
        "ENTER": "🟢",
        "WAIT": "⚪",
        "HOLD": "🟡",
        "REDUCE": "🟠",
        "EXIT": "🔴",
    }
    em = action_emoji.get(advice.action, "❓")
    print("\n" + "=" * 50)
    print("  🎯 买点/卖点（技术 × 博弈论）")
    print("=" * 50)
    print(f"  动作: {em} {advice.action}  紧急度:{advice.exit_urgency}  仓位提示×{advice.size_hint}")
    print(f"  买点: {advice.buy_point}")
    print(f"  卖点: {advice.sell_point}")
    print(
        f"  博弈: 玩家={_PLAYER_CN.get(advice.dominant_player, advice.dominant_player or '?')} "
        f"分{advice.gt_score} 拥挤{advice.crowding_score} 席位{advice.seat_signal}"
    )
    print(f"  置信: {advice.confidence:.0%}")
    if advice.rationale:
        print("  依据:")
        for line in advice.rationale[:8]:
            print(f"    · {line}")
    if advice.risks:
        print("  风险:")
        for r in advice.risks[:5]:
            print(f"    ⚠️ {r}")
    print("=" * 50)
