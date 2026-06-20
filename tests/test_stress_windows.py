import datetime as dt

from cli.stress.windows import PURGE_DAYS, build_oos_windows

_STARTS = ["2022-01-01", "2023-01-01", "2024-01-01", "2025-01-01"]


def _w():
    return build_oos_windows(_STARTS, data_start="2020-01-01", data_end="2026-06-15")


def test_one_window_per_test_start_labeled_by_year():
    w = _w()
    assert [x["label"] for x in w] == ["oos_2022", "oos_2023", "oos_2024", "oos_2025"]


def test_train_always_starts_at_data_start_expanding():
    assert all(x["train"][0] == "2020-01-01" for x in _w())


def test_train_ends_purge_days_before_test_start_leak_safe():
    for x in _w():
        train_end = dt.date.fromisoformat(x["train"][1])
        test_start = dt.date.fromisoformat(x["test"][0])
        assert (test_start - train_end).days == PURGE_DAYS  # strictly before, by the purge


def test_test_windows_are_contiguous_annual_last_to_data_end():
    w = _w()
    assert w[0]["test"] == ("2022-01-01", "2022-12-31")
    assert w[1]["test"] == ("2023-01-01", "2023-12-31")
    assert w[2]["test"] == ("2024-01-01", "2024-12-31")
    assert w[3]["test"] == ("2025-01-01", "2026-06-15")  # last → data_end (the iter-21 holdout)


def test_valid_sits_inside_the_purge_gap():
    for x in _w():
        vs, ve = dt.date.fromisoformat(x["valid"][0]), dt.date.fromisoformat(x["valid"][1])
        train_end = dt.date.fromisoformat(x["train"][1])
        test_start = dt.date.fromisoformat(x["test"][0])
        assert train_end < vs <= ve < test_start  # valid strictly between train and test
