"""Versioned, adapter-independent intake and review for research proposals."""

import argparse
import hashlib
import json
import math
from pathlib import Path

from . import experiment as tsk
from .artifacts import publish, put_new, read_json, read_run, require_keys, require_text
from .review import ISSUE_FIELDS, design_issues, validate_controls


STAGES = ("brief", "candidate", "audit", "pilot")
CHECKS = ("mechanism", "prior_art", "falsifiability", "feasibility")
TSK_EXAMPLE = Path(__file__).resolve().parents[1] / "examples/research_loop/tsk_overlap"
RESULT_TITLES = {
    "awaiting_candidate": "待提交提案",
    "awaiting_review": "待审查",
    "needs_revision": "需要修订",
    "ready_for_pilot": "可开始小试",
    "pilot_supports_claim": "本次小试支持预设主张",
    "pilot_does_not_support_claim": "本次小试未支持预设主张",
}


def prepare(run, value):
    require_keys(value, ("question", "constraints", "sources"))
    require_text(value["question"], "question")
    require_text(value["constraints"], "constraints")
    if not isinstance(value["sources"], list) or len(value["sources"]) > 12:
        raise ValueError("sources must be a list of at most 12 records")
    ids = set()
    for row in value["sources"]:
        require_keys(row, ("id", "title", "reference", "locator", "scope", "excerpt"))
        for key in row:
            if require_text(row[key], key, 6000) != row[key]:
                raise ValueError(f"{key} has leading or trailing whitespace")
        if row["id"] in ids:
            raise ValueError("Duplicate source id")
        if row["scope"] not in ("abstract", "method", "full_text", "other"):
            raise ValueError("Invalid reading scope")
        ids.add(row["id"])
    run.mkdir(parents=True, exist_ok=True)
    if any(run.iterdir()):
        raise ValueError("Use a fresh, empty run directory")
    return publish(run, "brief", None, value)


def record_candidate(run, value):
    history = read_run(run, STAGES)
    if tuple(history) != ("brief",):
        raise ValueError("A prepared brief and no prior candidate are required")
    brief = history["brief"]
    required = ("brief_id", "hypothesis", "mechanism", "simple_baseline", "closest_baseline",
                "closest_source_id", "comparisons", "experiment")
    if isinstance(value, dict) and "pilot_adapter" in value:
        required += ("pilot_adapter",)
    if isinstance(value, dict) and "design_version" in value:
        required += ("design_version",)
    require_keys(value, required)
    if value["brief_id"] != brief["id"]:
        raise ValueError("Candidate belongs to a different brief")
    for key in ("hypothesis", "mechanism", "simple_baseline", "closest_baseline"):
        require_text(value[key], key)
    sources = {row["id"]: row for row in brief["payload"]["sources"]}
    seen = set()
    if not isinstance(value["comparisons"], list) or len(value["comparisons"]) > len(sources):
        raise ValueError("Invalid comparison list")
    for comparison in value["comparisons"]:
        require_keys(comparison, ("source_id", "quote", "relationship", "reason"))
        source_id = comparison["source_id"]
        quote = comparison["quote"]
        require_text(source_id, "source_id")
        require_text(quote, "quote", 600)
        require_text(comparison["reason"], "reason")
        if source_id in seen or source_id not in sources or quote not in sources[source_id]["excerpt"]:
            raise ValueError("Quote missing from its supplied source, or source id repeated")
        if comparison["relationship"] not in ("distinct", "same_mechanism", "uncertain"):
            raise ValueError("Invalid relationship to prior work")
        seen.add(source_id)
    closest = value["closest_source_id"]
    if closest is not None:
        require_text(closest, "closest_source_id")
        if closest not in seen:
            raise ValueError("Closest source must be listed in comparisons")
    experiment = value["experiment"]
    experiment_fields = ("metric", "unit", "better", "minimum_gain", "evaluation_data",
                         "matched_conditions", "negative_control", "expected_control_behavior")
    if value.get("design_version") is not None:
        if value["design_version"] != 2:
            raise ValueError("Unsupported design_version")
        experiment_fields += ("controls",)
        validate_controls(value)
    require_keys(experiment, experiment_fields)
    for key in ("metric", "unit", "evaluation_data", "matched_conditions",
                "negative_control", "expected_control_behavior"):
        require_text(experiment[key], key)
    gain = experiment["minimum_gain"]
    if type(gain) not in (int, float) or not math.isfinite(gain) or gain <= 0:
        raise ValueError("minimum_gain must be a positive finite number")
    if experiment["better"] not in ("higher", "lower"):
        raise ValueError("better must be higher or lower")
    if "pilot_adapter" in value:
        validate_pilot_candidate(brief["payload"], value)
        value = {**value, "pilot_protocol": pilot_protocol()}
    return publish(run, "candidate", brief["id"], value)


