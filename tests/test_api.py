from pathlib import Path
from fastapi.testclient import TestClient
from paper_research import api
from paper_research.storage import Store


def test_health_does_not_expose_secret(tmp_path, monkeypatch):
    monkeypatch.setattr(api,"STORE",Store(tmp_path/"tasks.db"))
    with TestClient(api.app) as client:
        value=client.get("/api/health").json()
        assert "api_key" not in value and "base_url" not in value


def test_sse_resumes_after_last_event(tmp_path,monkeypatch):
    store=Store(tmp_path/"tasks.db"); monkeypatch.setattr(api,"STORE",store)
    with TestClient(api.app) as client:
        identity=store.create("research",{})
        store.event(identity,{"node":"first"}); store.event(identity,{"node":"second"})
        store.update(identity,"completed",{})
        first=store.events(identity)[0]["sequence"]
        response=client.get(f"/api/tasks/{identity}/events",headers={"Last-Event-ID":str(first)})
        assert response.status_code==200
        assert '"node": "second"' in response.text
        assert '"node": "first"' not in response.text


def test_invalid_upload_is_rejected(tmp_path,monkeypatch):
    monkeypatch.setattr(api,"STORE",Store(tmp_path/"tasks.db"))
    with TestClient(api.app) as client:
        response=client.post("/api/documents",files={"file":("fake.pdf",b"not a pdf","application/pdf")})
        assert response.status_code==415


def test_unknown_task_is_404(tmp_path,monkeypatch):
    monkeypatch.setattr(api,"STORE",Store(tmp_path/"tasks.db"))
    with TestClient(api.app) as client:
        assert client.get("/api/tasks/missing").status_code==404


def test_duplicate_pdf_reuses_document(tmp_path,monkeypatch):
    monkeypatch.setattr(api,"STORE",Store(tmp_path/"tasks.db"))
    pdf=(api.ROOT/"data/raw/qasper.pdf").read_bytes()
    with TestClient(api.app) as client:
        response=client.post("/api/documents",files={"file":("duplicate.pdf",pdf,"application/pdf")})
        assert response.status_code==202
        assert response.json()["duplicate"] is True
        assert response.json()["doc_id"]=="qasper"


def test_restart_marks_pending_task_interrupted(tmp_path):
    store=Store(tmp_path/"tasks.db")
    identity=store.create("research",{"questions":["q"]})
    store.update(identity,"running")
    store.recover()
    assert store.get(identity)["status"]=="interrupted"
    assert store.get(identity)["request"]["questions"]==["q"]


def test_connection_is_closed_after_operation(tmp_path):
    import pytest,sqlite3
    store=Store(tmp_path/"tasks.db")
    with store.connect() as db:
        assert db.execute("SELECT 1").fetchone()[0]==1
    with pytest.raises(sqlite3.ProgrammingError):
        db.execute("SELECT 1")
