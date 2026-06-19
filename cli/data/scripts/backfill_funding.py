"""One-time idempotent retrofit script: write funding.day.bin for every instrument
in an existing dataset that was built before the funding layer was added.

Usage:
    uv run python cli/data/scripts/backfill_funding.py [--data-dir <path>]

Idempotency: if an instrument's funding.day.bin already exists AND its row count
matches the instrument's kline row count (full coverage), that instrument is skipped.
A full re-run writes nothing new and leaves the dataset byte-identical.

This script is NOT part of the routine `zcrypto data` flow — see cli/data/scripts/README.md.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from cli.config import load_config, resolve_backup_dir, resolve_data_dir


def retrofit_funding(
    paths: "object",  # DatasetPaths
    source: "object",  # Source
    *,
    mirror_root: Path | None = None,
) -> dict[str, int]:
    """Fetch and write funding.day.bin for every instrument lacking full coverage.

    For each instrument in the dataset:
    - If funding.day.bin already exists with the expected row count, skip it (idempotent).
    - Otherwise, fetch funding archives for the instrument's date range and write the bin.

    Args:
        paths: DatasetPaths with .data_dir pointing at the compiled dataset.
        source: Source (real BinanceSource or FakeSource) for funding archive fetches.
        mirror_root: optional mirror dir for caching archive zips. Defaults to
                     paths.backup_dir / "raw" when omitted (standard layout).

    Returns:
        dict with "written" and "skipped" counts.
    """
    # Import here so the module is importable without the full cli package on path
    # when run standalone; uv handles the env.
    from cli.data.index import FieldEntry, compute_sha256, load_index, save_index, utc_now_iso
    from cli.data.pipeline import _funding_for_pair
    from cli.data.qlib_writer import read_bin, write_bin

    data_dir: Path = paths.data_dir  # type: ignore[attr-defined]
    backup_dir: Path = paths.backup_dir  # type: ignore[attr-defined]

    if mirror_root is None:
        mirror_root = backup_dir / "raw"

    idx = load_index(data_dir)
    if idx is None:
        raise RuntimeError(f"no index.json found at {data_dir}; run 'zcrypto data download' first")

    written = 0
    skipped = 0

    for sym, pair_entry in idx.pairs.items():
        interval_entry = pair_entry.intervals.get("1d")
        if interval_entry is None:
            continue

        expected_rows = interval_entry.rows
        feat_dir = data_dir / "features" / sym.lower()
        funding_bin = feat_dir / "funding.day.bin"

        # Idempotency check: skip if the bin exists with the right row count AND is already
        # registered in index.json as the "funding" field. Both conditions must hold; a bin
        # that exists but is not indexed would be an orphan and block further pipeline runs.
        if funding_bin.exists() and "funding" in interval_entry.fields:
            try:
                _, vals = read_bin(funding_bin)
                if len(vals) == expected_rows:
                    skipped += 1
                    continue
            except Exception:
                pass  # bin is corrupt or wrong format; overwrite it

        # Fetch funding for this instrument's date range.
        from_date = dt.date.fromisoformat(interval_entry.from_date)
        to_date = dt.date.fromisoformat(interval_entry.to_date)

        fmap = _funding_for_pair(source, sym, from_date, to_date, mirror_root)

        # Build one value per calendar day in [from_date, to_date].
        calendar_days: list[dt.date] = []
        cur = from_date
        while cur <= to_date:
            calendar_days.append(cur)
            cur += dt.timedelta(days=1)

        funding_values = [fmap.get(d, float("nan")) for d in calendar_days]

        # Determine the start_index: position of from_date in the global calendar.
        cal_from = dt.date.fromisoformat(idx.calendar.from_date)
        start_index = (from_date - cal_from).days

        write_bin(funding_bin, funding_values, start_index=start_index)

        # Register the new field in index.json so verify_dataset doesn't flag it as orphan.
        funding_rel = f"features/{sym.lower()}/funding.day.bin"
        interval_entry.fields["funding"] = FieldEntry(
            bin=funding_rel,
            sha256=compute_sha256(funding_bin),
            updated_at=utc_now_iso(),
        )
        written += 1

    if written > 0:
        save_index(data_dir, idx)

    return {"written": written, "skipped": skipped}


def main() -> None:
    import argparse

    from cli.data.binance import BinanceSource
    from cli.data.layout import DatasetPaths

    parser = argparse.ArgumentParser(description="Retrofit $funding onto an existing klines-only dataset (idempotent).")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="Path to the compiled dataset directory (default: from zcrypto.toml).",
    )
    args = parser.parse_args()

    cfg = load_config()
    data_dir = resolve_data_dir(args.data_dir, cfg)
    backup_dir = resolve_backup_dir(None, cfg)
    paths = DatasetPaths(data_dir=data_dir, backup_dir=backup_dir)
    source = BinanceSource(fetch=cfg.fetch)

    print(f"Retrofitting $funding onto {data_dir} ...")
    summary = retrofit_funding(paths, source)
    print(f"Done: {summary['written']} written, {summary['skipped']} skipped.")


if __name__ == "__main__":
    main()
