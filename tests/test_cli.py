from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from scopio.cli import cli


def test_cli_help() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "Usage:" in result.output
    for cmd in ["run", "report", "diff", "diff-report", "ci", "clean", "archive", "init"]:
        assert cmd in result.output


def test_cli_version() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert "version" in result.output or "0.1.1" in result.output


def test_cli_run_no_config(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["run", "--config", "/nonexistent/scopio.toml"], standalone_mode=False)
    assert result.exit_code != 0


def test_cli_init_creates_config(tmp_path: Path) -> None:
    runner = CliRunner()
    config_file = tmp_path / "scopio.toml"
    result = runner.invoke(cli, ["--config", str(config_file), "init"])
    assert result.exit_code == 0
    assert "Created:" in result.output
    assert config_file.exists()


def test_cli_init_twice_fails(tmp_path: Path) -> None:
    runner = CliRunner()
    config_file = tmp_path / "scopio.toml"
    runner.invoke(cli, ["--config", str(config_file), "init"])
    result = runner.invoke(cli, ["--config", str(config_file), "init"])
    assert result.exit_code != 0
    assert "already exists" in result.output


def test_cli_report_no_db(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["report", "--project", "test"])
    assert result.exit_code != 0


def test_cli_diff_no_db(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["diff", "--project", "test"])
    assert result.exit_code != 0


def test_cli_diff_report_no_db(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["diff-report", "--project", "test"])
    assert result.exit_code != 0


def test_cli_diff_missing_project_option(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["diff"])
    assert result.exit_code != 0
