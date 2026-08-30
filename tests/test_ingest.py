from __future__ import annotations

import json
from pathlib import Path

from scopio.collect.ingest.parsers import (
    ingest_linter_report,
    parse_clippy_json,
    parse_eslint_json,
    parse_ruff_json,
    parse_sarif,
)


def test_parse_ruff_json() -> None:
    data = [
        {
            "code": "E501",
            "filename": "scopio/cli.py",
            "location": {"row": 10},
            "message": "Line too long",
        },
        {
            "code": "E999",
            "filename": "scopio/audit.py",
            "location": {"row": 20},
            "message": "Syntax error",
        },
    ]
    summary = parse_ruff_json(json.dumps(data))
    assert summary["status"] == "violations"
    assert summary["warnings"] == 1
    assert summary["errors"] == 1
    assert len(summary["findings"]) == 2
    assert summary["findings"][0]["rule"] == "E501"


def test_parse_eslint_json() -> None:
    data = [
        {
            "filePath": "/app/src/index.js",
            "messages": [
                {"ruleId": "semi", "severity": 2, "message": "Missing semicolon", "line": 5},
                {"ruleId": "no-unused-vars", "severity": 1, "message": "Unused var", "line": 12},
            ],
        }
    ]
    summary = parse_eslint_json(json.dumps(data))
    assert summary["status"] == "violations"
    assert summary["errors"] == 1
    assert summary["warnings"] == 1
    assert len(summary["findings"]) == 2
    assert summary["findings"][0]["file"] == "/app/src/index.js"


def test_parse_clippy_json() -> None:
    ndjson = (
        '{"reason":"compiler-message","message":{"code":{"code":"clippy::needless_return"},'
        '"level":"warning","message":"unneeded return statement","spans":[{"file_name":"src/main.rs","line_start":15}]}}\n'
    )
    summary = parse_clippy_json(ndjson)
    assert summary["status"] == "violations"
    assert summary["warnings"] == 1
    assert len(summary["findings"]) == 1
    assert summary["findings"][0]["rule"] == "clippy::needless_return"
    assert summary["findings"][0]["file"] == "src/main.rs"


def test_parse_sarif() -> None:
    sarif = {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "runs": [
            {
                "results": [
                    {
                        "ruleId": "C0111",
                        "level": "error",
                        "message": {"text": "Missing docstring"},
                        "locations": [
                            {
                                "physicalLocation": {
                                    "artifactLocation": {"uri": "scopio/audit.py"},
                                    "region": {"startLine": 42},
                                }
                            }
                        ],
                    }
                ]
            }
        ],
    }
    summary = parse_sarif(json.dumps(sarif))
    assert summary["status"] == "violations"
    assert summary["errors"] == 1
    assert len(summary["findings"]) == 1
    assert summary["findings"][0]["file"] == "scopio/audit.py"
    assert summary["findings"][0]["line"] == 42


def test_ingest_linter_report(tmp_path: Path) -> None:
    report = tmp_path / "ruff.json"
    report.write_text(json.dumps([{"code": "F401", "filename": "app.py", "message": "unused import"}]))

    summary = ingest_linter_report(report)
    assert summary["status"] == "violations"
    assert len(summary["findings"]) == 1
