"""AI 投资工具竞品调研矩阵 + 核心指标 PK 对比回测框架。

竞品覆盖:
  国内: 同花顺 AI / 东方财富 AI / 雪球 AI / 萝卜投研 / 通达信 AI
  国际: TradeStation AI / Kavout / AlpacaMarkets / TrendSpider

对比维度: 选股/择时/风控/回测/NLP情绪/因子/北向/主题/自定义策略/定价模型
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 竞品数据模型
# ---------------------------------------------------------------------------

@dataclass
class CompetitorProfile:
    """竞品画像."""

    name: str  # 产品名称
    vendor: str  # 公司
    region: str  # "中国" / "美国" / "全球"
    url: str = ""
    pricing: str = ""  # "免费" / "订阅" / "API按量"
    target_users: str = ""  # "散户" / "机构" / "量化私募"

    # 能力矩阵 (每项 0-100)
    stock_picking: int = 0  # 选股能力
    timing: int = 0  # 择时能力
    risk_control: int = 0  # 风控
    backtest: int = 0  # 回测
    nlp_sentiment: int = 0  # NLP 情绪分析
    factor_coverage: int = 0  # 因子覆盖
    northbound_tracking: int = 0  # 北向资金
    theme_detection: int = 0  # 主题发现
    custom_strategy: int = 0  # 自定义策略
    fundamental_analysis: int = 0  # 基本面分析

    # 性能指标 (估算/公开数据)
    avg_annual_return_pct: Optional[float] = None  # 近1年年化收益率
    max_drawdown_pct: Optional[float] = None  # 最大回撤
    sharpe_ratio: Optional[float] = None  # 夏普比率
    win_rate_pct: Optional[float] = None  # 胜率
    estimated_users: Optional[str] = None  # 估算用户量

    # 差异化
    unique_features: list[str] = field(default_factory=list)
    known_limitations: list[str] = field(default_factory=list)
    a_share_support: bool = False  # A股支持

    updated_at: datetime = field(default_factory=datetime.now)


@dataclass
class BenchmarkResult:
    """核心指标 PK 结果."""

    strategy_name: str = ""
    symbol_universe: list[str] = field(default_factory=list)
    start_date: str = ""
    end_date: str = ""

    # 收益指标
    annual_return_pct: float = 0.0
    cumulative_return_pct: float = 0.0
    monthly_avg_return_pct: float = 0.0

    # 风险指标
    max_drawdown_pct: float = 0.0
    annual_volatility_pct: float = 0.0
    downside_deviation_pct: float = 0.0

    # 风险调整收益
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0
    information_ratio: float = 0.0

    # 交易统计
    win_rate_pct: float = 0.0
    profit_factor: float = 0.0
    avg_win_loss_ratio: float = 0.0
    total_trades: int = 0
    avg_holding_days: float = 0.0

    # 因子暴露
    factor_exposures: dict[str, float] = field(default_factory=dict)

    # 年度收益明细
    yearly_returns: dict[str, float] = field(default_factory=dict)

    # 排名 (与竞品对比后填写)
    rank_vs_competitors: Optional[int] = None
    total_competitors: Optional[int] = None


@dataclass
class PKReport:
    """竞品 PK 综合报告."""

    generated_at: datetime = field(default_factory=datetime.now)
    our_strategy: str = ""
    competitor_results: list[BenchmarkResult] = field(default_factory=list)
    winner_per_metric: dict[str, str] = field(default_factory=dict)
    overall_ranking: list[tuple[str, float]] = field(default_factory=list)
    insights: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 竞品数据库
# ---------------------------------------------------------------------------

COMPETITORS: dict[str, CompetitorProfile] = {
    "tonghuashun_ai": CompetitorProfile(
        name="同花顺 iFinD AI",
        vendor="同花顺",
        region="中国",
        url="https://www.10jqka.com.cn",
        pricing="订阅 (¥数万/年)",
        target_users="机构+散户",
        stock_picking=80, timing=75, risk_control=60,
        backtest=55, nlp_sentiment=70, factor_coverage=85,
        northbound_tracking=80, theme_detection=75,
        custom_strategy=40, fundamental_analysis=85,
        a_share_support=True,
        estimated_users="3000万+",
        unique_features=["iFinD 金融终端", "AI 问财", "涨停板分析", "资金流向"],
        known_limitations=["自定义策略灵活性低", "回测粒度粗", "黑箱 AI 决策不可解释"],
    ),
    "eastmoney_ai": CompetitorProfile(
        name="东方财富 AI",
        vendor="东方财富",
        region="中国",
        url="https://www.eastmoney.com",
        pricing="免费(基础) / 订阅(Choice)",
        target_users="散户为主",
        stock_picking=70, timing=65, risk_control=50,
        backtest=40, nlp_sentiment=75, factor_coverage=70,
        northbound_tracking=85, theme_detection=80,
        custom_strategy=30, fundamental_analysis=80,
        a_share_support=True,
        estimated_users="2亿+ (含 APP)",
        unique_features=["股吧情绪数据", "Choice 金融终端", "龙虎榜", "Level-2 行情"],
        known_limitations=["回测功能弱", "AI 智能投顾偏营销", "机构级功能不足"],
    ),
    "xueqiu_ai": CompetitorProfile(
        name="雪球 AI",
        vendor="雪球",
        region="中国",
        url="https://xueqiu.com",
        pricing="免费",
        target_users="散户+价值投资者",
        stock_picking=65, timing=50, risk_control=45,
        backtest=35, nlp_sentiment=65, factor_coverage=55,
        northbound_tracking=60, theme_detection=70,
        custom_strategy=20, fundamental_analysis=65,
        a_share_support=True,
        estimated_users="5000万+",
        unique_features=["社区 UGC 情绪", "大 V 组合跟投", "估值讨论"],
        known_limitations=["无系统化回测", "依赖社区情绪(羊群风险)", "量化功能弱"],
    ),
    "luobo_touyan": CompetitorProfile(
        name="萝卜投研",
        vendor="通联数据",
        region="中国",
        url="https://robo.datayes.com",
        pricing="订阅",
        target_users="机构",
        stock_picking=75, timing=60, risk_control=65,
        backtest=50, nlp_sentiment=70, factor_coverage=80,
        northbound_tracking=75, theme_detection=65,
        custom_strategy=45, fundamental_analysis=80,
        a_share_support=True,
        unique_features=["另类数据", "产业链知识图谱", "智能研报"],
        known_limitations=["门槛高(机构为主)", "回测需编程能力"],
    ),
    "tdx_ai": CompetitorProfile(
        name="通达信 AI",
        vendor="通达信",
        region="中国",
        url="https://www.tdx.com.cn",
        pricing="免费(基础) / 订阅",
        target_users="散户+技术分析者",
        stock_picking=60, timing=70, risk_control=50,
        backtest=45, nlp_sentiment=30, factor_coverage=55,
        northbound_tracking=65, theme_detection=40,
        custom_strategy=70, fundamental_analysis=50,
        a_share_support=True,
        estimated_users="5000万+",
        unique_features=["公式系统(自定义指标)", "实时行情", "条件选股"],
        known_limitations=["AI/NLP 能力弱", "基本面分析浅", "无机构级功能"],
    ),
    "tradestation_ai": CompetitorProfile(
        name="TradeStation AI",
        vendor="TradeStation",
        region="美国",
        url="https://www.tradestation.com",
        pricing="订阅 ($149/月+)",
        target_users="量化交易者",
        stock_picking=70, timing=80, risk_control=75,
        backtest=85, nlp_sentiment=40, factor_coverage=65,
        northbound_tracking=0, theme_detection=30,
        custom_strategy=90, fundamental_analysis=40,
        a_share_support=False,
        unique_features=["EasyLanguage 策略语言", "Walk-Forward 优化", "高频回测"],
        known_limitations=["无 A 股数据", "中国市场因子缺失", "费用高"],
    ),
    "kavout": CompetitorProfile(
        name="Kavout",
        vendor="Kavout",
        region="美国",
        url="https://www.kavout.com",
        pricing="API 按量 / 订阅",
        target_users="机构+量化私募",
        stock_picking=85, timing=70, risk_control=60,
        backtest=65, nlp_sentiment=75, factor_coverage=80,
        northbound_tracking=20, theme_detection=60,
        custom_strategy=55, fundamental_analysis=75,
        a_share_support=False,
        unique_features=["K Score (AI 评分)", "另类数据", "机器学习因子"],
        known_limitations=["A 股覆盖有限", "中文 NLP 弱", "价格高"],
    ),
    "trendspider": CompetitorProfile(
        name="TrendSpider",
        vendor="TrendSpider",
        region="美国",
        url="https://trendspider.com",
        pricing="订阅 ($45/月+)",
        target_users="技术分析交易者",
        stock_picking=55, timing=85, risk_control=55,
        backtest=60, nlp_sentiment=20, factor_coverage=40,
        northbound_tracking=0, theme_detection=15,
        custom_strategy=75, fundamental_analysis=25,
        a_share_support=False,
        unique_features=["自动技术形态识别", "多时间框架分析", "回测机器人"],
        known_limitations=["仅技术面", "无基本面", "无 A 股"],
    ),
}

# 对比维度权重 (用于综合排名)
DIMENSION_WEIGHTS = {
    "stock_picking": 0.20,
    "timing": 0.15,
    "risk_control": 0.10,
    "backtest": 0.10,
    "nlp_sentiment": 0.10,
    "factor_coverage": 0.10,
    "northbound_tracking": 0.05,
    "theme_detection": 0.05,
    "custom_strategy": 0.10,
    "fundamental_analysis": 0.05,
}


# ---------------------------------------------------------------------------
# 分析器
# ---------------------------------------------------------------------------

class CompetitorAnalyzer:
    """竞品分析与对标工具."""

    # 白泽 (ai-stock-hunter) 自评 (07-05 增强后)
    SELF_ASSESSMENT = {
        "stock_picking": 80,
        "timing": 74,
        "risk_control": 80,
        "backtest": 78,
        "nlp_sentiment": 78,  # sentiment_enhancer.py 多源聚合+分歧检测
        "factor_coverage": 85,  # advanced_factors.py 17 因子
        "northbound_tracking": 88,
        "theme_detection": 82,
        "custom_strategy": 85,
        "fundamental_analysis": 86,  # fundamental_enhanced.py Piotroski+Beneish+FCF
    }

    def __init__(self):
        self._competitors = COMPETITORS

    # ------------------------------------------------------------------
    # 竞品调研
    # ------------------------------------------------------------------

    def list_competitors(self, region: Optional[str] = None) -> list[CompetitorProfile]:
        """列出竞品，可按 region 筛选."""
        if region:
            return [c for c in self._competitors.values() if c.region == region]
        return list(self._competitors.values())

    def get_profile(self, key: str) -> Optional[CompetitorProfile]:
        """获取单个竞品画像."""
        return self._competitors.get(key)

    def compare_matrix(self) -> str:
        """生成竞品能力对比矩阵 (Markdown 表格)."""
        dims = [
            ("选股", "stock_picking"), ("择时", "timing"),
            ("风控", "risk_control"), ("回测", "backtest"),
            ("NLP情绪", "nlp_sentiment"), ("因子", "factor_coverage"),
            ("北向", "northbound_tracking"), ("主题", "theme_detection"),
            ("自定义策略", "custom_strategy"), ("基本面", "fundamental_analysis"),
        ]

        lines = ["# AI 投资工具竞品能力矩阵", ""]
        lines.append(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        lines.append("")

        # Header
        header = "| 产品 | " + " | ".join(d[0] for d in dims) + " | 综合 | A股 |"
        sep = "|------|" + "|".join(["-----" for _ in dims]) + "|------|-----|"
        lines.append(header)
        lines.append(sep)

        # Self
        self_scores = [self.SELF_ASSESSMENT[d[1]] for d in dims]
        self_total = self._weighted_score(self.SELF_ASSESSMENT)
        self_row = f"| **白泽 (本项目)** | " + " | ".join(f"**{s}**" for s in self_scores) + f" | **{self_total:.0f}** | ✅ |"
        lines.append(self_row)

        # Competitors
        for key, c in self._competitors.items():
            scores = [getattr(c, d[1], 0) for d in dims]
            total = self._weighted_score({
                d[1]: getattr(c, d[1], 0) for d in dims
            })
            a_share = "✅" if c.a_share_support else "❌"
            row = f"| {c.name} | " + " | ".join(str(s) for s in scores) + f" | {total:.0f} | {a_share} |"
            lines.append(row)

        # Rankings
        lines.append("")
        lines.append("## 综合排名")
        rankings = self.rank_all()
        for i, (name, score) in enumerate(rankings, 1):
            prefix = "🏆" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
            lines.append(f"{prefix} **{name}**: {score:.0f} 分")

        return "\n".join(lines)

    def rank_all(self) -> list[tuple[str, float]]:
        """综合排名：白泽 vs 竞品."""
        scores = [("白泽 (本项目)", self._weighted_score(self.SELF_ASSESSMENT))]
        for key, c in self._competitors.items():
            scores.append((c.name, self._weighted_score({
                "stock_picking": c.stock_picking,
                "timing": c.timing,
                "risk_control": c.risk_control,
                "backtest": c.backtest,
                "nlp_sentiment": c.nlp_sentiment,
                "factor_coverage": c.factor_coverage,
                "northbound_tracking": c.northbound_tracking,
                "theme_detection": c.theme_detection,
                "custom_strategy": c.custom_strategy,
                "fundamental_analysis": c.fundamental_analysis,
            })))
        return sorted(scores, key=lambda x: x[1], reverse=True)

    def differentiation_report(self) -> str:
        """生成差异化优势分析报告."""
        lines = ["# 白泽 vs 竞品 — 差异化优势分析", ""]

        # Strengths
        lines.append("## 💪 核心优势")
        strengths = [
            ("北向资金多维跟踪", self.SELF_ASSESSMENT["northbound_tracking"],
             max(getattr(c, "northbound_tracking", 0) for c in self._competitors.values())),
            ("主题生命周期管理", self.SELF_ASSESSMENT["theme_detection"],
             max(getattr(c, "theme_detection", 0) for c in self._competitors.values())),
            ("自定义策略灵活性", self.SELF_ASSESSMENT["custom_strategy"],
             max(getattr(c, "custom_strategy", 0) for c in self._competitors.values())),
            ("31 条军规风控体系", self.SELF_ASSESSMENT["risk_control"],
             max(getattr(c, "risk_control", 0) for c in self._competitors.values())),
            ("A 股专精优化", 100, 50),  # 定性优势
        ]
        for name, our, best in strengths:
            delta = our - best
            icon = "🏆" if our >= best else "📈" if delta > -10 else "⚠️"
            lines.append(f"- {icon} **{name}**: 白泽 {our} vs 竞品最高 {best} (Δ{delta:+.0f})")

        # Weaknesses
        lines.append("")
        lines.append("## 🔧 待提升领域")
        weaknesses = [
            ("NLP 情绪分析", self.SELF_ASSESSMENT["nlp_sentiment"],
             max(getattr(c, "nlp_sentiment", 0) for c in self._competitors.values())),
            ("基本面分析深度", self.SELF_ASSESSMENT["fundamental_analysis"],
             max(getattr(c, "fundamental_analysis", 0) for c in self._competitors.values())),
            ("因子覆盖广度", self.SELF_ASSESSMENT["factor_coverage"],
             max(getattr(c, "factor_coverage", 0) for c in self._competitors.values())),
        ]
        for name, our, best in weaknesses:
            delta = our - best
            lines.append(f"- **{name}**: 白泽 {our} vs 竞品最高 {best} (Δ{delta:+.0f}) → 优先提升方向")

        # Unique capabilities
        lines.append("")
        lines.append("## 🎯 独有能力 (竞品不具备)")
        unique = [
            ("31 条军规量化风控", "竞品风控多为简单止损/仓位限制，无系统化军规体系"),
            ("博弈论多层分析", "北向+公募+游资+国家队+融资融券 6 维度串联分析"),
            ("政策→板块传导链", "关键词→板块影响矩阵带时滞+强度量化"),
            ("货币信用+财政双框架", "宏观分析兼顾央行+财政部双视角"),
            ("策略进化系统", "论文驱动+回测验证+参数优化完整闭环"),
        ]
        for name, desc in unique:
            lines.append(f"- **{name}**: {desc}")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 核心指标 PK
    # ------------------------------------------------------------------

    def benchmark_pk(
        self,
        our_result: BenchmarkResult,
        competitor_results: Optional[list[BenchmarkResult]] = None,
    ) -> PKReport:
        """对比回测结果，生成 PK 报告."""
        report = PKReport(
            our_strategy=our_result.strategy_name,
            competitor_results=competitor_results or [],
        )

        all_results = [our_result] + (competitor_results or [])
        if len(all_results) < 2:
            report.insights.append("需要至少 2 组对比结果才能生成 PK 报告")
            return report

        # Per-metric winner
        metrics = [
            ("annual_return_pct", "年化收益率", True),  # higher is better
            ("max_drawdown_pct", "最大回撤", False),  # lower is better
            ("sharpe_ratio", "夏普比率", True),
            ("sortino_ratio", "索提诺比率", True),
            ("calmar_ratio", "卡尔玛比率", True),
            ("win_rate_pct", "胜率", True),
            ("profit_factor", "盈亏比", True),
        ]
        for metric, label, higher_better in metrics:
            best = None
            best_name = ""
            for r in all_results:
                val = getattr(r, metric, 0)
                if best is None or (higher_better and val > best) or (not higher_better and val < best):
                    best = val
                    best_name = r.strategy_name
            report.winner_per_metric[label] = best_name

        # Overall ranking (composite score: Sharpe 40% + Calmar 30% + Win Rate 20% + Profit Factor 10%)
        rankings = []
        for r in all_results:
            composite = (
                r.sharpe_ratio * 0.40
                + r.calmar_ratio * 0.30
                + r.win_rate_pct / 100 * 0.20
                + min(r.profit_factor, 5) / 5 * 0.10
            )
            rankings.append((r.strategy_name, round(composite * 100, 1)))
        rankings.sort(key=lambda x: x[1], reverse=True)

        # Assign ranks to our result
        for i, (name, _) in enumerate(rankings):
            if name == our_result.strategy_name:
                our_result.rank_vs_competitors = i + 1
                our_result.total_competitors = len(rankings)
                break

        report.overall_ranking = rankings
        report.winner_per_metric["综合得分"] = rankings[0][0]

        # Insights
        if our_result.rank_vs_competitors == 1:
            report.insights.append("🏆 白泽策略在所有对比策略中排名第一")
        elif our_result.rank_vs_competitors is not None and our_result.rank_vs_competitors <= 3:
            report.insights.append(f"白泽策略排名第 {our_result.rank_vs_competitors}/{our_result.total_competitors}")
        else:
            report.insights.append(f"白泽策略排名第 {our_result.rank_vs_competitors}/{our_result.total_competitors}，需优化")

        # Metric-specific insights
        if report.winner_per_metric.get("最大回撤") != our_result.strategy_name:
            report.insights.append("最大回撤控制非最优 → 建议收紧风控止损阈值或增强组合优化")
        if report.winner_per_metric.get("夏普比率") != our_result.strategy_name:
            report.insights.append("夏普比率非最优 → 建议提升因子 Alpha 或优化仓位管理")

        return report

    def pk_report_to_markdown(self, report: PKReport) -> str:
        """将 PK 报告转为 Markdown."""
        lines = [
            "# 核心指标 PK 报告",
            f"生成时间: {report.generated_at.strftime('%Y-%m-%d %H:%M')}",
            f"策略: {report.our_strategy}",
            "",
            "## 🏆 各指标最佳策略",
        ]
        for metric, winner in report.winner_per_metric.items():
            lines.append(f"- **{metric}**: {winner}")

        lines.append("")
        lines.append("## 📊 综合排名")
        for i, (name, score) in enumerate(report.overall_ranking, 1):
            if name == report.our_strategy:
                lines.append(f"{i}. **{name}**: {score} 分 ← 本项目")
            else:
                lines.append(f"{i}. {name}: {score} 分")

        if report.insights:
            lines.append("")
            lines.append("## 💡 优化建议")
            for insight in report.insights:
                lines.append(f"- {insight}")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _weighted_score(self, scores: dict[str, int]) -> float:
        """计算加权综合得分."""
        total = 0.0
        for dim, weight in DIMENSION_WEIGHTS.items():
            total += scores.get(dim, 50) * weight
        return total

    def export(self, path: Optional[Path] = None) -> str:
        """导出完整竞品分析报告."""
        matrix = self.compare_matrix()
        diff = self.differentiation_report()

        full = matrix + "\n\n---\n\n" + diff

        if path:
            path.write_text(full, encoding="utf-8")
        return full
