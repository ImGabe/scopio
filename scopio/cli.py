from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import click

from .audit import MetricsAuditor
from .db import open_db
from .diff import (
    _detect_ci_failures,
    project_diff,
    project_file_diff,
    render_ci_summary,
    render_file_markdown,
    render_github_comment,
    render_markdown,
)
from .types import AuditResult


@click.group()
@click.option("--config", default=None, help="Path to scopio.toml")
@click.option("--projects-dir", default=None, help="Root projects directory")
@click.option("--output-dir", default=None, help="Output directory")
@click.version_option()
@click.pass_context
def cli(ctx: click.Context, config: str | None, projects_dir: str | None, output_dir: str | None) -> None:
    root = Path.cwd()
    config_path = Path(config).resolve() if config else root / "scopio.toml"
    base_dir = config_path.parent if config else root
    projects_root = Path(projects_dir).resolve() if projects_dir else base_dir
    out = Path(output_dir).resolve() if output_dir else base_dir / ".scopio"
    out.mkdir(parents=True, exist_ok=True)
    ctx.obj = {
        "config_path": config_path,
        "projects_dir": projects_root,
        "output_dir": out,
    }


@cli.command()
@click.option("--verbose", is_flag=True, help="Verbose per-project logging")
@click.option("--quiet", is_flag=True, help="Suppress logging")
@click.option("--incremental", is_flag=True, help="Audit only projects changed since last run")
@click.option("--json", "json_output", is_flag=True, help="Output raw JSON observability log")
@click.pass_context
def run(ctx: click.Context, verbose: bool, quiet: bool, incremental: bool, json_output: bool) -> None:
    obj = ctx.obj
    auditor = MetricsAuditor(obj["config_path"], obj["projects_dir"], obj["output_dir"])
    summary = auditor.run(verbose=verbose, quiet=quiet, incremental=incremental)
    results = summary["results"]
    failures = summary["failures"]
    gate_failures = summary["gate_failures"]
    trend_failures = summary["trend_failures"]

    if failures:
        click.echo(f"Failures: {len(failures)} project(s) could not be audited.", err=True)

    if gate_failures:
        click.echo("\nQuality Gate Failures:", err=True)
        for r in gate_failures:
            click.echo(
                f"  [GATE FAIL] {r['project']}: CCN={r.get('ccn', 0):.1f}, MaxCCN={r.get('ccn_max', 0)}, "
                f"Warnings={r.get('warnings', 0)}, IngestErrors={r.get('ingest_errors', 0)}",
                err=True,
            )
            top = r.get("top_offenders") or []
            if top:
                click.echo("    Top Complexity Offenders:", err=True)
                for off in top[:3]:
                    func = off.get("function") or "global"
                    f_path = off.get("file") or ""
                    l_str = f":{off['line']}" if off.get("line") else ""
                    click.echo(f"      - {f_path}{l_str} -> {func} (CCN={off.get('ccn', 0)})", err=True)

    if trend_failures:
        click.echo("\nTrend Gate Failures:", err=True)
        for r in trend_failures:
            click.echo(f"  [TREND FAIL] {r['project']}: CCN={r.get('ccn', 0):.1f}", err=True)

    if failures or gate_failures or trend_failures:
        raise click.ClickException("Audit finished with failures.")

    if not json_output and not quiet:
        click.echo("\nProject Metrics Summary\n" + "-" * 75)
        click.echo(f"{'Project':<20} {'Lang':<10} {'Files':<7} {'LOC':<8} {'NLOC':<8} {'AvgCCN':<8} {'MaxCCN':<8}")
        click.echo("-" * 75)
        for r in results:
            click.echo(
                f"{r['project']:<20} {r['language']:<10} {r['files']:<7} {r['loc']:<8} {r['nloc']:<8} "
                f"{r['ccn']:<8.1f} {r.get('ccn_max') or '-':<8}"
            )
        click.echo("-" * 75)

    click.echo(f"Audit finished: {len(results)} projects.")
    if json_output or quiet:
        click.echo(json.dumps({"observability": summary["observability"]}))


