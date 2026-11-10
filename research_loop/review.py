"""Checks for experiment designs, shared by the graph and evaluation."""

import re
import unicodedata

from .artifacts import require_keys, require_text


ISSUE_FIELDS = (
    "hypothesis", "mechanism", "simple_baseline", "closest_baseline", "closest_source_id",
    "comparisons", "experiment.unit", "experiment.evaluation_data",
    "experiment.matched_conditions", "experiment.negative_control", "experiment.controls",
)
CONTROL_ROLES = ("simple_baseline", "closest_baseline", "negative_control")


def normalized(text):
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", text).casefold())


def validate_controls(candidate):
    controls = candidate["experiment"].get("controls")
    if not isinstance(controls, list) or len(controls) != 3:
        raise ValueError("Provide exactly three experiment.controls")
    if {row.get("role") for row in controls if isinstance(row, dict)} != set(CONTROL_ROLES):
        raise ValueError("Each control role must appear exactly once")
    expected = {**candidate, "negative_control": candidate["experiment"]["negative_control"]}
    for row in controls:
        require_keys(row, ("role", "method", "changed_factor", "held_constant", "expected"))
        for field, value in row.items():
            require_text(value, field)
        if normalized(row["method"]) != normalized(expected[row["role"]]):
            raise ValueError(f"Control method must match {row['role']}")


def design_issues(candidate):
    """Identify objective ambiguities. Semantic equivalence remains a review task."""
    experiment = candidate["experiment"]
    issues = []
    negative = normalized(experiment["negative_control"])
    if negative in {normalized(candidate["simple_baseline"]), normalized(candidate["closest_baseline"])}:
        issues.append({
            "field": "experiment.negative_control",
            "problem": "负对照与常规基线相同，无法单独检验所声称的机制。",
            "correction": "设计使目标机制失效的干预，明确保持条件和预期观察。",
        })
    if normalized(experiment["unit"]) in {"", "percent", "percentage", "百分比", "百分之"}:
        issues.append({
            "field": "experiment.unit",
            "problem": "收益单位未区分绝对分差和相对百分比。",
            "correction": "明确使用 0–1 分数差或百分点等绝对单位，使 minimum_gain 与指标尺度一致。",
        })
    return issues
