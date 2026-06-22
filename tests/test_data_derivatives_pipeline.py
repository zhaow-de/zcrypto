"""Pipeline integration tests for the six new derivatives fields.

Task 3 (iter-38): wire $oi/$oi_value/$ls_top/$ls_global/$taker_ratio/$basis through
the dataset lifecycle — same patterns as $funding but daily-keyed (not monthly).

No network — all tests use synthetic zips built from known rows.
"""

from __future__ import annotations

import datetime as dt
import io
import math
import threading
import zipfile
from pathlib import Path

import pytest

from cli.config import FetchConfig
from cli.data import mirror as _mirror
from cli.data.index import load_index
from cli.data.layout import DatasetPaths
from cli.data.pipeline import _fetch_all_derivatives_concurrent, download_pipeline, drop_pipeline, rename_pipeline
from cli.data.qlib_writer import read_bin
from cli.data.verify import verify_dataset
from tests.data_fixtures import FakeSource

# ---------------------------------------------------------------------------
# Synthetic zip builders (metrics + basis)
# ---------------------------------------------------------------------------

_METRICS_HEADER = (
    "create_time,symbol,sum_open_interest,sum_open_interest_value,"
    "count_toptrader_long_short_ratio,sum_toptrader_long_short_ratio,"
    "count_long_short_ratio,sum_taker_long_short_vol_ratio\n"
)


def _make_metrics_zip(
    perp: str,
    date: dt.date,
    oi: float = 80000.0,
    oi_value: float = 3.5e9,
    ls_top: float = 1.2,
    ls_global: float = 1.1,
    taker_ratio: float = 1.0,
) -> bytes:
    """Synthetic Binance daily metrics zip (one row — last-of-day snapshot)."""
    ts = f"{date} 23:55:00"
    row = f"{ts},{perp},{oi},{oi_value},{ls_global},{ls_top},{ls_global},{taker_ratio}\n"
    csv_text = _METRICS_HEADER + row
    inner = f"{perp}-metrics-{date}.csv"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(inner, csv_text)
    return buf.getvalue()


_BASIS_HEADER = (
    "open_time,open,high,low,close,volume,close_time,quote_volume,count,taker_buy_volume,taker_buy_quote_volume,ignore\n"
)


def _make_basis_zip(perp: str, date: dt.date, basis: float = 0.0007) -> bytes:
    """Synthetic Binance daily premiumIndexKlines zip (one 1d candle row)."""
    open_ms = int(dt.datetime(date.year, date.month, date.day, tzinfo=dt.timezone.utc).timestamp()) * 1000
    close_ms = open_ms + 86400000 - 1
    row = f"{open_ms},{basis},{basis * 1.1},{basis * 0.9},{basis},0,{close_ms},0,100,0,0,0\n"
    csv_text = _BASIS_HEADER + row
    inner = f"{perp}-1d-{date}.csv"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(inner, csv_text)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


def _seed_with_derivatives(
    tmp_path: Path,
    *,
    pairs: list[tuple[str, str, str]],  # [(symbol, base, quote)]
    date_range: tuple[dt.date, dt.date],
    perp_map: dict[str, str] | None = None,  # spot_symbol -> perp_symbol (identity if omitted)
    metrics_dates: dict[str, list[dt.date]] | None = None,  # perp -> dates with metrics
    basis_dates: dict[str, list[dt.date]] | None = None,  # perp -> dates with basis
) -> tuple[DatasetPaths, FakeSource]:
    """Build a dataset seeded with klines + derivatives archives.

    Pairs without an entry in perp_map get no derivatives (NaN throughout).
    metrics_dates / basis_dates default to all dates in the range for all perps.
    """
    pairs_file = tmp_path / "pairs.txt"
    pairs_file.write_text("\n".join(sym for sym, _, _ in pairs) + "\n")
    paths = DatasetPaths(data_dir=tmp_path / "data", backup_dir=tmp_path / "bk")

    src = FakeSource()
    for sym, base, quote in pairs:
        src.add_pair(sym, base, quote)

    start, end = date_range
    cur = start
    all_dates: list[dt.date] = []
    while cur <= end:
        all_dates.append(cur)
        cur += dt.timedelta(days=1)

    for sym, _, _ in pairs:
        for d in all_dates:
            src.add_kline(sym, "1d", d, base_price=100.0)

    if perp_map is None:
        perp_map = {}

    for spot_sym, perp in perp_map.items():
        m_dates = metrics_dates.get(perp, all_dates) if metrics_dates else all_dates
        for d in m_dates:
            src.add_metrics(perp, d)
        b_dates = basis_dates.get(perp, all_dates) if basis_dates else all_dates
        for d in b_dates:
            src.add_basis(perp, d)

    download_pipeline(paths, pairs_file, "1d", start, end, src)
    return paths, src


