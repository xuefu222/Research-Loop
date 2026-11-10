import pytest
from paper_research.retrieval import fuse_rankings, overlapping


def test_rrf_rewards_both_lists():
    order, scores = fuse_rankings([1,2], [2,3])
    assert order[0] == 2
    assert scores[2] > scores[1]


def test_rrf_zero_weight_excludes_branch():
    order, scores = fuse_rankings([1], [2], weight=0)
    assert order == [2]


def test_scope_filter_before_retrieval(retriever):
    result = retriever.search("GPU", scope="abstract", doc_ids=["qasper"])
    assert result["searched_chunk_count"] == 1
    assert all(row["section"] == "abstract" for row in result["results"])
    assert all("GPU" not in row["raw_text"] for row in result["results"])


def test_single_eligible_document_bm25_can_match(retriever):
    result = retriever.search("dataset", method="bm25", scope="abstract", doc_ids=["qasper"])
    assert result["results"][0]["chunk_id"] == "chunk-0"


def test_unknown_document_rejected(retriever):
    with pytest.raises(ValueError):
        retriever.search("dataset", doc_ids=["missing"])


def test_zero_keyword_match_is_empty(retriever):
    assert retriever.search("zzzxxyy", method="bm25")["results"] == []


def test_missing_abstract_does_not_fall_back_to_body(retriever):
    for row in retriever.rows:
        row["section"]="body"
    result=retriever.search("dataset",scope="abstract")
    assert result["returned_chunk_count"]==0
    assert result["searched_chunk_count"]==0


def test_result_omits_vectors_and_keeps_raw(retriever):
    row = retriever.search("dataset")["results"][0]
    assert "embedding" not in row
    assert row["raw_text"] == "alpha dataset evidence"
    assert row["dense_rank"] == 1


def test_overlap_uses_page_and_document():
    a = {"doc_id":"a","pdf_page":1,"start_char":0,"end_char":100}
    assert overlapping(a, {**a,"start_char":20}, 0.65)
    assert not overlapping(a, {**a,"pdf_page":2}, 0.65)
