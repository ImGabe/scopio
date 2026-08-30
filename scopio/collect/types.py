from __future__ import annotations

from typing import Literal, TypedDict


class Finding(TypedDict, total=False):
    source: str
    file: str
    rule: str
    severity: Literal["error", "warning", "info"]
    message: str
    line: int | None


class IngestSummary(TypedDict, total=False):
    source: str
    status: Literal["clean", "violations", "not_run"]
    errors: int
    warnings: int
    info: int
    findings: list[Finding]
