"""Matter Compiler v1 driver: deterministic grid search over physical mappings.

The XOR model stays frozen. Every candidate is compiled to SPICE and scored
from ngspice outputs. generated_xor.cir is never replaced.
"""

from __future__ import annotations

import json
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from compile_xor import (
    CIRCUIT_PATH,
    CLASS_THRESHOLD,
    PROJECT_ROOT,
    XOR_X,
    find_ngspice,
    generate_circuit,
    load_model,
)
from matter_compiler import (
    OPTIMIZED_CIRCUIT,
    CompileConfig,
    baseline_config,
    compile_mapping,
    evaluate_mapping,
    iter_search_grid,
    software_reference,
    write_optimized_circuit,
)
from test_robustness import (
    N_TRIALS,
    SEED,
    run_robustness_campaign,
)


RESULTS_DIR = PROJECT_ROOT / "results"
REPORT_PATH = RESULTS_DIR / "matter_compiler_report.json"
PLOT_PATH = RESULTS_DIR / "matter_compiler_search.png"
OPT_ROBUST_CIRCUIT = PROJECT_ROOT / "circuits" / "generated_xor_opt_robust.cir"
OPT_ROBUST_REPORT = RESULTS_DIR / "robustness_optimized_report.json"


def restore_baseline_circuit(w1, b1, w2, b2) -> None:
    net, _ = generate_circuit(XOR_X[0], w1, b1, w2, b2)
    CIRCUIT_PATH.write_text(net, encoding="utf-8")


def plot_search(records: list[dict], baseline_label: str, best_label: str) -> None:
    feasible = [r for r in records if not r["rejected"] and r["accuracy"] >= 1.0]
    fig, ax = plt.subplots(figsize=(8.2, 5.0))
    if feasible:
        xs = [r["total_conductance"] for r in feasible]
        ys = [r["max_abs_error"] for r in feasible]
        ax.scatter(xs, ys, c="0.65", s=36, label="Feasible (100% class)")
    rejected_n = sum(1 for r in records if r["rejected"])
    failed_n = sum(1 for r in records if not r["rejected"] and r["accuracy"] < 1.0)
    ax.set_xlabel("Total compiled conductance (S)")
    ax.set_ylabel("Max |physical - software|")
    ax.set_title("Matter Compiler v1: SPICE-scored mappings")
    ax.set_xscale("log")
    ax.grid(True, which="both", alpha=0.3)

    def mark(label: str, marker: str, color: str, z: int) -> None:
        hits = [r for r in records if r["label"] == label and not r["rejected"]]
        if not hits:
            return
        r = hits[0]
        ax.scatter(
            [r["total_conductance"]],
            [r["max_abs_error"]],
            marker=marker,
            s=140,
            c=color,
            zorder=z,
            label=label[:48],
        )

    mark(baseline_label, "*", "C0", 4)
    if best_label != baseline_label:
        mark(best_label, "D", "C1", 5)
    ax.legend(fontsize=8)
    fig.text(
        0.5,
        0.01,
        f"Rejected (range): {rejected_n}   Class failures: {failed_n}",
        ha="center",
        fontsize=8,
    )
    fig.tight_layout()
    fig.subplots_adjust(bottom=0.12)
    fig.savefig(PLOT_PATH, dpi=150)
    plt.close(fig)


def robustness_summary(conditions: list[dict]) -> dict:
    keys = (
        "resistor_1pct",
        "resistor_5pct",
        "resistor_10pct",
        "res5_noise10mV",
    )
    out = {}
    for key in keys:
        c = next(x for x in conditions if x["name"] == key)
        out[key] = {
            "accuracy": c["accuracy"],
            "failure_rate": c["failure_rate"],
            "max_abs_error": c["max_abs_error"],
            "mae": c["mae"],
        }
    out["min_accuracy"] = min(c["accuracy"] for c in conditions)
    return out


