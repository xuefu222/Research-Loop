"""从检索候选重建证据，模型不能自行决定来源与页码。"""
from .legacy import tool
import re


def is_comparison(question):
    return any(word in question.lower() for word in ("比较", "差异", "差别", "区别", "compare"))


def evidence_units(packet):
    """程序从 raw_text 建立可引用短句；模型只选择编号，不重写原文。"""
    units, seen = [], set()
    for row in packet["chunks"]:
        for match in re.finditer(r".+?(?:[.!?](?=\s)|$)", row["raw_text"], re.S):
            raw = match.group()
            start = match.start() + len(raw) - len(raw.lstrip())
            stop = match.end() - (len(raw) - len(raw.rstrip()))
            while start < stop:
                end = min(start + 450, stop)
                key = (row["doc_id"], row["pdf_page"], row["start_char"] + start, row["start_char"] + end)
                if key not in seen:
                    seen.add(key)
                    units.append({"unit_id": f"U{len(units) + 1}", "chunk_id": row["chunk_id"],
                        "doc_id": row["doc_id"], "pdf_page": row["pdf_page"],
                        "text": row["raw_text"][start:end]})
                if end == stop:
                    break
                start = end - 50
    return units


def material_scope(packet):
    return (f"已索引论文的{('摘要' if packet['scope'] == 'abstract' else '全文提取文本')}；"
            f"本次实际提供 {len(packet['chunks'])} 个候选片段，回答仅依据这些片段。")


def canonicalize(draft, packet, questions):
    if not isinstance(draft, dict):
        raise ValueError("报告必须是 JSON 对象")
    answers = draft.get("answers", [])
    if not isinstance(answers, list) or len(answers) != len(questions) or any(not isinstance(a, dict) for a in answers):
        raise ValueError("回答必须按原顺序逐一对应全部原始问题")
    answers = [dict(answer) for answer in answers]
    for index, answer in enumerate(answers):
        if type(answer.get("question_id")) is int and answer["question_id"] == index:
            answer["question"] = questions[index]
        elif answer.get("question") != questions[index]:
            raise ValueError("问题编号不完整或不符合原顺序")
    by_id = {row["chunk_id"]: row for row in packet["chunks"]}
    by_id.update({row["candidate_id"]: row for row in packet["chunks"] if row.get("candidate_id")})
    by_unit = {unit["unit_id"]: unit for unit in packet.get("evidence_units", [])}
    sources = {source["source_id"]: source for source in packet["sources"]}
    evidence, built_answers, known = [], [], {}
    for answer in answers:
        status = answer.get("status")
        if status not in ("supported", "inferred", "insufficient", "conflicting"):
            raise ValueError("回答状态无效")
        text = answer.get("answer")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("回答内容不能为空")
        references = []
        citations = answer.get("citations", [])
        if isinstance(citations, str):
            ids = [identity.strip() for identity in citations.split(",") if identity.strip()]
            if any(identity not in by_unit for identity in ids):
                raise ValueError("引用了不存在的证据单元")
            citations = [{"chunk_id": by_unit[identity]["chunk_id"], "quote": by_unit[identity]["text"]} for identity in ids]
        if citations is None and status == "insufficient":
            citations = []
        if not isinstance(citations, list):
            raise ValueError("citations 必须是列表")
        for citation in citations:
            if not isinstance(citation, dict):
                raise ValueError("引用条目必须是对象，或使用逗号分隔的 U 编号字符串")
            row = by_id.get(citation.get("chunk_id"))
            quote = citation.get("quote")
            if row is None:
                raise ValueError("引用了候选集合以外的片段")
            if not isinstance(quote, str) or not quote.strip() or len(quote) > 500:
                raise ValueError("原文摘录为空或超过 500 字符")
            offset = row["raw_text"].find(quote)
            if offset < 0:
                raise ValueError("摘录不是 raw_text 的连续原文，请保留空白与换行")
            key = (row["chunk_id"], quote)
            if key not in known:
                identity = "E" + str(len(evidence) + 1)
                known[key] = identity
                start = row["start_char"] + offset
                evidence.append({"evidence_id": identity, "source_id": row["source_id"],
                    "kind": "quote", "text": quote, "chunk_id": row["chunk_id"],
                    "pdf_page": row["pdf_page"], "start_char": start, "end_char": start + len(quote),
                    "location": f"PDF 第 {row['pdf_page']} 页，提取文字字符 [{start}, {start + len(quote)})"})
            references.append(known[key])
        if status != "insufficient" and not references:
            raise ValueError("有结论的回答必须提供可核对的原文摘录")
        if status == "conflicting" and len(set(references)) < 2:
            raise ValueError("冲突状态至少需要两条证据")
        if status != "insufficient" and is_comparison(answer["question"]):
            cited_sources = {item["source_id"] for item in evidence if item["evidence_id"] in references}
            if not set(packet.get("required_sources", [])) <= cited_sources:
                raise ValueError("跨论文比较必须引用每篇指定论文的直接证据；缺失时请返回不足")
        built_answers.append({"question": answer["question"], "status": status,
            "answer": text, "evidence_ids": list(dict.fromkeys(references))})
    report = {"material_scope": material_scope(packet), "answers": built_answers,
        "evidence": evidence, "sources": [{"source_id": key, "uri": source["uri"]}
            for key, source in sources.items()],
        "limitations": ["原文来自 PDF 文字提取，表格与公式需要回到 PDF 核对。",
            "自动审核使用与主流程相同的模型服务，不能视为独立人工核验。"]}
    errors = tool("validate_report").validate_report(report)
    if errors:
        raise ValueError("; ".join(errors))
    return report


def insufficient_report(packet, questions, reason):
    return {"material_scope": material_scope(packet),
        "answers": [{"question": question, "status": "insufficient",
            "answer": "当前提供的证据不足以可靠回答该问题。", "evidence_ids": []} for question in questions],
        "evidence": [], "sources": [{"source_id": source["source_id"], "uri": source["uri"]}
            for source in packet["sources"]], "limitations": [reason,
            "未确认不等于论文中绝对不存在相关信息。"]}
