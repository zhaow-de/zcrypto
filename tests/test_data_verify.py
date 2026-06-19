import datetime as dt
import json
from pathlib import Path

from cli.data.config import FIELDS
from cli.data.index import (
    CalendarEntry,
    FieldEntry,
    FileEntry,
    IndexData,
    PairEntry,
    PairIntervalEntry,
    compute_sha256,
    save_index,
    utc_now_iso,
)
from cli.data.qlib_writer import write_bin, write_calendar, write_instruments
from cli.data.verify import verify_dataset


def _build_valid_dataset(tmp_path: Path) -> IndexData:
    """Two pairs, ragged left edge: BTC starts day 0, ETH starts day 1."""
    cal = [dt.date(2024, 1, 1), dt.date(2024, 1, 2), dt.date(2024, 1, 3)]
    write_calendar(tmp_path, cal)
    write_instruments(
        tmp_path,
        {
            "BTCUSDT": (cal[0], cal[-1]),
            "ETHUSDT": (cal[1], cal[-1]),
        },
    )
    pairs = {}
    for sym, base, start in [("BTCUSDT", "BTC", 0), ("ETHUSDT", "ETH", 1)]:
        rows = len(cal) - start
        fields = {}
        for f in FIELDS:
            bin_rel = f"features/{sym.lower()}/{f}.day.bin"
            write_bin(tmp_path / bin_rel, [1.0] * rows, start_index=start)
            fields[f] = FieldEntry(bin=bin_rel, sha256=compute_sha256(tmp_path / bin_rel), updated_at=utc_now_iso())
        pairs[sym] = PairEntry(
            base_asset=base,
            quote_asset="USDT",
            intervals={
                "1d": PairIntervalEntry(
                    from_date=cal[start].isoformat(),
                    to_date=cal[start + rows - 1].isoformat(),
                    rows=rows,
                    fields=fields,
                )
            },
        )
    idx = IndexData(
        schema_version=2,
        updated_at=utc_now_iso(),
        calendar=CalendarEntry(freq="day", from_date=cal[0].isoformat(), to_date=cal[-1].isoformat(), days=len(cal)),
        pairs=pairs,
        other_files={
            "calendars/day.txt": FileEntry(sha256=compute_sha256(tmp_path / "calendars" / "day.txt"), updated_at=utc_now_iso()),
            "instruments/all.txt": FileEntry(sha256=compute_sha256(tmp_path / "instruments" / "all.txt"), updated_at=utc_now_iso()),
        },
    )
    save_index(tmp_path, idx)
    return idx


_PRICE_FIELDS = ("open", "high", "low", "close", "vwap")


def _mk_pair(tmp_path: Path, cal: list[dt.date], sym: str, base: str, start: int, rows: int, *, nan_offsets=()) -> PairEntry:
    fields = {}
    for f in FIELDS:
        vals = [1.0] * rows
        if f in _PRICE_FIELDS:
            for o in nan_offsets:
                vals[o] = float("nan")
        bin_rel = f"features/{sym.lower()}/{f}.day.bin"
        write_bin(tmp_path / bin_rel, vals, start_index=start)
        fields[f] = FieldEntry(bin=bin_rel, sha256=compute_sha256(tmp_path / bin_rel), updated_at=utc_now_iso())
    return PairEntry(
        base_asset=base,
        quote_asset="USDT",
        intervals={
            "1d": PairIntervalEntry(
                from_date=cal[start].isoformat(),
                to_date=cal[start + rows - 1].isoformat(),
                rows=rows,
                fields=fields,
            )
        },
    )


def _finalize(tmp_path: Path, cal: list[dt.date], pairs: dict[str, PairEntry]) -> None:
    write_calendar(tmp_path, cal)
    write_instruments(
        tmp_path,
        {
            sym: (dt.date.fromisoformat(p.intervals["1d"].from_date), dt.date.fromisoformat(p.intervals["1d"].dates_to))
            for sym, p in pairs.items()
        },
    )
    idx = IndexData(
        schema_version=2,
        updated_at=utc_now_iso(),
        calendar=CalendarEntry(freq="day", from_date=cal[0].isoformat(), to_date=cal[-1].isoformat(), days=len(cal)),
        pairs=pairs,
        other_files={
            "calendars/day.txt": FileEntry(sha256=compute_sha256(tmp_path / "calendars" / "day.txt"), updated_at=utc_now_iso()),
            "instruments/all.txt": FileEntry(sha256=compute_sha256(tmp_path / "instruments" / "all.txt"), updated_at=utc_now_iso()),
        },
    )
    save_index(tmp_path, idx)


def test_verify_valid_dataset(tmp_path):
    _build_valid_dataset(tmp_path)
    report = verify_dataset(tmp_path)
    assert report.ok, report.problems


