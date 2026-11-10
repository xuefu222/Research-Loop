"""Read, validate and publish immutable, versioned run artifacts."""

import hashlib
import json
import os
from pathlib import Path
import tempfile


MAX_INPUT_BYTES = 2 * 1024 * 1024


def read_json(path):
    with path.open("rb") as stream:
        raw = stream.read(MAX_INPUT_BYTES + 1)
    if len(raw) > MAX_INPUT_BYTES:
        raise ValueError(f"Input is too large: {path.name}")
    return json.loads(raw.decode("utf-8-sig"))


def digest(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def require_keys(value, expected):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise ValueError(f"Expected fields: {', '.join(expected)}")


def require_text(value, name, limit=4000):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"{name} must be nonempty text of at most {limit} characters")
    return value.strip()


def put_new(path, body):
    """Atomically publish a complete file while preserving any existing artifact."""
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    staged = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(body)
        # The link operation fails if another writer has already published this stage.
        os.link(staged, path)
    finally:
        staged.unlink(missing_ok=True)


def publish(run, stage, parent, payload):
    content = {"stage": stage, "parent_id": parent, "payload": payload}
    receipt = {**content, "id": digest(content)}
    put_new(run / f"{stage}.json", json.dumps(receipt, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    return receipt


def read_run(run, stages):
    history = {}
    parent_id = None
    for stage in stages:
        path = run / f"{stage}.json"
        if not path.exists():
            break
        record = read_json(path)
        require_keys(record, ("stage", "parent_id", "payload", "id"))
        content = {key: value for key, value in record.items() if key != "id"}
        if record["stage"] != stage or record["parent_id"] != parent_id or record["id"] != digest(content):
            raise ValueError(f"Receipt or parent mismatch: {path.name}")
        parent_id = record["id"]
        history[stage] = record
    if any((run / f"{name}.json").exists() for name in stages[len(history) + 1:]):
        raise ValueError("Run contains a stage with a missing predecessor")
    return history
