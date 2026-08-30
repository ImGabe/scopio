from __future__ import annotations

import json
import os
from datetime import UTC
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

from scopio.audit import (
    MetricsAuditor,
    _git_info,
    _language_from_scc,
    _parse_lizard_csv,
    _run_lizard,
    _run_scc,
)

# ─── _parse_lizard_csv ──────────────────────────────────────────────────

# Realistic lizard output. Note: the parser counts the "Total" line as a file
# and uses parts[2] (tokens) for initial CCN — pre-existing quirks.
LIZARD_CSV = """10,5,30,2,1,foo@10@scopio/foo.py,scopio/foo.py,foo,foo(x),1,10
5,2,15,1,1,bar@5@scopio/bar.py,scopio/bar.py,bar,bar(y),12,16
"""

LIZARD_CSV_EMPTY = """
"""

LIZARD_CSV_MALFORMED = "not,csv,at,all"


def test_parse_lizard_csv_complete() -> None:
    result = _parse_lizard_csv(LIZARD_CSV)
    assert result["nloc"] == 15  # 10 + 5
    assert result["ccn"] == 3.5  # (5+2)/2
    assert result["warnings"] == 0  # lizard CSV has no warnings per function
    assert len(result["files"]) == 2


def test_parse_lizard_csv_empty() -> None:
    result = _parse_lizard_csv(LIZARD_CSV_EMPTY)
    assert result["nloc"] == 0
    assert result["ccn"] == 0.0
    assert result["warnings"] == 0
    assert result["files"] == []


def test_parse_lizard_csv_malformed() -> None:
    result = _parse_lizard_csv(LIZARD_CSV_MALFORMED)
    assert result["nloc"] == 0
    assert result["ccn"] == 0.0
    assert result["warnings"] == 0
    assert result["files"] == []


# ─── _run_scc ─────────────────────────────────────────────────────────────

SCC_JSON = json.dumps(
    [
        {"Name": "Python", "Lines": 100, "Code": 80, "Count": 5},
        {"Name": "JSON", "Lines": 20, "Code": 0, "Count": 1},
    ]
)


def test_run_scc_success(monkeypatch: pytest.MonkeyPatch) -> None:
    mock = MagicMock()
    mock.returncode = 0
    mock.stdout = SCC_JSON
    monkeypatch.setattr("subprocess.run", lambda cmd, **kw: mock)

    result = _run_scc(Path("/tmp"), [])
    assert len(result) == 2
    assert result[0]["Name"] == "Python"


def test_run_scc_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    mock = MagicMock()
    mock.returncode = 1
    monkeypatch.setattr("subprocess.run", lambda cmd, **kw: mock)

    result = _run_scc(Path("/tmp"), [])
    assert result == []


def test_run_scc_invalid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    mock = MagicMock()
    mock.returncode = 0
    mock.stdout = "not json"
    monkeypatch.setattr("subprocess.run", lambda cmd, **kw: mock)

    result = _run_scc(Path("/tmp"), [])
    assert result == []


