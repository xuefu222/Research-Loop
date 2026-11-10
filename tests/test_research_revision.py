from copy import deepcopy
from pathlib import Path

import pytest

from research_loop import proposals
from research_loop.agent_graph import run_research
from research_loop.artifacts import read_json
from research_loop.evidence import supplement
from research_loop.review import design_issues
from research_loop.agent.main_agent import ask_agent
from test_research_agent_graph import ScriptedToolModel, call, controls_for, submit
from test_research_proposal import candidate_for, record_brief, review_for


def setup_candidate(tmp_path):
    brief = record_brief(tmp_path / "fixture")
    candidate = candidate_for(brief)
    candidate.pop("brief_id")
    return brief["payload"], candidate


def model_for_proposal(value):
    return ScriptedToolModel(replies=[
        call("read_evidence", {"source_ids": ["s1"]}, "read"),
        submit(value, "submit"),
    ])


def model_for_audit(status):
    checks = {name: {"status": "pass", "basis": "Controlled test"} for name in proposals.CHECKS}
    checks["falsifiability"] = {"status": status, "basis": "Check negative-control design"}
    if status == "fail":
        checks["falsifiability"]["issues"] = [{
            "field": "experiment.negative_control", "problem": "Duplicates baseline",
            "correction": "Shuffle the additional ranking signal",
        }]
    return ScriptedToolModel(replies=[
        call("read_evidence", {"source_ids": ["s1"]}, "read"),
        call("submit_audit", checks, "submit"),
    ])


def test_failed_design_retrieves_revises_and_preserves_old_receipts(tmp_path, retriever):
    brief, good = setup_candidate(tmp_path)
    bad = deepcopy(good)
    bad["experiment"]["negative_control"] = bad["simple_baseline"]
    models = iter([model_for_proposal(bad), model_for_audit("fail"),
                   model_for_proposal(good), model_for_audit("pass")])
    run = tmp_path / "run"
    result = run_research(run, brief, model_factory=lambda: next(models), plan_only=True,
                          retriever=retriever, doc_ids=["qasper"], retrieval_scope="abstract")
    assert result["state"] == "ready_for_pilot"
    assert result["revision_rounds"] == 1
    assert Path(result["report"]).parent == run / "revisions/01"
    assert read_json(run / "candidate.json")["payload"]["experiment"]["negative_control"] == bad["simple_baseline"]
    lineage = read_json(run / "revisions/01/revision.json")
    assert lineage["previous_candidate_id"] == read_json(run / "candidate.json")["id"]
    assert len(list(run.glob("RESULT-*.md"))) == 1
    assert lineage["retrieval"]["added_sources"]
    revised_brief = read_json(run / "revisions/01/brief.json")["payload"]
    assert len(revised_brief["sources"]) == 2
    assert revised_brief["sources"][-1]["scope"] == "abstract"


def test_failed_revision_delivers_previous_audited_report(tmp_path):
    brief, bad = setup_candidate(tmp_path)
    bad["experiment"]["negative_control"] = bad["simple_baseline"]
    models = iter([
        model_for_proposal(bad), model_for_audit("fail"),
        ScriptedToolModel(replies=[submit(bad, "no-read-1")]),
        ScriptedToolModel(replies=[submit(bad, "no-read-2")]),
    ])
    run = tmp_path / "run"
    result = run_research(run, brief, model_factory=lambda: next(models), plan_only=True)
    assert Path(result["report"]).parent == run
    assert result["state"] == "needs_revision"
    assert result["versions"]["audit"] == read_json(run / "audit.json")["id"]
    assert read_json(Path(result["agent_trace"]))[-1]["incomplete_revision"].endswith("01")


def test_revision_limit_stops_without_losing_audited_plan(tmp_path):
    brief, bad = setup_candidate(tmp_path)
    bad["experiment"]["negative_control"] = bad["simple_baseline"]
    models = iter([model_for_proposal(bad), model_for_audit("fail"),
                   model_for_proposal(bad), model_for_audit("fail")])
    result = run_research(tmp_path / "run", brief, model_factory=lambda: next(models), plan_only=True)
    assert result["state"] == "needs_revision"
    assert result["revision_rounds"] == 1


