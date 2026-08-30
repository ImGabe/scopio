from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from scopio.cli import cli
from scopio.db import open_db
from scopio.hotspots import compute_hotspots, render_hotspots


def test_compute_hotspots_empty(tmp_path: Path) -> None:
    db_path = tmp_path / "scopio.db"
    assert compute_hotspots(db_path, "proj") == []


def test_compute_and_render_hotspots(tmp_path: Path) -> None:
    db_path = tmp_path / "scopio.db"
    with open_db(db_path) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS metrics ("
            "audit_id INTEGER PRIMARY KEY AUTOINCREMENT, project TEXT, timestamp DATETIME)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS file_metrics ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, audit_id INTEGER, file_path TEXT, nloc INTEGER, "
            "ccn REAL, warnings INTEGER)"
        )
        # Insert audit 1
        conn.execute("INSERT INTO metrics (project) VALUES ('proj-a')")
        audit_id_1 = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO file_metrics (audit_id, file_path, nloc, ccn, warnings) VALUES (?, ?, ?, ?, ?)",
            (audit_id_1, "src/heavy.py", 200, 25.0, 2),
        )
        conn.execute(
            "INSERT INTO file_metrics (audit_id, file_path, nloc, ccn, warnings) VALUES (?, ?, ?, ?, ?)",
            (audit_id_1, "src/light.py", 50, 3.0, 0),
        )

        # Insert audit 2 (churn on heavy.py)
        conn.execute("INSERT INTO metrics (project) VALUES ('proj-a')")
        audit_id_2 = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO file_metrics (audit_id, file_path, nloc, ccn, warnings) VALUES (?, ?, ?, ?, ?)",
            (audit_id_2, "src/heavy.py", 220, 28.0, 3),
        )

    records = compute_hotspots(db_path, "proj-a", limit=10)
    assert len(records) == 2
    assert records[0]["path"] == "src/heavy.py"
    assert records[0]["ccn"] == 28.0
    assert records[0]["changes"] == 2
    assert records[0]["risk_level"] in ("HIGH", "MEDIUM")

    # Formats rendering
    txt = render_hotspots(records, fmt="text")
    assert "Code Hotspots Ranking" in txt
    assert "src/heavy.py" in txt

    js = render_hotspots(records, fmt="json")
    parsed = json.loads(js)
    assert len(parsed) == 2
    assert parsed[0]["path"] == "src/heavy.py"

    csv_data = render_hotspots(records, fmt="csv")
    assert "src/heavy.py" in csv_data

    md = render_hotspots(records, fmt="markdown")
    assert "Code Hotspots Analysis" in md


def test_cli_hotspots_command(tmp_path: Path) -> None:
    runner = CliRunner()
    cfg = tmp_path / "scopio.toml"
    cfg.write_text('[discovery]\nprojects = ["proj-a"]\n', encoding="utf-8")
    db_path = tmp_path / "scopio.db"

    with open_db(db_path) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS metrics (audit_id INTEGER PRIMARY KEY, project TEXT)")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS file_metrics (id INTEGER PRIMARY KEY, audit_id INTEGER, file_path TEXT, nloc INTEGER, ccn REAL, warnings INTEGER)"
        )
        conn.execute("INSERT INTO metrics (audit_id, project) VALUES (1, 'proj-a')")
        conn.execute(
            "INSERT INTO file_metrics (audit_id, file_path, nloc, ccn, warnings) VALUES (1, 'app.py', 100, 15.0, 0)"
        )

    result = runner.invoke(
        cli,
        [
            "--config",
            str(cfg),
            "--output-dir",
            str(tmp_path),
            "hotspots",
            "--project",
            "proj-a",
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 0
    parsed = json.loads(result.output)
    assert parsed[0]["path"] == "app.py"
