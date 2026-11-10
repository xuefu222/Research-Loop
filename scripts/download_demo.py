"""下载固定版本开放论文，保留原始文件与来源、校验和。"""
import hashlib
import json
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = [
    {"doc_id": "qasper", "title": "A Dataset of Information-Seeking Questions and Answers Anchored in Research Papers",
     "path": "data/raw/qasper.pdf", "url": "https://aclanthology.org/2021.naacl-main.365.pdf",
     "landing_url": "https://aclanthology.org/2021.naacl-main.365/", "version": "NAACL 2021 publisher PDF", "split": "train"},
    {"doc_id": "rag", "title": "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks",
     "path": "data/raw/rag.pdf", "url": "https://arxiv.org/pdf/2005.11401v4",
     "landing_url": "https://arxiv.org/abs/2005.11401v4", "version": "arXiv:2005.11401v4", "split": "train"},
    {"doc_id": "attention", "title": "Attention Is All You Need",
     "path": "data/raw/attention.pdf", "url": "https://arxiv.org/pdf/1706.03762v7",
     "landing_url": "https://arxiv.org/abs/1706.03762v7", "version": "arXiv:1706.03762v7", "split": "validation"},
    {"doc_id": "selfrag", "title": "Self-RAG: Learning to Retrieve, Generate, and Critique through Self-Reflection",
     "path": "data/raw/selfrag.pdf", "url": "https://arxiv.org/pdf/2310.11511v1",
     "landing_url": "https://arxiv.org/abs/2310.11511v1", "version": "arXiv:2310.11511v1", "split": "test"},
]


def main():
    for entry in DOCUMENTS:
        path = ROOT / entry["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            request = urllib.request.Request(entry["url"], headers={"User-Agent": "PaperResearchSkill/0.2"})
            with urllib.request.urlopen(request, timeout=90) as response:
                content = response.read(25 * 1024 * 1024)
            if not content.startswith(b"%PDF-"):
                raise ValueError("下载结果不是 PDF：" + entry["doc_id"])
            path.write_bytes(content)
            time.sleep(1)
        content = path.read_bytes()
        license_url = "not independently verified"
        try:
            with urllib.request.urlopen(entry["landing_url"], timeout=30) as response:
                html = response.read().decode("utf-8", errors="replace")
            matches = re.findall(r'href="([^"]*(?:creativecommons.org|arxiv.org/licenses)[^"]*)"', html)
            if matches:
                license_url = matches[0]
        except Exception:
            pass
        metadata = {**entry, "sha256": hashlib.sha256(content).hexdigest(),
            "bytes": len(content), "metadata_checked_at_utc": datetime.now(timezone.utc).isoformat(),
            "license_url": license_url, "license_note": "论文许可独立于本项目代码；未核实的许可不作推定。"}
        source_path = path.with_suffix(".source.json")
        if source_path.exists():
            old = json.loads(source_path.read_text(encoding="utf-8-sig"))
            metadata["previous_provenance"] = old.get("previous_provenance", old)
        source_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        print(entry["doc_id"], len(content), flush=True)
    (ROOT / "data/corpus_manifest.json").write_text(
        json.dumps({"documents": DOCUMENTS}, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
