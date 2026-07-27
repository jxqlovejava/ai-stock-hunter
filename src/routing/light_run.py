# -*- coding: utf-8 -*-
"""持仓轻体检 Pipeline（mode=light）— 性能优化版。

三档体系:
  sentinel  — Hermes cron，仅规则+报价（秒级）
  light     — 本模块：Phase 0 并行预拉 → 本地流水线（3-5s）
  tactics   — 短线战术管道（10-12s）
  daily/full— orchestrator 全链路（15-90s）

Phase 0 并行预拉消除重复网络调用（修复前 K线×3/财务×2/行情×2）。

跳过: 四大师辩论、Munger 全量、T+0 深扫、行业/公司深度、
      多通道资讯、高管/政策传导链、反操纵深扫、Alpha Lens 全量。

保留轻量博弈论: GameTheoryAnalyzer + EntryExit 技术时机 → 买/卖点融合
（用户纪律: 买点卖点不能只看技术，必须看谁在定价）。
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from src.data.source_citation import make_citation

if TYPE_CHECKING:
    from src.routing.orchestrator import Orchestrator, OrchestratorResult

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# Pipeline
# ═══════════════════════════════════════════════════════════════════


def run_light(
    orch: "Orchestrator",
    *,
    symbol: str,
    market: str = "SH",
    name: str = "",
    portfolio: Optional[dict] = None,
    strategy_version: str = "",
    strategy_params: Optional[dict] = None,
) -> "OrchestratorResult":
    """持仓轻体检 — 快速、可行动、不跑重辩论。"""
    from src.output.progress import step_start, step_done, info as _info
    from src.output.step_output import (
        print_admission, print_diagnosis, print_doctrine,
        print_positioning, print_risk_control, print_verdict,
    )
    from src.routing.orchestrator import OrchestratorResult

    result = OrchestratorResult(
        symbol=symbol, name=name,
        strategy_version=strategy_version,
        strategy_params=strategy_params or {},
    )
    result.data_gaps.append("[INFO] mode=light 持仓轻体检")

    print()
    print("  ⚡ light — 持仓轻体检")
    print("  📋 Phase 0: 并行预拉 → 门禁 → 诊断 → 博弈/时机 → 裁决 → 仓位/风控")

    # ═══════════════════════════════════════════════════════════════
    # Phase 0: 并行预拉 (2路: 行情 ‖ K线+财务)
    # ═══════════════════════════════════════════════════════════════
    _info("Phase 0: 并行拉取 行情/K线/财务...")

    _quote = None
    _cross_validated = False
    _bars_df = None
    _close_series: list[float] = []
    _ma20 = None
    _ma60 = None
    _fin_list: list[dict] = []

    def _io_quote():
        nonlocal _quote, _cross_validated
        try:
            _quote = orch.data.get_quote(symbol, market)
        except Exception:
            pass
        if _quote is None:
            try:
                _quote, _cross_validated, _ = orch.data.get_cross_validated_quote(symbol, market)
            except Exception:
                _quote = None
        if _quote is None:
            _quote = orch._quote_from_cache(symbol, market)

    def _io_bars_and_fin():
        nonlocal _bars_df, _close_series, _ma20, _ma60, _fin_list
        import pandas as pd

        try:
            end = datetime.now()
            _bars_df = orch.data.get_history(
                symbol,
                start_date=(end - timedelta(days=400)).strftime("%Y%m%d"),
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
            logger.debug("light bars: %s", e)

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
            logger.debug("light financials: %s", e)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {
            pool.submit(_io_quote): "quote",
            pool.submit(_io_bars_and_fin): "bars+fin",
        }
        for f in as_completed(futures):
            try:
                f.result()
            except Exception as e:
                logger.debug("light io %s: %s", futures[f], e)

    # 兜底
    if _quote is None:
        result.passed = False
        result.blocked_by.append("数据不可用")
        print("  ⛔ 行情不可用")
        return result

    current_price = float(getattr(_quote, "price", 0) or 0)
    if not name:
        name = _quote.name or ""
        result.name = name
    result.cross_validated = _cross_validated

    quote_dict = _quote.model_dump() if hasattr(_quote, "model_dump") else (
        _quote.dict() if hasattr(_quote, "dict") else {}
    )
    quote_dict["_source"] = getattr(_quote, "source", "unknown")
    quote_dict["cross_validated"] = _cross_validated
    quote_dict["ma20"] = _ma20
    quote_dict["ma60"] = _ma60
    quote_dict["close_series"] = (_close_series[-10:] if len(_close_series) >= 10
                                  else _close_series)

    _info(f"  行情{current_price:.2f} | 日线{len(_close_series)}根 | 财务{len(_fin_list)}期")

    # ═══════════════════════════════════════════════════════════════
    # Gate: 投资者偏好 + 军规 + 准入
    # ═══════════════════════════════════════════════════════════════

    # ── 投资者偏好 ──
    investor, result.using_default_profile, result.profile_completeness, result.profile_missing = (
        orch._get_investor_prefs()
    )
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
                result.passed = False
                result.blocked_by.append(f"板块限制: {get_board_from_symbol(symbol)}")
                step_done("⛔", "板块未开通")
                return result
            position_limits = resolve_position_limits(investor)
            weights = resolve_weights(investor)
            risk_mult = resolve_macro_cap_multiplier(investor)
            enabled_rules = resolve_rule_filter(investor)
        except Exception as e:
            logger.debug("light prefs: %s", e)

    # ── 军规 ──
    step_start(1, "军规门禁")
    ctx = {"stock_name": name, **(portfolio or {})}
    cs = _close_series
    if len(cs) >= 6:
        try:
            ctx["rise_5day_pct"] = round((cs[-1] - cs[-6]) / cs[-6] * 100, 2)
        except Exception:
            ctx["rise_5day_pct"] = 0.0
    if len(cs) >= 4:
        try:
            ctx["drop_3day_pct"] = round((cs[-1] - cs[-4]) / cs[-4] * 100, 2)
        except Exception:
            pass
    try:
        orch._inject_bottom_structure_ctx(symbol, market, quote_dict, ctx)
    except Exception:
        pass
    try:
        _extract_financial_doctrine_ctx(_fin_list, ctx)
    except Exception:
        pass

    doctrine_result = orch.doctrine.check(symbol, ctx, enabled_rules=enabled_rules)
    if not doctrine_result.passed:
        result.passed = False
        result.blocked_by = [r.name for r in doctrine_result.blocked_by]
        result.warnings = [r.name for r in doctrine_result.warnings]
        step_done("⛔", f"阻断 {len(doctrine_result.blocked_by)}")
        return result
    result.warnings = [r.name for r in doctrine_result.warnings]
    result.doctrine_result = {
        "passed": True, "mode": "light",
        "warn_count": len(doctrine_result.warnings),
        "warnings": result.warnings,
        "bottom_phase": ctx.get("bottom_phase", ""),
        "bottom_ab_ratio": ctx.get("bottom_ab_ratio"),
    }
    step_done("✅", f"通过  警告:{len(result.warnings)}")
    try:
        print_doctrine(result.doctrine_result)
        if result.doctrine_result.get("bottom_phase"):
            print(
                f"  📐 底部结构: {result.doctrine_result['bottom_phase']}"
                f"  B/A={result.doctrine_result.get('bottom_ab_ratio')}"
            )
    except Exception:
        pass

    # ── 准入 (复用 Phase 0 的 quote) ──
    step_start(2, "准入检查")
    gate_ctx = {"is_limit_up": False, "is_limit_down": False, "is_suspended": False}
    if _quote:
        if getattr(_quote, "listing_date", None):
            gate_ctx["listing_date"] = _quote.listing_date
        if getattr(_quote, "turnover", None):
            gate_ctx["avg_daily_volume"] = float(_quote.turnover)
    gate_result = orch.admission.check(symbol, name, gate_ctx)
    result.gate_status = gate_result.status.value
    if gate_result.status.value == "REJECTED":
        result.passed = False
        result.blocked_by = gate_result.flags
        step_done("⛔", "准入拒绝")
        return result
    step_done("✅", "通过")
    try:
        print_admission(result.gate_status)
    except Exception:
        pass

    # ═══════════════════════════════════════════════════════════════
    # 诊断 + 技术时机 + 博弈融合 (并行本地计算)
    # ═══════════════════════════════════════════════════════════════

    # ── 轻诊断 ──
    step_start(3, "轻诊断 (价值/质量/动量)")
    report = orch.diagnosis.analyze(
        symbol, name, quote_dict, _fin_list or None,
        {}, None,  # light: 空宏观
    )
    result.report = report
    step_done("✅",
        f"价值{report.value_score:.0f} 质量{report.quality_score:.0f} "
        f"动量{report.momentum_score:.0f}")
    try:
        print_diagnosis(report)
    except Exception:
        pass

    # ── 博弈论 + 技术时机 ──
    step_start(4, "博弈论 + 买/卖点")
    from src.routing.gt_timing import fuse_timing_with_game_theory, print_gt_timing

    gt_profile = None
    try:
        mcap = getattr(_quote, "market_cap", None) or quote_dict.get("market_cap")
        gt_profile = orch.gt_analyzer.analyze(symbol, name, mcap, "")
        report.game_theory_profile = gt_profile
        result.game_theory_info = gt_profile.to_dict() if gt_profile else None
        if gt_profile and getattr(gt_profile, "source_citations", None):
            report.source_citations.extend(gt_profile.source_citations)
    except Exception as e:
        logger.debug("light gt: %s", e)

    # 技术时机 (从缓存 K线构造, 不再拉网络)
    timing_result = _build_timing_from_cache(symbol, name, _bars_df, _close_series)

    pos_snap = _load_position_row(symbol)
    held = bool(pos_snap)
    loss_pct = 0.0
    if pos_snap:
        loss_pct = _pos_loss_pct(current_price, pos_snap.get("entry_price"))

    bottom_phase = ""
    if result.doctrine_result:
        bottom_phase = str(result.doctrine_result.get("bottom_phase") or "")
    if not bottom_phase:
        bottom_phase = str(getattr(report, "bottom_phase", "") or "")

    advice = fuse_timing_with_game_theory(
        timing_result, gt_profile,
        held=held, current_price=current_price,
        position_loss_pct=loss_pct, bottom_phase=bottom_phase,
    )
    result.timing_advice = advice.to_dict() if advice else None
    step_done("✅",
        f"{advice.action if advice else '?'} "
        f"买点={'有' if (advice and advice.entry_allowed) else '无'} "
        f"玩家={advice.dominant_player if advice else '?'} "
        f"拥挤{advice.crowding_score if advice else '?'}")
    try:
        if advice:
            print_gt_timing(advice)
    except Exception:
        pass

    # ── MACD+KDJ (从缓存 K线构造) ──
    mk = _eval_macd_kdj_from_cache(symbol, _bars_df, _close_series, quote_dict)
    result.macd_kdj_signal = mk
    if mk:
        act = mk.get("action", "NONE")
        methods = ",".join(mk.get("methods") or []) or "-"
        print(
            f"  📐 MACD+KDJ五法: {act} conf={mk.get('confidence', 0):.2f} "
            f"[{methods}]"
        )
        for n in (mk.get("notes") or [])[:2]:
            print(f"     · {n}")

        if advice:
            if act == "AVOID_ENTRY" and advice.entry_allowed:
                advice.entry_allowed = False
                if advice.action == "ENTER":
                    advice.action = "WAIT"
                result.timing_advice = advice.to_dict() if hasattr(advice, "to_dict") else advice
                result.warnings.append("五法AVOID 压过技术买点 → WAIT")
            elif act == "ENTER" and not advice.entry_allowed:
                result.warnings.append(
                    f"五法进场 vs 技术分歧 — 以风控优先")
    else:
        result.data_gaps.append("[DATA_GAP] MACD+KDJ（日线不足）")

    # ═══════════════════════════════════════════════════════════════
    # 裁决 + 仓位/风控
    # ═══════════════════════════════════════════════════════════════

    step_start(5, "综合裁决")
    from src.routing.verdict import VerdictEngine

    verdict = orch.verdict_engine.judge(report, weights_override=weights, mode="trading")
    result.verdict = verdict
    if verdict.confidence < VerdictEngine.MIN_CONFIDENCE:
        result.warnings.append(f"置信度偏低 ({verdict.confidence:.2f})")

    if advice:
        if (advice.action in ("EXIT", "REDUCE")
                and verdict.recommendation in ("ADD", "BUY", "STRONG_BUY")):
            result.warnings.append("卖点优先 — 忽略裁决看多信号")
        if (advice.action == "ENTER"
                and verdict.recommendation in ("REDUCE", "SELL", "AVOID")):
            result.warnings.append("勿逆裁决追入")
            advice.entry_allowed = False
            advice.action = "WAIT"
            result.timing_advice = advice.to_dict() if hasattr(advice, "to_dict") else advice

    step_done("✅", f"评分{verdict.score:.0f} {verdict.recommendation} 置信{verdict.confidence:.0%}")
    try:
        print_verdict(verdict, None, None)
    except Exception:
        pass

    # ── 仓位 + 风控 ──
    step_start(6, "仓位调度 + 风控")
    effective_cap = 0.80 * risk_mult * float(
        getattr(advice, 'size_hint', 1.0) if advice else 1.0
    )
    signal = orch.positioning.generate_signal(
        verdict,
        macro_cap=effective_cap,
        position_limits=position_limits,
        risk_multiplier=risk_mult * float(
            getattr(advice, 'size_hint', 1.0) if advice else 1.0
        ),
        name=name,
        extra=quote_dict,
        timing_result=timing_result,
    )

    if held and advice and advice.action in ("EXIT", "REDUCE"):
        try:
            signal.action = "CLOSE" if advice.action == "EXIT" else "REDUCE"  # type: ignore[attr-defined]
            if advice.action == "EXIT":
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

    result.signal = signal
    result.sizing_detail = {
        "method": getattr(signal, "sizing_method", "light"),
        "macro_cap": effective_cap,
        "risk_multiplier": risk_mult,
        "size_hint": getattr(advice, 'size_hint', 1.0) if advice else 1.0,
        "timing_action": getattr(advice, 'action', '?') if advice else '?',
        "mode": "light",
    }

    enriched = dict(portfolio or {})
    if pos_snap:
        enriched.update({
            "current_price": current_price,
            "entry_price": pos_snap.get("entry_price"),
            "stop_price": pos_stop or pos_snap.get("stop_price"),
            "quantity": pos_snap.get("quantity"),
            "position_loss_pct": loss_pct,
            "held": True,
        })
    else:
        enriched["held"] = False
        enriched["current_price"] = current_price
    if gt_profile:
        enriched["game_theory_risks"] = list(getattr(gt_profile, "risks", []) or [])
        enriched["dominant_player"] = getattr(gt_profile, "dominant_player", "")
    if advice:
        enriched["timing_action"] = advice.action
        enriched["exit_urgency"] = advice.exit_urgency

    risk = orch.risk_ctrl.check(
        signal,
        market={"change_pct": getattr(_quote, "change_pct", 0)},
        portfolio=enriched,
        position_limits=position_limits,
    )
    result.risk = risk
    step_done("✅",
        f"动作{getattr(signal, 'action', '?')} "
        f"权重{getattr(signal, 'weight', 0):.1%} "
        f"风控{'PASS' if getattr(risk, 'passed', True) else '⚠️'}")
    try:
        print_positioning(signal, result.sizing_detail)
        print_risk_control(risk)
    except Exception:
        pass

    # ── 摘要 ──
    print("\n" + "=" * 50)
    print("  ⚡ light 体检完成")
    print(f"  标的: {name} {symbol}  价 {current_price:.2f}")
    print(f"  裁决: {verdict.score:.0f}/100  {verdict.recommendation}  置信{verdict.confidence:.0%}")
    print(f"  信号: {getattr(signal, 'action', '-')}  仓位 {getattr(signal, 'weight', 0):.1%}")
    if advice:
        print(f"  买点: {advice.buy_point}")
        print(f"  卖点: {advice.sell_point}")
    if mk:
        print(f"  五法: {mk.get('action')} c={mk.get('confidence', 0):.2f}")
    if result.warnings:
        print(f"  ⚠️  {', '.join(result.warnings[:5])}")
    print("  深挖: python -m src diagnose <code> 或 tactics <code>")
    print("=" * 50)

    report.source_citations.append(make_citation(
        provider="light_pipeline", field="mode_light",
        data_type="analyst_report", source_tier="T2", nature="interpretation",
        confidence=min(0.75, float(verdict.confidence or 0.5)),
    ))
    result.passed = True
    return result


# ═══════════════════════════════════════════════════════════════════
# Helpers (缓存版 — 不再单独拉网络)
# ═══════════════════════════════════════════════════════════════════


def _build_timing_from_cache(
    symbol: str, name: str, bars_df, close_series: list[float],
):
    """从缓存 K线构造 TimingResult，不再拉网络。"""
    try:
        import pandas as pd
        from src.routing.entry_exit_engine import EntryExitEngine

        if bars_df is not None and not getattr(bars_df, "empty", True) and len(bars_df) >= 20:
            c = bars_df["close"] if "close" in bars_df.columns else None
            if c is None:
                return None
            h = bars_df["high"] if "high" in bars_df.columns else c
            l = bars_df["low"] if "low" in bars_df.columns else c
            v = bars_df["volume"] if "volume" in bars_df.columns else pd.Series([1e6] * len(c))
            panel = {
                "close": pd.DataFrame({symbol: c.values}, index=c.index),
                "high": pd.DataFrame({symbol: h.values}, index=h.index),
                "low": pd.DataFrame({symbol: l.values}, index=l.index),
                "volume": pd.DataFrame({symbol: v.values}, index=v.index),
            }
            return EntryExitEngine().evaluate(symbol, name, panel)

        # fallback: close_series only
        if len(close_series) < 20:
            return None
        close = pd.DataFrame({symbol: close_series})
        panel = {
            "close": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "volume": pd.DataFrame({symbol: [1e6] * len(close_series)}),
        }
        return EntryExitEngine().evaluate(symbol, name, panel)
    except Exception as e:
        logger.debug("light timing from cache: %s", e)
        return None


def _eval_macd_kdj_from_cache(
    symbol: str, bars_df, close_series: list[float], quote_dict: dict,
) -> Optional[dict]:
    """从缓存 K线计算 MACD+KDJ，不再拉网络。"""
    try:
        import pandas as pd
        from src.alphas.macd_kdj import evaluate_ohlc_latest, normalize_ohlc_df, load_kline_cache

        df = None
        if bars_df is not None and not getattr(bars_df, "empty", True):
            df = normalize_ohlc_df(bars_df)

        if df is None or len(df) < 40:
            df = load_kline_cache(symbol)

        if df is None or len(df) < 40:
            if len(close_series) >= 40:
                c = pd.Series(close_series, dtype=float)
                df = pd.DataFrame(
                    {"close": c, "high": c * 1.01, "low": c * 0.99, "open": c}
                )

        if df is not None and not df.empty:
            px = float(quote_dict.get("price") or quote_dict.get("close") or 0)
            if px > 0 and "close" in df.columns:
                last = float(df["close"].iloc[-1])
                if abs(last - px) / max(px, 1e-9) > 0.001:
                    df = df.copy()
                    df.loc[df.index[-1], "close"] = px

        return evaluate_ohlc_latest(df) if df is not None else None
    except Exception as e:
        logger.debug("light macd_kdj from cache: %s", e)
        return None


def _extract_financial_doctrine_ctx(fin_list: list[dict], ctx: dict) -> None:
    """从缓存财务数据提取军规上下文，替换 _inject_financial_doctrine_ctx 的网络调用。"""
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


def _load_position_row(symbol: str) -> Optional[dict]:
    for p in [Path("data/positions.json"),
              Path.home() / ".hermes" / "baize" / "positions.json"]:
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
