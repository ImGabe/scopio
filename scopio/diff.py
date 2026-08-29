from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import click

from .db import open_db
from .types import DiffSummary


def _safe_num(value: Any, default: float = 0) -> float:
    return value if value is not None else default


def project_diff(db_path: Path, project: str) -> DiffSummary:
    with open_db(db_path) as conn:
        rows = conn.execute(
            """
            SELECT timestamp, branch, commit_hash, loc, ccn, warnings, dirty,
                   tool_versions, duration_seconds
            FROM metrics
            WHERE project = ?
            ORDER BY timestamp ASC
            """,
            (project,),
        ).fetchall()

    if len(rows) < 2:
        raise click.ClickException("Not enough history for diff (requires at least 2 audits).")

    base = dict(rows[0])
    latest = dict(rows[-1])

    loc_delta = _safe_num(latest.get("loc")) - _safe_num(base.get("loc"))
    ccn_delta = _safe_num(latest.get("ccn")) - _safe_num(base.get("ccn"))
    warn_delta = _safe_num(latest.get("warnings")) - _safe_num(base.get("warnings"))

    loc_trend = None
    if base.get("loc"):
        loc_trend = loc_delta / base["loc"]

    ccn_trend = None
    if base.get("ccn"):
        ccn_trend = ccn_delta / base["ccn"]

    return {
        "project": project,
        "base": {
            "timestamp": base.get("timestamp"),
            "branch": base.get("branch"),
            "commit_hash": base.get("commit_hash"),
            "loc": base.get("loc"),
            "ccn": base.get("ccn"),
            "warnings": base.get("warnings"),
        },
        "latest": {
            "timestamp": latest.get("timestamp"),
            "branch": latest.get("branch"),
            "commit_hash": latest.get("commit_hash"),
            "loc": latest.get("loc"),
            "ccn": latest.get("ccn"),
            "warnings": latest.get("warnings"),
            "dirty": latest.get("dirty"),
        },
        "delta": {
            "loc": loc_delta,
            "loc_trend": loc_trend,
            "ccn": round(ccn_delta, 2),
            "ccn_trend": ccn_trend,
            "warnings": warn_delta,
        },
    }


def _fetch_project_audit_rows(db_path: Path, project: str) -> list[sqlite3.Row]:
    """Fetch audit rows and file_metrics for a project.
    Returns (audit_rows, latest_file_rows).
    """
    with open_db(db_path) as conn:
        rows = conn.execute(
            """
            SELECT audit_id, timestamp, branch, commit_hash, loc, ccn, warnings
            FROM metrics
            WHERE project = ?
            ORDER BY timestamp ASC
            """,
            (project,),
        ).fetchall()
    return rows


def _fetch_file_metrics_by_audit_id(db_path: Path, audit_id: int) -> dict[str, dict[str, Any]]:
    """Return {path: row_dict} for a given audit_id."""
    with open_db(db_path) as conn:
        return {
            row["path"]: dict(row)
            for row in conn.execute(
                "SELECT path, nloc, ccn, warnings FROM file_metrics WHERE audit_id = ?", (audit_id,)
            ).fetchall()
        }


def _compute_file_delta(
    path: str, base: dict[str, Any] | None, latest: dict[str, Any] | None, threshold_ccn: float | None
) -> dict[str, Any]:
    """Compute delta metrics for a single file across two audits."""
    item: dict[str, Any] = {
        "path": path,
        "added": base is None and latest is not None,
        "removed": base is not None and latest is None,
    }

    if base and latest:
        item["nloc_delta"] = _safe_num(latest["nloc"]) - _safe_num(base["nloc"])
        item["ccn_delta"] = _safe_num(latest["ccn"]) - _safe_num(base["ccn"])
        item["warnings_delta"] = _safe_num(latest["warnings"]) - _safe_num(base["warnings"])
        item["ccn"] = latest["ccn"]
        item["over_threshold"] = threshold_ccn is not None and _safe_num(latest["ccn"]) > threshold_ccn
    elif latest:
        item["nloc_delta"] = latest["nloc"]
        item["ccn_delta"] = latest["ccn"]
        item["warnings_delta"] = latest["warnings"]
        item["ccn"] = latest["ccn"]
        item["over_threshold"] = threshold_ccn is not None and _safe_num(latest["ccn"]) > threshold_ccn
    else:
        assert base is not None
        item["nloc_delta"] = -_safe_num(base["nloc"])
        item["ccn_delta"] = -_safe_num(base["ccn"])
        item["warnings_delta"] = -_safe_num(base["warnings"])
        item["ccn"] = base["ccn"]
        item["over_threshold"] = threshold_ccn is not None and _safe_num(base["ccn"]) > threshold_ccn

    return item


