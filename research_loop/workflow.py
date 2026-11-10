"""Prepare, validate, execute and render a versioned research run."""

import hashlib
from pathlib import Path
from urllib.parse import urlsplit

from . import experiment
from .artifacts import (
    MAX_INPUT_BYTES as MAX_INPUT_BYTES,
    digest as digest,
    publish,
    put_new,
    read_json,
    read_run as read_artifacts,
    require_keys,
    require_text,
)


STAGES = ("request", "proposal", "evaluation")


def read_run(run, stages=STAGES):
    return read_artifacts(run, stages)


def prepare(case_path, run):
    case = read_json(case_path)
    require_keys(case, ("title", "question", "adapter", "materials"))
    title = require_text(case["title"], "title", 160)
    question = require_text(case["question"], "question")
    if case["adapter"] != "tsk_overlap":
        raise ValueError("Adapter must be tsk_overlap")
    if not isinstance(case["materials"], list) or not 1 <= len(case["materials"]) <= 12:
        raise ValueError("Provide 1 to 12 source excerpts")
    ids = set()
    materials = []
    for item in case["materials"]:
        require_keys(item, ("id", "title", "url", "locator", "excerpt"))
        source = {key: require_text(value, key, 1200) for key, value in item.items()}
        if source["id"] in ids:
            raise ValueError("Duplicate source id")
        url = urlsplit(source["url"])
        if url.scheme != "https" or not url.hostname or url.username or url.password or any(c in source["url"] for c in " \r\n<>"):
            raise ValueError("Source must be a plain HTTPS reference")
        ids.add(source["id"])
        materials.append(source)
    run.mkdir(parents=True, exist_ok=True)
    if any(run.iterdir()):
        raise ValueError("Use an empty run directory")
    implementation = Path(experiment.__file__).read_bytes()
    return publish(run, "request", None, {
        "case": {"title": title, "question": question, "adapter": case["adapter"], "materials": materials},
        "protocol": experiment.SPEC,
        "adapter_sha256": hashlib.sha256(implementation).hexdigest(),
    })


def validate_proposal(request, submission):
    require_keys(submission, ("request_id", "proposal"))
    if submission["request_id"] != request["id"]:
        raise ValueError("Proposal targets a different request version")
    proposal = submission["proposal"]
    require_keys(proposal, ("hypothesis", "mechanism", "falsifier", "nearby_work"))
    for key in ("hypothesis", "mechanism", "falsifier"):
        require_text(proposal[key], key)
    sources = {row["id"]: row for row in request["payload"]["case"]["materials"]}
    references = proposal["nearby_work"]
    if not isinstance(references, list) or not 1 <= len(references) <= len(sources):
        raise ValueError("Provide one or more distinct source comparisons")
    seen = set()
    for row in references:
        require_keys(row, ("source_id", "quote", "comparison"))
        identity = require_text(row["source_id"], "source_id")
        quote = require_text(row["quote"], "quote", 600)
        require_text(row["comparison"], "comparison")
        if identity in seen or identity not in sources or quote not in sources[identity]["excerpt"]:
            raise ValueError(f"Unknown source, duplicate, or quote missing from its excerpt: {identity}")
        seen.add(identity)
    return proposal


def record(run, submission):
    history = read_run(run)
    if tuple(history) != ("request",):
        raise ValueError("Record requires a prepared run without a proposal")
    request = history["request"]
    proposal = validate_proposal(request, submission)
    return publish(run, "proposal", request["id"], proposal)


def evaluate(run):
    history = read_run(run)
    if tuple(history) != ("request", "proposal"):
        raise ValueError("Evaluate requires an accepted proposal and no existing evaluation")
    request = history["request"]["payload"]
    if request["adapter_sha256"] != hashlib.sha256(Path(experiment.__file__).read_bytes()).hexdigest():
        raise ValueError("Experiment implementation changed. Prepare a new run.")
    if request["protocol"] != experiment.SPEC:
        raise ValueError("Experiment protocol changed. Prepare a new run.")
    if set(request["protocol"]["validation_seeds"]) & set(request["protocol"]["heldout_seeds"]):
        raise ValueError("Validation and held-out seeds overlap")
    results = experiment.run(request["protocol"])
    return publish(run, "evaluation", history["proposal"]["id"], results)


