import pytest

from agent_backtest import __version__
from agent_backtest.cli import PLANNED_COMMANDS, main


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"agent-backtest {__version__}"


def test_no_args_prints_help_with_planned_commands(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    out = capsys.readouterr().out
    assert "usage: backtest" in out
    for name in PLANNED_COMMANDS:
        assert name in out