def main() -> int:
    print("MATTER COMPILER v1")
    print("Frozen XOR weights. Physical mapping is the search variable.")
    print()

    try:
        model = load_model()
        ngspice = find_ngspice()
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    w1, b1, w2, b2 = model["W1"], model["b1"], model["W2"], model["b2"]
    software, expected_cls = software_reference(w1, b1, w2, b2)
    print(f"class threshold: {CLASS_THRESHOLD}")
    print(f"software outputs: {np.array2string(software, precision=6)}")
    print()

    base_cfg = baseline_config()
    print(f"=== Baseline: {base_cfg.label()} ===")
    baseline = evaluate_mapping(
        ngspice, w1, b1, w2, b2, software, expected_cls, base_cfg
    )
    if baseline["rejected"] or baseline["accuracy"] < 1.0:
        print("BASELINE FAILED — not optimizing a broken Experiment 6 mapping.")
        restore_baseline_circuit(w1, b1, w2, b2)
        return 1
    print(
        f"accuracy={baseline['accuracy'] * 100:.0f}%  "
        f"MAE={baseline['mae']:.3e}  max|e|={baseline['max_abs_error']:.3e}  "
        f"Gtot={baseline['total_conductance']:.3e} S  "
        f"R=[{baseline['r_min_used']:.3g}, {baseline['r_max_used']:.3g}]  "
        f"score={baseline['score']:.6g}"
    )
    print()

    grid = iter_search_grid()
    print(f"Grid search: {len(grid)} candidates (deterministic order)")
    records: list[dict] = []
    best = baseline
    for i, cfg in enumerate(grid, start=1):
        rec = evaluate_mapping(
            ngspice, w1, b1, w2, b2, software, expected_cls, cfg
        )
        records.append(rec)
        status = "reject" if rec["rejected"] else f"acc={rec['accuracy'] * 100:.0f}%"
        extra = rec["reject_reason"] if rec["rejected"] else f"score={rec['score']:.6g}"
        print(f"  [{i:3d}/{len(grid)}] {cfg.label()}  {status}  {extra}")
        if rec["score"] < best["score"]:
            best = rec

    improved = best["label"] != baseline["label"] and best["score"] < baseline["score"]
    chosen = best if improved else baseline
    chosen_cfg = compile_config_from_record(chosen)

    print()
    print(f"Best score: {best['label']}  score={best['score']:.6g}")
    if improved:
        print("Optimizer selected a different mapping than the Experiment 6 baseline.")
        write_optimized_circuit(w1, b1, w2, b2, chosen_cfg, OPTIMIZED_CIRCUIT)
    else:
        print("No improvement found.")
        write_optimized_circuit(w1, b1, w2, b2, base_cfg, OPTIMIZED_CIRCUIT)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    plot_search(records, baseline["label"], best["label"])

    print()
    print("=== Robustness of chosen mapping (same Experiment 7 sweep) ===")
    opt_net, opt_cat, reason = compile_mapping(w1, b1, w2, b2, chosen_cfg)
    if opt_net is None:
        print(f"ERROR: chosen mapping rejected at write time: {reason}", file=sys.stderr)
        restore_baseline_circuit(w1, b1, w2, b2)
        return 1

    opt_conditions, opt_worst = run_robustness_campaign(
        ngspice,
        opt_net,
        opt_cat,
        software,
        expected_cls,
        dest=OPT_ROBUST_CIRCUIT,
    )
    opt_rob = robustness_summary(opt_conditions)
    OPT_ROBUST_REPORT.write_text(
        json.dumps(
            {
                "mapping": chosen["label"],
                "seed": SEED,
                "n_trials": N_TRIALS,
                "conditions": opt_conditions,
                "worst_case": opt_worst,
                "summary": opt_rob,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    restore_baseline_circuit(w1, b1, w2, b2)

    report = {
        "experiment": 8,
        "model": str(PROJECT_ROOT / "models" / "xor_model.npz"),
        "class_threshold": CLASS_THRESHOLD,
        "cost_function": {
            "rejected": "1e9",
            "wrong_class": "1e6 + 1e5 * n_wrong + 100 * max_error",
            "correct": "100*max_error + 10*mae + 50*total_G + 0.01*n_R",
        },
        "baseline": {k: v for k, v in baseline.items() if k != "catalog"},
        "candidates": [
            {k: v for k, v in r.items() if k != "catalog"} for r in records
        ],
        "best": {k: v for k, v in best.items() if k != "catalog"},
        "improved": improved,
        "chosen": {k: v for k, v in chosen.items() if k != "catalog"},
        "optimized_circuit": str(OPTIMIZED_CIRCUIT),
        "baseline_circuit": str(CIRCUIT_PATH),
        "optimized_robustness": opt_rob,
        "plot": str(PLOT_PATH),
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print()
    print("MATTER COMPILER v1")
    print("==================")
    print()
    print("BASELINE")
    print(f"accuracy: {baseline['accuracy'] * 100:.2f}%")
    print(f"MAE: {baseline['mae']:.6e}")
    print(f"max error: {baseline['max_abs_error']:.6e}")
    print(f"total conductance: {baseline['total_conductance']:.6e} S")
    print(f"resistor range: [{baseline['r_min_used']:.6g}, {baseline['r_max_used']:.6g}] Ohm")
    print()
    print("OPTIMIZED")
    print(f"mapping: {chosen['label']}")
    print(f"accuracy: {chosen['accuracy'] * 100:.2f}%")
    print(f"MAE: {chosen['mae']:.6e}")
    print(f"max error: {chosen['max_abs_error']:.6e}")
    print(f"total conductance: {chosen['total_conductance']:.6e} S")
    print(f"resistor range: [{chosen['r_min_used']:.6g}, {chosen['r_max_used']:.6g}] Ohm")
    print()
    print("ROBUSTNESS")
    print(
        f"optimized min accuracy across Experiment 7 conditions: "
        f"{opt_rob['min_accuracy'] * 100:.2f}%"
    )
    print(f"optimized 10% resistor accuracy: {opt_rob['resistor_10pct']['accuracy'] * 100:.2f}%")
    print(f"optimized 5%+10mV accuracy: {opt_rob['res5_noise10mV']['accuracy'] * 100:.2f}%")
    print()
    if improved:
        print("The optimizer improved the physical mapping (lower explicit cost).")
    else:
        print("No improvement found.")
    print()
    print(f"Wrote {REPORT_PATH}")
    print(f"Wrote {PLOT_PATH}")
    print(f"Wrote {OPTIMIZED_CIRCUIT}")
    print(f"Wrote {OPT_ROBUST_REPORT}")
    print()
    print("Experiment 6 circuit left at circuits/generated_xor.cir")
    return 0


def compile_config_from_record(record: dict) -> CompileConfig:
    cfg = record["config"]
    return CompileConfig(
        g_scale=cfg["g_scale"],
        quant_name=cfg["quant_name"],
        quant_step=cfg["quant_step"],
        range_name=cfg["range_name"],
        r_min=cfg["r_min"],
        r_max=cfg["r_max"],
    )


if __name__ == "__main__":
    sys.exit(main())
