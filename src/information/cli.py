"""I-Layer CLI — 消息面深度分析引擎命令行入口。

使用方式:
    python -m src.information.cli topic create --name "国产AI算力扩容" ...
    python -m src.information.cli topic list
    python -m src.information.cli topic show <id>
    python -m src.information.cli topic analyze <id>
    python -m src.information.cli topic report <id>
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta

from src.information.nlp import KeywordNLPProcessor
from src.information.schema import LifecycleStage, TopicSnapshot
from src.information.sources.financial_news import FinancialNewsSource
from src.information.sources.social_media import SocialMediaSource
from src.information.topic_manager import TopicManager


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="information",
        description="I-Layer: 消息面深度分析引擎",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # topic create
    p_create = sub.add_parser("topic", help="主题管理")
    topic_sub = p_create.add_subparsers(dest="topic_action", required=True)

    _create = topic_sub.add_parser("create", help="创建新主题")
    _create.add_argument("--name", required=True, help="主题名称")
    _create.add_argument("--id", default=None, help="主题 ID（默认从名称生成）")
    _create.add_argument("--description", default="", help="主题描述")
    _create.add_argument("--keywords", default="", help="搜索关键词（逗号分隔）")
    _create.add_argument("--stocks", default="", help="关联股票代码（逗号分隔）")
    _create.add_argument("--sectors", default="", help="关联行业（逗号分隔）")
    _create.add_argument("--hypothesis", default="", help="核心假设")
    _create.add_argument("--conditions", default="", help="可验证条件（逗号分隔）")
    _create.add_argument("--tags", default="", help="分类标签（逗号分隔）")

    _list = topic_sub.add_parser("list", help="列出所有主题")
    _list.add_argument("--all", dest="show_all", action="store_true", help="包含已停用")

    _show = topic_sub.add_parser("show", help="查看主题详情")
    _show.add_argument("topic_id", help="主题 ID")

    _delete = topic_sub.add_parser("delete", help="删除主题")
    _delete.add_argument("topic_id", help="主题 ID")

    _report = topic_sub.add_parser("report", help="生成主题分析快照")
    _report.add_argument("topic_id", help="主题 ID")
    _report.add_argument("--json", action="store_true", help="JSON 格式输出")

    _analyze = topic_sub.add_parser("analyze", help="手动触发分析（采集+情感）")
    _analyze.add_argument("topic_id", help="主题 ID")
    _analyze.add_argument("--sources", default="social_media,financial_news", help="信源列表")
    _analyze.add_argument("--days", type=int, default=7, help="回看天数")

    # 生命周期
    p_lifecycle = sub.add_parser("lifecycle", help="生命周期管理")
    p_lifecycle.add_argument("topic_id", help="主题 ID")
    p_lifecycle.add_argument(
        "--set",
        choices=[s.value for s in LifecycleStage],
        help="设置生命周期阶段",
    )

    args = parser.parse_args()
    mgr = TopicManager()

    if args.command == "topic":
        _handle_topic(args, mgr)
    elif args.command == "lifecycle":
        _handle_lifecycle(args, mgr)


def _handle_topic(args: argparse.Namespace, mgr: TopicManager) -> None:
    action = args.topic_action

    if action == "create":
        topic = mgr.create(
            name=args.name,
            topic_id=args.id,
            description=args.description,
            keywords=[k.strip() for k in args.keywords.split(",") if k.strip()],
            related_stocks=[s.strip() for s in args.stocks.split(",") if s.strip()],
            related_sectors=[s.strip() for s in args.sectors.split(",") if s.strip()],
            core_hypothesis=args.hypothesis,
            verifiable_conditions=[c.strip() for c in args.conditions.split(",") if c.strip()],
            tags=[t.strip() for t in args.tags.split(",") if t.strip()],
        )
        path = mgr._path(topic.id)
        print(f"✅ 主题已创建: {topic.name} ({topic.id})")
        print(f"   文件: {path}")

    elif action == "list":
        topics = mgr.list_all() if args.show_all else mgr.list_active()
        if not topics:
            print("(暂无主题)")
            return
        print(f"{'ID':<30} {'名称':<20} {'阶段':<12} {'活跃':<6}")
        print("-" * 70)
        for t in topics:
            flag = "✅" if t.is_active else "❌"
            print(f"{t.id:<30} {t.name:<20} {t.lifecycle_stage.value:<12} {flag:<6}")

    elif action == "show":
        topic = mgr.get(args.topic_id)
        if not topic:
            print(f"❌ 主题 '{args.topic_id}' 不存在")
            sys.exit(1)
        print(f"名称: {topic.name}")
        print(f"ID: {topic.id}")
        print(f"描述: {topic.description}")
        print(f"阶段: {topic.lifecycle_stage.value}")
        print(f"关键词: {', '.join(topic.keywords)}")
        print(f"关联股票: {', '.join(topic.related_stocks)}")
        print(f"关联行业: {', '.join(topic.related_sectors)}")
        print(f"核心假设: {topic.core_hypothesis}")
        print(f"可验证条件: {', '.join(topic.verifiable_conditions)}")
        print(f"标签: {', '.join(topic.tags)}")
        print(f"活跃: {topic.is_active}")
        print(f"版本: {topic.version}")
        print(f"创建: {topic.created_at.isoformat()}")
        print(f"更新: {topic.updated_at.isoformat()}")

    elif action == "delete":
        ok = mgr.delete(args.topic_id)
        if ok:
            print(f"✅ 已删除: {args.topic_id}")
        else:
            print(f"❌ 主题 '{args.topic_id}' 不存在")
            sys.exit(1)

    elif action == "report":
        topic = mgr.get(args.topic_id)
        if not topic:
            print(f"❌ 主题 '{args.topic_id}' 不存在")
            sys.exit(1)

        # 生成简易快照（无真实数据时用占位值）
        snapshot = TopicSnapshot(
            topic=topic,
            lifecycle_stage=topic.lifecycle_stage,
        )

        if args.json:
            print(snapshot.model_dump_json(indent=2))
        else:
            print(f"📊 主题快照: {topic.name}")
            print(f"   阶段: {topic.lifecycle_stage.value}")
            print(f"   关联股票: {', '.join(topic.related_stocks) or '(无)'}")
            print(f"   共识度: (需要运行 analyze 采集数据)")
            print(f"   分歧信号: (需要运行 analyze 采集数据)")
            print(f"   定价度: (需要运行 analyze 采集数据)")

    elif action == "analyze":
        topic = mgr.get(args.topic_id)
        if not topic:
            print(f"❌ 主题 '{args.topic_id}' 不存在")
            sys.exit(1)

        print(f"🔍 分析主题: {topic.name}")
        print(f"   信源: {args.sources}")
        print(f"   回看: {args.days} 天")
        print()
        print("⚠️  采集需要 Claude Code orchestrator 调用 Skill 工具。")
        print("   Python CLI 仅提供数据模型和处理逻辑。")
        print()
        print("   可用的信源适配器:")
        print(f"   - SocialMediaSource ({SocialMediaSource.meta.label})")
        print(f"   - FinancialNewsSource ({FinancialNewsSource.meta.label})")
        print()
        print("   分析流程:")
        print("   1. orchestrator 调用 Skill(last30days-cn) 采集社交媒体")
        print("   2. orchestrator 调用 AKShare 采集财经新闻")
        print("   3. 结果传入 NLP 管道做情感分析")
        print("   4. 生成 TopicSnapshot → 消费方 诊断/裁决")


def _handle_lifecycle(args: argparse.Namespace, mgr: TopicManager) -> None:
    if args.set:
        stage = LifecycleStage(args.set)
        topic = mgr.update_lifecycle(args.topic_id, stage)
        print(f"✅ {topic.name} → {stage.value}")
    else:
        topic = mgr.get(args.topic_id)
        if not topic:
            print(f"❌ 主题 '{args.topic_id}' 不存在")
            sys.exit(1)
        print(f"当前阶段: {topic.lifecycle_stage.value}")


if __name__ == "__main__":
    main()
