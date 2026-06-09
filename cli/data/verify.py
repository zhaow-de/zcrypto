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
    expected_dates = [cal_from + dt.timedelta(days=i) for i in range((cal_to - cal_from).days + 1)]
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
                problems.append(f"{sym} {interval}: rows {entry.rows} != expected {expected_rows}")
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
                    problems.append(f"{sym} {interval} {fname}: bin size {actual_size} != {expected_size}")
                else:
                    header_start, _ = read_bin(bin_path)
                    if header_start != start_idx:
                        problems.append(f"{sym} {interval} {fname}: header {header_start} != calendar index {start_idx}")

    indexed_bins = {e.bin for pair in index.pairs.values() for inter in pair.intervals.values() for e in inter.fields.values()}
    features_dir = out_dir / "features"
    if features_dir.is_dir():
        for p in features_dir.rglob("*.bin"):
            rel = p.relative_to(out_dir).as_posix()
            if rel not in indexed_bins:
                problems.append(f"orphan bin file: {rel}")

    return VerifyReport(ok=not problems, problems=problems)
