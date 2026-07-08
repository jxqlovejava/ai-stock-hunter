# -*- coding: utf-8 -*-
"""多因子合成引擎 — ICIR 加权 / 等权 / 最优化合成。

将多个单因子信号合成为一个综合 Alpha 评分，用于全市场排名。
参考 Barra / Axioma 风格的多因子合成方法。

使用模式:
    synthesizer = FactorSynthesizer()
    result = synthesizer.synthesize(
        ["pb_factor", "roe_factor", "momentum_20d"],
        method="icir",
        ic_stats={...},  # 可选，提供 IC 统计以计算权重
    )
    print(result.weights)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd

from src.alpha.schema import AlphaSynthesis, SynthesisMethod

logger = logging.getLogger(__name__)


# 默认 IC 统计（因子无历史数据时的 fallback）
DEFAULT_IC_STATS = {"icir": 0.2, "ic_mean": 0.02, "ic_std": 0.10}


class FactorSynthesizer:
    """多因子合成引擎。

    三种合成方法:
      - equal_weight: 等权平均，适合无历史数据时
      - icir_weight: 按 ICIR 加权，ICIR 越高的因子权重越大
      - optimized: 考虑因子间相关性，最大化组合 ICIR（简化版）
    """

    def __init__(self, registry=None):
        self._registry = registry  # lazy: Registry or None

    def _get_registry(self):
        """懒加载 registry，避免循环导入。"""
        if self._registry is None:
            from src.factors.registry import get_default_registry
            self._registry = get_default_registry()
        return self._registry

    def synthesize(
        self,
        alpha_ids: list[str],
        method: SynthesisMethod | str = SynthesisMethod.ICIR_WEIGHT,
        ic_stats: Optional[dict[str, dict[str, float]]] = None,
        factor_scores: Optional[dict[str, np.ndarray]] = None,
    ) -> AlphaSynthesis:
        """合成多因子。

        Args:
            alpha_ids: 因子 ID 列表
            method: 合成方法
            ic_stats: {alpha_id: {icir, ic_mean, ic_std}} 可选 IC 统计
            factor_scores: {alpha_id: ndarray} 可选预计算的因子评分

        Returns:
            AlphaSynthesis
        """
        if len(alpha_ids) < 2:
            return self._single_factor_result(alpha_ids, method)

        ic_stats = ic_stats or {}
        method_enum = method if isinstance(method, SynthesisMethod) else SynthesisMethod(method)

        # 计算权重
        if method_enum == SynthesisMethod.ICIR_WEIGHT:
            weights, contribs = self._icir_weights(alpha_ids, ic_stats)
        elif method_enum == SynthesisMethod.OPTIMIZED:
            weights, contribs = self._optimized_weights(alpha_ids, ic_stats, factor_scores)
        else:
            weights, contribs = self._equal_weights(alpha_ids)

        # 估计组合 ICIR
        expected_icir = self._estimate_composite_icir(alpha_ids, weights, ic_stats)

        # 相关性矩阵（如有数据）
        corr_matrix = self._correlation_matrix(alpha_ids, factor_scores)

        warnings = []
        if expected_icir < 0.2:
            warnings.append(f"预期组合 ICIR={expected_icir:.2f} < 0.2 — 因子组合预期效果较弱")
        missing_ic = [a for a in alpha_ids if a not in ic_stats]
        if missing_ic:
            warnings.append(f"以下因子无 IC 历史数据，使用默认 ICIR=0.2: {missing_ic}")

        return AlphaSynthesis(
            method=method_enum,
            alpha_ids=alpha_ids,
            weights=weights,
            expected_icir=expected_icir,
            factor_contributions=contribs,
            correlation_matrix=corr_matrix,
            warnings=warnings,
        )

    def compute_composite_score(
        self,
        df: pd.DataFrame,
        alpha_ids: list[str],
        weights: Optional[dict[str, float]] = None,
    ) -> pd.DataFrame:
        """对 spot DataFrame 计算复合因子评分。

        Args:
            df: spot DataFrame（每行一只股票）
            alpha_ids: 因子列表
            weights: 因子权重；None 则用 ICIR 等权

        Returns:
            追加了 composite_score 列的 DataFrame
        """
        from src.factors.adapter import build_spot_panel as _build_spot_panel
        panel = _build_spot_panel(df)

        if weights is None:
            synthesis = self.synthesize(alpha_ids)
            weights = synthesis.weights

        factor_scores = {}
        for alpha_id in alpha_ids:
            try:
                score_df = self._get_registry().compute(alpha_id, panel)
                if score_df.shape[0] == 1:
                    factor_scores[alpha_id] = score_df.iloc[0].values
                else:
                    factor_scores[alpha_id] = score_df.iloc[-1].values
            except Exception as exc:
                logger.debug("factor %s skipped: %s", alpha_id, exc)
                continue

        if not factor_scores:
            result = df.copy()
            result["composite_score"] = 50.0
            return result

        # 对齐维度
        codes = df.get("code", df.index)
        codes = [str(c) for c in (codes.iloc[:, 0] if isinstance(codes, pd.DataFrame) else codes)]
        n_stocks = len(codes)

        composite = np.full(n_stocks, 50.0)
        weight_sum = 0.0

        for alpha_id, scores in factor_scores.items():
            w = weights.get(alpha_id, 0.0)
            if w <= 0:
                continue
            # 标准化因子得分到 0-100
            normalized = self._normalize_scores(scores)
            if len(normalized) != n_stocks:
                # 维度不匹配，跳过
                continue
            composite += w * (normalized - 50.0)
            weight_sum += w

        if weight_sum > 0:
            composite = 50.0 + (composite - 50.0) / weight_sum

        result = df.copy()
        result["composite_score"] = np.clip(composite, 0.0, 100.0)
        return result

    # ------------------------------------------------------------------
    # Weight calculation
    # ------------------------------------------------------------------

    @staticmethod
    def _equal_weights(alpha_ids: list[str]) -> tuple[dict[str, float], dict[str, float]]:
        n = len(alpha_ids)
        w = 1.0 / n
        weights = {aid: w for aid in alpha_ids}
        contribs = {aid: w for aid in alpha_ids}
        return weights, contribs

    @staticmethod
    def _icir_weights(
        alpha_ids: list[str],
        ic_stats: dict[str, dict[str, float]],
    ) -> tuple[dict[str, float], dict[str, float]]:
        """ICIR 加权 — ICIR 高的因子权重更大。

        weight_i = max(0, ICIR_i) / sum(max(0, ICIR_j))
        """
        icirs = {}
        for aid in alpha_ids:
            stats = ic_stats.get(aid, DEFAULT_IC_STATS)
            icirs[aid] = max(0.01, stats.get("icir", DEFAULT_IC_STATS["icir"]))

        total = sum(icirs.values())
        if total <= 0:
            return FactorSynthesizer._equal_weights(alpha_ids)

        weights = {aid: icirs[aid] / total for aid in alpha_ids}
        contribs = dict(weights)
        return weights, contribs

    def _optimized_weights(
        self,
        alpha_ids: list[str],
        ic_stats: dict[str, dict[str, float]],
        factor_scores: Optional[dict[str, np.ndarray]] = None,
    ) -> tuple[dict[str, float], dict[str, float]]:
        """最优化权重 — 考虑因子间相关性，最大化 ICIR / sqrt(var)。

        简化版：对相关性高的因子对做降权处理。
        """
        # 获取 IC 向量
        ic_vecs = {}
        for aid in alpha_ids:
            stats = ic_stats.get(aid, DEFAULT_IC_STATS)
            icir = stats.get("icir", DEFAULT_IC_STATS["icir"])
            ic_vecs[aid] = max(0.01, icir)

        # 计算相关性矩阵
        corr = self._correlation_matrix(alpha_ids, factor_scores)

        # 简化最优化：对高相关因子降权
        base_weights = dict(ic_vecs)

        for i, aid_i in enumerate(alpha_ids):
            for j, aid_j in enumerate(alpha_ids):
                if i >= j:
                    continue
                r = corr.get(aid_i, {}).get(aid_j, 0.0)
                if r > 0.5:
                    # 相关性 > 0.5 → 两个因子各降权 20%
                    penalty = 1.0 - (r - 0.5) * 0.4
                    base_weights[aid_i] *= penalty
                    base_weights[aid_j] *= penalty

        # 归一化
        total = sum(base_weights.values())
        if total <= 0:
            return self._equal_weights(alpha_ids)

        weights = {aid: base_weights[aid] / total for aid in alpha_ids}
        # 贡献度 = 权重 * ICIR（归一化）
        raw_contribs = {aid: weights[aid] * ic_vecs.get(aid, 0.2) for aid in alpha_ids}
        contrib_total = sum(raw_contribs.values()) or 1.0
        contribs = {aid: raw_contribs[aid] / contrib_total for aid in alpha_ids}

        return weights, contribs

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _correlation_matrix(
        alpha_ids: list[str],
        factor_scores: Optional[dict[str, np.ndarray]] = None,
    ) -> dict[str, dict[str, float]]:
        """计算因子间相关性矩阵。"""
        matrix: dict[str, dict[str, float]] = {}
        if factor_scores is None or len(factor_scores) < 2:
            # 无数据时用单位矩阵
            for aid in alpha_ids:
                matrix[aid] = {other: 1.0 if other == aid else 0.0 for other in alpha_ids}
            return matrix

        for aid_i in alpha_ids:
            matrix[aid_i] = {}
            scores_i = factor_scores.get(aid_i)
            for aid_j in alpha_ids:
                scores_j = factor_scores.get(aid_j)
                if scores_i is None or scores_j is None:
                    matrix[aid_i][aid_j] = 0.0
                    continue
                if aid_i == aid_j:
                    matrix[aid_i][aid_j] = 1.0
                    continue
                try:
                    valid = ~(np.isnan(scores_i) | np.isnan(scores_j))
                    if valid.sum() < 3:
                        matrix[aid_i][aid_j] = 0.0
                    else:
                        matrix[aid_i][aid_j] = float(
                            np.corrcoef(scores_i[valid], scores_j[valid])[0, 1]
                        )
                except Exception:
                    matrix[aid_i][aid_j] = 0.0
        return matrix

    @staticmethod
    def _estimate_composite_icir(
        alpha_ids: list[str],
        weights: dict[str, float],
        ic_stats: dict[str, dict[str, float]],
    ) -> float:
        """估计组合 ICIR：加权平均 IC / sqrt(加权平均方差)。

        简化假设因子间相关系数 ~0.3。
        """
        n = len(alpha_ids)
        if n == 0:
            return 0.0

        rho = 0.3  # 假设平均相关系数
        weighted_ic = 0.0
        weighted_var = 0.0

        for aid in alpha_ids:
            w = weights.get(aid, 0.0)
            if w <= 0:
                continue
            ic = ic_stats.get(aid, DEFAULT_IC_STATS).get("ic_mean", 0.02)
            ic_std = ic_stats.get(aid, DEFAULT_IC_STATS).get("ic_std", 0.10)
            weighted_ic += w * ic
            weighted_var += w * w * (ic_std ** 2)

        # 协方差贡献
        for i, aid_i in enumerate(alpha_ids):
            for j, aid_j in enumerate(alpha_ids):
                if i >= j:
                    continue
                wi = weights.get(aid_i, 0.0)
                wj = weights.get(aid_j, 0.0)
                if wi <= 0 or wj <= 0:
                    continue
                std_i = ic_stats.get(aid_i, DEFAULT_IC_STATS).get("ic_std", 0.10)
                std_j = ic_stats.get(aid_j, DEFAULT_IC_STATS).get("ic_std", 0.10)
                weighted_var += 2 * wi * wj * rho * std_i * std_j

        composite_std = np.sqrt(max(weighted_var, 1e-9))
        return weighted_ic / composite_std if composite_std > 0 else 0.0

    @staticmethod
    def _normalize_scores(scores: np.ndarray) -> np.ndarray:
        """标准化因子得分到 0-100 分布。"""
        scores = np.asarray(scores, dtype=float)
        valid = ~np.isnan(scores)
        if valid.sum() < 3:
            return np.full_like(scores, 50.0)

        # Z-score → 映射到 0-100（均值 50，标准差 15）
        mean = np.mean(scores[valid])
        std = np.std(scores[valid])
        if std < 1e-9:
            return np.full_like(scores, 50.0)

        z = (scores - mean) / std
        normalized = 50.0 + z * 15.0
        return np.clip(normalized, 0.0, 100.0)

    @staticmethod
    def _single_factor_result(
        alpha_ids: list[str], method: SynthesisMethod | str
    ) -> AlphaSynthesis:
        """单因子结果。"""
        method_enum = method if isinstance(method, SynthesisMethod) else SynthesisMethod(method)
        aid = alpha_ids[0] if alpha_ids else ""
        return AlphaSynthesis(
            method=method_enum,
            alpha_ids=list(alpha_ids),
            weights={aid: 1.0} if aid else {},
            expected_icir=0.0,
            factor_contributions={aid: 1.0} if aid else {},
        )
