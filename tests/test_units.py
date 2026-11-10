import pytest
from paper_research.grounding import canonicalize, evidence_units
from paper_research.model import ModelClient


def test_unit_reference_is_filled_from_original(retriever):
    search=retriever.search("dataset",scope="abstract",doc_ids=["qasper"])
    packet={"chunks":search["results"],"sources":search["sources"],"scope":"abstract"}
    packet["evidence_units"]=evidence_units(packet)
    raw={"answers":[{"question_id":0,"status":"supported","answer":"alpha","citations":"U1"}]}
    report=canonicalize(raw,packet,["original question"])
    assert report["answers"][0]["question"]=="original question"
    assert report["evidence"][0]["text"]=="alpha dataset evidence"
    assert "question" not in raw["answers"][0]


def test_unknown_unit_is_rejected(retriever):
    search=retriever.search("dataset")
    packet={"chunks":search["results"],"sources":search["sources"],"scope":"full","evidence_units":[]}
    with pytest.raises(ValueError):
        canonicalize({"answers":[{"question_id":0,"status":"supported","answer":"x","citations":"U999"}]},packet,["q"])


def test_invalid_messages_fail_before_request():
    client=ModelClient({"base_url":"https://example.invalid","model":"test","api_key":"synthetic"})
    with pytest.raises(ValueError):
        client.text("not a message list")
    assert client.calls==[]


def test_comparison_requires_each_selected_source(retriever):
    search=retriever.search("dataset")
    packet={"chunks":search["results"],"sources":search["sources"],"scope":"full",
            "required_sources":["qasper","other"]}
    packet["evidence_units"]=evidence_units(packet)
    with pytest.raises(ValueError):
        canonicalize({"answers":[{"question_id":0,"status":"supported","answer":"comparison","citations":"U1"}]},packet,["比较这两篇论文"])


def test_network_retry_is_limited(monkeypatch):
    import httpx
    class Broken:
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def post(self,*args,**kwargs): raise httpx.RemoteProtocolError("synthetic disconnect")
    monkeypatch.setattr(httpx,"Client",lambda **kwargs:Broken())
    client=ModelClient({"base_url":"https://example.invalid","model":"test","api_key":"synthetic"},max_calls=2)
    with pytest.raises(RuntimeError):
        client.text([{"role":"user","content":"test"}])
    assert len(client.calls)==2
    assert all(call["status"]=="failed" for call in client.calls)
