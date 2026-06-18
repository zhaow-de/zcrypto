import math

import numpy as np
import pytest

from cli.experiment.stats import deflated_sharpe, expected_max_sharpe, pbo_cscv, psr, sharpe


def test_sharpe_basic_and_degenerate():
    assert sharpe([1.0, 1.0, 1.0]) == 0.0  # zero variance
    assert sharpe([0.01]) == 0.0  # too short
    r = np.array([0.01, -0.005, 0.02, 0.0, 0.015])
    assert abs(sharpe(r) - r.mean() / r.std(ddof=1)) < 1e-12


def test_psr_zero_mean_is_about_half():
    r = np.random.default_rng(2).normal(0.0, 0.01, 5000)
    assert abs(psr(r) - 0.5) < 0.06  # SR ~ 0 → PSR ~ 0.5


def test_psr_grows_with_sample_length():
    short = np.random.default_rng(1).normal(0.001, 0.01, 200)
    long = np.random.default_rng(1).normal(0.001, 0.01, 6000)
    assert 0.5 < psr(short) <= 1.0
    assert psr(long) > psr(short)  # more data, same edge → higher confidence


def test_psr_degenerate():
    assert math.isnan(psr([0.01]))  # n < 2
    assert math.isnan(psr([0.01, 0.01]))  # zero variance


def test_expected_max_sharpe_grows_with_trials():
    small = expected_max_sharpe([0.0, 0.1, -0.1, 0.05])
    big = expected_max_sharpe([0.0, 0.1, -0.1, 0.05] * 25)  # more trials, same spread
    assert big > small > 0
    assert math.isnan(expected_max_sharpe([0.1]))  # n < 2


def test_deflated_sharpe_decreases_with_more_trials():
    rng = np.random.default_rng(2)
    best = rng.normal(0.001, 0.01, 1000)
    sr_best = sharpe(best)
    few = deflated_sharpe(best, [sr_best, 0.0, -0.02, 0.02])
    many = deflated_sharpe(best, [sr_best, *list(rng.normal(0, 0.05, 200))])
    assert few > many  # more trials → harder to beat the max-null → lower DSR
    assert math.isnan(deflated_sharpe(best, [sr_best]))  # n < 2 → NaN


def test_pbo_low_for_dominant_strategy():
    rng = np.random.default_rng(3)
    M = np.hstack([rng.normal(0.003, 0.01, (320, 1)), rng.normal(0.0, 0.01, (320, 4))])
    res = pbo_cscv(M, n_splits=16)
    assert res["n_combinations"] == math.comb(16, 8)
    assert res["pbo"] < 0.3  # a real edge generalizes out-of-sample


def test_pbo_high_for_pure_noise():
    M = np.random.default_rng(6).normal(0, 0.01, (320, 8))  # no real edge
    assert 0.3 < pbo_cscv(M, n_splits=16)["pbo"] <= 1.0


def test_pbo_edge_cases():
    with pytest.raises(ValueError):
        pbo_cscv(np.zeros((100, 3)), n_splits=15)  # odd
    with pytest.raises(ValueError):
        pbo_cscv(np.zeros((10, 3)), n_splits=16)  # n_splits > t
    assert math.isnan(pbo_cscv(np.zeros((100, 1)))["pbo"])  # < 2 trials
