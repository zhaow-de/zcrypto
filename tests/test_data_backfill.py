from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from cli.data.index import load_index
from cli.data.pipeline import PipelineError, backfill_pipeline, download_pipeline
from cli.data.verify import verify_dataset
from tests.data_fixtures import FakeSource


def _bootstrap_two_pairs(tmp_path: Path, dates_through: dt.date) -> tuple[Path, FakeSource]:
    pairs = tmp_path / "pairs.txt"
    pairs.write_text("BTCUSDT\nETHUSDT\n")
    out = tmp_path / "ds"
    src = FakeSource()
    src.add_pair("BTCUSDT", "BTC", "USDT")
    src.add_pair("ETHUSDT", "ETH", "USDT")
    n = (dates_through - dt.date(2024, 1, 1)).days + 1
    for i in range(n):
        d = dt.date(2024, 1, 1) + dt.timedelta(days=i)
        src.add_kline("BTCUSDT", "1d", d)
        src.add_kline("ETHUSDT", "1d", d)
    download_pipeline(out, pairs, "1d", dt.date(2024, 1, 1), dates_through, src)
    return out, src


def test_backfill_happy_extends_to_arg_to(tmp_path):
    out, src = _bootstrap_two_pairs(tmp_path, dt.date(2024, 1, 5))
    for d in (dt.date(2024, 1, 6), dt.date(2024, 1, 7), dt.date(2024, 1, 8)):
        src.add_kline("BTCUSDT", "1d", d)
        src.add_kline("ETHUSDT", "1d", d)
    backfill_pipeline(out, "1d", dt.date(2024, 1, 8), src)
    idx = load_index(out)
    assert idx is not None
    for p in idx.pairs.values():
        assert p.intervals["1d"].dates_to == "2024-01-08"


def test_backfill_noop_when_all_caught_up_no_snapshot(tmp_path):
    out, src = _bootstrap_two_pairs(tmp_path, dt.date(2024, 1, 5))
    snaps_before = sorted((out / ".snapshots").glob("*.tar.gz"))
    backfill_pipeline(out, "1d", dt.date(2024, 1, 5), src)
    snaps_after = sorted((out / ".snapshots").glob("*.tar.gz"))
    assert snaps_before == snaps_after, "no-op backfill must not write a snapshot"


def test_backfill_silently_skips_break_status_pair(tmp_path):
    out, src = _bootstrap_two_pairs(tmp_path, dt.date(2024, 1, 5))
    # Flip BTCUSDT to BREAK on the source's exchange_info list
    for entry in src.exchange_info:
        if entry["symbol"] == "BTCUSDT":
            entry["status"] = "BREAK"
            break
    for d in (dt.date(2024, 1, 6), dt.date(2024, 1, 7)):
        src.add_kline("ETHUSDT", "1d", d)
    backfill_pipeline(out, "1d", dt.date(2024, 1, 7), src)
    idx = load_index(out)
    assert idx is not None
    btc = next(p for sym, p in idx.pairs.items() if sym == "BTCUSDT").intervals["1d"]
    eth = next(p for sym, p in idx.pairs.items() if sym == "ETHUSDT").intervals["1d"]
    assert btc.dates_to == "2024-01-05", "BREAK pair must not be extended"
    assert eth.dates_to == "2024-01-07", "TRADING pair extends normally"


def test_backfill_silently_skips_break_pair_dataset_still_valid(tmp_path):
    """Verify that after a partial backfill (BREAK skipped), verify_dataset passes."""
    out, src = _bootstrap_two_pairs(tmp_path, dt.date(2024, 1, 5))
    for entry in src.exchange_info:
        if entry["symbol"] == "BTCUSDT":
            entry["status"] = "BREAK"
            break
    for d in (dt.date(2024, 1, 6), dt.date(2024, 1, 7)):
        src.add_kline("ETHUSDT", "1d", d)
    backfill_pipeline(out, "1d", dt.date(2024, 1, 7), src)
    report = verify_dataset(out)
    assert report.ok, f"verify_dataset failed after partial backfill: {report.problems}"


def test_backfill_trading_pair_unreachable_raises_pipeline_error(tmp_path):
    out, src = _bootstrap_two_pairs(tmp_path, dt.date(2024, 1, 5))
    # BTCUSDT still TRADING but no new klines added; backfill --to 2024-02-04 (30-day gap > 7-day grace)
    # → sustained absence beyond grace fires the actionable delist/rename error
    with pytest.raises(PipelineError, match=r"delisted|renamed"):
        backfill_pipeline(out, "1d", dt.date(2024, 2, 4), src)


def test_backfill_dry_run_no_snapshot_prints_plan(tmp_path, capsys):
    out, src = _bootstrap_two_pairs(tmp_path, dt.date(2024, 1, 5))
    for d in (dt.date(2024, 1, 6), dt.date(2024, 1, 7)):
        src.add_kline("BTCUSDT", "1d", d)
        src.add_kline("ETHUSDT", "1d", d)
    snaps_before = sorted((out / ".snapshots").glob("*.tar.gz"))
    backfill_pipeline(out, "1d", dt.date(2024, 1, 7), src, dry_run=True)
    snaps_after = sorted((out / ".snapshots").glob("*.tar.gz"))
    assert snaps_before == snaps_after
    captured = capsys.readouterr()
    assert "DRY-RUN" in captured.out


def test_backfill_empty_index_raises(tmp_path):
    out = tmp_path / "ds"
    out.mkdir(parents=True)
    src = FakeSource()
    with pytest.raises(PipelineError, match=r"no pairs"):
        backfill_pipeline(out, "1d", dt.date(2024, 1, 5), src)


def test_backfill_trading_pair_publishing_lag_within_grace_no_op(tmp_path):
    """When archive lags by <= GRACE_DAYS, backfill is a silent no-op (no snapshot)."""
    out, src = _bootstrap_two_pairs(tmp_path, dt.date(2024, 1, 5))
    snaps_before = sorted((out / ".snapshots").glob("*.tar.gz"))
    # No new klines added; arg_to = index.to + 3 days (within 7-day grace)
    backfill_pipeline(out, "1d", dt.date(2024, 1, 8), src)
    snaps_after = sorted((out / ".snapshots").glob("*.tar.gz"))
    assert snaps_before == snaps_after, "publishing-lag backfill must not snapshot"
    # Pairs unchanged
    idx = load_index(out)
    for p in idx.pairs.values():
        assert p.intervals["1d"].dates_to == "2024-01-05"


def test_backfill_trading_pair_sustained_absence_beyond_grace_raises(tmp_path):
    """When the absence exceeds GRACE_DAYS, fire the actionable error."""
    out, src = _bootstrap_two_pairs(tmp_path, dt.date(2024, 1, 5))
    # No new klines; arg_to = index.to + 30 days (well beyond 7-day grace)
    with pytest.raises(PipelineError, match=r"delisted|renamed|publishing-lag grace"):
        backfill_pipeline(out, "1d", dt.date(2024, 2, 4), src)
