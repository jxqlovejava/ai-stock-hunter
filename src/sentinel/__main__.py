# -*- coding: utf-8 -*-
"""python -m src.sentinel 入口。

Hermes 约定:
  - 无异动：stdout 为空，exit 0
  - 有异动：stdout 打印人话卡片，exit 0
  - 致命错误：stderr 打印，exit 1

频道 (--mode):
  alert      持仓告警 + 大盘/板块/两融旁注（默认，包1）
  funds      两融 + 自选扫雷（包2）
  margin     仅两融
  watchlist  仅自选扫雷
  open       开盘前简报（包3）
  close      收盘简报（包3）
  sentiment  情绪/北向极端（包4）
  entry_signal  入场信号监测（融资回升+下影缩量）
  auto       按北京时间粗选
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .channels import ChannelConfig, run_channel


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="白泽持仓哨兵 / 微信推送频道")
    parser.add_argument(
        "--mode",
        default=os.environ.get("BAIZE_SENTINEL_MODE", "alert"),
        help="alert|funds|margin|watchlist|entry_signal|open|close|sentiment|auto",
    )
    parser.add_argument("--positions", type=Path, default=None)
    parser.add_argument("--state", type=Path, default=None)
    parser.add_argument("--watchlist", type=Path, default=None)
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument(
        "--force",
        action="store_true",
        help="忽略交易时段/部分冷却（测试）",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="调试 JSON（仅 alert 模式完整；其他模式输出 message）",
    )
    parser.add_argument(
        "--quiet-errors",
        action="store_true",
        help="失败也静默",
    )
    args = parser.parse_args(argv)

    config_path = args.config
    if config_path is None and os.environ.get("BAIZE_SENTINEL_CONFIG"):
        config_path = Path(os.environ["BAIZE_SENTINEL_CONFIG"])

    cfg_dict: dict = {}
    if config_path and config_path.exists():
        try:
            cfg_dict = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cfg_dict = {}

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
    default_wl = Path(
        os.environ.get(
            "BAIZE_WATCHLIST",
            cfg_dict.get("watchlist_path", "data/watchlist.json"),
        )
    )
    default_pf = Path(
        cfg_dict.get("portfolio_path", "data/portfolio.yaml")
    )

    ch = ChannelConfig(
        positions_path=args.positions or default_pos,
        state_path=args.state or default_state,
        portfolio_path=default_pf,
        watchlist_path=args.watchlist or default_wl,
        force=bool(args.force),
        cool_margin=int(cfg_dict.get("cool_margin", 180)),
        cool_watchlist=int(cfg_dict.get("cool_watchlist", 60)),
        cool_sentiment=int(cfg_dict.get("cool_sentiment", 120)),
        enable_margin=cfg_dict.get("enable_margin", True),
        enable_watchlist=cfg_dict.get("enable_watchlist", True),
        enable_context=cfg_dict.get("enable_context", True),
        kline_cache_dir=Path(
            cfg_dict.get("kline_cache_dir", "data/kline_cache")
        ),
    )

    mode = (args.mode or "alert").lower()

    try:
        message = run_channel(mode, ch)
    except Exception as e:
        if not args.quiet_errors:
            print(f"❌ 哨兵异常: {e}", file=sys.stderr)
        return 1

    if args.as_json:
        print(
            json.dumps(
                {
                    "mode": mode,
                    "silent": not bool((message or "").strip()),
                    "message": message or "",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if not (message or "").strip():
        return 0

    print(message, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
