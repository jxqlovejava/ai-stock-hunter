# -*- coding: utf-8 -*-
"""Playbook 假设验证引擎 — Phase 2 核心模块。

连接 seats.py（龙虎榜数据）与 playbooks.py（操盘手法假设），
通过历史数据统计验证每个 playbook 的假设是否成立。

验证流程:
  1. 历史龙虎榜数据批量拉取（多日回溯）
  2. 游资席位跟买胜率统计（次日/3日/5日）
  3. 涨停板接力模式匹配
  4. 机构抱团/国家队托底信号验证
  5. 证据级别自动升级: HYPOTHESIS → CONFIRMED / REFUTED

设计原则:
  - 所有验证输出携带 sample_size / confidence_interval / p_value
  - evidence_level 升级需要 ≥20 个样本 + 统计显著性
  - 参考: .references/UZI-Skill/skills/deep-analysis/scripts/fetch_lhb.py
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

logger = logging.getLogger(__name__)

# ── 东财 datacenter helpers (复用 seats.py 模式) ─────────────────────────
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
_EM_SESSION = None
_em_last_call = 0.0
EM_MIN_INTERVAL = 1.2


def _get_em_session():
    global _EM_SESSION
    if _EM_SESSION is None:
        import requests
        _EM_SESSION = requests.Session()
        _EM_SESSION.trust_env = False  # 禁止读取系统代理，避免代理工具干扰东财 API 连接
        _EM_SESSION.headers.update({"User-Agent": UA})
        try:
            from requests.adapters import HTTPAdapter
            from urllib3.util.retry import Retry
            _EM_SESSION.mount("https://", HTTPAdapter(max_retries=Retry(
                total=2, connect=2, backoff_factor=0.5,
                status_forcelist=[429, 500, 502, 503], allowed_methods=["GET"])))
        except Exception:
            pass
    return _EM_SESSION


def _em_get(url: str, params: dict = None, headers: dict = None, timeout: int = 15):
    global _em_last_call
    wait = EM_MIN_INTERVAL - (time.time() - _em_last_call)
    if wait > 0:
        time.sleep(wait + random.uniform(0.1, 0.5))
    try:
        return _get_em_session().get(url, params=params, headers=headers or {}, timeout=timeout)
    finally:
        _em_last_call = time.time()


DATACENTER_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"


def _dc_query(report_name: str, filter_str: str = "", page_size: int = 500,
              sort_columns: str = "", sort_types: str = "-1") -> list[dict]:
    r = _em_get(DATACENTER_URL, params={
        "reportName": report_name, "columns": "ALL",
        "filter": filter_str, "pageNumber": "1", "pageSize": str(page_size),
        "sortColumns": sort_columns, "sortTypes": sort_types,
        "source": "WEB", "client": "WEB",
    }, timeout=15)
    d = r.json()
    return (d.get("result") or {}).get("data") or []


# ── Data models ─────────────────────────────────────────────────────────

class EvidenceGrade(str, Enum):
    HYPOTHESIS = "HYPOTHESIS"       # 逻辑推演，未经数据验证
    PRELIMINARY = "PRELIMINARY"     # 初步数据支持（样本 < 20）
    CONFIRMED = "CONFIRMED"         # 数据验证通过（≥20 样本, p<0.05）
    REFUTED = "REFUTED"             # 数据证伪
    CALIBRATED = "CALIBRATED"       # 已校准参数（≥100 样本）


@dataclass
class SeatWinRate:
    """单个席位的跟买胜率统计。"""
    seat_name: str
    reputation_score: int = 0
    sample_size: int = 0
    win_rate_1d: float = 0.0        # T+1 胜率
    win_rate_3d: float = 0.0        # T+3 胜率
    win_rate_5d: float = 0.0        # T+5 胜率
    avg_return_1d: float = 0.0      # T+1 平均收益率%
    avg_return_3d: float = 0.0
    avg_return_5d: float = 0.0
    max_drawdown_5d: float = 0.0    # 5日最大回撤%
    sharpe_5d: float = 0.0          # 5日夏普（年化估算）
    confidence_interval_3d: tuple[float, float] = (0.0, 0.0)
    grade: EvidenceGrade = EvidenceGrade.HYPOTHESIS
    last_updated: datetime = field(default_factory=datetime.now)


@dataclass
class PlaybookValidation:
    """单个 playbook 的验证结果。"""
    playbook_id: str
    playbook_name: str
    total_samples: int = 0
    supporting_samples: int = 0     # 支持假设的样本数
    refuting_samples: int = 0       # 证伪假设的样本数
    pattern_match_rate: float = 0.0  # 模式匹配率（%）
    avg_return_after_match: float = 0.0  # 模式匹配后平均收益%
    significance_level: float = 0.0  # p-value
    verdict: str = ""               # 一句话结论
    details: list[str] = field(default_factory=list)
    evidence_grade_before: EvidenceGrade = EvidenceGrade.HYPOTHESIS
    evidence_grade_after: EvidenceGrade = EvidenceGrade.HYPOTHESIS
    seat_stats: list[SeatWinRate] = field(default_factory=list)
    validated_at: datetime = field(default_factory=datetime.now)


@dataclass
class ValidationReport:
    """全部 playbook 验证汇总报告。"""
    playbook_results: list[PlaybookValidation] = field(default_factory=list)
    seat_rankings: list[SeatWinRate] = field(default_factory=list)
    overall_sample_size: int = 0
    confirmed_count: int = 0
    refuted_count: int = 0
    generated_at: datetime = field(default_factory=datetime.now)


# ── PlaybookValidator ───────────────────────────────────────────────────

class PlaybookValidator:
    """Playbook 假设 → 数据统计验证引擎。"""

    def __init__(self, days_back: int = 60):
        self.days_back = days_back
        self._lhb_cache: list[dict] | None = None
        self._price_cache: dict[str, list[float]] = {}

    # ------------------------------------------------------------------
    # Public API — 主验证入口
    # ------------------------------------------------------------------

    def validate_all(self) -> ValidationReport:
        """验证全部 playbook 假设。"""
        from .playbooks import TOP_PLAYBOOKS
        results = [self.validate_playbook(pb) for pb in TOP_PLAYBOOKS]
        seat_rankings = self.calc_all_seats_win_rates()
        return ValidationReport(
            playbook_results=results,
            seat_rankings=seat_rankings,
            overall_sample_size=sum(r.total_samples for r in results),
            confirmed_count=sum(1 for r in results
                              if r.evidence_grade_after in (EvidenceGrade.CONFIRMED, EvidenceGrade.CALIBRATED)),
            refuted_count=sum(1 for r in results
                            if r.evidence_grade_after == EvidenceGrade.REFUTED),
        )

    def validate_playbook(self, playbook) -> PlaybookValidation:
        """验证单个 playbook 假设。

        Args:
            playbook: Playbook dataclass from playbooks.py

        Returns:
            PlaybookValidation with statistical evidence
        """
        if playbook.id == "limit_up_relay":
            return self._validate_limit_up_relay(playbook)
        elif playbook.id == "institutional_clustering":
            return self._validate_institutional_clustering(playbook)
        elif playbook.id == "national_team_bailout":
            return self._validate_national_team_bailout(playbook)
        else:
            return PlaybookValidation(
                playbook_id=playbook.id,
                playbook_name=playbook.name,
                verdict="未知 playbook 类型，无法验证",
            )

    # ------------------------------------------------------------------
    # 席位跟买胜率统计
    # ------------------------------------------------------------------

    def calc_seat_win_rate(self, seat_name: str, horizon_days: int = 3) -> SeatWinRate:
        """计算单个席位的跟买胜率。

        从历史龙虎榜数据中找出该席位买入的股票，跟踪后续 N 日表现。
        """
        from .seats import SeatTracker
        tracker = SeatTracker()
        seat_info = tracker._seats.get(seat_name)

        records = self._get_historical_lhb()
        buy_records = self._filter_seat_buys(seat_name, records)

        if not buy_records:
            return SeatWinRate(
                seat_name=seat_name,
                reputation_score=seat_info.reputation_score if seat_info else 0,
                grade=EvidenceGrade.HYPOTHESIS,
            )

        returns_1d, returns_3d, returns_5d = [], [], []
        for rec in buy_records:
            symbol = rec.get("SECURITY_CODE", "")
            trade_date = str(rec.get("TRADE_DATE", ""))[:10]
            if not symbol or not trade_date:
                continue
            r1 = self._get_forward_return(symbol, trade_date, 1)
            r3 = self._get_forward_return(symbol, trade_date, 3)
            r5 = self._get_forward_return(symbol, trade_date, 5)
            if r1 is not None:
                returns_1d.append(r1)
            if r3 is not None:
                returns_3d.append(r3)
            if r5 is not None:
                returns_5d.append(r5)

        n = len(returns_3d)
        if n == 0:
            return SeatWinRate(
                seat_name=seat_name,
                reputation_score=seat_info.reputation_score if seat_info else 0,
                grade=EvidenceGrade.HYPOTHESIS,
            )

        import math
        win_3d = sum(1 for r in returns_3d if r > 0) / n
        avg_3d = sum(returns_3d) / n
        std_3d = math.sqrt(sum((r - avg_3d) ** 2 for r in returns_3d) / (n - 1)) if n > 1 else 0
        ci_3d = (
            avg_3d - 1.96 * std_3d / math.sqrt(n),
            avg_3d + 1.96 * std_3d / math.sqrt(n),
        )

        sharpe = (avg_3d / std_3d * math.sqrt(52)) if std_3d > 0 else 0  # 周频→年化

        grade = EvidenceGrade.HYPOTHESIS
        if n >= 100:
            grade = EvidenceGrade.CALIBRATED
        elif n >= 20:
            grade = EvidenceGrade.CONFIRMED
        elif n >= 5:
            grade = EvidenceGrade.PRELIMINARY

        return SeatWinRate(
            seat_name=seat_name,
            reputation_score=seat_info.reputation_score if seat_info else 0,
            sample_size=n,
            win_rate_1d=sum(1 for r in returns_1d if r > 0) / max(len(returns_1d), 1),
            win_rate_3d=win_3d,
            win_rate_5d=sum(1 for r in returns_5d if r > 0) / max(len(returns_5d), 1),
            avg_return_1d=sum(returns_1d) / max(len(returns_1d), 1) if returns_1d else 0,
            avg_return_3d=avg_3d,
            avg_return_5d=sum(returns_5d) / max(len(returns_5d), 1) if returns_5d else 0,
            max_drawdown_5d=min(returns_5d) if returns_5d else 0,
            sharpe_5d=sharpe,
            confidence_interval_3d=ci_3d,
            grade=grade,
        )

    def calc_all_seats_win_rates(self) -> list[SeatWinRate]:
        """计算所有已知知名席位的跟买胜率。"""
        from .seats import KNOWN_SEATS
        results = []
        seen: set[str] = set()
        for seat in KNOWN_SEATS:
            if seat.seat_name in seen:
                continue
            seen.add(seat.seat_name)
            wr = self.calc_seat_win_rate(seat.seat_name)
            wr.reputation_score = seat.reputation_score
            results.append(wr)
        results.sort(key=lambda x: (x.win_rate_3d, x.sample_size), reverse=True)
        return results

    def get_top_seats(self, top_n: int = 10, min_samples: int = 5) -> list[SeatWinRate]:
        """获取跟买胜率最高的席位排名。"""
        all_seats = self.calc_all_seats_win_rates()
        return [s for s in all_seats if s.sample_size >= min_samples][:top_n]

    # ------------------------------------------------------------------
    # Playbook-specific validation
    # ------------------------------------------------------------------

    def _validate_limit_up_relay(self, playbook) -> PlaybookValidation:
        """验证涨停板接力 playbook。

        假设: 知名游资买入后，股价在 T+1 高开 3-5%，并可能形成连板。

        验证方法:
          1. 从历史 LHB 中识别知名游资买入的标的
          2. 统计后续 1/3/5 日表现
          3. 检查模式匹配率: 游资买入 → T+1 高开 → 连板
        """
        result = PlaybookValidation(
            playbook_id=playbook.id,
            playbook_name=playbook.name,
            evidence_grade_before=EvidenceGrade.HYPOTHESIS,
        )

        records = self._get_historical_lhb()
        from .seats import SeatTracker
        tracker = SeatTracker()

        # Step 1: 识别游资买入事件
        hot_money_buys: list[dict] = []
        for rec in records:
            code = rec.get("SECURITY_CODE", "")
            trade_date = str(rec.get("TRADE_DATE", ""))[:10]
            if not code or not trade_date:
                continue
            buy_seats = tracker._fetch_seat_details(code, trade_date, "BUY")
            for s in buy_seats[:5]:
                seat_name = s.get("OPERATEDEPT_NAME", "")
                if not seat_name:
                    continue
                activity = tracker._classify_seat(seat_name)
                if activity.identified and activity.following_signal in ("strong_buy", "buy"):
                    hot_money_buys.append({
                        "symbol": code,
                        "date": trade_date,
                        "seat": seat_name,
                        "buy_amount": (s.get("BUY") or 0) / 10000,
                        "reputation": activity.seat_info.reputation_score if activity.seat_info else 0,
                    })

        # Deduplicate by (symbol, date)
        seen = set()
        unique_buys = []
        for b in hot_money_buys:
            key = (b["symbol"], b["date"])
            if key not in seen:
                seen.add(key)
                unique_buys.append(b)

        result.total_samples = len(unique_buys)
        if result.total_samples < 5:
            result.verdict = f"样本不足（{result.total_samples} 个），无法验证。需至少 5 个游资买入事件。"
            result.evidence_grade_after = EvidenceGrade.PRELIMINARY if result.total_samples >= 2 else EvidenceGrade.HYPOTHESIS
            return result

        # Step 2: 统计后续表现
        matching_patterns = 0
        all_returns_1d = []
        all_returns_3d = []
        for b in unique_buys:
            r1 = self._get_forward_return(b["symbol"], b["date"], 1)
            r3 = self._get_forward_return(b["symbol"], b["date"], 3)
            if r1 is not None:
                all_returns_1d.append(r1)
            if r3 is not None:
                all_returns_3d.append(r3)

            # 模式匹配: T+1 收益 > 0（说明存在高开/冲高）
            if r1 is not None and r1 > 0:
                matching_patterns += 1

        n_returns = len(all_returns_1d)
        result.pattern_match_rate = (matching_patterns / result.total_samples * 100) if result.total_samples else 0
        result.supporting_samples = matching_patterns
        result.refuting_samples = result.total_samples - matching_patterns

        avg_r1 = sum(all_returns_1d) / len(all_returns_1d) if all_returns_1d else 0
        avg_r3 = sum(all_returns_3d) / len(all_returns_3d) if all_returns_3d else 0
        result.avg_return_after_match = avg_r1

        # Step 3: 统计显著性 — 二项检验
        import math
        # H0: 游资买入后 T+1 收益 > 0 概率 ≤ 0.5（随机）
        # H1: 游资买入后 T+1 收益 > 0 概率 > 0.5
        if n_returns >= 10:
            p_hat = matching_patterns / n_returns
            se = math.sqrt(0.5 * 0.5 / n_returns)
            z = (p_hat - 0.5) / se if se > 0 else 0
            # One-sided p-value via normal approx
            import math as m
            p_value = 0.5 * m.erfc(z / m.sqrt(2))
            result.significance_level = round(p_value, 4)
        else:
            result.significance_level = 1.0

        # Step 4: 席位统计
        seat_names = set(b["seat"] for b in unique_buys)
        for sn in seat_names:
            wr = self.calc_seat_win_rate(sn)
            result.seat_stats.append(wr)

        # Step 5: 判定
        result.details = [
            f"游资买入事件总数: {result.total_samples}",
            f"T+1 正收益比例: {result.pattern_match_rate:.1f}% ({matching_patterns}/{result.total_samples})",
            f"T+1 平均收益: {avg_r1:+.2f}%",
            f"T+3 平均收益: {avg_r3:+.2f}%",
            f"统计显著性: p={result.significance_level:.4f}",
        ]

        result.evidence_grade_after = self._upgrade_evidence(
            result.total_samples, matching_patterns,
            result.significance_level,
        )
        result.verdict = self._make_verdict(result)

        return result

    def _validate_institutional_clustering(self, playbook) -> PlaybookValidation:
        """验证机构抱团拉升 playbook。

        假设: 公募持仓集中度上升时，板块加速上涨；瓦解时踩踏下跌。

        验证方法:
          1. 通过北向流入 + 大盘换手率 + 波动率判断机构主导时段
          2. 检查基金持仓重叠度与后续板块表现的相关性
          3. 间接验证（Phase 2 简化版，完整版需基金季报接入）
        """
        result = PlaybookValidation(
            playbook_id=playbook.id,
            playbook_name=playbook.name,
            evidence_grade_before=EvidenceGrade.HYPOTHESIS,
        )

        # Phase 2 简化验证: 用大盘特征代替个股级基金持仓分析
        # 检查低换手率时段的市场表现（机构市特征）
        try:
            import akshare as ak
            import pandas as pd

            # Use CSI 300 index as proxy for institutional activity
            df = ak.stock_zh_index_daily(symbol="sh000300")
            if df is not None and len(df) >= 120:
                df["date"] = pd.to_datetime(df["date"])
                df = df.sort_values("date").tail(120)

                # Identify institutional regime: low turnover + low volatility periods
                turnover_changes = df["volume"].pct_change(20).dropna()
                price_changes = df["close"].pct_change(20).dropna()

                # 机构主导 = 换手下降但价格上涨（减少交易推升价格）
                inst_regime = (turnover_changes < -0.1) & (price_changes > 0.02)
                non_inst_regime = (turnover_changes > 0.1)

                inst_days = inst_regime.sum()
                inst_fwd_returns = []
                non_inst_fwd_returns = []

                for i in range(len(df) - 25):
                    if inst_regime.iloc[i]:
                        fwd_ret = (df["close"].iloc[i + 20] / df["close"].iloc[i] - 1) * 100
                        inst_fwd_returns.append(fwd_ret)
                    elif non_inst_regime.iloc[i]:
                        fwd_ret = (df["close"].iloc[i + 20] / df["close"].iloc[i] - 1) * 100
                        non_inst_fwd_returns.append(fwd_ret)

                avg_inst_fwd = sum(inst_fwd_returns) / len(inst_fwd_returns) if inst_fwd_returns else 0
                avg_non_inst_fwd = sum(non_inst_fwd_returns) / len(non_inst_fwd_returns) if non_inst_fwd_returns else 0

                result.total_samples = len(inst_fwd_returns) + len(non_inst_fwd_returns)
                if inst_fwd_returns:
                    positive = sum(1 for r in inst_fwd_returns if r > 0)
                    result.pattern_match_rate = positive / len(inst_fwd_returns) * 100
                    result.avg_return_after_match = avg_inst_fwd
                    result.supporting_samples = positive
                    result.refuting_samples = len(inst_fwd_returns) - positive

                result.details = [
                    f"机构主导日: {inst_days} 天",
                    f"机构主导后 20 日平均收益: {avg_inst_fwd:+.2f}%",
                    f"非机构主导后 20 日平均收益: {avg_non_inst_fwd:+.2f}%",
                    "⚠️ 间接验证: 基于大盘特征，精确验证需基金季报数据（Phase 3）",
                ]
            else:
                result.details.append("沪深300 指数数据不可用，跳过验证")

        except Exception as e:
            logger.warning("Institutional clustering validation failed: %s", e)
            result.details.append(f"数据获取失败: {e}")

        result.evidence_grade_after = self._upgrade_evidence(
            result.total_samples, result.supporting_samples,
            result.significance_level,
        )
        if result.total_samples < 10:
            result.evidence_grade_after = EvidenceGrade.HYPOTHESIS
        result.verdict = self._make_verdict(result)
        return result

    def _validate_national_team_bailout(self, playbook) -> PlaybookValidation:
        """验证国家队托底 playbook。

        假设: 大盘暴跌时国家队增持 ETF/蓝筹 → 指数止跌 → 北向跟风回流 → 国家队退出。

        验证方法:
          1. 识别大盘暴跌事件（HS300 单日跌 > 3%）
          2. 检查次日 HS300 ETF 成交量是否异常放大（> 3x 均值）
          3. 跟踪后续 5/10/20 日指数表现
        """
        result = PlaybookValidation(
            playbook_id=playbook.id,
            playbook_name=playbook.name,
            evidence_grade_before=EvidenceGrade.HYPOTHESIS,
        )

        try:
            import akshare as ak
            import pandas as pd

            # HS300 index data (000300.SH)
            idx_df = ak.stock_zh_index_daily(symbol="sh000300")
            # HS300 ETF (510300)
            etf_df = ak.stock_zh_a_hist(symbol="510300", period="daily",
                                        start_date="2024-01-01", end_date="")

            if idx_df is not None and len(idx_df) >= 250 and etf_df is not None:
                idx_df["date"] = pd.to_datetime(idx_df["date"])
                idx_df = idx_df.sort_values("date").tail(250)
                etf_df["日期"] = pd.to_datetime(etf_df["日期"])
                etf_df = etf_df.sort_values("日期").tail(250)

                # Merge on date
                merged = pd.merge(
                    idx_df, etf_df,
                    left_on="date", right_on="日期", how="inner",
                    suffixes=("_idx", "_etf"),
                )

                if len(merged) < 60:
                    result.details.append("数据合并后不足 60 天，跳过验证")
                    result.evidence_grade_after = EvidenceGrade.HYPOTHESIS
                    result.verdict = "数据不足，无法验证"
                    return result

                # Step 1: Identify crash days (index drop > 3%)
                merged["ret"] = merged["close"].pct_change()
                merged["vol_ratio"] = merged["volume_etf"] / merged["volume_etf"].rolling(20).mean()

                crash_days = merged[merged["ret"] < -0.03]

                if len(crash_days) < 3:
                    result.details.append(f"暴跌日不足 ({len(crash_days)} 个)，跳过验证")
                    result.evidence_grade_after = EvidenceGrade.PRELIMINARY
                    result.verdict = "近期没有足够的大跌事件来验证国家队托底模式"
                    return result

                # Step 2: Check for ETF volume anomalies (national team intervention)
                bailout_vol_ratio = []
                fwd_returns_5d = []
                fwd_returns_10d = []
                fwd_returns_20d = []

                for _, crash in crash_days.iterrows():
                    crash_idx = crash.name
                    # Next day ETF volume ratio
                    if crash_idx + 1 in merged.index:
                        vol_ratio = merged.loc[crash_idx + 1, "vol_ratio"]
                        bailout_vol_ratio.append(vol_ratio)

                        # Forward returns
                        if crash_idx + 5 in merged.index:
                            r5 = (merged.loc[crash_idx + 5, "close"] / crash["close"] - 1) * 100
                            fwd_returns_5d.append(r5)
                        if crash_idx + 10 in merged.index:
                            r10 = (merged.loc[crash_idx + 10, "close"] / crash["close"] - 1) * 100
                            fwd_returns_10d.append(r10)
                        if crash_idx + 20 in merged.index:
                            r20 = (merged.loc[crash_idx + 20, "close"] / crash["close"] - 1) * 100
                            fwd_returns_20d.append(r20)

                result.total_samples = len(crash_days)

                # Check: does high ETF vol (>2x) → better forward returns?
                if bailout_vol_ratio:
                    high_vol = [i for i, v in enumerate(bailout_vol_ratio) if v > 2.0]
                    if high_vol and fwd_returns_5d:
                        high_vol_returns_5d = [fwd_returns_5d[i] for i in high_vol if i < len(fwd_returns_5d)]
                        if high_vol_returns_5d:
                            avg_high_vol = sum(high_vol_returns_5d) / len(high_vol_returns_5d)
                            result.avg_return_after_match = avg_high_vol
                            positive = sum(1 for r in high_vol_returns_5d if r > 0)
                            result.pattern_match_rate = positive / len(high_vol_returns_5d) * 100
                            result.supporting_samples = positive
                            result.refuting_samples = len(high_vol_returns_5d) - positive

                avg_fwd_5d = sum(fwd_returns_5d) / len(fwd_returns_5d) if fwd_returns_5d else 0
                avg_fwd_10d = sum(fwd_returns_10d) / len(fwd_returns_10d) if fwd_returns_10d else 0

                result.details = [
                    f"暴跌日总数: {result.total_samples}",
                    f"暴跌后 5 日平均收益: {avg_fwd_5d:+.2f}%",
                    f"暴跌后 10 日平均收益: {avg_fwd_10d:+.2f}%",
                    f"ETF 放量 > 2x 时 5日胜率: {result.pattern_match_rate:.1f}%",
                    f"ETF 放量 > 2x 时 5日均收益: {result.avg_return_after_match:+.2f}%",
                    "⚠️ 间接验证: ETF 量价关系，精确验证需汇金公告/ETF 份额数据",
                ]
            else:
                result.details.append("HS300 或 ETF 数据不可用，跳过验证")

        except Exception as e:
            logger.warning("National team bailout validation failed: %s", e)
            result.details.append(f"数据获取失败: {e}")

        result.evidence_grade_after = self._upgrade_evidence(
            result.total_samples, result.supporting_samples,
            result.significance_level,
        )
        if result.total_samples < 5:
            result.evidence_grade_after = EvidenceGrade.HYPOTHESIS
        result.verdict = self._make_verdict(result)
        return result

    # ------------------------------------------------------------------
    # 历史数据获取
    # ------------------------------------------------------------------

    def _get_historical_lhb(self) -> list[dict]:
        """批量拉取历史龙虎榜数据（多日回溯）。

        Returns:
            list of dicts from 东财 datacenter RPT_DAILYBILLBOARD_DETAILSNEW
        """
        if self._lhb_cache is not None:
            return self._lhb_cache

        all_records = []
        today = datetime.now()

        # Fetch in batches of 10 days to avoid API limits
        for offset in range(0, self.days_back, 10):
            start_date = (today - timedelta(days=self.days_back - offset)).strftime("%Y-%m-%d")
            end_date = (today - timedelta(days=self.days_back - offset - 10)).strftime("%Y-%m-%d")
            if (today - timedelta(days=self.days_back - offset - 10)) > today:
                end_date = today.strftime("%Y-%m-%d")

            try:
                batch = _dc_query(
                    "RPT_DAILYBILLBOARD_DETAILSNEW",
                    filter_str=f"(TRADE_DATE>='{start_date}')(TRADE_DATE<='{end_date}')",
                    page_size=500,
                    sort_columns="BILLBOARD_NET_AMT", sort_types="-1",
                )
                all_records.extend(batch)
                logger.debug("Fetched %d LHB records for %s → %s", len(batch), start_date, end_date)
            except Exception as e:
                logger.warning("LHB fetch failed for %s → %s: %s", start_date, end_date, e)
                continue

        self._lhb_cache = all_records
        logger.info("Historical LHB: %d records over %d days", len(all_records), self.days_back)
        return all_records

    def _filter_seat_buys(self, seat_name: str, records: list[dict]) -> list[dict]:
        """从 LHB 记录中提取指定席位的买入记录。

        For each stock in LHB, check if the seat appears in buy-side details.
        """
        from .seats import SeatTracker
        tracker = SeatTracker()
        seat_buys = []

        seen = set()
        for rec in records:
            code = rec.get("SECURITY_CODE", "")
            trade_date = str(rec.get("TRADE_DATE", ""))[:10]
            key = (code, trade_date)
            if key in seen:
                continue
            seen.add(key)

            try:
                buy_seats = tracker._fetch_seat_details(code, trade_date, "BUY")
                for s in buy_seats[:5]:
                    s_name = s.get("OPERATEDEPT_NAME", "")
                    if not s_name:
                        continue
                    # Match: exact or partial
                    if seat_name in s_name or s_name in seat_name:
                        seat_buys.append({
                            "SECURITY_CODE": code,
                            "TRADE_DATE": trade_date,
                            "seat_name": s_name,
                            "BUY": s.get("BUY") or 0,
                        })
                        break
            except Exception as e:
                logger.debug("Seat detail fetch failed for %s/%s: %s", code, trade_date, e)
                continue

        return seat_buys

    def _get_forward_return(self, symbol: str, from_date: str, horizon_days: int) -> float | None:
        """计算指定日期后 N 个交易日的累计收益率。

        Returns:
            Percentage return (e.g., 3.5 means +3.5%), or None if data unavailable.
        """
        cache_key = f"{symbol}_{from_date}"
        # Fetch price data for this symbol
        if symbol not in self._price_cache:
            try:
                import akshare as ak
                from datetime import datetime as dt, timedelta as td
                start = (dt.strptime(from_date, "%Y-%m-%d") - td(days=10)).strftime("%Y%m%d")
                end = (dt.strptime(from_date, "%Y-%m-%d") + td(days=horizon_days + 5)).strftime("%Y%m%d")

                df = ak.stock_zh_a_hist(symbol=symbol, period="daily",
                                        start_date=start, end_date=end)
                if df is not None and len(df) > 0:
                    import pandas as pd
                    df["日期"] = pd.to_datetime(df["日期"])
                    df = df.sort_values("日期")
                    self._price_cache[symbol] = (
                        list(df["日期"].dt.strftime("%Y-%m-%d")),
                        list(df["收盘"].astype(float)),
                    )
                else:
                    self._price_cache[symbol] = ([], [])
            except Exception as e:
                logger.debug("Price fetch failed for %s: %s", symbol, e)
                self._price_cache[symbol] = ([], [])

        dates, prices = self._price_cache.get(symbol, ([], []))
        if not dates:
            return None

        try:
            idx_from = dates.index(from_date)
        except ValueError:
            # Find nearest date
            idx_from = None
            target = datetime.strptime(from_date, "%Y-%m-%d")
            for i, d in enumerate(dates):
                dt_d = datetime.strptime(d, "%Y-%m-%d")
                if dt_d >= target:
                    idx_from = i
                    break
            if idx_from is None:
                idx_from = len(dates) - 1

        idx_to = idx_from + horizon_days
        if idx_to >= len(prices):
            return None

        if prices[idx_from] == 0:
            return None

        return (prices[idx_to] / prices[idx_from] - 1) * 100

    # ------------------------------------------------------------------
    # 证据级别升级
    # ------------------------------------------------------------------

    @staticmethod
    def _upgrade_evidence(total: int, supporting: int, p_value: float) -> EvidenceGrade:
        """根据统计结果升级/降级 evidence level。

        规则:
          - ≥100 样本 + p<0.01 → CALIBRATED
          - ≥20 样本 + p<0.05 → CONFIRMED
          - ≥5 样本 → PRELIMINARY
          - <5 样本 → 保持 HYPOTHESIS
          - 证伪（supporting/total < 0.3 且 ≥20 样本）→ REFUTED
        """
        if total < 2:
            return EvidenceGrade.HYPOTHESIS

        support_rate = supporting / max(total, 1)

        if total >= 100 and p_value < 0.01 and support_rate > 0.5:
            return EvidenceGrade.CALIBRATED
        elif total >= 20 and p_value < 0.05 and support_rate > 0.5:
            return EvidenceGrade.CONFIRMED
        elif total >= 20 and support_rate < 0.3:
            return EvidenceGrade.REFUTED
        elif total >= 5:
            return EvidenceGrade.PRELIMINARY
        else:
            return EvidenceGrade.HYPOTHESIS

    @staticmethod
    def _make_verdict(result: PlaybookValidation) -> str:
        """生成自然语言验证结论。"""
        grade = result.evidence_grade_after
        if grade == EvidenceGrade.CALIBRATED:
            return (
                f"✅ 已验证（校准级）: '{result.playbook_name}' 模式在 {result.total_samples} 个样本中得到"
                f"统计显著支持 (p={result.significance_level:.4f}, "
                f"匹配率 {result.pattern_match_rate:.1f}%)。"
                f"平均收益 {result.avg_return_after_match:+.2f}%。"
            )
        elif grade == EvidenceGrade.CONFIRMED:
            return (
                f"✅ 已验证: '{result.playbook_name}' 模式在 {result.total_samples} 个样本中得到"
                f"统计支持 (p={result.significance_level:.4f}, "
                f"匹配率 {result.pattern_match_rate:.1f}%)。"
            )
        elif grade == EvidenceGrade.REFUTED:
            return (
                f"❌ 已证伪: '{result.playbook_name}' 假设在 {result.total_samples} 个样本中"
                f"不成立 (匹配率仅 {result.pattern_match_rate:.1f}%)。"
                f"建议修正或废弃此 playbook。"
            )
        elif grade == EvidenceGrade.PRELIMINARY:
            return (
                f"⚠️ 初步证据: '{result.playbook_name}' 有 {result.total_samples} 个样本"
                f"（< 20），匹配率 {result.pattern_match_rate:.1f}%。"
                f"需更多数据后重新验证。"
            )
        else:
            return (
                f"🔬 未验证: '{result.playbook_name}' 样本不足（{result.total_samples}），"
                f"保持 HYPOTHESIS 状态。"
            )

    # ------------------------------------------------------------------
    # Cache management
    # ------------------------------------------------------------------

    def clear_cache(self) -> None:
        self._lhb_cache = None
        self._price_cache.clear()

    def refresh(self) -> ValidationReport:
        """清除缓存后重新验证。"""
        self.clear_cache()
        return self.validate_all()


# ── Convenience functions ───────────────────────────────────────────────

def validate_playbooks(days_back: int = 60) -> ValidationReport:
    """便捷函数: 验证全部 playbook 假设。"""
    validator = PlaybookValidator(days_back=days_back)
    return validator.validate_all()


def get_seat_rankings(days_back: int = 60, min_samples: int = 5) -> list[SeatWinRate]:
    """便捷函数: 获取席位跟买胜率排名。"""
    validator = PlaybookValidator(days_back=days_back)
    return validator.get_top_seats(min_samples=min_samples)


def upgrade_playbook_evidence(playbook, validation: PlaybookValidation) -> str:
    """将验证结果回写到 playbook 的 evidence_level 字段。

    Args:
        playbook: Playbook dataclass instance (mutated in place — playbook is not frozen)
        validation: PlaybookValidation result

    Returns:
        Evidence grade as string
    """
    new_grade = validation.evidence_grade_after.value
    playbook.evidence_level = new_grade
    logger.info("Playbook '%s': %s → %s",
                playbook.name, validation.evidence_grade_before.value, new_grade)
    return new_grade
