from __future__ import annotations

import json
from pathlib import Path

import pytest

from scopio.audit import MetricsAuditor
from scopio.collect.run.runner import fetch_git_info


def test_provocation_3_git_zero_head(tmp_path: Path) -> None:
    """Stress Test Provocation 3: Fresh git repository with git init but zero commits."""
    proj = tmp_path / "zero-commit-repo"
    proj.mkdir()
    (proj / "app.py").write_text("print('hello world')\n")

    # Run git init
    import subprocess

    subprocess.run(["git", "init"], cwd=proj, check=True, capture_output=True)

    # 1. Test fetch_git_info does not crash on zero commits
    git_info = fetch_git_info(proj)
    assert git_info["commits"] == 0
    assert git_info["commit_hash"] == "n/a"
    assert git_info["branch"] in ("n/a", "master", "main", "unknown")

    # 2. Test MetricsAuditor handles zero-commit repo gracefully
    cfg = tmp_path / "scopio.toml"
    cfg.write_text('[discovery]\nprojects = ["zero-commit-repo"]\n')

    auditor = MetricsAuditor(cfg, tmp_path, tmp_path / "out")
    audited = auditor._audit_project("zero-commit-repo")

    assert audited is not None
    assert audited["commits"] == 0
    assert audited["commit_hash"] == "n/a"
    assert audited["loc"] > 0


