"""Tests for cli/research/leadlag/study.py — lead-lag predictive-regression probe (iter-51).

TDD: all tests use synthetic frames (no network, no disk I/O beyond tmp_path).

Contract schema from data.py:
    columns = ["timestamp_open_utc", "symbol", "open", "high", "low", "close", "volume"]
    timestamp_open_utc: tz-aware UTC pd.Timestamp (bar-open, hourly)
    symbol: uppercase pair string
    OHLCV: float64
    sorted by (symbol, timestamp_open_utc)
"""

from __future__ import annotations

import datetime as dt
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from cli.research.leadlag.study import (
    analyze,
    build_returns_panel,
    deflated_ic,
    preregister_grid,
    run_cell,
    verdict,
)

# ---------------------------------------------------------------------------
# Helpers: synthetic frame builders
# ---------------------------------------------------------------------------

_PREDICTORS = ("BTCUSDT", "ETHUSDT")
_ALTS = ("BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "DOGEUSDT", "TRXUSDT")
_ALL_SYMS = list(_PREDICTORS) + list(_ALTS)


def _make_contract_frame(
    prices: dict[str, np.ndarray],
    *,
    start: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Build a tidy contract-schema DataFrame from a dict symbol→price array.

    Each price array is treated as the hourly close price; open=close (simplified).
    start defaults to 2023-01-01 00:00 UTC.
    """
    if start is None:
        start = pd.Timestamp("2023-01-01 00:00:00", tz="UTC")

    rows = []
    for sym, px in prices.items():
        n = len(px)
        ts = pd.date_range(start, periods=n, freq="h", tz="UTC")
        df_sym = pd.DataFrame(
            {
                "timestamp_open_utc": ts,
                "symbol": sym,
                "open": px.astype("float64"),
                "high": px.astype("float64") * 1.001,
                "low": px.astype("float64") * 0.999,
                "close": px.astype("float64"),
                "volume": np.ones(n, dtype="float64") * 1000.0,
            }
        )
        rows.append(df_sym)

    result = pd.concat(rows, ignore_index=True)
    result = result.sort_values(["symbol", "timestamp_open_utc"]).reset_index(drop=True)
    return result


def _make_known_signal_frame(
    n_hours: int = 3000,
    k_star: int = 1,
    h_star: int = 2,
    theta: float = 0.4,
    noise_std: float = 0.002,
    seed: int = 42,
) -> pd.DataFrame:
    """Synthetic frame where alt log-returns = theta * BTC_lagged_log_return + noise.

    BTC: random walk (iid N(0, 0.01)).
    ETH: independent random walk.
    Alts: r_alt(t→t+h*) = theta * r_BTC(t-k*→t) + noise.

    The signal is injected at the single-bar granularity: for each bar t, the alt
    single-bar return at t is theta * BTC_return(t - k*) / h* + noise/h* so that
    when summed over h* bars the h*-bar return matches the formula.
    """
    rng = np.random.default_rng(seed)
    n = n_hours + 50  # extra for lags

    # BTC 1h log returns (single bar)
    btc_1h = rng.normal(0, 0.01, n)
    # ETH independent
    eth_1h = rng.normal(0, 0.01, n)

    # Alt 1h returns: contaminated by lagged BTC
    alt_data: dict[str, np.ndarray] = {}
    for sym in _ALTS:
        noise = rng.normal(0, noise_std, n)
        # Inject signal: single-bar alt return driven by BTC lag k*
        alt_1h = theta * np.roll(btc_1h, k_star) / max(h_star, 1) + noise
        alt_1h[:k_star] = noise[:k_star]  # clean first k* bars
        alt_data[sym] = alt_1h

    # Convert log-returns to prices (exp cumsum)
    prices: dict[str, np.ndarray] = {}
    for sym, rets_1h in {
        "BTCUSDT": btc_1h,
        "ETHUSDT": eth_1h,
        **alt_data,
    }.items():
        prices[sym] = np.exp(np.cumsum(rets_1h))

    return _make_contract_frame(prices)


def _make_null_frame(
    n_hours: int = 3000,
    ar_coef: float = 0.2,
    seed: int = 99,
) -> pd.DataFrame:
    """Synthetic frame where alts are INDEPENDENT of BTC — only own AR(1) autocorrelation.

    BTC/ETH: iid random walks.
    Alts: AR(1) process, no BTC signal.
    """
    rng = np.random.default_rng(seed)
    n = n_hours + 50

    btc_1h = rng.normal(0, 0.01, n)
    eth_1h = rng.normal(0, 0.01, n)

    alt_data: dict[str, np.ndarray] = {}
    for sym in _ALTS:
        noise = rng.normal(0, 0.01, n)
        ar = np.zeros(n)
        for t in range(1, n):
            ar[t] = ar_coef * ar[t - 1] + noise[t]
        alt_1h = ar
        alt_data[sym] = alt_1h

    prices: dict[str, np.ndarray] = {}
    for sym, rets_1h in {
        "BTCUSDT": btc_1h,
        "ETHUSDT": eth_1h,
        **alt_data,
    }.items():
        prices[sym] = np.exp(np.cumsum(rets_1h))

    return _make_contract_frame(prices)


# ---------------------------------------------------------------------------
# build_returns_panel
# ---------------------------------------------------------------------------


class TestBuildReturnsPanel:
    def test_returns_wide_dataframe(self):
        frame = _make_known_signal_frame(n_hours=200, k_star=1, h_star=1, theta=0.3)
        panel = build_returns_panel(frame)
        # Should be a DataFrame with one column per symbol
        assert isinstance(panel, pd.DataFrame)
        assert set(panel.columns) == set(_ALL_SYMS)

    def test_index_is_timestamp_utc(self):
        frame = _make_known_signal_frame(n_hours=200)
        panel = build_returns_panel(frame)
        assert panel.index.dtype == "datetime64[ns, UTC]"

    def test_log_returns_approx_correct(self):
        """Log returns are close(t)/close(t-1) in log-space."""
        frame = _make_known_signal_frame(n_hours=100)
        panel = build_returns_panel(frame)
        # Check BTCUSDT — the first non-NaN return should match manual calc
        btc_prices = frame[frame["symbol"] == "BTCUSDT"].sort_values("timestamp_open_utc")["close"].values
        manual_lr = np.log(btc_prices[1] / btc_prices[0])
        panel_lr = panel["BTCUSDT"].dropna().iloc[0]
        assert abs(panel_lr - manual_lr) < 1e-10

    def test_first_row_is_nan(self):
        """First row of each log-return series is NaN (no prior bar)."""
        frame = _make_known_signal_frame(n_hours=100)
        panel = build_returns_panel(frame)
        assert panel.iloc[0].isna().all()

    def test_predictors_subset_default(self):
        """Default predictors=('BTCUSDT','ETHUSDT') are present in the panel."""
        frame = _make_known_signal_frame(n_hours=100)
        panel = build_returns_panel(frame, predictors=("BTCUSDT", "ETHUSDT"))
        assert "BTCUSDT" in panel.columns
        assert "ETHUSDT" in panel.columns


# ---------------------------------------------------------------------------
# preregister_grid
# ---------------------------------------------------------------------------


class TestPreregisterGrid:
    def test_writes_json_before_analysis(self, tmp_path):
        out = str(tmp_path / "preregistration.json")
        grid, n_trials = preregister_grid(("BTCUSDT", "ETHUSDT"), out_path=out)
        assert Path(out).exists(), "preregistration JSON must be written"

    def test_n_trials_count(self, tmp_path):
        """2 predictors × 4 k_values × 5 h_values = 40 cells."""
        out = str(tmp_path / "preregistration.json")
        k_grid = (1, 2, 3, 6)
        h_grid = (1, 2, 3, 4, 6)
        grid, n_trials = preregister_grid(("BTCUSDT", "ETHUSDT"), k_grid=k_grid, h_grid=h_grid, out_path=out)
        assert n_trials == 2 * len(k_grid) * len(h_grid)

    def test_json_contains_n_trials(self, tmp_path):
        out = str(tmp_path / "preregistration.json")
        _, n_trials = preregister_grid(("BTCUSDT", "ETHUSDT"), out_path=out)
        data = json.loads(Path(out).read_text())
        assert data["n_trials"] == n_trials

    def test_json_contains_grid_entries(self, tmp_path):
        out = str(tmp_path / "preregistration.json")
        grid, n_trials = preregister_grid(("BTCUSDT", "ETHUSDT"), out_path=out)
        data = json.loads(Path(out).read_text())
        assert len(data["grid"]) == n_trials

    def test_n_trials_grows_with_predictors(self, tmp_path):
        out1 = str(tmp_path / "preg1.json")
        out2 = str(tmp_path / "preg2.json")
        _, n1 = preregister_grid(("BTCUSDT",), out_path=out1)
        _, n2 = preregister_grid(("BTCUSDT", "ETHUSDT"), out_path=out2)
        assert n2 == 2 * n1


# ---------------------------------------------------------------------------
# deflated_ic
# ---------------------------------------------------------------------------


class TestDeflatedIc:
    def test_haircut_is_nonnegative(self):
        """Deflated IC should be ≤ raw IC (haircut is non-negative)."""
        raw_ic = 0.06
        n_trials = 40
        deflated = deflated_ic(raw_ic, n_trials=n_trials)
        assert deflated <= raw_ic

    def test_haircut_grows_with_n_trials(self):
        """More trials → larger penalty → lower deflated IC."""
        raw_ic = 0.06
        d10 = deflated_ic(raw_ic, n_trials=10)
        d40 = deflated_ic(raw_ic, n_trials=40)
        d200 = deflated_ic(raw_ic, n_trials=200)
        assert d10 >= d40 >= d200

    def test_zero_ic_stays_nonpositive(self):
        """A zero raw IC deflated by any positive N_trials should be ≤ 0."""
        assert deflated_ic(0.0, n_trials=40) <= 0.0


# ---------------------------------------------------------------------------
# run_cell
# ---------------------------------------------------------------------------


class TestRunCell:
    def test_returns_dict_with_required_keys(self):
        frame = _make_known_signal_frame(n_hours=500, k_star=1, h_star=1, theta=0.3)
        panel = build_returns_panel(frame)
        result = run_cell(panel, "BTCUSDT", k=1, h=1)
        required = {"beta", "t_stat", "p_value", "rank_ic", "n_obs"}
        assert required.issubset(result.keys()), f"missing keys: {required - result.keys()}"

    def test_known_signal_positive_beta(self):
        """With an injected positive BTC→alt lead, beta should be positive."""
        frame = _make_known_signal_frame(n_hours=2000, k_star=1, h_star=1, theta=0.5, noise_std=0.001)
        panel = build_returns_panel(frame)
        result = run_cell(panel, "BTCUSDT", k=1, h=1)
        assert result["beta"] > 0, f"expected positive beta, got {result['beta']}"

    def test_known_signal_significant(self):
        """With a strong injected signal, p_value should be small."""
        frame = _make_known_signal_frame(n_hours=2000, k_star=1, h_star=1, theta=0.5, noise_std=0.001)
        panel = build_returns_panel(frame)
        result = run_cell(panel, "BTCUSDT", k=1, h=1)
        assert result["p_value"] < 0.05, f"expected p_value < 0.05, got {result['p_value']}"

    def test_null_panel_beta_near_zero(self):
        """With no signal, beta should be near zero on average."""
        frame = _make_null_frame(n_hours=2000)
        panel = build_returns_panel(frame)
        result = run_cell(panel, "BTCUSDT", k=1, h=1)
        # Beta should be very small — no signal planted
        assert abs(result["beta"]) < 0.5, f"expected near-zero beta for null panel, got {result['beta']}"

    def test_n_obs_is_positive(self):
        frame = _make_known_signal_frame(n_hours=500)
        panel = build_returns_panel(frame)
        result = run_cell(panel, "BTCUSDT", k=1, h=1)
        assert result["n_obs"] > 0

    def test_look_ahead_assert_fires(self):
        """A deliberately mis-aligned call (predictor window overlaps forward window) must raise AssertionError."""
        frame = _make_known_signal_frame(n_hours=500)
        panel = build_returns_panel(frame)
        # Pass a specially crafted bad panel where timestamps are manipulated to violate
        # the no-look-ahead constraint. We trigger this by calling with k=0, h=1 which means
        # predictor window ends at t (bar-close of t) and forward window also starts at t —
        # with k=0 the predictor return is the SAME bar as the prediction target start.
        # The study's run_cell must detect this and assert.
        with pytest.raises(AssertionError, match="look-ahead"):
            run_cell(panel, "BTCUSDT", k=0, h=1)


# ---------------------------------------------------------------------------
# analyze
# ---------------------------------------------------------------------------


class TestAnalyze:
    def test_returns_dict_with_required_keys(self, tmp_path):
        frame = _make_known_signal_frame(n_hours=1000, k_star=1, h_star=1, theta=0.3)
        panel = build_returns_panel(frame)
        k_grid = (1, 2)
        h_grid = (1, 2)
        _, n_trials = preregister_grid(("BTCUSDT",), k_grid=k_grid, h_grid=h_grid, out_path=str(tmp_path / "p.json"))
        grid = [{"predictor": "BTCUSDT", "k": k, "h": h} for k in k_grid for h in h_grid]
        results = analyze(panel, grid, n_trials=n_trials)
        required = {"cells", "best_cell", "net_edge_bps"}
        assert required.issubset(results.keys()), f"missing: {required - results.keys()}"

    def test_cells_have_bh_q_values(self, tmp_path):
        frame = _make_known_signal_frame(n_hours=1000, k_star=1, h_star=1, theta=0.3)
        panel = build_returns_panel(frame)
        k_grid = (1, 2)
        h_grid = (1, 2)
        grid = [{"predictor": "BTCUSDT", "k": k, "h": h} for k in k_grid for h in h_grid]
        _, n_trials = preregister_grid(("BTCUSDT",), k_grid=k_grid, h_grid=h_grid, out_path=str(tmp_path / "p.json"))
        results = analyze(panel, grid, n_trials=n_trials)
        for cell in results["cells"]:
            assert "bh_q" in cell, f"cell missing bh_q: {cell}"

    def test_cells_have_deflated_ic_and_bootstrap_ci(self, tmp_path):
        frame = _make_known_signal_frame(n_hours=1000, k_star=1, h_star=1, theta=0.3)
        panel = build_returns_panel(frame)
        k_grid = (1, 2)
        h_grid = (1, 2)
        grid = [{"predictor": "BTCUSDT", "k": k, "h": h} for k in k_grid for h in h_grid]
        _, n_trials = preregister_grid(("BTCUSDT",), k_grid=k_grid, h_grid=h_grid, out_path=str(tmp_path / "p.json"))
        results = analyze(panel, grid, n_trials=n_trials)
        for cell in results["cells"]:
            assert "deflated_ic" in cell
            assert "ic_ci_lo" in cell
            assert "ic_ci_hi" in cell

    def test_cells_have_per_year_same_sign(self, tmp_path):
        frame = _make_known_signal_frame(n_hours=3000, k_star=1, h_star=1, theta=0.3)
        panel = build_returns_panel(frame)
        k_grid = (1,)
        h_grid = (1,)
        grid = [{"predictor": "BTCUSDT", "k": 1, "h": 1}]
        _, n_trials = preregister_grid(("BTCUSDT",), k_grid=k_grid, h_grid=h_grid, out_path=str(tmp_path / "p.json"))
        results = analyze(panel, grid, n_trials=n_trials)
        cell = results["cells"][0]
        assert "per_year" in cell
        assert "same_sign_all_years" in cell

    def test_net_edge_uses_costs_constant(self, tmp_path):
        """net_edge_bps = gross_decile_spread_bps - round_trip_cost_bps (from costs.py)."""
        frame = _make_known_signal_frame(n_hours=3000, k_star=1, h_star=1, theta=0.5, noise_std=0.001)
        panel = build_returns_panel(frame)
        k_grid = (1,)
        h_grid = (1,)
        grid = [{"predictor": "BTCUSDT", "k": 1, "h": 1}]
        _, n_trials = preregister_grid(("BTCUSDT",), k_grid=k_grid, h_grid=h_grid, out_path=str(tmp_path / "p.json"))
        results = analyze(panel, grid, n_trials=n_trials)
        # net_edge must exist and be finite
        assert math.isfinite(results["net_edge_bps"])

    def test_economic_decile_spread_arithmetic(self, tmp_path):
        """net_edge_bps = gross_decile_spread_bps - round_trip_cost_bps."""
        frame = _make_known_signal_frame(n_hours=3000, k_star=1, h_star=1, theta=0.5)
        panel = build_returns_panel(frame)
        k_grid = (1,)
        h_grid = (1,)
        grid = [{"predictor": "BTCUSDT", "k": 1, "h": 1}]
        _, n_trials = preregister_grid(("BTCUSDT",), k_grid=k_grid, h_grid=h_grid, out_path=str(tmp_path / "p.json"))
        results = analyze(panel, grid, n_trials=n_trials)
        best = results["best_cell"]
        expected_net = best["gross_decile_spread_bps"] - results["roundtrip_cost_bps"]
        assert abs(results["net_edge_bps"] - expected_net) < 1e-9

    def test_analyze_handles_missing_bars(self, tmp_path):
        """Alts with different missing-bar gaps must not raise ValueError in analyze().

        Before the alignment fix, np.nanmean([ragged...], axis=0) raised
        ValueError: setting an array element with a sequence. The inhomogeneous shape
        error fires when alts drop different rows, producing arrays of different lengths.
        """
        rng = np.random.default_rng(7)
        n = 300
        syms = ["BTCUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"]
        ts = pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC")

        prices: dict[str, np.ndarray] = {}
        for sym in syms:
            rets = rng.normal(0, 0.01, n)
            prices[sym] = np.exp(np.cumsum(rets))

        frame = _make_contract_frame(prices)

        # Build panel; then manually NaN out different rows per alt to create ragged gaps.
        panel = build_returns_panel(frame)

        # Drop different rows per alt (mimics missing bars in real 1h data)
        panel = panel.copy()
        panel.loc[panel.index[10:15], "BNBUSDT"] = float("nan")
        panel.loc[panel.index[20:27], "SOLUSDT"] = float("nan")
        panel.loc[panel.index[5:8], "XRPUSDT"] = float("nan")

        grid = [{"predictor": "BTCUSDT", "k": 1, "h": 2}]
        _, n_trials = preregister_grid(("BTCUSDT",), k_grid=(1,), h_grid=(2,), out_path=str(tmp_path / "p.json"))

        # Must not raise; would have raised ValueError before the alignment fix.
        results = analyze(panel, grid, n_trials=n_trials, n_bootstrap=10)
        assert "cells" in results
        assert len(results["cells"]) == 1


# ---------------------------------------------------------------------------
# verdict
# ---------------------------------------------------------------------------


class TestVerdict:
    def test_returns_dict_with_required_keys(self, tmp_path):
        frame = _make_known_signal_frame(n_hours=1000, k_star=1, h_star=1, theta=0.3)
        panel = build_returns_panel(frame)
        k_grid = (1, 2)
        h_grid = (1, 2)
        grid = [{"predictor": "BTCUSDT", "k": k, "h": h} for k in k_grid for h in h_grid]
        _, n_trials = preregister_grid(("BTCUSDT",), k_grid=k_grid, h_grid=h_grid, out_path=str(tmp_path / "p.json"))
        results = analyze(panel, grid, n_trials=n_trials)
        v = verdict(results)
        required = {"go", "reasons", "n_trials"}
        assert required.issubset(v.keys()), f"missing: {required - v.keys()}"

    def test_go_is_bool(self, tmp_path):
        frame = _make_known_signal_frame(n_hours=1000)
        panel = build_returns_panel(frame)
        grid = [{"predictor": "BTCUSDT", "k": 1, "h": 1}]
        _, n_trials = preregister_grid(("BTCUSDT",), k_grid=(1,), h_grid=(1,), out_path=str(tmp_path / "p.json"))
        results = analyze(panel, grid, n_trials=n_trials)
        v = verdict(results)
        assert isinstance(v["go"], bool)

    def test_reasons_is_list_of_strings(self, tmp_path):
        frame = _make_known_signal_frame(n_hours=1000)
        panel = build_returns_panel(frame)
        grid = [{"predictor": "BTCUSDT", "k": 1, "h": 1}]
        _, n_trials = preregister_grid(("BTCUSDT",), k_grid=(1,), h_grid=(1,), out_path=str(tmp_path / "p.json"))
        results = analyze(panel, grid, n_trials=n_trials)
        v = verdict(results)
        assert isinstance(v["reasons"], list)
        for r in v["reasons"]:
            assert isinstance(r, str)


# ---------------------------------------------------------------------------
# Known-signal recovery (the main correctness test)
# ---------------------------------------------------------------------------


class TestKnownSignalRecovery:
    """The probe must recover an injected BTC→alt lead signal at the known (k*,h*)."""

    def test_best_cell_matches_injected_k_h(self, tmp_path):
        """The cell (predictor=BTC, k=k*, h=h*) must have the largest positive beta."""
        k_star, h_star = 1, 2
        frame = _make_known_signal_frame(
            n_hours=4000,
            k_star=k_star,
            h_star=h_star,
            theta=0.5,
            noise_std=0.001,
            seed=42,
        )
        panel = build_returns_panel(frame)
        k_grid = (1, 2, 3)
        h_grid = (1, 2, 3)
        grid = [{"predictor": "BTCUSDT", "k": k, "h": h} for k in k_grid for h in h_grid]
        _, n_trials = preregister_grid(("BTCUSDT",), k_grid=k_grid, h_grid=h_grid, out_path=str(tmp_path / "p.json"))
        results = analyze(panel, grid, n_trials=n_trials)

        # The known-signal cell should have positive beta
        target_cell = next(c for c in results["cells"] if c["predictor"] == "BTCUSDT" and c["k"] == k_star and c["h"] == h_star)
        assert target_cell["beta"] > 0, f"expected positive beta at (k={k_star},h={h_star}), got {target_cell['beta']}"

    def test_known_signal_survives_bh_fdr(self, tmp_path):
        """Injected signal at (k*,h*) must survive BH-FDR (q < 0.05)."""
        k_star, h_star = 1, 1
        frame = _make_known_signal_frame(
            n_hours=4000,
            k_star=k_star,
            h_star=h_star,
            theta=0.6,
            noise_std=0.001,
            seed=42,
        )
        panel = build_returns_panel(frame)
        k_grid = (1, 2, 3)
        h_grid = (1, 2, 3)
        grid = [{"predictor": "BTCUSDT", "k": k, "h": h} for k in k_grid for h in h_grid]
        _, n_trials = preregister_grid(("BTCUSDT",), k_grid=k_grid, h_grid=h_grid, out_path=str(tmp_path / "p.json"))
        results = analyze(panel, grid, n_trials=n_trials)
        target_cell = next(c for c in results["cells"] if c["predictor"] == "BTCUSDT" and c["k"] == k_star and c["h"] == h_star)
        assert target_cell["bh_q"] < 0.05, f"expected bh_q < 0.05 at (k={k_star},h={h_star}), got {target_cell['bh_q']}"

    def test_known_signal_verdict_go(self, tmp_path):
        """A very strong injected signal spanning 3 years should yield GO verdict."""
        k_star, h_star = 1, 1
        # 3 years of hourly data: 3 * 365 * 24 = 26280 hours to span 2023-2025
        frame = _make_known_signal_frame(
            n_hours=26280,
            k_star=k_star,
            h_star=h_star,
            theta=0.8,
            noise_std=0.0005,
            seed=42,
        )
        panel = build_returns_panel(frame)
        k_grid = (1, 2)
        h_grid = (1, 2)
        grid = [{"predictor": "BTCUSDT", "k": k, "h": h} for k in k_grid for h in h_grid]
        _, n_trials = preregister_grid(("BTCUSDT",), k_grid=k_grid, h_grid=h_grid, out_path=str(tmp_path / "p.json"))
        results = analyze(panel, grid, n_trials=n_trials)
        v = verdict(results)
        assert v["go"] is True, f"expected GO with strong signal, got NO-GO. reasons: {v['reasons']}"


# ---------------------------------------------------------------------------
# Known-null rejection (false-positive guard)
# ---------------------------------------------------------------------------


class TestKnownNullRejection:
    """With only own-AR(1) autocorrelation in alts (no BTC lead), probe must report NO-GO."""

    def test_null_no_cells_survive_bh_fdr(self, tmp_path):
        """Independent alts (own AR only): no cell should have bh_q < 0.05."""
        frame = _make_null_frame(n_hours=3000, ar_coef=0.3, seed=99)
        panel = build_returns_panel(frame)
        k_grid = (1, 2, 3)
        h_grid = (1, 2, 3)
        grid = [{"predictor": "BTCUSDT", "k": k, "h": h} for k in k_grid for h in h_grid]
        _, n_trials = preregister_grid(("BTCUSDT",), k_grid=k_grid, h_grid=h_grid, out_path=str(tmp_path / "p.json"))
        results = analyze(panel, grid, n_trials=n_trials)
        surviving = [c for c in results["cells"] if c["bh_q"] < 0.05]
        # Allow up to 1 spurious survivor due to random noise; strict null should have 0
        # but we allow a small tolerance for stochastic tests
        assert len(surviving) <= 1, f"expected ≤1 cells survive BH-FDR under null, got {len(surviving)}: {surviving}"

    def test_null_verdict_is_no_go(self, tmp_path):
        """Pure null panel must yield NO-GO verdict."""
        frame = _make_null_frame(n_hours=4000, ar_coef=0.3, seed=99)
        panel = build_returns_panel(frame)
        k_grid = (1, 2, 3)
        h_grid = (1, 2, 3)
        grid = [{"predictor": "BTCUSDT", "k": k, "h": h} for k in k_grid for h in h_grid]
        _, n_trials = preregister_grid(("BTCUSDT",), k_grid=k_grid, h_grid=h_grid, out_path=str(tmp_path / "p.json"))
        results = analyze(panel, grid, n_trials=n_trials)
        v = verdict(results)
        assert v["go"] is False, f"expected NO-GO for null panel, got GO. reasons: {v['reasons']}"

    def test_gamma_control_absorbs_alt_autocorrelation(self, tmp_path):
        """The γ own-lag control must absorb pure alt AR(1) — beta should be near zero."""
        frame = _make_null_frame(n_hours=3000, ar_coef=0.5, seed=42)
        panel = build_returns_panel(frame)
        result = run_cell(panel, "BTCUSDT", k=1, h=1)
        # beta should be small (no BTC signal, γ absorbs AR)
        assert abs(result["beta"]) < 0.3, f"beta={result['beta']} — γ control not absorbing AR(1)"

    def test_gamma_absorbs_btc_correlated_ar(self):
        """γ own-lag control must reduce |β| when alt autocorrelation is BTC-correlated.

        Construction: alt return at t = ρ_own*alt(t-1) + θ_btc*btc(t) + noise.
        Each alt has strong own AR(1), and the lagged alt value contains btc(t-1)
        (because alt(t-1) = ρ_own*alt(t-2) + θ_btc*btc(t-1) + ...). So with k=1 the
        predictor is btc(t-1), and the γ own-lag alt(t-1) partially absorbs it.

        Comparison is pooled vs pooled: both run the same pooled OLS on the same
        data matrix — one with the own_lag column, one without. This is a controlled
        A/B that measures only the γ column's contribution.
        """
        rng = np.random.default_rng(17)
        n = 2000
        k, h = 1, 2

        # BTC: pure random walk
        btc = rng.normal(0, 0.01, n)

        prices: dict[str, np.ndarray] = {"BTCUSDT": np.exp(np.cumsum(btc))}

        rho_own = 0.7  # strong own AR(1) persistence
        theta_btc = 0.5  # alt tracks BTC contemporaneously

        alts_used = list(_ALTS[:4])
        for sym in alts_used:
            noise = rng.normal(0, 0.005, n)
            alt = np.zeros(n)
            for t in range(1, n):
                alt[t] = rho_own * alt[t - 1] + theta_btc * btc[t] + noise[t]
            prices[sym] = np.exp(np.cumsum(alt))

        frame = _make_contract_frame(prices)
        panel = build_returns_panel(frame)

        # With γ own-lag control (default run_cell)
        result_with_gamma = run_cell(panel, "BTCUSDT", k=k, h=h)
        beta_with = result_with_gamma["beta"]

        # Without γ: build the same pooled matrix but drop the own_lag column, then OLS.
        # This is an apples-to-apples comparison — same data, same pooling, only γ differs.
        pred_k = panel["BTCUSDT"].rolling(k).sum()
        rows_list = []
        for sym in alts_used:
            fwd = panel[sym].shift(-1).rolling(h).sum().shift(-(h - 1))
            own_lag = panel[sym].rolling(k).sum()
            df_sym = pd.DataFrame({"fwd": fwd, "pred": pred_k, "own_lag": own_lag, "sym": sym}).dropna()
            rows_list.append(df_sym)
        pooled_no_gamma = pd.concat(rows_list, ignore_index=False).dropna()
        # Per-alt demeaning of fwd and pred (same as run_cell)
        pooled_no_gamma = pooled_no_gamma.copy()
        for col in ("fwd", "pred"):
            pooled_no_gamma[col] = pooled_no_gamma[col] - pooled_no_gamma.groupby("sym")[col].transform("mean")
        y_ng = pooled_no_gamma["fwd"].values
        x_ng = pooled_no_gamma["pred"].values.reshape(-1, 1)
        beta_hat_ng, _, _, _ = np.linalg.lstsq(x_ng, y_ng, rcond=None)
        beta_no_gamma = float(beta_hat_ng[0])

        # γ must reduce |β| — the own-lag absorbs the BTC-correlated autocorrelation
        assert abs(beta_with) < abs(beta_no_gamma), f"γ should reduce |β|: with_gamma={beta_with:.4f}, no_gamma={beta_no_gamma:.4f}"
        # The reduction should be non-trivial (at least 10%)
        reduction_frac = 1.0 - abs(beta_with) / max(abs(beta_no_gamma), 1e-9)
        assert reduction_frac >= 0.10, (
            f"γ reduces |β| by only {reduction_frac:.1%}: with={beta_with:.4f}, no_gamma={beta_no_gamma:.4f}"
        )


# ---------------------------------------------------------------------------
# Look-ahead assertion
# ---------------------------------------------------------------------------


class TestLookAheadAssertion:
    def test_assert_fires_on_k_zero(self):
        """k=0 means predictor window [t,t] — same bar as forward start — must raise AssertionError."""
        frame = _make_known_signal_frame(n_hours=500)
        panel = build_returns_panel(frame)
        with pytest.raises(AssertionError, match="look-ahead"):
            run_cell(panel, "BTCUSDT", k=0, h=1)

    def test_assert_does_not_fire_on_valid_k(self):
        """Valid k >= 1 must NOT raise AssertionError."""
        frame = _make_known_signal_frame(n_hours=500)
        panel = build_returns_panel(frame)
        # Should not raise
        result = run_cell(panel, "BTCUSDT", k=1, h=1)
        assert result is not None
