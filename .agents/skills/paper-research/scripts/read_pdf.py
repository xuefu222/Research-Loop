import argparse
import hashlib
import json
from io import BytesIO
from pathlib import Path

import pypdf
from pypdf import PdfReader
from pypdf.errors import PyPdfError


# 第一块：读取 PDF，提取每一页的文本
def extract_pdf(pdf_path, source_url):
    pdf_bytes = pdf_path.read_bytes()

    # 解析的内容与计算校验和的内容使用同一份数据
    reader = PdfReader(BytesIO(pdf_bytes))

    if reader.is_encrypted:
        raise ValueError("当前读取工具只处理未加密的 PDF")

    page_count = len(reader.pages)

    if page_count == 0:
        raise ValueError("PDF 没有可读取的页面")

    pages = []
    empty_pages = []

    for page_number, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""

        if not text.strip():
            empty_pages.append(page_number)

        pages.append({
            "pdf_page": page_number,
            "text": text,
            "char_count": len(text),
        })

    return {
        "source": {
            "file_path": str(pdf_path),
            "url": source_url,
            "sha256": hashlib.sha256(pdf_bytes).hexdigest(),
        },
        "parser": {
            "name": "pypdf",
            "version": pypdf.__version__,
        },
        "page_numbering": "PDF 页面顺序，从 1 开始",
        "page_count": page_count,
        "text_page_count": page_count - len(empty_pages),
        "empty_pages": empty_pages,
        "pages": pages,
    }


# 第二块：接收命令行参数并保存结果
def main():
    parser = argparse.ArgumentParser(
        description="提取论文 PDF 的逐页文本"
    )
    parser.add_argument("pdf", type=Path, help="输入 PDF 路径")
    parser.add_argument("output", type=Path, help="输出 JSON 路径")
    parser.add_argument(
        "--source-url",
        default=None,
        help="论文来源链接，仅用于记录",
    )
    args = parser.parse_args()

    pdf_path = args.pdf.resolve()
    output_path = args.output.resolve()

    try:
        if not pdf_path.is_file():
            raise ValueError(f"找不到 PDF 文件：{pdf_path}")

        if output_path.suffix.lower() != ".json":
            raise ValueError("输出文件必须使用 .json 扩展名")

        if output_path == pdf_path:
            raise ValueError("输入文件与输出文件不能相同")

        result = extract_pdf(pdf_path, args.source_url)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    except (OSError, ValueError, PyPdfError) as error:
        print(f"提取失败：{error}")
        return 2

    print(f"PDF 总页数：{result['page_count']}")
    print(f"有文本的页数：{result['text_page_count']}")
    print(f"未提取到文本的页面：{result['empty_pages']}")
    print(f"结果保存到：{output_path}")

    if result["text_page_count"] == 0:
        print("未提取到文字，请人工检查 PDF 的内容和形式。")
        return 1

    return 0


# 第三块：命令行入口
if __name__ == "__main__":
    raise SystemExit(main())
