from __future__ import annotations

import json
import logging
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tomllib
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar, TypedDict

from .db import open_db
from .formats import export_outputs
from .types import AuditResult, GitInfo, LizardFile, LizardSummary, SccRecord


class ConfigError(Exception):
    pass


class _JsonFormatter(logging.Formatter):
    """Formatter that ensures log records produce valid JSON."""

    def format(self, record: logging.LogRecord) -> str:
        record.msg = (
            json.dumps(record.msg) if not isinstance(record.msg, str) or not record.msg.startswith('"') else record.msg
        )
        return super().format(record)


def _setup_logging(verbose: bool = False, quiet: bool = False) -> logging.Logger:
    logger = logging.getLogger("scopio")
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setLevel(logging.DEBUG if verbose else logging.INFO)
        if quiet:
            handler.setLevel(logging.ERROR)
        formatter = _JsonFormatter(
            '{"ts": "%(asctime)s", "level": "%(levelname)s", "msg": %(message)s}',
            datefmt="%Y-%m-%dT%H:%M:%SZ",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    return logger


def _load_config(path: Path) -> dict[str, Any]:
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except (tomllib.TOMLDecodeError, FileNotFoundError) as exc:
        raise ConfigError(f"Invalid config file: {path} — {exc}") from exc


def _ensure_deps() -> None:
    for cmd in ["scc", "lizard", "git"]:
        if not shutil.which(cmd):
            raise ConfigError(f"Missing dependency: {cmd}")


def _run_cmd(path: Path, cmd: list[str]) -> str:
    try:
        res = subprocess.run(cmd, cwd=path, capture_output=True, text=True, timeout=30)
        return res.stdout.strip()
    except Exception as exc:  # pragma: no cover
        _log = logging.getLogger("scopio")
        _log.warning(json.dumps({"event": "run_cmd_error", "cmd": " ".join(cmd), "error": str(exc)}))
        return ""


def _git_info(path: Path) -> GitInfo:
    from scopio.collect.run.runner import fetch_git_info

    return fetch_git_info(path)


def _run_tool_version(cmd: str) -> str:
    if not shutil.which(cmd):
        return ""
    try:
        res = subprocess.run([cmd, "--version"], capture_output=True, text=True, timeout=10)
        return (res.stdout or res.stderr).strip().splitlines()[0]
    except Exception as exc:
        return f"ERROR:{exc}"


class _ToolVersionSpec(TypedDict):
    min: tuple[int, int]
    max: tuple[int, int]
    hint: str


EXPECTED_VERSIONS: dict[str, _ToolVersionSpec] = {
    "scc": {"min": (3, 3), "max": (4, 0), "hint": "scc >=3.3,<4.0"},
    "lizard": {"min": (1, 24), "max": (1, 25), "hint": "lizard >=1.24,<1.25"},
}


def _validate_tool_versions(versions: dict[str, str]) -> list[str]:
    """Check detected tool versions against the expected range.

    Returns a list of warning messages (empty = all good).
    """
    warnings: list[str] = []
    for cmd, spec in EXPECTED_VERSIONS.items():
        hint = spec["hint"]
        raw = versions.get(cmd, "")
        if not raw:
            warnings.append(f"{cmd}: not found, expected {hint}")
            continue
        match = re.search(r"(\d+)\.(\d+)", raw)
        if not match:
            warnings.append(f"{cmd}: version '{raw}' unparseable, expected {hint}")
            continue
        version = (int(match.group(1)), int(match.group(2)))
        if not (spec["min"] <= version < spec["max"]):
            warnings.append(f"{cmd}: version {version[0]}.{version[1]} detected, expected {hint}")
    return warnings


def _tool_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for cmd in ["scc", "lizard"]:
        version = _run_tool_version(cmd)
        if version:
            versions[cmd] = version
    return versions


def _parse_lizard_csv(output: str) -> LizardSummary:
    """Parse lizard --csv output into LizardSummary.

    CSV format (one line per function):
    NLOC,CCN,token,PARAM,length,location,file,function,function_long,start_line,end_line
    Aggregates per-function entries into per-file summary records.
    """
    import csv as csv_mod
    import io

    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if not lines:
        return {"nloc": 0, "ccn": 0.0, "warnings": 0, "files": [], "offenders": []}

    reader = csv_mod.reader(io.StringIO(output))
    by_path: dict[str, dict[str, Any]] = {}
    total_nloc = 0
    func_ccns: list[float] = []
    offenders_list: list[dict[str, Any]] = []
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

        func_name = str(row[7]) if len(row) >= 8 else "global"
        start_line = int(row[9]) if len(row) >= 10 and row[9].isdigit() else None
        offenders_list.append({"file": file_path, "function": func_name, "ccn": ccn, "line": start_line})

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
    offenders_list.sort(key=lambda x: x["ccn"], reverse=True)
    top_5 = offenders_list[:5]

    return {
        "nloc": total_nloc,
        "ccn": total_ccn,
        "ccn_max": ccn_max,
        "warnings": warning_count,
        "files": [cast(LizardFile, fm) for fm in aggregated_files],
        "offenders": [cast(Any, off) for off in top_5],
    }


def _run_scc(proj_path: Path, excludes: list[str]) -> list[SccRecord]:
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


def _run_lizard(proj_path: Path, extra_excludes: list[str]) -> LizardSummary:
    cmd = ["lizard", "--csv", str(proj_path), *extra_excludes]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if res.returncode != 0:
        return {"nloc": 0, "ccn": 0.0, "warnings": 0, "files": []}
    return _parse_lizard_csv(res.stdout)


def _language_from_scc(scc_data: list[SccRecord], ignored: set[str]) -> str:
    valid = [d for d in scc_data if d.get("Name") not in ignored]
    candidates = valid if valid else scc_data
    if not candidates:
        return "Unknown"
    candidates.sort(key=lambda d: d.get("Code", 0), reverse=True)
    name = candidates[0].get("Name")
    return str(name) if name else "Unknown"


def _parse_gitignore(gitignore_path: Path) -> tuple[list[str], list[str]]:
    """Parse a .gitignore file using pathspec and extract exclusion patterns for scc and lizard."""
    import pathspec

    scc_ex: list[str] = []
    lizard_ex: list[str] = []
    if not gitignore_path.is_file():
        return scc_ex, lizard_ex
    try:
        lines = gitignore_path.read_text().splitlines()
    except OSError:
        return scc_ex, lizard_ex

    # Validate syntax with pathspec
    _spec = pathspec.GitIgnoreSpec.from_lines(lines)

    for line in lines:
        raw = line.strip()
        if not raw or raw.startswith("#"):
            continue
        cleaned = raw.rstrip("/")
        if "/" not in cleaned and not any(c in cleaned for c in "*?["):
            scc_ex.append(cleaned)
            lizard_ex.extend(["-x", f"*/{cleaned}/*", "-x", f"*/{cleaned}"])
        else:
            lizard_ex.extend(["-x", raw])

    return scc_ex, lizard_ex


def _collect_ingest_sources(proj_path: Path, sources: list[Any]) -> tuple[list[Any], int, int, list[Any]]:
    ingest_results: list[Any] = []
    ingest_errors = 0
    ingest_warnings = 0
    ingest_findings: list[Any] = []

    from scopio.collect.ingest.parsers import ingest_linter_report

    for src in sources:
        if not isinstance(src, dict):
            continue
        src_name = str(src.get("name", "linter"))
        src_path = src.get("path")
        if not src_path:
            continue
        report_file = proj_path / str(src_path)
        res = ingest_linter_report(report_file, tool_hint=src_name)
        ingest_results.append(res)
        ingest_errors += int(res.get("errors", 0))
        ingest_warnings += int(res.get("warnings", 0))
        for f in res.get("findings", []):
            ingest_findings.append(f)

    return ingest_results, ingest_errors, ingest_warnings, ingest_findings


def _check_single_gate_failure(
    result: AuditResult,
    limit_ccn: float,
    limit_warnings: int,
    limit_function_ccn: float | None,
    max_errors: int | None,
    max_warnings_ingest: int | None,
) -> bool:
    if result["ccn"] > limit_ccn or result["warnings"] > limit_warnings:
        return True
    if limit_function_ccn is not None and float(result.get("ccn_max") or 0.0) > limit_function_ccn:
        return True
    if max_errors is not None and result.get("ingest_errors", 0) > max_errors:
        return True
    if max_warnings_ingest is not None and result.get("ingest_warnings", 0) > max_warnings_ingest:
        return True
    return False


class MetricsAuditor:
    def _table_columns(self, conn: sqlite3.Connection, table: str) -> set[str]:
        """Return the set of column names for a table (safe — table arg is internal constant)."""
        result = conn.execute(f"PRAGMA table_info({table})").fetchall()
        return {row["name"] for row in result}

    def __init__(self, config_path: Path, projects_dir: Path, output_dir: Path) -> None:
        self.config_path = config_path
        self.projects_dir = projects_dir.resolve()
        self.output_dir = output_dir.resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.config = _load_config(config_path)
        _ensure_deps()
        self.db_path = self.output_dir / "scopio.db"
        self._init_db()

    _MIGRATIONS: ClassVar[list[tuple[int, str]]] = [
        (
            1,
            """CREATE TABLE IF NOT EXISTS metrics (
            audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
            project TEXT NOT NULL, language TEXT, files INTEGER, loc INTEGER,
            code INTEGER, nloc INTEGER, ccn REAL, ccn_max INTEGER,
            warnings INTEGER, commits INTEGER, last_commit_date TEXT, author TEXT,
            branch TEXT, dirty INTEGER, commit_hash TEXT,
            tool_versions TEXT, duration_seconds REAL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_metrics_project ON metrics(project);
        CREATE UNIQUE INDEX IF NOT EXISTS uq_metrics_run
            ON metrics(project, branch, commit_hash);""",
        ),
        (2, "ALTER TABLE metrics ADD COLUMN ccn_max INTEGER"),
        (
            4,
            "ALTER TABLE metrics ADD COLUMN coverage REAL;"
            + "ALTER TABLE metrics ADD COLUMN duplication REAL;"
            + "ALTER TABLE metrics ADD COLUMN outdated_dependencies INTEGER",
        ),
        (
            5,
            """CREATE TABLE IF NOT EXISTS metrics_history (
            audit_id INTEGER PRIMARY KEY, project TEXT NOT NULL,
            language TEXT, timestamp DATETIME, loc INTEGER, ccn REAL, warnings INTEGER,
            FOREIGN KEY(audit_id) REFERENCES metrics(audit_id)
        );
        CREATE INDEX IF NOT EXISTS idx_history_project
            ON metrics_history(project, timestamp);""",
        ),
        (
            6,
            """CREATE TABLE IF NOT EXISTS file_metrics (
            file_metric_id INTEGER PRIMARY KEY AUTOINCREMENT,
            audit_id INTEGER, project TEXT NOT NULL,
            path TEXT NOT NULL, nloc INTEGER, ccn REAL, warnings INTEGER,
            FOREIGN KEY(audit_id) REFERENCES metrics(audit_id)
        );
        CREATE INDEX IF NOT EXISTS idx_file_metrics_audit
            ON file_metrics(audit_id, path);""",
        ),
        (7, "ALTER TABLE metrics ADD COLUMN runs_count INTEGER NOT NULL DEFAULT 1"),
        (8, "ALTER TABLE metrics_history ADD COLUMN ccn_max REAL"),
        (
            9,
            """CREATE TABLE IF NOT EXISTS audit_ingest_summary (
            audit_id INTEGER PRIMARY KEY,
            source TEXT NOT NULL,
            status TEXT NOT NULL,
            errors INTEGER DEFAULT 0,
            warnings INTEGER DEFAULT 0,
            info INTEGER DEFAULT 0,
            FOREIGN KEY(audit_id) REFERENCES metrics(audit_id)
        );
        CREATE TABLE IF NOT EXISTS file_findings (
            finding_id INTEGER PRIMARY KEY AUTOINCREMENT,
            audit_id INTEGER,
            project TEXT NOT NULL,
            source TEXT NOT NULL,
            path TEXT NOT NULL,
            rule TEXT NOT NULL,
            severity TEXT NOT NULL,
            message TEXT,
            line INTEGER,
            FOREIGN KEY(audit_id) REFERENCES metrics(audit_id)
        );
        CREATE INDEX IF NOT EXISTS idx_file_findings_audit ON file_findings(audit_id, path);""",
        ),
    ]

    def _init_db(self) -> None:
        with open_db(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER PRIMARY KEY
                )
                """
            )
            row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
            version = row[0] if row and row[0] is not None else 0

            # Legacy: ensure schema_version exists for migrations
            if version == 0:
                conn.execute("INSERT OR IGNORE INTO schema_version(version) VALUES (0)")

            for ver, sql in self._MIGRATIONS:
                if version < ver:
                    if sql.startswith("ALTER"):
                        match = re.search(r"ALTER\s+TABLE\s+(\w+)\s+ADD\s+COLUMN\s+(\w+)", sql)
                        table_name = match.group(1) if match else "metrics"
                        col_name = match.group(2) if match else ""
                        columns = self._table_columns(conn, table_name)
                        if col_name and col_name not in columns:
                            conn.executescript(sql)
                    else:
                        conn.executescript(sql)
                    conn.execute("INSERT OR IGNORE INTO schema_version(version) VALUES (?)", (ver,))
                    version = ver

    def _get_excludes(self, proj_path: Path) -> tuple[list[str], list[str]]:
        scc_excludes = list(self.config.get("filters", {}).get("global_dirs", []))
        lizard_excludes: list[str] = []

        if self.config.get("discovery", {}).get("ignore_hidden", True):
            for entry in proj_path.iterdir():
                if entry.is_dir() and entry.name.startswith("."):
                    scc_excludes.append(entry.name)
                    lizard_excludes.extend(["-x", f"*/{entry.name}/*"])
                    lizard_excludes.extend(["-x", f"*/{entry.name}"])

        for ignored in self.config.get("filters", {}).get("global_dirs", []):
            lizard_excludes.extend(["-x", f"*/{ignored}/*"])
            lizard_excludes.extend(["-x", f"*/{ignored}"])

        for pattern in self.config.get("filters", {}).get("minified_files", []):
            lizard_excludes.extend(["-x", pattern])

        # Auto-parse .gitignore
        gitignore_file = proj_path / ".gitignore"
        git_scc, git_lizard = _parse_gitignore(gitignore_file)
        scc_excludes.extend(git_scc)
        lizard_excludes.extend(git_lizard)

        ignore_file = proj_path / ".ignoremetrics"
        if ignore_file.is_file():
            for line in ignore_file.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    scc_excludes.append(line)
                    lizard_excludes.extend(["-x", f"*/{line}/*"])
                    lizard_excludes.extend(["-x", f"*/{line}"])

        return scc_excludes, lizard_excludes

    def _audit_project(self, target_rel_path: str) -> AuditResult | None:
        proj_path = (self.projects_dir / target_rel_path).resolve()

        if not proj_path.exists() and target_rel_path == self.projects_dir.name:
            proj_path = self.projects_dir.resolve()

        if not proj_path.is_dir():
            logging.getLogger("scopio").warning(
                json.dumps({"event": "directory_not_found", "project": target_rel_path})
            )
            return None

        if not proj_path.is_relative_to(self.projects_dir.resolve()) and proj_path != self.projects_dir.resolve():
            logging.getLogger("scopio").error(
                json.dumps({"event": "path_traversal", "project": target_rel_path, "resolved": str(proj_path)})
            )
            return None

        git = _git_info(proj_path)
        scc_excludes, lizard_excludes = self._get_excludes(proj_path)

        start = datetime.now(UTC)
        scc_data = _run_scc(proj_path, scc_excludes)
        lizard = _run_lizard(proj_path, lizard_excludes)

        ignored = set(self.config.get("filters", {}).get("ignored_langs", []))
        language = _language_from_scc(scc_data, ignored)

        loc = sum(item.get("Lines", 0) for item in scc_data)
        code = sum(item.get("Code", 0) for item in scc_data)
        files = sum(item.get("Count", 0) for item in scc_data)
        nloc = lizard.get("nloc", 0)
        ccn = lizard.get("ccn", 0.0)
        ccn_max = lizard.get("ccn_max", 0.0)
        warnings = lizard.get("warnings", 0)
        file_metrics = lizard.get("files", [])

        if nloc == 0 and any(proj_path.glob("*.fsproj")):
            warnings = self._fs_sharp_fallback(proj_path, warnings)

        # Ingest linter reports
        ingest_config = self.config.get("ingest", {}) or {}
        sources = ingest_config.get("sources", []) or []
        ingest_results, ingest_errors, ingest_warnings, ingest_findings = _collect_ingest_sources(proj_path, sources)

        if ingest_warnings > 0:
            warnings = ingest_warnings

        duration = (datetime.now(UTC) - start).total_seconds()
        tool_versions = _tool_versions()

        from typing import cast

        return cast(
            AuditResult,
            {
                "project": proj_path.name,
                "language": language,
                "files": files,
                "loc": loc,
                "code": code,
                "nloc": nloc,
                "ccn": ccn,
                "ccn_max": ccn_max,
                "warnings": warnings,
                "commits": git["commits"],
                "last_commit_date": git["last_commit_date"],
                "author": git["author"],
                "branch": git["branch"],
                "dirty": int(git["dirty"]),
                "commit_hash": git["commit_hash"],
                "tool_versions": json.dumps(tool_versions),
                "duration_seconds": duration,
                "file_metrics": file_metrics,
                "ingest_results": ingest_results,
                "ingest_errors": ingest_errors,
                "ingest_warnings": ingest_warnings,
                "ingest_findings": ingest_findings,
                "top_offenders": lizard.get("offenders", []),
            },
        )

    def _fs_sharp_fallback(self, proj_path: Path, warnings: int) -> int:
        dotnet_tools = str(Path.home() / ".dotnet/tools")
        path_env = os.environ.get("PATH", "")
        if dotnet_tools not in path_env:
            os.environ["PATH"] = f"{dotnet_tools}:{path_env}"

        try:
            fsproj = next(iter(proj_path.glob("*.fsproj")), None)
            if fsproj is None:
                return warnings
            res = subprocess.run(
                ["dotnet-fsharplint", "lint", str(fsproj), "--format", "human"],
                capture_output=True,
                text=True,
                timeout=120,
            )
            match = re.search(r"Summary:\s*(\d+)\s*warnings", res.stdout)
            if match:
                return int(match.group(1))
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            logger = logging.getLogger("scopio")
            logger.warning(
                json.dumps({"event": "fs_fallback_error", "project": str(proj_path.name), "error": str(exc)})
            )

        return warnings

    def _upsert_metrics_row(self, conn: sqlite3.Connection, result: AuditResult) -> int:
        params = dict(result)
        params.setdefault("ccn_max", None)
        cursor = conn.execute(
            """
            INSERT INTO metrics
            (project, language, files, loc, code, nloc, ccn, ccn_max, warnings,
             commits, last_commit_date, author, branch, dirty, commit_hash,
             tool_versions, duration_seconds, timestamp)
            VALUES
            (:project, :language, :files, :loc, :code, :nloc, :ccn, :ccn_max, :warnings,
             :commits, :last_commit_date, :author, :branch, :dirty, :commit_hash,
             :tool_versions, :duration_seconds, CURRENT_TIMESTAMP)
            ON CONFLICT(project, branch, commit_hash)
            DO UPDATE SET
                language = excluded.language, files = excluded.files,
                loc = excluded.loc, code = excluded.code, nloc = excluded.nloc,
                ccn = excluded.ccn, ccn_max = excluded.ccn_max, warnings = excluded.warnings,
                commits = excluded.commits, last_commit_date = excluded.last_commit_date,
                author = excluded.author, dirty = excluded.dirty,
                tool_versions = excluded.tool_versions,
                duration_seconds = excluded.duration_seconds,
                timestamp = excluded.timestamp, runs_count = runs_count + 1
            """,
            params,
        )
        audit_id = cursor.lastrowid
        if cursor.rowcount == 0 or not audit_id:
            row = conn.execute(
                "SELECT audit_id FROM metrics WHERE project = ? AND branch = ? AND commit_hash = ?",
                (result["project"], result["branch"], result["commit_hash"]),
            ).fetchone()
            if not row:
                return 0
            audit_id = row["audit_id"].__index__()
        return audit_id

    def _log_metrics_history(self, conn: sqlite3.Connection, audit_id: int, result: AuditResult) -> None:
        conn.execute(
            """
            INSERT OR IGNORE INTO metrics_history
            (audit_id, project, language, loc, ccn, ccn_max, warnings)
            VALUES (:audit_id, :project, :language, :loc, :ccn, :ccn_max, :warnings)
            """,
            {
                "audit_id": audit_id,
                "project": result["project"],
                "language": result.get("language"),
                "loc": result.get("loc"),
                "ccn": result.get("ccn"),
                "ccn_max": result.get("ccn_max"),
                "warnings": result.get("warnings"),
            },
        )

    def _save_file_metrics(self, conn: sqlite3.Connection, audit_id: int, result: AuditResult) -> None:
        conn.execute("DELETE FROM file_metrics WHERE audit_id = ?", (audit_id,))
        file_metrics = result.get("file_metrics") or []
        for fm in file_metrics:
            conn.execute(
                """
                INSERT OR IGNORE INTO file_metrics
                (audit_id, project, path, nloc, ccn, warnings)
                VALUES (:audit_id, :project, :path, :nloc, :ccn, :warnings)
                """,
                {
                    "audit_id": audit_id,
                    "project": result["project"],
                    "path": fm["path"],
                    "nloc": fm["nloc"],
                    "ccn": fm["ccn"],
                    "warnings": fm.get("warnings", 0),
                },
            )

    def _save_ingest_metrics(self, conn: sqlite3.Connection, audit_id: int, result: AuditResult) -> None:
        ingest_results = result.get("ingest_results") or []
        for ir in ingest_results:
            conn.execute(
                """
                INSERT OR REPLACE INTO audit_ingest_summary
                (audit_id, source, status, errors, warnings, info)
                VALUES (:audit_id, :source, :status, :errors, :warnings, :info)
                """,
                {
                    "audit_id": audit_id,
                    "source": ir.get("source", "linter"),
                    "status": ir.get("status", "clean"),
                    "errors": ir.get("errors", 0),
                    "warnings": ir.get("warnings", 0),
                    "info": ir.get("info", 0),
                },
            )

        ingest_findings = result.get("ingest_findings") or []
        conn.execute("DELETE FROM file_findings WHERE audit_id = ?", (audit_id,))
        for f in ingest_findings:
            conn.execute(
                """
                INSERT INTO file_findings
                (audit_id, project, source, path, rule, severity, message, line)
                VALUES (:audit_id, :project, :source, :path, :rule, :severity, :message, :line)
                """,
                {
                    "audit_id": audit_id,
                    "project": result["project"],
                    "source": f.get("source", "linter"),
                    "path": f.get("file", ""),
                    "rule": f.get("rule", ""),
                    "severity": f.get("severity", "warning"),
                    "message": f.get("message", ""),
                    "line": f.get("line"),
                },
            )

    def _save_results(self, results: list[AuditResult]) -> None:
        with open_db(self.db_path) as conn:
            for result in results:
                audit_id = self._upsert_metrics_row(conn, result)
                if audit_id:
                    self._log_metrics_history(conn, audit_id, result)
                    self._save_file_metrics(conn, audit_id, result)
                    self._save_ingest_metrics(conn, audit_id, result)
        export_outputs(self.output_dir, results)

    @staticmethod
    def _effective_limits(result: AuditResult, config: dict[str, Any]) -> tuple[float, int, float | None]:
        quality_gates = config.get("quality_gates", {})
        max_ccn = float(quality_gates.get("max_ccn", 10.0))
        max_warnings = int(quality_gates.get("max_warnings", 10))
        max_function_ccn = quality_gates.get("max_function_ccn")
        per_project = quality_gates.get("per_project", {}) or {}
        per_language = quality_gates.get("per_language", {}) or {}

        project_limits = per_project.get(result["project"])
        if project_limits:
            return (
                float(project_limits.get("max_ccn", max_ccn)),
                int(project_limits.get("max_warnings", max_warnings)),
                project_limits.get("max_function_ccn", max_function_ccn),
            )
        language_limits = per_language.get(result.get("language", ""))
        if language_limits:
            return (
                float(language_limits.get("max_ccn", max_ccn)),
                int(language_limits.get("max_warnings", max_warnings)),
                language_limits.get("max_function_ccn", max_function_ccn),
            )
        return max_ccn, max_warnings, max_function_ccn

    def _evaluate_quality_gates(
        self, results: list[AuditResult], config: dict[str, Any]
    ) -> tuple[list[AuditResult], list[AuditResult]]:

        quality_gates = config.get("quality_gates", {})
        max_trend_increase = float(quality_gates.get("max_ccn_trend_increase", 0.2))
        trend_sensitive = set(quality_gates.get("trend_sensitive_projects", []))

        ingest_gates = quality_gates.get("ingest", {}) or {}
        max_errors = ingest_gates.get("max_errors")
        max_warnings_ingest = ingest_gates.get("max_warnings")

        gate_failures = []
        for result in results:
            limit_ccn, limit_warnings, limit_function_ccn = self._effective_limits(result, config)
            if _check_single_gate_failure(
                result, limit_ccn, limit_warnings, limit_function_ccn, max_errors, max_warnings_ingest
            ):
                gate_failures.append(result)

        trend_failures = []
        for result in results:
            if result["project"] not in trend_sensitive:
                continue
            previous = self._get_last_metrics(result["project"])
            if not previous or previous["ccn"] <= 0:
                continue
            if (result["ccn"] - previous["ccn"]) / previous["ccn"] > max_trend_increase:
                trend_failures.append(result)

        return gate_failures, trend_failures

    def _quality_gates_summary(self) -> dict[str, Any]:
        quality_gates = self.config.get("quality_gates", {})
        return {
            "max_ccn": quality_gates.get("max_ccn", 10.0),
            "max_function_ccn": quality_gates.get("max_function_ccn"),
            "max_warnings": quality_gates.get("max_warnings", 10),
            "max_ccn_trend_increase": quality_gates.get("max_ccn_trend_increase", 0.2),
        }

    def _get_last_metrics(self, project: str) -> dict[str, Any] | None:
        """Return the most recent historical audit BEFORE the current one, for trend comparison.

        Uses metrics_history (append-only) rather than metrics (upserted) to avoid
        seeing the current run when gates are evaluated before save (B3 fix).
        """
        db_path = self.db_path
        with open_db(db_path) as conn:
            row = conn.execute(
                """
                SELECT timestamp, loc, ccn, warnings
                FROM metrics_history
                WHERE project = ?
                ORDER BY timestamp DESC
                LIMIT 1
                """,
                (project,),
            ).fetchone()
        if not row:
            return None
        return {
            "timestamp": row["timestamp"],
            "loc": row["loc"],
            "ccn": row["ccn"],
            "warnings": row["warnings"],
        }

    @staticmethod
    def _resolve_workers(projects: int) -> int:
        cpu = os.cpu_count() or 1
        if projects <= 1:
            return 1
        return max(1, min(projects, cpu * 2))

    def _filter_incremental(self, targets: list[str]) -> list[str]:
        """Return only projects that changed since last audit.
        Uses Path.rglob with early-exit: stops scanning a directory as soon as
        a single recent file is found.
        """
        selected = []
        for target in targets:
            row = self._get_last_metrics(target)
            proj_path = (self.projects_dir / target).resolve()
            if not proj_path.exists() and target == self.projects_dir.name:
                proj_path = self.projects_dir.resolve()

            if not proj_path.is_relative_to(self.projects_dir.resolve()) and proj_path != self.projects_dir.resolve():
                continue
            if row is None:
                selected.append(target)
                continue

            last_run = row.get("timestamp") or ""
            if not last_run:
                selected.append(target)
                continue

            from datetime import datetime

            last_run_dt = datetime.fromisoformat(last_run).replace(tzinfo=UTC)
            found_recent = False

            for fpath in proj_path.rglob("*"):
                if not fpath.is_file():
                    continue
                try:
                    mtime = fpath.stat().st_mtime
                except OSError:
                    continue
                if datetime.fromtimestamp(mtime, tz=UTC) > last_run_dt:
                    found_recent = True
                    break  # early-exit: one recent file is enough

            if found_recent:
                selected.append(target)
        return selected

    def run(self, verbose: bool = False, quiet: bool = False, incremental: bool = False) -> dict[str, Any]:
        logger = _setup_logging(verbose=verbose, quiet=quiet)
        targets = self.config.get("discovery", {}).get("projects", [])

        # Validate tool versions at start of each run
        current_versions = _tool_versions()
        version_warnings = _validate_tool_versions(current_versions)
        for w in version_warnings:
            logger.warning(json.dumps({"event": "tool_version_diverge", "msg": w}))
        results: list[AuditResult] = []
        failures: list[dict[str, Any]] = []

        if incremental:
            targets = self._filter_incremental(targets)

        max_workers = self._resolve_workers(len(targets))
        logger.info(
            json.dumps(
                {"event": "run_start", "projects": len(targets), "incremental": incremental, "workers": max_workers}
            )
        )

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(self._audit_project, target): target for target in targets}
            for future in as_completed(futures):
                target = futures[future]
                try:
                    result = future.result()
                except Exception as exc:
                    logger.error(json.dumps({"project": target, "error": str(exc)}))
                    failures.append({"project": target, "error": str(exc)})
                    continue

                if not result:
                    continue

                results.append(result)
                logger.info(
                    json.dumps(
                        {
                            "project": result["project"],
                            "language": result["language"],
                            "files": result["files"],
                            "loc": result["loc"],
                            "ccn": round(result["ccn"], 1),
                            "warnings": result["warnings"],
                        }
                    )
                )

        results.sort(key=lambda r: r["project"].lower())

        gate_failures, trend_failures = self._evaluate_quality_gates(results, self.config)

        self._save_results(results)

        return {
            "results": results,
            "failures": failures,
            "gate_failures": gate_failures,
            "trend_failures": trend_failures,
            "quality_gates": self._quality_gates_summary(),
            "observability": {
                "projects_processed": len(results),
                "projects_failed": len(failures),
                "gate_failures": len(gate_failures),
                "trend_failures": len(trend_failures),
                "workers": max_workers,
                "duration_seconds": sum(r.get("duration_seconds") or 0 for r in results),
                "tool_versions": _tool_versions(),
            },
        }
