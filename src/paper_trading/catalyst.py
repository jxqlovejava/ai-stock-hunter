# -*- coding: utf-8 -*-
"""催化信号监控器 — 政策/业绩/宏观/个股信号主动监控 (2026-08-08).

主动监控 5 类催化信号, 命中即微信推送 (Hermes stdout 约定):
  --mode price   价格买点/风险阈值 (特变电工 ≤18.13 等)
  --mode news    政策新闻关键词 (特高压招标/十五五细则/国网资本开支)
  --mode stock   个股信号 (沃尔核材融资止跌/洗盘企稳)
  --mode pmi     宏观 PMI (荣枯线 50)

配置: data/paper_trading/catalyst_rules.json (可编辑)
去重: 同规则命中后冷却 (price/stock 24h, news 6h)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

RULES_PATH = Path(
    "data/paper_trading/catalyst_rules.json"
)
DEDUP_PATH = Path("data/paper_trading/catalyst_dedup.json")

# 去重冷却 (小时)
PRICE_COOLDOWN_H = 24
NEWS_COOLDOWN_H = 6
STOCK_COOLDOWN_H = 24


def _load_rules() -> dict:
    try:
        return json.loads(RULES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _load_dedup() -> dict:
    try:
        return json.loads(DEDUP_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _dedup_ok(key: str, hours: int) -> bool:
    data = _load_dedup()
    last = data.get(key)
    if last:
        try:
            if datetime.now() - datetime.fromisoformat(last) < timedelta(hours=hours):
                return False
        except ValueError:
            pass
    data[key] = datetime.now().isoformat()
    try:
        DEDUP_PATH.parent.mkdir(parents=True, exist_ok=True)
        DEDUP_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass
    return True


def _market_of(symbol: str) -> str:
    return "SH" if symbol.startswith(("6", "68")) else "SZ"


# ══════════════════════════════════════════════════════════════════
# 价格买点/风险警报
# ══════════════════════════════════════════════════════════════════
def check_price(rules: dict) -> list[str]:
    from src.data.aggregator import DataAggregator
    agg = DataAggregator()
    hits: list[str] = []
    for r in rules.get("price_alerts", []):
        sym, name = r.get("symbol", ""), r.get("name", "")
        threshold = float(r.get("threshold", 0))
        direction = r.get("direction", "<=")
        if not sym or threshold <= 0:
            continue
        try:
            q = agg.get_quote(sym, _market_of(sym))
            if q is None:
                continue
            price = getattr(q, "price", 0) or 0
            hit = (price <= threshold) if direction == "<=" else (price >= threshold)
            if hit and _dedup_ok(f"price:{sym}:{direction}:{threshold}", PRICE_COOLDOWN_H):
                hits.append(
                    f"⚡ {r.get('message', f'{name}触发')} — 现价 {price:.2f} "
                    f"(阈值 {direction} {threshold:.2f})"
                )
        except Exception:
            continue
    return hits


# ══════════════════════════════════════════════════════════════════
# 政策新闻关键词
# ══════════════════════════════════════════════════════════════════
def check_news(rules: dict) -> list[str]:
    """东财 7×24 快讯关键词匹配 (零鉴权, Hermes 可用)。"""
    try:
        from src.data.eastmoney_fallback import fetch_em_global_news
    except ImportError:
        return []
    hits: list[str] = []
    try:
        items = fetch_em_global_news(page_size=80)
    except Exception:
        return []
    for rule in rules.get("news_keywords", []):
        kws = rule.get("keywords", [])
        if not kws:
            continue
        key = "|".join(kws)
        for item in items:
            text = f"{item.get('title', '')} {item.get('summary', '')}"
            if all(k in text for k in kws):
                if _dedup_ok(f"news:{key}", NEWS_COOLDOWN_H):
                    t = item.get("time", "")
                    hits.append(
                        f"{rule.get('message', '新闻催化')} — {item.get('title', '')[:60]} ({t})"
                    )
                break  # 每规则最多一条
    return hits


# ══════════════════════════════════════════════════════════════════
# 个股信号 (沃尔核材)
# ══════════════════════════════════════════════════════════════════
def check_stock(rules: dict) -> list[str]:
    hits: list[str] = []
    for r in rules.get("stock_signals", []):
        sym, name = r.get("symbol", ""), r.get("name", "")
        signal = r.get("signal", "")
        if not sym:
            continue
        key = f"stock:{sym}:{signal}"
        if signal == "margin_reversal":
            try:
                from src.sentinel.channels import _check_margin_reversal
                msg = _check_margin_reversal(sym, name)
                if msg and _dedup_ok(key, STOCK_COOLDOWN_H):
                    hits.append(f"💊 {r.get('message', '')} — {msg}")
            except Exception:
                continue
        elif signal == "washout_reclaim":
            try:
                from src.data.aggregator import DataAggregator
                import pandas as pd
                agg = DataAggregator()
                bars = agg.get_history(sym)
                if bars is None or getattr(bars, "empty", True):
                    continue
                closes = bars["close"].astype(float)
                vols = bars["volume"].astype(float)
                if len(closes) < 15 or len(vols) < 15:
                    continue
                # 洗盘企稳: 近5日回调 + 今日缩量 + 收回MA10上方
                ma10 = closes.rolling(10).mean()
                pullback = closes.iloc[-6] > closes.iloc[-1]  # 5日回落
                shrink = vols.iloc[-1] < vols.iloc[-5:].mean() * 0.8
                reclaim = closes.iloc[-1] >= ma10.iloc[-1]
                if pullback and shrink and reclaim and _dedup_ok(key, STOCK_COOLDOWN_H):
                    hits.append(f"💊 {r.get('message', '')} — 缩量回踩MA10企稳")
            except Exception:
                continue
    return hits


# ══════════════════════════════════════════════════════════════════
# 宏观 PMI
# ══════════════════════════════════════════════════════════════════
def check_pmi(rules: dict) -> list[str]:
    pmi_cfg = rules.get("pmi", {})
    if not pmi_cfg.get("enabled", False):
        return []
    try:
        from src.macro.cycle_valuer import CycleValuer
        v = CycleValuer()
        pmi = v._get_pmi()
        if pmi is None:
            return []
        below = pmi < 50.0
        if _dedup_ok("pmi:value", 24 * 30):  # 月度
            return [
                f"📊 PMI {pmi:.1f} — {'⚠️ 跌破荣枯线50 (经济收缩)' if below else '荣枯线上方 (经济扩张)'}"
            ]
    except Exception:
        return []
    return []


# ══════════════════════════════════════════════════════════════════
# 主入口
# ══════════════════════════════════════════════════════════════════
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="催化信号监控器")
    parser.add_argument("--mode", choices=("price", "news", "stock", "pmi", "all"), default="all")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    # 交易日门禁 (价格/个股信号只在交易日有意义)
    if not args.force and args.mode in ("price", "stock", "all"):
        from src.paper_trading.scheduler import is_trading_day
        if not is_trading_day():
            return 0

    rules = _load_rules()
    msgs: list[str] = []
    if args.mode in ("price", "all"):
        msgs.extend(check_price(rules))
    if args.mode in ("news", "all"):
        msgs.extend(check_news(rules))
    if args.mode in ("stock", "all"):
        msgs.extend(check_stock(rules))
    if args.mode in ("pmi", "all"):
        msgs.extend(check_pmi(rules))

    if msgs:
        print("\n".join(msgs), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
