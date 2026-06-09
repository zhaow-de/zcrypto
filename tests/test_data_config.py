from cli.data import config


def test_supported_intervals_is_1d_only():
    assert config.SUPPORTED_INTERVALS == frozenset({"1d"})


def test_fields_ordered_eleven_unique():
    assert isinstance(config.FIELDS, tuple)
    assert len(config.FIELDS) == 11
    assert len(set(config.FIELDS)) == 11
    assert config.FIELDS[:5] == ("open", "high", "low", "close", "volume")


def test_constants_present():
    assert config.BASE_URL == "https://data.binance.vision"
    assert config.EXCHANGE_INFO_URL == "https://api.binance.com/api/v3/exchangeInfo"
    assert config.SNAPSHOT_KEEP == 7
    assert config.SCHEMA_VERSION == 1
