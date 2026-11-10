"""调用真实接口做小规模验收，不能作为通用质量统计。"""
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from paper_research.workflow import research
from paper_research.reporting import save_artifacts
from paper_research.config import write_json

CASES=[
 {"id":"qasper","questions":["QASPER 包含多少个问题，涉及多少篇论文？","仅依据摘要，能否确认作者使用的 GPU 型号？"],"scope":"abstract","doc_ids":["qasper"]},
 {"id":"comparison","questions":["比较这两篇论文：RAG 采用的生成模型是什么，Self-RAG 用于自我反思的特殊 token 是什么？"],"scope":"full","doc_ids":["rag","selfrag"]},
 {"id":"unrelated","questions":["香蕉蛋糕的烘烤温度和时间是多少？"],"scope":"full","doc_ids":["qasper"]},
]


def main():
    results=[]
    for case in CASES:
        print("Running",case["id"],flush=True)
        result=research(case["questions"],case["scope"],case["doc_ids"],
            on_event=lambda event: print(json.dumps(event,ensure_ascii=False),flush=True))
        directory=ROOT/"output"/("live_"+case["id"])
        save_artifacts(directory,result)
        answers=result["report"]["answers"]
        if case["id"]=="qasper":
            text=answers[0]["answer"].replace(",","")
            passed=answers[0]["status"]=="supported" and "5049" in text and "1585" in text and answers[1]["status"]=="insufficient"
        elif case["id"]=="comparison":
            passed=answers[0]["status"] in ("supported","inferred") and len({e["source_id"] for e in result["report"]["evidence"]})>=2
        else:
            passed=all(answer["status"]=="insufficient" for answer in answers)
        results.append({"case_id":case["id"],"passed":passed,"statuses":[a["status"] for a in answers],
            "artifact_directory":str(directory),"model_calls":len(result["metrics"]["model_calls"]),
            "tokens":sum(call.get("usage",{}).get("total_tokens",0) for call in result["metrics"]["model_calls"])})
    summary={"cases":results,"passed":all(row["passed"] for row in results),
        "note":"真实接口冒烟检查，断言只是局部启发式，不等于盲测正确率或独立人工核验。"}
    write_json(ROOT/"output/live_smoke_results.json",summary)
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    return 0 if summary["passed"] else 1


if __name__=="__main__":
    raise SystemExit(main())
