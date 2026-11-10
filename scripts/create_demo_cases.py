"""依据人工核对的真实段落生成原页字符区间标注，不把答案写进检索查询。"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPECS = [
 ("qasper-count", "qasper", "train", "abstract", "QASPER 包含多少个问题和多少篇论文？", "QASPER dataset questions papers",
  r"a dataset of 5,049[\s\S]{0,120}?papers\.", "5049 个问题，1585 篇论文"),
 ("qasper-reader", "qasper", "train", "abstract", "QASPER 提问者在写问题时能阅读什么材料？", "question writer title abstract read only",
  r"read only[\s\S]{0,100}?sponding paper", "只阅读标题和摘要"),
 ("qasper-answer", "qasper", "train", "abstract", "QASPER 的答案与支撑证据由谁提供？", "questions answered separate practitioners supporting evidence",
  r"The questions\s+are then answered[\s\S]{0,160}?answers\.", "另一组 NLP 从业者回答并提供证据"),
 ("qasper-gap", "qasper", "train", "abstract", "现有模型在全文问答上比人类低至少多少 F1？", "underperforming humans 27 F1 entire papers",
  r"un-?\s*derperforming humans[\s\S]{0,130}?entire papers", "至少 27 F1"),
 ("rag-components", "rag", "train", "full", "RAG 论文使用哪种检索器和生成模型？", "DPR Dense Passage Retriever BART seq2seq",
  r"The\s+retriever \(Dense Passage Retriever[\s\S]{0,500}?output\.", "DPR 检索器和 BART 生成器"),
 ("rag-memory", "rag", "train", "abstract", "RAG 的非参数记忆来自什么语料？", "non parametric memory dense index Wikipedia",
  r"non-parametric memory is a dense[\s\S]{0,100}?retriever\.", "Wikipedia 的稠密向量索引"),
 ("rag-formulations", "rag", "train", "full", "RAG-Sequence 与 RAG-Token 对检索文档的使用有什么区别？", "RAG Sequence Token same different document target token",
  r"In one approach, RAG-Sequence[\s\S]{0,350}?different document\.", "前者同一序列使用同一文档，后者允许逐 token 使用不同文档"),
 ("rag-tasks", "rag", "train", "abstract", "论文报告在几个开放域问答任务上达到当时最佳水平？", "state art three open domain QA tasks",
  r"state\s+of\s+the\s+art\s+on\s+three\s+open\s+domain\s+QA\s+tasks", "三个任务；这是作者报告"),
 ("attention-heads", "attention", "validation", "full", "论文采用几个并行注意力头，每个头的 key 和 value 维度是多少？", "h 8 heads dk dv 64",
  r"In this work we employ h = 8[\s\S]{0,180}?= 64\.", "8 个头，dk=dv=64"),
 ("attention-dimension", "attention", "validation", "full", "基础 Transformer 的子层输出与嵌入维度 dmodel 是多少？", "embedding layers outputs dimension dmodel 512",
  r"all sub-layers[\s\S]{0,160}?dmodel = 512\.", "512"),
 ("attention-position", "attention", "validation", "full", "论文使用什么函数构造固定位置编码？", "positional encodings sine cosine frequencies",
  r"In this work, we use sine and cosine functions of different frequencies:", "不同频率的正弦和余弦函数"),
 ("attention-bleu", "attention", "validation", "abstract", "Transformer 在 WMT 2014 英德任务上报告了多少 BLEU？", "WMT 2014 English German 28.4 BLEU",
  r"Our model achieves 28.4 BLEU[\s\S]{0,140}?translation task", "28.4 BLEU"),
 ("selfrag-tokens", "selfrag", "test", "abstract", "Self-RAG 用什么特殊 token 支持反思？", "special reflection tokens",
  r"special tokens, called reflection tokens", "reflection tokens"),
 ("selfrag-size", "selfrag", "test", "abstract", "摘要报告的 Self-RAG 模型参数规模有哪些？", "Self RAG 7B 13B parameters",
  r"RAG \(7B and 13B parameters\)", "7B 与 13B"),
 ("selfrag-demand", "selfrag", "test", "abstract", "Self-RAG 如何决定何时检索材料？", "adaptively retrieves passages on demand",
  r"single arbitrary LM that adaptively[\s\S]{0,100}?retrieves passages on-demand", "模型自适应按需检索"),
 ("selfrag-types", "selfrag", "test", "full", "Self-RAG 把反思 token 分成哪两个大类？", "reflection tokens categorized retrieval critique",
  r"Reflection tokens are categorized into retrieval and critique tokens[\s\S]{0,160}?respectively", "检索 token 与批判 token"),
]


def main():
    cases = []
    for identity, paper, split, scope, question, lexical, pattern, expected in SPECS:
        data = json.loads((ROOT / f"data/processed/{paper}.pages.json").read_text(encoding="utf-8"))
        found = None
        for page in data["pages"]:
            match = re.search(pattern.replace(" ", r"\s+"), page["text"])
            if match:
                found = {"doc_id": paper, "pdf_page": page["pdf_page"],
                    "start_char": match.start(), "end_char": match.end()}
                break
        if found is None:
            raise ValueError("原文标注定位失败：" + identity)
        cases.append({"id": identity, "paper_id": paper, "split": split, "scope": scope,
            "question": question, "lexical_query": lexical, "evidence_spans": [found],
            "expected_answer": expected})
    cases.append({"id": "qasper-gpu-abstract", "paper_id": "qasper", "split": "train",
        "scope": "abstract", "question": "仅依据摘要，能否确认作者使用的 GPU 型号？",
        "lexical_query": "GPU graphics hardware model", "evidence_spans": [],
        "expected_status": "insufficient"})
    cases.append({"id": "qasper-unrelated", "paper_id": "qasper", "split": "train",
        "scope": "full", "question": "香蕉蛋糕的烘烤温度和时间是多少？",
        "lexical_query": "banana cake baking temperature time", "evidence_spans": [],
        "expected_status": "insufficient"})
    output = ROOT / "evals/cases.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"annotation": "人工设计问题和核对段落，程序定位原页字符区间；非官方评测集",
        "cases": cases}, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Saved", len(cases), "cases", flush=True)


if __name__ == "__main__":
    main()
