from pathlib import Path

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

from research_loop import proposals
from research_loop.agent_graph import run_research
from research_loop.workflow import read_json


class ScriptedToolModel(BaseChatModel):
    replies: list[AIMessage]
    requests: list = Field(default_factory=list)
    visible_tools: list = Field(default_factory=list)

    @property
    def _llm_type(self):
        return "scripted-test-model"

    def bind_tools(self, tools, **kwargs):
        self.visible_tools.append({tool.name for tool in tools})
        return self

    def get_num_tokens_from_messages(self, messages, tools=None):
        return 100

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        index = len(self.requests)
        self.requests.append(list(messages))
        if index >= len(self.replies):
            raise AssertionError("Unexpected model call")
        return ChatResult(generations=[ChatGeneration(message=self.replies[index])])


def call(name, args, identity):
    if name == "submit_audit":
        args = {"control_review": {
            "baseline_operation": "Original baseline",
            "negative_operation": "Disable the target signal",
            "disabled_mechanism": "The proposed informative signal",
            "status": "valid", "correction": "",
        }, **args}
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": identity}])


def submit(value, identity):
    if "experiment" in value:
        value = {**value, "experiment": {**value["experiment"], "controls": controls_for(value)}}
    return call("submit_result", value, identity)


def controls_for(value):
    return [
        {"role": role, "method": method, "changed_factor": "Fixed test factor",
         "held_constant": "Same test conditions", "expected": "Test fixture expectation"}
        for role, method in (
            ("simple_baseline", value["simple_baseline"]),
            ("closest_baseline", value["closest_baseline"]),
            ("negative_control", value["experiment"]["negative_control"]),
        )
    ]

def fixture():
    case = read_json(proposals.TSK_EXAMPLE / "case.json")
    source = next(row for row in case["materials"] if row["id"] == "swila")
    brief = {
        "question": case["question"], "constraints": "Only the fixed synthetic benchmark.",
        "sources": [{
            "id": source["id"], "title": source["title"], "reference": source["url"],
            "locator": source["locator"], "scope": "method", "excerpt": source["excerpt"],
        }],
    }
    draft = {"closest_source_id": "swila", "comparisons": [
        {"source_id": "swila", "quote": source["excerpt"], "relationship": "distinct",
         "reason": "Online EM and conditional shrinkage use different update rules."}
    ]}
    audit = {"checks": {name: {"status": "pass", "basis": "Scripted protocol test."}
                        for name in proposals.CHECKS}}
    return brief, draft, audit


def test_two_real_deep_agent_harnesses_read_separately_and_graph_runs_the_pilot(tmp_path):
    brief, draft, audit = fixture()
    author = ScriptedToolModel(replies=[
        call("read_evidence", {"source_ids": ["swila"]}, "author-read"),
        submit(draft, "author-submit"),
    ])
    reviewer = ScriptedToolModel(replies=[
        call("read_evidence", {"source_ids": ["swila"]}, "review-read"),
        call("submit_audit", audit["checks"], "review-submit"),
    ])
    models = iter([author, reviewer])
    result = run_research(tmp_path / "run", brief, model_factory=lambda: next(models), adapter="tsk_overlap")
    assert result["state"] == "pilot_does_not_support_claim"
    assert "## 实测结果" in Path(result["report"]).read_text(encoding="utf-8")
    trace = read_json(Path(result["agent_trace"]))
    assert [row["node"] for row in trace] == ["prepare", "draft", "audit", "deliver"]
    for model, own_read, tool in ((author, "author-read", "submit_result"),
                                  (reviewer, "review-read", "submit_audit")):
        assert len(model.requests) == 2
        assert all(names == {"read_evidence", tool} for names in model.visible_tools)
        assert not any(isinstance(message, ToolMessage) for message in model.requests[0])
        assert {message.tool_call_id for message in model.requests[1] if isinstance(message, ToolMessage)} == {own_read}


