"""默认只做本地检查，不调用生成模型。"""
import ast
import hashlib
import json
import subprocess
import sys
import os
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from paper_research.config import read_json,write_json,INDEX,model_config


def main():
    checks={}
    source_files=list((ROOT/"paper_research").glob("*.py"))+list((ROOT/"scripts").glob("*.py"))+list((ROOT/".agents/skills/paper-research/scripts").glob("*.py"))
    for path in source_files:
        ast.parse(path.read_text(encoding="utf-8-sig"))
    checks["source_syntax"]=True
    index=read_json(INDEX)
    rows=index["chunks"]
    pages={source["doc_id"]:{p["pdf_page"]:p["text"] for p in read_json(ROOT/f"data/processed/{source['doc_id']}.pages.json")["pages"]} for source in index["sources"]}
    checks["unique_chunks"]=len({row["chunk_id"] for row in rows})==len(rows)
    checks["all_raw_offsets_match"]=all(row["raw_text"]==pages[row["doc_id"]][row["pdf_page"]][row["start_char"]:row["end_char"]] for row in rows)
    vectors=np.asarray([row["embedding"] for row in rows])
    checks["finite_unit_vectors"]=bool(np.isfinite(vectors).all() and np.allclose(np.linalg.norm(vectors,axis=1),1,atol=1e-4))
    checks["all_sources_have_abstracts"]=all(any(row["doc_id"]==source["doc_id"] and row["section"]=="abstract" for row in rows) for source in index["sources"])
    checks["raw_pdf_checksums_match"]=all(hashlib.sha256((ROOT/source["path"]).read_bytes()).hexdigest()==source["sha256"] for source in index["sources"])
    private_key=model_config().get("api_key","")
    leaks=[]
    if private_key:
        for directory, folders, filenames in os.walk(ROOT):
            folders[:]=[name for name in folders if name not in (".venv","node_modules","models",".git","__pycache__")]
            for filename in filenames:
                path=Path(directory)/filename
                if path.name=="model.local.json":
                    continue
                if path.suffix.lower() in (".py",".json",".jsonl",".md",".txt",".log",".js",".css",".toml",".html",".yaml",".yml",".ps1",".bin",".pkl") and private_key.encode() in path.read_bytes():
                    leaks.append(str(path.relative_to(ROOT)))
    checks["credential_not_in_code_or_reports"]=not leaks
    results={}
    for name,args in (("dependencies",[sys.executable,"-m","pip","check"]),("tests",[sys.executable,"-m","pytest","-q"])):
        result=subprocess.run(args,cwd=ROOT,capture_output=True,text=True,encoding="utf-8",errors="replace")
        checks[name]=result.returncode==0
        results[name]={"exit_code":result.returncode,"stdout":result.stdout,"stderr":result.stderr}
    report={"checked_at_utc":datetime.now(timezone.utc).isoformat(),"passed":all(checks.values()),
        "checks":checks,"commands":results,"documents":len(index["sources"]),"chunks":len(rows),
        "credential_scan_flagged_files":leaks}
    write_json(ROOT/"output/acceptance.json",report)
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0 if report["passed"] else 1


if __name__=="__main__":
    raise SystemExit(main())
