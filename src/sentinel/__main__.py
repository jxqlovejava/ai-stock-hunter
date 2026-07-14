# -*- coding: utf-8 -*-
"""python -m src.sentinel 入口。

Hermes 约定:
  - 无异动：stdout 为空，exit 0
  - 有异动：stdout 打印卡片，exit 0
  - 致命错误：stderr 打印，exit 1（可选 --quiet-errors 改为静默）
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .engine import SentinelConfig, SentinelEngine


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="白泽持仓哨兵")
    parser.add_argument(
        "--positions",
        type=Path,
        default=None,
        help="positions.json 路径（默认 data/positions.json）",
    )
    parser.add_argument(
        "--state",
        type=Path,
        default=None,
        help="状态文件路径（默认 data/sentinel_state.json）",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="可选 JSON 配置覆盖阈值",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="忽略交易时段（测试/补跑）",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="输出 JSON（调试用；Hermes 推送请用默认文本）",
    )
    parser.add_argument(
        "--quiet-errors",
        action="store_true",
        help="报价失败也不打印，保持静默",
    )
    args = parser.parse_args(argv)

    import os

    # 配置文件：--config > 环境变量 > 无
    config_path = args.config
    if config_path is None and os.environ.get("BAIZE_SENTINEL_CONFIG"):
        config_path = Path(os.environ["BAIZE_SENTINEL_CONFIG"])

    cfg_dict: dict = {}
    if config_path and config_path.exists():
        cfg_dict = json.loads(config_path.read_text(encoding="utf-8"))

    # 路径默认：优先仓库 data/，Hermes 上可用环境变量覆盖
    default_pos = Path(
        os.environ.get(
            "BAIZE_POSITIONS",
            cfg_dict.get("positions_path", "data/positions.json"),
        )
    )
    default_state = Path(
        os.environ.get(
            "BAIZE_SENTINEL_STATE",
            cfg_dict.get("state_path", "data/sentinel_state.json"),
        )
    )

    cfg = SentinelConfig.from_dict(cfg_dict)
    cfg.positions_path = args.positions or default_pos
    cfg.state_path = args.state or default_state
    if args.force:
        cfg.force_trading_hours = True

    engine = SentinelEngine(cfg)
    try:
        result = engine.run()
    except Exception as e:
        if not args.quiet_errors:
            print(f"❌ 哨兵异常: {e}", file=sys.stderr)
        return 1

    if args.as_json:
        payload = {
            "silent": result.silent,
            "scanned": result.scanned,
            "errors": result.errors,
            "alerts": [
                {
                    "level": a.level.value,
                    "rule_id": a.rule_id,
                    "symbol": a.symbol,
                    "name": a.name,
                    "title": a.title,
                    "body": a.body,
                    "price": a.price,
                }
                for a in result.alerts
            ],
            "message": result.message,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    # Hermes: 无输出 = 不通知
    if result.silent or not result.message.strip():
        # 仅错误且非 quiet 时写 stderr，避免误推送
        if result.errors and not args.quiet_errors:
            print("⚠️ " + "; ".join(result.errors[:3]), file=sys.stderr)
        return 0

    print(result.message, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
