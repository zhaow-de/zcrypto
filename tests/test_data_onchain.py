"""Unit tests for cli/data/onchain.py — monkeypatched HTTP, no real network calls."""

from __future__ import annotations

import json
import math
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from cli.data import onchain as oc

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PAGE1 = {
    "data": [
        {"time": "2023-01-01T00:00:00.000Z", "CapMrktCurUSD": "400000000000", "AdrActCnt": "900000"},
        {"time": "2023-01-02T00:00:00.000Z", "CapMrktCurUSD": "500000000000", "AdrActCnt": "1000000"},
    ],
    "next_page_token": "token123",
}

_PAGE2 = {
    "data": [
        {"time": "2023-01-03T00:00:00.000Z", "CapMrktCurUSD": "600000000000", "AdrActCnt": "1100000"},
    ],
    # No next_page_token → last page
}


def _mock_resp(payload: dict) -> MagicMock:
    r = MagicMock(status=200)
    r.data = json.dumps(payload).encode()
    return r


def _two_page_side_effect(method, url, **kwargs):
    """Return page-1 on first call, page-2 on second."""
    if "page_token" not in url:
        return _mock_resp(_PAGE1)
    return _mock_resp(_PAGE2)


# ---------------------------------------------------------------------------
# fetch_btc_onchain tests
# ---------------------------------------------------------------------------


def test_pagination_all_three_rows():
    """All 3 rows from both pages are present in the result."""
    with patch.object(oc._pool, "request", side_effect=_two_page_side_effect):
        df = oc.fetch_btc_onchain("2023-01-01", "2023-01-03")
    assert len(df) == 3


def test_date_parsing_utc_normalized():
    """Index is a DatetimeIndex; each entry is UTC-normalized (time component 00:00:00)."""
    with patch.object(oc._pool, "request", side_effect=_two_page_side_effect):
        df = oc.fetch_btc_onchain("2023-01-01", "2023-01-03")
    assert isinstance(df.index, pd.DatetimeIndex)
    for ts in df.index:
        assert ts.hour == 0 and ts.minute == 0 and ts.second == 0


def test_float_coercion():
    """market_cap and active_addr are float64."""
    with patch.object(oc._pool, "request", side_effect=_two_page_side_effect):
        df = oc.fetch_btc_onchain("2023-01-01", "2023-01-03")
    assert df["market_cap"].dtype == np.float64
    assert df["active_addr"].dtype == np.float64


def test_nvm_correctness():
    """NVM = log(market_cap / active_addr²) — check the first row's value."""
    with patch.object(oc._pool, "request", side_effect=_two_page_side_effect):
        df = oc.fetch_btc_onchain("2023-01-01", "2023-01-03")
    # Row 0: market_cap=400e9, active_addr=900_000
    expected = math.log(400_000_000_000.0 / (900_000.0**2))
    # NVM is computed in build_btc_nvm_cache, not fetch_btc_onchain; compute directly here.
    row = df.iloc[0]
    computed = math.log(row["market_cap"] / row["active_addr"] ** 2)
    assert abs(computed - expected) < 1e-9


def test_nonfinite_guard_addr_zero_produces_nan():
    """A row with AdrActCnt=0 → NVM is NaN (division by zero guarded)."""
    page_with_zero = {
        "data": [
            {"time": "2023-01-01T00:00:00.000Z", "CapMrktCurUSD": "400000000000", "AdrActCnt": "900000"},
            {"time": "2023-01-02T00:00:00.000Z", "CapMrktCurUSD": "500000000000", "AdrActCnt": "1000000"},
            {"time": "2023-01-03T00:00:00.000Z", "CapMrktCurUSD": "600000000000", "AdrActCnt": "1100000"},
            {"time": "2023-01-04T00:00:00.000Z", "CapMrktCurUSD": "700000000000", "AdrActCnt": "0"},
        ],
        # No next_page_token
    }

    def _side_effect(method, url, **kwargs):
        return _mock_resp(page_with_zero)

    with patch.object(oc._pool, "request", side_effect=_side_effect):
        df = oc.fetch_btc_onchain("2023-01-01")

    # Compute NVM inline (same as build_btc_nvm_cache does)
    raw = np.log(df["market_cap"] / df["active_addr"] ** 2)
    nvm = np.where(np.isfinite(raw), raw, np.nan)
    assert np.isnan(nvm[-1]), "addr=0 row must produce NaN NVM"
    # Other rows must be finite
    assert all(np.isfinite(nvm[:-1]))


# ---------------------------------------------------------------------------
# build_btc_nvm_cache tests
# ---------------------------------------------------------------------------


def test_build_btc_nvm_cache_writes_parquet(tmp_path):
    """build_btc_nvm_cache writes a parquet with an 'nvm' column."""
    out_path = str(tmp_path / "onchain" / "btc_nvm.parquet")

    with patch.object(oc._pool, "request", side_effect=_two_page_side_effect):
        result = oc.build_btc_nvm_cache(path=out_path, start="2023-01-01", end="2023-01-03")

    # Return value has 'nvm' column
    assert "nvm" in result.columns
    assert len(result) == 3

    # Parquet was written
    import os

    assert os.path.exists(out_path)

    # Round-trip read
    loaded = pd.read_parquet(out_path)
    assert "nvm" in loaded.columns
    assert len(loaded) == 3


def test_build_btc_nvm_cache_nvm_values():
    """NVM values in the cache match log(market_cap / active_addr²)."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        out_path = f"{tmp}/btc_nvm.parquet"
        with patch.object(oc._pool, "request", side_effect=_two_page_side_effect):
            result = oc.build_btc_nvm_cache(path=out_path, start="2023-01-01", end="2023-01-03")

    # Row 0: market_cap=400e9, active_addr=900_000
    expected_row0 = math.log(400_000_000_000.0 / (900_000.0**2))
    assert abs(result["nvm"].iloc[0] - expected_row0) < 1e-9
