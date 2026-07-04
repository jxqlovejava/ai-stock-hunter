# -*- coding: utf-8 -*-
"""CLI 统一入口。

用法:
  python -m src.cli scan              # 全市场选股扫描
  python -m src.cli analyze 600519    # 单只股票全链路分析
  python -m src.cli macro             # 宏观快照
  python -m src.cli sentiment         # 情绪信号检测
  python -m src.cli backtest          # 运行回测
  python -m src.cli backtest-optimize # 参数优化
  python -m src.cli backtest-compare  # 多策略对比
  python -m src.cli diagnose 600519   # 一键诊断（小白入口）
  python -m src.cli game-theory       # 博弈论知识摘要
  python -m src.cli calibrate         # 置信度校准报告
  python -m src.cli profile           # 用户能力画像
  python -m src.cli feedback add      # 添加交易反馈
  python -m src.cli feedback summary  # 查看反馈统计
  python -m src.cli evolve            # 运行策略进化
  python -m src.cli learn report      # 生成学习报告
"""

from __future__ import annotations

import sys

from src.data.aggregator import DataAggregator
from src.doctrine.checker import DoctrineChecker
from src.game_theory import get_game_theory_summary
from src.learner import (
    DecisionJournal,
    EvolutionPipeline,
    FeedbackCollector,
    LearningReport,
    ProfileTracker,
    ReportGenerator,
    RuleCalibrator,
    SignalTracker,
    UserProfile,
)
from src.routing.orchestrator import Orchestrator
from src.sentiment.signals import SentimentDetector


def cmd_scan(args: list[str]):
    """全市场选股扫描。"""
    print("🔍 全市场选股扫描")
    agg = DataAggregator()
    status = agg.source_status()
    print(f"数据源: {status}")
    print("(Phase 3: 待接入因子筛选引擎)")


def cmd_analyze(symbol: str):
    """单只股票全链路分析。"""
    print(f"📊 分析 {symbol}")
    orch = Orchestrator()
    result = orch.run(symbol)
    if not result.passed:
        print(f"⛔ 不通过: {', '.join(result.blocked_by)}")
        return
    if result.warnings:
        print(f"⚠️  警告: {', '.join(result.warnings)}")
    if result.verdict:
        v = result.verdict
        print(f"评分: {v.score}/100  置信度: {v.confidence:.0%}  建议: {v.recommendation}")
    if result.risk:
        r = result.risk
        print(f"仓位: {r.adjusted_weight:.1%}  风控: {'✅' if r.passed else '⚠️ ' + ', '.join(r.violations)}")


def cmd_macro():
    """宏观快照。"""
    print("🌍 宏观快照")
    print("(Phase 3: 待接入国信宏观 API)")


def cmd_sentiment():
    """情绪信号检测。"""
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


def cmd_diagnose(symbol: str):
    """一键诊断（小白入口）。"""
    print(f"🏥 诊断 {symbol}")
    checker = DoctrineChecker()
    result = checker.check(symbol, {"stock_name": ""})
    if result.passed:
        print("✅ 军规通过 — 无硬阻断")
    else:
        print(f"⛔ 被拦截: {', '.join(r.name for r in result.blocked_by)}")
    cmd_analyze(symbol)


def cmd_game_theory():
    """博弈论知识摘要。"""
    print(get_game_theory_summary())


def cmd_calibrate():
    """置信度校准报告。"""
    print("📐 置信度校准")
    print("(Phase 4: 样本量 < 20，不出报告)")


def cmd_profile():
    """用户能力画像。"""
    print("👤 用户能力画像")
    tracker = ProfileTracker()
    profile = tracker.evaluate()
    print(profile.summary)


def cmd_feedback(args: list[str]):
    """用户反馈管理。"""
    sub = args[0] if args else "summary"
    collector = FeedbackCollector(db_path=":memory:")

    if sub == "add":
        print("💬 添加反馈")
        print("FeedbackCollector 已就绪。使用 agree/disagree/adjust/annotate 方法记录反馈。")
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
    """运行策略进化。"""
    print("🧬 策略进化")
    print("EvolutionPipeline 已就绪。")
    print("流程: 收集证据 → 分析弱点 → 生成建议 → 回测验证 → 部署")
    print("(需提供 engine_factory + registry + feedback 以运行完整进化)")


def cmd_learn(args: list[str]):
    """学习报告。"""
    sub = args[0] if args else "report"
    if sub == "report":
        print("📝 学习报告")
        gen = ReportGenerator()
        tracker = ProfileTracker()
        report = gen.generate(profile=tracker.evaluate(), period="weekly")
        print(report.render())
    else:
        print(f"未知子命令: {sub}，可用: report")


def main():
    if len(sys.argv) < 2:
        print("用法: python -m src.cli <command> [args]")
        print("  scan | analyze <code> | macro | sentiment | backtest")
        print("  backtest-optimize | backtest-compare")
        print("  diagnose <code> | game-theory | calibrate | profile")
        print("  feedback <add|summary> | evolve | learn <report>")
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
        "feedback": lambda: cmd_feedback(args),
        "evolve": cmd_evolve,
        "learn": lambda: cmd_learn(args),
    }

    handler = commands.get(cmd)
    if handler:
        handler()
    else:
        print(f"未知命令: {cmd}")
        print("可用: " + ", ".join(commands.keys()))


if __name__ == "__main__":
    main()
