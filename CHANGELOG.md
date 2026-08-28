# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed
- **Fixed bug in `_parse_lizard_output`**: CCN now reads from column 1 (CCN value) instead of column 2 (token count) and the summary/Total lines are filtered out so they don't inflate file counts and averages. This fixes quality gates reporting incorrectly.\n- `mypy` check added to CI workflow (`tests.yml`).\n- `pytest-cov` added to dev dependency group.\n- `scopio archive` now respects `--output-dir` from the parent context (was always writing to CWD).\n- `observability` dict no longer duplicated between `audit.py` and `cli.py`.\n- WAL journal mode enabled for SQLite (reduces lock contention under parallel audits).\n- `.pre-commit-config.yaml` added with ruff, ruff-format, mypy and uv-lock hooks.\n- `scopio.toml` added to `.gitignore`.\n- Git repository initialized.\n\n
- Migrated toolchain from setuptools/pip to **uv** (uv lock, uv sync, uv build).
- Build backend changed to **hatchling** for faster builds.
- `lizard` is now a declared project dependency (via PyPI) instead of a manual install.
- Development dependencies moved to `[dependency-groups]` (PEP 735) — `dev` group with pytest and ruff.
- Removed deprecated `tomli` fallback (Python ≥ 3.11 has `tomllib` built-in).
- CI workflows updated to use `astral-sh/setup-uv@v10` with caching.
- Dockerfile now uses `ghcr.io/astral-sh/uv:python3.11-bookworm-slim` with uv sync.
- Added `.gitignore`, `.python-version`, `uv.lock` (committed for reproducible builds).
- Code linting/formatting with **ruff**.

### Fixed
- `diff` and `diff-report` commands now registered in CLI (B1).
- `scopio archive` no longer crashes with `NameError: csv` (B2).
- Trend gate now evaluates against the **previous** audit instead of the just-saved one (B3).
- `metrics_history.timestamp` now correctly defaults to `CURRENT_TIMESTAMP` (B4).
- Legacy database migration no longer drops all data on open (`DROP TABLE metrics` replaced with safe ALTER TABLE, B5).
- `scopio clean` now also prunes orphaned rows in `file_metrics` and `metrics_history` tables (B6).
- Foreign key enforcement enabled via `PRAGMA foreign_keys = ON` on every database connection.
- Portuguese output strings in `diff.py` replaced with English for consistency (`Arquivos monitorados`, `Acima do threshold`, `Arquivos alterados`).
- Logging formatter replaced with `_JsonFormatter` wrapper that serialises arbitrary log messages to valid JSON.
- Removed always-dead fields (`ccn_max: 0`, `coverage: None`, `duplication: None`, `outdated_dependencies: None`) from audit result dict and INSERT statement.
- Dead columns (`ccn_max`, `coverage`, `duplication`, `outdated_dependencies`) left in schema for backward compatibility but no longer populated.
- Unused `dirs` loop variable in `_filter_incremental` renamed; missing `Any`/`render_file_markdown` imports fixed.

### Added
- CLI tests with `click.testing.CliRunner` covering all 8 commands (`tests/test_cli.py`, 7 tests).
- Field test for trend gate logic against an inserted-prior-row scenario (`test_trend_gate_detects_regression`).
- **mypy** added to dev dependency group with basic configuration (`[tool.mypy]` in `pyproject.toml`).
- **Upsert + runs_count**: `INSERT ... ON CONFLICT DO UPDATE` replaces `INSERT OR IGNORE` — re-auditing the same (project, branch, commit_hash) updates metrics and increments `runs_count`, avoiding silent data staleness (Option D, v7 migration).
- `runs_count` exposed in `scopio report`, CSV, JSON and Markdown exports.
- Added `tests/test_audit.py` with 22 tests covering: `_parse_lizard_output`, `_run_scc`/`_run_lizard` mocking, `_git_info`, `_audit_project` integration, quality gates, and upsert re-run behavior.
- Migration safety: all `ALTER TABLE` operations now check column existence via `PRAGMA table_info` before executing (eliminating silent `except: pass` in v2/v4 migrations).
- Migrations v5/v6 `CREATE TABLE IF NOT EXISTS` blocks no longer wrapped in silent try/except.
- `_fs_sharp_fallback` now logs structured warnings instead of silently swallowing errors; `next(iter(...), None)` avoids `StopIteration`.
- `PRAGMA foreign_keys = ON` enforced on every database connection.
- `scopio clean` now cascades to `file_metrics` and `metrics_history` before deleting `metrics` rows.
- Strings in `diff.py` output homogenised to English.
## [0.1.0] - 2026-08-27

### Added
- Initial release.
- CLI with subcommands: `run`, `report`, `diff`, `diff-report`, `clean`, `ci`, `init`, `archive`.
- SQLite persistence with versioned schema migrations.
- Quality gates with per-project and per-language overrides.
- Trend gate to detect CCN regressions between audits.
- Structured JSON logging for CI/monitoring integration.
- File-level metrics (`file_metrics`) for granular diffs.
- Incremental mode (`run --incremental`) to audit only changed projects.
- CI integration with `scopio ci` and `--fail-on-regression`.
- Dockerfile for containerized execution.
- Unit tests with pytest.
- Export outputs: JSON, CSV, Markdown.

### Fixed
- Idempotent audits: duplicate runs no longer create duplicate rows.
