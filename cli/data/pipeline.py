from __future__ import annotations

import dataclasses as _dc
import datetime as dt
import hashlib as _hashlib
import os
import shutil as _shutil
import tarfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Protocol

import pandas as _pd
import typer

from cli.constants import CliConstants
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
    "find_available_range",
    "download_pipeline",
    "DownloadPlan",
    "backfill_pipeline",
    "BackfillPlan",
    "delist_pipeline",
    "DelistPlan",
    "rename_pipeline",
    "RenamePlan",
]

_COMMIT_MARKER = ".commit-in-progress"

logger = get_logger("data.pipeline")


class PipelineError(Exception):
    """Operator-visible error from the download pipeline (stops execution, exits non-zero)."""


class Plan(Protocol):
    """Per-command plan dataclass shape. Each command defines its own
    concrete dataclass implementing this Protocol."""

    is_noop: bool

    def dry_run_summary(self) -> str: ...


def _execute_mutation(
    out_dir: Path,
    cmd_name: str,
    plan_fn: Callable[[Path], Plan],
    apply_fn: Callable[[Path, Path, Plan], None],
    *,
    dry_run: bool = False,
) -> None:
    """Shared mutation discipline: pre-flight (verify + recovery) → plan →
    no-op short-circuit → dry-run short-circuit → snapshot → marker → apply
    → post-verify → atomic commit → marker cleanup.
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    if not dry_run:
        _recover_from_interrupted_commit(out_dir)
    else:
        if (out_dir / _COMMIT_MARKER).exists():
            raise PipelineError(
                f"commit-in-progress marker present at {out_dir / _COMMIT_MARKER}; "
                "cannot dry-run until prior commit is recovered. "
                "Re-run without --dry-run to auto-recover."
            )

    pre = verify_dataset(out_dir)
    if not pre.ok:
        raise PipelineError(
            f"refusing to mutate {out_dir}: dataset is not in a verified state. "
            f"Problems: {pre.problems}. Resolve manually (restore from .snapshots/, "
            "or remove the orphan files) before re-running."
        )

    plan = plan_fn(out_dir)

    if plan.is_noop:
        msg = f"{cmd_name}: nothing to do"
        if dry_run:
            typer.echo(f"DRY-RUN: {msg}.")
        else:
            logger.info(msg)
        return

    if dry_run:
        typer.echo(plan.dry_run_summary())
        return

    staging = out_dir / ".staging"
    if staging.exists():
        _shutil.rmtree(staging)
    staging.mkdir()
    try:
        apply_fn(out_dir, staging, plan)
        post = verify_dataset(staging)
        if not post.ok:
            raise PipelineError(f"staging fails verify after apply: {post.problems}")
        _commit_staging(out_dir, staging, cmd_name=cmd_name)
    finally:
        if staging.exists():
            _shutil.rmtree(staging)


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


def validate_pairs_against_exchange(pairs: list[str], exchange_info: list[dict]) -> dict[str, tuple[str, str, str]]:
    sym_map = {e["symbol"]: (e["baseAsset"], e["quoteAsset"], e.get("status", "TRADING")) for e in exchange_info}
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


def _bisect_first_available(source: Source, symbol: str, interval: str, lo: dt.date, anchor: dt.date) -> dt.date:
    """Find the earliest date in [lo, anchor] with data. anchor is known good.

    Assumes data is **contiguous** within [lo, anchor]: a single uninterrupted
    block ending at-or-before anchor. For real Binance kline archives this
    holds (a pair trades continuously while listed; delisted pairs preserve
    a contiguous historical range). If data has internal gaps, the bisect
    may stop at a gap boundary and miss earlier data.
    """
    if source.exists_kline(symbol, interval, lo):
        return lo
    # Invariant: lo missing, anchor present.
    while lo + dt.timedelta(days=1) < anchor:
        mid = lo + dt.timedelta(days=(anchor - lo).days // 2)
        if source.exists_kline(symbol, interval, mid):
            anchor = mid
        else:
            lo = mid
    return anchor


def _bisect_last_available(source: Source, symbol: str, interval: str, anchor: dt.date, hi: dt.date) -> dt.date:
    """Find the latest date in [anchor, hi] with data. anchor is known good.

    Assumes data is **contiguous** within [anchor, hi]: a single uninterrupted
    block starting at-or-after anchor. Same caveat as `_bisect_first_available`
    — a real Binance kline archive satisfies this; a gappy synthetic source
    could trip the bisect into stopping at the gap.
    """
    if source.exists_kline(symbol, interval, hi):
        return hi
    # Invariant: anchor present, hi missing.
    while anchor + dt.timedelta(days=1) < hi:
        mid = anchor + dt.timedelta(days=(hi - anchor).days // 2)
        if source.exists_kline(symbol, interval, mid):
            anchor = mid
        else:
            hi = mid
    return anchor


def find_available_range(
    source: Source,
    symbol: str,
    interval: str,
    lo: dt.date,
    hi: dt.date,
) -> tuple[dt.date, dt.date] | None:
    """Return (first_available, last_available) within [lo, hi], or None
    if no kline zip exists in that range.

    Implementation: find an anchor (any date in [lo, hi] that has data),
    then bisect leftward for first_available and rightward for last_available.
    """
    if lo > hi:
        return None

    # Fast-path: try endpoints first.
    if source.exists_kline(symbol, interval, hi):
        anchor = hi
    elif source.exists_kline(symbol, interval, lo):
        anchor = lo
    else:
        # Probe scan: linear scan from lo+1 (lo and hi already checked above).
        anchor = None
        probe = lo + dt.timedelta(days=1)
        while probe < hi:
            if source.exists_kline(symbol, interval, probe):
                anchor = probe
                break
            probe += dt.timedelta(days=1)
        if anchor is None:
            return None

    first = _bisect_first_available(source, symbol, interval, lo, anchor)
    last = _bisect_last_available(source, symbol, interval, anchor, hi)
    return (first, last)


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
    pair_to_assets: dict[str, tuple[str, str, str]],
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

    for sym, (base, quote, status) in pair_to_assets.items():
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
            rng = find_available_range(source, sym, interval, effective_from, arg_to)
            if rng is None:
                days_since = (arg_to - existing_to).days
                if days_since > CliConstants.BACKFILL_RIGHT_EDGE_GRACE_DAYS:
                    raise PipelineError(
                        f"{sym}: no new archive data since {existing_to} ({days_since} days > "
                        f"{CliConstants.BACKFILL_RIGHT_EDGE_GRACE_DAYS}-day publishing-lag grace); "
                        "likely delisted or renamed. Reconcile with `zcrypto data delist` or "
                        "`zcrypto data rename`."
                    )
                logger.info(
                    "%s: no new archive data since %s (%d-day publishing-lag grace not yet exceeded); skipping.",
                    sym,
                    existing_to,
                    days_since,
                )
                continue
            # else rng = (first_new, last_new)
            if rng[0] > effective_from:
                raise PipelineError(
                    f"{sym}: gap detected — index.to={existing_to}, next archive day={rng[0]}; manual reconciliation required"
                )
            effective_from, effective_to_rng = rng
            if effective_to_rng < arg_to:
                logger.info(
                    "%s: archive last available %s (arg_to was %s); effective right edge clipped to %s (archive publishing lag).",
                    sym,
                    effective_to_rng,
                    arg_to,
                    effective_to_rng,
                )
            plan.append(_PerPair(sym, base, quote, effective_from, effective_to_rng, False, existing_from))
        else:
            # Unified discovery for both TRADING and non-TRADING new pairs.
            # find_available_range handles hi 404 (archive publishing lag) gracefully.
            rng = find_available_range(source, sym, interval, arg_from, arg_to)
            if rng is None:
                raise PipelineError(f"{sym}: no kline data available in [{arg_from}, {arg_to}]")
            eff_from, eff_to = rng
            if eff_from > arg_from:
                logger.warning("%s data starts %s, later than --from %s", sym, eff_from, arg_from)
            if status != "TRADING":
                logger.info(
                    "%s: status=%s on Binance; fetching only historical archive [%s..%s], no extension possible.",
                    sym,
                    status,
                    eff_from,
                    eff_to,
                )
            elif eff_to < arg_to:
                logger.info(
                    "%s: archive last available %s (arg_to was %s); effective right edge clipped to %s (archive publishing lag).",
                    sym,
                    eff_to,
                    arg_to,
                    eff_to,
                )
            plan.append(_PerPair(sym, base, quote, eff_from, eff_to, True, None))
    return plan


def _verify_checksum(source: Source, sym: str, interval: str, date: dt.date, zip_bytes: bytes) -> None:
    expected = source.fetch_kline_checksum(sym, interval, date)
    actual = _hashlib.sha256(zip_bytes).hexdigest()
    if expected.lower() != actual.lower():
        raise PipelineError(f"{sym} {date}: checksum mismatch")


def _fetch_one_date(source: Source, sym: str, interval: str, date: dt.date) -> tuple[str, dt.date, _pd.DataFrame]:
    """Fetch + checksum + parse one (sym, interval, date) tuple. Returns the parsed single-row DataFrame."""
    zip_bytes = source.fetch_kline_zip(sym, interval, date)
    _verify_checksum(source, sym, interval, date, zip_bytes)
    df = parse_kline_zip(zip_bytes, sym, interval, date)
    return sym, date, df


def _fetch_all_concurrent(source: Source, plan: list[_PerPair], interval: str, max_workers: int) -> dict[str, _pd.DataFrame]:
    """Fetch every (pair, date) tuple via a bounded thread pool. Per-pair gap-check runs after collection."""
    work: list[tuple[str, dt.date]] = []
    per_pair_expected: dict[str, list[dt.date]] = {}
    per_pair_rows: dict[str, list[_pd.DataFrame]] = {}
    for p in plan:
        dates: list[dt.date] = []
        cur = p.effective_from
        while cur <= p.effective_to:
            dates.append(cur)
            cur += dt.timedelta(days=1)
        per_pair_expected[p.symbol] = dates
        per_pair_rows[p.symbol] = []
        work.extend((p.symbol, d) for d in dates)

    if not work:
        return {sym: _pd.DataFrame(columns=["date"] + list(FIELDS)) for sym in per_pair_expected}

    logger.info(
        "fetching %d (pair, date) tuples concurrently (max_workers=%d)",
        len(work),
        max_workers,
    )

    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="zcrypto-fetch") as pool:
        futures = {pool.submit(_fetch_one_date, source, sym, interval, d): (sym, d) for sym, d in work}
        try:
            for fut in as_completed(futures):
                sym, d = futures[fut]
                try:
                    s, _, df = fut.result()
                except PipelineError:
                    raise
                except Exception as e:
                    raise PipelineError(f"{sym} {d}: fetch failed: {e}") from e
                per_pair_rows[s].append(df)
        except BaseException:
            # Cancel any future not yet started so in-flight workers drain quickly.
            for f in futures:
                f.cancel()
            raise

    result: dict[str, _pd.DataFrame] = {}
    for sym, expected in per_pair_expected.items():
        rows = per_pair_rows[sym]
        if not rows:
            result[sym] = _pd.DataFrame(columns=["date"] + list(FIELDS))
            continue
        df = _pd.concat(rows, ignore_index=True).sort_values("date").reset_index(drop=True)
        assert_no_internal_gaps(df["date"].tolist(), expected, symbol=sym)
        result[sym] = df
    return result


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

    # Per-pair effective_to: TRADING pairs go to arg_to; non-TRADING pairs stop at last_available.
    pair_effective_to: dict[str, dt.date] = {p.symbol: p.effective_to for p in plan}

    pair_starts = [df["date"].min() for df in merged.values()]
    union_from = min(pair_starts)
    union_to = max(pair_effective_to.values())
    calendar = [union_from + dt.timedelta(days=i) for i in range((union_to - union_from).days + 1)]
    cal_index = {d: i for i, d in enumerate(calendar)}

    write_calendar(staging, calendar)
    pair_ranges: dict[str, tuple[dt.date, dt.date]] = {
        sym: (df["date"].min(), pair_effective_to[sym]) for sym, df in merged.items()
    }
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


def _restore_from_snapshot(out_dir: Path, snapshot_path: Path) -> None:
    """Restore the dataset state captured in `snapshot_path` over `out_dir`.

    Removes any existing `calendars/`, `instruments/`, `features/`, and `index.json` first,
    then extracts the archive. Assumes the snapshot was taken from a verified state.
    """
    for name in ("calendars", "instruments", "features"):
        p = out_dir / name
        if p.exists():
            _shutil.rmtree(p)
    index_path = out_dir / "index.json"
    if index_path.exists():
        index_path.unlink()
    with tarfile.open(snapshot_path, "r:gz") as tar:
        tar.extractall(out_dir, filter="data")


def _write_commit_marker(out_dir: Path, snapshot_name: str) -> None:
    """Atomically write the commit-in-progress marker (tmp + os.replace), naming the snapshot to restore from."""
    marker = out_dir / _COMMIT_MARKER
    tmp = marker.with_suffix(marker.suffix + ".tmp")
    tmp.write_text(snapshot_name + "\n", encoding="utf-8")
    os.replace(tmp, marker)


def _recover_from_interrupted_commit(out_dir: Path) -> None:
    """If `.commit-in-progress` exists, restore from its referenced snapshot before any new work.

    Raises `PipelineError` if the marker points at a snapshot that does not exist (cannot auto-recover).
    """
    marker = out_dir / _COMMIT_MARKER
    if not marker.exists():
        return
    snap_name = marker.read_text(encoding="utf-8").strip()
    if not snap_name:
        raise PipelineError(
            f"commit-in-progress marker at {marker} is empty; cannot auto-recover. "
            "Manually restore from .snapshots/ or remove the marker after investigation."
        )
    snap = out_dir / ".snapshots" / snap_name
    if not snap.exists():
        raise PipelineError(
            f"commit-in-progress marker at {marker} points at {snap_name}, but that snapshot is "
            f"missing from {out_dir / '.snapshots'}; cannot auto-recover. "
            "Manually restore from .snapshots/ or remove the marker after investigation."
        )
    logger.warning("recovering from interrupted commit using snapshot %s", snap_name)
    _restore_from_snapshot(out_dir, snap)
    marker.unlink()


def _commit_staging(out_dir: Path, staging: Path, *, cmd_name: str = "download") -> None:
    """Atomically replace live files from staging, with snapshot-based crash recovery.

    The commit phase is bracketed by a snapshot + marker so that any failure (Python exception
    OR an OS-level crash that kills the process) is recoverable to the pre-commit state on the
    next invocation. The snapshot is the durability store; the marker names which snapshot to
    restore from.
    """
    snapshot = create_snapshot(out_dir, cmd_name)
    # Ordering: prune runs BEFORE the marker write because `snapshot` is the newest archive
    # (UTC stamp lexicographically sorts ascending) and `prune_snapshots` keeps the newest
    # `SNAPSHOT_KEEP`, so it can never remove what we just took. Re-check this invariant if
    # any code is ever inserted between these two lines that takes another snapshot.
    prune_snapshots(out_dir)
    _write_commit_marker(out_dir, snapshot.name)
    try:
        for name in ("calendars", "instruments", "features"):
            target = out_dir / name
            if target.exists():
                _shutil.rmtree(target)
            _shutil.move(str(staging / name), str(target))
        # Reuse the index module's atomic write (tmp + os.replace).
        staged_index = load_index(staging)
        assert staged_index is not None, "staging is supposed to contain a valid index.json"
        save_index(out_dir, staged_index)
    except BaseException:
        # Restore the pre-commit state from the snapshot we just took.
        try:
            _restore_from_snapshot(out_dir, snapshot)
        finally:
            (out_dir / _COMMIT_MARKER).unlink(missing_ok=True)
        raise
    else:
        (out_dir / _COMMIT_MARKER).unlink()
    finally:
        if staging.exists():
            _shutil.rmtree(staging)


@_dc.dataclass
class DownloadPlan:
    """Per-pair fetch plan for download (shared shape with backfill in later tasks)."""

    per_pair: list[_PerPair]
    existing: IndexData | None
    arg_to: dt.date
    interval: str
    is_noop: bool

    def dry_run_summary(self) -> str:
        if self.is_noop:
            return "DRY-RUN: download: nothing to do."
        lines = ["DRY-RUN: download plan:"]
        for p in self.per_pair:
            n_zips = max(0, (p.effective_to - p.effective_from).days + 1)
            if n_zips > 0:
                lines.append(f"  {p.symbol}: {p.effective_from} → {p.effective_to} ({n_zips} zips)")
        return "\n".join(lines)


def _download_plan(
    out_dir: Path,
    pairs_file: Path,
    interval: str,
    arg_from: dt.date,
    arg_to: dt.date,
    source: Source,
) -> DownloadPlan:
    """Read-only: parse + validate + resolve ranges. The harness has already run
    mkdir + recovery + pre-flight verify before calling this."""
    if interval not in SUPPORTED_INTERVALS:
        raise PipelineError(f"interval {interval!r} is not supported (only 1d)")
    if arg_from > arg_to:
        raise PipelineError(f"--from {arg_from} must be ≤ --to {arg_to}")

    requested = parse_pairs_file(pairs_file)
    exchange_info = source.fetch_exchange_info()
    pair_to_assets = validate_pairs_against_exchange(requested, exchange_info)

    existing = load_index(out_dir)
    per_pair = _resolve_ranges(pair_to_assets, existing, source, interval, arg_from, arg_to)

    is_noop = all(p.effective_from > p.effective_to for p in per_pair)
    return DownloadPlan(per_pair=per_pair, existing=existing, arg_to=arg_to, interval=interval, is_noop=is_noop)


def _download_apply(out_dir: Path, staging: Path, plan: DownloadPlan, source: Source) -> None:
    """Fetch + build staging. The harness handles snapshot, post-verify, commit."""
    non_empty = [p for p in plan.per_pair if p.effective_from <= p.effective_to]
    fetched = _fetch_all_concurrent(source, non_empty, plan.interval, CliConstants.FETCH_CONCURRENCY)
    new_rows_per_sym: dict[str, _pd.DataFrame] = {
        p.symbol: fetched.get(p.symbol, _pd.DataFrame(columns=["date"] + list(FIELDS))) for p in plan.per_pair
    }
    _build_staging(out_dir, staging, plan.per_pair, new_rows_per_sym, plan.existing, plan.interval)


def download_pipeline(
    out_dir: Path,
    pairs_file: Path,
    interval: str,
    from_date: dt.date,
    to_date: dt.date,
    source: Source,
    *,
    dry_run: bool = False,
) -> None:
    """Orchestrate: parse → validate → resolve → fetch → stage → verify → commit."""
    plan_fn = lambda d: _download_plan(d, pairs_file, interval, from_date, to_date, source)
    apply_fn = lambda d, s, p: _download_apply(d, s, p, source)
    _execute_mutation(out_dir, "download", plan_fn, apply_fn, dry_run=dry_run)


# ---------------------------------------------------------------------------
# Backfill pipeline
# ---------------------------------------------------------------------------


@_dc.dataclass
class BackfillPlan:
    """Per-pair extension plan for backfill."""

    per_pair: list[_PerPair]
    new_calendar: list[dt.date]
    skipped_pairs: list[tuple[str, str]]  # (symbol, status) for logged skips
    is_noop: bool

    def dry_run_summary(self) -> str:
        if self.is_noop:
            return "DRY-RUN: backfill: nothing to do."
        lines = ["DRY-RUN: backfill plan:"]
        for p in self.per_pair:
            cur = p.effective_from
            n_zips = 0
            while cur <= p.effective_to:
                n_zips += 1
                cur += dt.timedelta(days=1)
            lines.append(f"  {p.symbol}: {p.effective_from} → {p.effective_to} ({n_zips} zips)")
        for sym, status in self.skipped_pairs:
            lines.append(f"  {sym}: skipped (status={status})")
        return "\n".join(lines)


def _backfill_plan(out_dir: Path, interval: str, arg_to: dt.date, source: Source) -> BackfillPlan:
    """Read-only: load index, route each pair by status, build fetch plan."""
    existing = load_index(out_dir)
    if existing is None or not existing.pairs:
        raise PipelineError("no pairs in index; use 'data download' first to seed the dataset")

    exchange_info = source.fetch_exchange_info()
    per_pair: list[_PerPair] = []
    skipped: list[tuple[str, str]] = []

    for sym, pair_entry in existing.pairs.items():
        validated = validate_pairs_against_exchange([sym], exchange_info)
        base, quote, status = validated[sym]

        if status != "TRADING":
            logger.info("%s: status=%s on Binance; nothing to extend.", sym, status)
            skipped.append((sym, status))
            continue

        interval_entry = pair_entry.intervals[interval]
        current_to = dt.date.fromisoformat(interval_entry.dates_to)

        if current_to >= arg_to:
            # Already caught up — skip silently (not in plan)
            continue

        effective_from = current_to + dt.timedelta(days=1)

        rng = find_available_range(source, sym, interval, effective_from, arg_to)
        if rng is None:
            days_since = (arg_to - current_to).days
            if days_since > CliConstants.BACKFILL_RIGHT_EDGE_GRACE_DAYS:
                raise PipelineError(
                    f"{sym}: no new archive data since {current_to} ({days_since} days > "
                    f"{CliConstants.BACKFILL_RIGHT_EDGE_GRACE_DAYS}-day publishing-lag grace); "
                    "likely delisted or renamed. Reconcile with "
                    "'zcrypto data delist' or 'zcrypto data rename'."
                )
            logger.info(
                "%s: no new archive data since %s (%d-day publishing-lag grace not yet exceeded); skipping.",
                sym,
                current_to,
                days_since,
            )
            continue

        if rng[0] > effective_from:
            raise PipelineError(
                f"{sym}: gap detected — index.to={current_to}, next archive day={rng[0]}; manual reconciliation required"
            )
        effective_from, effective_to = rng
        if effective_to < arg_to:
            logger.info(
                "%s: archive last available %s (arg_to was %s); effective right edge clipped to %s (archive publishing lag).",
                sym,
                effective_to,
                arg_to,
                effective_to,
            )

        existing_from = dt.date.fromisoformat(interval_entry.from_date)
        per_pair.append(_PerPair(sym, base, quote, effective_from, effective_to, False, existing_from))

    # Build new calendar: union of [existing.calendar.from_date .. arg_to]
    cal_from = dt.date.fromisoformat(existing.calendar.from_date)
    cal_to = max(arg_to, dt.date.fromisoformat(existing.calendar.to_date))
    new_calendar = [cal_from + dt.timedelta(days=i) for i in range((cal_to - cal_from).days + 1)]

    is_noop = len(per_pair) == 0
    return BackfillPlan(per_pair=per_pair, new_calendar=new_calendar, skipped_pairs=skipped, is_noop=is_noop)


def _backfill_apply(out_dir: Path, staging: Path, plan: BackfillPlan, source: Source, interval: str) -> None:
    """Fetch new rows and rebuild staging with old + new data merged per pair."""
    existing = load_index(out_dir)
    assert existing is not None, "_backfill_apply called without an existing index"

    fetched = _fetch_all_concurrent(source, plan.per_pair, interval, CliConstants.FETCH_CONCURRENCY)

    # Collect all pairs: those being extended + those carried over unchanged.
    extended_syms = {p.symbol for p in plan.per_pair}
    carry_over: list[_PerPair] = []
    exchange_info = source.fetch_exchange_info()
    for sym, pair_entry in existing.pairs.items():
        if sym in extended_syms:
            continue
        validated = validate_pairs_against_exchange([sym], exchange_info)
        base, quote, _status = validated[sym]
        interval_entry = pair_entry.intervals[interval]
        existing_from = dt.date.fromisoformat(interval_entry.from_date)
        existing_to = dt.date.fromisoformat(interval_entry.dates_to)
        carry_over.append(_PerPair(sym, base, quote, existing_from, existing_to, False, existing_from))

    all_pairs = plan.per_pair + carry_over
    new_rows_per_sym: dict[str, _pd.DataFrame] = {}
    for p in plan.per_pair:
        new_rows_per_sym[p.symbol] = fetched.get(p.symbol, _pd.DataFrame(columns=["date"] + list(FIELDS)))
    # Carry-over pairs contribute no new rows (empty df); _build_staging will read existing bins.
    for p in carry_over:
        new_rows_per_sym[p.symbol] = _pd.DataFrame(columns=["date"] + list(FIELDS))

    _build_staging(out_dir, staging, all_pairs, new_rows_per_sym, existing, interval)


def backfill_pipeline(
    out_dir: Path,
    interval: str,
    arg_to: dt.date,
    source: Source,
    *,
    dry_run: bool = False,
) -> None:
    """Extend every TRADING pair in the index to arg_to. Non-TRADING pairs are silently skipped."""
    plan_fn = lambda d: _backfill_plan(d, interval, arg_to, source)
    apply_fn = lambda d, s, p: _backfill_apply(d, s, p, source, interval)
    _execute_mutation(out_dir, "backfill", plan_fn, apply_fn, dry_run=dry_run)


# ---------------------------------------------------------------------------
# Delist pipeline
# ---------------------------------------------------------------------------


@_dc.dataclass
class DelistPlan:
    symbol: str
    new_calendar: list[dt.date]
    front_trim: int
    back_trim: int
    rewrite_headers: bool
    remaining_symbols: list[str]
    is_noop: bool

    def dry_run_summary(self) -> str:
        lines = [f"DRY-RUN: delist plan: {self.symbol}"]
        lines.append(f"  features/{self.symbol.lower()}/ → deleted")
        lines.append(f"  instruments/all.txt → 1 line removed")
        lines.append(f"  index.json → 1 pair entry removed")
        lines.append(f"  calendar: front_trim={self.front_trim}, back_trim={self.back_trim}")
        if self.rewrite_headers:
            lines.append(f"  Remaining bins: headers rewritten (subtract {self.front_trim} from each start_index)")
        else:
            lines.append(f"  Remaining bins: headers unchanged")
        lines.append(f"  Remaining pairs: {len(self.remaining_symbols)} ({', '.join(self.remaining_symbols)})")
        return "\n".join(lines)


def _delist_plan(out_dir: Path, symbol: str) -> DelistPlan:
    """Read-only: validate symbol is in the index, compute calendar shrink plan."""
    idx = load_index(out_dir)
    assert idx is not None, "_delist_plan called on empty/missing index"
    sym = symbol.upper()

    if sym not in idx.pairs:
        raise PipelineError(f"{sym} not in index; nothing to remove")

    remaining = {s: p for s, p in idx.pairs.items() if s != sym}
    if not remaining:
        raise PipelineError(f"delisting {sym} would leave the dataset empty; remove {out_dir} manually if that's intended")

    interval = "1d"
    new_from = min(dt.date.fromisoformat(p.intervals[interval].from_date) for p in remaining.values())
    new_to = max(dt.date.fromisoformat(p.intervals[interval].dates_to) for p in remaining.values())

    # Gap check: every date in [new_from, new_to] must be covered by at least one remaining pair.
    cur = new_from
    while cur <= new_to:
        covers = any(
            dt.date.fromisoformat(p.intervals[interval].from_date) <= cur <= dt.date.fromisoformat(p.intervals[interval].dates_to)
            for p in remaining.values()
        )
        if not covers:
            raise PipelineError(
                f"delisting {sym} would create a non-contiguous calendar "
                f"(no remaining pair covers {cur}); reconcile manually before delisting"
            )
        cur += dt.timedelta(days=1)

    old_from = dt.date.fromisoformat(idx.calendar.from_date)
    old_to = dt.date.fromisoformat(idx.calendar.to_date)
    front_trim = (new_from - old_from).days
    back_trim = (old_to - new_to).days
    new_cal = [new_from + dt.timedelta(days=i) for i in range((new_to - new_from).days + 1)]

    return DelistPlan(
        symbol=sym,
        new_calendar=new_cal,
        front_trim=front_trim,
        back_trim=back_trim,
        rewrite_headers=(front_trim > 0),
        remaining_symbols=list(remaining.keys()),
        is_noop=False,
    )


def _rewrite_bin_start_index(bin_path: Path, delta: int) -> None:
    """Read first 4 bytes (float32 header), adjust by delta, write back."""
    import struct

    data = bytearray(bin_path.read_bytes())
    current = struct.unpack_from("<f", data, 0)[0]
    new_val = current + delta
    struct.pack_into("<f", data, 0, float(new_val))
    bin_path.write_bytes(bytes(data))


def _delist_apply(out_dir: Path, staging: Path, plan: DelistPlan) -> None:
    """Copy remaining pairs' bins, conditionally rewrite headers, write calendar/instruments/index."""
    interval = "1d"
    idx = load_index(out_dir)
    assert idx is not None

    # Copy remaining pairs' feature dirs into staging.
    (staging / "features").mkdir(parents=True, exist_ok=True)
    for sym in plan.remaining_symbols:
        src_dir = out_dir / "features" / sym.lower()
        dst_dir = staging / "features" / sym.lower()
        _shutil.copytree(src_dir, dst_dir)
        if plan.rewrite_headers:
            for field_path in dst_dir.iterdir():
                if field_path.suffix == ".bin":
                    _rewrite_bin_start_index(field_path, -plan.front_trim)

    # Write new calendar.
    write_calendar(staging, plan.new_calendar)

    # Write new instruments: remaining pairs use their existing from_date but same to_date.
    remaining_ranges: dict[str, tuple[dt.date, dt.date]] = {}
    for sym in plan.remaining_symbols:
        pair_entry = idx.pairs[sym]
        interval_entry = pair_entry.intervals[interval]
        from_d = dt.date.fromisoformat(interval_entry.from_date)
        to_d = dt.date.fromisoformat(interval_entry.dates_to)
        remaining_ranges[sym] = (from_d, to_d)
    write_instruments(staging, remaining_ranges)

    # Build new index.
    new_calendar = plan.new_calendar
    cal_index = {d: i for i, d in enumerate(new_calendar)}

    pairs_entries: dict[str, PairEntry] = {}
    for sym in plan.remaining_symbols:
        pair_entry = idx.pairs[sym]
        interval_entry = pair_entry.intervals[interval]
        from_d = dt.date.fromisoformat(interval_entry.from_date)
        fields: dict[str, FieldEntry] = {}
        for fname, fentry in interval_entry.fields.items():
            bin_path = staging / fentry.bin
            fields[fname] = FieldEntry(
                bin=fentry.bin,
                sha256=compute_sha256(bin_path),
                updated_at=utc_now_iso(),
            )
        pairs_entries[sym] = PairEntry(
            base_asset=pair_entry.base_asset,
            quote_asset=pair_entry.quote_asset,
            intervals={
                interval: PairIntervalEntry(
                    from_date=from_d.isoformat(),
                    rows=interval_entry.rows,
                    fields=fields,
                )
            },
        )

    from cli.data.config import SCHEMA_VERSION

    new_index = IndexData(
        schema_version=SCHEMA_VERSION,
        updated_at=utc_now_iso(),
        calendar=CalendarEntry(
            freq="day",
            from_date=new_calendar[0].isoformat(),
            to_date=new_calendar[-1].isoformat(),
            days=len(new_calendar),
        ),
        pairs=pairs_entries,
        other_files={
            "calendars/day.txt": FileEntry(
                sha256=compute_sha256(staging / "calendars" / "day.txt"),
                updated_at=utc_now_iso(),
            ),
            "instruments/all.txt": FileEntry(
                sha256=compute_sha256(staging / "instruments" / "all.txt"),
                updated_at=utc_now_iso(),
            ),
        },
    )
    save_index(staging, new_index)