def test_verify_reports_checks_performed(tmp_path):
    _build_valid_dataset(tmp_path)
    report = verify_dataset(tmp_path, fail_on_gap=True)
    assert report.ok, report.problems
    joined = " ".join(report.checks)
    for token in ("schema_version", "calendar", "instruments", "per-pair", "interior calendar gap", "orphan"):
        assert token in joined, f"missing check mentioning {token!r}: {report.checks}"


def test_verify_fails_on_interior_gap(tmp_path):
    """Two pairs leave a middle stretch of calendar covered by no pair → gap → FAIL."""
    cal = [dt.date(2024, 1, 1) + dt.timedelta(days=i) for i in range(6)]
    pairs = {
        "BTCUSDT": _mk_pair(tmp_path, cal, "BTCUSDT", "BTC", start=0, rows=2),  # covers 01-01..01-02
        "ETHUSDT": _mk_pair(tmp_path, cal, "ETHUSDT", "ETH", start=4, rows=2),  # covers 01-05..01-06
    }
    _finalize(tmp_path, cal, pairs)
    # Off by default (harness-safe: the download→rename intermediate is structurally valid)...
    assert verify_dataset(tmp_path).ok
    # ...but the user-facing command opts in and flags it.
    report = verify_dataset(tmp_path, fail_on_gap=True)
    assert not report.ok
    gap = next(p for p in report.problems if "interior calendar gap" in p)
    assert "2024-01-03..2024-01-04" in gap  # the uncovered middle days


def test_verify_reports_synthetic_nan_days_without_failing(tmp_path):
    """NaN price (rename gap fill) is reported as synthetic, not treated as a problem."""
    cal = [dt.date(2024, 1, 1) + dt.timedelta(days=i) for i in range(5)]
    pairs = {"POLUSDT": _mk_pair(tmp_path, cal, "POLUSDT", "POL", start=0, rows=5, nan_offsets=(2, 3))}
    _finalize(tmp_path, cal, pairs)
    report = verify_dataset(tmp_path)
    assert report.ok, report.problems  # synthetic NaN is informational, not a failure
    assert any("POLUSDT" in s and "synthetic" in s for s in report.synthetic)
    assert any("2024-01-03..2024-01-04" in s for s in report.synthetic)


def test_verify_reports_missing_index_when_components_present(tmp_path):
    """A partial state (components on disk but no index.json) is NOT ok."""
    (tmp_path / "calendars").mkdir()
    (tmp_path / "calendars" / "day.txt").write_text("2024-01-01\n")
    report = verify_dataset(tmp_path)
    assert not report.ok
    assert any("index.json" in p or "partial" in p for p in report.problems)


def test_verify_empty_directory_is_ok_with_is_empty_flag(tmp_path):
    report = verify_dataset(tmp_path)
    assert report.ok
    assert report.is_empty
    assert report.problems == []


def test_verify_nonexistent_directory_is_ok_with_is_empty_flag(tmp_path):
    # The pre-flight contract: verify_dataset on a path that doesn't exist yet should not crash.
    report = verify_dataset(tmp_path / "does_not_exist")
    assert report.ok
    assert report.is_empty


def test_verify_partial_state_index_missing_is_not_ok(tmp_path):
    # Only calendars/ present — partial/broken state.
    (tmp_path / "calendars").mkdir()
    (tmp_path / "calendars" / "day.txt").write_text("2024-01-01\n")
    report = verify_dataset(tmp_path)
    assert not report.ok
    assert not report.is_empty
    assert any("partial" in p or "missing" in p for p in report.problems)


def test_verify_index_only_no_components_is_not_ok(tmp_path):
    # Only index.json present, no components — partial/broken state.
    # has_index=True but has_components=False: falls through to load_index.
    # load_index("{}")  raises KeyError since the dict is missing required fields.
    import pytest

    (tmp_path / "index.json").write_text("{}")
    with pytest.raises(KeyError):
        verify_dataset(tmp_path)


def test_verify_detects_bin_sha_mismatch(tmp_path):
    idx = _build_valid_dataset(tmp_path)
    # Tamper one bin (must NOT touch sha header — just append bytes).
    target = tmp_path / "features" / "btcusdt" / "close.day.bin"
    target.write_bytes(target.read_bytes() + b"\x00\x00\x00\x00")
    report = verify_dataset(tmp_path)
    assert not report.ok
    assert any("close" in p and ("sha256" in p or "size" in p) for p in report.problems)


def test_verify_detects_calendar_gap(tmp_path):
    _build_valid_dataset(tmp_path)
    # Remove the middle date — calendar becomes non-dense.
    (tmp_path / "calendars" / "day.txt").write_text("2024-01-01\n2024-01-03\n")
    report = verify_dataset(tmp_path)
    assert not report.ok
    assert any("calendar" in p.lower() for p in report.problems)


