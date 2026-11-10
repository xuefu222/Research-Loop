import argparse
import hashlib
import json
import re
from pathlib import Path


# 第一块：清理检索用文本
def clean_text(text):
    replacements = str.maketrans({
        "ﬁ": "fi",
        "ﬂ": "fl",
        "ﬀ": "ff",
        "ﬃ": "ffi",
        "ﬄ": "ffl",
    })

    text = text.translate(replacements)

    # 把连续空格、换行和制表符统一为一个空格
    text = re.sub(r"\s+", " ", text)

    return text.strip()


# 第二块：在一页内部切分片段
def split_page(text, page_number, source_hash, chunk_size, overlap):
    chunks = []
    start = 0

    while start < len(text):
        end = min(start + chunk_size, len(text))

        raw_text = text[start:end]
        cleaned_text = clean_text(raw_text)

        if cleaned_text:
            chunk_id = (
                f"{source_hash}"
                f"-p{page_number}"
                f"-s{start}"
                f"-e{end}"
            )

            chunks.append({
                "chunk_id": chunk_id,
                "pdf_page": page_number,
                "start_char": start,
                "end_char": end,
                "raw_text": raw_text,
                "text": cleaned_text,
            })

        # 已经到达页尾，结束这一页
        if end == len(text):
            break

        # 下一块从上一块结束位置向前退 overlap 个字符
        start = end - overlap

    return chunks


# 第三块：读取逐页文本并生成片段
def build_chunks(data, chunk_size, overlap):
    if chunk_size <= 0:
        raise ValueError("chunk_size 必须大于 0")

    if not 0 <= overlap < chunk_size:
        raise ValueError("overlap 必须大于等于 0，并小于 chunk_size")

    if not isinstance(data, dict):
        raise ValueError("输入 JSON 顶层必须是对象")

    source = data.get("source")
    pages = data.get("pages")

    if not isinstance(source, dict):
        raise ValueError("输入缺少有效的 source 记录")

    source_hash = source.get("sha256")

    if not isinstance(source_hash, str):
        raise ValueError("source.sha256 必须是字符串")

    if not re.fullmatch(r"[0-9a-fA-F]{64}", source_hash):
        raise ValueError("source.sha256 必须是有效的 SHA-256 格式")

    if not isinstance(pages, list):
        raise ValueError("输入中的 pages 必须是列表")

    chunks = []
    seen_pages = set()

    for page in pages:
        if not isinstance(page, dict):
            raise ValueError("pages 中的每一项必须是对象")

        page_number = page.get("pdf_page")
        text = page.get("text")

        if type(page_number) is not int or page_number < 1:
            raise ValueError("pdf_page 必须是从 1 开始的整数")

        if page_number in seen_pages:
            raise ValueError(f"PDF 页码重复：{page_number}")

        if not isinstance(text, str):
            raise ValueError(f"第 {page_number} 页的 text 必须是字符串")

        seen_pages.add(page_number)

        page_chunks = split_page(
            text,
            page_number,
            source_hash,
            chunk_size,
            overlap,
        )
        chunks.extend(page_chunks)

    if not chunks:
        raise ValueError("没有生成有效片段，请检查 PDF 文本提取结果")

    return {
        "source": source,
        "parser": data.get("parser"),
        "normalization": "ligatures-and-whitespace-v1",
        "page_count": len(pages),
        "chunk_size": chunk_size,
        "overlap": overlap,
        "chunk_count": len(chunks),
        "chunks": chunks,
    }


# 第四块：命令行入口
def main():
    parser = argparse.ArgumentParser(
        description="清洗并切分论文逐页文本"
    )
    parser.add_argument("input", type=Path, help="逐页文本 JSON")
    parser.add_argument("output", type=Path, help="输出片段 JSON")
    parser.add_argument("--chunk-size", type=int, default=1000)
    parser.add_argument("--overlap", type=int, default=200)
    args = parser.parse_args()

    input_path = args.input.resolve()
    output_path = args.output.resolve()

    try:
        if input_path == output_path:
            raise ValueError("输入与输出文件不能相同")

        if output_path.suffix.lower() != ".json":
            raise ValueError("输出文件必须使用 .json 扩展名")

        input_bytes = input_path.read_bytes()
        data = json.loads(input_bytes.decode("utf-8-sig"))

        result = build_chunks(
            data,
            args.chunk_size,
            args.overlap,
        )

        result["input_file"] = str(input_path)
        result["input_sha256"] = hashlib.sha256(
            input_bytes
        ).hexdigest()

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    except (OSError, ValueError) as error:
        print(f"分块失败：{error}")
        return 2

    print(f"输入页数：{result['page_count']}")
    print(f"生成片段数：{result['chunk_count']}")
    print(f"片段长度：{result['chunk_size']}")
    print(f"重叠长度：{result['overlap']}")
    print(f"结果保存到：{output_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())