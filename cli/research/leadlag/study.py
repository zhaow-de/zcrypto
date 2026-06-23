"""Lead-lag feasibility probe — analysis layer (iter-51).

Offline predictive-regression study: does BTC/ETH→alt intraday lead-lag survive
multiple-testing correction + economic cost?

Entry points:
  - run_probe(...): wires data → preregister → analyze → verdict, writes artifacts to .tmp/leadlag/
  - python -m cli.research.leadlag.study: CLI entry point (orchestrator calls this)

No qlib, no harness, no network — pure pandas/numpy/scipy.
statsmodels is NOT available; HAC (Newey-West) and clustered SEs are implemented by hand.

Input contract (from data.py):
    columns = ["timestamp_open_utc", "symbol", "open", "high", "low", "close", "volume"]
    timestamp_open_utc: tz-aware UTC Timestamp (bar-open, hourly)
    symbol: uppercase pair string
    OHLCV: float64
    sorted by (symbol, timestamp_open_utc)
    A 1h bar stamped 12:00 closes at 13:00.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd
from scipy import stats

from cli.experiment.costs import COST_CALIBRATION
from cli.experiment.stats import stationary_bootstrap_ci
from cli.logging import get_logger

logger = get_logger("research.leadlag.study")

# ---------------------------------------------------------------------------
# Cost constant (round-trip = 2 × maker_fill_haircut, in basis points)
# ---------------------------------------------------------------------------
_ROUNDTRIP_COST_BPS: float = COST_CALIBRATION["maker_fill_haircut"] * 2 * 10_000  # ~4.33 bps

# ---------------------------------------------------------------------------
# Default grid parameters
# ---------------------------------------------------------------------------
_DEFAULT_PREDICTORS = ("BTCUSDT", "ETHUSDT")
_DEFAULT_K_GRID = (1, 2, 3, 6)
_DEFAULT_H_GRID = (1, 2, 3, 4, 6)

# ---------------------------------------------------------------------------
# Targets = all symbols except predictors
# ---------------------------------------------------------------------------
_ALL_MAJORS = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "DOGEUSDT", "TRXUSDT")
# iter-52: less-liquid mid-cap alts — the slow-diffusion hypothesis's best remaining shot; all listed before 2023
_MIDCAP_ALTS = (
    "LTCUSDT",
    "BCHUSDT",
    "ATOMUSDT",
    "DOTUSDT",
    "UNIUSDT",
    "ETCUSDT",
    "FILUSDT",
    "ALGOUSDT",
    "VETUSDT",
    "NEARUSDT",
    "AAVEUSDT",
    "SANDUSDT",
    "MANAUSDT",
    "EOSUSDT",
)


def select_universe(name: str) -> tuple[tuple[str, ...], tuple[str, ...], str, str]:
    """Map a universe name to (predictors, symbols, out_dir, cache_path).

    Args:
        name: "majors" (iter-51 default) or "midcap" (iter-52 re-run).

    Returns:
        (predictors, symbols, out_dir, cache_path) where:
          - predictors: the BTC/ETH predictor tuple
          - symbols: full symbol set to fetch (predictors must be included so their returns exist)
          - out_dir: output directory for run_probe artifacts
          - cache_path: per-universe parquet cache path (under out_dir)
    """
    _PREDS = ("BTCUSDT", "ETHUSDT")
    if name == "majors":
        out_dir = ".tmp/leadlag"
        return _PREDS, _ALL_MAJORS, out_dir, f"{out_dir}/1h_klines.parquet"
    if name == "midcap":
        symbols = ("BTCUSDT", "ETHUSDT", *_MIDCAP_ALTS)
        out_dir = ".tmp/leadlag_midcap"
        return _PREDS, symbols, out_dir, f"{out_dir}/1h_klines.parquet"
    raise ValueError(f"unknown universe {name!r}; choose 'majors' or 'midcap'")


# ---------------------------------------------------------------------------
# build_returns_panel
# ---------------------------------------------------------------------------


def build_returns_panel(
    frame: pd.DataFrame,
    *,
    predictors: tuple[str, ...] = _DEFAULT_PREDICTORS,
) -> pd.DataFrame:
    """Build a wide hourly log-return panel from the contract frame.

    Returns a DataFrame indexed by timestamp_open_utc (UTC), one column per symbol.
    Values are close-to-close 1h log returns. First row is NaN (no prior bar).

    Args:
        frame: tidy contract frame with columns
               ["timestamp_open_utc", "symbol", "open", "high", "low", "close", "volume"]
        predictors: tuple of predictor symbol strings (kept as columns alongside alts)

    Returns:
        wide DataFrame, index=timestamp_open_utc (DatetimeTZDtype[ns,UTC]),
        columns=all symbols present in frame, values=float64 log returns.
    """
    wide = frame.pivot_table(index="timestamp_open_utc", columns="symbol", values="close", aggfunc="last")
    wide = wide.sort_index()
    log_returns = np.log(wide).diff()
    log_returns.index = pd.DatetimeIndex(log_returns.index, tz="UTC") if log_returns.index.tz is None else log_returns.index
    return log_returns.astype("float64")


# ---------------------------------------------------------------------------
# preregister_grid
# ---------------------------------------------------------------------------


def preregister_grid(
    predictors: Sequence[str],
    k_grid: tuple[int, ...] = _DEFAULT_K_GRID,
    h_grid: tuple[int, ...] = _DEFAULT_H_GRID,
    out_path: str = ".tmp/leadlag/preregistration.json",
) -> tuple[list[dict], int]:
    """Write the full predictor×k×h grid + N_trials to disk BEFORE any analysis.

    MUST be called before any data analysis — the file is the pre-registration record.

    Args:
        predictors: predictor symbol strings
        k_grid: lag lengths (bars) to test
        h_grid: forward horizon lengths (bars) to test
        out_path: path where the JSON is written

    Returns:
        (grid, n_trials) where grid is a list of dicts with keys {predictor, k, h}
        and n_trials = len(grid).
    """
    grid = [{"predictor": p, "k": int(k), "h": int(h)} for p in predictors for k in k_grid for h in h_grid]
    n_trials = len(grid)
    record = {
        "n_trials": n_trials,
        "predictors": list(predictors),
        "k_grid": list(k_grid),
        "h_grid": list(h_grid),
        "grid": grid,
    }
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2))
    logger.info("pre-registered %d cells → %s", n_trials, path)
    return grid, n_trials


# ---------------------------------------------------------------------------
# deflated_ic: IC analogue of deflated_sharpe
# ---------------------------------------------------------------------------


def deflated_ic(raw_ic: float, *, n_trials: int, n_obs: int = 400) -> float:
    """Deflated-for-N_trials IC haircut.

    Subtracts the expected maximum IC under the null given N_trials from the
    headline IC. The expected max IC under the null is approximated using the
    same Euler-gamma formula as expected_max_sharpe (since IC is just a
    correlation statistic which under the null has the same EVT behaviour).

    Under the null, IC ~ N(0, 1/sqrt(T)) where T = n_obs (pooled observation count = n_time_steps ×
    n_alts). The code passes the pooled count, which is correct; n_obs here is NOT the number of
    time steps alone but the total pooled row count across all alts.
    E[max IC over N_trials] = (1/sqrt(T)) * expected_max_normal_order_stat(N_trials).

    Args:
        raw_ic: headline rank IC value
        n_trials: total number of pre-registered cells (for multiple-testing correction)
        n_obs: pooled observation count (n_time_steps × n_alts); used for null IC std = 1/sqrt(n_obs)

    When N_trials < 2 returns raw_ic unchanged.
    """
    if n_trials < 2:
        return raw_ic
    # Expected maximum of N iid standard normal order statistics (EVT approximation)
    # Euler-gamma formula: E[max Z_N] ≈ (1 - γ) * Φ^{-1}(1-1/N) + γ * Φ^{-1}(1-1/(N*e))
    _EULER_GAMMA = 0.5772156649015329
    n = float(n_trials)
    z1 = float(stats.norm.ppf(1.0 - 1.0 / n))
    z2 = float(stats.norm.ppf(1.0 - 1.0 / (n * math.e)))
    expected_max_z = (1.0 - _EULER_GAMMA) * z1 + _EULER_GAMMA * z2
    # Null IC std: 1/sqrt(n_obs); use conservative floor of 400 observations minimum
    std_ic_null = 1.0 / math.sqrt(max(n_obs, 400))
    return raw_ic - expected_max_z * std_ic_null


# ---------------------------------------------------------------------------
# HAC (Newey-West) + clustered SE helpers
# ---------------------------------------------------------------------------


def _newey_west_vcov(X: np.ndarray, resid: np.ndarray, n_lags: int) -> np.ndarray:
    """Compute Newey-West HAC variance-covariance matrix.

    Args:
        X: regressor matrix (n_obs × n_params), already demeaned if needed
        resid: regression residuals (n_obs,)
        n_lags: number of lags (Bartlett kernel; use h-1 for h-step ahead returns)

    Returns:
        HAC vcov matrix (n_params × n_params)
    """
    n, p = X.shape
    # Meat: S = sum_{l=-L}^{L} w_l * Gamma_l
    # Gamma_l = (1/n) * X.T @ diag(e) @ X lagged l
    score = X * resid[:, None]  # n × p
    S = score.T @ score / n  # l=0 term
    for lag in range(1, n_lags + 1):
        w = 1.0 - lag / (n_lags + 1)  # Bartlett weight
        gamma = score[lag:].T @ score[:-lag] / n
        S += w * (gamma + gamma.T)
    XtX_inv = np.linalg.pinv(X.T @ X / n)
    return (XtX_inv @ S @ XtX_inv) / n


def _clustered_vcov(X: np.ndarray, resid: np.ndarray, cluster_ids: np.ndarray) -> np.ndarray:
    """Compute cluster-robust variance-covariance matrix (Liang-Zeger).

    Args:
        X: regressor matrix (n_obs × n_params)
        resid: regression residuals (n_obs,)
        cluster_ids: integer cluster labels (n_obs,) — cluster by hour t

    Returns:
        Cluster-robust vcov matrix (n_params × n_params)
    """
    n, p = X.shape
    score = X * resid[:, None]  # n × p
    unique_clusters = np.unique(cluster_ids)
    G = len(unique_clusters)
    # Meat: sum over clusters of (sum_{i in g} score_i)^T (sum_{i in g} score_i)
    meat = np.zeros((p, p))
    for g in unique_clusters:
        mask = cluster_ids == g
        sg = score[mask].sum(axis=0)  # p,
        meat += np.outer(sg, sg)
    # Degrees-of-freedom correction
    df_correction = (G / (G - 1)) * ((n - 1) / (n - p))
    XtX_inv = np.linalg.pinv(X.T @ X)
    return df_correction * (XtX_inv @ meat @ XtX_inv)


def _combine_vcov(vcov_hac: np.ndarray, vcov_cl: np.ndarray) -> np.ndarray:
    """Conservative combination: take element-wise maximum of HAC and clustered vcov.

    This follows the "double-cluster" spirit — use the larger SE from either approach.
    """
    return np.maximum(vcov_hac, vcov_cl)


# ---------------------------------------------------------------------------
# run_cell: the core regression
# ---------------------------------------------------------------------------


def run_cell(
    panel: pd.DataFrame,
    predictor: str,
    k: int,
    h: int,
) -> dict:
    """Run a single pooled predictive regression cell.

    Model (per alt i, pooled):
        r_alt,i(t→t+h) = α_i + β·r_pred(t-k→t) + γ·r_alt,i(t-k→t) + ε

    Alt fixed effects via per-alt demeaning. Newey-West HAC SEs (lag=h-1) +
    timestamp-clustered SEs; conservative combination (element-wise maximum).

    LOOK-AHEAD ASSERTION:
        The predictor return r_pred(t-k→t) is known at the close of bar t (= bar-open(t) + 1h).
        The forward alt return r_alt,i(t→t+h) starts at the same close of bar t.
        So predictor_window_close_time == forward_window_start_time — valid (zero gap is OK).
        k=0 would mean predictor window = same bar as the prediction target → look-ahead.
        assert k >= 1 with message "look-ahead" to fire AssertionError on k=0.

    Args:
        panel: wide log-return panel (index=timestamp_utc, columns=symbols)
        predictor: predictor symbol (e.g. "BTCUSDT")
        k: lag in bars (must be >= 1)
        h: forward horizon in bars (must be >= 1)

    Returns:
        dict with keys: beta, t_stat, p_value, rank_ic, n_obs
    """
    # LOOK-AHEAD guard — k=0 means predictor window is the current bar, same as forward start
    assert k >= 1, "look-ahead: k must be >= 1 (predictor window must precede forward window)"

    # Targets = all symbols except the predictor
    targets = [col for col in panel.columns if col != predictor]

    # Compute rolling sums for k-period and h-period returns
    # k-period predictor return at time t: sum of 1h log-returns from t-k+1 to t (inclusive)
    # This is known at close of bar t (= open(t) + 1h)
    pred_k = panel[predictor].rolling(k).sum()  # r_pred(t-k→t) known at close of t

    # h-period forward alt return starting from close of t: sum of 1h log-returns t+1..t+h
    # bar t+1 has open = close of bar t, so r_alt(t→t+h) = sum of 1h rets from t+1 to t+h
    # We shift by -h to align: alt_fwd[t] = sum of returns from t+1 to t+h
    # = panel[alt].shift(-h).rolling(h).sum() — but easier: rolling(h).sum().shift(-h)
    # Actually: forward h-bar return = log(close[t+h] / close[t]) = rolling(h).sum() shifted
    alt_fwd: dict[str, pd.Series] = {}
    for sym in targets:
        # r_alt(t→t+h): the return from close of t to close of t+h
        # = sum of 1h log-returns at bars t+1, t+2, ..., t+h
        # = rolling(h).sum() shifted back by h (so value at t is sum of next h bars)
        fwd = panel[sym].shift(-1).rolling(h).sum().shift(-(h - 1))
        # Equivalent: shift by -1 first (bar t+1), then rolling h, then shift back h-1
        # Simpler: fwd[t] = sum(panel[sym][t+1 : t+h+1])
        alt_fwd[sym] = fwd

    # k-period own-lag alt return (the γ control): same window as predictor
    alt_lag: dict[str, pd.Series] = {sym: panel[sym].rolling(k).sum() for sym in targets}

    # Build pooled OLS matrices
    rows_list = []
    for sym in targets:
        df_sym = pd.DataFrame(
            {
                "fwd": alt_fwd[sym],
                "pred": pred_k,
                "own_lag": alt_lag[sym],
                "sym": sym,
            }
        )
        df_sym = df_sym.dropna()
        rows_list.append(df_sym)

    if not rows_list:
        return {"beta": float("nan"), "t_stat": float("nan"), "p_value": 1.0, "rank_ic": float("nan"), "n_obs": 0}

    pooled = pd.concat(rows_list, ignore_index=False)
    pooled = pooled.dropna()

    if len(pooled) < 10:
        return {"beta": float("nan"), "t_stat": float("nan"), "p_value": 1.0, "rank_ic": float("nan"), "n_obs": len(pooled)}

    # Per-alt demeaning (fixed effects)
    pooled = pooled.copy()
    for col in ("fwd", "pred", "own_lag"):
        pooled[col] = pooled[col] - pooled.groupby("sym")[col].transform("mean")

    # OLS: y = β·x_pred + γ·x_own + ε (no intercept after demeaning)
    y = pooled["fwd"].values
    X = np.column_stack([pooled["pred"].values, pooled["own_lag"].values])
    n_obs = len(y)

    # OLS coefficients
    beta_hat, _, _, _ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta_hat

    # Timestamp cluster IDs (cluster by the index timestamp — the hour t)
    ts_index = pooled.index
    # Convert timestamps to integer codes for clustering
    unique_ts, cluster_ids = np.unique(ts_index, return_inverse=True)

    # HAC Newey-West (lag = h-1, minimum 0)
    hac_lags = max(h - 1, 0)
    if hac_lags == 0:
        # OLS standard errors (no autocorrelation correction needed)
        resid_var = float(np.dot(resid, resid)) / max(n_obs - X.shape[1], 1)
        XtX_inv = np.linalg.pinv(X.T @ X)
        vcov_hac = resid_var * XtX_inv
    else:
        vcov_hac = _newey_west_vcov(X, resid, hac_lags)

    # Clustered SEs (cluster by hour t — all 8 alts at same hour share BTC shock)
    vcov_cl = _clustered_vcov(X, resid, cluster_ids)

    # Conservative combination: element-wise maximum
    vcov_combined = _combine_vcov(vcov_hac, vcov_cl)

    # Extract beta (coefficient on predictor, index 0) stats
    beta = float(beta_hat[0])
    se_beta = float(math.sqrt(max(vcov_combined[0, 0], 0.0)))
    if se_beta == 0 or not math.isfinite(se_beta):
        t_stat = float("nan")
        p_value = 1.0
    else:
        t_stat = beta / se_beta
        # Two-sided p-value (use normal approx for large n)
        p_value = float(2.0 * stats.norm.sf(abs(t_stat)))

    # Cross-sectional rank IC (secondary metric)
    # Compute per-timestamp: pred signal vs cross-section of alt fwd returns
    ic_vals = []
    ts_vals = pd.DatetimeIndex(pooled.index).unique()
    for ts in ts_vals:
        mask = pooled.index == ts
        subset = pooled[mask]
        if len(subset) < 2:
            continue
        pred_val = pred_k.get(ts, float("nan")) if hasattr(ts, "floor") else float("nan")
        if pd.isna(pred_val):
            continue
        alt_rets = subset["fwd"].values
        if len(alt_rets) < 2:
            continue
        # Spearman rank IC between predictor signal (scalar, broadcast) and cross-section
        # Since pred is scalar, IC = sign(pred) * mean(sign(alt_rets)) [normalized cross-sectional IC]
        ic_vals.append(float(np.sign(pred_val) * np.mean(np.sign(alt_rets))))

    rank_ic = float(np.nanmean(ic_vals)) if ic_vals else float("nan")

    return {
        "beta": beta,
        "t_stat": float(t_stat),
        "p_value": p_value,
        "rank_ic": rank_ic,
        "n_obs": n_obs,
    }


# ---------------------------------------------------------------------------
# BH-FDR correction
# ---------------------------------------------------------------------------


def _bh_fdr(p_values: list[float]) -> list[float]:
    """Benjamini-Hochberg FDR correction. Returns q-values same length as p_values."""
    n = len(p_values)
    if n == 0:
        return []
    idx = np.argsort(p_values)
    p_sorted = np.array(p_values)[idx]
    q_sorted = np.minimum(1.0, p_sorted * n / (np.arange(1, n + 1)))
    # Enforce monotonicity (take cumulative min from right)
    for i in range(n - 2, -1, -1):
        q_sorted[i] = min(q_sorted[i], q_sorted[i + 1])
    q = np.empty(n)
    q[idx] = q_sorted
    return q.tolist()


# ---------------------------------------------------------------------------
# analyze: run all cells + multiple-testing corrections + economic metrics
# ---------------------------------------------------------------------------


def analyze(
    panel: pd.DataFrame,
    grid: list[dict],
    *,
    n_trials: int,
    n_bootstrap: int = 500,
    bootstrap_seed: int = 42,
) -> dict:
    """Run all cells in the pre-registered grid and compute multiple-testing corrections.

    Steps:
      1. Run run_cell for every (predictor, k, h) in grid.
      2. BH-FDR q-values across all cells.
      3. Deflated-for-N_trials IC haircut on rank_ic of each cell.
      4. Stationary-bootstrap 95% CI on the rank IC series for each cell.
      5. Per-year (2023/24/25) split: β sign per year + same_sign_all_years flag.
      6. Economic: top-vs-bottom BTC-impulse-decile forward-alt-return spread (bps)
         for the best cell, vs round-trip cost.
      7. Non-overlapping cross-check (sample every h hours) for the best cell.

    Args:
        panel: wide log-return panel
        grid: list of dicts with keys {predictor, k, h}
        n_trials: from preregister_grid (for deflated IC)
        n_bootstrap: number of bootstrap resamples for CI
        bootstrap_seed: RNG seed for bootstrap

    Returns:
        dict with keys: cells, best_cell, net_edge_bps, roundtrip_cost_bps
    """
    # Step 1: run all cells
    cells = []
    for cell in grid:
        r = run_cell(panel, cell["predictor"], k=cell["k"], h=cell["h"])
        cells.append({**cell, **r})
        logger.debug("cell pred=%s k=%d h=%d: β=%.4f p=%.4f", cell["predictor"], cell["k"], cell["h"], r["beta"], r["p_value"])

    # Step 2: BH-FDR q-values
    p_vals = [c["p_value"] for c in cells]
    q_vals = _bh_fdr(p_vals)
    for i, cell in enumerate(cells):
        cell["bh_q"] = q_vals[i]

    # Step 3: Deflated IC + bootstrap CI per cell
    for cell in cells:
        raw_ic = cell["rank_ic"] if math.isfinite(cell.get("rank_ic", float("nan"))) else 0.0
        cell["deflated_ic"] = deflated_ic(raw_ic, n_trials=n_trials, n_obs=cell.get("n_obs", 400))

        # Bootstrap CI on the rank IC series
        # We reconstruct a per-timestamp IC series for this cell to bootstrap on
        pred = cell["predictor"]
        k, h = cell["k"], cell["h"]
        targets = [col for col in panel.columns if col != pred]
        pred_k = panel[pred].rolling(k).sum()

        ic_ts_dict: dict[str, pd.Series] = {}
        for sym in targets:
            fwd = panel[sym].shift(-1).rolling(h).sum().shift(-(h - 1))
            df_pair = pd.DataFrame({"fwd": fwd, "pred": pred_k}).dropna()
            if len(df_pair) < 10:
                continue
            ic_ts_dict[sym] = pd.Series(df_pair["fwd"].values * np.sign(df_pair["pred"].values), index=df_pair.index)

        if ic_ts_dict:
            ic_df = pd.DataFrame(ic_ts_dict)
            ic_series = ic_df.mean(axis=1).dropna().values
            ci = stationary_bootstrap_ci(
                ic_series,
                block_len=max(h, 1),
                n_resamples=n_bootstrap,
                statistic=lambda x: float(np.nanmean(x)),
                seed=bootstrap_seed,
            )
            cell["ic_ci_lo"] = ci["lo"]
            cell["ic_ci_hi"] = ci["hi"]
        else:
            cell["ic_ci_lo"] = float("nan")
            cell["ic_ci_hi"] = float("nan")

    # Step 4 (within step 3 above for each cell): per-year split
    years = [2023, 2024, 2025]
    for cell in cells:
        pred = cell["predictor"]
        k, h = cell["k"], cell["h"]
        per_year = {}
        for yr in years:
            yr_start = pd.Timestamp(f"{yr}-01-01", tz="UTC")
            yr_end = pd.Timestamp(f"{yr}-12-31 23:59:59", tz="UTC")
            sub = panel.loc[yr_start:yr_end]
            if len(sub) < 10:
                per_year[yr] = {"beta": float("nan"), "n_obs": 0}
                continue
            r_yr = run_cell(sub, pred, k=k, h=h)
            per_year[yr] = {"beta": r_yr["beta"], "n_obs": r_yr["n_obs"]}
        cell["per_year"] = per_year
        signs = [int(np.sign(per_year[yr]["beta"])) for yr in years if math.isfinite(per_year[yr]["beta"])]
        cell["same_sign_all_years"] = len(signs) >= 2 and len(set(signs)) == 1

    # Step 5: pick best cell (lowest BH q among positive-beta cells, then by |IC|)
    positive_cells = [c for c in cells if c["beta"] > 0]
    if positive_cells:
        best_cell = min(positive_cells, key=lambda c: (c["bh_q"], -abs(c.get("rank_ic", 0.0) or 0.0)))
    elif cells:
        best_cell = min(cells, key=lambda c: c["bh_q"])
    else:
        best_cell = {}

    # Step 6: economic decile spread for best cell
    gross_decile_spread_bps = 0.0
    if best_cell:
        pred = best_cell["predictor"]
        k, h = best_cell["k"], best_cell["h"]
        targets = [col for col in panel.columns if col != pred]
        pred_k = panel[pred].rolling(k).sum().dropna()
        gross_spread = _compute_decile_spread(panel, pred_k, targets, h)
        gross_decile_spread_bps = gross_spread * 10_000  # convert to bps
        best_cell["gross_decile_spread_bps"] = gross_decile_spread_bps

    roundtrip_cost_bps = _ROUNDTRIP_COST_BPS
    net_edge_bps = gross_decile_spread_bps - roundtrip_cost_bps

    # Step 7: non-overlapping cross-check for best cell (sample every h hours)
    if best_cell:
        h = best_cell["h"]
        # Subsample every h-th row to avoid overlap
        panel_nonoverlap = panel.iloc[::h]
        r_nonoverlap = run_cell(panel_nonoverlap, best_cell["predictor"], k=best_cell["k"], h=1)
        best_cell["nonoverlap_beta"] = r_nonoverlap["beta"]
        best_cell["nonoverlap_p"] = r_nonoverlap["p_value"]

    return {
        "cells": cells,
        "best_cell": best_cell,
        "net_edge_bps": net_edge_bps,
        "roundtrip_cost_bps": roundtrip_cost_bps,
    }


def _compute_decile_spread(
    panel: pd.DataFrame,
    pred_series: pd.Series,
    targets: list[str],
    h: int,
) -> float:
    """Compute top-vs-bottom BTC-impulse-decile forward-alt-return spread (fractional).

    Returns the mean forward alt return in the top decile of predictor signal minus
    the mean forward alt return in the bottom decile.
    """
    fwd_all = []
    for sym in targets:
        fwd = panel[sym].shift(-1).rolling(h).sum().shift(-(h - 1))
        df_pair = pd.DataFrame({"pred": pred_series, "fwd": fwd}).dropna()
        if len(df_pair) < 20:
            continue
        fwd_all.append(df_pair)

    if not fwd_all:
        return 0.0

    combined = pd.concat(fwd_all, ignore_index=True)
    if len(combined) < 20:
        return 0.0

    combined = combined.dropna()
    pred_vals = combined["pred"].values
    fwd_vals = combined["fwd"].values

    # Decile thresholds
    q10 = np.percentile(pred_vals, 10)
    q90 = np.percentile(pred_vals, 90)

    top_mask = pred_vals >= q90
    bot_mask = pred_vals <= q10

    if top_mask.sum() == 0 or bot_mask.sum() == 0:
        return 0.0

    spread = float(np.mean(fwd_vals[top_mask]) - np.mean(fwd_vals[bot_mask]))
    return spread


# ---------------------------------------------------------------------------
# verdict: 4-condition GO/NO-GO
# ---------------------------------------------------------------------------


def verdict(results: dict) -> dict:
    """Apply the 4-condition GO/NO-GO gate from the spec.

    Conditions (ALL must pass for GO):
    1. Statistical: headline pooled β has bh_q < 0.05 AND deflated_ic > 0
       AND bootstrap CI lo > 0.
    2. Regime-stable: same sign across 2023/24/25 (same_sign_all_years = True).
    3. Economic: decile spread > ~3× round-trip (~13–15 bps gross); rank_ic ≳ 0.03.
    4. Coherent decay: (secondary check — if multiple h values, IC should decay).
       For single-cell grids we skip this check.

    Reads verdict on the DEFLATED / lower-CI number net of cost, NEVER the peak.

    Args:
        results: output from analyze()

    Returns:
        dict with keys: go (bool), reasons (list[str]), n_trials (int),
                        headline (dict with key metrics)
    """
    cells = results.get("cells", [])
    best = results.get("best_cell", {})
    net_edge_bps = results.get("net_edge_bps", 0.0)
    roundtrip_cost_bps = results.get("roundtrip_cost_bps", _ROUNDTRIP_COST_BPS)
    n_trials = len(cells)

    reasons: list[str] = []
    conditions: dict[str, bool] = {}

    if not best:
        return {
            "go": False,
            "reasons": ["no cells in results"],
            "n_trials": n_trials,
            "headline": {},
        }

    # Condition 1: Statistical survival
    bh_q = best.get("bh_q", 1.0)
    deflated = best.get("deflated_ic", float("-inf"))
    ci_lo = best.get("ic_ci_lo", float("-inf"))
    stat_pass = (bh_q < 0.05) and (deflated > 0) and (math.isfinite(ci_lo) and ci_lo > 0)
    conditions["statistical"] = stat_pass
    if stat_pass:
        reasons.append(f"PASS stat: bh_q={bh_q:.4f} < 0.05, deflated_ic={deflated:.4f} > 0, ci_lo={ci_lo:.4f} > 0")
    else:
        reasons.append(f"FAIL stat: bh_q={bh_q:.4f}, deflated_ic={deflated:.4f}, ci_lo={ci_lo:.4f}")

    # Condition 2: Regime stability (same sign across years)
    same_sign = best.get("same_sign_all_years", False)
    conditions["regime_stable"] = same_sign
    per_year = best.get("per_year", {})
    year_betas = {yr: per_year.get(yr, {}).get("beta", float("nan")) for yr in [2023, 2024, 2025]}
    if same_sign:
        reasons.append(f"PASS regime: same sign 2023/24/25. betas={year_betas}")
    else:
        reasons.append(f"FAIL regime: sign flip across years. betas={year_betas}")

    # Condition 3: Economic relevance
    gross_bps = best.get("gross_decile_spread_bps", 0.0)
    rank_ic = best.get("rank_ic", 0.0) or 0.0
    min_gross = 3.0 * roundtrip_cost_bps  # ~3× round-trip
    econ_pass = (gross_bps > min_gross) and (rank_ic >= 0.03)
    conditions["economic"] = econ_pass
    if econ_pass:
        reasons.append(
            f"PASS econ: gross={gross_bps:.1f}bps > 3×rt={min_gross:.1f}bps, "
            f"rank_ic={rank_ic:.4f} ≥ 0.03, net_edge={net_edge_bps:.1f}bps"
        )
    else:
        reasons.append(
            f"FAIL econ: gross={gross_bps:.1f}bps (need >{min_gross:.1f}bps), "
            f"rank_ic={rank_ic:.4f} (need ≥0.03), net_edge={net_edge_bps:.1f}bps"
        )

    # Condition 4: Coherent decay (IC rises over h=1–3 then decays)
    # Check if there are multiple h values for the best predictor + k
    pred = best.get("predictor")
    k = best.get("k")
    h_cells = [(c["h"], c.get("rank_ic", 0.0) or 0.0) for c in cells if c.get("predictor") == pred and c.get("k") == k]
    h_cells.sort(key=lambda x: x[0])
    if len(h_cells) >= 3:
        ic_vals = [ic for _, ic in h_cells]
        # Look for rise then decay: max should not be at h=1 or the last h
        max_idx = int(np.argmax(ic_vals))
        decay_pass = 0 < max_idx < len(ic_vals) - 1
        conditions["coherent_decay"] = decay_pass
        if decay_pass:
            reasons.append(f"PASS decay: IC peaks at h={h_cells[max_idx][0]} (not first/last)")
        else:
            reasons.append(f"FAIL decay: IC does not peak in middle (values={ic_vals})")
    else:
        # Insufficient h values — skip this condition (count as pass to not block single-cell grids)
        conditions["coherent_decay"] = True
        reasons.append("SKIP decay: insufficient h values to assess coherent decay profile")

    go = all(conditions.values())

    headline = {
        "predictor": pred,
        "k": k,
        "h": best.get("h"),
        "beta": best.get("beta"),
        "bh_q": bh_q,
        "deflated_ic": deflated,
        "ic_ci_lo": ci_lo,
        "ic_ci_hi": best.get("ic_ci_hi"),
        "rank_ic": rank_ic,
        "gross_decile_spread_bps": gross_bps,
        "net_edge_bps": net_edge_bps,
        "same_sign_all_years": same_sign,
    }

    logger.info("verdict: %s | n_trials=%d | %s", "GO" if go else "NO-GO", n_trials, " | ".join(reasons))

    return {
        "go": go,
        "reasons": reasons,
        "n_trials": n_trials,
        "headline": headline,
    }


# ---------------------------------------------------------------------------
# run_probe: entry-point orchestrator
# ---------------------------------------------------------------------------


def run_probe(
    frame: pd.DataFrame,
    *,
    predictors: tuple[str, ...] = _DEFAULT_PREDICTORS,
    k_grid: tuple[int, ...] = _DEFAULT_K_GRID,
    h_grid: tuple[int, ...] = _DEFAULT_H_GRID,
    out_dir: str = ".tmp/leadlag",
    n_bootstrap: int = 500,
    bootstrap_seed: int = 42,
) -> dict:
    """Full probe: preregister → build_panel → analyze → verdict → save artifacts.

    Writes to out_dir/:
      - preregistration.json (written first, before any analysis)
      - results.json (full results dict)
      - verdict.json (the GO/NO-GO dict)
      - plots (IC-decay, heatmap, rolling IC, cross-correlation) — requires plotly

    Args:
        frame: contract frame from fetch_1h_klines
        predictors: predictor symbols
        k_grid: lag grid
        h_grid: forward horizon grid
        out_dir: output directory
        n_bootstrap: bootstrap resamples for CI
        bootstrap_seed: RNG seed

    Returns:
        verdict dict (GO/NO-GO + reasons + headline numbers)
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    # Pre-register BEFORE reading data
    grid, n_trials = preregister_grid(
        predictors,
        k_grid=k_grid,
        h_grid=h_grid,
        out_path=str(out / "preregistration.json"),
    )

    # Build returns panel
    logger.info("building returns panel for %d symbols", len(frame["symbol"].unique()))
    panel = build_returns_panel(frame, predictors=predictors)

    # Run analysis
    logger.info("running %d regression cells", n_trials)
    results = analyze(panel, grid, n_trials=n_trials, n_bootstrap=n_bootstrap, bootstrap_seed=bootstrap_seed)

    # Get verdict
    v = verdict(results)

    # Serialize results (convert non-JSON-serializable types)
    def _json_safe(obj):
        if isinstance(obj, (np.integer, np.floating)):
            return float(obj)
        if isinstance(obj, np.bool_):
            return bool(obj)
        if isinstance(obj, dict):
            return {k: _json_safe(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_json_safe(x) for x in obj]
        return obj

    # Save results
    results_path = out / "results.json"
    safe_results = _json_safe(
        {
            "cells": results["cells"],
            "net_edge_bps": results["net_edge_bps"],
            "roundtrip_cost_bps": results["roundtrip_cost_bps"],
        }
    )
    results_path.write_text(json.dumps(safe_results, indent=2))
    logger.info("wrote results to %s", results_path)

    verdict_path = out / "verdict.json"
    verdict_path.write_text(json.dumps(_json_safe(v), indent=2))
    logger.info("wrote verdict to %s (GO=%s)", verdict_path, v["go"])

    # Print summary tables
    _print_headline_table(results["cells"])
    _print_verdict(v)

    # Plots (best-effort — skip if plotly is unavailable)
    try:
        _write_plots(panel, results, grid, out_dir=out_dir)
    except Exception as e:
        logger.warning("plots skipped: %s", e)

    return v


def _print_headline_table(cells: list[dict]) -> None:
    """Print the headline results table to stdout."""
    print("\n=== Lead-Lag Probe: Headline Results ===")
    print(f"{'Predictor':<10} {'k':>3} {'h':>3} {'beta':>8} {'t-stat':>8} {'p':>8} {'bh_q':>8} {'IC':>8} {'defl_IC':>8}")
    print("-" * 80)
    for c in sorted(cells, key=lambda x: x.get("bh_q", 1.0)):
        print(
            f"{c['predictor']:<10} {c['k']:>3d} {c['h']:>3d} "
            f"{c.get('beta', float('nan')):>8.4f} {c.get('t_stat', float('nan')):>8.3f} "
            f"{c.get('p_value', 1.0):>8.4f} {c.get('bh_q', 1.0):>8.4f} "
            f"{c.get('rank_ic', float('nan')):>8.4f} {c.get('deflated_ic', float('nan')):>8.4f}"
        )


def _print_verdict(v: dict) -> None:
    """Print the GO/NO-GO verdict to stdout."""
    print(f"\n=== VERDICT: {'GO' if v['go'] else 'NO-GO'} ===")
    print(f"N_trials: {v['n_trials']}")
    for r in v["reasons"]:
        print(f"  {r}")
    h = v.get("headline", {})
    if h:
        print(f"\nHeadline cell: predictor={h.get('predictor')} k={h.get('k')} h={h.get('h')}")
        print(f"  beta={h.get('beta', float('nan')):.4f}  bh_q={h.get('bh_q', 1.0):.4f}")
        print(
            f"  deflated_ic={h.get('deflated_ic', float('nan')):.4f}  ci=[{h.get('ic_ci_lo', float('nan')):.4f}, {h.get('ic_ci_hi', float('nan')):.4f}]"
        )
        print(f"  gross_decile_spread={h.get('gross_decile_spread_bps', 0.0):.1f}bps  net_edge={h.get('net_edge_bps', 0.0):.1f}bps")


def _write_plots(panel: pd.DataFrame, results: dict, grid: list[dict], *, out_dir: str) -> None:
    """Write diagnostic plots to out_dir. Requires plotly."""
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    cells = results["cells"]
    out = Path(out_dir)

    # Plot 1: IC-decay vs h per predictor and k
    preds = list(dict.fromkeys(c["predictor"] for c in cells))
    ks = sorted(set(c["k"] for c in cells))
    fig1 = go.Figure()
    for pred in preds:
        for k in ks:
            h_ic = [(c["h"], c.get("rank_ic", 0.0) or 0.0) for c in cells if c["predictor"] == pred and c["k"] == k]
            h_ic.sort()
            if h_ic:
                hs, ics = zip(*h_ic)
                fig1.add_trace(go.Scatter(x=list(hs), y=list(ics), mode="lines+markers", name=f"{pred} k={k}"))
    fig1.update_layout(title="IC Decay vs h per (predictor, k)", xaxis_title="h (forward bars)", yaxis_title="Rank IC")
    fig1.write_html(str(out / "ic_decay.html"))

    # Plot 2: k×h heatmap (beta values) for the best predictor
    best = results.get("best_cell", {})
    if best:
        pred = best["predictor"]
        pred_cells = [c for c in cells if c["predictor"] == pred]
        ks_sorted = sorted(set(c["k"] for c in pred_cells))
        hs_sorted = sorted(set(c["h"] for c in pred_cells))
        z = [
            [next((c["beta"] for c in pred_cells if c["k"] == k and c["h"] == h), float("nan")) for h in hs_sorted]
            for k in ks_sorted
        ]
        fig2 = go.Figure(
            data=go.Heatmap(z=z, x=[str(h) for h in hs_sorted], y=[str(k) for k in ks_sorted], colorscale="RdBu", zmid=0)
        )
        fig2.update_layout(title=f"β heatmap: {pred}", xaxis_title="h", yaxis_title="k")
        fig2.write_html(str(out / "beta_heatmap.html"))

    # Plot 3: rolling-60d IC of best cell
    if best:
        pred = best["predictor"]
        k, h = best["k"], best["h"]
        targets = [col for col in panel.columns if col != pred]
        pred_k = panel[pred].rolling(k).sum()
        ic_ts = pd.Series(dtype="float64")
        for sym in targets:
            fwd = panel[sym].shift(-1).rolling(h).sum().shift(-(h - 1))
            df_p = pd.DataFrame({"pred": pred_k, "fwd": fwd}).dropna()
            ic = df_p["fwd"] * np.sign(df_p["pred"])
            ic_ts = ic_ts.add(ic, fill_value=0.0)
        ic_ts = ic_ts / len(targets)
        rolling_ic = ic_ts.rolling(60 * 24).mean()  # 60 days = 60*24 hours
        fig3 = go.Figure(go.Scatter(x=rolling_ic.index.astype(str), y=rolling_ic.values, mode="lines"))
        fig3.update_layout(title=f"Rolling-60d IC: {pred} k={k} h={h}", xaxis_title="Time", yaxis_title="IC (rolling 60d)")
        fig3.write_html(str(out / "rolling_ic.html"))

    # Plot 4: cross-correlation pre-screen heatmap
    preds_list = list(dict.fromkeys(c["predictor"] for c in grid))
    alts = [col for col in panel.columns if col not in preds_list]
    lags = list(range(-6, 7))
    for pred in preds_list[:1]:  # first predictor only
        z_cc = []
        for sym in alts[:8]:
            row = []
            for lag in lags:
                s1 = panel[pred].dropna()
                s2 = panel[sym].dropna()
                aligned = pd.DataFrame({"p": s1, "a": s2}).dropna()
                if len(aligned) < 20:
                    row.append(float("nan"))
                    continue
                shifted_a = aligned["a"].shift(-lag)
                cc_df = pd.DataFrame({"p": aligned["p"], "sa": shifted_a}).dropna()
                if len(cc_df) < 10:
                    row.append(float("nan"))
                    continue
                rho, _ = stats.pearsonr(cc_df["p"].values, cc_df["sa"].values)
                row.append(float(rho))
            z_cc.append(row)
        fig4 = go.Figure(data=go.Heatmap(z=z_cc, x=[str(lg) for lg in lags], y=alts[:8], colorscale="RdBu", zmid=0))
        fig4.update_layout(title=f"Cross-correlation pre-screen: {pred}", xaxis_title="Lag (hours)", yaxis_title="Alt")
        fig4.write_html(str(out / f"crosscorr_{pred}.html"))


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import datetime as dt
    import sys

    from cli.research.leadlag.data import fetch_1h_klines

    _START = dt.date(2023, 1, 1)
    _END = dt.date(2025, 12, 31)

    name = sys.argv[1] if len(sys.argv) > 1 else "majors"
    predictors, symbols, out_dir, cache_path = select_universe(name)

    logger.info("fetching 1h klines for universe=%r (%d symbols) %s .. %s", name, len(symbols), _START, _END)
    frame = fetch_1h_klines(list(symbols), _START, _END, cache_path=cache_path)

    v = run_probe(frame, predictors=predictors, out_dir=out_dir)
    sys.exit(0 if v["go"] else 1)
