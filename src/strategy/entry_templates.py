# -*- coding: utf-8 -*-
"""入场规则模板 — 4 通用 + 3 A 股特有。

每个模板是独立的可调用函数，签名统一:
    template(watchlist, portfolio, market_data, **params) → list[StrategySignal]

用法::

    engine = StrategyEngine()
    engine.register_entry_rule(trend_following(params={"lookback": 20}))
    engine.register_entry_rule(capital_inflow(params={"consecutive_days": 3}))

A 股数据依赖说明:
    - 通用模板(1-4): 仅需 OHLCV，mootdx/腾讯可获取
    - 北向模板(5): 需北向资金数据，东财/同花顺可获取
    - 板块模板(6): 需板块分类+成分股列表，申万分类可获取
    - 龙虎榜模板(7): 需龙虎榜明细，东财龙虎榜接口可获取
"""

from __future__ import annotations

import logging
from typing import Callable

from .types import PortfolioSnapshot, StrategySignal

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# 模板工厂
# ──────────────────────────────────────────────


def _make_template(
    name: str,
    check_fn: Callable,
    default_params: dict | None = None,
) -> Callable:
    """Wrap a check function into a standard entry-rule callable."""
    params = default_params or {}

    def rule(
        watchlist: list[str],
        portfolio: PortfolioSnapshot,
        market_data: dict,
        **overrides,
    ) -> list[StrategySignal]:
        cfg = {**params, **overrides}
        signals: list[StrategySignal] = []
        for symbol in watchlist:
            if symbol in portfolio.positions:
                continue  # 已有持仓，不重复入场
            mkt = market_data.get(symbol, {})
            if not mkt:
                continue
            try:
                result = check_fn(symbol, mkt, cfg)
                if result:
                    signals.append(result)
            except Exception:
                logger.debug("%s: %s check skipped (data missing)", name, symbol)
        return signals

    rule.__name__ = name
    return rule


# ──────────────────────────────────────────────
# 1. 趋势跟随 (Trend Following)
#    价格突破 N 日最高价 → ENTER
# ──────────────────────────────────────────────


def _trend_check(symbol: str, mkt: dict, cfg: dict) -> StrategySignal | None:
    lookback = cfg.get("lookback", 20)
    current = mkt.get("current_price", 0)
    n_day_high = mkt.get(f"high_{lookback}d", 0)
    # 如果数据源没提供 N 日最高价，用 close_vs_ma 替代
    if n_day_high <= 0:
        ma = mkt.get(f"ma_{lookback}d", 0)
        if ma > 0 and current > ma * (1 + cfg.get("breakout_pct", 0.02)):
            return StrategySignal(
                symbol=symbol, action="ENTER", direction="LONG",
                strength=0.6, reason=f"趋势跟随: 价格突破{lookback}日均线{cfg.get('breakout_pct', 0.02):.0%}",
            )
        return None
    if current >= n_day_high:
        return StrategySignal(
            symbol=symbol, action="ENTER", direction="LONG",
            strength=0.6, reason=f"趋势跟随: 突破{lookback}日高点 {n_day_high:.2f}",
        )
    return None


trend_following = _make_template("trend_following", _trend_check, {"lookback": 20, "breakout_pct": 0.02})


# ──────────────────────────────────────────────
# 2. 均值回归 (Mean Reversion)
#    价格跌破布林下轨 + 动量超卖 → ENTER
# ──────────────────────────────────────────────


def _mean_reversion_check(symbol: str, mkt: dict, cfg: dict) -> StrategySignal | None:
    current = mkt.get("current_price", 0)
    bb_lower = mkt.get("bb_lower", 0)
    rsi = mkt.get("rsi_14", 50)
    bb_threshold = cfg.get("bb_threshold", 1.0)  # 价格≤下轨*threshold 触发
    rsi_max = cfg.get("rsi_max", 30)

    if bb_lower > 0 and current <= bb_lower * bb_threshold and rsi <= rsi_max:
        return StrategySignal(
            symbol=symbol, action="ENTER", direction="LONG",
            strength=0.55,
            reason=f"均值回归: 跌破布林下轨({bb_lower:.2f}), RSI={rsi:.0f}",
        )
    # fallback: 仅 RSI 超卖
    if rsi <= cfg.get("rsi_fallback", 20):
        return StrategySignal(
            symbol=symbol, action="ENTER", direction="LONG",
            strength=0.40, reason=f"均值回归(弱): RSI超卖={rsi:.0f}",
        )
    return None


