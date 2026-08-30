from __future__ import annotations

from pathlib import Path

import pytest
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
    result = runner.invoke(
        cli, ["--config", str(tmp_path / "scopio.toml"), "--output-dir", str(tmp_path), "clean", "--keep", "5"]
    )
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
            "ccn REAL, ccn_max REAL, warnings INTEGER, commits INTEGER, last_commit_date TEXT, "
            "author TEXT, branch TEXT, dirty INTEGER, commit_hash TEXT, "
            "tool_versions TEXT, duration_seconds REAL, runs_count INTEGER DEFAULT 1, "
            "timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)"
        )
        conn.execute(
            "INSERT INTO metrics (project, loc, ccn, warnings, branch, commit_hash) VALUES (?, ?, ?, ?, ?, ?)",
            ("test-proj", 100, 3.0, 0, "main", "abc123"),
        )

    result = runner.invoke(
        cli, ["--config", str(tmp_path / "scopio.toml"), "--output-dir", str(tmp_path), "archive", "--format", "json"]
    )
    assert result.exit_code == 0
    assert "Archived" in result.output


def test_cli_archive_parquet_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """archive with --format parquet should show error if pandas not installed."""
    import sys

    monkeypatch.setitem(sys.modules, "pandas", None)
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
            "ccn REAL, ccn_max REAL, warnings INTEGER, commits INTEGER, last_commit_date TEXT, "
            "author TEXT, branch TEXT, dirty INTEGER, commit_hash TEXT, "
            "tool_versions TEXT, duration_seconds REAL, runs_count INTEGER DEFAULT 1, "
            "timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)"
        )
        conn.execute(
            "INSERT INTO metrics (project, loc, ccn, warnings, branch, commit_hash) VALUES (?, ?, ?, ?, ?, ?)",
            ("test-proj", 100, 3.0, 0, "main", "abc123"),
        )

    result = runner.invoke(
        cli,
        ["--config", str(tmp_path / "scopio.toml"), "--output-dir", str(tmp_path), "archive", "--format", "parquet"],
    )
    # Should fail gracefully with ClickException (pandas not available)
    assert result.exit_code != 0
    assert "pandas" in result.output.lower() or "Parquet" in result.output


def test_cli_doctor() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["doctor"])
    assert result.exit_code == 0
    assert "Scopio Doctor" in result.output
    assert "Python:" in result.output


def test_cli_resolve_project_auto(tmp_path: Path) -> None:
    """When --project is omitted and scopio.toml has 1 project, resolve it automatically."""
    from scopio.db import open_db

    runner = CliRunner()
    cfg = tmp_path / "scopio.toml"
    cfg.write_text('[discovery]\nprojects = ["my-single-proj"]\n')

    db_path = tmp_path / "scopio.db"
    with open_db(db_path) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS metrics ("
            "audit_id INTEGER PRIMARY KEY AUTOINCREMENT, project TEXT, language TEXT, "
            "files INTEGER, loc INTEGER, code INTEGER, nloc INTEGER, "
            "ccn REAL, ccn_max REAL, warnings INTEGER, commits INTEGER, last_commit_date TEXT, "
            "author TEXT, branch TEXT, dirty INTEGER, commit_hash TEXT, "
            "tool_versions TEXT, duration_seconds REAL, runs_count INTEGER DEFAULT 1, "
            "timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)"
        )
        conn.execute(
            "INSERT INTO metrics (project, loc, ccn, warnings, branch, commit_hash) VALUES (?, ?, ?, ?, ?, ?)",
            ("my-single-proj", 100, 3.0, 0, "main", "abc123"),
        )

    # Invoke report without --project
    result = runner.invoke(cli, ["--config", str(cfg), "--output-dir", str(tmp_path), "report"])
    assert result.exit_code == 0
    assert "main" in result.output


def test_cli_diff_dirty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from scopio.db import open_db

    runner = CliRunner()
    cfg = tmp_path / "scopio.toml"
    cfg.write_text('[discovery]\nprojects = ["my-single-proj"]\n')

    db_path = tmp_path / "scopio.db"
    with open_db(db_path) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS metrics ("
            "audit_id INTEGER PRIMARY KEY AUTOINCREMENT, project TEXT, language TEXT, "
            "files INTEGER, loc INTEGER, code INTEGER, nloc INTEGER, "
            "ccn REAL, ccn_max REAL, warnings INTEGER, commits INTEGER, last_commit_date TEXT, "
            "author TEXT, branch TEXT, dirty INTEGER, commit_hash TEXT, "
            "tool_versions TEXT, duration_seconds REAL, runs_count INTEGER DEFAULT 1, "
            "timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)"
        )
        conn.execute(
            "INSERT INTO metrics (project, loc, ccn, warnings, branch, commit_hash) VALUES (?, ?, ?, ?, ?, ?)",
            ("my-single-proj", 100, 3.0, 0, "main", "abc123"),
        )

    # Patch _audit_project on MetricsAuditor to return dirty working-tree metrics
    def fake_audit(self, target):
        return {
            "project": target,
            "language": "Python",
            "files": 2,
            "loc": 150,
            "code": 100,
            "nloc": 80,
            "ccn": 4.0,
            "ccn_max": 7.0,
            "warnings": 0,
            "commits": 5,
            "last_commit_date": "now",
            "author": "a",
            "branch": "main",
            "dirty": 1,
            "commit_hash": "working-tree",
            "tool_versions": "{}",
            "duration_seconds": 0.1,
            "file_metrics": [],
        }

    monkeypatch.setattr("scopio.audit.MetricsAuditor._audit_project", fake_audit)

    result = runner.invoke(cli, ["--config", str(cfg), "--output-dir", str(tmp_path), "diff", "--dirty"])
    assert result.exit_code == 0
    assert "LOC  : 100 -> 150 (+50)" in result.output
