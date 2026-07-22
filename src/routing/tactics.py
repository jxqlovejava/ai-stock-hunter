# -*- coding: utf-8 -*-
"""短线战术管道 (Tactics Pipeline) — 4-Phase 架构。

聚焦买卖时机判断。按交易员思维模型组织:
  Phase 0: 数据预拉 (6路并行IO)
  Phase 1: 盘面全景 (TacticalSnapshot, 4维并行本地计算)
  Phase 2: 过筛+深思 (军规 → 辩论‖芒格‖T+0)
  Phase 3: 裁决+执行

与选股管道(diagnose/analyze)的本质区别:
  - 跳过: 准入/宏观象限/北向/盈利修正/Alpha Lens/多维诊断6维/
         反操纵深扫/质量审查/情景估值/行业公司深度
  - 保留: 军规/四大师辩论/芒格模型/综合裁决/仓位调度/风控执行
  - 新增: 技术6维全量/入场出场信号/融资融券/板块资金/市场情绪/博弈融合

预估耗时: 10-12s (瓶颈在LLM调用); --no-debate 可降至 2-3s
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.data.source_citation import make_citation

logger = logging.getLogger(__name__)

# perf 计数器 (仅 debug 模式)
_perf = __debug__


# ═══════════════════════════════════════════════════════════════════
# DTO
# ═══════════════════════════════════════════════════════════════════


@dataclass
class TacticalSnapshot:
    """盘面全景快照 — Phase 1 输出，Phase 2/3 的共享输入。"""

    symbol: str
    name: str
    current_price: float = 0.0
    change_pct: float = 0.0

    # ── 🌍 市场背景 ──
    sentiment_label: str = "normal"          # fear / greed / normal
    sentiment_score: float = 50.0            # 0=fear, 100=greed
    market_breadth: str = ""                 # "涨412/跌4785 (8.6%)"
    sentiment_advice: str = ""               # 对操作的提示
    global_market_summary: str = ""           # 全球市场一行总结

    # ── 📊 基本面 ──
    value_score: float = 50.0
    quality_score: float = 50.0
    momentum_score: float = 50.0
    pe_ttm: Optional[float] = None
    industry_pe: Optional[float] = None
    roe: Optional[float] = None
    fundamental_note: str = ""

    # ── 📈 技术面 ──
    trend_score: float = 50.0
    reversal_score: float = 50.0
    volume_score: float = 50.0
    volatility_score: float = 50.0
    ma_score: float = 50.0
    limit_up_score: float = 50.0
    technical_composite: float = 50.0
    entry_signals: list[dict] = field(default_factory=list)
    exit_signals: list[dict] = field(default_factory=list)
    best_entry: Optional[dict] = None
    suggested_stop: float = 0.0
    atr_stop: float = 0.0           # ATR 移动止损价
    target_prices: list[float] = field(default_factory=list)
    time_stop_days: int = 10
    macd_kdj: Optional[dict] = None
    technical_note: str = ""

    # ── 💰 资金面 ──
    margin_balance: Optional[float] = None         # 融资余额(亿)
    margin_trend: str = "stable"                   # increasing/decreasing/stable
    margin_5d_pct: float = 0.0                     # 5日融资变化%
    short_balance: Optional[float] = None           # 融券余额(亿)
    short_5d_pct: float = 0.0                      # 5日融券变化%
    margin_alerts: list[str] = field(default_factory=list)
    sector_inflow: bool = False                     # 标的板块今日净流入?
    sector_top_inflow: list[str] = field(default_factory=list)   # 今日资金流入 top3 板块
    sector_top_outflow: list[str] = field(default_factory=list)  # 今日资金流出 top3 板块
    dominant_player: str = ""                       # 博弈论主导玩家
    crowding_score: int = 50                        # 拥挤度
    gt_entry_allowed: bool = False                  # 博弈是否允许入场
    gt_action: str = "WAIT"                         # 博弈建议动作
    gt_rationale: list[str] = field(default_factory=list)
    capital_note: str = ""

    # ── 持仓 ──
    held: bool = False
    position_entry: Optional[float] = None
    position_loss_pct: float = 0.0

    # ── 元数据 ──
    data_gaps: list[str] = field(default_factory=list)

    def to_summary_dict(self) -> dict:
        """转为 dict 供 Phase 2/3 消费。"""
        return {
            "symbol": self.symbol, "name": self.name,
            "current_price": self.current_price, "change_pct": self.change_pct,
            "sentiment": self.sentiment_label, "sentiment_score": self.sentiment_score,
            "value_score": self.value_score, "quality_score": self.quality_score,
            "momentum_score": self.momentum_score,
            "technical_composite": self.technical_composite,
            "entry_signals": self.entry_signals, "exit_signals": self.exit_signals,
            "best_entry": self.best_entry,
            "suggested_stop": self.suggested_stop,
            "target_prices": self.target_prices,
            "macd_kdj_action": self.macd_kdj.get("action") if self.macd_kdj else None,
            "margin_trend": self.margin_trend,
            "margin_5d_pct": self.margin_5d_pct,
            "short_5d_pct": self.short_5d_pct,
            "sector_inflow": self.sector_inflow,
            "dominant_player": self.dominant_player,
            "crowding_score": self.crowding_score,
            "gt_entry_allowed": self.gt_entry_allowed,
            "held": self.held, "position_loss_pct": self.position_loss_pct,
            "data_gaps": self.data_gaps,
        }


@dataclass
class TacticsResult:
    """短线战术最终结论。"""

    symbol: str
    name: str = ""
    current_price: float = 0.0

    # Phase 1 快照
    snapshot: Optional[TacticalSnapshot] = None

    # Phase 2 输出
    doctrine_passed: bool = True
    doctrine_warnings: list[str] = field(default_factory=list)
    debate_result: Optional[dict] = None
    debate_perspectives: Optional[dict] = None
    mental_models: list[dict] = field(default_factory=list)
    t0_result: Optional[dict] = None

    # Phase 3 输出
    verdict_score: float = 0.0
    verdict_recommendation: str = ""
    verdict_confidence: float = 0.0
    signal_action: str = ""
    signal_weight: float = 0.0
    sizing_detail: Optional[dict] = None
    risk_passed: bool = True

    # 最终
    action: str = "WAIT"
    confidence: float = 0.5
    warnings: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)


# ═══════════════════════════════════════════════════════════════════
# Pipeline
# ═══════════════════════════════════════════════════════════════════


def run_tactics(
    orch: "Orchestrator",
    *,
    symbol: str,
    market: str = "SH",
    name: str = "",
    skip_t0: bool = False,
    skip_debate: bool = False,
) -> TacticsResult:
    """短线战术管道 — 4-Phase 架构，买卖时机判断。

    Args:
        orch: Orchestrator 实例（复用所有引擎）
        symbol: 6 位股票代码
        market: SH / SZ
        name: 股票名称
        skip_t0: True=跳过 T+0
        skip_debate: True=跳过辩论+芒格（极速模式，2-3s）
    """
    from src.output.progress import step_start, step_done, info as _info
    from src.output.step_output import (
        print_doctrine, print_diagnosis, print_debate, print_munger_models,
        print_positioning, print_risk_control,
    )

    result = TacticsResult(symbol=symbol, name=name)

    print()
    print("  ⚡ tactics — 短线战术（买卖时机）")
    mode_label = "极速模式" if skip_debate else "标准模式"
    print(f"  📡 {mode_label} | 8步流水线")

    # 步骤计数器 — 贯穿 Phase 1→2→3
    TOTAL = 8
    _step = 0  # Phase 1→2→3 numbered steps

    # ═══════════════════════════════════════════════════════════════
    # Phase 0: 并行预拉取 6 路数据 (~2s)
    # ═══════════════════════════════════════════════════════════════
    _info("Phase 0: 并行拉取 行情/K线/财务/融资/板块资金/市场情绪...")
    t0_tick = datetime.now()

    # 共享存储
    _quote = None
    _cross_validated = False
    _bars_df = None       # pd.DataFrame | None
    _close_series: list[float] = []
    _ma20 = None
    _ma60 = None
    _fin_list: list[dict] = []
    _margin_profile = None
    _margin_alerts: list = []
    _sector_flow = None
    _sentiment = None

    # --- 路 1: 行情 ---
    def _io_quote():
        nonlocal _quote, _cross_validated
        try:
            _quote, _cross_validated, _ = orch.data.get_cross_validated_quote(symbol, market)
        except Exception:
            try:
                _quote = orch.data.get_quote(symbol, market)
            except Exception:
                _quote = orch._quote_from_cache(symbol, market)

    # --- 路 2: 日线K线+MA+财务 ---
    def _io_bars_and_financials():
        nonlocal _bars_df, _close_series, _ma20, _ma60, _fin_list
        import pandas as pd
        end = datetime.now()
        try:
            _bars_df = orch.data.get_history(
                symbol,
                start_date=(end - __import__("datetime").timedelta(days=400)).strftime("%Y%m%d"),
                end_date=end.strftime("%Y%m%d"),
                period="daily",
            )
            if _bars_df is not None and not getattr(_bars_df, "empty", True):
                col_map = {
                    "open": "open", "high": "high", "low": "low",
                    "close": "close", "volume": "volume", "vol": "volume",
                    "开盘": "open", "最高": "high", "最低": "low",
                    "收盘": "close", "成交量": "volume",
                }
                if hasattr(_bars_df, "rename"):
                    _bars_df = _bars_df.rename(
                        columns={c: col_map[c] for c in _bars_df.columns if c in col_map}
                    )
        except Exception as e:
            logger.debug("tactics bars: %s", e)

        if _bars_df is not None and not _bars_df.empty:
            c_col = _bars_df["close"] if "close" in _bars_df.columns else None
            if c_col is not None and len(c_col) > 0:
                _close_series = c_col.tolist()
                if len(c_col) >= 60:
                    _ma20 = float(c_col.rolling(20).mean().iloc[-1])
                    _ma60 = float(c_col.rolling(60).mean().iloc[-1])
                elif len(c_col) >= 20:
                    _ma20 = float(c_col.rolling(20).mean().iloc[-1])

        # 财务
        try:
            fins = orch.data.get_financials(symbol, market, count=8)
            _fin_list = [
                f.model_dump() if hasattr(f, "model_dump") else dict(f)
                for f in (fins or [])
            ]
        except Exception as e:
            logger.debug("tactics financials: %s", e)

    # --- 路 3: 融资融券 ---
    def _io_margin():
        nonlocal _margin_profile, _margin_alerts
        try:
            from src.game_theory.margin import get_margin_analyzer
            analyzer = get_margin_analyzer()
            _margin_profile = analyzer.analyze(symbol, name, close_price=0)
            _margin_alerts = analyzer.get_alerts(symbol, name, close_price=0)
        except Exception as e:
            logger.debug("tactics margin: %s", e)

    # --- 路 4: 板块资金流向 ---
    def _io_sector_flow():
        nonlocal _sector_flow
        try:
            _sector_flow = orch.data.get_sector_capital_flow()
        except Exception as e:
            logger.debug("tactics sector flow: %s", e)

    # --- 路 5: 市场情绪 ---
    def _io_sentiment():
        nonlocal _sentiment
        try:
            from src.sentiment.signals import SentimentDetector
            _sentiment = SentimentDetector().detect_market()
        except Exception as e:
            logger.debug("tactics sentiment: %s", e)

    # --- 路 6: 全球市场 (US+日韩+恒生+A股大盘, 东财API批量) ---
    _global_market = None

    def _io_global_market():
        nonlocal _global_market
        try:
            _global_market = orch.data.get_global_market()
        except Exception as e:
            logger.debug("tactics global_market: %s", e)

    # --- 路 7: 日内K线 (如果 skip_t0, 跳过) ---
    _minute_bars = None

    def _io_minute():
        nonlocal _minute_bars
        if skip_t0:
            return
        try:
            from src.data.schema import Resolution
            today = datetime.now().strftime("%Y%m%d")
            _minute_bars = orch.data.mootdx.get_bars(
                symbol, Resolution.MIN_1, start=today, end=today,
            )
            if _minute_bars:
                now = datetime.now()
                today_dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
                _minute_bars = [
                    b for b in _minute_bars
                    if b is not None and b.timestamp.date() == today_dt.date()
                    and b.timestamp <= now
                ]
        except Exception as e:
            logger.debug("tactics minute bars: %s", e)

    # --- 并行执行 ---
    io_tasks = {
        "quote": _io_quote,
        "bars+fin": _io_bars_and_financials,
        "margin": _io_margin,
        "sector_flow": _io_sector_flow,
        "sentiment": _io_sentiment,
        "global_market": _io_global_market,
        "minute": _io_minute,
    }

    with ThreadPoolExecutor(max_workers=len(io_tasks)) as pool:
        futures = {pool.submit(fn): label for label, fn in io_tasks.items()}
        for f in as_completed(futures):
            try:
                f.result()
            except Exception as e:
                logger.debug("tactics io %s: %s", futures[f], e)

    # 逐源状态 — 每路IO独立展示成功/失败
    _io_parts = []
    cv = "✅双源" if _cross_validated else "⚠️单源"
    _io_parts.append(f"行情{cv}" if _quote else "行情❌")
    if _bars_df is not None and not getattr(_bars_df, "empty", True):
        _io_parts.append(f"K线{len(_close_series)}根")
    else:
        _io_parts.append("K线❌")
    _io_parts.append(f"财务{len(_fin_list)}期" if _fin_list else "财务❌")
    _io_parts.append("融资✅" if _margin_profile is not None else "融资❌")
    _io_parts.append("板块✅" if _sector_flow is not None else "板块❌")
    _io_parts.append("情绪✅" if _sentiment is not None else "情绪❌")
    _io_parts.append("全球✅" if _global_market is not None else "全球❌")
    if not skip_t0:
        _io_parts.append(f"日内{len(_minute_bars)}根" if _minute_bars else "日内❌")
    _info(f"  {' | '.join(_io_parts)}")

    phase0_elapsed = (datetime.now() - t0_tick).total_seconds()
    _info(f"  Phase 0 完成 ({phase0_elapsed:.1f}s)")

    # --- Phase 0 兜底检查 ---
    if _quote is None:
        result.warnings.append("行情数据不可用")
        print("  ⛔ 行情不可用")
        return result

    current_price = float(getattr(_quote, "price", 0) or 0)
    result.current_price = current_price
    if not name:
        name = _quote.name or ""
        result.name = name

    quote_dict = _quote.model_dump() if hasattr(_quote, "model_dump") else (
        _quote.dict() if hasattr(_quote, "dict") else {}
    )
    quote_dict["_source"] = getattr(_quote, "source", "unknown")
    quote_dict["cross_validated"] = _cross_validated
    quote_dict["ma20"] = _ma20
    quote_dict["ma60"] = _ma60
    quote_dict["close_series"] = (_close_series[-10:] if len(_close_series) >= 10
                                  else _close_series)

    # 投资者偏好
    investor, _, _, _ = orch._get_investor_prefs()
    position_limits = None
    weights = None
    risk_mult = 1.0
    enabled_rules = None
    if investor is not None:
        try:
            from src.learner.preference.adapter import (
                resolve_weights, resolve_rule_filter,
                resolve_position_limits, resolve_macro_cap_multiplier,
                is_board_accessible,
            )
            from src.learner.preference.model import get_board_from_symbol
            if not is_board_accessible(investor, symbol):
                result.warnings.append(f"板块限制: {get_board_from_symbol(symbol)}")
                return result
            position_limits = resolve_position_limits(investor)
            weights = resolve_weights(investor)
            risk_mult = resolve_macro_cap_multiplier(investor)
            enabled_rules = resolve_rule_filter(investor)
        except Exception as e:
            logger.debug("tactics prefs: %s", e)

    # 持仓
    pos_snap = _load_position_row(symbol)
    held = bool(pos_snap)
    loss_pct = 0.0
    if pos_snap:
        loss_pct = _pos_loss_pct(current_price, pos_snap.get("entry_price"))

    # ═══════════════════════════════════════════════════════════════
    # Phase 1: 盘面全景 (~0.5s, 4维并行本地计算)
    # ═══════════════════════════════════════════════════════════════
    _info("Phase 1: 盘面全景 (基本面‖技术面‖资金面‖市场背景 并行)...")
    t1_tick = datetime.now()

    snapshot = TacticalSnapshot(
        symbol=symbol, name=name,
        current_price=current_price,
        change_pct=float(getattr(_quote, "change_pct", 0) or 0),
        held=held, position_loss_pct=loss_pct,
    )
    if pos_snap:
        snapshot.position_entry = pos_snap.get("entry_price")

    # 并行计算上下文
    _report = None          # diagnosis report
    _gt_profile = None      # game theory profile
    _gt_advice = None       # fused timing advice
    _timing_result = None   # entry/exit timing result

    # --- 维度 1: 市场背景 ---
    def _dim_market_bg():
        if _sentiment is not None:
            # ... existing sentiment code ...
            try:
                level = getattr(getattr(_sentiment, "level", None), "value", None)
                score = getattr(_sentiment, "score", 50)
                if level is None:
                    level = str(getattr(_sentiment, "level", "normal"))
                snapshot.sentiment_label = str(level)
                snapshot.sentiment_score = float(score) if score else 50.0
            except Exception:
                pass
            up = getattr(_sentiment, "up_count", 0) or 0
            dn = getattr(_sentiment, "down_count", 0) or 0
            total = up + dn
            if total > 0:
                snapshot.market_breadth = f"涨{up}/跌{dn} ({up / total * 100:.1f}%上涨)"
            else:
                snapshot.market_breadth = "数据暂缺"

        # 全球市场
        if _global_market and _global_market.summary:
            snapshot.global_market_summary = _global_market.summary
        elif _global_market and _global_market.us_summary:
            snapshot.global_market_summary = _global_market.us_summary

        # 情绪建议 (融入全球市场背景)
        s = snapshot.sentiment_score
        gm = snapshot.global_market_summary
        if s < 25:
            base = "恐慌 — 可稍激进"
            if gm and "-" in gm:
                snapshot.sentiment_advice = f"{base}, 但注意全球联动偏弱"
            else:
                snapshot.sentiment_advice = f"{base}, 注意流动性"
        elif s > 75:
            snapshot.sentiment_advice = "贪婪 — 谨慎追高, 止损必须更紧"
        else:
            snapshot.sentiment_advice = "正常 — 按个股自身判断"

    # --- 维度 2: 基本面 ---
    def _dim_fundamental():
        nonlocal _report
        try:
            _report = orch.diagnosis.analyze(
                symbol, name, quote_dict, _fin_list or None, {}, None,
            )
            if _report:
                snapshot.value_score = _report.value_score
                snapshot.quality_score = _report.quality_score
                snapshot.momentum_score = _report.momentum_score
                # 提取 PE / ROE
                if hasattr(_report, "__dict__"):
                    d = _report.__dict__
                    snapshot.pe_ttm = d.get("pe_ttm") or d.get("pe")
                    snapshot.roe = d.get("roe")
                if _fin_list:
                    latest = _fin_list[0]
                    if snapshot.pe_ttm is None:
                        snapshot.pe_ttm = quote_dict.get("pe_ttm") or quote_dict.get("pe")
                    if snapshot.roe is None:
                        snapshot.roe = latest.get("roe")
                # 行业PE
                if snapshot.pe_ttm:
                    snapshot.industry_pe = _estimate_industry_pe(symbol)
                snapshot.fundamental_note = (
                    f"价值{snapshot.value_score:.0f} 质量{snapshot.quality_score:.0f} "
                    f"动量{snapshot.momentum_score:.0f}"
                )
        except Exception as e:
            logger.debug("tactics fundamental: %s", e)
            snapshot.data_gaps.append("[DATA_GAP] 基本面诊断")

    # --- 维度 3: 技术面 (6维+入场出场+KDJ, 共享K线) ---
    def _dim_technical():
        nonlocal _timing_result
        if _bars_df is None or getattr(_bars_df, "empty", True):
            snapshot.data_gaps.append("[DATA_GAP] 技术面(日线不可用)")
            return

        import pandas as pd
        from src.routing.technical import TechnicalAnalyzer
        from src.routing.entry_exit_engine import EntryExitEngine
        from src.alphas.macd_kdj import evaluate_ohlc_latest, normalize_ohlc_df

        df = _bars_df
        if len(df) < 20:
            snapshot.data_gaps.append("[DATA_GAP] 技术面(日线不足20根)")
            return

        c_col = df["close"] if "close" in df.columns else None
        if c_col is None:
            return
        h_col = df["high"] if "high" in df.columns else c_col
        l_col = df["low"] if "low" in df.columns else c_col
        v_col = df["volume"] if "volume" in df.columns else pd.Series([1e6] * len(c_col))

        panel = {
            "close": pd.DataFrame({symbol: c_col.values}, index=c_col.index),
            "high": pd.DataFrame({symbol: h_col.values}, index=h_col.index),
            "low": pd.DataFrame({symbol: l_col.values}, index=l_col.index),
            "volume": pd.DataFrame({symbol: v_col.values}, index=v_col.index),
        }

        # 6维评分
        try:
            tech = TechnicalAnalyzer().analyze(symbol, name, panel)
            snapshot.trend_score = tech.trend_score
            snapshot.reversal_score = tech.reversal_score
            snapshot.volume_score = tech.volume_score
            snapshot.volatility_score = tech.volatility_score
            snapshot.ma_score = tech.ma_score
            snapshot.limit_up_score = tech.limit_up_score
            snapshot.technical_composite = tech.composite_score
        except Exception:
            pass

        # 入场/出场信号
        try:
            _timing_result = EntryExitEngine().evaluate(symbol, name, panel)
            if _timing_result:
                snapshot.entry_signals = [
                    {"type": s.type, "description": s.description,
                     "zone_low": s.entry_zone_low, "zone_high": s.entry_zone_high,
                     "confidence": s.confidence}
                    for s in _timing_result.entry_signals
                ]
                snapshot.exit_signals = [
                    {"type": s.type, "description": s.description,
                     "zone_low": s.exit_zone_low, "zone_high": s.exit_zone_high,
                     "confidence": s.confidence, "urgency": s.urgency}
                    for s in _timing_result.exit_signals
                ]
                if _timing_result.best_entry:
                    be = _timing_result.best_entry
                    snapshot.best_entry = {
                        "type": be.type, "description": be.description,
                        "zone_low": be.entry_zone_low, "zone_high": be.entry_zone_high,
                        "confidence": be.confidence,
                    }
                snapshot.suggested_stop = _timing_result.suggested_stop
                snapshot.atr_stop = _timing_result.atr_stop
                snapshot.target_prices = [_timing_result.target_1, _timing_result.target_2]
                snapshot.time_stop_days = _timing_result.time_stop_days
        except Exception:
            pass

        # KDJ+MACD
        try:
            kdj_df = normalize_ohlc_df(df)
            if kdj_df is not None and len(kdj_df) >= 40:
                px = float(quote_dict.get("price") or quote_dict.get("close") or 0)
                if px > 0 and "close" in kdj_df.columns:
                    last = float(kdj_df["close"].iloc[-1])
                    if abs(last - px) / max(px, 1e-9) > 0.001:
                        kdj_df = kdj_df.copy()
                        kdj_df.loc[kdj_df.index[-1], "close"] = px
                snapshot.macd_kdj = evaluate_ohlc_latest(kdj_df)
        except Exception:
            pass

        snapshot.technical_note = (
            f"综合{snapshot.technical_composite:.0f} "
            f"趋势{snapshot.trend_score:.0f} 反转{snapshot.reversal_score:.0f} "
            f"量价{snapshot.volume_score:.0f} | "
            f"入场{len(snapshot.entry_signals)}个 出场{len(snapshot.exit_signals)}个"
        )

    # --- 维度 4: 资金面 (融资+板块+博弈融合) ---
    def _dim_capital():
        nonlocal _gt_profile, _gt_advice

        # 融资融券
        if _margin_profile is not None:
            mp = _margin_profile
            snapshot.margin_balance = getattr(mp, "margin_balance", None)
            snapshot.margin_trend = getattr(mp, "margin_balance_trend", "stable") or "stable"
            snapshot.margin_5d_pct = getattr(mp, "margin_balance_5d_change_pct", 0.0) or 0.0
            snapshot.short_balance = getattr(mp, "short_balance", None)
            snapshot.short_5d_pct = getattr(mp, "short_balance_5d_change_pct", 0.0) or 0.0
            if _margin_alerts:
                snapshot.margin_alerts = [
                    f"[{a.severity}] {a.message[:80]}" for a in _margin_alerts[:5]
                ]
        else:
            snapshot.data_gaps.append("[DATA_GAP] 融资融券")

        # 板块资金流向
        if _sector_flow is not None and hasattr(_sector_flow, "sectors") and _sector_flow.sectors:
            try:
                top_in = sorted(_sector_flow.sectors, key=lambda x: x.main_net, reverse=True)[:3]
                top_out = sorted(_sector_flow.sectors, key=lambda x: x.main_net)[:3]
                snapshot.sector_top_inflow = [
                    f"{s.sector_name}({s.main_net:+.1f}亿)" for s in top_in
                ]
                snapshot.sector_top_outflow = [
                    f"{s.sector_name}({s.main_net:+.1f}亿)" for s in top_out
                ]
                # 判断标的所在板块是否净流入 (先确定板块名)
                stock_sector = _infer_stock_sector(symbol, name)
                for s in _sector_flow.sectors:
                    if s.sector_name == stock_sector:
                        snapshot.sector_inflow = s.main_net > 0
                        break
            except Exception:
                pass
        elif _sector_flow is not None:
            snapshot.data_gaps.append(
                getattr(_sector_flow, "data_gap_reason", "[DATA_GAP] 板块资金流向")
            )

        # 博弈论分析
        try:
            mcap = getattr(_quote, "market_cap", None) or quote_dict.get("market_cap")
            _gt_profile = orch.gt_analyzer.analyze(symbol, name, mcap, "")
        except Exception as e:
            logger.debug("tactics gt: %s", e)

        if _gt_profile:
            snapshot.dominant_player = getattr(_gt_profile, "dominant_player", "") or ""
            snapshot.crowding_score = int(
                getattr(_gt_profile, "crowding_score", 50) or 50
            )

        # 博弈×技术融合
        if _timing_result and _gt_profile:
            try:
                from src.routing.gt_timing import fuse_timing_with_game_theory
                _gt_advice = fuse_timing_with_game_theory(
                    _timing_result, _gt_profile,
                    held=held, current_price=current_price,
                    position_loss_pct=loss_pct,
                    bottom_phase="",
                )
            except Exception:
                pass

        if _gt_advice:
            snapshot.gt_entry_allowed = getattr(_gt_advice, "entry_allowed", False)
            snapshot.gt_action = getattr(_gt_advice, "action", "WAIT") or "WAIT"
            snapshot.gt_rationale = list(
                getattr(_gt_advice, "rationale", []) or []
            )[:3]

        # 资金面备注
        parts = []
        if snapshot.margin_balance:
            parts.append(f"融资{snapshot.margin_balance:.1f}亿 {snapshot.margin_trend}")
        if snapshot.short_5d_pct and abs(snapshot.short_5d_pct) > 5:
            parts.append(f"融券5日{snapshot.short_5d_pct:+.0f}%")
        if snapshot.sector_top_inflow:
            parts.append(f"板块流入TOP: {snapshot.sector_top_inflow[0]}")
        parts.append(f"博弈: {snapshot.dominant_player or '?'} 拥挤{snapshot.crowding_score}")
        snapshot.capital_note = " | ".join(parts)

    # --- 并行执行 ---
    _dim_labels = {
        "market_bg": "市场背景", "fundamental": "基本面诊断",
        "technical": "技术面6维", "capital": "资金面",
    }
    dim_tasks = {
        "market_bg": _dim_market_bg,
        "fundamental": _dim_fundamental,
        "technical": _dim_technical,
        "capital": _dim_capital,
    }
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(fn): label for label, fn in dim_tasks.items()}
        for f in as_completed(futures):
            label = futures[f]
            try:
                f.result()
                _info(f"    ✅ {_dim_labels.get(label, label)}")
            except Exception as e:
                _info(f"    ⚠️ {_dim_labels.get(label, label)}")
                logger.debug("tactics dim %s: %s", label, e)

    result.snapshot = snapshot
    phase1_elapsed = (datetime.now() - t1_tick).total_seconds()

    # Phase 1 step marker — after data computed, before detailed output
    _step += 1
    step_start(_step, "盘面全景", total=TOTAL)
    funds_parts = []
    if snapshot.margin_balance:
        funds_parts.append(f"融资{snapshot.margin_balance:.1f}亿")
    if snapshot.sector_top_inflow:
        funds_parts.append(f"板块流入{snapshot.sector_top_inflow[0]}")
    pe_label = f"PE{snapshot.pe_ttm:.0f}" if snapshot.pe_ttm else "PE暂无"
    detail_items = [
        f"情绪{snapshot.sentiment_label.upper()}",
        pe_label,
        f"技术{snapshot.technical_composite:.0f}",
    ] + funds_parts
    step_done("✅", " | ".join(detail_items))

    # --- 输出盘面全景 ---
    _print_snapshot(snapshot)

    # ═══════════════════════════════════════════════════════════════
    # Phase 2: 军规 → 辩论 ‖ 芒格 ‖ T+0
    # ═══════════════════════════════════════════════════════════════
    t2_tick = datetime.now()

    # --- 2a: 军规 (串行, 纯规则, ~0.1s) ---
    _step += 1
    step_start(_step, "军规审查", total=TOTAL)
    _doctrine_warnings: list[str] = []
    _doctrine_full = None

    # 构建军规上下文 (从缓存提取, 零网络)
    doctrine_ctx = {"stock_name": name}
    cs = _close_series
    if len(cs) >= 6:
        try:
            doctrine_ctx["rise_5day_pct"] = round((cs[-1] - cs[-6]) / cs[-6] * 100, 2)
        except Exception:
            doctrine_ctx["rise_5day_pct"] = 0.0
    if len(cs) >= 4:
        try:
            doctrine_ctx["drop_3day_pct"] = round((cs[-1] - cs[-4]) / cs[-4] * 100, 2)
        except Exception:
            pass
    try:
        bottom_ctx = {}
        orch._inject_bottom_structure_ctx(symbol, market,
            {"close_series": cs}, bottom_ctx)
        doctrine_ctx.update(bottom_ctx)
    except Exception:
        pass
    try:
        _extract_financial_doctrine_ctx(_fin_list, doctrine_ctx)
    except Exception:
        pass

    dr = orch.doctrine.check(symbol, doctrine_ctx, enabled_rules=enabled_rules)
    # 短线模式: 所有规则降级为 warn, 不 block
    _doctrine_warnings = [r.name for r in dr.warnings + dr.blocked_by]

    # 构建 doctrine_full
    triggered = {r.id for r in dr.blocked_by + dr.warnings + dr.infos}
    from src.doctrine.rules import MILITARY_RULES
    all_rules = []
    for rule in MILITARY_RULES:
        if enabled_rules is not None and rule.id not in enabled_rules:
            continue
        status = (
            "warn" if (rule in dr.blocked_by or rule in dr.warnings)
            else ("info" if rule in dr.infos else "passed")
        )
        all_rules.append({
            "id": rule.id, "name": rule.name,
            "severity": rule.severity.value,
            "description": rule.description, "status": status,
        })
    _doctrine_full = {"passed": True, "warn_count": len(_doctrine_warnings), "rules": all_rules}

    result.doctrine_passed = True  # 短线模式不block
    result.doctrine_warnings = _doctrine_warnings

    step_done(
        ("⚠️" if _doctrine_warnings else "✅"),
        f"31条: 阻断0 警告{len(_doctrine_warnings)}"
    )
    try:
        print_doctrine(_doctrine_full)
    except Exception:
        pass

    # --- 2b: 辩论 ‖ 芒格 ‖ T+0 (并行) ---
    _debate = None
    _matched_models: list = []
    _t0 = None

    def _run_debate():
        nonlocal _debate
        if skip_debate:
            return
        if _report is None:
            return
        try:
            _debate = orch.perspective_analyzer.debate(
                symbol, name, l1_report=_report,
                quote=quote_dict, financials=_fin_list or [],
            )
        except Exception as e:
            logger.debug("tactics debate: %s", e)

    def _run_mental_models():
        nonlocal _matched_models
        if skip_debate:
            return
        if _report is None:
            return
        try:
            _sector = getattr(_report, "sector", "") or ""
            # 注入时机上下文 — 让匹配器知道这是短线买卖时机判断而非选股
            timing_question = _build_timing_question(snapshot)
            _matched_models = orch.mental_model_matcher.match_models(
                symbol, name, sector=_sector, report=_report,
                question=timing_question,
            )
        except Exception as e:
            logger.debug("tactics munger: %s", e)

    def _run_t0():
        nonlocal _t0
        if skip_t0:
            return
        try:
            _t0 = orch.run_t0(symbol, market, name)
        except Exception as e:
            logger.debug("tactics t0: %s", e)

    phase2_tasks = {
        "debate": _run_debate,
        "mental_models": _run_mental_models,
        "t0": _run_t0,
    }

    # 先并行跑，再按顺序展示步骤进度
    _phase2_results: dict[str, Exception | None] = {}
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(fn): label for label, fn in phase2_tasks.items()}
        for f in as_completed(futures):
            label = futures[f]
            try:
                f.result()
                _phase2_results[label] = None
            except Exception as e:
                _phase2_results[label] = e
                logger.debug("tactics phase2 %s: %s", label, e)

    # --- 2b-1: 四大师辩论 ---
    _step += 1
    step_start(_step, "四大师辩论", total=TOTAL)
    if _debate:
        step_done("✅", f"分歧度{_debate.score_range:.1f} 评分{_debate.avg_score:.1f}/5")
    elif skip_debate:
        step_done("⏭️", "极速模式跳过")
    else:
        step_done("⚠️", "辩论数据不可用")

    # --- 2b-2: Munger 思维模型 ---
    _step += 1
    step_start(_step, "Munger思维模型", total=TOTAL)
    if _matched_models:
        step_done("✅", f"匹配{len(_matched_models)}个模型")
    elif skip_debate:
        step_done("⏭️", "极速模式跳过")
    else:
        step_done("⚠️", "模型匹配不可用")

    # --- 2b-3: T+0 日内时机 ---
    _step += 1
    step_start(_step, "T+0日内时机", total=TOTAL)
    if _t0 is not None:
        score = _t0.get("score", 0) if isinstance(_t0, dict) else getattr(_t0, "score", 0)
        action = _t0.get("advice", "") if isinstance(_t0, dict) else getattr(_t0, "advice", "")
        step_done("✅", f"得分{score} {action}" if action else f"得分{score}")
    elif skip_t0:
        step_done("⏭️", "已跳过")
    else:
        step_done("⚠️", "T+0数据不可用")

    # --- 处理结果 ---
    if _debate:
        result.debate_result = {
            "avg_score": _debate.avg_score,
            "score_range": _debate.score_range,
            "agreement_level": _debate.agreement_level,
            "recommendation": _debate.recommendation,
            "top_disagreement": _debate.top_disagreement,
            "top_agreement": _debate.top_agreement,
            "tension_summary": _debate.tension_summary,
        }
        result.debate_perspectives = {
            "buffett": _perspective_to_dict(_debate.buffett),
            "li_lu": _perspective_to_dict(_debate.li_lu),
            "munger": _perspective_to_dict(_debate.munger),
            "lynch": _perspective_to_dict(_debate.lynch),
        }
        try:
            print_debate(result.debate_perspectives, result.debate_result)
        except Exception:
            pass

    # ── 博弈论×技术融合 (GT Timing) ──
    if _gt_advice:
        try:
            from src.routing.gt_timing import print_gt_timing
            print_gt_timing(_gt_advice)
        except Exception:
            pass

    if _matched_models:
        result.mental_models = _matched_models
        try:
            print_munger_models(_matched_models, name)
        except Exception:
            pass

    if _t0 is not None:
        result.t0_result = _t0
        try:
            from src.output.step_output import print_t0
            print_t0(_t0)
        except Exception:
            pass
    elif not skip_t0:
        snapshot.data_gaps.append("[DATA_GAP] T+0")

    phase2_elapsed = (datetime.now() - t2_tick).total_seconds()

    # ═══════════════════════════════════════════════════════════════
    # Phase 3: 裁决+仓位+风控 (~1s)
    # ═══════════════════════════════════════════════════════════════
    t3_tick = datetime.now()

    if _report is None:
        result.warnings.append("诊断数据缺失，无法裁决")
        return result

    # --- 3a: 裁决 ---
    _step += 1
    step_start(_step, "综合裁决", total=TOTAL)
    from src.routing.verdict import VerdictEngine
    verdict = orch.verdict_engine.judge(_report, weights_override=weights, mode="trading")
    result.verdict_score = verdict.score
    result.verdict_recommendation = verdict.recommendation
    result.verdict_confidence = verdict.confidence

    if verdict.confidence < VerdictEngine.MIN_CONFIDENCE:
        result.warnings.append(f"置信度偏低 ({verdict.confidence:.2f})")

    # 补齐 citations
    if _gt_profile and getattr(_gt_profile, "source_citations", None):
        _report.source_citations.extend(_gt_profile.source_citations)
    if _debate:
        _report.source_citations.append(make_citation(
            provider="perspective_analyzer", field="four_perspective_debate_timing",
            data_type="analyst_report", source_tier="T3", nature="speculation",
            confidence=0.45,
        ))
    if _matched_models:
        _report.source_citations.append(make_citation(
            provider="mental_model_matcher", field="munger_mental_models_timing",
            data_type="analyst_report", source_tier="T2", nature="interpretation",
            confidence=0.65,
        ))

    # 交叉校验
    if _gt_advice:
        if (_gt_advice.action in ("EXIT", "REDUCE")
                and verdict.recommendation in ("ADD", "BUY", "STRONG_BUY")):
            result.warnings.append(
                f"博弈卖点({_gt_advice.action}) vs 裁决({verdict.recommendation}) — 卖点优先"
            )
        if (_gt_advice.action == "ENTER"
                and verdict.recommendation in ("REDUCE", "SELL", "AVOID")):
            result.warnings.append(
                f"技术买点 vs 裁决({verdict.recommendation}) — 勿逆裁决"
            )
            _gt_advice.entry_allowed = False
            _gt_advice.action = "WAIT"

    step_done(
        "✅" if verdict.score >= 60 else ("🟡" if verdict.score >= 40 else "🔴"),
        f"{verdict.score:.0f}/100 {verdict.recommendation} 置信{verdict.confidence:.0%}"
    )
    from src.output.step_output import print_verdict
    try:
        print_verdict(verdict, None, None)
    except Exception:
        pass

    # --- 仓位 ---
    effective_cap = 0.80 * risk_mult * float(
        getattr(_gt_advice, 'size_hint', 1.0) if _gt_advice else 1.0
    )
    signal = orch.positioning.generate_signal(
        verdict,
        macro_cap=effective_cap,
        position_limits=position_limits,
        risk_multiplier=risk_mult * float(
            getattr(_gt_advice, 'size_hint', 1.0) if _gt_advice else 1.0
        ),
        name=name,
        extra=quote_dict,
        timing_result=_timing_result,
    )

    # 持仓卖点覆盖
    if held and _gt_advice and _gt_advice.action in ("EXIT", "REDUCE"):
        try:
            signal.action = "CLOSE" if _gt_advice.action == "EXIT" else "REDUCE"  # type: ignore[attr-defined]
            if _gt_advice.action == "EXIT":
                if hasattr(signal, "weight"):
                    signal.weight = 0.0  # type: ignore[attr-defined]
        except Exception:
            pass

    pos_stop = None
    if pos_snap:
        try:
            pos_stop = float(pos_snap.get("stop_price") or 0) or None
        except (TypeError, ValueError):
            pass
    if held and pos_stop and pos_stop > 0 and hasattr(signal, "suggested_stop"):
        try:
            signal.suggested_stop = pos_stop  # type: ignore[attr-defined]
        except Exception:
            pass

    result.signal_action = getattr(signal, "action", "?")
    result.signal_weight = float(getattr(signal, "weight", 0) or 0)
    result.sizing_detail = {
        "method": getattr(signal, "sizing_method", "tactics"),
        "macro_cap": effective_cap,
        "risk_multiplier": risk_mult,
        "timing_action": getattr(_gt_advice, 'action', '?') if _gt_advice else '?',
        "mode": "tactics",
    }

    # --- 风控 ---
    enriched = {"current_price": current_price}
    if pos_snap:
        enriched.update({
            "held": True, "entry_price": pos_snap.get("entry_price"),
            "stop_price": pos_stop or pos_snap.get("stop_price"),
            "quantity": pos_snap.get("quantity"),
            "position_loss_pct": loss_pct,
        })
    else:
        enriched["held"] = False
    if _gt_profile:
        enriched["game_theory_risks"] = list(getattr(_gt_profile, "risks", []) or [])
        enriched["dominant_player"] = getattr(_gt_profile, "dominant_player", "")
    if _gt_advice:
        enriched["timing_action"] = _gt_advice.action
        enriched["exit_urgency"] = _gt_advice.exit_urgency

    risk = orch.risk_ctrl.check(
        signal,
        market={"change_pct": getattr(_quote, "change_pct", 0)},
        portfolio=enriched,
        position_limits=position_limits,
    )
    result.risk_passed = getattr(risk, "passed", True)

    # --- 3b: 仓位 ---
    _step += 1
    step_start(_step, "仓位调度", total=TOTAL)
    step_done(
        "✅" if result.signal_weight > 0 else "🟡",
        f"{result.signal_action} {result.signal_weight:.1%} | "
        f"方法:{result.sizing_detail.get('method','?')}"
    )

    # --- 3c: 风控 ---
    _step += 1
    step_start(_step, "风控执行", total=TOTAL)
    step_done("✅" if result.risk_passed else "🔴", "通过" if result.risk_passed else "拦截")
    try:
        print_positioning(signal, result.sizing_detail)
        print_risk_control(risk)
    except Exception:
        pass

    phase3_elapsed = (datetime.now() - t3_tick).total_seconds()
    total_elapsed = (datetime.now() - t0_tick).total_seconds()

    # ═══════════════════════════════════════════════════════════════
    # 最终结论
    # ═══════════════════════════════════════════════════════════════
    _resolve_final_action(result, snapshot, _gt_advice, held)

    # 投资者画像摘要
    investor_line = ""
    if investor is not None:
        try:
            style = getattr(investor, 'trading_style', None)
            risk = getattr(investor, 'risk_profile', None)
            parts = []
            if style:
                parts.append(f"风格={style.value}")
            if risk:
                parts.append(f"风险={risk.value}")
            parts.append(f"仓位系数={risk_mult:.0%}")
            investor_line = " | ".join(parts)
        except Exception:
            pass

    # 凯利公式信息
    kelly_info = ""
    if result.sizing_detail:
        method = result.sizing_detail.get("method", "")
        if method and method not in ("linear_fallback", "unknown"):
            kelly_info = f"凯利({method})"

    # ATR 止损额外展示
    atr_info = ""
    if snapshot.atr_stop > 0 and snapshot.atr_stop != snapshot.suggested_stop:
        atr_info = f" ATR止损{snapshot.atr_stop:.2f}"

    print("\n" + "=" * 56)
    print(f"  ⚡ tactics 完成 ({total_elapsed:.1f}s)"
          f"{' [极速]' if skip_debate else ''}")
    if investor_line:
        print(f"  👤 {investor_line}")
    print(f"  {name} {symbol}  {current_price:.2f}  "
          f"({snapshot.change_pct:+.2f}%)")
    print(f"  情绪: {snapshot.sentiment_label} "
          f"军规: {'✅' if not _doctrine_warnings else '⚠️'+str(len(_doctrine_warnings))} | "
          f"裁决: {result.verdict_score:.0f}/100 {result.verdict_recommendation}")
    print(f"  动作: {result.action} | 仓位: {result.signal_weight:.1%}"
          f"{' | '+kelly_info if kelly_info else ''}"
          f" | 风控: {'PASS' if result.risk_passed else '⚠️'}")
    if snapshot.best_entry:
        be = snapshot.best_entry
        print(f"  入场: {be['type']} [{be['zone_low']:.2f}-{be['zone_high']:.2f}] "
              f"c={be['confidence']:.0%}")
    if snapshot.suggested_stop > 0:
        print(f"  止损: {snapshot.suggested_stop:.2f}{atr_info}", end="")
        if snapshot.target_prices and snapshot.target_prices[0] > 0:
            print(f" | 目标: {snapshot.target_prices[0]:.2f}/{snapshot.target_prices[1]:.2f}")
        else:
            print()
    if snapshot.macd_kdj:
        print(f"  KDJ: {snapshot.macd_kdj.get('action')} "
              f"c={snapshot.macd_kdj.get('confidence', 0):.2f}")
    if snapshot.margin_balance:
        print(f"  融资: {snapshot.margin_balance:.1f}亿 {snapshot.margin_trend}"
              f"{' | 融券5日'+f'{snapshot.short_5d_pct:+.0f}%' if snapshot.short_5d_pct else ''}")
    if snapshot.sector_top_inflow:
        print(f"  板块: 流入TOP {snapshot.sector_top_inflow[0]}")
    if result.debate_result:
        print(f"  辩论: {result.debate_result.get('agreement_level', '?')} "
              f"评分{result.debate_result.get('avg_score', 0):.0f}")
    if result.warnings:
        print(f"  ⚠️  {', '.join(result.warnings[:5])}")
    print("=" * 56)

    result.confidence = verdict.confidence
    return result


# ═══════════════════════════════════════════════════════════════════
# Phase 1 输出
# ═══════════════════════════════════════════════════════════════════


def _print_snapshot(s: TacticalSnapshot) -> None:
    """格式化输出盘面全景 — 每维度完整展示，像 diagnose 管道一样清晰。"""
    HR = "─" * 60

    # ── 🌍 市场背景 ──
    label_emoji = {"fear": "😱", "greed": "🤑"}.get(s.sentiment_label, "😐")
    print(f"\n{'='*60}")
    print(f"  🌍 市场背景")
    print(f"{'='*60}")
    print(f"  情绪: {label_emoji} {s.sentiment_label.upper()}  "
          f"评分 {s.sentiment_score:.0f}/100")
    if s.market_breadth:
        print(f"  宽度: {s.market_breadth}")
    if s.global_market_summary:
        print(f"  全球: 🌏 {s.global_market_summary}")
    print(f"  建议: {s.sentiment_advice}")

    # ── 📊 基本面 ──
    print(f"\n  {HR}")
    print(f"  📊 基本面诊断")
    print(f"  {HR}")
    pe_str = (f"PE(TTM) {s.pe_ttm:.1f}" if s.pe_ttm else "PE(TTM) 暂无")
    ind_str = (f"(行业参考 {s.industry_pe:.0f})" if s.industry_pe else "")
    roe_str = (f"ROE {s.roe:.1f}%" if s.roe else "ROE 暂无")
    print(f"  估值: {pe_str} {ind_str}  {roe_str}")
    # 三维评分 + 解读
    _score_bar = lambda v: "█" * int(v / 10) + "░" * (10 - int(v / 10))
    print(f"  价值 {_score_bar(s.value_score)} {s.value_score:.0f}/100  "
          f"质量 {_score_bar(s.quality_score)} {s.quality_score:.0f}/100  "
          f"动量 {_score_bar(s.momentum_score)} {s.momentum_score:.0f}/100")
    _interpret_value(s.value_score, "价值")
    _interpret_quality(s.quality_score, s.roe)
    _interpret_momentum(s.momentum_score, s.change_pct)

    # ── 📈 技术面 ──
    print(f"\n  {HR}")
    print(f"  📈 技术面 (6维)")
    print(f"  {HR}")
    dims = [
        ("趋势", s.trend_score, _trend_interpret(s.trend_score)),
        ("反转", s.reversal_score, _reversal_interpret(s.reversal_score)),
        ("量价", s.volume_score, _volume_interpret(s.volume_score)),
        ("波动", s.volatility_score, _vol_interpret(s.volatility_score)),
        ("均线", s.ma_score, _ma_interpret(s.ma_score)),
        ("打板", s.limit_up_score, _limit_up_interpret(s.limit_up_score)),
    ]
    for name, score, interp in dims:
        bar = "█" * int(score / 10) + "░" * (10 - int(score / 10))
        print(f"  {name:4s} {bar} {score:3.0f}/100  → {interp}")
    print(f"  {'综合':4s} {'='*20} {s.technical_composite:.0f}/100")

    # 入场信号详情
    if s.entry_signals:
        print(f"\n  🟢 入场信号 ({len(s.entry_signals)}个):")
        for es in s.entry_signals:
            print(f"     · {es['type']}: {es['description']}")
            print(f"       入场区间 [{es['zone_low']:.2f} — {es['zone_high']:.2f}]  置信度 {es['confidence']:.0%}")
    else:
        print(f"\n  🟢 入场信号: 暂无 — 尚未触发技术买点")

    # 出场信号详情
    if s.exit_signals:
        print(f"\n  🔴 出场信号 ({len(s.exit_signals)}个):")
        for xs in s.exit_signals:
            u = " ⚠️紧急!" if xs.get("urgency") == "URGENT" else ""
            print(f"     · {xs['type']}: {xs['description']}{u}")
            print(f"       出场区间 [{xs['zone_low']:.2f} — {xs['zone_high']:.2f}]  置信度 {xs['confidence']:.0%}")
    else:
        print(f"\n  🔴 出场信号: 暂无")

    # 最佳入场/止损/目标
    if s.best_entry:
        be = s.best_entry
        print(f"\n  🎯 最佳入场: {be['type']} [{be['zone_low']:.2f}—{be['zone_high']:.2f}] "
              f"置信度 {be['confidence']:.0%}")
        print(f"     {be['description']}")
    if s.suggested_stop > 0:
        stops = [f"建议止损 {s.suggested_stop:.2f}"]
        if s.atr_stop > 0 and abs(s.atr_stop - s.suggested_stop) > 0.01:
            stops.append(f"ATR止损 {s.atr_stop:.2f}")
        print(f"  🛑 {' | '.join(stops)}")
    if s.target_prices and s.target_prices[0] > 0:
        print(f"  🎯 目标价: T1={s.target_prices[0]:.2f}  T2={s.target_prices[1]:.2f}")

    # MACD+KDJ 五法 详细
    if s.macd_kdj:
        mk = s.macd_kdj
        print(f"\n  📐 MACD+KDJ 五法:")
        print(f"     动作: {mk.get('action')}  置信度 {mk.get('confidence', 0):.2f}")
        methods = mk.get("methods", []) or []
        if methods:
            print(f"     触发方法: {', '.join(methods)}")
        notes = mk.get("notes", []) or []
        if notes:
            for note in notes[:5]:
                print(f"     · {note}")
        # 数值
        vals = []
        for k in ["dif", "dea", "hist", "k", "d", "j"]:
            v = mk.get(k)
            if v is not None:
                vals.append(f"{k.upper()}={v:+.4f}" if k == "hist" else f"{k.upper()}={v:.2f}")
        if vals:
            print(f"     数值: {' | '.join(vals)}")

    # ── 💰 资金面 ──
    print(f"\n  {HR}")
    print(f"  💰 资金面")
    print(f"  {HR}")

    # 融资融券
    if s.margin_balance:
        trend_icon = {"increasing": "📈 增加", "decreasing": "📉 减少"}.get(s.margin_trend, "➡️ 持平")
        print(f"  融资余额: {s.margin_balance:.1f}亿  {trend_icon}  5日变化 {s.margin_5d_pct:+.1f}%")
        if s.short_balance:
            print(f"  融券余额: {s.short_balance:.2f}亿  5日变化 {s.short_5d_pct:+.1f}%")
        # 解读融资信号
        if s.margin_5d_pct < -5:
            print(f"     ⚠️ 融资5日大幅流出 — 杠杆资金撤退信号")
        elif s.margin_5d_pct < -2:
            print(f"     ⚠️ 融资5日小幅流出 — 短线杠杆偏谨慎")
        elif s.margin_5d_pct > 5:
            print(f"     📈 融资5日大幅流入 — 杠杆资金积极做多")
        elif s.margin_5d_pct > 2:
            print(f"     📈 融资5日小幅流入 — 杠杆资金偏乐观")
    else:
        print(f"  融资融券: 数据暂缺")
    if s.margin_alerts:
        for a in s.margin_alerts[:3]:
            print(f"     {a}")

    # 板块资金流向
    if s.sector_top_inflow:
        print(f"\n  板块资金流向 (主力净额):")
        print(f"    🟢 流入 TOP3: {', '.join(s.sector_top_inflow)}")
    if s.sector_top_outflow:
        print(f"    🔴 流出 TOP3: {', '.join(s.sector_top_outflow)}")
    if s.sector_inflow is not None:
        status = "🟢 标的板块今日净流入" if s.sector_inflow else "🔴 标的板块今日净流出"
        print(f"    {status}")

    # 博弈论摘要
    print(f"\n  博弈论:")
    print(f"    主导玩家: {s.dominant_player or '(未知)'}  "
          f"拥挤度: {s.crowding_score}/100  "
          f"{'✅ 可入场' if s.gt_entry_allowed else '⛔ 不建议入场'}")
    _interpret_crowding(s.crowding_score)
    if s.gt_rationale:
        print(f"    博弈依据:")
        for r in s.gt_rationale[:5]:
            print(f"      · {r}")

    # 持仓
    if s.held and s.position_entry:
        loss_str = f"{s.position_loss_pct:+.1%}"
        loss_icon = "🔴" if s.position_loss_pct < -0.05 else ("🟢" if s.position_loss_pct > 0.05 else "🟡")
        print(f"\n  📦 持仓状态: {loss_icon} 浮盈{loss_str}  "
              f"成本价 {s.position_entry:.2f}")

    # 数据缺口
    if s.data_gaps:
        print(f"\n  {'─'*60}")
        print(f"  📋 数据缺口:")
        for g in s.data_gaps[:5]:
            print(f"     {g}")
    print()


# ═══════════════════════════════════════════════════════════════════
# 解读辅助函数 — 将裸分数翻译为可读中文信号
# ═══════════════════════════════════════════════════════════════════


def _interpret_value(score: float, label: str = "价值"):
    """价值维度解读。"""
    if score >= 70:
        print(f"     ✅ {label}优秀 — PE显著低于行业/历史中位，估值有安全边际")
    elif score >= 50:
        print(f"     🟡 {label}适中 — PE在合理区间，无显著高估或低估")
    else:
        print(f"     🔴 {label}偏低 — PE偏高或处于历史高分位，估值无安全边际")


def _interpret_quality(score: float, roe):
    """质量维度解读。"""
    roe_s = f"ROE {roe:.1f}%" if roe else ""
    if score >= 70:
        print(f"     ✅ 质量优秀 {roe_s}— 高ROE+现金流扎实+盈利可验证")
    elif score >= 50:
        print(f"     🟡 质量一般 {roe_s}— 盈利尚可但存在纸面利润/现金流风险")
    else:
        print(f"     🔴 质量偏弱 {roe_s}— ROE持续性存疑或现金流质量差")


def _interpret_momentum(score: float, change_pct: float):
    """动量维度解读。"""
    chg = f"当日{change_pct:+.1f}%" if change_pct else ""
    if score >= 60:
        print(f"     📈 动量偏强 {chg}— 短期趋势向上，机构/北向可能流入")
    elif score >= 40:
        print(f"     🟡 动量中性 {chg}— 短期无明确方向，横盘整理中")
    else:
        print(f"     📉 动量偏弱 {chg}— 短期趋势向下，资金可能在流出")


def _trend_interpret(score: float) -> str:
    if score >= 70: return "强势上升通道，均线多头排列"
    if score >= 55: return "温和上行，均线修复中"
    if score >= 45: return "横盘震荡，无明确趋势"
    if score >= 30: return "弱势下行，均线空头排列"
    return "急跌通道，趋势严重破位"


def _reversal_interpret(score: float) -> str:
    if score >= 70: return "超卖+底背离+锤子线等反转信号叠加"
    if score >= 55: return "初步出现超卖/底背离迹象"
    if score >= 45: return "中性，无明确反转信号"
    if score >= 30: return "超买迹象，可能回调"
    return "RSI/KDJ严重超买，大概率见顶回落"


def _volume_interpret(score: float) -> str:
    if score >= 70: return "放量突破，量价配合良好"
    if score >= 55: return "温和放量，量价配合尚可"
    if score >= 45: return "平量，无显著量价背离"
    if score >= 30: return "缩量下跌或放量滞涨，量价背离"
    return "严重缩量或放量暴跌，量价关系恶化"


def _vol_interpret(score: float) -> str:
    if score >= 70: return "波动率收缩至低位，变盘窗口临近"
    if score >= 55: return "波动率适中偏低，风险可控"
    if score >= 45: return "波动率中性"
    if score >= 30: return "波动率偏高，短线风险加大"
    return "极端高波动，警惕短线资金博弈剧烈"


def _ma_interpret(score: float) -> str:
    if score >= 70: return "均线多头排列，MA5>MA10>MA20"
    if score >= 55: return "股价站上MA5，但均线系统未完全多头"
    if score >= 45: return "股价围绕均线震荡，方向不明"
    if score >= 30: return "跌破MA20，均线空头排列雏形"
    return "跌破MA60，均线系统完全空头排列"


def _limit_up_interpret(score: float) -> str:
    if score >= 70: return "涨停基因活跃，封板率高"
    if score >= 55: return "有一定涨停基因，偶尔封板"
    if score >= 45: return "打板属性中性"
    if score >= 30: return "炸板率高，追高风险大"
    return "缺乏涨停基因，非打板标的"


def _interpret_crowding(score: int):
    """拥挤度解读。"""
    if score >= 80:
        print("     🔴 极度拥挤 — 持仓高度集中，踩踏风险极大")
    elif score >= 70:
        print("     🟠 高度拥挤 — 新开仓减半，止损必须更紧")
    elif score >= 50:
        print("     🟡 中度拥挤 — 尚可入场但需控制仓位")
    elif score >= 30:
        print("     🟢 轻度拥挤 — 筹码分散，适合建仓")
    else:
        print("     🟢 不拥挤 — 无人关注时正是好时机")


# ═══════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════


def _load_position_row(symbol: str) -> Optional[dict]:
    for p in [
        Path("data/positions.json"),
        Path.home() / ".hermes" / "baize" / "positions.json",
    ]:
        if not p.exists():
            continue
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(raw, dict) and symbol in raw:
            return raw[symbol]
        if isinstance(raw, list):
            for row in raw:
                if isinstance(row, dict) and str(row.get("symbol")) == symbol:
                    return row
    return None


def _pos_loss_pct(price: float, entry) -> float:
    try:
        e = float(entry or 0)
    except (TypeError, ValueError):
        return 0.0
    if e <= 0 or price <= 0:
        return 0.0
    return (float(price) - e) / e


def _extract_financial_doctrine_ctx(fin_list: list[dict], ctx: dict) -> None:
    """从预拉取的财务数据中提取 r032/r033/r034 军规上下文。内联实现，零网络。"""
    if not fin_list:
        return
    by_year: dict[int, dict] = defaultdict(lambda: {"roe": None, "ocf": 0.0, "np": 0.0})
    for f in fin_list:
        period = f.get("report_period", "")
        if not period or len(period) < 4:
            continue
        try:
            year = int(period[:4])
        except ValueError:
            continue
        is_q4 = "Q4" in period
        if is_q4 or by_year[year]["roe"] is None:
            roe = f.get("roe")
            if roe is not None:
                by_year[year]["roe"] = roe
        ocf = f.get("operating_cash_flow")
        if ocf is not None:
            by_year[year]["ocf"] += ocf
        np_ = f.get("net_profit")
        if np_ is not None:
            by_year[year]["np"] += np_

    sorted_years = sorted(by_year.keys())[-3:]
    ctx["roe_history"] = [
        by_year[y]["roe"] for y in sorted_years
        if by_year[y]["roe"] is not None
    ]
    ctx["operating_cash_flow_3y"] = sum(by_year[y]["ocf"] for y in sorted_years)
    ctx["net_profit_3y"] = sum(by_year[y]["np"] for y in sorted_years)


def _estimate_industry_pe(symbol: str) -> Optional[float]:
    """根据股票代码快速估算行业PE。T2级别，仅作参考。"""
    if symbol.startswith(("600", "601", "603", "605")):
        return 18.0  # 沪主板
    elif symbol.startswith("000") or symbol.startswith("002"):
        return 25.0  # 深主板/中小板
    elif symbol.startswith("300"):
        return 35.0  # 创业板
    elif symbol.startswith("688"):
        return 45.0  # 科创板
    return None


def _infer_stock_sector(symbol: str, name: str) -> str:
    """基于代码+名称推断行业板块。简化版，用于匹配板块资金流向。"""
    try:
        from src.industry.classifier import SectorClassifier
        sc = SectorClassifier()
        result = sc.classify(symbol, name)
        if result and result.sw1_name:
            return result.sw1_name
    except Exception:
        pass
    return ""


def _build_timing_question(snapshot: TacticalSnapshot) -> str:
    """根据盘面快照构造时机上下文问题，注入 Munger 模型匹配器。

    让匹配器知道这是短线买卖时机判断（非选股），匹配偏向：
    - 止损纪律 / 趋势判断 / 逆向思维 / 机会成本 等时机相关模型
    - 而非 护城河 / 管理层 / 复利 等选股相关模型

    关键：输出文本必须包含 _build_signals 中 timing 检测关键词，
    否则 timing_entry/exit/discipline/risk 信号族不会被激活。
    """
    parts = [
        # 基础上下文 — 触发短线模式
        "短线买卖时机判断",
        # 下列关键词直接触发 timing 信号族检测：
        # timing_entry 触发词: 入场|买点|抄底|建仓|突破|回踩|金叉
        # timing_exit 触发词: 出场|卖点|止盈|止损|破位|死叉|减仓|清仓
        # timing_disc 触发词: 时机确认|耐心等待|机会成本|逆向思维|纪律执行
        # timing_risk 触发词: 追高|接刀|博弈|频繁交易|恐慌抛售|FOMO
    ]

    # 趋势状态 → timing_entry / timing_exit
    if snapshot.trend_score >= 60:
        parts.append("追高买入突破金叉入场点确认")
    elif snapshot.trend_score <= 35:
        parts.append("下跌趋势抄底建仓止损纪律死叉减仓")
    else:
        parts.append("方向不明耐心等待时机确认")

    # 反转信号
    if snapshot.reversal_score >= 60:
        parts.append("超卖反弹抄底买点")
    elif snapshot.reversal_score <= 35:
        parts.append("超买回调止盈卖点出场")

    # 拥挤度
    if snapshot.crowding_score >= 70:
        parts.append("拥挤交易避免追高博弈")
    elif snapshot.crowding_score <= 30:
        parts.append("逆向思维恐慌买入机会成本")

    # 持仓状态
    if snapshot.held and snapshot.position_loss_pct < -0.05:
        parts.append("持仓浮亏止损还是持有接刀沉没成本纪律执行")

    # 入场/出场信号
    if snapshot.entry_signals:
        parts.append("技术买点入场金叉确认")
    if snapshot.exit_signals:
        parts.append("技术卖点出场死叉破位减仓")

    # 融资趋势
    if snapshot.margin_5d_pct < -5:
        parts.append("杠杆资金撤退去杠杆止损清仓")
    elif snapshot.margin_5d_pct > 5:
        parts.append("杠杆资金涌入追高FOMO博弈")

    # 波动率
    if snapshot.volatility_score <= 35:
        parts.append("高波动短线博弈频繁交易风险控制")

    # T+0 信号
    if snapshot.macd_kdj:
        action = snapshot.macd_kdj.get("action", "")
        if action == "ENTER":
            parts.append("金叉入场确认")
        elif action == "EXIT":
            parts.append("死叉离场减仓")

    return " ".join(parts)


def _perspective_to_dict(p) -> dict:
    """完整提取大师视角所有字段 — 确保 print_debate 有足够数据展示。"""
    if p is None:
        return {}
    if hasattr(p, "to_dict"):
        d = p.to_dict()
    elif hasattr(p, "model_dump"):
        d = p.model_dump()
    elif isinstance(p, dict):
        d = dict(p)
    else:
        d = {}
    # 补全 print_debate 需要的所有字段（从属性兜底）
    for attr, key in [
        ("score", "score"), ("recommendation", "recommendation"), ("verdict", "verdict"),
        ("methodology", "methodology"), ("one_line_thesis", "one_line_thesis"),
        ("unique_insight", "unique_insight"), ("bull_points", "bull_points"),
        ("bear_points", "bear_points"), ("key_concern", "key_concern"),
        ("qa_pairs", "qa_pairs"), ("questions_to_ask", "questions_to_ask"),
    ]:
        if key not in d or not d[key]:
            val = getattr(p, key, None) if not isinstance(p, dict) else None
            if val:
                d[key] = val
    return d


def _resolve_final_action(
    result: TacticsResult,
    snapshot: TacticalSnapshot,
    advice,
    held: bool,
) -> None:
    """整合所有信号，确定最终 action。"""
    # 卖点优先
    if advice and advice.action in ("EXIT", "REDUCE") and held:
        result.action = advice.action
        return

    rec = result.verdict_recommendation
    if rec in ("STRONG_BUY", "BUY"):
        result.action = "ENTER" if not held else "HOLD"
    elif rec == "ADD":
        result.action = "ENTER" if not held else "ADD"
    elif rec == "REDUCE":
        result.action = "REDUCE"
    elif rec in ("SELL", "AVOID"):
        result.action = "EXIT" if held else "WAIT"
    else:
        result.action = (
            getattr(advice, 'action', 'HOLD') if advice
            else ("HOLD" if held else "WAIT")
        )

    # 博弈阻止
    if advice and not getattr(advice, 'entry_allowed', True) and result.action == "ENTER":
        result.action = "WAIT"
        result.warnings.append("博弈论阻止入场 → WAIT")

    # KDJ 交叉验证
    if snapshot.macd_kdj:
        mk = snapshot.macd_kdj
        if mk.get("action") == "AVOID_ENTRY" and result.action == "ENTER":
            result.action = "WAIT"
            result.warnings.append("KDJ: AVOID_ENTRY → WAIT")
