"""Command-line entrypoint for the Research Loop workflow."""

import argparse
import json
from pathlib import Path
import sys

from . import proposals, workflow
from .artifacts import read_json


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(description="Run an evidence-bound, falsifiable paper experiment")
    operations = parser.add_subparsers(dest="operation", required=True)
    operations.add_parser("proposal", add_help=False, help="Review a research proposal and deliver its result")
    if argv[:1] == ["proposal"]:
        return proposals.main(argv[1:], prog=f"{parser.prog} proposal")
    agent = operations.add_parser("agent", help="Run the LangGraph and Deep Agents workflow")
    agent.add_argument("--input", required=True, type=Path)
    agent.add_argument("--run", required=True, type=Path)
    agent.add_argument("--pilot-adapter", choices=("tsk_overlap",))
    agent.add_argument("--plan-only", action="store_true")
    agent.add_argument("--max-revisions", type=int, choices=(0, 1, 2), default=1)
    agent.add_argument("--retrieve", action="store_true", help="Supplement evidence from the local hybrid index")
    agent.add_argument("--doc-id", action="append", dest="doc_ids")
    agent.add_argument("--retrieval-scope", choices=("abstract", "full"), default="full")
    for command in ("prepare", "record", "evaluate", "report", "verify", "demo"):
        sub = operations.add_parser(command)
        sub.add_argument("--run", required=True, type=Path)
        if command in ("prepare", "demo"):
            sub.add_argument("--case", required=True, type=Path)
        if command in ("record", "demo"):
            sub.add_argument("--proposal", required=True, type=Path)
    args = parser.parse_args(argv)
    run = args.run.resolve()
    try:
        if args.operation == "agent":
            from .agent_graph import run_research
            retriever = None
            if args.retrieve:
                from paper_research.retrieval import Retriever
                retriever = Retriever()

            result = run_research(run, read_json(args.input), adapter=args.pilot_adapter,
                                  plan_only=args.plan_only, max_revisions=args.max_revisions,
                                  retriever=retriever, doc_ids=args.doc_ids, retrieval_scope=args.retrieval_scope)
        if args.operation in ("prepare", "demo"):
            if args.operation == "demo":
                proposal = read_json(args.proposal)
            request = workflow.prepare(args.case, run)
            result = {"request_id": request["id"]}
        if args.operation == "demo":
            workflow.record(run, {"request_id": request["id"], "proposal": proposal})
            evaluation = workflow.evaluate(run)["payload"]
            path = workflow.report(run)
            result = {**workflow.verify(run), "report": str(path),
                      "candidate": evaluation["frozen_candidate"],
                      "policy": evaluation["recommended_policy"],
                      "experiment_gate_passed": evaluation["experiment_gate_passed"]}
        elif args.operation == "record":
            result = {"proposal_id": workflow.record(run, read_json(args.proposal))["id"]}
        elif args.operation == "evaluate":
            evaluation = workflow.evaluate(run)
            result = {"evaluation_id": evaluation["id"],
                      "experiment_gate_passed": evaluation["payload"]["experiment_gate_passed"]}
        elif args.operation == "report":
            result = {"report": str(workflow.report(run))}
        elif args.operation == "verify":
            result = workflow.verify(run)
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.exit(2, f"research-loop: {error}\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
