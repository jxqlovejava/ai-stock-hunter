# -*- coding: utf-8 -*-
"""wash_then_markup 实盘事件研究测试（合成 kline_cache，无网络）。"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.game_theory.manipulation.wash_backtest import (
    WashCycleBacktester,
    WashEvent,
    _ttest_mean_gt_zero,
)
from src.game_theory.playbook_validator import EvidenceGrade, PlaybookValidator
from src.game_theory.playbooks import TOP_PLAYBOOKS


def _write_decline_csv(
    path: Path,
    *,
    n: int = 200,
    start: float = 20.0,
    seed: int = 0,
) -> None:
    """合成含多段下跌→缩量→反弹的日线，便于触发洗盘相位。"""
    rng = np.random.default_rng(seed)
    rows = []
    price = start
    for i in range(n):
        # 每 40 日一段：缓跌 20 日 + 弱反弹 5 日 + 再跌 10 日 + 缩量企稳反弹
        phase = i % 40
        if phase < 20:
            ret = -0.012 + rng.normal(0, 0.003)
            vol = 1_000_000 * (0.95 ** (phase % 10))
        elif phase < 25:
            ret = 0.008 + rng.normal(0, 0.002)
            vol = 800_000
        elif phase < 35:
            ret = -0.01 + rng.normal(0, 0.003)
            vol = 700_000 * (0.9 ** (phase - 25))
        else:
            ret = 0.015 + rng.normal(0, 0.004)
            vol = 1_200_000
        o = price
        c = max(0.5, price * (1 + ret))
        h = max(o, c) * 1.005
        l = min(o, c) * 0.995
        # 日期从 2020 起
        day = pd.Timestamp("2020-01-02") + pd.Timedelta(days=i)
        # 跳过周末
        while day.weekday() >= 5:
            day += pd.Timedelta(days=1)
        rows.append({
            "date": day.strftime("%Y-%m-%d"),
            "open": o, "high": h, "low": l, "close": c, "volume": vol,
        })
        price = c
    pd.DataFrame(rows).to_csv(path, index=False)


@pytest.fixture()
def synth_cache(tmp_path: Path) -> Path:
    for i, code in enumerate(["600001", "600002", "000001", "002001"]):
        _write_decline_csv(
            tmp_path / f"{code}_20150101_20251231_daily.csv",
            seed=i + 1,
        )
    return tmp_path


class TestWashCycleBacktester:
    def test_scan_produces_events_and_stats(self, synth_cache: Path):
        bt = WashCycleBacktester(cache_dir=synth_cache, step=3, cooldown=5)
        report = bt.run(max_stocks=10, seed=1)
        assert report.n_stocks_scanned == 4
        assert report.n_stocks_with_data == 4
        # 合成数据应至少检出部分入场或失败事件
        assert report.n_entry_events + report.n_fail_events >= 1
        assert report.evidence_grade in {
            g.value for g in EvidenceGrade
        }
        assert report.verdict
        d = report.to_dict()
        assert "entry_stats" in d
        fields = report.to_playbook_validation_fields()
        assert "total_samples" in fields
        assert "evidence_grade" in fields

    def test_save_report(self, synth_cache: Path, tmp_path: Path):
        bt = WashCycleBacktester(cache_dir=synth_cache)
        report = bt.run(max_stocks=4)
        out = bt.save_report(report, tmp_path / "w.json")
        assert out.exists()
        assert out.stat().st_size > 50

    def test_apply_evidence_upgrade(self, synth_cache: Path):
        bt = WashCycleBacktester(cache_dir=synth_cache)
        report = bt.run(max_stocks=4)
        grade = bt.apply_evidence_upgrade(report)
        pb = next(p for p in TOP_PLAYBOOKS if p.id == "wash_then_markup")
        assert pb.evidence_level == grade
        assert grade == report.evidence_grade


class TestTTest:
    def test_positive_mean_low_p(self):
        xs = [0.02] * 30
        p = _ttest_mean_gt_zero(xs)
        assert p < 0.01

    def test_zero_mean_high_p(self):
        xs = [0.01, -0.01] * 20
        p = _ttest_mean_gt_zero(xs)
        assert p > 0.1


class TestValidatorLiveFlag:
    def test_fixture_path_without_live(self):
        pb = next(p for p in TOP_PLAYBOOKS if p.id == "wash_then_markup")
        v = PlaybookValidator().validate_playbook(pb, live_backtest=False)
        assert v.total_samples >= 5
        assert v.supporting_samples >= 4
        assert v.evidence_grade_after in (
            EvidenceGrade.PRELIMINARY,
            EvidenceGrade.CONFIRMED,
        )

    def test_live_backtest_on_synth_cache(self, synth_cache: Path, monkeypatch):
        # 指向合成缓存
        import src.game_theory.manipulation.wash_backtest as wb

        monkeypatch.setattr(wb, "_DEFAULT_CACHE", synth_cache)
        pb = next(p for p in TOP_PLAYBOOKS if p.id == "wash_then_markup")
        v = PlaybookValidator().validate_playbook(
            pb, live_backtest=True, max_stocks=4,
        )
        assert any("[live]" in d or "[fixture]" in d for d in v.details)
        assert v.evidence_grade_after in list(EvidenceGrade)
