# -*- coding: utf-8 -*-
"""内部策略竞技场 — CLI 处理。

子命令:
    arena run        运行策略对比
    arena benchmark  快速基准测试（默认策略 + 默认参数）
    arena list       历史竞技场记录
    arena show <id>  查看单次详情
    arena compare <id1> <id2>  跨期对比
"""

from __future__ import annotations

import argparse

from .orchestrator import ArenaOrchestrator, PRESET_STRATEGIES
from .report import ArenaReport


def arena_cli_handler(args: list[str]) -> None:
    """CLI 入口，由 src/cli.py 调用。"""
    parser = argparse.ArgumentParser(
        prog="arena",
        description="🏟️ 内部策略竞技场 — 多策略横向对比回测",
    )
    sub = parser.add_subparsers(dest="subcommand", help="子命令")

    # ---- run ----
    p_run = sub.add_parser("run", help="运行竞技场对比")
    p_run.add_argument("--universe", default="csi300", help="股票池 (csi300 / custom逗号分隔)")
    p_run.add_argument("--start", default="2020-01-01", help="开始日期")
    p_run.add_argument("--end", default="2024-12-31", help="结束日期")
    p_run.add_argument("--strategies", default="", help="策略缩写 (逗号分隔，如 mvp1,mvp2)")
    p_run.add_argument("--cash", type=float, default=1_000_000, help="初始资金")
    p_run.add_argument("--engine", default="legacy", choices=["legacy", "v2"])
    p_run.add_argument("--walkforward", action="store_true", help="启用 Walk-Forward 过拟合检测")
    p_run.add_argument("--no-save", action="store_true", help="不保存会话")

    # ---- benchmark ----
    p_bench = sub.add_parser("benchmark", help="快速基准测试（所有预置策略）")
    p_bench.add_argument("--universe", default="csi300", help="股票池")
    p_bench.add_argument("--start", default="2020-01-01")
    p_bench.add_argument("--end", default="2024-12-31")

    # ---- list ----
    sub.add_parser("list", help="历史竞技场记录")

    # ---- show ----
    p_show = sub.add_parser("show", help="查看单次竞技场详情")
    p_show.add_argument("session_id", help="会话 ID")

    # ---- compare ----
    p_cmp = sub.add_parser("compare", help="跨期对比两个会话")
    p_cmp.add_argument("id1", help="会话 ID 1")
    p_cmp.add_argument("id2", help="会话 ID 2")

    parsed = parser.parse_args(args)

    if not parsed.subcommand:
        parser.print_help()
        return

    orchestrator = ArenaOrchestrator()

    if parsed.subcommand == "run":
        _handle_run(orchestrator, parsed)
    elif parsed.subcommand == "benchmark":
        _handle_benchmark(orchestrator, parsed)
    elif parsed.subcommand == "list":
        _handle_list(orchestrator)
    elif parsed.subcommand == "show":
        _handle_show(orchestrator, parsed.session_id)
    elif parsed.subcommand == "compare":
        _handle_compare(orchestrator, parsed.id1, parsed.id2)


# ---------------------------------------------------------------------------
# handlers
# ---------------------------------------------------------------------------

def _handle_run(orchestrator: ArenaOrchestrator, args) -> None:
    """运行自定义竞技场。"""
    # 解析策略
    if args.strategies:
        strat_keys = [s.strip() for s in args.strategies.split(",")]
    else:
        strat_keys = list(PRESET_STRATEGIES.keys())

    # 解析股票池
    from .orchestrator import CSI300_SAMPLE

    if args.universe == "csi300":
        universe = CSI300_SAMPLE[:]
        universe_name = "csi300_sample"
    else:
        universe = [s.strip() for s in args.universe.split(",")]
        universe_name = "custom"

    config = orchestrator.prepare(
        strategies=strat_keys,
        universe=universe,
        universe_name=universe_name,
        start_date=args.start,
        end_date=args.end,
        initial_cash=args.cash,
        engine_type=args.engine,
        use_walkforward=args.walkforward,
    )

    if args.no_save:
        config.save_session = False

    print(f"\n🏟️ 策略竞技场启动: {len(config.strategies)} 策略 × {len(universe)} 股票")
    print(f"   {args.start} → {args.end}  |  初始资金: {args.cash:,.0f}\n")

    session = orchestrator.run(config)

    # 输出
    reporter = ArenaReport()
    print(reporter.console_summary(session))
    print()

    if not args.no_save:
        print(f"💾 会话已保存: {session.session_id}")
    print(f"   查看详情: python -m src arena show {session.session_id}")


