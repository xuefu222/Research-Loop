"""Run the same public QASPER task with two evidence scopes."""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from time import perf_counter


ROOT = Path(__file__).resolve().parents[1]
SKILL_SCRIPT = ROOT / ".agents/skills/research-loop/scripts/run_research_loop.py"
CASE = ROOT / "evals/research_loop/qasper.json"


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def evaluate_condition(root, case, scope, excerpt):
    source = {"id": "qasper", "title": case["title"], "scope": scope, **excerpt}
    brief = {
        "question": case["question"],
        "constraints": case["constraints"],
        "sources": [source],
    }
    input_path = root / f"{scope}-input.json"
    input_path.write_text(json.dumps(brief, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    run = root / scope
    start = perf_counter()
    process = subprocess.run(
        [sys.executable, "-X", "utf8", str(SKILL_SCRIPT), "agent", "--input", str(input_path),
         "--run", str(run), "--plan-only", "--max-revisions", "0"],
        cwd=ROOT, check=True, capture_output=True, encoding="utf-8", timeout=360,
    )
    result = json.loads(process.stdout)
    seconds = round(perf_counter() - start, 2)
    trace = load_json(Path(result["agent_trace"]))
    versions = result["versions"]
    candidate = load_json(run / "candidate.json")["payload"] if "candidate" in versions else {}
    checks = load_json(run / "audit.json")["payload"]["checks"] if "audit" in versions else {}
    quotes = candidate.get("comparisons", [])
    evidence_readers = [
        event["node"] for event in trace
        if event.get("status") == "recorded" and "qasper" in event.get("evidence_reads", [])
    ]
    return {
        "state": result["state"],
        "report_written": Path(result["report"]).is_file(),
        "proposal_recorded": "candidate" in versions,
        "audit_recorded": "audit" in versions,
        "closest_source_id": candidate.get("closest_source_id"),
        "prior_art": checks.get("prior_art", {}).get("status"),
        "quotes": len(quotes),
        "quotes_found_in_source": sum(
            row["source_id"] == "qasper" and row["quote"] in source["excerpt"] for row in quotes
        ),
        "evidence_readers": evidence_readers,
        "model_calls": sum(row.get("model_calls", 0) for row in trace),
        "pilot_executed": "pilot" in versions,
        "wall_seconds": seconds,
        "report": Path(result["report"]).name,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, type=Path, help="New output directory")
    args = parser.parse_args()
    root = args.run.resolve()
    root.mkdir(parents=True)
    case = load_json(CASE)
    results = {}
    for scope, source in case["conditions"].items():
        results[scope] = evaluate_condition(root, case, scope, source)
        print(f"{scope}: {results[scope]['state']}", flush=True)

    summary = root / "summary.json"
    summary.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(summary)


if __name__ == "__main__":
    main()
