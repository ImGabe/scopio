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


def test_ci_command_fail_on_regression_when_loc_increases(seeded_db: Path, tmp_path: Path) -> None:
    """--fail-on-regression should fail when the CI summary reports a failure."""
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
    assert result.exit_code != 0, f"Should fail (LOC increased): {result.output}"
    assert "failed" in result.output.lower()
    assert "LOC increased" in result.output


def test_ci_command_fail_on_regression_when_clean(seeded_db: Path, tmp_path: Path) -> None:
    """--fail-on-regression should pass when there is no CI rule failure."""
    with open_db(seeded_db) as conn:
        conn.execute(
            "INSERT INTO metrics (project, loc, ccn, warnings, branch, commit_hash, runs_count) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("clean-proj", 100, 5.0, 2, "main", "ccc001", 1),
        )
        aid1 = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO metrics_history (audit_id, project, loc, ccn, warnings) VALUES (?, ?, ?, ?, ?)",
            (aid1, "clean-proj", 100, 5.0, 2),
        )
        conn.execute(
            "INSERT INTO metrics (project, loc, ccn, warnings, branch, commit_hash, runs_count) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("clean-proj", 100, 4.0, 1, "main", "ccc002", 1),
        )
        aid2 = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO metrics_history (audit_id, project, loc, ccn, warnings) VALUES (?, ?, ?, ?, ?)",
            (aid2, "clean-proj", 100, 4.0, 1),
        )

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
            "clean-proj",
            "--fail-on-regression",
        ],
    )
    assert result.exit_code == 0, f"Should pass (no regressions): {result.output}"


# ─── Edge cases ────────────────────────────────────────────────────


def test_diff_requires_two_audits(seeded_db: Path, tmp_path: Path) -> None:
    """diff with only 1 audit should fail with clear message."""
    from click.testing import CliRunner

    from scopio.cli import cli
    from scopio.db import open_db

    # Single audit project
    with open_db(seeded_db) as conn:
        conn.execute(
            "INSERT INTO metrics (project, loc, ccn, warnings, branch, commit_hash, runs_count) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("single-proj", 50, 2.0, 0, "main", "aaa001", 1),
        )
        aid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO metrics_history (audit_id, project, loc, ccn, warnings) VALUES (?, ?, ?, ?, ?)",
            (aid, "single-proj", 50, 2.0, 0),
        )

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["--config", str(tmp_path / "scopio.toml"), "--output-dir", str(tmp_path), "diff", "--project", "single-proj"],
    )
    assert result.exit_code != 0
    assert "Not enough history" in result.output


def test_diff_cross_branch(seeded_db: Path, tmp_path: Path) -> None:
    """diff between different branches should still work."""
    from click.testing import CliRunner

    from scopio.cli import cli
    from scopio.db import open_db

    with open_db(seeded_db) as conn:
        conn.execute(
            "INSERT INTO metrics (project, loc, ccn, warnings, branch, commit_hash, runs_count) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("multi-branch", 100, 5.0, 2, "feature/x", "fff001", 1),
        )
        aid1 = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO metrics_history (audit_id, project, loc, ccn, warnings) VALUES (?, ?, ?, ?, ?)",
            (aid1, "multi-branch", 100, 5.0, 2),
        )
        conn.execute(
            "INSERT INTO metrics (project, loc, ccn, warnings, branch, commit_hash, runs_count) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("multi-branch", 120, 3.0, 1, "main", "fff002", 1),
        )
        aid2 = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO metrics_history (audit_id, project, loc, ccn, warnings) VALUES (?, ?, ?, ?, ?)",
            (aid2, "multi-branch", 120, 3.0, 1),
        )

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["--config", str(tmp_path / "scopio.toml"), "--output-dir", str(tmp_path), "diff", "--project", "multi-branch"],
    )
    assert result.exit_code == 0
    assert "multi-branch" in result.output


# ─── _detect_ci_failures unit tests ─────────────────────────────────


def test_ci_failures_ccn_increased() -> None:
    from scopio.diff import _detect_ci_failures

    summary = {
        "base": {"ccn": 1.0, "loc": 100, "warnings": 0},
        "latest": {"ccn": 5.0, "loc": 100, "warnings": 0},
        "delta": {"ccn_trend": 4.0, "loc_trend": 0.0},
    }
    failures = _detect_ci_failures(summary)
    assert any("CCN increased" in f for f in failures)
    assert any("LOC increased" not in f for f in failures)


def test_ci_failures_loc_increased() -> None:
    from scopio.diff import _detect_ci_failures

    summary = {
        "base": {"ccn": 1.0, "loc": 100, "warnings": 0},
        "latest": {"ccn": 1.0, "loc": 200, "warnings": 0},
        "delta": {"ccn_trend": 0.0, "loc_trend": 1.0},
    }
    failures = _detect_ci_failures(summary)
    assert any("LOC increased" in f for f in failures)


def test_ci_failures_warnings_increased() -> None:
    from scopio.diff import _detect_ci_failures

    summary = {
        "base": {"ccn": 1.0, "loc": 100, "warnings": 2},
        "latest": {"ccn": 1.0, "loc": 100, "warnings": 5},
        "delta": {"ccn_trend": 0.0, "loc_trend": 0.0},
    }
    failures = _detect_ci_failures(summary)
    assert any("Warnings increased" in f for f in failures)


