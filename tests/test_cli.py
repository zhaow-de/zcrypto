from importlib.metadata import version

from typer.testing import CliRunner

from cli.__main__ import app

runner = CliRunner()


def test_version_prints_name_and_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.output.strip() == f"zcrypto v{version('zcrypto')} (with pyqlib-{version('pyqlib')})"


def test_no_args_prints_help():
    result = runner.invoke(app, [])
    assert result.exit_code == 0
    assert "Usage" in result.output


def test_help_flag_prints_help():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Usage" in result.output


def test_short_version_flag():
    result = runner.invoke(app, ["-v"])
    assert result.exit_code == 0
    assert result.output.strip() == f"zcrypto v{version('zcrypto')} (with pyqlib-{version('pyqlib')})"


def test_short_help_flag():
    result = runner.invoke(app, ["-h"])
    assert result.exit_code == 0
    assert "Usage" in result.output
