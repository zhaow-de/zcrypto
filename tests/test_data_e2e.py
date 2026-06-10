"""End-to-end iter-5 scenarios. Exercise download + rename + backfill flows over
realistic MATIC/POL-shaped sequences using FakeSource. All offline."""

import datetime as dt

import pytest

from cli.data.index import load_index
from cli.data.pipeline import (
    PipelineError,
    backfill_pipeline,
    download_pipeline,
    rename_pipeline,
)
from cli.data.qlib_writer import read_bin
from cli.data.verify import verify_dataset
from tests.data_fixtures import FakeSource


def test_e2e_fresh_full_history_via_download_plus_rename_merge(tmp_path):
    """Spec scenario 1: pairs.txt with MATICUSDT + POLUSDT; download fetches both
    (Change C: MATIC as historical archive); rename merges into POL Variant 2.
    Final dataset has POL with continuous history end-to-end."""
    pairs = tmp_path / "pairs.txt"
    pairs.write_text("MATICUSDT\nPOLUSDT\n")
    out = tmp_path / "ds"
    src = FakeSource()
    src.add_pair("MATICUSDT", "MATIC", "USDT", status="BREAK")
    src.add_pair("POLUSDT", "POL", "USDT")
    # MATIC historical: 2024-08-01..2024-09-10
    cur = dt.date(2024, 8, 1)
    while cur <= dt.date(2024, 9, 10):
        src.add_kline("MATICUSDT", "1d", cur)
        cur += dt.timedelta(days=1)
    # POL recent: 2024-09-13..2024-09-20
    cur = dt.date(2024, 9, 13)
    while cur <= dt.date(2024, 9, 20):
        src.add_kline("POLUSDT", "1d", cur)
        cur += dt.timedelta(days=1)

    download_pipeline(out, pairs, "1d", dt.date(2024, 8, 1), dt.date(2024, 9, 20), src)
    assert verify_dataset(out).ok
    idx = load_index(out)
    assert {"MATICUSDT", "POLUSDT"} <= set(idx.pairs.keys())

    rename_pipeline(out, "MATICUSDT", "POLUSDT", src)
    idx = load_index(out)
    assert "MATICUSDT" not in idx.pairs
    pol = idx.pairs["POLUSDT"].intervals["1d"]
    assert pol.dates_from == "2024-08-01"
    assert pol.dates_to == "2024-09-20"
    # Verify merged bin has: 41 OLD + 2 gap + 8 NEW = 51 rows
    _, vols = read_bin(out / "features" / "polusdt" / "volume.day.bin")
    assert len(vols) == 51
    assert vols[41] == pytest.approx(0.0)  # synthetic gap day
    assert verify_dataset(out).ok


def test_e2e_ongoing_dataset_survives_mid_window_rename(tmp_path):
    """Spec scenario 2: existing MATIC dataset; status flips to BREAK; backfill
    skips MATIC silently; rename Variant 1 (2-day synth gap); subsequent
    backfill extends POL forward."""
    pairs = tmp_path / "pairs.txt"
    pairs.write_text("MATICUSDT\n")
    out = tmp_path / "ds"
    src = FakeSource()
    src.add_pair("MATICUSDT", "MATIC", "USDT")
    # First download: MATIC as TRADING through 2024-09-10
    for i in range(((dt.date(2024, 9, 10) - dt.date(2024, 9, 1)).days) + 1):
        src.add_kline("MATICUSDT", "1d", dt.date(2024, 9, 1) + dt.timedelta(days=i))
    download_pipeline(out, pairs, "1d", dt.date(2024, 9, 1), dt.date(2024, 9, 10), src)
    assert verify_dataset(out).ok

    # Mid-window: MATIC flips to BREAK, POL appears on archive
    next(e for e in src.exchange_info if e["symbol"] == "MATICUSDT")["status"] = "BREAK"
    src.add_pair("POLUSDT", "POL", "USDT")
    for i in range(3):
        src.add_kline("POLUSDT", "1d", dt.date(2024, 9, 13) + dt.timedelta(days=i))

    # Backfill skips MATIC (no-op overall since MATIC is the only pair)
    snaps_before = sorted((out / ".snapshots").glob("*.tar.gz"))
    backfill_pipeline(out, "1d", dt.date(2024, 9, 15), src)
    snaps_after = sorted((out / ".snapshots").glob("*.tar.gz"))
    assert snaps_before == snaps_after, "backfill of only-delisted-pair must not snapshot"

    # Rename MATIC → POL Variant 1 (gap of Sept 11, 12)
    rename_pipeline(out, "MATICUSDT", "POLUSDT", src)
    idx = load_index(out)
    pol = idx.pairs["POLUSDT"].intervals["1d"]
    assert pol.dates_to == "2024-09-12"
    assert "MATICUSDT" not in idx.pairs

    # Subsequent backfill extends POL forward
    backfill_pipeline(out, "1d", dt.date(2024, 9, 15), src)
    idx = load_index(out)
    pol = idx.pairs["POLUSDT"].intervals["1d"]
    assert pol.dates_to == "2024-09-15"
    assert verify_dataset(out).ok


