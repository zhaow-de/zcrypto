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
            intervals={"1d": PairIntervalEntry(from_date=cal[start].isoformat(), rows=rows, fields=fields)},
        )
    idx = IndexData(
        schema_version=1,
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


def test_verify_valid_dataset(tmp_path):
    _build_valid_dataset(tmp_path)
    report = verify_dataset(tmp_path)
    assert report.ok, report.problems


def test_verify_reports_missing_index(tmp_path):
    report = verify_dataset(tmp_path)
    assert not report.ok
    assert any("index.json missing" in p for p in report.problems)


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
