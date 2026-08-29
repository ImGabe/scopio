# Contributing

## Branch strategy

- `main` is the only long-lived branch and must always be releasable.
- Use short-lived branches for each change: `feat/...`, `fix/...`, `docs/...`, `chore/...`.
- For solo work you may commit directly to `main`; prefer fast-forward merges (`git merge --ff-only`) to keep history linear.

## Commit messages

Follow [Conventional Commits](https://www.conventionalcommits.org/). All messages are written in English.

```
<type>[optional scope]: <short description>

[optional body]

[optional footer, e.g. BREAKING CHANGE:, Refs #123]
```

Rules:

- Imperative, lowercase, no trailing period.
- Use `feat!:`/`fix!:` or a `BREAKING CHANGE:` footer for incompatible changes.

Allowed types:

| Type | Use |
|---|---|
| `feat` | New feature (minor bump) |
| `fix` | Bug fix (patch bump) |
| `docs` | Documentation |
| `style` | Formatting, no logic change |
| `refactor` | Refactoring, no behavior change |
| `perf` | Performance |
| `test` | Tests |
| `build` | Build system / external dependencies |
| `ci` | CI/CD configuration |
| `chore` | Maintenance |

Commit message format is enforced by a `commit-msg` pre-commit hook.

## Local checks

```bash
uv sync
uv run pytest -q --cov=scopio --cov-fail-under=80
uv run mypy scopio/
uv run ruff check scopio/ tests/
uv run ruff format --check scopio/ tests/
```

## Release workflow

The project uses [Commitizen](https://commitizen-tools.github.io/commitizen/) for SemVer, changelog generation and annotated tags.

```bash
git checkout main
git pull origin main

# Compute the next version from commits since the last tag,
# update version files and CHANGELOG.md, and create an annotated tag.
# The bump commit message is "chore: bump version to X.Y.Z".
cz bump --changelog

# Push the release commit and its annotated tag.
git push origin main --follow-tags
```

Pushing a `v*` tag triggers `.github/workflows/publish.yml`, which builds the distribution, runs `twine check`, and publishes to PyPI after manual approval in the `pypi` environment.

Bump rules (from commits since the last tag):

- `feat` → minor.
- `fix`, `refactor`, `perf` → patch.
- `feat!`/`fix!` or a `BREAKING CHANGE:` footer → major (or minor while on 0.x).

Commits of type `docs`, `style`, `test`, `build`, `ci` and `chore` do not trigger an automatic bump. To release when only those types are present, use:

```bash
cz bump --increment PATCH
```
