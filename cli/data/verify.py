from __future__ import annotations

import dataclasses as dc
import datetime as dt
from pathlib import Path

import numpy as np

from cli.data.config import SCHEMA_VERSION
from cli.data.index import compute_sha256, load_index
from cli.data.qlib_writer import read_bin


@dc.dataclass
class VerifyReport:
    ok: bool
    problems: list[str]
    is_empty: bool = False
    checks: list[str] = dc.field(default_factory=list)  # human-readable account of what was validated
    synthetic: list[str] = dc.field(default_factory=list)  # per-pair synthetic (NaN-price) day summaries


def _iso_to_date(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


def _collapse_date_ranges(dates: list[dt.date]) -> list[str]:
    """Collapse a sorted date list into compact contiguous-range strings (`a..b` or `a`)."""
    out: list[str] = []
    run_start = run_end = dates[0]
    for d in dates[1:]:
        if d == run_end + dt.timedelta(days=1):
            run_end = d
        else:
            out.append(f"{run_start}..{run_end}" if run_start != run_end else f"{run_start}")
            run_start = run_end = d
    out.append(f"{run_start}..{run_end}" if run_start != run_end else f"{run_start}")
    return out


def verify_dataset(out_dir: Path, *, fail_on_gap: bool = False) -> VerifyReport:
    """Read-only re-validation of every invariant in `docs/specs/00003-data-prep-design.md`.

    `fail_on_gap` adds a completeness check: every calendar day must be covered by at
    least one pair. It is off by default because a legitimate intermediate state — two
    pairs with a listing gap between them (e.g. MATIC delisted before POL listed),
    pending a `rename` that fills the gap — has an interior gap yet is structurally
    valid, so the mutation harness must accept it. The user-facing `data verify` command
    turns it on to flag an incomplete dataset.
    """
    problems: list[str] = []
    checks: list[str] = []
    synthetic: list[str] = []

    # Distinguish "empty" (legitimate fresh state) from "partial/broken" (corruption).
    index_path = out_dir / "index.json"
    has_index = index_path.exists()
    has_components = any((out_dir / name).exists() for name in ("calendars", "instruments", "features"))
    if not has_index and not has_components:
        return VerifyReport(ok=True, problems=[], is_empty=True)
    if not has_index:
        return VerifyReport(
            ok=False,
            problems=[
                "index.json missing but dataset components (calendars/instruments/features) "
                "are present — partial/broken state. Restore from .snapshots/ or remove the orphan files."
            ],
        )

    index = load_index(out_dir)
    assert index is not None, "has_index just checked"
    if index.schema_version != SCHEMA_VERSION:
        problems.append(f"unknown schema_version {index.schema_version}")
    checks.append(f"index.json present; schema_version == {SCHEMA_VERSION}")

    if (out_dir / ".commit-in-progress").exists():
        problems.append(
            "stale commit-in-progress marker found; the previous download may have been "
            "interrupted — re-run `data download` to auto-recover or inspect .snapshots/"
        )
    checks.append("no stale .commit-in-progress marker")

    cal_path = out_dir / "calendars" / "day.txt"
    if not cal_path.exists():
        problems.append("calendars/day.txt missing")
        return VerifyReport(False, problems, checks=checks, synthetic=synthetic)

    raw = cal_path.read_text(encoding="utf-8").strip().splitlines()
    on_disk_dates = [_iso_to_date(line) for line in raw if line.strip()]
    cal_from = _iso_to_date(index.calendar.from_date)
    cal_to = _iso_to_date(index.calendar.to_date)
    expected_dates = [cal_from + dt.timedelta(days=i) for i in range((cal_to - cal_from).days + 1)]
    if on_disk_dates != expected_dates:
        problems.append("calendar file is not dense or does not match index calendar")
    if len(on_disk_dates) != index.calendar.days:
        problems.append(f"calendar days {len(on_disk_dates)} != index.days {index.calendar.days}")
    checks.append(f"calendar/day.txt: dense daily {cal_from}..{cal_to} ({len(expected_dates)} days), matches index")

    cal_index = {d: i for i, d in enumerate(expected_dates)}

    # Calendar sha (independent of instruments existence)
    cal_entry = index.other_files.get("calendars/day.txt")
    if cal_entry is None:
        problems.append("calendars/day.txt entry missing from other_files")
    elif compute_sha256(cal_path) != cal_entry.sha256:
        problems.append("calendars/day.txt sha256 mismatch")

    # Instruments file (existence, sha, matches index)
    inst_path = out_dir / "instruments" / "all.txt"
    if not inst_path.exists():
        problems.append("instruments/all.txt missing")
    else:
        inst_entry = index.other_files.get("instruments/all.txt")
        if inst_entry is None:
            problems.append("instruments/all.txt entry missing from other_files")
        elif compute_sha256(inst_path) != inst_entry.sha256:
            problems.append("instruments/all.txt sha256 mismatch")
        instr_lines = sorted(inst_path.read_text(encoding="utf-8").strip().splitlines())
        expected_lines = sorted(
            f"{sym.upper()}\t{p.intervals['1d'].from_date}\t{p.intervals['1d'].dates_to}"
            for sym, p in index.pairs.items()
            if "1d" in p.intervals
        )
        if instr_lines != expected_lines:
            problems.append("instruments/all.txt does not match index pairs")
    checks.append(f"calendars/day.txt + instruments/all.txt sha256; instruments matches index ({len(index.pairs)} pair(s))")

    for sym, pair in index.pairs.items():
        for interval, entry in pair.intervals.items():
            from_d = _iso_to_date(entry.from_date)
            if from_d not in cal_index:
                problems.append(f"{sym} {interval}: from-date {from_d} not in calendar")
                continue
            start_idx = cal_index[from_d]
            # Rows are stored per-pair in the index; pairs may end before calendar.to (e.g. delisted pairs).
            expected_rows = entry.rows
            if expected_rows <= 0:
                problems.append(f"{sym} {interval}: rows {expected_rows} must be > 0")
            # Interval-agnostic cross-check: to-date is the calendar entry at start_idx + rows - 1.
            to_d = _iso_to_date(entry.dates_to)
            if to_d not in cal_index:
                problems.append(f"{sym} {interval}: to-date {to_d} not in calendar")
            elif cal_index[to_d] != start_idx + expected_rows - 1:
                problems.append(
                    f"{sym} {interval}: to-date {to_d} (calendar index {cal_index[to_d]}) "
                    f"!= from index {start_idx} + rows {expected_rows} - 1"
                )
            # Cross-check: all fields for this pair must agree on the same row count.
            _checked_first_field = False
            for fname, fentry in entry.fields.items():
                bin_path = out_dir / fentry.bin
                if not bin_path.exists():
                    problems.append(f"{sym} {interval} {fname}: bin {fentry.bin} missing")
                    continue
                if compute_sha256(bin_path) != fentry.sha256:
                    problems.append(f"{sym} {interval} {fname}: sha256 mismatch")
                actual_size = bin_path.stat().st_size
                actual_rows_from_bin = (actual_size // 4) - 1
                if not _checked_first_field:
                    # Emit a "rows" problem when index.rows disagrees with what the bin encodes.
                    if actual_rows_from_bin != expected_rows:
                        problems.append(f"{sym} {interval}: rows {expected_rows} != bin-derived rows {actual_rows_from_bin}")
                    _checked_first_field = True
                expected_size = (expected_rows + 1) * 4
                if actual_size != expected_size:
                    problems.append(f"{sym} {interval} {fname}: bin size {actual_size} != {expected_size}")
                else:
                    header_start, values = read_bin(bin_path)
                    if header_start != start_idx:
                        problems.append(f"{sym} {interval} {fname}: header {header_start} != calendar index {start_idx}")
                    # Synthetic days carry NaN price (rename gap fill); report them from the close series.
                    if fname == "close":
                        nan_offsets = np.nonzero(np.isnan(values))[0]
                        if nan_offsets.size:
                            syn_dates = [expected_dates[start_idx + int(o)] for o in nan_offsets]
                            synthetic.append(
                                f"{sym} {interval}: {nan_offsets.size} synthetic day(s) "
                                f"({', '.join(_collapse_date_ranges(syn_dates))})"
                            )
    checks.append(
        f"per-pair ({len(index.pairs)}): from in calendar, rows>0, to == calendar[from+rows-1], every field bin sha256/size/header"
    )

    # Interior-gap completeness check (opt-in): every calendar day must be covered by
    # >= 1 pair's [from, to]. Off for the harness gate; on for the `data verify` command.
    if fail_on_gap:
        covered = [False] * len(expected_dates)
        for pair in index.pairs.values():
            for entry in pair.intervals.values():
                fd = _iso_to_date(entry.from_date)
                td = _iso_to_date(entry.dates_to)
                if fd in cal_index and td in cal_index:
                    for i in range(cal_index[fd], cal_index[td] + 1):
                        covered[i] = True
        uncovered = [expected_dates[i] for i, c in enumerate(covered) if not c]
        if uncovered:
            problems.append(
                f"interior calendar gap: {len(uncovered)} day(s) covered by no pair — "
                + "; ".join(_collapse_date_ranges(uncovered))
            )
        else:
            checks.append("no interior calendar gap (every day covered by >=1 pair)")

    indexed_bins = {e.bin for pair in index.pairs.values() for inter in pair.intervals.values() for e in inter.fields.values()}
    features_dir = out_dir / "features"
    if features_dir.is_dir():
        for p in features_dir.rglob("*.bin"):
            rel = p.relative_to(out_dir).as_posix()
            if rel not in indexed_bins:
                problems.append(f"orphan bin file: {rel}")

    # Orphans in calendars/ and instruments/ not listed in other_files
    indexed_other = set(index.other_files.keys())
    for name, subdir in (("calendars", "calendars"), ("instruments", "instruments")):
        d = out_dir / subdir
        if d.is_dir():
            for p in d.iterdir():
                if not p.is_file():
                    continue
                rel = p.relative_to(out_dir).as_posix()
                if rel not in indexed_other:
                    problems.append(f"orphan file: {rel}")
    checks.append("no orphan bin / calendar / instrument files")

    return VerifyReport(ok=not problems, problems=problems, checks=checks, synthetic=synthetic)
