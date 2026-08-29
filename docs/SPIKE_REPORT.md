# Spike Report: Native Python Dependencies (radon + pygount)

## Objective
Evaluate whether external binary dependencies (`scc` and `lizard`) can be replaced by native Python libraries (`radon` for complexity, `pygount` for line counting).

## Methodology
- **radon** 6.0.1: `cc_visit` (cyclomatic complexity) + `analyze` (raw LOC)
- **pygount** (latest): `SourceAnalysis.from_file` for per-file code count
- Compared against `scc` (v3.7.0) and `lizard` (v1.24.0) via `--csv` and `--format json`
- Tested against 2 projects:
  1. Pure Python (5 functions, 3 files)
  2. Python + JavaScript (6 functions, 2 files)

## Results

### Project 1: Pure Python

| Metric | radon/pygount | scc/lizard | Difference |
|---|---|---|---|
| LOC (code) | 27 | 27 | **0.0%** |
| Functions | 5 | 5 | **0.0%** |
| Avg CCN | 3.0 | 3.0 | **0.0%** |

### Project 2: Python + JavaScript

| Metric | radon/pygount | scc/lizard | Difference |
|---|---|---|---|
| LOC (code) | 29 | 33 | **12.1%** |
| Functions | 4 (Python only) | 6 (all languages) | **33.3%** |
| Avg CCN | 2.2 | 2.3 | **4.3%** |

## Advantages Observed
- No subprocess calls (pure Python API)
- radon provides detailed per-function complexity data
- pygount supports multiple languages for code counting

## Disadvantages Observed
- **radon only handles Python** — lizard supports 15+ languages (C, C++, Java, JS, TypeScript, etc.)
- **pygount is significantly slower** than `scc` for large codebases (timeout on scopio itself)
- **12.1% LOC discrepancy** for JavaScript between pygount and scc (different counting methodologies)
- **33.3% function count discrepancy** for polyglot projects (radon misses non-Python functions)
- Lizard's `--csv` output is already stable and well-tested

## Conclusion
**Not viable** for complete replacement of `scc` and `lizard`.

The primary blocker is multi-language support: `radon` is Python-only, while `lizard` handles the full range of languages that `scopio` audits. The performance gap with `pygount` vs `scc` is also a concern for large projects.

**Recommendation**: Keep the current architecture with `scc` and `lizard` as external dependencies. The version validation (`_validate_tool_versions`) and pinning (`EXPECTED_VERSIONS`) already mitigate the main risks of external tool divergence.

### Future Potential
If multi-language support is not a requirement, `radon` could replace `lizard` for Python-only projects, and `pygount` could replace `scc` for Python-only LOC counting. This would require a configuration flag or fallback mechanism. Not recommended for the current scope of `scopio`.