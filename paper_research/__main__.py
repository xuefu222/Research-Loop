import argparse
import json
import sys
import uuid
from pathlib import Path
from .config import ROOT, INDEX, CACHE, write_json


def main():
    parser = argparse.ArgumentParser(description="论文调研与证据核验")
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build", help="提取、切分并构建混合检索索引")
    build.add_argument("--manifest", type=Path, default=ROOT / "data/corpus_manifest.json")
    build.add_argument("--output", type=Path, default=INDEX)
    search = sub.add_parser("search", help="检索候选片段")
    search.add_argument("--query", required=True)
    search.add_argument("--method", choices=["bm25", "dense", "hybrid"], default="hybrid")
    search.add_argument("--scope", choices=["full", "abstract"], default="full")
    search.add_argument("--doc-id", action="append", dest="doc_ids")
    search.add_argument("--top-k", type=int, default=6)
    search.add_argument("--lexical-query")
    search.add_argument("--index", type=Path, default=INDEX)
    search.add_argument("--output", type=Path, default=ROOT / "output/hybrid_search.json")
    run = sub.add_parser("research", help="生成带原文证据的调研报告")
    run.add_argument("--question", action="append", required=True, dest="questions")
    run.add_argument("--scope", choices=["full", "abstract"], default="full")
    run.add_argument("--doc-id", action="append", dest="doc_ids")
    run.add_argument("--mode", choices=["agent", "packet"], default="agent")
    run.add_argument("--output-dir", type=Path)
    run.add_argument("--selection-prompt", type=Path, help="显式使用已审阅的候选证据选择提示词")
    serve = sub.add_parser("serve", help="启动本地网页与 API")
    serve.add_argument("--port", type=int, default=8765)
    evaluate = sub.add_parser("evaluate", help="运行固定证据标注的检索评测")
    evaluate.add_argument("--cases", type=Path, default=ROOT / "evals/cases.json")
    evaluate.add_argument("--output", type=Path, default=ROOT / "output/retrieval_evaluation.json")
    tune = sub.add_parser("tune", help="只在训练和验证论文上选择检索策略")
    tune.add_argument("--output", type=Path, default=ROOT / "output/retrieval_tuning.json")
    gepa = sub.add_parser("gepa", help="GEPA 优化证据选择提示词")
    gepa.add_argument("--budget", type=int, default=12)
    gepa.add_argument("--output", type=Path, default=ROOT / "output/gepa")
    args = parser.parse_args()
    try:
        if args.command == "build":
            from .indexing import build_index
            result = build_index(args.manifest, args.output)
        elif args.command == "search":
            from .retrieval import Retriever
            if args.index.resolve() == args.output.resolve():
                raise ValueError("检索输出不能覆盖输入索引")
            result = Retriever(args.index).search(args.query, args.top_k, args.method,
                args.scope, args.doc_ids, args.lexical_query)
            write_json(args.output, result)
        elif args.command == "research":
            from .workflow import research
            from .reporting import save_artifacts
            result = research(args.questions, args.scope, args.doc_ids, args.mode,
                selection_prompt=args.selection_prompt.read_text(encoding="utf-8") if args.selection_prompt else None,
                on_event=lambda event: print(json.dumps(event, ensure_ascii=False), flush=True))
            directory = args.output_dir or ROOT / "output/tasks" / uuid.uuid4().hex
            save_artifacts(directory, result)
            result = {"artifact_directory": str(directory), "metrics": result["metrics"]}
        elif args.command == "serve":
            import uvicorn
            uvicorn.run("paper_research.api:app", host="127.0.0.1", port=args.port)
            return 0
        elif args.command == "evaluate":
            from .evaluation import evaluate
            result = evaluate(args.cases, args.output)
        elif args.command == "tune":
            from .evaluation import tune_retrieval
            result = tune_retrieval(args.output)
        else:
            from .optimization import optimize_selection
            result = optimize_selection(args.budget, args.output)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, RuntimeError) as error:
        print(type(error).__name__ + ": " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
