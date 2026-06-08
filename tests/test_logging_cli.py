import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cli.__main__ import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def _reset_loggers():
    import logging

    yield
    for name in ("zcrypto", "qlib"):
        lg = logging.getLogger(name)
        for h in list(lg.handlers):
            lg.removeHandler(h)
            try:
                h.close()
            except OSError:
                pass
        lg.propagate = True
        lg.setLevel(logging.NOTSET)


def test_version_still_works_without_log_flags():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "zcrypto v" in result.output


def test_log_flag_writes_jsonl_to_file(tmp_path: Path):
    log = tmp_path / "z.log"
    result = runner.invoke(app, ["-l", str(log), "example"])
    assert result.exit_code == 0, result.output
    # _render's metrics table goes to stdout (typer.echo); no logs should land there with -l.
    assert "annualized_return" in result.stdout
    assert "Excess vs ETH" in result.stdout
    # file must be JSONL with the documented field set
    lines = [ln for ln in log.read_text().splitlines() if ln.strip()]
    assert lines, "log file is empty"
    parsed = [json.loads(ln) for ln in lines]
    for obj in parsed:
        assert set(obj.keys()) >= {"ts", "level", "logger", "file", "line", "message"}
        assert "pid" not in obj and "thread" not in obj
    # qlib emits INFO records through the qlib.* namespace during init/fit.
    assert any(obj["logger"].startswith("qlib.") for obj in parsed), "no qlib record captured"


def test_no_log_flag_emits_plain_text_lines_on_stdout():
    result = runner.invoke(app, ["example"])
    assert result.exit_code == 0, result.output
    # StreamHandler targets sys.stdout, so both qlib log lines and _render's table land there.
    assert " INFO qlib." in result.stdout
    assert "annualized_return" in result.stdout


def test_invalid_log_level_errors():
    result = runner.invoke(app, ["--log-level", "TRACE", "--version"])
    assert result.exit_code != 0
