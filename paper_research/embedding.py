"""共享 CPU 模型与查询缓存；不在导入模块时加载权重。"""
import threading
from functools import lru_cache
import numpy as np
from .config import CACHE, MODEL_ID, MODEL_REVISION


class Embedder:
    def __init__(self, cache=CACHE):
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer(MODEL_ID, revision=MODEL_REVISION,
            cache_folder=str(cache), local_files_only=True, device="cpu",
            trust_remote_code=False, model_kwargs={"use_safetensors": True})
        self.model.max_seq_length = 512
        self.lock = threading.Lock()

    def encode(self, texts, prefix):
        inputs = [prefix + text for text in texts]
        with self.lock:
            lengths = self.model.tokenizer(inputs, truncation=False,
                padding=False, return_length=True)["length"]
            if max(lengths, default=0) > 512:
                raise ValueError("模型输入超过 512 tokens，请缩短问题或片段")
            result = self.model.encode(inputs, prompt="", batch_size=8,
                normalize_embeddings=True, convert_to_numpy=True,
                show_progress_bar=False)
        if result.shape != (len(texts), 384) or not np.isfinite(result).all():
            raise ValueError("模型返回的向量无效")
        if not np.allclose(np.linalg.norm(result, axis=1), 1, atol=1e-4):
            raise ValueError("向量归一化失败")
        return result

    @lru_cache(maxsize=256)
    def query(self, text):
        result = self.encode([text], "query: ")[0]
        result.flags.writeable = False
        return result


@lru_cache(maxsize=2)
def _load_embedder(cache):
    return Embedder(cache)


_LOAD_LOCK = threading.Lock()


def get_embedder(cache=str(CACHE)):
    with _LOAD_LOCK:
        return _load_embedder(str(cache))