def test_verify_detects_rows_mismatch(tmp_path):
    _build_valid_dataset(tmp_path)
    raw = json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))
    raw["pairs"]["BTCUSDT"]["intervals"]["1d"]["rows"] += 1
    (tmp_path / "index.json").write_text(json.dumps(raw), encoding="utf-8")
    report = verify_dataset(tmp_path)
    assert not report.ok
    assert any("rows" in p for p in report.problems)


def test_verify_detects_orphan_bin(tmp_path):
    _build_valid_dataset(tmp_path)
    orphan = tmp_path / "features" / "btcusdt" / "junk.day.bin"
    orphan.write_bytes(b"\x00" * 4)
    report = verify_dataset(tmp_path)
    assert not report.ok
    assert any("orphan" in p for p in report.problems)


def test_verify_detects_header_start_index_mismatch(tmp_path):
    _build_valid_dataset(tmp_path)
    # Rewrite a bin so its header start-index disagrees with the calendar position.
    target = tmp_path / "features" / "ethusdt" / "open.day.bin"
    # ETH starts at calendar index 1; write a bin claiming start 0.
    write_bin(target, [1.0, 1.0], start_index=0)  # wrong header
    # Patch sha to match so we isolate the header check.
    raw = json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))
    raw["pairs"]["ETHUSDT"]["intervals"]["1d"]["fields"]["open"]["sha256"] = compute_sha256(target)
    # Bin now has 2+1=3 floats * 4 bytes = 12 bytes, but expected rows=2 so size is fine.
    (tmp_path / "index.json").write_text(json.dumps(raw), encoding="utf-8")
    report = verify_dataset(tmp_path)
    assert not report.ok
    assert any("header" in p for p in report.problems)


def test_verify_detects_calendar_sha_mismatch_even_when_instruments_missing(tmp_path):
    """The calendar sha check must run regardless of whether instruments/all.txt exists."""
    _build_valid_dataset(tmp_path)
    # Remove instruments AND tamper the calendar file's bytes.
    (tmp_path / "instruments" / "all.txt").unlink()
    cal = tmp_path / "calendars" / "day.txt"
    cal.write_text(cal.read_text(encoding="utf-8") + "\n", encoding="utf-8")  # extra blank → different sha
    report = verify_dataset(tmp_path)
    assert not report.ok
    problems = report.problems
    # Both problems should surface (calendar sha + missing instruments)
    assert any("calendars/day.txt sha256 mismatch" in p for p in problems), problems
    assert any("instruments/all.txt missing" in p for p in problems), problems


def test_verify_detects_orphan_in_instruments_dir(tmp_path):
    _build_valid_dataset(tmp_path)
    (tmp_path / "instruments" / "stray.txt").write_text("hello")
    report = verify_dataset(tmp_path)
    assert not report.ok
    assert any("orphan" in p and "stray.txt" in p for p in report.problems)


def _mk_pair_with_funding(
    tmp_path: Path,
    cal: list[dt.date],
    sym: str,
    base: str,
    start: int,
    rows: int,
    funding_values: list[float] | None = None,
) -> PairEntry:
    """Build a PairEntry that includes a funding.day.bin alongside the kline fields."""
    fields = {}
    for f in FIELDS:
        bin_rel = f"features/{sym.lower()}/{f}.day.bin"
        write_bin(tmp_path / bin_rel, [1.0] * rows, start_index=start)
        fields[f] = FieldEntry(bin=bin_rel, sha256=compute_sha256(tmp_path / bin_rel), updated_at=utc_now_iso())
    # funding field — values default to real data (non-NaN) spanning the full row range
    fvals = funding_values if funding_values is not None else [0.0001] * rows
    funding_rel = f"features/{sym.lower()}/funding.day.bin"
    write_bin(tmp_path / funding_rel, fvals, start_index=start)
    fields["funding"] = FieldEntry(bin=funding_rel, sha256=compute_sha256(tmp_path / funding_rel), updated_at=utc_now_iso())
    return PairEntry(
        base_asset=base,
        quote_asset="USDT",
        intervals={
            "1d": PairIntervalEntry(
                from_date=cal[start].isoformat(),
                to_date=cal[start + rows - 1].isoformat(),
                rows=rows,
                fields=fields,
            )
        },
    )


def test_verify_funding_reports_coverage_check(tmp_path):
    """A dataset with funding bins should have a per-instrument coverage check reported."""
    cal = [dt.date(2024, 1, 1) + dt.timedelta(days=i) for i in range(5)]
    pairs = {"BTCUSDT": _mk_pair_with_funding(tmp_path, cal, "BTCUSDT", "BTC", start=0, rows=5)}
    _finalize(tmp_path, cal, pairs)
    report = verify_dataset(tmp_path)
    assert report.ok, report.problems
    # A human-readable funding coverage check must appear
    funding_checks = [c for c in report.checks if "funding" in c.lower()]
    assert funding_checks, f"No funding check in report.checks: {report.checks}"
    # Should mention the instrument and a date range
    assert any("BTCUSDT" in c for c in funding_checks), funding_checks