def delist_pipeline(
    out_dir: Path,
    symbol: str,
    *,
    dry_run: bool = False,
) -> None:
    """Remove SYMBOL from the dataset under the snapshot+commit discipline."""
    plan_fn = lambda d: _delist_plan(d, symbol)
    apply_fn = lambda d, s, p: _delist_apply(d, s, p)
    _execute_mutation(out_dir, "delist", plan_fn, apply_fn, dry_run=dry_run)


# ---------------------------------------------------------------------------
# Rename pipeline
# ---------------------------------------------------------------------------

_FIELD_SYNTH: dict[str, object] = {
    "open": lambda c: c,
    "high": lambda c: c,
    "low": lambda c: c,
    "close": lambda c: c,
    "vwap": lambda c: c,
    "volume": lambda c: 0.0,
    "amount": lambda c: 0.0,
    "trades": lambda c: 0.0,
    "taker_buy_base": lambda c: 0.0,
    "taker_buy_amount": lambda c: 0.0,
    "factor": lambda c: 1.0,
}


def _synthetic_value(field: str, locked: float) -> float:
    return _FIELD_SYNTH[field](locked)  # type: ignore[operator]


@_dc.dataclass
class RenamePlan:
    variant: int
    old_symbol: str
    new_symbol: str
    new_base_asset: str
    new_quote_asset: str
    new_first: dt.date
    new_to: dt.date  # renamed pair's index.to after fill = new_first - 1 day
    gap_dates: list[dt.date]
    synthetic_locked_ohlc: float
    is_noop: bool

    def dry_run_summary(self) -> str:
        lines = [f"DRY-RUN: rename plan (Variant {self.variant}): {self.old_symbol} → {self.new_symbol}"]
        if self.gap_dates:
            lines.append(f"  synthetic gap fill: {len(self.gap_dates)} day(s) ({self.gap_dates[0]} .. {self.gap_dates[-1]})")
            lines.append(f"  locked OHLC/VWAP = {self.synthetic_locked_ohlc}, volume/amount/trades = 0.0, factor = 1.0")
        else:
            lines.append("  no synthetic gap fill needed")
        lines.append(f"  renamed pair index.to will be: {self.new_to}")
        lines.append(f"  NEW first archive day: {self.new_first}")
        return "\n".join(lines)


