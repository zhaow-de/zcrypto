from cli.experiment.walkforward import build_wf_periods


def test_quarterly_expanding_covers_test_window():
    periods = build_wf_periods("2020-01-01", "2025-01-01", "2025-12-31", freq="quarter", window="expanding")
    assert len(periods) == 4
    # first predict quarter
    assert periods[0][1] == ("2025-01-01", "2025-03-31")
    # last predict quarter clamped to test_end
    assert periods[-1][1][1] == "2025-12-31"
    # expanding train always starts at train_start
    assert all(tr[0] == "2020-01-01" for tr, _ in periods)


def test_purge_gap_between_train_end_and_predict_start():
    periods = build_wf_periods("2020-01-01", "2025-01-01", "2025-03-31", freq="quarter", purge_days=6)
    (_, train_end), (predict_start, _) = periods[0]
    import pandas as pd

    assert pd.Timestamp(predict_start) - pd.Timestamp(train_end) == pd.Timedelta(days=7)  # 6 purge + 1


def test_rolling_window_drops_old_history():
    periods = build_wf_periods("2020-01-01", "2025-01-01", "2025-03-31", window="rolling", rolling_years=3)
    (train_start, _), (predict_start, _) = periods[0]
    import pandas as pd

    assert pd.Timestamp(train_start) == pd.Timestamp(predict_start) - pd.DateOffset(years=3)


def test_annual_freq():
    periods = build_wf_periods("2020-01-01", "2025-01-01", "2026-06-30", freq="year")
    assert len(periods) == 2
    assert periods[0][1] == ("2025-01-01", "2025-12-31")
    assert periods[1][1] == ("2026-01-01", "2026-06-30")
