# -*- coding: utf-8 -*-
"""持仓哨兵引擎。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from .models import (
    AlertLevel,
    PositionSnapshot,
    QuoteSnapshot,
    SentinelAlert,
    SentinelResult,
)
from .quotes import fetch_quotes
from .state import SentinelStateStore

BEIJING = timezone(timedelta(hours=8))


@dataclass
class SentinelConfig:
    """可调阈值。"""

    positions_path: Path = Path("data/positions.json")
    state_path: Path = Path("data/sentinel_state.json")
    # 止损
    stop_hit_buffer_pct: float = 0.0  # 触及：price <= stop
    stop_near_pct: float = 1.5  # 距止损 ≤ 1.5% 预警
    # 成本
    cost_break_pct: float = 0.3  # 跌破成本超过 0.3% 才报
    # 日内
    day_drop_pct: float = 5.0
    day_rise_pct: float = 5.0
    jump_pct: float = 1.5  # 相对上次采样跳变
    accel_total_pct: float = 1.0
    accel_step_pct: float = 0.5
    amplitude_thresholds: list[float] = field(
        default_factory=lambda: [3.0, 5.0, 7.0, 10.0]
    )
    # 冷却（分钟）
    cool_p0: int = 5
    cool_p1: int = 20
    cool_p2: int = 45
    history_window: int = 5
    force_trading_hours: bool = False  # True=忽略交易时段（测试用）
    prefer_huatai: bool = False

    @classmethod
    def from_dict(cls, d: dict) -> "SentinelConfig":
        cfg = cls()
        for k, v in d.items():
            if k in ("positions_path", "state_path") and v is not None:
                setattr(cfg, k, Path(v))
            elif hasattr(cfg, k) and v is not None:
                setattr(cfg, k, v)
        return cfg


class SentinelEngine:
    """扫描持仓 → 产出预警（或静默）。"""

    def __init__(self, config: Optional[SentinelConfig] = None):
        self.config = config or SentinelConfig()
        self.store = SentinelStateStore(self.config.state_path)

    def load_positions(self, path: Optional[Path] = None) -> list[PositionSnapshot]:
        p = path or self.config.positions_path
        if not p.exists():
            return []
        raw = json.loads(p.read_text(encoding="utf-8"))
        positions: list[PositionSnapshot] = []
        if isinstance(raw, dict):
            # { "002460": {...}, ... }
            for sym, data in raw.items():
                if not isinstance(data, dict):
                    continue
                positions.append(PositionSnapshot.from_dict(sym, data))
        elif isinstance(raw, list):
            for data in raw:
                if not isinstance(data, dict):
                    continue
                sym = str(data.get("symbol") or "")
                if sym:
                    positions.append(PositionSnapshot.from_dict(sym, data))
        return positions

    def run(self, now: Optional[datetime] = None) -> SentinelResult:
        now = now or datetime.now(BEIJING)
        result = SentinelResult()

        if not self.config.force_trading_hours and not is_trading_time(now):
            result.silent = True
            return result

        positions = self.load_positions()
        if not positions:
            result.silent = True
            return result

        symbols = [p.symbol for p in positions]
        names = {p.symbol: p.name for p in positions}
        quotes, q_errors = fetch_quotes(
            symbols, names=names, prefer_huatai=self.config.prefer_huatai
        )
        result.errors.extend(q_errors)
        result.scanned = len(positions)

        day = now.strftime("%Y-%m-%d")
        ts = now.strftime("%H:%M:%S")
        ts_epoch = now.timestamp()

        for pos in positions:
            q = quotes.get(pos.symbol)
            if q is None or q.price <= 0:
                continue
            alerts = self._eval_position(pos, q, day, ts_epoch)
            result.alerts.extend(alerts)

        self.store.prune_cooling(ts_epoch)
        self.store.save()
        return result.finalize(ts=ts)

    def _eval_position(
        self,
        pos: PositionSnapshot,
        q: QuoteSnapshot,
        day: str,
        now_ts: float,
    ) -> list[SentinelAlert]:
        cfg = self.config
        name = pos.name or q.name or pos.symbol
        price = q.price
        st = self.store.get_symbol(pos.symbol)

        # 换日重置振幅标记
        if st.get("day") != day:
            st["day"] = day
            st["amplitude_alerted"] = []

        last_price = st.get("last_price")
        history: list = list(st.get("history") or [])
        history.append(price)
        if len(history) > cfg.history_window:
            history = history[-cfg.history_window :]
        st["history"] = history
        st["last_price"] = price
        self.store.set_symbol(pos.symbol, st)

        candidates: list[SentinelAlert] = []

        # --- P0: 止损触及 ---
        if pos.stop_price and pos.stop_price > 0 and pos.direction == "LONG":
            if price <= pos.stop_price * (1 - cfg.stop_hit_buffer_pct / 100.0):
                candidates.append(
                    SentinelAlert(
                        level=AlertLevel.P0,
                        rule_id="stop_hit",
                        symbol=pos.symbol,
                        name=name,
                        title="止损触及",
                        body=(
                            f"现价 {price:.2f} ≤ 止损 {pos.stop_price:.2f}\n"
                            f"成本 {pos.entry_price:.2f} | 浮盈 "
                            f"{_pnl_pct(price, pos.entry_price):+.1f}%\n"
                            f"动作：按纪律减/平，勿补仓硬扛"
                        ),
                        price=price,
                        cooling_key=f"{pos.symbol}:stop_hit:{day}",
                        cooling_minutes=cfg.cool_p0,
                    )
                )
            else:
                # 逼近止损
                dist = (price - pos.stop_price) / price * 100.0
                if 0 < dist <= cfg.stop_near_pct:
                    candidates.append(
                        SentinelAlert(
                            level=AlertLevel.P0,
                            rule_id="stop_near",
                            symbol=pos.symbol,
                            name=name,
                            title="止损逼近",
                            body=(
                                f"现价 {price:.2f} | 止损 {pos.stop_price:.2f} | "
                                f"仅差 {dist:.2f}%\n"
                                f"成本 {pos.entry_price:.2f} | 浮盈 "
                                f"{_pnl_pct(price, pos.entry_price):+.1f}%\n"
                                f"动作：准备执行，勿幻想反弹"
                            ),
                            price=price,
                            cooling_key=f"{pos.symbol}:stop_near:{day}",
                            cooling_minutes=cfg.cool_p0,
                        )
                    )

        # --- P1: 跌破成本 ---
        if pos.entry_price > 0 and pos.direction == "LONG":
            break_line = pos.entry_price * (1 - cfg.cost_break_pct / 100.0)
            if price < break_line:
                candidates.append(
                    SentinelAlert(
                        level=AlertLevel.P1,
                        rule_id="cost_break",
                        symbol=pos.symbol,
                        name=name,
                        title="跌破成本",
                        body=(
                            f"现价 {price:.2f} < 成本 {pos.entry_price:.2f} "
                            f"({_pnl_pct(price, pos.entry_price):+.1f}%)\n"
                            f"动作：不补仓；若同步逼近止损优先风控"
                        ),
                        price=price,
                        cooling_key=f"{pos.symbol}:cost_break:{day}",
                        cooling_minutes=cfg.cool_p1,
                    )
                )

        # --- P1: 日内大跌/大涨 ---
        chg = q.change_pct
        if chg == 0 and q.prev_close and q.prev_close > 0:
            chg = (price - q.prev_close) / q.prev_close * 100.0
        if chg <= -cfg.day_drop_pct:
            candidates.append(
                SentinelAlert(
                    level=AlertLevel.P1,
                    rule_id="day_drop",
                    symbol=pos.symbol,
                    name=name,
                    title="日内急跌",
                    body=(
                        f"今日 {chg:+.2f}% | 现价 {price:.2f}\n"
                        f"成本 {pos.entry_price:.2f} | 止损 "
                        f"{pos.stop_price or '—'}\n"
                        f"动作：检查是否触发止损/减仓纪律，勿恐慌乱补"
                    ),
                    price=price,
                    cooling_key=f"{pos.symbol}:day_drop:{day}",
                    cooling_minutes=cfg.cool_p1,
                )
            )
        elif chg >= cfg.day_rise_pct:
            candidates.append(
                SentinelAlert(
                    level=AlertLevel.P1,
                    rule_id="day_rise",
                    symbol=pos.symbol,
                    name=name,
                    title="日内急涨",
                    body=(
                        f"今日 {chg:+.2f}% | 现价 {price:.2f}\n"
                        f"成本 {pos.entry_price:.2f} | 浮盈 "
                        f"{_pnl_pct(price, pos.entry_price):+.1f}%\n"
                        f"动作：可评估分批止盈/上移止损，勿追高加仓"
                    ),
                    price=price,
                    cooling_key=f"{pos.symbol}:day_rise:{day}",
                    cooling_minutes=cfg.cool_p1,
                )
            )

        # --- P2: 采样跳变 ---
        if last_price and last_price > 0:
            jump = (price - float(last_price)) / float(last_price) * 100.0
            if abs(jump) >= cfg.jump_pct:
                direction = "快速拉升" if jump > 0 else "快速下挫"
                candidates.append(
                    SentinelAlert(
                        level=AlertLevel.P2,
                        rule_id="jump",
                        symbol=pos.symbol,
                        name=name,
                        title="分钟跳变",
                        body=(
                            f"{direction} {jump:+.2f}% "
                            f"({float(last_price):.2f} → {price:.2f})"
                        ),
                        price=price,
                        cooling_key=f"{pos.symbol}:jump",
                        cooling_minutes=cfg.cool_p2,
                    )
                )

            # 近 3 次同向加速
            if len(history) >= 3:
                recent = history[-3:]
                diffs = [recent[i] - recent[i - 1] for i in range(1, len(recent))]
                ref = recent[0] or price
                step = cfg.accel_step_pct * ref / 100.0
                all_up = all(d >= step for d in diffs)
                all_down = all(d <= -step for d in diffs)
                if all_up or all_down:
                    total = (recent[-1] - recent[0]) / recent[0] * 100.0
                    if abs(total) >= cfg.accel_total_pct:
                        direction = "连续拉升" if total > 0 else "连续下挫"
                        candidates.append(
                            SentinelAlert(
                                level=AlertLevel.P2,
                                rule_id="accel",
                                symbol=pos.symbol,
                                name=name,
                                title="连续同向",
                                body=f"{direction} 近采样累计 {total:+.2f}%",
                                price=price,
                                cooling_key=f"{pos.symbol}:accel",
                                cooling_minutes=cfg.cool_p2,
                            )
                        )

        # --- P2: 日内振幅阈值 ---
        if q.high and q.low and q.high > q.low:
            ref = q.open or q.prev_close or price
            if ref and ref > 0:
                amp = (q.high - q.low) / ref * 100.0
                alerted = list(st.get("amplitude_alerted") or [])
                for th in cfg.amplitude_thresholds:
                    if amp >= th and th not in alerted:
                        candidates.append(
                            SentinelAlert(
                                level=AlertLevel.P2,
                                rule_id=f"amplitude_{th}",
                                symbol=pos.symbol,
                                name=name,
                                title="日内振幅",
                                body=(
                                    f"振幅 {amp:.2f}% ≥ {th}% | "
                                    f"高 {q.high:.2f} / 低 {q.low:.2f}"
                                ),
                                price=price,
                                cooling_key=f"{pos.symbol}:amp:{day}:{th}",
                                cooling_minutes=cfg.cool_p2,
                            )
                        )
                        alerted.append(th)
                st["amplitude_alerted"] = alerted
                self.store.set_symbol(pos.symbol, st)

        # 冷却过滤
        out: list[SentinelAlert] = []
        for a in candidates:
            if self.store.is_cooling(a.cooling_key, now_ts):
                continue
            self.store.set_cooling(a.cooling_key, a.cooling_minutes, now_ts)
            out.append(a)
        return out


def is_trading_time(now: Optional[datetime] = None) -> bool:
    """A 股连续竞价时段（含午休外）。"""
    now = now or datetime.now(BEIJING)
    if now.tzinfo is None:
        now = now.replace(tzinfo=BEIJING)
    else:
        now = now.astimezone(BEIJING)
    if now.weekday() >= 5:
        return False
    t = now.hour * 100 + now.minute
    return (930 <= t <= 1130) or (1300 <= t <= 1500)


def _pnl_pct(price: float, entry: float) -> float:
    if entry <= 0:
        return 0.0
    return (price - entry) / entry * 100.0
