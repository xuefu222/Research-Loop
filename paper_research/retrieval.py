import hashlib
import re
import math
from pathlib import Path
import numpy as np
from rank_bm25 import BM25Okapi
from .config import INDEX, MODEL_ID, MODEL_REVISION, read_json, retrieval_config
from .embedding import get_embedder

ALIASES = {"数据集": "dataset", "问题": "questions", "论文": "papers", "证据": "evidence",
    "训练": "training", "参数": "parameters", "注意力": "attention", "检索": "retrieval",
    "生成": "generation", "反思": "reflection", "模型": "model", "基线": "baseline",
    "引用": "citation", "编码器": "encoder", "解码器": "decoder", "指标": "evaluation"}
STOP = set("the a an of in to for and is are what how does do on with by this that which".split())


def tokenize(text):
    return [token for token in re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]", text.lower()) if token not in STOP]


def expand_query(text):
    return text + " " + " ".join(value for key, value in ALIASES.items() if key in text)


def fuse_rankings(dense, sparse, weight=0.5, k=60):
    if not 0 <= weight <= 1 or k <= 0:
        raise ValueError("融合权重或 RRF 常数无效")
    scores = {}
    for ranking, branch_weight in ((dense, weight), (sparse, 1 - weight)):
        if branch_weight == 0:
            continue
        for rank, identity in enumerate(dict.fromkeys(ranking), 1):
            scores[identity] = scores.get(identity, 0) + branch_weight / (k + rank)
    return sorted(scores, key=lambda identity: (-scores[identity], identity)), scores


def overlapping(a, b, threshold):
    if a["doc_id"] != b["doc_id"] or a["pdf_page"] != b["pdf_page"]:
        return False
    intersection = max(0, min(a["end_char"], b["end_char"]) - max(a["start_char"], b["start_char"]))
    length = min(a["end_char"] - a["start_char"], b["end_char"] - b["start_char"])
    return intersection / max(length, 1) >= threshold


class Retriever:
    def __init__(self, index=INDEX, embedder=None, config=None):
        self.path = Path(index)
        self.data = read_json(index)
        self.config = config or retrieval_config()
        self.embedder = embedder
        meta = self.data["embedding_model"]
        if meta["model_id"] != MODEL_ID or meta["revision"] != MODEL_REVISION:
            raise ValueError("查询模型与索引模型不一致，请重新建库")
        self.rows = self.data["chunks"]
        if not self.rows:
            raise ValueError("索引为空")
        if "sources" not in self.data:  # 兼容最初单篇论文向量文件
            self.data["sources"] = [{**self.data["source"], "source_id": "qasper",
                "doc_id": "qasper", "uri": self.data["source"].get("url") or self.data["source"]["file_path"]}]
            self.rows = [{**row, "doc_id": "qasper", "source_id": "qasper", "section": "body"} for row in self.rows]
        self.sources = {item["doc_id"]: item for item in self.data["sources"]}
        if len({row["chunk_id"] for row in self.rows}) != len(self.rows):
            raise ValueError("索引含重复片段编号")
        self.vectors = np.asarray([row["embedding"] for row in self.rows], dtype=np.float32)
        if self.vectors.shape != (len(self.rows), 384) or not np.isfinite(self.vectors).all():
            raise ValueError("索引向量形状或数值无效")
        if not np.allclose(np.linalg.norm(self.vectors, axis=1), 1, atol=1e-4):
            raise ValueError("索引向量未归一化")
        self.fingerprint = hashlib.sha256(self.path.read_bytes()).hexdigest()

    def search(self, query, top_k=None, method="hybrid", scope="full", doc_ids=None, lexical_query=None):
        if not query.strip() or method not in ("bm25", "dense", "hybrid"):
            raise ValueError("问题为空或检索方法无效")
        if scope not in ("full", "abstract"):
            raise ValueError("材料范围必须为 full 或 abstract")
        top_k = top_k if top_k is not None else self.config["top_k"]
        if not 1 <= top_k <= 50:
            raise ValueError("top_k 必须位于 1 至 50")
        selected_docs = set(doc_ids or self.sources)
        if selected_docs - self.sources.keys():
            raise ValueError("指定文档不存在")
        eligible = [i for i, row in enumerate(self.rows) if row["doc_id"] in selected_docs
                    and (scope == "full" or row.get("section") == "abstract")]
        if not eligible:
            return {"query": query, "scope": scope, "results": [], "sources": [],
                "searched_chunk_count": 0, "returned_chunk_count": 0, "doc_ids": sorted(selected_docs),
                "method": method, "index_sha256": self.fingerprint}
        n = max(top_k, self.config["candidate_k"])
        dense, sparse, dense_scores, sparse_scores = [], [], {}, {}
        lex = lexical_query or expand_query(query)
        if method != "dense":
            token_lists = [tokenize(self.rows[i]["text"]) or ["__empty__"] for i in eligible]
            bm25 = BM25Okapi(token_lists)
            # 使用 Lucene 的正 IDF，避免极小语料里所有命中项都得到负分。
            frequencies = {}
            for tokens in token_lists:
                for token in set(tokens):
                    frequencies[token] = frequencies.get(token, 0) + 1
            bm25.idf = {token: math.log1p((len(token_lists) - count + 0.5) / (count + 0.5))
                        for token, count in frequencies.items()}
            values = bm25.get_scores(tokenize(lex))
            sparse = [eligible[int(j)] for j in np.argsort(-values, kind="stable") if values[int(j)] > 0][:n]
            sparse_scores = {i: float(values[eligible.index(i)]) for i in sparse}
        if method != "bm25":
            embedder = self.embedder or get_embedder()
            values = self.vectors[eligible] @ embedder.query(query)
            dense = [eligible[int(j)] for j in np.argsort(-values, kind="stable")[:n]]
            dense_scores = {i: float(values[eligible.index(i)]) for i in dense}
        if method == "hybrid":
            order, scores = fuse_rankings(dense, sparse, self.config["dense_weight"], self.config["rrf_k"])
        else:
            order, scores = (dense, dense_scores) if method == "dense" else (sparse, sparse_scores)
        results = []
        for i in order:
            row = self.rows[i]
            if any(overlapping(row, existing, self.config["overlap_threshold"]) for existing in results):
                continue
            results.append({**{key: value for key, value in row.items() if key != "embedding"},
                "rank": len(results) + 1, "score": scores[i],
                "dense_score": dense_scores.get(i), "bm25_score": sparse_scores.get(i),
                "dense_rank": dense.index(i) + 1 if i in dense else None,
                "bm25_rank": sparse.index(i) + 1 if i in sparse else None})
            if len(results) == top_k:
                break
        used = {row["doc_id"] for row in results}
        return {"query": query, "lexical_query": lex, "method": method, "scope": scope,
            "doc_ids": sorted(selected_docs), "searched_chunk_count": len(eligible),
            "score_type": "weighted_rrf" if method == "hybrid" else method,
            "index_sha256": self.fingerprint, "returned_chunk_count": len(results),
            "sources": [self.sources[doc] for doc in sorted(used)], "results": results}
