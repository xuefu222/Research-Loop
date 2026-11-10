import argparse
import hashlib
import json
import re
from pathlib import Path


# 第一块：把英文文字拆成词
def tokenize(text):
    return re.findall(r"[a-z0-9]+", text.lower())


# 第二块：检索论文片段
def search_chunks(data, query, top_k):
    if top_k <= 0:
        raise ValueError("top_k 必须大于 0")

    if not isinstance(data, dict):
        raise ValueError("输入 JSON 顶层必须是对象")

    source = data.get("source")
    chunks = data.get("chunks")

    if not isinstance(source, dict):
        raise ValueError("输入缺少有效的 source 记录")

    if not isinstance(chunks, list) or not chunks:
        raise ValueError("chunks 必须是非空列表")

    # 去除重复检索词，并排序，方便保存和检查
    query_terms = sorted(set(tokenize(query)))

    if not query_terms:
        raise ValueError("当前版本需要输入英文单词或数字")

    results = []

    for index, chunk in enumerate(chunks):
        if not isinstance(chunk, dict):
            raise ValueError(f"chunks[{index}] 必须是对象")

        text = chunk.get("text")
        chunk_id = chunk.get("chunk_id")
        page_number = chunk.get("pdf_page")

        if not isinstance(text, str):
            raise ValueError(f"chunks[{index}].text 必须是字符串")

        if not isinstance(chunk_id, str) or not chunk_id.strip():
            raise ValueError(
                f"chunks[{index}].chunk_id 必须是非空字符串"
            )

        if type(page_number) is not int or page_number < 1:
            raise ValueError(
                f"chunks[{index}].pdf_page 必须是正整数"
            )

        # 当前片段中出现过的词
        chunk_terms = set(tokenize(text))

        # 找出检索词与片段共有的词
        matched_terms = [
            term
            for term in query_terms
            if term in chunk_terms
        ]

        # 没有匹配词的片段，不加入结果
        if not matched_terms:
            continue

        # 得分：匹配的不同检索词数量 / 检索词总数
        score = len(matched_terms) / len(query_terms)

        # 保留原始片段中的所有字段，再加入检索信息
        results.append({
            **chunk,
            "score": score,
            "matched_terms": matched_terms,
        })

    # 得分高的排前面；同分时保留原来的先后顺序
    results.sort(
        key=lambda item: item["score"],
        reverse=True,
    )

    matched_chunk_count = len(results)

    # 最多返回 top_k 条
    selected = results[:top_k]

    # 给返回结果添加排名，从 1 开始
    ranked_results = [
        {"rank": rank, **item}
        for rank, item in enumerate(selected, start=1)
    ]

    return {
        "method": "keyword-coverage-v1",
        "source": source,
        "query": query,
        "query_terms": query_terms,
        "top_k": top_k,
        "searched_chunk_count": len(chunks),
        "matched_chunk_count": matched_chunk_count,
        "returned_chunk_count": len(ranked_results),
        "results": ranked_results,
    }


# 第三块：读取参数、执行检索、保存结果
def main():
    parser = argparse.ArgumentParser(
        description="使用英文关键词检索论文片段"
    )
    parser.add_argument(
        "input",
        type=Path,
        help="论文片段 JSON 文件",
    )
    parser.add_argument(
        "output",
        type=Path,
        help="检索结果 JSON 文件",
    )
    parser.add_argument(
        "--query",
        required=True,
        help="英文检索词，多个词用空格分隔",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="最多返回多少个片段，默认 5",
    )
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

        result = search_chunks(
            data,
            args.query,
            args.top_k,
        )

        # 记录本次检索使用的是哪个输入文件
        result["input_file"] = str(input_path)
        result["input_sha256"] = hashlib.sha256(
            input_bytes
        ).hexdigest()

        output_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        output_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    except (OSError, ValueError) as error:
        print(f"检索失败：{error}")
        return 2

    print(f"检索词：{', '.join(result['query_terms'])}")
    print(f"检索片段数：{result['searched_chunk_count']}")
    print(f"匹配片段数：{result['matched_chunk_count']}")
    print(f"返回片段数：{result['returned_chunk_count']}")

    for item in result["results"]:
        print()
        print(
            f"第 {item['rank']} 条 | "
            f"PDF 第 {item['pdf_page']} 页 | "
            f"关键词覆盖率 {item['score']:.2f}"
        )
        print(
            f"匹配词：{', '.join(item['matched_terms'])}"
        )
        print(f"文字预览：{item['text'][:240]}")

    print()
    print(f"完整结果保存到：{output_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())