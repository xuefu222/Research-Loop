"""有限轮次 LangGraph：规划→混合检索→证据选择→回答→核验。"""
import time
import hashlib
from typing import TypedDict
from langgraph.graph import StateGraph, START, END
from .config import ROOT, retrieval_config
from .model import ModelClient
from .grounding import canonicalize, insufficient_report, evidence_units, is_comparison
from .retrieval import Retriever, overlapping


class State(TypedDict, total=False):
    questions: list
    scope: str
    doc_ids: list
    mode: str
    queries: list
    attempt: int
    packet: dict
    report: dict
    approved: bool
    feedback: list


def prompt(name):
    return (ROOT / "prompts" / f"{name}.txt").read_text(encoding="utf-8")


def model_packet(packet):
    return {"scope": packet["scope"], "chunks": [{"chunk_id": row.get("candidate_id", row["chunk_id"]),
        "doc_id": row["doc_id"], "pdf_page": row["pdf_page"], "section": row.get("section"),
        "raw_text": row["raw_text"]} for row in packet["chunks"]]}


def research(questions, scope="full", doc_ids=None, mode="agent", retriever=None,
             client=None, on_event=None, selection_prompt=None):
    if not questions or len(questions) > 5 or any(not isinstance(q, str) or not q.strip() or len(q) > 2000 for q in questions):
        raise ValueError("需要 1 至 5 个非空问题，每个最多 2000 字符")
    questions = [q.strip() for q in questions]
    retriever = retriever or Retriever()
    if mode not in ("agent", "packet"):
        raise ValueError("mode 必须是 agent 或 packet")
    client = (client or ModelClient(max_calls=8)) if mode == "agent" else None
    config = retrieval_config()
    trace = []
    drafts = []
    start = time.monotonic()

    def emit(node, **details):
        event = {"node": node, "elapsed_seconds": round(time.monotonic() - start, 3), **details}
        trace.append(event)
        if on_event:
            on_event(event)

    def plan(state):
        queries = [{"semantic_query": q, "lexical_query": None} for q in questions]
        if client:
            try:
                result = client.json(prompt("plan"), {"questions": questions}, "planner")
                proposed = result["queries"]
                if len(proposed) == len(questions) and all(isinstance(q.get("semantic_query"), str) and q["semantic_query"].strip() and isinstance(q.get("lexical_query"), str) for q in proposed):
                    queries = proposed
            except (ValueError, KeyError, TypeError):
                emit("plan_fallback", reason="规划 JSON 无效，使用原问题")
        emit("plan", questions=len(questions))
        return {"queries": queries, "attempt": 0, "feedback": []}

    def retrieve(state):
        attempt = state["attempt"] + 1
        chunks, sources = [], {}
        for question, query in zip(questions, state["queries"]):
            result = retriever.search(query["semantic_query"] if attempt == 1 else question,
                top_k=min(50, config["top_k"] + (attempt - 1) * 4), scope=scope,
                doc_ids=doc_ids, lexical_query=query.get("lexical_query"))
            if doc_ids and len(doc_ids) > 1 and is_comparison(question):
                for doc in doc_ids:
                    extra = retriever.search(query["semantic_query"], top_k=2, scope=scope,
                        doc_ids=[doc], lexical_query=query.get("lexical_query"))
                    result["results"].extend(extra["results"])
                    result["sources"].extend(extra["sources"])
            sources.update({source["source_id"]: source for source in result["sources"]})
            for row in result["results"]:
                if not any(row["chunk_id"] == old["chunk_id"] or overlapping(row, old, config["overlap_threshold"]) for old in chunks):
                    chunks.append(row)
        retained, size = [], 0
        for row in chunks:
            if size + len(row["raw_text"]) <= config["max_context_chars"]:
                retained.append({**row, "candidate_id": f"C{len(retained) + 1}"})
                size += len(row["raw_text"])
        packet = {"scope": scope, "questions": questions, "doc_ids": doc_ids or list(retriever.sources),
            "required_sources": doc_ids if doc_ids and any(is_comparison(q) for q in questions) else [],
            "chunks": retained, "sources": list(sources.values()), "index_sha256": retriever.fingerprint}
        emit("retrieve", attempt=attempt, candidates=len(retained), context_chars=size)
        return {"packet": packet, "attempt": attempt}

    def select(state):
        packet = dict(state["packet"])
        original_chunks = list(packet["chunks"])
        if client and packet["chunks"]:
            try:
                selection = client.json(selection_prompt or prompt("select"),
                    {"questions": questions, **model_packet(packet)}, "selector")
                ids = selection["chunk_ids"]
                if not isinstance(ids, list) or any(not isinstance(i, str) for i in ids):
                    raise ValueError("选择结果不是编号列表")
                allowed = {row.get("candidate_id", row["chunk_id"]): row["chunk_id"] for row in packet["chunks"]}
                allowed.update({row["chunk_id"]: row["chunk_id"] for row in packet["chunks"]})
                if set(ids) - allowed.keys():
                    raise ValueError("选择结果含未知编号")
                ids = {allowed[identity] for identity in ids[:8]}
                packet["chunks"] = [row for row in packet["chunks"] if row["chunk_id"] in ids]
            except (ValueError, KeyError, TypeError):
                emit("selection_fallback", reason="选择格式无效，保留原候选")
        if packet.get("required_sources"):
            required_rows = []
            for source in packet["required_sources"]:
                row = next((row for row in packet["chunks"] if row["source_id"] == source), None)
                row = row or next((row for row in original_chunks if row["source_id"] == source), None)
                if row:
                    required_rows.append(row)
            identities = {row["chunk_id"] for row in required_rows}
            packet["chunks"] = (required_rows + [row for row in packet["chunks"] if row["chunk_id"] not in identities])[:8]
        emit("select", selected=len(packet["chunks"]))
        packet["evidence_units"] = evidence_units(packet)
        return {"packet": packet}

    def draft(state):
        if mode == "packet":
            return {"report": None, "approved": True}
        if not state["packet"]["chunks"]:
            report = insufficient_report(state["packet"], questions, "在限定范围内没有选择到可用证据。")
            return {"report": report, "approved": True}
        try:
            value = client.json(prompt("answer"), {"questions": questions,
                "material_scope": scope, "required_sources": state["packet"].get("required_sources", []),
                "evidence_units": [{"unit_id": unit["unit_id"], "doc_id": unit["doc_id"], "text": unit["text"]} for unit in state["packet"]["evidence_units"]],
                "previous_feedback": state["feedback"]}, "main")
            drafts.append(value)
            report = canonicalize(value, state["packet"], questions)
            emit("draft", structural_validation="passed")
            return {"report": report, "approved": False}
        except (ValueError, KeyError, TypeError) as error:
            emit("draft", structural_validation="failed")
            return {"report": None, "approved": False, "feedback": [str(error)]}

    def verify(state):
        if mode == "packet" or state.get("approved"):
            emit("verify", status="not_required")
            return {}
        if not state.get("report"):
            emit("verify", status="structure_failed")
            return {"approved": False}
        try:
            review = client.json(prompt("review"), {"questions": questions,
                "packet": model_packet(state["packet"]), "report": state["report"]}, "reviewer")
            approved = review.get("approved") is True and isinstance(review.get("issues"), list) and not review["issues"]
            feedback = review.get("issues", ["审核格式无效"])
            if not isinstance(feedback, list) or any(not isinstance(item, str) for item in feedback):
                approved, feedback = False, ["审核格式无效"]
        except (ValueError, KeyError, TypeError):
            approved, feedback = False, ["审核 JSON 无效"]
        emit("verify", approved=approved)
        return {"approved": approved, "feedback": feedback}

    def route(state):
        if state.get("approved") or state["attempt"] >= config["max_attempts"]:
            return "finish"
        emit("retry", reason=state["feedback"])
        return "retrieve"

    def finish(state):
        if mode == "agent" and not state.get("approved"):
            return {"report": insufficient_report(state["packet"], questions,
                "证据或报告未通过核验，达到轮次上限后停止：" + "; ".join(state.get("feedback", [])))}
        return {}

    graph = StateGraph(State)
    for name, node in (("plan", plan), ("retrieve", retrieve), ("select", select),
                       ("draft", draft), ("verify", verify), ("finish", finish)):
        graph.add_node(name, node)
    graph.add_edge(START, "plan")
    graph.add_edge("plan", "retrieve")
    graph.add_edge("retrieve", "select")
    graph.add_edge("select", "draft")
    graph.add_edge("draft", "verify")
    graph.add_conditional_edges("verify", route, {"finish": "finish", "retrieve": "retrieve"})
    graph.add_edge("finish", END)
    result = graph.compile().invoke({"questions": questions, "scope": scope,
        "doc_ids": doc_ids or [], "mode": mode}, {"recursion_limit": 20})
    emit("finish", status="completed")
    return {"packet": result["packet"], "report": result.get("report"), "trace": trace, "drafts": drafts,
        "metrics": {"mode": mode, "attempts": result["attempt"], "approved": result.get("approved", False),
            "prompt_sha256": {name: hashlib.sha256((selection_prompt if name == "select" and selection_prompt else prompt(name)).encode()).hexdigest()
                              for name in ("plan", "select", "answer", "review")},
            "elapsed_seconds": round(time.monotonic() - start, 3),
            "model_calls": client.calls if client else [],
            "verification": "model_and_structure" if result.get("approved") and mode == "agent" else "packet_or_failed_closed"}}
