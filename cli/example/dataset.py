from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

FIELDS = ["open", "high", "low", "close", "volume", "factor"]


def build_provider(csv_path: Path, out_dir: Path) -> str:
    """Write a Qlib file-format dataset from an OHLCV CSV; return the provider_uri."""
    df = pd.read_csv(csv_path, parse_dates=["date"]).sort_values(["symbol", "date"])
    if "factor" not in df.columns:
        df["factor"] = 1.0

    calendar = sorted(pd.to_datetime(df["date"].unique()))
    date_to_idx = {ts: i for i, ts in enumerate(calendar)}

    out_dir = Path(out_dir)
    _write_calendar(out_dir, calendar)
    _write_instruments(out_dir, df)
    _write_features(out_dir, df, date_to_idx)
    return str(out_dir)


def _write_calendar(out_dir: Path, calendar: list) -> None:
    cal_dir = out_dir / "calendars"
    cal_dir.mkdir(parents=True, exist_ok=True)
    lines = [ts.strftime("%Y-%m-%d") for ts in calendar]
    (cal_dir / "day.txt").write_text("\n".join(lines) + "\n")


def _write_instruments(out_dir: Path, df: pd.DataFrame) -> None:
    inst_dir = out_dir / "instruments"
    inst_dir.mkdir(parents=True, exist_ok=True)
    lines = []
    for symbol, g in df.groupby("symbol"):
        start = g["date"].min().strftime("%Y-%m-%d")
        end = g["date"].max().strftime("%Y-%m-%d")
        lines.append(f"{symbol.upper()}\t{start}\t{end}")
    (inst_dir / "all.txt").write_text("\n".join(lines) + "\n")


def _write_features(out_dir: Path, df: pd.DataFrame, date_to_idx: dict) -> None:
    for symbol, g in df.groupby("symbol"):
        g = g.sort_values("date")
        start_idx = date_to_idx[g["date"].iloc[0]]
        code_dir = out_dir / "features" / symbol.lower()
        code_dir.mkdir(parents=True, exist_ok=True)
        for field in FIELDS:
            values = g[field].to_numpy(dtype="float32")
            arr = np.concatenate([[np.float32(start_idx)], values]).astype("<f4")
            arr.tofile(code_dir / f"{field}.day.bin")