def test_program_blocks_bad_design_even_if_reviewer_passes(tmp_path):
    run = tmp_path / "run"
    brief = record_brief(run)
    candidate = candidate_for(brief)
    candidate["design_version"] = 2
    candidate["experiment"].update(negative_control=candidate["simple_baseline"], unit="%")
    candidate["experiment"]["controls"] = controls_for(candidate)
    receipt = proposals.record_candidate(run, candidate)
    proposals.record_audit(run, review_for(receipt))
    assert proposals.describe(run)["state"] == "needs_revision"
    assert {row["field"] for row in design_issues(candidate)} == {
        "experiment.negative_control", "experiment.unit",
    }


def test_hybrid_supplement_respects_document_and_abstract_scope(tmp_path, retriever):
    brief, _ = setup_candidate(tmp_path)
    expanded, receipt = supplement(brief, retriever, doc_ids=["qasper"], scope="abstract")
    added = expanded["sources"][1:]
    assert len(added) == 1
    assert added[0]["scope"] == "abstract"
    assert "GPU" not in added[0]["excerpt"]
    assert receipt["method"] == "hybrid"
    assert receipt["index_sha256"] == retriever.fingerprint
    again, receipt = supplement(expanded, retriever, doc_ids=["qasper"], scope="abstract")
    assert again == expanded
    assert receipt["added_sources"] == []


def test_passing_review_cannot_contain_unresolved_issue(tmp_path):
    run = tmp_path / "run"
    receipt = proposals.record_candidate(run, candidate_for(record_brief(run)))
    audit = review_for(receipt)
    audit["checks"]["feasibility"]["issues"] = [{
        "field": "experiment.controls", "problem": "Missing intervention", "correction": "Specify it",
    }]
    with pytest.raises(ValueError, match="cannot pass"):
        proposals.record_audit(run, audit)


def test_invalid_control_assessment_blocks_otherwise_passing_review(tmp_path):
    brief, candidate = setup_candidate(tmp_path)
    checks = {name: {"status": "pass", "basis": "Test"} for name in proposals.CHECKS}
    reviewer = ScriptedToolModel(replies=[
        call("read_evidence", {"source_ids": ["s1"]}, "r-read"),
        call("submit_audit", {**checks, "control_review": {
            "baseline_operation": "Run baseline",
            "negative_operation": "Run baseline again",
            "disabled_mechanism": "None",
            "status": "invalid",
            "correction": "Shuffle the added ranking signal",
        }}, "r-submit"),
    ])
    models = iter([model_for_proposal(candidate), reviewer])
    result = run_research(tmp_path / "run", brief, model_factory=lambda: next(models),
                          plan_only=True, max_revisions=0)
    assert result["state"] == "needs_revision"
    audit = read_json(tmp_path / "run/audit.json")["payload"]
    assert audit["checks"]["falsifiability"]["status"] == "fail"
    assert audit["checks"]["falsifiability"]["issues"][0]["field"] == "experiment.negative_control"


def test_transient_author_timeout_retries_before_committing(tmp_path):
    brief, candidate = setup_candidate(tmp_path)
    attempts = iter([TimeoutError("temporary"), model_for_proposal(candidate), model_for_audit("pass")])

    def factory():
        model = next(attempts)
        if isinstance(model, Exception):
            raise model
        return model

    result = run_research(tmp_path / "run", brief, model_factory=factory, plan_only=True)
    assert result["state"] == "ready_for_pilot"
    drafts = [row for row in read_json(Path(result["agent_trace"])) if row["node"] == "draft"]
    assert [row["status"] for row in drafts] == ["error", "recorded"]


def test_four_registered_excerpts_are_read_before_submission(tmp_path):
    brief, candidate = setup_candidate(tmp_path)
    sources = [{**brief["sources"][0], "id": f"s{index}"} for index in range(1, 5)]
    model = ScriptedToolModel(replies=[
        call("read_evidence", {"source_ids": [row["id"] for row in sources]}, "read-four"),
        submit(candidate, "submit"),
    ])
    event = {}
    ask_agent(model, {"question": brief["question"]}, sources, event)
    assert event["evidence_reads"] == ["s1", "s2", "s3", "s4"]
