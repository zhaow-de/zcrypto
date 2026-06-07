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
    # stdout must still carry _render's metrics table
    assert "annualized_return" in result.output
    assert "Excess vs ETH" in result.output
    # file must be JSONL with the documented field set
    lines = [ln for ln in log.read_text().splitlines() if ln.strip()]
    assert lines, "log file is empty"
    parsed = [json.loads(ln) for ln in lines]
    for obj in parsed:
        assert set(obj.keys()) >= {"ts", "level", "logger", "file", "line", "message"}
        assert "pid" not in obj and "thread" not in obj
    assert any(obj["logger"].startswith("qlib.") for obj in parsed), "no qlib record captured"


def test_no_log_flag_emits_plain_text_lines_on_stdout():
    result = runner.invoke(app, ["example"])
    assert result.exit_code == 0, result.output
    # at least one qlib INFO and the _render metrics table both land on stdout
    assert " INFO qlib." in result.output
    assert "annualized_return" in result.output


def test_invalid_log_level_errors():
    result = runner.invoke(app, ["--log-level", "TRACE", "--version"])
    assert result.exit_code != 0
