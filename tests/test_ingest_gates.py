from __future__ import annotations

import json
from pathlib import Path

import pytest

from scopio.audit import MetricsAuditor


def test_evaluate_quality_gates_ingest_errors() -> None:
    config = {
        "quality_gates": {
            "max_ccn": 10.0,
            "max_warnings": 10,
            "ingest": {
                "max_errors": 0,
                "max_warnings": 5,
            },
        }
    }
    results = [
        {"project": "p1", "language": "Python", "ccn": 5.0, "warnings": 2, "ingest_errors": 1, "ingest_warnings": 0},
    ]
    auditor = MetricsAuditor.__new__(MetricsAuditor)
    gate_fails, _ = auditor._evaluate_quality_gates(results, config)  # type: ignore[arg-type]
    assert len(gate_fails) == 1
    assert gate_fails[0]["project"] == "p1"


def test_audit_project_with_ingest_sources(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    proj = tmp_path / "projects" / "test-ingest-proj"
    proj.mkdir(parents=True)
    (proj / "main.py").write_text("x = 1\n")

    reports_dir = proj / "reports"
    reports_dir.mkdir()
    ruff_report = reports_dir / "ruff.json"
    ruff_report.write_text(json.dumps([{"code": "E501", "filename": "main.py", "message": "line too long"}]))

    config_file = tmp_path / "scopio.toml"
    config_file.write_text(
        '[discovery]\nprojects = ["test-ingest-proj"]\n[[ingest.sources]]\nname = "ruff"\npath = "reports/ruff.json"\n'
    )

    auditor = MetricsAuditor(config_file, tmp_path / "projects", tmp_path)

    monkeypatch.setattr(
        "scopio.audit._run_scc",
        lambda path, excludes: [{"Name": "Python", "Lines": 10, "Code": 8, "Count": 1}],
    )
    monkeypatch.setattr(
        "scopio.audit._run_lizard",
        lambda path, excludes: {"nloc": 6, "ccn": 2.0, "warnings": 0, "files": []},
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

    res = auditor._audit_project("test-ingest-proj")
    assert res is not None
    assert res["ingest_warnings"] == 1
    assert len(res["ingest_results"]) == 1
    assert len(res["ingest_findings"]) == 1
