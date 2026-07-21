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
    PortfolioLimits,
    PositionSnapshot,
    QuoteSnapshot,
    SentinelAlert,
    SentinelResult,
)
from .portfolio import load_portfolio_limits, merge_limits
from .quotes import fetch_quotes
from .state import SentinelStateStore

BEIJING = timezone(timedelta(hours=8))


@dataclass
class SentinelConfig:
    """可调阈值。"""

    positions_path: Path = Path("data/positions.json")
    state_path: Path = Path("data/sentinel_state.json")
    portfolio_path: Path = Path("data/portfolio.yaml")
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
    # ── 轻量风控（非完整 L4）──
    enable_risk: bool = True
    float_loss_pct: Optional[float] = None  # 单票浮亏%告警；None=用 portfolio/持仓
    peak_drawdown_pct: float = 8.0  # 从持仓最高价回撤 %
    portfolio_loss_pct: float = 5.0  # 组合相对成本浮亏 %
    # ── 轻量仓位管理（非完整 L3）──
    enable_position_mgmt: bool = True
    total_capital: Optional[float] = None  # None=读 portfolio.yaml
    max_single_pct: Optional[float] = None
    max_total_exposure: Optional[float] = None
    min_cash_pct: Optional[float] = None
    # 冷却（分钟）
    cool_p0: int = 5
    cool_p1: int = 20
    cool_p2: int = 45
    history_window: int = 5
    force_trading_hours: bool = False  # True=忽略交易时段（测试用）
    prefer_huatai: bool = False
    # MACD+KDJ 五法（读本地 kline_cache，不拉网，保 sentinel 秒级）
    enable_macd_kdj: bool = True
    kline_cache_dir: Path = Path("data/kline_cache")

    @classmethod
    def from_dict(cls, d: dict) -> "SentinelConfig":
        cfg = cls()
        path_keys = ("positions_path", "state_path", "portfolio_path", "kline_cache_dir")
        for k, v in d.items():
            if k in path_keys and v is not None:
                setattr(cfg, k, Path(v))
            elif hasattr(cfg, k) and v is not None:
                setattr(cfg, k, v)
        return cfg

    def resolve_limits(self) -> PortfolioLimits:
        base = load_portfolio_limits(self.portfolio_path)
        overrides: dict = {}
        if self.total_capital is not None:
            overrides["total_capital"] = self.total_capital
        if self.max_single_pct is not None:
            overrides["max_single_pct"] = self.max_single_pct
        if self.max_total_exposure is not None:
            overrides["max_total_exposure"] = self.max_total_exposure
        if self.min_cash_pct is not None:
            overrides["min_cash_pct"] = self.min_cash_pct
        if self.float_loss_pct is not None:
            overrides["single_stop_loss_pct"] = abs(self.float_loss_pct) / 100.0
        if self.peak_drawdown_pct is not None:
            overrides["peak_drawdown_pct"] = abs(self.peak_drawdown_pct) / 100.0
        if self.portfolio_loss_pct is not None:
            overrides["portfolio_drawdown_pct"] = abs(self.portfolio_loss_pct) / 100.0
        return merge_limits(base, overrides)


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

        limits = self.config.resolve_limits()
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

        # 组合聚合：市值、成本、浮盈
        book: list[tuple[PositionSnapshot, QuoteSnapshot, float]] = []
        for pos in positions:
            q = quotes.get(pos.symbol)
            if q is None or q.price <= 0:
                continue
            mv = pos.market_value(q.price)
            book.append((pos, q, mv))
            alerts = self._eval_position(pos, q, day, ts_epoch, limits)
            result.alerts.extend(alerts)

        if book and (self.config.enable_risk or self.config.enable_position_mgmt):
            result.alerts.extend(
                self._eval_portfolio(book, day, ts_epoch, limits)
            )

        self.store.prune_cooling(ts_epoch)
        self.store.save()
        return result.finalize(ts=ts)

    def _eval_position(
        self,
        pos: PositionSnapshot,
        q: QuoteSnapshot,
        day: str,
        now_ts: float,
        limits: Optional[PortfolioLimits] = None,
    ) -> list[SentinelAlert]:
        cfg = self.config
        limits = limits or cfg.resolve_limits()
        name = pos.name or q.name or pos.symbol
        price = q.price
        # 日内涨跌幅（提前计算，后续告警 body 统一引用）
        chg = q.change_pct
        if chg == 0 and q.prev_close and q.prev_close > 0:
            chg = (price - q.prev_close) / q.prev_close * 100.0
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
        # 跟踪盘中最高价（用于回撤）
        peak = st.get("peak_price")
        try:
            peak_f = float(peak) if peak is not None else 0.0
        except (TypeError, ValueError):
            peak_f = 0.0
        if pos.high_price:
            peak_f = max(peak_f, float(pos.high_price))
        peak_f = max(peak_f, price, float(pos.entry_price or 0))
        st["peak_price"] = peak_f
        self.store.set_symbol(pos.symbol, st)

        candidates: list[SentinelAlert] = []

        # --- P0: 止损触及 ---
        if pos.stop_price and pos.stop_price > 0 and pos.direction == "LONG":
            if price <= pos.stop_price * (1 - cfg.stop_hit_buffer_pct / 100.0):
                day_tag = f"今日 {chg:+.1f}% | " if chg != 0 else ""
                candidates.append(
                    SentinelAlert(
                        level=AlertLevel.P0,
                        rule_id="stop_hit",
                        symbol=pos.symbol,
                        name=name,
                        title="止损触及",
                        body=(
                            f"{day_tag}现价 {price:.2f} ≤ 止损 {pos.stop_price:.2f}\n"
                            f"成本 {pos.entry_price:.2f} | 成本浮盈 "
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
                    day_tag = f"今日 {chg:+.1f}% | " if chg != 0 else ""
                    candidates.append(
                        SentinelAlert(
                            level=AlertLevel.P0,
                            rule_id="stop_near",
                            symbol=pos.symbol,
                            name=name,
                            title="止损逼近",
                            body=(
                                f"{day_tag}现价 {price:.2f} | 止损 {pos.stop_price:.2f} | "
                                f"仅差 {dist:.2f}%\n"
                                f"成本 {pos.entry_price:.2f} | 成本浮盈 "
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
                day_tag = f"今日 {chg:+.1f}% | " if chg != 0 else ""
                candidates.append(
                    SentinelAlert(
                        level=AlertLevel.P1,
                        rule_id="cost_break",
                        symbol=pos.symbol,
                        name=name,
                        title="跌破成本",
                        body=(
                            f"{day_tag}现价 {price:.2f} < 成本 {pos.entry_price:.2f} "
                            f"({_pnl_pct(price, pos.entry_price):+.1f}%)\n"
                            f"动作：不补仓；若同步逼近止损优先风控"
                        ),
                        price=price,
                        cooling_key=f"{pos.symbol}:cost_break:{day}",
                        cooling_minutes=cfg.cool_p1,
                    )
                )

        # --- P1: 日内大跌/大涨 ---
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

        # ── 轻量风控：单票浮亏 / 从高点回撤 ──
        if cfg.enable_risk and pos.direction == "LONG" and pos.entry_price > 0:
            pnl = _pnl_pct(price, pos.entry_price)
            # 浮亏阈值：持仓 initial_stop > config/portfolio
            loss_thr = abs(limits.single_stop_loss_pct) * 100.0
            if pos.initial_stop_pct is not None and pos.initial_stop_pct < 0:
                loss_thr = max(loss_thr, abs(pos.initial_stop_pct) * 100.0)
            if cfg.float_loss_pct is not None:
                loss_thr = abs(cfg.float_loss_pct)
            if pnl <= -loss_thr:
                day_tag = f"今日 {chg:+.1f}% | " if chg != 0 else ""
                candidates.append(
                    SentinelAlert(
                        level=AlertLevel.P0,
                        rule_id="float_loss",
                        symbol=pos.symbol,
                        name=name,
                        title="单票浮亏超限",
                        body=(
                            f"{day_tag}成本浮盈 {pnl:+.1f}% ≤ -{loss_thr:.1f}% 阈值\n"
                            f"成本 {pos.entry_price:.2f} → 现价 {price:.2f}\n"
                            f"动作：风控优先，评估减仓/止损，禁止补仓摊薄"
                        ),
                        price=price,
                        cooling_key=f"{pos.symbol}:float_loss:{day}",
                        cooling_minutes=cfg.cool_p0,
                    )
                )

            # 从持仓最高价回撤
            if peak_f > 0 and price < peak_f:
                dd = (peak_f - price) / peak_f * 100.0
                dd_thr = abs(limits.peak_drawdown_pct) * 100.0
                if cfg.peak_drawdown_pct is not None:
                    dd_thr = abs(cfg.peak_drawdown_pct)
                if dd >= dd_thr:
                    day_tag = f"今日 {chg:+.1f}% | " if chg != 0 else ""
                    candidates.append(
                        SentinelAlert(
                            level=AlertLevel.P1,
                            rule_id="peak_drawdown",
                            symbol=pos.symbol,
                            name=name,
                            title="浮盈回吐",
                            body=(
                                f"{day_tag}从高点 {peak_f:.2f} 回撤 {dd:.1f}% "
                                f"(≥{dd_thr:.1f}%)\n"
                                f"现价 {price:.2f} | 成本 {pos.entry_price:.2f} | "
                                f"成本浮盈 {pnl:+.1f}%\n"
                                f"动作：考虑上移止损/分批止盈，勿因回撤情绪化加仓"
                            ),
                            price=price,
                            cooling_key=f"{pos.symbol}:peak_dd:{day}",
                            cooling_minutes=cfg.cool_p1,
                        )
                    )

        # ── 轻量仓位：单票市值占比 ──
        if cfg.enable_position_mgmt and limits.total_capital > 0 and pos.quantity > 0:
            mv = pos.market_value(price)
            weight = mv / limits.total_capital
            cap = limits.max_single_pct
            if weight > cap + 1e-9:
                candidates.append(
                    SentinelAlert(
                        level=AlertLevel.P1,
                        rule_id="single_overweight",
                        symbol=pos.symbol,
                        name=name,
                        title="单票仓位超限",
                        body=(
                            f"市值 {mv:,.0f} / 总资金 {limits.total_capital:,.0f} "
                            f"= {weight*100:.1f}% > 上限 {cap*100:.0f}%\n"
                            f"数量 {pos.quantity:.0f} × 现价 {price:.2f}\n"
                            f"动作：禁止加仓；可计划减至 ≤{cap*100:.0f}%"
                        ),
                        price=price,
                        cooling_key=f"{pos.symbol}:single_ow:{day}",
                        cooling_minutes=cfg.cool_p1,
                    )
                )

        # ── MACD+KDJ 五法（缓存日线，interpretation）──
        if cfg.enable_macd_kdj:
            candidates.extend(
                self._eval_macd_kdj(pos, q, name, price, day)
            )

        return self._apply_cooling(candidates, now_ts)

    def _eval_macd_kdj(
        self,
        pos: PositionSnapshot,
        q: QuoteSnapshot,
        name: str,
        price: float,
        day: str,
    ) -> list[SentinelAlert]:
        """持仓五法日检。只读 kline_cache，失败静默。"""
        cfg = self.config
        try:
            from src.alphas.macd_kdj import evaluate_ohlc_latest, load_kline_cache

            df = load_kline_cache(pos.symbol, cfg.kline_cache_dir)
            # 也试 Hermes 部署路径
            if df is None or len(df) < 40:
                alt = Path.home() / "ai-stock-hunter" / "data" / "kline_cache"
                if alt.exists():
                    df = load_kline_cache(pos.symbol, alt)
            if df is None or len(df) < 40:
                return []
            mk = evaluate_ohlc_latest(df)
            if not mk or mk.get("action") in (None, "NONE"):
                return []

            act = str(mk.get("action"))
            conf = float(mk.get("confidence") or 0)
            notes = "；".join(mk.get("notes") or [])[:120]
            methods = ",".join(mk.get("methods") or []) or "-"
            detail = (
                f"DIF {mk.get('dif')} / DEA {mk.get('dea')} | "
                f"K {mk.get('k')} D {mk.get('d')} | conf≤{conf:.2f}\n"
                f"方法 {methods}\n"
                f"{notes}\n"
                f"性质: interpretation · 非下单指令"
            )

            out: list[SentinelAlert] = []
            if act == "EXIT" and pos.direction == "LONG":
                out.append(
                    SentinelAlert(
                        level=AlertLevel.P1,
                        rule_id="macd_kdj_exit",
                        symbol=pos.symbol,
                        name=name,
                        title="五法离场候选",
                        body=(
                            f"MACD+KDJ 共振死叉/弱势死叉\n"
                            f"现价 {price:.2f} | 成本 {pos.entry_price:.2f} | "
                            f"止损 {pos.stop_price or '—'}\n"
                            f"{detail}\n"
                            f"动作：对照止损与卖点纪律，勿盲目补仓"
                        ),
                        price=price,
                        cooling_key=f"{pos.symbol}:mk_exit:{day}",
                        cooling_minutes=cfg.cool_p1,
                    )
                )
            elif act == "AVOID_ENTRY":
                out.append(
                    SentinelAlert(
                        level=AlertLevel.P2,
                        rule_id="macd_kdj_avoid",
                        symbol=pos.symbol,
                        name=name,
                        title="五法勿追假反弹",
                        body=(
                            f"0轴下未拐头 + KDJ金叉 → 假反弹风险\n"
                            f"现价 {price:.2f}\n{detail}\n"
                            f"动作：持仓勿加仓摊薄；空仓勿抄底"
                        ),
                        price=price,
                        cooling_key=f"{pos.symbol}:mk_avoid:{day}",
                        cooling_minutes=cfg.cool_p2,
                    )
                )
            elif act == "ENTER" and pos.direction == "LONG":
                # 持仓语境：仅提示「共振」勿当加仓令
                out.append(
                    SentinelAlert(
                        level=AlertLevel.P2,
                        rule_id="macd_kdj_enter",
                        symbol=pos.symbol,
                        name=name,
                        title="五法共振提示",
                        body=(
                            f"MACD+KDJ 进场形态（教学规则）\n"
                            f"现价 {price:.2f} | 成本 {pos.entry_price:.2f}\n"
                            f"{detail}\n"
                            f"动作：已持仓则评估是否补仓纪律；禁止仅凭此加仓"
                        ),
                        price=price,
                        cooling_key=f"{pos.symbol}:mk_enter:{day}",
                        cooling_minutes=cfg.cool_p2,
                    )
                )
            elif act == "HOLD" and pos.direction == "LONG":
                out.append(
                    SentinelAlert(
                        level=AlertLevel.P2,
                        rule_id="macd_kdj_hold",
                        symbol=pos.symbol,
                        name=name,
                        title="五法洗盘持股",
                        body=(
                            f"双死叉后小幅回调再双金叉 → 洗盘持股候选\n"
                            f"现价 {price:.2f}\n{detail}\n"
                            f"动作：勿因短线死叉恐慌割肉；仍守止损"
                        ),
                        price=price,
                        cooling_key=f"{pos.symbol}:mk_hold:{day}",
                        cooling_minutes=cfg.cool_p2,
                    )
                )
            return out
        except Exception:
            return []

    def _eval_portfolio(
        self,
        book: list[tuple[PositionSnapshot, QuoteSnapshot, float]],
        day: str,
        now_ts: float,
        limits: PortfolioLimits,
    ) -> list[SentinelAlert]:
        """组合层：总敞口、现金、组合浮亏。"""
        cfg = self.config
        capital = limits.total_capital
        if capital <= 0 or not book:
            return []

        total_mv = sum(mv for _, _, mv in book)
        total_cost = sum(pos.cost_value() for pos, _, _ in book)
        exposure = total_mv / capital
        cash_pct = max(0.0, 1.0 - exposure)
        port_pnl_pct = 0.0
        if total_cost > 0:
            port_pnl_pct = (total_mv - total_cost) / total_cost * 100.0

        candidates: list[SentinelAlert] = []

        if cfg.enable_position_mgmt:
            if exposure > limits.max_total_exposure + 1e-9:
                candidates.append(
                    SentinelAlert(
                        level=AlertLevel.P1,
                        rule_id="total_exposure",
                        symbol="PORTFOLIO",
                        name="组合",
                        title="总仓位超限",
                        body=(
                            f"持仓市值 {total_mv:,.0f} / 资金 {capital:,.0f} "
                            f"= {exposure*100:.1f}% > 上限 "
                            f"{limits.max_total_exposure*100:.0f}%\n"
                            f"持仓 {len(book)} 只 | 现金约 {cash_pct*100:.1f}%\n"
                            f"动作：禁止新开仓；优先减超限单票"
                        ),
                        price=0.0,
                        cooling_key=f"PORT:exposure:{day}",
                        cooling_minutes=cfg.cool_p1,
                    )
                )
            if cash_pct + 1e-9 < limits.min_cash_pct:
                candidates.append(
                    SentinelAlert(
                        level=AlertLevel.P1,
                        rule_id="cash_low",
                        symbol="PORTFOLIO",
                        name="组合",
                        title="现金不足",
                        body=(
                            f"估算现金比例 {cash_pct*100:.1f}% < "
                            f"底线 {limits.min_cash_pct*100:.0f}%\n"
                            f"总敞口 {exposure*100:.1f}% | 市值 {total_mv:,.0f}\n"
                            f"动作：停止加仓，保留子弹子弹弹药"
                        ),
                        price=0.0,
                        cooling_key=f"PORT:cash:{day}",
                        cooling_minutes=cfg.cool_p1,
                    )
                )

        if cfg.enable_risk and total_cost > 0:
            thr = abs(limits.portfolio_drawdown_pct) * 100.0
            if cfg.portfolio_loss_pct is not None:
                thr = abs(cfg.portfolio_loss_pct)
            if port_pnl_pct <= -thr:
                candidates.append(
                    SentinelAlert(
                        level=AlertLevel.P0,
                        rule_id="portfolio_loss",
                        symbol="PORTFOLIO",
                        name="组合",
                        title="组合浮亏超限",
                        body=(
                            f"组合浮盈 {port_pnl_pct:+.1f}% ≤ -{thr:.1f}%\n"
                            f"成本合计 {total_cost:,.0f} → 市值 {total_mv:,.0f}\n"
                            f"动作：暂停新开；逐票检查止损，勿情绪化补仓"
                        ),
                        price=0.0,
                        cooling_key=f"PORT:loss:{day}",
                        cooling_minutes=cfg.cool_p0,
                    )
                )

        return self._apply_cooling(candidates, now_ts)

    def _apply_cooling(
        self, candidates: list[SentinelAlert], now_ts: float
    ) -> list[SentinelAlert]:
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
