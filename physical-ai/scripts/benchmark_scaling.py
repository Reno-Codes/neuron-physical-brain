"""Physical AI - Experiment 9: scaling benchmark of the compiled SPICE MLP.

Frozen random 2-layer networks (ReLU hidden, linear output) are compiled
with Matter Compiler v1. Weights are never edited. Only G_SCALE may change.

Circuits are written under circuits/scaling/. Experiment 6/8 XOR netlists
are not touched.
"""

from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from compile_xor import (
    CLASS_THRESHOLD,
    PROJECT_ROOT,
    apply_resistor_values,
    find_ngspice,
    generate_circuit,
    run_ngspice,
)
from matter_compiler import (
    G_SCALE_GRID,
    CompileConfig,
    physical_cost,
    resistor_values_from_catalog,
    total_conductance,
)
from test_robustness import extract_all, sample_resistor_values


SEED = 9
N_TEST = 100
N_SEARCH = 20
N_ROBUST_TRIALS = 100
N_ROBUST_INPUTS = 8
ROBUST_TOLERANCE = 0.05
MATCH_TOL = 1.0e-3
RAIL = 15.0

CIRCUIT_DIR = PROJECT_ROOT / "circuits" / "scaling"
MODEL_DIR = PROJECT_ROOT / "models" / "scaling"
RESULTS_DIR = PROJECT_ROOT / "results"
REPORT_PATH = RESULTS_DIR / "scaling_report.json"

NETWORKS = (
    {"id": "A", "n_in": 2, "n_hidden": 4, "n_out": 1},
    {"id": "B", "n_in": 2, "n_hidden": 8, "n_out": 1},
    {"id": "C", "n_in": 2, "n_hidden": 16, "n_out": 1},
    {"id": "D", "n_in": 4, "n_hidden": 8, "n_out": 4},
    {"id": "E", "n_in": 8, "n_hidden": 16, "n_out": 8},
    {"id": "F", "n_in": 16, "n_hidden": 32, "n_out": 16},
)


def network_label(spec: dict) -> str:
    return f"{spec['id']} {spec['n_in']}->{spec['n_hidden']}->{spec['n_out']}"


def make_rng(*parts: int | str) -> np.random.Generator:
    payload = [SEED]
    for part in parts:
        if isinstance(part, str):
            payload.append(sum(ord(ch) * (i + 1) for i, ch in enumerate(part)))
        else:
            payload.append(int(part))
    return np.random.default_rng(payload)


def generate_weights(n_in: int, n_hidden: int, n_out: int) -> dict[str, np.ndarray]:
    """Deterministic He-style init. No per-weight editing."""
    rng = make_rng("weights", n_in, n_hidden, n_out)
    w1 = rng.normal(0.0, math.sqrt(2.0 / n_in), size=(n_hidden, n_in))
    b1 = rng.normal(0.0, 0.05, size=(n_hidden,))
    w2 = rng.normal(0.0, math.sqrt(2.0 / n_hidden), size=(n_out, n_hidden))
    b2 = rng.normal(0.0, 0.05, size=(n_out,))
    return {"W1": w1, "b1": b1, "W2": w2, "b2": b2}


def generate_inputs(n_in: int, n_vectors: int, tag: str) -> np.ndarray:
    rng = make_rng("inputs", tag, n_in, n_vectors)
    return rng.uniform(-1.0, 1.0, size=(n_vectors, n_in))


def software_forward_batch(
    x: np.ndarray,
    w1: np.ndarray,
    b1: np.ndarray,
    w2: np.ndarray,
    b2: np.ndarray,
) -> np.ndarray:
    x = np.atleast_2d(np.asarray(x, dtype=float))
    hidden = np.maximum(0.0, x @ w1.T + b1)
    return hidden @ w2.T + b2


def classification_labels(outputs: np.ndarray) -> np.ndarray:
    y = np.atleast_2d(np.asarray(outputs, dtype=float))
    if y.shape[1] == 1:
        return (y[:, 0] >= CLASS_THRESHOLD).astype(int)
    return np.argmax(y, axis=1)