def _rename_plan(out_dir: Path, old_symbol: str, new_symbol: str, source: Source) -> RenamePlan:
    """Read-only pre-flight: validate, detect variant, probe NEW archive availability."""
    import struct

    idx = load_index(out_dir)
    assert idx is not None, "_rename_plan called on empty/missing index"

    old = old_symbol.upper()
    new = new_symbol.upper()

    if old not in idx.pairs:
        raise PipelineError(f"{old} not in index; nothing to rename")

    if old == new:
        raise PipelineError("old_symbol equals new_symbol; no change requested")

    variant = 2 if new in idx.pairs else 1

    exchange_info = source.fetch_exchange_info()
    sym_map = {e["symbol"]: (e["baseAsset"], e["quoteAsset"]) for e in exchange_info}
    if new not in sym_map:
        raise PipelineError(f"{new} not found on Binance (exchangeInfo); not a valid symbol")
    new_base_asset, new_quote_asset = sym_map[new]

    if variant == 2:
        old_pair = idx.pairs[old]
        new_pair = idx.pairs[new]
        old_interval_entry = old_pair.intervals["1d"]
        new_interval_entry = new_pair.intervals["1d"]
        old_to = dt.date.fromisoformat(old_interval_entry.dates_to)
        new_from = dt.date.fromisoformat(new_interval_entry.from_date)
        new_to_v2 = dt.date.fromisoformat(new_interval_entry.dates_to)

        # Overlap check: if NEW's downloaded range starts at-or-before OLD's last day → error.
        if new_from <= old_to:
            raise PipelineError(
                f"rename Variant 2 overlap: {old} ends {old_to} but {new} starts {new_from}; "
                "operator must reconcile manually before merging"
            )

        # Read OLD's last close for gap-fill synthetic value.
        old_close_bin = out_dir / "features" / old.lower() / "close.day.bin"
        _header, old_closes = read_bin(old_close_bin)
        synthetic_locked_ohlc = float(old_closes[-1])

        # Gap dates: days between old_to+1 and new_from-1 (may be empty).
        gap_dates_v2: list[dt.date] = []
        cur = old_to + dt.timedelta(days=1)
        while cur < new_from:
            gap_dates_v2.append(cur)
            cur += dt.timedelta(days=1)

        if len(gap_dates_v2) > CliConstants.RENAME_SYNTH_WARN_DAYS:
            logger.warning(
                "rename %s → %s (Variant 2): large synthetic gap fill: %d days (%s .. %s), locked OHLC = %s. Verify data integrity after rename.",
                old,
                new,
                len(gap_dates_v2),
                gap_dates_v2[0],
                gap_dates_v2[-1],
                synthetic_locked_ohlc,
            )
        elif gap_dates_v2:
            logger.warning(
                "rename %s → %s (Variant 2): synthetic gap fill: %d day(s) (%s .. %s), locked OHLC = %s",
                old,
                new,
                len(gap_dates_v2),
                gap_dates_v2[0],
                gap_dates_v2[-1],
                synthetic_locked_ohlc,
            )

        return RenamePlan(
            variant=2,
            old_symbol=old,
            new_symbol=new,
            new_base_asset=new_base_asset,
            new_quote_asset=new_quote_asset,
            new_first=new_from,
            new_to=new_to_v2,
            gap_dates=gap_dates_v2,
            synthetic_locked_ohlc=synthetic_locked_ohlc,
            is_noop=False,
        )

    # Variant 1 only below.
    old_pair = idx.pairs[old]
    old_interval_entry = old_pair.intervals["1d"]
    old_to = dt.date.fromisoformat(old_interval_entry.dates_to)

    # Read OLD's last close from the bin.
    old_close_bin = out_dir / "features" / old.lower() / "close.day.bin"
    _header, old_closes = read_bin(old_close_bin)
    synthetic_locked_ohlc = float(old_closes[-1])

    # Probe NEW's first archive day starting from old_to + 1.
    yesterday_utc = dt.date.today() - dt.timedelta(days=1)
    probe_lo = old_to + dt.timedelta(days=1)
    rng = find_available_range(source, new, "1d", probe_lo, yesterday_utc)
    if rng is None:
        raise PipelineError(
            f"{new} has no daily archive available on data.binance.vision yet (likely too early after listing). Try again tomorrow."
        )
    new_first = rng[0]

    if new_first <= old_to:
        raise PipelineError(
            f"rename has overlapping data: {old} ends {old_to} but {new} starts {new_first}; manual resolution required"
        )

    # Gap dates: days between old_to+1 and new_first-1 (may be empty).
    gap_dates: list[dt.date] = []
    cur = old_to + dt.timedelta(days=1)
    while cur < new_first:
        gap_dates.append(cur)
        cur += dt.timedelta(days=1)

    new_to = new_first - dt.timedelta(days=1)

    if len(gap_dates) > CliConstants.RENAME_SYNTH_WARN_DAYS:
        logger.warning(
            "rename %s → %s: large synthetic gap fill: %d days (%s .. %s), locked OHLC = %s. Verify data integrity after rename.",
            old,
            new,
            len(gap_dates),
            gap_dates[0],
            gap_dates[-1],
            synthetic_locked_ohlc,
        )
    elif gap_dates:
        logger.warning(
            "rename %s → %s: synthetic gap fill: %d day(s) (%s .. %s), locked OHLC = %s",
            old,
            new,
            len(gap_dates),
            gap_dates[0],
            gap_dates[-1],
            synthetic_locked_ohlc,
        )

    return RenamePlan(
        variant=1,
        old_symbol=old,
        new_symbol=new,
        new_base_asset=new_base_asset,
        new_quote_asset=new_quote_asset,
        new_first=new_first,
        new_to=new_to,
        gap_dates=gap_dates,
        synthetic_locked_ohlc=synthetic_locked_ohlc,
        is_noop=False,
    )


