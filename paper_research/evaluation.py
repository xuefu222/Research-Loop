"""使用原页字符区间作为金标准，避免把相邻重叠片段当成不同正确答案。"""
import copy
import hashlib
import time
from collections import defaultdict
from datetime import datetime, timezone
import numpy as np
from .config import ROOT, read_json, write_json, retrieval_config
from .retrieval import Retriever


def covers(row, span):
    return (row["doc_id"] == span["doc_id"] and row["pdf_page"] == span["pdf_page"]
        and row["start_char"] <= span["start_char"] and row["end_char"] >= span["end_char"])


def metrics(rows, spans):
    hits = [any(covers(row, span) for row in rows) for span in spans]
    first = next((i + 1 for i, row in enumerate(rows) if any(covers(row, span) for span in spans)), None)
    return {"hit": float(any(hits)), "evidence_recall": sum(hits) / len(hits),
            "mrr": 1 / first if first else 0.0}


def validate_cases(cases):
    documents = {}
    for case in cases:
        paper = case["paper_id"]
        if paper in documents and documents[paper] != case["split"]:
            raise ValueError("同一论文跨越多个评测划分")
        documents[paper] = case["split"]
        data = read_json(ROOT / f"data/processed/{paper}.pages.json")
        page_map = {p["pdf_page"]: p["text"] for p in data["pages"]}
        for span in case["evidence_spans"]:
            if span["doc_id"] != paper or not (0 <= span["start_char"] < span["end_char"] <= len(page_map[span["pdf_page"]])):
                raise ValueError("证据标注超出原文范围")
    return documents


def evaluate(cases_path=None, output=None, config=None):
    path = cases_path or ROOT / "evals/cases.json"
    cases = read_json(path)["cases"]
    splits = validate_cases(cases)
    retriever = Retriever(config=config)
    begin = time.perf_counter()
    from .embedding import get_embedder
    get_embedder().query("retrieval warmup")
    warmup = time.perf_counter() - begin
    results = []
    for method in ("bm25", "dense", "hybrid"):
        for case in cases:
            if not case["evidence_spans"]:
                continue  # 无答案问题单独做端到端拒答检查，不能计作检索命中
            if method in ("dense", "hybrid"):
                get_embedder().query.cache_clear()
            start = time.perf_counter()
            value = retriever.search(case["question"], top_k=5, method=method,
                scope=case.get("scope", "full"), lexical_query=case.get("lexical_query"))
            results.append({"case_id": case["id"], "split": case["split"], "method": method,
                **metrics(value["results"], case["evidence_spans"]),
                "elapsed_ms": (time.perf_counter() - start) * 1000,
                "chunk_ids": [row["chunk_id"] for row in value["results"]]})
    summaries = []
    for split in ("all", "train", "validation", "test"):
        for method in ("bm25", "dense", "hybrid"):
            rows = [row for row in results if row["method"] == method and (split == "all" or row["split"] == split)]
            if rows:
                summaries.append({"split": split, "method": method, "n": len(rows),
                    "hit_at_5": float(np.mean([row["hit"] for row in rows])),
                    "evidence_recall_at_5": float(np.mean([row["evidence_recall"] for row in rows])),
                    "mrr_at_5": float(np.mean([row["mrr"] for row in rows])),
                    "latency_p50_ms": float(np.percentile([row["elapsed_ms"] for row in rows], 50)),
                    "latency_p95_ms": float(np.percentile([row["elapsed_ms"] for row in rows], 95))})
    result = {"created_at_utc": datetime.now(timezone.utc).isoformat(), "k": 5,
        "index_sha256": retriever.fingerprint, "cases_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "paper_splits": splits, "warmup_seconds": warmup, "timing_policy": "model warmed; per-query embedding cache cleared for dense and hybrid",
        "unanswerable_cases_excluded": sum(not row["evidence_spans"] for row in cases),
        "summary": summaries, "per_case": results,
        "limitations": ["小规模人工编写的冒烟集，不是 QASPER 官方测试集，不能推断真实业务性能。",
            "英文稀疏检索词由人工预先给出，评测不包含在线规划器翻译错误。",
            "无答案检测与最终回答质量不由这些检索指标衡量。",
            "时延是当前机器顺序运行测量；已预热模型，并清空每个语义查询的缓存，不是并发压测。"]}
    if output:
        write_json(output, result)
    return result


def tune_retrieval(output):
    cases = read_json(ROOT / "evals/cases.json")["cases"]
    validate_cases(cases)
    records = []
    for weight in (0.25, 0.5, 0.75):
        config = copy.deepcopy(retrieval_config())
        config["dense_weight"] = weight
        retriever = Retriever(config=config)
        scores = defaultdict(list)
        for case in cases:
            if case["split"] == "test" or not case["evidence_spans"]:
                continue
            result = retriever.search(case["question"], top_k=5, lexical_query=case.get("lexical_query"),
                scope=case.get("scope", "full"))
            scores[case["split"]].append(metrics(result["results"], case["evidence_spans"])["evidence_recall"])
        records.append({"dense_weight": weight,
            "train_recall": float(np.mean(scores["train"])),
            "validation_recall": float(np.mean(scores["validation"]))})
    best = max(records, key=lambda row: (row["validation_recall"], row["train_recall"], -abs(row["dense_weight"] - 0.5)))
    result = {"candidates": records, "selected": best, "test_used_for_selection": False,
        "promoted_to_default": False, "note": "只记录候选，不自动替换线上配置；最终测试标签未参与选择。"}
    write_json(output, result)
    return result
