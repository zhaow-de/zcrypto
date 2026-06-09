from typer.testing import CliRunner

from cli.__main__ import app

runner = CliRunner()


def test_bare_data_prints_help_and_exits_zero():
    result = runner.invoke(app, ["data"])
    assert result.exit_code == 0, result.output
    # Help mentions both subcommands (will exist once Tasks 7–8 land);
    # for Task 1, we only assert the group itself appears and exit is 0.
    assert "Usage" in result.output
    assert "data" in result.output.lower()
