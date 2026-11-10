import argparse
import hashlib
import json
import platform
from importlib.metadata import version
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer


# 固定模型及其版本，避免以后自动换成其他版本
MODEL_ID = "intfloat/multilingual-e5-small"
MODEL_REVISION = "614241f622f53c4eeff9890bdc4f31cfecc418b3"

DOCUMENT_PREFIX = "passage: "
QUERY_PREFIX = "query: "

EXPECTED_DIMENSION = 384
MAX_TOKENS = 512


# 第一块：检查输入数据
def check_chunks(data):
    if not isinstance(data, dict):
        raise ValueError("输入 JSON 顶层必须是对象")

    if not isinstance(data.get("source"), dict):
        raise ValueError("输入缺少有效的 source 记录")

    chunks = data.get("chunks")

    if not isinstance(chunks, list) or not chunks:
        raise ValueError("chunks 必须是非空列表")

    seen_ids = set()

    for index, chunk in enumerate(chunks):
        if not isinstance(chunk, dict):
            raise ValueError(f"chunks[{index}] 必须是对象")

        chunk_id = chunk.get("chunk_id")
        text = chunk.get("text")
        page_number = chunk.get("pdf_page")

        if not isinstance(chunk_id, str) or not chunk_id.strip():
            raise ValueError(
                f"chunks[{index}].chunk_id 必须是非空字符串"
            )

        if chunk_id in seen_ids:
            raise ValueError(f"片段编号重复：{chunk_id}")

        if not isinstance(text, str) or not text.strip():
            raise ValueError(
                f"chunks[{index}].text 必须是非空字符串"
            )

        if type(page_number) is not int or page_number < 1:
            raise ValueError(
                f"chunks[{index}].pdf_page 必须是正整数"
            )

        seen_ids.add(chunk_id)

    return chunks


# 第二块：调用模型，生成向量
def build_embeddings(data, cache_dir):
    chunks = check_chunks(data)

    print(f"正在加载模型：{MODEL_ID}", flush=True)
    print("首次运行可能需要下载模型文件。", flush=True)

    model = SentenceTransformer(
        MODEL_ID,
        revision=MODEL_REVISION,
        device="cpu",
        cache_folder=str(cache_dir),
        trust_remote_code=False,
        model_kwargs={"use_safetensors": True},
    )

    model.max_seq_length = MAX_TOKENS

    # 前缀只用于模型输入，不修改原来的论文文字
    passages = [
        DOCUMENT_PREFIX + chunk["text"]
        for chunk in chunks
    ]

    # 检查实际 token 数，避免模型静默截断片段
    tokenized = model.tokenizer(
        passages,
        add_special_tokens=True,
        padding=False,
        truncation=False,
        return_length=True,
    )
    token_counts = tokenized["length"]

    too_long = [
        chunks[index]["chunk_id"]
        for index, count in enumerate(token_counts)
        if count > MAX_TOKENS
    ]

    if too_long:
        raise ValueError(
            f"有 {len(too_long)} 个片段超过 "
            f"{MAX_TOKENS} tokens，请先缩小分块长度。"
            f"示例：{too_long[0]}"
        )

    print(f"待处理片段数：{len(chunks)}", flush=True)

    embeddings = model.encode(
        passages,
        prompt="",
        batch_size=8,
        show_progress_bar=True,
        convert_to_numpy=True,
        normalize_embeddings=True,
    )

    # 第三块：检查向量，再与原片段逐条关联
    expected_shape = (len(chunks), EXPECTED_DIMENSION)

    if embeddings.shape != expected_shape:
        raise ValueError(
            f"向量形状不符合预期：{embeddings.shape}，"
            f"预期为 {expected_shape}"
        )

    if not np.isfinite(embeddings).all():
        raise ValueError("向量中存在无效数值")

    norms = np.linalg.norm(embeddings, axis=1)

    if not np.allclose(norms, 1.0, atol=1e-4):
        raise ValueError("向量归一化检查失败")

    records = []

    for chunk, vector, count in zip(
        chunks,
        embeddings,
        token_counts,
    ):
        records.append({
            **chunk,
            "embedding_token_count": int(count),
            "embedding": vector.tolist(),
        })

    return {
        "source": data["source"],
        "parser": data.get("parser"),
        "normalization": data.get("normalization"),
        "chunk_size": data.get("chunk_size"),
        "overlap": data.get("overlap"),
        "embedding_model": {
            "model_id": MODEL_ID,
            "revision": MODEL_REVISION,
            "dimension": EXPECTED_DIMENSION,
            "document_prefix": DOCUMENT_PREFIX,
            "query_prefix": QUERY_PREFIX,
            "normalize_embeddings": True,
            "max_tokens": MAX_TOKENS,
            "max_observed_tokens": int(max(token_counts)),
            "device": "cpu",
            "batch_size": 8,
        },
        "runtime": {
            "python": platform.python_version(),
            "packages": {
                name: version(name)
                for name in (
                    "sentence-transformers",
                    "transformers",
                    "torch",
                    "numpy",
                    "huggingface-hub",
                )
            },
        },
        "chunk_count": len(records),
        "chunks": records,
    }


# 第四块：读取文件、执行任务、保存结果
def main():
    parser = argparse.ArgumentParser(
        description="将论文片段转换成向量并保存"
    )
    parser.add_argument(
        "input",
        type=Path,
        help="论文片段 JSON 文件",
    )
    parser.add_argument(
        "output",
        type=Path,
        help="向量结果 JSON 文件",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        required=True,
        help="模型下载缓存目录",
    )
    args = parser.parse_args()

    input_path = args.input.resolve()
    output_path = args.output.resolve()
    cache_dir = args.cache_dir.resolve()

    try:
        if input_path == output_path:
            raise ValueError("输入与输出文件不能相同")

        if output_path.suffix.lower() != ".json":
            raise ValueError("输出文件必须使用 .json 扩展名")

        input_bytes = input_path.read_bytes()
        data = json.loads(input_bytes.decode("utf-8-sig"))

        result = build_embeddings(data, cache_dir)

        result["input_file"] = str(input_path)
        result["input_sha256"] = hashlib.sha256(
            input_bytes
        ).hexdigest()

        output_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        output_path.write_text(
            json.dumps(
                result,
                ensure_ascii=False,
                indent=2,
                allow_nan=False,
            ),
            encoding="utf-8",
        )

    except (OSError, ValueError, RuntimeError) as error:
        print(f"向量生成失败：{error}")
        return 2

    model_info = result["embedding_model"]

    print()
    print(f"处理片段数：{result['chunk_count']}")
    print(f"每条向量维度：{model_info['dimension']}")
    print(
        f"最长模型输入："
        f"{model_info['max_observed_tokens']} tokens"
    )
    print("向量数值和归一化检查通过。")
    print(f"结果保存到：{output_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
