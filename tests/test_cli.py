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


def test_cli_clean_no_db(tmp_path: Path) -> None:
    """clean with no database should just print a message."""
    runner = CliRunner()
    result = runner.invoke(cli, ["--config", str(tmp_path / "scopio.toml"),
                                 "--output-dir", str(tmp_path), "clean", "--keep", "5"])
    assert result.exit_code == 0, f"clean failed: {result.output}"
    assert "Nothing to clean" in result.output


def test_cli_archive_json_format(tmp_path: Path) -> None:
    """archive with --format json should work."""
    from scopio.db import open_db

    runner = CliRunner()
    result = runner.invoke(cli, ["--config", str(tmp_path / "scopio.toml"), "--output-dir", str(tmp_path), "init"])
    assert result.exit_code == 0

    db_path = tmp_path / "scopio.db"
    with open_db(db_path) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS metrics ("
            "audit_id INTEGER PRIMARY KEY AUTOINCREMENT, project TEXT, language TEXT, "
            "files INTEGER, loc INTEGER, code INTEGER, nloc INTEGER, "
            "ccn REAL, warnings INTEGER, commits INTEGER, last_commit_date TEXT, "
            "author TEXT, branch TEXT, dirty INTEGER, commit_hash TEXT, "
            "tool_versions TEXT, duration_seconds REAL, runs_count INTEGER DEFAULT 1, "
            "timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)"
        )
        conn.execute(
            "INSERT INTO metrics (project, loc, ccn, warnings, branch, commit_hash) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("test-proj", 100, 3.0, 0, "main", "abc123"),
        )

    result = runner.invoke(cli, [
        "--config", str(tmp_path / "scopio.toml"),
        "--output-dir", str(tmp_path),
        "archive", "--format", "json"
    ])
    assert result.exit_code == 0
    assert "Archived" in result.output


def test_cli_archive_parquet_fallback(tmp_path: Path) -> None:
    """archive with --format parquet should show error if pandas not installed."""
    from scopio.db import open_db

    runner = CliRunner()
    result = runner.invoke(cli, ["--config", str(tmp_path / "scopio.toml"), "--output-dir", str(tmp_path), "init"])
    assert result.exit_code == 0

    db_path = tmp_path / "scopio.db"
    with open_db(db_path) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS metrics ("
            "audit_id INTEGER PRIMARY KEY AUTOINCREMENT, project TEXT, language TEXT, "
            "files INTEGER, loc INTEGER, code INTEGER, nloc INTEGER, "
            "ccn REAL, warnings INTEGER, commits INTEGER, last_commit_date TEXT, "
            "author TEXT, branch TEXT, dirty INTEGER, commit_hash TEXT, "
            "tool_versions TEXT, duration_seconds REAL, runs_count INTEGER DEFAULT 1, "
            "timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)"
        )
        conn.execute(
            "INSERT INTO metrics (project, loc, ccn, warnings, branch, commit_hash) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("test-proj", 100, 3.0, 0, "main", "abc123"),
        )

    result = runner.invoke(cli, [
        "--config", str(tmp_path / "scopio.toml"),
        "--output-dir", str(tmp_path),
        "archive", "--format", "parquet"
    ])
    # Should fail gracefully with ClickException (pandas not available)
    assert result.exit_code != 0
    assert "pandas" in result.output.lower() or "Parquet" in result.output
