from __future__ import annotations

import pytest

from scopio.diff import CI_RULES, _detect_ci_failures


def _summary_trend(key: str, val: float) -> dict:
    delta = {"ccn_trend": 0.0, "loc_trend": 0.0}
    delta[key] = val
    return {
        "base": {"ccn": 1.0, "loc": 100, "warnings": 0},
        "latest": {"ccn": 1.0, "loc": 100, "warnings": 0},
        "delta": delta,
    }


def _summary_absolute(base_w: int, latest_w: int) -> dict:
    return {
        "base": {"ccn": 1.0, "loc": 100, "warnings": base_w},
        "latest": {"ccn": 1.0, "loc": 100, "warnings": latest_w},
        "delta": {"ccn_trend": 0.0, "loc_trend": 0.0},
    }


def _summary_regression(base_c: float, latest_c: float) -> dict:
    return {
        "base": {"ccn": base_c, "loc": 100, "warnings": 0},
        "latest": {"ccn": latest_c, "loc": 100, "warnings": 0},
        "delta": {"ccn_trend": 0.0, "loc_trend": 0.0},
    }


def _summary_decrease(base_loc: int, latest_loc: int) -> dict:
    return {
        "base": {"ccn": 1.0, "loc": base_loc, "warnings": 0},
        "latest": {"ccn": 1.0, "loc": latest_loc, "warnings": 0},
        "delta": {"ccn_trend": 0.0, "loc_trend": 0.0},
    }


TRIGGER_CASES = [
    (0, _summary_trend("ccn_trend", 0.5), True, "ccn"),  # CCN increased
    (0, _summary_trend("ccn_trend", 0.0), False, ""),  # CCN unchanged
    (1, _summary_trend("loc_trend", 0.3), True, "LOC"),  # LOC increased
    (1, _summary_trend("loc_trend", -0.1), False, ""),  # LOC decreased
    (2, _summary_absolute(1, 5), True, "Warnings"),  # Warnings increased
    (2, _summary_absolute(5, 2), False, ""),  # Warnings decreased
    (3, _summary_regression(2.0, 6.0), True, "CCN"),  # CCN regressed
    (3, _summary_regression(6.0, 2.0), False, ""),  # CCN improved
    (4, _summary_decrease(200, 100), True, "LOC decreased"),  # LOC decreased
    (4, _summary_decrease(100, 200), False, ""),  # LOC increased
]


class TestCiRulesStructure:
    """Verify that CI_RULES constant is well-formed."""

    def test_ci_rules_is_list(self) -> None:
        assert isinstance(CI_RULES, list)

    def test_ci_rules_not_empty(self) -> None:
        assert len(CI_RULES) > 0

    def test_each_rule_has_three_elements(self) -> None:
        for i, rule in enumerate(CI_RULES):
            assert len(rule) == 3, f"Rule {i} has {len(rule)} elements, expected 3"
            key, rule_type, fmt = rule
            assert isinstance(key, str), f"Rule {i}: key is not str"
            assert isinstance(rule_type, str), f"Rule {i}: rule_type is not str"
            assert isinstance(fmt, str), f"Rule {i}: fmt is not str"
            assert len(key) > 0, f"Rule {i}: empty key"
            assert len(rule_type) > 0, f"Rule {i}: empty rule_type"
            assert len(fmt) > 0, f"Rule {i}: empty fmt"

    def test_ci_rules_types_known(self) -> None:
        known_types = {"trend", "absolute", "regression", "decrease"}
        for i, (_, rule_type, _) in enumerate(CI_RULES):
            assert rule_type in known_types, f"Rule {i}: unknown type '{rule_type}'"


class TestCiRulesTrigger:
    """Parametrized tests that each rule triggers correctly."""

    @pytest.mark.parametrize(
        ("rule_idx", "summary", "expect_fail", "expected_text"),
        TRIGGER_CASES,
        ids=[
            "ccn_increased",
            "ccn_unchanged",
            "loc_increased",
            "loc_decreased",
            "warnings_increased",
            "warnings_decreased",
            "ccn_regressed",
            "ccn_improved",
            "loc_decreased_rule",
            "loc_increased_rule",
        ],
    )
    def test_rule_trigger(self, rule_idx: int, summary: dict, expect_fail: bool, expected_text: str) -> None:
        failures = _detect_ci_failures(summary)
        if expect_fail:
            assert len(failures) > 0, f"Rule {rule_idx} should have triggered but got failures={failures}"
            assert any(expected_text.lower() in f.lower() for f in failures), (
                f"Rule {rule_idx}: expected '{expected_text}' in failures={failures}"
            )
        else:
            assert len(failures) == 0, f"Rule {rule_idx} should NOT have triggered but got failures={failures}"
