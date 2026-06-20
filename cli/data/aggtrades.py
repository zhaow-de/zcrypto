from __future__ import annotations

import datetime as dt
import io
import json
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from cli.config import FetchConfig
from cli.data import mirror
from cli.data.binance import Source
from cli.data.layout import DatasetPaths
from cli.data.pipeline import PipelineError, fetch_checksummed_zip
from cli.logging import get_logger

logger = get_logger("data.aggtrades")

_MANIFEST_REL = "spot/daily/aggTrades/aggtrades-manifest.json"


def validate_aggtrades_zip(raw: bytes) -> None:
    """Structural integrity gate for a daily aggTrades zip — NO full row parse.

    aggTrades archives carry millions of rows; parsing every one would be prohibitively slow.
    This asserts only the structure: the bytes open as a zip, extract to exactly one `.csv`
    member, and that member is non-empty/openable. Raises `ValueError` otherwise. Used as the
    integrity gate on the unchecksummed path, mirroring how `parse_kline_zip` gates klines.
    """
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        names = zf.namelist()
        csv_names = [n for n in names if n.lower().endswith(".csv")]
        if len(csv_names) != 1:
            raise ValueError(f"aggTrades zip: expected exactly one .csv member, got {names}")
        name = csv_names[0]
        info = zf.getinfo(name)
        if info.file_size == 0:
            raise ValueError(f"aggTrades zip: member {name!r} is empty")
        with zf.open(name) as fh:
            if not fh.read(1):
                raise ValueError(f"aggTrades zip: member {name!r} is not readable / empty")


def _fetch_one_aggtrades(
    source: Source,
    symbol: str,
    date: dt.date,
    raw_root: Path,
) -> tuple[str, dt.date, bytes, bool]:
    """Fetch one (symbol, date) aggTrades zip.

    Mirror hit → return cached bytes (skipped=True). Miss → fetch_checksummed_zip; if not
    checksum-validated, run validate_aggtrades_zip as the integrity gate (gate-before-save,
    never cache an invalid zip); then save to mirror. Returns (symbol, date, raw, skipped).
    """
    mpath = mirror.aggtrades_mirror_path(raw_root, symbol, date)
    cached = mirror.read_zip(mpath)
    if cached is not None:
        logger.debug("aggtrades mirror hit %s %s: %s", symbol, date, mpath)
        return symbol, date, cached, True

    try:
        zip_bytes, validated = fetch_checksummed_zip(
            lambda: source.fetch_aggtrades_archive(symbol, date),
            lambda: source.fetch_aggtrades_checksum(symbol, date),
        )
    except PipelineError:
        raise PipelineError(f"{symbol} {date}: checksum mismatch") from None

    if not validated:
        try:
            validate_aggtrades_zip(zip_bytes)
        except ValueError as e:
            raise PipelineError(f"{symbol} {date}: invalid zip structure: {e}") from e
        logger.warning("%s %s: no .CHECKSUM published; verified by structure only", symbol, date)

    mirror.save_zip(mpath, zip_bytes)
    return symbol, date, zip_bytes, False


def fetch_aggtrades_sample(
    paths: DatasetPaths,
    source: Source,
    pairs: list[str],
    from_date: dt.date,
    to_date: dt.date,
    *,
    fetch: FetchConfig = FetchConfig(),
) -> dict[str, Any]:
    """Fetch daily aggTrades zips for `pairs` over `[from_date, to_date]`, mirror them, and write a manifest.

    Idempotent: a mirror hit skips re-fetch (no network call). Integrity gate: unchecksummed zips
    are validated structurally by `validate_aggtrades_zip` before save, same as the kline path.
    Concurrency: bounded thread pool, mirroring `_fetch_all_concurrent`'s pattern.

    Returns the manifest dict (also written as JSON to the aggTrades mirror root).
    """
    raw_root = paths.raw_root
    work: list[tuple[str, dt.date]] = []
    for pair in pairs:
        cur = from_date
        while cur <= to_date:
            work.append((pair, cur))
            cur += dt.timedelta(days=1)

    max_workers = fetch.fetch_concurrency
    log_every = fetch.fetch_progress_log_interval
    total = len(work)
    completed = 0

    # per_pair_stats: fetched_bytes list + skipped count
    per_pair_fetched: dict[str, list[tuple[dt.date, int]]] = {p: [] for p in pairs}
    per_pair_skipped: dict[str, int] = {p: 0 for p in pairs}

    logger.info("aggtrades: fetching %d (pair, date) tuples (max_workers=%d)", total, max_workers)

    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="zcrypto-aggt") as pool:
        futures = {pool.submit(_fetch_one_aggtrades, source, sym, d, raw_root): (sym, d) for sym, d in work}
        try:
            for fut in as_completed(futures):
                sym, d = futures[fut]
                try:
                    s, date, raw, skipped = fut.result()
                except PipelineError:
                    raise
                except Exception as e:
                    raise PipelineError(f"{sym} {d}: fetch failed: {e}") from e
                if skipped:
                    per_pair_skipped[s] += 1
                else:
                    per_pair_fetched[s].append((date, len(raw)))
                completed += 1
                if completed % log_every == 0 or completed == total:
                    logger.info("aggtrades fetch progress: %d/%d (%.1f%%)", completed, total, 100.0 * completed / total)
        except BaseException:
            for f in futures:
                f.cancel()
            raise

    pairs_stats: dict[str, dict[str, Any]] = {}
    for pair in pairs:
        fetched_entries = sorted(per_pair_fetched[pair], key=lambda x: x[0])
        pairs_stats[pair] = {
            "fetched": len(fetched_entries),
            "skipped": per_pair_skipped[pair],
            "fetched_dates": [d.isoformat() for d, _ in fetched_entries],
            "total_bytes": sum(b for _, b in fetched_entries),
        }

    manifest: dict[str, Any] = {
        "pairs": pairs,
        "from": from_date.isoformat(),
        "to": to_date.isoformat(),
        "pairs_stats": pairs_stats,
    }

    manifest_path = raw_root / _MANIFEST_REL
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    logger.info("aggtrades manifest written to %s", manifest_path)

    return manifest
