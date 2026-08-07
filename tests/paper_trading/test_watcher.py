# -*- coding: utf-8 -*-
"""paper_trading.watcher 纯逻辑测试 (2026-08-08).

覆盖: 强信号去重 / 交易消息格式化 / 复盘边界判断 / 快筛结果。
全部为纯函数/快照级测试, 不触发网络。
"""
import json
from datetime import date, timedelta
from pathlib import Path

from src.paper_trading.watcher import (
    _chanlun_recent,
    _dedup_ok,
    _fmt_trade,
    _is_review_day,
    _load_dedup,
)


# ══════════════════════════════════════════════════════════════════
# 缠论买点时效过滤
# ══════════════════════════════════════════════════════════════════
class TestChanlunRecent:
    def test_recent_signal_ok(self):
        from datetime import date
        recent = date.today().isoformat()
        assert _chanlun_recent(f"🥋 缠论买点: 最近信号 三买 @18.6 ({recent})") is True

    def test_old_signal_filtered(self):
        from datetime import timedelta
        old = (date.today() - timedelta(days=30)).isoformat()
        assert _chanlun_recent(f"🥋 缠论买点: 最近信号 三买 @18.6 ({old})") is False

    def test_no_date_false(self):
        assert _chanlun_recent("🥋 缠论买点: 无日期") is False
        assert _chanlun_recent(None) is False


# ══════════════════════════════════════════════════════════════════
# 强信号去重
# ══════════════════════════════════════════════════════════════════
class TestDedup:
    def setup_method(self):
        # 用临时去重文件
        import src.paper_trading.watcher as w
        self._orig = w.DEDUP_PATH
        w.DEDUP_PATH = Path("/tmp/pt_dedup_test.json")
        if w.DEDUP_PATH.exists():
            w.DEDUP_PATH.unlink()

    def teardown_method(self):
        import src.paper_trading.watcher as w
        w.DEDUP_PATH = self._orig

    def test_first_signal_allowed(self):
        assert _dedup_ok("600089", "buy") is True

    def test_same_signal_within_24h_blocked(self):
        _dedup_ok("600089", "buy")
        assert _dedup_ok("600089", "buy") is False

    def test_different_signal_allowed(self):
        _dedup_ok("600089", "buy")
        assert _dedup_ok("600089", "sell") is True

    def test_different_symbol_allowed(self):
        _dedup_ok("600089", "buy")
        assert _dedup_ok("002130", "buy") is True

    def test_old_signal_expired(self):
        _dedup_ok("600089", "buy")
        # 模拟 25 小时前
        data = _load_dedup()
        data["600089:buy"] = (date.today() - timedelta(days=1)).isoformat()
        p = Path("/tmp/pt_dedup_test.json")
        p.write_text(json.dumps(data), encoding="utf-8")
        # 25h+ 前 (跨日) → 允许再次触发
        assert _dedup_ok("600089", "buy") is True


# ══════════════════════════════════════════════════════════════════
# 交易消息格式化
# ══════════════════════════════════════════════════════════════════
class TestFormatTrade:
    def _trade(self, action="buy", pnl_pct=0.0):
        from types import SimpleNamespace
        return SimpleNamespace(
            symbol="600089", name="特变电工", action=action,
            quantity=200, price=21.33, commission=5.0,
            stamp_tax=0.0, transfer_fee=0.02, pnl_pct=pnl_pct,
        )

    def test_buy_format(self):
        m = _fmt_trade(self._trade())
        assert "买入" in m and "特变电工" in m and "200股" in m and "21.33" in m

    def test_sell_format_with_pnl(self):
        m = _fmt_trade(self._trade(action="sell", pnl_pct=0.05))
        assert "卖出" in m and "盈亏 +5.00%" in m


# ══════════════════════════════════════════════════════════════════
# 复盘边界判断
# ══════════════════════════════════════════════════════════════════
class TestReviewDay:
    def test_weekly_not_trading_day(self):
        # 2026-08-08 周六 → 非交易日
        assert _is_review_day("weekly", date(2026, 8, 8)) is False

    def test_monthly_not_last_trading_day(self):
        # 2026-08-03 周一 → 非月末 → False
        assert _is_review_day("monthly", date(2026, 8, 3)) is False

    def test_quarterly_off_month(self):
        # 2026-08 (非季末月) → False
        assert _is_review_day("quarterly", date(2026, 8, 28)) is False


# ══════════════════════════════════════════════════════════════════
# 快筛 (mock 数据)
# ══════════════════════════════════════════════════════════════════
class TestFastCheck:
    def test_buy_candidate_near_ma20(self, monkeypatch):
        import pandas as pd
        from src.paper_trading import watcher as w

        class _Bars:
            empty = False
            columns = ["close"]
            def __getitem__(self, k):
                # 39 天爬升后末日上冲 → 现价高出 MA20 约 2% (贴近支撑)
                closes = [float(100 + i * 0.1) for i in range(39)]
                closes.append(105.0)  # 末日冲高, ma20≈102.9, dist≈+2%
                return pd.Series(closes)

        class _Agg:
            def get_history(self, sym):
                return _Bars()

        monkeypatch.setattr(w, "_check_chanlun", lambda *a, **k: None)
        monkeypatch.setattr("src.data.aggregator.DataAggregator", _Agg)
        r = w._fast_check("600089", "特变电工")
        assert r["buy_candidate"] is True
        assert "买点区附近" in (r["hint"] or "")

    def test_sell_candidate_below_ma20(self, monkeypatch):
        import pandas as pd
        from src.paper_trading import watcher as w

        class _Bars:
            empty = False
            columns = ["close"]
            def __getitem__(self, k):
                # 价格持续走低 → 连续跌破 MA20
                closes = [float(100 - i) for i in range(40)]
                return pd.Series(closes)

        class _Agg:
            def get_history(self, sym):
                return _Bars()

        monkeypatch.setattr(w, "_check_chanlun", lambda *a, **k: None)
        monkeypatch.setattr("src.data.aggregator.DataAggregator", _Agg)
        r = w._fast_check("600089", "特变电工")
        assert r["sell_candidate"] is True
        assert r["below_ma20"] is True
