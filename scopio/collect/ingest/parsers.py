from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scopio.collect.types import Finding, IngestSummary


def _normalize_path(uri: str) -> str:
    cleaned = uri.removeprefix("file://")
    return cleaned.replace("\\", "/")


def parse_ruff_json(content: str, source: str = "ruff") -> IngestSummary:
    try:
        data = json.loads(content)
        if not isinstance(data, list):
            return {"source": source, "status": "not_run", "errors": 0, "warnings": 0, "info": 0, "findings": []}
    except json.JSONDecodeError:
        return {"source": source, "status": "not_run", "errors": 0, "warnings": 0, "info": 0, "findings": []}

    findings: list[Finding] = []
    errors = 0
    warnings = 0

    for item in data:
        if not isinstance(item, dict):
            continue
        rule = str(item.get("code") or "ruff-violation")
        file_path = _normalize_path(str(item.get("filename") or ""))
        msg = str(item.get("message") or "")
        loc = item.get("location") or {}
        line_val = loc.get("row") if isinstance(loc, dict) else None
        line = int(line_val) if line_val is not None and str(line_val).isdigit() else None

        # Syntax errors vs normal lint warnings
        severity: Any = "error" if rule.startswith("E9") or rule.startswith("F82") else "warning"
        if severity == "error":
            errors += 1
        else:
            warnings += 1

        findings.append(
            {
                "source": source,
                "file": file_path,
                "rule": rule,
                "severity": severity,
                "message": msg,
                "line": line,
            }
        )

    status: Any = "violations" if findings else "clean"
    return {
        "source": source,
        "status": status,
        "errors": errors,
        "warnings": warnings,
        "info": 0,
        "findings": findings,
    }


def parse_eslint_json(content: str, source: str = "eslint") -> IngestSummary:
    try:
        data = json.loads(content)
        if not isinstance(data, list):
            return {"source": source, "status": "not_run", "errors": 0, "warnings": 0, "info": 0, "findings": []}
    except json.JSONDecodeError:
        return {"source": source, "status": "not_run", "errors": 0, "warnings": 0, "info": 0, "findings": []}

    findings: list[Finding] = []
    errors = 0
    warnings = 0
    info = 0

    for file_entry in data:
        if not isinstance(file_entry, dict):
            continue
        file_path = _normalize_path(str(file_entry.get("filePath") or ""))
        messages = file_entry.get("messages") or []
        for item in messages:
            if not isinstance(item, dict):
                continue
            rule = str(item.get("ruleId") or "eslint-violation")
            msg = str(item.get("message") or "")
            l_val = item.get("line")
            line = int(l_val) if l_val is not None and str(l_val).isdigit() else None

            sev_num = item.get("severity", 1)

            severity: Any = "error" if sev_num == 2 else ("warning" if sev_num == 1 else "info")
            if severity == "error":
                errors += 1
            elif severity == "warning":
                warnings += 1
            else:
                info += 1

            findings.append(
                {
                    "source": source,
                    "file": file_path,
                    "rule": rule,
                    "severity": severity,
                    "message": msg,
                    "line": line,
                }
            )

    status: Any = "violations" if findings else "clean"
    return {
        "source": source,
        "status": status,
        "errors": errors,
        "warnings": warnings,
        "info": info,
        "findings": findings,
    }


def parse_clippy_json(content: str, source: str = "clippy") -> IngestSummary:
    findings: list[Finding] = []
    errors = 0
    warnings = 0
    info = 0

    lines = [line.strip() for line in content.splitlines() if line.strip()]
    for line in lines:
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue

        if not isinstance(item, dict) or item.get("reason") != "compiler-message":
            continue

        msg_obj = item.get("message") or {}
        if not isinstance(msg_obj, dict):
            continue

        code_obj = msg_obj.get("code") or {}
        rule = str(code_obj.get("code") or "clippy-message") if isinstance(code_obj, dict) else "clippy-message"
        msg = str(msg_obj.get("message") or "")
        level = str(msg_obj.get("level") or "warning")

        severity: Any = "error" if level == "error" else ("warning" if level == "warning" else "info")

        spans = msg_obj.get("spans") or []
        file_path = ""
        line_num = None
        if isinstance(spans, list) and len(spans) > 0 and isinstance(spans[0], dict):
            file_path = _normalize_path(str(spans[0].get("file_name") or ""))
            line_num = spans[0].get("line_start")

        if severity == "error":
            errors += 1
        elif severity == "warning":
            warnings += 1
        else:
            info += 1

        findings.append(
            {
                "source": source,
                "file": file_path,
                "rule": rule,
                "severity": severity,
                "message": msg,
                "line": line_num,
            }
        )

    status: Any = "violations" if findings else ("clean" if lines else "not_run")
    return {
        "source": source,
        "status": status,
        "errors": errors,
        "warnings": warnings,
        "info": info,
        "findings": findings,
    }


