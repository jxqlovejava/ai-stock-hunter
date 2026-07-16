# -*- coding: utf-8 -*-
"""持仓轻体检 Pipeline（mode=light）。

三档体系:
  sentinel  — Hermes cron，仅规则+报价（秒级）
  light     — 本模块：行情+军规+准入+轻诊断+裁决+轻仓位/风控（十秒级）
  daily/full— orchestrator 全链路（几十秒～分钟）

跳过: 四大师辩论、Munger 全量、T+0 深扫、行业/公司深度、
      多通道资讯、高管/政策传导链、反操纵深扫、Alpha Lens 全量。

保留轻量博弈论: GameTheoryAnalyzer + EntryExit 技术时机 → 买/卖点融合
（用户纪律: 买点卖点不能只看技术，必须看谁在定价）。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from src.data.source_citation import make_citation, make_data_gap_citation

if TYPE_CHECKING:
    from src.routing.orchestrator import Orchestrator, OrchestratorResult

logger = logging.getLogger(__name__)


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
    from src.output.progress import step_start, step_done
    from src.output.step_output import (
        print_admission,
        print_diagnosis,
        print_doctrine,
        print_positioning,
        print_risk_control,
        print_verdict,
    )
    from src.routing.orchestrator import OrchestratorResult

    result = OrchestratorResult(
        symbol=symbol,
        name=name,
        strategy_version=strategy_version,
        strategy_params=strategy_params or {},
    )
    result.data_gaps.append("[INFO] mode=light 持仓轻体检（跳过辩论/T+0/深度研究）")

    print()
    print("  ⚡ 分析模式: light（持仓轻体检）")
    print("  📋 管道: 行情 → 军规 → 准入 → 轻诊断 → 博弈/时机 → 裁决 → 仓位/风控")

    # ── 1. 行情（优先单源快路径，失败再双源）──
    step_start(1, "行情获取 (light)")
    quote = None
    cross_validated = False
    try:
        quote = orch.data.get_quote(symbol, market)
    except Exception as e:
        logger.debug("light get_quote failed: %s", e)
    if quote is None:
        try:
            quote, cross_validated, _ = orch.data.get_cross_validated_quote(symbol, market)
        except Exception:
            quote = None
    if quote is None:
        quote = orch._quote_from_cache(symbol, market)
        if quote is None:
            result.passed = False
            result.blocked_by.append("数据不可用")
            step_done("⛔", "行情不可用")
            return result
    if not name:
        name = quote.name or ""
        result.name = name
    result.cross_validated = cross_validated
    quote_dict = quote.model_dump() if hasattr(quote, "model_dump") else (
        quote.dict() if hasattr(quote, "dict") else {}
    )
    quote_dict["_source"] = getattr(quote, "source", "unknown")
    quote_dict["cross_validated"] = cross_validated
    try:
        orch._inject_ma_data(symbol, quote_dict)
    except Exception:
        pass
    # 持仓日线（供底部结构）
    try:
        bars = None
        if hasattr(orch.data, "get_daily_bars"):
            bars = orch.data.get_daily_bars(symbol, market, count=90)
        if bars:
            quote_dict["daily_bars"] = bars
    except Exception:
        pass
    step_done("✅", f"价格 {getattr(quote, 'price', 0):.2f}"
              f"  {'双源' if cross_validated else '单源'}")

    # ── 2. 投资者偏好 + 军规 ──
    step_start(2, "军规门禁 (light)")
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
                resolve_weights,
                resolve_rule_filter,
                resolve_position_limits,
                resolve_macro_cap_multiplier,
                is_board_accessible,
            )
            from src.learner.preference.model import get_board_from_symbol

            if not is_board_accessible(investor, symbol):
                board = get_board_from_symbol(symbol)
                result.passed = False
                result.blocked_by.append(f"板块限制: {board}")
                step_done("⛔", "板块未开通")
                return result
            position_limits = resolve_position_limits(investor)
            weights = resolve_weights(investor)
            risk_mult = resolve_macro_cap_multiplier(investor)
            enabled_rules = resolve_rule_filter(investor)
        except Exception as e:
            logger.debug("light prefs resolve: %s", e)

    ctx = {"stock_name": name, **(portfolio or {})}
    close_series = quote_dict.get("close_series") or []
    if len(close_series) >= 6:
        try:
            ctx["rise_5day_pct"] = round(
                (close_series[-1] - close_series[-6]) / close_series[-6] * 100.0, 2
            )
        except Exception:
            ctx["rise_5day_pct"] = 0.0
    if len(close_series) >= 4:
        try:
            ctx["drop_3day_pct"] = round(
                (close_series[-1] - close_series[-4]) / close_series[-4] * 100.0, 2
            )
        except Exception:
            pass
    try:
        orch._inject_bottom_structure_ctx(symbol, market, quote_dict, ctx)
    except Exception:
        pass
    try:
        orch._inject_financial_doctrine_ctx(symbol, market, ctx)
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
        "passed": True,
        "mode": "light",
        "warn_count": len(doctrine_result.warnings),
        "warnings": result.warnings,
        "bottom_phase": ctx.get("bottom_phase", ""),
        "bottom_ab_ratio": ctx.get("bottom_ab_ratio"),
    }
    step_done("✅", f"通过  警告:{len(result.warnings)}")
    if result.doctrine_result.get("bottom_phase"):
        print(
            f"  📐 底部结构: {result.doctrine_result['bottom_phase']}"
            f"  B/A={result.doctrine_result.get('bottom_ab_ratio')}"
        )
    try:
        print_doctrine(result.doctrine_result)
    except Exception:
        pass

    # ── 3. 准入 ──
    step_start(3, "准入检查 (light)")
    gate_ctx = {"is_limit_up": False, "is_limit_down": False, "is_suspended": False}
    try:
        q = orch.data.get_quote(symbol, market)
        if q:
            if getattr(q, "listing_date", None):
                gate_ctx["listing_date"] = q.listing_date
            if getattr(q, "turnover", None):
                gate_ctx["avg_daily_volume"] = float(q.turnover)
    except Exception:
        pass
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

    # ── 4. 轻诊断（最小数据）──
    step_start(4, "轻诊断 (价值/质量/动量子集)")
    fin_list: list = []
    try:
        fins = orch.data.get_financials(symbol, market, count=4)
        fin_list = [f.model_dump() if hasattr(f, "model_dump") else dict(f) for f in (fins or [])]
    except Exception:
        result.data_gaps.append("[DATA_GAP] 财务简表")
    report = orch.diagnosis.analyze(
        symbol, name,
        quote_dict,
        fin_list or None,
        {},  # light: 不拉宏观全量，诊断侧用默认分
        None,
    )
    result.report = report
    scores = (
        f"宏观{report.macro_score:.0f} 价值{report.value_score:.0f} "
        f"质量{report.quality_score:.0f} 动量{report.momentum_score:.0f}"
    )
    step_done("✅", scores)
    if getattr(report, "bottom_phase", ""):
        print(
            f"  📐 诊断底部结构: {report.bottom_phase} "
            f"分{getattr(report, 'bottom_structure_score', 50):.0f}"
        )
    try:
        print_diagnosis(report)
    except Exception:
        pass

    # ── 5. 博弈论 + 技术时机 → 买/卖点 ──
    step_start(5, "博弈论 + 买/卖点")
    from src.routing.gt_timing import fuse_timing_with_game_theory, print_gt_timing

    gt_profile = None
    try:
        mcap = getattr(quote, "market_cap", None) or quote_dict.get("market_cap")
        gt_profile = orch.gt_analyzer.analyze(symbol, name, mcap, "")
        report.game_theory_profile = gt_profile
        result.game_theory_info = gt_profile.to_dict() if gt_profile else None
        if gt_profile and getattr(gt_profile, "source_citations", None):
            report.source_citations.extend(gt_profile.source_citations)
    except Exception as e:
        logger.debug("light game_theory failed: %s", e)
        result.data_gaps.append("[DATA_GAP] 博弈论轻扫失败")

    timing_result = _build_timing(orch, symbol, name, quote_dict)
    pos_snap = _load_position_row(symbol)
    held = bool(pos_snap)
    loss_pct = 0.0
    if pos_snap:
        loss_pct = _pos_loss_pct(getattr(quote, "price", 0), pos_snap.get("entry_price"))

    bottom_phase = ""
    if result.doctrine_result:
        bottom_phase = str(result.doctrine_result.get("bottom_phase") or "")
    if not bottom_phase:
        bottom_phase = str(getattr(report, "bottom_phase", "") or "")

    advice = fuse_timing_with_game_theory(
        timing_result,
        gt_profile,
        held=held,
        current_price=float(getattr(quote, "price", 0) or 0),
        position_loss_pct=loss_pct,
        bottom_phase=bottom_phase,
    )
    result.timing_advice = advice.to_dict()
    step_done(
        "✅",
        f"{advice.action} 买点={'有' if advice.entry_allowed else '无'} "
        f"玩家={advice.dominant_player or '?'} 拥挤{advice.crowding_score}",
    )
    try:
        print_gt_timing(advice)
    except Exception:
        pass

    # ── 5b. MACD+KDJ 五法（教学规则，辅助）──
    mk = _eval_macd_kdj(orch, symbol, quote_dict)
    result.macd_kdj_signal = mk
    if mk:
        act = mk.get("action", "NONE")
        methods = ",".join(mk.get("methods") or []) or "-"
        print(
            f"  📐 MACD+KDJ五法: {act} conf={mk.get('confidence', 0):.2f} "
            f"[{methods}] DIF={mk.get('dif')} DEA={mk.get('dea')} "
            f"K={mk.get('k')} D={mk.get('d')}"
        )
        for n in (mk.get("notes") or [])[:3]:
            print(f"     · {n}")
        # 与 timing 交叉提示
        if act == "EXIT" and held:
            result.warnings.append("MACD+KDJ五法: 离场候选 — 对照止损/卖点纪律")
            if advice.action in ("ENTER", "HOLD", "WAIT"):
                result.warnings.append(
                    f"五法EXIT 与 timing({advice.action}) 分歧 — 持仓优先风控"
                )
        elif act == "AVOID_ENTRY" and not held:
            result.warnings.append("MACD+KDJ五法: 0轴下假反弹，勿轻易进场")
            if advice.entry_allowed:
                advice.entry_allowed = False
                if advice.action == "ENTER":
                    advice.action = "WAIT"
                result.timing_advice = advice.to_dict()
                result.warnings.append("五法AVOID 压过技术买点 → 改为 WAIT")
        elif act == "ENTER" and not held:
            result.warnings.append(
                f"MACD+KDJ五法进场候选 conf≤{mk.get('confidence', 0):.2f} — 仍须过裁决/风控"
            )
        elif act == "HOLD" and held:
            result.warnings.append("MACD+KDJ五法: 洗盘后持股候选 — 勿因短线死叉恐慌")
    else:
        result.data_gaps.append("[DATA_GAP] MACD+KDJ五法（日线不足或不可用）")

    # ── 6. 轻裁决（含博弈乘数）──
    step_start(6, "综合裁决 (light)")
    from src.routing.verdict import VerdictEngine

    verdict = orch.verdict_engine.judge(report, weights_override=weights, mode="trading")
    result.verdict = verdict
    if verdict.confidence < VerdictEngine.MIN_CONFIDENCE:
        result.warnings.append(
            f"置信度偏低 ({verdict.confidence:.2f}) — light 模式仅提示不阻断"
        )
    # 买/卖点与裁决交叉提示
    if advice.action in ("EXIT", "REDUCE") and verdict.recommendation in ("ADD", "BUY", "STRONG_BUY"):
        result.warnings.append(
            f"博弈卖点({advice.action}) 与裁决({verdict.recommendation}) 冲突 — 以卖点纪律优先"
        )
    if advice.action == "ENTER" and verdict.recommendation in ("REDUCE", "SELL", "AVOID"):
        result.warnings.append(
            f"技术买点与裁决({verdict.recommendation}) 冲突 — 勿逆裁决追入"
        )
        advice.entry_allowed = False
        advice.action = "WAIT"
        result.timing_advice = advice.to_dict()
    step_done("✅", f"评分{verdict.score:.0f} {verdict.recommendation} 置信{verdict.confidence:.0%}")
    try:
        print_verdict(verdict, None, None)
    except Exception:
        pass

    # ── 7. 仓位 + 风控（轻，叠加 size_hint / timing）──
    step_start(7, "仓位调度 + 风控 (light)")
    effective_macro_cap = 0.80 * risk_mult * float(advice.size_hint or 1.0)
    signal = orch.positioning.generate_signal(
        verdict,
        macro_cap=effective_macro_cap,
        position_limits=position_limits,
        risk_multiplier=risk_mult * float(advice.size_hint or 1.0),
        name=name,
        extra=quote_dict,
        timing_result=timing_result,
    )
    # 持仓卖点纪律：EXIT/REDUCE 覆盖动作（TradeSignal: OPEN/ADD/HOLD/REDUCE/CLOSE）
    if held and advice.action in ("EXIT", "REDUCE"):
        mapped = "CLOSE" if advice.action == "EXIT" else "REDUCE"
        try:
            signal.action = mapped  # type: ignore[attr-defined]
            if advice.action == "EXIT":
                if hasattr(signal, "weight"):
                    signal.weight = 0.0  # type: ignore[attr-defined]
                if hasattr(signal, "target_weight"):
                    signal.target_weight = 0.0  # type: ignore[attr-defined]
        except Exception as e:
            logger.debug("override signal action failed: %s", e)

    # 持仓止损统一：positions.json 覆盖 timing ATR 建议止损
    pos_stop = None
    if pos_snap:
        try:
            pos_stop = float(pos_snap.get("stop_price") or 0) or None
        except (TypeError, ValueError):
            pos_stop = None
    if held and pos_stop and pos_stop > 0:
        timing_stop = float(getattr(signal, "suggested_stop", 0) or 0)
        try:
            signal.suggested_stop = pos_stop  # type: ignore[attr-defined]
            # 保留 timing 值作参考，避免误导为「ATR 重算」
            if hasattr(signal, "atr_stop") and timing_stop > 0:
                signal.atr_stop = timing_stop  # type: ignore[attr-defined]
            if hasattr(signal, "extra") and isinstance(getattr(signal, "extra", None), dict):
                signal.extra = {
                    **(signal.extra or {}),
                    "stop_source": "positions.json",
                    "timing_suggested_stop": timing_stop,
                    "position_stop": pos_stop,
                }
        except Exception as e:
            logger.debug("override suggested_stop from positions failed: %s", e)

    result.signal = signal
    result.sizing_detail = {
        "method": getattr(signal, "sizing_method", "light"),
        "macro_cap": effective_macro_cap,
        "risk_multiplier": risk_mult,
        "size_hint": advice.size_hint,
        "timing_action": advice.action,
        "mode": "light",
        "stop_source": "positions.json" if (held and pos_stop) else "timing",
        "position_stop": pos_stop,
    }

    # 合并持仓文件到 portfolio，供风控读止损/现价
    enriched = dict(portfolio or {})
    if pos_snap:
        enriched.update({
            "current_price": getattr(quote, "price", 0),
            "entry_price": pos_snap.get("entry_price"),
            "stop_price": pos_stop or pos_snap.get("stop_price"),
            "quantity": pos_snap.get("quantity"),
            "position_loss_pct": loss_pct,
            "held": True,
            "peak_price": pos_snap.get("high_price"),
        })
        timing_stop_show = float(getattr(signal, "atr_stop", 0) or 0)
        print(
            f"  📦 持仓: 成本{pos_snap.get('entry_price')} "
            f"止损{pos_stop or pos_snap.get('stop_price')} "
            f"(源=positions.json"
            f"{f', timing参考{timing_stop_show:.2f}' if timing_stop_show > 0 else ''}"
            f") 数量{pos_snap.get('quantity')}"
        )
    else:
        enriched["held"] = False
        enriched["current_price"] = getattr(quote, "price", 0)

    if gt_profile:
        enriched["game_theory_risks"] = list(getattr(gt_profile, "risks", None) or [])
        enriched["dominant_player"] = getattr(gt_profile, "dominant_player", "")
        enriched["market_regime"] = getattr(gt_profile, "market_regime", "")
    enriched["timing_action"] = advice.action
    enriched["exit_urgency"] = advice.exit_urgency

    risk = orch.risk_ctrl.check(
        signal,
        market={"change_pct": getattr(quote, "change_pct", 0)},
        portfolio=enriched,
        position_limits=position_limits,
    )
    result.risk = risk
    step_done(
        "✅",
        f"动作{getattr(signal, 'action', '?')} "
        f"权重{getattr(signal, 'weight', 0):.1%} "
        f"风控{getattr(risk, 'status', getattr(risk, 'action', '?'))}",
    )
    try:
        print_positioning(signal, result.sizing_detail)
        print_risk_control(risk)
    except Exception:
        pass

    # ── 8. 摘要 ──
    print("\n" + "=" * 50)
    print("  ⚡ light 体检完成（非全链路）")
    print(f"  标的: {name} {symbol}  价 {getattr(quote, 'price', 0):.2f}")
    print(f"  裁决: {verdict.score:.0f}/100  {verdict.recommendation}  置信{verdict.confidence:.0%}")
    print(f"  信号: {getattr(signal, 'action', '-')}  建议仓位 {getattr(signal, 'weight', 0):.1%}")
    print(f"  买点: {advice.buy_point}")
    print(f"  卖点: {advice.sell_point}")
    if result.macd_kdj_signal:
        mk = result.macd_kdj_signal
        print(
            f"  五法: {mk.get('action')} conf={mk.get('confidence', 0):.2f} "
            f"methods={','.join(mk.get('methods') or []) or '-'}"
        )
    if result.warnings:
        print(f"  警告: {', '.join(result.warnings[:5])}")
    if result.data_gaps:
        print(f"  说明: {result.data_gaps[0]}")
    print("  深挖: python -m src diagnose <代码>   或  analyze --deep")
    print("=" * 50)

    report.source_citations.append(make_citation(
        provider="light_pipeline",
        field="mode_light",
        data_type="analyst_report",
        source_tier="T2",
        nature="interpretation",
        confidence=min(0.75, float(verdict.confidence or 0.5)),
    ))
    result.passed = True
    return result


def _build_timing(orch, symbol: str, name: str, quote_dict: dict):
    """从日线历史构造 EntryExit TimingResult；失败返回 None。"""
    try:
        import pandas as pd
        from datetime import datetime, timedelta
        from src.routing.entry_exit_engine import EntryExitEngine

        end = datetime.now()
        start = (end - timedelta(days=180)).strftime("%Y%m%d")
        bars = orch.data.get_history(
            symbol, start_date=start, end_date=end.strftime("%Y%m%d"), period="daily"
        )
        if bars is None or getattr(bars, "empty", True):
            # fallback: close_series only → synthetic flat OHLC
            series = quote_dict.get("close_series") or []
            if len(series) < 20:
                return None
            close = pd.DataFrame({symbol: series})
            panel = {
                "close": close,
                "high": close * 1.01,
                "low": close * 0.99,
                "volume": pd.DataFrame({symbol: [1e6] * len(series)}),
            }
            return EntryExitEngine().evaluate(symbol, name, panel)

        def _col(name_en: str, name_cn: str):
            if name_en in bars.columns:
                return bars[name_en]
            if name_cn in bars.columns:
                return bars[name_cn]
            return None

        c = _col("close", "收盘")
        h = _col("high", "最高")
        l = _col("low", "最低")
        v = _col("volume", "成交量")
        if c is None:
            return None
        if h is None:
            h = c
        if l is None:
            l = c
        if v is None:
            v = c * 0 + 1e6
        panel = {
            "close": pd.DataFrame({symbol: c.values}, index=c.index),
            "high": pd.DataFrame({symbol: h.values}, index=h.index),
            "low": pd.DataFrame({symbol: l.values}, index=l.index),
            "volume": pd.DataFrame({symbol: v.values}, index=v.index),
        }
        return EntryExitEngine().evaluate(symbol, name, panel)
    except Exception as e:
        logger.debug("light timing build failed: %s", e)
        return None


def _load_position_row(symbol: str) -> Optional[dict]:
    candidates = [
        Path("data/positions.json"),
        Path.home() / ".hermes" / "baize" / "positions.json",
    ]
    for p in candidates:
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
    """浮盈亏比例（ratio），与 risk_control / mental_model 一致。

    例: 现价 90、成本 100 → -0.1（非 -10.0）。
    风控侧用 ``.1%`` 格式化为百分比展示。
    """
    try:
        e = float(entry or 0)
    except (TypeError, ValueError):
        return 0.0
    if e <= 0 or price <= 0:
        return 0.0
    return (float(price) - e) / e


def _eval_macd_kdj(orch, symbol: str, quote_dict: dict) -> Optional[dict]:
    """计算 MACD+KDJ 五法最新状态。优先 get_history，回退 kline_cache / close_series。"""
    try:
        import pandas as pd
        from datetime import datetime, timedelta
        from src.alphas.macd_kdj import (
            evaluate_ohlc_latest,
            load_kline_cache,
            normalize_ohlc_df,
        )

        df = None
        try:
            end = datetime.now()
            start = (end - timedelta(days=400)).strftime("%Y-%m-%d")
            hist = orch.data.get_history(
                symbol,
                start_date=start,
                end_date=end.strftime("%Y-%m-%d"),
                period="daily",
            )
            if hist is not None and not getattr(hist, "empty", True):
                df = normalize_ohlc_df(hist)
        except Exception as e:
            logger.debug("light macd_kdj history: %s", e)

        if df is None or len(df) < 40:
            df = load_kline_cache(symbol)

        if df is None or len(df) < 40:
            series = quote_dict.get("close_series") or []
            if len(series) >= 40:
                c = pd.Series(series, dtype=float)
                df = pd.DataFrame(
                    {
                        "close": c,
                        "high": c * 1.01,
                        "low": c * 0.99,
                        "open": c,
                    }
                )

        # 合并当日 quote 收盘价（若历史最后一根早于今日）
        if df is not None and not df.empty:
            px = float(quote_dict.get("price") or quote_dict.get("close") or 0)
            if px > 0 and "close" in df.columns:
                last = float(df["close"].iloc[-1])
                if abs(last - px) / max(px, 1e-9) > 0.001:
                    # 仅更新最后一根 close，避免伪造整根 K
                    df = df.copy()
                    df.loc[df.index[-1], "close"] = px

        return evaluate_ohlc_latest(df) if df is not None else None
    except Exception as e:
        logger.debug("light macd_kdj failed: %s", e)
        return None
