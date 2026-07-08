# -*- coding: utf-8 -*-
"""残差动量因子 — 剔除市场 Beta 和行业 Beta 后的价格动量。

Residual Momentum = 滚动回归残差的累积收益。

两步:
  1. 对过去 252 日收益率做: r_i = α + β_market × r_m + β_industry × r_ind + ε
  2. Residual Momentum = Σ ε_{t-12 到 t-1}（跳过最近 1 月）

残差动量剔除了市场涨跌和行业轮动的 Beta 收益，捕捉的是
"超越市场和同行的真实价格趋势"。

A 股适配: 残差动量在行业轮动剧烈的 A 股市场比原始价格动量更干净。
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

__alpha_meta__ = {
    "id": "residual_momentum",
    "nickname": "残差动量",
    "category": "momentum",
    "description": "剔除市场和行业 Beta 后的 12-1 月残差累积收益",
    "columns_required": ["close"],
    "frequency": "daily",
    "min_warmup_bars": 252,
    "provider_confidence": 0.75,
    "tags": ["momentum", "residual", "alpha", "advanced"],
}


def compute(
    panel: dict[str, pd.DataFrame],
    market_returns: pd.Series | None = None,
    industry_returns: dict[str, pd.Series] | None = None,
    industry_map: dict[str, str] | None = None,
) -> pd.DataFrame:
    """计算残差动量因子。

    Args:
        panel: {symbol: DataFrame}，须含 "close" 列
        market_returns: 市场日收益率序列（如沪深300）
        industry_returns: {industry_name: 行业日收益率序列}
        industry_map: {symbol: industry_name}

    Returns:
        DataFrame with column "residual_momentum"
    """
    results: dict[str, float] = {}

    for symbol, df in panel.items():
        if df.empty or "close" not in df.columns:
            results[symbol] = np.nan
            continue

        if len(df) < 252:
            results[symbol] = np.nan
            continue

        try:
            # 计算日收益率
            close = df["close"].astype(float)
            returns = close.pct_change().dropna().iloc[-252:]

            if len(returns) < 126:
                results[symbol] = np.nan
                continue

            # 构造回归变量
            X = pd.DataFrame(index=returns.index)

            # 截距
            X["const"] = 1.0

            # 市场 Beta
            if market_returns is not None:
                aligned = market_returns.reindex(returns.index).fillna(0)
                X["market"] = aligned

            # 行业 Beta
            if industry_returns is not None and industry_map is not None:
                ind_name = industry_map.get(symbol)
                if ind_name and ind_name in industry_returns:
                    aligned = industry_returns[ind_name].reindex(returns.index).fillna(0)
                    X["industry"] = aligned

            # OLS 回归
            X_np = X.values.astype(float)
            y_np = returns.values.astype(float)

            # 去除含 NaN 的行
            valid = ~np.isnan(X_np).any(axis=1) & ~np.isnan(y_np)
            if valid.sum() < 60:
                results[symbol] = np.nan
                continue

            X_clean = X_np[valid]
            y_clean = y_np[valid]

            # (X'X)^(-1) X'y
            try:
                beta = np.linalg.lstsq(X_clean, y_clean, rcond=None)[0]
            except np.linalg.LinAlgError:
                results[symbol] = np.nan
                continue

            # 残差 = y - Xβ
            residuals = y_clean - X_clean @ beta

            # 残差动量: 跳过最近 21 日 (~1 个月) 的 12 个月累积残差
            skip = 21
            if len(residuals) <= skip:
                results[symbol] = np.nan
                continue

            mom_residuals = residuals[:-skip] if skip > 0 else residuals
            residual_momentum = float(mom_residuals[-231:].sum()) if len(mom_residuals) >= 231 else float(mom_residuals.sum())

            results[symbol] = residual_momentum

        except Exception as e:
            logger.debug("残差动量计算失败 %s: %s", symbol, e)
            results[symbol] = np.nan

    return pd.DataFrame(
        {"residual_momentum": results.values()},
        index=results.keys(),
    )
