# iter-4 — Data Download & Verify Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `zcrypto data download` (Binance spot 1d klines → checksum-validated, append-aware Qlib dataset + `index.json`) and `zcrypto data verify` (read-only re-validation, also reusable as a pure function), per `docs/specs/00003-data-prep-design.md`.

**Architecture:** New `cli/data/` subpackage with focused modules behind a Typer sub-app. Fetching sits behind a `Source` Protocol (stdlib `urllib.request`) so tests inject a `FakeSource` — **no network in tests**. `download` rebuilds the full dataset in a sibling `.staging/` dir, validates it via the same `verify_dataset()` that powers `verify`, then snapshots live (single tar.gz, rolling 7) and replaces files with `index.json` written last as the commit marker.

**Tech Stack:** Python 3.12 · Typer · pandas / numpy (deferred imports) · stdlib `urllib.request`, `tarfile`, `zipfile`, `hashlib`, `dataclasses`, `json` · pytest · ruff · pre-commit (mdformat / yamllint / ruff).

---

## File Structure

**Create (source):**

| File | Responsibility |
| --- | --- |
| `cli/data/__init__.py` | Empty package marker. |
| `cli/data/config.py` | Module-level constants: `BASE_URL`, `EXCHANGE_INFO_URL`, ordered `FIELDS` tuple (11 names), `SUPPORTED_INTERVALS = frozenset({"1d"})`, `SNAPSHOT_KEEP = 7`, `SCHEMA_VERSION = 1`. |
| `cli/data/klines.py` | `parse_kline_zip(zip_bytes, symbol, interval, date) -> pd.DataFrame` (single-row DataFrame with all 11 fields incl. derived `vwap`, `factor`, `date`); `assert_no_internal_gaps(observed, expected)`. Header detection. |
| `cli/data/qlib_writer.py` | Pure write/read of Qlib's binary file format: `write_calendar`, `write_instruments`, `write_bin`, `read_bin`. Float32 little-endian with start-index header. |
| `cli/data/index.py` | `IndexData` dataclasses (incl. `CalendarEntry`, `PairEntry`, `PairIntervalEntry`, `FieldEntry`, `FileEntry`), `load_index`, `save_index`, `compute_sha256`, `utc_now_iso`. |
| `cli/data/snapshots.py` | `create_snapshot(out_dir, command) -> Path` (single `<stamp>-<cmd>.tar.gz`), `prune_snapshots(out_dir, keep=7)`. |
| `cli/data/binance.py` | `Source` Protocol, URL helpers (`kline_zip_url`, `kline_checksum_url`), `parse_checksum_file`, concrete `BinanceSource` (HTTP methods marked `# pragma: no cover`). |
| `cli/data/verify.py` | `VerifyReport` dataclass + `verify_dataset(out_dir) -> VerifyReport` (pure, no printing). |
| `cli/data/pipeline.py` | Download orchestration: `parse_pairs_file`, `validate_pairs_against_exchange`, `find_first_available`, `resolve_ranges`, `fetch_all`, `build_staging`, `commit_staging`, `download_pipeline`. |
| `cli/data/command.py` | Typer sub-app: `data` group (bare → help-exit), `data download`, `data verify`. Date-arg validation callbacks. |

**Modify:**

- `cli/__main__.py` — register the `data` sub-app with `app.add_typer(data_app, name="data")`.
- `README.md` — `## Usage` documents `data download` and `data verify`.
- `docs/iterations-history.md` — append the iter-4 entry (closeout).

**Create (tests):**

| File | Coverage |
| --- | --- |
| `tests/data_fixtures.py` | Test helpers (non-test module): `synthetic_kline_csv`, `make_zip_with_checksum`, `FakeSource`. Not auto-discovered by pytest. |
| `tests/test_data_config.py` | Constants sanity. |
| `tests/test_data_klines.py` | CSV parse with/without header, `vwap` derivation incl. zero-volume fallback, gap check, wrong-date detection. |
| `tests/test_data_qlib_writer.py` | calendar / instruments file shape; bin round-trip incl. start-index header. |
| `tests/test_data_index.py` | Dataclass `to_dict`/`from_dict` round-trip; `load_index` returns `None` when missing; `compute_sha256` matches `hashlib`. |
| `tests/test_data_snapshots.py` | Archive contains only `SNAPSHOT_ITEMS`; prune keeps newest 7. |
| `tests/test_data_binance.py` | URL builders; `parse_checksum_file` valid + malformed. |
| `tests/test_data_verify.py` | Happy path + each failure path (missing index, bad sha, bad bin size, orphans, calendar gap, instruments mismatch). |
| `tests/test_data_pipeline.py` | `parse_pairs_file`, `validate_pairs_against_exchange`, `find_first_available`, full `download_pipeline` (fresh + extend + reconcile errors). |
| `tests/test_data_command.py` | Bare `zcrypto data` prints help + exits 0; bad `--from` rejected at parse time; `data verify --silent` exit codes; `data download` smoke. |

---

## Conventions for every commit

