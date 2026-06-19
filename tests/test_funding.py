import datetime as dt
import io
import zipfile

from cli.data.binance import funding_archive_parts, funding_url
from cli.data.funding import daily_funding, parse_funding, perp_symbol
from tests.data_fixtures import FakeSource


def test_perp_symbol_identity():
    assert perp_symbol("BTCUSDT", dt.date(2023, 1, 1)) == "BTCUSDT"


def test_perp_symbol_pepe_1000x():
    assert perp_symbol("PEPEUSDT", dt.date(2024, 1, 1)) == "1000PEPEUSDT"


def test_perp_symbol_pol_timesplit():
    assert perp_symbol("POLUSDT", dt.date(2024, 9, 10)) == "MATICUSDT"
    assert perp_symbol("POLUSDT", dt.date(2024, 9, 13)) == "POLUSDT"
    assert perp_symbol("POLUSDT", dt.date(2024, 9, 11)) is None  # rename gap
    assert perp_symbol("POLUSDT", dt.date(2024, 9, 12)) is None


def test_daily_funding_sums_settlements():
    d = dt.date(2024, 1, 1)
    rows = [
        (dt.datetime(2024, 1, 1, 0), 0.0001),
        (dt.datetime(2024, 1, 1, 8), 0.0002),
        (dt.datetime(2024, 1, 1, 16), 0.0003),
        (dt.datetime(2024, 1, 2, 0), 0.0005),
    ]
    out = daily_funding(rows)
    assert abs(out[d] - 0.0006) < 1e-12
    assert abs(out[dt.date(2024, 1, 2)] - 0.0005) < 1e-12


# --- parse_funding: synthetic archive matching the recon'd Vision schema --------------
#
# RECON (verified against data.binance.vision 2026-06-19):
#   path:    data/futures/um/monthly/fundingRate/<PERP>/<PERP>-fundingRate-<YYYY-MM>.zip
#   columns: calc_time, funding_interval_hours, last_funding_rate   (header present)
#   units:   calc_time = ms epoch (UTC); rate = decimal fraction
#   cadence: 8-hourly (00/08/16 UTC) historically; some perps moved to 4-hourly
#            (00/04/08/12/16/20 UTC) — calc_time can carry a few ms of jitter.


def _make_funding_zip(rows: list[tuple[int, int, str]], csv_name: str = "BTCUSDT-fundingRate-2024-01.csv") -> bytes:
    lines = ["calc_time,funding_interval_hours,last_funding_rate"]
    lines += [f"{ct},{iv},{rate}" for ct, iv, rate in rows]
    csv = ("\n".join(lines) + "\n").encode()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(csv_name, csv)
    return buf.getvalue()


def test_parse_funding_schema():
    # 2024-01-01 00:00 / 08:00 / 16:00 UTC, 8-hourly. Last ts carries 1 ms of jitter.
    rows = [
        (1704067200000, 8, "0.00037409"),
        (1704096000000, 8, "0.00027213"),
        (1704124800001, 8, "0.00033601"),
    ]
    out = parse_funding(_make_funding_zip(rows))
    assert out == [
        (dt.datetime(2024, 1, 1, 0, 0, tzinfo=dt.timezone.utc), 0.00037409),
        (dt.datetime(2024, 1, 1, 8, 0, tzinfo=dt.timezone.utc), 0.00027213),
        # sub-second jitter preserved on the datetime; daily_funding buckets by date.
        (dt.datetime(2024, 1, 1, 16, 0, 0, 1000, tzinfo=dt.timezone.utc), 0.00033601),
    ]


def test_parse_funding_then_daily_funding_4hourly():
    # POL moved to 4-hourly funding — daily_funding must sum all settlements per UTC
    # date, cadence-agnostic. Six 4-hourly settlements on 2024-09-14.
    base = int(dt.datetime(2024, 9, 14, 0, tzinfo=dt.timezone.utc).timestamp() * 1000)
    rows = [(base + i * 4 * 3600 * 1000, 4, f"0.0000{i + 1}") for i in range(6)]
    parsed = parse_funding(_make_funding_zip(rows, "POLUSDT-fundingRate-2024-09.csv"))
    out = daily_funding(parsed)
    expected = sum(0.0000 + (i + 1) / 100000 for i in range(6))
    assert abs(out[dt.date(2024, 9, 14)] - expected) < 1e-12


# --- funding_archive_parts / funding_url -------------------------------------------


def test_funding_archive_parts():
    rel_dir, name = funding_archive_parts("BTCUSDT", 2024, 1)
    assert rel_dir == "futures/um/monthly/fundingRate/BTCUSDT"
    assert name == "BTCUSDT-fundingRate-2024-01.zip"


def test_funding_archive_parts_zero_pads_month():
    rel_dir, name = funding_archive_parts("ETHUSDT", 2023, 9)
    assert name == "ETHUSDT-fundingRate-2023-09.zip"


def test_funding_url():
    url = funding_url("BTCUSDT", 2024, 1)
    assert url == "https://data.binance.vision/data/futures/um/monthly/fundingRate/BTCUSDT/BTCUSDT-fundingRate-2024-01.zip"


# --- FakeSource.fetch_funding_archive -----------------------------------------------


