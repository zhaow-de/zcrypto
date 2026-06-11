import datetime as dt

from cli.data import mirror
from cli.data.pipeline import _fetch_one_date, download_pipeline
from cli.data.verify import verify_dataset
from tests.data_fixtures import FakeSource, make_zip_with_checksum, synthetic_kline_csv


def test_root_for_is_dataset_local_dot_raw(tmp_path):
    assert mirror.root_for(tmp_path) == tmp_path / ".raw"


def test_mirror_path_inserts_year_subdir_and_reuses_layout(tmp_path):
    p = mirror.mirror_path(tmp_path, "DOTUSDT", "1d", dt.date(2025, 10, 14))
    assert p == tmp_path / "spot/daily/klines/DOTUSDT/1d/2025/DOTUSDT-1d-2025-10-14.zip"


def test_read_zip_absent_returns_none(tmp_path):
    assert mirror.read_zip(tmp_path / "nope.zip") is None


def test_save_zip_is_atomic_and_creates_parents(tmp_path):
    target = mirror.mirror_path(tmp_path, "DOTUSDT", "1d", dt.date(2025, 1, 2))
    mirror.save_zip(target, b"payload")
    assert target.read_bytes() == b"payload"
    assert not target.with_name(target.name + ".tmp").exists()  # no leftover temp
    assert mirror.read_zip(target) == b"payload"


def test_fetch_one_date_miss_saves_verified_zip_to_mirror(tmp_path):
    root = mirror.root_for(tmp_path)
    date = dt.date(2025, 1, 2)
    src = FakeSource()
    src.add_pair("DOTUSDT", "DOT", "USDT")
    src.add_kline("DOTUSDT", "1d", date)
    mpath = mirror.mirror_path(root, "DOTUSDT", "1d", date)
    assert not mpath.exists()

    _, d, df = _fetch_one_date(src, "DOTUSDT", "1d", date, root)
    assert d == date
    assert df.iloc[0]["date"] == date
    assert mpath.exists()  # cached under <out_dir>/.raw/.../<year>/ for recovery


def test_fetch_one_date_mirror_hit_does_not_touch_source(tmp_path):
    root = mirror.root_for(tmp_path)
    date = dt.date(2024, 1, 2)
    zip_bytes, _ = make_zip_with_checksum(synthetic_kline_csv(date), f"BTCUSDT-1d-{date}.csv")
    mirror.save_zip(mirror.mirror_path(root, "BTCUSDT", "1d", date), zip_bytes)

    class ExplodingSource:
        def fetch_kline_zip(self, *a):
            raise AssertionError("mirror hit must not fetch")

        def fetch_kline_checksum(self, *a):
            raise AssertionError("mirror hit must not re-checksum")

    _, d, df = _fetch_one_date(ExplodingSource(), "BTCUSDT", "1d", date, root)
    assert d == date
    assert df.iloc[0]["date"] == date


def test_fetch_one_date_missing_checksum_caches_after_parse(tmp_path):
    root = mirror.root_for(tmp_path)
    date = dt.date(2025, 7, 13)
    src = FakeSource()
    src.add_pair("DOTUSDT", "DOT", "USDT")
    src.add_kline("DOTUSDT", "1d", date)
    src.drop_kline_checksum("DOTUSDT", "1d", date)

    _, d, _df = _fetch_one_date(src, "DOTUSDT", "1d", date, root)
    assert d == date
    assert mirror.mirror_path(root, "DOTUSDT", "1d", date).exists()  # structurally verified, then cached


def test_download_creates_dataset_local_mirror_without_breaking_verify(tmp_path):
    """End-to-end: the mirror lands at <out_dir>/.raw and does not trip verify."""
    pairs = tmp_path / "pairs.txt"
    pairs.write_text("BTCUSDT\n")
    out = tmp_path / "ds"
    src = FakeSource()
    src.add_pair("BTCUSDT", "BTC", "USDT")
    for i in range(3):
        src.add_kline("BTCUSDT", "1d", dt.date(2024, 1, 1) + dt.timedelta(days=i))
    download_pipeline(out, pairs, "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 3), src)

    assert (out / ".raw").is_dir()
    assert mirror.mirror_path(mirror.root_for(out), "BTCUSDT", "1d", dt.date(2024, 1, 2)).exists()
    assert verify_dataset(out).ok  # a .raw dir in out_dir must not break verification
