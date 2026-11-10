"""供 Skill 中的独立脚本复用的命令行适配器。"""
import argparse
from pathlib import Path
from paper_research.config import INDEX, CACHE, write_json
from paper_research.retrieval import Retriever


def main(method):
    parser = argparse.ArgumentParser(description="检索论文片段")
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--query", required=True)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--cache-dir", type=Path, default=CACHE)
    parser.add_argument("--scope", choices=["full", "abstract"], default="full")
    parser.add_argument("--doc-id", action="append", dest="doc_ids")
    parser.add_argument("--lexical-query")
    args = parser.parse_args()
    if args.input.resolve() == args.output.resolve():
        parser.error("输入和输出文件不能相同")
    if args.output.suffix.lower() != ".json":
        parser.error("输出文件必须使用 .json 扩展名")
    from paper_research.embedding import get_embedder
    embedder = get_embedder(str(args.cache_dir)) if method != "bm25" else None
    result = Retriever(args.input, embedder=embedder).search(args.query, args.top_k,
        method, args.scope, args.doc_ids, args.lexical_query)
    write_json(args.output, result)
    for row in result["results"]:
        print(f"{row['rank']} | {row['doc_id']} PDF 第 {row['pdf_page']} 页 | {row['score']:.5f}")
        print(row["text"][:300])
    print("保存到", args.output)
    return 0