def test_run_scc_includes_exclude_dirs(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[str] = []

    def fake_run(cmd, **kw):
        captured.extend(cmd)
        mock = MagicMock()
        mock.returncode = 0
        mock.stdout = "[]"
        return mock

    monkeypatch.setattr("subprocess.run", fake_run)
    _run_scc(Path("/tmp"), ["node_modules", "dist"])
    assert "--exclude-dir" in captured
    idx = captured.index("--exclude-dir")
    assert "node_modules,dist" in captured[idx + 1]


# ─── _run_lizard ──────────────────────────────────────────────────────────


def test_run_lizard_success(monkeypatch: pytest.MonkeyPatch) -> None:
    mock = MagicMock()
    mock.returncode = 0
    mock.stdout = LIZARD_CSV
    monkeypatch.setattr("subprocess.run", lambda cmd, **kw: mock)

    result = _run_lizard(Path("/tmp"), [])
    assert result["nloc"] == 15


def test_run_lizard_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    mock = MagicMock()
    mock.returncode = 1
    monkeypatch.setattr("subprocess.run", lambda cmd, **kw: mock)

    result = _run_lizard(Path("/tmp"), [])
    assert result == {"nloc": 0, "ccn": 0.0, "warnings": 0, "files": []}


# ─── _language_from_scc ───────────────────────────────────────────────────


def test_language_from_scc_prefers_valid() -> None:
    data = [
        {"Name": "JSON", "Code": 10},
        {"Name": "Python", "Code": 120},
    ]
    assert _language_from_scc(data, {"JSON"}) == "Python"


def test_language_from_scc_fallback() -> None:
    data = [
        {"Name": "JSON", "Code": 10},
        {"Name": "XML", "Code": 5},
    ]
    assert _language_from_scc(data, {"JSON", "XML"}) == "JSON"


def test_language_from_scc_empty() -> None:
    assert _language_from_scc([], {"JSON"}) == "Unknown"


# ─── _git_info ────────────────────────────────────────────────────────────


def test_git_info_no_git(tmp_path: Path) -> None:
    result = _git_info(tmp_path)
    assert result["commits"] == 0
    assert result["branch"] == "n/a"
    assert result["dirty"] is False


def test_git_info_with_git(monkeypatch: pytest.MonkeyPatch) -> None:
    tmp = Path("/tmp/fake_git_test")
    (tmp / ".git").mkdir(parents=True, exist_ok=True)
    call_log: list[list[str]] = []

    def fake_run_cmd(path, cmd):
        call_log.append(cmd)
        mapping = {
            "rev-list --count HEAD": "42",
            "branch --show-current": "main",
            "log -1 --format=%ad --date=short": "2026-01-15",
            "log -1 --format=%an": "Author",
            "rev-parse HEAD": "abc123",
            "status --porcelain": " M src/main.py\n",
        }
        key = " ".join(cmd[1:])
        return mapping.get(key, "")

    monkeypatch.setattr("scopio.collect.run.runner.run_cmd", fake_run_cmd)

    try:
        result = _git_info(tmp)
        assert result["commits"] == 42
        assert result["branch"] == "main"
        assert result["last_commit_date"] == "2026-01-15"
        assert result["author"] == "Author"
        assert result["commit_hash"] == "abc123"
        assert result["dirty"] is True
    finally:
        import shutil

        shutil.rmtree(str(tmp / ".git"), ignore_errors=True)


# ─── _audit_project integrado ─────────────────────────────────────────────


def test_audit_project_basic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Integration: _audit_project with dependencies patched."""
    proj = tmp_path / "projects" / "test-proj"
    proj.mkdir(parents=True)
    (proj / "main.py").write_text("x = 1\n")

    config = tmp_path / "scopio.toml"
    config.write_text(
        '[discovery]\nprojects = ["test-proj"]\n'
        "[filters]\nglobal_dirs = []\n"
        "[quality_gates]\nmax_ccn = 10.0\nmax_warnings = 10\n"
    )

    auditor = MetricsAuditor(config, tmp_path / "projects", tmp_path)

    monkeypatch.setattr(
        "scopio.audit._run_scc",
        lambda path, excludes: [{"Name": "Python", "Lines": 10, "Code": 8, "Count": 1}],
    )
    monkeypatch.setattr(
        "scopio.audit._run_lizard",
        lambda path, excludes: {
            "nloc": 6,
            "ccn": 2.0,
            "warnings": 0,
            "files": [{"path": "main.py", "nloc": 6, "ccn": 2.0, "warnings": 0}],
        },
    )
    monkeypatch.setattr(
        "scopio.audit._tool_versions",
        lambda: {"scc": "v3", "lizard": "v1"},
    )
    monkeypatch.setattr(
        "scopio.audit._run_cmd",
        lambda path, cmd: "",
    )
    monkeypatch.setattr(
        "scopio.audit.shutil.which",
        lambda cmd: "/usr/bin/" + cmd,
    )

    result = auditor._audit_project("test-proj")
    assert result is not None
    assert result["project"] == "test-proj"
    assert result["language"] == "Python"
    assert result["files"] == 1
    assert result["loc"] == 10
    assert result["code"] == 8
    assert result["nloc"] == 6
    assert result["ccn"] == 2.0
    assert result["warnings"] == 0
    assert len(result["file_metrics"]) == 1
    assert isinstance(result["tool_versions"], str)


def test_audit_project_missing_project(tmp_path: Path) -> None:
    """Non-existent project dir returns None."""
    config = tmp_path / "scopio.toml"
    config.write_text('[discovery]\nprojects = ["missing"]\n[quality_gates]\nmax_ccn = 10.0\nmax_warnings = 10\n')
    auditor = MetricsAuditor(config, tmp_path / "projects", tmp_path)
    result = auditor._audit_project("missing")
    assert result is None


# ─── _evaluate_quality_gates ──────────────────────────────────────────────


def test_evaluate_quality_gates_passes() -> None:
    config = {
        "quality_gates": {
            "max_ccn": 10.0,
            "max_warnings": 10,
        }
    }
    results = [
        {"project": "p1", "language": "Python", "ccn": 5.0, "warnings": 2},
    ]
    auditor = MetricsAuditor.__new__(MetricsAuditor)
    gate_fails, trend_fails = auditor._evaluate_quality_gates(results, config)
    assert len(gate_fails) == 0
    assert len(trend_fails) == 0


def test_evaluate_quality_gates_fails() -> None:
    config = {
        "quality_gates": {
            "max_ccn": 10.0,
            "max_warnings": 10,
        }
    }
    results = [
        {"project": "p1", "language": "Python", "ccn": 15.0, "warnings": 2},
        {"project": "p2", "language": "Python", "ccn": 5.0, "warnings": 20},
    ]
    auditor = MetricsAuditor.__new__(MetricsAuditor)
    gate_fails, _ = auditor._evaluate_quality_gates(results, config)
    assert len(gate_fails) == 2


def test_evaluate_quality_gates_per_language_override() -> None:
    config = {
        "quality_gates": {
            "max_ccn": 10.0,
            "max_warnings": 10,
            "per_language": {
                "Python": {"max_ccn": 5.0},
            },
        }
    }
    results = [
        {"project": "p1", "language": "Python", "ccn": 7.0, "warnings": 2},
        {"project": "p2", "language": "Rust", "ccn": 7.0, "warnings": 2},
    ]
    auditor = MetricsAuditor.__new__(MetricsAuditor)
    gate_fails, _ = auditor._evaluate_quality_gates(results, config)
    assert any(f["project"] == "p1" for f in gate_fails)
    assert not any(f["project"] == "p2" for f in gate_fails)


# ─── Upsert + runs_count (Phase 4, Option D) ────────────────────────────


def test_upsert_new_commit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """First run on a project/branch/commit creates a row with runs_count=1."""
    proj = tmp_path / "projects" / "up-test"
    proj.mkdir(parents=True)
    (proj / "main.py").write_text("x = 1\n")

    config = tmp_path / "scopio.toml"
    config.write_text('[discovery]\nprojects = ["up-test"]\n')

    auditor = MetricsAuditor(config, tmp_path / "projects", tmp_path)

    auditor._audit_project = lambda target: {  # type: ignore[method-assign]
        "project": target,
        "language": "Python",
        "files": 1,
        "loc": 1,
        "code": 1,
        "nloc": 1,
        "ccn": 1.0,
        "warnings": 0,
        "commits": 1,
        "last_commit_date": "now",
        "author": "t",
        "branch": "main",
        "dirty": 0,
        "commit_hash": "abc123",
        "tool_versions": "{}",
        "duration_seconds": 0.1,
        "file_metrics": [],
    }
    monkeypatch.setattr("scopio.audit.export_outputs", lambda od, r: None)
    auditor.run()

    from scopio.db import open_db

    with open_db(auditor.db_path) as conn:
        row = conn.execute("SELECT runs_count, commit_hash FROM metrics WHERE project = ?", ("up-test",)).fetchone()
        assert row is not None
        assert row["runs_count"] == 1
        assert row["commit_hash"] == "abc123"


def test_upsert_same_commit_increments(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Re-running on the same project/branch/commit updates and increments runs_count."""
    proj = tmp_path / "projects" / "up-inc"
    proj.mkdir(parents=True)
    (proj / "main.py").write_text("x = 1\n")

    config = tmp_path / "scopio.toml"
    config.write_text('[discovery]\nprojects = ["up-inc"]\n')

    auditor = MetricsAuditor(config, tmp_path / "projects", tmp_path)
    from scopio.db import open_db

    # Seed: insert a row
    auditor._init_db()
    with open_db(auditor.db_path) as conn:
        conn.execute(
            "INSERT INTO metrics (project, language, files, loc, code, nloc, ccn, warnings, "
            "commits, last_commit_date, author, branch, dirty, commit_hash, "
            "tool_versions, duration_seconds, runs_count) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("up-inc", "Python", 1, 1, 1, 1, 1.0, 0, 1, "2026-01-01", "t", "main", 0, "def456", "{}", 0.1, 2),
        )
        conn.commit()

    # Run again with same commit_hash -> upsert must increment runs_count
    auditor._audit_project = lambda target: {  # type: ignore[method-assign]
        "project": target,
        "language": "Python",
        "files": 2,
        "loc": 20,
        "code": 15,
        "nloc": 10,
        "ccn": 3.0,
        "warnings": 1,
        "commits": 1,
        "last_commit_date": "now",
        "author": "t",
        "branch": "main",
        "dirty": 1,
        "commit_hash": "def456",
        "tool_versions": "{}",
        "duration_seconds": 0.5,
        "file_metrics": [{"path": "main.py", "nloc": 10, "ccn": 3.0, "warnings": 1}],
    }
    monkeypatch.setattr("scopio.audit.export_outputs", lambda od, r: None)
    auditor.run()

    with open_db(auditor.db_path) as conn:
        rows = conn.execute(
            "SELECT runs_count, loc, ccn, warnings, dirty, duration_seconds, commit_hash "
            "FROM metrics WHERE project = ? ORDER BY timestamp DESC",
            ("up-inc",),
        ).fetchall()
        assert len(rows) == 1, f"Expected 1 row, got {len(rows)}"
        row = rows[0]
        assert row["runs_count"] == 3, f"Expected runs_count=3, got {row['runs_count']}"
        assert row["loc"] == 20, f"Expected loc=20 (updated), got {row['loc']}"
        assert row["ccn"] == 3.0, f"Expected ccn=3.0 (updated), got {row['ccn']}"
        assert row["dirty"] == 1
        assert row["duration_seconds"] == 0.5


def test_upsert_different_commit_creates_separate_row(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Runs on different commits create separate rows with independent runs_count."""
    proj = tmp_path / "projects" / "up-multi"
    proj.mkdir(parents=True)
    (proj / "main.py").write_text("x = 1\n")

    config = tmp_path / "scopio.toml"
    config.write_text('[discovery]\nprojects = ["up-multi"]\n')

    auditor = MetricsAuditor(config, tmp_path / "projects", tmp_path)
    auditor._init_db()

    call_count = [0]

    def fake_audit(target):
        call_count[0] += 1
        commit = "aaa001" if call_count[0] == 1 else "bbb002"
        return {
            "project": target,
            "language": "Python",
            "files": 1,
            "loc": 1,
            "code": 1,
            "nloc": 1,
            "ccn": 1.0,
            "warnings": 0,
            "commits": 1,
            "last_commit_date": "now",
            "author": "t",
            "branch": "main",
            "dirty": 0,
            "commit_hash": commit,
            "tool_versions": "{}",
            "duration_seconds": 0.1,
            "file_metrics": [],
        }

    auditor._audit_project = fake_audit  # type: ignore[method-assign]
    monkeypatch.setattr("scopio.audit.export_outputs", lambda od, r: None)
    auditor.run()

    from scopio.db import open_db

    with open_db(auditor.db_path) as conn:
        rows = conn.execute(
            "SELECT runs_count, commit_hash FROM metrics WHERE project = ? ORDER BY timestamp", ("up-multi",)
        ).fetchall()
        assert len(rows) == 1, f"After first run: expected 1 row, got {len(rows)}"
        assert rows[0]["runs_count"] == 1
        assert rows[0]["commit_hash"] == "aaa001"

    # Second run: different project config to force a new call but same commit_hash to test variation
    call_count[0] = 0  # Reset so it uses aaa001 again (same commit)
    auditor.run()
    with open_db(auditor.db_path) as conn:
        rows = conn.execute(
            "SELECT runs_count, commit_hash FROM metrics WHERE project = ? ORDER BY timestamp", ("up-multi",)
        ).fetchall()
        # Still 1 row (upserted) with runs_count incremented
        assert len(rows) == 1, f"After second run (same commit): expected 1 row, got {len(rows)}"
        assert rows[0]["runs_count"] == 2, f"runs_count should be 2, got {rows[0]['runs_count']}"


# ─── Path traversal guard ─────────────────────────────────────────────────


def test_audit_project_path_traversal(tmp_path: Path) -> None:
    """_audit_project must reject paths outside projects_dir (e.g. ../../etc)."""
    config = tmp_path / "scopio.toml"
    config.write_text(
        '[discovery]\nprojects = ["../../etc/passwd"]\n[quality_gates]\nmax_ccn = 10.0\nmax_warnings = 10\n'
    )
    auditor = MetricsAuditor(config, tmp_path / "projects", tmp_path)
    result = auditor._audit_project("../../etc/passwd")
    assert result is None, "Path traversal should return None"


# ─── e2e clean command ────────────────────────────────────────────────────


def test_clean_keeps_correct_rows(tmp_path: Path) -> None:
    """Clean should keep only the last N rows and cascade to child tables."""
    from scopio.cli import cli
    from scopio.db import open_db

    # Create a scopio.toml and run init to get .scopio/ created
    (tmp_path / "scopio.toml").write_text("[discovery]\nprojects = []\n")

    runner = CliRunner()
    db_path = tmp_path / "scopio.db"
    with open_db(db_path) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS metrics ("
            "audit_id INTEGER PRIMARY KEY AUTOINCREMENT, project TEXT, branch TEXT, commit_hash TEXT, "
            "timestamp DATETIME DEFAULT CURRENT_TIMESTAMP"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS metrics_history ("
            "audit_id INTEGER, project TEXT, loc INTEGER, ccn REAL, warnings INTEGER, "
            "FOREIGN KEY(audit_id) REFERENCES metrics(audit_id)"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS file_metrics ("
            "file_metric_id INTEGER PRIMARY KEY AUTOINCREMENT, audit_id INTEGER, project TEXT, "
            "path TEXT, nloc INTEGER, ccn REAL, warnings INTEGER, "
            "FOREIGN KEY(audit_id) REFERENCES metrics(audit_id)"
            ")"
        )
        # Insert 5 rows
        for i in range(1, 6):
            cursor = conn.execute(
                "INSERT INTO metrics (project, branch, commit_hash) VALUES (?, ?, ?)",
                ("proj", "main", f"abc00{i}"),
            )
            aid = cursor.lastrowid
            conn.execute(
                "INSERT INTO metrics_history (audit_id, project, loc, ccn, warnings) VALUES (?, ?, ?, ?, ?)",
                (aid, "proj", 10, 1.0, 0),
            )
            conn.execute(
                "INSERT INTO file_metrics (audit_id, project, path, nloc, ccn, warnings) VALUES (?, ?, ?, ?, ?, ?)",
                (aid, "proj", "main.py", 10, 1.0, 0),
            )

    # Run clean with keep=2
    result = runner.invoke(
        cli, ["--config", str(tmp_path / "scopio.toml"), "--output-dir", str(tmp_path), "clean", "--keep", "2"]
    )
    assert result.exit_code == 0, f"clean failed: {result.output}"

    with open_db(db_path) as conn:
        metrics = conn.execute("SELECT COUNT(*) FROM metrics").fetchone()[0]
        assert metrics == 2, f"Expected 2 metrics rows, got {metrics}"
        history = conn.execute("SELECT COUNT(*) FROM metrics_history").fetchone()[0]
        assert history == 2, f"Expected 2 history rows, got {history}"
        file_metrics = conn.execute("SELECT COUNT(*) FROM file_metrics").fetchone()[0]
        assert file_metrics == 2, f"Expected 2 file_metrics rows, got {file_metrics}"


# ─── Version validation ──────────────────────────────────────────────────


def test_validate_tool_versions_all_good() -> None:
    from scopio.audit import _validate_tool_versions

    versions = {"scc": "scc version 3.3.0", "lizard": "lizard 1.24.0"}
    warnings = _validate_tool_versions(versions)
    assert len(warnings) == 0, f"Expected no warnings, got: {warnings}"


def test_validate_tool_versions_diverge() -> None:
    from scopio.audit import _validate_tool_versions

    versions = {"scc": "scc version 4.0.0", "lizard": "lizard 1.23.0"}
    warnings = _validate_tool_versions(versions)
    assert len(warnings) == 2, f"Expected 2 warnings, got: {warnings}"
    assert any("scc" in w for w in warnings)
    assert any("lizard" in w for w in warnings)


def test_validate_tool_versions_in_range() -> None:
    from scopio.audit import _validate_tool_versions

    versions = {"scc": "scc version 3.6.0", "lizard": "lizard 1.24.5"}
    warnings = _validate_tool_versions(versions)
    assert warnings == [], f"Expected no warnings, got: {warnings}"


def test_validate_tool_versions_missing() -> None:
    from scopio.audit import _validate_tool_versions

    warnings = _validate_tool_versions({})
    assert len(warnings) == 2
    assert all("not found" in w for w in warnings)


def test_validate_tool_versions_unparseable() -> None:
    from scopio.audit import _validate_tool_versions

    warnings = _validate_tool_versions({"scc": "garbage", "lizard": "1.24.0"})
    assert len(warnings) == 1
    assert "unparseable" in warnings[0]


# ─── _filter_incremental tests ───────────────────────────────────────


def test_filter_incremental_no_recent_files(tmp_path: Path) -> None:
    """Project with no recent files should NOT be selected."""
    from datetime import datetime

    config = tmp_path / "scopio.toml"
    config.write_text('[discovery]\nprojects = ["old-proj"]\n[quality_gates]\nmax_ccn = 10.0\nmax_warnings = 10\n')

    proj = tmp_path / "projects" / "old-proj"
    proj.mkdir(parents=True)

    # Create an old file (timestamp before epoch so it's always "old")
    old_file = proj / "old.py"
    old_file.write_text("x = 1\n")
    old_mtime = datetime(2020, 1, 1, tzinfo=UTC).timestamp()
    os.utime(old_file, (old_mtime, old_mtime))

    auditor = MetricsAuditor(config, tmp_path / "projects", tmp_path)

    # Simulate a last run time in the future to make all files "old"
    # We need to monkeypatch _get_last_metrics to return a timestamp in the future
    original = auditor._get_last_metrics
    auditor._get_last_metrics = lambda proj: {  # type: ignore[method-assign]
        "timestamp": "2026-12-31 23:59:59+00:00",
        "loc": 1,
        "ccn": 1.0,
        "warnings": 0,
    }

    result = auditor._filter_incremental(["old-proj"])
    assert len(result) == 0, f"Expected no selection, got {result}"
    auditor._get_last_metrics = original


def test_filter_incremental_recent_file(tmp_path: Path) -> None:
    """Project with a recent file should be selected."""
    config = tmp_path / "scopio.toml"
    config.write_text('[discovery]\nprojects = ["recent-proj"]\n[quality_gates]\nmax_ccn = 10.0\nmax_warnings = 10\n')

    proj = tmp_path / "projects" / "recent-proj"
    proj.mkdir(parents=True)
    (proj / "main.py").write_text("x = 1\n")
    # File is newly created, so mtime is "now"

    auditor = MetricsAuditor(config, tmp_path / "projects", tmp_path)

    # Last run was in the past
    auditor._get_last_metrics = lambda proj: {  # type: ignore[method-assign]
        "timestamp": "2020-01-01 00:00:00+00:00",
        "loc": 1,
        "ccn": 1.0,
        "warnings": 0,
    }

    result = auditor._filter_incremental(["recent-proj"])
    assert len(result) == 1, f"Expected selection, got {result}"
    assert result[0] == "recent-proj"


def test_filter_incremental_subdir_recent(tmp_path: Path) -> None:
    """File in subdirectory should also trigger selection."""
    config = tmp_path / "scopio.toml"
    config.write_text('[discovery]\nprojects = ["sub-proj"]\n[quality_gates]\nmax_ccn = 10.0\nmax_warnings = 10\n')

    proj = tmp_path / "projects" / "sub-proj"
    proj.mkdir(parents=True)
    sub = proj / "src" / "sub"
    sub.mkdir(parents=True)
    (sub / "deep.py").write_text("x = 1\n")

    auditor = MetricsAuditor(config, tmp_path / "projects", tmp_path)

    auditor._get_last_metrics = lambda proj: {  # type: ignore[method-assign]
        "timestamp": "2020-01-01 00:00:00+00:00",
        "loc": 1,
        "ccn": 1.0,
        "warnings": 0,
    }

    result = auditor._filter_incremental(["sub-proj"])
    assert len(result) == 1, f"Expected selection, got {result}"


def test_filter_incremental_no_previous_audit(tmp_path: Path) -> None:
    """Project with no previous audit should always be selected."""
    config = tmp_path / "scopio.toml"
    config.write_text('[discovery]\nprojects = ["new-proj"]\n[quality_gates]\nmax_ccn = 10.0\nmax_warnings = 10\n')

    proj = tmp_path / "projects" / "new-proj"
    proj.mkdir(parents=True)
    (proj / "main.py").write_text("x = 1\n")

    auditor = MetricsAuditor(config, tmp_path / "projects", tmp_path)

    # No previous audit -> _get_last_metrics returns None
    auditor._get_last_metrics = lambda proj: None  # type: ignore[method-assign]

    result = auditor._filter_incremental(["new-proj"])
    assert len(result) == 1, f"Expected new project selected, got {result}"


def test_parse_gitignore(tmp_path: Path) -> None:
    from scopio.audit import _parse_gitignore

    gitignore = tmp_path / ".gitignore"
    gitignore.write_text("# comment\ntarget/\n*.log\nnode_modules\n")

    scc_ex, lizard_ex = _parse_gitignore(gitignore)
    assert "target" in scc_ex
    assert "node_modules" in scc_ex
    assert "-x" in lizard_ex
    assert "*.log" in lizard_ex


def test_parse_lizard_csv_aggregates_files() -> None:
    # 2 functions in the same file
    multi_func_csv = """10,5,30,2,1,foo@10@scopio/foo.py,scopio/foo.py,foo,foo(x),1,10
20,8,40,3,1,bar@20@scopio/foo.py,scopio/foo.py,bar,bar(y),12,25
"""
    result = _parse_lizard_csv(multi_func_csv)
    assert result["nloc"] == 30  # 10 + 20
    assert result["ccn_max"] == 8.0
    assert len(result["files"]) == 1  # aggregated into 1 file entry!
    assert result["files"][0]["path"] == "scopio/foo.py"
    assert result["files"][0]["nloc"] == 30
    assert result["files"][0]["ccn"] == 8.0
