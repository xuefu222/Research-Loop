"""用 @tool 把论文摘录查询和结果提交暴露给 Agent。"""

import json
from typing import Literal

from langchain_core.tools import tool
from pydantic import BaseModel, Field


class ReviewIssue(BaseModel):
    field: Literal[
        "hypothesis", "mechanism", "simple_baseline", "closest_baseline", "closest_source_id",
        "comparisons", "experiment.unit", "experiment.evaluation_data",
        "experiment.matched_conditions", "experiment.negative_control", "experiment.controls",
    ]
    problem: str = Field(min_length=1)
    correction: str = Field(min_length=1)


class AuditCheck(BaseModel):
    status: Literal["pass", "uncertain", "fail"]
    basis: str = Field(min_length=1)
    issues: list[ReviewIssue] = Field(default_factory=list)


class ControlSpec(BaseModel):
    role: Literal["simple_baseline", "closest_baseline", "negative_control"]
    method: str
    changed_factor: str
    held_constant: str
    expected: str


class ControlReview(BaseModel):
    baseline_operation: str = Field(min_length=1)
    negative_operation: str = Field(min_length=1)
    disabled_mechanism: str = Field(min_length=1)
    status: Literal["valid", "invalid", "uncertain"]
    correction: str


class Comparison(BaseModel):
    source_id: str
    quote: str
    relationship: Literal["distinct", "same_mechanism", "uncertain"]
    reason: str


class ExperimentPlan(BaseModel):
    metric: str
    unit: str
    better: Literal["higher", "lower"]
    minimum_gain: float = Field(gt=0, allow_inf_nan=False)
    evaluation_data: str
    matched_conditions: str
    negative_control: str
    expected_control_behavior: str
    controls: list[ControlSpec] = Field(min_length=3, max_length=3)


def build_tools(sources, event, submitted, lock, *, reviewer, fixed_proposal):
    """每次调用创建一组工具，阅读记录只属于本次 Agent。"""
    by_id = {row["id"]: row for row in sources}
    read_at = {}

    @tool
    def read_evidence(source_ids: list[str]) -> str:
        """Read verbatim excerpts for up to six registered source IDs."""
        with lock:
            requested = set(source_ids)
            if not 1 <= len(source_ids) <= 6 or requested - by_id.keys() or len(read_at.keys() | requested) > 6:
                return "Invalid source IDs or evidence budget exceeded."
            for key in requested:
                read_at.setdefault(key, event["model_calls"])
        fields = ("id", "title", "scope", "locator", "excerpt")
        return json.dumps([{field: by_id[key][field] for field in fields}
                           for key in dict.fromkeys(source_ids)], ensure_ascii=False)

    def save_submission(payload):
        with lock:
            submitted.append(payload)
            event["evidence_reads"] = sorted(
                key for key, turn in read_at.items() if turn < event["model_calls"]
            )

    @tool(return_direct=True)
    def submit_result(
        hypothesis: str,
        mechanism: str,
        simple_baseline: str,
        closest_baseline: str,
        experiment: ExperimentPlan,
        comparisons: list[Comparison],
        closest_source_id: str | None = None,
    ) -> str:
        """Submit a complete proposal. Omit closest_source_id if the evidence cannot identify one."""
        save_submission({
            "design_version": 2,
            "hypothesis": hypothesis, "mechanism": mechanism,
            "simple_baseline": simple_baseline, "closest_baseline": closest_baseline,
            "experiment": experiment.model_dump(),
            "closest_source_id": closest_source_id or None,
            "comparisons": [item.model_dump() for item in comparisons],
        })
        return "Proposal submitted for validation."

    @tool("submit_result", return_direct=True)
    def submit_fixed_comparison(
        comparisons: list[Comparison],
        closest_source_id: str | None = None,
    ) -> str:
        """Submit the literature comparisons for the proposal preset by the experiment protocol."""
        save_submission({
            "closest_source_id": closest_source_id or None,
            "comparisons": [item.model_dump() for item in comparisons],
        })
        return "Literature comparisons submitted for validation."

    @tool(return_direct=True)
    def submit_audit(
        mechanism: AuditCheck,
        prior_art: AuditCheck,
        falsifiability: AuditCheck,
        feasibility: AuditCheck,
        control_review: ControlReview,
    ) -> str:
        """Submit four checks and explicitly contrast the baseline with the negative control."""
        checks = {
            "mechanism": mechanism.model_dump(),
            "prior_art": prior_art.model_dump(),
            "falsifiability": falsifiability.model_dump(),
            "feasibility": feasibility.model_dump(),
        }
        if control_review.status != "valid":
            checks["falsifiability"]["status"] = "fail" if control_review.status == "invalid" else "uncertain"
            checks["falsifiability"]["issues"].append({
                "field": "experiment.negative_control",
                "problem": f"基线操作为 {control_review.baseline_operation}；负对照操作为 {control_review.negative_operation}；机制干预为 {control_review.disabled_mechanism}。",
                "correction": control_review.correction or "明确设计使目标机制失效的操作及其预期结果。",
            })
        save_submission({"checks": checks, "control_review": control_review.model_dump()})
        return "Audit submitted for validation."

    if reviewer:
        return [read_evidence, submit_audit]
    return [read_evidence, submit_fixed_comparison if fixed_proposal else submit_result]
