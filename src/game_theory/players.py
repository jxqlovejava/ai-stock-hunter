# -*- coding: utf-8 -*-
"""核心玩家画像（原则 4a）。

六类核心参与者: 国家队、公募/私募、游资、量化、北向资金、散户
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class PlayerType(str, Enum):
    NATIONAL_TEAM = "national_team"
    INSTITUTIONAL = "institutional"
    HOT_MONEY = "hot_money"
    QUANT = "quant"
    NORTHBOUND = "northbound"
    RETAIL = "retail"
    MANIPULATOR = "manipulator"


@dataclass
class PlayerProfile:
    """核心玩家画像。"""
    type: PlayerType
    name: str
    avg_capital_scale: str
    holding_period: str
    signature_patterns: list[str]
    data_sources: list[str]


PLAYER_PROFILES: list[PlayerProfile] = [
    PlayerProfile(
        type=PlayerType.NATIONAL_TEAM,
        name="国家队 (汇金/证金/社保/养老金)",
        avg_capital_scale="万亿级",
        holding_period="年级",
        signature_patterns=[
            "大盘暴跌时增持银行/蓝筹 ETF",
            "沪深300 ETF 成交量异常放大",
            "通常不卖——买入即长期持有",
            "买入信号通过公告滞后确认",
        ],
        data_sources=["季报披露", "ETF 份额变化", "中央汇金公告"],
    ),
    PlayerProfile(
        type=PlayerType.INSTITUTIONAL,
        name="公募/私募/保险",
        avg_capital_scale="百亿-千亿级",
        holding_period="季度-年级",
        signature_patterns=[
            "季度末调仓——同质化配置推升重仓股",
            "卖方一致推荐→公募集中配置→抱团推升→瓦解踩踏",
            "业绩排名压力→年底冲刺/年初调仓",
        ],
        data_sources=["基金季报", "仓位测算", "卖方一致预期"],
    ),
    PlayerProfile(
        type=PlayerType.HOT_MONEY,
        name="游资/涨停板敢死队",
        avg_capital_scale="千万-亿级",
        holding_period="日-周级",
        signature_patterns=[
            "小盘股涨停封板（流通市值 < 50 亿）",
            "涨停板接力——T 日封板→T+1 高开→连板 3-5→出货",
            "利用 T+1 制造流动性陷阱割散户",
        ],
        data_sources=["龙虎榜", "涨停板数据", "营业部追踪"],
    ),
    PlayerProfile(
        type=PlayerType.QUANT,
        name="量化/程序化交易",
        avg_capital_scale="百亿级",
        holding_period="分钟-日级",
        signature_patterns=[
            "高频交易——捕捉价差和流动性溢价",
            "ETF 申赎套利——利用 IOPV 与市价偏差",
            "统计套利——配对交易/期现套利",
        ],
        data_sources=["成交量异常", "程序化交易占比", "ETF 折溢价"],
    ),
    PlayerProfile(
        type=PlayerType.NORTHBOUND,
        name="北向资金 (外资)",
        avg_capital_scale="万亿级(累计)",
        holding_period="月-年级",
        signature_patterns=[
            "偏好消费/金融/新能源龙头",
            "连续净流入/流出是 A 股大盘方向领先指标",
            "对全球流动性敏感——Fed 加息周期流出",
        ],
        data_sources=["沪深股通每日数据", "持股明细"],
    ),
    PlayerProfile(
        type=PlayerType.RETAIL,
        name="散户 (对照基准)",
        avg_capital_scale="万-百万级",
        holding_period="日-周级",
        signature_patterns=[
            "追涨杀跌——在上涨后期追入、下跌初期割肉",
            "过度交易——换手率远超机构",
            "处置效应——盈利早卖、亏损死扛",
        ],
        data_sources=["开户数", "银证转账", "融资余额变化"],
    ),
    PlayerProfile(
        type=PlayerType.MANIPULATOR,
        name="庄家 (市场操纵者)",
        avg_capital_scale="亿-十亿级",
        holding_period="周-月级",
        signature_patterns=[
            "利用拖拉机账户分散持仓规避监管",
            "对倒交易制造虚假量价信号吸引跟风盘",
            "利用信息优势提前布局，借利好出货",
            "尾盘/集合竞价操纵收盘价影响技术指标",
            "目标标的: 流通市值 < 30 亿的小盘冷门股",
            "分时图出现钓鱼线/一字断魂刀等经典出货形态",
        ],
        data_sources=["分时量价异常检测", "龙虎榜联动席位分析", "大宗交易折溢价异常", "股东户数骤变"],
    ),
]
