from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from scopio.collect.run.runner import (
    fetch_git_info,
    fetch_lizard_metrics,
    fetch_scc_metrics,
    parse_lizard_csv,
    run_cmd,
)


def test_run_cmd(monkeypatch: pytest.MonkeyPatch) -> None:
    mock = MagicMock()
    mock.stdout = "hello\n"
    monkeypatch.setattr("subprocess.run", lambda *a, **kw: mock)
    res = run_cmd(Path("/tmp"), ["echo", "hello"])
    assert res == "hello"


def test_fetch_git_info_no_git(tmp_path: Path) -> None:
    git_info = fetch_git_info(tmp_path)
    assert git_info["commits"] == 0
    assert git_info["branch"] == "n/a"
    assert git_info["dirty"] is False


def test_fetch_git_info_with_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / ".git").mkdir()

    def fake_run_cmd(path, cmd):
        cmd_str = " ".join(cmd)
        if "rev-list" in cmd_str:
            return "10"
        if "branch" in cmd_str:
            return "feature"
        if "--format=%ad" in cmd_str:
            return "2026-08-29"
        if "--format=%an" in cmd_str:
            return "Gabe"
        if "rev-parse" in cmd_str:
            return "abc1234"
        if "status" in cmd_str:
            return " M file.py\n"
        return ""

    monkeypatch.setattr("scopio.collect.run.runner.run_cmd", fake_run_cmd)

    git_info = fetch_git_info(tmp_path)
    assert git_info["commits"] == 10
    assert git_info["branch"] == "feature"
    assert git_info["dirty"] is True
    assert git_info["author"] == "Gabe"


def test_fetch_scc_metrics_success(monkeypatch: pytest.MonkeyPatch) -> None:
    mock = MagicMock()
    mock.returncode = 0
    mock.stdout = '[{"Name": "Python", "Lines": 100, "Code": 80, "Count": 2}]'
    monkeypatch.setattr("subprocess.run", lambda *a, **kw: mock)

    res = fetch_scc_metrics(Path("/tmp"), ["node_modules"])
    assert len(res) == 1
    assert res[0]["Name"] == "Python"


def test_fetch_scc_metrics_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    mock = MagicMock()
    mock.returncode = 1
    monkeypatch.setattr("subprocess.run", lambda *a, **kw: mock)

    res = fetch_scc_metrics(Path("/tmp"), [])
    assert res == []


def test_fetch_lizard_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    mock = MagicMock()
    mock.returncode = 0
    mock.stdout = "10,2,10,1,1,foo@10@app.py,app.py,foo,foo(),1,10\n"
    monkeypatch.setattr("subprocess.run", lambda *a, **kw: mock)

    res = fetch_lizard_metrics(Path("/tmp"), [])
    assert res["nloc"] == 10
    assert res["ccn"] == 2.0
    assert len(res["files"]) == 1


def test_parse_lizard_csv_empty() -> None:
    res = parse_lizard_csv("")
    assert res["nloc"] == 0
    assert res["files"] == []