- Per-commit `Co-Authored-By: Claude <Model> <noreply@anthropic.com>` (use the **actual** model that authored the commit; the **subagent's own model** when subagent-authored — see `commit-messages.md`).
- Conventional Commit form: `<type>(data): <subject>`. Type is `feat` for new behavior, `test` for tests-only, `docs` for docs.
- Re-stage and re-commit after any pre-commit reformat (mdformat / ruff). **Never** `--no-verify`.
- Subject lines lowercase, imperative, no trailing period.

---

## Task 1: Bootstrap — `cli/data/` package, constants, bare `zcrypto data` help-only

**Files:**

- Create: `cli/data/__init__.py`, `cli/data/config.py`, `cli/data/command.py`
- Modify: `cli/__main__.py`
- Test: `tests/test_data_config.py`, `tests/test_data_command.py`

### Step 1.1: Write failing tests

- [ ] Create `tests/test_data_config.py`:

```python
from cli.data import config


def test_supported_intervals_is_1d_only():
    assert config.SUPPORTED_INTERVALS == frozenset({"1d"})


def test_fields_ordered_eleven_unique():
    assert isinstance(config.FIELDS, tuple)
    assert len(config.FIELDS) == 11
    assert len(set(config.FIELDS)) == 11
    assert config.FIELDS[:5] == ("open", "high", "low", "close", "volume")


def test_constants_present():
    assert config.BASE_URL == "https://data.binance.vision"
    assert config.EXCHANGE_INFO_URL == "https://api.binance.com/api/v3/exchangeInfo"
    assert config.SNAPSHOT_KEEP == 7
    assert config.SCHEMA_VERSION == 1
```

- [ ] Create `tests/test_data_command.py` with just the bare-help smoke for now:

```python
from typer.testing import CliRunner

from cli.__main__ import app

runner = CliRunner()


def test_bare_data_prints_help_and_exits_zero():
    result = runner.invoke(app, ["data"])
    assert result.exit_code == 0, result.output
    # Help mentions both subcommands (will exist once Tasks 7–8 land);
    # for Task 1, we only assert the group itself appears and exit is 0.
    assert "Usage" in result.output
    assert "data" in result.output.lower()
```

### Step 1.2: Run tests — expect failures

```bash
uv run pytest tests/test_data_config.py tests/test_data_command.py -v
```

Expected: import errors (`cli.data` does not exist).

### Step 1.3: Implement `cli/data/__init__.py`

- [ ] Write `cli/data/__init__.py` (empty file):

```python
```

### Step 1.4: Implement `cli/data/config.py`

- [ ] Write `cli/data/config.py`:

```python
from __future__ import annotations

BASE_URL = "https://data.binance.vision"
EXCHANGE_INFO_URL = "https://api.binance.com/api/v3/exchangeInfo"

FIELDS: tuple[str, ...] = (
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "trades",
    "taker_buy_base",
    "taker_buy_amount",
    "vwap",
    "factor",
)

SUPPORTED_INTERVALS = frozenset({"1d"})
SNAPSHOT_KEEP = 7
SCHEMA_VERSION = 1
```

### Step 1.5: Implement `cli/data/command.py` — group callback only

- [ ] Write `cli/data/command.py`:

```python
from __future__ import annotations

import typer

data_app = typer.Typer(
    add_completion=False,
    context_settings={"help_option_names": ["-h", "--help"]},
    help="Prepare a Qlib-ready dataset from Binance spot klines.",
    no_args_is_help=True,
)


@data_app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """`zcrypto data` — bare invocation prints this group's help and exits."""
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()
```

### Step 1.6: Wire into `cli/__main__.py`

- [ ] Edit `cli/__main__.py` — add the new import + registration alongside the existing `example` registration. After the existing `app.command(name="example")(example)` line, add:

```python
from cli.data.command import data_app

app.add_typer(data_app, name="data")
```

(Keep import order: imports at the bottom of the file, mirroring the `example` pattern. Deferred imports keep `zcrypto --version` fast — the new module is stdlib-only at import time, so this is safe.)

### Step 1.7: Run tests — expect pass

```bash
uv run pytest tests/test_data_config.py tests/test_data_command.py -v
```

Expected: 4 passed.

### Step 1.8: Run linters

```bash
uv run ruff check cli/data tests/test_data_config.py tests/test_data_command.py
uv run ruff format cli/data tests/test_data_config.py tests/test_data_command.py
```

### Step 1.9: Commit

```bash
git add cli/__main__.py cli/data tests/test_data_config.py tests/test_data_command.py
git commit -m "feat(data): scaffold cli/data subpackage with help-only data command

Co-Authored-By: Claude <ACTUAL_MODEL> <noreply@anthropic.com>"
```

(Replace `<ACTUAL_MODEL>` with the actual model that authored this commit, e.g. `Sonnet 4.6`. If pre-commit reformats, re-stage and re-commit.)

---

## Task 2: Klines parser (CSV → normalized 11-field DataFrame)

**Files:**

- Create: `cli/data/klines.py`
- Test: `tests/test_data_klines.py`, `tests/data_fixtures.py`

### Step 2.1: Create test-only fixtures module `tests/data_fixtures.py`

- [ ] Write `tests/data_fixtures.py` (helpers; not a test file, no pytest discovery):

```python
"""Shared, non-test helpers for cli/data tests. Imported explicitly by tests."""

from __future__ import annotations

import datetime as dt
import hashlib
import io
import zipfile


def synthetic_kline_csv(date: dt.date, *, base_price: float = 100.0, base_vol: float = 50.0) -> str:
    """One Binance-shaped 12-column 1d kline CSV row for the given UTC date."""
    open_ms = int(dt.datetime(date.year, date.month, date.day, tzinfo=dt.timezone.utc).timestamp() * 1000)
    close_ms = open_ms + 86_400_000 - 1
    open_ = base_price
    close = base_price * 1.01
    high = close * 1.02
    low = open_ * 0.98
    volume = base_vol
    quote_volume = volume * (open_ + close) / 2.0
    trades = 100
    taker_buy_base = volume * 0.5
    taker_buy_quote = quote_volume * 0.5
    return (
        f"{open_ms},{open_},{high},{low},{close},{volume},{close_ms},"
        f"{quote_volume},{trades},{taker_buy_base},{taker_buy_quote},0\n"
    )


def make_zip_with_checksum(csv_text: str, inner_name: str) -> tuple[bytes, str]:
    """Pack csv_text into a zip with inner_name; return (zip_bytes, sha256_hex)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(inner_name, csv_text)
    zip_bytes = buf.getvalue()
    return zip_bytes, hashlib.sha256(zip_bytes).hexdigest()
```

### Step 2.2: Write failing tests

- [ ] Create `tests/test_data_klines.py`:

```python
import datetime as dt
import io
import zipfile

import pytest

from cli.data.klines import assert_no_internal_gaps, parse_kline_zip
from tests.data_fixtures import make_zip_with_checksum, synthetic_kline_csv


D = dt.date(2024, 1, 2)


def test_parse_kline_zip_no_header_one_row():
    csv = synthetic_kline_csv(D, base_price=100.0, base_vol=50.0)
    zip_bytes, _ = make_zip_with_checksum(csv, f"BTCUSDT-1d-{D}.csv")
    df = parse_kline_zip(zip_bytes, "BTCUSDT", "1d", D)
    assert len(df) == 1
    row = df.iloc[0]
    assert row["date"] == D
    assert row["open"] == pytest.approx(100.0)
    assert row["close"] == pytest.approx(101.0)
    assert row["volume"] == pytest.approx(50.0)
    # vwap = amount/volume = (50 * (100+101)/2) / 50 = 100.5
    assert row["vwap"] == pytest.approx(100.5)
    assert row["factor"] == pytest.approx(1.0)


def test_parse_kline_zip_skips_header_row():
    header = (
        "open_time,open,high,low,close,volume,close_time,quote_asset_volume,"
        "count,taker_buy_base_volume,taker_buy_quote_volume,ignore\n"
    )
    csv = header + synthetic_kline_csv(D)
    zip_bytes, _ = make_zip_with_checksum(csv, f"BTCUSDT-1d-{D}.csv")
    df = parse_kline_zip(zip_bytes, "BTCUSDT", "1d", D)
    assert df.iloc[0]["date"] == D


def test_parse_kline_zip_zero_volume_vwap_falls_back_to_close():
    open_ms = int(dt.datetime(D.year, D.month, D.day, tzinfo=dt.timezone.utc).timestamp() * 1000)
    close_ms = open_ms + 86_400_000 - 1
    csv = f"{open_ms},100,101,99,100.5,0,{close_ms},0,0,0,0,0\n"
    zip_bytes, _ = make_zip_with_checksum(csv, f"BTCUSDT-1d-{D}.csv")
    df = parse_kline_zip(zip_bytes, "BTCUSDT", "1d", D)
    assert df.iloc[0]["volume"] == 0
    assert df.iloc[0]["vwap"] == pytest.approx(100.5)  # = close


def test_parse_kline_zip_wrong_date_raises():
    csv = synthetic_kline_csv(D)
    zip_bytes, _ = make_zip_with_checksum(csv, f"BTCUSDT-1d-{D}.csv")
    with pytest.raises(ValueError, match="mismatch"):
        parse_kline_zip(zip_bytes, "BTCUSDT", "1d", dt.date(2024, 1, 3))


def test_parse_kline_zip_more_than_one_file_in_zip_raises():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("a.csv", "x")
        zf.writestr("b.csv", "x")
    with pytest.raises(ValueError, match="exactly one file"):
        parse_kline_zip(buf.getvalue(), "BTCUSDT", "1d", D)


def test_assert_no_internal_gaps_passes():
    expected = [D, D + dt.timedelta(days=1), D + dt.timedelta(days=2)]
    observed = list(expected)
    assert_no_internal_gaps(observed, expected)  # no raise


def test_assert_no_internal_gaps_raises_on_missing():
    expected = [D, D + dt.timedelta(days=1), D + dt.timedelta(days=2)]
    observed = [D, D + dt.timedelta(days=2)]
    with pytest.raises(ValueError, match="gap"):
        assert_no_internal_gaps(observed, expected)
```

### Step 2.3: Run tests — expect failures

```bash
uv run pytest tests/test_data_klines.py -v
```

Expected: import errors.

### Step 2.4: Implement `cli/data/klines.py`

- [ ] Write `cli/data/klines.py`:

```python
from __future__ import annotations

import datetime as dt
import io
import zipfile
from collections.abc import Iterable

import pandas as pd

_RAW_COLS = [
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_asset_volume",
    "count",
    "taker_buy_base_volume",
    "taker_buy_quote_volume",
    "ignore",
]


def parse_kline_zip(zip_bytes: bytes, symbol: str, interval: str, date: dt.date) -> pd.DataFrame:
    """Decode one Binance daily kline zip → single-row DataFrame with normalized 11 fields + date."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = zf.namelist()
        if len(names) != 1:
            raise ValueError(f"{symbol} {date}: expected exactly one file in zip, got {names}")
        csv_bytes = zf.read(names[0])

    # Header detection: try first cell as int. Recent files may carry a header.
    first_cell = csv_bytes.split(b",", 1)[0].split(b"\n", 1)[0].strip()
    skiprows = 0 if first_cell.lstrip(b"-").isdigit() else 1
    df = pd.read_csv(io.BytesIO(csv_bytes), header=None, skiprows=skiprows, names=_RAW_COLS)

    if len(df) != 1:
        raise ValueError(f"{symbol} {date}: expected 1 row in kline csv, got {len(df)}")

    row = df.iloc[0]
    obs = dt.datetime.fromtimestamp(int(row["open_time"]) / 1000, tz=dt.timezone.utc).date()
    if obs != date:
        raise ValueError(f"{symbol} {date}: kline open_time maps to {obs}, mismatch")

    volume = float(row["volume"])
    amount = float(row["quote_asset_volume"])
    close = float(row["close"])
    vwap = amount / volume if volume != 0.0 else close

    return pd.DataFrame(
        [
            {
                "date": obs,
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": close,
                "volume": volume,
                "amount": amount,
                "trades": float(row["count"]),
                "taker_buy_base": float(row["taker_buy_base_volume"]),
                "taker_buy_amount": float(row["taker_buy_quote_volume"]),
                "vwap": vwap,
                "factor": 1.0,
            }
        ]
    )


def assert_no_internal_gaps(observed: Iterable[dt.date], expected: Iterable[dt.date]) -> None:
    """Raise if any expected date is missing from observed (set-difference)."""
    obs = set(observed)
    missing = [d for d in expected if d not in obs]
    if missing:
        raise ValueError(f"internal gap in fetched kline sequence; missing: {missing[:5]}")
```

### Step 2.5: Run tests — expect pass

```bash
uv run pytest tests/test_data_klines.py -v
```

Expected: 7 passed.

### Step 2.6: Lint + commit

```bash
uv run ruff check cli/data/klines.py tests/data_fixtures.py tests/test_data_klines.py
uv run ruff format cli/data/klines.py tests/data_fixtures.py tests/test_data_klines.py
git add cli/data/klines.py tests/data_fixtures.py tests/test_data_klines.py
git commit -m "feat(data): add Binance kline csv parser with vwap derivation

Co-Authored-By: Claude <ACTUAL_MODEL> <noreply@anthropic.com>"
```

---

## Task 3: Qlib binary writer / reader (calendar, instruments, bins)

**Files:**

- Create: `cli/data/qlib_writer.py`
- Test: `tests/test_data_qlib_writer.py`

### Step 3.1: Write failing tests

- [ ] Create `tests/test_data_qlib_writer.py`:

```python
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
```

### Step 3.2: Run tests — expect failures

```bash
uv run pytest tests/test_data_qlib_writer.py -v
```

Expected: import errors.

### Step 3.3: Implement `cli/data/qlib_writer.py`

- [ ] Write `cli/data/qlib_writer.py`:

```python
from __future__ import annotations

import datetime as dt
from pathlib import Path

import numpy as np


def write_calendar(out_dir: Path, dates: list[dt.date]) -> None:
    """Write `<out_dir>/calendars/day.txt` — one ISO date per line, sorted."""
    cal_dir = out_dir / "calendars"
    cal_dir.mkdir(parents=True, exist_ok=True)
    lines = [d.strftime("%Y-%m-%d") for d in dates]
    (cal_dir / "day.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_instruments(out_dir: Path, pairs_to_range: dict[str, tuple[dt.date, dt.date]]) -> None:
    """Write `<out_dir>/instruments/all.txt` — `SYMBOL<TAB>FROM<TAB>TO`, sorted, uppercase."""
    inst_dir = out_dir / "instruments"
    inst_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        f"{sym.upper()}\t{f.strftime('%Y-%m-%d')}\t{t.strftime('%Y-%m-%d')}"
        for sym, (f, t) in sorted(pairs_to_range.items(), key=lambda kv: kv[0].upper())
    ]
    (inst_dir / "all.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_bin(path: Path, values: list[float], start_index: int) -> None:
    """Write a Qlib `<field>.day.bin`: [start_index_as_f4, v0, v1, ...] little-endian float32."""
    path.parent.mkdir(parents=True, exist_ok=True)
    arr = np.empty(len(values) + 1, dtype="<f4")
    arr[0] = np.float32(start_index)
    arr[1:] = np.array(values, dtype="<f4")
    arr.tofile(path)


def read_bin(path: Path) -> tuple[int, np.ndarray]:
    """Decode a Qlib `.day.bin` → (start_index, values)."""
    arr = np.fromfile(path, dtype="<f4")
    if arr.size < 1:
        raise ValueError(f"{path}: bin file is empty")
    return int(arr[0]), arr[1:]
```

### Step 3.4: Run tests — expect pass

```bash
uv run pytest tests/test_data_qlib_writer.py -v
```

Expected: 4 passed.

### Step 3.5: Lint + commit

```bash
uv run ruff check cli/data/qlib_writer.py tests/test_data_qlib_writer.py
uv run ruff format cli/data/qlib_writer.py tests/test_data_qlib_writer.py
git add cli/data/qlib_writer.py tests/test_data_qlib_writer.py
git commit -m "feat(data): add qlib binary writer/reader with start-index header

Co-Authored-By: Claude <ACTUAL_MODEL> <noreply@anthropic.com>"
```

---

## Task 4: `index.json` schema (dataclasses, r/w, sha256)

**Files:**

- Create: `cli/data/index.py`
- Test: `tests/test_data_index.py`

### Step 4.1: Write failing tests

- [ ] Create `tests/test_data_index.py`:

```python
import datetime as dt
import hashlib
import json

import pytest

from cli.data.index import (
    CalendarEntry,
    FieldEntry,
    FileEntry,
    IndexData,
    PairEntry,
    PairIntervalEntry,
    compute_sha256,
    load_index,
    save_index,
    utc_now_iso,
)


def _sample_index() -> IndexData:
    cal = CalendarEntry(freq="day", from_date="2024-01-01", to_date="2024-01-03", days=3)
    fields = {
        "open": FieldEntry(bin="features/btcusdt/open.day.bin", sha256="a" * 64, updated_at="2024-01-03T12:00:00Z"),
        "close": FieldEntry(bin="features/btcusdt/close.day.bin", sha256="b" * 64, updated_at="2024-01-03T12:00:00Z"),
    }
    pair = PairEntry(
        base_asset="BTC",
        quote_asset="USDT",
        intervals={
            "1d": PairIntervalEntry(from_date="2024-01-01", rows=3, fields=fields),
        },
    )
    return IndexData(
        schema_version=1,
        updated_at="2024-01-03T12:00:00Z",
        calendar=cal,
        pairs={"BTCUSDT": pair},
        other_files={
            "calendars/day.txt": FileEntry(sha256="c" * 64, updated_at="2024-01-03T12:00:00Z"),
            "instruments/all.txt": FileEntry(sha256="d" * 64, updated_at="2024-01-03T12:00:00Z"),
        },
    )


def test_index_roundtrip_via_dict():
    idx = _sample_index()
    d = idx.to_dict()
    rebuilt = IndexData.from_dict(d)
    assert rebuilt.to_dict() == d


def test_save_and_load_index_roundtrip(tmp_path):
    idx = _sample_index()
    save_index(tmp_path, idx)
    loaded = load_index(tmp_path)
    assert loaded.to_dict() == idx.to_dict()


def test_load_index_returns_none_when_missing(tmp_path):
    assert load_index(tmp_path) is None


def test_save_index_includes_keys_in_documented_order(tmp_path):
    save_index(tmp_path, _sample_index())
    raw = json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))
    assert list(raw.keys()) == ["schema_version", "updated_at", "calendar", "pairs", "other_files"]


def test_compute_sha256_matches_hashlib(tmp_path):
    p = tmp_path / "x.bin"
    p.write_bytes(b"abc")
    assert compute_sha256(p) == hashlib.sha256(b"abc").hexdigest()


def test_utc_now_iso_format():
    s = utc_now_iso()
    assert s.endswith("Z")
    # Round-trip parseable as a UTC datetime
    dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ")
```

### Step 4.2: Run tests — expect failures

```bash
uv run pytest tests/test_data_index.py -v
```

Expected: import errors.

### Step 4.3: Implement `cli/data/index.py`

- [ ] Write `cli/data/index.py`:

```python
from __future__ import annotations

import dataclasses as dc
import datetime as dt
import hashlib
import json
from pathlib import Path


@dc.dataclass
class FileEntry:
    sha256: str
    updated_at: str

    def to_dict(self) -> dict:
        return {"sha256": self.sha256, "updated_at": self.updated_at}

    @classmethod
    def from_dict(cls, d: dict) -> "FileEntry":
        return cls(sha256=d["sha256"], updated_at=d["updated_at"])


@dc.dataclass
class FieldEntry:
    bin: str
    sha256: str
    updated_at: str

    def to_dict(self) -> dict:
        return {"bin": self.bin, "sha256": self.sha256, "updated_at": self.updated_at}

    @classmethod
    def from_dict(cls, d: dict) -> "FieldEntry":
        return cls(bin=d["bin"], sha256=d["sha256"], updated_at=d["updated_at"])


@dc.dataclass
class PairIntervalEntry:
    from_date: str  # ISO YYYY-MM-DD
    rows: int
    fields: dict[str, FieldEntry]

    def to_dict(self) -> dict:
        return {
            "from": self.from_date,
            "rows": self.rows,
            "fields": {k: v.to_dict() for k, v in self.fields.items()},
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PairIntervalEntry":
        return cls(
            from_date=d["from"],
            rows=int(d["rows"]),
            fields={k: FieldEntry.from_dict(v) for k, v in d["fields"].items()},
        )


@dc.dataclass
class PairEntry:
    base_asset: str
    quote_asset: str
    intervals: dict[str, PairIntervalEntry]

    def to_dict(self) -> dict:
        return {
            "base_asset": self.base_asset,
            "quote_asset": self.quote_asset,
            "intervals": {k: v.to_dict() for k, v in self.intervals.items()},
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PairEntry":
        return cls(
            base_asset=d["base_asset"],
            quote_asset=d["quote_asset"],
            intervals={k: PairIntervalEntry.from_dict(v) for k, v in d["intervals"].items()},
        )


@dc.dataclass
class CalendarEntry:
    freq: str
    from_date: str
    to_date: str
    days: int

    def to_dict(self) -> dict:
        return {"freq": self.freq, "from": self.from_date, "to": self.to_date, "days": self.days}

    @classmethod
    def from_dict(cls, d: dict) -> "CalendarEntry":
        return cls(freq=d["freq"], from_date=d["from"], to_date=d["to"], days=int(d["days"]))


@dc.dataclass
class IndexData:
    schema_version: int
    updated_at: str
    calendar: CalendarEntry
    pairs: dict[str, PairEntry]
    other_files: dict[str, FileEntry]

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "updated_at": self.updated_at,
            "calendar": self.calendar.to_dict(),
            "pairs": {k: v.to_dict() for k, v in self.pairs.items()},
            "other_files": {k: v.to_dict() for k, v in self.other_files.items()},
        }

    @classmethod
    def from_dict(cls, d: dict) -> "IndexData":
        return cls(
            schema_version=int(d["schema_version"]),
            updated_at=d["updated_at"],
            calendar=CalendarEntry.from_dict(d["calendar"]),
            pairs={k: PairEntry.from_dict(v) for k, v in d["pairs"].items()},
            other_files={k: FileEntry.from_dict(v) for k, v in d["other_files"].items()},
        )


def load_index(out_dir: Path) -> IndexData | None:
    p = out_dir / "index.json"
    if not p.exists():
        return None
    return IndexData.from_dict(json.loads(p.read_text(encoding="utf-8")))


def save_index(out_dir: Path, index: IndexData) -> None:
    (out_dir / "index.json").write_text(
        json.dumps(index.to_dict(), indent=2) + "\n", encoding="utf-8"
    )


def compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def utc_now_iso() -> str:
    return dt.datetime.now(tz=dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
```

### Step 4.4: Run tests — expect pass

```bash
uv run pytest tests/test_data_index.py -v
```

Expected: 6 passed.

### Step 4.5: Lint + commit

```bash
uv run ruff check cli/data/index.py tests/test_data_index.py
uv run ruff format cli/data/index.py tests/test_data_index.py
git add cli/data/index.py tests/test_data_index.py
git commit -m "feat(data): add index.json schema with dataclasses and sha256 helper

Co-Authored-By: Claude <ACTUAL_MODEL> <noreply@anthropic.com>"
```

---

## Task 5: Snapshots (single tar.gz per snapshot, rolling 7)

**Files:**

- Create: `cli/data/snapshots.py`
- Test: `tests/test_data_snapshots.py`

### Step 5.1: Write failing tests

- [ ] Create `tests/test_data_snapshots.py`:

```python
import tarfile
import time

from cli.data.snapshots import SNAPSHOT_ITEMS, create_snapshot, prune_snapshots


def _populate(out_dir):
    (out_dir / "calendars").mkdir()
    (out_dir / "calendars" / "day.txt").write_text("2024-01-01\n")
    (out_dir / "instruments").mkdir()
    (out_dir / "instruments" / "all.txt").write_text("BTCUSDT\t2024-01-01\t2024-01-01\n")
    (out_dir / "features").mkdir()
    (out_dir / "features" / "btcusdt").mkdir()
    (out_dir / "features" / "btcusdt" / "close.day.bin").write_bytes(b"\x00" * 8)
    (out_dir / "index.json").write_text("{}\n")
    # noise that must be excluded
    (out_dir / ".staging").mkdir()
    (out_dir / ".staging" / "junk").write_text("ignored")


def test_create_snapshot_archives_only_documented_items(tmp_path):
    _populate(tmp_path)
    archive = create_snapshot(tmp_path, "download")
    assert archive.parent == tmp_path / ".snapshots"
    assert archive.name.endswith("-download.tar.gz")
    with tarfile.open(archive, "r:gz") as tar:
        names = sorted(tar.getnames())
    # Top-level archive entries must be exactly SNAPSHOT_ITEMS
    top_level = sorted({n.split("/", 1)[0] for n in names})
    assert top_level == sorted(SNAPSHOT_ITEMS)
    # Excluded
    assert all(".staging" not in n and ".snapshots" not in n for n in names)


def test_prune_snapshots_keeps_newest_seven(tmp_path):
    snaps = tmp_path / ".snapshots"
    snaps.mkdir()
    # Names sort chronologically because the stamps do.
    for i in range(10):
        (snaps / f"2024010{i % 10}T0000{i:02d}Z-download.tar.gz").write_bytes(b"x")
    removed = prune_snapshots(tmp_path, keep=7)
    remaining = sorted(p.name for p in snaps.iterdir())
    assert len(remaining) == 7
    assert len(removed) == 3


def test_prune_snapshots_noop_under_keep(tmp_path):
    snaps = tmp_path / ".snapshots"
    snaps.mkdir()
    (snaps / "20240101T000000Z-download.tar.gz").write_bytes(b"x")
    assert prune_snapshots(tmp_path, keep=7) == []


def test_create_snapshot_stamps_are_monotone(tmp_path):
    _populate(tmp_path)
    a = create_snapshot(tmp_path, "download")
    time.sleep(1.1)  # ensure stamp difference (UTC seconds resolution)
    b = create_snapshot(tmp_path, "download")
    assert a.name < b.name
```

### Step 5.2: Run tests — expect failures

```bash
uv run pytest tests/test_data_snapshots.py -v
```

Expected: import errors.

### Step 5.3: Implement `cli/data/snapshots.py`

- [ ] Write `cli/data/snapshots.py`:

```python
from __future__ import annotations

import datetime as dt
import tarfile
from pathlib import Path

from cli.data.config import SNAPSHOT_KEEP

SNAPSHOT_ITEMS: tuple[str, ...] = ("calendars", "instruments", "features", "index.json")


def create_snapshot(out_dir: Path, command: str) -> Path:
    """Pack the relevant dataset files into `<out_dir>/.snapshots/<stamp>-<cmd>.tar.gz`."""
    snap_dir = out_dir / ".snapshots"
    snap_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(tz=dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive = snap_dir / f"{stamp}-{command}.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        for name in SNAPSHOT_ITEMS:
            p = out_dir / name
            if p.exists():
                tar.add(p, arcname=name)
    return archive


def prune_snapshots(out_dir: Path, keep: int = SNAPSHOT_KEEP) -> list[Path]:
    """Keep newest `keep` archives in `<out_dir>/.snapshots/`; remove older. Return removed paths."""
    snap_dir = out_dir / ".snapshots"
    if not snap_dir.is_dir():
        return []
    archives = sorted(snap_dir.glob("*.tar.gz"))
    if len(archives) <= keep:
        return []
    removed = archives[: len(archives) - keep]
    for p in removed:
        p.unlink()
    return removed
```

### Step 5.4: Run tests — expect pass

```bash
uv run pytest tests/test_data_snapshots.py -v
```

Expected: 4 passed.

### Step 5.5: Lint + commit

```bash
uv run ruff check cli/data/snapshots.py tests/test_data_snapshots.py
uv run ruff format cli/data/snapshots.py tests/test_data_snapshots.py
git add cli/data/snapshots.py tests/test_data_snapshots.py
git commit -m "feat(data): add rolling tar.gz snapshot helpers

Co-Authored-By: Claude <ACTUAL_MODEL> <noreply@anthropic.com>"
```

---

## Task 6: Binance source (Protocol + URL helpers + concrete BinanceSource + FakeSource)

**Files:**

- Create: `cli/data/binance.py`
- Modify: `tests/data_fixtures.py` (add `FakeSource`)
- Test: `tests/test_data_binance.py`

### Step 6.1: Write failing tests

- [ ] Create `tests/test_data_binance.py`:

```python
import datetime as dt

import pytest

from cli.data.binance import kline_checksum_url, kline_zip_url, parse_checksum_file


def test_kline_zip_url_shape():
    url = kline_zip_url("BTCUSDT", "1d", dt.date(2024, 1, 2))
    assert url == (
        "https://data.binance.vision/data/spot/daily/klines/"
        "BTCUSDT/1d/BTCUSDT-1d-2024-01-02.zip"
    )


def test_kline_checksum_url_appends_suffix():
    url = kline_checksum_url("ETHUSDT", "1d", dt.date(2024, 1, 2))
    assert url == kline_zip_url("ETHUSDT", "1d", dt.date(2024, 1, 2)) + ".CHECKSUM"


def test_parse_checksum_file_valid():
    content = "a" * 64 + "  ETHUSDT-1d-2024-01-02.zip\n"
    assert parse_checksum_file(content) == "a" * 64


def test_parse_checksum_file_malformed_raises():
    with pytest.raises(ValueError, match="malformed"):
        parse_checksum_file("oops not a hash\n")
    with pytest.raises(ValueError, match="malformed"):
        parse_checksum_file("")
```

### Step 6.2: Run tests — expect failures

```bash
uv run pytest tests/test_data_binance.py -v
```

Expected: import errors.

### Step 6.3: Implement `cli/data/binance.py`

- [ ] Write `cli/data/binance.py`:

```python
from __future__ import annotations

import datetime as dt
import json
import urllib.error
import urllib.request
from typing import Protocol

from cli.data.config import BASE_URL, EXCHANGE_INFO_URL


class Source(Protocol):
    """Minimal interface for fetching Binance reference + kline data. Injected for tests."""

    def fetch_exchange_info(self) -> list[dict]: ...

    def exists_kline(self, symbol: str, interval: str, date: dt.date) -> bool: ...

    def fetch_kline_zip(self, symbol: str, interval: str, date: dt.date) -> bytes: ...

    def fetch_kline_checksum(self, symbol: str, interval: str, date: dt.date) -> str: ...


def kline_zip_url(symbol: str, interval: str, date: dt.date) -> str:
    iso = date.strftime("%Y-%m-%d")
    return f"{BASE_URL}/data/spot/daily/klines/{symbol}/{interval}/{symbol}-{interval}-{iso}.zip"


def kline_checksum_url(symbol: str, interval: str, date: dt.date) -> str:
    return kline_zip_url(symbol, interval, date) + ".CHECKSUM"


def parse_checksum_file(content: str) -> str:
    """Binance `.CHECKSUM` = `<sha256hex>  <filename>\\n` → hex (raises on malformed)."""
    head = content.strip().split(maxsplit=1)
    if not head or len(head[0]) != 64 or not all(c in "0123456789abcdefABCDEF" for c in head[0]):
        raise ValueError(f"malformed .CHECKSUM content: {content!r}")
    return head[0].lower()


class BinanceSource:
    """Concrete `Source` over stdlib `urllib.request`. HTTP paths excluded from coverage."""

    def fetch_exchange_info(self) -> list[dict]:  # pragma: no cover
        with urllib.request.urlopen(EXCHANGE_INFO_URL) as resp:
            data = json.loads(resp.read())
        return data["symbols"]

    def exists_kline(self, symbol: str, interval: str, date: dt.date) -> bool:  # pragma: no cover
        url = kline_zip_url(symbol, interval, date)
        req = urllib.request.Request(url, method="HEAD")
        try:
            with urllib.request.urlopen(req):
                return True
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return False
            raise

    def fetch_kline_zip(self, symbol: str, interval: str, date: dt.date) -> bytes:  # pragma: no cover
        with urllib.request.urlopen(kline_zip_url(symbol, interval, date)) as resp:
            return resp.read()

    def fetch_kline_checksum(self, symbol: str, interval: str, date: dt.date) -> str:  # pragma: no cover
        with urllib.request.urlopen(kline_checksum_url(symbol, interval, date)) as resp:
            return parse_checksum_file(resp.read().decode("utf-8"))
```

### Step 6.4: Run tests — expect pass

```bash
uv run pytest tests/test_data_binance.py -v
```

Expected: 4 passed.

### Step 6.5: Add `FakeSource` to `tests/data_fixtures.py`

- [ ] Append to `tests/data_fixtures.py`:

```python
import datetime as dt  # noqa: F811  (re-import is fine inside the module)


class FakeSource:
    """In-memory Source for tests; pre-load via `.add_pair` / `.add_kline`."""

    def __init__(self) -> None:
        self.exchange_info: list[dict] = []
        # (symbol, interval, date) -> (zip_bytes, sha256_hex)
        self._klines: dict[tuple[str, str, dt.date], tuple[bytes, str]] = {}

    def add_pair(self, symbol: str, base: str, quote: str) -> None:
        self.exchange_info.append(
            {"symbol": symbol, "baseAsset": base, "quoteAsset": quote, "status": "TRADING"}
        )

    def add_kline(
        self,
        symbol: str,
        interval: str,
        date: dt.date,
        *,
        base_price: float = 100.0,
        base_vol: float = 50.0,
    ) -> None:
        csv = synthetic_kline_csv(date, base_price=base_price, base_vol=base_vol)
        zip_bytes, digest = make_zip_with_checksum(csv, f"{symbol}-{interval}-{date}.csv")
        self._klines[(symbol, interval, date)] = (zip_bytes, digest)

    def tamper_kline_checksum(self, symbol: str, interval: str, date: dt.date) -> None:
        """Force a checksum mismatch on the next fetch (for negative-path tests)."""
        zb, _ = self._klines[(symbol, interval, date)]
        self._klines[(symbol, interval, date)] = (zb, "0" * 64)

    # Source protocol
    def fetch_exchange_info(self) -> list[dict]:
        return list(self.exchange_info)

    def exists_kline(self, symbol: str, interval: str, date: dt.date) -> bool:
        return (symbol, interval, date) in self._klines

    def fetch_kline_zip(self, symbol: str, interval: str, date: dt.date) -> bytes:
        return self._klines[(symbol, interval, date)][0]

    def fetch_kline_checksum(self, symbol: str, interval: str, date: dt.date) -> str:
        return self._klines[(symbol, interval, date)][1]
```

(Drop the `noqa: F811` if the `import datetime as dt` line at the top already exists — it does from Task 2.)

### Step 6.6: Lint + commit

```bash
uv run ruff check cli/data/binance.py tests/data_fixtures.py tests/test_data_binance.py
uv run ruff format cli/data/binance.py tests/data_fixtures.py tests/test_data_binance.py
git add cli/data/binance.py tests/data_fixtures.py tests/test_data_binance.py
git commit -m "feat(data): add binance Source protocol and url helpers

Co-Authored-By: Claude <ACTUAL_MODEL> <noreply@anthropic.com>"
```

---

## Task 7: `verify_dataset()` + `zcrypto data verify` CLI

**Files:**

- Create: `cli/data/verify.py`
- Modify: `cli/data/command.py` (add `verify` subcommand)
- Test: `tests/test_data_verify.py`, `tests/test_data_command.py` (extend)

### Step 7.1: Write failing tests for `verify_dataset()`

- [ ] Create `tests/test_data_verify.py`:

```python
import datetime as dt
import json
from pathlib import Path

import numpy as np

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
            "calendars/day.txt": FileEntry(
                sha256=compute_sha256(tmp_path / "calendars" / "day.txt"), updated_at=utc_now_iso()
            ),
            "instruments/all.txt": FileEntry(
                sha256=compute_sha256(tmp_path / "instruments" / "all.txt"), updated_at=utc_now_iso()
            ),
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
```

### Step 7.2: Run tests — expect failures

```bash
uv run pytest tests/test_data_verify.py -v
```

Expected: import errors.

### Step 7.3: Implement `cli/data/verify.py`

- [ ] Write `cli/data/verify.py`:

```python
from __future__ import annotations

import dataclasses as dc
import datetime as dt
from pathlib import Path

from cli.data.config import SCHEMA_VERSION
from cli.data.index import compute_sha256, load_index
from cli.data.qlib_writer import read_bin


@dc.dataclass
class VerifyReport:
    ok: bool
    problems: list[str]


def _iso_to_date(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


def verify_dataset(out_dir: Path) -> VerifyReport:
    """Read-only re-validation of every invariant in `docs/specs/00003-data-prep-design.md`."""
    problems: list[str] = []
    index = load_index(out_dir)
    if index is None:
        return VerifyReport(False, ["index.json missing"])
    if index.schema_version != SCHEMA_VERSION:
        problems.append(f"unknown schema_version {index.schema_version}")

    cal_path = out_dir / "calendars" / "day.txt"
    if not cal_path.exists():
        problems.append("calendars/day.txt missing")
        return VerifyReport(False, problems)

    raw = cal_path.read_text(encoding="utf-8").strip().splitlines()
    on_disk_dates = [_iso_to_date(line) for line in raw if line.strip()]
    cal_from = _iso_to_date(index.calendar.from_date)
    cal_to = _iso_to_date(index.calendar.to_date)
    expected_dates = [
        cal_from + dt.timedelta(days=i) for i in range((cal_to - cal_from).days + 1)
    ]
    if on_disk_dates != expected_dates:
        problems.append("calendar file is not dense or does not match index calendar")
    if len(on_disk_dates) != index.calendar.days:
        problems.append(f"calendar days {len(on_disk_dates)} != index.days {index.calendar.days}")

    cal_index = {d: i for i, d in enumerate(expected_dates)}

    inst_path = out_dir / "instruments" / "all.txt"
    if not inst_path.exists():
        problems.append("instruments/all.txt missing")
    else:
        cal_entry = index.other_files.get("calendars/day.txt")
        if cal_entry is None:
            problems.append("calendars/day.txt entry missing from other_files")
        elif compute_sha256(cal_path) != cal_entry.sha256:
            problems.append("calendars/day.txt sha256 mismatch")
        inst_entry = index.other_files.get("instruments/all.txt")
        if inst_entry is None:
            problems.append("instruments/all.txt entry missing from other_files")
        elif compute_sha256(inst_path) != inst_entry.sha256:
            problems.append("instruments/all.txt sha256 mismatch")
        instr_lines = sorted(inst_path.read_text(encoding="utf-8").strip().splitlines())
        expected_lines = sorted(
            f"{sym.upper()}\t{p.intervals['1d'].from_date}\t{index.calendar.to_date}"
            for sym, p in index.pairs.items()
            if "1d" in p.intervals
        )
        if instr_lines != expected_lines:
            problems.append("instruments/all.txt does not match index pairs")

    for sym, pair in index.pairs.items():
        for interval, entry in pair.intervals.items():
            from_d = _iso_to_date(entry.from_date)
            if from_d not in cal_index:
                problems.append(f"{sym} {interval}: from-date {from_d} not in calendar")
                continue
            start_idx = cal_index[from_d]
            expected_rows = len(expected_dates) - start_idx
            if entry.rows != expected_rows:
                problems.append(
                    f"{sym} {interval}: rows {entry.rows} != expected {expected_rows}"
                )
            for fname, fentry in entry.fields.items():
                bin_path = out_dir / fentry.bin
                if not bin_path.exists():
                    problems.append(f"{sym} {interval} {fname}: bin {fentry.bin} missing")
                    continue
                if compute_sha256(bin_path) != fentry.sha256:
                    problems.append(f"{sym} {interval} {fname}: sha256 mismatch")
                actual_size = bin_path.stat().st_size
                expected_size = (expected_rows + 1) * 4
                if actual_size != expected_size:
                    problems.append(
                        f"{sym} {interval} {fname}: bin size {actual_size} != {expected_size}"
                    )
                else:
                    header_start, _ = read_bin(bin_path)
                    if header_start != start_idx:
                        problems.append(
                            f"{sym} {interval} {fname}: header {header_start} != calendar index {start_idx}"
                        )

    indexed_bins = {
        e.bin
        for pair in index.pairs.values()
        for inter in pair.intervals.values()
        for e in inter.fields.values()
    }
    features_dir = out_dir / "features"
    if features_dir.is_dir():
        for p in features_dir.rglob("*.bin"):
            rel = p.relative_to(out_dir).as_posix()
            if rel not in indexed_bins:
                problems.append(f"orphan bin file: {rel}")

    return VerifyReport(ok=not problems, problems=problems)
```

### Step 7.4: Run tests — expect pass

```bash
uv run pytest tests/test_data_verify.py -v
```

Expected: 7 passed.

### Step 7.5: Add `data verify` CLI command + `--silent`

- [ ] Edit `cli/data/command.py` — add the imports at the top (alongside the existing `import typer`):

```python
from pathlib import Path

from cli.data.verify import verify_dataset
```

Then append at the bottom of the file (after the existing group callback):

```python
@data_app.command("verify")
def verify_cmd(
    out_dir: Path = typer.Argument(..., help="Dataset directory to validate.", exists=True, file_okay=False),
    silent: bool = typer.Option(False, "--silent", help="Print nothing; convey result via exit code only."),
) -> None:
    """Re-validate an existing dataset against `index.json` and all invariants."""
    report = verify_dataset(out_dir)
    if not silent:
        if report.ok:
            typer.echo(f"OK — {out_dir} validates clean.")
        else:
            typer.echo(f"FAIL — {len(report.problems)} problem(s) in {out_dir}:")
            for p in report.problems:
                typer.echo(f"  - {p}")
    raise typer.Exit(code=0 if report.ok else 1)
```

### Step 7.6: Add CLI-integration tests for verify

- [ ] Append to `tests/test_data_command.py`:

```python
import datetime as dt
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
        schema_version=1,
        updated_at=utc_now_iso(),
        calendar=CalendarEntry(freq="day", from_date="2024-01-01", to_date="2024-01-02", days=2),
        pairs={
            "BTCUSDT": PairEntry(
                base_asset="BTC",
                quote_asset="USDT",
                intervals={"1d": PairIntervalEntry(from_date="2024-01-01", rows=2, fields=fields)},
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
```

### Step 7.7: Run tests — expect pass

```bash
uv run pytest tests/test_data_verify.py tests/test_data_command.py -v
```

Expected: 10+ passed (verify unit + CLI integration).

### Step 7.8: Lint + commit

```bash
uv run ruff check cli/data tests/test_data_verify.py tests/test_data_command.py
uv run ruff format cli/data tests/test_data_verify.py tests/test_data_command.py
git add cli/data/verify.py cli/data/command.py tests/test_data_verify.py tests/test_data_command.py
git commit -m "feat(data): add verify_dataset and zcrypto data verify command

Co-Authored-By: Claude <ACTUAL_MODEL> <noreply@anthropic.com>"
```

---

## Task 8: `download_pipeline` + `zcrypto data download` CLI

**Files:**

- Create: `cli/data/pipeline.py`
- Modify: `cli/data/command.py` (add `download` subcommand + date-arg validators)
- Test: `tests/test_data_pipeline.py`, `tests/test_data_command.py` (extend)

This task is bigger; commits are split per logical slice (helpers → resolver → orchestration → CLI).

### Step 8.1: Write failing tests for the helper functions

- [ ] Create `tests/test_data_pipeline.py`:

```python
import datetime as dt
from pathlib import Path

import pytest

from cli.data.pipeline import (
    PipelineError,
    find_first_available,
    parse_pairs_file,
    validate_pairs_against_exchange,
)
from tests.data_fixtures import FakeSource


def test_parse_pairs_file_returns_unique_nonblank_lines(tmp_path):
    p = tmp_path / "pairs.txt"
    p.write_text("BTCUSDT\n\nETHUSDT\nBTCUSDT\n\n")
    assert parse_pairs_file(p) == ["BTCUSDT", "ETHUSDT"]


def test_parse_pairs_file_missing_file_raises(tmp_path):
    with pytest.raises(PipelineError, match="does not exist"):
        parse_pairs_file(tmp_path / "missing.txt")


def test_parse_pairs_file_empty_or_blank_raises(tmp_path):
    p = tmp_path / "pairs.txt"
    p.write_text("\n\n\n")
    with pytest.raises(PipelineError, match="no symbols"):
        parse_pairs_file(p)


def test_validate_pairs_against_exchange_returns_base_quote_map():
    info = [
        {"symbol": "BTCUSDT", "baseAsset": "BTC", "quoteAsset": "USDT"},
        {"symbol": "ETHUSDT", "baseAsset": "ETH", "quoteAsset": "USDT"},
    ]
    assert validate_pairs_against_exchange(["BTCUSDT", "ETHUSDT"], info) == {
        "BTCUSDT": ("BTC", "USDT"),
        "ETHUSDT": ("ETH", "USDT"),
    }


def test_validate_pairs_against_exchange_unknown_raises():
    info = [{"symbol": "BTCUSDT", "baseAsset": "BTC", "quoteAsset": "USDT"}]
    with pytest.raises(PipelineError, match="WHATUSDT"):
        validate_pairs_against_exchange(["BTCUSDT", "WHATUSDT"], info)


def test_find_first_available_finds_start_of_listing():
    src = FakeSource()
    listing_start = dt.date(2024, 1, 5)
    for d in (listing_start + dt.timedelta(days=i) for i in range(10)):
        src.add_kline("XYZUSDT", "1d", d)
    found = find_first_available(src, "XYZUSDT", "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 14))
    assert found == listing_start


def test_find_first_available_returns_none_when_window_predates_listing():
    src = FakeSource()
    assert find_first_available(src, "ZZZUSDT", "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 14)) is None


def test_find_first_available_skips_search_when_lo_exists():
    src = FakeSource()
    for d in (dt.date(2024, 1, 1) + dt.timedelta(days=i) for i in range(5)):
        src.add_kline("ABCUSDT", "1d", d)
    found = find_first_available(src, "ABCUSDT", "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 5))
    assert found == dt.date(2024, 1, 1)
```

### Step 8.2: Run helper tests — expect failures

```bash
uv run pytest tests/test_data_pipeline.py -v
```

Expected: import errors.

### Step 8.3: Implement helpers in `cli/data/pipeline.py`

- [ ] Write `cli/data/pipeline.py` (initial slice — helpers only):

```python
from __future__ import annotations

import datetime as dt
from pathlib import Path

from cli.data.binance import Source

__all__ = [
    "PipelineError",
    "parse_pairs_file",
    "validate_pairs_against_exchange",
    "find_first_available",
]


class PipelineError(Exception):
    """Operator-visible error from the download pipeline (stops execution, exits non-zero)."""


def parse_pairs_file(path: Path) -> list[str]:
    if not path.exists():
        raise PipelineError(f"pairs file does not exist: {path}")
    raw = path.read_text(encoding="utf-8")
    pairs: list[str] = []
    seen: set[str] = set()
    for line in raw.splitlines():
        s = line.strip()
        if not s or s in seen:
            continue
        seen.add(s)
        pairs.append(s)
    if not pairs:
        raise PipelineError(f"pairs file has no symbols: {path}")
    return pairs


def validate_pairs_against_exchange(
    pairs: list[str], exchange_info: list[dict]
) -> dict[str, tuple[str, str]]:
    sym_map = {e["symbol"]: (e["baseAsset"], e["quoteAsset"]) for e in exchange_info}
    missing = [p for p in pairs if p not in sym_map]
    if missing:
        raise PipelineError(f"symbols not on Binance exchangeInfo: {missing}")
    return {p: sym_map[p] for p in pairs}


def find_first_available(
    source: Source, symbol: str, interval: str, lo: dt.date, hi: dt.date
) -> dt.date | None:
    """Smallest date in [lo, hi] where the kline exists, else None.

    Pre: availability is monotone after the listing date — `exists_kline(d)`
    implies `exists_kline(d')` for all `d ≤ d' ≤ hi`.
    """
    if hi < lo:
        return None
    if not source.exists_kline(symbol, interval, hi):
        return None
    if source.exists_kline(symbol, interval, lo):
        return lo
    # Invariant: lo missing, hi present. Bisect.
    while lo + dt.timedelta(days=1) < hi:
        mid = lo + dt.timedelta(days=(hi - lo).days // 2)
        if source.exists_kline(symbol, interval, mid):
            hi = mid
        else:
            lo = mid
    return hi
```

### Step 8.4: Run helper tests — expect pass

```bash
uv run pytest tests/test_data_pipeline.py -v
```

Expected: 8 passed.

### Step 8.5: Commit the helper slice

```bash
uv run ruff check cli/data/pipeline.py tests/test_data_pipeline.py
uv run ruff format cli/data/pipeline.py tests/test_data_pipeline.py
git add cli/data/pipeline.py tests/test_data_pipeline.py
git commit -m "feat(data): add pipeline helpers (pairs parser, exchange validator, listing bisect)

Co-Authored-By: Claude <ACTUAL_MODEL> <noreply@anthropic.com>"
```

### Step 8.6: Add failing tests for the orchestration

- [ ] Append to `tests/test_data_pipeline.py`:

```python
import datetime as dt

from cli.data.pipeline import PipelineError, download_pipeline
from cli.data.verify import verify_dataset


def _seed_source(start: dt.date, end: dt.date) -> FakeSource:
    src = FakeSource()
    src.add_pair("BTCUSDT", "BTC", "USDT")
    src.add_pair("ETHUSDT", "ETH", "USDT")
    cur = start
    while cur <= end:
        src.add_kline("BTCUSDT", "1d", cur, base_price=20000.0)
        if cur >= start + dt.timedelta(days=2):  # ragged left edge for ETH
            src.add_kline("ETHUSDT", "1d", cur, base_price=1500.0)
        cur += dt.timedelta(days=1)
    return src


def test_download_fresh_writes_valid_dataset(tmp_path):
    pairs = tmp_path / "pairs.txt"
    pairs.write_text("BTCUSDT\nETHUSDT\n")
    src = _seed_source(dt.date(2024, 1, 1), dt.date(2024, 1, 5))
    download_pipeline(
        out_dir=tmp_path / "ds",
        pairs_file=pairs,
        interval="1d",
        from_date=dt.date(2024, 1, 1),
        to_date=dt.date(2024, 1, 5),
        source=src,
    )
    report = verify_dataset(tmp_path / "ds")
    assert report.ok, report.problems
    # Ragged left edge: ETH from 2024-01-03 (start+2)
    instr = (tmp_path / "ds" / "instruments" / "all.txt").read_text(encoding="utf-8").splitlines()
    assert "BTCUSDT\t2024-01-01\t2024-01-05" in instr
    assert "ETHUSDT\t2024-01-03\t2024-01-05" in instr


def test_download_extend_appends_new_dates(tmp_path):
    pairs = tmp_path / "pairs.txt"
    pairs.write_text("BTCUSDT\nETHUSDT\n")
    out = tmp_path / "ds"
    src = _seed_source(dt.date(2024, 1, 1), dt.date(2024, 1, 5))
    download_pipeline(out, pairs, "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 5), src)

    # Add more days; re-run with the same --from (overlap → adjust)
    cur = dt.date(2024, 1, 6)
    while cur <= dt.date(2024, 1, 8):
        src.add_kline("BTCUSDT", "1d", cur)
        src.add_kline("ETHUSDT", "1d", cur)
        cur += dt.timedelta(days=1)
    download_pipeline(out, pairs, "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 8), src)
    assert verify_dataset(out).ok


def test_download_gap_error(tmp_path):
    pairs = tmp_path / "pairs.txt"
    pairs.write_text("BTCUSDT\n")
    out = tmp_path / "ds"
    src = _seed_source(dt.date(2024, 1, 1), dt.date(2024, 1, 5))
    download_pipeline(out, pairs, "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 5), src)
    # Now caller asks for a from-date 2+ days past index.to → gap error.
    with pytest.raises(PipelineError, match="gap"):
        download_pipeline(out, pairs, "1d", dt.date(2024, 1, 10), dt.date(2024, 1, 12), src)


def test_download_unsupported_interval_raises(tmp_path):
    pairs = tmp_path / "pairs.txt"
    pairs.write_text("BTCUSDT\n")
    with pytest.raises(PipelineError, match="not supported"):
        download_pipeline(tmp_path / "ds", pairs, "1h", dt.date(2024, 1, 1), dt.date(2024, 1, 2), FakeSource())


def test_download_indexed_pair_absent_from_file_errors(tmp_path):
    pairs = tmp_path / "pairs.txt"
    pairs.write_text("BTCUSDT\nETHUSDT\n")
    out = tmp_path / "ds"
    src = _seed_source(dt.date(2024, 1, 1), dt.date(2024, 1, 5))
    download_pipeline(out, pairs, "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 5), src)
    # Drop ETH from the file → second run should error.
    pairs.write_text("BTCUSDT\n")
    with pytest.raises(PipelineError, match="absent from pairs file"):
        download_pipeline(out, pairs, "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 8), src)


def test_download_checksum_mismatch_raises(tmp_path):
    pairs = tmp_path / "pairs.txt"
    pairs.write_text("BTCUSDT\n")
    src = _seed_source(dt.date(2024, 1, 1), dt.date(2024, 1, 3))
    src.tamper_kline_checksum("BTCUSDT", "1d", dt.date(2024, 1, 2))
    with pytest.raises(PipelineError, match="checksum"):
        download_pipeline(tmp_path / "ds", pairs, "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 3), src)


def test_download_leaves_live_dir_pristine_on_error(tmp_path):
    pairs = tmp_path / "pairs.txt"
    pairs.write_text("BTCUSDT\nETHUSDT\n")
    out = tmp_path / "ds"
    src = _seed_source(dt.date(2024, 1, 1), dt.date(2024, 1, 5))
    download_pipeline(out, pairs, "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 5), src)
    before = sorted((out / "features" / "btcusdt").glob("*.bin"))
    before_sizes = [p.stat().st_size for p in before]

    # Force a checksum failure on a subsequent extend → expect raise, live untouched.
    cur = dt.date(2024, 1, 6)
    while cur <= dt.date(2024, 1, 8):
        src.add_kline("BTCUSDT", "1d", cur)
        src.add_kline("ETHUSDT", "1d", cur)
        cur += dt.timedelta(days=1)
    src.tamper_kline_checksum("BTCUSDT", "1d", dt.date(2024, 1, 7))
    with pytest.raises(PipelineError):
        download_pipeline(out, pairs, "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 8), src)
    after_sizes = [p.stat().st_size for p in sorted((out / "features" / "btcusdt").glob("*.bin"))]
    assert before_sizes == after_sizes
    assert verify_dataset(out).ok
```

### Step 8.7: Run orchestration tests — expect failures

```bash
uv run pytest tests/test_data_pipeline.py -v
```

Expected: import errors for `download_pipeline`.

### Step 8.8: Implement orchestration (append to `cli/data/pipeline.py`)

- [ ] Extend `cli/data/pipeline.py`:

```python
import dataclasses as _dc
import hashlib as _hashlib
import shutil as _shutil

import pandas as _pd

from cli.data.config import FIELDS, SCHEMA_VERSION, SUPPORTED_INTERVALS
from cli.data.index import (
    CalendarEntry,
    FieldEntry,
    FileEntry,
    IndexData,
    PairEntry,
    PairIntervalEntry,
    compute_sha256,
    load_index,
    save_index,
    utc_now_iso,
)
from cli.data.klines import assert_no_internal_gaps, parse_kline_zip
from cli.data.qlib_writer import read_bin, write_bin, write_calendar, write_instruments
from cli.data.snapshots import create_snapshot, prune_snapshots
from cli.data.verify import verify_dataset
from cli.logging import get_logger

__all__ += ["download_pipeline"]

logger = get_logger("data.pipeline")


@_dc.dataclass
class _PerPair:
    symbol: str
    base: str
    quote: str
    effective_from: dt.date
    effective_to: dt.date
    is_new: bool
    existing_from: dt.date | None  # the pair's `from` already in the index


def _resolve_ranges(
    pair_to_assets: dict[str, tuple[str, str]],
    existing: IndexData | None,
    source: Source,
    interval: str,
    arg_from: dt.date,
    arg_to: dt.date,
) -> list[_PerPair]:
    plan: list[_PerPair] = []
    existing_to: dt.date | None = (
        dt.date.fromisoformat(existing.calendar.to_date) if existing else None
    )
    indexed_pairs = set(existing.pairs.keys()) if existing else set()

    # Guard against silent truncation: an explicit --to earlier than the existing
    # right edge would shrink the calendar and lose data on commit. Reject it.
    if existing_to is not None and arg_to < existing_to:
        raise PipelineError(
            f"--to {arg_to} is before existing calendar.to {existing_to}; cannot truncate"
        )

    # Pair-set reconciliation
    requested = set(pair_to_assets.keys())
    absent_from_file = sorted(indexed_pairs - requested)
    if absent_from_file:
        raise PipelineError(
            f"indexed pairs absent from pairs file (use delist/rename): {absent_from_file}"
        )

    for sym, (base, quote) in pair_to_assets.items():
        if sym in indexed_pairs:
            assert existing_to is not None
            if arg_from <= existing_to:
                logger.warning(
                    "adjusting --from for %s to %s (overlap with index.to=%s)",
                    sym, existing_to + dt.timedelta(days=1), existing_to,
                )
                effective_from = existing_to + dt.timedelta(days=1)
            elif arg_from == existing_to + dt.timedelta(days=1):
                effective_from = arg_from
            else:
                raise PipelineError(
                    f"gap for {sym}: --from {arg_from} is more than one day after index.to {existing_to}"
                )
            existing_from = dt.date.fromisoformat(
                existing.pairs[sym].intervals[interval].from_date
            )
            plan.append(_PerPair(sym, base, quote, effective_from, arg_to, False, existing_from))
        else:
            # New pair: binary-search listing date.
            first = find_first_available(source, sym, interval, arg_from, arg_to)
            if first is None:
                raise PipelineError(f"{sym}: no kline data available in [{arg_from}, {arg_to}]")
            if first > arg_from:
                logger.warning(
                    "%s data starts %s, later than --from %s", sym, first, arg_from
                )
            plan.append(_PerPair(sym, base, quote, max(arg_from, first), arg_to, True, None))
    return plan


def _verify_checksum(source: Source, sym: str, interval: str, date: dt.date, zip_bytes: bytes) -> None:
    expected = source.fetch_kline_checksum(sym, interval, date)
    actual = _hashlib.sha256(zip_bytes).hexdigest()
    if expected.lower() != actual.lower():
        raise PipelineError(f"{sym} {date}: checksum mismatch")


def _fetch_pair(source: Source, plan: _PerPair, interval: str) -> _pd.DataFrame:
    """Returns concatenated single-row DataFrames covering [effective_from, effective_to]."""
    dates: list[dt.date] = []
    cur = plan.effective_from
    while cur <= plan.effective_to:
        dates.append(cur)
        cur += dt.timedelta(days=1)
    rows: list[_pd.DataFrame] = []
    for d in dates:
        zip_bytes = source.fetch_kline_zip(plan.symbol, interval, d)
        _verify_checksum(source, plan.symbol, interval, d, zip_bytes)
        rows.append(parse_kline_zip(zip_bytes, plan.symbol, interval, d))
    df = _pd.concat(rows, ignore_index=True) if rows else _pd.DataFrame(columns=["date"] + list(FIELDS))
    assert_no_internal_gaps(df["date"].tolist(), dates)
    return df


def _read_existing_pair(out_dir: Path, sym: str, existing_from: dt.date, calendar: list[dt.date]) -> _pd.DataFrame:
    """Decode existing bins for one pair → DataFrame indexed by date over [existing_from, calendar[-1]]."""
    start_idx = calendar.index(existing_from)
    span = len(calendar) - start_idx
    rec: dict = {"date": calendar[start_idx:]}
    for f in FIELDS:
        bin_path = out_dir / "features" / sym.lower() / f"{f}.day.bin"
        header, values = read_bin(bin_path)
        if header != start_idx or len(values) != span:
            raise PipelineError(
                f"existing {sym} {f} bin inconsistent with index: header={header}, len={len(values)}"
            )
        rec[f] = list(values)
    return _pd.DataFrame(rec)


def _build_staging(
    out_dir: Path,
    staging: Path,
    plan: list[_PerPair],
    new_rows_per_sym: dict[str, _pd.DataFrame],
    existing: IndexData | None,
    arg_to: dt.date,
    interval: str,
) -> None:
    """Assemble the complete dataset in `staging/`. Old + new rows merged per pair."""
    if staging.exists():
        _shutil.rmtree(staging)
    staging.mkdir(parents=True)

    # Per-pair merged DataFrames: existing_calendar_rows + new_rows
    merged: dict[str, _pd.DataFrame] = {}
    existing_calendar: list[dt.date] = []
    if existing is not None:
        cal_from = dt.date.fromisoformat(existing.calendar.from_date)
        cal_to = dt.date.fromisoformat(existing.calendar.to_date)
        existing_calendar = [cal_from + dt.timedelta(days=i) for i in range((cal_to - cal_from).days + 1)]

    for p in plan:
        new_df = new_rows_per_sym.get(p.symbol, _pd.DataFrame(columns=["date"] + list(FIELDS)))
        if p.is_new:
            merged[p.symbol] = new_df
        else:
            old_df = _read_existing_pair(out_dir, p.symbol, p.existing_from, existing_calendar)
            merged[p.symbol] = _pd.concat([old_df, new_df], ignore_index=True)

    # Union calendar = global min from → arg_to
    pair_starts = [df["date"].min() for df in merged.values()]
    union_from = min(pair_starts)
    union_to = arg_to
    calendar = [union_from + dt.timedelta(days=i) for i in range((union_to - union_from).days + 1)]
    cal_index = {d: i for i, d in enumerate(calendar)}

    write_calendar(staging, calendar)
    pair_ranges: dict[str, tuple[dt.date, dt.date]] = {
        sym: (df["date"].min(), union_to) for sym, df in merged.items()
    }
    write_instruments(staging, pair_ranges)

    # Write bins per pair
    pairs_entries: dict[str, PairEntry] = {}
    for p in plan:
        df = merged[p.symbol].sort_values("date").reset_index(drop=True)
        start_idx = cal_index[df["date"].iloc[0]]
        fields_entries: dict[str, FieldEntry] = {}
        for f in FIELDS:
            rel = f"features/{p.symbol.lower()}/{f}.day.bin"
            write_bin(staging / rel, [float(v) for v in df[f].tolist()], start_index=start_idx)
            fields_entries[f] = FieldEntry(
                bin=rel, sha256=compute_sha256(staging / rel), updated_at=utc_now_iso()
            )
        pairs_entries[p.symbol] = PairEntry(
            base_asset=p.base,
            quote_asset=p.quote,
            intervals={
                interval: PairIntervalEntry(
                    from_date=df["date"].iloc[0].isoformat(),
                    rows=len(df),
                    fields=fields_entries,
                )
            },
        )

    index = IndexData(
        schema_version=SCHEMA_VERSION,
        updated_at=utc_now_iso(),
        calendar=CalendarEntry(
            freq="day", from_date=calendar[0].isoformat(), to_date=calendar[-1].isoformat(), days=len(calendar)
        ),
        pairs=pairs_entries,
        other_files={
            "calendars/day.txt": FileEntry(
                sha256=compute_sha256(staging / "calendars" / "day.txt"), updated_at=utc_now_iso()
            ),
            "instruments/all.txt": FileEntry(
                sha256=compute_sha256(staging / "instruments" / "all.txt"), updated_at=utc_now_iso()
            ),
        },
    )
    save_index(staging, index)


def _commit_staging(out_dir: Path, staging: Path) -> None:
    """Atomically replace live files from staging. `index.json` is written last."""
    create_snapshot(out_dir, "download")
    prune_snapshots(out_dir)
    # Move calendar / instruments / features
    for name in ("calendars", "instruments", "features"):
        target = out_dir / name
        if target.exists():
            _shutil.rmtree(target)
        _shutil.move(str(staging / name), str(target))
    # index.json last → the commit marker
    (out_dir / "index.json").write_text(
        (staging / "index.json").read_text(encoding="utf-8"), encoding="utf-8"
    )
    _shutil.rmtree(staging)


def download_pipeline(
    out_dir: Path,
    pairs_file: Path,
    interval: str,
    from_date: dt.date,
    to_date: dt.date,
    source: Source,
) -> None:
    """Orchestrate: parse → validate → resolve → fetch → stage → verify → commit."""
    out_dir.mkdir(parents=True, exist_ok=True)
    if interval not in SUPPORTED_INTERVALS:
        raise PipelineError(f"interval {interval!r} is not supported (only 1d)")
    if from_date > to_date:
        raise PipelineError(f"--from {from_date} must be ≤ --to {to_date}")

    pairs = parse_pairs_file(pairs_file)
    exchange_info = source.fetch_exchange_info()
    pair_to_assets = validate_pairs_against_exchange(pairs, exchange_info)

    existing = load_index(out_dir)
    plan = _resolve_ranges(pair_to_assets, existing, source, interval, from_date, to_date)

    new_rows_per_sym: dict[str, _pd.DataFrame] = {}
    for p in plan:
        if p.effective_from > p.effective_to:
            # Nothing to fetch — happens for existing pairs where overlap-adjust
            # gives an empty window because index already covered the range.
            new_rows_per_sym[p.symbol] = _pd.DataFrame(columns=["date"] + list(FIELDS))
        else:
            new_rows_per_sym[p.symbol] = _fetch_pair(source, p, interval)

    staging = out_dir / ".staging"
    _build_staging(out_dir, staging, plan, new_rows_per_sym, existing, to_date, interval)

    report = verify_dataset(staging)
    if not report.ok:
        raise PipelineError(f"staging verify failed: {report.problems[:3]}")

    _commit_staging(out_dir, staging)
```

> Note for the implementer: keep date columns as Python `datetime.date` end-to-end (not `pd.Timestamp`). `parse_kline_zip` already returns `dt.date` in the `date` column, `pd.concat` preserves object dtype, and the `cal_index[df["date"].iloc[0]]` lookup relies on `dt.date` keys.

### Step 8.9: Run orchestration tests — expect pass

```bash
uv run pytest tests/test_data_pipeline.py -v
```

Expected: all (helpers + orchestration) passed.

### Step 8.10: Commit the orchestration slice

```bash
uv run ruff check cli/data/pipeline.py tests/test_data_pipeline.py
uv run ruff format cli/data/pipeline.py tests/test_data_pipeline.py
git add cli/data/pipeline.py tests/test_data_pipeline.py
git commit -m "feat(data): add download_pipeline orchestration (stage + verify + atomic commit)

Co-Authored-By: Claude <ACTUAL_MODEL> <noreply@anthropic.com>"
```

### Step 8.11: Wire `data download` CLI command + date validators

- [ ] Edit `cli/data/command.py` — add at module top under `data_app`:

```python
import datetime as dt
import re
from pathlib import Path

from cli.data.binance import BinanceSource
from cli.data.pipeline import PipelineError, download_pipeline

_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _parse_date_arg(name: str, value: str) -> dt.date:
    if not _ISO_RE.match(value):
        raise typer.BadParameter(f"{name} must be YYYY-MM-DD, got {value!r}")
    try:
        return dt.date.fromisoformat(value)
    except ValueError as e:
        raise typer.BadParameter(f"{name} is not a real calendar date: {value!r}") from e


def _from_callback(value: str | None) -> str | None:
    if value is None:
        return None
    _parse_date_arg("--from", value)
    return value


def _to_callback(value: str | None) -> str | None:
    if value is None:
        return None
    _parse_date_arg("--to", value)
    return value


def _default_to() -> str:
    return (dt.date.today() - dt.timedelta(days=1)).isoformat()


@data_app.command("download")
def download_cmd(
    out_dir: Path = typer.Argument(..., help="Dataset directory (created if absent).", file_okay=False),
    pairs_file: Path = typer.Argument(..., help="Plain-text file: one Binance symbol per line.", exists=True, dir_okay=False),
    interval: str = typer.Option("1d", "--interval", help="Kline interval (only 1d supported)."),
    from_date: str = typer.Option("2020-01-01", "--from", callback=_from_callback, help="ISO date YYYY-MM-DD."),
    to_date: str = typer.Option(None, "--to", callback=_to_callback, help="ISO date YYYY-MM-DD (default: yesterday UTC)."),
) -> None:
    """Fetch Binance spot klines and write/append a Qlib-ready dataset."""
    fd = _parse_date_arg("--from", from_date)
    td = _parse_date_arg("--to", to_date or _default_to())
    try:
        download_pipeline(out_dir, pairs_file, interval, fd, td, source=BinanceSource())
    except PipelineError as e:
        typer.echo(f"ERROR: {e}", err=True)
        raise typer.Exit(code=1) from e
    typer.echo(f"OK — dataset at {out_dir} now reaches {td}.")
```

### Step 8.12: Add CLI integration tests for download

- [ ] Append to `tests/test_data_command.py`:

```python
import datetime as dt
import json
from pathlib import Path
from unittest.mock import patch

from tests.data_fixtures import FakeSource


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
            "data", "download", str(tmp_path / "ds"), str(pairs),
            "--interval", "1h",
            "--from", "2024-01-01", "--to", "2024-01-02",
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

    # Patch the concrete BinanceSource that download_cmd constructs.
    with patch("cli.data.command.BinanceSource", return_value=src):
        result = runner.invoke(
            app,
            [
                "data", "download", str(tmp_path / "ds"), str(pairs),
                "--from", "2024-01-01", "--to", "2024-01-03",
            ],
        )
    assert result.exit_code == 0, result.output
    assert (tmp_path / "ds" / "index.json").exists()
    idx = json.loads((tmp_path / "ds" / "index.json").read_text(encoding="utf-8"))
    assert idx["calendar"]["to"] == "2024-01-03"
```

### Step 8.13: Run all tests — expect pass

```bash
uv run pytest tests/test_data_pipeline.py tests/test_data_command.py -v
```

Expected: all passed.

### Step 8.14: Commit the CLI slice

```bash
uv run ruff check cli/data/command.py tests/test_data_command.py
uv run ruff format cli/data/command.py tests/test_data_command.py
git add cli/data/command.py tests/test_data_command.py
git commit -m "feat(data): add zcrypto data download command with parse-time date validation

Co-Authored-By: Claude <ACTUAL_MODEL> <noreply@anthropic.com>"
```

---

## Task 9: README `## Usage`, iterations-history, full verification

**Files:**

- Modify: `README.md` (the `## Usage` section)
- Modify: `docs/iterations-history.md` (append new section)
- No test changes; closeout-only.

### Step 9.1: Update README `## Usage`

- [ ] Read the current `## Usage` section (it documents `--version`, `--log`, `--log-level`, and `example`). Add entries for `data`, `data download`, `data verify` below `example`. Each subcommand gets a sub-heading with options table and a minimal invocation example. Match the existing wording / formatting style exactly. Then re-run `mdformat` via pre-commit so the TOC regenerates.

  Insert text outline (fill table contents accurately):

  ```markdown
  ### `zcrypto data`

  Prepare a Qlib-ready dataset from Binance spot klines. Bare `zcrypto data` prints this group's help.

  #### `zcrypto data download OUT_DIR PAIRS_FILE`

  Fetch Binance spot 1d klines, checksum-validate them, and write/append a Qlib-ready dataset to OUT_DIR.

  | Argument / option | Default | Effect |
  | --- | --- | --- |
  | `OUT_DIR` (positional, required) | — | Dataset directory; created if absent. |
  | `PAIRS_FILE` (positional, required) | — | Plain text — one Binance symbol per line (blank lines allowed; ≥1 symbol). |
  | `--interval` | `1d` | Kline interval. Only `1d` is supported in iter-4. |
  | `--from` | `2020-01-01` | Lower bound (ISO `YYYY-MM-DD`). |
  | `--to` | yesterday (UTC) | Upper bound (ISO `YYYY-MM-DD`). |

  Example:

  ```bash
  echo BTCUSDT > pairs.txt
  zcrypto data download ./ds pairs.txt --from 2024-01-01 --to 2024-01-31
  ```

  #### `zcrypto data verify OUT_DIR`

  Re-validate an existing dataset against `index.json` and all invariants. Read-only.

  | Option | Effect |
  | --- | --- |
  | `--silent` | Print nothing; convey result via exit code only (0 = valid, non-zero = problem). |

  Example:

  ```bash
  zcrypto data verify ./ds
  ```
  ```

### Step 9.2: Append iterations-history entry

- [ ] Append to the bottom of `docs/iterations-history.md` (under the existing iter-3 section):

```markdown
## 2026-06-09 — iter-4: `zcrypto data download` & `data verify`

- Added `cli/data/` subpackage (`config.py`, `klines.py`, `qlib_writer.py`, `index.py`, `snapshots.py`, `binance.py`, `verify.py`, `pipeline.py`, `command.py`) registered as a `data` sub-app on the root Typer app. Bare `zcrypto data` prints this group's help and exits (git-like one-level scoping); the full nested reference lives only in README `## Usage`.
- `zcrypto data download OUT_DIR PAIRS_FILE [--interval 1d] [--from 2020-01-01] [--to <yesterday UTC>]` fetches Binance spot 1d klines from `data.binance.vision`, validates each daily zip against its `.CHECKSUM` (sha256), and writes a Qlib-ready dataset directly into `OUT_DIR` (`calendars/day.txt`, `instruments/all.txt`, `features/<sym>/<field>.day.bin` for 11 fields incl. derived `vwap` and constant `factor=1.0`), plus `index.json`. Reconcile-to-file semantics: new pairs full-history fetched (binary-search the listing date), existing pairs time-extended; overlap → log warning and adjust; gap >1 day → error and exit; an indexed pair absent from the pairs file → error and exit (deferred to iter-5's `delist`/`rename`).
- `zcrypto data verify OUT_DIR [--silent]` re-validates an existing dataset against the index + all invariants and returns a structured `VerifyReport` from `verify_dataset()` — usable as a pure function from any Qlib pipeline. `--silent` conveys the result via exit code only.
- Date arguments (`--from`, `--to`) are validated at parse time (regex `^\d{4}-\d{2}-\d{2}$` + real calendar parse) so `20260609` or `2026-13-40` is rejected before any I/O.
- Every mutating subcommand (currently `download`) packs the whole relevant fileset (`calendars/`, `instruments/`, `features/`, `index.json`) into a single `OUT_DIR/.snapshots/<UTCstamp>-<cmd>.tar.gz`, retaining the newest 7. Staging happens in `OUT_DIR/.staging/`; `index.json` is written last as the commit marker so the live dir stays pristine on any error.
- `cli/data/binance.py` exposes a `Source` Protocol behind a stdlib `urllib.request` `BinanceSource` (HTTP paths `# pragma: no cover`); tests inject a `FakeSource` from `tests/data_fixtures.py` so the suite is fully offline.
- README `## Usage` documents the new commands; mdformat regenerates the TOC.
- Initial multi-year downloads are slow (one daily zip + checksum per pair-day); an open topic for concurrent / monthly-archive bulk fetch is to be filed under `docs/open-topics/`.
- Sneak-in: this iteration's first commit adds `docs/research/01.binance-eea-spot-quant.md` (the strategy/infra roadmap motivating the data work) and registers it in the mdformat pre-commit files: regex so its TOC stays auto-maintained.
```

### Step 9.3: Full verification

- [ ] Run the entire suite and pre-commit:

```bash
uv run pytest -q
uv run coverage run -m pytest && uv run coverage report -m
uv run pre-commit run --all-files
```

Expected:

- All tests pass.
- Coverage on `cli/data/*` is high; `cli/data/binance.py` HTTP methods are skipped via `# pragma: no cover`.
- pre-commit fully green (incl. mdformat regenerating README + research-doc TOCs if needed; ruff is clean).

### Step 9.4: Commit

```bash
git add README.md docs/iterations-history.md
git commit -m "docs(data): document data download/verify and append iter-4 history

Co-Authored-By: Claude <ACTUAL_MODEL> <noreply@anthropic.com>"
```

### Step 9.5: Open the iteration PR

After all task commits land, open the PR from `feat/data-download-verify` → `develop` with title `feat(data): iter-4 — data download & verify`, following the body template in `.claude/rules/pull-requests.md`. The PR body must include the aggregated `Co-Authored-By:` (and `Reviewed-by:` if reviewer subagents signed off) trailers per the rule.

---

## Open-topic to file post-execution (orchestrator)

Per `.claude/rules/open-topics.md` (mandatory approval gate), after the plan's tasks land, the orchestrator proposes to the user (via `AskUserQuestion`):

- Title: `binance-vision daily-only fetch is slow`
- Body summarizing: 5 years × 365 days × ~20 pairs = ~36,500 sequential HTTP GETs; investigate either a concurrency-bounded pool or a monthly-archive bulk-fetch fast path (the spec's "deferred" item).

On user approval, the file lands as `docs/open-topics/00001-binance-fetch-slow.md` (or next available serial) with a one-line index bump in `docs/open-topics/README.md`. This step does not happen inside a subagent task.
