import datetime as dt
import os

import numpy as np

from cli.data.qlib_writer import read_bin, write_bin, write_calendar, write_instruments


def test_write_calendar_writes_dense_iso_dates(tmp_path):
    dates = [dt.date(2024, 1, 1), dt.date(2024, 1, 2), dt.date(2024, 1, 3)]
    write_calendar(tmp_path, dates)
    content = (tmp_path / "calendars" / "day.txt").read_text(encoding="utf-8")
    assert content == "2024-01-01\n2024-01-02\n2024-01-03\n"


def test_write_instruments_writes_tab_separated_uppercase_sorted(tmp_path):
    write_instruments(
        tmp_path,
        {
            "ethusdt": (dt.date(2024, 1, 1), dt.date(2024, 1, 5)),
            "BTCUSDT": (dt.date(2024, 1, 2), dt.date(2024, 1, 5)),
        },
    )
    lines = (tmp_path / "instruments" / "all.txt").read_text(encoding="utf-8").splitlines()
    assert lines == ["BTCUSDT\t2024-01-02\t2024-01-05", "ETHUSDT\t2024-01-01\t2024-01-05"]


def test_bin_round_trip_with_start_index(tmp_path):
    path = tmp_path / "features" / "btcusdt" / "close.day.bin"
    write_bin(path, [101.0, 102.5, 103.25], start_index=2)
    start, values = read_bin(path)
    assert start == 2
    assert values.dtype == np.dtype("<f4")
    np.testing.assert_array_equal(values, np.array([101.0, 102.5, 103.25], dtype="<f4"))


def test_bin_file_size_is_header_plus_values_times_four_bytes(tmp_path):
    path = tmp_path / "v.bin"
    write_bin(path, [1.0, 2.0, 3.0, 4.0], start_index=0)
    assert os.path.getsize(path) == (1 + 4) * 4