def test_ci_failures_ccn_regressed() -> None:
    from scopio.diff import _detect_ci_failures

    summary = {
        "base": {"ccn": 3.0, "loc": 100, "warnings": 0},
        "latest": {"ccn": 5.0, "loc": 100, "warnings": 0},
        "delta": {"ccn_trend": 0.67, "loc_trend": 0.0},
    }
    failures = _detect_ci_failures(summary)
    assert any("CCN regressed" in f for f in failures)


def test_ci_failures_loc_decreased() -> None:
    from scopio.diff import _detect_ci_failures

    summary = {
        "base": {"ccn": 1.0, "loc": 200, "warnings": 0},
        "latest": {"ccn": 1.0, "loc": 100, "warnings": 0},
        "delta": {"ccn_trend": 0.0, "loc_trend": -0.5},
    }
    failures = _detect_ci_failures(summary)
    assert any("LOC decreased" in f for f in failures)


def test_ci_failures_all_clear() -> None:
    from scopio.diff import _detect_ci_failures

    summary = {
        "base": {"ccn": 5.0, "loc": 100, "warnings": 2},
        "latest": {"ccn": 3.0, "loc": 100, "warnings": 1},
        "delta": {"ccn_trend": -0.4, "loc_trend": 0.0},
    }
    failures = _detect_ci_failures(summary)
    assert len(failures) == 0


# ─── Render function tests ───────────────────────────────────────────


def test_render_markdown_empty() -> None:
    """render_markdown with empty summary should not crash."""
    from scopio.diff import render_markdown

    summary = {
        "project": "test-proj",
        "base": {"timestamp": "now", "branch": "main", "commit_hash": "abc", "loc": 100, "ccn": 5.0, "warnings": 2},
        "latest": {"timestamp": "now", "branch": "main", "commit_hash": "def", "loc": 100, "ccn": 5.0, "warnings": 2},
        "delta": {"loc": 0, "loc_trend": None, "ccn": 0.0, "ccn_trend": None, "warnings": 0},
    }
    result = render_markdown(summary)
    assert isinstance(result, str)
    assert len(result) > 0
    assert "test-proj" in result


def test_render_markdown_with_improvement() -> None:
    """render_markdown with improvement trends."""
    from scopio.diff import render_markdown

    summary = {
        "project": "test-proj",
        "base": {"timestamp": "old", "branch": "main", "commit_hash": "abc", "loc": 200, "ccn": 5.0, "warnings": 3},
        "latest": {"timestamp": "new", "branch": "main", "commit_hash": "def", "loc": 150, "ccn": 3.0, "warnings": 1},
        "delta": {"loc": -50, "loc_trend": -0.25, "ccn": -2.0, "ccn_trend": -0.4, "warnings": -2},
    }
    result = render_markdown(summary)
    assert isinstance(result, str)
    assert "-50" in result or "-2.0" in result


def test_render_ci_summary_failed() -> None:
    """render_ci_summary with regression should show failures."""
    from scopio.diff import render_ci_summary

    summary = {
        "project": "reg-proj",
        "base": {"timestamp": "old", "branch": "main", "commit_hash": "abc", "loc": 100, "ccn": 2.0, "warnings": 0},
        "latest": {"timestamp": "new", "branch": "main", "commit_hash": "def", "loc": 100, "ccn": 5.0, "warnings": 0},
        "delta": {"loc": 0, "loc_trend": 0.0, "ccn": 3.0, "ccn_trend": 1.5, "warnings": 0},
    }
    result = render_ci_summary(summary)
    assert isinstance(result, str)
    assert "reg-proj" in result
    assert "failed" in result.lower() or "CCN" in result


def test_render_ci_summary_passed() -> None:
    """render_ci_summary with improvement should show passed."""
    from scopio.diff import render_ci_summary

    summary = {
        "project": "ok-proj",
        "base": {"timestamp": "old", "branch": "main", "commit_hash": "abc", "loc": 100, "ccn": 5.0, "warnings": 2},
        "latest": {"timestamp": "new", "branch": "main", "commit_hash": "def", "loc": 100, "ccn": 3.0, "warnings": 1},
        "delta": {"loc": 0, "loc_trend": 0.0, "ccn": -2.0, "ccn_trend": -0.4, "warnings": -1},
    }
    result = render_ci_summary(summary)
    assert isinstance(result, str)
    assert "passed" in result.lower()


def test_render_file_markdown_empty() -> None:
    """render_file_markdown with empty files should not crash."""
    from scopio.diff import render_file_markdown

    summary = {
        "project": "test-proj",
        "base": {"timestamp": "now", "branch": "main", "commit_hash": "abc", "loc": 100, "ccn": 5.0, "warnings": 2},
        "latest": {"timestamp": "now", "branch": "main", "commit_hash": "def", "loc": 100, "ccn": 5.0, "warnings": 2},
        "threshold_ccn": None,
        "files": [],
        "summary": {
            "total_files": 0,
            "added_files": 0,
            "removed_files": 0,
            "changed_files": 0,
            "over_threshold_files": 0,
        },
    }
    result = render_file_markdown(summary)
    assert isinstance(result, str)


def test_render_diff_delta_all_none() -> None:
    """_render_diff_delta with None values should not crash."""
    from scopio.diff import render_markdown

    summary = {
        "project": "test-proj",
        "base": {"timestamp": None, "branch": None, "commit_hash": None, "loc": 100, "ccn": 5.0, "warnings": 2},
        "latest": {"timestamp": None, "branch": None, "commit_hash": None, "loc": 100, "ccn": 5.0, "warnings": 2},
        "delta": {"loc": 0, "loc_trend": None, "ccn": 0.0, "ccn_trend": None, "warnings": 0},
    }
    result = render_markdown(summary)
    assert isinstance(result, str)
