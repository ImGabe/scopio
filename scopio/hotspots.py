from __future__ import annotations

import csv
import io
import json
import math
from pathlib import Path
from typing import TypedDict

from scopio.db import open_db


class HotspotRecord(TypedDict, total=False):
    path: str
    nloc: int
    ccn: float
    warnings: int
    changes: int
    score: float
    risk_level: str


def compute_hotspots(db_path: Path, project: str, limit: int = 10) -> list[HotspotRecord]:
    """Compute code hotspots ranking per file based on Complexity (CCN) and Churn (Changes).

    Formula: Score = CCN * (1 + log2(changes + 1)) + (warnings * 1.5)
    """
    if not db_path.exists():
        return []

    with open_db(db_path) as conn:
        # Fetch file_metrics from recent audits for project
        rows = conn.execute(
            """
            SELECT path as file_path, nloc, ccn, warnings, COUNT(*) as changes_count, MAX(ccn) as max_ccn
            FROM file_metrics
            JOIN metrics ON file_metrics.audit_id = metrics.audit_id
            WHERE metrics.project = ?
            GROUP BY path
            ORDER BY max_ccn DESC

            """,
            (project,),
        ).fetchall()

    hotspots: list[HotspotRecord] = []
    for r in rows:
        f_path = str(r["file_path"])
        nloc = int(r["nloc"] or 0)
        ccn = float(r["max_ccn"] or r["ccn"] or 0.0)
        warnings = int(r["warnings"] or 0)
        changes = int(r["changes_count"] or 1)

        # Hotspot Score formula
        churn_factor = 1.0 + math.log2(changes + 1)
        score = round((ccn * churn_factor) + (warnings * 1.5), 1)

        if score >= 30.0:
            risk = "HIGH"
        elif score >= 15.0:
            risk = "MEDIUM"
        else:
            risk = "LOW"

        hotspots.append(
            {
                "path": f_path,
                "nloc": nloc,
                "ccn": ccn,
                "warnings": warnings,
                "changes": changes,
                "score": score,
                "risk_level": risk,
            }
        )

    hotspots.sort(key=lambda x: x["score"], reverse=True)
    return hotspots[:limit]


def render_hotspots(hotspots: list[HotspotRecord], fmt: str = "text") -> str:
    """Render hotspots list in text, json, csv or markdown formats."""
    if fmt == "json":
        return json.dumps(hotspots, indent=2)

    if fmt == "csv":
        out = io.StringIO()
        writer = csv.DictWriter(out, fieldnames=["path", "nloc", "ccn", "warnings", "changes", "score", "risk_level"])
        writer.writeheader()
        writer.writerows(hotspots)
        return out.getvalue()

    if fmt == "markdown":
        lines = [
            "# 🔥 Code Hotspots Analysis",
            "",
            "| File Path | NLOC | Max CCN | Warnings | Audited Changes | Hotspot Score | Risk Level |",
            "| :--- | :---: | :---: | :---: | :---: | :---: | :---: |",
        ]
        for h in hotspots:
            badge = "HIGH" if h["risk_level"] == "HIGH" else ("MEDIUM" if h["risk_level"] == "MEDIUM" else "LOW")
            lines.append(
                f"| `{h['path']}` | {h['nloc']} | {h['ccn']:.1f} | {h['warnings']} | {h['changes']} | **{h['score']:.1f}** | {badge} |"
            )
        return "\n".join(lines)

    # Text format (default)
    header = f"{'Rank':<5} {'Risk':<10} {'Score':<8} {'CCN':<6} {'Changes':<8} {'File Path'}"
    divider = "-" * 80
    lines = ["Code Hotspots Ranking (Complexity x Churn)", divider, header, divider]
    for i, h in enumerate(hotspots, 1):
        risk_icon = "HIGH" if h["risk_level"] == "HIGH" else ("MEDIUM" if h["risk_level"] == "MEDIUM" else "LOW")
        lines.append(f"{i:<5} {risk_icon:<10} {h['score']:<8.1f} {h['ccn']:<6.1f} {h['changes']:<8} {h['path']}")
    lines.append(divider)
    return "\n".join(lines)
