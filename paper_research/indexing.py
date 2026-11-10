import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from .config import ROOT, INDEX, MODEL_ID, MODEL_REVISION, read_json, write_json
from .embedding import get_embedder
from .legacy import tool


def abstract_range(text):
    """只接受有明确 Abstract 与 Introduction 边界的摘要。"""
    start = re.search(r"(?im)^\s*Abstract\s*$", text)
    if not start:
        return None
    for line in re.finditer(r"(?m)^.*$", text[start.end():]):
        compact = re.sub(r"\s+", "", line.group()).lower()
        if compact in ("1introduction", "1.introduction", "introduction") or line.group().startswith(("∗", "*Equal contribution", "†Work")):
            return start.start(), start.end() + line.start()
    return None


def document_chunks(entry):
    pdf_path = ROOT / entry["path"]
    extracted = tool("read_pdf").extract_pdf(pdf_path, entry["url"])
    if not extracted["text_page_count"]:
        raise ValueError("未提取到文字，需要 OCR 后才能入库")
    write_json(ROOT / "data/processed" / f"{entry['doc_id']}.pages.json", extracted)
    sha = extracted["source"]["sha256"]
    source = {**entry, "sha256": sha, "page_count": extracted["page_count"],
              "source_id": entry["doc_id"], "uri": entry["url"]}
    chunks = []
    boundary = abstract_range("\n".join(page["text"] for page in extracted["pages"][:2]))
    page_offset = 0
    for page in extracted["pages"]:
        text = page["text"]
        segments = [(0, len(text), "body")]
        if boundary and boundary[0] < page_offset + len(text) and boundary[1] > page_offset:
            a, b = max(0, boundary[0] - page_offset), min(len(text), boundary[1] - page_offset)
            segments = [(0, a, "preamble"), (a, b, "abstract"), (b, len(text), "body")]
        for start, end, section in segments:
            for item in tool("chunk_text").split_page(text[start:end], page["pdf_page"], sha, 1000, 200):
                item["start_char"] += start
                item["end_char"] += start
                item["chunk_id"] = f"{sha}-p{page['pdf_page']}-s{item['start_char']}-e{item['end_char']}"
                chunks.append({**item, "doc_id": entry["doc_id"], "source_id": entry["doc_id"],
                    "title": entry["title"], "section": section})
        page_offset += len(text) + 1
    if len({item["chunk_id"] for item in chunks}) != len(chunks):
        raise ValueError("存在重复片段编号")
    return source, chunks


def fit_chunks(chunks):
    """只细分超长窗口；每个子窗口仍能映射回原页原文。"""
    tokenizer = get_embedder().model.tokenizer
    fitted = []
    pending = list(reversed(chunks))
    while pending:
        row = pending.pop()
        length = len(tokenizer("passage: " + row["text"], truncation=False)["input_ids"])
        if length <= 512:
            fitted.append(row)
            continue
        raw = row["raw_text"]
        if len(raw) < 8:
            raise ValueError("极短片段仍超出 token 限制，请检查文字提取")
        middle = len(raw) // 2
        overlap = min(100, len(raw) // 8)
        children = []
        for a, b in ((0, middle + overlap), (middle - overlap, len(raw))):
            start = row["start_char"] + a
            end = row["start_char"] + b
            sha = row["chunk_id"].split("-p", 1)[0]
            children.append({**row, "raw_text": raw[a:b],
                "text": tool("chunk_text").clean_text(raw[a:b]),
                "start_char": start, "end_char": end,
                "chunk_id": f"{sha}-p{row['pdf_page']}-s{start}-e{end}"})
        pending.extend(reversed(children))
    return fitted


def build_index(manifest=None, output=INDEX):
    manifest = manifest or ROOT / "data/corpus_manifest.json"
    entries = read_json(manifest)["documents"]
    if len({entry["doc_id"] for entry in entries}) != len(entries):
        raise ValueError("文档编号重复")
    old = read_json(output) if Path(output).exists() else {}
    old_rows = {}
    if old.get("embedding_model", {}).get("revision") == MODEL_REVISION:
        old_rows = {item["chunk_id"]: item for item in old["chunks"]}
    sources, chunks = [], []
    for entry in entries:
        source, rows = document_chunks(entry)
        sources.append(source)
        chunks.extend(rows)
    chunks = fit_chunks(chunks)
    if len({row["chunk_id"] for row in chunks}) != len(chunks):
        raise ValueError("同一 PDF 被重复收录，请复用已有文档编号")
    missing = [row for row in chunks if row["chunk_id"] not in old_rows
               or old_rows[row["chunk_id"]]["text"] != row["text"]]
    if missing:
        vectors = get_embedder().encode([row["text"] for row in missing], "passage: ")
        new = {row["chunk_id"]: vector.tolist() for row, vector in zip(missing, vectors)}
    else:
        new = {}
    for row in chunks:
        row["embedding"] = new.get(row["chunk_id"], old_rows.get(row["chunk_id"], {}).get("embedding"))
    fingerprint = hashlib.sha256((MODEL_REVISION + "".join(row["chunk_id"] for row in chunks)).encode()).hexdigest()
    result = {"format_version": 2, "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "fingerprint": fingerprint, "sources": sources, "chunk_count": len(chunks),
        "chunking": {"target_chars": 1000, "overlap_chars": 200,
                     "max_tokens": 512, "overflow": "recursive overlapping bisection"},
        "embedding_model": {"model_id": MODEL_ID, "revision": MODEL_REVISION,
            "dimension": 384, "normalize_embeddings": True}, "chunks": chunks}
    write_json(output, result)
    return {"index": str(output), "documents": len(sources), "chunks": len(chunks),
            "embedded_now": len(missing), "fingerprint": fingerprint}
