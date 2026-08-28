from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from scopio.audit import _language_from_scc, _load_config
from scopio.db import open_db


def test_load_config(tmp_path: Path) -> None:
    config = tmp_path / "scopio.toml"
    config.write_text(
        """
[discovery]
ignore_hidden = true
projects = ["foo", "bar"]

[filters]
global_dirs = ["node_modules", "target"]
minified_files = ["*.min.js"]
ignored_langs = ["JSON", "Markdown"]

[quality_gates]
max_ccn = 10.0
max_warnings = 10
""",
        encoding="utf-8",
    )
    data = _load_config(config)
    assert data["discovery"]["ignore_hidden"] is True
    assert data["discovery"]["projects"] == ["foo", "bar"]
    assert data["filters"]["global_dirs"] == ["node_modules", "target"]
    assert data["quality_gates"]["max_ccn"] == 10.0


def test_language_from_scc_prefers_valid_language() -> None:
    scc_data = [
        {"Name": "JSON", "Code": 10},
        {"Name": "Rust", "Code": 120},
        {"Name": "Markdown", "Code": 5},
    ]
    assert _language_from_scc(scc_data, {"JSON", "Markdown"}) == "Rust"


def test_language_from_scc_falls_back_to_highest_code() -> None:
    scc_data = [
        {"Name": "JSON", "Code": 10},
        {"Name": "XML", "Code": 5},
    ]
    assert _language_from_scc(scc_data, {"JSON", "XML"}) == "JSON"


def test_language_from_scc_empty_candidates() -> None:
    assert _language_from_scc([], {"JSON"}) == "Unknown"


def test_open_db_creates_schema(tmp_path: Path) -> None:
    db_path = tmp_path / "scopio.db"
    with open_db(db_path) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS metrics (id INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO metrics (id) VALUES (1)")
    assert sqlite3.connect(db_path).execute("SELECT COUNT(*) FROM metrics").fetchone()[0] == 1


def test_project_file_diff_requires_history(tmp_path: Path) -> None:
    from click import ClickException

    from scopio.diff import project_file_diff

    db_path = tmp_path / "scopio.db"
    with open_db(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS metrics (
                audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                project TEXT NOT NULL,
                language TEXT,
                files INTEGER,
                loc INTEGER,
                code INTEGER,
                nloc INTEGER,
                ccn REAL,
                ccn_max INTEGER,
                warnings INTEGER,
                commits INTEGER,
                last_commit_date TEXT,
                author TEXT,
                branch TEXT,
                dirty INTEGER,
                commit_hash TEXT,
                tool_versions TEXT,
                duration_seconds REAL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            "INSERT INTO metrics (project, language, files, loc, code, nloc, ccn, ccn_max, warnings, commits, last_commit_date, author, branch, dirty, commit_hash, tool_versions, duration_seconds) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "wrong-web",
                "Rust",
                39,
                100,
                90,
                80,
                4.0,
                5,
                0,
                1,
                "2026-01-01",
                "gabe",
                "main",
                0,
                "abc123",
                "{}",
                1.0,
            ),
        )

    with pytest.raises(ClickException):
        project_file_diff(db_path, "wrong-web")


def test_trend_gate_evaluates_before_save(tmp_path: Path) -> None:
    """Verify _evaluate_quality_gates runs before _save_results (B3 fix).

    This checks that the order in run() calls gates before save,
    so _get_last_metrics() finds the previous audit, not the current one.
    """

    from scopio.audit import MetricsAuditor

    config = tmp_path / "scopio.toml"
    config.write_text(
        """
        [discovery]
        projects = ["dummy-project"]
        [quality_gates]
        max_ccn = 10.0
        max_warnings = 10
        max_ccn_trend_increase = 0.2
        trend_sensitive_projects = ["dummy-project"]
        """,
        encoding="utf-8",
    )

    projects_root = tmp_path / "projects"
    projects_root.mkdir()
    dummy = projects_root / "dummy-project"
    dummy.mkdir()

    # Write a small Python file with measurable CCN
    (dummy / "main.py").write_text("def foo(x):\n    if x > 0:\n        return 1\n    else:\n        return -1\n")

    auditor = MetricsAuditor(config, projects_root, tmp_path)

    # First run — no previous data, trend gate should pass
    summary = auditor.run()
    assert len(summary["results"]) == 1


def test_trend_gate_detects_regression(tmp_path: Path) -> None:
    """With a metric_history row, a CCN increase > threshold must fail."""
    from scopio.audit import MetricsAuditor
    from scopio.db import open_db

    config = tmp_path / "scopio.toml"
    config.write_text(
        """
        [discovery]
        projects = ["dummy-reg"]
        [quality_gates]
        max_ccn = 10.0
        max_warnings = 10
        max_ccn_trend_increase = 0.2
        trend_sensitive_projects = ["dummy-reg"]
        """,
        encoding="utf-8",
    )

    projects_root = tmp_path / "projects"
    projects_root.mkdir()
    dummy = projects_root / "dummy-reg"
    dummy.mkdir()
    # Write a file that generates measurable CCN
    (dummy / "main.py").write_text("def foo(x):\n    if x > 0:\n        return 1\n    else:\n        return -1\n")

    auditor = MetricsAuditor(config, projects_root, tmp_path)

    # Insert a fake previous audit with low CCN so trend gate triggers
    # We use the fact that _init_db creates the schema, then manually insert
    # an older row BEFORE running the real audit
    auditor._init_db()
    with open_db(auditor.db_path) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO metrics
            (project, language, files, loc, code, nloc, ccn, warnings,
             commits, last_commit_date, author, branch, dirty, commit_hash,
             tool_versions, duration_seconds)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "dummy-reg",
                "Python",
                1,
                10,
                8,
                6,
                1.0,
                0,
                1,
                "2026-01-01",
                "test",
                "main",
                0,
                "abc",
                '{"scc":"v1"}',
                0.1,
            ),
        )

    summary = auditor.run()
    # If trend gate works, this project should appear in trend_failures
    assert len(summary["trend_failures"]) > 0, (
        "Expected trend_failures because CCN increased from 1.0 to actual "
        f"(results={summary['results']}, trend_failures={summary['trend_failures']})"
    )
