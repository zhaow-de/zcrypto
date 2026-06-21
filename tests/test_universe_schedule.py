"""Tests for cli.experiment.universe_schedule — pure-fn only, no qlib needed."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from cli.experiment.universe_schedule import liquidity_rank_schedule

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_panel(n_days: int = 120, symbols: list[str] | None = None) -> pd.DataFrame:
    """Synthetic daily $amount panel (wide, index=date, cols=symbols)."""
    if symbols is None:
        symbols = ["AAA", "BBB", "CCC", "DDD", "EEE"]
    idx = pd.date_range("2024-01-01", periods=n_days, freq="D")
    rng = np.random.default_rng(42)
    data = rng.uniform(1e6, 1e8, size=(n_days, len(symbols)))
    return pd.DataFrame(data, index=idx, columns=symbols)


# ---------------------------------------------------------------------------
# 1. basic membership + rank order
# ---------------------------------------------------------------------------


def test_basic_membership_and_rank():
    """Known-by-construction: top symbols at each rebalance match trailing-mean rank."""
    # 5 symbols with deterministic fixed amounts — easy to reason about
    idx = pd.date_range("2024-01-01", periods=120, freq="D")
    df = pd.DataFrame(
        {
            "AAA": [100.0] * 120,
            "BBB": [200.0] * 120,
            "CCC": [300.0] * 120,
            "DDD": [400.0] * 120,
            "EEE": [500.0] * 120,
        },
        index=idx,
    )
    result = liquidity_rank_schedule(df, top_n=3, lookback_days=30)
    # At every rebalance date the trailing mean is constant → top-3 by value = EEE, DDD, CCC
    for ts, symbols in result.items():
        assert symbols == ["EEE", "DDD", "CCC"], f"Failed at {ts}: {symbols}"


def test_rank_order_descending():
    """Rank order in output list is descending by trailing mean (best first)."""
    idx = pd.date_range("2024-01-01", periods=90, freq="D")
    df = pd.DataFrame(
        {
            "LOW": [10.0] * 90,
            "MID": [50.0] * 90,
            "HIGH": [100.0] * 90,
        },
        index=idx,
    )
    result = liquidity_rank_schedule(df, top_n=3, lookback_days=30)
    for ts, symbols in result.items():
        assert symbols[0] == "HIGH"
        assert symbols[1] == "MID"
        assert symbols[2] == "LOW"


# ---------------------------------------------------------------------------
# 2. PIT (point-in-time) eligibility — NaN before listing
# ---------------------------------------------------------------------------


def test_pit_unlisted_name_absent_before_listing():
    """A symbol that is all-NaN before its listing date must not appear before it has data."""
    idx = pd.date_range("2024-01-01", periods=120, freq="D")
    listing_day = 60  # LATE lists on day 60 (2024-03-01 area)

    df = pd.DataFrame(
        {
            "AAA": [100.0] * 120,
            "BBB": [200.0] * 120,
            "CCC": [300.0] * 120,
            "LATE": [np.nan] * listing_day + [1e9] * (120 - listing_day),
        },
        index=idx,
    )
    result = liquidity_rank_schedule(df, top_n=3, lookback_days=30)

    listing_ts = idx[listing_day]
    for ts, symbols in result.items():
        if ts < listing_ts:
            assert "LATE" not in symbols, f"LATE appeared before listing at {ts}"

    # After sufficient data, LATE (1e9 >> others) must appear
    found_late = any("LATE" in symbols for ts, symbols in result.items() if ts >= listing_ts)
    assert found_late, "LATE never appeared after its listing date"


# ---------------------------------------------------------------------------
# 3. top_n > available columns → no crash, returns all available
# ---------------------------------------------------------------------------


def test_top_n_larger_than_columns():
    """When top_n exceeds live column count, returns all available names (no crash)."""
    idx = pd.date_range("2024-01-01", periods=60, freq="D")
    df = pd.DataFrame(
        {"AAA": [100.0] * 60, "BBB": [200.0] * 60},
        index=idx,
    )
    result = liquidity_rank_schedule(df, top_n=10, lookback_days=30)
    assert len(result) > 0
    for ts, symbols in result.items():
        assert len(symbols) <= 2  # can't exceed available columns
        assert set(symbols) <= {"AAA", "BBB"}


# ---------------------------------------------------------------------------
# 4. reproducibility
# ---------------------------------------------------------------------------


def test_reproducibility():
    """Two calls with same input return identical dicts."""
    df = _make_panel()
    r1 = liquidity_rank_schedule(df, top_n=3, lookback_days=30)
    r2 = liquidity_rank_schedule(df, top_n=3, lookback_days=30)
    assert r1 == r2


# ---------------------------------------------------------------------------
# 5. deterministic tie-break by name
# ---------------------------------------------------------------------------


def test_deterministic_tie_break():
    """Two columns with exactly equal trailing means → ordered alphabetically by name."""
    idx = pd.date_range("2024-01-01", periods=90, freq="D")
    # ZZZ and AAA have identical amounts — tie must be broken by name (AAA < ZZZ)
    df = pd.DataFrame(
        {
            "ZZZ": [100.0] * 90,
            "AAA": [100.0] * 90,
            "MID": [50.0] * 90,
        },
        index=idx,
    )
    result = liquidity_rank_schedule(df, top_n=2, lookback_days=30)
    for ts, symbols in result.items():
        # top-2 are ZZZ and AAA (tied at 100), but AAA < ZZZ alphabetically
        assert set(symbols) == {"AAA", "ZZZ"}, f"Unexpected symbols at {ts}: {symbols}"
        assert symbols[0] == "AAA", f"Expected AAA first (alpha tie-break) at {ts}: {symbols}"
        assert symbols[1] == "ZZZ"


# ---------------------------------------------------------------------------
# 6. return structure
# ---------------------------------------------------------------------------


def test_return_type_and_keys():
    """Keys are pd.Timestamp; values are lists of str."""
    df = _make_panel()
    result = liquidity_rank_schedule(df, top_n=3, lookback_days=30)
    assert isinstance(result, dict)
    assert len(result) > 0
    for k, v in result.items():
        assert isinstance(k, pd.Timestamp), f"Key {k!r} is not a Timestamp"
        assert isinstance(v, list)
        assert all(isinstance(s, str) for s in v)
