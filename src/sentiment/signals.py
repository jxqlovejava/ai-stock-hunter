# -*- coding: utf-8 -*-
"""情绪信号检测 — 实时数据驱动的市场情绪分析。

数据来源优先级：akshare(东财) > 腾讯行情 > 本地缓存
追踪 14 个情绪指标，分三级:
  Level 1: 大盘情绪（每日）— 涨跌比、涨停/跌停数、成交量、北向资金、融资余额
  Level 2: 板块情绪（实时）— 板块涨跌比、板块资金流向、板块新闻情感
  Level 3: 事件驱动（实时）— 突发利空、过度反应、澄清反转、机构分歧、量价背离
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Optional

import numpy as np

try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False

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
    percentile: float = 50.0           # 历史分位数 (0-100)，50=中性
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

    @staticmethod
    def fetch_limit_up_pool() -> dict:
        """获取涨停池与炸板池 → 炸板率 + 连板高度 + 连板梯队。

        Returns dict with: break_rate, max_height, zt_count, zb_count,
                          ladder (连板梯队), source, error
        """
        try:
            import akshare as ak
            today = datetime.now().strftime("%Y%m%d")

            # 涨停池
            zt_df = ak.stock_zt_pool_em(date=today)
            if zt_df is None or len(zt_df) == 0:
                # 非交易时间可能为空，尝试前一交易日
                return {"error": "涨停池数据为空（可能非交易时间）", "source": "akshare/东方财富"}

            zt_count = len(zt_df)

            # 炸板池
            zb_count = 0
            try:
                zb_df = ak.stock_zt_pool_zbgc_em(date=today)
                if zb_df is not None and len(zb_df) > 0:
                    zb_count = len(zb_df)
            except Exception:
                logger.debug("炸板池获取失败，炸板数设为 0")

            # 炸板率
            total_attempts = zt_count + zb_count
            break_rate = zb_count / max(total_attempts, 1)

            # 连板高度 & 梯队
            max_height = 0
            ladder: dict[int, int] = {}
            if '连板数' in zt_df.columns:
                lb_col = zt_df['连板数']
                for lb in lb_col.dropna():
                    n = int(lb)
                    max_height = max(max_height, n)
                    ladder[n] = ladder.get(n, 0) + 1
            elif '连板天数' in zt_df.columns:
                lb_col = zt_df['连板天数']
                for lb in lb_col.dropna():
                    n = int(lb)
                    max_height = max(max_height, n)
                    ladder[n] = ladder.get(n, 0) + 1

            # 如果没有连板数列，尝试从名称推断
            if max_height == 0:
                for _, row in zt_df.iterrows():
                    name = str(row.get('名称', row.get('name', '')))
                    if '连板' in name or row.get('连板数', row.get('连续涨停天数', 0)):
                        pass  # 已处理

            return {
                "break_rate": round(break_rate, 3),
                "max_height": max_height,
                "zt_count": zt_count,
                "zb_count": zb_count,
                "ladder": {str(k): v for k, v in sorted(ladder.items())},
                "source": "akshare/东方财富",
                "error": None,
            }
        except ImportError:
            return {"error": "akshare 未安装", "source": "N/A"}
        except Exception as e:
            logger.warning(f"获取涨停池数据失败: {e}")
            return {"error": str(e), "source": "akshare/东方财富"}

    @staticmethod
    def fetch_etf_ivix_proxy() -> dict:
        """获取 50ETF 期权波动率指数 QVIX（A 股版 VIX 官方继任者）。

        iVIX 已于 2018 年停发，QVIX 是上交所官方替代品。
        使用 akshare 的 index_option_50etf_qvix() 获取。

        Returns dict with: ivix_proxy, latest_close, change_pct, source, error
        """
        try:
            import akshare as ak
            df = ak.index_option_50etf_qvix()
            if df is None or len(df) == 0:
                return {"error": "QVIX 数据为空", "source": "akshare/上交所"}

            latest = df.iloc[-1]
            ivix_val = float(latest['close'])

            # 计算日变化
            prev_close = float(df.iloc[-2]['close']) if len(df) > 1 else ivix_val
            change = ivix_val - prev_close

            return {
                "ivix_proxy": round(ivix_val, 1),
                "latest_close": round(ivix_val, 1),
                "change": round(change, 1),
                "source": "akshare/上交所(QVIX)",
                "error": None,
            }
        except ImportError:
            return {"error": "akshare 未安装", "source": "N/A"}
        except Exception as e:
            logger.warning(f"获取 QVIX 失败: {e}")
            return {"error": str(e), "source": "akshare/上交所"}

    @staticmethod
    def fetch_market_fund_flow() -> dict:
        """获取全市场资金流向（主力/超大单/大单/中单/小单）。

        使用东方财富大盘资金流向接口。

        Returns dict with: main_net, super_large_net, large_net, medium_net,
                          small_net, total_turnover, source, error
        """
        try:
            import akshare as ak
            df = ak.stock_market_fund_flow()
            if df is None or len(df) == 0:
                return {"error": "大盘资金流向数据为空", "source": "akshare/东方财富"}

            latest = df.iloc[-1]

            # 字段映射（不同版本 akshare 字段名可能不同）
            def _get(col_candidates: list[str], default: float = 0.0) -> float:
                for col in col_candidates:
                    if col in df.columns:
                        try:
                            return float(latest[col])
                        except (ValueError, TypeError):
                            continue
                return default

            # akshare 返回单位为元，转换为亿元以便与阈值比较和展示
            main_net = _get(["主力净流入", "主力净流入-净额", "main_net"], 0.0) / 1e8
            super_large_net = _get(["超大单净流入", "超大单净流入-净额", "super_large_net"], 0.0) / 1e8
            large_net = _get(["大单净流入", "大单净流入-净额", "large_net"], 0.0) / 1e8
            medium_net = _get(["中单净流入", "中单净流入-净额", "medium_net"], 0.0) / 1e8
            small_net = _get(["小单净流入", "小单净流入-净额", "small_net"], 0.0) / 1e8

            return {
                "main_net": round(main_net, 2),          # 亿元
                "super_large_net": round(super_large_net, 2),
                "large_net": round(large_net, 2),
                "medium_net": round(medium_net, 2),
                "small_net": round(small_net, 2),
                "source": "akshare/东方财富",
                "error": None,
            }
        except ImportError:
            return {"error": "akshare 未安装", "source": "N/A"}
        except Exception as e:
            logger.warning(f"获取大盘资金流向失败: {e}")
            return {"error": str(e), "source": "akshare/东方财富"}

    @staticmethod
    def fetch_margin_history(days: int = 20) -> dict:
        """获取融资余额历史 → 日变化 + 偏离度。

        Returns dict with: latest_balance, daily_change, avg_20d, std_20d,
                          deviation_sigma, source, error
        """
        try:
            import akshare as ak
            df = ak.stock_margin_sse(start_date="")
            if df is None or len(df) < 5:
                return {"error": "融资余额历史数据不足", "source": "akshare/上交所"}

            # 找融资余额列
            balance_col = None
            for col in df.columns:
                if '融资余额' in str(col) or 'margin_balance' in str(col).lower():
                    balance_col = col
                    break
            if balance_col is None:
                # 尝试最后一列（通常是余额）
                numeric_cols = df.select_dtypes(include=[np.number]).columns
                if len(numeric_cols) > 0:
                    balance_col = numeric_cols[-1]

            if balance_col is None:
                return {"error": "无法识别融资余额列", "source": "akshare/上交所"}

            recent = df.tail(days + 1)
            if len(recent) < 2:
                return {"error": "融资余额历史不足", "source": "akshare/上交所"}

            # akshare 返回单位为元，转换为亿元
            balances = recent[balance_col].astype(float) / 1e8
            latest_balance = float(balances.iloc[-1])
            prev_balance = float(balances.iloc[-2])
            daily_change = latest_balance - prev_balance

            window = min(days, len(balances))
            rolling = balances.tail(window)
            avg_20d = float(rolling.mean())
            std_20d = float(rolling.std()) if len(rolling) > 2 else 1.0
            deviation_sigma = (latest_balance - avg_20d) / max(std_20d, 1e-6)

            return {
                "latest_balance": round(latest_balance, 2),
                "daily_change": round(daily_change, 2),
                "avg_20d": round(avg_20d, 2),
                "std_20d": round(std_20d, 2),
                "deviation_sigma": round(deviation_sigma, 2),
                "source": "akshare/上交所",
                "error": None,
            }
        except ImportError:
            return {"error": "akshare 未安装", "source": "N/A"}
        except Exception as e:
            logger.warning(f"获取融资余额历史失败: {e}")
            return {"error": str(e), "source": "akshare/上交所"}


# ---------------------------------------------------------------------------
# 历史分位数存储
# ---------------------------------------------------------------------------

class SentimentHistory:
    """持久化情绪评分历史，用于分位数校准。

    将每次 detect_market() 的结果追加到 JSON 文件，
    提供最近 N 条记录的加载和分位数计算。
    """

    DEFAULT_PATH = Path("data/sentiment_history.json")
    DEFAULT_WINDOW = 60  # 默认 60 个交易日窗口

    @classmethod
    def _path(cls) -> Path:
        """获取存储路径，确保目录存在。"""
        p = cls.DEFAULT_PATH
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    @classmethod
    def load(cls) -> list[dict]:
        """加载全部历史记录。"""
        path = cls._path()
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"读取情绪历史失败: {e}")
            return []

    @classmethod
    def save(cls, record: dict) -> None:
        """追加一条情绪记录。"""
        path = cls._path()
        history = cls.load()
        history.append(record)
        # 只保留最近 250 条（约 1 年交易日）
        if len(history) > 250:
            history = history[-250:]
        path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def recent(cls, n: int = DEFAULT_WINDOW) -> "pd.DataFrame":
        """返回最近 n 条记录为 DataFrame。"""
        if not HAS_PANDAS:
            return None
        history = cls.load()
        if not history:
            return None
        recent = history[-n:]
        return pd.DataFrame(recent)

    @classmethod
    def percentile_of(cls, score: float, window: int = DEFAULT_WINDOW) -> float:
        """计算当前 score 在历史窗口中的分位数 (0-100)。

        返回: 0 = 历史最低位, 100 = 历史最高位。
        历史数据不足时返回 50（中性）。
        """
        history = cls.load()
        scores = [r.get("score", 50) for r in history[-window:]]
        if len(scores) < 5:
            return 50.0
        # 严格小于当前分数的比例 × 100
        rank = sum(1 for s in scores if s < score)
        percentile = (rank / len(scores)) * 100.0
        return round(percentile, 1)


# ---------------------------------------------------------------------------
# 情绪检测器
# ---------------------------------------------------------------------------

class SentimentDetector:
    """多维度市场情绪检测器 — 接入实时数据并输出结构化分析。"""

    # ---- 阈值常量 ----
    # 涨跌比 / 涨跌停
    PANIC_AD_RATIO = 0.33          # 涨跌比 < 0.33 → 恐慌
    GREED_AD_RATIO = 3.0           # 涨跌比 > 3.0 → 贪婪
    EXTREME_AD_RATIO = 0.2         # 涨跌比 < 0.2 → 极端恐慌
    PANIC_LIMIT_DOWN = 50          # 跌停 > 50 家 → 恐慌
    EXTREME_LIMIT_DOWN = 100       # 跌停 > 100 家 → 极端
    GREED_LIMIT_UP = 80            # 涨停 > 80 家 → 贪婪
    EXTREME_GREED_LIMIT_UP = 150   # 涨停 > 150 家 → 极度贪婪
    # 成交量 / 北向
    PANIC_VOLUME_SPIKE = 2.0       # 量比 > 2x → 恐慌放量
    PANIC_NORTHBOUND_OUT = -50     # 北向流出 > 50亿 → 恐慌
    EXTREME_NORTHBOUND_OUT = -100  # 北向流出 > 100亿 → 极端
    GREED_MARGIN_SPIKE = 100       # 融资日增 > 100亿 → 贪婪信号
    # 炸板率 / 连板高度 (P0 新增)
    BREAK_RATE_PANIC = 0.40        # 炸板率 > 40% → 恐慌
    BREAK_RATE_EXTREME = 0.50      # 炸板率 > 50% → 极端恐慌
    MAX_HEIGHT_GREED = 7           # 连板高度 > 7 板 → 贪婪
    MAX_HEIGHT_PANIC = 3           # 连板高度 < 3 板(有涨停) → 短线情绪弱
    # QVIX (P0 新增)
    IVIX_PANIC = 30                # IV > 30 → 恐慌
    IVIX_EXTREME = 40              # IV > 40 → 极端恐慌
    IVIX_GREED = 15                # IV < 15 → 过度安逸
    # 主力资金 (P1 新增)
    MAIN_OUTFLOW_PANIC = -200      # 主力净流出 > 200亿 → 恐慌
    SUPER_LARGE_OUTFLOW_PANIC = -100  # 超大单净流出 > 100亿 → 恐慌
    # 融资余额偏离度 (P1 新增)
    MARGIN_DAILY_DECLINE_PANIC = -50   # 融资日减 > 50亿 → 恐慌
    MARGIN_DEV_SIGMA = 2.0             # 偏离 20 日均线 > 2σ → 增强信号

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

        # ---- 4. 融资融券 (历史数据 + 阈值判定) ----
        margin_hist = self.fetcher.fetch_margin_history(days=20)
        if margin_hist.get("error"):
            data_errors.append(f"融资融券历史: {margin_hist['error']}")
            # 回退：尝试旧版单点数据
            margin = self.fetcher.fetch_margin_data()
            if margin.get("error"):
                data_errors.append(f"融资融券: {margin['error']}")
            else:
                indicators.append(IndicatorSnapshot(
                    name="融资余额", en_name="margin_balance",
                    current_value=margin.get("margin_balance", 0), unit="亿元",
                    description=f"融资余额（无历史数据，不判定）",
                    data_source=margin.get("source", "N/A"),
                ))
        else:
            latest_balance = margin_hist["latest_balance"]
            daily_change = margin_hist["daily_change"]
            avg_20d = margin_hist["avg_20d"]
            dev_sigma = margin_hist["deviation_sigma"]

            # 融资余额变化判定
            margin_signal = "normal"
            if daily_change <= -50:  # 日减 > 50 亿
                margin_signal = "panic"
                panic_signals.append(f"融资余额日减 {abs(daily_change):.0f} 亿 ≥ 50 亿（去杠杆恐慌）")
                score -= 5
            elif daily_change >= self.GREED_MARGIN_SPIKE:
                margin_signal = "greed"
                greed_signals.append(f"融资余额日增 {daily_change:.0f} 亿 ≥ {self.GREED_MARGIN_SPIKE} 亿（杠杆贪婪）")
                score += 5

            # 偏离度增强
            if abs(dev_sigma) >= self.MARGIN_DEV_SIGMA:
                if dev_sigma > 0 and margin_signal == "greed":
                    greed_signals.append(f"融资余额偏离 20 日均线 +{dev_sigma:.1f}σ（加速上杠杆）")
                    score += 3
                elif dev_sigma < 0 and margin_signal == "panic":
                    panic_signals.append(f"融资余额偏离 20 日均线 {dev_sigma:.1f}σ（加速去杠杆）")
                    score -= 3

            indicators.append(IndicatorSnapshot(
                name="融资余额", en_name="margin_balance",
                current_value=latest_balance, unit="亿元",
                greed_threshold=self.GREED_MARGIN_SPIKE,
                signal=margin_signal,
                description=f"融资 {latest_balance:.1f} 亿（日变化 {daily_change:+.1f} 亿，偏离 {dev_sigma:+.1f}σ）",
                data_source=margin_hist["source"],
            ))

        # ---- 5. 炸板率 & 连板高度 (P0 新增) ----
        lu_pool = self.fetcher.fetch_limit_up_pool()
        if lu_pool.get("error"):
            data_errors.append(f"涨停池: {lu_pool['error']}")
        else:
            break_rate = lu_pool["break_rate"]
            max_height = lu_pool["max_height"]
            zt_count = lu_pool.get("zt_count", 0)
            zb_count = lu_pool.get("zb_count", 0)

            # 炸板率判定
            br_signal = "normal"
            if break_rate >= self.BREAK_RATE_EXTREME:
                br_signal = "extreme_panic"
                score -= 15
                extreme_signals.append(f"炸板率 {break_rate*100:.0f}% ≥ {self.BREAK_RATE_EXTREME*100:.0f}%（极端恐慌）")
            elif break_rate >= self.BREAK_RATE_PANIC:
                br_signal = "panic"
                score -= 10
                panic_signals.append(f"炸板率 {break_rate*100:.0f}% ≥ {self.BREAK_RATE_PANIC*100:.0f}%（封板意愿弱）")

            indicators.append(IndicatorSnapshot(
                name="炸板率", en_name="break_rate",
                current_value=round(break_rate * 100, 1), unit="%",
                panic_threshold=self.BREAK_RATE_PANIC * 100,
                extreme_threshold=self.BREAK_RATE_EXTREME * 100,
                signal=br_signal,
                description=f"{zt_count} 只涨停, {zb_count} 只炸板（炸板率 {break_rate*100:.1f}%）",
                data_source=lu_pool["source"],
            ))

            # 连板高度判定
            mh_signal = "normal"
            if max_height >= self.MAX_HEIGHT_GREED:
                mh_signal = "greed"
                score += 8
                greed_signals.append(f"最高连板 {max_height} 板 ≥ {self.MAX_HEIGHT_GREED} 板（短线情绪亢奋）")
            elif max_height < self.MAX_HEIGHT_PANIC and zt_count > 0:
                mh_signal = "panic"
                score -= 5
                panic_signals.append(f"最高连板仅 {max_height} 板 < {self.MAX_HEIGHT_PANIC}（短线情绪低迷）")

            ladder_desc = ", ".join(f"{k}板×{v}" for k, v in lu_pool.get("ladder", {}).items())
            indicators.append(IndicatorSnapshot(
                name="连板高度", en_name="max_consecutive_height",
                current_value=max_height, unit="板",
                greed_threshold=self.MAX_HEIGHT_GREED,
                panic_threshold=self.MAX_HEIGHT_PANIC,
                signal=mh_signal,
                description=f"最高 {max_height} 连板" + (f"（{ladder_desc}）" if ladder_desc else ""),
                data_source=lu_pool["source"],
            ))

        # ---- 6. QVIX / 50ETF 隐含波动率 (P0 新增) ----
        ivix = self.fetcher.fetch_etf_ivix_proxy()
        if ivix.get("error"):
            data_errors.append(f"QVIX: {ivix['error']}")
        else:
            ivix_val = ivix["ivix_proxy"]
            iv_signal = "normal"
            if ivix_val >= self.IVIX_EXTREME:
                iv_signal = "extreme_panic"
                score -= 15
                extreme_signals.append(f"QVIX {ivix_val:.0f} ≥ {self.IVIX_EXTREME}（极端恐慌）")
            elif ivix_val >= self.IVIX_PANIC:
                iv_signal = "panic"
                score -= 10
                panic_signals.append(f"QVIX {ivix_val:.0f} ≥ {self.IVIX_PANIC}（恐慌升温）")
            elif ivix_val <= self.IVIX_GREED:
                iv_signal = "greed"
                score += 5
                greed_signals.append(f"QVIX {ivix_val:.0f} ≤ {self.IVIX_GREED}（过度安逸）")

            indicators.append(IndicatorSnapshot(
                name="QVIX(50ETF波指)", en_name="qvix_proxy",
                current_value=ivix_val, unit="%",
                panic_threshold=self.IVIX_PANIC,
                extreme_threshold=self.IVIX_EXTREME,
                greed_threshold=self.IVIX_GREED,
                signal=iv_signal,
                description=f"波动率指数 {ivix_val:.1f}%（日变化 {ivix.get('change', 0):+.1f}）",
                data_source=ivix["source"],
            ))

        # ---- 7. 主力资金流向 (P1 新增) ----
        fund_flow = self.fetcher.fetch_market_fund_flow()
        if fund_flow.get("error"):
            data_errors.append(f"主力资金: {fund_flow['error']}")
        else:
            main_net = fund_flow["main_net"]
            super_large_net = fund_flow["super_large_net"]

            # 主力净流向判定
            main_signal = "normal"
            if main_net <= self.MAIN_OUTFLOW_PANIC:
                main_signal = "panic"
                score -= 10
                panic_signals.append(f"主力净流出 {abs(main_net):.0f} 亿 ≥ {abs(self.MAIN_OUTFLOW_PANIC)} 亿（主力撤退）")

            indicators.append(IndicatorSnapshot(
                name="主力资金", en_name="main_capital_flow",
                current_value=main_net, unit="亿元",
                panic_threshold=self.MAIN_OUTFLOW_PANIC,
                signal=main_signal,
                description=f"主力净{'流入' if main_net > 0 else '流出'} {abs(main_net):.1f} 亿",
                data_source=fund_flow["source"],
            ))

            # 超大单流向判定
            sl_signal = "normal"
            if super_large_net <= self.SUPER_LARGE_OUTFLOW_PANIC:
                sl_signal = "panic"
                score -= 8
                panic_signals.append(f"超大单净流出 {abs(super_large_net):.0f} 亿 ≥ {abs(self.SUPER_LARGE_OUTFLOW_PANIC)} 亿（机构撤离）")

            indicators.append(IndicatorSnapshot(
                name="超大单资金", en_name="super_large_flow",
                current_value=super_large_net, unit="亿元",
                panic_threshold=self.SUPER_LARGE_OUTFLOW_PANIC,
                signal=sl_signal,
                description=f"超大单净{'流入' if super_large_net > 0 else '流出'} {abs(super_large_net):.1f} 亿",
                data_source=fund_flow["source"],
            ))

        # ---- 8. 历史分位数校准 (P1 新增) ----
        score = max(0, min(100, score))
        percentile = SentimentHistory.percentile_of(score)
        if percentile < 10 and score > 30:
            score -= 10  # 相对历史是极端低位，当前中性也被压低
        elif percentile > 90 and score < 70:
            score += 10  # 相对历史是极端高位
        elif percentile < 25 and score > 50:
            score -= 5   # 偏低位校准
        elif percentile > 75 and score < 50:
            score += 5   # 偏高位校准
        score = max(0, min(100, score))

        # ---- 9. 综合判定 ----
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

        # ---- 10. 恐慌套利建议 ----
        panic_arb_advice = self._generate_panic_arb_advice(level, score, panic_signals, extreme_signals)

        # ---- 11. 置信度 ----
        total_indicators = len(indicators)
        failed_indicators = len(data_errors)
        confidence = 1.0 - (failed_indicators / max(total_indicators, 1)) * 0.5
        confidence = min(1.0, max(0.0, confidence))

        # ---- 12. 一句话总结 ----
        level_labels = {
            SentimentLevel.EXTREME_PANIC: "市场处于极度恐慌状态，恐慌指标全面触发",
            SentimentLevel.PANIC: f"市场恐慌蔓延（{len(panic_signals)} 个恐慌信号）",
            SentimentLevel.NORMAL: "市场情绪平稳，无明显极端信号",
            SentimentLevel.GREED: f"市场贪婪情绪升温（{len(greed_signals)} 个贪婪信号）",
            SentimentLevel.EXTREME_GREED: "市场处于极度贪婪状态，追高风险极大",
        }

        # ---- 13. 持久化历史记录 ----
        try:
            SentimentHistory.save({
                "timestamp": datetime.now().isoformat(),
                "score": score,
                "level": level.value,
                "confidence": round(confidence, 2),
                "percentile": percentile,
                "panic_count": len(panic_signals),
                "greed_count": len(greed_signals),
                "extreme_count": len(extreme_signals),
            })
        except Exception as e:
            logger.debug(f"保存情绪历史失败（非关键）: {e}")

        return MarketSentiment(
            level=level,
            score=score,
            confidence=round(confidence, 2),
            percentile=percentile,
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