# ---------------------------------------------------------------------------
# Test: six fields land in the compiled dataset
# ---------------------------------------------------------------------------


def test_download_writes_derivatives_bins(tmp_path):
    """download_pipeline writes all 6 derivatives bins for a pair with a perp."""
    start = dt.date(2024, 1, 1)
    end = dt.date(2024, 1, 3)
    paths, _ = _seed_with_derivatives(
        tmp_path,
        pairs=[("BTCUSDT", "BTC", "USDT")],
        date_range=(start, end),
        perp_map={"BTCUSDT": "BTCUSDT"},
    )
    data_dir = paths.data_dir
    assert verify_dataset(data_dir).ok

    feat_dir = data_dir / "features" / "btcusdt"
    for field in ("oi", "oi_value", "ls_top", "ls_global", "taker_ratio", "basis"):
        assert (feat_dir / f"{field}.day.bin").exists(), f"missing {field}.day.bin"


def test_download_derivatives_same_day_aligned_with_close(tmp_path):
    """Derivatives bins have same start_index and row count as close.day.bin."""
    start = dt.date(2024, 1, 1)
    end = dt.date(2024, 1, 4)
    paths, _ = _seed_with_derivatives(
        tmp_path,
        pairs=[("BTCUSDT", "BTC", "USDT")],
        date_range=(start, end),
        perp_map={"BTCUSDT": "BTCUSDT"},
    )
    data_dir = paths.data_dir
    feat_dir = data_dir / "features" / "btcusdt"

    close_idx, close_vals = read_bin(feat_dir / "close.day.bin")
    for field in ("oi", "oi_value", "ls_top", "ls_global", "taker_ratio", "basis"):
        idx, vals = read_bin(feat_dir / f"{field}.day.bin")
        assert idx == close_idx, f"{field} start_index mismatch"
        assert len(vals) == len(close_vals), f"{field} row count mismatch"

    # $ls_top and $ls_global must not be swapped at the pipeline boundary: the fixture seeds
    # sum_toptrader_long_short_ratio=1.2 ($ls_top) and count_long_short_ratio=1.1 ($ls_global).
    _, ls_top_vals = read_bin(feat_dir / "ls_top.day.bin")
    _, ls_global_vals = read_bin(feat_dir / "ls_global.day.bin")
    assert abs(ls_top_vals[-1] - 1.2) < 1e-4, "ls_top must map to sum_toptrader (1.2)"
    assert abs(ls_global_vals[-1] - 1.1) < 1e-4, "ls_global must map to count_long_short (1.1)"


def test_download_derivatives_nan_for_pair_without_perp(tmp_path):
    """A pair with no perp in the map gets all-NaN derivatives bins."""
    start = dt.date(2024, 1, 1)
    end = dt.date(2024, 1, 3)
    # ETHUSDT has no perp_map entry → all derivatives are NaN
    paths, _ = _seed_with_derivatives(
        tmp_path,
        pairs=[("ETHUSDT", "ETH", "USDT")],
        date_range=(start, end),
        perp_map={},
    )
    data_dir = paths.data_dir
    assert verify_dataset(data_dir).ok

    feat_dir = data_dir / "features" / "ethusdt"
    for field in ("oi", "oi_value", "ls_top", "ls_global", "taker_ratio", "basis"):
        _, vals = read_bin(feat_dir / f"{field}.day.bin")
        assert all(math.isnan(v) for v in vals), f"{field} should be all-NaN for pair without perp"


