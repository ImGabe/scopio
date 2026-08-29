from __future__ import annotations

import csv
import json
from pathlib import Path

import click

from .audit import MetricsAuditor
from .db import open_db
from .diff import (
    _detect_ci_failures,
    project_diff,
    project_file_diff,
    render_ci_summary,
    render_file_markdown,
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
    config_path = Path(config) if config else root / "scopio.toml"
    projects_root = Path(projects_dir) if projects_dir else root
    out = Path(output_dir) if output_dir else root / ".scopio"
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
@click.pass_context
def run(ctx: click.Context, verbose: bool, quiet: bool, incremental: bool) -> None:
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
        names = ", ".join(r["project"] for r in gate_failures)
        click.echo(f"Quality gate failed in: {names}", err=True)

    if trend_failures:
        names = ", ".join(r["project"] for r in trend_failures)
        click.echo(f"Trend gate failed in: {names}", err=True)

    if failures or gate_failures or trend_failures:
        raise click.ClickException("Audit finished with failures.")

    click.echo(f"Audit finished: {len(results)} projects.")
    click.echo(json.dumps({"observability": summary["observability"]}))


@cli.command()
@click.option("--project", required=True, help="Project name")
@click.option("--limit", default=10, show_default=True, help="Max rows")
@click.pass_context
def report(ctx: click.Context, project: str, limit: int) -> None:
    db_path = ctx.obj["output_dir"] / "scopio.db"
    with open_db(db_path) as conn:
        rows = conn.execute(
            """
            SELECT project, language, files, loc, code, nloc, ccn, warnings,
                   commits, last_commit_date, author, branch, dirty, commit_hash, runs_count, timestamp
            FROM metrics
            WHERE project = ?
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (project, limit),
        ).fetchall()

    if not rows:
        raise click.ClickException(f"No history for: {project}")

    for row in rows:
        click.echo(
            f"{row['timestamp']} | {row['branch']} | {row['commit_hash']} | "
            f"loc={row['loc']} ccn={row['ccn']} warnings={row['warnings']}"
            f"{' | runs=' + str(row['runs_count']) if row['runs_count'] and row['runs_count'] > 1 else ''}"
        )


@cli.command("diff")
@click.option("--project", required=True, help="Project name")
@click.option("--base", default=None, help="Base timestamp for diff")
@click.pass_context
def diff(ctx: click.Context, project: str, base: str | None) -> None:
    db_path = ctx.obj["output_dir"] / "scopio.db"
    summary = project_diff(db_path, project)

    if base and summary["base"]["timestamp"] != base:
        with open_db(db_path) as conn:
            row = conn.execute(
                "SELECT timestamp, branch, commit_hash, loc, ccn, warnings, dirty FROM metrics WHERE project = ? AND timestamp = ?",
                (project, base),
            ).fetchone()
        if not row:
            raise click.ClickException(f"Base '{base}' not found for project '{project}'.")
        summary["base"] = dict(row)  # type: ignore[typeddict-item]

    click.echo(f"Project: {project}")
    click.echo(f"Base : {summary['base']['timestamp']} ({summary['base']['branch']})")
    click.echo(f"Current: {summary['latest']['timestamp']} ({summary['latest']['branch']})")
    click.echo(f"LOC  : {summary['base']['loc']} -> {summary['latest']['loc']} ({summary['delta']['loc']:+})")
    click.echo(f"CCN  : {summary['base']['ccn']} -> {summary['latest']['ccn']} ({summary['delta']['ccn']:+.2f})")
    click.echo(
        f"Warn : {summary['base']['warnings']} -> {summary['latest']['warnings']} ({summary['delta']['warnings']:+})"
    )


@cli.command("diff-report")
@click.option("--project", required=True, help="Project name")
@click.option("--format", "output_format", default="text", type=click.Choice(["text", "json", "md"]))
@click.option("--files", is_flag=True, help="Include per-file granular diff")
@click.option("--threshold-ccn", default=None, type=float, help="CCN threshold to highlight files")
@click.pass_context
def diff_report(
    ctx: click.Context,
    project: str,
    output_format: str,
    files: bool,
    threshold_ccn: float | None,
) -> None:
    db_path = ctx.obj["output_dir"] / "scopio.db"
    summary = project_diff(db_path, project)

    if files:
        summary = project_file_diff(db_path, project, threshold_ccn=threshold_ccn)  # type: ignore[assignment]

    if output_format == "json":
        click.echo(json.dumps(summary, indent=2))
    elif output_format == "md":
        if files:
            click.echo(render_file_markdown(summary))  # type: ignore[arg-type]
        else:
            click.echo(render_markdown(summary))  # type: ignore[arg-type]
    else:
        if files:
            file_summary = project_file_diff(db_path, project, threshold_ccn=threshold_ccn)
            click.echo(f"Project: {project}")
            click.echo(f"Monitored files: {file_summary['summary']['total_files']}")
            click.echo(f"Changed: {file_summary['summary']['changed_files']}")
            click.echo(f"Above threshold: {file_summary['summary']['over_threshold_files']}")
        else:
            base = summary["base"]
            latest = summary["latest"]
            delta = summary["delta"]
            click.echo(f"Project: {project}")
            click.echo(f"Base : {base['timestamp']} ({base['branch']})")
            click.echo(f"Current: {latest['timestamp']} ({latest['branch']})")
            click.echo(f"LOC  : {base['loc']} -> {latest['loc']} ({delta['loc']:+})")
            click.echo(f"CCN  : {base['ccn']} -> {latest['ccn']} ({delta['ccn']:+.2f})")
            click.echo(f"Warn : {base['warnings']} -> {latest['warnings']} ({delta['warnings']:+})")


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


@cli.command("ci")
@click.option("--project", required=True, help="Project name")
@click.option("--fail-on-regression", is_flag=True, help="Fail if metrics regressed")
@click.pass_context
def ci_cmd(ctx: click.Context, project: str, fail_on_regression: bool) -> None:
    db_path = ctx.obj["output_dir"] / "scopio.db"
    summary = project_diff(db_path, project)
    output = render_ci_summary(summary)  # type: ignore[arg-type]
    click.echo(output)

    if fail_on_regression:
        failures = _detect_ci_failures(summary)  # type: ignore[arg-type]
        if failures:
            raise click.ClickException(f"CI check failed: {'; '.join(failures)}")


@cli.command()
@click.option("--path", default=None, help="Path to scopio.db")
@click.option("--older-than", default=None, help="Only rows with timestamp before YYYY-MM-DD")
@click.option("--format", "output_format", default="csv", type=click.Choice(["csv", "json", "parquet"]))
def archive(path: str | None, older_than: str | None, output_format: str) -> None:
    db_path = Path(path) if path else click.get_current_context().obj["output_dir"] / "scopio.db"
    if not db_path.exists():
        raise click.ClickException(f"Database not found: {db_path}")

    query = """
        SELECT project, language, files, loc, code, nloc, ccn, warnings,
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
projects = ["my-project"]

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
max_warnings = 10
max_ccn_trend_increase = 0.2
trend_sensitive_projects = []

[quality_gates.per_project]
# \"my-project\" = { max_ccn = 12.0, max_warnings = 15 }

[quality_gates.per_language]
# Python = { max_ccn = 12.0, max_warnings = 20 }
"""
    config.write_text(sample)
    click.echo(f"Created: {config}")


def main() -> None:
    cli(obj={})
