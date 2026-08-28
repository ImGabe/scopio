from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


def export_outputs(output_dir: Path, results: list[dict[str, Any]]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    # Enrich results with tool versions and duration for JSON export
    enriched = []
    for r in results:
        item = dict(r)
        tool_versions = item.get("tool_versions")
        if isinstance(tool_versions, str):
            try:
                item["tool_versions"] = json.loads(tool_versions)
            except json.JSONDecodeError:
                item["tool_versions"] = {}
        enriched.append(item)

    with (output_dir / "scopio.json").open("w") as f:
        json.dump(enriched, f, indent=2, default=str)

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
        for r in enriched:
            tools = r.get("tool_versions") or {}
            tools_str = "; ".join(f"{k}={v}" for k, v in tools.items())
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
                    tools_str,
                ]
            )

    lines = [
        "# Project Metrics Summary",
        "",
        "| Project | Language | Files | LOC | Code | NLOC | Avg CCN | Warnings | Commits | Last Commit | Author | Branch | Dirty | Runs | Duration | Tools |",
        "|---------|----------|------:|----:|-----:|-----:|--------:|--------:|--------:|-------------|--------|-------|------|-----:|--------:|-------|",
    ]
    for r in enriched:
        tools = r.get("tool_versions") or {}
        tools_str = "; ".join(f"{k}={v}" for k, v in tools.items())
        lines.append(
            f"| **{r['project']}** | {r['language']} | {r['files']} | {r['loc']} | {r['code']} | {r['nloc']} | {r['ccn']:.1f} | {r['warnings']} | {r['commits']} | {r['last_commit_date']} | {r['author']} | {r['branch']} | {str(bool(r['dirty'])).lower()} | {r.get('runs_count') or 1} | {r.get('duration_seconds') or '-'} | {tools_str} |"
        )
    (output_dir / "scopio.md").write_text("\n".join(lines) + "\n")