def _load_calendar_dates(cal_path: Path) -> list[dt.date]:
    """Parse calendars/day.txt → sorted list of dt.date."""
    dates: list[dt.date] = []
    for line in cal_path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s:
            dates.append(dt.date.fromisoformat(s))
    return dates


def _build_pair_entry_from_staging(
    staging: Path,
    sym: str,
    base: str,
    quote: str,
    from_date: dt.date,
    rows: int,
    interval: str = "1d",
) -> PairEntry:
    """Build a PairEntry by computing sha256 of each field bin in staging."""
    fields_entries: dict[str, FieldEntry] = {}
    feat_lower = sym.lower()
    for fname in FIELDS:
        rel = f"features/{feat_lower}/{fname}.day.bin"
        bin_path = staging / rel
        fields_entries[fname] = FieldEntry(
            bin=rel,
            sha256=compute_sha256(bin_path),
            updated_at=utc_now_iso(),
        )
    return PairEntry(
        base_asset=base,
        quote_asset=quote,
        intervals={
            interval: PairIntervalEntry(
                from_date=from_date.isoformat(),
                rows=rows,
                fields=fields_entries,
            )
        },
    )


def _rename_apply(out_dir: Path, staging: Path, plan: RenamePlan) -> None:
    """Dispatch to variant-specific apply."""
    if plan.variant == 1:
        _rename_apply_variant1(out_dir, staging, plan)
    else:
        _rename_apply_variant2(out_dir, staging, plan)


