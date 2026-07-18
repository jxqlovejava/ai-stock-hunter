# -*- coding: utf-8 -*-
"""多波洗盘 playbook 实盘事件研究 (WashCycleBacktester)。

在本地 ``data/kline_cache`` 日线上扫描 WashCycleAnalyzer 信号，
统计 WASH_EXHAUSTION / MARKUP_CANDIDATE 触发后 3/5/10 日前瞻收益，
用于将 ``wash_then_markup`` 证据级从 PRELIMINARY 升级到 CONFIRMED。

设计:
  - 默认只读本地缓存，不强制联网
  - 滚动窗口 + cooldown，避免同一段下跌重复计数
  - 主假设: 洗尽/拉升候选后 5 日收益均值 > 0 且胜率 > 50%
  - 对照: FAILED_WASHOUT 后 5 日应偏弱（过滤真出货）
"""

from __future__ import annotations

import json
import logging
import math
import random
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

import numpy as np

from .wash_cycle import WashCycleAnalyzer, WashCyclePhase

logger = logging.getLogger(__name__)

# 信号相位：主假设「洗完再涨」
_ENTRY_PHASES = frozenset({
    WashCyclePhase.WASH_EXHAUSTION,
    WashCyclePhase.MARKUP_CANDIDATE,
})
# 对照：真出货过滤
_FAIL_PHASE = WashCyclePhase.FAILED_WASHOUT

# manipulation/ -> game_theory/ -> src/ -> repo root
_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_CACHE = _REPO_ROOT / "data" / "kline_cache"
_DEFAULT_REPORT_DIR = _REPO_ROOT / "data" / "reports"

_LOOKBACK = 30
_STEP = 5
_COOLDOWN = 10
_HORIZONS = (3, 5, 10)
_MIN_BARS = 80
_MIN_CONF = 0.50


@dataclass
class WashEvent:
    """单次洗盘生命周期事件。"""

    symbol: str
    date: str
    phase: str
    confidence: float
    cumulative_drop_pct: float
    wave_count: int
    short_pressure_flag: bool = False
    fwd_ret_3d: Optional[float] = None   # 小数，如 0.03 = +3%
    fwd_ret_5d: Optional[float] = None
    fwd_ret_10d: Optional[float] = None

    def primary_return(self) -> Optional[float]:
        return self.fwd_ret_5d


@dataclass
class PhaseStats:
    """按相位汇总的前瞻收益统计。"""

    phase: str
    n_events: int = 0
    n_with_fwd: int = 0
    win_rate_5d: float = 0.0
    avg_ret_3d: float = 0.0
    avg_ret_5d: float = 0.0
    avg_ret_10d: float = 0.0
    median_ret_5d: float = 0.0
    p_value_5d: float = 1.0


@dataclass
class WashBacktestReport:
    """洗盘事件研究完整报告。"""

    n_stocks_scanned: int = 0
    n_stocks_with_data: int = 0
    n_entry_events: int = 0
    n_fail_events: int = 0
    entry_stats: PhaseStats = field(
        default_factory=lambda: PhaseStats(phase="entry_combined")
    )
    fail_stats: PhaseStats = field(
        default_factory=lambda: PhaseStats(phase="failed_washout")
    )
    by_phase: dict[str, PhaseStats] = field(default_factory=dict)
    evidence_grade: str = "HYPOTHESIS"
    verdict: str = ""
    details: list[str] = field(default_factory=list)
    sample_events: list[dict] = field(default_factory=list)
    generated_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    cache_dir: str = ""
    params: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    def to_playbook_validation_fields(self) -> dict:
        """映射到 PlaybookValidation 关键字段。"""
        es = self.entry_stats
        supporting = int(round(es.win_rate_5d * es.n_with_fwd)) if es.n_with_fwd else 0
        return {
            "total_samples": es.n_with_fwd,
            "supporting_samples": supporting,
            "refuting_samples": max(0, es.n_with_fwd - supporting),
            "pattern_match_rate": es.win_rate_5d * 100,
            "avg_return_after_match": es.avg_ret_5d * 100,
            "significance_level": es.p_value_5d,
            "evidence_grade": self.evidence_grade,
            "verdict": self.verdict,
            "details": list(self.details),
        }


