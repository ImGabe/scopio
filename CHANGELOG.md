# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0] - 2026-08-29

### Added
- Per-function complexity gate (`max_function_ccn`) that catches worst-function outliers the average CCN gate misses.
- `ccn_max` metric now tracked in the database, history, exports, `report`, and diff/CI summaries.
- `--base {previous,first}` option on `diff` and `diff-report`; the default is now the previous audit.

### Changed
- `diff`/`ci` now compare the previous audit against the current one (was first vs last).
- `file_metrics` in `diff-report` are aggregated per file (NLOC sum, CCN max).
- CI rules are threshold-aware (`max_ccn_trend_increase` and `[ci] max_loc_trend_increase`) and no longer fail on LOC decrease or a redundant CCN-regression rule.

### Fixed
- `metrics_history` ALTER migrations now target the correct table (was hardcoded to `metrics`).

### Removed
- Dead `_parse_lizard_output` parser (superseded by the CSV parser).

## [0.2.2] - 2026-08-29

### Changed
- README reestruturado: seções reordenadas, nova seção de Features, badges de Python/License, exemplos consistentes e remoção de conteúdo duplicado.
- Workflow de publish separado em jobs de `build` e `publish-to-pypi` (com `upload-artifact`/`download-artifact`), alinhado ao guia de Trusted Publishing da PyPA.
- Validação de distribuições (`uv build` + `twine check`) adicionada aos workflows de testes e publish.

## [0.2.1] - 2026-08-29

### Added
- Testes parametrizados para CI_RULES (14 testes estruturais + 10 parametrizados).
- Documentação de requisito de lizard >= 1.24.0 no README.
- Relatório do spike de dependências nativas (docs/SPIKE_REPORT.md) — conclusão: não viável.
- Testes de renderização para markdown, CI summary e file-level markdown.
- Testes de cobertura para archive (json, parquet), clean (sem db), e filtro incremental.

### Changed
- Otimização de `_filter_incremental`: substituído `os.walk` por `Path.rglob` com early-exit (interrompe varredura ao primeiro arquivo recente).
- Simplificação do comando `clean`: agora usa subquery correlacionada para manter as últimas N auditorias **por projeto** (era global).
- Gate de cobertura global elevado para 80%.
- Gate de cobertura de `diff.py` elevado para 75%.

## [0.2.0] - 2026-08-29

### Added
- **Toolchain migrated to uv**: `uv.lock`, `.python-version`, hatchling build backend, `uv sync`/`uv build`/`uv publish` — replaces setuptools/pip.
- **TypedDicts throughout**: `scopio/types.py` with `AuditResult`, `LizardSummary`, `SccRecord`, `GitInfo`, `DiffSummary` — adopted in all modules.
- **Upsert + `runs_count`**: `INSERT ... ON CONFLICT DO UPDATE` replaces `INSERT OR IGNORE` — re-auditing the same (project, branch, commit_hash) updates metrics and increments `runs_count` (v7 migration).
- **mypy strict** with `disallow_untyped_defs = true` — 0 issues in 7 source files.
- **ruff**: lint + format, integrated via CI and pre-commit.
- **pytest-cov** with coverage gate (70%).
- **CLI tests**: `tests/test_cli.py` with `CliRunner` covering all 8 commands.
- **Audit tests**: `tests/test_audit.py` with 24 tests covering `_parse_lizard_csv`, `_run_scc`/`_run_lizard` mocking, `_git_info`, `_audit_project` integration, quality gates, upsert, path traversal, clean cascading, and tool version validation.
- **Diff/CI tests**: `tests/test_diff_commands.py` with 6 tests covering `diff`, `diff-report`, `ci` with seeded multi-audit history.
- **Pre-commit hooks**: ruff, ruff-format, mypy, uv-lock.
- **`.pre-commit-config.yaml`**, `.gitignore`, `.python-version` files.
- **`tool_version_diverge` event**: warns when `scc`/`lizard` versions differ from expected range (visible in logs, non-blocking).

### Changed
- **Parser migrated to lizard --csv**: replaces fragile textual `_parse_lizard_output` with stable CSV parser (`_parse_lizard_csv`). Sanity check warns if CCN is 0 despite files being parsed.
- **`_init_db` made declarative**: if-chain replaced with `_MIGRATIONS` list of `(version, sql)` tuples and clean loop.
- **`_save_results` decomposed** into `_upsert_metrics_row`, `_log_metrics_history`, `_save_file_metrics`.
- **`export_outputs` decomposed** into `_enrich_results`, `_export_json`, `_export_csv`, `_export_markdown`.
- **Trend gate now queries `metrics_history`** (append-only) instead of `metrics` (upsert) — more robust.
- **Output artifacts moved to `.scopio/`**: database, JSON, CSV, Markdown files default to `.scopio/` instead of CWD (`--output-dir` override still works).
- **`scopio archive`** now resolves DB path and output directory from shared context.
- **`ci --fail-on-regression`** respects `max_ccn_trend_increase` from config (aligned with trend gate).
- **`observability` dict** no longer duplicated between `audit.py` and `cli.py`.
- **`_run_cmd`** returns "" + log instead of `"ERROR:{exc}"` that corrupted data.
- **`_fs_sharp_fallback`** logs structured warnings instead of swallowing errors.
- **All migration ALTER TABLEs** check column existence via `PRAGMA table_info` first.
- **Strings in `diff.py`** homogenised to English.
- **WAL journal mode** enabled for SQLite.
- **`init` sample** now includes all `quality_gates` options (`max_ccn_trend_increase`, `trend_sensitive_projects`, `per_project`, `per_language`).
- **`lizard`** pinned to `>=1.24,<1.25` in `pyproject.toml`.
- **`scc` v3.3.0** pinned in Dockerfile (expected runtime version).

### Fixed
- `diff` and `diff-report` commands not registered in CLI (B1).
- `scopio archive` `NameError: csv` (B2).
- Trend gate evaluating against just-saved audit instead of previous (B3).
- `metrics_history.timestamp` always NULL (B4).
- Legacy database DROP TABLE on open (B5).
- `scopio clean` not cascading to child tables (B6).
- `_save_results` hardcoded `"warnings": 0` for file metrics.
- Migration loop `version = 7` outside `if` block (prevented all migrations after v1).
- `scopio clean` missing bind parameters (crash on clean).
- Path traversal unrestricted in `_audit_project`.
- `FileNotFoundError`/`TOMLDecodeError` leaking raw tracebacks (now `ConfigError`).
- Unused imports and loop variables flagged by ruff.

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