def _rename_apply_variant1(out_dir: Path, staging: Path, plan: RenamePlan) -> None:
    """Copy and optionally extend bins; rewrite calendar, instruments, and index."""
    import struct

    interval = "1d"
    idx = load_index(out_dir)
    assert idx is not None

    (staging / "features").mkdir(parents=True, exist_ok=True)

    # Copy each pair's feature dir; rename OLD → NEW with optional gap fill.
    for sym, pair_entry in idx.pairs.items():
        src_dir = out_dir / "features" / sym.lower()
        if sym == plan.old_symbol:
            dst_dir = staging / "features" / plan.new_symbol.lower()
        else:
            dst_dir = staging / "features" / sym.lower()
        _shutil.copytree(src_dir, dst_dir)

        if sym == plan.old_symbol and plan.gap_dates:
            # Append synthetic float32 values for each gap day to each field bin.
            for field in FIELDS:
                bin_path = dst_dir / f"{field}.day.bin"
                gap_bytes = b""
                for _d in plan.gap_dates:
                    val = _synthetic_value(field, plan.synthetic_locked_ohlc)
                    gap_bytes += struct.pack("<f", val)
                with bin_path.open("ab") as fh:
                    fh.write(gap_bytes)

    # Calendar: union of old calendar dates and gap_dates (dedup + sort).
    old_cal_dates = _load_calendar_dates(out_dir / "calendars" / "day.txt")
    new_calendar = sorted(set(old_cal_dates) | set(plan.gap_dates))
    write_calendar(staging, new_calendar)

    # Instruments: for OLD→NEW line, use new symbol + old from + new_to.
    # For others, keep as-is.
    instruments_ranges: dict[str, tuple[dt.date, dt.date]] = {}
    for sym, pair_entry in idx.pairs.items():
        iv = pair_entry.intervals[interval]
        from_d = dt.date.fromisoformat(iv.from_date)
        if sym == plan.old_symbol:
            instruments_ranges[plan.new_symbol] = (from_d, plan.new_to)
        else:
            to_d = dt.date.fromisoformat(iv.dates_to)
            instruments_ranges[sym] = (from_d, to_d)
    write_instruments(staging, instruments_ranges)

    # Build fresh index.
    pairs_entries: dict[str, PairEntry] = {}
    for sym, pair_entry in idx.pairs.items():
        iv = pair_entry.intervals[interval]
        from_d = dt.date.fromisoformat(iv.from_date)
        old_rows = iv.rows

        if sym == plan.old_symbol:
            new_sym = plan.new_symbol
            new_rows = old_rows + len(plan.gap_dates)
            base = plan.new_base_asset
            quote = plan.new_quote_asset
            feat_lower = plan.new_symbol.lower()
        else:
            new_sym = sym
            new_rows = old_rows
            base = pair_entry.base_asset
            quote = pair_entry.quote_asset
            feat_lower = sym.lower()

        fields_entries: dict[str, FieldEntry] = {}
        for fname in FIELDS:
            rel = f"features/{feat_lower}/{fname}.day.bin"
            bin_path = staging / rel
            fields_entries[fname] = FieldEntry(
                bin=rel,
                sha256=compute_sha256(bin_path),
                updated_at=utc_now_iso(),
            )

        pairs_entries[new_sym] = PairEntry(
            base_asset=base,
            quote_asset=quote,
            intervals={
                interval: PairIntervalEntry(
                    from_date=from_d.isoformat(),
                    rows=new_rows,
                    fields=fields_entries,
                )
            },
        )

    from cli.data.config import SCHEMA_VERSION

    new_index = IndexData(
        schema_version=SCHEMA_VERSION,
        updated_at=utc_now_iso(),
        calendar=CalendarEntry(
            freq="day",
            from_date=new_calendar[0].isoformat(),
            to_date=new_calendar[-1].isoformat(),
            days=len(new_calendar),
        ),
        pairs=pairs_entries,
        other_files={
            "calendars/day.txt": FileEntry(
                sha256=compute_sha256(staging / "calendars" / "day.txt"),
                updated_at=utc_now_iso(),
            ),
            "instruments/all.txt": FileEntry(
                sha256=compute_sha256(staging / "instruments" / "all.txt"),
                updated_at=utc_now_iso(),
            ),
        },
    )
    save_index(staging, new_index)


