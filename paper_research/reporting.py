import html
import json
from pathlib import Path
from .config import write_json


def render_markdown(report):
    lines = ["# 论文调研报告", "", html.escape(report["material_scope"]), ""]
    for item in report["answers"]:
        lines += ["## " + html.escape(item["question"]), "",
            "**状态：** " + item["status"], "", html.escape(item["answer"]), "",
            "**证据：** " + (", ".join(item["evidence_ids"]) or "暂无"), ""]
    lines += ["## 原文证据", ""]
    for item in report["evidence"]:
        lines += [f"### {item['evidence_id']} · {item['source_id']}", "",
            *["> " + html.escape(line) for line in item["text"].splitlines()], "",
            item["location"], ""]
    lines += ["## 来源", ""]
    lines += [f"- {item['source_id']}: {item['uri']}" for item in report["sources"]]
    lines += ["", "## 材料限制", ""]
    lines += ["- " + html.escape(item) for item in report["limitations"]]
    return "\n".join(lines) + "\n"


def save_artifacts(directory, result):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    for field, filename in (("packet", "evidence_packet.json"), ("trace", "trace.json"),
                             ("metrics", "run.json")):
        write_json(directory / filename, result[field])
    write_json(directory / "drafts.json", result.get("drafts", []))
    if result.get("report"):
        write_json(directory / "report.json", result["report"])
        (directory / "report.md").write_text(render_markdown(result["report"]), encoding="utf-8")
    return str(directory)
