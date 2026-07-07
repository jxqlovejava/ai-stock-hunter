# -*- coding: utf-8 -*-
"""CLI 统一入口 — 白泽 (Baize) A 股智能投资决策系统。

用法:
  python -m src.cli scan [--preset value]         # 全市场选股扫描
  python -m src.cli analyze <code>                # 单只股票全链路分析
  python -m src.cli diagnose <code>               # 一键诊断（小白入口）
  python -m src.cli alpha <code>                  # Alpha Lens 三维评估
  python -m src.cli alpha-scan [--limit N]        # 高 Alpha 股票扫描
  python -m src.cli alpha-decay <code>            # Alpha 衰减追踪
  python -m src.cli macro                         # 宏观快照
  python -m src.cli sentiment                     # 情绪信号检测
  python -m src.cli backtest                      # 运行回测
  python -m src.cli backtest-optimize             # 参数优化
  python -m src.cli backtest-compare              # 多策略对比
  python -m src.cli game-theory                   # 博弈论知识摘要
  python -m src.cli calibrate                     # 置信度校准报告
  python -m src.cli profile                       # 用户能力画像
  python -m src.cli preference <view|setup|edit|reset>  # 投资者偏好管理
  python -m src.cli feedback <add|summary>        # 交易反馈
  python -m src.cli learn report                  # 生成学习报告
  python -m src.cli search-news <query>           # 金融资讯搜索
  python -m src.cli screen <conditions>           # 条件选股
  python -m src.cli related <symbol>              # 关联关系查询
  python -m src.cli paper-trade <action>          # 模拟交易管理
  python -m src.cli poster --title --text         # AI 社区发帖
  python -m src.cli evolution <sub>               # 策略进化（论文驱动）
  python -m src.cli trade-track <add|list|kelly>  # 交易追踪（凯利公式）

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


def _validate_symbol(symbol: str) -> bool:
    """验证 A 股股票代码格式 (6 位数字)。"""
    if not re.match(r"^\d{6}$", symbol):
        print(f"❌ 无效股票代码: {symbol} (需要 6 位数字，如 600519)")
        return False
    return True


def _infer_market(symbol: str) -> str:
    """根据股票代码前缀推断市场。"""
    if symbol.startswith(("600", "601", "603", "605", "688")):
        return "SH"
    return "SZ"


def _safe_cmd(func: Callable) -> Callable:
    """统一错误处理装饰器 — 捕获异常并打印友好消息。"""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except ImportError as e:
            print(f"⚠️ 缺少依赖: {e}")
            print("   请运行: pip install -r requirements.txt")
        except Exception as e:
            print(f"❌ 错误: {e}")
            if os.environ.get("DEBUG"):
                traceback.print_exc()
            else:
                print("   (设置 DEBUG=1 查看详细错误信息)")

    return wrapper


def _run_command(handler: Callable) -> Callable:
    """包装命令函数，添加股票代码验证和错误处理。"""
    return _safe_cmd(handler)


@_safe_cmd
def cmd_scan(args: list[str]):
    """全市场选股扫描。"""
    import argparse
    from src.data.aggregator import DataAggregator
    from src.routing.l1_analyze import L1Analyzer, SCREENING_PRESETS

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
    print(f"扫描范围: {len(stocks)} 只股票")

    if not stocks:
        print("⚠️ 无可用股票数据")
        return

    analyzer = L1Analyzer()
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
def cmd_analyze(symbol: str):
    """单只股票全链路分析。"""
    if not _validate_symbol(symbol):
        return
    from src.routing.orchestrator import Orchestrator
    from src.output.formatter import format_analysis_result

    print(f"📊 分析 {symbol}")
    orch = Orchestrator()
    result = orch.run(symbol, market=_infer_market(symbol))

    if not result.passed:
        print(f"⛔ 不通过: {', '.join(result.blocked_by)}")
        if result.warnings:
            print(f"⚠️  警告: {', '.join(result.warnings)}")
        return

    # 使用详细输出格式化器
    print(format_analysis_result(result))


def cmd_macro():
    """宏观快照。"""
    from src.macro.output import MacroSystemizedOutput, IndicatorSnapshot, QUADRANT_SECTOR_MAP

    print("🌍 宏观货币信用快照")
    try:
        from src.macro.monetary_credit import MonetaryCreditAnalyzer
        analyzer = MonetaryCreditAnalyzer()
        regime = analyzer.analyze()
        if regime is not None:
            quadrant_name = regime.quadrant.value
            quadrant_info = QUADRANT_SECTOR_MAP.get(quadrant_name, {})
            output = MacroSystemizedOutput(
                date=regime.date or "",
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


@_safe_cmd
def cmd_sentiment():
    """情绪信号检测。"""
    from src.sentiment.signals import SentimentDetector

    print("📈 情绪信号")
    detector = SentimentDetector()
    sentiment = detector.detect_market()
    print(f"大盘情绪: {sentiment.level.value} (score={sentiment.score})")


def cmd_backtest():
    """运行 MVP1 回测。"""
    print("📊 回测")
    print("(Phase 3: 待接入完整因子数据管道)")


def cmd_backtest_optimize():
    """参数优化。"""
    print("🔧 参数优化")
    from src.backtest import GridSearchOptimizer, StrategyRegistry
    print("优化器已就绪。使用 GridSearchOptimizer 进行参数网格搜索。")
    print("(需提供数据源和策略类以运行完整优化)")


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
def cmd_diagnose(symbol: str):
    """一键诊断（小白入口）。"""
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
    cmd_analyze(symbol)


@_safe_cmd
def cmd_game_theory():
    """博弈论知识摘要。"""
    from src.game_theory import get_game_theory_summary
    print(get_game_theory_summary())


def cmd_calibrate():
    """置信度校准报告。"""
    print("📐 置信度校准")
    print("⏳ Phase 4: 样本量 < 20，不出报告。使用 trade-track add 录入交易后运行 calibrate。")


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
    elif sub == "path":
        print(os.path.abspath(loader.path))
    else:
        print(f"未知子命令: {sub}，可用: view | setup | edit | reset | path")


def _cmd_preference_setup(loader):
    """交互式投资者画像设置向导 — 10 步完整画像。"""
    from datetime import datetime
    from src.learner.preference.model import (
        InvestorPreference, RiskProfile, InvestmentGoal,
        TradingStyle, InvestorTier, HoldingPeriod, PositionLimits,
    )

    prefs = loader.load()
    step = 0

    print("\n🎯 投资者画像设置向导")
    print("=" * 50)
    print("花 3 分钟设置你的专属画像，分析引擎会根据你的实际情况")
    print("调整 L2 评分权重、L3 仓位建议、L4 风控参数。")
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
        print(f"\n📋 L2 裁决: {v.score}/100 | 建议: {v.recommendation}")
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
        print(f"扫描范围: {len(stocks)} 只股票")
    except Exception as e:
        print(f"⚠️ 扫描失败: {e}")
        return

    lens = AlphaLens()
    results: list[tuple[str, str, float, str]] = []

    for stock in stocks[:50]:  # 限制扫描数量
        symbol = stock.get("symbol", "")
        name = stock.get("name", "")
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
        print(
            f"  {rank:2d}. {sym} {name:<8s} "
            f"Alpha {score:.0f} | 叙事: {emoji.get(stage, '❓')} {stage}"
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
            quote = agg.get_realtime_quote(sym)
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


def main():
    """白泽 CLI 主入口。"""

    # 配置日志
    log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(levelname)s [%(name)s] %(message)s",
    )

    if len(sys.argv) < 2:
        print("白泽 (Baize) — A 股智能投资决策系统 v0.1.0")
        print()
        print("用法: python -m src <command> [args]")
        print()
        print("📊 核心分析:")
        print("  analyze <code>         单只股票全链路分析")
        print("  diagnose <code>        一键诊断（小白入口）")
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
        print("🔔 盯盘 & 预警:")
        print("  sweep                   自选股扫雷")
        print("  alert watch-add <code>  加入自选股")
        print("  alert list              查看自选股")
        print("  alert panic <code>      恐慌套利检查")
        print()
        print("🧬 学习 & 进化:")
        print("  evolution <sub>         策略进化（论文驱动）")
        print("  calibrate               置信度校准")
        print("  learn report            学习报告")
        print("  profile                 用户能力画像")
        print("  preference <view|setup|edit>  投资者偏好管理")
        print("  feedback <add|summary>  交易反馈")
        print()
        print("📢 社交:")
        print("  poster --title --text   AI 社区发帖")
        print()
        print("💡 快速开始:")
        print("  python -m src diagnose 600519    # 一键诊断茅台")
        print("  python -m src analyze 000001     # 全链路分析平安银行")
        print()
        return

    cmd = sys.argv[1]
    args = sys.argv[2:]

    commands = {
        "scan": lambda: cmd_scan(args),
        "analyze": lambda: cmd_analyze(args[0]) if args else print("用法: analyze <code>"),
        "macro": cmd_macro,
        "sentiment": cmd_sentiment,
        "backtest": cmd_backtest,
        "backtest-optimize": cmd_backtest_optimize,
        "backtest-compare": cmd_backtest_compare,
        "diagnose": lambda: cmd_diagnose(args[0]) if args else print("用法: diagnose <code>"),
        "game-theory": cmd_game_theory,
        "calibrate": cmd_calibrate,
        "profile": cmd_profile,
        "preference": lambda: cmd_preference(args),
        "feedback": lambda: cmd_feedback(args),
        "evolve": cmd_evolve,
        "learn": lambda: cmd_learn(args),
        # V4 妙想 Skill 命令
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
        print(f"未知命令: {cmd}")
        print("可用命令: " + ", ".join(sorted(commands.keys())))
        print("运行 python -m src 查看完整帮助。")


if __name__ == "__main__":
    main()
