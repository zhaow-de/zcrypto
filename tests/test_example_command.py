from typer.testing import CliRunner

from cli.__main__ import app

runner = CliRunner()


def test_example_runs_and_reports_metrics():
    result = runner.invoke(app, ["example"])
    assert result.exit_code == 0, result.output
    assert "annualized_return" in result.output
    assert "Excess vs ETH" in result.output


def test_example_listed_in_help():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "example" in result.output
