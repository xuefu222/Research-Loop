import numpy as np
import pytest
from paper_research.config import MODEL_ID, MODEL_REVISION, write_json
from paper_research.retrieval import Retriever


class FakeEmbedder:
    def query(self, text):
        return np.eye(1, 384, 0, dtype=np.float32)[0]


@pytest.fixture
def retriever(tmp_path):
    rows = []
    for i, (doc, section, text) in enumerate((
        ("qasper", "abstract", "alpha dataset evidence"),
        ("qasper", "body", "beta accelerator GPU"),
        ("other", "abstract", "gamma unrelated"))):
        rows.append({"chunk_id": f"chunk-{i}", "doc_id": doc, "source_id": doc,
            "section": section, "pdf_page": i + 1, "start_char": 0, "end_char": len(text),
            "raw_text": text, "text": text, "embedding": np.eye(1,384,i)[0].tolist()})
    index = tmp_path / "index.json"
    write_json(index, {"embedding_model": {"model_id": MODEL_ID, "revision": MODEL_REVISION},
        "sources": [{"doc_id": doc, "source_id": doc, "uri": "https://example.invalid/" + doc}
            for doc in ("qasper", "other")], "chunks": rows})
    return Retriever(index, embedder=FakeEmbedder())
