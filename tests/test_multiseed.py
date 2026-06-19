from cli.experiment.multiseed import separation, summarize_seed_metrics


def _per_seed(vals):  # vals: list of sharpe values; fill others trivially
    return [{"ending_value": 10000 * (1 + v), "sharpe": v, "psr": 0.5, "max_drawdown": -0.5} for v in vals]


def test_summarize_basic_stats():
    s = summarize_seed_metrics(_per_seed([0.0, 0.2, 0.4]))
    assert s["sharpe"]["n"] == 3
    assert abs(s["sharpe"]["mean"] - 0.2) < 1e-9
    assert s["sharpe"]["min"] == 0.0 and s["sharpe"]["max"] == 0.4
    assert s["sharpe"]["std"] > 0


def test_separation_z():
    a = summarize_seed_metrics(_per_seed([0.5, 0.5, 0.5]))  # crossasset-like, tight
    b = summarize_seed_metrics(_per_seed([0.0, 0.0, 0.0]))  # steady-like, tight
    sep = separation(a, b, metric="sharpe")
    assert abs(sep["mean_gap"] - 0.5) < 1e-9
    assert sep["z"] > 0  # a separated above b


def test_separation_within_noise():
    a = summarize_seed_metrics(_per_seed([0.0, 0.3, -0.3, 0.4, -0.4]))
    b = summarize_seed_metrics(_per_seed([0.05, 0.25, -0.25, 0.35, -0.35]))
    sep = separation(a, b, metric="sharpe")
    assert abs(sep["z"]) < 1.0  # overlapping distributions -> not separated


def test_summarize_single_seed_std_zero():
    s = summarize_seed_metrics(_per_seed([0.3]))
    assert s["sharpe"]["n"] == 1
    assert s["sharpe"]["std"] == 0.0
    assert s["sharpe"]["mean"] == 0.3
    assert s["sharpe"]["min"] == 0.3
    assert s["sharpe"]["max"] == 0.3


def test_separation_divide_by_zero_nonzero_gap():
    # Both distributions have std==0 (single seed or identical values) but different means
    # pooled_std = 0, mean_gap != 0 -> z = inf
    a = summarize_seed_metrics(_per_seed([0.5]))
    b = summarize_seed_metrics(_per_seed([0.0]))
    sep = separation(a, b, metric="sharpe")
    assert sep["pooled_std"] == 0.0
    assert sep["z"] == float("inf")
    assert sep["mean_gap"] == 0.5


def test_separation_divide_by_zero_zero_gap():
    # Both distributions identical (std==0, gap==0) -> z = 0.0
    a = summarize_seed_metrics(_per_seed([0.3]))
    b = summarize_seed_metrics(_per_seed([0.3]))
    sep = separation(a, b, metric="sharpe")
    assert sep["pooled_std"] == 0.0
    assert sep["z"] == 0.0
    assert sep["mean_gap"] == 0.0