def test_unverified_comparison_gets_one_retry_then_a_report(tmp_path):
    brief, draft, _ = fixture()
    models = iter([
        ScriptedToolModel(replies=[submit(draft, "submit-without-reading")]),
        ScriptedToolModel(replies=[submit(draft, "again-without-reading")]),
    ])
    result = run_research(tmp_path / "run", brief, model_factory=lambda: next(models), adapter="tsk_overlap")
    assert result["state"] == "awaiting_candidate"
    trace = read_json(Path(result["agent_trace"]))
    assert [row["node"] for row in trace] == ["prepare", "draft", "draft", "deliver"]
    assert all(row["status"] == "rejected" for row in trace if row["node"] == "draft")


def test_reviewer_cannot_pass_prior_art_without_its_own_read(tmp_path):
    brief, draft, audit = fixture()
    models = iter([
        ScriptedToolModel(replies=[call("read_evidence", {"source_ids": ["swila"]}, "a-read"),
                                   submit(draft, "a-submit")]),
        ScriptedToolModel(replies=[call("submit_audit", audit["checks"], "r-submit")]),
    ])
    result = run_research(tmp_path / "run", brief, model_factory=lambda: next(models), adapter="tsk_overlap")
    assert result["state"] == "awaiting_review"
    assert "pilot" not in result["versions"]
    assert read_json(Path(result["agent_trace"]))[-2]["status"] == "not_recorded"


def test_incomplete_audit_tool_arguments_leave_review_pending(tmp_path):
    brief, draft, audit = fixture()
    incomplete = {name: check for name, check in audit["checks"].items() if name != "feasibility"}
    reviewer = ScriptedToolModel(replies=[
        call("read_evidence", {"source_ids": ["swila"]}, "r-read"),
        call("submit_audit", incomplete, "incomplete-audit"),
    ])
    models = iter([
        ScriptedToolModel(replies=[call("read_evidence", {"source_ids": ["swila"]}, "a-read"),
                                   submit(draft, "a-submit")]),
        reviewer,
    ])
    result = run_research(tmp_path / "run", brief, model_factory=lambda: next(models),
                          adapter="tsk_overlap", plan_only=True)
    assert result["state"] == "awaiting_review"
    assert "audit" not in result["versions"]
    assert "pilot" not in result["versions"]
    trace = read_json(Path(result["agent_trace"]))
    assert trace[-2]["status"] == "not_recorded"
    assert trace[-2]["tool_calls"] == ["read_evidence", "submit_audit"]


def test_plain_text_draft_gets_a_submission_reminder_with_only_abstract_evidence(tmp_path):
    brief, draft, audit = fixture()
    brief["sources"][0]["scope"] = "abstract"
    draft.pop("closest_source_id")
    draft["comparisons"][0]["relationship"] = "uncertain"
    draft.update(
        hypothesis="The update can improve prediction on the target stream.",
        mechanism="Apply shrinkage in directions with low support in the window.",
        simple_baseline="joint ridge",
        closest_baseline="strong ridge",
        experiment={
            "metric": "RMSE",
            "unit": "RMSE",
            "better": "lower",
            "minimum_gain": 0.002,
            "evaluation_data": "fixed synthetic stream",
            "matched_conditions": "Use the same seeds and history windows.",
            "negative_control": "no drift",
            "expected_control_behavior": "No material regression under stationary inputs.",
        },
    )
    audit["checks"]["prior_art"] = {"status": "uncertain", "basis": "Only the abstract was available."}
    author = ScriptedToolModel(replies=[
        call("read_evidence", {"source_ids": ["swila"]}, "a-read"),
        AIMessage(content="An online shrinkage plan with a fixed comparison."),
        submit(draft, "a-submit"),
    ])
    reviewer = ScriptedToolModel(replies=[
        call("read_evidence", {"source_ids": ["swila"]}, "r-read"),
        call("submit_audit", audit["checks"], "r-submit"),
    ])
    models = iter([author, reviewer])
    result = run_research(tmp_path / "run", brief, model_factory=lambda: next(models), plan_only=True)
    assert result["state"] == "needs_revision"
    assert "audit" in result["versions"]
    trace = read_json(Path(result["agent_trace"]))
    assert trace[1]["submission_reminder"] is True
    assert trace[1]["evidence_reads"] == ["swila"]
    assert "submit_result tool" in author.requests[2][-1].content