def test_provocation_4_multilanguage_monorepo_ingestion(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Stress Test Provocation 4: Ingesting Ruff + ESLint + Clippy + SARIF simultaneously."""
    proj = tmp_path / "polyglot-monorepo"
    proj.mkdir()
    reports = proj / "reports"
    reports.mkdir()

    # Ruff report (1 warning)
    (reports / "ruff.json").write_text(
        json.dumps([{"code": "E501", "filename": "py/app.py", "location": {"row": 10}, "message": "Line too long"}])
    )

    # ESLint report (1 error, 1 warning)
    (reports / "eslint.json").write_text(
        json.dumps(
            [
                {
                    "filePath": "js/index.js",
                    "messages": [
                        {"ruleId": "no-eval", "severity": 2, "message": "eval is evil", "line": 5},
                        {"ruleId": "semi", "severity": 1, "message": "missing semi", "line": 8},
                    ],
                }
            ]
        )
    )

    # Clippy report (1 warning)
    (reports / "clippy.json").write_text(
        '{"reason":"compiler-message","message":{"code":{"code":"clippy::needless_return"},'
        '"level":"warning","message":"unneeded return","spans":[{"file_name":"src/main.rs","line_start":12}]}}\n'
    )

    # SARIF report (1 error)
    sarif_data = {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "runs": [
            {
                "results": [
                    {
                        "ruleId": "SEC001",
                        "level": "error",
                        "message": {"text": "Hardcoded secret"},
                        "locations": [
                            {
                                "physicalLocation": {
                                    "artifactLocation": {"uri": "config.json"},
                                    "region": {"startLine": 1},
                                }
                            }
                        ],
                    }
                ]
            }
        ],
    }
    (reports / "sarif.json").write_text(json.dumps(sarif_data))

    # Config with all 4 ingest sources
    cfg = tmp_path / "scopio.toml"
    cfg.write_text(
        '[discovery]\nprojects = ["polyglot-monorepo"]\n'
        '[[ingest.sources]]\nname = "ruff"\npath = "reports/ruff.json"\n'
        '[[ingest.sources]]\nname = "eslint"\npath = "reports/eslint.json"\n'
        '[[ingest.sources]]\nname = "clippy"\npath = "reports/clippy.json"\n'
        '[[ingest.sources]]\nname = "sarif"\npath = "reports/sarif.json"\n'
        "[quality_gates.ingest]\nmax_errors = 5\nmax_warnings = 10\n"
    )

    auditor = MetricsAuditor(cfg, tmp_path, tmp_path / "out")

    monkeypatch.setattr(
        "scopio.audit._run_scc", lambda path, excludes: [{"Name": "Python", "Lines": 100, "Code": 80, "Count": 3}]
    )
    monkeypatch.setattr(
        "scopio.audit._run_lizard", lambda path, excludes: {"nloc": 50, "ccn": 2.0, "warnings": 0, "files": []}
    )
    monkeypatch.setattr("scopio.audit._tool_versions", lambda: {"scc": "v3", "lizard": "v1"})
    monkeypatch.setattr("scopio.audit.shutil.which", lambda cmd: "/usr/bin/" + cmd)

    audited = auditor._audit_project("polyglot-monorepo")
    assert audited is not None
    assert len(audited["ingest_results"]) == 4
    assert audited["ingest_errors"] == 2  # 1 from ESLint + 1 from SARIF
    assert audited["ingest_warnings"] == 3  # 1 from Ruff + 1 from ESLint + 1 from Clippy
    assert len(audited["ingest_findings"]) == 5  # Total findings across all linters


def test_provocation_1_monorepo_concurrency(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Stress Test Provocation 1: 20 parallel projects auditing concurrently into SQLite."""
    projects = []
    projects_dir = tmp_path / "monorepo"
    projects_dir.mkdir()

    for i in range(20):
        p_name = f"subproj-{i:02d}"
        projects.append(p_name)
        p_path = projects_dir / p_name
        p_path.mkdir()
        (p_path / "main.py").write_text(f"# Subproject {i}\nx = {i}\n")

    cfg = tmp_path / "scopio.toml"
    cfg.write_text(f"[discovery]\nprojects = {json.dumps(projects)}\n")

    auditor = MetricsAuditor(cfg, projects_dir, tmp_path / "out")

    monkeypatch.setattr(
        "scopio.audit._run_scc", lambda path, excludes: [{"Name": "Python", "Lines": 10, "Code": 8, "Count": 1}]
    )
    monkeypatch.setattr(
        "scopio.audit._run_lizard", lambda path, excludes: {"nloc": 5, "ccn": 1.0, "warnings": 0, "files": []}
    )
    monkeypatch.setattr("scopio.audit._tool_versions", lambda: {"scc": "v3", "lizard": "v1"})
    monkeypatch.setattr("scopio.audit.shutil.which", lambda cmd: "/usr/bin/" + cmd)

    # Execute concurrent audit across 20 parallel projects
    summary = auditor.run(verbose=False, quiet=True, incremental=False)
    assert len(summary["results"]) == 20
    assert summary["observability"]["projects_processed"] == 20
    assert summary["observability"]["projects_failed"] == 0


def test_provocation_2_corrupted_linter_reports(tmp_path: Path) -> None:
    """Stress Test Provocation 2: Handling truncated JSON, binary data, and malformed linter reports gracefully."""
    from scopio.collect.ingest.parsers import ingest_linter_report

    # 1. Truncated JSON file
    trunc_file = tmp_path / "truncated.json"
    trunc_file.write_text('{"code": "E501", "filename": "app.py"')
    res1 = ingest_linter_report(trunc_file, tool_hint="ruff")
    assert res1["status"] in ("clean", "not_run")
    assert len(res1["findings"]) == 0

    # 2. Binary / non-UTF-8 file
    bin_file = tmp_path / "corrupted.bin"
    bin_file.write_bytes(b"\x80\x81\xff\x00\xfe\xfd\xfa\xfb")
    res2 = ingest_linter_report(bin_file, tool_hint="sarif")
    assert res2["status"] == "not_run"
    assert len(res2["findings"]) == 0

    # 3. Plain text / non-JSON file pretending to be ESLint
    txt_file = tmp_path / "eslint_text.txt"
    txt_file.write_text("Fatal crash error in compiler on line 42")
    res3 = ingest_linter_report(txt_file, tool_hint="eslint")
    assert res3["status"] in ("clean", "not_run")
    assert len(res3["findings"]) == 0
