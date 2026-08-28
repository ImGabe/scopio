from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from scopio.audit import (
    MetricsAuditor,
    _git_info,
    _language_from_scc,
    _parse_lizard_output,
    _run_lizard,
    _run_scc,
)

# ─── _parse_lizard_output ────────────────────────────────────────────────

# Realistic lizard output. Note: the parser counts the "Total" line as a file
# and uses parts[2] (tokens) for initial CCN — pre-existing quirks.
LIZARD_COMPLETE = """
==============================================================
  NLOC    CCN   token  PARAM  START  END   LOC   METHOD
==============================================================
    10      5     30      2      1    11    10   foo
     5      2     15      1     12    16     5   bar
==============================================================
    15      7     45      3     13    27    15   <<<== Total
"""

LIZARD_EMPTY = """
==============================================================
  NLOC    CCN   token  PARAM  START  END   LOC   METHOD
==============================================================
==============================================================
     0      0      0      0     0     0     0   <<<== Total
"""

LIZARD_MALFORMED = ""


def test_parse_lizard_complete() -> None:
    result = _parse_lizard_output(LIZARD_COMPLETE)
    assert result["nloc"] == 15  # from total line parts[0]
    # CCN: parsed from the last line parts[1]=7, then file loop sums cols[1]
    # and divides by file count (2 files, Total line filtered out). (5+2)/2 = 3.5
    assert result["ccn"] == 3.5
    # warnings: file loop sums cols[5]: foo(11)+bar(16) = 27
    assert result["warnings"] == 27
    assert len(result["files"]) == 2


def test_parse_lizard_empty() -> None:
    result = _parse_lizard_output(LIZARD_EMPTY)
    assert result["nloc"] == 0
    assert result["ccn"] == 0.0
    assert result["warnings"] == 0
    # The "Total" line is now filtered (<<<== check), so files = []
    assert result["files"] == []


def test_parse_lizard_malformed() -> None:
    result = _parse_lizard_output(LIZARD_MALFORMED)
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
    mock.stdout = LIZARD_COMPLETE
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

    monkeypatch.setattr("scopio.audit._run_cmd", fake_run_cmd)

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