def _summarize_file_changes(files: list[dict[str, Any]]) -> dict[str, int]:
    """Compute summary statistics from a list of file diffs."""
    added = [f for f in files if f["added"]]
    removed = [f for f in files if f["removed"]]
    changed = [f for f in files if not f["added"] and not f["removed"] and f.get("ccn_delta") not in (None, 0)]
    over = [f for f in files if f.get("over_threshold")]
    return {
        "total_files": len(files),
        "added_files": len(added),
        "removed_files": len(removed),
        "changed_files": len(changed),
        "over_threshold_files": len(over),
    }


def _snapshot_meta(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "timestamp": row.get("timestamp"),
        "branch": row.get("branch"),
        "commit_hash": row.get("commit_hash"),
    }


def project_file_diff(db_path: Path, project: str, threshold_ccn: float | None = None) -> dict[str, Any]:
    rows = _fetch_project_audit_rows(db_path, project)

    if len(rows) < 2:
        raise click.ClickException("Not enough history for granular diff (requires at least 2 audits).")

    base_meta = dict(rows[0])
    latest_meta = dict(rows[-1])

    base_files = _fetch_file_metrics_by_audit_id(db_path, rows[0]["audit_id"])
    latest_files = _fetch_file_metrics_by_audit_id(db_path, rows[-1]["audit_id"])

    all_paths = sorted(set(base_files) | set(latest_files))
    files = [
        _compute_file_delta(path, base_files.get(path), latest_files.get(path), threshold_ccn) for path in all_paths
    ]

    return {
        "project": project,
        "base": _snapshot_meta(base_meta),
        "latest": _snapshot_meta(latest_meta),
        "threshold_ccn": threshold_ccn,
        "files": files,
        "summary": _summarize_file_changes(files),
    }


def _render_diff_header(summary: dict[str, Any]) -> list[str]:
    return [
        f"# Diff — {summary['project']}",
        "",
        "## Base",
        f"- {summary['base']['timestamp']} (`{summary['base']['branch']}`) `{summary['base']['commit_hash']}`",
        f"- LOC {summary['base']['loc']} | CCN {summary['base']['ccn']} | warnings {summary['base']['warnings']}",
        "",
        "## Latest",
        f"- {summary['latest']['timestamp']} (`{summary['latest']['branch']}`) `{summary['latest']['commit_hash']}`",
        f"- LOC {summary['latest']['loc']} | CCN {summary['latest']['ccn']} | warnings {summary['latest']['warnings']}",
        "",
    ]


def _render_diff_delta(summary: dict[str, Any]) -> list[str]:
    lines = [
        "## Delta",
        f"- LOC: {summary['delta']['loc']:+}",
        f"- CCN: {summary['delta']['ccn']:+.2f}",
        f"- Warnings: {summary['delta']['warnings']:+}",
        "",
    ]
    loc_trend = summary["delta"].get("loc_trend")
    ccn_trend = summary["delta"].get("ccn_trend")
    if loc_trend is not None:
        lines.append(f"- LOC trend: {loc_trend:+.2%}")
    if ccn_trend is not None:
        lines.append(f"- CCN trend: {ccn_trend:+.2%}")
    return lines


def render_markdown(summary: dict[str, Any]) -> str:
    lines = _render_diff_header(summary)
    lines.extend(_render_diff_delta(summary))
    return "\n".join(lines) + "\n"


def _render_file_summary(summary: dict[str, Any]) -> list[str]:
    lines = [
        f"# Diff granular — {summary['project']}",
        "",
        "## Summary",
        f"- Monitored files: {summary['summary']['total_files']}",
        f"- Adicionados: {summary['summary']['added_files']}",
        f"- Removidos: {summary['summary']['removed_files']}",
        f"- Alterados: {summary['summary']['changed_files']}",
        "",
    ]
    if summary.get("threshold_ccn"):
        lines.append(
            f"- Above CCN threshold ({summary['threshold_ccn']}): {summary['summary']['over_threshold_files']}"
        )
    return lines


