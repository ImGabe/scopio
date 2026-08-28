# scopio

Code metrics auditor with SQLite history, diffs and quality gates.

[![PyPI version](https://badge.fury.io/py/scopio.svg)](https://pypi.org/project/scopio/)

## Install

```bash
pip install scopio
```

## Development

This project uses [uv](https://docs.astral.sh/uv/) as the Python toolchain.

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

## Quick Start

```bash
scopio --config scopio.toml run
```

## Usage

### Run audit

```bash
scopio --config scopio.toml run
scopio --config scopio.toml run --verbose
scopio --config scopio.toml run --incremental
```

### Report history

```bash
scopio report --project wrong-web --limit 10
```

### Diff between audits

```bash
scopio diff --project wrong-web
```

### Diff report with file-level detail

```bash
scopio diff-report --project wrong-web --files --threshold-ccn 6
```

### CI integration

```bash
scopio ci --project wrong-web --fail-on-regression
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
max_ccn = 10.0
max_warnings = 10
max_ccn_trend_increase = 0.2
trend_sensitive_projects = []

[quality_gates.per_project]
# "my-project" = { max_ccn = 12.0, max_warnings = 15 }

[quality_gates.per_language]
# Python = { max_ccn = 12.0, max_warnings = 20 }
```

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

## License

MIT