def test_e2e_pure_delisted_snapshot(tmp_path):
    """Spec scenario 3: pairs.txt with MATICUSDT only (status=BREAK); Change C
    fetches truncated range; verify passes; backfill is no-op.

    Realistic MATIC dates: traded 2019-04-26..2024-09-10 before the POL rename."""
    pairs = tmp_path / "pairs.txt"
    pairs.write_text("MATICUSDT\n")
    out = tmp_path / "ds"
    src = FakeSource()
    src.add_pair("MATICUSDT", "MATIC", "USDT", status="BREAK")
    cur = dt.date(2019, 4, 26)
    while cur <= dt.date(2024, 9, 10):
        src.add_kline("MATICUSDT", "1d", cur)
        cur += dt.timedelta(days=1)

    download_pipeline(out, pairs, "1d", dt.date(2018, 1, 1), dt.date(2026, 1, 1), src)
    assert verify_dataset(out).ok
    idx = load_index(out)
    mat = idx.pairs["MATICUSDT"].intervals["1d"]
    assert mat.dates_to == "2024-09-10"  # last_available, truncated from arg_to

    # backfill is no-op
    snaps_before = sorted((out / ".snapshots").glob("*.tar.gz"))
    backfill_pipeline(out, "1d", dt.date(2026, 1, 1), src)
    snaps_after = sorted((out / ".snapshots").glob("*.tar.gz"))
    assert snaps_before == snaps_after, "delisted-only backfill must not snapshot"
    assert verify_dataset(out).ok


def test_e2e_download_rename_backfill_extends_ragged_renamed_pair(tmp_path):
    """User-reported edge case (download → rename → backfill).

    Download a delisted pair (MATIC, archive ends 09-10) alongside a trading pair
    (ADA, reaches 09-16) that pushes the calendar past MATIC. Rename MATIC→POL,
    which leaves POL ragged (ends 09-12, calendar ends 09-16). Then backfill POL
    to the calendar end. Backfill must extend the ragged renamed pair without the
    "existing POLUSDT open bin inconsistent with index" crash."""
    pairs = tmp_path / "pairs.txt"
    pairs.write_text("MATICUSDT\nADAUSDT\n")
    out = tmp_path / "ds"

    # Step 1: download. MATIC (BREAK) archive 09-08..09-10; ADA (TRADING) 09-08..09-16.
    dl = FakeSource()
    dl.add_pair("MATICUSDT", "MATIC", "USDT", status="BREAK")
    dl.add_pair("ADAUSDT", "ADA", "USDT")
    for i in range(3):
        dl.add_kline("MATICUSDT", "1d", dt.date(2024, 9, 8) + dt.timedelta(days=i))
    for i in range(9):
        dl.add_kline("ADAUSDT", "1d", dt.date(2024, 9, 8) + dt.timedelta(days=i))
    download_pipeline(out, pairs, "1d", dt.date(2024, 9, 8), dt.date(2024, 9, 16), dl)

    # Step 2: rename MATIC→POL. POL (TRADING) first archive 09-13 → gap 09-11..09-12.
    ren = FakeSource()
    ren.add_pair("POLUSDT", "POL", "USDT")
    ren.add_pair("ADAUSDT", "ADA", "USDT")
    for i in range(4):
        ren.add_kline("POLUSDT", "1d", dt.date(2024, 9, 13) + dt.timedelta(days=i))
    rename_pipeline(out, "MATICUSDT", "POLUSDT", ren)
    idx = load_index(out)
    assert "MATICUSDT" not in idx.pairs
    assert idx.pairs["POLUSDT"].intervals["1d"].dates_to == "2024-09-12"  # ragged

    # Step 3: backfill POL to 09-16 (ADA already caught up → skipped).
    backfill_pipeline(out, "1d", dt.date(2024, 9, 16), ren)
    idx = load_index(out)
    pol = idx.pairs["POLUSDT"].intervals["1d"]
    assert pol.dates_to == "2024-09-16"
    assert pol.rows == 9  # 3 real MATIC + 2 synthetic gap + 4 real POL
    assert idx.pairs["ADAUSDT"].intervals["1d"].dates_to == "2024-09-16"
    assert verify_dataset(out).ok
