"""GEPA 只优化证据选择提示词；不修改模型权重，不自动替换已发布策略。"""
import hashlib
import time
from pathlib import Path
import numpy as np
import gepa
from gepa.core.adapter import EvaluationBatch
from .config import ROOT, read_json, write_json
from .evaluation import covers, validate_cases
from .model import ModelClient
from .retrieval import Retriever
from .workflow import prompt, model_packet


class SelectionAdapter:
    propose_new_texts = None

    def __init__(self, retriever, client):
        self.retriever, self.client = retriever, client

    def prepare(self, case):
        value = self.retriever.search(case["question"], top_k=8, doc_ids=[case["paper_id"]],
            lexical_query=case.get("lexical_query"), scope=case.get("scope", "full"))
        return {**case, "chunks": [{**row, "candidate_id": f"C{i + 1}"} for i, row in enumerate(value["results"])]}

    def evaluate(self, batch, candidate, capture_traces=False):
        outputs, scores, traces = [], [], []
        for case in batch:
            allowed = {row["candidate_id"]: row for row in case["chunks"]}
            try:
                value = self.client.json(candidate["selection_prompt"],
                    {"questions": [case["question"]], **model_packet({"scope": case.get("scope", "full"), "chunks": case["chunks"]})}, "gepa_selector")
                ids = value.get("chunk_ids")
                if not isinstance(ids, list) or any(not isinstance(i, str) or i not in allowed for i in ids) or len(ids) > 8:
                    raise ValueError("返回了无效的片段编号")
                selected = [allowed[i] for i in dict.fromkeys(ids)]
                spans = case["evidence_spans"]
                if spans:
                    recall = sum(any(covers(row, span) for row in selected) for span in spans) / len(spans)
                    precision = sum(any(covers(row, span) for span in spans) for row in selected) / max(len(selected), 1)
                    score = 0.9 * recall + 0.1 * precision
                else:
                    score = float(not selected)
                feedback = "根据原页证据区间计算选择召回和精度。"
            except (ValueError, KeyError, TypeError) as error:
                value, score, feedback = {}, 0.0, str(error)
            outputs.append(value)
            scores.append(score)
            gold_ids = [identity for identity, row in allowed.items() if any(covers(row, span) for span in case["evidence_spans"])]
            traces.append({"Inputs": {"question": case["question"],
                "chunks": [{"chunk_id": row["candidate_id"], "raw_text": row["raw_text"]} for row in case["chunks"]]},
                "Generated Outputs": value, "Feedback": feedback + " 正确证据候选编号：" + str(gold_ids),
                "score": score})
        return EvaluationBatch(outputs=outputs, scores=scores, trajectories=traces if capture_traces else None)

    def make_reflective_dataset(self, candidate, eval_batch, components_to_update):
        return {component: eval_batch.trajectories for component in components_to_update}


def optimize_selection(budget=12, output=None):
    if not 8 <= budget <= 32:
        raise ValueError("演示优化预算必须位于 8 至 32 次样本评测")
    output = Path(output or ROOT / "output/gepa")
    output.mkdir(parents=True, exist_ok=True)
    cases = read_json(ROOT / "evals/cases.json")["cases"]
    validate_cases(cases)
    client = ModelClient(max_calls=budget * 2 + 8)
    adapter = SelectionAdapter(Retriever(), client)
    groups = {}
    for split in ("train", "validation", "test"):
        choices = [case for case in cases if case["split"] == split]
        balanced = list({case["paper_id"]: case for case in reversed(choices)}.values())
        for case in choices:
            if case not in balanced:
                balanced.append(case)
        groups[split] = [adapter.prepare(case) for case in balanced[:2]]
    seed = {"selection_prompt": prompt("select")}
    resumed = (output / "engine").exists() and any((output / "engine").iterdir())
    started = time.monotonic()
    reflection_count = 0
    def reflect(value):
        nonlocal reflection_count
        reflection_count += 1
        messages = [{"role": "user", "content": value}] if isinstance(value, str) else value
        return client.text(messages, "gepa_reflection", json_mode=False)
    def stop(state):
        return len(client.calls) >= budget + 4 or reflection_count >= 3 or time.monotonic() - started > 180
    result = gepa.optimize(seed_candidate=seed, trainset=groups["train"], valset=groups["validation"],
        adapter=adapter, reflection_lm=reflect, stop_callbacks=[stop],
        reflection_minibatch_size=1, max_metric_calls=budget, skip_perfect_score=False,
        run_dir=str(output / "engine"), seed=42, display_progress_bar=False, raise_on_exception=True)
    # 只在优化结束后评估保留测试论文。保留测试不参与反思、选择或上线。
    baseline = adapter.evaluate(groups["test"], seed)
    selected = adapter.evaluate(groups["test"], result.best_candidate)
    record = {"best_candidate": result.best_candidate, "best_idx": result.best_idx,
        "validation_scores": result.val_aggregate_scores, "candidate_count": len(result.candidates),
        "metric_calls": result.total_metric_calls,
        "resumed_existing_engine_directory": resumed,
        "model_usage_scope": "only API calls made in this invocation; earlier failed debugging calls are not included",
        "reflection_calls": reflection_count,
        "heldout_baseline_score": float(np.mean(baseline.scores)),
        "heldout_candidate_score": float(np.mean(selected.scores)),
        "heldout_used_in_optimization": False, "promoted_to_default": False,
        "paper_splits": {split: sorted({case["paper_id"] for case in rows}) for split, rows in groups.items()},
        "task_model": client.config["model"], "model_calls": client.calls,
        "seed_prompt_sha256": hashlib.sha256(seed["selection_prompt"].encode()).hexdigest(),
        "limitations": ["只在极小演示集上试跑，不能声称泛化提升或自主持续进化。",
            "验证集参与 GEPA 的候选选择；保留测试只在优化结束后比较一次。",
            "主任务与反思使用同一模型，评分规则只检查证据选择，不证明最终回答正确。"]}
    write_json(output / "result.json", record)
    write_json(output / "candidates.json", result.to_dict())
    (output / "candidate_prompt.txt").write_text(result.best_candidate["selection_prompt"], encoding="utf-8")
    return record
