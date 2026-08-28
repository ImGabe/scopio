from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .types import AuditResult


def _enrich_results(results: list[AuditResult]) -> list[dict[str, Any]]:
    """Parse tool_versions JSON strings into dicts for clean output."""
    enriched: list[dict[str, Any]] = []
    for r in results:
        item: dict[str, Any] = dict(r)
        tool_versions = item.get("tool_versions")
        if isinstance(tool_versions, str):
            try:
                item["tool_versions"] = json.loads(tool_versions)
            except json.JSONDecodeError:
                item["tool_versions"] = {}
        enriched.append(item)
    return enriched


def _tools_str(r: dict[str, Any]) -> str:
    tv = r.get("tool_versions") or {}
    tools: dict[str, Any] = tv if isinstance(tv, dict) else {}
    return "; ".join(f"{k}={v}" for k, v in tools.items())


def _export_json(output_dir: Path, enriched: list[dict[str, Any]]) -> None:
    with (output_dir / "scopio.json").open("w") as f:
        json.dump(enriched, f, indent=2, default=str)


def _export_csv(output_dir: Path, enriched: list[dict[str, Any]]) -> None:
    headers = [
        "Project",
        "Language",
        "Files",
        "LOC",
        "SCC_Code",
        "NLOC",
        "Avg_CCN",
        "Warnings",
        "Commits",
        "Last_Commit",
        "Author",
        "Branch",
        "Dirty",
        "Runs",
        "Duration (s)",
        "Tools",
    ]
    with (output_dir / "scopio.csv").open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        for _i, r in enumerate(enriched):
            writer.writerow(
                [
                    r["project"],
                    r["language"],
                    r["files"],
                    r["loc"],
                    r["code"],
                    r["nloc"],
                    f"{r['ccn']:.1f}",
                    r["warnings"],
                    r["commits"],
                    r["last_commit_date"],
                    r["author"],
                    r["branch"],
                    str(bool(r["dirty"])).lower(),
                    r.get("runs_count") or 1,
                    r.get("duration_seconds") or "",
                    _tools_str(r),
                ]
            )


def _export_markdown(output_dir: Path, enriched: list[dict[str, Any]]) -> None:
    lines = [
        "# Project Metrics Summary",
        "",
        "| Project | Language | Files | LOC | Code | NLOC | Avg CCN | Warnings | Commits | Last Commit | Author | Branch | Dirty | Runs | Duration | Tools |",
        "|---------|----------|------:|----:|-----:|-----:|--------:|--------:|--------:|-------------|--------|-------|------|-----:|--------:|-------|",
    ]
    for r in enriched:
        lines.append(
            f"| **{r['project']}** | {r['language']} | {r['files']} | {r['loc']} | {r['code']} | {r['nloc']} | {r['ccn']:.1f} | {r['warnings']} | {r['commits']} | {r['last_commit_date']} | {r['author']} | {r['branch']} | {str(bool(r['dirty'])).lower()} | {r.get('runs_count') or 1} | {r.get('duration_seconds') or '-'} | {_tools_str(r)} |"
        )
    (output_dir / "scopio.md").write_text("\n".join(lines) + "\n")


def export_outputs(output_dir: Path, results: list[AuditResult]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    enriched = _enrich_results(results)
    _export_json(output_dir, enriched)
    _export_csv(output_dir, enriched)
    _export_markdown(output_dir, enriched)
