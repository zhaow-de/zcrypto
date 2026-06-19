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
