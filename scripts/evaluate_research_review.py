"""Measure field-level review errors against a small, prelabelled design set."""

import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from research_loop import proposals
from research_loop.agent.llm import make_model
from research_loop.agent.main_agent import ask_agent
from research_loop.artifacts import digest, put_new, read_json
from research_loop.review import design_issues


def score_cases(results, *, include_program=False):
    true_positives = 0
    predicted = 0
    expected_count = 0
    exact_cases = 0
    for row in results:
        detected = set(row["detected"])
        if include_program:
            detected.update(row["program_findings"])
        expected = set(row["expected"])
        true_positives += len(detected & expected)
        predicted += len(detected)
        expected_count += len(expected)
        exact_cases += row["status"] == "recorded" and detected == expected
    return {
        "true_positives": true_positives,
        "expected_issues": expected_count,
        "precision": true_positives / predicted if predicted else None,
        "recall": true_positives / expected_count if expected_count else None,
        "exact_cases": exact_cases,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, type=Path)
    args = parser.parse_args()
    run = args.run.resolve()
    run.mkdir(parents=True)
    dataset = read_json(ROOT / "evals/research_loop/audit_cases.json")
    qasper = read_json(ROOT / "evals/research_loop/qasper.json")
    source = {"id": "qasper", "title": qasper["title"], "scope": "method",
              **qasper["conditions"]["method"]}
    brief = {"question": qasper["question"], "constraints": qasper["constraints"], "sources": [source]}
    results = []
    for case in dataset["cases"]:
        case_run = run / case["id"]
        prepared = proposals.prepare(case_run, brief)
        value = deepcopy(dataset["candidate"])
        value["experiment"].update(case["experiment_patch"])
        candidate = proposals.record_candidate(case_run, {**value, "brief_id": prepared["id"]})
        findings = design_issues(value)
        event = {"node": "audit"}
        started = perf_counter()
        detected = set()
        try:
            response = ask_agent(make_model(), {
                "question": brief["question"], "constraints": brief["constraints"],
                "candidate": value, "deterministic_findings": findings,
            }, brief["sources"], event, reviewer=True)
            proposals.record_audit(case_run, {**response, "candidate_id": candidate["id"]})
            for check in response["checks"].values():
                detected.update(row["field"] for row in check.get("issues", []))
            event["status"] = "recorded"
        except Exception as error:
            event.update(status="error", error=type(error).__name__)
        expected = set(case["expected_issue_fields"])
        detected &= set(dataset["scored_fields"])
        result = {
            "id": case["id"], "expected": sorted(expected), "detected": sorted(detected),
            "false_positives": sorted(detected - expected), "missed": sorted(expected - detected),
            "program_findings": sorted({row["field"] for row in findings}),
            "seconds": round(perf_counter() - started, 2), **event,
        }
        results.append(result)
        proposals.report(case_run)
        put_new(case_run / "review-evaluation.json", json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        print(f"{case['id']}: {event['status']}, missed={len(result['missed'])}", flush=True)

    summary = {
        "dataset_sha256": digest(dataset), "cases": results,
        **score_cases(results),
        "combined": score_cases(results, include_program=True),
        "scope": "四条预标注开发案例，只计负对照和单位。审查可见程序检查结果。",
    }
    put_new(run / "summary.json", json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(run / "summary.json")


if __name__ == "__main__":
    main()
