# -*- coding: utf-8 -*-
"""CLI 统一入口 — 白泽 (Baize) A 股智能投资决策系统。

用法:
  python -m src scan [--preset value]         # 全市场选股扫描
  python -m src analyze <code>                # 单只股票全链路分析
  python -m src diagnose <code>               # 一键诊断（小白入口）
  python -m src alpha <code>                  # Alpha Lens 三维评估
  python -m src alpha-scan [--limit N]        # 高 Alpha 股票扫描
  python -m src alpha-decay <code>            # Alpha 衰减追踪
  python -m src macro                         # 宏观快照
  python -m src sentiment                     # 情绪信号检测
  python -m src backtest                      # 运行回测
  python -m src backtest-optimize             # 参数优化
  python -m src backtest-compare              # 多策略对比
  python -m src game-theory                   # 博弈论知识摘要
  python -m src calibrate                     # 置信度校准报告
  python -m src profile                       # 用户能力画像
  python -m src preference <view|setup|edit|reset>  # 投资者偏好管理
  python -m src feedback <add|summary>        # 交易反馈
  python -m src learn report                  # 生成学习报告
  python -m src search-news <query>           # 金融资讯搜索
  python -m src screen <conditions>           # 条件选股
  python -m src related <symbol>              # 关联关系查询
  python -m src paper-trade <action>          # 模拟交易管理
  python -m src poster --title --text         # AI 社区发帖
  python -m src evolution <sub>               # 策略进化（论文驱动）
  python -m src trade-track <add|list|kelly>  # 交易追踪（凯利公式）

数据源: mootdx+腾讯 > 国信 > AKShare. 设置 MX_APIKEY 以启用妙想API.
"""

from __future__ import annotations

import functools
import logging
import os
import re
import sys
import traceback
from datetime import datetime
from typing import Any, Callable

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# 工具函数
# ------------------------------------------------------------------

def _import_or_none(module_path: str, name: str) -> Any:
    """安全延迟导入 — 失败返回 None 而非崩溃。"""
    try:
        mod = __import__(module_path, fromlist=[name])
        return getattr(mod, name)
    except Exception as e:
        logger.debug("无法导入 %s.%s: %s", module_path, name, e)
        return None


def _validate_symbol(symbol: str, silent: bool = False) -> bool:
    """验证 A 股股票代码格式 (6 位数字) / Validate A-share stock code (6 digits)."""
    if not re.match(r"^\d{6}$", symbol):
        if not silent:
            print(f"❌ 无效股票代码 / Invalid code: {symbol} (需要 6 位数字 / need 6 digits, e.g. 600519)")
        return False
    return True


def _infer_market(symbol: str) -> str:
    """根据股票代码前缀推断市场 / Infer market from stock code prefix."""
    if symbol.startswith(("600", "601", "603", "605", "688")):
        return "SH"
    return "SZ"


