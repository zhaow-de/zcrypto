import numpy as np
import pandas as pd

from cli.experiment.longshort import long_short_spread


def _mi(date_inst_value):
    idx = pd.MultiIndex.from_tuples([(d, i) for d, i, _ in date_inst_value], names=["datetime", "instrument"])
    return pd.Series([v for *_, v in date_inst_value], index=idx)


def test_perfect_signal_positive_spread():
    # 2 dates, 6 instruments; score == next-day return → longs (top-2) beat shorts (bottom-2).
    rows_s, rows_r = [], []
    for d in pd.to_datetime(["2025-01-01", "2025-01-02"]):
        rets = {"A": 0.05, "B": 0.03, "C": 0.01, "D": -0.01, "E": -0.03, "F": -0.05}
        for inst, r in rets.items():
            rows_s.append((d, inst, r))  # score = the realized fwd return (perfect)
            rows_r.append((d, inst, r))
    out = long_short_spread(_mi(rows_s), _mi(rows_r), k=2, cost_per_side=0.0)
    # top-2 (A,B) mean 0.04 minus bottom-2 (E,F) mean -0.04 = +0.08 each day.
    assert out["daily"].round(6).tolist() == [0.08, 0.08]
    assert out["ending"] > 1.0
    # A 2-date constant-spread series has zero variance, so _sharpe's guard returns 0.0;
    # the meaningful assertions are the daily values and ending > 1.0.
    assert out["sharpe"] >= 0.0


def test_inverted_signal_negative_spread():
    rets = {"A": 0.05, "B": -0.05}
    d = pd.Timestamp("2025-01-01")
    scores = _mi([(d, "A", -1.0), (d, "B", 1.0)])  # score inverted vs return
    fwd = _mi([(d, "A", 0.05), (d, "B", -0.05)])
    out = long_short_spread(scores, fwd, k=1, cost_per_side=0.0)
    # long B (score 1.0, ret -0.05), short A (ret 0.05) → -0.05 - 0.05 = -0.10
    assert out["daily"].round(6).tolist() == [-0.10]


def test_turnover_cost_subtracted():
    # day1 longs={A}, shorts={C}; day2 the book flips entirely → full turnover both legs.
    d1, d2 = pd.to_datetime(["2025-01-01", "2025-01-02"])
    scores = _mi([(d1, "A", 1.0), (d1, "B", 0.0), (d1, "C", -1.0), (d2, "A", -1.0), (d2, "B", 0.0), (d2, "C", 1.0)])
    fwd = _mi(
        [(d1, "A", 0.0), (d1, "B", 0.0), (d1, "C", 0.0), (d2, "A", 0.0), (d2, "B", 0.0), (d2, "C", 0.0)]
    )  # zero returns → isolate cost
    out = long_short_spread(scores, fwd, k=1, cost_per_side=0.001)
    # day1: longs={A} (new), shorts={C} (new) → turnover 1+1 → cost 0.002; spread 0 → net -0.002
    # day2: longs={C} (new vs {A}), shorts={A} (new vs {C}) → turnover 1+1 → cost 0.002 → net -0.002
    assert out["daily"].round(6).tolist() == [-0.002, -0.002]


def test_clamps_k_when_universe_small():
    d = pd.Timestamp("2025-01-01")
    scores = _mi([(d, "A", 1.0), (d, "B", -1.0)])  # n=2, k=5 → kk=min(5, 1)=1
    fwd = _mi([(d, "A", 0.02), (d, "B", -0.02)])
    out = long_short_spread(scores, fwd, k=5, cost_per_side=0.0)
    assert out["daily"].round(6).tolist() == [0.04]  # long A 0.02 - short B -0.02


def test_nan_rows_dropped_and_empty_date_is_zero():
    d1, d2 = pd.to_datetime(["2025-01-01", "2025-01-02"])
    # d2 has only 1 non-NaN instrument → kk=0 → spread 0.0
    scores = _mi([(d1, "A", 1.0), (d1, "B", -1.0), (d2, "A", 1.0), (d2, "B", np.nan)])
    fwd = _mi([(d1, "A", 0.02), (d1, "B", -0.02), (d2, "A", 0.02), (d2, "B", 0.02)])
    out = long_short_spread(scores, fwd, k=1, cost_per_side=0.0)
    assert out["daily"].round(6).tolist() == [0.04, 0.0]
