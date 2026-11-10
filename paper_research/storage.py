"""SQLite 记录任务状态和事件；每次操作单独连接，适配后台线程。"""
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from .config import ROOT


class Store:
    def __init__(self, path=None):
        self.path = path or ROOT / "data/app.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS tasks(
                    id TEXT PRIMARY KEY, kind TEXT, status TEXT, request TEXT,
                    result TEXT, error TEXT, created_at TEXT);
                CREATE TABLE IF NOT EXISTS events(
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT, payload TEXT);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def recover(self):
        with self.connect() as db:
            db.execute("UPDATE tasks SET status='interrupted',error='服务重启，任务需重新提交' WHERE status IN ('queued','running')")

    def create(self, kind, request):
        identity = uuid.uuid4().hex
        with self.connect() as db:
            db.execute("INSERT INTO tasks VALUES(?,?,?,?,?,?,?)", (identity, kind, "queued",
                json.dumps(request, ensure_ascii=False), None, None, datetime.now(timezone.utc).isoformat()))
        return identity

    def update(self, identity, status, result=None, error=None):
        with self.connect() as db:
            db.execute("UPDATE tasks SET status=?,result=?,error=? WHERE id=?",
                (status, json.dumps(result, ensure_ascii=False) if result is not None else None, error, identity))

    def event(self, identity, payload):
        with self.connect() as db:
            db.execute("INSERT INTO events(task_id,payload) VALUES(?,?)",
                (identity, json.dumps(payload, ensure_ascii=False)))

    def events(self, identity, after=0):
        with self.connect() as db:
            rows = db.execute("SELECT sequence,payload FROM events WHERE task_id=? AND sequence>? ORDER BY sequence",
                (identity, after)).fetchall()
        return [{"sequence": row["sequence"], **json.loads(row["payload"])} for row in rows]

    def get(self, identity):
        with self.connect() as db:
            row = db.execute("SELECT * FROM tasks WHERE id=?", (identity,)).fetchone()
        if not row:
            return None
        result = dict(row)
        for field in ("request", "result"):
            result[field] = json.loads(result[field]) if result[field] else None
        return result
