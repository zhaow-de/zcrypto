"""Pure funding-rate layer: spot↔perp mapping, archive parse, 8-hourly→daily sum.

No qlib, no network — stdlib + pandas only. The network probe that established the
Binance Vision schema lives in the iteration's RECON report, not here.

RECON (verified against data.binance.vision on 2026-06-19):
  - Archive: data/futures/um/monthly/fundingRate/<PERP>/<PERP>-fundingRate-<YYYY-MM>.zip
  - One CSV per zip, columns: calc_time, funding_interval_hours, last_funding_rate
    (a header row is present).
  - calc_time is a UTC ms epoch (occasionally carrying a few ms of jitter, e.g.
    1704412800001); last_funding_rate is a decimal fraction (e.g. 0.00037409).
  - Settlement cadence is 8-hourly (00/08/16 UTC) historically; some perps have
    since moved to 4-hourly (00/04/08/12/16/20 UTC). daily_funding sums every
    settlement that falls on a UTC date, so it is cadence-agnostic.
"""

from __future__ import annotations

import datetime as dt
import io
import zipfile

import pandas as pd

# The 19 USDT-spot coins (instruments/all.txt minus the non-USDT BTCEUR / ETHBTC)
# map to a USDT-perp ticker on Binance USDⓈ-M futures. The default is identity;
# only the two below differ. All 19 perp tickers were confirmed present on
# data.binance.vision (2026-06-19).

# PEPE trades as 1000PEPEUSDT on futures (the perp is denominated in 1000-PEPE
# units); the spot pair is PEPEUSDT.
_PERP_OVERRIDE: dict[str, str] = {
    "PEPEUSDT": "1000PEPEUSDT",
}

# POL was renamed from MATIC. The spot instrument is POLUSDT throughout; the perp
# to source from depends on the date:
#   <= 2024-09-10  -> MATICUSDT     (pre-rename perp)
#   2024-09-11/12  -> None          (rename gap — no perp attributed)
#   >= 2024-09-13  -> POLUSDT       (post-rename perp; POL futures funding starts
#                                    2024-09-13 16:00 UTC)
_MATIC_LAST_DATE = dt.date(2024, 9, 10)
_POL_FIRST_DATE = dt.date(2024, 9, 13)


def perp_symbol(instrument: str, on: dt.date) -> str | None:
    """The USDT-perp symbol to source funding from for `instrument` on UTC date `on`.

    Returns None only during the MATIC→POL rename gap (2024-09-11/12), where no
    perp is attributed to the spot instrument.
    """
    if instrument == "POLUSDT":
        if on <= _MATIC_LAST_DATE:
            return "MATICUSDT"
        if on >= _POL_FIRST_DATE:
            return "POLUSDT"
        return None
    return _PERP_OVERRIDE.get(instrument, instrument)


def parse_funding(raw: bytes) -> list[tuple[dt.datetime, float]]:
    """Decode one Binance funding-rate monthly zip → [(settlement_time_utc, rate), ...].

    Tolerates the optional header row and the ms jitter on calc_time. Rows are
    returned in file order (chronological); the settlement datetime is tz-aware UTC.
    """
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        names = zf.namelist()
        if len(names) != 1:
            raise ValueError(f"expected exactly one file in funding zip, got {names}")
        csv_bytes = zf.read(names[0])

    # Header detection: a data row's first cell is an integer epoch; a header is not.
    first_cell = csv_bytes.split(b",", 1)[0].split(b"\n", 1)[0].strip()
    skiprows = 0 if first_cell.lstrip(b"-").isdigit() else 1
    df = pd.read_csv(
        io.BytesIO(csv_bytes),
        header=None,
        skiprows=skiprows,
        names=["calc_time", "funding_interval_hours", "last_funding_rate"],
    )

    out: list[tuple[dt.datetime, float]] = []
    for calc_time, rate in zip(df["calc_time"], df["last_funding_rate"]):
        ts = dt.datetime.fromtimestamp(int(calc_time) / 1000, tz=dt.timezone.utc)
        out.append((ts, float(rate)))
    return out


def daily_funding(rows: list[tuple[dt.datetime, float]]) -> dict[dt.date, float]:
    """Sum funding rates by UTC settlement date (the daily carry).

    Cadence-agnostic: 8-hourly, 4-hourly, or any mix sums correctly because each
    settlement is bucketed by its UTC date.
    """
    out: dict[dt.date, float] = {}
    for ts, rate in rows:
        day = ts.astimezone(dt.timezone.utc).date() if ts.tzinfo is not None else ts.date()
        out[day] = out.get(day, 0.0) + rate
    return out
