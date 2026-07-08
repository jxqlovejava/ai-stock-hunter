# -*- coding: utf-8 -*-
"""偏好加载器 — YAML 持久化 InvestorPreference。

读取 data/portfolio.yaml，写回验证。文件缺失或损坏时静默回退到默认值。
"""

from __future__ import annotations

import logging
import os

import yaml

from .model import InvestorPreference

logger = logging.getLogger(__name__)

DEFAULT_PATH = "data/portfolio.yaml"
EXAMPLE_PATH = "data/portfolio.example.yaml"


class InvestorPreferenceLoader:
    """加载和持久化投资者偏好。"""

    def __init__(self, path: str = DEFAULT_PATH):
        self._path = path

    @property
    def path(self) -> str:
        return os.path.abspath(self._path)

    def load(self) -> InvestorPreference:
        """加载偏好。文件缺失时从 template 自动创建，损坏时返回默认值。"""
        if not os.path.exists(self._path):
            # 尝试从 example 模板复制
            if os.path.exists(EXAMPLE_PATH):
                try:
                    import shutil
                    shutil.copy(EXAMPLE_PATH, self._path)
                    logger.info("从 %s 创建初始偏好文件 %s", EXAMPLE_PATH, self._path)
                except Exception as e:
                    logger.warning("无法复制模板文件: %s", e)
            if not os.path.exists(self._path):
                logger.info("偏好文件 %s 不存在，使用默认值", self._path)
                return InvestorPreference()
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if data is None:
                return InvestorPreference()
            return InvestorPreference.from_dict(data)
        except yaml.YAMLError as e:
            logger.warning("偏好文件 YAML 解析失败: %s，回退到默认值", e)
            return InvestorPreference()
        except Exception as e:
            logger.warning("加载偏好失败: %s，回退到默认值", e)
            return InvestorPreference()

    def save(self, prefs: InvestorPreference) -> None:
        """保存偏好到 YAML 文件。"""
        os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as f:
            f.write(
                "# 白泽 — 投资者偏好配置文件\n"
                "# 由 InvestorPreferenceLoader 读取，注入路由管道。\n\n"
            )
            yaml.dump(
                prefs.to_dict(),
                f,
                default_flow_style=False,
                allow_unicode=True,
                sort_keys=False,
                Dumper=yaml.SafeDumper,
            )
        logger.info("偏好已保存到 %s", self._path)

    def reset(self) -> InvestorPreference:
        """重置为默认值并覆盖文件。"""
        prefs = InvestorPreference()
        self.save(prefs)
        return prefs

    def summary(self, prefs: InvestorPreference | None = None) -> str:
        """格式化为人类可读摘要。"""
        if prefs is None:
            prefs = self.load()
        limits = prefs.position_limits
        coc = prefs.circle_of_competence.industries

        coc_lines = "\n".join(
            f"    {industry}: {'⭐' * min(fam, 5)} ({fam}/5)"
            for industry, fam in sorted(coc.items())
        )
        weights = prefs.score_weights
        weight_lines = []
        for k in ("fundamental", "technical", "macro", "sector", "sentiment"):
            v = getattr(weights, k, None)
            weight_lines.append(f"    {k}: {v if v is not None else '系统默认'}")

        return f"""# 投资者偏好画像

## 身份与目标
  风险偏好: {prefs.risk_profile.value}
  投资目标: {prefs.investment_goal.value}
  交易风格: {prefs.trading_style.value}
  持有时间: {prefs.holding_period.value}
  投资者层级: {prefs.tier.value}
  投资周期: {prefs.investment_horizon}
  业绩基准: {prefs.benchmark}
  可交易板块: {', '.join(b.value for b in prefs.accessible_boards)}

## 仓位约束
  总投资本金: {limits.total_capital:,.0f}
  单票上限: {limits.max_single_pct:.0%}
  行业上限: {limits.max_sector_pct:.0%}
  总仓位上限: {limits.max_total_exposure:.0%}
  最低现金: {limits.min_cash_pct:.0%}
  单笔止损: {limits.single_stop_loss_pct:.0%}
  组合回撤: {limits.portfolio_drawdown_pct:.0%}
  双创折扣: {limits.gem_discount:.0%}

## 能力圈
{coc_lines}

## 裁决评分权重
{chr(10).join(weight_lines)}

## 军规过滤
  启用的规则: {prefs.enabled_rules or '基于层级自动决定 (' + prefs.tier.value + ')'}

## 配置文件
  {self.path}
"""
