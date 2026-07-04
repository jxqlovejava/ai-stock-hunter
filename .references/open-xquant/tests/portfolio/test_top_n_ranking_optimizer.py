import pandas as pd
from oxq.core.types import PortfolioOptimizer
from oxq.portfolio.optimizers import TopNRankingOptimizer


def test_protocol():
    assert isinstance(TopNRankingOptimizer(score_col="score"), PortfolioOptimizer)


def test_basic_ranking():
    opt = TopNRankingOptimizer(score_col="score", n=2)
    indicators = {
        "A": pd.DataFrame({"score": [30.0]}, index=pd.to_datetime(["2024-01-01"])),
        "B": pd.DataFrame({"score": [20.0]}, index=pd.to_datetime(["2024-01-01"])),
        "C": pd.DataFrame({"score": [10.0]}, index=pd.to_datetime(["2024-01-01"])),
    }
    result = opt.optimize({}, indicators)
    assert abs(result["A"] - 0.6) < 1e-9
    assert abs(result["B"] - 0.4) < 1e-9
    assert "C" not in result


def test_filter_negative():
    opt = TopNRankingOptimizer(score_col="score", n=5)
    indicators = {
        "A": pd.DataFrame({"score": [10.0]}, index=pd.to_datetime(["2024-01-01"])),
        "B": pd.DataFrame({"score": [-5.0]}, index=pd.to_datetime(["2024-01-01"])),
    }
    result = opt.optimize({}, indicators)
    assert result["A"] == 1.0
    assert "B" not in result


def test_max_weight_cap():
    opt = TopNRankingOptimizer(score_col="score", n=2, max_weight=0.5)
    indicators = {
        "A": pd.DataFrame({"score": [90.0]}, index=pd.to_datetime(["2024-01-01"])),
        "B": pd.DataFrame({"score": [10.0]}, index=pd.to_datetime(["2024-01-01"])),
    }
    result = opt.optimize({}, indicators)
    assert result["A"] == 0.5
    assert abs(result["B"] - 0.1) < 1e-9


def test_empty_returns_cash():
    opt = TopNRankingOptimizer(score_col="score", n=5)
    result = opt.optimize({}, {})
    assert result == {"CASH": 1.0}


def test_all_negative_returns_cash():
    opt = TopNRankingOptimizer(score_col="score", n=5)
    indicators = {"A": pd.DataFrame({"score": [-1.0]}, index=pd.to_datetime(["2024-01-01"]))}
    result = opt.optimize({}, indicators)
    assert result == {"CASH": 1.0}
