from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from scopio.cli import cli
from scopio.diff import render_github_comment


def test_render_github_comment_passed() -> None:
    summary = {
        "project": "my-project",
        "base": {"commit_hash": "abc1234", "loc": 100, "ccn": 3.0, "ccn_max": 5.0, "warnings": 0},
        "latest": {"commit_hash": "def5678", "loc": 110, "ccn": 3.2, "ccn_max": 5.0, "warnings": 0},
        "delta": {"loc": 10, "ccn": 0.2, "warnings": 0},
    }

    markdown = render_github_comment(summary)
    assert "## 🔍 Scopio Audit Summary — my-project" in markdown
    assert "✅ **PASSED**" in markdown
    assert "| **LOC** | 100 | 110 | `+10` |" in markdown


def test_render_github_comment_failed() -> None:
    summary = {
        "project": "my-project",
        "base": {"commit_hash": "abc1234", "loc": 100, "ccn": 3.0, "ccn_max": 5.0, "warnings": 0},
        "latest": {"commit_hash": "def5678", "loc": 150, "ccn": 4.5, "ccn_max": 10.0, "warnings": 0},
        "delta": {"loc": 50, "loc_trend": 0.5, "ccn": 1.5, "ccn_trend": 0.5, "warnings": 0},
    }

    markdown = render_github_comment(summary, thresholds={"ccn_trend": 0.2})
    assert "❌ **FAILED**" in markdown
    assert "### ⚠️ Quality Gate Failures" in markdown


def test_cli_ci_format_github_comment(tmp_path: Path) -> None:
    from scopio.db import open_db

    runner = CliRunner()
    cfg = tmp_path / "scopio.toml"
    cfg.write_text('[discovery]\nprojects = ["my-project"]\n[ci]\nmax_loc_trend_increase = 0.5\n')

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
            "INSERT INTO metrics (project, loc, ccn, ccn_max, warnings, branch, commit_hash) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("my-project", 100, 3.0, 5.0, 0, "main", "abc1234"),
        )
        conn.execute(
            "INSERT INTO metrics (project, loc, ccn, ccn_max, warnings, branch, commit_hash) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("my-project", 120, 3.2, 5.0, 0, "main", "def5678"),
        )

    result = runner.invoke(
        cli, ["--config", str(cfg), "--output-dir", str(tmp_path), "ci", "--format", "github-comment"]
    )
    assert result.exit_code == 0
    assert "Scopio Audit Summary" in result.output
    assert "PASSED" in result.output
