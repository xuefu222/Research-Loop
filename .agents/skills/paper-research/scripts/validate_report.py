import argparse
import json
from pathlib import Path


# 第一块：检查一组记录中的字段
def check_items(items, fields, label):
    errors = []

    for index, item in enumerate(items):
        position = f"{label}[{index}]"

        if not isinstance(item, dict):
            errors.append(f"{position} 必须是一条对象记录")
            continue

        for field, expected_type in fields.items():
            if field not in item:
                errors.append(f"{position} 缺少字段：{field}")
                continue

            value = item[field]

            if not isinstance(value, expected_type):
                errors.append(f"{position}.{field} 类型不正确")
            elif isinstance(value, str) and not value.strip():
                errors.append(f"{position}.{field} 不能为空")

    return errors


# 第二块：检查完整报告
def validate_report(report):
    errors = []

    if not isinstance(report, dict):
        return ["JSON 顶层必须是对象"]

    required_fields = {
        "material_scope": str,
        "answers": list,
        "evidence": list,
        "sources": list,
        "limitations": list,
    }

    for field, expected_type in required_fields.items():
        if field not in report:
            errors.append(f"缺少顶层字段：{field}")
        elif not isinstance(report[field], expected_type):
            errors.append(f"顶层字段 {field} 类型不正确")

    # 先保证基本结构正确，再继续检查内部内容
    if errors:
        return errors

    if not report["material_scope"].strip():
        errors.append("material_scope 不能为空")

    if not report["answers"]:
        errors.append("answers 至少需要包含一个回答")

    errors.extend(check_items(
        report["sources"],
        {"source_id": str, "uri": str},
        "sources",
    ))

    errors.extend(check_items(
        report["evidence"],
        {
            "evidence_id": str,
            "source_id": str,
            "kind": str,
            "text": str,
            "location": str,
        },
        "evidence",
    ))

    errors.extend(check_items(
        report["answers"],
        {
            "question": str,
            "status": str,
            "answer": str,
            "evidence_ids": list,
        },
        "answers",
    ))

    if errors:
        return errors

    source_ids = [
        item["source_id"] for item in report["sources"]
    ]

    evidence_ids = [
        item["evidence_id"] for item in report["evidence"]
    ]

    if len(source_ids) != len(set(source_ids)):
        errors.append("source_id 存在重复")

    if len(evidence_ids) != len(set(evidence_ids)):
        errors.append("evidence_id 存在重复")

    for index, item in enumerate(report["evidence"]):
        if item["source_id"] not in source_ids:
            errors.append(
                f"evidence[{index}] 引用了不存在的来源："
                f"{item['source_id']}"
            )

        if item["kind"] not in ("quote", "paraphrase"):
            errors.append(
                f"evidence[{index}].kind 必须是 quote 或 paraphrase"
            )

    allowed_statuses = (
        "supported",
        "inferred",
        "insufficient",
        "conflicting",
    )

    for index, item in enumerate(report["answers"]):
        status = item["status"]
        references = item["evidence_ids"]

        if status not in allowed_statuses:
            errors.append(f"answers[{index}].status 不合法")

        if status in ("supported", "inferred", "conflicting"):
            if not references:
                errors.append(
                    f"answers[{index}] 的状态为 {status}，需要关联证据"
                )

        for reference in references:
            if not isinstance(reference, str):
                errors.append(
                    f"answers[{index}].evidence_ids 中必须是字符串"
                )
            elif reference not in evidence_ids:
                errors.append(
                    f"answers[{index}] 引用了不存在的证据：{reference}"
                )

    for index, item in enumerate(report["limitations"]):
        if not isinstance(item, str) or not item.strip():
            errors.append(
                f"limitations[{index}] 必须是非空字符串"
            )

    return errors


# 第三块：读取命令行参数和 JSON 文件
def main():
    parser = argparse.ArgumentParser(
        description="检查论文调研结果的结构和引用关系"
    )
    parser.add_argument("report", help="待检查的 JSON 文件路径")
    args = parser.parse_args()

    report_path = Path(args.report)

    try:
        text = report_path.read_text(encoding="utf-8-sig")
        report = json.loads(text)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        print(f"读取或解析失败：{error}")
        return 2

    errors = validate_report(report)

    if errors:
        print("校验失败：")

        for error in errors:
            print(f"- {error}")

        return 1

    print("校验通过：结构、状态值和引用编号符合规范。")
    return 0


# 直接运行本文件时，才执行命令行入口
if __name__ == "__main__":
    raise SystemExit(main())