def parse_sarif(content: str, source: str = "sarif") -> IngestSummary:
    try:
        data = json.loads(content)
        if not isinstance(data, dict):
            return {"source": source, "status": "not_run", "errors": 0, "warnings": 0, "info": 0, "findings": []}
    except json.JSONDecodeError:
        return {"source": source, "status": "not_run", "errors": 0, "warnings": 0, "info": 0, "findings": []}

    findings: list[Finding] = []
    errors = 0
    warnings = 0
    info = 0

    runs = data.get("runs") or []
    for run in runs:
        if not isinstance(run, dict):
            continue
        results = run.get("results") or []
        for res in results:
            if not isinstance(res, dict):
                continue
            rule = str(res.get("ruleId") or "sarif-rule")
            msg_obj = res.get("message") or {}
            msg = str(msg_obj.get("text") or "") if isinstance(msg_obj, dict) else ""
            level = str(res.get("level") or "warning").lower()

            severity: Any = (
                "error" if level in ("error", "high") else ("warning" if level in ("warning", "medium") else "info")
            )

            locations = res.get("locations") or []
            file_path = ""
            line_num = None
            if isinstance(locations, list) and len(locations) > 0 and isinstance(locations[0], dict):
                phys = locations[0].get("physicalLocation") or {}
                if isinstance(phys, dict):
                    artifact = phys.get("artifactLocation") or {}
                    if isinstance(artifact, dict):
                        file_path = _normalize_path(str(artifact.get("uri") or ""))
                    region = phys.get("region") or {}
                    if isinstance(region, dict):
                        line_num = region.get("startLine")

            if severity == "error":
                errors += 1
            elif severity == "warning":
                warnings += 1
            else:
                info += 1

            findings.append(
                {
                    "source": source,
                    "file": file_path,
                    "rule": rule,
                    "severity": severity,
                    "message": msg,
                    "line": line_num,
                }
            )

    status: Any = "violations" if findings else "clean"
    return {
        "source": source,
        "status": status,
        "errors": errors,
        "warnings": warnings,
        "info": info,
        "findings": findings,
    }


def ingest_linter_report(report_path: Path, tool_hint: str | None = None) -> IngestSummary:
    if not report_path.is_file():
        return {
            "source": tool_hint or report_path.stem,
            "status": "not_run",
            "errors": 0,
            "warnings": 0,
            "info": 0,
            "findings": [],
        }

    try:
        content = report_path.read_text()
    except OSError:
        return {
            "source": tool_hint or report_path.stem,
            "status": "not_run",
            "errors": 0,
            "warnings": 0,
            "info": 0,
            "findings": [],
        }

    source_name = tool_hint or report_path.stem.lower()

    if "sarif" in report_path.name.lower() or source_name == "sarif":
        return parse_sarif(content, source=source_name)
    if "ruff" in report_path.name.lower() or source_name == "ruff":
        return parse_ruff_json(content, source=source_name)
    if "eslint" in report_path.name.lower() or source_name == "eslint":
        return parse_eslint_json(content, source=source_name)
    if "clippy" in report_path.name.lower() or source_name == "clippy":
        return parse_clippy_json(content, source=source_name)

    # Auto-detect JSON content structure
    try:
        parsed = json.loads(content)
        if isinstance(parsed, dict) and "$schema" in parsed and "sarif" in parsed["$schema"].lower():
            return parse_sarif(content, source=source_name)
        if isinstance(parsed, list) and len(parsed) > 0:
            sample = parsed[0]
            if isinstance(sample, dict):
                if "filePath" in sample:
                    return parse_eslint_json(content, source=source_name)
                if "filename" in sample and "location" in sample:
                    return parse_ruff_json(content, source=source_name)
    except json.JSONDecodeError:
        if "reason" in content and "compiler-message" in content:
            return parse_clippy_json(content, source=source_name)

    return parse_sarif(content, source=source_name)
