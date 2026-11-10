import json
from pathlib import Path

import pytest

from research_loop import proposals
from research_loop.__main__ import main


def record_brief(run, scope="method"):
    return proposals.prepare(run, {
        "question": "Can a reranker reduce missed evidence?",
        "constraints": "Fixed retrieval pool and CPU-only budget.",
        "sources": [{
            "id": "s1", "title": "Synthetic reading fixture",
            "reference": "fixture.md", "locator": "Methods",
            "scope": scope, "excerpt": "The baseline ranks candidates by term frequency.",
        }],
    })


def candidate_for(brief):
    return {
        "brief_id": brief["id"], "hypothesis": "Late fusion improves document recall.",
        "mechanism": "Compute two rankings for each query and fuse them.",
        "simple_baseline": "Keyword ranking.",
        "closest_baseline": "Term-frequency reranking with the same pool.",
        "closest_source_id": "s1",
        "comparisons": [{
            "source_id": "s1", "quote": "ranks candidates by term frequency",
            "relationship": "distinct", "reason": "It uses one ranking signal.",
        }],
        "experiment": {
            "metric": "recall", "unit": "percentage points", "better": "higher",
            "minimum_gain": 2, "evaluation_data": "Frozen queries and labels.",
            "matched_conditions": "Same candidate pool and top-k.",
            "negative_control": "Shuffle one ranking.",
            "expected_control_behavior": "The improvement should disappear.",
        },
    }


def review_for(candidate, prior_art="pass"):
    return {"candidate_id": candidate["id"], "checks": {
        name: {"status": prior_art if name == "prior_art" else "pass", "basis": "Test fixture."}
        for name in proposals.CHECKS
    }}


def test_proposal_refuses_forged_excerpt_and_invalid_threshold(tmp_path):
    run = tmp_path / "run"
    brief = record_brief(run)
    candidate = candidate_for(brief)
    candidate["comparisons"][0]["quote"] = "made-up quote"
    with pytest.raises(ValueError, match="Quote missing"):
        proposals.record_candidate(run, candidate)
    candidate = candidate_for(brief)
    candidate["experiment"]["minimum_gain"] = float("inf")
    with pytest.raises(ValueError, match="positive finite"):
        proposals.record_candidate(run, candidate)
    assert proposals.describe(run)["state"] == "awaiting_candidate"


def test_review_is_bound_to_exact_candidate_version(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    a = proposals.record_candidate(first, candidate_for(record_brief(first)))
    revised = candidate_for(record_brief(second))
    revised["hypothesis"] = "Revised hypothesis with a narrower scope."
    b = proposals.record_candidate(second, revised)
    assert a["id"] != b["id"]
    with pytest.raises(ValueError, match="different candidate version"):
        proposals.record_audit(second, review_for(a))
    assert proposals.describe(second)["state"] == "awaiting_review"
    proposals.record_audit(second, review_for(b))
    assert proposals.describe(second)["state"] == "ready_for_pilot"


@pytest.mark.parametrize(("scope", "prior_art", "relationship"), [
    ("abstract", "pass", "distinct"),
    ("method", "uncertain", "distinct"),
    ("method", "pass", "same_mechanism"),
])
def test_readiness_needs_method_evidence_and_no_unresolved_review(tmp_path, scope, prior_art, relationship):
    run = tmp_path / "run"
    value = candidate_for(record_brief(run, scope=scope))
    value["comparisons"][0]["relationship"] = relationship
    candidate = proposals.record_candidate(run, value)
    proposals.record_audit(run, review_for(candidate, prior_art=prior_art))
    state = proposals.describe(run)
    assert state["state"] == "needs_revision"
    assert state["reasons"]
    assert "任一对照" in state["falsification_rule"]


def test_report_delivers_a_plan_and_preserves_the_previous_report(tmp_path):
    run = tmp_path / "run"
    brief = record_brief(run)
    candidate = proposals.record_candidate(run, candidate_for(brief))
    pending = proposals.report(run)
    proposals.record_audit(run, review_for(candidate))
    ready = proposals.finish(run)
    assert ready["state"] == "ready_for_pilot"
    assert ready["report"] != pending["report"]
    assert Path(pending["report"]).exists()
    body = Path(ready["report"]).read_text(encoding="utf-8")
    assert "证伪条件" in body
    assert "尚未运行小试" in body
    assert "## 实测结果" not in body
    with pytest.raises(ValueError, match="No pilot adapter"):
        proposals.run_pilot(run)


def prepare_tsk_example(run):
    case = proposals.read_json(proposals.TSK_EXAMPLE / "case.json")
    proposal = proposals.read_json(proposals.TSK_EXAMPLE / "proposal.json")
    closest = next(row for row in case["materials"] if row["id"] == "swila")
    brief = proposals.prepare(run, {
        "question": case["question"],
        "constraints": "离线合成数据流程演示。审查输入是测试样例，实验数字来自实际运行。",
        "sources": [{
            "id": closest["id"], "title": closest["title"], "reference": closest["url"],
            "locator": closest["locator"], "scope": "method", "excerpt": closest["excerpt"],
        }],
    })
    record = candidate_for(brief)
    record.update(hypothesis=proposal["hypothesis"], mechanism=proposal["mechanism"],
                  simple_baseline="joint_ridge", closest_baseline="strong_ridge",
                  closest_source_id="swila", pilot_adapter="tsk_overlap")
    record["comparisons"] = [{"source_id": "swila", "quote": closest["excerpt"],
                              "relationship": "distinct",
                              "reason": "此演示评估固定模糊前件后的条件谱收缩。"}]
    record["experiment"].update(metric="RMSE", unit="RMSE", better="lower", minimum_gain=0.002,
                                evaluation_data="synthetic_prequential",
                                matched_conditions="相同数据流、历史窗口与长期参数。",
                                negative_control="no_drift",
                                expected_control_behavior="无漂移时误差相对联合岭不得退步超过固定协议门槛。")
    return record


def test_pilot_executes_fixed_benchmark_after_review_and_reports_negative_result(tmp_path, monkeypatch, capsys):
    run = tmp_path / "run"
    value = prepare_tsk_example(run)
    with pytest.raises(ValueError, match="demonstration question"):
        proposals.record_candidate(run, {**value, "mechanism": "A different method."})
    candidate = proposals.record_candidate(run, value)
    with pytest.raises(ValueError, match="passed review"):
        proposals.run_pilot(run)
    proposals.record_audit(run, review_for(candidate))
    with monkeypatch.context() as modified:
        modified.setattr(proposals, "pilot_protocol", lambda: {"adapter_sha256": "different"})
        with pytest.raises(ValueError, match="protocol changed"):
            proposals.run_pilot(run)
    main(["proposal", "finish", "--run", str(run)])
    result = json.loads(capsys.readouterr().out)
    assert result["state"] == "pilot_does_not_support_claim"
    assert result["pilot"]["gains_vs_controls"]["strong_ridge"] < 0
    assert proposals.run_pilot(run)["id"] == result["versions"]["pilot"]
    body = Path(result["report"]).read_text(encoding="utf-8")
    assert "## 实测结果" in body
    assert "overlap_shared" in body
    assert "本次小试未支持预设主张" in body