def record_audit(run, value):
    history = read_run(run, STAGES)
    if tuple(history) != ("brief", "candidate"):
        raise ValueError("A recorded candidate and no prior audit are required")
    candidate = history["candidate"]
    fields = ("candidate_id", "checks")
    if "control_review" in value:
        fields += ("control_review",)
        control = value["control_review"]
        require_keys(control, ("baseline_operation", "negative_operation", "disabled_mechanism",
                               "status", "correction"))
        for field in ("baseline_operation", "negative_operation", "disabled_mechanism"):
            require_text(control[field], field)
        if control["status"] not in ("valid", "invalid", "uncertain") or not isinstance(control["correction"], str):
            raise ValueError("Invalid control review")
        if control["status"] != "valid" and value["checks"]["falsifiability"]["status"] == "pass":
            raise ValueError("An unresolved control review cannot pass falsifiability")
    require_keys(value, fields)
    if value["candidate_id"] != candidate["id"]:
        raise ValueError("Audit belongs to a different candidate version")
    require_keys(value["checks"], CHECKS)
    for name, check in value["checks"].items():
        fields = ("status", "basis", "issues") if "issues" in check else ("status", "basis")
        require_keys(check, fields)
        if check["status"] not in ("pass", "uncertain", "fail"):
            raise ValueError(f"Invalid review status for {name}")
        require_text(check["basis"], f"{name} basis")
        issues = check.get("issues", [])
        if not isinstance(issues, list) or len(issues) > 8:
            raise ValueError("Review issues must be a list of at most eight items")
        if check["status"] == "pass" and issues:
            raise ValueError("A check with unresolved issues cannot pass")
        for issue in issues:
            require_keys(issue, ("field", "problem", "correction"))
            if issue["field"] not in ISSUE_FIELDS:
                raise ValueError("Unknown review issue field")
            require_text(issue["problem"], "problem")
            require_text(issue["correction"], "correction")
    return publish(run, "audit", candidate["id"], value)


def decision(history):
    if "candidate" not in history:
        return "awaiting_candidate", ["等待提交单一提案"]
    if "audit" not in history:
        return "awaiting_review", ["等待独立上下文审查"]
    brief = history["brief"]["payload"]
    candidate = history["candidate"]["payload"]
    audit = history["audit"]["payload"]["checks"]
    issues = [f"{key} · {check['status']}" for key, check in audit.items() if check["status"] != "pass"]
    if candidate.get("design_version") == 2:
        issues.extend(row["problem"] for row in design_issues(candidate))
    by_source = {row["id"]: row for row in brief["sources"]}
    closest = candidate["closest_source_id"]
    closest_comparison = next(
        (row for row in candidate["comparisons"] if row["source_id"] == closest), None
    )
    if closest_comparison is None or by_source[closest]["scope"] not in ("method", "full_text"):
        issues.append("缺少最接近工作的具体方法证据")
    if closest_comparison is not None and closest_comparison["relationship"] != "distinct":
        issues.append("最接近工作的方法差异尚未确立")
    if any(row["relationship"] == "same_mechanism" for row in candidate["comparisons"]):
        issues.append("提案记录了核心机制重合的工作")
    if issues:
        return "needs_revision", issues
    if "pilot" in history:
        pilot = history["pilot"]["payload"]
        return ("pilot_supports_claim" if not pilot["failures"] else "pilot_does_not_support_claim",
                pilot["failures"])
    return "ready_for_pilot", []


def validate_pilot_candidate(brief, candidate):
    if candidate["pilot_adapter"] != "tsk_overlap":
        raise ValueError("Unknown pilot adapter")
    case = read_json(TSK_EXAMPLE / "case.json")
    proposal = read_json(TSK_EXAMPLE / "proposal.json")
    if brief["question"] != case["question"] or any(
        candidate[key] != proposal[key] for key in ("hypothesis", "mechanism")
    ):
        raise ValueError("This adapter only runs the supplied TSK demonstration question and mechanism")
    test = candidate["experiment"]
    if (candidate["simple_baseline"], candidate["closest_baseline"], test["metric"],
        test["unit"], test["better"], test["negative_control"], test["evaluation_data"]) != (
        "joint_ridge", "strong_ridge", "RMSE", "RMSE", "lower", "no_drift", tsk.SPEC["scope"]
    ):
        raise ValueError("Pilot adapter expects the documented synthetic protocol and RMSE controls")


