# -*- coding: utf-8 -*-
"""模拟交易独立配置 — 初始从 portfolio.yaml 拷贝风格字段，账户字段独立维护。

复用策略:
  - "人"的属性: risk_profile, trading_style, holding_period, investment_goal,
    circle_of_competence, score_weights, benchmark → 初始拷贝，周/月复盘可独立调整
  - "账户"的属性: total_capital=200000, position_limits → 完全独立，不与主系统互扰
"""

from __future__ import annotations

import logging
import os
from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)

# 默认配置路径
DEFAULT_CONFIG_DIR = Path("data/paper_trading")
DEFAULT_CONFIG_PATH = DEFAULT_CONFIG_DIR / "config.yaml"
DEFAULT_WATCHLIST_PATH = DEFAULT_CONFIG_DIR / "watchlist.json"
PORTFOLIO_CONFIG_PATH = Path("data/portfolio.yaml")
MAIN_WATCHLIST_PATH = Path("data/watchlist.json")


# ══════════════════════════════════════════════════════════════════════
# 枚举 (复用主系统定义)
# ══════════════════════════════════════════════════════════════════════

class RiskProfile(str, Enum):
    CONSERVATIVE = "conservative"
    BALANCED = "balanced"
    AGGRESSIVE = "aggressive"


class InvestmentGoal(str, Enum):
    ABSOLUTE_RETURN = "absolute_return"
    RELATIVE_RETURN = "relative_return"
    CASH_FLOW = "cash_flow"


class TradingStyle(str, Enum):
    LONG_TERM = "long_term"
    SWING = "swing"
    SHORT_TERM = "short_term"
    MIXED = "mixed"


class HoldingPeriod(str, Enum):
    SHORT = "short"
    MEDIUM = "medium"
    LONG = "long"
    ULTRA_LONG = "ultra"


# ══════════════════════════════════════════════════════════════════════
# 数据模型
# ══════════════════════════════════════════════════════════════════════


@dataclass
class PositionLimits:
    """仓位约束 — 模拟交易独立账户。

    与主系统 portfolio.yaml 的 position_limits 结构相同但值独立。
    """
    total_capital: float = 200_000.0       # 总资金 20 万
    max_single_pct: float = 0.20           # 单票上限 20%
    max_sector_pct: float = 0.40           # 单行业上限 40%
    max_total_exposure: float = 0.80       # 总仓位上限 80%
    min_cash_pct: float = 0.20             # 最低现金 20%
    single_stop_loss_pct: float = 0.02     # 单笔止损 2%
    portfolio_drawdown_pct: float = 0.15   # 组合回撤熔断 15%
    max_total_loss_pct: float = 0.25       # 最大总亏损 25%
    gem_discount: float = 0.80             # 双创折扣
    kelly_fraction: float = 0.50           # 凯利分数
    breakeven_trigger_pct: float = 0.20    # 保本止损触发
    trailing_trigger_pct: float = 0.30     # 移动止盈触发

    def to_dict(self) -> dict:
        return {
            "total_capital": self.total_capital,
            "max_single_pct": self.max_single_pct,
            "max_sector_pct": self.max_sector_pct,
            "max_total_exposure": self.max_total_exposure,
            "min_cash_pct": self.min_cash_pct,
            "single_stop_loss_pct": self.single_stop_loss_pct,
            "portfolio_drawdown_pct": self.portfolio_drawdown_pct,
            "max_total_loss_pct": self.max_total_loss_pct,
            "gem_discount": self.gem_discount,
            "kelly_fraction": self.kelly_fraction,
            "breakeven_trigger_pct": self.breakeven_trigger_pct,
            "trailing_trigger_pct": self.trailing_trigger_pct,
        }

    @classmethod
    def from_dict(cls, d: dict) -> PositionLimits:
        return cls(
            total_capital=float(d.get("total_capital", 200_000)),
            max_single_pct=float(d.get("max_single_pct", 0.20)),
            max_sector_pct=float(d.get("max_sector_pct", 0.40)),
            max_total_exposure=float(d.get("max_total_exposure", 0.80)),
            min_cash_pct=float(d.get("min_cash_pct", 0.20)),
            single_stop_loss_pct=float(d.get("single_stop_loss_pct", 0.02)),
            portfolio_drawdown_pct=float(d.get("portfolio_drawdown_pct", 0.15)),
            max_total_loss_pct=float(d.get("max_total_loss_pct", 0.25)),
            gem_discount=float(d.get("gem_discount", 0.80)),
            kelly_fraction=float(d.get("kelly_fraction", 0.50)),
            breakeven_trigger_pct=float(d.get("breakeven_trigger_pct", 0.20)),
            trailing_trigger_pct=float(d.get("trailing_trigger_pct", 0.30)),
        )


