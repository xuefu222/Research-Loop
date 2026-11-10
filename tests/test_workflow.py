from paper_research.workflow import research


class Client:
    def __init__(self, bad=False, reject=False):
        self.calls=[]; self.bad=bad; self.reject=reject
    def json(self, system, data, role):
        self.calls.append({"role":role})
        if role=="planner":
            return {"queries":[{"semantic_query":q,"lexical_query":"dataset"} for q in data["questions"]]}
        if role=="selector":
            return {"chunk_ids":[row["chunk_id"] for row in data["chunks"]]}
        if role=="main":
            row=data["evidence_units"][0]
            return {"answers":[{"question":q,"status":"supported","answer":"alpha",
                "citations":[{"chunk_id":row["chunk_id"],"quote":"fabricated"}] if self.bad else row["unit_id"]}
                for q in data["questions"]]}
        return {"approved":not self.reject,"issues":["not supported"] if self.reject else []}


def test_workflow_runs_and_records_roles(retriever):
    client=Client()
    result=research(["alpha"], retriever=retriever, client=client, scope="abstract",doc_ids=["qasper"])
    assert result["report"]["answers"][0]["status"]=="supported"
    assert [call["role"] for call in client.calls]==["planner","selector","main","reviewer"]


def test_bad_quote_retries_then_fails_closed(retriever):
    client=Client(bad=True)
    result=research(["alpha"],retriever=retriever,client=client)
    assert result["metrics"]["attempts"]==2
    assert result["report"]["answers"][0]["status"]=="insufficient"
    assert result["report"]["evidence"]==[]


def test_semantic_rejection_is_bounded(retriever):
    client=Client(reject=True)
    result=research(["alpha"],retriever=retriever,client=client)
    assert result["metrics"]["attempts"]==2
    assert len(client.calls)<=8
    assert result["report"]["answers"][0]["status"]=="insufficient"


def test_packet_does_not_call_generation_model(retriever):
    result=research(["alpha"],retriever=retriever,mode="packet")
    assert result["report"] is None
    assert result["metrics"]["model_calls"]==[]


def test_provider_error_is_not_disguised_as_insufficient(retriever):
    class Broken(Client):
        def json(self,*args,**kwargs):
            raise RuntimeError("provider unavailable")
    import pytest
    with pytest.raises(RuntimeError):
        research(["alpha"],retriever=retriever,client=Broken())
