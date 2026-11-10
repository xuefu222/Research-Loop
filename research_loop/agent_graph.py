"""用 LangGraph 编排研究提案、审查与交付。"""

import json
from operator import add
from pathlib import Path
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph

from . import proposals
from .agent.llm import make_model
from .agent.main_agent import ask_agent
from .artifacts import put_new, read_json
from .review import design_issues


MAX_AUTHOR_ATTEMPTS = 2


class ResearchState(TypedDict, total=False):
    material: dict
    run_path: str
    round: int
    feedback: dict
    revise: bool
    previous_run: str
    brief: dict
    candidate: dict | None
    author_attempts: int
    retry_author: bool
    error: str | None
    events: Annotated[list[dict], add]
    result: dict


def locked_pilot(brief, adapter):
    if adapter is None:
        return {}, {}
    if adapter != "tsk_overlap":
        raise ValueError("Unsupported experimental adapter")
    case = read_json(proposals.TSK_EXAMPLE / "case.json")
    known = read_json(proposals.TSK_EXAMPLE / "proposal.json")
    if brief["question"] != case["question"]:
        raise ValueError("The TSK adapter is only available for the supplied demonstration question")
    return {
        "hypothesis": known["hypothesis"], "mechanism": known["mechanism"],
        "simple_baseline": "joint_ridge", "closest_baseline": "strong_ridge",
    }, {
        "metric": "RMSE", "unit": "RMSE", "better": "lower", "minimum_gain": 0.002,
        "evaluation_data": "synthetic_prequential",
        "matched_conditions": "相同合成数据流、历史窗口和长期参数。",
        "negative_control": "no_drift",
        "expected_control_behavior": "固定协议下，无漂移情景相对联合岭的退步不能超过预设门槛。",
    }


