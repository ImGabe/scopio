from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import Any

from scopio.types import GitInfo, LizardFile, LizardSummary, SccRecord


def run_cmd(path: Path, cmd: list[str]) -> str:
    try:
        res = subprocess.run(cmd, cwd=path, capture_output=True, text=True, timeout=30)
        return res.stdout.strip()
    except Exception as exc:  # pragma: no cover
        _log = logging.getLogger("scopio")
        _log.warning(json.dumps({"event": "run_cmd_error", "cmd": " ".join(cmd), "error": str(exc)}))
        return ""


def fetch_git_info(path: Path) -> GitInfo:
    if not (path / ".git").is_dir():
        return {
            "commits": 0,
            "branch": "n/a",
            "last_commit_date": "never",
            "author": "",
            "dirty": False,
            "commit_hash": "n/a",
        }

    commits = run_cmd(path, ["git", "rev-list", "--count", "HEAD"])
    branch = run_cmd(path, ["git", "branch", "--show-current"])
    date = run_cmd(path, ["git", "log", "-1", "--format=%ad", "--date=short"])
    author = run_cmd(path, ["git", "log", "-1", "--format=%an"])
    commit_hash = run_cmd(path, ["git", "rev-parse", "HEAD"])
    status = run_cmd(path, ["git", "status", "--porcelain"])

    return {
        "commits": int(commits) if commits.isdigit() else 0,
        "branch": branch or "unknown",
        "last_commit_date": date or "never",
        "author": author,
        "dirty": bool(status),
        "commit_hash": commit_hash or "n/a",
    }


def fetch_scc_metrics(proj_path: Path, excludes: list[str]) -> list[SccRecord]:
    cmd = [
        "scc",
        str(proj_path),
        "--no-cocomo",
        "--format",
        "json",
    ]
    if excludes:
        cmd.extend(["--exclude-dir", ",".join(excludes)])

    res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if res.returncode != 0:
        return []
    try:
        data = json.loads(res.stdout or "[]")
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


def parse_lizard_csv(output: str) -> LizardSummary:
    import csv as csv_mod
    import io

    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if not lines:
        return {"nloc": 0, "ccn": 0.0, "warnings": 0, "files": []}

    reader = csv_mod.reader(io.StringIO(output))
    by_path: dict[str, dict[str, Any]] = {}
    total_nloc = 0
    func_ccns: list[float] = []
    warning_count = 0

    for row in reader:
        if len(row) < 7:
            continue
        try:
            nloc = int(row[0])
            ccn = float(row[1])
            file_path = str(row[6])
        except (IndexError, ValueError):
            continue

        total_nloc += nloc
        func_ccns.append(ccn)

        entry = by_path.setdefault(
            file_path,
            {
                "path": file_path,
                "nloc": 0,
                "ccn": 0.0,
                "warnings": 0,
            },
        )
        entry["nloc"] += nloc
        entry["ccn"] = max(entry["ccn"], ccn)

    total_ccn = round(sum(func_ccns) / len(func_ccns), 1) if func_ccns else 0.0

    if func_ccns and total_ccn == 0.0:
        logger = logging.getLogger("scopio")
        logger.warning(
            json.dumps(
                {
                    "event": "lizard_parse_suspicious",
                    "files_count": len(by_path),
                    "total_nloc": total_nloc,
                    "ccn": total_ccn,
                }
            )
        )

    from typing import cast

    ccn_max = round(max(func_ccns), 1) if func_ccns else 0.0
    aggregated_files = list(by_path.values())

    return {
        "nloc": total_nloc,
        "ccn": total_ccn,
        "ccn_max": ccn_max,
        "warnings": warning_count,
        "files": [cast(LizardFile, fm) for fm in aggregated_files],
    }


def fetch_lizard_metrics(proj_path: Path, extra_excludes: list[str]) -> LizardSummary:
    cmd = ["lizard", "--csv", str(proj_path), *extra_excludes]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if res.returncode != 0:
        return {"nloc": 0, "ccn": 0.0, "warnings": 0, "files": []}
    return parse_lizard_csv(res.stdout)