def markdown(history):
    request = history["request"]["payload"]
    case, spec = request["case"], request["protocol"]
    proposal, data = (history[name]["payload"] for name in ("proposal", "evaluation"))
    selected = data["frozen_candidate"]
    controls = data["heldout"]["mean_seed_rmse"]
    assessment = "通过本次合成实验的预设门槛" if data["experiment_gate_passed"] else "未通过预设门槛，保留联合岭回归"
    lines = [
        "# " + case["title"], "", case["question"], "", "## 待检验的想法", "",
        proposal["hypothesis"], "", proposal["mechanism"], "", "**预设反例**", "", proposal["falsifier"],
        "", "## 已读证据与近邻", "",
    ]
    sources = {row["id"]: row for row in case["materials"]}
    for comparison in proposal["nearby_work"]:
        source = sources[comparison["source_id"]]
        lines.extend([f"- {source['title']}（{source['locator']}）。{comparison['comparison']} [原始材料](<{source['url']}>)"])
    lines.extend([
        "", "## 固定协议与结果", "",
        f"验证使用 {len(spec['validation_seeds'])} 个种子，保留测试使用 {len(spec['heldout_seeds'])} 个不同种子。"
        f"每个情景每个种子预测 {spec['steps'] - spec['window']} 次。每步仅用此前 {spec['window']} 条已观测标签。",
        f"验证阶段确定候选 `{selected}`，保留测试只评估该候选与对照。指标为每条流的 RMSE 后按种子平均。",
        f"主情景需较联合岭回归改善至少 {100*spec['minimum_primary_gain']:.0f}%，同时优于该情景最强对照。"
        f"任何情景相对联合岭回归的退步不能超过 {100*spec['maximum_slice_loss']:.0f}%。验证与保留测试都需要通过。",
        "", "| 保留测试情景 | 联合岭 RMSE | 候选 RMSE | 相对变化（正值表示改善） |", "|---|---:|---:|---:|",
    ])
    for scenario, methods in controls.items():
        gain = data["heldout"]["gate"]["gains_vs_joint_ridge"][scenario]
        lines.append(f"| {scenario} | {methods[spec['baseline']]:.5f} | {methods[selected]:.5f} | {gain:+.2%} |")
    for name, gate in [("验证", data["validation"]["gates"][selected]), ("保留测试", data["heldout"]["gate"])]:
        messages = "、".join(gate["failures"]) if gate["failures"] else "通过"
        lines.extend(["", f"- **{name}门槛** {messages}。主情景最强对照为 `{gate['best_primary_control']}`。"])
    lines.extend([
        "", f"**决策** {assessment}。本轮策略为 `{data['recommended_policy']}`。",
        "", "## 结论范围", "",
        "数据由预定情景生成，长期参数使用合成模型已知初值。结果只适用于这批种子、数据生成过程与预设策略。",
        "论文摘录只核查来源绑定。机制相似性仍需阅读方法全文判断，候选的论文新颖性仍待核实。"
        "保留结果中的负面切片，避免把主情景收益写成普遍提升。",
        "", "## 运行记录", "",
        f"- 输入版本 `{history['request']['id']}`",
        f"- 提案版本 `{history['proposal']['id']}`",
        f"- 实验版本 `{history['evaluation']['id']}`",
        f"- 实验总耗时 {data['elapsed_seconds']:.3f} 秒，包含所有对照，不是单个方法的推理延迟。",
        "",
    ])
    return "\n".join(lines)


def report(run):
    history = read_run(run)
    if tuple(history) != STAGES:
        raise ValueError("Report requires a completed evaluation")
    path = run / "REPORT.md"
    expected = markdown(history)
    if path.exists():
        if path.read_text(encoding="utf-8") != expected:
            raise ValueError("Existing report does not match its receipts")
    else:
        put_new(path, expected)
    return path


def verify(run):
    history = read_run(run)
    if tuple(history) != STAGES:
        raise ValueError("Run is incomplete")
    validate_proposal(history["request"], {
        "request_id": history["request"]["id"],
        "proposal": history["proposal"]["payload"],
    })
    if (run / "REPORT.md").read_text(encoding="utf-8") != markdown(history):
        raise ValueError("Report does not match experiment receipts")
    return {"status": "verified", "stages": {name: row["id"] for name, row in history.items()}}