def build_graph(run, brief_input, model_factory, *, adapter=None, plan_only=False,
                max_revisions=1, retriever=None, doc_ids=None, retrieval_scope="full"):
    locked, fixed_experiment = locked_pilot(brief_input, adapter)

    def prepare(state):
        brief = proposals.prepare(run, brief_input)
        return {"brief": brief, "material": brief_input, "run_path": str(run), "round": 0,
                "author_attempts": 0, "candidate": None, "feedback": {},
                "events": [{"node": "prepare", "status": "recorded", "brief_id": brief["id"]}]}

    def draft(state):
        attempt = state["author_attempts"] + 1
        event = {"node": "draft", "attempt": attempt, "round": state["round"]}
        validating_proposal = False
        try:
            value = ask_agent(model_factory(), {
                "question": brief_input["question"], "constraints": brief_input["constraints"],
                "prior_failure": state.get("error"),
                "revision_feedback": state["feedback"],
                "locked_fields": {**locked, **({"experiment": fixed_experiment} if adapter else {})},
            }, state["material"]["sources"], event)
            validating_proposal = True
            if {"pilot_adapter", "pilot_protocol"} & value.keys():
                raise ValueError("Experiment adapter can only be chosen by the caller")
            if adapter:
                value = {**value, **locked, "experiment": fixed_experiment, "pilot_adapter": adapter}
            comparisons = value.get("comparisons")
            if not isinstance(comparisons, list) or any(
                not isinstance(row, dict) or row.get("source_id") not in event["evidence_reads"]
                for row in comparisons
            ):
                raise ValueError("Every compared excerpt must be read through read_evidence")
            candidate = proposals.record_candidate(Path(state["run_path"]),
                                                   {**value, "brief_id": state["brief"]["id"]})
        except (ValueError, TypeError, KeyError) as error:
            # Share validator guidance with the retry, never model API exception bodies.
            event.update(status="rejected", error=type(error).__name__)
            guidance = str(error)[:240] if type(error) is ValueError else type(error).__name__
            if validating_proposal:
                event["validation_error"] = guidance
            return {"author_attempts": attempt, "retry_author": attempt < MAX_AUTHOR_ATTEMPTS,
                    "error": guidance, "events": [event]}
        except Exception as error:
            event.update(status="error", error=type(error).__name__)
            if isinstance(getattr(error, "status_code", None), int):
                event["http_status"] = error.status_code
            transient = (type(error).__name__.endswith(("TimeoutError", "ConnectionError"))
                         or getattr(error, "status_code", None) in (429, 500, 502, 503, 504))
            return {"author_attempts": attempt, "retry_author": transient and attempt < MAX_AUTHOR_ATTEMPTS,
                    "error": "提案 Agent 执行失败。", "events": [event]}
        event.update(status="recorded", candidate_id=candidate["id"])
        return {"candidate": candidate, "author_attempts": attempt, "retry_author": False,
                "error": None, "events": [event]}

    def audit(state):
        event = {"node": "audit", "round": state["round"]}
        candidate = state["candidate"]
        findings = design_issues(candidate["payload"])
        try:
            value = ask_agent(model_factory(), {
                "question": brief_input["question"], "constraints": brief_input["constraints"],
                "candidate": candidate["payload"],
                "deterministic_findings": findings,
            }, state["material"]["sources"], event, reviewer=True)
            closest = candidate["payload"]["closest_source_id"]
            if value["checks"]["prior_art"]["status"] == "pass" and closest not in event["evidence_reads"]:
                raise ValueError("Reviewer must read the closest source to pass prior-art review")
            current_run = Path(state["run_path"])
            receipt = proposals.record_audit(current_run, {**value, "candidate_id": candidate["id"]})
        except Exception as error:
            event.update(status="not_recorded", error=type(error).__name__)
            if isinstance(getattr(error, "status_code", None), int):
                event["http_status"] = error.status_code
            return {"error": "审查 Agent 未提交有效结果。", "revise": False, "events": [event]}
        event.update(status="recorded", audit_id=receipt["id"])
        status = proposals.describe(current_run)["state"]
        checks = receipt["payload"]["checks"]
        design_failed = findings or any(checks[key]["status"] != "pass"
                                       for key in ("mechanism", "falsifiability", "feasibility"))
        can_revise = (status == "needs_revision" and state["round"] < max_revisions
                      and adapter is None and (design_failed or retriever is not None))
        return {"events": [event], "revise": bool(can_revise),
                "feedback": {"candidate": candidate["payload"], "checks": checks,
                             "deterministic_findings": findings}}

    def revise(state):
        # 每轮先交付旧报告，再在新目录登记，保持提案与审查的版本关系。
        current_run = Path(state["run_path"])
        proposals.report(current_run)
        material = state["material"]
        event = {"node": "revise", "round": state["round"] + 1}
        if retriever is not None:
            from .evidence import supplement

            try:
                material, retrieval = supplement(material, retriever, doc_ids=doc_ids,
                                                  scope=retrieval_scope)
                event["retrieval"] = retrieval
            except (OSError, ValueError, RuntimeError) as error:
                event["retrieval_error"] = type(error).__name__
        next_run = run / "revisions" / f"{state['round'] + 1:02d}"
        brief = proposals.prepare(next_run, material)
        put_new(next_run / "revision.json", json.dumps({
            "previous_candidate_id": state["candidate"]["id"],
            "previous_audit_id": read_json(current_run / "audit.json")["id"],
            "feedback": state["feedback"], "retrieval": event.get("retrieval"),
        }, ensure_ascii=False, indent=2) + "\n")
        return {"run_path": str(next_run), "previous_run": str(current_run), "brief": brief,
                "material": material, "round": state["round"] + 1, "candidate": None,
                "author_attempts": 0, "error": None, "revise": False, "events": [event]}

    def deliver(state):
        event = {"node": "deliver", "mode": "plan_only" if plan_only else "allow_pilot"}
        current_run = Path(state["run_path"])
        if state["candidate"] is None and state.get("previous_run"):
            event["incomplete_revision"] = str(current_run)
            current_run = Path(state["previous_run"])
        try:
            result = proposals.report(current_run) if plan_only else proposals.finish(current_run)
        except (OSError, ValueError, RuntimeError) as error:
            result = proposals.report(current_run)
            event["pilot_error"] = type(error).__name__
        event["status"] = result["state"]
        return {"result": result, "events": [event]}

    def after_draft(state):
        if state["candidate"] is not None:
            return "audit"
        return "draft" if state["retry_author"] else "deliver"

    # 外层图控制阶段。各节点里的 Agent 只负责完成本阶段的任务。
    graph = StateGraph(ResearchState)
    graph.add_node("prepare", prepare)
    graph.add_node("draft", draft)
    graph.add_node("audit", audit)
    graph.add_node("revise", revise)
    graph.add_node("deliver", deliver)
    graph.add_edge(START, "prepare")
    graph.add_edge("prepare", "draft")
    graph.add_conditional_edges("draft", after_draft, ["audit", "draft", "deliver"])
    graph.add_conditional_edges("audit", lambda state: "revise" if state["revise"] else "deliver",
                                ["revise", "deliver"])
    graph.add_edge("revise", "draft")
    graph.add_edge("deliver", END)
    return graph.compile()


def run_research(run: Path, brief: dict, *, model_factory=make_model, adapter=None, plan_only=False,
                 max_revisions=1, retriever=None, doc_ids=None, retrieval_scope="full"):
    if type(max_revisions) is not int or not 0 <= max_revisions <= 2:
        raise ValueError("max_revisions must be 0, 1 or 2")
    graph = build_graph(run, brief, model_factory, adapter=adapter, plan_only=plan_only,
                        max_revisions=max_revisions, retriever=retriever, doc_ids=doc_ids,
                        retrieval_scope=retrieval_scope)
    result = graph.invoke({}, config={"recursion_limit": 30})
    trace_path = run / "agent-trace.json"
    put_new(trace_path, json.dumps(result["events"], ensure_ascii=False, indent=2) + "\n")
    return {**result["result"], "agent_trace": str(trace_path.resolve()), "revision_rounds": result["round"]}