def _resolve_project(ctx: click.Context, project: str | None) -> str:
    """Resolve project name automatically if omitted when only 1 project is configured."""
    if project:
        return project

    config_path: Path = ctx.obj.get("config_path")
    if config_path and config_path.exists():
        from .audit import _load_config

        try:
            cfg = _load_config(config_path)
            projects = cfg.get("discovery", {}).get("projects", [])
            if len(projects) == 1:
                proj_name = projects[0]
                if proj_name == "." or not proj_name:
                    return str(ctx.obj["projects_dir"].name)
                return str(Path(proj_name).name)
        except Exception:
            pass

    raise click.ClickException("Missing option '--project'. Must specify --project when multiple projects exist.")


@cli.command()
@click.option("--project", default=None, help="Project name (auto-detected if omitted and single project)")
@click.option("--limit", default=10, show_default=True, help="Max rows")
@click.option(
    "--format", "fmt", type=click.Choice(["text", "json"]), default="text", help="Output format (text or json)"
)
@click.pass_context
def report(ctx: click.Context, project: str | None, limit: int, fmt: str) -> None:
    proj_name = _resolve_project(ctx, project)
    db_path = ctx.obj["output_dir"] / "scopio.db"
    with open_db(db_path) as conn:
        rows = conn.execute(
            """
            SELECT project, language, files, loc, code, nloc, ccn, ccn_max, warnings,
                   commits, last_commit_date, author, branch, dirty, commit_hash, runs_count, timestamp
            FROM metrics
            WHERE project = ?
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (proj_name, limit),
        ).fetchall()

    if not rows:
        raise click.ClickException(f"No history for: {proj_name}")

    if fmt == "json":
        data = [dict(row) for row in rows]
        click.echo(json.dumps(data, indent=2))
        return

    for row in rows:
        click.echo(
            f"{row['timestamp']} | {row['branch']} | {row['commit_hash']} | "
            f"loc={row['loc']} ccn={row['ccn']} ccn_max={row['ccn_max']} warnings={row['warnings']}"
            f"{' | runs=' + str(row['runs_count']) if row['runs_count'] and row['runs_count'] > 1 else ''}"
        )


@cli.command("diff")
@click.option("--project", default=None, help="Project name (auto-detected if omitted and single project)")
@click.option(
    "--base",
    type=click.Choice(["previous", "first"]),
    default="previous",
    show_default=True,
    help="Base audit for comparison",
)
@click.option(
    "--dirty", "--uncommitted", "dirty", is_flag=True, help="Compare uncommitted working tree against last audit"
)
@click.pass_context
def diff(ctx: click.Context, project: str | None, base: str, dirty: bool) -> None:
    proj_name = _resolve_project(ctx, project)
    db_path = ctx.obj["output_dir"] / "scopio.db"
    dirty_metrics: dict[str, Any] | None = None
    if dirty:
        auditor = MetricsAuditor(ctx.obj["config_path"], ctx.obj["projects_dir"], ctx.obj["output_dir"])
        audited = auditor._audit_project(proj_name)
        if audited:
            dirty_metrics = dict(audited)

    summary = project_diff(db_path, proj_name, base=base, dirty_metrics=dirty_metrics)

    click.echo(f"Project: {proj_name}")
    click.echo(f"Base : {summary['base']['timestamp']} ({summary['base']['branch']})")
    click.echo(f"Current: {summary['latest']['timestamp']} ({summary['latest']['branch']})")
    click.echo(f"LOC  : {summary['base']['loc']} -> {summary['latest']['loc']} ({summary['delta']['loc']:+})")
    click.echo(f"CCN  : {summary['base']['ccn']} -> {summary['latest']['ccn']} ({summary['delta']['ccn']:+.2f})")
    click.echo(f"MaxCCN: {summary['base']['ccn_max']} -> {summary['latest']['ccn_max']}")
    click.echo(
        f"Warn : {summary['base']['warnings']} -> {summary['latest']['warnings']} ({summary['delta']['warnings']:+})"
    )


@cli.command("diff-report")
@click.option("--project", default=None, help="Project name (auto-detected if omitted and single project)")
@click.option("--format", "output_format", default="text", type=click.Choice(["text", "json", "md"]))
@click.option("--files", is_flag=True, help="Include per-file granular diff")
@click.option("--threshold-ccn", default=None, type=float, help="CCN threshold to highlight files")
@click.option(
    "--base",
    type=click.Choice(["previous", "first"]),
    default="previous",
    show_default=True,
    help="Base audit for comparison",
)
@click.option(
    "--dirty", "--uncommitted", "dirty", is_flag=True, help="Compare uncommitted working tree against last audit"
)
@click.pass_context
def diff_report(
    ctx: click.Context,
    project: str | None,
    output_format: str,
    files: bool,
    threshold_ccn: float | None,
    base: str,
    dirty: bool,
) -> None:
    proj_name = _resolve_project(ctx, project)
    db_path = ctx.obj["output_dir"] / "scopio.db"
    dirty_metrics: dict[str, Any] | None = None
    if dirty:
        auditor = MetricsAuditor(ctx.obj["config_path"], ctx.obj["projects_dir"], ctx.obj["output_dir"])
        audited = auditor._audit_project(proj_name)
        if audited:
            dirty_metrics = dict(audited)

    summary = project_diff(db_path, proj_name, base=base, dirty_metrics=dirty_metrics)

    if files:
        summary = project_file_diff(db_path, proj_name, threshold_ccn=threshold_ccn, base=base)  # type: ignore[assignment]

    if output_format == "json":
        click.echo(json.dumps(summary, indent=2))
    elif output_format == "md":
        if files:
            click.echo(render_file_markdown(summary))  # type: ignore[arg-type]
        else:
            click.echo(render_markdown(summary))  # type: ignore[arg-type]
    else:
        if files:
            file_summary = project_file_diff(db_path, proj_name, threshold_ccn=threshold_ccn, base=base)
            click.echo(f"Project: {proj_name}")
            click.echo(f"Monitored files: {file_summary['summary']['total_files']}")
            click.echo(f"Changed: {file_summary['summary']['changed_files']}")
            click.echo(f"Above threshold: {file_summary['summary']['over_threshold_files']}")
        else:
            base_snapshot = summary["base"]
            latest = summary["latest"]
            delta = summary["delta"]
            click.echo(f"Project: {proj_name}")
            click.echo(f"Base : {base_snapshot['timestamp']} ({base_snapshot['branch']})")
            click.echo(f"Current: {latest['timestamp']} ({latest['branch']})")
            click.echo(f"LOC  : {base_snapshot['loc']} -> {latest['loc']} ({delta['loc']:+})")
            click.echo(f"CCN  : {base_snapshot['ccn']} -> {latest['ccn']} ({delta['ccn']:+.2f})")
            click.echo(f"MaxCCN: {base_snapshot['ccn_max']} -> {latest['ccn_max']}")
            click.echo(f"Warn : {base_snapshot['warnings']} -> {latest['warnings']} ({delta['warnings']:+})")


@cli.command()
@click.option("--keep", default=50, show_default=True, help="Keep last N rows")
@click.pass_context
def clean(ctx: click.Context, keep: int) -> None:
    db_path = ctx.obj["output_dir"] / "scopio.db"
    if not db_path.exists():
        click.echo("Nothing to clean.")
        return

    with open_db(db_path) as conn:
        # Per-project cleanup: keep last N audits per project using correlated subquery
        keep_sql = """(
            SELECT m2.audit_id FROM metrics m2
            WHERE m2.project = m.project
            ORDER BY m2.timestamp DESC
            LIMIT ?
        )"""

        conn.execute(
            f"""
            DELETE FROM file_metrics
            WHERE audit_id NOT IN (
                SELECT m.audit_id FROM metrics m
                WHERE m.audit_id IN {keep_sql}
            )
            """,
            (keep,),
        )
        conn.execute(
            f"""
            DELETE FROM metrics_history
            WHERE audit_id NOT IN (
                SELECT m.audit_id FROM metrics m
                WHERE m.audit_id IN {keep_sql}
            )
            """,
            (keep,),
        )
        conn.execute(
            f"""
            DELETE FROM metrics
            WHERE audit_id NOT IN (
                SELECT m.audit_id FROM metrics m
                WHERE m.audit_id IN {keep_sql}
            )
            """,
            (keep,),
        )
    click.echo(f"Cleanup done. Keeping last {keep} audits per project.")


def _ci_thresholds(ctx: click.Context) -> dict[str, float]:
    """Read CI trend thresholds from the config."""
    config_path = ctx.obj["config_path"]
    thresholds = {"ccn_trend": 0.2, "loc_trend": 0.0}
    if config_path.exists():
        from .audit import _load_config

        try:
            cfg = _load_config(config_path)
        except Exception:
            return thresholds
        thresholds["ccn_trend"] = float(cfg.get("quality_gates", {}).get("max_ccn_trend_increase", 0.2))
        thresholds["loc_trend"] = float((cfg.get("ci", {}) or {}).get("max_loc_trend_increase", 0.0))
    return thresholds


@cli.command("ci")
@click.option("--project", default=None, help="Project name (auto-detected if omitted and single project)")
@click.option("--format", "output_format", default="json", type=click.Choice(["json", "github-comment"]))
@click.option("--fail-on-regression", is_flag=True, help="Fail if metrics regressed")
@click.pass_context
def ci_cmd(ctx: click.Context, project: str | None, output_format: str, fail_on_regression: bool) -> None:
    proj_name = _resolve_project(ctx, project)
    db_path = ctx.obj["output_dir"] / "scopio.db"
    summary = project_diff(db_path, proj_name)
    thresholds = _ci_thresholds(ctx)

    if output_format == "github-comment":
        output = render_github_comment(summary, thresholds=thresholds)  # type: ignore[arg-type]
    else:
        output = render_ci_summary(summary, thresholds=thresholds)  # type: ignore[arg-type]

    click.echo(output)

    if fail_on_regression:
        failures = _detect_ci_failures(summary, thresholds=thresholds)  # type: ignore[arg-type]
        if failures:
            raise click.ClickException(f"CI check failed: {'; '.join(failures)}")


@cli.command("doctor")
@click.pass_context
def doctor(ctx: click.Context) -> None:
    """Check tool environment, system dependencies and version compatibility."""
    import shutil
    import sys

    from .audit import _run_tool_version, _validate_tool_versions

    click.echo("Scopio Doctor — Environment & Tool Health Check\n" + "-" * 48)
    click.echo(f"[✓] Python: {sys.version.split()[0]} ({sys.executable})")

    deps = [
        ("git", "Git version control", "Install git (https://git-scm.com)"),
        (
            "scc",
            "Boyter SCC code counter",
            "Install scc: `go install github.com/boyter/scc/v3@latest` or download release binary",
        ),
        ("lizard", "Lizard complexity analyzer", "Install lizard: `pip install lizard`"),
    ]

    detected_versions: dict[str, str] = {}
    missing_count = 0

    for cmd, desc, hint in deps:
        path = shutil.which(cmd)
        if path:
            version = _run_tool_version(cmd)
            detected_versions[cmd] = version
            click.echo(f"[✓] {cmd}: {version} ({path})")
        else:
            missing_count += 1
            click.echo(f"[✗] {cmd}: NOT FOUND — {desc}")
            click.echo(f"    └─ Hint: {hint}")

    version_warnings = _validate_tool_versions(detected_versions)
    if version_warnings:
        click.echo("\nTool Version Compatibility Warnings:")
        for w in version_warnings:
            click.echo(f"  ⚠ {w}")

    if missing_count == 0 and not version_warnings:
        click.echo("\nAll system dependencies and tool versions are healthy!")
    elif missing_count > 0:
        raise click.ClickException(f"Environment check failed: {missing_count} missing dependency(ies).")


@cli.command()
@click.option("--path", default=None, help="Path to scopio.db")
@click.option("--older-than", default=None, help="Only rows with timestamp before YYYY-MM-DD")
@click.option("--format", "output_format", default="csv", type=click.Choice(["csv", "json", "parquet"]))
def archive(path: str | None, older_than: str | None, output_format: str) -> None:
    db_path = Path(path) if path else click.get_current_context().obj["output_dir"] / "scopio.db"
    if not db_path.exists():
        raise click.ClickException(f"Database not found: {db_path}")

    query = """
        SELECT project, language, files, loc, code, nloc, ccn, ccn_max, warnings,
               commits, last_commit_date, author, branch, dirty, commit_hash,
               tool_versions, duration_seconds, runs_count, timestamp
        FROM metrics
    """
    args = []
    if older_than:
        query += " WHERE timestamp < ?"
        args.append(older_than)

    with open_db(db_path) as conn:
        rows = conn.execute(query, args).fetchall()

    if not rows:
        click.echo("Nothing to archive.")
        return

    out_dir = click.get_current_context().obj["output_dir"]
    out_dir.mkdir(parents=True, exist_ok=True)
    if output_format == "csv":
        out = out_dir / "scopio_archive.csv"
        with out.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows([dict(r) for r in rows])
    elif output_format == "json":
        out = out_dir / "scopio_archive.json"
        out.write_text(json.dumps([dict(r) for r in rows], indent=2, default=str))
    else:
        out = out_dir / "scopio_archive.parquet"
        _write_parquet(out, [dict(r) for r in rows])  # type: ignore[misc]

    click.echo(f"Archived: {len(rows)} rows to {out}")


def _write_parquet(path: Path, rows: list[AuditResult]) -> None:
    try:
        import pandas as pd
    except ImportError as exc:
        raise click.ClickException("Parquet requires pandas/pyarrow installed.") from exc
    pd.DataFrame(rows).to_parquet(path, index=False)


@cli.command()
@click.pass_context
def init(ctx: click.Context) -> None:
    config = ctx.obj["config_path"]
    if config.exists():
        raise click.ClickException(f"{config} already exists.")

    sample = """\
[discovery]
ignore_hidden = true
projects = ["."]


[filters]
global_dirs = [
    "node_modules", "target", "dist", "build", "bin",
    "obj", "venv", "env", "__pycache__", "dataset", "datasets",
    "models", "checkpoints", "public", ".astro"
]
minified_files = ["*.min.js", "*.min.css"]
ignored_langs = [
    "JSON", "Markdown", "TOML", "YAML", "XML", "License",
    "CSV", "CSS", "HTML", "Shell", "BASH", "Makefile",
    "Properties File", "Windows Resource-Definition Script"
]

[quality_gates]
max_ccn = 10.0
max_function_ccn = 15.0
max_warnings = 10
max_ccn_trend_increase = 0.2
trend_sensitive_projects = []

[quality_gates.per_project]
# \"my-project\" = { max_ccn = 12.0, max_warnings = 15 }

[quality_gates.per_language]
# Python = { max_ccn = 12.0, max_warnings = 20 }

[ci]
max_loc_trend_increase = 0.0  # fail if LOC grows above this ratio (0.0 = any growth fails)
"""
    config.write_text(sample)
    click.echo(f"Created: {config}")


def main() -> None:
    cli(obj={})
