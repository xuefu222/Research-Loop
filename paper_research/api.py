import asyncio
import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import ROOT, INDEX, model_config, read_json, write_json
from .indexing import build_index
from .reporting import save_artifacts
from .retrieval import Retriever
from .storage import Store
from .workflow import research

STORE = Store()
WORKERS = ThreadPoolExecutor(max_workers=2, thread_name_prefix="paper-task")
INGEST_LOCK = threading.Lock()


@asynccontextmanager
async def lifespan(app):
    STORE.recover()
    yield


app = FastAPI(title="Paper Research · 论文证据工作台", version="0.2.0", lifespan=lifespan)


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    method: Literal["bm25", "dense", "hybrid"] = "hybrid"
    scope: Literal["full", "abstract"] = "full"
    doc_ids: list[str] | None = Field(default=None, min_length=1, max_length=8)
    top_k: int = Field(default=6, ge=1, le=50)
    lexical_query: str | None = Field(default=None, max_length=2000)


class TaskRequest(BaseModel):
    questions: list[str] = Field(min_length=1, max_length=5)
    scope: Literal["full", "abstract"] = "full"
    doc_ids: list[str] | None = Field(default=None, min_length=1, max_length=8)
    mode: Literal["agent", "packet"] = "agent"


def queue_research(identity, request):
    STORE.update(identity, "running")
    try:
        result = research(**request, on_event=lambda event: STORE.event(identity, event))
        result["artifact_directory"] = save_artifacts(ROOT / "output/tasks" / identity, result)
        STORE.update(identity, "completed", result)
        STORE.event(identity, {"node": "task", "status": "completed"})
    except Exception as error:
        STORE.update(identity, "failed", error=type(error).__name__ + ": " + str(error))
        STORE.event(identity, {"node": "task", "status": "failed"})


@app.get("/api/health")
def health():
    config = model_config()
    return {"status": "ok", "index_ready": INDEX.exists(),
        "model_configured": all(config.get(key) for key in ("base_url", "model", "api_key")),
        "model": config.get("model"), "project_version": "0.2.0"}


@app.get("/api/documents")
def documents():
    if not INDEX.exists():
        return {"documents": []}
    data = read_json(INDEX)
    return {"documents": [{**source, "abstract_chunks": sum(
        row["doc_id"] == source["doc_id"] and row["section"] == "abstract" for row in data["chunks"])}
        for source in data["sources"]], "chunk_count": data["chunk_count"]}


@app.post("/api/search")
def search(request: SearchRequest):
    try:
        return Retriever().search(**request.model_dump())
    except (ValueError, FileNotFoundError) as error:
        raise HTTPException(400, str(error)) from None


@app.post("/api/tasks", status_code=202)
def create_task(request: TaskRequest):
    if any(not question.strip() or len(question) > 2000 for question in request.questions):
        raise HTTPException(422, "每个问题必须为非空文本且不超过 2000 字符")
    if not INDEX.exists():
        raise HTTPException(409, "请先构建语料索引")
    known = {doc["doc_id"] for doc in read_json(INDEX)["sources"]}
    if request.doc_ids and set(request.doc_ids) - known:
        raise HTTPException(422, "指定论文不存在")
    identity = STORE.create("research", request.model_dump())
    WORKERS.submit(queue_research, identity, request.model_dump())
    return {"task_id": identity, "status": "queued"}


@app.get("/api/tasks/{identity}")
def get_task(identity: str):
    task = STORE.get(identity)
    if not task:
        raise HTTPException(404, "任务不存在")
    return task


@app.get("/api/tasks/{identity}/events")
async def events(identity: str, last_event_id: str | None = Header(default=None), after: int = 0):
    if not STORE.get(identity):
        raise HTTPException(404, "任务不存在")
    try:
        cursor = max(after, int(last_event_id or 0))
    except ValueError:
        raise HTTPException(400, "Last-Event-ID 必须为整数") from None

    async def stream():
        nonlocal cursor
        while True:
            for event in STORE.events(identity, cursor):
                cursor = event["sequence"]
                yield f"id: {cursor}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
            task = STORE.get(identity)
            if task["status"] in ("completed", "failed", "interrupted"):
                break
            yield ": heartbeat\n\n"
            await asyncio.sleep(0.5)
    return StreamingResponse(stream(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/tasks/{identity}/report")
def download_report(identity: str, format: Literal["json", "md"] = "md"):
    task = STORE.get(identity)
    if not task:
        raise HTTPException(404, "任务不存在")
    path = ROOT / "output/tasks" / task["id"] / f"report.{format}"
    if not path.is_file():
        raise HTTPException(409, "此任务尚未生成报告")
    return FileResponse(path, filename=f"paper-report-{identity[:8]}.{format}")


def ingest_job(identity, entry):
    STORE.update(identity, "running")
    try:
        with INGEST_LOCK:
            manifest_path = ROOT / "data/corpus_manifest.json"
            manifest = read_json(manifest_path)
            if not any(doc["doc_id"] == entry["doc_id"] for doc in manifest["documents"]):
                manifest["documents"].append(entry)
            pending_manifest = ROOT / "data" / f"manifest-{identity}.pending.json"
            write_json(pending_manifest, manifest)
            STORE.event(identity, {"node": "ingest", "status": "indexing"})
            try:
                summary = build_index(pending_manifest)
                write_json(manifest_path, manifest)
            finally:
                pending_manifest.unlink(missing_ok=True)
        STORE.update(identity, "completed", summary)
        STORE.event(identity, {"node": "ingest", "status": "completed"})
    except Exception as error:
        STORE.update(identity, "failed", error=type(error).__name__ + ": " + str(error))
        STORE.event(identity, {"node": "ingest", "status": "failed"})


@app.post("/api/documents", status_code=202)
async def upload_document(file: UploadFile = File(...), title: str = Form("")):
    content = await file.read(20 * 1024 * 1024 + 1)
    await file.close()
    if len(content) > 20 * 1024 * 1024:
        raise HTTPException(413, "单个 PDF 不得超过 20 MB")
    if not content.startswith(b"%PDF-"):
        raise HTTPException(415, "需要真实 PDF 文件")
    digest = hashlib.sha256(content).hexdigest()
    if INDEX.exists():
        existing = next((doc for doc in read_json(INDEX)["sources"] if doc["sha256"] == digest), None)
        if existing:
            identity = STORE.create("ingest", {"doc_id": existing["doc_id"], "duplicate": True})
            STORE.update(identity, "completed", {"doc_id": existing["doc_id"], "duplicate": True})
            STORE.event(identity, {"node": "ingest", "status": "completed"})
            return {"task_id": identity, "doc_id": existing["doc_id"], "duplicate": True}
    doc_id = "upload-" + digest[:12]
    path = ROOT / "data/raw" / f"{doc_id}.pdf"
    path.write_bytes(content)
    entry = {"doc_id": doc_id, "title": title.strip()[:200] or file.filename or doc_id,
        "path": str(path.relative_to(ROOT)), "url": path.as_uri(), "version": "user-upload",
        "sha256": digest, "license": "user supplied; not independently verified"}
    write_json(path.with_suffix(".source.json"), entry)
    identity = STORE.create("ingest", {"doc_id": doc_id, "title": entry["title"]})
    WORKERS.submit(ingest_job, identity, entry)
    return {"task_id": identity, "doc_id": doc_id}


if (ROOT / "web/index.html").exists():
    app.mount("/", StaticFiles(directory=ROOT / "web", html=True), name="web")
