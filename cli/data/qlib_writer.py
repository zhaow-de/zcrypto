from __future__ import annotations

import datetime as dt
from pathlib import Path

import numpy as np


def write_calendar(out_dir: Path, dates: list[dt.date]) -> None:
    """Write `<out_dir>/calendars/day.txt` — one ISO date per line, sorted."""
    dates = sorted(dates)
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
    if start_index < 0:
        raise ValueError(f"start_index must be >= 0, got {start_index}")
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
    header = float(arr[0])
    if not header.is_integer():
        raise ValueError(f"{path}: bin header {header} is not a whole number")
    return int(header), arr[1:]