def _render_file_changes(files: list[dict[str, Any]]) -> list[str]:
    lines = ["", "## Changed files", ""]
    items = [item for item in files if item.get("ccn_delta") is not None and item["ccn_delta"] != 0]
    if not items:
        lines.append("No per-file changes.")
    else:
        for item in items:
            base = item.get("base") or {}
            latest = item.get("latest") or {}
            lines.append(
                f"- `{item['path']}` CCN {base.get('ccn', '?')} -> {latest.get('ccn', '?')} ({item.get('ccn_delta', 0):+.2f})"
            )
    return lines


def _render_threshold(files: list[dict[str, Any]]) -> list[str]:
    lines = ["", "## Above threshold", ""]
    over = [item for item in files if item.get("over_threshold")]
    if not over:
        lines.append("No files above threshold.")
    else:
        for item in over:
            latest = item.get("latest") or {}
            lines.append(f"- `{item['path']}` CCN {latest.get('ccn', '?')}")
    return lines


def render_file_markdown(summary: dict[str, Any]) -> str:
    lines = _render_file_summary(summary)
    lines.extend(_render_file_changes(summary["files"]))
    lines.extend(_render_threshold(summary["files"]))
    return "\n".join(lines) + "\n"


CI_RULES: list[tuple[str, str, str]] = [
    # (key_delta, key_message, format_string)
    ("ccn_trend", "trend", "CCN increased by {:.2%}"),
    ("loc_trend", "trend", "LOC increased by {:.2%}"),
    ("warnings", "absolute", "Warnings increased from {} to {}"),
    ("ccn", "regression", "CCN regressed from {} to {}"),
    ("loc", "decrease", "LOC decreased from {} to {}"),
]


def _detect_ci_failures(summary: dict[str, Any]) -> list[str]:
    """Check summary against CI rules and return list of failure messages."""
    base = summary["base"]
    latest = summary["latest"]
    delta = summary["delta"]

    failures = []
    for key, rule_type, fmt in CI_RULES:
        if rule_type == "trend":
            val = delta.get(key)
            if val is not None and val > 0:
                failures.append(fmt.format(val))
        elif rule_type == "absolute":
            lv = latest.get(key) or 0
            bv = base.get(key) or 0
            if lv > bv:
                failures.append(fmt.format(bv, lv))
        elif rule_type == "regression":
            lv = latest.get(key)
            bv = base.get(key) or 0
            if lv is not None and bv > 0 and lv > bv:
                failures.append(fmt.format(bv, lv))
        elif rule_type == "decrease":
            lv = latest.get(key)
            bv = base.get(key, 0)
            if lv is not None and lv < bv:
                failures.append(fmt.format(bv, lv))
    return failures


def render_ci_summary(summary: dict[str, Any]) -> str:
    failures = _detect_ci_failures(summary)

    payload = {
        "status": "failed" if failures else "passed",
        "project": summary.get("project"),
        "base": {
            "timestamp": summary["base"].get("timestamp"),
            "branch": summary["base"].get("branch"),
            "commit": summary["base"].get("commit_hash"),
            "loc": summary["base"].get("loc"),
            "ccn": summary["base"].get("ccn"),
            "warnings": summary["base"].get("warnings"),
        },
        "latest": {
            "timestamp": summary["latest"].get("timestamp"),
            "branch": summary["latest"].get("branch"),
            "commit": summary["latest"].get("commit_hash"),
            "loc": summary["latest"].get("loc"),
            "ccn": summary["latest"].get("ccn"),
            "warnings": summary["latest"].get("warnings"),
            "dirty": summary["latest"].get("dirty"),
        },
        "delta": {
            "loc": summary["delta"].get("loc"),
            "loc_trend": summary["delta"].get("loc_trend"),
            "ccn": summary["delta"].get("ccn"),
            "ccn_trend": summary["delta"].get("ccn_trend"),
            "warnings": summary["delta"].get("warnings"),
        },
        "failures": failures,
    }
    return json.dumps(payload, indent=2)
