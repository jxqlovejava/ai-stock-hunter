"""债务周期阶段定位 + 美元潮汐风险传导。

借鉴瑞·达利欧《债务危机》框架（经自媒体《全球6次债务危机》转述，T3 信源）：
  - 债务周期叙事: 低利率黄金时代 → 加杠杆/信用扩张 → 资产泡沫累积 → 加息刺破 → 去杠杆
  - 通缩型 vs 通胀型危机: 本币债（央行能印钞放水缓解）vs 外币债（印不了外币，越印贬值越快）
  - 美元潮汐: 美联储加息 + 美元走强 → 新兴市场/北向资金承压（拉美、亚洲金融危机教训）

数据源（逐字段独立 try/except 降级，失败标记 DATA_GAP）:
  - 社融增速 / M1-M2 剪刀差 / DR007 / 信贷脉冲: 复用 monetary_credit.MonetaryCreditAnalyzer
  - 美债 10Y 收益率: akshare bond_zh_us_rate
  - 美元指数 DXY: dxy_provider.fetch_dxy（东财直连 100.UDI + Yahoo DX-Y.NYB 双源交叉验证）
  - 美元兑人民币: akshare currency_boc_sina
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import Enum
from typing import Optional

from .dxy_provider import fetch_dxy

logger = logging.getLogger(__name__)

# 名义 GDP 增速（信贷脉冲 = 社融增速 - 名义 GDP 增速）
NOMINAL_GDP_GROWTH = 5.0
# 信用扩张/收缩阈值（信贷脉冲，单位 %）
CREDIT_PULSE_EXPAND = 1.0
CREDIT_PULSE_CONTRACT = -1.0
CREDIT_PULSE_FROTH = 2.0  # 强扩张 → 泡沫累积风险

# 美元潮汐方向判定阈值（美债 10Y 20日变化 / DXY 20日变化 / USDCY 20日变化）
US10Y_HIKE_BPS = 15.0
DXY_HIKE_PCT = 1.5
CNY_WEAKEN_PCT = 1.0


class DebtCyclePhase(str, Enum):
    """债务周期阶段（达利欧框架在 A 股宏观层面的映射）。"""

    NEUTRAL = "NEUTRAL"  # 信号不足 / 中性
    CREDIT_EXPANSION = "CREDIT_EXPANSION"  # 加杠杆 / 信用扩张
    ASSET_FROTH = "ASSET_FROTH"  # 资产泡沫累积（强扩张 + 高社融）
    DELEVERAGING = "DELEVERAGING"  # 去杠杆 / 信用收缩


@dataclass
class DollarTideSignal:
    """美元潮汐信号：美债利率 / 美元指数 / 人民币汇率 → A 股流动性传导。"""

    us10y: Optional[float] = None  # 美债 10Y 收益率 (%)
    us10y_change_20d: Optional[float] = None  # 20 日变化 (bps)
    dxy: Optional[float] = None  # 美元指数
    dxy_change_20d: Optional[float] = None  # 20 日变化 (%)
    usdcny: Optional[float] = None  # 美元兑人民币
    usdcny_change_20d: Optional[float] = None  # 20 日变化 (%)
    dxy_estimated: bool = False  # DXY 为 ECB 计算估算值（官方源不可用时的兜底）
    tide_direction: str = "neutral"  # inflow / outflow / neutral
    transmission: str = ""  # 传导链说明
    data_gaps: list[str] = field(default_factory=list)


@dataclass
class DebtCycleResult:
    """债务周期阶段 + 美元潮汐输出。"""

    phase: DebtCyclePhase = DebtCyclePhase.NEUTRAL
    phase_label: str = "信号不足"
    confidence: float = 0.3
    signals: dict[str, Optional[float]] = field(default_factory=dict)
    implication: str = ""
    dollar_tide: DollarTideSignal = field(default_factory=DollarTideSignal)
    data_gaps: list[str] = field(default_factory=list)


class DollarTideAnalyzer:
    """美元潮汐分析器 — 抓美债10Y/DXY/USDCY，判定 inflow/outflow 并给出传导链。"""

    def __init__(self) -> None:
        self._cache: dict[str, tuple[object, object]] = {}
        self._cache_ttl = timedelta(hours=4)

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def analyze(self) -> DollarTideSignal:
        sig = DollarTideSignal()
        self._fetch_bond(sig)
        self._fetch_dxy(sig)
        self._fetch_usdcny(sig)
        self._classify_tide(sig)
        sig.transmission = self._transmission(sig)
        return sig

    # ------------------------------------------------------------------
    # Fetchers（逐字段独立降级）
    # ------------------------------------------------------------------

    def _fetch_bond(self, sig: DollarTideSignal) -> None:
        try:
            import akshare as ak

            df = ak.bond_zh_us_rate(start_date=(date.today() - timedelta(days=120)).strftime("%Y%m%d"))
            if df is None or len(df) < 20:
                sig.data_gaps.append("美债10Y")  # 空数据也需显式声明 DATA_GAP
                return
            for col in df.columns:
                c = str(col)
                if "美国" in c and ("10" in c):
                    vals = df[col].dropna().tolist()
                    if len(vals) >= 20:
                        sig.us10y = float(vals[-1])
                        sig.us10y_change_20d = round((float(vals[-1]) - float(vals[-20])) * 100, 1)
                    break
        except Exception as exc:  # noqa: BLE001
            logger.debug("DollarTide us10y fetch failed: %s", exc)
        if sig.us10y is None:
            sig.data_gaps.append("美债10Y")

    def _fetch_dxy(self, sig: DollarTideSignal) -> None:
        try:
            data = fetch_dxy()
        except Exception as exc:  # noqa: BLE001
            logger.debug("DollarTide dxy fetch failed: %s", exc)
            sig.data_gaps.append("美元指数DXY")
            return
        if data.dxy is None:
            sig.data_gaps.extend(data.errors)
            return
        sig.dxy = data.dxy
        sig.dxy_change_20d = data.dxy_change_20d
        # 仅 dxy 值本身是否估算；change 是否估算单独用 data_gaps 标记
        sig.dxy_estimated = data.dxy_estimated
        if data.dxy_estimated:
            # 估算值显式标记，禁止冒充官方 ICE DXY（ECB 参考汇率计算，非官方实时）
            sig.data_gaps.append("美元指数DXY为ECB估算值[ESTIMATED]")
        if data.change_estimated:
            sig.data_gaps.append("美元指数DXY 20日变化为估算[ESTIMATED]")
        if not data.cross_validated:
            # ⚠️ 单源未验证（guardrails 要求关键数据 ≥2 源）
            sig.data_gaps.append(f"美元指数DXY单源({data.source})")

    def _fetch_usdcny(self, sig: DollarTideSignal) -> None:
        try:
            import akshare as ak

            end = date.today()
            start = end - timedelta(days=150)
            df = ak.currency_boc_sina(
                symbol="美元",
                start_date=start.strftime("%Y%m%d"),
                end_date=end.strftime("%Y%m%d"),
            )
            if df is None or len(df) == 0:
                sig.data_gaps.append("美元兑人民币")  # 空数据也需显式声明 DATA_GAP
                return
            # 价格列（中行折算价/央行中间价），单位为 分 → 除以 100 得 USD/CNY
            col = next(
                (c for c in df.columns if "折算" in str(c) or "中间价" in str(c)),
                None,
            )
            if col is None:
                sig.data_gaps.append("美元兑人民币")
                return
            vals = [float(v) / 100.0 for v in df[col].dropna().tolist()]
            if len(vals) >= 20:
                sig.usdcny = vals[-1]
                sig.usdcny_change_20d = round((vals[-1] / vals[-20] - 1) * 100, 2)
        except Exception as exc:  # noqa: BLE001
            logger.debug("DollarTide usdcny fetch failed: %s", exc)
        if sig.usdcny is None:
            sig.data_gaps.append("美元兑人民币")

    # ------------------------------------------------------------------
    # 判定与传导
    # ------------------------------------------------------------------

    def _classify_tide(self, sig: DollarTideSignal) -> None:
        """判定美元潮汐方向: 美债利率↑ 或 DXY↑ 或 人民币贬值 → outflow。"""
        outflow = 0
        inflow = 0
        if sig.us10y_change_20d is not None:
            if sig.us10y_change_20d > US10Y_HIKE_BPS:
                outflow += 1
            elif sig.us10y_change_20d < -US10Y_HIKE_BPS:
                inflow += 1
        if sig.dxy_change_20d is not None:
            if sig.dxy_change_20d > DXY_HIKE_PCT:
                outflow += 1
            elif sig.dxy_change_20d < -DXY_HIKE_PCT:
                inflow += 1
        if sig.usdcny_change_20d is not None:
            if sig.usdcny_change_20d > CNY_WEAKEN_PCT:
                outflow += 1
            elif sig.usdcny_change_20d < -CNY_WEAKEN_PCT:
                inflow += 1
        if outflow > inflow:
            sig.tide_direction = "outflow"
        elif inflow > outflow:
            sig.tide_direction = "inflow"
        else:
            sig.tide_direction = "neutral"

    @staticmethod
    def _transmission(sig: DollarTideSignal) -> str:
        """美元潮汐 → 北向资金 → A股估值 传导链说明。"""
        if sig.tide_direction == "outflow":
            parts = ["美元潮汐流出: 美债利率上升/美元走强/人民币贬值 → 北向资金承压 → A股估值受压制（拉美/亚洲金融危机教训）"]
            if sig.us10y is not None:
                parts.append(f"美债10Y {sig.us10y:.2f}%（20日 {sig.us10y_change_20d:+.0f}bps）")
            if sig.dxy is not None:
                parts.append(f"DXY {sig.dxy:.1f}（20日 {sig.dxy_change_20d:+.2f}%）")
            if sig.usdcny is not None:
                parts.append(f"USDCNY {sig.usdcny:.4f}（20日 {sig.usdcny_change_20d:+.2f}%）")
            return "；".join(parts)
        if sig.tide_direction == "inflow":
            return "美元潮汐流入: 美债利率下行/美元走弱/人民币升值 → 有利北向资金回流 → A股流动性偏暖"
        return "美元潮汐中性: 美债利率/美元指数/人民币汇率无一致方向，对A股流动性影响有限"


class DebtCycleAnalyzer:
    """债务周期阶段定位分析器。"""

    def __init__(self) -> None:
        self._tide = DollarTideAnalyzer()

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def analyze(self) -> DebtCycleResult:
        res = DebtCycleResult()
        res.dollar_tide = self._tide.analyze()

        # 复用货币-信用象限数据（社融增速/信贷脉冲/M1-M2/DR007），失败则 DATA_GAP
        try:
            from src.macro.monetary_credit import MonetaryCreditAnalyzer

            regime = MonetaryCreditAnalyzer().analyze()
            res.signals = {
                "sf_growth": regime.social_financing_growth,
                "credit_pulse": regime.credit_pulse,
                "m1_m2_gap": regime.m1_m2_gap,
                "dr007": regime.dr007,
                "dxy": res.dollar_tide.dxy,
                "us10y": res.dollar_tide.us10y,
                "usdcny": res.dollar_tide.usdcny,
            }
        except Exception as exc:  # noqa: BLE001
            logger.debug("debt_cycle monetary_credit reuse failed: %s", exc)
            res.data_gaps.append("社融/信贷脉冲")

        self._classify_phase(res)
        res.confidence = self._confidence(res)
        res.implication = self._implication(res)
        res.data_gaps.extend(res.dollar_tide.data_gaps)
        return res

    # ------------------------------------------------------------------
    # 阶段判定
    # ------------------------------------------------------------------

    @staticmethod
    def _classify_phase(res: DebtCycleResult) -> None:
        sf = res.signals.get("sf_growth")
        cp = res.signals.get("credit_pulse")
        dr007 = res.signals.get("dr007")
        m1m2 = res.signals.get("m1_m2_gap")

        if cp is not None and cp >= CREDIT_PULSE_FROTH and sf is not None and sf > NOMINAL_GDP_GROWTH + 1.5:
            res.phase = DebtCyclePhase.ASSET_FROTH
            res.phase_label = "资产泡沫累积（强信用扩张 + 高社融）"
            return
        if cp is not None:
            if cp >= CREDIT_PULSE_EXPAND:
                res.phase = DebtCyclePhase.CREDIT_EXPANSION
                res.phase_label = "加杠杆 / 信用扩张"
                return
            if cp <= CREDIT_PULSE_CONTRACT:
                res.phase = DebtCyclePhase.DELEVERAGING
                res.phase_label = "去杠杆 / 信用收缩"
                return
        # 信贷脉冲缺失时用 M1-M2 剪刀差做方向代理（走阔=资金活化/扩张，倒挂=沉淀/收缩）
        if cp is None and m1m2 is not None:
            if m1m2 > 1.0:
                res.phase = DebtCyclePhase.CREDIT_EXPANSION
                res.phase_label = "加杠杆 / 信用扩张（M1-M2 剪刀差走阔代理）"
                return
            if m1m2 < -1.0:
                res.phase = DebtCyclePhase.DELEVERAGING
                res.phase_label = "去杠杆 / 信用收缩（M1-M2 剪刀差倒挂代理）"
                return
        # 信贷脉冲与 M1-M2 都缺失时用 DR007 相对政策利率做弱代理
        if cp is None and dr007 is not None:
            if dr007 > 2.2:
                res.phase = DebtCyclePhase.DELEVERAGING
                res.phase_label = "去杠杆（资金面偏紧）"
                return
        res.phase = DebtCyclePhase.NEUTRAL
        res.phase_label = "信号不足 / 中性"

    @staticmethod
    def _confidence(res: DebtCycleResult) -> float:
        missing = sum(1 for v in res.signals.values() if v is None)
        base = 1.0 - missing * 0.15
        if res.dollar_tide.tide_direction == "neutral" and missing >= 3:
            base -= 0.2
        if res.dollar_tide.dxy_estimated:
            base -= 0.1  # DXY 为 ECB 估算值，非官方实时，信号可靠性下降
        return max(0.3, round(base, 2))

    @staticmethod
    def _implication(res: DebtCycleResult) -> str:
        parts = [f"债务周期阶段: {res.phase_label}（置信度 {res.confidence:.2f}）"]
        tide = res.dollar_tide
        if tide.transmission:
            parts.append(tide.transmission)
        if res.phase == DebtCyclePhase.DELEVERAGING:
            parts.append("信用收缩期: 高杠杆/题材股承压，守现金优先（通缩型危机应对：留足流动性）")
        elif res.phase == DebtCyclePhase.ASSET_FROTH:
            parts.append("泡沫累积期: 警惕加息刺破，控制杠杆，勿追高估值泡沫资产")
        elif res.phase == DebtCyclePhase.CREDIT_EXPANSION:
            parts.append("信用扩张期: 权益相对受益，但需跟踪信贷脉冲何时转负")
        return "。".join(p for p in parts if p)


def analyze_debt_cycle() -> DebtCycleResult:
    """便捷入口。"""
    return DebtCycleAnalyzer().analyze()
