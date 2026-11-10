"""从宿主生成的 U 编号草稿回填真实原文、来源和页码。"""
import argparse
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
from paper_research.config import read_json, write_json
from paper_research.grounding import canonicalize
from paper_research.reporting import render_markdown


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("packet",type=Path)
    parser.add_argument("draft",type=Path)
    parser.add_argument("output",type=Path)
    parser.add_argument("--question",action="append")
    args=parser.parse_args()
    try:
        if args.output.suffix.lower() != ".json":
            raise ValueError("输出文件必须使用 .json 扩展名")
        if args.output.resolve() in (args.packet.resolve(), args.draft.resolve()):
            raise ValueError("输出不能覆盖输入")
        packet=read_json(args.packet)
        questions=args.question or packet.get("questions")
        if not questions:
            raise ValueError("证据包缺少 questions，请用 --question 按原顺序提供")
        report=canonicalize(read_json(args.draft),packet,questions)
        write_json(args.output,report)
        args.output.with_suffix(".md").write_text(render_markdown(report),encoding="utf-8")
        print("报告已保存，结构与引文原文对应关系通过。语义支持仍需审核。")
        return 0
    except (OSError,ValueError,KeyError) as error:
        print("组装失败："+str(error)); return 1


if __name__=="__main__":
    raise SystemExit(main())
