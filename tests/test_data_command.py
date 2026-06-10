import datetime as dt
import json
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from cli.__main__ import app
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
from tests.data_fixtures import FakeSource

runner = CliRunner()


def test_bare_data_prints_help_and_exits_zero():
    result = runner.invoke(app, ["data"])
    assert result.exit_code == 0, result.output
    # Help mentions both subcommands (will exist once Tasks 7–8 land);
    # for Task 1, we only assert the group itself appears and exit is 0.
    assert "Usage" in result.output
    assert "data" in result.output.lower()


def _seed_valid_dataset(out_dir: Path) -> None:
    cal = [dt.date(2024, 1, 1), dt.date(2024, 1, 2)]
    write_calendar(out_dir, cal)
    write_instruments(out_dir, {"BTCUSDT": (cal[0], cal[-1])})
    fields = {}
    for f in FIELDS:
        rel = f"features/btcusdt/{f}.day.bin"
        write_bin(out_dir / rel, [1.0, 1.0], start_index=0)
        fields[f] = FieldEntry(bin=rel, sha256=compute_sha256(out_dir / rel), updated_at=utc_now_iso())
    idx = IndexData(
        schema_version=2,
        updated_at=utc_now_iso(),
        calendar=CalendarEntry(freq="day", from_date="2024-01-01", to_date="2024-01-02", days=2),
        pairs={
            "BTCUSDT": PairEntry(
                base_asset="BTC",
                quote_asset="USDT",
                intervals={"1d": PairIntervalEntry(from_date="2024-01-01", to_date="2024-01-02", rows=2, fields=fields)},
            )
        },
        other_files={
            "calendars/day.txt": FileEntry(sha256=compute_sha256(out_dir / "calendars" / "day.txt"), updated_at=utc_now_iso()),
            "instruments/all.txt": FileEntry(sha256=compute_sha256(out_dir / "instruments" / "all.txt"), updated_at=utc_now_iso()),
        },
    )
    save_index(out_dir, idx)