mean_reversion = _make_template("mean_reversion", _mean_reversion_check, {"bb_threshold": 1.0, "rsi_max": 30, "rsi_fallback": 20})


# ──────────────────────────────────────────────
# 3. 动量突破 (Momentum Breakout)
#    成交量放大 + 价格突破关键阻力 → ENTER
# ──────────────────────────────────────────────


def _momentum_check(symbol: str, mkt: dict, cfg: dict) -> StrategySignal | None:
    current = mkt.get("current_price", 0)
    avg_vol = mkt.get("avg_volume_20d", 0)
    today_vol = mkt.get("volume", 0)
    resistance = mkt.get("resistance", 0)  # 最近阻力位 (20日高点或布林上轨)
    vol_mult = cfg.get("vol_multiplier", 1.5)
    price_chg = mkt.get("change_pct", 0)

    vol_surge = avg_vol > 0 and today_vol > avg_vol * vol_mult
    if resistance <= 0:
        resistance = mkt.get("bb_upper", 0) or mkt.get(f"high_20d", 0)
    price_break = resistance > 0 and current >= resistance

    if vol_surge and price_break and price_chg > 0:
        return StrategySignal(
            symbol=symbol, action="ENTER", direction="LONG",
            strength=0.65,
            reason=f"动量突破: 放量{vol_mult:.1f}x突破{resistance:.2f}, +{price_chg:.1%}",
        )
    # 较弱信号: 仅放量
    if vol_surge and price_chg > cfg.get("min_chg", 0.02):
        return StrategySignal(
            symbol=symbol, action="ENTER", direction="LONG",
            strength=0.45, reason=f"动量(弱): 放量{vol_mult:.1f}x, +{price_chg:.1%}",
        )
    return None


momentum_breakout = _make_template("momentum_breakout", _momentum_check, {"vol_multiplier": 1.5, "min_chg": 0.02})


# ──────────────────────────────────────────────
# 4. 波动率扩张 (Volatility Expansion)
#    ATR 突然放大至 N 日均值 2 倍 → 波动来了
# ──────────────────────────────────────────────


def _vol_expansion_check(symbol: str, mkt: dict, cfg: dict) -> StrategySignal | None:
    atr = mkt.get("atr", 0)
    atr_avg = mkt.get("atr_avg_20d", 0)
    price_chg = mkt.get("change_pct", 0)
    expansion_mult = cfg.get("expansion_mult", 2.0)

    if atr_avg > 0 and atr > atr_avg * expansion_mult:
        direction = "LONG" if price_chg > 0 else "SHORT"
        return StrategySignal(
            symbol=symbol, action="ENTER", direction=direction,
            strength=0.50,
            reason=f"波动率扩张: ATR({atr:.2f})={atr/atr_avg:.1f}x均({atr_avg:.2f}), +{price_chg:.1%}",
        )
    return None


volatility_expansion = _make_template("volatility_expansion", _vol_expansion_check, {"expansion_mult": 2.0})


# ══════════════════════════════════════════════
# A 股特有模板
# ══════════════════════════════════════════════


# ──────────────────────────────────────────────
# 5. 资金流入 — 北向+主力资金连续净流入 (A-share)
# ──────────────────────────────────────────────


def _capital_inflow_check(symbol: str, mkt: dict, cfg: dict) -> StrategySignal | None:
    """北向资金或主力资金连续净流入信号。

    数据字段 (由东财/同花顺资金流接口提供):
        - northbound_inflow_Nd: 北向连续N日净流入(1=是,0=否)
        - main_capital_inflow_Nd: 主力资金连续N日净流入
        - northbound_holding_pct: 北向持股占比
    """
    consecutive = cfg.get("consecutive_days", 3)
    nb_key = f"northbound_inflow_{consecutive}d"
    mc_key = f"main_capital_inflow_{consecutive}d"

    nb_flow = mkt.get(nb_key, 0)
    mc_flow = mkt.get(mc_key, 0)
    holding_pct = mkt.get("northbound_holding_pct", 0)

    # 北向连续流入 + 持股占比 > 阈值
    if nb_flow and holding_pct >= cfg.get("min_holding_pct", 0.01):
        return StrategySignal(
            symbol=symbol, action="ENTER", direction="LONG",
            strength=0.70,
            reason=f"北向资金: 连续{consecutive}日净流入, 持股{holding_pct:.1%}",
        )
    # 主力资金连续流入
    if mc_flow:
        return StrategySignal(
            symbol=symbol, action="ENTER", direction="LONG",
            strength=0.60,
            reason=f"主力资金: 连续{consecutive}日净流入",
        )
    return None


