from __future__ import annotations

from pathlib import Path

from scopio.db import open_db
from scopio.diff import project_diff


def test_project_diff_dirty(tmp_path: Path) -> None:
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
            ("proj", 100, 3.0, 5.0, 0, "main", "abc123"),
        )

    dirty_metrics = {
        "project": "proj",
        "loc": 120,
        "ccn": 3.5,
        "ccn_max": 6.0,
        "warnings": 1,
        "branch": "main",
        "commit_hash": "working-tree",
    }

    summary = project_diff(db_path, "proj", dirty_metrics=dirty_metrics)
    assert summary["project"] == "proj"
    assert summary["base"]["loc"] == 100
    assert summary["latest"]["loc"] == 120
    assert summary["delta"]["loc"] == 20
    assert summary["delta"]["ccn"] == 0.5
    assert summary["latest"]["dirty"] is True
