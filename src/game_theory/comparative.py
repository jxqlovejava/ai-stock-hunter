# -*- coding: utf-8 -*-
"""跨市场对比（原则 2）。

A 股 vs 美股 vs 港股的制度差异 + 大资金/小资金不对等分析。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MarketComparison:
    """单维度跨市场对比。"""
    dimension: str
    a_share: str
    us_market: str
    hk_market: str
    impact_on_small_cap: str
    impact_on_large_cap: str
    verdict: str  # "为谁服务"判断


MARKET_COMPARISONS: list[MarketComparison] = [
    MarketComparison(
        dimension="交易制度",
        a_share="T+1 交割（A 股），部分 ETF/可转债 T+0",
        us_market="T+0（日内回转交易）",
        hk_market="T+0",
        impact_on_small_cap="A 股 T+1 下散户无法日内止损，放大亏损",
        impact_on_large_cap="机构可通过 ETF T+0 变相日内交易",
        verdict="大资金占优——可绕开 T+1 限制",
    ),
    MarketComparison(
        dimension="涨跌幅限制",
        a_share="±10%（主板）/ ±20%（科创/创业板）",
        us_market="无涨跌幅限制（有熔断机制）",
        hk_market="无涨跌幅限制",
        impact_on_small_cap="涨跌停板下散户追涨停被锁",
        impact_on_large_cap="游资利用涨跌停制造封板效应收割散户",
        verdict="游资占优——利用制度制造陷阱",
    ),
    MarketComparison(
        dimension="做空机制",
        a_share="融券券源极少，做空成本极高",
        us_market="完善的做空机制（个股期权/期货/融券）",
        hk_market="可做空（融券+衍生品）",
        impact_on_small_cap="散户无法做空对冲",
        impact_on_large_cap="机构通过收益互换/场外期权变相做空",
        verdict="大资金占优——唯一能做空的群体",
    ),
    MarketComparison(
        dimension="退市制度",
        a_share="退市率极低（< 1%/年），壳价值支撑",
        us_market="退市率高（5-8%/年），优胜劣汰",
        hk_market="退市中等（2-3%/年）",
        impact_on_small_cap="A 股垃圾股有壳价值托底，散户可能误判风险",
        impact_on_large_cap="壳价值不影响大市值标的",
        verdict="散户错觉保护——实际在赌壳",
    ),
    MarketComparison(
        dimension="信息披露",
        a_share="处罚力度弱于美股，内幕交易普遍",
        us_market="SEC 执法严格，集体诉讼机制完善",
        hk_market="介于两者之间",
        impact_on_small_cap="散户更依赖公开信息但信息质量差",
        impact_on_large_cap="机构有调研优势和草根数据",
        verdict="机构占优——信息不对称更严重",
    ),
    MarketComparison(
        dimension="政府干预",
        a_share="国家队直接入市（约 3-5% 市值），政策影响强",
        us_market="美联储间接影响，极少直接入市",
        hk_market="港府入市罕见（1998 年金融保卫战为特例）",
        impact_on_small_cap="国家队不买小盘股——危机中无托底",
        impact_on_large_cap="国家队买入即信号——可跟风获利",
        verdict="大资金（跟随国家队）占优",
    ),
    MarketComparison(
        dimension="IPO 定价",
        a_share="23 倍 PE 隐形上限→打新稳赚",
        us_market="市场化定价，破发常见",
        hk_market="市场化定价",
        impact_on_small_cap="散户打新中签率极低（0.01%）",
        impact_on_large_cap="机构配售比例远超散户",
        verdict="机构占优——拿走了绝大部分打新收益",
    ),
    MarketComparison(
        dimension="外资准入",
        a_share="沪深股通额度管理，部分标的受限",
        us_market="完全开放",
        hk_market="完全开放",
        impact_on_small_cap="外资不买的小盘股缺少定价锚",
        impact_on_large_cap="外资定价权对蓝筹影响显著",
        verdict="大资金（外资+跟随者）占优",
    ),
]


def compare_markets() -> list[MarketComparison]:
    """返回 8 维度的跨市场对比。"""
    return MARKET_COMPARISONS


def asymmetry_report(capital_size: float) -> str:
    """根据投资者资金量输出不对等分析。

    Args:
        capital_size: 投资者资金量（万元）
    """
    if capital_size < 50:
        return "小额资金（< 50万）：在 T+1、打新、融券、信息获取上均处于劣势。建议以指数 ETF 为主，减少个股操作。"
    elif capital_size < 500:
        return "中等资金（50-500万）：可参与打新和两融，但仍无法做空。T+1 下注意仓位管理。"
    elif capital_size < 5000:
        return "大中资金（500-5000万）：可充分利用 ETF T+0、两融、大宗交易等工具缩小不对等。"
    else:
        return "大资金（> 5000万）：在制度和工具上占全面优势，需注意市场冲击成本。"