def test_download_derivatives_nan_before_perp_launch(tmp_path):
    """Derivatives are NaN before the perp's first archive date."""
    start = dt.date(2024, 1, 1)
    end = dt.date(2024, 1, 5)
    perp_launch = dt.date(2024, 1, 3)  # perp archives only exist from Jan 3 onward

    all_dates = [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]
    late_dates = [d for d in all_dates if d >= perp_launch]

    paths, _ = _seed_with_derivatives(
        tmp_path,
        pairs=[("BTCUSDT", "BTC", "USDT")],
        date_range=(start, end),
        perp_map={"BTCUSDT": "BTCUSDT"},
        metrics_dates={"BTCUSDT": late_dates},
        basis_dates={"BTCUSDT": late_dates},
    )
    data_dir = paths.data_dir
    assert verify_dataset(data_dir).ok

    feat_dir = data_dir / "features" / "btcusdt"
    _, oi_vals = read_bin(feat_dir / "oi.day.bin")
    # Days 0,1 (Jan 1,2) → NaN; days 2,3,4 (Jan 3,4,5) → non-NaN
    assert math.isnan(oi_vals[0]), "Jan 1 should be NaN (before perp launch)"
    assert math.isnan(oi_vals[1]), "Jan 2 should be NaN (before perp launch)"
    assert not math.isnan(oi_vals[2]), "Jan 3 should be non-NaN"
    assert not math.isnan(oi_vals[3]), "Jan 4 should be non-NaN"
    assert not math.isnan(oi_vals[4]), "Jan 5 should be non-NaN"


def test_download_derivatives_404_date_becomes_nan(tmp_path):
    """A 404 on a derivatives archive for one date → that date is NaN, others are present."""
    start = dt.date(2024, 1, 1)
    end = dt.date(2024, 1, 4)
    # Metrics available only for Jan 1 and Jan 3 (Jan 2 and Jan 4 are 404)
    partial_dates = [dt.date(2024, 1, 1), dt.date(2024, 1, 3)]
    paths, _ = _seed_with_derivatives(
        tmp_path,
        pairs=[("BTCUSDT", "BTC", "USDT")],
        date_range=(start, end),
        perp_map={"BTCUSDT": "BTCUSDT"},
        metrics_dates={"BTCUSDT": partial_dates},
        basis_dates={"BTCUSDT": partial_dates},
    )
    data_dir = paths.data_dir
    assert verify_dataset(data_dir).ok

    feat_dir = data_dir / "features" / "btcusdt"
    _, oi_vals = read_bin(feat_dir / "oi.day.bin")
    assert not math.isnan(oi_vals[0]), "Jan 1 should be present"
    assert math.isnan(oi_vals[1]), "Jan 2 → 404 → NaN"
    assert not math.isnan(oi_vals[2]), "Jan 3 should be present"
    assert math.isnan(oi_vals[3]), "Jan 4 → 404 → NaN"


# ---------------------------------------------------------------------------
# Test: PEPE → 1000PEPEUSDT perp mapping
# ---------------------------------------------------------------------------


def test_download_pepe_maps_to_1000pepe_perp(tmp_path):
    """PEPEUSDT spot → 1000PEPEUSDT perp for derivatives; bins are non-NaN."""
    start = dt.date(2024, 1, 1)
    end = dt.date(2024, 1, 3)

    pairs_file = tmp_path / "pairs.txt"
    pairs_file.write_text("PEPEUSDT\n")
    paths = DatasetPaths(data_dir=tmp_path / "data", backup_dir=tmp_path / "bk")
    src = FakeSource()
    src.add_pair("PEPEUSDT", "PEPE", "USDT")
    cur = start
    while cur <= end:
        src.add_kline("PEPEUSDT", "1d", cur, base_price=0.001)
        # Register archives under the 1000PEPE perp name
        src.add_metrics("1000PEPEUSDT", cur)
        src.add_basis("1000PEPEUSDT", cur)
        cur += dt.timedelta(days=1)

    download_pipeline(paths, pairs_file, "1d", start, end, src)
    assert verify_dataset(paths.data_dir).ok

    feat_dir = paths.data_dir / "features" / "pepeusdt"
    _, oi_vals = read_bin(feat_dir / "oi.day.bin")
    assert not any(math.isnan(v) for v in oi_vals), "PEPE→1000PEPE mapping should yield non-NaN OI"