def count_spice_elements(netlist: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    total = 0
    for raw in netlist.splitlines():
        line = raw.strip()
        if not line or line.startswith("*") or line.startswith("."):
            continue
        kind = line[0].upper()
        if kind not in "RVFHBDE":
            continue
        counts[kind] = counts.get(kind, 0) + 1
        total += 1
    counts["total"] = total
    return counts


def path_counts(catalog: list[dict]) -> tuple[int, int]:
    n_pos = 0
    n_neg = 0
    for item in catalog:
        comment = str(item.get("comment", ""))
        if comment.endswith("w+") or comment.endswith("b+"):
            n_pos += 1
        elif comment.endswith("w-") or comment.endswith("b-"):
            n_neg += 1
    return n_pos, n_neg


def compile_network(
    spec: dict,
    weights: dict[str, np.ndarray],
    config: CompileConfig,
) -> tuple[str | None, list[dict], str | None]:
    n_in = spec["n_in"]
    dummy = np.zeros(n_in, dtype=float)
    title = (
        f"* Physical AI - Experiment 9: scaling network {network_label(spec)}\n"
        f"* Frozen random weights (seed {SEED}). Weights were not edited.\n"
        f"* Matter Compiler v1 mapping: {config.label()}"
    )
    netlist, catalog = generate_circuit(
        dummy,
        weights["W1"],
        weights["b1"],
        weights["W2"],
        weights["b2"],
        g_scale=config.g_scale,
        control="outputs",
        title=title,
    )
    values, compiled, reason = resistor_values_from_catalog(catalog, config)
    if reason is not None:
        return None, compiled, reason
    return apply_resistor_values(netlist, values), compiled, None


def batch_control(inputs: np.ndarray, n_out: int) -> str:
    lines = [".control", "set numdgt=15"]
    for x in inputs:
        for i, xi in enumerate(np.atleast_1d(x), start=1):
            lines.append(f"alter Vin{i} DC {float(xi):.15g}")
        lines.append("op")
        for k in range(1, n_out + 1):
            lines.append(f"print v(o{k}lin)")
    lines.extend([".endc", "", ".end", ""])
    return "\n".join(lines)


def parse_physical_outputs(text: str, n_vectors: int, n_out: int) -> np.ndarray:
    columns = []
    for k in range(1, n_out + 1):
        values = extract_all(text, f"v(o{k}lin)")
        if len(values) != n_vectors:
            raise RuntimeError(
                f"expected {n_vectors} v(o{k}lin) values, got {len(values)}"
            )
        columns.append(values)
    return np.column_stack(columns)


def detect_spice_failure(result) -> str | None:
    text = f"{result.stdout or ''}\n{result.stderr or ''}"
    lowered = text.lower()
    if result.returncode == 124 or "timed out" in lowered:
        return "ngspice timeout / possible non-convergence"
    if result.returncode != 0:
        return f"ngspice exit {result.returncode}"
    if "without convergence" in lowered or "doanalyses" in lowered and "failed" in lowered:
        return "ngspice convergence failure"
    if "fatal" in lowered and "error" in lowered:
        return "ngspice fatal error"
    return None


def simulate_batch(
    ngspice: Path,
    netlist: str,
    inputs: np.ndarray,
    n_out: int,
    dest: Path,
    r_values: dict[str, float] | None = None,
    timeout: float | None = None,
) -> tuple[np.ndarray | None, float, str | None, str]:
    head, sep, _tail = netlist.partition(".control")
    if not sep:
        return None, 0.0, "generated netlist has no .control section", ""
    body = apply_resistor_values(head, r_values or {})
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(body.rstrip() + "\n" + batch_control(inputs, n_out), encoding="utf-8")
    t0 = time.perf_counter()
    result = run_ngspice(ngspice, dest, timeout=timeout)
    runtime = time.perf_counter() - t0
    text = f"{result.stdout or ''}\n{result.stderr or ''}"
    fail = detect_spice_failure(result)
    if fail:
        return None, runtime, fail, text[-4000:]
    try:
        physical = parse_physical_outputs(text, len(inputs), n_out)
    except RuntimeError as exc:
        return None, runtime, str(exc), text[-4000:]
    return physical, runtime, None, text[-2000:]


def error_stats(physical: np.ndarray, software: np.ndarray) -> dict[str, float]:
    delta = physical - software
    return {
        "mae": float(np.mean(np.abs(delta))),
        "rms": float(np.sqrt(np.mean(delta**2))),
        "max_abs_error": float(np.max(np.abs(delta))),
    }


def loglog_fit(x, y) -> dict | None:
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    mask = (x > 0) & (y > 0) & np.isfinite(x) & np.isfinite(y)
    if int(np.sum(mask)) < 2:
        return None
    slope, intercept = np.polyfit(np.log(x[mask]), np.log(y[mask]), 1)
    pred = np.exp(intercept) * np.power(x[mask], slope)
    ss_res = float(np.sum((y[mask] - pred) ** 2))
    ss_tot = float(np.sum((y[mask] - np.mean(y[mask])) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    return {
        "form": "y = A * x^b  (log-log least squares on measured points)",
        "exponent_b": float(slope),
        "prefactor_A": float(math.exp(intercept)),
        "r_squared": r2,
        "n_points": int(np.sum(mask)),
        "kind": "measured_fit",
    }


def choose_mapping(
    ngspice: Path,
    spec: dict,
    weights: dict[str, np.ndarray],
    search_x: np.ndarray,
) -> dict:
    software = software_forward_batch(
        search_x, weights["W1"], weights["b1"], weights["W2"], weights["b2"]
    )
    expected = classification_labels(software)
    dest = CIRCUIT_DIR / f"{spec['id']}_search.cir"
    records = []
    best = None
    for g_scale in G_SCALE_GRID:
        config = CompileConfig(g_scale=g_scale)
        print(f"    search G_SCALE={g_scale:.3g}", flush=True)
        netlist, catalog, reason = compile_network(spec, weights, config)
        rec = {
            "g_scale": g_scale,
            "label": config.label(),
            "rejected": reason is not None,
            "reject_reason": reason,
            "n_resistors": len(catalog),
            "spice_error": None,
            "spice_runtime_s": None,
        }
        if netlist is None:
            rec["score"] = physical_cost(0.0, len(search_x), 0.0, 0.0, 0.0, 0, True)
            records.append(rec)
            continue
        physical, runtime, spice_err, _log = simulate_batch(
            ngspice, netlist, search_x, spec["n_out"], dest
        )
        rec["spice_runtime_s"] = runtime
        if spice_err or physical is None:
            rec["spice_error"] = spice_err or "no physical outputs"
            rec["score"] = physical_cost(0.0, len(search_x), 0.0, 0.0, 0.0, 0, True)
            records.append(rec)
            print(f"      failed: {rec['spice_error']}", flush=True)
            continue
        stats = error_stats(physical, software)
        pred = classification_labels(physical)
        n_fail = int(np.sum(pred != expected))
        acc = float(1.0 - n_fail / len(expected))
        g_total = total_conductance(catalog)
        score = physical_cost(
            acc, n_fail, stats["mae"], stats["max_abs_error"],
            g_total, len(catalog), rejected=False,
        )
        rec.update(
            {
                "mae": stats["mae"],
                "rms": stats["rms"],
                "max_abs_error": stats["max_abs_error"],
                "accuracy": acc,
                "n_failures": n_fail,
                "total_conductance": g_total,
                "score": score,
            }
        )
        records.append(rec)
        print(
            f"      MAE={stats['mae']:.4e} max={stats['max_abs_error']:.4e} "
            f"acc={acc:.3f} SigmaG={g_total:.4e} score={score:.4g} "
            f"t={runtime:.2f}s",
            flush=True,
        )
        if best is None or score < best["score"]:
            best = {**rec, "config": config, "catalog": catalog, "netlist": netlist}
    if best is None:
        best = {
            "config": CompileConfig(g_scale=G_SCALE_GRID[0]),
            "catalog": [],
            "netlist": None,
            "score": physical_cost(0.0, len(search_x), 0.0, 0.0, 0.0, 0, True),
            "spice_error": "all G_SCALE candidates failed",
            "g_scale": G_SCALE_GRID[0],
        }
    return {"best": best, "candidates": records}


def run_robustness(
    ngspice: Path,
    spec: dict,
    netlist: str,
    catalog: list[dict],
    subset_x: np.ndarray,
    software: np.ndarray,
    n_trials: int,
) -> dict:
    dest = CIRCUIT_DIR / f"{spec['id']}_robust.cir"
    rng = make_rng("robust", spec["id"])
    expected = classification_labels(software)
    maes = []
    maxes = []
    accs = []
    failures = 0
    t0 = time.perf_counter()
    for trial in range(n_trials):
        values = sample_resistor_values(catalog, ROBUST_TOLERANCE, rng)
        physical, _runtime, spice_err, _log = simulate_batch(
            ngspice, netlist, subset_x, spec["n_out"], dest, r_values=values
        )
        if spice_err or physical is None:
            failures += 1
            continue
        stats = error_stats(physical, software)
        pred = classification_labels(physical)
        maes.append(stats["mae"])
        maxes.append(stats["max_abs_error"])
        accs.append(float(np.mean(pred == expected)))
        if (trial + 1) % 25 == 0 or trial == 0:
            print(
                f"      robustness trial {trial + 1}/{n_trials} "
                f"MAE={stats['mae']:.4e}",
                flush=True,
            )
    runtime = time.perf_counter() - t0
    if not maes:
        return {
            "tolerance": ROBUST_TOLERANCE,
            "n_trials": n_trials,
            "n_inputs": int(len(subset_x)),
            "n_spice_failures": failures,
            "spice_runtime_s": runtime,
            "failed": True,
        }
    return {
        "tolerance": ROBUST_TOLERANCE,
        "n_trials": n_trials,
        "n_inputs": int(len(subset_x)),
        "n_spice_failures": failures,
        "spice_runtime_s": runtime,
        "failed": False,
        "mae_mean": float(np.mean(maes)),
        "mae_max": float(np.max(maes)),
        "max_abs_error_mean": float(np.mean(maxes)),
        "max_abs_error_worst": float(np.max(maxes)),
        "accuracy_mean": float(np.mean(accs)),
        "accuracy_min": float(np.min(accs)),
    }


def adaptive_counts(spec: dict) -> dict[str, int]:
    """Requested workload. Counts stay full unless a later run has to shrink them."""
    n_test = N_TEST
    return {
        "n_test": n_test,
        "n_search": min(N_SEARCH, n_test),
        "n_robust_trials": N_ROBUST_TRIALS,
        "n_robust_inputs": min(N_ROBUST_INPUTS, n_test),
        "reduced": False,
    }


def evaluate_network(ngspice: Path, spec: dict) -> dict:
    counts = adaptive_counts(spec)
    weights = generate_weights(spec["n_in"], spec["n_hidden"], spec["n_out"])
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    model_path = MODEL_DIR / f"{spec['id']}.npz"
    np.savez(model_path, **weights, seed=SEED, **spec)

    x_all = generate_inputs(spec["n_in"], counts["n_test"], spec["id"])
    x_search = x_all[: counts["n_search"]]
    x_robust = x_all[: counts["n_robust_inputs"]]
    y_sw_all = software_forward_batch(
        x_all, weights["W1"], weights["b1"], weights["W2"], weights["b2"]
    )
    y_sw_rob = software_forward_batch(
        x_robust, weights["W1"], weights["b1"], weights["W2"], weights["b2"]
    )
    software_abs_max = float(np.max(np.abs(y_sw_all)))
    hidden_abs_max = float(
        np.max(np.abs(np.maximum(0.0, x_all @ weights["W1"].T + weights["b1"])))
    )

    n_weights = spec["n_in"] * spec["n_hidden"] + spec["n_hidden"] * spec["n_out"]
    n_biases = spec["n_hidden"] + spec["n_out"]
    n_neurons = spec["n_hidden"] + spec["n_out"]

    print(f"\n=== {network_label(spec)} ===", flush=True)
    print(
        f"  neurons={n_neurons} weights={n_weights} biases={n_biases} "
        f"test={counts['n_test']} search={counts['n_search']}",
        flush=True,
    )

    search = choose_mapping(ngspice, spec, weights, x_search)
    best = search["best"]
    config: CompileConfig = best["config"]
    catalog = best.get("catalog") or []
    netlist = best.get("netlist")

    record = {
        "id": spec["id"],
        "label": network_label(spec),
        "n_in": spec["n_in"],
        "n_hidden": spec["n_hidden"],
        "n_out": spec["n_out"],
        "n_neurons": n_neurons,
        "n_weights": n_weights,
        "n_biases": n_biases,
        "n_test": counts["n_test"],
        "n_search": counts["n_search"],
        "workload_reduced": counts["reduced"],
        "workload_note": (
            "test/robustness counts reduced for runtime, network was not skipped"
            if counts["reduced"]
            else "full requested workload"
        ),
        "software_output_abs_max": software_abs_max,
        "software_hidden_abs_max": hidden_abs_max,
        "chosen_g_scale": float(config.g_scale),
        "chosen_mapping": config.label(),
        "search": search["candidates"],
        "matched_software": False,
        "failed": False,
        "failure_reason": None,
        "model_path": str(model_path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
    }

    if netlist is None:
        record["failed"] = True
        record["failure_reason"] = best.get("spice_error") or "compiler produced no netlist"
        return record

    dest = CIRCUIT_DIR / f"{spec['id']}_{spec['n_in']}_{spec['n_hidden']}_{spec['n_out']}.cir"
    print(f"  verifying {counts['n_test']} vectors at {config.label()}", flush=True)
    physical, runtime, spice_err, _log = simulate_batch(
        ngspice, netlist, x_all, spec["n_out"], dest
    )
    n_pos, n_neg = path_counts(catalog)
    resistances = [float(item["R"]) for item in catalog]
    elements = count_spice_elements(netlist)
    record.update(
        {
            "circuit_path": str(dest.relative_to(PROJECT_ROOT)).replace("\\", "/"),
            "n_resistors": len(catalog),
            "n_positive_conductances": n_pos,
            "n_negative_conductances": n_neg,
            "total_conductance": total_conductance(catalog) if catalog else None,
            "r_min": min(resistances) if resistances else None,
            "r_max": max(resistances) if resistances else None,
            "r_mean": float(np.mean(resistances)) if resistances else None,
            "spice_elements": elements,
            "spice_runtime_s": runtime,
            "spice_runtime_per_vector_s": runtime / max(len(x_all), 1),
        }
    )
    if spice_err or physical is None:
        record["failed"] = True
        record["failure_reason"] = spice_err or "no physical outputs"
        print(f"  FAILED: {record['failure_reason']}", flush=True)
        return record

    stats = error_stats(physical, y_sw_all)
    pred = classification_labels(physical)
    expected = classification_labels(y_sw_all)
    n_fail = int(np.sum(pred != expected))
    acc = float(1.0 - n_fail / len(expected))
    rail_hits = int(np.sum(np.abs(physical) >= RAIL - 1e-6))
    matched = (not math.isnan(stats["max_abs_error"])) and stats["max_abs_error"] <= MATCH_TOL
    record.update(
        {
            "mae": stats["mae"],
            "rms": stats["rms"],
            "max_abs_error": stats["max_abs_error"],
            "classification_rule": "threshold_0.5" if spec["n_out"] == 1 else "argmax",
            "classification_accuracy": acc,
            "n_class_failures": n_fail,
            "n_rail_hits": rail_hits,
            "matched_software": matched,
            "match_tolerance": MATCH_TOL,
        }
    )
    print(
        f"  MAE={stats['mae']:.4e} RMS={stats['rms']:.4e} "
        f"max={stats['max_abs_error']:.4e} acc={acc:.3f} "
        f"R={len(catalog)} SigmaG={record['total_conductance']:.4e} "
        f"t={runtime:.2f}s match={matched}",
        flush=True,
    )

    print(
        f"  robustness 5% x {counts['n_robust_trials']} trials, "
        f"{counts['n_robust_inputs']} inputs",
        flush=True,
    )
    record["robustness"] = run_robustness(
        ngspice,
        spec,
        netlist,
        catalog,
        x_robust,
        y_sw_rob,
        counts["n_robust_trials"],
    )
    return record


def scaling_analysis(rows: list[dict]) -> dict:
    ok = [r for r in rows if not r.get("failed") and r.get("mae") is not None]
    if not ok:
        return {"note": "no successful networks to analyze"}

    def col(name: str) -> list[float]:
        return [float(r[name]) for r in ok]

    neurons = col("n_neurons")
    weights = col("n_weights")
    resistors = col("n_resistors")
    runtime = col("spice_runtime_s")
    mae = col("mae")
    gtot = col("total_conductance")
    ratios = []
    for r in ok:
        ratios.append(
            {
                "id": r["id"],
                "resistors_per_weight": r["n_resistors"] / r["n_weights"],
                "runtime_per_neuron": r["spice_runtime_s"] / r["n_neurons"],
                "runtime_per_resistor": r["spice_runtime_s"] / max(r["n_resistors"], 1),
                "conductance_per_neuron": r["total_conductance"] / r["n_neurons"],
                "error_per_neuron": r["mae"] / r["n_neurons"],
            }
        )
    return {
        "note": (
            "Fits are least-squares log-log curves through the measured points. "
            "They are empirical descriptions, not theoretical complexity proofs."
        ),
        "ratios": ratios,
        "measured_fits": {
            "resistors_vs_weights": loglog_fit(weights, resistors),
            "runtime_vs_neurons": loglog_fit(neurons, runtime),
            "runtime_vs_resistors": loglog_fit(resistors, runtime),
            "conductance_vs_neurons": loglog_fit(neurons, gtot),
            "mae_vs_neurons": loglog_fit(neurons, mae),
        },
        "theoretical_expectation": {
            "resistors": (
                "Each nonzero signed weight or bias component becomes one "
                "positive resistor, so resistor count should track the number "
                "of nonzero parameters, not a higher-order graph term."
            ),
            "runtime": (
                "One DC operating point of a circuit whose device count grows "
                "with parameters. Newton iteration cost is expected to grow "
                "at least with element count; the measured exponent is not a proof."
            ),
            "conductance": (
                "SigmaG = G_SCALE * sum(|compiled components|). If the compiler "
                "keeps the same G_SCALE, total conductance should track the L1 "
                "weight mass. Different chosen G_SCALE values break that trend."
            ),
            "error": (
                "Exact (unquantized) mapping should keep analog error roughly "
                "independent of width if the circuit stays off the precision-"
                "rectifier rails. Growth of MAE with size is a measured deviation, "
                "not an assumed complexity law."
            ),
        },
    }


def make_plots(rows: list[dict]) -> dict[str, str]:
    ok = [r for r in rows if not r.get("failed") and r.get("mae") is not None]
    paths = {}
    if not ok:
        return paths
    ordered = sorted(ok, key=lambda r: (r["n_weights"], r["n_neurons"]))
    labels = [r["id"] for r in ordered]
    size = [r["n_weights"] for r in ordered]

    def save(name: str, ylabel: str, values: list[float], path: Path) -> None:
        fig, ax = plt.subplots(figsize=(7.2, 4.4))
        ax.plot(size, values, "o-", color="#1f4e79", linewidth=2, markersize=8)
        for x, y, lab in zip(size, values, labels):
            ax.annotate(lab, (x, y), textcoords="offset points", xytext=(6, 6))
        ax.set_xlabel("weight count (frozen parameters in W1 and W2)")
        ax.set_ylabel(ylabel)
        ax.set_title(name)
        ax.grid(True, alpha=0.3)
        fig.tight_layout()
        fig.savefig(path, dpi=140)
        plt.close(fig)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    p_comp = RESULTS_DIR / "scaling_components.png"
    p_run = RESULTS_DIR / "scaling_runtime.png"
    p_err = RESULTS_DIR / "scaling_error.png"
    p_g = RESULTS_DIR / "scaling_conductance.png"
    save("Resistor count vs network size", "compiled resistors", [r["n_resistors"] for r in ordered], p_comp)
    save("ngspice runtime vs network size", "verification runtime (s)", [r["spice_runtime_s"] for r in ordered], p_run)
    save("Physical MAE vs network size", "MAE vs NumPy reference", [r["mae"] for r in ordered], p_err)
    save("Total conductance vs network size", "Sigma G (S)", [r["total_conductance"] for r in ordered], p_g)
    return {
        "scaling_components": str(p_comp.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        "scaling_runtime": str(p_run.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        "scaling_error": str(p_err.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        "scaling_conductance": str(p_g.relative_to(PROJECT_ROOT)).replace("\\", "/"),
    }


def print_table(rows: list[dict]) -> None:
    header = (
        f"{'NETWORK':<18} {'NEURONS':>8} {'WEIGHTS':>8} {'RESISTORS':>10} "
        f"{'SPICE TIME':>12} {'MAE':>11} {'MAX ERROR':>11} "
        f"{'SigmaG':>11} {'R MIN':>11} {'R MAX':>11}"
    )
    print("\n" + header)
    print("-" * len(header))
    for r in rows:
        if r.get("failed"):
            print(
                f"{r['label']:<18} {r['n_neurons']:>8} {r['n_weights']:>8} "
                f"{'FAIL':>10} {'FAIL':>12} {'FAIL':>11} {'FAIL':>11} "
                f"{'FAIL':>11} {'FAIL':>11} {'FAIL':>11}"
            )
            continue
        print(
            f"{r['label']:<18} {r['n_neurons']:>8} {r['n_weights']:>8} "
            f"{r['n_resistors']:>10} {r['spice_runtime_s']:>11.3f}s "
            f"{r['mae']:>11.3e} {r['max_abs_error']:>11.3e} "
            f"{r['total_conductance']:>11.3e} {r['r_min']:>11.3e} {r['r_max']:>11.3e}"
        )


def identify(rows: list[dict]) -> dict:
    ok = [r for r in rows if not r.get("failed") and r.get("mae") is not None]
    failed = [r for r in rows if r.get("failed")]
    summary = {
        "smallest_network": rows[0]["label"] if rows else None,
        "largest_successfully_simulated": ok[-1]["label"] if ok else None,
        "largest_error": None,
        "fastest_simulation": None,
        "slowest_simulation": None,
        "lowest_conductance": None,
        "highest_conductance": None,
        "all_matched_numpy": bool(ok) and all(r.get("matched_software") for r in rows) and not failed,
        "first_problem": None,
    }
    if ok:
        worst = max(ok, key=lambda r: r["max_abs_error"])
        fastest = min(ok, key=lambda r: r["spice_runtime_s"])
        slowest = max(ok, key=lambda r: r["spice_runtime_s"])
        lo_g = min(ok, key=lambda r: r["total_conductance"])
        hi_g = max(ok, key=lambda r: r["total_conductance"])
        summary.update(
            {
                "largest_error": {
                    "network": worst["label"],
                    "max_abs_error": worst["max_abs_error"],
                },
                "fastest_simulation": {
                    "network": fastest["label"],
                    "spice_runtime_s": fastest["spice_runtime_s"],
                },
                "slowest_simulation": {
                    "network": slowest["label"],
                    "spice_runtime_s": slowest["spice_runtime_s"],
                },
                "lowest_conductance": {
                    "network": lo_g["label"],
                    "total_conductance": lo_g["total_conductance"],
                },
                "highest_conductance": {
                    "network": hi_g["label"],
                    "total_conductance": hi_g["total_conductance"],
                },
            }
        )
    for r in rows:
        if r.get("failed") or not r.get("matched_software"):
            summary["first_problem"] = {
                "network": r["label"],
                "reason": r.get("failure_reason")
                or f"max abs error {r.get('max_abs_error')} > {MATCH_TOL}",
            }
            break
    verdict = (
        "SCALING BENCHMARK PASSED"
        if summary["all_matched_numpy"]
        else "SCALING LIMIT FOUND"
    )
    summary["verdict"] = verdict
    return summary


def main() -> int:
    ngspice = find_ngspice()
    CIRCUIT_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    print("Physical AI - Experiment 9: scaling benchmark")
    print(f"ngspice: {ngspice}")
    print(f"G_SCALE candidates: {list(G_SCALE_GRID)}")
    print(f"seed={SEED}  match_tol={MATCH_TOL}")

    rows = [evaluate_network(ngspice, spec) for spec in NETWORKS]
    analysis = scaling_analysis(rows)
    plots = make_plots(rows)
    summary = identify(rows)
    report = {
        "experiment": 9,
        "seed": SEED,
        "g_scale_grid": list(G_SCALE_GRID),
        "match_tolerance": MATCH_TOL,
        "architecture": (
            "signed conductance, physical current summation and subtraction, "
            "physical ReLU, physical bias; Matter Compiler v1 G_SCALE search "
            "with exact resistors and unconstrained range"
        ),
        "fairness": (
            "weights frozen after deterministic generation; only physical "
            "mapping (G_SCALE) was searched"
        ),
        "networks": rows,
        "analysis": analysis,
        "plots": plots,
        "summary": summary,
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print_table(rows)
    print("\nSmallest network:", summary["smallest_network"])
    print("Largest successfully simulated:", summary["largest_successfully_simulated"])
    print("Largest error:", summary["largest_error"])
    print("Fastest simulation:", summary["fastest_simulation"])
    print("Slowest simulation:", summary["slowest_simulation"])
    print("Lowest conductance:", summary["lowest_conductance"])
    print("Highest conductance:", summary["highest_conductance"])
    print(
        "Every benchmark matched NumPy:",
        "yes" if summary["all_matched_numpy"] else "no",
    )
    if summary["first_problem"]:
        print("First problem:", summary["first_problem"])
    print(f"\nWrote {REPORT_PATH}")
    for key, path in plots.items():
        print(f"Wrote {path}")
    print("\n" + summary["verdict"])
    return 0 if summary["all_matched_numpy"] else 1


if __name__ == "__main__":
    sys.exit(main())
