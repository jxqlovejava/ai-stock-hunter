# -*- coding: utf-8 -*-
"""交叉验证模块。

对来自多个数据源的同字段进行对比，检测差异并标记 DISPUTED。

规则:
  - 差异 ≤ 3%  → 验证通过
  - 差异 > 3%  → 标记 DISPUTED，不进入分析管道
  - 仅 1 源    → cross_validated=False，置信度降级
"""

from __future__ import annotations

from .schema import FundamentalMetrics, Quote

DISPUTE_THRESHOLD = 0.03  # 3%


def validate_price(gs: Quote | None, ak: Quote | None) -> dict:
    """交叉验证收盘价。

    Returns:
        {"price": float|None, "validated": bool, "dispute": bool, "diff_pct": float|None}
    """
    vals = []
    if gs is not None and gs.price > 0:
        vals.append(("guosen", gs.price))
    if ak is not None and ak.price > 0:
        vals.append(("akshare", ak.price))

    if len(vals) == 0:
        return {"price": None, "validated": False, "dispute": False, "diff_pct": None}

    if len(vals) == 1:
        return {
            "price": vals[0][1],
            "validated": False,
            "dispute": False,
            "diff_pct": None,
        }

    p1, p2 = vals[0][1], vals[1][1]
    diff_pct = abs(p1 - p2) / p2
    dispute = diff_pct > DISPUTE_THRESHOLD
    return {
        "price": (p1 + p2) / 2,  # 取均值
        "validated": True,
        "dispute": dispute,
        "diff_pct": diff_pct,
    }


def validate_fundamentals(
    metrics: list[FundamentalMetrics],
) -> FundamentalMetrics | None:
    """合并并交叉验证多个源的基本面指标。

    取各源的中位数作为最终值，标记交叉验证状态。
    """
    if not metrics:
        return None
    if len(metrics) == 1:
        m = metrics[0]
        m.cross_validated = False
        return m

    # 收集所有源的值
    pe_vals = [m.pe_ttm for m in metrics if m.pe_ttm is not None]
    pb_vals = [m.pb for m in metrics if m.pb is not None]
    roe_vals = [m.roe for m in metrics if m.roe is not None]

    dispute = False
    for vals in [pe_vals, pb_vals, roe_vals]:
        if len(vals) >= 2:
            diff = abs(vals[0] - vals[1]) / abs(vals[1]) if vals[1] != 0 else 0
            if diff > 0.05:  # 5% threshold for fundamentals
                dispute = True
                break

    sources = list({s for m in metrics for s in m.sources})

    return FundamentalMetrics(
        symbol=metrics[0].symbol,
        name=metrics[0].name,
        pe_ttm=pe_vals[0] if pe_vals else None,
        pb=pb_vals[0] if pb_vals else None,
        roe=roe_vals[0] if roe_vals else None,
        debt_to_equity=metrics[0].debt_to_equity,
        market_cap=metrics[0].market_cap,
        sources=sources,
        cross_validated=len(sources) >= 2,
        dispute=dispute,
    )