def pilot_protocol():
    return {"spec": tsk.SPEC, "adapter_sha256": hashlib.sha256(Path(tsk.__file__).read_bytes()).hexdigest()}


def run_pilot(run):
    history = read_run(run, STAGES)
    state, _ = decision(history)
    if "pilot" in history:
        return history["pilot"]
    if state != "ready_for_pilot":
        raise ValueError("Pilot requires a proposal that has passed review")
    candidate = history["candidate"]["payload"]
    if "pilot_adapter" not in candidate:
        raise ValueError("No pilot adapter is bound to this proposal. Use report to export the plan.")
    validate_pilot_candidate(history["brief"]["payload"], candidate)
    if candidate.get("pilot_protocol") != pilot_protocol():
        raise ValueError("The experiment protocol changed after submission. Start a new reviewed run.")
    evaluation = tsk.run(tsk.SPEC)
    selected = evaluation["frozen_candidate"]
    summary = evaluation["heldout"]["mean_seed_rmse"][tsk.PRIMARY]
    minimum_gain = candidate["experiment"]["minimum_gain"]
    baselines = ("joint_ridge", "strong_ridge")
    gains = {method: summary[method] - summary[selected] for method in baselines}
    failures = [f"相对 {method} 的主情景 RMSE 改善未达到 {minimum_gain}。" for method in baselines
                if gains[method] < minimum_gain]
    if not evaluation["experiment_gate_passed"]:
        failures.append("未通过 Research Loop 的固定实验门槛。")
    return publish(run, "pilot", history["audit"]["id"], {
        "adapter": candidate["pilot_adapter"],
        "protocol": candidate["pilot_protocol"],
        "primary_scenario": tsk.PRIMARY,
        "gains_vs_controls": gains,
        "failures": failures,
        "evaluation": evaluation,
    })


def describe_history(history):
    if not history:
        raise ValueError("No prepared brief")
    state, reasons = decision(history)
    result = {"state": state, "reasons": reasons,
              "versions": {name: row["id"] for name, row in history.items()}}
    if "candidate" in history:
        experiment = history["candidate"]["payload"]["experiment"]
        delta = "候选分数 − 对照分数" if experiment["better"] == "higher" else "对照分数 − 候选分数"
        result["falsification_rule"] = (
            f"在预设评估数据上，任一对照的{experiment['metric']}差值"
            f"（{delta}）小于 {experiment['minimum_gain']} {experiment['unit']}，"
            "则预设收益主张未获支持。负对照异常也需要解释。"
        )
    if "pilot" in history:
        pilot = history["pilot"]["payload"]
        result["pilot"] = {"scope": pilot["evaluation"]["scope"],
                           "candidate": pilot["evaluation"]["frozen_candidate"],
                           "primary_scenario": pilot["primary_scenario"],
                           "gains_vs_controls": pilot["gains_vs_controls"]}
    return result


def describe(run):
    return describe_history(read_run(run, STAGES))


