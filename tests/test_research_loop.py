import copy
import json
from pathlib import Path

import numpy as np
import pytest

from research_loop import experiment, workflow


CASE = Path(__file__).resolve().parents[1] / "examples/research_loop/tsk_overlap"


@pytest.fixture
def prepared(tmp_path):
    run = tmp_path / "run"
    request = workflow.prepare(CASE / "case.json", run)
    proposal = workflow.read_json(CASE / "proposal.json")
    return run, {"request_id": request["id"], "proposal": proposal}


def test_stale_request_and_fabricated_quote_do_not_create_receipt(prepared):
    run, submission = prepared
    with pytest.raises(ValueError, match="different request"):
        workflow.record(run, {**submission, "request_id": "stale"})
    fabricated = copy.deepcopy(submission)
    fabricated["proposal"]["nearby_work"][0]["quote"] = "This sentence does not exist."
    with pytest.raises(ValueError, match="quote missing"):
        workflow.record(run, fabricated)
    assert not (run / "proposal.json").exists()


def test_receipt_cannot_be_overwritten_or_tampered_silently(prepared):
    run, submission = prepared
    recorded = workflow.record(run, submission)
    with pytest.raises(ValueError, match="without a proposal"):
        workflow.record(run, submission)
    assert workflow.read_run(run)["proposal"]["id"] == recorded["id"]
    path = run / "proposal.json"
    saved = json.loads(path.read_text(encoding="utf-8"))
    saved["payload"]["hypothesis"] = "Altered after the original record."
    path.write_text(json.dumps(saved), encoding="utf-8")
    with pytest.raises(ValueError, match="Receipt or parent mismatch"):
        workflow.read_run(run)


def test_future_labels_cannot_change_a_prediction():
    a, b, prior, y = experiment.stream(101, "overlap_shared", 144)
    altered = y.copy()
    altered[51:] += 100
    original = experiment.predictions(a, b, prior, y, 51, 16, 0.025, [0.02])
    assert original == experiment.predictions(a, b, prior, altered, 51, 16, 0.025, [0.02])


def test_schur_joint_baseline_agrees_with_direct_ridge():
    a, b, prior, y = experiment.stream(102, "overlap_shared", 144)
    t, width, penalty = 70, 16, 0.025
    history = slice(t - width, t)
    features = np.column_stack((a[history], b[history]))
    rhs = features.T @ (y[history] - prior[history])
    direct = prior[t] + np.concatenate((a[t], b[t])) @ np.linalg.solve(
        features.T @ features + penalty * np.eye(features.shape[1]), rhs
    )
    result = experiment.predictions(a, b, prior, y, t, width, penalty, [])
    assert result["joint_ridge"] == pytest.approx(direct, abs=1e-10)


def test_positive_main_result_does_not_override_a_slice_regression():
    candidate = "candidate"
    scores = {
        scenario: {**dict.fromkeys(experiment.CONTROLS, 1.0), candidate: 0.95}
        for scenario in experiment.SCENARIOS
    }
    scores["overlap_contrast"][candidate] = 1.03
    decision = experiment.gate(scores, candidate, experiment.SPEC)
    assert decision["gains_vs_joint_ridge"][experiment.PRIMARY] > 0
    assert not decision["passes"]
    assert decision["failures"] == ["regression:overlap_contrast"]
