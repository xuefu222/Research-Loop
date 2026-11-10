import pytest
from paper_research.grounding import canonicalize


def packet(retriever):
    result = retriever.search("dataset")
    return {"chunks":result["results"], "sources":result["sources"],"scope":"abstract"}


def draft(quote="alpha dataset", identity="chunk-0"):
    return {"answers":[{"question":"what", "status":"supported","answer":"answer",
        "citations":[{"chunk_id":identity,"quote":quote}]}]}


def test_exact_quote_location(retriever):
    report = canonicalize(draft(), packet(retriever), ["what"])
    evidence = report["evidence"][0]
    assert evidence["start_char"] == 0
    assert evidence["end_char"] == len("alpha dataset")
    assert evidence["source_id"] == "qasper"


def test_fabricated_quote_rejected(retriever):
    with pytest.raises(ValueError):
        canonicalize(draft("not in source"), packet(retriever), ["what"])


def test_unknown_chunk_rejected(retriever):
    with pytest.raises(ValueError):
        canonicalize(draft(identity="forged"), packet(retriever), ["what"])


def test_dropped_question_rejected(retriever):
    with pytest.raises(ValueError):
        canonicalize(draft(), packet(retriever), ["what","another"])


def test_conflict_needs_two_evidence_items(retriever):
    value=draft(); value["answers"][0]["status"]="conflicting"
    with pytest.raises(ValueError):
        canonicalize(value,packet(retriever),["what"])