def _rename_apply_variant2(out_dir: Path, staging: Path, plan: RenamePlan) -> None:
    """Merge OLD's bin into NEW's slot: OLD.bin + synthetic gap + NEW.bin per field.
    Drop OLD's index entry. Update NEW's range to span both."""
    import struct

    interval = "1d"
    idx = load_index(out_dir)
    assert idx is not None

    old_entry = idx.pairs[plan.old_symbol]
    new_entry = idx.pairs[plan.new_symbol]
    old_interval = old_entry.intervals[interval]
    new_interval = new_entry.intervals[interval]
    old_from = dt.date.fromisoformat(old_interval.from_date)
    new_from = dt.date.fromisoformat(new_interval.from_date)
    new_to = dt.date.fromisoformat(new_interval.dates_to)

    # Load existing calendar; union with gap_dates.
    old_cal = _load_calendar_dates(out_dir / "calendars" / "day.txt")
    new_cal_dates = sorted(set(old_cal) | set(plan.gap_dates))

    # Detect front-extension: does OLD's history predate the existing calendar start?
    front_extension = (old_cal[0] - new_cal_dates[0]).days if new_cal_dates[0] < old_cal[0] else 0

    # Merged bin's logical start date.
    merged_from = min(old_from, new_from)

    (staging / "features").mkdir(parents=True)
    n_gap = len(plan.gap_dates)

    # 1. Build merged bins for NEW: OLD data + gap + NEW data.
    new_dir_staging = staging / "features" / plan.new_symbol.lower()
    new_dir_staging.mkdir()
    old_dir_live = out_dir / "features" / plan.old_symbol.lower()
    new_dir_live = out_dir / "features" / plan.new_symbol.lower()

    new_start_index = new_cal_dates.index(merged_from)

    for field in FIELDS:
        old_bytes = (old_dir_live / f"{field}.day.bin").read_bytes()
        new_bytes = (new_dir_live / f"{field}.day.bin").read_bytes()
        # Strip the 4-byte start_index header from each.
        old_data = old_bytes[4:]
        new_data = new_bytes[4:]
        # Synthetic gap bytes.
        synth_val = _synthetic_value(field, plan.synthetic_locked_ohlc)
        gap_data = struct.pack("<f", float(synth_val)) * n_gap
        merged_data = old_data + gap_data + new_data
        # Write with new header (start_index as float32).
        header = struct.pack("<f", float(new_start_index))
        (new_dir_staging / f"{field}.day.bin").write_bytes(header + merged_data)

    # 2. Copy OTHER pairs (not OLD, not NEW) unchanged; rewrite headers if front_extension > 0.
    for sym in idx.pairs:
        if sym in (plan.old_symbol, plan.new_symbol):
            continue
        src_dir = out_dir / "features" / sym.lower()
        dst_dir = staging / "features" / sym.lower()
        _shutil.copytree(src_dir, dst_dir)
        if front_extension > 0:
            for field_file in dst_dir.iterdir():
                if field_file.suffix == ".bin":
                    _rewrite_bin_start_index(field_file, +front_extension)

    # 3. Write new calendar.
    write_calendar(staging, new_cal_dates)

    # 4. Write new instruments: drop OLD, update NEW's range to [merged_from, new_to].
    instruments_ranges: dict[str, tuple[dt.date, dt.date]] = {}
    for sym, entry in idx.pairs.items():
        if sym == plan.old_symbol:
            continue
        if sym == plan.new_symbol:
            instruments_ranges[sym] = (merged_from, new_to)
        else:
            instruments_ranges[sym] = (
                dt.date.fromisoformat(entry.intervals[interval].from_date),
                dt.date.fromisoformat(entry.intervals[interval].dates_to),
            )
    write_instruments(staging, instruments_ranges)

    # 5. Build new IndexData.
    old_rows = old_interval.rows
    new_rows = new_interval.rows
    merged_rows = old_rows + n_gap + new_rows

    pairs_entries: dict[str, PairEntry] = {}
    for sym, entry in idx.pairs.items():
        if sym == plan.old_symbol:
            continue
        if sym == plan.new_symbol:
            pairs_entries[sym] = _build_pair_entry_from_staging(
                staging,
                sym,
                plan.new_base_asset,
                plan.new_quote_asset,
                merged_from,
                merged_rows,
                interval,
            )
        else:
            iv = entry.intervals[interval]
            if front_extension > 0:
                pairs_entries[sym] = _build_pair_entry_from_staging(
                    staging,
                    sym,
                    entry.base_asset,
                    entry.quote_asset,
                    dt.date.fromisoformat(iv.from_date),
                    iv.rows,
                    interval,
                )
            else:
                # Headers unchanged; reuse existing entry as-is, recomputing sha256 from staging copy.
                pairs_entries[sym] = _build_pair_entry_from_staging(
                    staging,
                    sym,
                    entry.base_asset,
                    entry.quote_asset,
                    dt.date.fromisoformat(iv.from_date),
                    iv.rows,
                    interval,
                )

    from cli.data.config import SCHEMA_VERSION

    new_index = IndexData(
        schema_version=SCHEMA_VERSION,
        updated_at=utc_now_iso(),
        calendar=CalendarEntry(
            freq="day",
            from_date=new_cal_dates[0].isoformat(),
            to_date=new_cal_dates[-1].isoformat(),
            days=len(new_cal_dates),
        ),
        pairs=pairs_entries,
        other_files={
            "calendars/day.txt": FileEntry(
                sha256=compute_sha256(staging / "calendars" / "day.txt"),
                updated_at=utc_now_iso(),
            ),
            "instruments/all.txt": FileEntry(
                sha256=compute_sha256(staging / "instruments" / "all.txt"),
                updated_at=utc_now_iso(),
            ),
        },
    )
    save_index(staging, new_index)


def rename_pipeline(
    out_dir: Path,
    old_symbol: str,
    new_symbol: str,
    source: Source,
    *,
    dry_run: bool = False,
) -> None:
    """Re-label OLD → NEW under the snapshot+commit discipline (Variant 1 and Variant 2)."""
    plan_fn = lambda d: _rename_plan(d, old_symbol, new_symbol, source)
    apply_fn = lambda d, s, p: _rename_apply(d, s, p)
    _execute_mutation(out_dir, "rename", plan_fn, apply_fn, dry_run=dry_run)
