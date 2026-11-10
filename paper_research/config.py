import json
import os
from pathlib import Path

ROOT = Path(os.getenv("PAPER_RESEARCH_ROOT", Path(__file__).resolve().parents[1]))
SKILL = ROOT / ".agents/skills/paper-research"
CACHE = ROOT / "models/hf_cache"
INDEX = ROOT / "data/index/corpus.json"
MODEL_ID = "intfloat/multilingual-e5-small"
MODEL_REVISION = "614241f622f53c4eeff9890bdc4f31cfecc418b3"


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path, value):
    """同目录临时文件加原子替换，避免读取到半个索引。"""
    import os
    import tempfile
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     suffix=".tmp", delete=False) as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        temp = stream.name
    try:
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def retrieval_config():
    return read_json(ROOT / "config/retrieval.json")


def model_config():
    path = ROOT / "config/model.local.json"
    value = read_json(path) if path.exists() else {}
    for key, env in (("base_url", "MAIN_BASE_URL"), ("model", "MAIN_MODEL"),
                     ("api_key", "MAIN_API_KEY")):
        if os.getenv(env):
            value[key] = os.environ[env]
    return value