# ---------------------------------------------------------------------------
# Test: MATIC → POL split
# ---------------------------------------------------------------------------


def test_download_pol_maticpol_split(tmp_path):
    """POLUSDT spot → MATICUSDT perp pre-rename, POLUSDT perp post-rename; gap is NaN."""
    # Simulate the MATIC→POL rename gap:
    # Pre: 2024-09-08..2024-09-10 → MATICUSDT perp
    # Gap: 2024-09-11..2024-09-12 → None (no perp)
    # Post: 2024-09-13..2024-09-15 → POLUSDT perp
    start = dt.date(2024, 9, 8)
    end = dt.date(2024, 9, 15)
    matic_last = dt.date(2024, 9, 10)
    pol_first = dt.date(2024, 9, 13)

    matic_dates = [dt.date(2024, 9, 8), dt.date(2024, 9, 9), dt.date(2024, 9, 10)]
    pol_dates = [dt.date(2024, 9, 13), dt.date(2024, 9, 14), dt.date(2024, 9, 15)]

    pairs_file = tmp_path / "pairs.txt"
    pairs_file.write_text("POLUSDT\n")
    paths = DatasetPaths(data_dir=tmp_path / "data", backup_dir=tmp_path / "bk")
    src = FakeSource()
    src.add_pair("POLUSDT", "POL", "USDT")
    cur = start
    while cur <= end:
        src.add_kline("POLUSDT", "1d", cur, base_price=0.5)
        cur += dt.timedelta(days=1)
    for d in matic_dates:
        src.add_metrics("MATICUSDT", d)
        src.add_basis("MATICUSDT", d)
    for d in pol_dates:
        src.add_metrics("POLUSDT", d)
        src.add_basis("POLUSDT", d)

    download_pipeline(paths, pairs_file, "1d", start, end, src)
    assert verify_dataset(paths.data_dir).ok

    feat_dir = paths.data_dir / "features" / "polusdt"
    all_dates = [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]
    _, oi_vals = read_bin(feat_dir / "oi.day.bin")

    # Days 0..2 (Sep 8-10) → MATIC perp → non-NaN
    for i, d in enumerate(all_dates):
        if d in matic_dates or d in pol_dates:
            assert not math.isnan(oi_vals[i]), f"{d} should be non-NaN"
        else:
            # Gap (Sep 11-12)
            assert math.isnan(oi_vals[i]), f"{d} (rename gap) should be NaN"


# ---------------------------------------------------------------------------
# Test: verify reports per-field coverage
# ---------------------------------------------------------------------------


def test_verify_reports_derivatives_coverage(tmp_path):
    """verify_dataset reports per-coin coverage for each of the 6 new fields."""
    start = dt.date(2024, 1, 1)
    end = dt.date(2024, 1, 3)
    paths, _ = _seed_with_derivatives(
        tmp_path,
        pairs=[("BTCUSDT", "BTC", "USDT")],
        date_range=(start, end),
        perp_map={"BTCUSDT": "BTCUSDT"},
    )
    report = verify_dataset(paths.data_dir)
    assert report.ok, report.problems

    # Each of the 6 new fields should appear in the checks output
    checks_text = "\n".join(report.checks)
    for field in ("oi", "oi_value", "ls_top", "ls_global", "taker_ratio", "basis"):
        assert field in checks_text, f"verify should report coverage for {field}"


# ---------------------------------------------------------------------------
# Test: drop removes all derivatives bins
# ---------------------------------------------------------------------------


