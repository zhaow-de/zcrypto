"""Smoke-tests for the committed synthetic qlib fixture used by experiment tests."""

from __future__ import annotations

from pathlib import Path

from cli.data.verify import verify_dataset

PROVIDER = Path(__file__).resolve().parents[1] / "cli" / "experiment" / "data" / "provider"

EXPECTED_INSTRUMENTS = {
    "BTCUSDT",
    "ETHUSDT",
    "BNBUSDT",
    "SOLUSDT",
    "XRPUSDT",
    "ADAUSDT",
    "AVAXUSDT",
    "LINKUSDT",
    "DOGEUSDT",
    "TRXUSDT",
    "DOTUSDT",
    "POLUSDT",
    "LTCUSDT",
    "ATOMUSDT",
    "UNIUSDT",
    "NEARUSDT",
    "ARBUSDT",
    "APTUSDT",
    "PEPEUSDT",
    "BTCEUR",
    "ETHBTC",
}  # 21 total


def test_fixture_verify_passes():
    """The committed provider must pass a full verify (including gap check)."""
    report = verify_dataset(PROVIDER, fail_on_gap=True)
    assert report.ok is True, report.problems


def test_fixture_has_all_21_instruments():
    """Feature directories for all 21 instruments must be present."""
    features_dir = PROVIDER / "features"
    assert features_dir.is_dir(), f"features/ not found under {PROVIDER}"
    found = {d.name.upper() for d in features_dir.iterdir() if d.is_dir()}
    missing = EXPECTED_INSTRUMENTS - found
    assert not missing, f"Missing feature dirs: {sorted(missing)}"


def test_fixture_includes_reference_instruments():
    """BTCEUR and ETHBTC (non-USDT reference pairs) must be present."""
    features_dir = PROVIDER / "features"
    for sym in ("btceur", "ethbtc"):
        assert (features_dir / sym).is_dir(), f"Missing feature dir for {sym}"


def test_fixture_calendar_length():
    """Calendar must cover roughly 540 bars (2023-01-02..2024-06-28 = 544 days)."""
    cal_path = PROVIDER / "calendars" / "day.txt"
    lines = [ln for ln in cal_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert 530 <= len(lines) <= 560, f"Unexpected calendar length {len(lines)}"
