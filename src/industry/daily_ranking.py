# -*- coding: utf-8 -*-
"""板块每日排行与热力图。

Adapted from DojoAgents dojoagents/dashboard/services/market_sector_lead.py

提供:
  - 申万一级行业涨跌排行
  - 板块热力图数据（涨跌矩阵）
  - 板块轮动检测（连续 N 日排行变化）

使用:
    from src.industry.daily_ranking import SectorRanking

    sr = SectorRanking()
    ranking = sr.rank_sectors(quotes)  # 当日排行
    heatmap = sr.heatmap_data(ranking)  # 热力图矩阵
    rotated = sr.detect_rotation(history)  # 轮动检测
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# 申万一级行业（28 个）供排行使用
SW1_SECTORS: list[str] = [
    "食品饮料", "银行", "医药生物", "电子", "计算机", "电力设备",
    "汽车", "家用电器", "机械设备", "基础化工", "有色金属", "煤炭",
    "钢铁", "建筑材料", "建筑装饰", "房地产", "农林牧渔", "纺织服饰",
    "轻工制造", "商贸零售", "社会服务", "交通运输", "公用事业", "环保",
    "国防军工", "通信", "传媒", "非银金融", "石油石化",
]


@dataclass(frozen=True)
class SectorRankItem:
    """单个板块排行条目。"""

    name: str           # 板块名称
    level: str = "L1"   # L1 / L2
    change_pct: float = 0.0        # 涨跌幅 %
    member_count: int = 0          # 成分股数量
    sample_tickers: list[str] = field(default_factory=list)  # 样本股
    rank: int = 0                  # 当日排名 (1 = 涨幅最大)
    prev_rank: int = 0             # 前一日排名
    direction: str = ""            # "up" / "down" / "flat"


@dataclass(frozen=True)
class SectorRankingResult:
    """板块排行结果。"""

    date: str
    items: list[SectorRankItem]
    top_gainers: list[SectorRankItem]      # 涨幅 Top 3
    top_losers: list[SectorRankItem]       # 跌幅 Top 3
    market_breadth: float = 0.0            # 上涨板块占比 0-1


@dataclass(frozen=True)
class HeatmapData:
    """热力图数据。"""

    date: str
    sectors: list[str]                     # 板块名列表 (行)
    periods: list[str]                     # 时间段标签 (列), 如 ["1d", "5d", "20d"]
    matrix: list[list[float]]              # [sector][period] 涨跌幅矩阵
    annotations: list[list[str]]           # 对应的格式化的标注文本


@dataclass(frozen=True)
class RotationSignal:
    """板块轮动信号。"""

    detected: bool
    description: str = ""
    leaders_changed: list[str] = field(default_factory=list)   # 新晋领先板块
    laggards_changed: list[str] = field(default_factory=list)   # 新晋落后板块
    rotation_score: float = 0.0  # 0-1, 越高越确定


class SectorRanking:
    """板块排行 + 热力图 + 轮动检测。

    用法:
        sr = SectorRanking()
        result = sr.rank(quotes={"食品饮料": 2.3, "银行": -1.2, ...})
        heatmap = sr.heatmap(result)
        rotation = sr.detect_rotation(history=[result_t, result_t1, result_t2])
    """

    def rank(self, quotes: dict[str, float], member_counts: Optional[dict[str, int]] = None) -> SectorRankingResult:
        """按当日涨跌幅对板块排行。

        Args:
            quotes: {板块名: 涨跌幅%}
            member_counts: {板块名: 成分股数}, 可选

        Returns:
            SectorRankingResult 含完整排行 + Top/Bottom 3
        """
        from datetime import date as dt_date

        pairs = [(name, pct) for name, pct in quotes.items()]
        pairs.sort(key=lambda x: x[1], reverse=True)

        total = len(pairs)
        gainers = sum(1 for _, pct in pairs if pct > 0)

        items: list[SectorRankItem] = []
        for rank, (name, pct) in enumerate(pairs, start=1):
            items.append(SectorRankItem(
                name=name,
                change_pct=round(pct, 2),
                member_count=member_counts.get(name, 0) if member_counts else 0,
                rank=rank,
                direction="up" if pct > 0 else ("down" if pct < 0 else "flat"),
            ))

        return SectorRankingResult(
            date=dt_date.today().isoformat(),
            items=items,
            top_gainers=items[:3] if len(items) >= 3 else items,
            top_losers=items[-3:][::-1] if len(items) >= 3 else items[::-1],
            market_breadth=round(gainers / total, 2) if total > 0 else 0.0,
        )

    def heatmap(self, result: SectorRankingResult) -> HeatmapData:
        """单日排行 → 热力图数据 (仅 1 日视图)。"""
        sectors = [item.name for item in result.items]
        values = [[item.change_pct] for item in result.items]
        annotations = [[f"{item.change_pct:+.1f}%" if item.change_pct != 0 else "0.0%"] for item in result.items]
        return HeatmapData(
            date=result.date,
            sectors=sectors,
            periods=["1d"],
            matrix=values,
            annotations=annotations,
        )

    def multi_period_heatmap(
        self,
        rankings: dict[str, SectorRankingResult],
    ) -> HeatmapData:
        """多时间段热力图。

        Args:
            rankings: {"1d": result_1d, "5d": result_5d, "20d": result_20d}

        Returns:
            HeatmapData 含多列矩阵
        """
        period_order = ["1d", "5d", "20d"]
        ordered = [(p, rankings[p]) for p in period_order if p in rankings]
        if not ordered:
            raise ValueError("至少提供一个时间段的数据")

        period_labels = [p for p, _ in ordered]
        # 用第一个有数据的日期的板块顺序
        ref_items = ordered[0][1].items
        sectors = [item.name for item in ref_items]
        name_to_idx = {name: i for i, name in enumerate(sectors)}

        matrix: list[list[float]] = [[0.0] * len(ordered) for _ in range(len(sectors))]
        annotations: list[list[str]] = [[""] * len(ordered) for _ in range(len(sectors))]

        for col_idx, (period_label, rank_result) in enumerate(ordered):
            for item in rank_result.items:
                row_idx = name_to_idx.get(item.name)
                if row_idx is not None:
                    matrix[row_idx][col_idx] = item.change_pct
                    annotations[row_idx][col_idx] = f"{item.change_pct:+.1f}%"

        return HeatmapData(
            date=ordered[0][1].date,
            sectors=sectors,
            periods=period_labels,
            matrix=matrix,
            annotations=annotations,
        )

    def detect_rotation(
        self,
        history: list[SectorRankingResult],
        threshold_rank_change: int = 5,
    ) -> RotationSignal:
        """检测板块轮动。

        Args:
            history: 按时间从早到晚排列的排行结果 (至少 2 个)
            threshold_rank_change: 排名变化超过此值视为"轮动"

        Returns:
            RotationSignal
        """
        if len(history) < 2:
            return RotationSignal(detected=False, description="数据不足，至少需要 2 天的排行数据")

        current = history[-1]
        previous = history[-2]

        prev_ranks: dict[str, int] = {item.name: item.rank for item in previous.items}
        leaders_changed: list[str] = []
        laggards_changed: list[str] = []

        total_movement = 0.0
        for item in current.items:
            prev_rank = prev_ranks.get(item.name, item.rank)
            rank_delta = abs(item.rank - prev_rank)
            total_movement += rank_delta

            if rank_delta >= threshold_rank_change:
                if item.rank <= 5:
                    leaders_changed.append(item.name)
                elif item.rank >= len(current.items) - 4:
                    laggards_changed.append(item.name)

        n_sectors = len(current.items)
        max_movement = n_sectors * n_sectors  # 理论最大
        rotation_score = round(min(total_movement / max_movement, 1.0), 2)

        detected = len(leaders_changed) >= 2 or len(laggards_changed) >= 2 or rotation_score > 0.3

        desc_parts: list[str] = []
        if leaders_changed:
            desc_parts.append(f"领先板块变动: {', '.join(leaders_changed)}")
        if laggards_changed:
            desc_parts.append(f"落后板块变动: {', '.join(laggards_changed)}")
        if not desc_parts:
            desc_parts.append("板块排名稳定，无明显轮动")

        return RotationSignal(
            detected=detected,
            description="; ".join(desc_parts),
            leaders_changed=leaders_changed,
            laggards_changed=laggards_changed,
            rotation_score=rotation_score,
        )

    def format_table(self, result: SectorRankingResult, top_n: int = 10) -> str:
        """格式化排行表格（适合终端输出）。"""
        lines = [f"📊 板块排行 — {result.date}", f"市场宽度: {result.market_breadth:.0%} 板块上涨", ""]
        lines.append(f"{'排名':<5} {'板块':<10} {'涨跌幅':>8} {'方向':<6}")
        lines.append("-" * 35)
        for item in result.items[:top_n]:
            arrow = "🔴" if item.direction == "up" else ("🟢" if item.direction == "down" else "⚪")
            lines.append(f"{item.rank:<5} {item.name:<10} {item.change_pct:>+7.2f}% {arrow:<6}")

        if result.top_gainers:
            lines.append("")
            lines.append(f"🏆 涨幅 Top 3: {', '.join(i.name for i in result.top_gainers)}")
        if result.top_losers:
            lines.append(f"📉 跌幅 Top 3: {', '.join(i.name for i in result.top_losers)}")
        return "\n".join(lines)

    def format_heatmap(self, heatmap: HeatmapData) -> str:
        """格式化热力图（纯文本，终端可用）。"""
        lines = [f"🔥 板块热力图 — {heatmap.date}", ""]
        header = f"{'板块':<10}" + "".join(f"{p:>8}" for p in heatmap.periods)
        lines.append(header)
        lines.append("-" * (10 + 8 * len(heatmap.periods)))
        for i, sector in enumerate(heatmap.sectors):
            values = "".join(f"{heatmap.annotations[i][j]:>8}" for j in range(len(heatmap.periods)))
            lines.append(f"{sector:<10}{values}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# 数据获取辅助
# ---------------------------------------------------------------------------
def fetch_sector_quotes_from_mootdx() -> dict[str, float]:
    """从 mootdx 获取申万一级行业实时涨跌幅。

    通过申万行业指数代码 (SW1_INDEX_MAP) 拉取标准行情，
    计算 (price - last_close) / last_close 作为涨跌幅。
    """
    try:
        from mootdx.quotes import Quotes
        from src.industry.classifier import SW1_INDEX_MAP

        codes = list(SW1_INDEX_MAP.values())
        code_to_name = {v: k for k, v in SW1_INDEX_MAP.items()}
        # 处理重复 code (综合=000833=电力设备, 保留第一个)
        seen_codes: set[str] = set()

        client = Quotes.factory(market="standard")
        data = client.quotes(symbol=codes)
        if data is None or data.empty:
            return {}

        result: dict[str, float] = {}
        for _, row in data.iterrows():
            code = str(row.get("code", ""))
            if code in seen_codes:
                continue
            name = code_to_name.get(code)
            if not name:
                continue
            seen_codes.add(code)

            price = float(row.get("price", 0) or 0)
            last_close = float(row.get("last_close", 0) or 0)
            if price > 0 and last_close > 0:
                pct = (price - last_close) / last_close * 100
                result[name] = round(pct, 2)

        return result
    except Exception as e:
        logger.warning("mootdx 板块数据获取失败: %s", e)

    return {}


def format_sector_flow_table(df: pd.DataFrame, top_n: int = 3) -> str:
    """把 AKShare 板块资金流向 DataFrame 格式化为紧凑 Top/Bottom 字符串。

    Args:
        df: AKShare `stock_sector_fund_flow_rank` 返回的 DataFrame。
        top_n: 取净流入/净流出各 N 个。

    Returns:
        多行字符串，适合终端直接打印；空数据时返回 DATA_GAP 提示。
    """
    if df is None or df.empty:
        return "  [DATA_GAP] 板块资金流向数据不可用"

    # 自动识别净流入净额列（今日/5日/10日前缀均可）
    net_col = None
    for col in df.columns:
        if "净流入" in str(col) and "净额" in str(col):
            net_col = col
            break
    if net_col is None:
        return "  [DATA_GAP] 板块资金流向列识别失败"

    name_col = "名称" if "名称" in df.columns else df.columns[0]

    def _to_yi(val) -> float:
        try:
            return float(val) / 10000  # 万元 -> 亿元
        except (ValueError, TypeError):
            return 0.0

    df = df.copy()
    df["_net_yi"] = df[net_col].apply(_to_yi)
    df_sorted = df.sort_values("_net_yi", ascending=False)

    top = df_sorted.head(top_n)
    # 排除已出现在净流入 Top N 中的板块，避免重叠
    remaining = df_sorted.iloc[top_n:] if len(df_sorted) > top_n else df_sorted.iloc[:0]
    bottom = remaining.tail(top_n).iloc[::-1]

    def _fmt(row) -> str:
        name = str(row.get(name_col, "")).strip()
        val = float(row.get("_net_yi", 0))
        return f"{name}({val:+.1f}亿)"

    lines = [
        f"  净流入 Top {top_n}: {', '.join(_fmt(r) for _, r in top.iterrows())}",
        f"  净流出 Top {top_n}: {', '.join(_fmt(r) for _, r in bottom.iterrows())}",
    ]
    return "\n".join(lines)