def test_drop_removes_derivatives_bins(tmp_path):
    """drop_pipeline removes all 6 derivatives bins for the dropped pair."""
    start = dt.date(2024, 1, 1)
    end = dt.date(2024, 1, 3)
    src_fakeobj = FakeSource()
    src_fakeobj.add_pair("BTCUSDT", "BTC", "USDT")
    src_fakeobj.add_pair("ETHUSDT", "ETH", "USDT")
    cur = start
    while cur <= end:
        src_fakeobj.add_kline("BTCUSDT", "1d", cur)
        src_fakeobj.add_kline("ETHUSDT", "1d", cur)
        src_fakeobj.add_metrics("BTCUSDT", cur)
        src_fakeobj.add_basis("BTCUSDT", cur)
        src_fakeobj.add_metrics("ETHUSDT", cur)
        src_fakeobj.add_basis("ETHUSDT", cur)
        cur += dt.timedelta(days=1)

    pairs_file = tmp_path / "pairs.txt"
    pairs_file.write_text("BTCUSDT\nETHUSDT\n")
    paths = DatasetPaths(data_dir=tmp_path / "data", backup_dir=tmp_path / "bk")
    download_pipeline(paths, pairs_file, "1d", start, end, src_fakeobj)

    # Drop BTC — its entire feature dir (including derivatives) must be gone
    drop_pipeline(paths, "BTCUSDT")
    assert verify_dataset(paths.data_dir).ok
    assert not (paths.data_dir / "features" / "btcusdt").exists()

    # ETH's derivatives bins must still be present
    eth_dir = paths.data_dir / "features" / "ethusdt"
    for field in ("oi", "oi_value", "ls_top", "ls_global", "taker_ratio", "basis"):
        assert (eth_dir / f"{field}.day.bin").exists(), f"ETH {field}.day.bin should survive drop"


# ---------------------------------------------------------------------------
# Test: rename carries derivatives bins
# ---------------------------------------------------------------------------


def test_rename_carries_derivatives_bins(tmp_path):
    """rename_pipeline (Variant 1) carries all 6 derivatives bins from OLD to NEW."""
    start = dt.date(2024, 1, 1)
    end = dt.date(2024, 1, 3)

    src_fakeobj = FakeSource()
    src_fakeobj.add_pair("OLDUSDT", "OLD", "USDT", status="BREAK")
    src_fakeobj.add_pair("NEWUSDT", "NEW", "USDT")

    cur = start
    while cur <= end:
        src_fakeobj.add_kline("OLDUSDT", "1d", cur)
        src_fakeobj.add_metrics("OLDUSDT", cur)
        src_fakeobj.add_basis("OLDUSDT", cur)
        cur += dt.timedelta(days=1)

    # NEW starts one day after OLD ends (no gap)
    new_start = end + dt.timedelta(days=1)
    new_end = new_start + dt.timedelta(days=2)
    cur = new_start
    while cur <= new_end:
        src_fakeobj.add_kline("NEWUSDT", "1d", cur)
        cur += dt.timedelta(days=1)

    pairs_file = tmp_path / "pairs.txt"
    pairs_file.write_text("OLDUSDT\n")
    paths = DatasetPaths(data_dir=tmp_path / "data", backup_dir=tmp_path / "bk")
    download_pipeline(paths, pairs_file, "1d", start, end, src_fakeobj)

    rename_pipeline(paths, "OLDUSDT", "NEWUSDT", src_fakeobj)
    assert verify_dataset(paths.data_dir).ok

    # NEW should have all derivatives bins from OLD (gap-filled with NaN for any gap days)
    new_dir = paths.data_dir / "features" / "newusdt"
    for field in ("oi", "oi_value", "ls_top", "ls_global", "taker_ratio", "basis"):
        assert (new_dir / f"{field}.day.bin").exists(), f"renamed NEW {field}.day.bin should exist"


# ---------------------------------------------------------------------------
# Test: concurrent derivatives pre-fetch populates the mirror
# ---------------------------------------------------------------------------


class _TrackingSource(FakeSource):
    """FakeSource that counts calls to fetch_metrics_archive and fetch_basis_archive."""

    def __init__(self) -> None:
        super().__init__()
        self._lock = threading.Lock()
        self.metrics_fetch_count = 0
        self.basis_fetch_count = 0

    def fetch_metrics_archive(self, perp: str, date: dt.date) -> bytes | None:
        with self._lock:
            self.metrics_fetch_count += 1
        return super().fetch_metrics_archive(perp, date)

    def fetch_basis_archive(self, perp: str, date: dt.date) -> bytes | None:
        with self._lock:
            self.basis_fetch_count += 1
        return super().fetch_basis_archive(perp, date)