capital_inflow = _make_template("capital_inflow", _capital_inflow_check, {"consecutive_days": 3, "min_holding_pct": 0.01})


# ──────────────────────────────────────────────
# 6. 板块共振 — 同板块 ≥3 支票同时放量异动 (A-share)
# ──────────────────────────────────────────────


def _sector_resonance_check(symbol: str, mkt: dict, cfg: dict) -> StrategySignal | None:
    """板块联动信号。

    数据字段 (由板块排名/申万分类提供):
        - sector_code: 申万行业代码
        - sector_rising_count: 同板块涨幅>threshold的股票数
        - sector_volume_surge_count: 同板块放量的股票数
    """
    min_count = cfg.get("min_stocks", 3)
    vol_surge_count = mkt.get("sector_volume_surge_count", 0)
    rising_count = mkt.get("sector_rising_count", 0)
    sector_name = mkt.get("sector_name", "")

    if vol_surge_count >= min_count:
        return StrategySignal(
            symbol=symbol, action="ENTER", direction="LONG",
            strength=0.65,
            reason=f"板块共振: {sector_name} {vol_surge_count}只放量异动",
        )
    if rising_count >= min_count:
        return StrategySignal(
            symbol=symbol, action="ENTER", direction="LONG",
            strength=0.55,
            reason=f"板块联动: {sector_name} {rising_count}只齐涨",
        )
    return None


sector_resonance = _make_template("sector_resonance", _sector_resonance_check, {"min_stocks": 3})


# ──────────────────────────────────────────────
# 7. 龙虎榜信号 — 知名游资席位净买入 (A-share)
# ──────────────────────────────────────────────


def _dragon_tiger_check(symbol: str, mkt: dict, cfg: dict) -> StrategySignal | None:
    """龙虎榜信号。

    数据字段 (由东财龙虎榜接口提供):
        - lhb_net_buy: 龙虎榜净买入额(万元)
        - lhb_top_seats: 上榜知名游资席位列表
        - lhb_seal_strength: 封板强度(封单/流通市值, 0-1)
        - lhb_is_on_list: 是否上榜 (1=是)
    """
    if not mkt.get("lhb_is_on_list", 0):
        return None

    net_buy = mkt.get("lhb_net_buy", 0)  # 万元
    top_seats = mkt.get("lhb_top_seats", [])
    seal = mkt.get("lhb_seal_strength", 0)
    min_net_buy = cfg.get("min_net_buy_wan", 500)  # 默认500万
    min_seal = cfg.get("min_seal_strength", 0.03)

    # 知名游资席位净买入
    if top_seats and net_buy > 0:
        seat_names = ", ".join(top_seats[:3])
        return StrategySignal(
            symbol=symbol, action="ENTER", direction="LONG",
            strength=min(0.85, 0.50 + len(top_seats) * 0.10),
            reason=f"龙虎榜: {seat_names} 净买入 {net_buy:.0f}万",
        )
    # 封板强度高
    if seal >= min_seal and net_buy >= min_net_buy:
        return StrategySignal(
            symbol=symbol, action="ENTER", direction="LONG",
            strength=0.70,
            reason=f"龙虎榜: 封板强度{seal:.1%}, 净买入{net_buy:.0f}万",
        )
    # 上榜但条件不够 → 弱信号
    if net_buy >= min_net_buy:
        return StrategySignal(
            symbol=symbol, action="ENTER", direction="LONG",
            strength=0.45,
            reason=f"龙虎榜(弱): 净买入{net_buy:.0f}万",
        )
    return None


dragon_tiger = _make_template("dragon_tiger", _dragon_tiger_check, {"min_net_buy_wan": 500, "min_seal_strength": 0.03})


# ──────────────────────────────────────────────
# 全部模板注册表
# ──────────────────────────────────────────────

ALL_TEMPLATES: dict[str, Callable] = {
    "trend_following": trend_following,
    "mean_reversion": mean_reversion,
    "momentum_breakout": momentum_breakout,
    "volatility_expansion": volatility_expansion,
    "capital_inflow": capital_inflow,
    "sector_resonance": sector_resonance,
    "dragon_tiger": dragon_tiger,
}

UNIVERSAL_TEMPLATES = ["trend_following", "mean_reversion", "momentum_breakout", "volatility_expansion"]
ASHARE_TEMPLATES = ["capital_inflow", "sector_resonance", "dragon_tiger"]