def report(run):
    history = read_run(run, STAGES)
    summary = describe_history(history)
    brief = history["brief"]["payload"]
    state = summary["state"]
    lines = ["# 研究提案结果报告", "", f"**结论** {RESULT_TITLES[state]}", "",
             f"**研究问题** {brief['question']}", "", f"**资源约束** {brief['constraints']}"]
    if summary["reasons"]:
        lines += ["", "## 判断依据", "", *(f"- {reason}" for reason in summary["reasons"])]
    if "candidate" in history:
        candidate = history["candidate"]["payload"]
        test = candidate["experiment"]
        lines += ["", "## 提案", "", candidate["hypothesis"], "", candidate["mechanism"],
                  "", "## 小试计划", "",
                  f"- 简单基线：{candidate['simple_baseline']}",
                  f"- 最接近的对照：{candidate['closest_baseline']}",
                  f"- 评估数据：{test['evaluation_data']}",
                  f"- 公平条件：{test['matched_conditions']}",
                  f"- 负对照：{test['negative_control']}。预期：{test['expected_control_behavior']}",
                  "", "**证伪条件** " + summary["falsification_rule"]]
        for control in test.get("controls", []):
            lines += ["", f"**{control['role']}** {control['method']}",
                      f"- 改变因素　{control['changed_factor']}",
                      f"- 保持条件　{control['held_constant']}",
                      f"- 预期观察　{control['expected']}"]
        sources = {row["id"]: row for row in brief["sources"]}
        if candidate["comparisons"]:
            lines += ["", "## 文献依据", ""]
            for row in candidate["comparisons"]:
                source = sources[row["source_id"]]
                lines += [f"- {source['title']}（{source['scope']}，{source['locator']}）",
                          f"  来源：{source['reference']}", f"  摘录：{row['quote']}",
                          f"  比较：{row['reason']}"]
    if "audit" in history:
        lines += ["", "## 审查记录", ""]
        for name, check in history["audit"]["payload"]["checks"].items():
            lines.append(f"- {name}（{check['status']}）：{check['basis']}")
            for issue in check.get("issues", []):
                lines.append(f"  - {issue['field']}　{issue['problem']} 修改要求　{issue['correction']}")
        control = history["audit"]["payload"].get("control_review")
        if control:
            lines += ["", "**负对照复核**",
                      f"- 基线操作　{control['baseline_operation']}",
                      f"- 负对照操作　{control['negative_operation']}",
                      f"- 使其失效的机制　{control['disabled_mechanism']}",
                      f"- 判断　{control['status']}"]
    if "pilot" in history:
        pilot = history["pilot"]["payload"]
        data = pilot["evaluation"]
        method = data["frozen_candidate"]
        lines += ["", "## 实测结果", "",
                  f"协议：{data['scope']}。验证种子选择候选 {method}，保留种子用于最终对照。",
                  "", "| 保留情景 | 候选 RMSE | 联合岭 RMSE | 强岭 RMSE |", "| --- | ---: | ---: | ---: |"]
        for scenario, scores in data["heldout"]["mean_seed_rmse"].items():
            lines.append(f"| {scenario} | {scores[method]:.6f} | {scores['joint_ridge']:.6f} | {scores['strong_ridge']:.6f} |")
        lines += ["", "主情景改善以对照 RMSE 减候选 RMSE 计算。"]
        lines += [f"- 相对 {name}：{gain:+.6f} RMSE。" for name, gain in pilot["gains_vs_controls"].items()]
        for label, gate in [("验证", data["validation"]["gates"][method]), ("保留测试", data["heldout"]["gate"])]:
            reasons = "、".join(gate["failures"]) if gate["failures"] else "通过"
            lines.append(f"- {label}门槛：{reasons}。")
        lines += ["", "本次结论适用于固定合成协议。真实数据表现与研究新颖性仍待核查。"]
    else:
        lines += ["", "## 实验进度", "", "尚未运行小试。上面的判断来自材料和提案审查。"]
        if state == "ready_for_pilot":
            candidate = history["candidate"]["payload"]
            lines.append("按小试计划准备数据和运行对照。" if "pilot_adapter" not in candidate
                         else "已绑定实验适配器，可以运行 pilot 取得实测结果。")
    lines += ["", "## 版本", "", *(f"- {name}：{identity}" for name, identity in summary["versions"].items()), ""]
    path = run / f"RESULT-{list(summary['versions'].values())[-1][:12]}.md"
    body = "\n".join(lines)
    try:
        put_new(path, body)
    except FileExistsError:
        if path.read_text(encoding="utf-8") != body:
            raise ValueError("Existing report does not match its receipts") from None
    return {**summary, "report": str(path.resolve())}


def finish(run):
    history = read_run(run, STAGES)
    state, _ = decision(history)
    if state == "ready_for_pilot" and "pilot_adapter" in history["candidate"]["payload"]:
        run_pilot(run)
    return report(run)


def main(argv=None, *, prog=None):
    parser = argparse.ArgumentParser(prog=prog, description="Review a research proposal and deliver its pilot report")
    commands = parser.add_subparsers(dest="command", required=True)
    actions = {"prepare": prepare, "candidate": record_candidate, "audit": record_audit}
    for name in (*actions, "status", "pilot", "report", "finish"):
        command = commands.add_parser(name)
        command.add_argument("--run", type=Path, required=True)
        if name in actions:
            command.add_argument("--input", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command in actions:
            actions[args.command](args.run, read_json(args.input))
        if args.command == "finish":
            result = finish(args.run)
        elif args.command == "pilot":
            run_pilot(args.run)
            result = report(args.run)
        elif args.command == "report":
            result = report(args.run)
        else:
            result = describe(args.run)
    except (OSError, ValueError, KeyError, TypeError, OverflowError) as error:
        parser.exit(2, f"research-proposal: {error}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
