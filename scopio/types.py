from __future__ import annotations

from typing import Any, TypedDict


class GitInfo(TypedDict, total=False):
    commits: int
    branch: str
    last_commit_date: str
    author: str
    dirty: bool
    commit_hash: str


class SccRecord(TypedDict, total=False):
    Name: str
    Code: int
    Lines: int
    Count: int


class LizardFile(TypedDict, total=False):
    path: str
    nloc: int
    ccn: float
    warnings: int


class LizardSummary(TypedDict, total=False):
    nloc: int
    ccn: float
    warnings: int
    files: list[LizardFile]


class FileMetric(TypedDict, total=False):
    path: str
    nloc: int
    ccn: float
    warnings: int
    ccn_delta: float | None
    nloc_delta: int | None
    warnings_delta: int | None
    added: bool
    removed: bool
    over_threshold: bool


class AuditResult(TypedDict, total=False):
    project: str
    language: str
    files: int
    loc: int
    code: int
    nloc: int
    ccn: float
    warnings: int
    commits: int
    last_commit_date: str
    author: str
    branch: str
    dirty: int
    commit_hash: str
    tool_versions: str
    duration_seconds: float
    file_metrics: list[FileMetric]


class DiffDelta(TypedDict, total=False):
    loc: float
    loc_trend: float | None
    ccn: float
    ccn_trend: float | None
    warnings: float


class DiffSnapshot(TypedDict, total=False):
    timestamp: str | None
    branch: str | None
    commit_hash: str | None
    loc: int | None
    ccn: float | None
    warnings: int | None
    dirty: bool | None


class DiffSummary(TypedDict, total=False):
    project: str
    base: DiffSnapshot
    latest: DiffSnapshot
    delta: DiffDelta
    threshold_ccn: float | None
    files: list[FileMetric]
    summary: dict[str, Any]
