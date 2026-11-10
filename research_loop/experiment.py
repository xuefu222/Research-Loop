"""Bounded CPU experiment for evidence-aware TSK consequent adaptation."""

from time import perf_counter

import numpy as np


CONTROLS = ("static", "shared_only", "joint_ridge", "strong_ridge", "uniform_shrink", "generic_spectral")
SCENARIOS = ("overlap_shared", "overlap_contrast", "separated_shared", "no_drift")
PRIMARY = "overlap_shared"
SPEC = {
    "validation_seeds": [31, 32, 33, 34],
    "heldout_seeds": [101, 102, 103, 104, 105, 106],
    "window": 16,
    "steps": 144,
    "penalty": 0.025,
    "strengths": [0.002, 0.02, 0.15],
    "minimum_primary_gain": 0.02,
    "maximum_slice_loss": 0.02,
    "baseline": "joint_ridge",
    "scope": "synthetic_prequential",
}


def design(x, width):
    """Return shared and contrast features in an orthonormal two-rule basis."""
    z = np.column_stack((np.ones_like(x), x)) / np.sqrt(2)
    contrast = np.tanh(0.75 * x / width**2)
    return z, z * contrast[:, None]


def stream(seed, scenario, steps):
    """A known input at t and a response revealed only after prediction at t."""
    rng = np.random.default_rng(seed)
    width = 1.6 if scenario.startswith("overlap") else 0.75
    x = rng.uniform(-1.5, 1.5, size=steps)
    if scenario.startswith("overlap"):
        sparse_probe = np.arange(steps) % 9 == 8
        x[~sparse_probe] = rng.normal(0, 0.12, size=np.count_nonzero(~sparse_probe))
    shared, contrast = design(x, width)
    basis = np.column_stack((shared, contrast))
    prior = np.array([0.1, 0.7, -0.3, 0.2])
    drift = np.zeros((steps, 4))
    if scenario != "no_drift":
        columns = slice(2, 4) if scenario == "overlap_contrast" else slice(0, 2)
        drift[48:96, columns] = [0.55, -0.5]
        drift[96:, columns] = [-0.55, 0.5]
    y = np.sum(basis * (prior + drift), axis=1) + rng.normal(0, 0.16, steps)
    return shared, contrast, basis @ prior, y


def predictions(shared, contrast, prior, y, t, window, penalty, strengths):
    """Compute methods on the same window, using no target at or after t."""
    history = slice(t - window, t)
    a, b = shared[history], contrast[history]
    next_a, next_b = shared[t], contrast[t]
    residual = y[history] - prior[history]
    x = np.column_stack((a, b))
    next_x = np.concatenate((next_a, next_b))
    gram = x.T @ x
    rhs = x.T @ residual
    identity = np.eye(x.shape[1])
    strong = next_x @ np.linalg.solve(gram + 10 * penalty * identity, rhs)

    aa = a.T @ a + penalty * np.eye(a.shape[1])
    ab = a.T @ b
    shared_delta = np.linalg.solve(aa, a.T @ residual)
    transfer = np.linalg.solve(aa, ab)
    information = b.T @ b - ab.T @ transfer
    values, vectors = np.linalg.eigh(information)
    values = np.maximum(values, 0.0)
    contrast_rhs = b.T @ (residual - a @ shared_delta)
    coordinates = (vectors.T @ contrast_rhs) / (values + penalty)
    query = (next_b - next_a @ transfer) @ vectors
    shared_prediction = prior[t] + next_a @ shared_delta
    joint_adjustment = query @ coordinates

    generic_values, generic_vectors = np.linalg.eigh(gram)
    generic_values = np.maximum(generic_values, 0.0)
    generic_ridge = (generic_vectors.T @ rhs) / (generic_values + penalty)
    generic_gate = generic_values / (generic_values + 0.02)
    result = {
        "static": prior[t],
        "shared_only": shared_prediction,
        "joint_ridge": shared_prediction + joint_adjustment,
        "strong_ridge": prior[t] + strong,
        "uniform_shrink": shared_prediction + 0.5 * joint_adjustment,
        "generic_spectral": prior[t] + (next_x @ generic_vectors) @ (generic_ridge * generic_gate),
    }
    for strength in strengths:
        gate = values / (values + strength)
        result[f"contrast_gate_{strength:g}"] = shared_prediction + query @ (gate * coordinates)
    return result


def evaluate_split(seeds, spec, strengths):
    rows = []
    for scenario in SCENARIOS:
        for seed in seeds:
            start = perf_counter()
            shared, contrast, prior, y = stream(seed, scenario, spec["steps"])
            squared_errors = {}
            for t in range(spec["window"], len(y)):
                methods = predictions(shared, contrast, prior, y, t, spec["window"], spec["penalty"], strengths)
                for method, prediction in methods.items():
                    squared_errors.setdefault(method, []).append((float(prediction) - float(y[t])) ** 2)
            rows.append({
                "scenario": scenario,
                "seed": seed,
                "n_predictions": len(y) - spec["window"],
                "rmse": {name: float(np.sqrt(np.mean(errors))) for name, errors in squared_errors.items()},
                "elapsed_seconds_all_methods": round(perf_counter() - start, 6),
            })
    return rows


def summarize(rows):
    return {
        scenario: {
            method: float(np.mean([row["rmse"][method] for row in rows if row["scenario"] == scenario]))
            for method in rows[0]["rmse"]
        }
        for scenario in SCENARIOS
    }


def gate(summary, candidate, spec):
    baseline = spec["baseline"]
    gains = {name: 1 - methods[candidate] / methods[baseline] for name, methods in summary.items()}
    failures = []
    if gains[PRIMARY] < spec["minimum_primary_gain"]:
        failures.append("primary_gain_below_threshold")
    for scenario in SCENARIOS:
        if gains[scenario] < -spec["maximum_slice_loss"]:
            failures.append(f"regression:{scenario}")
    best_control = min(CONTROLS, key=summary[PRIMARY].get)
    if summary[PRIMARY][candidate] >= summary[PRIMARY][best_control]:
        failures.append("did_not_beat_strongest_primary_control")
    return {"passes": not failures, "failures": failures, "gains_vs_joint_ridge": gains,
            "best_primary_control": best_control}


def run(spec):
    start = perf_counter()
    strengths = spec["strengths"]
    validation = evaluate_split(spec["validation_seeds"], spec, strengths)
    val_summary = summarize(validation)
    candidates = {f"contrast_gate_{value:g}": value for value in strengths}
    val_gates = {name: gate(val_summary, name, spec) for name in candidates}
    eligible = [name for name, status in val_gates.items() if status["passes"]]
    # If validation rejects all candidates, freeze the best primary candidate only
    # for diagnostic reporting. The holdout cannot overturn the validation veto.
    selected = min(eligible or list(candidates), key=lambda name: (val_summary[PRIMARY][name], name))
    holdout = evaluate_split(spec["heldout_seeds"], spec, [candidates[selected]])
    heldout_summary = summarize(holdout)
    heldout_gate = gate(heldout_summary, selected, spec)
    accepted = val_gates[selected]["passes"] and heldout_gate["passes"]
    return {
        "scope": spec["scope"],
        "frozen_candidate": selected,
        "selection_used_heldout": False,
        "validation": {"rows": validation, "mean_seed_rmse": val_summary, "gates": val_gates},
        "heldout": {"rows": holdout, "mean_seed_rmse": heldout_summary, "gate": heldout_gate},
        "experiment_gate_passed": accepted,
        "recommended_policy": selected if accepted else spec["baseline"],
        "elapsed_seconds": round(perf_counter() - start, 6),
    }