def _safe_cmd(func: Callable) -> Callable:
    """统一错误处理 — 捕获异常并打印双语消息 / Unified error handler with bilingual messages."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except ImportError as e:
            print(f"⚠️ 缺少依赖 / Missing dependency: {e}")
            print("   请运行 / Run: pip install -r requirements.txt")
        except Exception as e:
            print(f"❌ 错误 / Error: {e}")
            if os.environ.get("DEBUG"):
                traceback.print_exc()
            else:
                print("   (设置 DEBUG=1 查看详细信息 / Set DEBUG=1 for full traceback)")

    return wrapper


def _run_command(handler: Callable) -> Callable:
    """包装命令函数，添加股票代码验证和错误处理。"""
    return _safe_cmd(handler)


@_safe_cmd
def cmd_scan(args: list[str]):
    """全市场选股扫描。"""
    import argparse
    from src.data.aggregator import DataAggregator
    from src.routing.diagnosis import DiagnosisEngine, SCREENING_PRESETS

    parser = argparse.ArgumentParser(description="全市场选股扫描")
    parser.add_argument(
        "--preset", choices=list(SCREENING_PRESETS.keys()),
        default="value", help="选股方法论预设"
    )
    parser.add_argument("--limit", type=int, default=20, help="返回数量上限")
    parsed = parser.parse_args(args)

    preset = SCREENING_PRESETS[parsed.preset]
    print(f"🔍 全市场选股扫描 [{preset.name}]: {preset.description}")
    print(f"A 股适配规则: {', '.join(preset.adapters[:3])}...")
    print(f"权重配置: {preset.weight_overrides}")
    print(f"阈值配置: {preset.thresholds}")

    agg = DataAggregator()
    status = agg.source_status()
    print(f"数据源: {status}")

    stocks = agg.scan_all_stocks() or []

    # ── 板块过滤 (P0) ──
    # 根据投资者画像中的 accessible_boards 预过滤不可交易板块，
    # 避免对 300xxx/688xxx/8xxxxx 等未开通板块浪费诊断算力。
    board_filtered = 0
    try:
        from src.learner.preference.loader import InvestorPreferenceLoader
        from src.learner.preference.adapter import resolve_board_filter
        loader = InvestorPreferenceLoader()
        board_ok = resolve_board_filter(loader.load())
        filtered = []
        for s in stocks:
            symbol = s.get("symbol", "") if isinstance(s, dict) else getattr(s, "symbol", "")
            if not symbol or board_ok(symbol):
                filtered.append(s)
            else:
                board_filtered += 1
        if board_filtered:
            accessible = loader.load().accessible_boards
            print(f"🔒 板块过滤: 排除 {board_filtered} 只不可交易板块标的 "
                  f"(仅保留 {[b.value for b in accessible]})")
        stocks = filtered
    except Exception:
        pass  # 画像加载失败时不过滤，照常扫描

    # ── 行业过滤 (能力圈) ──
    # 根据投资者能力圈中的行业关键词，映射到东财行业板块成分股，
    # 仅保留能力圈内的标的。familiarity=0 的行业不参与筛选。
    sector_filtered = 0
    try:
        from src.learner.preference.sector_filter import build_competence_symbol_set
        coc = loader.load().circle_of_competence.industries
        competence_symbols = build_competence_symbol_set(coc)
        if competence_symbols is not None:
            before = len(stocks)
            filtered = []
            for s in stocks:
                symbol = s.get("symbol", "") if isinstance(s, dict) else getattr(s, "symbol", "")
                if symbol in competence_symbols:
                    filtered.append(s)
                else:
                    sector_filtered += 1
            stocks = filtered
            if sector_filtered:
                coc_names = [k for k, v in coc.items() if v > 0]
                print(
                    f"🎯 能力圈过滤: {before} → {len(stocks)} 只 "
                    f"(能力圈: {coc_names})"
                )
    except Exception:
        pass  # 行业过滤失败时不过滤，照常扫描

    print(f"扫描范围: {len(stocks)} 只股票")

    if not stocks:
        print("⚠️ 无可用股票数据")
        return

    analyzer = DiagnosisEngine()
    results = analyzer.screen_by_preset(parsed.preset, stocks, limit=parsed.limit)
    if not results:
        print("⚠️ 无股票通过筛选")
        return

    print(f"\n🏆 前 {len(results)} 名:")
    for rank, (symbol, report, score) in enumerate(results, 1):
        print(
            f"  {rank:2d}. {symbol} {report.name:<8s} "
            f"综合 {score:.1f} | "
            f"价值 {report.value_score:.0f} 质量 {report.quality_score:.0f} "
            f"动量 {report.momentum_score:.0f} 宏观 {report.macro_score:.0f} | "
            f"信心度 {report.confidence:.2f}"
        )


@_safe_cmd
def cmd_analyze(args: list[str]):
    """单只股票全链路分析。"""
    import argparse
    parser = argparse.ArgumentParser(description="单只股票全链路分析")
    parser.add_argument("symbol", help="股票代码")
    parser.add_argument("--deep", action="store_true", help="深度模式（含行业+公司深度研究）")
    parser.add_argument("--no-t0", action="store_true", dest="no_t0", help="跳过 T+0 日内时机分析（Alpha/中长期机会搜索时推荐）")
    parser.add_argument("--event", type=str, default="", help="当日重大宏观事件描述（如: 美联储加息50bp）")
    parser.add_argument("--event-category", type=str, default="", help="事件类型: monetary/geopolitical/trade_policy/tech_sanction/financial_crisis/commodity")
    parsed = parser.parse_args(args)

    symbol = parsed.symbol
    if not _validate_symbol(symbol):
        return
    from src.routing.orchestrator import Orchestrator

    mode = "full" if parsed.deep else "daily"
    orch = Orchestrator()
    result = orch.run(
        symbol, market=_infer_market(symbol), mode=mode,
        macro_event_desc=parsed.event,
        macro_event_category=parsed.event_category,
        skip_t0=parsed.no_t0,
    )

    if not result.passed:
        print(f"⛔ 不通过: {', '.join(result.blocked_by)}")
        if result.warnings:
            print(f"⚠️  警告: {', '.join(result.warnings)}")
        return
    # 生成投资备忘录
    try:
        from src.reporting.memo_renderer import MemoRenderer
        memo = MemoRenderer()
        memo_ctx = memo.render(result) if hasattr(memo, "render") else None
        if memo_ctx:
            print(f"\n📝 投资备忘录已生成")
    except Exception:
        pass  # memo 渲染失败不影响主流程


def cmd_macro():
    """宏观快照 — 货币信用象限 + 三大根本问题诊断。"""
    from src.macro.output import MacroSystemizedOutput, IndicatorSnapshot, QUADRANT_SECTOR_MAP

    print("🌍 宏观货币信用快照")
    regime = None
    try:
        from src.macro.monetary_credit import MonetaryCreditAnalyzer
        analyzer = MonetaryCreditAnalyzer()
        regime = analyzer.analyze()
        if regime is not None:
            quadrant_name = regime.quadrant.value
            quadrant_info = QUADRANT_SECTOR_MAP.get(quadrant_name, {})
            output = MacroSystemizedOutput(
                date=str(regime.updated_at.date()) if regime.updated_at else "",
                regime=quadrant_name,
                regime_confidence=getattr(regime, "confidence", 0.5),
                overall_assessment=quadrant_info.get("description", ""),
                position_advice=quadrant_info.get("position", "neutral"),
                position_cap=1.0 if quadrant_info.get("position") == "aggressive" else 0.80,
                indicators=[
                    IndicatorSnapshot(name="M2 增速", value=getattr(regime, "m2_growth", 0) or 0, source="央行"),
                    IndicatorSnapshot(name="社融增速", value=getattr(regime, "social_financing_growth", 0) or 0, source="央行"),
                    IndicatorSnapshot(name="M1-M2 剪刀差", value=getattr(regime, "m1_m2_gap", 0) or 0, source="计算"),
                    IndicatorSnapshot(name="DR007", value=getattr(regime, "dr007", 0) or 0, unit="%", source="银行间"),
                    IndicatorSnapshot(name="LPR 1Y", value=getattr(regime, "lpr_1y", 0) or 0, unit="%", source="央行"),
                ],
                sector_impact={s: quadrant_info.get("description", "") for s in quadrant_info.get("sectors", [])},
            )
            print(output.to_summary())
        else:
            print("⚠️ 宏观数据不可用")
    except ImportError:
        print("⚠️ 宏观分析模块未安装, 请检查依赖")
    except Exception as e:
        print(f"⚠️ 宏观分析失败: {e}")

    # ---- 三大根本问题诊断 ----
    print()
    print("📋 三大根本问题诊断")
    print("-" * 50)
    try:
        from src.routing.fundamental_diagnosis import FundamentalDiagnosisEngine
        from src.data.aggregator import DataAggregator

        agg = DataAggregator()
        fd = FundamentalDiagnosisEngine(speed_monitor=agg.speed_monitor)

        # 拉取上证指数日线
        index_prices = None
        try:
            idx = agg.get_history("000001", "SH", period="daily")
            if idx is not None and not idx.empty and "close" in idx.columns:
                index_prices = idx["close"].tolist()
        except Exception:
            pass

        # 财政政策
        fiscal = None
        try:
            from src.macro.fiscal import FiscalAnalyzer
            fiscal = FiscalAnalyzer().analyze()
        except Exception:
            pass

        # 政策信号
        policy_signals = None
        policy_kw: list[str] = []
        try:
            from src.policy.tracker import PolicyTracker
            policy_signals = PolicyTracker().analyze_current()
            if policy_signals:
                for s in policy_signals:
                    policy_kw.extend(s.get("keywords", []))
        except Exception:
            pass

        fd_report = fd.diagnose(
            macro_regime=regime if regime else None,
            fiscal_regime=fiscal,
            policy_signals=policy_signals,
            index_prices=index_prices,
            sector_keywords=policy_kw if policy_kw else None,
        )

        # Q1: 政策市/市场市
        q1 = fd_report.q1
        print(f"  ❓ Q1 政策市还是市场市？")
        print(f"     结论: [{q1.classification}]  置信度 {q1.confidence:.0%}")
        print(f"     货币象限: {q1.monetary_quadrant} | 市场状态: {q1.market_regime}")
        print(f"     财政立场: {q1.fiscal_stance} | 政策强度: {q1.policy_intensity}")
        if q1.evidence:
            for ev in q1.evidence[:3]:
                print(f"       • {ev}")

        # Q2: 定价权
        q2 = fd_report.q2
        print(f"  ❓ Q2 定价权在谁手里？")
        print(f"     主导: {q2.dominant_player}  置信度 {q2.dominance_confidence:.0%}")
        if q2.marginal_pricer_ranking:
            ranking_str = " > ".join(
                f"{p['player']}({p['influence']:.0%})" for p in q2.marginal_pricer_ranking[:3]
            )
            print(f"     边际定价者排名: {ranking_str}")
        print(f"     北向: {q2.northbound_direction} | 杠杆情绪: {q2.margin_fear_greed}")
        if q2.crowding_warning:
            print(f"     ⚠️ 公募拥挤度偏高 ({q2.crowding_score})")

        # Q3: 信息优势
        q3 = fd_report.q3
        print(f"  ❓ Q3 信息优势是否存在？")
        print(f"     信息优势评分: {q3.information_advantage_score:.0f}/100  置信度 {q3.confidence:.0%}")
        print(f"     速度: {q3.speed_grade} | 覆盖度: {q3.coverage_grade} | 活跃源: {q3.source_count}")
        if q3.total_events > 0:
            print(f"     平均延迟: {q3.avg_latency_seconds:.3f}s | 最快源: {q3.fastest_source}")
        if q3.bottlenecks:
            print(f"     瓶颈: {', '.join(q3.bottlenecks[:3])}")
        if q3.recommendations:
            for rec in q3.recommendations[:2]:
                print(f"       • {rec}")

    except ImportError as e:
        print(f"  ⚠️ 三大诊断模块不可用: {e}")
    except Exception as e:
        print(f"  ⚠️ 三大根本问题诊断失败: {e}")


@_safe_cmd
@_safe_cmd
def cmd_sentiment():
    """情绪信号检测 — 拉取实时数据并输出完整分析。"""
    from src.sentiment.signals import SentimentDetector
    from src.sentiment.output import format_sentiment_plain

    print("📈 情绪信号检测")
    print("正在拉取实时市场数据...")
    detector = SentimentDetector()
    sentiment = detector.detect_market()
    report = format_sentiment_plain(sentiment)
    print(report)


def cmd_backtest():
    """运行 MVP1 回测 — 沪深300成分股 + PE分位/ROE因子 + Backtrader引擎。"""
    from src.backtest.runner import run_backtest

    print("📊 运行回测 (沪深300, 2019-2024)")
    print("=" * 60)
    try:
        result = run_backtest()
        print(f"\n✅ 回测完成")
        print(f"   年化收益: {result.annual_return:.1%}")
        print(f"   夏普比率: {result.sharpe_ratio:.2f}")
        print(f"   最大回撤: {result.max_drawdown:.1%}")
        print(f"   胜率: {result.win_rate:.1%}")
    except Exception as e:
        print(f"❌ 回测失败: {e}")
        print("   (可能需要完整数据源配置)")


def cmd_verdict_backtest():
    """运行 Verdict 回测 — 实盘 VerdictEngine 多维加权评分。"""
    from src.backtest.runner import run_verdict_backtest

    print("📊 Verdict 回测 (沪深300, 2019-2024)")
    print("   评分模型: VerdictEngine 6维加权 (实盘同款)")
    print("=" * 60)
    try:
        result = run_verdict_backtest()
        print(f"\n✅ 回测完成")
        print(f"   年化收益: {result.annual_return:.1%}")
        print(f"   夏普比率: {result.sharpe_ratio:.2f}")
        print(f"   最大回撤: {result.max_drawdown:.1%}")
        print(f"   胜率: {result.win_rate:.1%}")
    except Exception as e:
        print(f"❌ 回测失败: {e}")


@_safe_cmd
def cmd_patterns(args: list[str]):
    """K线形态识别 — 检测个股最近的蜡烛图形态信号。

    用法: python -m src patterns <code> [--days N]
    """
    import argparse
    from src.data.aggregator import DataAggregator
    from src.indicators.candlestick import (
        Hammer, ShootingStar, Doji, BullishEngulfing, BearishEngulfing,
        MorningStar, EveningStar, ThreeWhiteSoldiers, ThreeBlackCrows,
        DragonflyDoji, GravestoneDoji, HangingMan, InvertedHammer,
        Piercing, DarkCloudCover, Marubozu, SpinningTop,
    )

    parser = argparse.ArgumentParser(description="K线形态识别")
    parser.add_argument("symbol", nargs="?", default="", help="6 位股票代码")
    parser.add_argument("--days", type=int, default=20, help="回溯交易日数 (默认 20)")
    parsed = parser.parse_args(args)

    symbol = parsed.symbol
    if not symbol:
        print("用法: python -m src patterns <code> [--days N]")
        print()
        print("支持 60+ 种 K 线形态识别:")
        print("  反转形态: 锤子线/上吊线/射击之星/倒锤子/吞没/孕线/刺透/乌云盖顶")
        print("  星形态:   晨星/黄昏星/十字星/蜻蜓十字/墓碑十字")
        print("  三兵/三鸦: 白三兵/黑三鸦/三内升/三外降")
        print("  其他:      Marubozu/ spinning top/ high wave")
        return

    if not re.match(r"^\d{6}$", symbol):
        print(f"❌ 无效股票代码: {symbol}")
        return

    agg = DataAggregator()
    try:
        df = agg.get_history(symbol)
        name = agg.get_quote(symbol).name if agg.get_quote(symbol) else symbol
    except Exception:
        print(f"❌ 无法获取 {symbol} 数据")
        return

    if df is None or (hasattr(df, "empty") and df.empty):
        print(f"❌ {symbol} 无数据")
        return

    print(f"🕯️ K线形态识别: {symbol} {name} (近 {parsed.days} 日)")
    print("=" * 60)

    # 归一化列名
    col_map = {"开盘": "open", "收盘": "close", "最高": "high", "最低": "low",
               "open": "open", "close": "close", "high": "high", "low": "low"}
    if hasattr(df, "rename"):
        df = df.rename(columns={c: col_map[c] for c in df.columns if c in col_map})

    recent = df.tail(parsed.days)
    patterns_found = []

    # 扫描最近 N 天每根 K 线
    for idx in range(len(recent)):
        row = recent.iloc[idx]
        try:
            o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
        except (KeyError, ValueError):
            continue

        bar = (o, h, l, c)
        date_str = str(recent.index[idx])[:10]

        # 遍历形态检测器
        detectors = [
            ("🔨 锤子线 (Hammer)", Hammer()),
            ("🔨 倒锤子 (InvertedHammer)", InvertedHammer()),
            ("🔫 射击之星 (ShootingStar)", ShootingStar()),
            ("🪢 上吊线 (HangingMan)", HangingMan()),
            ("➕ 十字星 (Doji)", Doji()),
            ("🐉 蜻蜓十字 (DragonflyDoji)", DragonflyDoji()),
            ("🪦 墓碑十字 (GravestoneDoji)", GravestoneDoji()),
            ("🟢 看涨吞没 (BullishEngulfing)", BullishEngulfing()),
            ("🔴 看跌吞没 (BearishEngulfing)", BearishEngulfing()),
            ("🌅 晨星 (MorningStar)", MorningStar()),
            ("🌆 黄昏星 (EveningStar)", EveningStar()),
            ("⚔️ 刺透形态 (Piercing)", Piercing()),
            ("☁️ 乌云盖顶 (DarkCloudCover)", DarkCloudCover()),
            ("⬜ Marubozu", Marubozu()),
            ("💫 SpinningTop", SpinningTop()),
        ]

        for name, detector in detectors:
            detector.update(bar)
            if detector.is_ready:
                val = detector.current_value
                if isinstance(val, (int, float)) and val != 0:
                    direction = "🟢 看涨" if val > 0 else "🔴 看跌"
                    patterns_found.append((date_str, name, direction, abs(val)))

    if patterns_found:
        for date_str, name, direction, strength in patterns_found[-20:]:
            bar = "█" * min(int(strength * 10), 10)
            print(f"  {date_str} | {name:<40} {direction} {bar}")
        print(f"\n  共检测到 {len(patterns_found)} 个形态信号")
    else:
        print("  (未检测到明显形态信号)")


@_safe_cmd
def cmd_indicators(args: list[str]):
    """技术指标计算 — 计算并展示个股的技术指标。

    用法: python -m src indicators <code> [--days N]
    """
    import argparse
    from src.data.aggregator import DataAggregator
    from src.indicators.trend import SuperTrend, HullMovingAverage, ParabolicSAR
    from src.indicators.oscillator import StochasticRSI, ConnorsRSI
    from src.indicators.volatility import ChoppinessIndex, KeltnerChannels

    parser = argparse.ArgumentParser(description="技术指标计算")
    parser.add_argument("symbol", nargs="?", default="", help="6 位股票代码")
    parser.add_argument("--days", type=int, default=60, help="回溯交易日数 (默认 60)")
    parsed = parser.parse_args(args)

    symbol = parsed.symbol
    if not symbol:
        print("用法: python -m src indicators <code> [--days N]")
        print()
        print("支持指标:")
        print("  趋势: SuperTrend / Hull Moving Average / Parabolic SAR / Ichimoku")
        print("  震荡: Stochastic RSI / Connors RSI / Ultimate Oscillator / Fisher Transform")
        print("  波动: Keltner Channels / Choppiness Index / Force Index")
        print("  结构: Hurst Exponent / ZigZag")
        return

    if not re.match(r"^\d{6}$", symbol):
        print(f"❌ 无效股票代码: {symbol}")
        return

    agg = DataAggregator()
    try:
        df = agg.get_history(symbol)
        name = agg.get_quote(symbol).name if agg.get_quote(symbol) else symbol
    except Exception:
        print(f"❌ 无法获取 {symbol} 数据")
        return

    if df is None or (hasattr(df, "empty") and df.empty):
        print(f"❌ {symbol} 无数据")
        return

    # 归一化列名
    col_map = {"开盘": "open", "收盘": "close", "最高": "high", "最低": "low",
               "open": "open", "close": "close", "high": "high", "low": "low"}
    if hasattr(df, "rename"):
        df = df.rename(columns={c: col_map[c] for c in df.columns if c in col_map})

    recent = df.tail(parsed.days)
    opens = recent["open"].values.astype(float)
    highs = recent["high"].values.astype(float)
    lows = recent["low"].values.astype(float)
    closes = recent["close"].values.astype(float)

    print(f"📊 技术指标: {symbol} {name} (近 {parsed.days} 日)")
    print("=" * 60)

    # SuperTrend
    try:
        st = SuperTrend()
        for i in range(len(recent)):
            st.update((float(highs[i]), float(lows[i]), float(closes[i])))
        if st.is_ready:
            val = st.current_value
            print(f"  📈 SuperTrend: {val['trend']:.2f} ({'多头' if val.get('is_uptrend') else '空头'})")
    except Exception:
        pass

    # Hull Moving Average
    try:
        hma = HullMovingAverage()
        for i in range(len(recent)):
            hma.update(float(closes[i]))
        if hma.is_ready:
            last_close = float(closes[-1])
            hma_val = hma.current_value
            trend = "↑ 多头" if last_close > hma_val else "↓ 空头"
            print(f"  🌊 Hull MA: {hma_val:.2f} (价格 {last_close:.2f} {trend})")
    except Exception:
        pass

    # Stochastic RSI
    try:
        srsi = StochasticRSI()
        for i in range(len(recent)):
            srsi.update(float(closes[i]))
        if srsi.is_ready:
            k, d = srsi.current_value
            zone = "超买区" if k > 80 else ("超卖区" if k < 20 else "中性区")
            print(f"  📉 StochRSI: K={k:.1f} D={d:.1f} ({zone})")
    except Exception:
        pass

    # Choppiness Index
    try:
        chop = ChoppinessIndex()
        for i in range(len(recent)):
            chop.update((float(highs[i]), float(lows[i]), float(closes[i])))
        if chop.is_ready:
            ci = chop.current_value
            state = "震荡/盘整" if ci > 61.8 else "趋势市中"
            print(f"  📐 Choppiness: {ci:.1f} ({state})")
    except Exception:
        pass

    # Parabolic SAR
    try:
        psar = ParabolicSAR()
        for i in range(len(recent)):
            psar.update((float(highs[i]), float(lows[i])))
        if psar.is_ready:
            sar_val, is_long = psar.current_value
            direction = "多头" if is_long else "空头"
            print(f"  🎯 Para SAR: {sar_val:.2f} ({direction})")
    except Exception:
        pass

    print()
    print("💡 更多指标: 趋势/震荡/波动率/结构共 20+ 种，见 src/indicators/")


def cmd_backtest_optimize():
    """参数优化 — 对 MVP1 策略进行网格搜索参数优化。"""
    from src.backtest.optimizer import GridSearchOptimizer
    from src.backtest.runner import run_backtest

    print("🔧 参数优化 (网格搜索)")
    print("=" * 60)
    try:
        param_grid = {
            "max_positions": [10, 15, 20],
            "rebalance_days": [21, 63, 126],
        }
        optimizer = GridSearchOptimizer(
            engine_factory=lambda: run_backtest(engine="legacy"),
            param_grid=param_grid,
        )
        result = optimizer.optimize()
        print(f"\n✅ 优化完成: {len(result.results)} 组参数")
        if result.best_params:
            print(f"   最优参数: {result.best_params}")
            print(f"   最优夏普: {result.best_score:.2f}")
    except Exception as e:
        print(f"❌ 优化失败: {e}")
        print("   (需完整数据源配置: python -m src backtest 先测试基本回测)")


def cmd_backtest_compare():
    """多策略对比。"""
    print("📊 策略对比")
    from src.backtest import StrategyComparator, StrategyRegistry
    registry = StrategyRegistry(db_path=":memory:")
    strategies = registry.list_strategies()
    if not strategies:
        print("暂无已注册策略。请先运行 backtest-optimize 注册策略版本。")
        return
    for name in strategies:
        history = registry.history(name)
        print(f"  {name}: {len(history)} 个版本")


@_safe_cmd
def cmd_diagnose(args: list[str]):
    """一键诊断（小白入口）。支持单票和批量模式。

    用法:
      python -m src diagnose 002415                  # 单票诊断
      python -m src diagnose --batch 002415,000938   # 批量对比
      python -m src diagnose 300750 --as-of 2025-09-01  # 历史回测
    """
    import argparse
    parser = argparse.ArgumentParser(description="一键诊断")
    parser.add_argument("symbol", nargs="?", help="股票代码（单票模式）")
    parser.add_argument("--deep", action="store_true", help="深度模式（含行业+公司深度研究）")
    parser.add_argument("--no-t0", action="store_true", dest="no_t0", help="跳过 T+0 日内时机分析")
    parser.add_argument("--batch", type=str, default="", metavar="CODES",
                        help="批量诊断模式，逗号分隔股票代码列表，如 002415,000938,601138")
    parser.add_argument("--as-of", type=str, default="", metavar="DATE",
                        help="历史回测日期 (YYYY-MM-DD)，如 2025-09-01")
    parsed = parser.parse_args(args)

    # ── 批量模式 ──
    if parsed.batch:
        symbols = [s.strip() for s in parsed.batch.split(",") if s.strip()]
        if not symbols:
            print("❌ --batch 需要至少一个股票代码")
            return
        # 验证所有代码
        invalid = [s for s in symbols if not _validate_symbol(s, silent=True)]
        if invalid:
            print(f"❌ 无效代码: {', '.join(invalid)}")
            return

        print(f"🔬 批量诊断 {len(symbols)} 支股票 (默认跳过 T+0，选股非择时)...")
        from src.routing.orchestrator import Orchestrator
        orch = Orchestrator()
        batch_results = orch.run_batch(
            symbols=symbols,
            skip_t0=True,  # 批量模式默认跳过 T+0：选股≠择时
            as_of_date=parsed.as_of,
        )
        from src.output.step_output import print_batch_comparison
        print_batch_comparison(batch_results)
        return

    # ── 单票模式 ──
    symbol = parsed.symbol
    if not symbol:
        print("❌ 请提供股票代码，或使用 --batch 批量模式")
        print("   用法: python -m src diagnose 002415")
        print("   用法: python -m src diagnose --batch 002415,000938,601138")
        return
    if not _validate_symbol(symbol):
        return
    from src.doctrine.checker import DoctrineChecker

    print(f"🏥 诊断 {symbol}")
    checker = DoctrineChecker()
    result = checker.check(symbol, {"stock_name": ""})
    if result.passed:
        print("✅ 军规通过 — 无硬阻断")
    else:
        print(f"⛔ 被拦截: {', '.join(r.name for r in result.blocked_by)}")
    # 传递 --deep / --no-t0 flag
    deep_args = [symbol]
    if parsed.deep:
        deep_args.append("--deep")
    if parsed.no_t0:
        deep_args.append("--no-t0")
    if parsed.as_of:
        deep_args.append("--as-of")
        deep_args.append(parsed.as_of)
    cmd_analyze(deep_args)


@_safe_cmd
def cmd_game_theory():
    """博弈论知识摘要。"""
    from src.game_theory import get_game_theory_summary
    print(get_game_theory_summary())


@_safe_cmd
def cmd_topic(args: list[str]):
    """主题生命周期管理 — 查看/搜索当前市场热点主题。

    用法: python -m src topic [search|list] [query]
    """
    from src.information.topic_manager import TopicManager

    sub = args[0] if args else "list"

    print("🔥 主题生命周期管理")
    print("=" * 60)

    try:
        tm = TopicManager()
        if sub == "search" and len(args) > 1:
            query = " ".join(args[1:])
            print(f"搜索主题: {query}")
            results = tm.search(query)
            for r in results[:10]:
                print(f"  • {r}")
        else:
            topics = tm.list_all() if hasattr(tm, "list_all") else []
            if topics:
                for t in topics[:15]:
                    print(f"  • {t}")
            else:
                print("  (主题数据暂不可用，需数据源配置)")
    except Exception as e:
        print(f"  ⚠️ 主题管理暂不可用: {e}")


@_safe_cmd
def cmd_policy(args: list[str]):
    """政策跟踪 — 查看/搜索近期行业政策信号。

    用法: python -m src policy [search|list] [query]
    """
    from src.policy.tracker import PolicyTracker

    sub = args[0] if args else "list"

    print("📰 政策跟踪")
    print("=" * 60)

    try:
        tracker = PolicyTracker()
        if sub == "search" and len(args) > 1:
            query = " ".join(args[1:])
            print(f"搜索政策: {query}")
            signals = tracker.search(query)
            for s in signals[:10]:
                print(f"  • {s}")
        else:
            signals = tracker.recent() if hasattr(tracker, "recent") else []
            if signals:
                for s in signals[:15]:
                    print(f"  • {s}")
            else:
                print("  (政策数据暂不可用，需数据源配置)")
    except Exception as e:
        print(f"  ⚠️ 政策跟踪暂不可用: {e}")


@_safe_cmd
def cmd_manipulation(args: list[str]):
    """庄家操盘手法检测 — 7 种经典操纵模式实时识别。

    用法: python -m src manipulation <code> [--date YYYY-MM-DD]

    检测模式: 诱多出货 / 诱空吸筹 / 对倒拉升 / 洗盘震仓 /
             分时钓鱼线 / 尾盘偷袭拉升 / 尾盘偷袭砸盘
    """
    import argparse
    from datetime import datetime
    from src.game_theory.manipulation import ManipulationDetector
    from src.data.aggregator import DataAggregator

    parser = argparse.ArgumentParser(description="庄家操盘手法检测")
    parser.add_argument("symbol", nargs="?", default="", help="6 位股票代码")
    parser.add_argument("--date", type=str, default="", help="检测日期 YYYY-MM-DD")
    parsed = parser.parse_args(args)

    symbol = parsed.symbol
    if not symbol:
        print("用法: python -m src manipulation <code> [--date YYYY-MM-DD]")
        print()
        print("检测 7 种经典庄家操纵模式:")
        print("  🔴 诱多出货 — 虚假突破→高位放量→跳水")
        print("  🟠 诱空吸筹 — 砸盘破位→散户割肉→快速拉回")
        print("  🟠 对倒拉升 — 自买自卖→量价齐升假象")
        print("  🟠 洗盘震仓 — 急跌→制造恐慌→低位吸筹")
        print("  🔴 分时钓鱼线 — 直线拉升→缓慢阴跌出货")
        print("  🟡 尾盘偷袭拉升 — 14:50后异常拉升操纵收盘价")
        print("  🟡 尾盘偷袭砸盘 — 14:50后异常砸盘打压股价")
        return

    if not re.match(r"^\d{6}$", symbol):
        print(f"❌ 无效股票代码: {symbol}")
        return

    date = parsed.date or datetime.now().strftime("%Y-%m-%d")

    print(f"🕵️ 庄家操盘手法检测: {symbol} ({date})")
    print("=" * 60)

    # 获取分钟级数据
    agg = DataAggregator()
    try:
        quote = agg.get_quote(symbol)
        name = quote.name if quote else symbol
    except Exception:
        name = symbol

    print(f"   标的: {name}")
    print()

    # 尝试获取分钟K线
    try:
        minute_df = agg.mootdx.get_history(symbol, period="1min")
    except Exception:
        try:
            minute_df = agg.get_history(symbol, period="1min")
        except Exception:
            minute_df = None

    # 归一化列名 (支持中文/英文)
    COLUMN_MAP = {
        "开盘": "open", "收盘": "close", "最高": "high", "最低": "low",
        "成交量": "volume", "成交额": "amount", "日期": "datetime",
        "open": "open", "close": "close", "high": "high", "low": "low",
        "vol": "volume", "volume": "volume", "amount": "amount",
        "datetime": "datetime",
    }
    if minute_df is not None and not (hasattr(minute_df, "empty") and minute_df.empty):
        if hasattr(minute_df, "rename"):
            rename_map = {c: COLUMN_MAP.get(c, c) for c in minute_df.columns if c in COLUMN_MAP}
            minute_df = minute_df.rename(columns=rename_map)

    if minute_df is None or (hasattr(minute_df, "empty") and minute_df.empty):
        print("⚠️ 无法获取分钟级数据，使用日线降级检测")
        try:
            daily_df = agg.get_history(symbol)
        except Exception:
            print("❌ 数据获取失败")
            return
        detector = ManipulationDetector()
        result = detector.detect(symbol, daily_df, name=name)
    else:
        detector = ManipulationDetector()
        result = detector.detect(symbol, minute_df, name=name)

    # 输出结果
    print(f"   操纵风险评分: {result.risk_score:.0f}/100")
    print(f"   风险等级: {result.risk_level.upper()}")
    print()

    if result.signals:
        print(f"   检测到 {len(result.signals)} 个可疑信号:")
        for sig in result.signals:
            emoji = {"high": "🔴", "medium": "🟠", "low": "🟡"}.get(sig.risk_level, "⚪")
            print(f"   {emoji} {sig.playbook_name}")
            print(f"      置信度: {sig.confidence:.0%} | 检测时间: {sig.detected_at}")
            for e in sig.evidence:
                print(f"      • {e}")
            print(f"      → {sig.suggestion}")
            print()
    else:
        print("   🟢 未检测到明显的庄家操纵迹象")

    print("─" * 60)
    print(result.summary)


def cmd_calibrate():
    """置信度校准报告 — 基于交易追踪数据验证系统预测准确度。"""
    from src.learner.calibrator import Calibrator
    from src.kelly.tracker import TradeTracker

    print("📐 置信度校准")
    print("=" * 60)

    cal = Calibrator()
    try:
        tracker = TradeTracker()
        records = tracker.list_records() if hasattr(tracker, "list_records") else []
        for r in records:
            if hasattr(r, "confidence") and hasattr(r, "pnl"):
                cal.record(r.confidence, r.pnl > 0)
    except Exception:
        pass

    report = cal.generate_report()
    print(f"   样本数: {report.total_predictions} (需要 ≥ {cal.MIN_SAMPLES})")
    print(f"   样本充足: {'✅' if report.sample_sufficient else '❌'}")

    if report.sample_sufficient:
        print(f"\n   校准结果:")
        for band, acc in report.band_accuracy.items() if hasattr(report, "band_accuracy") else []:
            bar = "█" * int(acc * 20)
            print(f"   置信度 {band}: {acc:.0%} {bar}")
    else:
        remaining = cal.MIN_SAMPLES - report.total_predictions
        print(f"\n   ⚠️ 还需 {remaining} 条交易记录")
        print(f"   使用 'python -m src trade-track add' 录入交易")


@_safe_cmd
def cmd_profile():
    """用户能力画像。"""
    from src.learner import ProfileTracker

    print("👤 用户能力画像")
    tracker = ProfileTracker()
    profile = tracker.evaluate()
    print(profile.summary)


def cmd_preference(args: list[str]):
    """投资者偏好管理。"""
    from src.learner.preference.loader import InvestorPreferenceLoader

    loader = InvestorPreferenceLoader()
    sub = args[0] if args else "view"

    if sub == "view":
        prefs = loader.load()
        print(loader.summary(prefs))
    elif sub == "setup":
        _cmd_preference_setup(loader)
    elif sub == "edit":
        path = os.path.abspath(loader.path)
        editor = os.environ.get("EDITOR", "nano")
        os.system(f"{editor} {path}")
    elif sub == "reset":
        loader.reset()
        print("✅ 偏好已重置为默认值")
    elif sub == "coc-update" and len(args) >= 3:
        industry = args[1]
        try:
            level = int(args[2])
        except ValueError:
            print("❌ 熟悉度需为 1-5 的数字")
            return
        ok = loader.update_circle_of_competence(industry, level)
        if ok:
            print(f"✅ 能力圈已更新: {industry} = {'⭐' * level} ({level}/5)")
        else:
            print(f"❌ 更新能力圈失败")
    elif sub == "path":
        print(os.path.abspath(loader.path))
    else:
        print(f"未知子命令: {sub}，可用: view | setup | edit | reset | coc-update <行业> <熟悉度(1-5)> | path")


def _cmd_preference_setup(loader):
    """交互式投资者画像设置向导 — 10 步完整画像。"""
    from datetime import datetime
    from src.learner.preference.model import (
        BoardAccess,
        InvestorPreference, RiskProfile, InvestmentGoal,
        TradingStyle, InvestorTier, HoldingPeriod, PositionLimits,
    )

    prefs = loader.load()
    step = 0

    print("\n🎯 投资者画像设置向导")
    print("=" * 50)
    print("花 3 分钟设置你的专属画像，分析引擎会根据你的实际情况")
    print("调整裁决评分权重、仓位调度建议、风控参数。")
    print("(按回车跳过，保持当前值)\n")

    # ── 基本信息 ──
    print("── 基本信息 ──")

    # 1. 风险偏好
    step += 1
    print(f"\n{step}️⃣  风险偏好 — 你能接受多大的波动？")
    print("   conservative = 保守型：追求稳定，少亏钱比多赚钱重要")
    print("   balanced     = 均衡型：在风险与收益间取平衡")
    print("   aggressive   = 进取型：愿意承受较大波动博取高收益")
    choice = input(f"   选择 [{prefs.risk_profile.value}]: ").strip().lower()
    if choice in ("conservative", "balanced", "aggressive"):
        prefs.risk_profile = RiskProfile(choice)

    # 2. 投资目标
    step += 1
    print(f"\n{step}️⃣  投资目标 — 你投资的主要目的是什么？")
    print("   absolute_return = 绝对收益：跑赢存款/理财，正收益优先")
    print("   relative_return = 相对收益：跑赢沪深300指数")
    print("   cash_flow       = 现金流：追求稳定股息分红")
    choice = input(f"   选择 [{prefs.investment_goal.value}]: ").strip().lower()
    if choice in ("absolute_return", "relative_return", "cash_flow"):
        prefs.investment_goal = InvestmentGoal(choice)

    # 3. 交易风格 + 持有时间
    step += 1
    print(f"\n{step}️⃣  交易风格")
    print("   long_term  = 中长线配置：持有数月到数年")
    print("   swing      = 波段交易：持有数周到数月")
    print("   short_term = 短线交易：持有数天到数周")
    print("   mixed      = 混合风格")
    choice = input(f"   选择 [{prefs.trading_style.value}]: ").strip().lower()
    if choice in ("long_term", "swing", "short_term", "mixed"):
        prefs.trading_style = TradingStyle(choice)

    step += 1
    print(f"\n{step}️⃣  典型持有时间")
    print("   short = 短线 (<1个月)")
    print("   medium = 中线 (1-12个月)")
    print("   long = 长线 (1-3年)")
    print("   ultra = 超长线 (3年以上)")
    choice = input(f"   选择 [{prefs.holding_period.value}]: ").strip().lower()
    if choice in ("short", "medium", "long", "ultra"):
        prefs.holding_period = HoldingPeriod(choice)

    # ── 可交易板块 ──
    print("\n── 可交易板块 ──")

    step += 1
    print(f"\n{step}️⃣  可交易的 A 股板块 — 你的账户能交易哪些板块？")
    print("   不同板块有不同的开通门槛：")
    print("   main_sh = 上海主板 (60xxxx)  — 无门槛，所有人都能买")
    print("   main_sz = 深圳主板 (00xxxx)  — 无门槛，所有人都能买")
    print("   gem     = 创业板   (30xxxx)  — 需 2 年经验 + 10 万资产")
    print("   star    = 科创板   (68xxxx)  — 需 2 年经验 + 50 万资产")
    print("   bse     = 北交所   (8xxxxx)  — 需 2 年经验 + 50 万资产")
    current_boards = [b.value for b in prefs.accessible_boards]
    print(f"\n   当前可交易板块: {', '.join(current_boards)}")
    print("\n   常见配置:")
    print("   ① 仅主板（无法交易科创/创业板）→ 输入: main_sh,main_sz")
    print("   ② 主板+创业板（有 10 万+2 年经验）→ 输入: main_sh,main_sz,gem")
    print("   ③ 全部板块 → 输入: all")
    board_input = input(f"   输入 [{','.join(current_boards)}]: ").strip().lower()
    if board_input:
        if board_input == "all":
            prefs.accessible_boards = [
                BoardAccess.MAIN_SH, BoardAccess.MAIN_SZ,
                BoardAccess.GEM, BoardAccess.STAR, BoardAccess.BSE,
            ]
        else:
            boards = []
            for b in board_input.split(","):
                b = b.strip()
                try:
                    boards.append(BoardAccess(b))
                except ValueError:
                    pass
            if boards:
                prefs.accessible_boards = boards
        print(f"   ✅ 已设置: {', '.join(b.value for b in prefs.accessible_boards)}")

    # ── 风控参数 ──
    print("\n── 风控参数 ──")

    # 5. 投资者级别
    step += 1
    print(f"\n{step}️⃣  投资者级别")
    print("   beginner     = 小白：全量军规保护，输出详细易懂")
    print("   intermediate = 进阶：部分军规可放宽")
    print("   pro          = 专业：仅保留核心风控")
    choice = input(f"   选择 [{prefs.tier.value}]: ").strip().lower()
    if choice in ("beginner", "intermediate", "pro"):
        prefs.tier = InvestorTier(choice)

    # 6. 投资本金
    step += 1
    print(f"\n{step}️⃣  总投资本金 (万元)")
    current = prefs.position_limits.total_capital / 10000
    choice = input(f"   输入 [{current:.0f}]: ").strip()
    if choice:
        try:
            prefs.position_limits.total_capital = float(choice) * 10000
        except ValueError:
            print("   ⚠️ 输入无效，保持原值")

    # 7. 能忍受的最大总亏损
    step += 1
    print(f"\n{step}️⃣  能忍受的最大总亏损 (%)")
    print("   即全部资金最多能亏多少就停止交易")
    current_pct = prefs.position_limits.max_total_loss_pct * 100
    choice = input(f"   输入 [{current_pct:.0f}]: ").strip()
    if choice:
        try:
            prefs.position_limits.max_total_loss_pct = float(choice) / 100
        except ValueError:
            print("   ⚠️ 输入无效，保持原值")

    # 8. 单笔止损 + 投资期限
    step += 1
    print(f"\n{step}️⃣  单笔最大亏损容忍 (%)")
    current_pct = prefs.position_limits.single_stop_loss_pct * 100
    choice = input(f"   输入 [{current_pct:.0f}]: ").strip()
    if choice:
        try:
            prefs.position_limits.single_stop_loss_pct = float(choice) / 100
        except ValueError:
            print("   ⚠️ 输入无效，保持原值")

    step += 1
    print(f"\n{step}️⃣  投资期限（预期投资多久）")
    print("   例如: 1-3年 / 3-5年 / 5年以上 / 长期不用")
    choice = input(f"   输入 [{prefs.investment_horizon}]: ").strip()
    if choice:
        prefs.investment_horizon = choice

    # ── 能力圈与自选股 ──
    print("\n── 能力圈 & 自选股 ──")

    step += 1
    print(f"\n{step}️⃣  能力圈 — 你熟悉哪些行业？")
    coc = prefs.circle_of_competence
    current_industries = dict(coc.industries)
    if current_industries:
        for ind, fam in sorted(current_industries.items()):
            print(f"     {ind}: {'⭐' * fam} ({fam}/5)")
    else:
        print("     (无)")
    print("\n   常见行业参考: 消费、新能源、科技、医药、金融、制造、通信、半导体、白酒、汽车、互联网、军工、地产")
    print("   输入格式: 行业名 熟悉度(1-5)，例如: 医药 4")
    print("   熟悉度: 5=从业者/深度跟踪 4=深入研究 3=基本了解 2=略知 1=听说过")
    print("   输入空行结束。")
    new_industries = dict(current_industries)
    while True:
        line = input("   添加: ").strip()
        if not line:
            break
        parts = line.split()
        if len(parts) >= 2:
            try:
                name = parts[0]
                fam = int(parts[1])
                if 1 <= fam <= 5:
                    new_industries[name] = fam
                    print(f"     ✅ {name}: {'⭐' * fam}")
                else:
                    print("   ⚠️ 熟悉度需在 1-5 之间")
            except ValueError:
                print("   ⚠️ 格式错误，例如: 医药 4")
    coc.industries = new_industries

    # ── 保存 ──
    prefs.last_updated = datetime.now().isoformat()
    prefs.setup_step = step
    comp = prefs.completeness()

    print(f"\n{'=' * 50}")
    print("📋 配置预览:")
    print(f"   风险偏好: {prefs.risk_profile.value}")
    print(f"   投资目标: {prefs.investment_goal.value}")
    print(f"   交易风格: {prefs.trading_style.value} / 持有: {prefs.holding_period.value}")
    print(f"   投资级别: {prefs.tier.value}")
    print(f"   投资本金: {prefs.position_limits.total_capital:,.0f}")
    print(f"   总投资期限: {prefs.investment_horizon}")
    print(f"   最大总亏损: {prefs.position_limits.max_total_loss_pct:.0%}")
    print(f"   单笔止损: {prefs.position_limits.single_stop_loss_pct:.0%}")
    print(f"   可交易板块: {', '.join(b.value for b in prefs.accessible_boards)}")
    print(f"   能力圈: {', '.join(f'{k}({v}/5)' for k, v in sorted(coc.industries.items()))}")
    print(f"\n   📊 画像完整度: {comp['score']}%")
    if comp["missing"]:
        print(f"   📝 还可以补充: {', '.join(comp['missing'][:5])}")

    confirm = input("\n保存配置? [Y/n]: ").strip().lower()
    if confirm in ("", "y", "yes"):
        loader.save(prefs)
        print(f"✅ 配置已保存到 {loader.path}")
        print("   下次运行 analyze 时自动生效！")
    else:
        print("❌ 已取消，配置未保存")


@_safe_cmd
def cmd_feedback(args: list[str]):
    """用户反馈管理。"""
    from src.learner import FeedbackCollector

    sub = args[0] if args else "summary"
    collector = FeedbackCollector(db_path=":memory:")

    if sub == "add":
        print("💬 添加反馈")
        print("FeedbackCollector 已就绪。使用 agree/disagree/adjust/annotate 方法记录反馈。")
        print("⏳ 交互式反馈录入开发中。")
    elif sub == "summary":
        print("📊 反馈统计")
        s = collector.summary()
        print(f"总反馈: {s.total}")
        print(f"赞同率: {s.agreement_rate:.1%}")
        if s.lessons:
            print(f"教训: {', '.join(s.lessons[:5])}")
    else:
        print(f"未知子命令: {sub}，可用: add | summary")


def cmd_evolve():
    """[已废弃] 请使用 evolution 命令。"""
    print("🧬 策略进化")
    print("⚠️  'evolve' 命令已废弃，请使用 'evolution' 命令。")
    print("")
    print("  python -m src evolution help    # 查看可用子命令")
    print("  python -m src evolution list    # 列出所有进化策略")
    print("  python -m src evolution import <url>  # 导入论文")
    print("")
    print("可用子命令: import | list | status | promote | degrade |")
    print("            retire | optimize | proposals | monitor | report")


@_safe_cmd
def cmd_learn(args: list[str]):
    """学习报告。"""
    from src.learner import ProfileTracker, ReportGenerator

    sub = args[0] if args else "report"
    if sub == "report":
        print("📝 学习报告")
        gen = ReportGenerator()
        tracker = ProfileTracker()
        report = gen.generate(profile=tracker.evaluate(), period="weekly")
        print(report.render())
    else:
        print(f"未知子命令: {sub}，可用: report")


# ------------------------------------------------------------------
# V4 新增: 妙想 Skill CLI 命令
# ------------------------------------------------------------------

@_safe_cmd
@_safe_cmd
def cmd_finance(args: list[str]):
    """财务数据查询 — NL 驱动的财务报表查询。

    用法: python -m src finance <code> [statement]
      statement: lrb(利润表) / fzb(资产负债表) / llb(现金流量表)
    """
    import argparse
    from src.finance.meta_tool import MetaTool

    parser = argparse.ArgumentParser(description="财务报表查询")
    parser.add_argument("symbol", nargs="?", default="", help="6 位股票代码")
    parser.add_argument("statement", nargs="?", default="lrb", help="报表类型: lrb/fzb/llb")
    parsed = parser.parse_args(args)

    symbol = parsed.symbol
    if not symbol:
        print("用法: python -m src finance <code> [lrb|fzb|llb]")
        print()
        print("财务报表查询:")
        print("  lrb — 利润表 (营业收入/净利润/EPS)")
        print("  fzb — 资产负债表 (总资产/负债/净资产)")
        print("  llb — 现金流量表 (经营/投资/筹资现金流)")
        return

    if not re.match(r"^\d{6}$", symbol):
        print(f"❌ 无效股票代码: {symbol}")
        return

    stype_map = {"lrb": "利润表", "fzb": "资产负债表", "llb": "现金流量表"}
    stype = parsed.statement
    print(f"📊 {stype_map.get(stype, stype)}: {symbol}")
    print("=" * 60)

    try:
        tool = MetaTool()
        result = tool.query(symbol, stype) if hasattr(tool, "query") else None
        if result:
            print(result)
        else:
            from src.data.aggregator import DataAggregator
            agg = DataAggregator()
            quote = agg.get_quote(symbol)
            name = quote.name if quote else symbol
            print(f"  标的: {name}")
            print(f"  (详细财务数据需配置数据源: GS_API_KEY / AKShare)")
            print(f"  可用 python -m src diagnose {symbol} 查看综合诊断")
    except Exception as e:
        print(f"  ⚠️ 财务查询暂不可用: {e}")


def cmd_search_news(args: list[str]):
    """mx-search 金融资讯搜索。"""
    if not args:
        print("用法: search-news <query> [--limit N]")
        print("示例: search-news \"贵州茅台最新研报\"")
        return

    import argparse
    from src.data.aggregator import DataAggregator

    parser = argparse.ArgumentParser(description="金融资讯搜索")
    parser.add_argument("query", nargs="*", help="搜索查询（自然语言）")
    parser.add_argument("--limit", type=int, default=10, help="返回数量上限")
    parsed = parser.parse_args(args)

    query = " ".join(parsed.query) if parsed.query else ""
    if not query:
        print("请提供搜索查询")
        return

    print(f"🔍 搜索: {query}")
    agg = DataAggregator()
    items = agg.search_news(query, max_results=parsed.limit)

    if not items:
        print("📭 无结果（mx-search 不可用或无匹配内容）")
        return

    print(f"\n📰 找到 {len(items)} 条资讯:\n")
    for i, item in enumerate(items, 1):
        print(f"{'─' * 60}")
        print(f"  {i}. {item.title}")
        if item.source:
            print(f"     来源: {item.source}  |  日期: {item.date}")
        if item.content:
            content = item.content[:200].replace("\n", " ")
            print(f"     {content}...")
        if item.secu_list:
            symbols = [s.get("secuCode", "") for s in item.secu_list[:3]]
            print(f"     关联: {', '.join(symbols)}")


@_safe_cmd
def cmd_screen(args: list[str]):
    """mx-xuangu 条件选股。"""
    if not args:
        print("用法: screen <conditions> [--industry INDUSTRY]")
        print("示例: screen \"市盈率<20,ROE>15%\"")
        print("      screen --industry 新能源 \"涨幅>1%\"")
        return

    import argparse
    from src.data.aggregator import DataAggregator

    parser = argparse.ArgumentParser(description="条件选股")
    parser.add_argument("conditions", nargs="*", help="选股条件（自然语言）")
    parser.add_argument("--industry", type=str, default="", help="限定行业/板块")
    parsed = parser.parse_args(args)

    conditions = " ".join(parsed.conditions) if parsed.conditions else ""
    if parsed.industry and conditions:
        conditions = f"{parsed.industry}板块 {conditions}"
    elif parsed.industry:
        conditions = f"{parsed.industry}板块"

    if not conditions:
        print("请提供选股条件")
        return

    print(f"🔍 选股: {conditions}")
    agg = DataAggregator()

    if parsed.industry and not any(w in conditions for w in ["板块", "行业"]):
        results = agg.screen_by_industry(parsed.industry)
    else:
        results = agg.screen_stocks(conditions)

    if not results:
        print("📭 无股票满足条件")
        return

    # ── 板块过滤 (P0) ──
    try:
        from src.learner.preference.loader import InvestorPreferenceLoader
        from src.learner.preference.adapter import resolve_board_filter
        loader = InvestorPreferenceLoader()
        board_ok = resolve_board_filter(loader.load())
        before = len(results)
        results = [r for r in results if board_ok(r.symbol)]
        if len(results) < before:
            accessible = loader.load().accessible_boards
            print(f"🔒 板块过滤: {before} → {len(results)} 只 "
                  f"(仅保留 {[b.value for b in accessible]})")
    except Exception:
        pass

    # ── 行业过滤 (能力圈) ──
    try:
        from src.learner.preference.sector_filter import build_competence_symbol_set
        coc = loader.load().circle_of_competence.industries
        competence_symbols = build_competence_symbol_set(coc)
        if competence_symbols is not None:
            before = len(results)
            results = [r for r in results if r.symbol in competence_symbols]
            if len(results) < before:
                coc_names = [k for k, v in coc.items() if v > 0]
                print(f"🎯 能力圈过滤: {before} → {len(results)} 只 "
                      f"(能力圈: {coc_names})")
    except Exception:
        pass

    if not results:
        print("📭 板块过滤后无剩余标的")
        return

    print(f"\n🏆 筛选结果: {len(results)} 只股票\n")
    print(f"{'代码':<8s} {'名称':<10s} {'最新价':>8s} {'涨跌幅':>8s} {'市场':<4s}")
    print("-" * 42)
    for r in results[:30]:
        price = f"{r.price:.2f}" if r.price else "N/A"
        chg = f"{r.change_pct:+.2f}%" if r.change_pct is not None else "N/A"
        print(f"{r.symbol:<8s} {r.name:<10s} {price:>8s} {chg:>8s} {r.market:<4s}")
    if len(results) > 30:
        print(f"... 还有 {len(results) - 30} 只")


@_safe_cmd
def cmd_related(args: list[str]):
    """mx-data 关联关系查询。"""
    if not args:
        print("用法: related <symbol>")
        print("示例: related 600519")
        return

    from src.data.aggregator import DataAggregator

    symbol = args[0]
    print(f"🔗 关联关系: {symbol}")
    agg = DataAggregator()
    parties = agg.get_related_parties(symbol)

    if not parties:
        print("📭 无关联关系数据（mx-data 不可用或无数据）")
        return

    print(f"\n👥 关联方: {len(parties)} 个\n")
    for p in parties:
        type_icon = {"股东": "💰", "高管": "👔", "子公司": "🏢"}.get(p.relation_type, "📌")
        print(f"  {type_icon} {p.entity_name}")
        if p.relation_type:
            print(f"     类型: {p.relation_type}")
        if p.stake_pct:
            print(f"     持股: {p.stake_pct:.2f}%")
        if p.position:
            print(f"     分类: {p.position}")


def cmd_paper_trade(args: list[str]):
    """mx-moni 模拟交易管理。"""
    import argparse
    parser = argparse.ArgumentParser(description="模拟交易管理")
    parser.add_argument("action", nargs="?", default="status",
                        choices=["status", "positions", "balance", "orders", "buy", "sell", "cancel"])
    parser.add_argument("--code", type=str, help="股票代码")
    parser.add_argument("--price", type=float, help="委托价格")
    parser.add_argument("--qty", type=int, default=100, help="委托数量")
    parser.add_argument("--market", action="store_true", help="以市价委托")
    parser.add_argument("--order-id", type=str, help="委托单ID（撤单时使用）")
    parser.add_argument("--cancel-all", action="store_true", help="一键撤单")
    parsed = parser.parse_args(args)

    try:
        from src.data.miaoxiang_provider import MiaoXiangProvider
        mx = MiaoXiangProvider()
    except Exception as e:
        print(f"❌ 妙想 Provider 不可用: {e}")
        return

    action = parsed.action

    if action == "status":
        balance = mx.moni_get_balance()
        positions = mx.moni_get_positions()
        if balance:
            data = balance.get("data", balance)
            print(f"💰 资金: 总资产 {data.get('totalAssets', 'N/A')}  可用 {data.get('availBalance', 'N/A')}")
        if positions:
            data = positions.get("data", positions)
            pos_list = data.get("posList", [])
            print(f"📊 持仓: {data.get('posCount', len(pos_list))} 只")
            for p in (pos_list or []):
                print(f"  {p.get('secCode', '')} {p.get('secName', '')} "
                      f"数量:{p.get('count', 0)} 成本:{p.get('costPrice', 0)} 盈亏:{p.get('profit', 0)}")

    elif action == "positions":
        result = mx.moni_get_positions()
        print(result or "获取持仓失败")

    elif action == "balance":
        result = mx.moni_get_balance()
        print(result or "获取资金失败")

    elif action == "orders":
        result = mx.moni_get_orders()
        print(result or "获取委托失败")

    elif action in ("buy", "sell"):
        if not parsed.code:
            print("❌ 请提供股票代码 --code")
            return
        if not parsed.market and not parsed.price:
            print("❌ 请提供委托价格 --price 或使用 --market 市价委托")
            return
        result = mx.moni_place_trade(
            stock_code=parsed.code,
            trade_type=action,
            price=parsed.price or 0.0,
            quantity=parsed.qty,
            use_market_price=parsed.market,
        )
        print(result or "委托失败")

    elif action == "cancel":
        if not parsed.cancel_all and not parsed.order_id:
            print("❌ 请提供 --order-id 或 --cancel-all 一键撤单")
            return
        result = mx.moni_cancel_order(
            order_id=parsed.order_id or "",
            cancel_all=parsed.cancel_all,
        )
        print(result or "撤单失败")


def cmd_poster(args: list[str]):
    """mx-poster AI 社区发帖。"""
    import argparse
    parser = argparse.ArgumentParser(description="AI 社区发帖")
    parser.add_argument("--title", type=str, help="帖子标题")
    parser.add_argument("--text", type=str, help="正文 HTML")
    parser.add_argument("--from-verdict", type=str, help="从分析结果生成帖子 (symbol)")
    parsed = parser.parse_args(args)

    try:
        from src.data.miaoxiang_provider import MiaoXiangProvider
        mx = MiaoXiangProvider()
    except Exception as e:
        print(f"❌ 妙想 Provider 不可用: {e}")
        return

    if parsed.from_verdict:
        from src.routing.orchestrator import Orchestrator

        symbol = parsed.from_verdict
        print(f"📝 从 {symbol} 分析结果生成社区帖子...")
        orch = Orchestrator()
        result = orch.run(symbol)
        if not result.verdict:
            print("❌ 无分析结果")
            return
        v = result.verdict
        title = f"{result.name} 投资价值分析"
        text = (
            f"<h3>综合评分: {v.score}/100</h3>"
            f"<p>推荐: {v.recommendation}</p>"
            f"<p>置信度: {v.confidence:.0%}</p>"
            f"<p><strong>风险提示：</strong>以上为AI分析结果，不构成投资建议。投资有风险，入市需谨慎。</p>"
        )
        parsed = argparse.Namespace(title=title, text=text, from_verdict=None)

    if not parsed.title or not parsed.text:
        print("❌ 请提供 --title 和 --text，或使用 --from-verdict <symbol>")
        return

    result = mx.poster_post(parsed.title, parsed.text)
    if result:
        print(f"✅ 已发布: {parsed.title}")
    else:
        print("❌ 发布失败（检查授权和 MX_APIKEY）")


@_safe_cmd
def cmd_alpha(symbol: str):
    """Alpha 视角分析 — 三维 Alpha 评估 + 全链路注入。"""
    if not _validate_symbol(symbol):
        return
    from src.alpha.lens import AlphaLens
    from src.routing.orchestrator import Orchestrator

    print(f"🔍 Alpha Lens 分析: {symbol}")
    print("=" * 50)

    orch = Orchestrator()
    result = orch.run(symbol, market=_infer_market(symbol))

    if not result.passed:
        print(f"⛔ 不通过: {', '.join(result.blocked_by)}")
        return
    print(f"✅ 行情交叉验证: {'通过' if result.cross_validated else '未通过'}")
    if result.data_gaps:
        print(f"📭 数据缺口: {', '.join(result.data_gaps)}")
    if result.report and result.report.source_citations:
        tiers = {}
        for sc in result.report.source_citations:
            tiers[sc.source_tier] = tiers.get(sc.source_tier, 0) + 1
        print(f"📚 信源分级: {', '.join(f'{t}: {c}' for t, c in sorted(tiers.items()))}")

    # Alpha Profile
    ap = result.alpha_profile
    if ap:
        print(f"\n📊 Alpha 综合评分: {ap.alpha_score:.0f}/100")
        print(f"   置信度: {ap.alpha_confidence:.0%}")
        print(f"   衰减状态: {ap.decay_status.value}")
        print(f"   核心差异点: {ap.key_differentiator}")
        print(f"\n{'─' * 40}")
        print(f"📰 信息来源层级: {ap.source.source_tier.value}")
        print(f"   一手性: {ap.source.originality_score:.0f}/100")
        print(f"   理解深度: {ap.source.interpretation_depth:.0f}/100")
        print(f"   噪音比例: {ap.source.noise_ratio:.0%}")
        if ap.source.primary_sources:
            print(f"   一手来源: {', '.join(ap.source.primary_sources[:3])}")
        if ap.source.tertiary_sources:
            print(f"   噪音来源: {', '.join(ap.source.tertiary_sources[:3])}")
        print(f"\n{'─' * 40}")
        print(f"🕳️ 共识-现实缺口: {ap.consensus_gap.gap_score:.0f}/100")
        print(f"   市场叙事: {ap.consensus_gap.market_narrative[:80]}...")
        print(f"   叙事强度: {ap.consensus_gap.narrative_intensity:.0%}")
        print(f"   夸大程度: {ap.consensus_gap.exaggeration_score:.0f}/100")
        if ap.consensus_gap.logical_flaws:
            print(f"   逻辑漏洞:")
            for flaw in ap.consensus_gap.logical_flaws:
                print(f"     ⚡ {flaw}")
        if ap.consensus_gap.contrarian_evidence:
            print(f"   反向证据:")
            for ev in ap.consensus_gap.contrarian_evidence:
                print(f"     🔄 {ev}")
        print(f"   Alpha 机会: {ap.consensus_gap.alpha_opportunity}")
        print(f"\n{'─' * 40}")
        print(f"📈 叙事生命周期: {ap.narrative.stage.value}")
        print(f"   阶段: {ap.narrative.stage.value}")
        print(f"   早期信号: {ap.narrative.early_signal_score:.0f}/100")
        print(f"   拥挤信号: {ap.narrative.crowded_signal_score:.0f}/100")
        print(f"   仓位上限: {ap.narrative.position_cap_pct:.0f}%")
        print(f"   操作提示: {ap.narrative.action_hint}")
        print(f"   估值反映度: {ap.narrative.valuation_reflected:.0%}")
        # 🆕 供应链深度 Alpha（紫苏叶理论）
        sc = ap.supply_chain
        print(f"\n{'─' * 40}")
        tier_icon = {"shiso_leaf": "🍃", "tuna": "🐟", "commodity": "📦"}
        tier_labels = {"shiso_leaf": "紫苏叶（上游隐蔽关键）", "tuna": "金枪鱼（终端显眼）", "commodity": "普通配料"}
        print(f"🔗 供应链深度 Alpha: {tier_icon.get(sc.shiso_tier.value, '📦')} {tier_labels.get(sc.shiso_tier.value, sc.shiso_tier.value)}")
        print(f"   所在层级: {sc.chain_layer or '未知'} (离终端 {sc.depth_from_end_demand} 层)")
        print(f"   不可替代性: {sc.irreplaceability_score:.0f}/100")
        print(f"   供应商集中度: {sc.supplier_concentration} 家 {'⚠️ 高度集中' if sc.supplier_concentration <= 3 else ''}")
        print(f"   下游切换成本: {sc.switching_cost}")
        print(f"   瓶颈类型: {sc.bottleneck_type} ({sc.bottleneck_score:.0f}/100)")
        if sc.is_shiso_leaf:
            print(f"   🍃 紫苏叶判定: 该标的是热门主题上游被忽视的关键环节")
        elif sc.is_tuna:
            print(f"   🐟 金枪鱼判定: 已被市场充分关注，Alpha 来自基本面超预期")
        print(f"   深度评分: {sc.depth_score:.0f}/100")
        print(f"   理由: {sc.rationale}")
        print(f"\n{'─' * 40}")
        print(f"💡 {ap.summary}")
    else:
        print("⚠️ Alpha Profile 不可用")

    # Pipeline results
    if result.game_theory_info:
        gt = result.game_theory_info
        print(f"\n🎲 博弈论分析: {gt.get('score', 0)}/100")
        print(f"   主导玩家: {gt.get('dominant_player', 'unknown')} | 市场状态: {gt.get('market_regime', 'unknown')}")
        print(f"   拥挤度: {gt.get('crowding_score', 0)} | 杠杆: {gt.get('margin_score', 0)} | 席位: {gt.get('seat_signal', 'unknown')}")
        if gt.get('risks'):
            for r in gt['risks'][:3]:
                print(f"   ⚠️ {r}")

    if result.mental_model_info:
        mm = result.mental_model_info
        print(f"\n🧠 投资思维模型匹配: {mm.get('fit_score', 0)}/100")
        print(f"   能力圈: {mm.get('competence_match', 'unknown')} | 风险偏好匹配: {mm.get('risk_profile_match', False)}")
        if mm.get('bias_flags'):
            for f in mm['bias_flags'][:3]:
                print(f"   ⚠️ {f}")

    if result.mental_models:
        print(f"\n🧩 Munger 思维模型推荐 ({len(result.mental_models)}):")
        for m in result.mental_models[:5]:
            print(f"   • {m.get('name_cn')} [{m.get('discipline')}]: {m.get('reason_for_match')}")

    if result.debate_result:
        dr = result.debate_result
        print(f"\n🎭 四视角辩论:")
        print(f"   平均分: {dr.get('avg_score', 0):.2f}/5 | 分歧度: {dr.get('score_range', 0):.2f}")
        print(f"   一致度: {dr.get('agreement_level', '')}")
        print(f"   综合建议: {dr.get('recommendation', '')}")
        if dr.get('top_disagreement'):
            print(f"   最大分歧: {dr.get('top_disagreement')}")

    if result.red_lines:
        print(f"\n🚨 红线检查: {', '.join(result.red_lines)}")

    if result.scenario_valuation:
        sv = result.scenario_valuation
        print(f"\n📐 三情景估值:")
        print(f"   乐观: {sv.get('bull_target')} | 基准: {sv.get('base_target')} | 悲观: {sv.get('bear_target')}")
        print(f"   隐含上涨: {sv.get('implied_upside', 0):+.1f}% | 隐含下跌: {sv.get('implied_downside', 0):+.1f}%")

    if result.enforced_verdict:
        ev = result.enforced_verdict
        print(f"\n⚖️ 强制结论: {ev.get('level')} | {ev.get('one_line_conclusion')}")
        if ev.get('is_abstain'):
            print(f"   弃权原因: {', '.join(ev.get('abstain_reasons', []))}")
        pr = ev.get('price_range', {})
        print(f"   价格区间: 当前 {pr.get('current_price')} / 买入≤{pr.get('buy_below')} / 卖出≥{pr.get('sell_above')}")

    if result.verdict:
        v = result.verdict
        print(f"\n📋 裁决: {v.score}/100 | 建议: {v.recommendation}")
        if v.alpha_rationale:
            print(f"   Alpha 理由: {v.alpha_rationale[:120]}...")
        if v.consensus_challenge:
            print(f"   共识挑战: {v.consensus_challenge}")
        print(f"   Alpha 乘数: {v.alpha_multiplier:.2f}x")
        if v.game_theory_risks:
            print(f"   博弈风险: {', '.join(v.game_theory_risks[:2])}")
        if v.mental_model_warnings:
            print(f"   心理模型警示: {', '.join(v.mental_model_warnings[:2])}")


@_safe_cmd
def cmd_alpha_scan(args: list[str]):
    """扫描高 Alpha 潜力股票。"""
    import argparse
    from src.alpha.lens import AlphaLens
    from src.data.aggregator import DataAggregator

    parser = argparse.ArgumentParser(description="扫描高 Alpha 潜力股票")
    parser.add_argument("--limit", type=int, default=10, help="返回数量上限")
    parser.add_argument("--min-alpha", type=float, default=50, help="最低 Alpha 评分")
    parsed = parser.parse_args(args)

    print(f"🔍 Alpha 潜力扫描 (min_alpha={parsed.min_alpha})")
    print("=" * 50)

    agg = DataAggregator()
    try:
        stocks = agg.scan_all_stocks() or []
    except Exception as e:
        print(f"⚠️ 扫描失败: {e}")
        return

    # ── 板块过滤 (P0) ──
    try:
        from src.learner.preference.loader import InvestorPreferenceLoader
        from src.learner.preference.adapter import resolve_board_filter
        loader = InvestorPreferenceLoader()
        board_ok = resolve_board_filter(loader.load())
        before = len(stocks)
        stocks = [s for s in stocks if board_ok(
            s.get("symbol", "") if isinstance(s, dict) else getattr(s, "symbol", ""))]
        if len(stocks) < before:
            accessible = loader.load().accessible_boards
            print(f"🔒 板块过滤: {before} → {len(stocks)} 只 "
                  f"(仅保留 {[b.value for b in accessible]})")
    except Exception:
        pass

    print(f"扫描范围: {len(stocks)} 只股票")

    # ── 主板过滤 ──
    def _is_main_board(symbol: str) -> bool:
        """主板: 上证60xxxx, 深证00xxxx/002xxx/003xxx"""
        if symbol.startswith('sh60'):
            return True
        if symbol.startswith('sz00') or symbol.startswith('sz002') or symbol.startswith('sz003'):
            return True
        return False

    stocks = [s for s in stocks if _is_main_board(
        s.get("symbol", "") if isinstance(s, dict) else getattr(s, "symbol", ""))]
    print(f"🔒 主板过滤后: {len(stocks)} 只")

    lens = AlphaLens()
    results: list[tuple[str, str, float, str]] = []

    import random
    sample_size = min(len(stocks), 500)
    sample = random.sample(stocks, sample_size)
    print(f"🎲 随机采样 {sample_size} 只进行分析...")
    for stock in sample:
        if isinstance(stock, dict):
            symbol = stock.get("symbol", "")
            name = stock.get("name", "")
        else:
            symbol = getattr(stock, "symbol", "")
            name = getattr(stock, "name", "")
        try:
            profile = lens.analyze(symbol=symbol)
            if profile.alpha_score >= parsed.min_alpha:
                results.append((
                    symbol, name, profile.alpha_score,
                    profile.narrative.stage.value,
                ))
        except Exception:
            continue

    results.sort(key=lambda x: x[2], reverse=True)
    results = results[:parsed.limit]

    if not results:
        print("⚠️ 无股票通过 Alpha 筛选")
        return

    print(f"\n🏆 前 {len(results)} 名:")
    for rank, (sym, name, score, stage) in enumerate(results, 1):
        emoji = {"dormant": "💤", "emerging": "⭐", "spreading": "📈",
                 "consensus": "⚠️", "crowded": "🚨", "fading": "📉"}
        stage_cn = {"dormant": "休眠期", "emerging": "萌芽期", "spreading": "扩散期",
                     "consensus": "共识期", "crowded": "拥挤期", "fading": "消退期"}
        print(
            f"  {rank:2d}. {sym} {name:<8s} "
            f"Alpha {score:.0f} | 叙事: {emoji.get(stage, '❓')} {stage_cn.get(stage, stage)}"
        )


@_safe_cmd
def cmd_alpha_decay(symbol: str):
    """查看 Alpha 衰减状态。"""
    if not _validate_symbol(symbol):
        return
    from src.alpha.monitor import AlphaMonitor
    from src.routing.orchestrator import Orchestrator

    print(f"📉 Alpha 衰减追踪: {symbol}")
    print("=" * 50)

    orch = Orchestrator()
    result = orch.run(symbol, market=_infer_market(symbol))

    ap = result.alpha_profile
    if not ap:
        print("⚠️ Alpha Profile 不可用")
        return

    monitor = AlphaMonitor()
    monitor.track(symbol, ap)
    print(monitor.summary(symbol))

    # 衰减详情
    print(f"\n📊 衰减详情:")
    print(f"   状态: {ap.decay_status.value}")
    print(f"   首次检测: {ap.first_detected or '首次'}")
    print(f"   已追踪: {ap.days_since_detection} 天")
    print(f"   衰减速度: {ap.decay_rate:.2f}/天")

    # 拥挤检测
    is_crowded, msg = monitor.detect_crowding(
        symbol,
        discussion_volume=ap.narrative.discussion_volume,
        discussion_growth_rate=ap.narrative.discussion_growth_rate,
        retail_attention=ap.narrative.retail_attention,
        institutional_attention=ap.narrative.institutional_attention,
    )
    if is_crowded:
        print(f"\n🚨 拥挤警告: {msg}")
    elif msg:
        print(f"\n⚠️ 关注信号: {msg}")

    if ap.is_priced_in:
        print(f"\n💀 Alpha 已基本消失 — {ap.summary}")


@_safe_cmd
def cmd_factor_backtest(args: list[str]):
    """单因子回测 — IC/IR/分层收益。"""
    import argparse
    from src.alpha.factor_backtest import FactorBacktestEngine
    from src.factors.registry import get_default_registry

    parser = argparse.ArgumentParser(description="单因子回测")
    parser.add_argument("alpha_id", help="因子 ID（如 pb_factor）")
    parser.add_argument("--start", default="2024-01-01", help="起始日 YYYY-MM-DD")
    parser.add_argument("--end", default="2024-12-31", help="终止日 YYYY-MM-DD")
    parser.add_argument("--symbols", nargs="*", help="股票池（默认全市场）")
    parsed = parser.parse_args(args)

    reg = get_default_registry()
    available = reg.list()
    if parsed.alpha_id not in available:
        print(f"⚠️ 因子 '{parsed.alpha_id}' 不在注册表中")
        print(f"可用因子 ({len(available)}): {', '.join(available[:10])}...")
        return

    print(f"🔬 因子回测: {parsed.alpha_id}")
    print(f"   区间: {parsed.start} → {parsed.end}")
    print("=" * 50)

    engine = FactorBacktestEngine()
    result = engine.run(
        parsed.alpha_id,
        parsed.start,
        parsed.end,
        symbols=parsed.symbols or None,
    )

    print(f"\n📊 回测结果 ({result.n_periods} 期, 均{result.n_stocks_avg:.0f}只):")
    print(f"   Rank IC:      {result.ic_mean:+.4f} ± {result.ic_std:.4f}")
    print(f"   ICIR:          {result.icir:.2f}")
    print(f"   IC>0 比例:     {result.ic_positive_ratio:.1%}")
    print(f"   t 统计量:      {result.ic_t_stat:.2f}")
    print(f"   Top 分位年化:  {result.top_quintile_return:+.2%}")
    print(f"   Bottom 分位年化:{result.bottom_quintile_return:+.2%}")
    print(f"   多空年化:      {result.long_short_return:+.2%} (夏普 {result.long_short_sharpe:.2f})")
    print(f"   平均换手率:    {result.avg_turnover:.1%}")
    print(f"   IC 衰减(20d):  {result.ic_decay_20d:+.4f}")
    print(f"   稳定性:        {result.stability_score:.0f}/100")
    print(f"   分类:          {result.category}")
    print(f"\n   结论: {'✅ 有效' if result.is_effective else '❌ 无效'} — {result.summary}")
    if result.warnings:
        print(f"   ⚠️ 警告: {'; '.join(result.warnings)}")


@_safe_cmd
def cmd_factor_scan(args: list[str]):
    """扫描所有因子绩效 — 按 ICIR 排序。"""
    import argparse
    from src.alpha.factor_backtest import FactorBacktestEngine
    from src.alpha.schema import FactorScanResult
    from src.factors.registry import get_default_registry

    parser = argparse.ArgumentParser(description="因子绩效扫描")
    parser.add_argument("--min-icir", type=float, default=0.2, help="最低 ICIR 阈值")
    parser.add_argument("--start", default="2024-01-01", help="起始日 YYYY-MM-DD")
    parser.add_argument("--end", default="2024-12-31", help="终止日 YYYY-MM-DD")
    parser.add_argument("--category", help="因子分类筛选 (value/quality/growth/technical/crowding/flow/volatility/reversal/expectation)")
    parsed = parser.parse_args(args)

    reg = get_default_registry()
    all_alphas = reg.list()

    if parsed.category:
        all_alphas = [a for a in all_alphas if reg.get(a).meta.category == parsed.category]

    print(f"🔍 因子绩效扫描 ({len(all_alphas)} 个因子)")
    print(f"   区间: {parsed.start} → {parsed.end} | 最低 ICIR: {parsed.min_icir}")
    if parsed.category:
        print(f"   分类: {parsed.category}")
    print("=" * 60)

    engine = FactorBacktestEngine()
    scan = FactorScanResult()

    for alpha_id in all_alphas:
        try:
            r = engine.run(alpha_id, parsed.start, parsed.end)
            scan.results.append(r)
        except Exception as exc:
            print(f"  ⚠️ {alpha_id}: 回测失败 ({exc})")

    # 排序
    scan.results.sort(key=lambda r: r.icir, reverse=True)
    scan.top_by_icir = [r.alpha_id for r in scan.results[:5] if r.is_effective]
    scan.top_by_sharpe = sorted(
        [r for r in scan.results if r.is_effective],
        key=lambda r: r.long_short_sharpe, reverse=True
    )[:5]
    scan.top_by_sharpe = [r.alpha_id for r in scan.top_by_sharpe]

    print(f"\n{'排名':<4} {'因子ID':<30} {'IC均值':>8} {'ICIR':>6} {'多空收益':>10} {'换手率':>8} {'稳定性':>6} {'有效'}")
    print("-" * 80)
    for rank, r in enumerate(scan.results, 1):
        if r.icir < parsed.min_icir:
            continue
        print(
            f"{rank:<4} {r.alpha_id:<30} "
            f"{r.ic_mean:>+7.4f} "
            f"{r.icir:>6.2f} "
            f"{r.long_short_return:>+9.2%} "
            f"{r.avg_turnover:>7.1%} "
            f"{r.stability_score:>5.0f} "
            f"{'✅' if r.is_effective else '❌'}"
        )

    print(f"\n🏆 Top by ICIR: {', '.join(scan.top_by_icir) if scan.top_by_icir else '无'}")
    print(f"🏆 Top by Sharpe: {', '.join(scan.top_by_sharpe) if scan.top_by_sharpe else '无'}")


@_safe_cmd
def cmd_alpha_rank(args: list[str]):
    """全市场 Alpha 排名。"""
    import argparse
    from src.alpha.ranking_engine import RankingEngine
    from src.alpha.schema import SynthesisMethod
    from src.factors.registry import get_default_registry

    parser = argparse.ArgumentParser(description="全市场 Alpha 排名")
    parser.add_argument("--factors", nargs="+", help="因子列表（默认用所有有效因子）")
    parser.add_argument("--method", choices=["equal_weight", "icir_weight", "optimized"],
                        default="icir_weight", help="合成方法")
    parser.add_argument("--limit", type=int, default=30, help="返回数量")
    parsed = parser.parse_args(args)

    # 默认因子列表
    if parsed.factors:
        alpha_ids = parsed.factors
    else:
        reg = get_default_registry()
        alpha_ids = reg.list()
        # 取各类别的代表性因子
        preferred = [a for a in alpha_ids
                     if reg.get(a).meta.category in ("value", "quality", "growth", "momentum",
                                                      "reversal", "volatility", "flow")]
        alpha_ids = preferred[:12] if preferred else alpha_ids[:12]

    print(f"🏆 全市场 Alpha 排名")
    print(f"   因子: {', '.join(alpha_ids[:8])}{'...' if len(alpha_ids) > 8 else ''}")
    print(f"   方法: {parsed.method} | Top {parsed.limit}")
    print("=" * 60)

    engine = RankingEngine()
    result = engine.rank_all(
        alpha_ids,
        limit=parsed.limit,
        method=SynthesisMethod(parsed.method),
    )

    if result.synthesis:
        print(f"\n📊 合成配置:")
        print(f"   方法: {result.synthesis.method.value}")
        print(f"   预期 ICIR: {result.synthesis.expected_icir:.2f}")
        if result.synthesis.warnings:
            print(f"   ⚠️ {', '.join(result.synthesis.warnings)}")

    if result.data_gaps:
        print(f"\n⚠️ 数据缺口: {'; '.join(result.data_gaps)}")
        return

    print(f"\n扫描 {result.total_scanned} 只 → 通过 {result.total_passed} 只\n")

    if not result.stocks:
        print("⚠️ 无股票通过筛选")
        return

    print(f"{'排名':<4} {'代码':<10} {'名称':<10} {'综合得分':>8} {'市值(亿)':>10}")
    print("-" * 50)
    for stock in result.stocks:
        mcap_yi = stock.market_cap / 1e8 if stock.market_cap > 0 else 0
        print(
            f"{stock.rank:<4} {stock.symbol:<10} {stock.name:<10} "
            f"{stock.composite_score:>8.1f} {mcap_yi:>10.1f}"
        )


@_safe_cmd
def cmd_sector_research(args: list[str]):
    """行业深度研究 — 全景研报（分类+竞争+估值+催化剂+供应链）。"""
    import argparse
    from src.industry.classifier import SectorClassifier
    from src.industry.research import SectorResearchReporter

    parser = argparse.ArgumentParser(description="行业深度研究")
    parser.add_argument("sector", help="申万一级行业名称（如 食品饮料、半导体）")
    parser.add_argument("--pe", type=float, help="当前行业 PE（可选）")
    parsed = parser.parse_args(args)

    classifier = SectorClassifier()
    sectors = classifier.list_sectors()

    # 模糊匹配
    matched = [s for s in sectors if parsed.sector in s]
    if not matched:
        print(f"⚠️ 未找到行业 '{parsed.sector}'")
        print(f"可用行业: {', '.join(sectors[:10])}...")
        return

    sector_name = matched[0] if len(matched) == 1 else parsed.sector
    print(f"🏭 行业深度研究: {sector_name}")
    print("=" * 60)

    reporter = SectorResearchReporter()
    report = reporter.generate(sector_name, current_pe=parsed.pe)

    # 分类
    print(f"\n📋 行业分类: {report.sector.sw1_name}")
    print(f"   基准指数: {report.sector.benchmark_index}")

    # 竞争格局
    if report.competition:
        c = report.competition
        print(f"\n⚔️ 竞争格局:")
        print(f"   CR5: {c.cr5:.0f}% | HHI: {c.hhi:.0f} | {c.concentration_label}")
        print(f"   进入壁垒: {c.entry_barrier.value} ({', '.join(c.barrier_factors[:3])})")
        print(f"   竞争烈度: {c.competition_intensity:.0f}/100")
        print(f"   行业护城河潜力: {c.moat_potential:.0f}/100")

    # 估值
    if report.valuation:
        v = report.valuation
        print(f"\n💰 估值框架:")
        print(f"   主要方法: {v.primary_method.value}")
        if v.secondary_methods:
            print(f"   辅助方法: {', '.join(m.value for m in v.secondary_methods)}")
        print(f"   历史 PE 中枢: {v.historical_pe_median:.0f} (P25: {v.historical_pe_p25:.0f}, P75: {v.historical_pe_p75:.0f})")
        if parsed.pe:
            print(f"   当前 PE: {parsed.pe:.1f} (分位: {v.current_pe_percentile:.0f}%)")
            print(f"   估值吸引力: {v.valuation_score:.0f}/100")

    # 催化剂
    print(f"\n🚀 催化剂 (强度: {report.catalyst_score:.0f}/100):")
    for cat in report.catalysts[:5]:
        print(f"   • {cat}")

    # 政策
    print(f"\n📜 政策影响: {report.policy_impact:+.0f}/100")
    for note in report.policy_notes[:3]:
        print(f"   • {note}")

    # 代表标的
    if report.representative_stocks:
        print(f"\n📌 代表标的: {', '.join(report.representative_stocks[:5])}")

    # 景气度
    print(f"\n📊 行业景气度: {report.prosperity_score:.0f}/100 ({report.prosperity_trend})")

    # 综合
    print(f"\n{'='*60}")
    print(f"🏆 综合行业评分: {report.overall_score:.0f}/100")
    print(f"   置信度: {report.confidence:.2f}")
    if report.data_gaps:
        print(f"   ⚠️ {'; '.join(report.data_gaps)}")


@_safe_cmd
def cmd_deep_research(args: list[str]):
    """公司深度研究 — 护城河+红旗+DCF+管理层+一致预期。"""
    import argparse
    from src.fundamental.research import CompanyDeepResearcher

    parser = argparse.ArgumentParser(description="公司深度研究")
    parser.add_argument("symbol", help="股票代码")
    parser.add_argument("--name", default="", help="公司名称")
    parser.add_argument("--fcf", type=float, default=0, help="自由现金流（亿元）")
    parser.add_argument("--price", type=float, default=0, help="当前股价")
    parser.add_argument("--growth", type=float, default=0.08, help="FCF 增长率")
    parser.add_argument("--shares", type=float, default=None, help="总股本（亿股）")
    parser.add_argument("--debt", type=float, default=0, help="净债务（亿元）")
    parsed = parser.parse_args(args)

    symbol = parsed.symbol
    print(f"🔬 公司深度研究: {symbol} {parsed.name}")
    print("=" * 60)

    researcher = CompanyDeepResearcher()
    report = researcher.generate(
        symbol, name=parsed.name,
        free_cashflow=parsed.fcf * 1e8 if parsed.fcf > 0 else 0,
        current_price=parsed.price,
        growth_rate=parsed.growth,
        shares_outstanding=parsed.shares * 1e8 if parsed.shares else None,
        net_debt=parsed.debt * 1e8 if parsed.debt > 0 else 0,
    )

    # 护城河
    if report.moat:
        m = report.moat
        print(f"\n🏰 护城河: {m.overall_width.value} ({m.moat_score:.0f}/100)")
        print(f"   品牌: {m.dimensions.get('brand', 50):.0f}  转换成本: {m.dimensions.get('switching_cost', 50):.0f}")
        print(f"   网络效应: {m.dimensions.get('network_effect', 50):.0f}  规模经济: {m.dimensions.get('scale_economy', 50):.0f}")
        print(f"   无形资产: {m.dimensions.get('intangible', 50):.0f}  趋势: {m.moat_trend}")
        if m.key_evidence:
            print(f"   关键证据: {'; '.join(m.key_evidence[:3])}")
        if m.threats:
            print(f"   威胁: {'; '.join(m.threats[:3])}")

    # 财务红旗
    if report.red_flags:
        rf = report.red_flags
        print(f"\n🚩 财务红旗: {rf.overall_risk.upper()} ({rf.total_flags} 个)")
        if rf.m_score is not None:
            print(f"   M-Score: {rf.m_score:.2f} ({rf.m_score_risk})")
        if rf.f_score is not None:
            print(f"   F-Score: {rf.f_score:.0f}/9 ({rf.f_score_quality})")
        for flag in rf.flags[:5]:
            print(f"   [{flag.severity.value}] {flag.name}: {flag.description}")

    # DCF 估值
    if report.dcf and report.dcf.fair_value > 0:
        d = report.dcf
        print(f"\n💎 DCF 估值:")
        print(f"   公允价值: ¥{d.fair_value:.2f}")
        if d.current_price > 0:
            print(f"   当前价格: ¥{d.current_price:.2f}")
            print(f"   上行空间: {d.upside_pct:+.1%}")
            print(f"   安全边际: {d.margin_of_safety:.1%}")
        print(f"   三情景: 熊¥{d.bear_case:.1f} / 基¥{d.base_case:.1f} / 牛¥{d.bull_case:.1f}")
        print(f"   假设: WACC={d.wacc:.1%}, 终值增速={d.terminal_growth:.1%}, {d.projection_years}年")

    # 管理层
    if report.management:
        mgmt = report.management
        print(f"\n👔 管理层: {mgmt.overall_score:.0f}/100")
        print(f"   资本配置: {mgmt.capital_allocation:.0f}  诚信: {mgmt.integrity_score:.0f}")
        print(f"   专业能力: {mgmt.competency_score:.0f}  激励对齐: {mgmt.incentive_alignment:.0f}")
        if mgmt.insider_ownership_pct > 0:
            print(f"   内部人持股: {mgmt.insider_ownership_pct:.1f}%")

    # 一致预期
    if report.consensus and report.consensus.n_analysts > 0:
        c = report.consensus
        print(f"\n📋 分析师一致预期 ({c.n_analysts} 位):")
        print(f"   评级: {c.consensus_rating} (买{c.buy_count}/持{c.hold_count}/卖{c.sell_count})")
        print(f"   目标价: ¥{c.target_price_mean:.1f} (区间 ¥{c.target_price_low:.0f}-{c.target_price_high:.0f})")
        print(f"   趋势: 评级{c.rating_trend} / EPS修正{c.eps_revision_trend}")

    # 投资逻辑
    print(f"\n💡 投资逻辑: {report.investment_thesis}")
    if report.key_risks:
        print(f"⚠️ 关键风险: {'; '.join(report.key_risks[:5])}")
    if report.data_gaps:
        print(f"⚠️ 数据缺口: {'; '.join(report.data_gaps)}")

    # 综合
    print(f"\n{'='*60}")
    print(f"🏆 综合评分: {report.overall_score:.0f}/100 | 置信度: {report.confidence:.2f}")


def cmd_trade_track(args: list[str]):
    """交易记录管理 — 录入/查看/删除交易记录，用于凯利公式仓位计算。

    用法:
      python -m src.cli trade-track add <symbol> <entry_date> <exit_date> <entry_price> <exit_price> [--shares N] [--notes ...]
      python -m src.cli trade-track list [symbol]
      python -m src.cli trade-track kelly [symbol]        # 查看凯利参数
      python -m src.cli trade-track remove <symbol> <idx>
    """
    import argparse
    from src.kelly.tracker import TradeTracker, TradeRecord

    parser = argparse.ArgumentParser(description="交易记录管理")
    parser.add_argument("action", nargs="?",
                        choices=["add", "list", "kelly", "remove"],
                        default="list", help="操作类型")
    parsed, remaining = parser.parse_known_args(args)

    tracker = TradeTracker()

    if parsed.action == "add":
        add_parser = argparse.ArgumentParser(description="录入交易记录")
        add_parser.add_argument("symbol", help="股票代码")
        add_parser.add_argument("entry_date", help="买入日期 YYYY-MM-DD")
        add_parser.add_argument("exit_date", help="卖出日期 YYYY-MM-DD")
        add_parser.add_argument("entry_price", type=float, help="买入价格")
        add_parser.add_argument("exit_price", type=float, help="卖出价格")
        add_parser.add_argument("--shares", type=int, default=0, help="股数")
        add_parser.add_argument("--direction", choices=["LONG", "SHORT"], default="LONG")
        add_parser.add_argument("--notes", type=str, default="", help="备注")
        try:
            a = add_parser.parse_args(remaining)
        except SystemExit:
            return

        record = TradeRecord(
            symbol=a.symbol,
            entry_date=a.entry_date,
            exit_date=a.exit_date,
            entry_price=a.entry_price,
            exit_price=a.exit_price,
            shares=a.shares,
            direction=a.direction,
            notes=a.notes,
        )
        tracker.track(record)
        ret = record.return_pct
        print(f"✅ 已录入: {a.symbol} {a.entry_date}→{a.exit_date} "
              f"{'🟢' if record.is_win else '🔴'} {ret:+.2%}"
              f"{' (sizing: ' + a.notes + ')' if a.notes else ''}")

    elif parsed.action == "list":
        if remaining:
            symbol = remaining[0]
            trades = tracker.get_trades(symbol)
            if not trades:
                print(f"📭 {symbol} 暂无交易记录")
                return
            print(f"\n📊 {symbol} 交易记录 ({len(trades)}笔):")
            print(f"{'idx':>3} {'买入':>10} {'卖出':>10} {'成本':>8} {'现价':>8} {'收益':>8} {'结果':>4}")
            print("-" * 60)
            for i, t in enumerate(trades):
                print(f"{i:>3} {t.entry_date:>10} {t.exit_date:>10} {t.entry_price:>8.2f} "
                      f"{t.exit_price:>8.2f} {t.return_pct:>+7.2%} {'WIN' if t.is_win else 'LOSS':>4}")
        else:
            symbols = tracker.get_all_symbols()
            if not symbols:
                print("📭 暂无任何交易记录。使用 trade-track add 录入。")
                return
            print(tracker.summary())

    elif parsed.action == "kelly":
        from src.kelly.sizer import KellyPositionSizer
        sizer = KellyPositionSizer(tracker)

        if remaining:
            symbol = remaining[0]
            kp = tracker.get_kelly_params(symbol)
            if kp.n_trades == 0:
                print(f"📭 {symbol} 暂无交易记录")
                return
            result = sizer.calc(symbol, score=70, macro_cap=0.80)
            print(f"\n📊 {symbol} 凯利参数:")
            print(f"   交易笔数: {kp.n_trades}")
            print(f"   胜率 (p): {kp.win_rate:.1%}")
            print(f"   盈亏比 (b): {kp.payoff_ratio:.2f}")
            print(f"   累计收益: {kp.total_return_pct:+.2f}%")
            print(f"   凯利 f*: {'N/A (冷启动)' if not kp.is_hot else f'{kp.kelly_f:.1%}'}")
            print(f"   仓位建议: {result.target_weight:.1%} ({result.method})")
            print(f"   来源: {result.source_citation}")
        else:
            print(tracker.summary())

    elif parsed.action == "remove":
        if len(remaining) < 2:
            print("用法: trade-track remove <symbol> <index>")
            return
        symbol = remaining[0]
        try:
            idx = int(remaining[1])
        except ValueError:
            print(f"无效的索引: {remaining[1]}")
            return
        if tracker.remove_trade(symbol, idx):
            print(f"✅ 已删除: {symbol} 第 {idx} 笔交易")
        else:
            print(f"❌ 删除失败: {symbol} 索引 {idx} 不存在")


def cmd_evolution(args: list[str]):
    """策略进化模块 — 论文驱动的策略进化与全生命周期管理。"""
    sub = args[0] if args else "help"
    sub_args = args[1:]

    subcommands = {
        "import": _evolve_import,
        "list": _evolve_list,
        "status": _evolve_status,
        "promote": _evolve_promote,
        "degrade": _evolve_degrade,
        "retire": _evolve_retire,
        "optimize": _evolve_optimize,
        "proposals": _evolve_proposals,
        "monitor": _evolve_monitor,
        "report": _evolve_report,
    }

    handler = subcommands.get(sub)
    if handler:
        handler(sub_args)
    else:
        print(f"未知 evolution 子命令: {sub}")
        print("可用: " + ", ".join(subcommands.keys()))
        print("用法: python -m src.cli evolution <子命令> [参数]")


def _evolve_import(args: list[str]):
    """导入论文URL。"""
    import argparse
    parser = argparse.ArgumentParser(description="导入论文")
    parser.add_argument("url", nargs="?", help="论文URL")
    parser.add_argument("--type", choices=["auto", "manual"], default="auto",
                        help="导入方式 (默认: auto)")
    parser.add_argument("--desc", type=str, default="", help="手动导入时的策略描述")
    parsed = parser.parse_args(args)

    from src.evolution import PaperImporter, LifecycleManager, LifecycleState

    importer = PaperImporter()
    manager = LifecycleManager()

    if parsed.type == "manual":
        if not parsed.desc:
            print("手动模式需要 --desc 参数")
            return
        paper = importer.import_from_text(parsed.desc)
    elif parsed.url:
        print(f"📥 导入论文: {parsed.url}")
        paper = importer.import_from_url(parsed.url)
    else:
        print("请提供论文URL或使用 --type manual --desc")
        return

    print(f"\n📄 {paper.title}")
    print(f"   分类: {paper.paper_type.value} (置信度 {paper.classification_confidence:.0%})")

    if paper.paper_type.value == "strategy":
        from src.evolution import StrategyExtractor
        extractor = StrategyExtractor()
        strategy = extractor.extract(paper)
        paper.extracted_strategy = strategy

        lc = manager.create(
            paper_id=paper.id,
            strategy_name=strategy.strategy_name,
            state=LifecycleState.EXTRACTED,
        )
        print(f"\n🧬 策略: {strategy.strategy_name}")
        print(f"   类型: {strategy.strategy_type}")
        print(f"   参数: {len(strategy.parameters)} 个")
        print(f"   买入条件: {len(strategy.entry_conditions)} 条")
        print(f"   卖出条件: {len(strategy.exit_conditions)} 条")
        print(f"   提取置信度: {strategy.extraction_confidence:.0%}")
        print(f"   生命周期ID: {lc.id}")
        if strategy.unsourced_fields:
            print(f"   ⚠️ [UNSOURCED]: {', '.join(strategy.unsourced_fields)}")

    elif paper.paper_type.value == "architecture":
        from src.evolution import ArchitectureAnalyzer, ProposalManager
        analyzer = ArchitectureAnalyzer()
        proposal = analyzer.analyze(paper)
        paper.extracted_proposal = proposal

        pm = ProposalManager()
        pm._proposals[proposal.id] = proposal
        pm._save()

        print(f"\n🏗️ 改进提案: {proposal.title}")
        print(f"   影响模块: {', '.join(proposal.target_modules)}")
        print(f"   提案ID: {proposal.id}")
    else:
        print("\n⚠️ 无法自动分类，请手动指定 --type")


def _evolve_list(args: list[str]):
    """列出所有进化策略。"""
    from src.evolution import LifecycleManager
    manager = LifecycleManager()
    lifecycles = manager.list_all()
    if not lifecycles:
        print("📭 暂无进化策略。使用 evolution import <url> 导入论文。")
        return

    print(manager.summary())
    print()
    for lc in lifecycles:
        emoji = {
            "extracted": "📄", "candidate": "⭐", "trial": "🧪",
            "active": "💰", "degraded": "⚠️", "optimizing": "🔧",
            "rejected": "❌", "retired": "🏁", "error": "💥",
        }.get(lc.state.value, "❓")
        print(f"  {emoji} {lc.id} | {lc.strategy_name} | {lc.state.value}")
        if lc.backtest_sharpe:
            print(f"     回测 Sharpe: {lc.backtest_sharpe:.2f}  {'✅' if lc.backtest_passed else '❌'}")
        if lc.trial_sharpe is not None:
            print(f"     模拟盘 Sharpe: {lc.trial_sharpe:.2f}  交易: {lc.trial_trades}笔")


def _evolve_status(args: list[str]):
    """查看策略详情。"""
    if not args:
        print("用法: evolution status <lifecycle_id>")
        return
    from src.evolution import LifecycleManager
    manager = LifecycleManager()
    lc = manager.get(args[0])
    if lc is None:
        print(f"生命周期不存在: {args[0]}")
        return
    print(f"📋 {lc.strategy_name} ({lc.id})")
    print(f"   状态: {lc.state.value}")
    print(f"   版本: {lc.strategy_version}")
    print(f"   创建: {lc.created_at}")
    if lc.backtest_sharpe:
        print(f"   回测: Sharpe {lc.backtest_sharpe:.2f}  收益 {lc.backtest_return:.1%}  MaxDD {lc.backtest_max_dd:.1%}  {'✅' if lc.backtest_passed else '❌'}")
    if lc.trial_sharpe is not None:
        print(f"   模拟盘: Sharpe {lc.trial_sharpe:.2f}  收益 {lc.trial_return:.1%}  MaxDD {lc.trial_max_dd:.1%}  交易{lc.trial_trades}笔")
    if lc.live_sharpe is not None:
        print(f"   实战: Sharpe {lc.live_sharpe:.2f}  收益 {lc.live_return:.1%}  MaxDD {lc.live_max_dd:.1%}")
    print(f"\n   状态历史:")
    for t in lc.state_history[-10:]:
        print(f"     {t.from_state.value} → {t.to_state.value} ({t.reason[:50]})")


def _evolve_promote(args: list[str]):
    """手动推进策略状态。"""
    if not args:
        print("用法: evolution promote <lifecycle_id> [--target state] [--force]")
        return
    import argparse
    parser = argparse.ArgumentParser(description="推进策略状态")
    parser.add_argument("lifecycle_id", help="生命周期ID")
    parser.add_argument("--target", choices=[s.value for s in LifecycleState], help="目标状态")
    parser.add_argument("--force", action="store_true", help="跳过条件检查")
    parsed = parser.parse_args(args)

    from src.evolution import LifecycleManager, TransitionRequest, LifecycleState as LS
    manager = LifecycleManager()
    lc = manager.get(parsed.lifecycle_id)
    if lc is None:
        print(f"生命周期不存在: {parsed.lifecycle_id}")
        return

    # 自动推断目标状态
    target_map = {
        LS.EXTRACTED: LS.CANDIDATE,
        LS.CANDIDATE: LS.TRIAL,
        LS.TRIAL: LS.ACTIVE,
        LS.DEGRADED: LS.OPTIMIZING,
    }
    target = LS(parsed.target) if parsed.target else target_map.get(lc.state)
    if target is None:
        print(f"无法从 {lc.state.value} 自动推进，请手动指定 --target")
        return

    resp = manager.transition(TransitionRequest(
        lifecycle_id=parsed.lifecycle_id,
        target_state=target,
        reason="用户手动推进",
        triggered_by="user",
        force=parsed.force,
    ))
    if resp.result.value == "ok":
        print(f"✅ {lc.state.value} → {resp.new_state.value if resp.new_state else target.value}")
    else:
        print(f"❌ {resp.message}")


def _evolve_degrade(args: list[str]):
    """手动降级策略。"""
    if not args:
        print("用法: evolution degrade <lifecycle_id> [--reason ...]")
        return
    reason = " ".join(args[1:]) if len(args) > 1 else "用户手动降级"

    from src.evolution import LifecycleManager, LifecycleState as LS, TransitionRequest
    manager = LifecycleManager()
    resp = manager.transition(TransitionRequest(
        lifecycle_id=args[0],
        target_state=LS.DEGRADED,
        reason=reason,
        triggered_by="user",
    ))
    if resp.result.value == "ok":
        print(f"✅ 已降级: {args[0]}")
    else:
        print(f"❌ {resp.message}")


def _evolve_retire(args: list[str]):
    """退役策略。"""
    if not args:
        print("用法: evolution retire <lifecycle_id> [--reason ...]")
        return
    reason = " ".join(args[1:]) if len(args) > 1 else "用户手动退役"

    from src.evolution import RollbackManager
    rollback = RollbackManager()
    record = rollback.retire(args[0], reason)
    if record:
        print(f"🏁 已退役: {args[0]}")
    else:
        print(f"❌ 退役失败")


def _evolve_optimize(args: list[str]):
    """触发策略自动优化。"""
    if not args:
        print("用法: evolution optimize <lifecycle_id>")
        return

    from src.evolution import LifecycleManager, LifecycleState as LS, TransitionRequest
    manager = LifecycleManager()
    # 先转为 DEGRADED → OPTIMIZING
    resp1 = manager.transition(TransitionRequest(
        lifecycle_id=args[0],
        target_state=LS.DEGRADED,
        reason="用户触发优化",
        triggered_by="user",
        force=True,
    ))
    if resp1.result.value != "ok":
        print(f"❌ {resp1.message}")
        return
    resp2 = manager.transition(TransitionRequest(
        lifecycle_id=args[0],
        target_state=LS.OPTIMIZING,
        reason="用户触发优化",
        triggered_by="user",
        force=True,
    ))
    if resp2.result.value == "ok":
        print(f"🔧 已触发优化: {args[0]}")
        print("(接入现有 EvolutionPipeline 进行参数优化)")
    else:
        print(f"❌ {resp2.message}")


def _evolve_proposals(args: list[str]):
    """管理改进提案。"""
    sub = args[0] if args else "list"
    sub_args = args[1:]

    from src.evolution import ProposalManager
    pm = ProposalManager()

    if sub == "list":
        proposals = pm.list_all()
        if not proposals:
            print("📭 暂无改进提案")
            return
        for p in proposals:
            emoji = {"draft": "📝", "pending_review": "⏳", "approved": "✅",
                     "rejected": "❌", "implementing": "🔧", "validating": "🧪",
                     "merged": "🏆", "closed": "📁"}.get(p.status.value, "❓")
            print(f"  {emoji} {p.id} | {p.status.value} | {p.title[:60]}")
    elif sub == "review":
        if not sub_args:
            print("用法: evolution proposals review <proposal_id> [approve|reject] [--note ...]")
            return
        import argparse
        parser = argparse.ArgumentParser(description="审核提案")
        parser.add_argument("proposal_id", help="提案ID")
        parser.add_argument("action", choices=["approve", "reject"], nargs="?", default="approve")
        parser.add_argument("--note", type=str, default="", help="审核备注")
        parsed = parser.parse_args(sub_args)
        if parsed.action == "approve":
            pm.approve(parsed.proposal_id, parsed.note)
            print(f"✅ 已批准: {parsed.proposal_id}")
        else:
            pm.reject(parsed.proposal_id, parsed.note)
            print(f"❌ 已驳回: {parsed.proposal_id}")
    elif sub == "apply":
        if not sub_args:
            print("用法: evolution proposals apply <proposal_id>")
            return
        pm.mark_implementing(sub_args[0])
        print(f"🔧 开始实施: {sub_args[0]}")
    elif sub == "compare":
        if not sub_args:
            print("用法: evolution proposals compare <proposal_id> [--old-sharpe X] [--new-sharpe Y] ...")
            return
        import argparse
        parser = argparse.ArgumentParser(description="A/B对比")
        parser.add_argument("proposal_id", help="提案ID")
        parser.add_argument("--old-sharpe", type=float, default=0.8)
        parser.add_argument("--new-sharpe", type=float, default=1.0)
        parser.add_argument("--old-return", type=float, default=0.25)
        parser.add_argument("--new-return", type=float, default=0.30)
        parser.add_argument("--old-maxdd", type=float, default=0.20)
        parser.add_argument("--new-maxdd", type=float, default=0.15)
        parsed = parser.parse_args(sub_args)

        from src.evolution import PipelineComparator
        comparator = PipelineComparator()
        result = comparator.compare_metrics(
            old_sharpe=parsed.old_sharpe,
            old_return=parsed.old_return,
            old_max_dd=parsed.old_maxdd,
            new_sharpe=parsed.new_sharpe,
            new_return=parsed.new_return,
            new_max_dd=parsed.new_maxdd,
        )
        print(result.report)
        if result.improved:
            pm.set_pipeline_metrics(parsed.proposal_id,
                                     {"sharpe_ratio": parsed.old_sharpe},
                                     {"sharpe_ratio": parsed.new_sharpe})
            pm.mark_merged(parsed.proposal_id, result.sharpe_improvement_pct)
    else:
        print(f"未知 proposals 子命令: {sub}，可用: list | review | apply | compare")


def _evolve_monitor(args: list[str]):
    """查看监控状态。"""
    from src.evolution import LifecycleManager, TrialRunner, TrialMonitor
    manager = LifecycleManager()
    runner = TrialRunner(manager)
    monitor = TrialMonitor(manager, runner)
    print(monitor.summary())


def _evolve_report(args: list[str]):
    """查看策略详细报告。"""
    if not args:
        print("用法: evolution report <lifecycle_id>")
        return
    from src.evolution import LifecycleManager
    manager = LifecycleManager()
    lc = manager.get(args[0])
    if lc is None:
        print(f"生命周期不存在: {args[0]}")
        return

    print(f"📊 策略报告: {lc.strategy_name}")
    print(f"   ID: {lc.id}")
    print(f"   论文: {lc.paper_id}")
    print(f"   状态: {lc.state.value}")
    print(f"   版本: {lc.strategy_version or 'N/A'}")
    print(f"   创建: {lc.created_at}")
    print(f"   更新: {lc.updated_at}")
    print()
    print("📈 回测:")
    print(f"   Sharpe: {lc.backtest_sharpe or 'N/A'}  收益: {lc.backtest_return or 'N/A'}  MaxDD: {lc.backtest_max_dd or 'N/A'}")
    print(f"   通过: {'✅' if lc.backtest_passed else '❌'}")
    print()
    print("🧪 模拟盘:")
    print(f"   Sharpe: {lc.trial_sharpe or 'N/A'}  收益: {lc.trial_return or 'N/A'}  MaxDD: {lc.trial_max_dd or 'N/A'}")
    print(f"   交易笔数: {lc.trial_trades}  通过: {'✅' if lc.trial_passed else '❌'}")
    if lc.trial_started_at:
        print(f"   开始: {lc.trial_started_at}")
    print()
    print("💰 实战:")
    print(f"   Sharpe: {lc.live_sharpe or 'N/A'}  收益: {lc.live_return or 'N/A'}  MaxDD: {lc.live_max_dd or 'N/A'}")
    if lc.active_started_at:
        print(f"   开始: {lc.active_started_at}")
    print()
    print("📜 状态历史:")
    for t in lc.state_history:
        print(f"   {t.timestamp[:19]}  {t.from_state.value} → {t.to_state.value}  [{t.triggered_by}] {t.reason[:60]}")


# ------------------------------------------------------------------
# 盯盘: 自选股扫雷 + 预警管理 + 恐慌套利
# ------------------------------------------------------------------

DEFAULT_WATCHLIST_PATH = "data/watchlist.json"


def _load_watchlist(path: str = DEFAULT_WATCHLIST_PATH) -> list[dict]:
    """加载自选股列表。"""
    import json
    try:
        with open(path, "r") as f:
            data = json.load(f)
        return data.get("stocks", [])
    except FileNotFoundError:
        return []
    except Exception as e:
        print(f"⚠️ 自选股文件读取失败: {e}")
        return []


def _save_watchlist(stocks: list[dict], path: str = DEFAULT_WATCHLIST_PATH):
    """保存自选股列表。"""
    import json
    os.makedirs(os.path.dirname(path) or "data", exist_ok=True)
    with open(path, "w") as f:
        json.dump({"stocks": stocks, "updated_at": datetime.now().isoformat()},
                  f, ensure_ascii=False, indent=2)


@_safe_cmd
def cmd_position_monitor(args: list[str]):
    """持仓监控 — 检查所有开仓头寸的状态和动态止损。

    用法:
      python -m src position-monitor status          # 查看所有持仓摘要
      python -m src position-monitor check           # 实时拉取价格并更新/检查止损
      python -m src position-monitor detail <code>   # 查看单票详情
      python -m src position-monitor close <code>    # 手动清除持仓状态
    """
    import argparse
    from src.routing.position_state import (
        PositionStateManager, StopStage, StopAlert, DynamicStopCalculator,
    )

    parser = argparse.ArgumentParser(description="持仓状态监控")
    parser.add_argument("action", nargs="?", default="status",
                        choices=["status", "check", "detail", "close", "list"],
                        help="status=摘要 check=实时检查 detail=<code> close=<code>")
    parser.add_argument("symbol", nargs="?", default="", help="股票代码 (detail/close 时使用)")
    parsed, _remaining = parser.parse_known_args(args)

    mgr = PositionStateManager()

    if parsed.action in ("status", "list"):
        positions = mgr.get_all()
        if not positions:
            print("📭 暂无开仓头寸。使用 position-monitor check 检查。")
            return
        print(f"\n📊 持仓监控 ({len(positions)} 只开仓):")
        header = (
            f"{'标的':<10s} {'方向':<6s} {'入场价':>8s} {'最新价':>8s} "
            f"{'浮盈%':>8s} {'max浮盈%':>9s} {'阶段':<12s} {'止损价':>8s} {'距止损%':>8s}"
        )
        print(header)
        print("-" * 90)
        for p in sorted(positions, key=lambda x: x.max_favor_pct, reverse=True):
            dist_pct = (
                f"{(p.last_price - p.stop_price) / p.last_price * 100:.1f}%"
                if p.last_price > 0 and p.stop_price > 0 else "N/A"
            )
            stage_icon = {
                StopStage.INITIAL: "🟡 初始",
                StopStage.BREAKEVEN: "🟢 保本",
                StopStage.TRAILING: "🔵 追踪",
            }
            print(
                f"{p.symbol:<10s} {p.direction:<6s} {p.entry_price:>8.2f} {p.last_price:>8.2f} "
                f"{p.unrealized_pnl_pct*100:>7.1f}% {p.max_favor_pct*100:>8.1f}% "
                f"{stage_icon.get(p.stop_stage, p.stop_stage.value):<12s} "
                f"{p.stop_price:>8.2f} {dist_pct:>8s}"
            )

        # 汇总统计
        trailing_count = sum(1 for p in positions if p.stop_stage == StopStage.TRAILING)
        breakeven_count = sum(1 for p in positions if p.stop_stage == StopStage.BREAKEVEN)
        initial_count = sum(1 for p in positions if p.stop_stage == StopStage.INITIAL)
        print(f"\n   阶段分布: 🟡初始 {initial_count}  |  🟢保本 {breakeven_count}  |  🔵追踪 {trailing_count}")

    elif parsed.action == "check":
        from src.data.aggregator import DataAggregator
        agg = DataAggregator()
        positions = mgr.get_all()
        if not positions:
            print("📭 暂无开仓头寸。")
            return
        total_alerts = 0
        for p in positions:
            try:
                q = agg.get_quote(p.symbol)
                if q and q.price:
                    _, alerts = mgr.update_price(p.symbol, float(q.price))
                    for a in alerts:
                        icon = {"CRITICAL": "🚨", "WARNING": "⚠️", "INFO": "ℹ️"}.get(a.severity, "📌")
                        print(f"  {icon} [{a.severity}] {p.symbol} {p.name}: {a.message}")
                        total_alerts += 1
                else:
                    print(f"  ⚠️ {p.symbol}: 行情获取失败")
            except Exception as e:
                print(f"  ⚠️ {p.symbol}: {e}")
        print(f"\n✅ 检查完成。{total_alerts} 条预警。")

    elif parsed.action == "detail":
        sym = parsed.symbol
        if not sym:
            print("用法: python -m src position-monitor detail <code>")
            return
        p = mgr.get(sym)
        if not p:
            print(f"📭 持仓未找到: {sym}")
            return
        print(f"\n📋 持仓详情: {p.symbol}")
        print("=" * 40)
        print(f"   名称: {p.name}")
        print(f"   方向: {p.direction}")
        print(f"   入场价: {p.entry_price:.2f} ({p.entry_date.isoformat()[:10]})")
        print(f"   数量: {p.quantity}")
        print(f"   最高价: {p.high_price:.2f}")
        print(f"   最低价: {p.low_price:.2f}")
        print(f"   最新价: {p.last_price:.2f}")
        print(f"   浮盈: {p.unrealized_pnl_pct*100:.1f}%")
        print(f"   最大浮盈: {p.max_favor_pct*100:.1f}%")
        print(f"   最大浮亏: {p.max_adversity_pct*100:.1f}%")
        stage_icon = {
            StopStage.INITIAL: "🟡 INITIAL",
            StopStage.BREAKEVEN: "🟢 BREAKEVEN",
            StopStage.TRAILING: "🔵 TRAILING",
        }
        print(f"   止损阶段: {stage_icon.get(p.stop_stage, p.stop_stage.value)}")
        print(f"   止损价: {p.stop_price:.2f}")
        print(f"   止损备注: {p.stop_note or '(无)'}")
        print(f"\n   配置:")
        print(f"     初始止损%: {p.initial_stop_pct*100:.0f}%")
        print(f"     保本触发: {p.breakeven_trigger_pct*100:.0f}% (r019)")
        print(f"     追踪触发: {p.trailing_trigger_pct*100:.0f}% (r028)")
        print(f"     追踪回撤: {p.trailing_stop_pct*100:.0f}%")
        print(f"     ATR倍率: {p.atr_multiplier:.1f}")

    elif parsed.action == "close":
        sym = parsed.symbol
        if not sym:
            print("用法: python -m src position-monitor close <code>")
            return
        state = mgr.close(sym)
        if state:
            print(f"✅ 持仓状态已清除: {sym} (入场 {state.entry_price:.2f}, 最大浮盈 {state.max_favor_pct*100:.1f}%)")
        else:
            print(f"📭 持仓未找到: {sym}")


def _get_quotes_dict(aggregator, symbols: list[str]) -> dict[str, dict]:
    """批量获取实时行情，返回 {symbol: {name, price, ...}} 字典。

    用于 sweep / monitor 等批量行情查询，优先走免费 fallback 链。
    """
    result: dict[str, dict] = {}
    for sym in symbols:
        try:
            q = aggregator.get_quote(sym)
            if q:
                result[sym] = {
                    "name": q.name or sym,
                    "price": q.price or 0,
                    "volume": q.volume or 0,
                    "change_pct": q.change_pct or 0,
                    "high": q.high or 0,
                    "low": q.low or 0,
                    "open": q.open or 0,
                    "prev_close": q.prev_close or 0,
                }
        except Exception:
            continue
    return result


@_safe_cmd
def cmd_sweep(args: list[str]):
    """自选股扫雷 — 检查所有自选股的价格预警、止损、异常波动。"""
    import argparse
    from src.data.aggregator import DataAggregator
    from src.output.alert import AlertManager
    from src.sentiment.panic_arb import PanicArbEngine

    parser = argparse.ArgumentParser(description="自选股扫雷")
    parser.add_argument("--watchlist", type=str, default=DEFAULT_WATCHLIST_PATH,
                        help="自选股文件路径 (JSON)")
    parser.add_argument("--panic", action="store_true", help="同时检查恐慌套利信号")
    parsed = parser.parse_args(args)

    watchlist = _load_watchlist(parsed.watchlist)
    if not watchlist:
        print("📭 自选股列表为空")
        print(f"   创建自选股: python -m src alert watch-add <symbol> [--name NAME] [--stop-price X]")
        return

    print(f"🔍 扫雷 {len(watchlist)} 只自选股...")
    print("=" * 50)

    # 获取行情
    agg = DataAggregator()
    symbols = [s["symbol"] for s in watchlist]
    quotes: dict[str, float] = {}
    context: dict[str, dict] = {}

    for s in watchlist:
        sym = s["symbol"]
        try:
            quote = agg.get_quote(sym)
            if quote:
                quotes[sym] = quote.price or 0
                context[sym] = {
                    "name": s.get("name", sym),
                    "stop_price": s.get("stop_price"),
                    "change_pct": getattr(quote, "change_pct", 0) or 0,
                    "volume_ratio": getattr(quote, "volume_ratio", 1.0) or 1.0,
                }
            else:
                context[sym] = {"name": s.get("name", sym), "error": "行情不可用"}
        except Exception:
            context[sym] = {"name": s.get("name", sym), "error": "获取失败"}

    # 运行扫雷
    mgr = AlertManager()
    for s in watchlist:
        sym = s["symbol"]
        if s.get("stop_price"):
            mgr.add_stop_loss_alert(sym, s.get("name", sym), s["stop_price"])
        if s.get("alert_above"):
            mgr.add_price_alert(sym, s.get("name", sym), above=s["alert_above"])
        if s.get("alert_below"):
            mgr.add_price_alert(sym, s.get("name", sym), below=s["alert_below"])

    alerts = mgr.check(quotes)
    sweep_alerts = mgr.scan_watchlist([s["symbol"] for s in watchlist], quotes, context)

    # 输出
    all_alerts = alerts + sweep_alerts
    if not all_alerts:
        print("✅ 无预警触发")
    else:
        critical = [a for a in all_alerts if a.severity == "CRITICAL"]
        warnings = [a for a in all_alerts if a.severity == "WARNING"]

        if critical:
            print(f"\n🚨 严重预警 ({len(critical)}):")
            for a in critical:
                print(f"  🔴 {a.alert_type}: {a.message}")
        if warnings:
            print(f"\n⚠️ 警告 ({len(warnings)}):")
            for a in warnings:
                print(f"  🟡 {a.alert_type}: {a.message}")

    # 概览
    print(f"\n📊 自选股概览:")
    print(f"{'代码':<8s} {'名称':<10s} {'最新价':>8s} {'涨跌幅':>8s} {'状态':<12s}")
    print("-" * 52)
    for s in watchlist:
        sym = s["symbol"]
        ctx = context.get(sym, {})
        price = quotes.get(sym)
        price_str = f"{price:.2f}" if price else "N/A"
        chg = ctx.get("change_pct", 0)
        chg_str = f"{chg:+.2f}%" if chg else "N/A"

        # 状态
        status = "正常"
        if ctx.get("error"):
            status = "⚠️ 数据缺失"
        elif s.get("stop_price") and price and price <= s["stop_price"]:
            status = "🚨 止损"
        elif chg and chg < -5:
            status = "⚠️ 大跌"
        elif chg and chg > 5:
            status = "📈 大涨"

        print(f"{sym:<8s} {s.get('name', sym):<10s} {price_str:>8s} {chg_str:>8s} {status:<12s}")

    # ── 融资融券监控 (v2.0) ────────────────────────────────────
    print(f"\n💰 融资融券监控:")
    try:
        from src.game_theory.margin import get_margin_analyzer
        ma = get_margin_analyzer()
        margin_warnings = []
        for s in watchlist:
            sym = s["symbol"]
            price = quotes.get(sym)
            try:
                alerts = ma.get_alerts(sym, s.get("name", sym), close_price=price or 0)
                if alerts:
                    margin_warnings.append((sym, s.get("name", sym), alerts))
            except Exception:
                continue

        if margin_warnings:
            for sym, name, alerts in margin_warnings:
                for a in alerts:
                    icon = "🔴" if a.severity == "high" else "🟡"
                    print(f"  {icon} {name}({sym}): {a.message[:80]}")
        else:
            profile_002460 = ma.analyze("002460", close_price=quotes.get("002460") or 0)
            if profile_002460.margin_balance:
                print(f"  📊 赣锋锂业: 融资余额{profile_002460.margin_balance:.1f}亿 "
                      f"| 趋势{profile_002460.margin_balance_trend} "
                      f"| 连续流出{profile_002460.consecutive_outflow_days}天")
            else:
                print("  ✅ 自选股无融资预警")
    except Exception as e:
        print(f"  ⚠️ 融资数据不可用: {e}")

    # ── Monitor Events 状态 (v2.0) ─────────────────────────────
    try:
        from src.monitor import MonitorStore, generate_monitor_signals
        mon_signals = generate_monitor_signals()
        triggered = [s for s in mon_signals if s.direction != "neutral"]
        active = [s for s in mon_signals if s.direction == "neutral"]
        if triggered or active:
            print(f"\n📡 Monitor Events: {len(triggered)}触发 | {len(active)}观测中")
            for sig in triggered[:5]:
                icon = "🔴" if sig.metadata.get("severity") == "high" else "🟡"
                print(f"  {icon} {sig.name}: {sig.description[:80]}")
    except Exception:
        pass

    # 恐慌套利
    if parsed.panic:
        print(f"\n🎯 恐慌套利检查:")
        panic_engine = PanicArbEngine()
        for s in watchlist:
            sym = s["symbol"]
            ctx = context.get(sym, {})
            chg = ctx.get("change_pct", 0)
            if chg < -3:
                event = {
                    "type": "sentiment",
                    "description": f"{s.get('name', sym)} 单日跌 {chg:.1f}%",
                    "actual_drop_pct": abs(chg),
                    "eps_impact_pct": 0,
                    "affected_stocks": [sym],
                }
                signal = panic_engine.analyze(event)
                if signal.level.value != "NONE":
                    print(f"  {sym} {s.get('name', sym)}: {signal.level.value} "
                          f"| 超跌比 {signal.overreaction_ratio:.1f}x "
                          f"| {signal.entry_timing}")


@_safe_cmd
def cmd_pullback_scan(args: list[str]):
    """回调扫描 — 扫描自选股中的回调入场机会。"""
    import argparse
    from src.analysis.pullback import (
        PullbackDetector, AntiManipulationGate,
        PullbackScanner, ScanConfig,
    )

    parser = argparse.ArgumentParser(description="回调入场扫描")
    parser.add_argument("--watchlist", type=str, default=DEFAULT_WATCHLIST_PATH,
                        help="自选股文件路径 (JSON)")
    parser.add_argument("--sector", type=str, default="",
                        help="行业过滤 (空白=全部)")
    parser.add_argument("--min-score", type=float, default=50.0,
                        help="最低回调质量分 (默认 50)")
    parser.add_argument("--no-anti-manip", action="store_true",
                        help="跳过反操纵验证（仅技术检测）")
    parsed = parser.parse_args(args)

    watchlist = _load_watchlist(parsed.watchlist)
    if not watchlist:
        print("📭 自选股列表为空")
        print("   创建自选股: python -m src alert watch-add <symbol>")
        return

    symbols = [s["symbol"] for s in watchlist]
    names = {s["symbol"]: s.get("name", "") for s in watchlist}

    gate = None if parsed.no_anti_manip else AntiManipulationGate()
    detector = PullbackDetector(anti_manipulation_gate=gate)
    scanner = PullbackScanner(data_provider=None, detector=detector)

    config = ScanConfig(
        symbols=symbols,
        names=names,
        sector_filter=parsed.sector,
        min_score=parsed.min_score,
        require_authentic=not parsed.no_anti_manip,
    )

    # 逐个扫描（无 data_provider 时需要手动提供数据）
    result = scanner.scan(config)

    if result.ready or result.watch or result.blocked:
        print(scanner.format_result(result))
    else:
        print("📊 未检测到回调信号 — 自选股均不在回调区域")


@_safe_cmd
def cmd_pullback_watch(args: list[str]):
    """回调条件监控 — 管理回调入场条件单。"""
    import argparse
    from src.analysis.pullback import (
        PullbackDetector, AntiManipulationGate,
        EntryConditionMonitor,
    )

    parser = argparse.ArgumentParser(description="回调条件监控")
    sub = parser.add_subparsers(dest="action", help="操作")

    add_p = sub.add_parser("add", help="加入监控")
    add_p.add_argument("symbol", help="股票代码")
    add_p.add_argument("--name", type=str, default="", help="股票名称")

    sub.add_parser("list", help="查看监控列表")

    check_p = sub.add_parser("check", help="检查单票条件")
    check_p.add_argument("symbol", help="股票代码")

    rm_p = sub.add_parser("remove", help="移除监控")
    rm_p.add_argument("symbol", help="股票代码")

    parsed = parser.parse_args(args)

    gate = AntiManipulationGate()
    detector = PullbackDetector(anti_manipulation_gate=gate)
    monitor = EntryConditionMonitor(detector=detector)

    if parsed.action == "add":
        monitor.add(parsed.symbol, name=parsed.name)
        print(f"✅ {parsed.symbol} {parsed.name} 已加入回调监控")
    elif parsed.action == "list":
        entries = monitor.list_all()
        if not entries:
            print("📭 监控列表为空")
            print("   添加: python -m src pullback-watch add <code>")
            return
        print(f"📋 回调监控列表 ({len(entries)} 项):")
        print(f"  {'代码':<8} {'名称':<10} {'状态':<18} {'条件满足':>6} {'触发价':>8}")
        for e in entries:
            status = e.last_status.value if e.last_status else "NEW"
            print(
                f"  {e.symbol:<8} {e.name:<10} {status:<18} "
                f"{e.condition_met_count:>6} {e.trigger_price:>8.2f}"
            )
    elif parsed.action == "check":
        entry = monitor.check_one(parsed.symbol)
        if entry is None:
            print(f"❌ {parsed.symbol} 不在监控列表中")
            return
        print(f"📌 {entry.symbol} {entry.name}")
        print(f"   状态: {entry.last_status.value if entry.last_status else 'N/A'}")
        print(f"   条件: {entry.trigger_condition}")
        print(f"   触发价: {entry.trigger_price:.2f}")
        print(f"   连续满足: {entry.condition_met_count} 次")
        print(f"   上次检查: {entry.last_check_at}")
    elif parsed.action == "remove":
        ok = monitor.remove(parsed.symbol)
        print(f"{'✅' if ok else '❌'} {parsed.symbol} {'已移除' if ok else '未找到'}")
    else:
        # 默认列出
        entries = monitor.list_all()
        if not entries:
            print("📭 监控列表为空")
            return
        print(f"📋 回调监控列表 ({len(entries)} 项)")
        for e in entries:
            print(f"  {e.symbol} {e.name}: {e.trigger_condition or '待检测'}")


@_safe_cmd
def cmd_alert(args: list[str]):
    """预警管理 — 添加/查看/清理价格和止损预警。"""
    import argparse
    from src.output.alert import AlertManager

    parser = argparse.ArgumentParser(description="预警管理")
    parser.add_argument("action", nargs="?",
                        choices=["add-price", "add-stop", "watch-add", "watch-remove",
                                 "list", "clear", "panic"],
                        default="list", help="操作类型")
    parsed, remaining = parser.parse_known_args(args)

    mgr = AlertManager()

    if parsed.action == "add-price":
        p = argparse.ArgumentParser(description="添加价格预警")
        p.add_argument("symbol", help="股票代码")
        p.add_argument("--above", type=float, help="上破预警价")
        p.add_argument("--below", type=float, help="下破预警价")
        p.add_argument("--name", type=str, default="", help="股票名称")
        try:
            a = p.parse_args(remaining)
        except SystemExit:
            return
        mgr.add_price_alert(a.symbol, a.name or a.symbol, above=a.above, below=a.below)
        conditions = []
        if a.above:
            conditions.append(f"上破 {a.above}")
        if a.below:
            conditions.append(f"下破 {a.below}")
        print(f"✅ 已添加: {a.symbol} {' + '.join(conditions)}")

    elif parsed.action == "add-stop":
        p = argparse.ArgumentParser(description="添加止损预警")
        p.add_argument("symbol", help="股票代码")
        p.add_argument("price", type=float, help="止损价格")
        p.add_argument("--name", type=str, default="", help="股票名称")
        try:
            a = p.parse_args(remaining)
        except SystemExit:
            return
        mgr.add_stop_loss_alert(a.symbol, a.name or a.symbol, a.price)
        print(f"✅ 已添加: {a.symbol} 止损 {a.price}")

    elif parsed.action == "watch-add":
        p = argparse.ArgumentParser(description="加入自选股")
        p.add_argument("symbol", help="股票代码")
        p.add_argument("--name", type=str, default="", help="股票名称")
        p.add_argument("--stop-price", type=float, help="止损价")
        p.add_argument("--alert-above", type=float, help="上破预警")
        p.add_argument("--alert-below", type=float, help="下破预警")
        try:
            a = p.parse_args(remaining)
        except SystemExit:
            return
        watchlist = _load_watchlist()
        existing = [s for s in watchlist if s["symbol"] == a.symbol]
        entry = {"symbol": a.symbol, "name": a.name or a.symbol}
        if a.stop_price:
            entry["stop_price"] = a.stop_price
        if a.alert_above:
            entry["alert_above"] = a.alert_above
        if a.alert_below:
            entry["alert_below"] = a.alert_below
        if existing:
            existing[0].update(entry)
        else:
            watchlist.append(entry)
        _save_watchlist(watchlist)
        print(f"✅ 自选股已更新: {a.symbol} {a.name or ''} ({len(watchlist)} 只)")

    elif parsed.action == "watch-remove":
        if not remaining:
            print("用法: alert watch-remove <symbol>")
            return
        symbol = remaining[0]
        watchlist = _load_watchlist()
        watchlist = [s for s in watchlist if s["symbol"] != symbol]
        _save_watchlist(watchlist)
        print(f"✅ 已移除: {symbol} ({len(watchlist)} 只)")

    elif parsed.action == "list":
        watchlist = _load_watchlist()
        print(f"📋 自选股 ({len(watchlist)} 只):")
        if not watchlist:
            print("   (空) 使用 alert watch-add <symbol> 添加")
        for s in watchlist:
            extras = []
            if s.get("stop_price"):
                extras.append(f"止损 {s['stop_price']}")
            if s.get("alert_above"):
                extras.append(f"上破 {s['alert_above']}")
            if s.get("alert_below"):
                extras.append(f"下破 {s['alert_below']}")
            extra_str = f"  [{', '.join(extras)}]" if extras else ""
            print(f"  {s['symbol']} {s.get('name', '')}{extra_str}")

    elif parsed.action == "clear":
        mgr.clear_expired()
        print("✅ 已清理过期预警")

    elif parsed.action == "panic":
        if not remaining:
            print("用法: alert panic <symbol>")
            return
        from src.sentiment.panic_arb import PanicArbEngine
        engine = PanicArbEngine()
        event = {
            "type": "sentiment",
            "description": f"用户请求检查 {remaining[0]}",
            "actual_drop_pct": 5.0,
            "eps_impact_pct": 0,
        }
        signal = engine.analyze(event)
        print(f"{'=' * 50}")
        print(f"🎯 恐慌套利分析: {remaining[0]}")
        print(f"   级别: {signal.level.value}")
        print(f"   事件类型: {signal.event_type}")
        print(f"   超跌比: {signal.overreaction_ratio:.1f}x")
        print(f"   建议仓位: {signal.suggested_position_pct:.0%}")
        print(f"   入场时机: {signal.entry_timing or '等待信号'}")
        if signal.risks:
            print(f"   风险:")
            for r in signal.risks:
                print(f"     ⚠️ {r}")


@_safe_cmd
def cmd_monitor(args: list[str]):
    """盯盘引擎 — 启动/停止实时监控。"""
    import argparse
    import json
    from src.monitor.watchdog import Watchdog, WatchdogConfig
    from src.data.aggregator import DataAggregator

    parser = argparse.ArgumentParser(description="实时盯盘监控")
    parser.add_argument("action", nargs="?", default="start",
                        choices=["start", "stop", "status", "once"],
                        help="start=启动后台盯盘, stop=停止, status=查看状态, once=单次扫描")
    parser.add_argument("--symbols", type=str, default="",
                        help="监控标的列表, 逗号分隔 (默认读取自选股)")
    parser.add_argument("--interval", type=int, default=60,
                        help="扫描间隔秒数 (默认60)")
    parser.add_argument("--once", action="store_true",
                        help="单次扫描后退出")
    parsed = parser.parse_args(args)

    if parsed.action == "stop":
        print("🔔 盯盘已停止")
        return

    if parsed.action == "status":
        print("🔔 盯盘状态: 未运行 (使用 'monitor start' 启动)")
        return

    # 解析标的
    symbols = []
    if parsed.symbols:
        symbols = [s.strip() for s in parsed.symbols.split(",") if s.strip()]
    else:
        # 从自选股加载
        from src.cli import _load_watchlist
        try:
            wl = _load_watchlist()
            symbols = [w["symbol"] for w in wl]
        except Exception:
            pass

    if not symbols:
        print("⚠️ 未指定监控标的。使用 --symbols 或先添加自选股 (alert watch-add)")
        return

    print(f"🔔 盯盘启动: {len(symbols)} 只标的, 间隔 {parsed.interval}s")
    print(f"   标的: {', '.join(symbols[:10])}{'...' if len(symbols) > 10 else ''}")

    if parsed.once or parsed.action == "once":
        # 单次扫描模式
        config = WatchdogConfig(symbols=symbols, interval_seconds=parsed.interval)
        dog = Watchdog(config)
        aggregator = DataAggregator()

        try:
            # 获取实时行情
            quotes_raw = _get_quotes_dict(aggregator, symbols)
            quotes = {}
            for sym in symbols:
                q = quotes_raw.get(sym, {})
                quotes[sym] = {
                    "name": q.get("name", sym),
                    "price": q.get("price", 0) or 0,
                    "volume": q.get("volume", 0) or 0,
                    "change_pct": q.get("change_pct", 0) or 0,
                    "high": q.get("high", 0) or 0,
                    "low": q.get("low", 0) or 0,
                    "avg_vol_20": q.get("avg_vol_20", 0) or 0,
                    "ma5": q.get("ma5", 0) or 0,
                    "ma20": q.get("ma20", 0) or 0,
                    "high_20d": q.get("high_20d", 0) or 0,
                    "turnover": q.get("turnover", 0) or 0,
                }

            market_ctx = {
                "zt_count": 0, "zb_count": 0, "dt_count": 0,
                "break_rate": 0.0, "hs300_change": 0.0,
                "northbound_net": 0.0,
            }

            alerts = dog.run_once(quotes, market_ctx)
            if alerts:
                print(f"\n触发 {len(alerts)} 条预警:")
                for a in alerts:
                    emoji = {"CRITICAL": "🔴", "WARNING": "🟡", "INFO": "🔵"}.get(a.severity, "⚪")
                    print(f"  {emoji} [{a.alert_type.value}] {a.name}({a.symbol}): {a.message}")
            else:
                print("✅ 未触发预警")
        except Exception as e:
            print(f"⚠️ 获取行情失败: {e}")
            print("   (需要数据源支持，请确认 MOOTDX/TENCENT 配置)")
    else:
        print("💡 持续盯盘模式: 按 Ctrl+C 停止")
        print("   (后台运行: python -m src monitor start --interval 60 &)")
        # 持续运行在前台
        config = WatchdogConfig(symbols=symbols, interval_seconds=parsed.interval)
        dog = Watchdog(config)

        def _get_quotes():
            aggregator = DataAggregator()
            try:
                return _get_quotes_dict(aggregator, symbols)
            except Exception:
                return {}

        try:
            dog.run_loop(_get_quotes)
        except KeyboardInterrupt:
            dog.stop()
            print("\n👋 盯盘已停止")


@_safe_cmd
def cmd_technical(args: list[str]):
    """技术分析报告 — 单票 6 维技术评分。"""
    import argparse
    parser = argparse.ArgumentParser(description="技术分析报告")
    parser.add_argument("symbol", nargs="?", default="", help="股票代码")
    parser.add_argument("--name", type=str, default="", help="股票名称")
    parsed = parser.parse_args(args)

    if not parsed.symbol:
        print("用法: technical <code> [--name NAME]")
        print("示例: technical 000001 --name 平安银行")
        return

    symbol = parsed.symbol
    name = parsed.name or symbol

    print(f"🔬 技术分析: {name} ({symbol})")
    print("=" * 60)

    try:
        from src.data.aggregator import DataAggregator
        aggregator = DataAggregator()

        # 获取日线数据
        kline = aggregator.get_daily_kline(symbol)
        if kline is None or kline.empty:
            print("⚠️ 无法获取行情数据，尝试使用默认面板")
            import numpy as np
            import pandas as pd
            dates = pd.date_range('2025-01-01', periods=200, freq='B')
            panel = {}
            for col in ['close', 'high', 'low', 'volume']:
                base = np.random.randn(200, 1).cumsum(axis=0) + 100
                if col == 'high':
                    base = base + np.abs(np.random.randn(200, 1)) * 2
                if col == 'low':
                    base = base - np.abs(np.random.randn(200, 1)) * 2
                if col == 'volume':
                    base = np.abs(base) * 1e7
                panel[col] = pd.DataFrame(base, index=dates, columns=[symbol])
        else:
            panel = {
                "close": kline[["close"]].rename(columns={"close": symbol}),
                "high": kline[["high"]].rename(columns={"high": symbol}),
                "low": kline[["low"]].rename(columns={"low": symbol}),
                "volume": kline[["volume"]].rename(columns={"volume": symbol}),
            }

        from src.routing.technical import TechnicalAnalyzer
        from src.routing.entry_exit_engine import EntryExitEngine

        analyzer = TechnicalAnalyzer()
        report = analyzer.analyze(symbol, name, panel)

        print(f"\n📊 技术综合评分: {report.composite_score:.0f}/100")
        print(f"   置信度: {report.confidence:.0%}")
        print()
        print("📈 六维评分:")
        print(f"   趋势 (Trend):     {report.trend_score:5.0f}/100")
        print(f"   反转 (Reversal):  {report.reversal_score:5.0f}/100")
        print(f"   量价 (Volume):    {report.volume_score:5.0f}/100")
        print(f"   波动 (Volatility):{report.volatility_score:5.0f}/100")
        print(f"   均线 (MA):        {report.ma_score:5.0f}/100")
        print(f"   打板 (LimitUp):   {report.limit_up_score:5.0f}/100")

        if report.signals:
            print(f"\n📡 技术信号 ({len(report.signals)}):")
            for s in report.signals:
                flag = "🟢" if s.is_entry else ("🔴" if s.is_exit else "⚪")
                print(f"  {flag} [{s.indicator}] {s.direction}: {s.description[:80]}")

        if report.data_gaps:
            print(f"\n⚠️ 数据缺口: {', '.join(report.data_gaps)}")

        # 入场/出场时机
        engine = EntryExitEngine()
        timing = engine.evaluate(symbol, name, panel)
        if timing.entry_signals:
            print(f"\n🎯 入场信号 ({len(timing.entry_signals)}):")
            for es in timing.entry_signals:
                print(f"  🔵 {es.type}: {es.description[:80]}")
                print(f"     入场区间: [{es.entry_zone_low:.2f} - {es.entry_zone_high:.2f}] (置信度 {es.confidence:.0%})")
        if timing.exit_signals:
            print(f"\n🚪 出场信号 ({len(timing.exit_signals)}):")
            for es in timing.exit_signals:
                print(f"  🔴 {es.type} [{es.urgency}]: {es.description[:80]}")
        if timing.suggested_stop > 0:
            print(f"\n🛑 止损: {timing.suggested_stop:.2f} (ATR={timing.atr_stop:.2f})")
            print(f"🎯 目标: T1={timing.target_1:.2f} T2={timing.target_2:.2f}")
            print(f"⏱️ 时间止损: {timing.time_stop_days}天")

    except Exception as e:
        print(f"❌ 分析失败: {e}")
        if os.environ.get("DEBUG"):
            traceback.print_exc()


@_safe_cmd
def cmd_timing(args: list[str]):
    """T+0 日内时机分析 — 日线+分钟线双维度判断建仓/加仓/减仓时机。"""
    from src.routing.orchestrator import Orchestrator

    symbol = args[0] if args else ""
    if not symbol or not _validate_symbol(symbol):
        print("用法: python -m src timing <股票代码>")
        print("示例: python -m src timing 002460")
        return

    market = _infer_market(symbol)
    print(f"⏱️  T+0 日内时机分析: {symbol}")
    print("=" * 60)

    orch = Orchestrator()
    t0 = orch.run_t0(symbol, market)

    if t0 is None:
        print("❌ T+0 分析不可用（分钟数据获取失败或交易日未开盘）")
        print("   提示: T+0 分析需要盘中交易时段运行")
        return

    action_emoji = {"add": "🟢", "hold": "🟡", "reduce": "🟠", "cut": "🔴", "no_position": "⚪"}
    action_text = {"add": "可以加仓", "hold": "观望等待", "reduce": "建议减仓", "cut": "坚决减仓", "no_position": "不建议建仓"}
    emoji = action_emoji.get(t0["action"], "❓")
    text = action_text.get(t0["action"], "未知")

    print(f"\n  {emoji} {text}  得分: {t0['score']}")
    print(f"\n  ── 日线技术位 ──")
    print(f"  MA5: {t0['ma5']:.2f}  MA10: {t0['ma10']:.2f}  MA20: {t0['ma20']:.2f}")
    print(f"  阻力: {t0['resistance']}  支撑: {t0['support_1']}")

    if t0.get("vwap", 0) > 0:
        print(f"\n  ── 日内数据 ──")
        print(f"  VWAP: {t0['vwap']:.2f}  H={t0['day_high']} L={t0['day_low']} ({t0.get('day_low_time','')})")
        print(f"  振幅: {t0['amplitude']}%  反弹: {t0['rebound_from_low']:+.1f}%")
        print(f"  总成交: {t0['total_vol']/10000:.0f}万股 / {t0['total_amount']/1e8:.1f}亿")
        print(f"  反弹质量: {t0['rebound_quality']}")

    if t0.get("daily_patterns"):
        print(f"\n  ── K线形态 ──")
        for p in t0["daily_patterns"]:
            print(f"  {p}")
    if t0.get("intraday_pattern"):
        print(f"\n  ── 分时形态 ──")
        print(f"  {t0['intraday_pattern']}")

    if t0.get("signals_bull"):
        print(f"\n  🟢 看多信号:")
        for s in t0["signals_bull"]:
            print(f"    + {s}")
    if t0.get("signals_bear"):
        print(f"\n  🔴 看空信号:")
        for s in t0["signals_bear"]:
            print(f"    - {s}")

    if t0.get("suggested_price", 0) > 0:
        print(f"\n  💰 建议操作价: {t0['suggested_price']:.2f}")
    if t0.get("stop_loss", 0) > 0:
        print(f"  🛑 止损价: {t0['stop_loss']:.2f}")
    if t0.get("trigger_condition"):
        print(f"  📋 {t0['trigger_condition']}")

    print(f"\n  ⚠️ A股T+1制度下，日内操作需已有底仓。以上不构成投资建议。")


@_safe_cmd
def cmd_attribute(args: list[str]):
    """个股涨跌归因 — Phase 1 自动并行数据搜集 + 质量预检。

    用法: python -m src attribute <code> [--date YYYY-MM-DD]

    Phase 1 (自动): AttributionEngine 并行搜集新闻/公告/行情/资金面/行业数据，
                    自动生成 T0-T3 分级 + STALE/DATA_GAP 标记 + QualitySummary。
    Phase 2/3 (AI): 由 AI 代理调用 macro-monitor/sector-research/sentiment-analysis
                    等 skill 完成多维归因和因果推断。
    """
    import argparse
    from datetime import datetime

    from src.routing.attribution import AttributionEngine
    from src.routing.attribution_formatter import format_attribution_result

    parser = argparse.ArgumentParser(description="个股涨跌归因")
    parser.add_argument("symbol", nargs="?", default="", help="6 位股票代码")
    parser.add_argument("--date", type=str, default="", help="归因日期 YYYY-MM-DD (默认今天)")
    parsed = parser.parse_args(args)

    symbol = parsed.symbol
    if not symbol:
        print("用法: python -m src attribute <code> [--date YYYY-MM-DD]")
        print()
        print("示例:")
        print("  python -m src attribute 600089")
        print("  python -m src attribute 000063 --date 2026-07-01")
        print()
        print("Phase 1 自动搜集: 新闻/公告/行情/K线/龙虎榜/北向/融资融券/行业分类")
        print("Phase 2/3 由 AI 代理完成: 多维归因 → 因果推断 → 强制格式输出")
        return

    if not re.match(r"^\d{6}$", symbol):
        print(f"❌ 无效股票代码: {symbol} (需要 6 位数字)")
        return

    date = parsed.date or datetime.now().strftime("%Y-%m-%d")

    print(f"🔍 个股涨跌归因: {symbol} ({date})")
    print("=" * 60)
    print()
    print("📡 Phase 1 — 信息搜集 (并行)")
    print("   ├→ 资讯/新闻")
    print("   ├→ 公告 (巨潮)")
    print("   ├→ 行情/K线 (腾讯 + mootdx)")
    print("   ├→ 资金面 (龙虎榜/北向/融资融券)")
    print("   └→ 行业分类 (东财)")
    print()

    engine = AttributionEngine()
    result = engine.collect(symbol, date=date)

    # 输出 Phase 1 结果
    print(format_attribution_result(result))
    print()
    print("─" * 60)
    print("📌 Phase 1 完成。请 AI 代理继续执行:")
    print("   Phase 2: macro-monitor / sector-research / sentiment-analysis")
    print("            / topic-manager / policy-tracker + 资金面+技术面")
    print("   Phase 3: 信息源质量检查 → 因果链推导 → 主因排序")
    print("   Skill:   stock-attribution (含完整 CHECKLIST)")
    print("   CLI:     结果已在上方，可用 result.drivers / result.confidence 补充")


@_safe_cmd
def cmd_macro_event(args: list[str]):
    """宏观事件因果链分析 — 事件→A股传导路径→影响估计→策略建议。"""
    from src.macro.event_analyzer import EventAnalyzer

    if not args:
        print("用法: python -m src macro-event <事件描述> [--category 类型] [--symbol 股票] [--sector 行业]")
        print()
        print("示例:")
        print('  python -m src macro-event "美联储意外加息50bp" --category monetary')
        print('  python -m src macro-event "美国扩大AI芯片出口限制" --category tech_sanction --symbol 002460')
        return

    import argparse
    parser = argparse.ArgumentParser(description="宏观事件因果链分析")
    parser.add_argument("description", nargs="+", help="事件描述")
    parser.add_argument("--category", default="", choices=["monetary","geopolitical","trade_policy","tech_sanction","economic_data","financial_crisis","commodity","regulatory"], help="事件类型")
    parser.add_argument("--symbol", default="", help="关注的个股代码")
    parser.add_argument("--sector", default="", help="个股所属行业")
    parser.add_argument("--source", default="", help="信息来源")
    parsed = parser.parse_args(args)

    desc = " ".join(parsed.description) if isinstance(parsed.description, list) else parsed.description

    print(f"🌍 宏观事件因果链分析")
    print("=" * 60)

    analyzer = EventAnalyzer()
    report = analyzer.analyze(
        event_description=desc,
        category_hint=parsed.category,
        source=parsed.source,
        stock_symbol=parsed.symbol,
        stock_sector=parsed.sector,
    )

    # 事件摘要
    print(f"\n  📰 事件: {report.event.title}")
    print(f"  🏷️  分类: {report.event.category.value}")
    if report.event.source:
        print(f"  📎 来源: {report.event.source}")

    # 传导路径
    print(f"\n  ── 传导路径 ({len(report.transmission_channels)}条) ──")
    if report.transmission_channels:
        for ch in report.transmission_channels:
            direction_emoji = {"bullish": "🟢", "bearish": "🔴", "neutral": "➖"}
            mag_bar = {"strong": "███", "moderate": "██", "weak": "█"}
            emoji = direction_emoji.get(ch.direction.value, "➖")
            bar = mag_bar.get(ch.magnitude.value, "█")
            print(f"  {emoji} {ch.channel} [{bar}] {ch.timeframe.value}")
            print(f"     {ch.description}")
            if ch.affected_sectors:
                print(f"     影响行业: {', '.join(ch.affected_sectors)}")
    else:
        print("  (无匹配传导路径)")

    # 影响估计
    if report.impact:
        imp = report.impact
        print(f"\n  ── 影响估计 ──")
        print(f"  方向: {imp.direction.value}  基准: {imp.base_case_change_pct:+.1f}%")
        print(f"  乐观: {imp.bullish_case_change_pct:+.1f}%  悲观: {imp.bearish_case_change_pct:+.1f}%")
        print(f"  峰值: {imp.peak_impact_days}天  置信度: {imp.confidence:.0%}")
        print(f"  净得分: {report.net_bullish_score:+.2f}")
        if imp.reasoning:
            print(f"  推理: {imp.reasoning}")

    # 历史类比
    if report.historical_analogs:
        print(f"\n  ── 历史类比 ──")
        for a in report.historical_analogs:
            print(f"  📖 {a.event_name} ({a.period})")
            print(f"     上证{a.shanghai_change_pct:+.0f}%  相似度{a.similarity_score:.0%}")
            if a.key_parallels:
                print(f"     相似: {', '.join(a.key_parallels[:3])}")
            if a.key_differences:
                print(f"     差异: {', '.join(a.key_differences[:3])}")

    # 策略建议
    print(f"\n  ── 策略建议 ──")
    print(f"  整体定位: {report.strategy.overall_position}")
    if report.strategy.suggested_action:
        print(f"  操作: {report.strategy.suggested_action}")
    if report.strategy.hedging_suggestions:
        print(f"  对冲: {', '.join(report.strategy.hedging_suggestions)}")
    if report.strategy.monitoring_indicators:
        print(f"  监控: {', '.join(report.strategy.monitoring_indicators)}")
    if report.strategy.position_sizing:
        print(f"  仓位: {report.strategy.position_sizing}")

    # 风险
    if report.risk_factors:
        print(f"\n  ── 风险因子 ──")
        for r in report.risk_factors:
            print(f"  ⚠️  {r}")

    # 个股影响
    if parsed.symbol and report.stock_impact_summary:
        print(f"\n  ── 个股影响 ({parsed.symbol}) ──")
        print(f"  {report.stock_impact_summary}")

    print(f"\n  ⚠️ 以上为系统分析，不构成投资建议。")


@_safe_cmd
def cmd_swing_scan(args: list[str]):
    """波段选股扫描 — 扫描技术面符合条件的短线标的。"""
    import argparse
    parser = argparse.ArgumentParser(description="波段选股扫描")
    parser.add_argument("--preset", type=str, default="balanced",
                        choices=["aggressive", "balanced", "conservative"],
                        help="扫描风格: aggressive=高波动+追涨, balanced=适中, conservative=稳健低吸")
    parser.add_argument("--limit", type=int, default=20, help="返回数量上限")
    parsed = parser.parse_args(args)

    print(f"🔍 波段选股扫描 (风格: {parsed.preset})")
    print("=" * 60)

    preset_configs = {
        "aggressive": {"min_score": 65, "max_vol_ratio": 5.0, "prefer_breakout": True},
        "balanced": {"min_score": 55, "max_vol_ratio": 3.0, "prefer_breakout": False},
        "conservative": {"min_score": 45, "max_vol_ratio": 2.0, "prefer_breakout": False},
    }
    config = preset_configs[parsed.preset]

    try:
        from src.data.aggregator import DataAggregator
        aggregator = DataAggregator()

        # 获取候选股票池 (沪深300 + 中证500 成分股)
        candidates = aggregator.get_index_constituents("hs300") or []
        if not candidates:
            print("⚠️ 无法获取成分股列表，使用默认候选池")
            candidates = ["000001", "000002", "600000", "600036", "601318"]

        print(f"📋 候选池: {len(candidates)} 只")
        print(f"🔎 扫描中...")

        results = []
        for sym in candidates[:parsed.limit * 3]:  # 多扫一些用于排序
            try:
                kline = aggregator.get_daily_kline(sym)
                if kline is None or kline.empty or len(kline) < 60:
                    continue

                # 快速预筛: 基于简单技术条件
                close = kline["close"]
                ma20 = close.rolling(20).mean().iloc[-1]
                ma60 = close.rolling(60).mean().iloc[-1] if len(close) >= 60 else ma20
                latest = close.iloc[-1]
                avg_vol = kline["volume"].rolling(20).mean().iloc[-1]
                latest_vol = kline["volume"].iloc[-1]
                vol_ratio = latest_vol / avg_vol if avg_vol > 0 else 1.0
                ret_5d = (latest / close.iloc[-5] - 1) * 100 if len(close) >= 5 else 0

                # 技术评分简化版
                score = 50.0
                if latest > ma20:
                    score += 10
                if latest > ma60:
                    score += 10
                if 1.0 <= vol_ratio <= config["max_vol_ratio"]:
                    score += 10
                if -3 < ret_5d < 8:
                    score += 10
                if latest < ma20 * 1.05:
                    score += 10

                if score >= config["min_score"]:
                    name = getattr(kline, "name", sym)
                    results.append({
                        "symbol": sym, "name": str(name), "score": score,
                        "close": float(latest), "vol_ratio": round(float(vol_ratio), 1),
                        "ret_5d": round(float(ret_5d), 1),
                    })
            except Exception:
                continue

        # 排序输出
        results.sort(key=lambda x: x["score"], reverse=True)
        results = results[:parsed.limit]

        if results:
            print(f"\n✅ 选出 {len(results)} 只候选:")
            print(f"{'代码':<10} {'名称':<10} {'评分':<6} {'现价':<8} {'量比':<6} {'5日%':<8}")
            print("-" * 50)
            for r in results:
                ret_str = f"+{r['ret_5d']:.1f}%" if r['ret_5d'] >= 0 else f"{r['ret_5d']:.1f}%"
                print(
                    f"{r['symbol']:<10} {r['name']:<10} {r['score']:<6.0f} "
                    f"{r['close']:<8.2f} {r['vol_ratio']:<6.1f} {ret_str:<8}"
                )
        else:
            print("😕 当前无符合条件的波段标的")

    except Exception as e:
        print(f"❌ 扫描失败: {e}")
        if os.environ.get("DEBUG"):
            traceback.print_exc()


# ---------------------------------------------------------------------------
# 策略竞技场
# ---------------------------------------------------------------------------

@_safe_cmd
def cmd_arena(args: list[str]):
    """内部策略竞技场 — 多策略横向对比回测。"""
    from src.arena.cli import arena_cli_handler
    arena_cli_handler(args)


def _print_command_detail(cmd: str) -> None:
    """打印单个命令的详细帮助。"""
    details = {
        "start": ("python -m src start", "新手引导 — 交互式导览系统功能", []),
        "analyze": ("python -m src analyze <code> [--deep]", "单只股票全链路分析（军规→准入→诊断→裁决→仓位→风控）", ["--deep: 启用深度分析模式（含辩论+思维模型）"]),
        "diagnose": ("python -m src diagnose <code> [--deep] [--no-t0] [--batch CODES] [--as-of DATE]",
            "一键诊断（小白入口），支持单票/批量/历史回测",
            [
                "--deep: 启用深度诊断",
                "--no-t0: 跳过 T+0 日内时机分析",
                "--batch CODES: 批量对比模式，逗号分隔 (如 002415,000938)",
                "--as-of DATE: 历史回测日期 (如 2025-09-01)",
            ]),
        "alpha": ("python -m src alpha <code>", "Alpha Lens 三维评估（信息层级/共识缺口/叙事生命周期）", []),
        "alpha-scan": ("python -m src alpha-scan [--limit N]", "扫描全市场高 Alpha 股票", ["--limit N: 返回前 N 只（默认 20）"]),
        "scan": ("python -m src scan --preset <preset>", "全市场选股扫描", ["--preset value|growth|momentum|quality|dividend: 选股预设"]),
        "macro": ("python -m src macro", "宏观货币信用快照（社融/DR007/M1-M2/LPR）", []),
        "sentiment": ("python -m src sentiment", "市场情绪信号检测（恐慌/贪婪/极端）", []),
        "backtest": ("python -m src backtest", "运行策略回测", []),
        "technical": ("python -m src technical <code> [--name 名称]", "技术分析报告（六维评分 + 入场/出场时机）", ["--name: 股票名称（可选）"]),
        "sweep": ("python -m src sweep", "自选股扫雷（检查所有自选股风险）", []),
        "preference": ("python -m src preference <view|setup|edit|reset>", "投资者偏好管理", ["view: 查看当前配置", "setup: 交互式设置向导", "edit: 编辑配置", "reset: 重置为默认"]),
        "preview-earnings": ("python -m src preview-earnings [code] [--consensus N] [--q2-shipment N]", "业绩先行研判 — 基于锂盐价格等高频公开数据测算Q2业绩", ["code: 股票代码 (默认002460 赣锋锂业)", "--consensus: 机构一致预期Q2净利(亿元)", "--q2-shipment: Q2锂盐出货量(千吨LCE)", "--no-sensitivity: 跳过敏感性分析"]),
    }

    if cmd in details:
        usage, desc, options = details[cmd]
        print(f"📖 {cmd} — {desc}")
        print()
        print(f"   用法: {usage}")
        if options:
            print()
            print("   选项:")
            for opt in options:
                print(f"     {opt}")
    else:
        print(f"📖 {cmd}")
        print()
        print(f"   运行 python -m src {cmd} 执行。")
        print(f"   运行 python -m src 查看所有命令。")

    print()


@_safe_cmd
def cmd_health():
    """系统能力自检 — 验证所有模块和命令的健康状态。"""
    import importlib

    print("🏥 白泽系统能力自检")
    print("=" * 60)

    # 数据源
    print("\n📡 数据源:")
    try:
        from src.data.aggregator import DataAggregator
        agg = DataAggregator()
        status = agg.source_status()
        for src, state in status.items():
            icon = "✅" if "✅" in str(state) else "❌"
            print(f"  {icon} {src}: {state}")
    except Exception as e:
        print(f"  ❌ 数据聚合器: {e}")

    # 模块
    print("\n📦 核心模块:")
    modules = [
        ("routing.orchestrator", "管道编排"),
        ("routing.diagnosis", "多维诊断"),
        ("routing.verdict", "综合裁决"),
        ("routing.positioning", "仓位调度"),
        ("routing.risk_control", "风控执行"),
        ("routing.attribution", "涨跌归因"),
        ("game_theory.manipulation", "庄家操纵检测"),
        ("game_theory.playbooks", "操盘手法库"),
        ("sentiment.signals", "情绪检测"),
        ("sentiment.panic_arb", "恐慌套利"),
        ("macro.monetary_credit", "宏观货币信用"),
        ("indicators.candlestick", "K线形态识别"),
        ("backtest.runner", "策略回测"),
        ("learner.calibrator", "置信度校准"),
        ("cron.executor", "定时任务"),
        ("pipeline.confidence_gate", "置信门控"),
        ("profile", "用户画像"),
        ("memory.store", "记忆系统"),
        ("reporting.memo_renderer", "投资备忘录"),
        ("finance.meta_tool", "财务查询"),
    ]
    for mod_path, desc in modules:
        try:
            importlib.import_module(f"src.{mod_path}")
            print(f"  ✅ {desc} ({mod_path})")
        except Exception as e:
            print(f"  ❌ {desc} ({mod_path}): {e}")

    # CLI 命令
    print("\n🔧 CLI 命令:")
    cmd_count = len([c for c in dir(sys.modules[__name__]) if c.startswith("cmd_")])
    print(f"  总计 {cmd_count} 个命令已注册")

    # cron
    print("\n⏰ 主动任务:")
    try:
        from src.cron.executor import JobExecutor
        builtins = JobExecutor.list_builtins()
        for name, cmd in builtins.items():
            print(f"  📋 {name}: {cmd}")
        if not builtins:
            print("  (无)")
    except Exception as e:
        print(f"  ❌ {e}")

    print(f"\n✅ 自检完成")


def cmd_start(args: list[str]) -> None:
    """新手引导 — 交互式导览系统功能。"""
    steps = [
        ("🦄 欢迎使用白泽 (Baize)！", "A 股智能投资决策系统"),
        ("📊 了解系统能力", "白泽提供 5 层管道分析：\n"
         "  军规(31条) → 准入检查 → 多维诊断 → 综合裁决 → 仓位调度 → 风控执行"),
        ("🔑 数据源", "默认使用免费数据源（mootdx + 腾讯 + AKShare）。\n"
         "  配置付费源可获更高质量数据，详见 SECRET.md。"),
        ("🏥 第一种用法：一键诊断", "运行 python -m src diagnose <股票代码>\n"
         "  例: python -m src diagnose 600519  # 分析贵州茅台\n"
         "  批量: python -m src diagnose --batch 002415,000938,601138\n"
         "  回测: python -m src diagnose 300750 --as-of 2025-09-01"),
        ("📊 第二种用法：全链路分析", "运行 python -m src analyze <股票代码>\n"
         "  比 diagnose 更详细，包含博弈论和仓位建议"),
        ("🔍 第三种用法：选股扫描", "运行 python -m src scan --preset value\n"
         "  预设: value(价值) growth(成长) momentum(动量) quality(质量)"),
        ("🌍 第四种用法：市场监控", "运行 python -m src macro    # 宏观快照\n"
         "  运行 python -m src sentiment  # 情绪检测"),
        ("⚡ 短线/技术分析", "运行 python -m src technical <股票代码>\n"
         "  六维评分 + 入场/出场时机 + K线形态识别"),
        ("👤 个性化配置", "运行 python -m src preference setup\n"
         "  10 步交互式向导：风险偏好、投资风格、风控参数"),
        ("✅ 下一步", "试试: python -m src diagnose 600519"),
    ]

    print()
    i = 0
    for title, content in steps:
        i += 1
        input(f"[{i}/{len(steps)}] {title} — 按 Enter 继续...")
        print()
        print(f"  {content}")
        print()

    print("🎉 引导完成！开始你的 A 股投资之旅吧！")
    print()
    print("💡 常用命令速查：")
    print("   python -m src diagnose <code>   一键诊断")
    print("   python -m src scan --preset value  价值选股")
    print("   python -m src macro              宏观快照")
    print("   python -m src --help             查看所有命令")


# ------------------------------------------------------------------
# 自然语言路由
# ------------------------------------------------------------------

# NL→命令 关键词映射 (key: 关键词列表, cmd: 命令, help: 示例)
_NL_ROUTES: list[dict] = [
    {"keys": ["情绪", "恐慌", "贪婪", "market sentiment", "市场气氛", "大盘情绪", "市场怎么样"], "cmd": "sentiment", "help": "python -m src sentiment"},
    {"keys": ["宏观", "宏观快照", "货币", "信用", "社融", "利率", "macro", "lpr", "mlf", "降息", "降准"], "cmd": "macro", "help": "python -m src macro"},
    {"keys": ["选股", "扫描", "筛选", "scan", "选股器", "找股票", "推荐股票", "有什么好股票", "找一些", "价值股", "成长股"], "cmd": "scan --preset value", "help": "python -m src scan --preset value"},
    {"keys": ["回测", "backtest", "策略", "测试策略"], "cmd": "backtest", "help": "python -m src backtest"},
    {"keys": ["分析", "诊断", "看看", "analyze", "diagnose", "怎么样", "如何"], "cmd": "diagnose", "help": "python -m src diagnose <code>  # 需要股票代码"},
    {"keys": ["形态", "k线", "蜡烛", "candlestick", "技术形态"], "cmd": "patterns", "help": "python -m src patterns <code>  # 需要股票代码"},
    {"keys": ["短线", "波段", "技术分析", "入场", "出场", "technical", "swing"], "cmd": "technical", "help": "python -m src technical <code>  # 需要股票代码"},
    {"keys": ["新手", "引导", "入门", "开始", "帮助", "help", "start", "怎么用", "如何使用"], "cmd": "start", "help": "python -m src start"},
    {"keys": ["自选", "盯盘", "扫雷", "watchlist", "sweep", "预警", "alert"], "cmd": "sweep", "help": "python -m src sweep"},
    {"keys": ["进化", "学习", "策略进化", "论文", "evolution"], "cmd": "evolution list", "help": "python -m src evolution list"},
    {"keys": ["偏好", "设置", "配置", "profile", "preference", "风险偏好", "投资风格"], "cmd": "preference setup", "help": "python -m src preference setup"},
    {"keys": ["为什么涨", "为什么跌", "涨停原因", "跌停原因", "大涨原因", "大跌原因", "涨跌原因", "归因", "attribute"], "cmd": "attribute", "help": "python -m src attribute <code>  # 需要股票代码"},
    {"keys": ["庄家", "操纵", "诱多", "诱空", "出货", "对倒", "洗盘", "钓鱼线", "尾盘偷袭", "操盘手法", "manipulation"], "cmd": "manipulation", "help": "python -m src manipulation <code>  # 需要股票代码"},
]


def _route_nl(query: str) -> str | None:
    """自然语言 → 命令路由。

    根据关键词匹配返回对应的命令字符串。
    多关键词命中时取匹配最多的那条。
    返回 None 表示无法识别。
    """
    query_lower = query.lower().strip()
    best_match = None
    best_count = 0

    for route in _NL_ROUTES:
        hits = sum(1 for key in route["keys"] if key.lower() in query_lower)
        if hits > best_count:
            best_count = hits
            best_match = route

    if best_match and best_count >= 1:
        return best_match
    return None


def _print_nl_help():
    """打印自然语言查询帮助。"""
    print()
    print("🤖 自然语言查询 — 你可以这样问我：")
    print()
    print("  市场情绪:  \"当前A股市场情绪如何\"")
    print("  宏观快照:  \"现在宏观环境怎么样\"")
    print("  选股扫描:  \"帮我找一些价值股\"")
    print("  新手引导:  \"我该怎么开始\"")
    print("  分析股票:  \"分析贵州茅台\" → 需要代码: python -m src diagnose 600519")
    print()


@_safe_cmd
def cmd_record_position(symbol: str, name: str, entry_price: float, quantity: int):
    """记录持仓到 data/positions.json（可被 AI agent 编程调用）。"""
    import json
    from pathlib import Path

    path = Path("data/positions.json")
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            try:
                positions = json.load(f)
            except json.JSONDecodeError:
                positions = {}
    else:
        positions = {}
        path.parent.mkdir(parents=True, exist_ok=True)

    from datetime import datetime
    now = datetime.now().isoformat()
    positions[symbol] = {
        "symbol": symbol,
        "name": name,
        "entry_price": entry_price,
        "entry_date": now.split("T")[0],
        "quantity": quantity,
        "direction": "LONG",
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(positions, f, ensure_ascii=False, indent=2)
    print(f"✅ 记录持仓: {name}({symbol}) {quantity}股@{entry_price}")
    return positions


@_safe_cmd
def cmd_update_watchlist(symbol: str, name: str, stop_price: float = None, alert_above: float = None):
    """更新自选股到 data/watchlist.json（可被 AI agent 编程调用）。"""
    import json
    from datetime import datetime
    from pathlib import Path

    path = Path("data/watchlist.json")
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            try:
                watchlist = json.load(f)
            except json.JSONDecodeError:
                watchlist = {"stocks": [], "updated_at": ""}
    else:
        watchlist = {"stocks": [], "updated_at": ""}
        path.parent.mkdir(parents=True, exist_ok=True)

    stocks = watchlist.get("stocks", [])
    # 更新已有条目或追加
    existing = next((s for s in stocks if s.get("symbol") == symbol), None)
    if existing:
        existing["name"] = name
        if stop_price is not None:
            existing["stop_price"] = stop_price
        if alert_above is not None:
            existing["alert_above"] = alert_above
    else:
        stocks.append({
            "symbol": symbol,
            "name": name,
            "stop_price": stop_price,
            "alert_above": alert_above,
        })
    watchlist["stocks"] = stocks
    watchlist["updated_at"] = datetime.now().isoformat()

    with open(path, "w", encoding="utf-8") as f:
        json.dump(watchlist, f, ensure_ascii=False, indent=2)
    print(f"✅ 更新自选股: {name}({symbol})" +
          (f" 止损={stop_price}" if stop_price is not None else "") +
          (f" 预警≥{alert_above}" if alert_above is not None else ""))


def cmd_preview_earnings(args: list[str]):
    """业绩先行研判 — 基于碳酸锂价格等先行指标预测Q2业绩。"""
    import argparse

    parser = argparse.ArgumentParser(
        description="业绩先行研判: 基于锂盐价格等高频公开数据，"
        "在财报发布前测算碳酸锂企业季度业绩 (支持Q1/Q2)",
    )
    parser.add_argument(
        "code", nargs="?", default="002460",
        help="股票代码 (默认: 002460 赣锋锂业)",
    )
    parser.add_argument(
        "--consensus", type=float, default=None,
        help="机构一致预期Q2净利(亿元)，用于Beat/Miss对比",
    )
    parser.add_argument(
        "--q2-shipment", type=float, default=None,
        help="Q2锂盐出货量(万吨LCE)，覆盖默认值",
    )
    parser.add_argument(
        "--no-sensitivity", action="store_true",
        help="跳过敏感性分析矩阵",
    )
    parser.add_argument(
        "--target-quarter", type=str, default="Q2", choices=["Q1", "Q2"],
        help="目标预测季度: Q1 或 Q2 (默认: Q2)",
    )
    opts = parser.parse_args(args)

    from src.data.commodity.lithium_tracker import LithiumPriceTracker
    from src.industry.earnings_preview import EarningsPreviewModel
    from src.output.earnings_preview_fmt import print_earnings_preview

    tq = opts.target_quarter
    baseline_label = "Q4_2025" if tq == "Q1" else "Q1_2026"
    target_label = tq

    print(f"🔍 正在获取锂盐价格数据 (基线: {baseline_label} → 目标: {target_label})...")
    tracker = LithiumPriceTracker()

    # 获取锂盐价格一篮子
    basket = tracker.get_lithium_basket(target_quarter=tq)
    basket_price = basket.q2_basket_price  # LithiumBasket: q1=基线, q2=目标
    print(f"   {target_label} 加权均价: {basket_price:,.0f} 元/吨"
          if basket_price else f"   {target_label} 加权均价: N/A")
    print(f"   数据点数: {basket.data_points_q2}")
    print(f"   数据源: {basket.source}")

    # 创建测算模型
    if opts.code == "002460":
        model = EarningsPreviewModel.for_ganfeng(target_quarter=tq)
    else:
        model = EarningsPreviewModel.custom(code=opts.code)

    # 覆盖出货量
    if opts.q2_shipment is not None:
        model._p.q2_shipment_kt = opts.q2_shipment

    # 执行测算
    print(f"\n📊 正在测算 Q2 业绩...")
    result = model.preview_q2(
        basket, consensus_q2_profit=opts.consensus
    )

    # 敏感性分析
    sensitivity = None
    if not opts.no_sensitivity:
        sensitivity = model.sensitivity_table(basket)

    # 输出报告
    print_earnings_preview(result, basket, sensitivity)


def main():
    """白泽 CLI 主入口。"""

    # 配置日志
    log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(levelname)s [%(name)s] %(message)s",
    )

    # 注册默认主动任务 (cron 系统)
    try:
        from src.cron.executor import register_default_jobs
        register_default_jobs()
    except Exception:
        pass

    # 首次运行检测：无 .env 时提示
    _env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
    if not os.path.exists(_env_path):
        print("🦄 欢迎使用白泽 (Baize) — A 股智能投资决策系统！")
        print()
        print("⚠️  未检测到 .env 文件。建议运行安装脚本完成初始化：")
        print()
        print("     ./setup.sh")
        print()
        print("  或手动配置：")
        print("     cp .env.example .env")
        print("     # 编辑 .env，可选配置 AI 模型密钥和数据源密钥")
        print("     # 不配置密钥也可使用——系统自动使用免费数据源")
        print()

    if len(sys.argv) < 2 or sys.argv[1] in ("--help", "-h", "help"):
        print("白泽 (Baize) — A 股智能投资决策系统 v0.1.0")
        print()
        print("用法: python -m src <command> [args]")
        print()
        print("📊 核心分析:")
        print("  start                   新手引导（5分钟了解系统）")
        print("  analyze <code> [--deep] 单只股票全链路分析")
        print("  diagnose <code> [--deep] 一键诊断（小白入口）")
        print("  alpha <code>           Alpha Lens 三维评估")
        print("  alpha-scan             高 Alpha 股票扫描")
        print("  alpha-decay <code>     Alpha 衰减追踪")
        print("  scan                    全市场选股扫描")
        print()
        print("📈 市场监控:")
        print("  macro                   宏观货币信用快照")
        print("  sentiment               市场情绪信号检测")
        print("  game-theory             博弈论知识摘要")
        print("  search-news <query>     金融资讯搜索")
        print("  screen <conditions>     条件选股")
        print("  related <symbol>        关联关系查询")
        print()
        print("🔧 交易 & 风控:")
        print("  backtest                运行回测")
        print("  backtest-optimize       参数优化")
        print("  backtest-compare        多策略对比")
        print("  paper-trade <action>    模拟交易管理")
        print("  trade-track <add|list|kelly>  交易追踪")
        print()
        print("📊 持仓监控 (NEW):")
        print("  position-monitor status  查看所有持仓摘要")
        print("  position-monitor check   实时检查更新止损")
        print("  position-monitor detail  单票详情")
        print("  pm                       同 position-monitor")
        print()
        print("🔔 盯盘 & 预警:")
        print("  sweep                   自选股扫雷")
        print("  alert watch-add <code>  加入自选股")
        print("  alert list              查看自选股")
        print("  alert panic <code>      恐慌套利检查")
        print()
        print("⚡ 短线/波段 (NEW):")
        print("  technical <code>        技术分析报告 (六维评分)")
        print("  swing-scan              波段选股扫描")
        print("  monitor [start|once]    实时盯盘监控")
        print("  timing <code>           T+0 日内时机分析 (建仓/加仓/减仓)")
        print("  macro-event <desc>      宏观事件因果链分析 (A股传导)")
        print()
        print("🕯️ K线形态 (NEW):")
        print("  patterns <code>         K线形态识别 (63种)")
        print("  indicators <code>       技术指标计算 (25种)")
        print()
        print("🧬 学习 & 进化:")
        print("  evolution <sub>         策略进化（论文驱动）")
        print("  calibrate               置信度校准")
        print("  learn report            学习报告")
        print("  profile                 用户能力画像")
        print("  preference <view|setup|edit>  投资者偏好管理")
        print("  feedback <add|summary>  交易反馈")
        print()
        print("🔬 Alpha 挖掘 (NEW):")
        print("  factor-backtest <id>    单因子回测 IC/IR/分层")
        print("  factor-scan             扫描所有因子绩效")
        print("  alpha-rank              全市场 Alpha 排名")
        print()
        print("🔍 归因分析 (NEW):")
        print("  attribute <code>         个股涨跌归因 (自动搜集+质量预检)")
        print()
        print("🏭 深度研究 (NEW):")
        print("  sector-research <行业>   行业全景研究")
        print("  deep-research <code>     公司深度研究")
        print()
        print("🏟️ 策略竞技场 (NEW):")
        print("  arena run               运行策略竞技场对比")
        print("  arena benchmark         快速基准测试（全部预置策略）")
        print("  arena list              历史竞技场记录")
        print("  arena show <id>         查看竞技场详情")
        print("  arena compare <id1> <id2>  跨期对比")
        print()
        print("📢 社交:")
        print("  poster --title --text   AI 社区发帖")
        print()
        print("💡 快速开始:")
        print("  python -m src start                    新手引导（推荐首次使用）")
        print("  python -m src diagnose 600519    # 一键诊断茅台")
        print("  python -m src analyze 000001     # 全链路分析平安银行")
        print()
        return

    cmd = sys.argv[1]
    args = sys.argv[2:]

    # --help 子命令: python -m src diagnose --help
    if "--help" in args or "-h" in args:
        args = [a for a in args if a not in ("--help", "-h")]
        _print_command_detail(cmd)
        return

    commands = {
        "health": cmd_health,
        "start": lambda: cmd_start(args),
        "scan": lambda: cmd_scan(args),
        "analyze": lambda: cmd_analyze(args) if args else print("用法: analyze <code> [--deep]"),
        "macro": cmd_macro,
        "sentiment": cmd_sentiment,
        "backtest": cmd_backtest,
        "verdict-backtest": cmd_verdict_backtest,
        "backtest-optimize": cmd_backtest_optimize,
        "backtest-compare": cmd_backtest_compare,
        "diagnose": lambda: cmd_diagnose(args) if args else print(
            "用法: diagnose <code> [--deep] [--no-t0] [--batch CODES] [--as-of DATE]"),
        "game-theory": cmd_game_theory,
        "patterns": lambda: cmd_patterns(args),
        "indicators": lambda: cmd_indicators(args),
        "topic": lambda: cmd_topic(args),
        "policy": lambda: cmd_policy(args),
        "manipulation": lambda: cmd_manipulation(args),
        "calibrate": cmd_calibrate,
        "profile": cmd_profile,
        "preference": lambda: cmd_preference(args),
        "feedback": lambda: cmd_feedback(args),
        "evolve": cmd_evolve,
        "learn": lambda: cmd_learn(args),
        # V4 妙想 Skill 命令
        "finance": lambda: cmd_finance(args),
        "search-news": lambda: cmd_search_news(args),
        "screen": lambda: cmd_screen(args),
        "related": lambda: cmd_related(args),
        "paper-trade": lambda: cmd_paper_trade(args),
        "poster": lambda: cmd_poster(args),
        # Phase 4: Alpha Lens 命令
        "alpha": lambda: cmd_alpha(args[0]) if args else print("用法: alpha <code>"),
        "alpha-scan": lambda: cmd_alpha_scan(args),
        "alpha-decay": lambda: cmd_alpha_decay(args[0]) if args else print("用法: alpha-decay <code>"),
        # Phase 5: 策略进化模块
        "evolution": lambda: cmd_evolution(args),
        # Phase 5: 凯利公式交易追踪
        "trade-track": lambda: cmd_trade_track(args),
        # 盯盘: 自选股扫雷 + 预警管理
        "sweep": lambda: cmd_sweep(args),
        "alert": lambda: cmd_alert(args),
        # Phase 7: 短线/波段
        "monitor": lambda: cmd_monitor(args),
        "technical": lambda: cmd_technical(args),
        "swing-scan": lambda: cmd_swing_scan(args),
        "timing": lambda: cmd_timing(args),
        "macro-event": lambda: cmd_macro_event(args),
        "attribute": lambda: cmd_attribute(args),
        # 策略竞技场
        "arena": lambda: cmd_arena(args),
        # Phase 8: Alpha 挖掘管线
        "factor-backtest": lambda: cmd_factor_backtest(args),
        "factor-scan": lambda: cmd_factor_scan(args),
        "alpha-rank": lambda: cmd_alpha_rank(args),
        # Phase 9: 行业深度 + 公司深度研究
        "sector-research": lambda: cmd_sector_research(args),
        "deep-research": lambda: cmd_deep_research(args),
        # Phase 12: 持仓实时监控 + 动态止盈止损
        "position-monitor": lambda: cmd_position_monitor(args),
        "pm": lambda: cmd_position_monitor(args),
        # Phase 12: 回调入场
        "pullback-scan": lambda: cmd_pullback_scan(args),
        "pullback-watch": lambda: cmd_pullback_watch(args),
        # 场景五: 程序化持仓/自选股记录
        "record-position": lambda: cmd_record_position(args[0], args[1], float(args[2]), int(args[3])) if len(args) >= 4 else print("用法: record-position <code> <名称> <价格> <数量>"),
        "update-watchlist": lambda: cmd_update_watchlist(args[0], args[1], float(args[2]) if len(args) >= 3 and args[2] else None, float(args[3]) if len(args) >= 4 and args[3] else None) if args else print("用法: update-watchlist <code> <名称> [止损价] [预警价]"),
        # 先行指标业绩研判
        "preview-earnings": lambda: cmd_preview_earnings(args),
    }

    handler = commands.get(cmd)
    if handler:
        try:
            handler()
        except ImportError as e:
            print(f"⚠️ 缺少依赖: {e}")
            print("   请运行: pip install -r requirements.txt")
        except Exception as e:
            print(f"❌ 错误: {e}")
            if os.environ.get("DEBUG"):
                traceback.print_exc()
            else:
                print("   (设置 DEBUG=1 查看详细错误信息)")
    else:
        # ---- 自然语言路由 ----
        nl_query = " ".join(sys.argv[1:])
        nl_result = _route_nl(nl_query) if nl_query else None
        if nl_result:
            print(f"🤖 理解: \"{nl_query}\" → 路由到 {nl_result['cmd']}")
            print(f"   等效命令: {nl_result['help']}")
            print()
            if nl_result["cmd"] == "sentiment":
                cmd_sentiment()
            elif nl_result["cmd"] == "macro":
                cmd_macro()
            elif nl_result["cmd"] == "backtest":
                cmd_backtest()
            elif nl_result["cmd"] == "sweep":
                cmd_sweep(args)
            elif nl_result["cmd"] == "start":
                cmd_start(args)
            elif nl_result["cmd"] in ("diagnose", "analyze", "technical", "patterns"):
                print(f"⚠️  '{nl_result['cmd']}' 需要股票代码 / needs stock code")
                print(f"   例: {nl_result['help']}")
            elif "scan" in nl_result["cmd"]:
                cmd_scan(args)
            elif nl_result["cmd"] == "evolution list":
                print("策略进化列表待实现 / evolution list TBD")
            elif nl_result["cmd"] == "preference setup":
                print("请运行 / Run: python -m src preference setup")
            else:
                print(f"   请使用 / Use: {nl_result['help']}")
        else:
            print(f"未知命令 / Unknown command: {cmd}")
            print(f"可用命令 / Available: {', '.join(sorted(commands.keys()))}")
            print(f"运行 / Run 'python -m src' 查看完整帮助 / for full help.")
            print()
            _print_nl_help()


if __name__ == "__main__":
    main()
