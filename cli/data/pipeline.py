from __future__ import annotations

import dataclasses as _dc
import datetime as dt
import hashlib as _hashlib
import shutil as _shutil
from pathlib import Path

import pandas as _pd

from cli.data.binance import Source
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

__all__ = [
    "PipelineError",
    "parse_pairs_file",
    "validate_pairs_against_exchange",
    "find_first_available",
    "download_pipeline",
]

logger = get_logger("data.pipeline")


class PipelineError(Exception):
    """Operator-visible error from the download pipeline (stops execution, exits non-zero)."""


def parse_pairs_file(path: Path) -> list[str]:
    if not path.exists():
        raise PipelineError(f"pairs file does not exist: {path}")
    raw = path.read_text(encoding="utf-8")
    pairs: list[str] = []
    seen: set[str] = set()
    for line in raw.splitlines():
        s = line.strip().upper()  # Binance symbols are uppercase
        if not s or s in seen:
            continue
        seen.add(s)
        pairs.append(s)
    if not pairs:
        raise PipelineError(f"pairs file has no symbols: {path}")
    return pairs


def validate_pairs_against_exchange(pairs: list[str], exchange_info: list[dict]) -> dict[str, tuple[str, str]]:
    sym_map = {e["symbol"]: (e["baseAsset"], e["quoteAsset"]) for e in exchange_info}
    missing = [p for p in pairs if p not in sym_map]
    if missing:
        raise PipelineError(f"symbols not on Binance exchangeInfo: {missing}")
    return {p: sym_map[p] for p in pairs}


def find_first_available(source: Source, symbol: str, interval: str, lo: dt.date, hi: dt.date) -> dt.date | None:
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


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


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
    existing_to: dt.date | None = dt.date.fromisoformat(existing.calendar.to_date) if existing else None
    indexed_pairs = set(existing.pairs.keys()) if existing else set()

    # Guard against silent truncation
    if existing_to is not None and arg_to < existing_to:
        raise PipelineError(f"--to {arg_to} is before existing calendar.to {existing_to}; cannot truncate")

    requested = set(pair_to_assets.keys())
    absent_from_file = sorted(indexed_pairs - requested)
    if absent_from_file:
        raise PipelineError(f"indexed pairs absent from pairs file (use delist/rename): {absent_from_file}")

    for sym, (base, quote) in pair_to_assets.items():
        if sym in indexed_pairs:
            assert existing_to is not None
            if arg_from <= existing_to:
                logger.warning(
                    "adjusting --from for %s to %s (overlap with index.to=%s)",
                    sym,
                    existing_to + dt.timedelta(days=1),
                    existing_to,
                )
                effective_from = existing_to + dt.timedelta(days=1)
            elif arg_from == existing_to + dt.timedelta(days=1):
                effective_from = arg_from
            else:
                raise PipelineError(f"gap for {sym}: --from {arg_from} is more than one day after index.to {existing_to}")
            existing_from = dt.date.fromisoformat(existing.pairs[sym].intervals[interval].from_date)
            plan.append(_PerPair(sym, base, quote, effective_from, arg_to, False, existing_from))
        else:
            first = find_first_available(source, sym, interval, arg_from, arg_to)
            if first is None:
                raise PipelineError(f"{sym}: no kline data available in [{arg_from}, {arg_to}]")
            if first > arg_from:
                logger.warning("%s data starts %s, later than --from %s", sym, first, arg_from)
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
    assert_no_internal_gaps(df["date"].tolist(), dates, symbol=plan.symbol)
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
            raise PipelineError(f"existing {sym} {f} bin inconsistent with index: header={header}, len={len(values)}")
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

    pair_starts = [df["date"].min() for df in merged.values()]
    union_from = min(pair_starts)
    union_to = arg_to
    calendar = [union_from + dt.timedelta(days=i) for i in range((union_to - union_from).days + 1)]
    cal_index = {d: i for i, d in enumerate(calendar)}

    write_calendar(staging, calendar)
    pair_ranges: dict[str, tuple[dt.date, dt.date]] = {sym: (df["date"].min(), union_to) for sym, df in merged.items()}
    write_instruments(staging, pair_ranges)

    pairs_entries: dict[str, PairEntry] = {}
    for p in plan:
        df = merged[p.symbol].sort_values("date").reset_index(drop=True)
        start_idx = cal_index[df["date"].iloc[0]]
        fields_entries: dict[str, FieldEntry] = {}
        for f in FIELDS:
            rel = f"features/{p.symbol.lower()}/{f}.day.bin"
            write_bin(staging / rel, [float(v) for v in df[f].tolist()], start_index=start_idx)
            fields_entries[f] = FieldEntry(bin=rel, sha256=compute_sha256(staging / rel), updated_at=utc_now_iso())
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
            freq="day",
            from_date=calendar[0].isoformat(),
            to_date=calendar[-1].isoformat(),
            days=len(calendar),
        ),
        pairs=pairs_entries,
        other_files={
            "calendars/day.txt": FileEntry(sha256=compute_sha256(staging / "calendars" / "day.txt"), updated_at=utc_now_iso()),
            "instruments/all.txt": FileEntry(sha256=compute_sha256(staging / "instruments" / "all.txt"), updated_at=utc_now_iso()),
        },
    )
    save_index(staging, index)


def _commit_staging(out_dir: Path, staging: Path) -> None:
    """Atomically replace live files from staging. `index.json` is written last."""
    create_snapshot(out_dir, "download")
    prune_snapshots(out_dir)
    for name in ("calendars", "instruments", "features"):
        target = out_dir / name
        if target.exists():
            _shutil.rmtree(target)
        _shutil.move(str(staging / name), str(target))
    # Reuse the index module's atomic write (tmp + os.replace).
    staged_index = load_index(staging)
    assert staged_index is not None, "staging is supposed to contain a valid index.json"
    save_index(out_dir, staged_index)
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
            new_rows_per_sym[p.symbol] = _pd.DataFrame(columns=["date"] + list(FIELDS))
        else:
            new_rows_per_sym[p.symbol] = _fetch_pair(source, p, interval)

    staging = out_dir / ".staging"
    _build_staging(out_dir, staging, plan, new_rows_per_sym, existing, to_date, interval)

    report = verify_dataset(staging)
    if not report.ok:
        raise PipelineError(f"staging verify failed: {report.problems[:3]}")

    _commit_staging(out_dir, staging)
