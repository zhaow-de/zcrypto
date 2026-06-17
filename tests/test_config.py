from pathlib import Path

import pytest

from cli.config import (
    AppConfig,
    ConfigError,
    FetchConfig,
    load_config,
    resolve_backup_dir,
    resolve_data_dir,
)


def _write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "zcrypto.toml"
    p.write_text(body)
    return p


def test_absent_file_yields_none_paths_and_default_fetch(tmp_path):
    cfg = load_config(tmp_path / "zcrypto.toml")
    assert cfg.data_dir is None
    assert cfg.backup_dir is None
    assert cfg.fetch == FetchConfig()


def test_reads_paths(tmp_path):
    cfg = load_config(_write(tmp_path, '[zcrypto]\ndata_dir = "data"\nbackup_dir = "../zcrypto-data"\n'))
    assert cfg.data_dir == Path("data")
    assert cfg.backup_dir == Path("../zcrypto-data")


def test_missing_one_path_key_is_none(tmp_path):
    cfg = load_config(_write(tmp_path, '[zcrypto]\ndata_dir = "data"\n'))
    assert cfg.data_dir == Path("data")
    assert cfg.backup_dir is None


def test_fetch_override_merges_over_defaults(tmp_path):
    cfg = load_config(_write(tmp_path, "[zcrypto.fetch]\nfetch_concurrency = 3\n"))
    assert cfg.fetch.fetch_concurrency == 3
    assert cfg.fetch.http_timeout_get_secs == 60  # untouched default


def test_malformed_toml_raises(tmp_path):
    with pytest.raises(ConfigError):
        load_config(_write(tmp_path, "this is = = not toml"))


def test_non_string_path_raises(tmp_path):
    with pytest.raises(ConfigError):
        load_config(_write(tmp_path, "[zcrypto]\ndata_dir = 5\n"))


def test_non_positive_fetch_value_raises(tmp_path):
    with pytest.raises(ConfigError):
        load_config(_write(tmp_path, "[zcrypto.fetch]\nfetch_concurrency = 0\n"))


def test_non_int_fetch_value_raises(tmp_path):
    with pytest.raises(ConfigError):
        load_config(_write(tmp_path, '[zcrypto.fetch]\nfetch_concurrency = "x"\n'))


def test_unknown_fetch_key_raises(tmp_path):
    with pytest.raises(ConfigError):
        load_config(_write(tmp_path, "[zcrypto.fetch]\nnope = 1\n"))


def test_bool_fetch_value_raises(tmp_path):
    # bool is a subclass of int; it must be rejected, not silently accepted as 1.
    with pytest.raises(ConfigError):
        load_config(_write(tmp_path, "[zcrypto.fetch]\nfetch_concurrency = true\n"))


def test_resolve_flag_wins(tmp_path):
    cfg = load_config(_write(tmp_path, '[zcrypto]\ndata_dir = "from_config"\n'))
    assert resolve_data_dir(Path("from_flag"), cfg) == Path("from_flag")


def test_resolve_falls_back_to_config(tmp_path):
    cfg = load_config(_write(tmp_path, '[zcrypto]\nbackup_dir = "cfg_bk"\n'))
    assert resolve_backup_dir(None, cfg) == Path("cfg_bk")


def test_resolve_unconfigured_raises_with_both_remedies():
    cfg = AppConfig(data_dir=None, backup_dir=None, fetch=FetchConfig())
    with pytest.raises(ConfigError) as exc:
        resolve_data_dir(None, cfg)
    msg = str(exc.value)
    assert "--data-dir" in msg and "[zcrypto].data_dir" in msg