def test_fake_source_fetch_funding_archive_returns_parseable_bytes():
    src = FakeSource()
    src.add_funding("BTCUSDT", 2024, 1)
    raw = src.fetch_funding_archive("BTCUSDT", 2024, 1)
    assert isinstance(raw, bytes)
    rows = parse_funding(raw)
    assert len(rows) > 0
    # All settlements should fall within January 2024
    for ts, rate in rows:
        assert ts.year == 2024
        assert ts.month == 1
        assert isinstance(rate, float)


def test_fake_source_fetch_funding_archive_missing_returns_none():
    src = FakeSource()
    # Not added — should return None (mirroring 404 convention)
    result = src.fetch_funding_archive("BTCUSDT", 2024, 1)
    assert result is None


# --- _funding_for_pair: end-to-end perp-attribution tests ---------------------------


def _make_funding_zip_custom(perp: str, year: int, month: int, settlements: list[tuple[dt.datetime, float]]) -> bytes:
    """Build a Binance-shaped funding zip with explicit settlement timestamps and rates."""
    lines = ["calc_time,funding_interval_hours,last_funding_rate"]
    for ts, rate in settlements:
        ms = int(ts.timestamp() * 1000)
        lines.append(f"{ms},8,{rate:.8f}")
    csv = ("\n".join(lines) + "\n").encode()
    inner_name = f"{perp}-fundingRate-{year}-{month:02d}.csv"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(inner_name, csv)
    return buf.getvalue()


def test_funding_for_pair_pol_split(tmp_path) -> None:
    """_funding_for_pair must use MATIC rates for dates <=09-10 and POL rates for dates >=09-13.

    09-11 and 09-12 are the rename gap (perp_symbol returns None) so they must be absent.

    Bug being tested: without the perp_symbol attribution check, the POLUSDT archive's
    settlement on 2024-09-01 (a MATIC-attributed date) bleeds into the output — producing
    a wrong non-NaN value for a day that should only be populated from MATICUSDT data.
    """
    from cli.data.pipeline import _funding_for_pair

    tz = dt.timezone.utc
    # MATICUSDT Sept-2024: one settlement on 2024-09-08 at a distinctive rate
    matic_zip = _make_funding_zip_custom(
        "MATICUSDT",
        2024,
        9,
        [(dt.datetime(2024, 9, 8, 0, tzinfo=tz), 0.001)],
    )
    # POLUSDT Sept-2024: settlement on 2024-09-01 (a MATIC-attributed date — must NOT bleed)
    # plus a legitimate settlement on 2024-09-13 (a POL-attributed date).
    pol_zip = _make_funding_zip_custom(
        "POLUSDT",
        2024,
        9,
        [
            (dt.datetime(2024, 9, 1, 0, tzinfo=tz), 0.999),  # must be excluded: 09-01 → MATIC
            (dt.datetime(2024, 9, 13, 0, tzinfo=tz), 0.009),
        ],
    )

    src = FakeSource()
    src.add_funding("MATICUSDT", 2024, 9, raw=matic_zip)
    src.add_funding("POLUSDT", 2024, 9, raw=pol_zip)

    result = _funding_for_pair(src, "POLUSDT", dt.date(2024, 9, 1), dt.date(2024, 9, 15), tmp_path)

    # 09-01 is in MATIC range → the POLUSDT archive's 0.999 settlement must NOT appear here
    assert dt.date(2024, 9, 1) not in result, (
        f"09-01 (MATIC date) must be absent — POLUSDT archive data must not bleed into MATIC dates; "
        f"got {result.get(dt.date(2024, 9, 1))}"
    )

    # 09-08 is in MATIC range → MATIC rate from MATICUSDT archive
    assert dt.date(2024, 9, 8) in result, "09-08 (MATIC date) must be present"
    assert abs(result[dt.date(2024, 9, 8)] - 0.001) < 1e-9, (
        f"09-08 rate should be MATIC (0.001), got {result.get(dt.date(2024, 9, 8))}"
    )

    # 09-13 is in POL range → POL rate
    assert dt.date(2024, 9, 13) in result, "09-13 (POL date) must be present"
    assert abs(result[dt.date(2024, 9, 13)] - 0.009) < 1e-9, (
        f"09-13 rate should be POL (0.009), got {result.get(dt.date(2024, 9, 13))}"
    )

    # 09-11 and 09-12 are the rename gap → must be absent
    assert dt.date(2024, 9, 11) not in result, "09-11 (rename gap) must be absent"
    assert dt.date(2024, 9, 12) not in result, "09-12 (rename gap) must be absent"


def test_funding_for_pair_pepe_1000x(tmp_path) -> None:
    """_funding_for_pair("PEPEUSDT", ...) must read from 1000PEPEUSDT archives."""
    from cli.data.pipeline import _funding_for_pair

    tz = dt.timezone.utc
    pepe_zip = _make_funding_zip_custom(
        "1000PEPEUSDT",
        2024,
        1,
        [(dt.datetime(2024, 1, 5, 0, tzinfo=tz), 0.00042)],
    )

    src = FakeSource()
    src.add_funding("1000PEPEUSDT", 2024, 1, raw=pepe_zip)

    result = _funding_for_pair(src, "PEPEUSDT", dt.date(2024, 1, 1), dt.date(2024, 1, 7), tmp_path)

    assert dt.date(2024, 1, 5) in result, "2024-01-05 must be present via 1000PEPEUSDT archive"
    assert abs(result[dt.date(2024, 1, 5)] - 0.00042) < 1e-9, f"unexpected rate: {result.get(dt.date(2024, 1, 5))}"