@dataclass
class ScoreWeights:
    """裁决评分权重。"""
    fundamental: Optional[float] = None
    technical: Optional[float] = None
    macro: Optional[float] = None
    sector: Optional[float] = None
    sentiment: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "fundamental": self.fundamental,
            "technical": self.technical,
            "macro": self.macro,
            "sector": self.sector,
            "sentiment": self.sentiment,
        }

    @classmethod
    def from_dict(cls, d: dict | None) -> ScoreWeights:
        if d is None:
            return ScoreWeights()
        return cls(
            fundamental=d.get("fundamental"),
            technical=d.get("technical"),
            macro=d.get("macro"),
            sector=d.get("sector"),
            sentiment=d.get("sentiment"),
        )


@dataclass
class PaperTradingConfig:
    """模拟交易独立配置。

    初始从 portfolio.yaml 拷贝风格字段，账户字段独立设置。
    后续周/月复盘可调整此配置，不影响主系统。
    """

    # -- "人"的属性 (初始从 portfolio.yaml 拷贝) --
    risk_profile: RiskProfile = RiskProfile.BALANCED
    investment_goal: InvestmentGoal = InvestmentGoal.ABSOLUTE_RETURN
    trading_style: TradingStyle = TradingStyle.MIXED
    holding_period: HoldingPeriod = HoldingPeriod.LONG
    investment_horizon: str = "3-5年"
    benchmark: str = "沪深300"
    circle_of_competence: dict[str, int] = field(default_factory=dict)
    score_weights: ScoreWeights = field(default_factory=ScoreWeights)
    accessible_boards: list[str] = field(default_factory=lambda: ["main_sh", "main_sz"])

    # -- "账户"的属性 (独立，不与主系统互扰) --
    position_limits: PositionLimits = field(default_factory=PositionLimits)

    # -- 元数据 --
    created_at: str = ""
    last_updated: str = ""

    def to_dict(self) -> dict:
        return {
            "risk_profile": self.risk_profile.value,
            "investment_goal": self.investment_goal.value,
            "trading_style": self.trading_style.value,
            "holding_period": self.holding_period.value,
            "investment_horizon": self.investment_horizon,
            "benchmark": self.benchmark,
            "circle_of_competence": dict(self.circle_of_competence),
            "score_weights": self.score_weights.to_dict(),
            "accessible_boards": list(self.accessible_boards),
            "position_limits": self.position_limits.to_dict(),
            "created_at": self.created_at,
            "last_updated": self.last_updated,
        }

    @classmethod
    def from_dict(cls, d: dict) -> PaperTradingConfig:
        def _enum(cls_enum, val):
            try:
                return cls_enum(val)
            except (ValueError, TypeError):
                return list(cls_enum)[0]

        return cls(
            risk_profile=_enum(RiskProfile, d.get("risk_profile", "balanced")),
            investment_goal=_enum(InvestmentGoal, d.get("investment_goal", "absolute_return")),
            trading_style=_enum(TradingStyle, d.get("trading_style", "mixed")),
            holding_period=_enum(HoldingPeriod, d.get("holding_period", "long")),
            investment_horizon=str(d.get("investment_horizon", "3-5年")),
            benchmark=str(d.get("benchmark", "沪深300")),
            circle_of_competence=dict(d.get("circle_of_competence", {})),
            score_weights=ScoreWeights.from_dict(d.get("score_weights")),
            accessible_boards=list(d.get("accessible_boards", ["main_sh", "main_sz"])),
            position_limits=PositionLimits.from_dict(d.get("position_limits", {})),
            created_at=str(d.get("created_at", "")),
            last_updated=str(d.get("last_updated", "")),
        )


# ══════════════════════════════════════════════════════════════════════
# 配置管理器
# ══════════════════════════════════════════════════════════════════════


