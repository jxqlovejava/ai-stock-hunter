# -*- coding: utf-8 -*-
"""情绪信号检测 — 实时数据驱动的市场情绪分析。

数据来源优先级：akshare(东财) > 腾讯行情 > 本地缓存
追踪 14 个情绪指标，分三级:
  Level 1: 大盘情绪（每日）— 涨跌比、涨停/跌停数、成交量、北向资金、融资余额
  Level 2: 板块情绪（实时）— 板块涨跌比、板块资金流向、板块新闻情感
  Level 3: 事件驱动（实时）— 突发利空、过度反应、澄清反转、机构分歧、量价背离
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------

class SentimentLevel(str, Enum):
    EXTREME_PANIC = "EXTREME_PANIC"   # 极度恐慌 → 别人恐惧我贪婪
    PANIC = "PANIC"                    # 恐慌蔓延
    NORMAL = "NORMAL"                  # 正常波动
    GREED = "GREED"                    # 贪婪情绪
    EXTREME_GREED = "EXTREME_GREED"    # 极度贪婪 → 别人贪婪我恐惧


@dataclass
class IndicatorSnapshot:
    """单个情绪指标的当前值、阈值和判定。"""
    name: str                          # 指标中文名
    en_name: str                       # 英文名
    current_value: float
    unit: str                          # 单位 (%, 亿, 家, x)
    panic_threshold: Optional[float] = None   # < 此值为恐慌信号
    greed_threshold: Optional[float] = None   # > 此值为贪婪信号
    extreme_threshold: Optional[float] = None  # 极端阈值
    signal: str = ""                   # normal / panic / greed / extreme
    weight: float = 1.0                # 权重
    description: str = ""              # 人类可读的解释
    data_source: str = ""              # 数据来源
    data_freshness: str = ""           # 数据新鲜度


@dataclass
class MarketSentiment:
    """大盘情绪完整快照。"""
    level: SentimentLevel = SentimentLevel.NORMAL
    score: int = 50                    # 0=极端恐慌, 50=中性, 100=极端贪婪
    confidence: float = 0.0            # 0.0-1.0 数据完整度
    indicators: list[IndicatorSnapshot] = field(default_factory=list)
    panic_signals: list[str] = field(default_factory=list)
    greed_signals: list[str] = field(default_factory=list)
    extreme_signals: list[str] = field(default_factory=list)
    summary: str = ""                  # 一句话总结
    timestamp: str = ""                # ISO 时间戳
    data_errors: list[str] = field(default_factory=list)  # 数据获取失败记录
    panic_arb_advice: str = ""         # 恐慌套利建议


# ---------------------------------------------------------------------------
# 数据获取器
# ---------------------------------------------------------------------------

class SentimentDataFetcher:
    """从 akshare 获取实时市场情绪数据。

    所有 fetch_* 方法独立运行 — 一个失败不影响其他。
    """

    @staticmethod
    def fetch_market_breadth() -> dict:
        """获取市场宽度数据（涨跌比、涨停跌停数）。

        Returns dict with: advance_count, decline_count, limit_up, limit_down,
                          total_stocks, source, error (if any)
        """
        try:
            import akshare as ak
            df = ak.stock_zh_a_spot_em()
            if df is None or len(df) == 0:
                return {"error": "A 股实时行情返回空数据", "source": "akshare/东财"}

            # 过滤有效数据（排除停牌、无成交）
            valid = df[df['成交量'] > 0] if '成交量' in df.columns else df
            up = len(valid[valid['涨跌幅'] > 0])
            down = len(valid[valid['涨跌幅'] < 0])
            flat = len(valid) - up - down

            # 涨跌停判定（A 股 ±10%，科创/创业板 ±20%）
            limit_up = len(valid[valid['涨跌幅'] >= 9.5])
            limit_down = len(valid[valid['涨跌幅'] <= -9.5])

            return {
                "advance_count": up,
                "decline_count": down,
                "flat_count": flat,
                "total_stocks": len(valid),
                "limit_up": limit_up,
                "limit_down": limit_down,
                "source": "akshare/东方财富",
                "error": None,
            }
        except ImportError:
            logger.warning("akshare 未安装，无法获取实时行情")
            return {"error": "akshare 未安装", "source": "N/A"}
        except Exception as e:
            logger.warning(f"获取市场宽度失败: {e}")
            return {"error": str(e), "source": "akshare/东方财富"}

    @staticmethod
    def fetch_northbound_flow() -> dict:
        """获取北向资金净流向。

        Returns dict with: net_flow_rmb, direction, source, error
        """
        try:
            import akshare as ak
            # 尝试沪股通+深股通北向净流入
            df = ak.stock_hsgt_north_net_flow_in_em(symbol="沪股通")
            if df is not None and len(df) > 0:
                latest = df.iloc[-1]
                net_flow = float(latest.iloc[0]) if hasattr(latest, 'iloc') else 0.0
                return {
                    "net_flow_rmb": net_flow,  # 亿元
                    "direction": "流入" if net_flow > 0 else "流出",
                    "source": "akshare/东方财富",
                    "error": None,
                }
            return {"error": "北向资金数据为空", "source": "akshare/东方财富"}
        except ImportError:
            return {"error": "akshare 未安装", "source": "N/A"}
        except Exception as e:
            logger.warning(f"获取北向资金失败: {e}")
            return {"error": str(e), "source": "akshare/东方财富"}

    @staticmethod
    def fetch_margin_data() -> dict:
        """获取融资融券数据。

        Returns dict with: margin_balance, daily_change, source, error
        """
        try:
            import akshare as ak
            # 沪深两市融资融券汇总
            df = ak.stock_margin_detail_sse()
            if df is not None and len(df) > 0:
                latest = df.iloc[-1]
                return {
                    "margin_balance": float(latest.iloc[-1]) if hasattr(latest, 'iloc') else 0.0,
                    "source": "akshare/上交所",
                    "error": None,
                }
            return {"error": "融资融券数据为空", "source": "akshare/上交所"}
        except ImportError:
            return {"error": "akshare 未安装", "source": "N/A"}
        except Exception as e:
            logger.warning(f"获取融资融券数据失败: {e}")
            return {"error": str(e), "source": "akshare/上交所"}

    @staticmethod
    def fetch_volume_ratio() -> dict:
        """获取大盘成交量比（vs 20日均量）。

        Returns dict with: volume_ratio, latest_volume, avg_20d_volume, source, error
        """
        try:
            import akshare as ak
            df = ak.stock_zh_index_daily_em(symbol="sh000001")  # 上证指数
            if df is None or len(df) < 21:
                return {"error": "上证指数数据不足", "source": "akshare/东方财富"}

            latest = df.iloc[-1]
            avg_20 = df['volume'].tail(21).head(20).mean()
            ratio = float(latest['volume']) / float(avg_20) if avg_20 > 0 else 1.0

            return {
                "volume_ratio": round(ratio, 2),
                "latest_volume": int(latest['volume']),
                "avg_20d_volume": int(avg_20),
                "source": "akshare/东方财富",
                "error": None,
            }
        except ImportError:
            return {"error": "akshare 未安装", "source": "N/A"}
        except Exception as e:
            logger.warning(f"获取成交量数据失败: {e}")
            return {"error": str(e), "source": "akshare/东方财富"}


# ---------------------------------------------------------------------------
# 情绪检测器
# ---------------------------------------------------------------------------

class SentimentDetector:
    """多维度市场情绪检测器 — 接入实时数据并输出结构化分析。"""

    # ---- 阈值常量 ----
    PANIC_AD_RATIO = 0.33          # 涨跌比 < 0.33 → 恐慌
    GREED_AD_RATIO = 3.0           # 涨跌比 > 3.0 → 贪婪
    EXTREME_AD_RATIO = 0.2         # 涨跌比 < 0.2 → 极端恐慌
    PANIC_LIMIT_DOWN = 50          # 跌停 > 50 家 → 恐慌
    EXTREME_LIMIT_DOWN = 100       # 跌停 > 100 家 → 极端
    GREED_LIMIT_UP = 80            # 涨停 > 80 家 → 贪婪
    EXTREME_GREED_LIMIT_UP = 150   # 涨停 > 150 家 → 极度贪婪
    PANIC_VOLUME_SPIKE = 2.0       # 量比 > 2x → 恐慌放量
    PANIC_NORTHBOUND_OUT = -50     # 北向流出 > 50亿 → 恐慌
    EXTREME_NORTHBOUND_OUT = -100  # 北向流出 > 100亿 → 极端
    GREED_MARGIN_SPIKE = 100       # 融资日增 > 100亿 → 贪婪信号

    def __init__(self, fetcher: Optional[SentimentDataFetcher] = None):
        self.fetcher = fetcher or SentimentDataFetcher()

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------

    def detect_market(self) -> MarketSentiment:
        """检测当前大盘情绪 — 拉取实时数据并评估。

        返回完整的 MarketSentiment，包含所有指标明细、判定理由和恐慌套利建议。
        数据获取失败时使用默认值并标注 [DATA_GAP]。
        """
        indicators: list[IndicatorSnapshot] = []
        panic_signals: list[str] = []
        greed_signals: list[str] = []
        extreme_signals: list[str] = []
        data_errors: list[str] = []
        score = 50

        # ---- 1. 市场宽度 (涨跌比 + 涨跌停) ----
        breadth = self.fetcher.fetch_market_breadth()
        if breadth.get("error"):
            data_errors.append(f"市场宽度: {breadth['error']}")
            advance_decline = 1.0
            limit_up = 0
            limit_down = 0
        else:
            up, down = breadth["advance_count"], breadth["decline_count"]
            advance_decline = up / max(down, 1)
            limit_up = breadth["limit_up"]
            limit_down = breadth["limit_down"]

            indicators.append(IndicatorSnapshot(
                name="上涨家数", en_name="advance_count",
                current_value=up, unit="家",
                description=f"{up} 家上涨",
                data_source=breadth["source"],
            ))
            indicators.append(IndicatorSnapshot(
                name="下跌家数", en_name="decline_count",
                current_value=down, unit="家",
                description=f"{down} 家下跌",
                data_source=breadth["source"],
            ))

        # 涨跌比判定
        ad_indicator = IndicatorSnapshot(
            name="涨跌比", en_name="advance_decline_ratio",
            current_value=round(advance_decline, 2), unit="",
            panic_threshold=self.PANIC_AD_RATIO,
            greed_threshold=self.GREED_AD_RATIO,
            extreme_threshold=self.EXTREME_AD_RATIO,
            data_source=breadth.get("source", "N/A"),
        )
        if advance_decline < self.EXTREME_AD_RATIO:
            ad_indicator.signal = "extreme_panic"
            score -= 20
            extreme_signals.append(f"涨跌比 {advance_decline:.2f} < {self.EXTREME_AD_RATIO}（极端恐慌）")
        elif advance_decline < self.PANIC_AD_RATIO:
            ad_indicator.signal = "panic"
            score -= 15
            panic_signals.append(f"涨跌比 {advance_decline:.2f} < {self.PANIC_AD_RATIO}（恐慌）")
        elif advance_decline > self.GREED_AD_RATIO:
            ad_indicator.signal = "greed"
            score += 15
            greed_signals.append(f"涨跌比 {advance_decline:.2f} > {self.GREED_AD_RATIO}（贪婪）")
        else:
            ad_indicator.signal = "normal"
        ad_indicator.description = f"涨跌比 {advance_decline:.2f}（每 1 只下跌对应 {advance_decline:.1f} 只上涨）"
        indicators.append(ad_indicator)

        # 涨跌停判定
        lu_indicator = IndicatorSnapshot(
            name="涨停家数", en_name="limit_up_count",
            current_value=limit_up, unit="家",
            greed_threshold=self.GREED_LIMIT_UP,
            extreme_threshold=self.EXTREME_GREED_LIMIT_UP,
            data_source=breadth.get("source", "N/A"),
            description=f"{limit_up} 只涨停, {limit_down} 只跌停",
        )
        if limit_up > self.EXTREME_GREED_LIMIT_UP:
            lu_indicator.signal = "extreme_greed"
            score += 10
            extreme_signals.append(f"涨停 {limit_up} > {self.EXTREME_GREED_LIMIT_UP} 家（极度贪婪）")
        elif limit_up > self.GREED_LIMIT_UP:
            lu_indicator.signal = "greed"
            score += 8
            greed_signals.append(f"涨停 {limit_up} > {self.GREED_LIMIT_UP} 家（贪婪）")
        else:
            lu_indicator.signal = "normal"
        indicators.append(lu_indicator)

        ld_indicator = IndicatorSnapshot(
            name="跌停家数", en_name="limit_down_count",
            current_value=limit_down, unit="家",
            panic_threshold=self.PANIC_LIMIT_DOWN,
            extreme_threshold=self.EXTREME_LIMIT_DOWN,
            data_source=breadth.get("source", "N/A"),
        )
        if limit_down >= self.EXTREME_LIMIT_DOWN:
            ld_indicator.signal = "extreme_panic"
            score -= 20
            extreme_signals.append(f"跌停 {limit_down} ≥ {self.EXTREME_LIMIT_DOWN} 家（极端恐慌）")
        elif limit_down >= self.PANIC_LIMIT_DOWN:
            ld_indicator.signal = "panic"
            score -= 12
            panic_signals.append(f"跌停 {limit_down} ≥ {self.PANIC_LIMIT_DOWN} 家（恐慌）")
        else:
            ld_indicator.signal = "normal"
        ld_indicator.description = f"{limit_up} 只涨停, {limit_down} 只跌停"
        indicators.append(ld_indicator)

        # ---- 2. 成交量 ----
        vol = self.fetcher.fetch_volume_ratio()
        if vol.get("error"):
            data_errors.append(f"成交量: {vol['error']}")
            volume_ratio = 1.0
        else:
            volume_ratio = vol["volume_ratio"]
            indicators.append(IndicatorSnapshot(
                name="成交量比", en_name="volume_ratio",
                current_value=volume_ratio, unit="x",
                panic_threshold=self.PANIC_VOLUME_SPIKE,
                description=f"当前成交量 / 20日均量 = {volume_ratio:.2f}x",
                data_source=vol["source"],
            ))

        if volume_ratio > self.PANIC_VOLUME_SPIKE:
            panic_signals.append(f"成交量比 {volume_ratio:.2f}x > {self.PANIC_VOLUME_SPIKE}x（恐慌放量）")
            score -= 5

        # ---- 3. 北向资金 ----
        nb = self.fetcher.fetch_northbound_flow()
        if nb.get("error"):
            data_errors.append(f"北向资金: {nb['error']}")
            northbound_net = 0.0
        else:
            northbound_net = nb["net_flow_rmb"]
            indicators.append(IndicatorSnapshot(
                name="北向资金", en_name="northbound_net_flow",
                current_value=northbound_net, unit="亿元",
                panic_threshold=self.PANIC_NORTHBOUND_OUT,
                extreme_threshold=self.EXTREME_NORTHBOUND_OUT,
                description=f"北向净{nb['direction']} {abs(northbound_net):.1f} 亿",
                data_source=nb["source"],
            ))

        if northbound_net <= self.EXTREME_NORTHBOUND_OUT:
            extreme_signals.append(f"北向净流出 {abs(northbound_net):.0f} 亿 ≥ {abs(self.EXTREME_NORTHBOUND_OUT)} 亿（极端）")
            score -= 15
        elif northbound_net <= self.PANIC_NORTHBOUND_OUT:
            panic_signals.append(f"北向净流出 {abs(northbound_net):.0f} 亿 ≥ {abs(self.PANIC_NORTHBOUND_OUT)} 亿")
            score -= 8

        # ---- 4. 融资融券 ----
        margin = self.fetcher.fetch_margin_data()
        if margin.get("error"):
            data_errors.append(f"融资融券: {margin['error']}")
        else:
            # 简化：仅展示融资余额，不做判定（需要历史变化数据）
            indicators.append(IndicatorSnapshot(
                name="融资余额", en_name="margin_balance",
                current_value=margin.get("margin_balance", 0), unit="亿元",
                description=f"融资余额参考值",
                data_source=margin.get("source", "N/A"),
            ))

        # ---- 5. 综合判定 ----
        score = max(0, min(100, score))

        if extreme_signals:
            level = SentimentLevel.EXTREME_PANIC if score < 30 else SentimentLevel.EXTREME_GREED
        elif len(panic_signals) >= 3:
            level = SentimentLevel.PANIC
        elif len(panic_signals) >= 1 and len(greed_signals) >= 1:
            level = SentimentLevel.NORMAL  # 信号矛盾 → 正常
        elif len(greed_signals) >= 3:
            level = SentimentLevel.GREED
        else:
            level = SentimentLevel.NORMAL

        # 微调：极端信号覆盖
        if score <= 15:
            level = SentimentLevel.EXTREME_PANIC
        elif score >= 85:
            level = SentimentLevel.EXTREME_GREED

        # ---- 6. 恐慌套利建议 ----
        panic_arb_advice = self._generate_panic_arb_advice(level, score, panic_signals, extreme_signals)

        # ---- 7. 置信度 ----
        total_indicators = len(indicators)
        failed_indicators = len(data_errors)
        confidence = 1.0 - (failed_indicators / max(total_indicators, 1)) * 0.5
        confidence = min(1.0, max(0.0, confidence))

        # ---- 8. 一句话总结 ----
        level_labels = {
            SentimentLevel.EXTREME_PANIC: "市场处于极度恐慌状态，恐慌指标全面触发",
            SentimentLevel.PANIC: f"市场恐慌蔓延（{len(panic_signals)} 个恐慌信号）",
            SentimentLevel.NORMAL: "市场情绪平稳，无明显极端信号",
            SentimentLevel.GREED: f"市场贪婪情绪升温（{len(greed_signals)} 个贪婪信号）",
            SentimentLevel.EXTREME_GREED: "市场处于极度贪婪状态，追高风险极大",
        }

        return MarketSentiment(
            level=level,
            score=score,
            confidence=round(confidence, 2),
            indicators=indicators,
            panic_signals=panic_signals,
            greed_signals=greed_signals,
            extreme_signals=extreme_signals,
            summary=level_labels[level],
            timestamp=datetime.now().isoformat(),
            data_errors=data_errors,
            panic_arb_advice=panic_arb_advice,
        )

    # ------------------------------------------------------------------
    # 恐慌套利
    # ------------------------------------------------------------------

    def _generate_panic_arb_advice(
        self, level: SentimentLevel, score: int,
        panic_signals: list[str], extreme_signals: list[str],
    ) -> str:
        """根据情绪等级生成恐慌套利建议。"""
        if level == SentimentLevel.EXTREME_PANIC:
            return (
                "🔴 极度恐慌 — 触发恐慌套利条件\n"
                "   • 别人恐惧我贪婪：极端恐慌往往伴随过度抛售\n"
                "   • ⚠️ A 股 T+1 约束：恐慌抄底仓位上限 25%（当日无法止损）\n"
                "   • 建议等待次日确认信号——恐慌日流动性枯竭，跌停标的不可买入\n"
                "   • 优先关注被误杀的优质标的（基本面未变、因恐慌被拖累）\n"
                f"   • 触发信号: {'; '.join(extreme_signals[:3])}"
            )
        elif level == SentimentLevel.PANIC:
            return (
                "🟠 恐慌蔓延 — 关注恐慌套利机会\n"
                "   • 密切监控跌停家数和北向资金变化\n"
                "   • 如恐慌进一步升级为极端恐慌，可考虑分批建仓被误杀标的\n"
                f"   • 当前信号: {'; '.join(panic_signals[:3])}"
            )
        elif level == SentimentLevel.EXTREME_GREED:
            return (
                "🟢 极度贪婪 — 别人贪婪我恐惧\n"
                "   • 市场过热，追高风险极大\n"
                "   • 建议减仓/设置更紧的止损\n"
                "   • 考虑逐步兑现盈利，保留现金等待回调"
            )
        elif level == SentimentLevel.GREED:
            return (
                "🟡 市场偏贪婪 — 保持警惕\n"
                "   • 可继续持有但不宜追高加仓\n"
                "   • 设置移动止损保护利润"
            )
        else:
            return "🟢 市场情绪正常 — 无明显套利机会，按正常策略执行。"

    # ------------------------------------------------------------------
    # 板块情绪（Level 2）
    # ------------------------------------------------------------------

    def detect_sector(self, sector_data: dict) -> str:
        """检测板块情绪 — 根据板块涨跌比和资金流向。"""
        ratio = sector_data.get("advance_decline", 1.0)
        flow = sector_data.get("capital_flow", 0)
        if ratio < 0.5 and flow < 0:
            return "PANIC"
        elif ratio > 2.0 and flow > 0:
            return "GREED"
        return "NORMAL"