def test_verify_funding_all_nan_reported_not_failed(tmp_path):
    """An all-NaN funding bin is reported as an observation but must NOT add to problems."""
    cal = [dt.date(2024, 1, 1) + dt.timedelta(days=i) for i in range(5)]
    all_nan = [float("nan")] * 5
    pairs = {"PEPEUSDT": _mk_pair_with_funding(tmp_path, cal, "PEPEUSDT", "PEPE", start=0, rows=5, funding_values=all_nan)}
    _finalize(tmp_path, cal, pairs)
    report = verify_dataset(tmp_path)
    assert report.ok, report.problems  # all-NaN funding is NOT a hard failure
    # But the situation must be surfaced (in checks or synthetic)
    all_text = " ".join(report.checks + report.synthetic)
    assert "PEPEUSDT" in all_text and ("no coverage" in all_text or "all NaN" in all_text or "all-NaN" in all_text)


def test_verify_funding_absent_reported_not_failed(tmp_path):
    """When funding.day.bin is missing entirely, it is reported but does NOT fail the dataset."""
    cal = [dt.date(2024, 1, 1) + dt.timedelta(days=i) for i in range(5)]
    # Build a pair WITHOUT a funding field
    pairs = {"NEWUSDT": _mk_pair(tmp_path, cal, "NEWUSDT", "NEW", start=0, rows=5)}
    _finalize(tmp_path, cal, pairs)
    report = verify_dataset(tmp_path)
    assert report.ok, report.problems  # absent funding is NOT a hard failure
    all_text = " ".join(report.checks + report.synthetic)
    assert "NEWUSDT" in all_text and ("no coverage" in all_text or "absent" in all_text or "no funding" in all_text)


def test_verify_funding_structural_corruption_is_problem(tmp_path):
    """A funding.day.bin with a wrong start_index (structural corruption) IS a problem."""
    cal = [dt.date(2024, 1, 1) + dt.timedelta(days=i) for i in range(5)]
    pairs = {"BTCUSDT": _mk_pair_with_funding(tmp_path, cal, "BTCUSDT", "BTC", start=0, rows=5)}
    _finalize(tmp_path, cal, pairs)

    # Overwrite funding.day.bin with a wrong start_index (2 instead of 0)
    funding_path = tmp_path / "features" / "btcusdt" / "funding.day.bin"
    import json as _json  # noqa: PLC0415 (local import for test isolation)

    write_bin(funding_path, [0.0001] * 5, start_index=2)  # wrong: BTC starts at 0
    # Patch SHA in index so the sha check doesn't fire first
    raw = _json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))
    raw["pairs"]["BTCUSDT"]["intervals"]["1d"]["fields"]["funding"]["sha256"] = compute_sha256(funding_path)
    (tmp_path / "index.json").write_text(_json.dumps(raw), encoding="utf-8")

    report = verify_dataset(tmp_path)
    assert not report.ok
    assert any("funding" in p and "header" in p for p in report.problems)


def test_verify_ignores_cache_and_staging_dirs(tmp_path):
    """cache/ (qlib disk cache) and .staging/ (pipeline work dir) must not trip the orphan scan.

    Boundary: the orphan scan only walks features/**/*.bin, calendars/, and instruments/ — top-level
    dirs like cache/ (written by qlib in iter-7) and .staging/ are intentionally outside that scope.
    """
    _build_valid_dataset(tmp_path)

    # qlib writes its disk cache here — these bins are NOT inside features/ so the scan ignores them
    cache_dir = tmp_path / "cache" / "feature"
    cache_dir.mkdir(parents=True)
    (cache_dir / "x.bin").write_bytes(b"\x01\x02\x03\x04")

    # pipeline staging area — also outside the scanned dirs
    staging_dir = tmp_path / ".staging"
    staging_dir.mkdir()
    (staging_dir / "leftover.txt").write_text("leftover")

    # Guard: stray top-level dirs must NOT trip the orphan scan
    report = verify_dataset(tmp_path, fail_on_gap=True)
    assert report.ok is True, report.problems
    assert report.problems == []

    # Teeth: prove the orphan scan is actually live — a .bin inside features/ that is NOT indexed
    # must be caught. Without this, the guard above passes vacuously even if the scan is broken.
    orphan = tmp_path / "features" / "btcusdt" / "orphan.day.bin"
    orphan.write_bytes(b"\x00" * 4)
    report2 = verify_dataset(tmp_path, fail_on_gap=True)
    assert report2.ok is False
    assert any("orphan" in p for p in report2.problems)