class PaperTradingConfigManager:
    """模拟交易配置管理器。

    职责:
      1. 首次启动时从 portfolio.yaml 拷贝风格字段，账户字段独立初始化
      2. 后续从独立 config.yaml 加载
      3. 保存/更新配置

    用法:
        mgr = PaperTradingConfigManager()
        config = mgr.load_or_initialize()
        # ... 运行模拟交易 ...
        config.position_limits.total_capital = 195000  # 亏损后更新
        mgr.save(config)
    """

    def __init__(self, config_path: Path | None = None):
        self._path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH

    @property
    def path(self) -> Path:
        return self._path.resolve()

    # ------------------------------------------------------------------
    # 加载 / 初始化
    # ------------------------------------------------------------------

    def load_or_initialize(self) -> PaperTradingConfig:
        """加载配置；首次启动时从 portfolio.yaml 拷贝风格字段并初始化独立账户。"""
        if self._path.exists():
            return self._load()
        return self._initialize()

    def _load(self) -> PaperTradingConfig:
        """从独立配置文件加载。"""
        try:
            raw = yaml.safe_load(self._path.read_text(encoding="utf-8"))
            if raw is None:
                logger.warning("配置文件为空，重新初始化")
                return self._initialize()
            return PaperTradingConfig.from_dict(raw)
        except yaml.YAMLError as e:
            logger.warning("配置文件 YAML 解析失败: %s，重新初始化", e)
            return self._initialize()
        except Exception as e:
            logger.warning("加载模拟交易配置失败: %s，重新初始化", e)
            return self._initialize()

    def _initialize(self) -> PaperTradingConfig:
        """首次初始化：从 portfolio.yaml 拷贝风格字段，账户字段独立设置 20 万。"""
        from datetime import datetime

        config = PaperTradingConfig()

        # 尝试从主系统 portfolio.yaml 拷贝风格字段
        if PORTFOLIO_CONFIG_PATH.exists():
            try:
                portfolio_raw = yaml.safe_load(PORTFOLIO_CONFIG_PATH.read_text(encoding="utf-8"))
                if portfolio_raw:
                    config.risk_profile = _enum_safe(RiskProfile, portfolio_raw.get("risk_profile", "balanced"))
                    config.investment_goal = _enum_safe(InvestmentGoal, portfolio_raw.get("investment_goal", "absolute_return"))
                    config.trading_style = _enum_safe(TradingStyle, portfolio_raw.get("trading_style", "mixed"))
                    config.holding_period = _enum_safe(HoldingPeriod, portfolio_raw.get("holding_period", "long"))
                    config.investment_horizon = str(portfolio_raw.get("investment_horizon", "3-5年"))
                    config.benchmark = str(portfolio_raw.get("benchmark", "沪深300"))
                    config.circle_of_competence = dict(portfolio_raw.get("circle_of_competence", {}))
                    config.accessible_boards = list(portfolio_raw.get("accessible_boards", ["main_sh", "main_sz"]))

                    # 拷贝评分权重
                    sw = portfolio_raw.get("score_weights")
                    if sw:
                        config.score_weights = ScoreWeights.from_dict(sw)

                    logger.info("已从 %s 拷贝风格字段 (风险偏好/交易风格/能力圈/权重)", PORTFOLIO_CONFIG_PATH)
            except Exception as e:
                logger.warning("拷贝 portfolio.yaml 风格字段失败: %s，使用默认值", e)

        # 账户字段保持独立默认值 (20 万本金)
        config.position_limits = PositionLimits()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        config.created_at = now
        config.last_updated = now

        # 持久化
        self.save(config)
        # 克隆主系统自选股
        self.clone_watchlist_if_needed()
        logger.info("模拟交易独立配置已初始化: %s (本金 %.0f 元)", self._path, config.position_limits.total_capital)
        return config

    # ------------------------------------------------------------------
    # 保存
    # ------------------------------------------------------------------

    def save(self, config: PaperTradingConfig) -> None:
        """保存配置到 YAML 文件。"""
        from datetime import datetime

        config.last_updated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._path.parent.mkdir(parents=True, exist_ok=True)

        with open(self._path, "w", encoding="utf-8") as f:
            f.write(
                "# 白泽模拟交易 — 独立账户配置\n"
                "# 风格字段初始从 portfolio.yaml 拷贝，后续独立演化。\n"
                "# 账户字段 (position_limits) 完全独立，不与主系统互扰。\n\n"
            )
            yaml.dump(
                config.to_dict(),
                f,
                default_flow_style=False,
                allow_unicode=True,
                sort_keys=False,
                Dumper=yaml.SafeDumper,
            )
        logger.info("模拟交易配置已保存到 %s", self._path)

    # ------------------------------------------------------------------
    # 自选股管理 (独立于主系统)
    # ------------------------------------------------------------------

    def clone_watchlist_if_needed(self) -> Path:
        """首次启动时从主系统 watchlist.json 克隆自选股。

        之后模拟交易独立维护自己的自选股，与主系统互不干扰。
        """
        if DEFAULT_WATCHLIST_PATH.exists():
            logger.debug("自选股已存在，跳过克隆: %s", DEFAULT_WATCHLIST_PATH)
            return DEFAULT_WATCHLIST_PATH

        if MAIN_WATCHLIST_PATH.exists():
            import shutil
            import json as _json
            try:
                DEFAULT_WATCHLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(MAIN_WATCHLIST_PATH, DEFAULT_WATCHLIST_PATH)
                logger.info("自选股已克隆: %s → %s", MAIN_WATCHLIST_PATH, DEFAULT_WATCHLIST_PATH)
            except Exception as e:
                # fallback: 创建空自选股
                logger.warning("克隆自选股失败: %s，创建空列表", e)
                DEFAULT_WATCHLIST_PATH.write_text(
                    _json.dumps({"stocks": [], "updated_at": ""}, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
        else:
            import json as _json
            DEFAULT_WATCHLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
            DEFAULT_WATCHLIST_PATH.write_text(
                _json.dumps({"stocks": [], "updated_at": ""}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        return DEFAULT_WATCHLIST_PATH

    @staticmethod
    def load_watchlist() -> list[dict]:
        """加载模拟交易独立自选股。"""
        import json as _json
        if not DEFAULT_WATCHLIST_PATH.exists():
            return []
        try:
            data = _json.loads(DEFAULT_WATCHLIST_PATH.read_text(encoding="utf-8"))
            return data.get("stocks", [])
        except (_json.JSONDecodeError, KeyError) as e:
            logger.warning("无法加载自选股: %s", e)
            return []

    @staticmethod
    def save_watchlist(stocks: list[dict]) -> None:
        """保存模拟交易独立自选股。"""
        import json as _json
        from datetime import datetime
        DEFAULT_WATCHLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "stocks": stocks,
            "updated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        }
        DEFAULT_WATCHLIST_PATH.write_text(
            _json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("自选股已保存: %d 只", len(stocks))

    @staticmethod
    def add_to_watchlist(symbol: str, name: str = "", stop_price: float | None = None) -> bool:
        """添加股票到模拟交易自选股。

        Returns:
            True 添加成功，False 已存在
        """
        stocks = PaperTradingConfigManager.load_watchlist()
        existing = [s for s in stocks if s.get("symbol") == symbol]
        if existing:
            logger.debug("%s 已在自选股中", symbol)
            return False
        stocks.append({
            "symbol": symbol,
            "name": name,
            "stop_price": stop_price,
            "alert_above": None,
        })
        PaperTradingConfigManager.save_watchlist(stocks)
        logger.info("已添加 %s (%s) 到模拟交易自选股", symbol, name)
        return True

    @staticmethod
    def remove_from_watchlist(symbol: str) -> bool:
        """从模拟交易自选股移除。"""
        stocks = PaperTradingConfigManager.load_watchlist()
        new_stocks = [s for s in stocks if s.get("symbol") != symbol]
        if len(new_stocks) == len(stocks):
            return False
        PaperTradingConfigManager.save_watchlist(new_stocks)
        logger.info("已从模拟交易自选股移除 %s", symbol)
        return True

    # ------------------------------------------------------------------
    # 更新能力圈 (周/月复盘时调用)
    # ------------------------------------------------------------------

    def update_competence(self, industry: str, level: int) -> PaperTradingConfig:
        """更新能力圈 — 基于模拟交易经验调整。"""
        config = self.load_or_initialize()
        if level < 1 or level > 5:
            logger.warning("能力圈熟悉度需在 1-5 之间: %d", level)
            return config
        config.circle_of_competence[industry] = level
        self.save(config)
        logger.info("模拟交易能力圈已更新: %s = %d/5", industry, level)
        return config

    def update_position_limits(self, **kwargs) -> PaperTradingConfig:
        """更新仓位约束 — 周/月复盘后调整风控参数。"""
        config = self.load_or_initialize()
        limits = config.position_limits
        for key, value in kwargs.items():
            if hasattr(limits, key):
                setattr(limits, key, value)
            else:
                logger.warning("未知仓位约束字段: %s", key)
        self.save(config)
        return config


# ══════════════════════════════════════════════════════════════════════
# 工具函数
# ══════════════════════════════════════════════════════════════════════


def _enum_safe(cls_enum, val):
    """安全解析枚举值，失败返回第一个枚举值。"""
    try:
        return cls_enum(val)
    except (ValueError, TypeError):
        return list(cls_enum)[0]


def default_config_manager() -> PaperTradingConfigManager:
    """获取默认配置管理器。"""
    return PaperTradingConfigManager()
