"""Experiment 11: dynamic-range / multi-branch physical weight encoding.

Compares Experiment 9 baseline, Experiment 10 single-scale constrained,
and Experiment 11 multi-range banks on frozen networks A and F.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from benchmark_scaling import (
    MATCH_TOL,
    N_ROBUST_INPUTS,
    N_ROBUST_TRIALS,
    N_TEST,
    NETWORKS,
    ROBUST_TOLERANCE,
    classification_labels,
    error_stats,
    generate_inputs,
    make_rng,
    simulate_batch,
    software_forward_batch,
)
from compile_xor import PROJECT_ROOT, find_ngspice
from dynamic_range_compiler import (
    CIRCUIT_DIR,
    R_MAX,
    R_MIN,
    RangeConfig,
    compile_dynamic,
    config_public,
    encoding_stats,
    iter_range_grid,
    representation_limits,
)
from hardware_constrained_compiler import (
    BASELINE_G,
    HardwareConfig,
    compile_baseline,
    compile_hardware,
    current_cost_estimate,
    load_frozen_model,
)
from matter_compiler import physical_cost, total_conductance
from test_hardware_constraints import measure_source_current, spec_by_id
from test_robustness import sample_resistor_values


RESULTS_DIR = PROJECT_ROOT / "results"
REPORT_PATH = RESULTS_DIR / "dynamic_range_report.json"
N_SEARCH = 8
TEST_IDS = ("A", "F")

# Experiment 10 1k-1M winner for A (exact search point). F had no mapping.
EXP10_A_1K1M = HardwareConfig(
    g_weight_1=3.232409087862467e-06,
    g_bias_1=0.016828919668733906,
    g_weight_2=2.8792227596549085e-06,
    g_bias_2=9.661414313244723e-05,
    r_min=1.0e3,
    r_max=1.0e6,
    range_name="1k-1M",
    mode="per_layer",
)


def run_robustness(
    ngspice: Path,
    spec: dict,
    netlist: str,
    catalog: list[dict],
    subset_x: np.ndarray,
    software: np.ndarray,
    dest: Path,
    tag: str,
) -> dict:
    rng = make_rng("hw11", spec["id"], tag)
    expected = classification_labels(software)
    maes, maxes, accs = [], [], []
    failures = 0
    t0 = time.perf_counter()
    for trial in range(N_ROBUST_TRIALS):
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
                f"      robustness {tag} {trial + 1}/{N_ROBUST_TRIALS} "
                f"MAE={stats['mae']:.4e}",
                flush=True,
            )
    runtime = time.perf_counter() - t0
    if not maes:
        return {
            "tolerance": ROBUST_TOLERANCE,
            "n_trials": N_ROBUST_TRIALS,
            "n_inputs": int(len(subset_x)),
            "n_spice_failures": failures,
            "failed": True,
            "spice_runtime_s": runtime,
        }
    return {
        "tolerance": ROBUST_TOLERANCE,
        "n_trials": N_ROBUST_TRIALS,
        "n_inputs": int(len(subset_x)),
        "n_spice_failures": failures,
        "failed": False,
        "spice_runtime_s": runtime,
        "mae_mean": float(np.mean(maes)),
        "max_abs_error_worst": float(np.max(maxes)),
        "accuracy_mean": float(np.mean(accs)),
        "accuracy_min": float(np.min(accs)),
    }


def score_record(record: dict, n_eval: int) -> float:
    return physical_cost(
        float(record.get("accuracy") or 0.0),
        int(record.get("n_class_failures") or n_eval),
        float(record.get("mae") or 0.0),
        float(record.get("max_abs_error") or 0.0),
        float(record.get("total_conductance") or 0.0),
        int(record.get("n_resistors") or 0),
        rejected=bool(record.get("failed")),
    )


def evaluate_mapping(
    ngspice: Path,
    spec: dict,
    netlist: str,
    catalog: list[dict],
    inputs: np.ndarray,
    software: np.ndarray,
    dest: Path,
    n_weights: int,
    check_range: bool,
) -> dict:
    stats = encoding_stats(catalog, n_weights)
    record = {
        **stats,
        "constraints_satisfied": True,
        "failed": False,
        "failure_reason": None,
        "matched_software": False,
    }
    if check_range:
        bad = [
            item["name"]
            for item in catalog
            if float(item["R"]) < R_MIN or float(item["R"]) > R_MAX
        ]
        if bad:
            record["constraints_satisfied"] = False
            record["failed"] = True
            record["failure_reason"] = f"out of range: {bad[0]}"
            return record
    t0 = time.perf_counter()
    physical, runtime, spice_err, _log = simulate_batch(
        ngspice, netlist, inputs, spec["n_out"], dest
    )
    record["spice_runtime_s"] = runtime if spice_err or physical is not None else time.perf_counter() - t0
    if spice_err or physical is None:
        record["failed"] = True
        record["failure_reason"] = spice_err or "no physical outputs"
        return record
    err = error_stats(physical, software)
    pred = classification_labels(physical)
    expected = classification_labels(software)
    n_fail = int(np.sum(pred != expected))
    record.update(
        {
            "mae": err["mae"],
            "rms": err["rms"],
            "max_abs_error": err["max_abs_error"],
            "accuracy": float(1.0 - n_fail / max(len(expected), 1)),
            "n_class_failures": n_fail,
            "matched_software": err["max_abs_error"] <= MATCH_TOL,
            "current_cost": current_cost_estimate(
                catalog,
                measure_source_current(
                    ngspice, netlist, inputs[0], dest.with_name(dest.stem + "_i.cir")
                ),
            ),
        }
    )
    return record


def search_multirange(
    ngspice: Path,
    spec: dict,
    weights: dict[str, np.ndarray],
    search_x: np.ndarray,
    software_search: np.ndarray,
) -> dict:
    dest = CIRCUIT_DIR / f"{spec['id']}_search.cir"
    records = []
    best = None
    n_ok = 0
    n_fail_encode = 0
    parallel_only_fail = 0
    for cfg in iter_range_grid():
        netlist, catalog, reason = compile_dynamic(spec, weights, cfg)
        rec = {"config": config_public(cfg), "rejected": reason is not None, "reject_reason": reason}
        if reason is not None:
            n_fail_encode += 1
            if len(cfg.banks) == 1:
                parallel_only_fail += 1
            records.append(rec)
            continue
        physical, runtime, spice_err, _log = simulate_batch(
            ngspice, netlist, search_x, spec["n_out"], dest
        )
        rec["spice_runtime_s"] = runtime
        if spice_err or physical is None:
            rec["spice_error"] = spice_err
            records.append(rec)
            continue
        err = error_stats(physical, software_search)
        pred = classification_labels(physical)
        expected = classification_labels(software_search)
        n_fail = int(np.sum(pred != expected))
        acc = float(1.0 - n_fail / max(len(expected), 1))
        g_total = total_conductance(catalog)
        score = physical_cost(
            acc, n_fail, err["mae"], err["max_abs_error"], g_total, len(catalog), False
        )
        rec.update(
            {
                "mae": err["mae"],
                "max_abs_error": err["max_abs_error"],
                "accuracy": acc,
                "n_resistors": len(catalog),
                "total_conductance": g_total,
                "score": score,
            }
        )
        records.append(rec)
        n_ok += 1
        if best is None or score < best["score"]:
            best = {
                **rec,
                "range_config": cfg,
                "catalog": catalog,
                "netlist": netlist,
            }
        if n_ok <= 8 or n_ok % 15 == 0:
            print(
                f"    {cfg.label()} R={len(catalog)} MAE={err['mae']:.3e} "
                f"score={score:.4g}",
                flush=True,
            )
    return {
        "n_candidates": len(list(iter_range_grid())),
        "n_encode_failures": n_fail_encode,
        "n_parallel_only_failures": parallel_only_fail,
        "n_spice_ok": n_ok,
        "candidates": [
            {k: v for k, v in r.items() if k not in {"range_config", "catalog", "netlist"}}
            for r in records
        ],
        "best": best,
    }


def evaluate_network(ngspice: Path, spec: dict) -> dict:
    weights = load_frozen_model(spec["id"])
    n_weights = spec["n_in"] * spec["n_hidden"] + spec["n_hidden"] * spec["n_out"]
    x_all = generate_inputs(spec["n_in"], N_TEST, spec["id"])
    x_search = x_all[:N_SEARCH]
    x_rob = x_all[:N_ROBUST_INPUTS]
    y_all = software_forward_batch(
        x_all, weights["W1"], weights["b1"], weights["W2"], weights["b2"]
    )
    y_search = software_forward_batch(
        x_search, weights["W1"], weights["b1"], weights["W2"], weights["b2"]
    )
    y_rob = software_forward_batch(
        x_rob, weights["W1"], weights["b1"], weights["W2"], weights["b2"]
    )

    print(f"\n=== {spec['id']} {spec['n_in']}->{spec['n_hidden']}->{spec['n_out']} ===")
    limits = representation_limits(weights)
    print(
        f"  W1 ratio={limits['parameter_spans']['W1']['ratio']:.4g} "
        f"W2 ratio={limits['parameter_spans']['W2']['ratio']:.4g}",
        flush=True,
    )

    methods = {}

    print("  baseline (Exp 9, unconstrained G=1e-5)")
    base_net, base_cat = compile_baseline(spec, weights)
    methods["baseline"] = evaluate_mapping(
        ngspice, spec, base_net, base_cat, x_all, y_all,
        CIRCUIT_DIR / f"{spec['id']}_baseline.cir", n_weights, check_range=False,
    )
    methods["baseline"]["mapping"] = f"unified G_SCALE={BASELINE_G:g}"
    methods["baseline"]["constraints_satisfied"] = False
    print(
        f"    MAE={methods['baseline'].get('mae')} "
        f"R=[{methods['baseline'].get('r_min')}, {methods['baseline'].get('r_max')}] "
        f"nR={methods['baseline'].get('n_resistors')}",
        flush=True,
    )
    if not methods["baseline"].get("failed"):
        methods["baseline"]["robustness"] = run_robustness(
            ngspice, spec, base_net, base_cat, x_rob, y_rob,
            CIRCUIT_DIR / f"{spec['id']}_baseline_robust.cir", "baseline",
        )

    print("  single-scale constrained (Exp 10, 1k-1M)")
    if spec["id"] == "A":
        ss_net, ss_cat, ss_reason = compile_hardware(spec, weights, EXP10_A_1K1M)
        if ss_reason or ss_net is None:
            methods["single_scale"] = {
                "failed": True,
                "constraints_satisfied": False,
                "failure_reason": ss_reason,
                "mapping": "Experiment 10 1k-1M winner could not be rebuilt",
            }
        else:
            methods["single_scale"] = evaluate_mapping(
                ngspice, spec, ss_net, ss_cat, x_all, y_all,
                CIRCUIT_DIR / f"{spec['id']}_single_scale.cir",
                n_weights, check_range=True,
            )
            methods["single_scale"]["mapping"] = EXP10_A_1K1M.label()
            if not methods["single_scale"].get("failed"):
                methods["single_scale"]["robustness"] = run_robustness(
                    ngspice, spec, ss_net, ss_cat, x_rob, y_rob,
                    CIRCUIT_DIR / f"{spec['id']}_single_scale_robust.cir",
                    "single",
                )
    else:
        methods["single_scale"] = {
            "failed": True,
            "constraints_satisfied": False,
            "found_valid_mapping": False,
            "failure_reason": (
                "Experiment 10: no single-scale mapping. "
                f"W1 ratio {limits['parameter_spans']['W1']['ratio']:.4g} and "
                f"W2 ratio {limits['parameter_spans']['W2']['ratio']:.4g} "
                f"exceed R_MAX/R_MIN={R_MAX / R_MIN:.4g}."
            ),
            "mapping": "none",
        }
        print("    LIMIT: no Experiment 10 mapping")

    print("  multi-range search")
    search = search_multirange(ngspice, spec, weights, x_search, y_search)
    best = search.pop("best")
    methods["multi_range_search"] = {
        "n_candidates": search["n_candidates"],
        "n_encode_failures": search["n_encode_failures"],
        "n_parallel_only_failures": search["n_parallel_only_failures"],
        "n_spice_ok": search["n_spice_ok"],
    }
    if best is None:
        methods["multi_range"] = {
            "failed": True,
            "constraints_satisfied": False,
            "failure_reason": (
                "No multi-range encoding produced an in-range resistor set."
            ),
        }
        print("    LIMIT: no multi-range mapping")
    else:
        cfg: RangeConfig = best["range_config"]
        dest = CIRCUIT_DIR / f"{spec['id']}_multirange.cir"
        dest.write_text(best["netlist"], encoding="utf-8")
        print(f"    winner {cfg.label()}")
        methods["multi_range"] = evaluate_mapping(
            ngspice, spec, best["netlist"], best["catalog"], x_all, y_all,
            dest, n_weights, check_range=True,
        )
        methods["multi_range"]["mapping"] = cfg.label()
        methods["multi_range"]["config"] = config_public(cfg)
        methods["multi_range"]["circuit_path"] = str(
            dest.relative_to(PROJECT_ROOT)
        ).replace("\\", "/")
        print(
            f"    MAE={methods['multi_range'].get('mae')} "
            f"R=[{methods['multi_range'].get('r_min')}, {methods['multi_range'].get('r_max')}] "
            f"nR={methods['multi_range'].get('n_resistors')} "
            f"R/weight={methods['multi_range'].get('resistors_per_weight')}",
            flush=True,
        )
        if (
            not methods["multi_range"].get("failed")
            and methods["multi_range"].get("constraints_satisfied")
        ):
            methods["multi_range"]["robustness"] = run_robustness(
                ngspice, spec, best["netlist"], best["catalog"], x_rob, y_rob,
                CIRCUIT_DIR / f"{spec['id']}_multirange_robust.cir",
                "multi",
            )

    return {
        "id": spec["id"],
        "label": f"{spec['id']} {spec['n_in']}->{spec['n_hidden']}->{spec['n_out']}",
        "n_weights": n_weights,
        "n_test": N_TEST,
        "model_path": f"models/scaling/{spec['id']}.npz",
        "limits": limits,
        "methods": methods,
    }


def make_plots(rows: list[dict]) -> dict[str, str]:
    labels = [r["id"] for r in rows]
    x = np.arange(len(labels))
    width = 0.25
    names = ("baseline", "single_scale", "multi_range")
    colors = ("#4a4a4a", "#1f4e79", "#7a9e4e")
    titles = ("Exp 9 baseline", "Exp 10 single-scale", "Exp 11 multi-range")

    def values(key: str) -> list[list[float]]:
        out = []
        for name in names:
            col = []
            for row in rows:
                rec = row["methods"].get(name) or {}
                val = rec.get(key)
                col.append(val if isinstance(val, (int, float)) else np.nan)
            out.append(col)
        return out

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    paths = {}

    fig, ax = plt.subplots(figsize=(7.4, 4.3))
    for i, (vals, title, color) in enumerate(zip(values("n_resistors"), titles, colors)):
        ax.bar(x + (i - 1) * width, vals, width, label=title, color=color)
    ax.set_xticks(x, labels)
    ax.set_ylabel("compiled resistors")
    ax.set_title("Component count")
    ax.legend(fontsize=8)
    ax.grid(True, axis="y", alpha=0.3)
    fig.tight_layout()
    p1 = RESULTS_DIR / "dynamic_range_components.png"
    fig.savefig(p1, dpi=140)
    plt.close(fig)
    paths["components"] = str(p1.relative_to(PROJECT_ROOT)).replace("\\", "/")

    fig, ax = plt.subplots(figsize=(7.4, 4.3))
    for i, (vals, title, color) in enumerate(zip(values("accuracy"), titles, colors)):
        ax.bar(x + (i - 1) * width, vals, width, label=title, color=color)
    ax.set_xticks(x, labels)
    ax.set_ylabel("classification accuracy")
    ax.set_ylim(0.0, 1.05)
    ax.set_title("Accuracy vs NumPy labels")
    ax.legend(fontsize=8)
    ax.grid(True, axis="y", alpha=0.3)
    fig.tight_layout()
    p2 = RESULTS_DIR / "dynamic_range_accuracy.png"
    fig.savefig(p2, dpi=140)
    plt.close(fig)
    paths["accuracy"] = str(p2.relative_to(PROJECT_ROOT)).replace("\\", "/")

    fig, ax = plt.subplots(figsize=(7.4, 4.3))
    for i, (vals, title, color) in enumerate(zip(values("mae"), titles, colors)):
        ax.bar(x + (i - 1) * width, vals, width, label=title, color=color)
    ax.set_xticks(x, labels)
    ax.set_ylabel("MAE vs NumPy")
    ax.set_yscale("log")
    ax.set_title("Analog error")
    ax.legend(fontsize=8)
    ax.grid(True, axis="y", alpha=0.3)
    fig.tight_layout()
    p3 = RESULTS_DIR / "dynamic_range_error.png"
    fig.savefig(p3, dpi=140)
    plt.close(fig)
    paths["error"] = str(p3.relative_to(PROJECT_ROOT)).replace("\\", "/")
    return paths


def fmt(value, spec=".4e") -> str:
    if value is None:
        return "n/a"
    return format(value, spec)


def print_method(title: str, rec: dict) -> None:
    print(f"{title}:")
    if rec.get("failed") and not rec.get("mae"):
        print(f"  status: no valid mapping")
        print(f"  reason: {rec.get('failure_reason')}")
        return
    print(f"  accuracy: {fmt(rec.get('accuracy'), '.4f')}")
    print(f"  MAE: {fmt(rec.get('mae'))}")
    print(f"  max error: {fmt(rec.get('max_abs_error'))}")
    print(f"  resistor min: {fmt(rec.get('r_min'))} Ohm")
    print(f"  resistor max: {fmt(rec.get('r_max'))} Ohm")
    print(f"  physical resistors: {rec.get('n_resistors')}")
    print(f"  resistors/weight: {fmt(rec.get('resistors_per_weight'), '.3f')}")
    print(f"  total conductance: {fmt(rec.get('total_conductance'))} S")
    cc = rec.get("current_cost") or {}
    print(f"  relative current I_rel: {fmt(cc.get('i_rel_A'))} A")
    print(f"  SPICE |Isource|: {fmt(cc.get('spice_source_current_A'))} A")
    print(f"  SPICE runtime: {fmt(rec.get('spice_runtime_s'), '.4f')} s")
    print(f"  constraints satisfied: {'yes' if rec.get('constraints_satisfied') else 'no'}")
    rob = rec.get("robustness") or {}
    if rob:
        print(
            f"  robustness: MAE_mean={fmt(rob.get('mae_mean'))} "
            f"acc_mean={fmt(rob.get('accuracy_mean'), '.4f')} "
            f"acc_min={fmt(rob.get('accuracy_min'), '.4f')}"
        )
    if rec.get("mapping"):
        print(f"  mapping: {rec['mapping']}")


def summarize(rows: list[dict]) -> dict:
    f_multi = next(r["methods"].get("multi_range") or {} for r in rows if r["id"] == "F")
    a_multi = next(r["methods"].get("multi_range") or {} for r in rows if r["id"] == "A")
    f_ok = bool(
        f_multi
        and not f_multi.get("failed")
        and f_multi.get("constraints_satisfied")
        and f_multi.get("matched_software")
    )
    a_ok = bool(
        a_multi
        and not a_multi.get("failed")
        and a_multi.get("matched_software")
    )
    if f_ok:
        verdict = "DYNAMIC-RANGE COMPILATION PASSED"
        detail = (
            "Frozen Network F compiled into 1 kOhm-1 MOhm with multi-range "
            "banks. Inference is physical SPICE vs unchanged NumPy weights."
        )
    else:
        verdict = "DYNAMIC-RANGE LIMIT FOUND"
        detail = f_multi.get("failure_reason") or "Network F has no valid multi-range mapping."
    return {
        "verdict": verdict,
        "detail": detail,
        "network_a_ok": a_ok,
        "network_f_ok": f_ok,
        "largest_weight_ratio_represented": (
            next(r["limits"]["parameter_spans"]["W2"]["ratio"] for r in rows if r["id"] == "F")
            if f_ok
            else next(r["limits"]["parameter_spans"]["W1"]["ratio"] for r in rows if r["id"] == "A")
        ),
    }


def main() -> int:
    ngspice = find_ngspice()
    CIRCUIT_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    print("Physical AI - Experiment 11: dynamic-range physical encoding")
    print(f"ngspice: {ngspice}")
    print(f"target window: {R_MIN:g} .. {R_MAX:g} Ohm")
    print("Frozen models: models/scaling/{A,F}.npz")
    print("Resistors are never clipped. Weights are never edited.")

    rows = [evaluate_network(ngspice, spec_by_id(net_id)) for net_id in TEST_IDS]
    plots = make_plots(rows)
    summary = summarize(rows)
    report = {
        "experiment": 11,
        "r_min": R_MIN,
        "r_max": R_MAX,
        "match_tolerance": MATCH_TOL,
        "encoding": (
            "Multi-range conductance banks: I_inj = alpha * V / R, "
            "optional parallel branches on one bank, KCL sum in SPICE."
        ),
        "fairness": (
            "Frozen Experiment 9 weights. No clipping, no Python output correction."
        ),
        "networks": rows,
        "plots": plots,
        "summary": summary,
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("\nEXPERIMENT 11")
    print("DYNAMIC-RANGE PHYSICAL ENCODING")
    for row in rows:
        print(f"\nNETWORK {row['label']}")
        print_method("baseline", row["methods"]["baseline"])
        print_method("single-scale constrained", row["methods"]["single_scale"])
        print_method("multi-range", row["methods"]["multi_range"])

    print("\nlargest weight dynamic range successfully represented:", summary["largest_weight_ratio_represented"])
    print("physical resistor range:", f"{R_MIN:g} .. {R_MAX:g} Ohm")
    if rows[-1]["methods"].get("multi_range"):
        mr = rows[-1]["methods"]["multi_range"]
        print("component overhead (F resistors/weight):", mr.get("resistors_per_weight"))
        print("accuracy (F multi-range):", mr.get("accuracy"))
        print("MAE (F multi-range):", mr.get("mae"))
        rob = mr.get("robustness") or {}
        print(
            "robustness (F multi-range):",
            f"MAE_mean={rob.get('mae_mean')} acc_mean={rob.get('accuracy_mean')} "
            f"acc_min={rob.get('accuracy_min')}",
        )
    print(f"\nWrote {REPORT_PATH}")
    for path in plots.values():
        print(f"Wrote {path}")
    print("\n" + summary["verdict"])
    print(summary["detail"])
    return 0 if summary["network_f_ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
