# -*- coding: utf-8 -*-
"""财务红旗检测 — Beneish M-Score / Sloan Accruals / Piotroski F-Score。

用于检测财务造假、盈利质量恶化、基本面恶化等红旗信号。

使用模式:
    detector = RedFlagDetector()
    report = detector.detect("600519", financial_data)
"""

from __future__ import annotations

import logging
from typing import Optional

from src.fundamental.schema import RedFlag, RedFlagReport, RedFlagSeverity

logger = logging.getLogger(__name__)


class RedFlagDetector:
    """财务红旗检测器。

    三大检测模型:
      1. Beneish M-Score (8变量) — 盈余操纵概率
      2. Sloan Accruals — 应计项目质量
      3. Piotroski F-Score (9变量) — 基本面健康度
    """

    # Beneish M-Score 阈值
    M_SCORE_THRESHOLD = -1.78    # > -1.78 可能操纵
    M_SCORE_HIGH_RISK = -1.49    # > -1.49 高风险

    # Piotroski F-Score 阈值
    F_SCORE_STRONG = 7           # ≥7 强基本面
    F_SCORE_WEAK = 3             # ≤3 弱基本面

    def detect(
        self,
        symbol: str,
        name: str = "",
        financials: Optional[dict] = None,
    ) -> RedFlagReport:
        """运行全部检测。

        Args:
            symbol: 股票代码
            name: 公司名称
            financials: 财务数据 dict，None 则标记数据缺口

        Returns:
            RedFlagReport
        """
        flags: list[RedFlag] = []

        if financials is None:
            return RedFlagReport(
                symbol=symbol,
                name=name,
                overall_risk="unknown",
            )

        # 1. 应计项目异常
        accrual_flag = self._check_accruals(financials)
        if accrual_flag:
            flags.append(accrual_flag)

        # 2. 应收账款/营收比异常
        ar_ratio_flag = self._check_ar_ratio(financials)
        if ar_ratio_flag:
            flags.append(ar_ratio_flag)

        # 3. 毛利恶化
        margin_flag = self._check_gross_margin(financials)
        if margin_flag:
            flags.append(margin_flag)

        # 4. 资产周转率恶化
        turnover_flag = self._check_asset_turnover(financials)
        if turnover_flag:
            flags.append(turnover_flag)

        # 5. 杠杆恶化
        leverage_flag = self._check_leverage(financials)
        if leverage_flag:
            flags.append(leverage_flag)

        # 6. 经营现金流 vs 净利润
        cf_flag = self._check_cashflow_quality(financials)
        if cf_flag:
            flags.append(cf_flag)

        # M-Score & F-Score 计算
        m_score = self._calc_m_score(financials)
        f_score = self._calc_f_score(financials)

        # 风险判定
        critical_flags = sum(1 for f in flags if f.severity == RedFlagSeverity.CRITICAL)
        if critical_flags >= 2 or (m_score is not None and m_score > self.M_SCORE_HIGH_RISK):
            overall_risk = "critical"
        elif critical_flags >= 1 or (m_score is not None and m_score > self.M_SCORE_THRESHOLD):
            overall_risk = "high"
        elif len(flags) >= 2:
            overall_risk = "medium"
        else:
            overall_risk = "low"

        return RedFlagReport(
            symbol=symbol,
            name=name,
            flags=flags,
            m_score=m_score,
            m_score_risk=self._m_score_risk_label(m_score),
            f_score=f_score,
            f_score_quality=self._f_score_label(f_score),
            overall_risk=overall_risk,
            total_flags=len(flags),
            critical_flags=critical_flags,
        )

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    @staticmethod
    def _check_accruals(financials: dict) -> Optional[RedFlag]:
        """应计项目 / 总资产 > 20% → 红旗。"""
        net_income = financials.get("net_profit", 0) or 0
        ocf = financials.get("operating_cashflow", 0) or 0
        total_assets = financials.get("total_assets", 1) or 1
        if total_assets <= 0:
            return None

        accruals = (net_income - ocf) / total_assets
        if abs(accruals) > 0.20:
            severity = RedFlagSeverity.CRITICAL if abs(accruals) > 0.30 else RedFlagSeverity.WARNING
            return RedFlag(
                name="应计项目异常",
                severity=severity,
                score=abs(accruals),
                threshold=0.20,
                actual_value=accruals,
                description=f"应计/总资产={accruals:.1%}，{'远超' if abs(accruals) > 0.30 else '超过'}20%阈值",
            )
        return None

    @staticmethod
    def _check_ar_ratio(financials: dict) -> Optional[RedFlag]:
        """应收账款增速 > 营收增速 + 20% → 红旗。"""
        ar_growth = financials.get("ar_growth", 0) or 0
        rev_growth = financials.get("revenue_growth", 0) or 0

        diff = ar_growth - rev_growth
        if diff > 0.20:
            return RedFlag(
                name="应收账款异常增长",
                severity=RedFlagSeverity.WARNING,
                score=diff,
                threshold=0.20,
                actual_value=diff,
                description=f"应收增速({ar_growth:.1%})远超营收增速({rev_growth:.1%})，可能虚增收入",
            )
        return None

    @staticmethod
    def _check_gross_margin(financials: dict) -> Optional[RedFlag]:
        """毛利率同比下降 > 5pp → 红旗。"""
        gm = financials.get("gross_margin", 0.5) or 0.5
        gm_prev = financials.get("gross_margin_prev", 0.5) or 0.5

        decline = gm_prev - gm
        if decline > 0.05:
            return RedFlag(
                name="毛利率恶化",
                severity=RedFlagSeverity.WARNING,
                score=decline * 100,
                threshold=0.05,
                actual_value=decline,
                description=f"毛利率下降 {decline:.1%}，竞争加剧或成本失控",
            )
        return None

    @staticmethod
    def _check_asset_turnover(financials: dict) -> Optional[RedFlag]:
        """资产周转率同比下降 > 20% → 红旗。"""
        at = financials.get("asset_turnover", 0.5) or 0.5
        at_prev = financials.get("asset_turnover_prev", 0.5) or 0.5
        if at_prev <= 0:
            return None

        decline = (at_prev - at) / at_prev
        if decline > 0.20:
            return RedFlag(
                name="资产效率恶化",
                severity=RedFlagSeverity.WARNING,
                score=decline,
                threshold=0.20,
                actual_value=decline,
                description=f"资产周转率下降 {decline:.1%}",
            )
        return None

    @staticmethod
    def _check_leverage(financials: dict) -> Optional[RedFlag]:
        """资产负债率 > 80% → 红旗。"""
        leverage = financials.get("debt_to_asset", 0) or 0
        if leverage > 0.80:
            severity = RedFlagSeverity.CRITICAL if leverage > 0.90 else RedFlagSeverity.WARNING
            return RedFlag(
                name="高杠杆风险",
                severity=severity,
                score=leverage,
                threshold=0.80,
                actual_value=leverage,
                description=f"资产负债率={leverage:.1%}",
            )
        return None

    @staticmethod
    def _check_cashflow_quality(financials: dict) -> Optional[RedFlag]:
        """经营现金流/净利润 < 0.5 连续 → 红旗。"""
        net_profit = financials.get("net_profit", 1) or 1
        ocf = financials.get("operating_cashflow", 0) or 0
        if net_profit <= 0:
            return None

        ratio = ocf / net_profit
        if ratio < 0.5:
            return RedFlag(
                name="现金流质量差",
                severity=RedFlagSeverity.CRITICAL if ratio < 0 else RedFlagSeverity.WARNING,
                score=1.0 - ratio,
                threshold=0.5,
                actual_value=ratio,
                description=f"经营现金流/净利润={ratio:.1%}，盈利质量存疑",
            )
        return None

    # ------------------------------------------------------------------
    # M-Score & F-Score (simplified with available data)
    # ------------------------------------------------------------------

    @staticmethod
    def _calc_m_score(financials: dict) -> Optional[float]:
        """简化版 Beneish M-Score。完整版需要 8 个变量。"""
        # 仅用可用数据近似计算
        dsri = 1.0    # Days Sales in Receivables Index
        gmi = 1.0     # Gross Margin Index
        aqi = 1.0     # Asset Quality Index
        sgi = 1.0     # Sales Growth Index
        depi = 1.0    # Depreciation Index
        sgai = 1.0    # SGA Expense Index
        lvgi = 1.0    # Leverage Index
        tata = 0.0    # Total Accruals to Total Assets

        # 用可用数据填充
        net_income = financials.get("net_profit", 0) or 0
        ocf = financials.get("operating_cashflow", 0) or 0
        total_assets = financials.get("total_assets", 1) or 1
        prev_assets = financials.get("total_assets_prev", total_assets) or total_assets

        if total_assets > 0:
            tata = (net_income - ocf) / total_assets

        leverage = financials.get("debt_to_asset", 0.5) or 0.5
        prev_leverage = financials.get("debt_to_asset_prev", leverage) or leverage
        if prev_leverage > 0:
            lvgi = leverage / prev_leverage

        rev_growth = financials.get("revenue_growth", 0) or 0
        sgi = 1.0 + rev_growth

        gm = financials.get("gross_margin", 0.5) or 0.5
        gm_prev = financials.get("gross_margin_prev", gm) or gm
        if gm_prev > 0:
            gmi = gm_prev / gm

        if prev_assets > 0:
            aqi = (total_assets - (financials.get("current_assets", 0) or 0)
                   - (financials.get("ppe", 0) or 0)) / total_assets

        # M-Score = -4.84 + 0.92*DSRI + 0.528*GMI + 0.404*AQI + 0.892*SGI
        #           + 0.115*DEPI - 0.172*SGAI + 4.679*TATA - 0.327*LVGI
        m = -4.84 + 0.92 * dsri + 0.528 * gmi + 0.404 * aqi + 0.892 * sgi \
            + 0.115 * depi - 0.172 * sgai + 4.679 * tata - 0.327 * lvgi
        return float(m)

    @staticmethod
    def _calc_f_score(financials: dict) -> Optional[float]:
        """简化版 Piotroski F-Score (0-9)。"""
        score = 0

        # 盈利能力 (0-4)
        if (financials.get("net_profit", 0) or 0) > 0:
            score += 1
        if (financials.get("operating_cashflow", 0) or 0) > 0:
            score += 1
        if (financials.get("roe", 0) or 0) > (financials.get("roe_prev", 0) or 0):
            score += 1
        if (financials.get("operating_cashflow", 0) or 0) > (financials.get("net_profit", 0) or 0):
            score += 1

        # 杠杆/流动性 (0-3)
        leverage = financials.get("debt_to_asset", 0.5) or 0.5
        prev_leverage = financials.get("debt_to_asset_prev", leverage) or leverage
        if leverage < prev_leverage:
            score += 1
        current_ratio = financials.get("current_ratio", 1) or 1
        prev_cr = financials.get("current_ratio_prev", current_ratio) or current_ratio
        if current_ratio > prev_cr:
            score += 1

        # 运营效率 (0-2)
        if (financials.get("gross_margin", 0.5) or 0.5) > (financials.get("gross_margin_prev", 0.5) or 0.5):
            score += 1
        if (financials.get("asset_turnover", 0.5) or 0.5) > (financials.get("asset_turnover_prev", 0.5) or 0.5):
            score += 1

        return float(score)

    # ------------------------------------------------------------------
    # Labels
    # ------------------------------------------------------------------

    @staticmethod
    def _m_score_risk_label(m_score: Optional[float]) -> str:
        if m_score is None:
            return "unknown"
        if m_score > -1.49:
            return "high"
        if m_score > -1.78:
            return "medium"
        return "low"

    @staticmethod
    def _f_score_label(f_score: Optional[float]) -> str:
        if f_score is None:
            return "unknown"
        if f_score >= 7:
            return "strong"
        if f_score >= 4:
            return "moderate"
        return "weak"