def test_data_verify_ok_exits_zero_and_prints_ok(tmp_path):
    _seed_valid_dataset(tmp_path)
    result = runner.invoke(app, ["data", "verify", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "OK" in result.output


def test_data_verify_empty_directory_prints_empty_message(tmp_path):
    empty = tmp_path / "fresh"
    empty.mkdir()
    result = runner.invoke(app, ["data", "verify", str(empty)])
    assert result.exit_code == 0, result.output
    assert "empty" in result.output.lower()


def test_data_verify_silent_empty_directory_exits_zero(tmp_path):
    empty = tmp_path / "fresh"
    empty.mkdir()
    result = runner.invoke(app, ["data", "verify", "--silent", str(empty)])
    assert result.exit_code == 0
    assert result.output.strip() == ""


def test_data_verify_fail_exits_nonzero(tmp_path):
    _seed_valid_dataset(tmp_path)
    # Corrupt the calendar
    (tmp_path / "calendars" / "day.txt").write_text("2024-01-01\n")
    result = runner.invoke(app, ["data", "verify", str(tmp_path)])
    assert result.exit_code != 0
    assert "FAIL" in result.output


def test_data_verify_silent_prints_nothing(tmp_path):
    _seed_valid_dataset(tmp_path)
    result = runner.invoke(app, ["data", "verify", "--silent", str(tmp_path)])
    assert result.exit_code == 0
    assert result.output.strip() == ""


# ---------------------------------------------------------------------------
# download command tests (Slice 3)
# ---------------------------------------------------------------------------


def _pairs_file(tmp_path: Path, names: list[str]) -> Path:
    p = tmp_path / "pairs.txt"
    p.write_text("\n".join(names) + "\n")
    return p


def test_data_download_rejects_bad_date_at_parse_time(tmp_path):
    pairs = _pairs_file(tmp_path, ["BTCUSDT"])
    result = runner.invoke(
        app,
        ["data", "download", str(tmp_path / "ds"), str(pairs), "--from", "20240101"],
    )
    assert result.exit_code != 0
    assert "YYYY-MM-DD" in result.output


def test_data_download_rejects_non_calendar_date(tmp_path):
    pairs = _pairs_file(tmp_path, ["BTCUSDT"])
    result = runner.invoke(
        app,
        ["data", "download", str(tmp_path / "ds"), str(pairs), "--from", "2024-13-40"],
    )
    assert result.exit_code != 0
    assert "calendar" in result.output.lower()


def test_data_download_unsupported_interval_exits_nonzero(tmp_path):
    pairs = _pairs_file(tmp_path, ["BTCUSDT"])
    result = runner.invoke(
        app,
        [
            "data",
            "download",
            str(tmp_path / "ds"),
            str(pairs),
            "--interval",
            "1h",
            "--from",
            "2024-01-01",
            "--to",
            "2024-01-02",
        ],
    )
    assert result.exit_code != 0
    assert "not supported" in result.output.lower() or "1d" in result.output


def test_data_download_smoke_with_fake_source(tmp_path):
    pairs = _pairs_file(tmp_path, ["BTCUSDT"])
    src = FakeSource()
    src.add_pair("BTCUSDT", "BTC", "USDT")
    for d in (dt.date(2024, 1, 1) + dt.timedelta(days=i) for i in range(3)):
        src.add_kline("BTCUSDT", "1d", d)

    with patch("cli.data.command.BinanceSource", return_value=src):
        result = runner.invoke(
            app,
            [
                "data",
                "download",
                str(tmp_path / "ds"),
                str(pairs),
                "--from",
                "2024-01-01",
                "--to",
                "2024-01-03",
            ],
        )
    assert result.exit_code == 0, result.output
    assert (tmp_path / "ds" / "index.json").exists()
    idx = json.loads((tmp_path / "ds" / "index.json").read_text(encoding="utf-8"))
    assert idx["calendar"]["to"] == "2024-01-03"


def test_data_download_dry_run_flag_accepted(tmp_path, monkeypatch):
    """`data download --dry-run` is parsed; the CLI handler passes dry_run=True to download_pipeline."""
    captured = {}

    def fake_pipeline(*args, dry_run=False, **kw):
        captured["dry_run"] = dry_run

    from cli.data import command as cmd_mod

    monkeypatch.setattr(cmd_mod, "download_pipeline", fake_pipeline)
    # Avoid touching the real network: stub BinanceSource with a no-op object
    monkeypatch.setattr(cmd_mod, "BinanceSource", lambda: object())

    pairs = tmp_path / "pairs.txt"
    pairs.write_text("BTCUSDT\n")

    result = runner.invoke(
        app,
        [
            "data",
            "download",
            str(tmp_path / "ds"),
            str(pairs),
            "--from",
            "2024-01-01",
            "--to",
            "2024-01-02",
            "--dry-run",
        ],
    )
    assert result.exit_code == 0, result.output
    assert captured.get("dry_run") is True


def test_data_backfill_dry_run_flag_accepted(tmp_path, monkeypatch):
    """`data backfill --dry-run` is parsed; the CLI handler passes dry_run=True to backfill_pipeline."""
    captured = {}

    def fake_pipeline(*args, dry_run=False, **kw):
        captured["dry_run"] = dry_run

    from cli.data import command as cmd_mod

    monkeypatch.setattr(cmd_mod, "backfill_pipeline", fake_pipeline)
    monkeypatch.setattr(cmd_mod, "BinanceSource", lambda: object())

    result = runner.invoke(
        app,
        [
            "data",
            "backfill",
            str(tmp_path / "ds"),
            "--to",
            "2024-01-02",
            "--dry-run",
        ],
    )
    assert result.exit_code == 0, result.output
    assert captured.get("dry_run") is True


def test_data_delist_dry_run_flag_accepted(tmp_path, monkeypatch):
    """`data delist --dry-run` is parsed; the CLI handler passes dry_run=True to delist_pipeline."""
    captured = {}

    def fake_pipeline(*args, dry_run=False, **kw):
        captured["dry_run"] = dry_run

    from cli.data import command as cmd_mod

    monkeypatch.setattr(cmd_mod, "delist_pipeline", fake_pipeline)

    result = runner.invoke(app, ["data", "delist", str(tmp_path / "ds"), "BTCUSDT", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert captured.get("dry_run") is True


def test_data_rename_dry_run_flag_accepted(tmp_path, monkeypatch):
    """`data rename --dry-run` is parsed; the CLI handler passes dry_run=True to rename_pipeline."""
    captured = {}

    def fake_pipeline(*args, dry_run=False, **kw):
        captured["dry_run"] = dry_run

    from cli.data import command as cmd_mod

    monkeypatch.setattr(cmd_mod, "rename_pipeline", fake_pipeline)
    monkeypatch.setattr(cmd_mod, "BinanceSource", lambda: object())

    result = runner.invoke(app, ["data", "rename", str(tmp_path / "ds"), "MATICUSDT", "POLUSDT", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert captured.get("dry_run") is True
