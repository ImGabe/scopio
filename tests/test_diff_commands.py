from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from scopio.cli import cli
from scopio.db import open_db


@pytest.fixture
def seeded_db(tmp_path: Path) -> Path:
    """Create a scopio.toml + .scopio/ with seeded metrics (2 audits)."""
    runner = CliRunner()
    result = runner.invoke(cli, ["--config", str(tmp_path / "scopio.toml"), "--output-dir", str(tmp_path), "init"])
    assert result.exit_code == 0

    db_path = tmp_path / "scopio.db"
    with open_db(db_path) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS metrics ("
            "audit_id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "project TEXT, language TEXT, files INTEGER, loc INTEGER, code INTEGER, "
            "nloc INTEGER, ccn REAL, warnings INTEGER, commits INTEGER, "
            "last_commit_date TEXT, author TEXT, branch TEXT, dirty INTEGER, "
            "commit_hash TEXT, tool_versions TEXT, duration_seconds REAL, "
            "runs_count INTEGER DEFAULT 1, "
            "timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS metrics_history ("
            "audit_id INTEGER, project TEXT, language TEXT, "
            "timestamp DATETIME, loc INTEGER, ccn REAL, warnings INTEGER, "
            "FOREIGN KEY(audit_id) REFERENCES metrics(audit_id))"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS file_metrics ("
            "file_metric_id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "audit_id INTEGER, project TEXT, path TEXT, "
            "nloc INTEGER, ccn REAL, warnings INTEGER, "
            "FOREIGN KEY(audit_id) REFERENCES metrics(audit_id))"
        )
        # First audit: high CCN (regression scenario)
        conn.execute(
            "INSERT INTO metrics (project, loc, ccn, warnings, branch, commit_hash, runs_count) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("proj1", 100, 5.0, 2, "main", "abc001", 1),
        )
        aid1 = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO metrics_history (audit_id, project, loc, ccn, warnings) VALUES (?, ?, ?, ?, ?)",
            (aid1, "proj1", 100, 5.0, 2),
        )
        conn.execute(
            "INSERT INTO file_metrics (audit_id, project, path, nloc, ccn, warnings) VALUES (?, ?, ?, ?, ?, ?)",
            (aid1, "proj1", "main.py", 50, 4.0, 1),
        )
        conn.execute(
            "INSERT INTO file_metrics (audit_id, project, path, nloc, ccn, warnings) VALUES (?, ?, ?, ?, ?, ?)",
            (aid1, "proj1", "utils.py", 50, 6.0, 1),
        )

        # Second audit: lower CCN (improvement)
        conn.execute(
            "INSERT INTO metrics (project, loc, ccn, warnings, branch, commit_hash, runs_count) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("proj1", 120, 3.0, 1, "main", "abc002", 1),
        )
        aid2 = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO metrics_history (audit_id, project, loc, ccn, warnings) VALUES (?, ?, ?, ?, ?)",
            (aid2, "proj1", 120, 3.0, 1),
        )
        conn.execute(
            "INSERT INTO file_metrics (audit_id, project, path, nloc, ccn, warnings) VALUES (?, ?, ?, ?, ?, ?)",
            (aid2, "proj1", "main.py", 70, 2.0, 0),
        )
        conn.execute(
            "INSERT INTO file_metrics (audit_id, project, path, nloc, ccn, warnings) VALUES (?, ?, ?, ?, ?, ?)",
            (aid2, "proj1", "utils.py", 50, 4.0, 1),
        )

    return db_path


def test_diff_command_output(seeded_db: Path, tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli, ["--config", str(tmp_path / "scopio.toml"), "--output-dir", str(tmp_path), "diff", "--project", "proj1"]
    )
    assert result.exit_code == 0
    assert "proj1" in result.output
    assert "5.0" in result.output  # base CCN
    assert "3.0" in result.output  # latest CCN
    assert "-2.00" in result.output  # delta


def test_diff_report_command_text(seeded_db: Path, tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["--config", str(tmp_path / "scopio.toml"), "--output-dir", str(tmp_path), "diff-report", "--project", "proj1"],
    )
    assert result.exit_code == 0
    assert "proj1" in result.output
    assert "Base" in result.output


def test_diff_report_command_json(seeded_db: Path, tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "--config",
            str(tmp_path / "scopio.toml"),
            "--output-dir",
            str(tmp_path),
            "diff-report",
            "--project",
            "proj1",
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 0
    assert "{" in result.output
    assert "proj1" in result.output


def test_diff_report_command_files(seeded_db: Path, tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "--config",
            str(tmp_path / "scopio.toml"),
            "--output-dir",
            str(tmp_path),
            "diff-report",
            "--project",
            "proj1",
            "--files",
            "--threshold-ccn",
            "5",
        ],
    )
    assert result.exit_code == 0
    assert "Monitored files" in result.output
    assert "Changed" in result.output
    assert "Above" in result.output


def test_ci_command_success(seeded_db: Path, tmp_path: Path) -> None:
    """Improvement (CCN 5.0 -> 3.0) should pass."""
    runner = CliRunner()
    result = runner.invoke(
        cli, ["--config", str(tmp_path / "scopio.toml"), "--output-dir", str(tmp_path), "ci", "--project", "proj1"]
    )
    assert result.exit_code == 0
    assert "proj1" in result.output


def test_ci_command_fail_on_regression(seeded_db: Path, tmp_path: Path) -> None:
    """With --fail-on-regression but CCN improved, should pass."""
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "--config",
            str(tmp_path / "scopio.toml"),
            "--output-dir",
            str(tmp_path),
            "ci",
            "--project",
            "proj1",
            "--fail-on-regression",
        ],
    )
    assert result.exit_code == 0, f"Should pass (CCN improved): {result.output}"
    assert "regression" not in result.output.lower()
