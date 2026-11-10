"""Attach traceable paragraphs from the existing hybrid retriever."""

from .artifacts import digest


def supplement(brief, retriever, *, doc_ids=None, scope="full"):
    packet = retriever.search(brief["question"], top_k=3, method="hybrid",
                              scope=scope, doc_ids=doc_ids)
    source_metadata = {row["doc_id"]: row for row in packet["sources"]}
    sources = list(brief["sources"])
    seen = {(row["reference"], row["excerpt"]) for row in sources}
    added = []
    for row in packet["results"]:
        metadata = source_metadata[row["doc_id"]]
        reference = metadata["uri"]
        excerpt = row["text"].strip()
        if (reference, excerpt) in seen or len(sources) >= 12:
            continue
        identity = "retrieved-" + digest({"index": packet["index_sha256"],
                                         "chunk": row["chunk_id"]})[:16]
        sources.append({
            "id": identity,
            "title": metadata.get("title", row.get("title", row["doc_id"])),
            "reference": reference,
            "locator": f"仅此检索片段，PDF 第 {row['pdf_page']} 页，字符 {row['start_char']}–{row['end_char']}",
            "scope": "abstract" if row["section"] == "abstract" else "full_text",
            "excerpt": excerpt,
        })
        seen.add((reference, excerpt))
        added.append(identity)
    return {**brief, "sources": sources}, {
        "method": packet["method"], "scope": scope, "doc_ids": packet["doc_ids"],
        "index_sha256": packet["index_sha256"], "added_sources": added,
    }
