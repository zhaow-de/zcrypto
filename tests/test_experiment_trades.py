"""Unit tests for cli.experiment.trades — derive buy/sell trades from qlib positions."""

from __future__ import annotations

import types

import pandas as pd
import pytest

from cli.experiment.trades import trade_summary, trades_from_positions

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DAY0 = pd.Timestamp("2024-01-01")
DAY1 = pd.Timestamp("2024-01-02")
DAY2 = pd.Timestamp("2024-01-03")


def _make_positions() -> dict:
    """Three-day positions dict exercising buy, unchanged, partial sell, and full sell-out."""
    return {
        DAY0: types.SimpleNamespace(
            position={
                "BTC": {"amount": 1.0, "price": 50000.0},
                "ETH": {"amount": 2.0, "price": 3000.0},
                "cash": 10000.0,
                "now_account_value": 66000.0,
            }
        ),
        DAY1: types.SimpleNamespace(
            position={
                "BTC": {"amount": 1.5, "price": 52000.0},
                "ETH": {"amount": 2.0, "price": 3100.0},  # unchanged amount
                "cash": 5000.0,
                "now_account_value": 85200.0,
            }
        ),
        DAY2: types.SimpleNamespace(
            position={
                # BTC fully sold — absent from dict entirely
                "ETH": {"amount": 1.0, "price": 3200.0},  # partial sell
                "cash": 100000.0,
                "now_account_value": 103200.0,
            }
        ),
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_trades_row_count_and_columns():
    positions = _make_positions()
    trades = trades_from_positions(positions)

    assert list(trades.columns) == ["date", "side", "symbol", "qty", "price", "value"]
    assert len(trades) == 5


def test_day0_initial_buys():
    trades = trades_from_positions(_make_positions())
    day0 = trades[trades["date"] == DAY0].reset_index(drop=True)

    # Two buys on day 0 (BTC and ETH), sorted by symbol → BTC first
    assert len(day0) == 2

    btc = day0[day0["symbol"] == "BTC"].iloc[0]
    assert btc["side"] == "buy"
    assert btc["qty"] == pytest.approx(1.0)
    assert btc["price"] == pytest.approx(50000.0)
    assert btc["value"] == pytest.approx(50000.0)

    eth = day0[day0["symbol"] == "ETH"].iloc[0]
    assert eth["side"] == "buy"
    assert eth["qty"] == pytest.approx(2.0)
    assert eth["price"] == pytest.approx(3000.0)
    assert eth["value"] == pytest.approx(6000.0)


def test_day1_partial_buy_only():
    trades = trades_from_positions(_make_positions())
    day1 = trades[trades["date"] == DAY1].reset_index(drop=True)

    # Only BTC changed (amount 1.0 → 1.5); ETH unchanged → no row
    assert len(day1) == 1

    btc = day1.iloc[0]
    assert btc["symbol"] == "BTC"
    assert btc["side"] == "buy"
    assert btc["qty"] == pytest.approx(0.5)
    assert btc["price"] == pytest.approx(52000.0)
    assert btc["value"] == pytest.approx(26000.0)


def test_day2_sells_with_price_fallback():
    trades = trades_from_positions(_make_positions())
    day2 = trades[trades["date"] == DAY2].reset_index(drop=True)

    # BTC fully sold (absent from day2 position dict → fallback to prior price 52000)
    # ETH partially sold (2.0 → 1.0)
    assert len(day2) == 2

    btc = day2[day2["symbol"] == "BTC"].iloc[0]
    assert btc["side"] == "sell"
    assert btc["qty"] == pytest.approx(1.5)
    assert btc["price"] == pytest.approx(52000.0)  # fallback to day1 price
    assert btc["value"] == pytest.approx(78000.0)

    eth = day2[day2["symbol"] == "ETH"].iloc[0]
    assert eth["side"] == "sell"
    assert eth["qty"] == pytest.approx(1.0)
    assert eth["price"] == pytest.approx(3200.0)
    assert eth["value"] == pytest.approx(3200.0)


def test_trade_summary():
    trades = trades_from_positions(_make_positions())
    summary = trade_summary(trades)

    assert summary["total"] == 5
    assert summary["buys"] == 3
    assert summary["sells"] == 2
    assert summary["turnover"] == pytest.approx(163200.0)
    assert summary["per_symbol"] == {"BTC": 3, "ETH": 2}


def test_empty_positions_returns_empty_dataframe():
    trades = trades_from_positions({})

    assert trades.empty
    assert list(trades.columns) == ["date", "side", "symbol", "qty", "price", "value"]


def test_empty_positions_summary():
    trades = trades_from_positions({})
    summary = trade_summary(trades)

    assert summary == {"total": 0, "buys": 0, "sells": 0, "turnover": 0.0, "per_symbol": {}}
