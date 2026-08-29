# scopio

Code metrics auditor with SQLite history, diffs and quality gates.

[![PyPI version](https://badge.fury.io/py/scopio.svg)](https://pypi.org/project/scopio/)
[![Python versions](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Features

- Audits code metrics (lines, complexity, warnings, languages) across multiple projects.
- Stores audit history in SQLite with diffs and quality gates.
- Exports results as JSON, CSV and Markdown.
- Compares audits and detects regressions for CI (`--fail-on-regression`).

## Install

```bash
pip install scopio
```

### Requirements

- Python >= 3.11
- `lizard` >= 1.24.0 (required for CSV parsing mode)
- `scc` >= 3.3.0 (optional, used for language/line counting) — the [boyter/scc](https://github.com/boyter/scc) code counter, **not** the unrelated PyPI `scc` package:
  ```bash
  # Download a binary from https://github.com/boyter/scc/releases, or:
  go install github.com/boyter/scc/v3@latest
  ```
- `git` (optional, used for metadata)

## Quick Start

```bash
scopio --config scopio.toml run
```

All output artifacts (database, JSON, CSV, Markdown) are stored in the `.scopio/` directory by default. Use `--output-dir` to override.

If `scc` or `lizard` versions differ from the expected range, a non-blocking `tool_version_diverge` warning is emitted in the logs.

## Usage

### Run audit

```bash
scopio --config scopio.toml run
scopio --config scopio.toml run --verbose
scopio --config scopio.toml run --incremental
```

### Report history

```bash
scopio report --project my-project --limit 10
```

### Diff between audits

```bash
scopio diff --project my-project
```

### Diff report with file-level detail

```bash
scopio diff-report --project my-project --files --threshold-ccn 6
```

### CI integration

```bash
scopio ci --project my-project --fail-on-regression
```

### Clean old audits

```bash
scopio clean --keep 50
```

### Archive old data

```bash
scopio archive --older-than 2026-01-01 --format csv
```

### Initialize config

```bash
scopio init
```

## Configuration

```toml
[discovery]
ignore_hidden = true
projects = ["my-project"]

[filters]
global_dirs = ["node_modules", "target", "dist", "build"]
minified_files = ["*.min.js", "*.min.css"]
ignored_langs = ["JSON", "Markdown", "TOML"]

[quality_gates]
max_ccn = 10.0            # average CCN per function
max_function_ccn = 15.0   # worst function complexity (disabled if omitted)
max_warnings = 10
max_ccn_trend_increase = 0.2
trend_sensitive_projects = []

[quality_gates.per_project]
# "my-project" = { max_ccn = 12.0, max_warnings = 15, max_function_ccn = 20.0 }

[quality_gates.per_language]
# Python = { max_ccn = 12.0, max_warnings = 20 }

[ci]
max_loc_trend_increase = 0.0  # fail if LOC grows above this ratio (0.0 = any growth)
```

## Audit behavior

- Each audit run creates/updates a single row per `(project, branch, commit_hash)`.
- **Same commit, same branch**: metrics are **upserted** (updated) and `runs_count` is incremented. This avoids data staleness when re-running on the same commit (e.g. after changing `.scopio.toml` filters).
- **Different commit**: a new row is created with `runs_count = 1`.
- The `runs_count` field is exposed in `report`, CSV, JSON and Markdown exports.
- Diff and CI comparisons compare the **previous** audit against the current one by default (use `--base first` to compare against the very first audit).
- Quality gates use the current audit's values; the trend gate compares against the **previous** historical audit.

## What the numbers mean

- **LOC**: source lines of code counted by `scc`.
- **NLOC**: logical lines of code counted by `lizard`. LOC and NLOC are intentionally different metrics (different counting methodologies).
- **CCN (avg)**: cyclomatic complexity averaged over all functions. Averages hide outliers.
- **ccn_max / `max_function_ccn`**: cyclomatic complexity of the **worst** single function — this is what the per-function quality gate checks.
- **warnings**: currently always `0` — the `lizard --csv` format does not emit warnings. Language-specific warning adapters (clippy, eslint, ruff) are planned.
- **file_metrics**: stored per-function in the database; the granular `diff-report` aggregates them per file (NLOC sum, CCN max).

## GitHub Actions

```yaml
name: Scopio
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  scopio:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Install uv
        uses: astral-sh/setup-uv@v10.0.1
        with:
          enable-cache: true
          cache-dependency-glob: "uv.lock"
      - name: Install Python
        run: uv python install 3.11
      - name: Install scopio
        run: pip install scopio
      - name: Run scopio
        run: scopio ci --project my-project --fail-on-regression
```

## Development

This project uses [uv](https://docs.astral.sh/uv/) as the Python toolchain.

See [CONTRIBUTING.md](CONTRIBUTING.md) for the commit convention and release workflow.

```bash
# Sync dependencies and create a virtual environment
uv sync

# Run tests
uv run pytest

# Run a lint check
uv run ruff check

# Run scopio locally
uv run scopio --help
```

## Semantic Versioning

This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## License

[MIT](LICENSE)