def _handle_benchmark(orchestrator: ArenaOrchestrator, args) -> None:
    """快速基准测试 — 运行所有预置策略。"""
    from .orchestrator import CSI300_SAMPLE

    if args.universe == "csi300":
        universe = CSI300_SAMPLE[:]
        universe_name = "csi300_sample"
    else:
        universe = [s.strip() for s in args.universe.split(",")]
        universe_name = "custom"

    config = orchestrator.prepare(
        strategies=None,  # 全部预置策略
        universe=universe,
        universe_name=universe_name,
        start_date=args.start,
        end_date=args.end,
    )

    n = len(config.strategies)
    print(f"\n🔥 基准测试: {n} 策略 × {len(universe)} 股票")
    print(f"   {args.start} → {args.end}\n")

    session = orchestrator.run(config)

    reporter = ArenaReport()
    print(reporter.console_summary(session))
    print()

    # 输出完整 Markdown
    print(reporter.markdown(session))
    print(f"\n💾 会话 ID: {session.session_id}")


def _handle_list(orchestrator: ArenaOrchestrator) -> None:
    """列出历史会话。"""
    sessions = orchestrator.list_sessions()
    if not sessions:
        print("📭 暂无竞技场记录。运行 `python -m src arena benchmark` 开始第一次对比。")
        return

    print(f"\n📚 竞技场历史记录 ({len(sessions)} 条):\n")
    print(f"  {'ID':<14s} {'日期':<21s} {'股票池':<16s} {'策略数':<8s} {'冠军':<20s}")
    print(f"  {'-'*12}  {'-'*19}  {'-'*14}  {'-'*6}  {'-'*18}")

    for s in sessions:
        print(
            f"  {s['id']:<14s} {s['created_at'][:19]:<21s} "
            f"{s['universe']:<16s} {s['n_strategies']:<8d} {s['winner']:<20s}"
        )
    print()


def _handle_show(orchestrator: ArenaOrchestrator, session_id: str) -> None:
    """查看会话详情。"""
    session = orchestrator.load_session(session_id)
    if not session:
        print(f"❌ 会话不存在: {session_id}")
        return

    reporter = ArenaReport()
    print()
    print(reporter.markdown(session))

    # 尝试生成雷达图
    chart_path = reporter.radar_chart(session)
    if chart_path:
        print(f"📊 雷达图: {chart_path}")
    else:
        print("(雷达图不可用 — 需安装 matplotlib)")


def _handle_compare(
    orchestrator: ArenaOrchestrator, id1: str, id2: str
) -> None:
    """跨会话对比。"""
    result = orchestrator.compare_sessions(id1, id2)
    if not result:
        print("❌ 无法对比 — 请确认两个会话 ID 均有效且包含相同策略")
        return

    print(f"\n📊 跨期对比: {id1} vs {id2}\n")
    print(f"  {'策略':<20s} {'Sharpe 变化':>10s} {'收益变化':>10s} {'回撤变化':>10s}")
    print(f"  {'-'*18}  {'-'*8}  {'-'*8}  {'-'*8}")

    for r in result:
        sd = r["sharpe_delta"]
        rd = r["return_delta"]
        dd = r["dd_delta"]
        s_emoji = "📈" if sd > 0 else "📉"
        print(
            f"  {r['strategy']:<20s} {s_emoji} {sd:+.2f}    {rd:+.1f}%    {dd:+.1f}%"
        )
    print()