def test_concurrent_derivatives_prefetch_populates_mirror(tmp_path):
    """_fetch_all_derivatives_concurrent writes archives into the mirror so that the
    sequential _derivatives_for_pair loop sees only mirror hits (no network calls there).

    Approach: run _fetch_all_derivatives_concurrent with a tracking source, then verify
    the mirror contains the expected files; run it again and confirm the source counters
    do not increment (all hits served from the mirror).
    """
    start = dt.date(2024, 1, 1)
    end = dt.date(2024, 1, 3)
    paths = DatasetPaths(data_dir=tmp_path / "data", backup_dir=tmp_path / "bk")
    mirror_root = _mirror.root_for(paths)

    src = _TrackingSource()
    src.add_pair("BTCUSDT", "BTC", "USDT")
    cur = start
    all_dates: list[dt.date] = []
    while cur <= end:
        all_dates.append(cur)
        src.add_metrics("BTCUSDT", cur)
        src.add_basis("BTCUSDT", cur)
        cur += dt.timedelta(days=1)

    from cli.data.pipeline import _PerPair

    plan = [_PerPair("BTCUSDT", "BTC", "USDT", start, end, True, None)]
    fetch = FetchConfig()

    # First pass: archives are fetched from source and written to the mirror.
    _fetch_all_derivatives_concurrent(src, plan, fetch, mirror_root)

    n_days = (end - start).days + 1
    assert src.metrics_fetch_count == n_days, f"expected {n_days} metrics fetches, got {src.metrics_fetch_count}"
    assert src.basis_fetch_count == n_days, f"expected {n_days} basis fetches, got {src.basis_fetch_count}"

    # Verify mirror files exist for every date.
    for d in all_dates:
        m_path = _mirror.metrics_mirror_path(mirror_root, "BTCUSDT", d)
        b_path = _mirror.basis_mirror_path(mirror_root, "BTCUSDT", d)
        assert m_path.exists(), f"metrics mirror file missing for {d}"
        assert b_path.exists(), f"basis mirror file missing for {d}"

    # Second pass: all hits from mirror — source counters must not increment.
    counts_before = (src.metrics_fetch_count, src.basis_fetch_count)
    _fetch_all_derivatives_concurrent(src, plan, fetch, mirror_root)
    assert src.metrics_fetch_count == counts_before[0], "second pass must not re-fetch metrics (mirror hit)"
    assert src.basis_fetch_count == counts_before[1], "second pass must not re-fetch basis (mirror hit)"


def test_download_pipeline_derivatives_served_from_mirror_in_sequential_loop(tmp_path):
    """download_pipeline pre-fetches derivatives concurrently; _derivatives_for_pair
    reads only from the mirror (no network calls during the sequential loop).

    Verifies that the total source.fetch_metrics_archive calls equal the number of
    derivatives dates (one per date, during the concurrent pre-fetch) — not doubled
    (which would indicate the sequential loop also hit the network).
    """
    start = dt.date(2024, 1, 1)
    end = dt.date(2024, 1, 3)

    src = _TrackingSource()
    src.add_pair("BTCUSDT", "BTC", "USDT")
    cur = start
    while cur <= end:
        src.add_kline("BTCUSDT", "1d", cur)
        src.add_metrics("BTCUSDT", cur)
        src.add_basis("BTCUSDT", cur)
        cur += dt.timedelta(days=1)

    pairs_file = tmp_path / "pairs.txt"
    pairs_file.write_text("BTCUSDT\n")
    paths = DatasetPaths(data_dir=tmp_path / "data", backup_dir=tmp_path / "bk")

    download_pipeline(paths, pairs_file, "1d", start, end, src)
    assert verify_dataset(paths.data_dir).ok

    # _fetch_all_derivatives_concurrent fetches once per (perp, date);
    # _derivatives_for_pair must get mirror hits → no additional source calls.
    n_days = (end - start).days + 1
    assert src.metrics_fetch_count == n_days, (
        f"expected exactly {n_days} metrics fetches (pre-fetch only), got {src.metrics_fetch_count}"
    )
    assert src.basis_fetch_count == n_days, f"expected exactly {n_days} basis fetches (pre-fetch only), got {src.basis_fetch_count}"