class WashCycleBacktester:
    """本地 kline_cache 上的多波洗盘事件研究。"""

    def __init__(
        self,
        cache_dir: Path | str | None = None,
        lookback: int = _LOOKBACK,
        step: int = _STEP,
        cooldown: int = _COOLDOWN,
        min_confidence: float = _MIN_CONF,
    ) -> None:
        self.cache_dir = Path(cache_dir) if cache_dir else _DEFAULT_CACHE
        self.lookback = lookback
        self.step = step
        self.cooldown = cooldown
        self.min_confidence = min_confidence
        self._analyzer = WashCycleAnalyzer()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        symbols: Optional[Iterable[str]] = None,
        *,
        max_stocks: int = 300,
        seed: int = 42,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> WashBacktestReport:
        """扫描股票宇宙，产出事件研究报告。"""
        files = self._list_cache_files()
        if symbols is not None:
            want = {s.strip().split(".")[0] for s in symbols}
            files = [(s, p) for s, p in files if s in want]
        else:
            # 可复现抽样，避免 1900+ 全扫过慢；max_stocks<=0 表示全量
            rng = random.Random(seed)
            if max_stocks > 0 and len(files) > max_stocks:
                files = rng.sample(files, max_stocks)

        report = WashBacktestReport(
            n_stocks_scanned=len(files),
            cache_dir=str(self.cache_dir),
            params={
                "lookback": self.lookback,
                "step": self.step,
                "cooldown": self.cooldown,
                "min_confidence": self.min_confidence,
                "max_stocks": max_stocks,
                "start_date": start_date,
                "end_date": end_date,
                "seed": seed,
            },
        )

        entry_events: list[WashEvent] = []
        fail_events: list[WashEvent] = []
        by_phase_events: dict[str, list[WashEvent]] = {}

        for symbol, path in files:
            try:
                bars = self._load_bars(path, start_date=start_date, end_date=end_date)
            except Exception as e:
                logger.debug("load %s failed: %s", path, e)
                continue
            if len(bars) < _MIN_BARS:
                continue
            report.n_stocks_with_data += 1
            events = self._scan_symbol(symbol, bars)
            for ev in events:
                by_phase_events.setdefault(ev.phase, []).append(ev)
                if ev.phase == _FAIL_PHASE.value:
                    fail_events.append(ev)
                elif ev.phase in {p.value for p in _ENTRY_PHASES}:
                    entry_events.append(ev)

        report.n_entry_events = len(entry_events)
        report.n_fail_events = len(fail_events)
        report.entry_stats = self._stats("entry_combined", entry_events)
        report.fail_stats = self._stats("failed_washout", fail_events)
        report.by_phase = {
            phase: self._stats(phase, evs)
            for phase, evs in sorted(by_phase_events.items())
        }
        report.sample_events = [
            asdict(e) for e in (entry_events[:8] + fail_events[:4])
        ]
        report.evidence_grade = self._grade(report).value
        report.verdict, report.details = self._verdict(report)
        return report

    def save_report(self, report: WashBacktestReport, path: Path | str | None = None) -> Path:
        """写入 JSON 报告。"""
        out = Path(path) if path else (
            _DEFAULT_REPORT_DIR / f"wash_backtest_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return out

    def apply_evidence_upgrade(self, report: WashBacktestReport) -> str:
        """将证据级回写 playbooks.wash_then_markup（进程内可变 dataclass）。"""
        from src.game_theory.playbooks import TOP_PLAYBOOKS

        grade = report.evidence_grade
        for pb in TOP_PLAYBOOKS:
            if pb.id == "wash_then_markup":
                before = pb.evidence_level
                pb.evidence_level = grade
                logger.info("wash_then_markup evidence %s → %s", before, grade)
                return grade
        return grade

    # ------------------------------------------------------------------
    # Scan helpers
    # ------------------------------------------------------------------

    def _scan_symbol(self, symbol: str, bars: list[dict]) -> list[WashEvent]:
        events: list[WashEvent] = []
        n = len(bars)
        last_signal_i = -10_000
        # 从 lookback 起，按 step 推进；末尾预留 10 日做前瞻
        end = n - max(_HORIZONS) - 1
        if end <= self.lookback:
            return events

        for i in range(self.lookback, end, self.step):
            if i - last_signal_i < self.cooldown:
                continue
            window = bars[i - self.lookback + 1 : i + 1]
            result = self._analyzer.analyze(symbol, window)
            if result.confidence < self.min_confidence:
                continue
            if result.phase not in _ENTRY_PHASES and result.phase != _FAIL_PHASE:
                continue

            # 前瞻收益（按 close）
            c0 = float(bars[i]["close"])
            if c0 <= 0:
                continue
            rets: dict[str, Optional[float]] = {}
            for h in _HORIZONS:
                j = i + h
                if j >= n:
                    rets[f"fwd_ret_{h}d"] = None
                else:
                    c1 = float(bars[j]["close"])
                    rets[f"fwd_ret_{h}d"] = (c1 / c0 - 1.0) if c1 > 0 else None

            # 至少要有 5 日收益才计入
            if rets.get("fwd_ret_5d") is None:
                continue

            events.append(WashEvent(
                symbol=symbol,
                date=str(bars[i].get("date", "")),
                phase=result.phase.value,
                confidence=float(result.confidence),
                cumulative_drop_pct=float(result.cumulative_drop_pct),
                wave_count=int(result.wave_count),
                short_pressure_flag=bool(result.short_pressure_flag),
                fwd_ret_3d=rets.get("fwd_ret_3d"),
                fwd_ret_5d=rets.get("fwd_ret_5d"),
                fwd_ret_10d=rets.get("fwd_ret_10d"),
            ))
            last_signal_i = i
        return events

    def _list_cache_files(self) -> list[tuple[str, Path]]:
        if not self.cache_dir.exists():
            return []
        out: list[tuple[str, Path]] = []
        for p in sorted(self.cache_dir.glob("*_*_daily.csv")):
            name = p.name
            if name.startswith("IDX_"):
                continue
            symbol = name.split("_")[0]
            if not symbol.isdigit() or len(symbol) != 6:
                continue
            out.append((symbol, p))
        return out

    def _load_bars(
        self,
        path: Path,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[dict]:
        import pandas as pd

        df = pd.read_csv(path)
        # 统一列名
        colmap = {
            "日期": "date", "开盘": "open", "最高": "high", "最低": "low",
            "收盘": "close", "成交量": "volume", "vol": "volume",
        }
        df = df.rename(columns={c: colmap.get(c, c) for c in df.columns})
        if "date" not in df.columns:
            # index may be date
            if df.index.name in ("date", "日期") or "Unnamed" not in str(df.columns[0]):
                df = df.reset_index()
                if "date" not in df.columns and "index" in df.columns:
                    df = df.rename(columns={"index": "date"})
        need = {"open", "high", "low", "close"}
        if not need.issubset(set(df.columns)):
            return []
        if "volume" not in df.columns:
            df["volume"] = 1_000_000.0
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date", "close"]).sort_values("date")
        if start_date:
            df = df[df["date"] >= pd.Timestamp(start_date)]
        if end_date:
            df = df[df["date"] <= pd.Timestamp(end_date)]
        bars: list[dict] = []
        for _, row in df.iterrows():
            bars.append({
                "date": row["date"].strftime("%Y-%m-%d"),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row.get("volume") or 0),
            })
        return bars

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    @staticmethod
    def _stats(phase: str, events: list[WashEvent]) -> PhaseStats:
        st = PhaseStats(phase=phase, n_events=len(events))
        r3 = [e.fwd_ret_3d for e in events if e.fwd_ret_3d is not None]
        r5 = [e.fwd_ret_5d for e in events if e.fwd_ret_5d is not None]
        r10 = [e.fwd_ret_10d for e in events if e.fwd_ret_10d is not None]
        st.n_with_fwd = len(r5)
        if r3:
            st.avg_ret_3d = float(np.mean(r3))
        if r5:
            st.avg_ret_5d = float(np.mean(r5))
            st.median_ret_5d = float(np.median(r5))
            st.win_rate_5d = float(sum(1 for x in r5 if x > 0) / len(r5))
            st.p_value_5d = _ttest_mean_gt_zero(r5)
        if r10:
            st.avg_ret_10d = float(np.mean(r10))
        return st

    @staticmethod
    def _grade(report: WashBacktestReport):
        from src.game_theory.playbook_validator import EvidenceGrade

        es = report.entry_stats
        n = es.n_with_fwd
        if n < 5:
            return EvidenceGrade.HYPOTHESIS
        support_rate = es.win_rate_5d
        p = es.p_value_5d
        # 主假设: 洗尽/拉升候选后正向收益
        if n >= 100 and p < 0.01 and support_rate > 0.5 and es.avg_ret_5d > 0:
            return EvidenceGrade.CALIBRATED
        if n >= 20 and p < 0.05 and support_rate > 0.5 and es.avg_ret_5d > 0:
            return EvidenceGrade.CONFIRMED
        if n >= 20 and support_rate < 0.35 and es.avg_ret_5d < 0:
            return EvidenceGrade.REFUTED
        if n >= 5:
            return EvidenceGrade.PRELIMINARY
        return EvidenceGrade.HYPOTHESIS

    @staticmethod
    def _verdict(report: WashBacktestReport) -> tuple[str, list[str]]:
        es = report.entry_stats
        fs = report.fail_stats
        details = [
            f"扫描股票 {report.n_stocks_scanned}，有效数据 {report.n_stocks_with_data}",
            f"入场事件(洗尽/拉升候选) {report.n_entry_events}，有 5 日前瞻 {es.n_with_fwd}",
            f"入场 5 日胜率 {es.win_rate_5d:.1%} | 均值 {es.avg_ret_5d:.2%} | "
            f"中位 {es.median_ret_5d:.2%} | p={es.p_value_5d:.4f}",
            f"入场 3 日均值 {es.avg_ret_3d:.2%} | 10 日均值 {es.avg_ret_10d:.2%}",
            f"FAILED_WASHOUT 事件 {report.n_fail_events}，5 日均值 {fs.avg_ret_5d:.2%} | "
            f"胜率 {fs.win_rate_5d:.1%}",
        ]
        for phase, st in report.by_phase.items():
            details.append(
                f"  phase={phase}: n={st.n_with_fwd} wr5={st.win_rate_5d:.1%} "
                f"avg5={st.avg_ret_5d:.2%} p={st.p_value_5d:.3f}"
            )

        grade = report.evidence_grade
        if grade == "CONFIRMED":
            verdict = (
                f"✅ 实盘事件研究确认 wash_then_markup："
                f"{es.n_with_fwd} 样本，5 日胜率 {es.win_rate_5d:.1%}，"
                f"均收益 {es.avg_ret_5d:.2%} (p={es.p_value_5d:.4f})"
            )
        elif grade == "CALIBRATED":
            verdict = (
                f"✅ 校准级确认 wash_then_markup："
                f"{es.n_with_fwd} 样本，5 日胜率 {es.win_rate_5d:.1%}，"
                f"均收益 {es.avg_ret_5d:.2%} (p={es.p_value_5d:.4f})"
            )
        elif grade == "REFUTED":
            verdict = (
                f"❌ 实盘证伪：入场后 5 日胜率仅 {es.win_rate_5d:.1%}，"
                f"均收益 {es.avg_ret_5d:.2%}"
            )
        elif grade == "PRELIMINARY":
            verdict = (
                f"🟡 初步支持：{es.n_with_fwd} 样本，5 日胜率 {es.win_rate_5d:.1%}，"
                f"均收益 {es.avg_ret_5d:.2%} (p={es.p_value_5d:.4f})；"
                f"样本或显著性未达 CONFIRMED"
            )
        else:
            verdict = (
                f"🔬 样本不足 ({es.n_with_fwd})，保持 HYPOTHESIS。"
                f"请扩大 max_stocks 或检查 kline_cache。"
            )
        return verdict, details


def _ttest_mean_gt_zero(xs: list[float]) -> float:
    """单样本 t 检验 H1: mean > 0，返回近似单侧 p-value。"""
    n = len(xs)
    if n < 2:
        return 1.0
    arr = np.asarray(xs, dtype=float)
    mean = float(arr.mean())
    std = float(arr.std(ddof=1))
    if std <= 1e-12:
        return 0.0 if mean > 0 else 1.0
    t = mean / (std / math.sqrt(n))
    # 正态近似单侧
    try:
        from math import erfc
        # P(Z > t) for standard normal
        p = 0.5 * erfc(t / math.sqrt(2))
        return float(min(1.0, max(0.0, p)))
    except Exception:
        return 0.05 if t > 1.65 else 0.5


def run_wash_backtest(
    max_stocks: int = 300,
    cache_dir: str | Path | None = None,
    apply_upgrade: bool = True,
    save: bool = True,
) -> WashBacktestReport:
    """便捷入口。"""
    bt = WashCycleBacktester(cache_dir=cache_dir)
    report = bt.run(max_stocks=max_stocks)
    if apply_upgrade:
        bt.apply_evidence_upgrade(report)
    if save:
        path = bt.save_report(report)
        report.details.append(f"报告已写入 {path}")
    return report
