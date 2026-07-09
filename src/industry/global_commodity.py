# -*- coding: utf-8 -*-
"""全球大宗商品供需分析 (Step 7)。

针对全球定价的大宗商品行业（有色金属/石油石化/煤炭/钢铁/基础化工）：
  - 海外矿山/油田产能跟踪
  - 海外龙头对标 (yfinance best-effort)
  - 全球成本曲线排序
  - 地缘政治风险矩阵
  - 需求端分地区拆解 (EV/储能/消费电子/...)

对国内定价行业（白酒/水泥/地产等）直接跳过，零开销。
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 行业门控
# ---------------------------------------------------------------------------

# 全球定价大宗商品 → 申万一级行业映射
GLOBAL_COMMODITY_INDUSTRIES: set[str] = {
    "有色金属", "石油石化", "煤炭", "钢铁", "基础化工",
}

# 申万一级 → 商品类型
SECTOR_TO_COMMODITY: dict[str, str] = {
    "有色金属": "有色金属",
    "石油石化": "原油",
    "煤炭": "煤炭",
    "钢铁": "钢铁",
    "基础化工": "石化产品",
}


def is_global_commodity_industry(sector_name: str) -> bool:
    """判断行业是否需要全球供需分析。"""
    return sector_name in GLOBAL_COMMODITY_INDUSTRIES


def get_commodity_type(sector_name: str) -> str:
    """获取行业对应的商品类型。"""
    return SECTOR_TO_COMMODITY.get(sector_name, "未知")


# ---------------------------------------------------------------------------
# 全球大宗商品配置（硬编码 + yfinance best-effort）
# ---------------------------------------------------------------------------

GLOBAL_COMMODITY_CONFIG: dict = {
    "有色金属": {
        "sub_commodities": {
            "lithium": {
                "display_name": "锂",
                "overseas_assets": [
                    {
                        "name": "Greenbushes",
                        "country": "澳大利亚",
                        "type": "硬岩锂辉石",
                        "capacity": "~150kt LCE/年",
                        "owner": "天齐锂业(51%) / IGO(49%)，ALB 包销",
                        "cost_position": "低成本 ( Tier 1 )",
                        "expansion": "CGP3 扩产中，目标 ~200kt LCE",
                    },
                    {
                        "name": "Atacama 盐湖",
                        "country": "智利",
                        "type": "盐湖卤水",
                        "capacity": "~200kt LCE/年",
                        "owner": "SQM / ALB (各占一部分)",
                        "cost_position": "极低成本 ( Tier 0 )",
                        "expansion": "SQM 扩产至 ~210kt，2030 年特许权到期",
                    },
                    {
                        "name": "Cauchari-Olaroz",
                        "country": "阿根廷",
                        "type": "盐湖卤水",
                        "capacity": "~40kt LCE/年 (爬坡中)",
                        "owner": "赣锋锂业(46.7%) / Lithium Americas",
                        "cost_position": "中低成本",
                        "expansion": "二期扩产至 ~60kt，产能爬坡中",
                    },
                    {
                        "name": "Pilgangoora",
                        "country": "澳大利亚",
                        "type": "硬岩锂辉石",
                        "capacity": "~80kt LCE/年",
                        "owner": "Pilbara Minerals (ASX: PLS)",
                        "cost_position": "中等成本",
                        "expansion": "P680/P1000 项目扩产中",
                    },
                    {
                        "name": "Goulamina",
                        "country": "马里",
                        "type": "硬岩锂辉石",
                        "capacity": "~50kt LCE/年 (一期)",
                        "owner": "赣锋锂业(50%) / Leo Lithium",
                        "cost_position": "中等成本",
                        "expansion": "二期规划中，非洲物流成本偏高",
                    },
                    {
                        "name": "Manono",
                        "country": "刚果(金)",
                        "type": "硬岩锂辉石",
                        "capacity": "~70kt LCE/年 (规划)",
                        "owner": "AVZ Minerals / 紫金矿业(15%)",
                        "cost_position": "低成本但地缘风险极高",
                        "expansion": "矿权纠纷未解决，投产时间不确定",
                    },
                    {
                        "name": "Mt Marion / Wodgina",
                        "country": "澳大利亚",
                        "type": "硬岩锂辉石",
                        "capacity": "合计 ~100kt LCE/年",
                        "owner": "Mineral Resources / 赣锋锂业(Mt Marion 50%)",
                        "cost_position": "中等偏高成本",
                        "expansion": "Wodgina 三条产线，当前仅开一条",
                    },
                ],
                "overseas_peers": [
                    {"ticker": "ALB", "name": "Albemarle", "country": "美国", "role": "全球最大锂盐厂"},
                    {"ticker": "SQM", "name": "Sociedad Química y Minera", "country": "智利", "role": "全球第二大，盐湖提锂成本最低"},
                    {"ticker": "PLS.AX", "name": "Pilbara Minerals", "country": "澳大利亚", "role": "锂精矿拍卖价风向标"},
                    {"ticker": "LTM.N", "name": "Arcadium Lithium", "country": "美国/阿根廷", "role": "Livent+Allkem 合并，全球第四"},
                ],
                "cost_curve": [
                    {"tier": "Tier 0 (极低成本 <$4,000/t)", "producers": "Atacama 盐湖 (SQM/ALB)", "share_of_global": "~20%"},
                    {"tier": "Tier 1 (低成本 $4,000-$6,000/t)", "producers": "Greenbushes, Cauchari, 部分澳洲矿山", "share_of_global": "~25%"},
                    {"tier": "Tier 2 (中等成本 $6,000-$10,000/t)", "producers": "Pilgangoora, Mt Marion, Goulamina, 中国盐湖", "share_of_global": "~30%"},
                    {"tier": "Tier 3 (高成本 >$10,000/t)", "producers": "江西锂云母 (宁德/国轩), 非洲手工矿, Wodgina", "share_of_global": "~25%"},
                ],
                "geopolitical_risks": [
                    {"risk": "智利锂资源国有化", "level": "HIGH", "detail": "SQM 特许权 2030 到期，智利政府推进国家锂业公司(Codelco)控股", "affected": "SQM, ALB"},
                    {"risk": "加拿大限制中资锂企", "level": "HIGH", "detail": "加拿大要求中资剥离锂矿资产(中矿/藏格/盛新)，已执行", "affected": "中矿资源, 藏格矿业, 盛新锂能"},
                    {"risk": "美国 IRA FEOC 条款", "level": "MEDIUM", "detail": "EV 补贴要求锂来源不来自 FEOC(中国等)，影响中国锂企对美出口", "affected": "赣锋锂业, 天齐锂业"},
                    {"risk": "非洲矿业政策不确定性", "level": "MEDIUM", "detail": "马里/津巴布韦/刚果(金)矿业税和出口管制政策不稳定", "affected": "赣锋锂业(Goulamina), 中矿资源, 华友钴业"},
                    {"risk": "澳洲外资审查 (FIRB)", "level": "LOW", "detail": "中资在澳洲锂矿收购审批趋严但存量项目影响有限", "affected": "天齐锂业(Greenbushes)"},
                ],
                "demand_drivers": {
                    "EV 动力电池": 0.55,
                    "储能 (ESS)": 0.25,
                    "消费电子": 0.12,
                    "其他 (玻璃/陶瓷/润滑脂)": 0.08,
                },
                "pricing": {
                    "domestic_futures": "广州期货交易所 LC (碳酸锂)",
                    "overseas_spot": "Fastmarkets / Platts 锂精矿现货",
                    "auction": "Pilbara Minerals BMX 拍卖 (锂精矿价格领先指标)",
                    "contract": "长协价 (季度定价) vs 现货价",
                },
            },
            "copper": {
                "display_name": "铜",
                "overseas_assets": [],
                "overseas_peers": [],
                "cost_curve": [],
                "geopolitical_risks": [],
                "demand_drivers": {},
            },
            "rare_earth": {
                "display_name": "稀土",
                "overseas_assets": [],
                "overseas_peers": [],
                "cost_curve": [],
                "geopolitical_risks": [],
                "demand_drivers": {},
            },
        },
    },
    "石油石化": {
        "sub_commodities": {
            "crude_oil": {
                "display_name": "原油",
                "overseas_assets": [],
                "overseas_peers": [],
                "cost_curve": [],
                "geopolitical_risks": [],
                "demand_drivers": {},
            },
        },
    },
    "煤炭": {
        "sub_commodities": {
            "coal": {
                "display_name": "动力煤/焦煤",
                "overseas_assets": [],
                "overseas_peers": [],
                "cost_curve": [],
                "geopolitical_risks": [],
                "demand_drivers": {},
            },
        },
    },
    "钢铁": {
        "sub_commodities": {
            "steel": {
                "display_name": "钢铁",
                "overseas_assets": [],
                "overseas_peers": [],
                "cost_curve": [],
                "geopolitical_risks": [],
                "demand_drivers": {},
            },
        },
    },
    "基础化工": {
        "sub_commodities": {
            "petrochemical": {
                "display_name": "石化产品",
                "overseas_assets": [],
                "overseas_peers": [],
                "cost_curve": [],
                "geopolitical_risks": [],
                "demand_drivers": {},
            },
        },
    },
}


# ---------------------------------------------------------------------------
# GlobalCommodityAnalyzer
# ---------------------------------------------------------------------------


class GlobalCommodityAnalyzer:
    """全球大宗商品供需分析器。

    对全球定价大宗商品行业进行:
      1. 海外矿山/产能数据
      2. 海外龙头对标 (yfinance best-effort)
      3. 全球成本曲线排序
      4. 地缘政治风险矩阵
      5. 需求端分地区/分应用拆解

    yfinance 失败时降级为硬编码配置数据，标注 [DATA_GAP]。
    """

    def __init__(self):
        self._yf_available = self._check_yfinance()

    @staticmethod
    def _check_yfinance() -> bool:
        """检查 yfinance 是否可用。"""
        try:
            import yfinance  # noqa: F401
            return True
        except ImportError:
            logger.debug("yfinance 未安装，全球对标价格数据不可用")
            return False

    def analyze(self, sector_name: str) -> dict:
        """对行业进行全球供需分析。

        Args:
            sector_name: 申万一级行业名称

        Returns:
            dict 包含 enabled, commodity_type, config, peer_prices(可选), data_quality
        """
        if not is_global_commodity_industry(sector_name):
            return {
                "enabled": False,
                "reason": f"{sector_name} 非全球定价大宗商品行业，跳过 Step 7",
                "data_quality": {
                    "source_tier": "",
                    "confidence": 1.0,
                    "freshness_hours": 0,
                },
            }

        commodity_type = get_commodity_type(sector_name)
        config = GLOBAL_COMMODITY_CONFIG.get(sector_name, {})
        sub_commodities = config.get("sub_commodities", {})
        # 先处理完善度最高的子商品
        detailed = {
            k: v for k, v in sub_commodities.items()
            if v.get("overseas_assets") or v.get("overseas_peers")
        }
        skeleton = {
            k: v for k, v in sub_commodities.items()
            if not v.get("overseas_assets") and not v.get("overseas_peers")
        }

        # 尝试拉取海外对标价格
        peer_prices = {}
        yf_errors = []
        all_peers: list[dict] = []
        for sub_name, sub_data in detailed.items():
            for peer in sub_data.get("overseas_peers", []):
                all_peers.append(peer)

        if self._yf_available and all_peers:
            peer_prices, yf_errors = self._fetch_peer_prices(all_peers)

        data_quality = {
            "source_tier": "T2",
            "nature": "interpretation",
            "confidence": 0.65,
            "freshness_hours": 168,  # 一周
        }

        if yf_errors:
            data_quality["confidence"] = max(0.45, data_quality["confidence"] - 0.10)
            data_quality["gaps"] = [f"yfinance 拉取失败: {t}" for t in yf_errors]
        if skeleton:
            data_quality["confidence"] = max(0.40, data_quality["confidence"] - 0.10)
            data_quality["warnings"] = [
                f"以下子商品仅有骨架，待完善: {', '.join(skeleton.keys())}"
            ]

        return {
            "enabled": True,
            "commodity_type": commodity_type,
            "detailed_commodities": detailed,
            "skeleton_commodities": list(skeleton.keys()) if skeleton else [],
            "peer_prices": peer_prices,
            "yf_errors": yf_errors,
            "data_quality": data_quality,
        }

    def _fetch_peer_prices(self, peers: list[dict]) -> tuple[dict, list[str]]:
        """通过 yfinance 拉取海外对标股价和估值。

        Returns:
            ({ticker: {price, change_pct, pe_ttm, pb, mcap}}, [error_messages])
        """
        errors: list[str] = []
        prices: dict = {}
        try:
            import yfinance as yf

            tickers = [p["ticker"] for p in peers]
            # 批量拉取
            data = yf.download(
                tickers,
                period="5d",
                progress=False,
                auto_adjust=True,
            )
            for peer in peers:
                t = peer["ticker"]
                try:
                    ticker_obj = yf.Ticker(t)
                    info = ticker_obj.info or {}
                    close_series = data.get("Close", {}).get(t, None)
                    if close_series is not None and not close_series.empty:
                        latest = float(close_series.dropna().iloc[-1])
                    else:
                        latest = info.get("currentPrice") or info.get("regularMarketPrice") or 0

                    prices[t] = {
                        "name": peer["name"],
                        "country": peer["country"],
                        "price": round(latest, 2) if latest else None,
                        "currency": info.get("currency", "USD"),
                        "pe_ttm": info.get("trailingPE"),
                        "pb": info.get("priceToBook"),
                        "mcap": info.get("marketCap"),
                    }
                except Exception as e:
                    errors.append(f"{t}: {e}")
                    prices[t] = {
                        "name": peer["name"],
                        "country": peer["country"],
                        "error": str(e)[:200],
                    }
        except Exception as e:
            errors.append(f"yfinance import/connect: {e}")

        return prices, errors

    def analyze_for_symbol(
        self,
        symbol: str,
        sector_name: str,
        supply_chain_data: dict | None = None,
    ) -> dict:
        """对特定标的做全球供需叠加分析。

        结合 supply_chain.py 的瓶颈分类，对个股在全球供需中的位置做评估。
        """
        base = self.analyze(sector_name)
        if not base.get("enabled"):
            return base

        # 叠加个股在全球供需中的位置
        stock_position = {
            "symbol": symbol,
            "global_exposure": "unknown",
            "assessment": "",
        }

        # 从供应链数据判断全球敞口
        if supply_chain_data:
            node_name = supply_chain_data.get("node_name", "")
            bottleneck = supply_chain_data.get("bottleneck_score", 0)

            if "矿" in node_name or "盐" in node_name or "材料" in node_name:
                stock_position["global_exposure"] = "direct"
                stock_position["assessment"] = "直接受益/受损于全球商品价格波动"
            elif bottleneck >= 70:
                stock_position["global_exposure"] = "bottleneck_owner"
                stock_position["assessment"] = "掌握上游瓶颈，价格传导能力强"
            else:
                stock_position["global_exposure"] = "indirect"
                stock_position["assessment"] = "间接受到影响，传导系数较低"

        base["stock_position"] = stock_position
        return base
