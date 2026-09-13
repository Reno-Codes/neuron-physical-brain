"""Experiment 21: finite TIA gain is per-neuron, not a global scale.

Frozen Experiment 9 A and F. Architecture A only. SPICE uncorrected.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from benchmark_scaling import classification_labels, error_stats, generate_inputs
from compile_xor import PROJECT_ROOT, find_ngspice
from finite_a_scale import (
    CIRCUIT_DIR,
    compile_a,
    neuron_k_factors,
    predict_global,
    predict_neuron,
)
from hardware_constrained_compiler import load_frozen_model
from precision_architectures import ARCH_C_CFG, hidden_preact_max, software_reference
from test_hardware_constraints import spec_by_id
from test_iv_architectures import ERROR_LIMIT, N_F_SWEEP, N_TEST, evaluate_netlist


RESULTS_DIR = PROJECT_ROOT / "results"
REPORT_JSON = RESULTS_DIR / "finite_a_scale_report.json"
REPORT_MD = RESULTS_DIR / "exp21_finite_a_scale.md"
GAINS = (1e2, 1e3, 1e4, 1e5, 1e6)
TEST_IDS = ("A", "F")
RAIL = 15.0


def dest(*parts: str) -> Path:
    name = "_".join(str(p).replace(".", "p") for p in parts)
    CIRCUIT_DIR.mkdir(parents=True, exist_ok=True)
    return CIRCUIT_DIR / f"{name}.cir"


def fmt(value, spec=".4e") -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return format(value, spec)
    return str(value)


def software_for(weights, inputs):
    zmax, hmax = hidden_preact_max(inputs, weights["W1"], weights["b1"])
    clipped = hmax > RAIL + 1e-12
    y = software_reference(
        inputs, weights["W1"], weights["b1"], weights["W2"], weights["b2"],
        linear=False, hidden_rail=RAIL if clipped else None,
    )
    return y


def run_net(ngspice, spec, weights, x) -> dict:
    print(f"Network {spec['id']}", flush=True)
    y = software_for(weights, x)
    cfg = ARCH_C_CFG[spec["id"]]
    net0, cat, reason = compile_a(spec, weights, 1e5)
    if reason or net0 is None:
        return {"failed": True, "failure_reason": reason}
    factors_ref = neuron_k_factors(spec, cat, 1e5, cfg.g_weight_1, cfg.g_weight_2)
    rows = []
    for a in GAINS:
        net, cat, reason = compile_a(spec, weights, a)
        rec = {"A": a, "failed": bool(reason), "failure_reason": reason}
        if reason or net is None:
            rows.append(rec)
            continue
        dest(spec["id"], f"A{a:g}").write_text(net, encoding="utf-8")
        ev = evaluate_netlist(
            ngspice, spec, net, x, y, dest(spec["id"], f"A{a:g}")
        )
        rec.update(ev)
        fac = neuron_k_factors(spec, cat, a, cfg.g_weight_1, cfg.g_weight_2)
        rec["k"] = {
            "global": fac["k_global"],
            "k_hidden_min": fac["k_hidden_min"],
            "k_hidden_max": fac["k_hidden_max"],
            "k_hidden_mean": fac["k_hidden_mean"],
            "G_hidden_min": fac["G_hidden_min"],
            "G_hidden_max": fac["G_hidden_max"],
            "Rf_Gtot_hidden_max": fac["Rf_Gtot_hidden_max"],
        }
        if not ev.get("failed"):
            physical, _rt, err, _log = __import__(
                "benchmark_scaling", fromlist=["simulate_batch"]
            ).simulate_batch(
                ngspice, net, x, spec["n_out"], dest(spec["id"], f"A{a:g}_p"),
                timeout=40.0,
            )
            if physical is not None and not err:
                y_g = predict_global(weights, x, fac["k_global"], RAIL)
                y_n = predict_neuron(weights, x, fac, RAIL)
                rec["mae_vs_global_k"] = error_stats(physical, y_g)["mae"]
                rec["mae_vs_per_neuron_k"] = error_stats(physical, y_n)["mae"]
                rec["class_vs_software"] = ev.get("accuracy")
                rec["class_vs_global_k"] = float(
                    np.mean(classification_labels(physical) == classification_labels(y_g))
                )
                rec["class_vs_per_neuron_k"] = float(
                    np.mean(classification_labels(physical) == classification_labels(y_n))
                )
        print(
            f"  A={a:g} MAE_sw={fmt(rec.get('mae'))} "
            f"MAE_glob={fmt(rec.get('mae_vs_global_k'))} "
            f"MAE_neuron={fmt(rec.get('mae_vs_per_neuron_k'))} "
            f"k_h=[{fmt(fac['k_hidden_min'], '.4f')},{fmt(fac['k_hidden_max'], '.4f')}] "
            f"acc={fmt(rec.get('accuracy'), '.3f')}",
            flush=True,
        )
        rows.append(rec)
    return {
        "failed": False,
        "gtot_span": {
            "G_hidden_min": factors_ref["G_hidden_min"],
            "G_hidden_max": factors_ref["G_hidden_max"],
            "ratio": factors_ref["G_hidden_max"] / max(factors_ref["G_hidden_min"], 1e-18),
            "Rf_Gtot_hidden_max": factors_ref["Rf_Gtot_hidden_max"],
        },
        "sweeps": rows,
    }


def write_plots(report: dict) -> list[str]:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    for net_id, style in (("A", "-"), ("F", "--")):
        rows = report["networks"].get(net_id, {}).get("sweeps") or []
        xs = [r["A"] for r in rows if r.get("mae") is not None]
        ax.plot(xs, [r["mae"] for r in rows if r.get("mae") is not None],
                style, marker="o", label=f"{net_id} vs frozen")
        ax.plot(xs, [r.get("mae_vs_global_k") for r in rows if r.get("mae") is not None],
                style, marker="s", label=f"{net_id} vs global k")
        ax.plot(xs, [r.get("mae_vs_per_neuron_k") for r in rows if r.get("mae") is not None],
                style, marker="^", label=f"{net_id} vs per-neuron k")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("TIA open-loop A")
    ax.set_ylabel("MAE")
    ax.set_title("Experiment 21: finite A is not a global scale")
    ax.axhline(ERROR_LIMIT, color="k", ls="--", lw=0.8)
    ax.legend(fontsize=7)
    fig.tight_layout()
    p = RESULTS_DIR / "finite_a_scale.png"
    fig.savefig(p, dpi=140)
    plt.close(fig)
    return [str(p)]


def write_markdown(report: dict) -> None:
    lines = [
        "# Experiment 21 — finite TIA gain is per-neuron, not global",
        "",
        "## TITLE",
        "Can finite open-loop gain be treated as a ratiometric / common-mode scale?",
        "",
        "## QUESTION",
        "If every TIA shares k=A/(A+1), ReLU(k z)=k ReLU(z) and the map is "
        "a global scale (F argmax invariant; A threshold is not). Does the "
        "physical TIA actually share one k?",
        "",
        "## HYPOTHESIS",
        "k_j = A/(A+1+Rf G_tot_j). Fine-bank physical conductances make G_tot "
        "span orders of magnitude, so finite A is a per-neuron error.",
        "",
        "## ARCHITECTURE",
        "Experiment 17 Architecture A. No new I-to-V.",
        "",
        "## WHAT CHANGED",
        "Measurement only. Open-loop A swept. Predictions are physics checks, "
        "not SPICE corrections.",
        "",
        "## WHAT REMAINED FROZEN",
        "Experiment 9 weights. Fabric. ReLU.",
        "",
        "## TEST CONDITIONS",
        "A in {1e2, 1e3, 1e4, 1e5, 1e6} on networks A and F.",
        "",
        "## RESULTS",
        "",
    ]
    for net_id in TEST_IDS:
        block = report["networks"].get(net_id, {})
        g = block.get("gtot_span") or {}
        lines.append(f"#### Network {net_id}")
        lines.append(
            f"- hidden G_tot span {fmt(g.get('G_hidden_min'))} .. "
            f"{fmt(g.get('G_hidden_max'))} (ratio {fmt(g.get('ratio'), '.2f')}), "
            f"max Rf G_tot={fmt(g.get('Rf_Gtot_hidden_max'), '.3g')}"
        )
        for r in block.get("sweeps") or []:
            lines.append(
                f"- A={r.get('A')}: MAE_sw={fmt(r.get('mae'))} "
                f"MAE_global={fmt(r.get('mae_vs_global_k'))} "
                f"MAE_neuron={fmt(r.get('mae_vs_per_neuron_k'))} "
                f"acc={fmt(r.get('accuracy'), '.3f')} "
                f"k_h=[{fmt((r.get('k') or {}).get('k_hidden_min'), '.4f')},"
                f"{fmt((r.get('k') or {}).get('k_hidden_max'), '.4f')}]"
            )
    lines += [
        "",
        "## COMPARISON WITH PREVIOUS BEST",
        report.get("comparison") or "",
        "",
        "## FAILURE MODES",
        report.get("failure_modes") or "",
        "",
        "## DOMINANT ERROR SOURCE",
        report.get("dominant_error") or "",
        "",
        "## PHYSICAL INTERPRETATION",
        report.get("physical_interpretation") or "",
        "",
        "## HARDWARE REALISM LEVEL",
        report.get("hardware_level") or "",
        "",
        "## CONCLUSION",
        report.get("conclusion") or "",
        "",
        "## NEXT RESEARCH QUESTION",
        report.get("next_question") or "",
        "",
    ]
    REPORT_MD.write_text("\n".join(lines), encoding="utf-8")


def conclude(report: dict) -> None:
    f = report["networks"].get("F", {})
    rows = f.get("sweeps") or []
    r2 = next((r for r in rows if r.get("A") == 100), None)
    r5 = next((r for r in rows if r.get("A") == 1e5), None)
    g = f.get("gtot_span") or {}
    report["comparison"] = (
        f"F G_tot ratio={fmt(g.get('ratio'), '.1f')}, max RfG={fmt(g.get('Rf_Gtot_hidden_max'), '.2f')}. "
        f"At A=100, MAE_sw={fmt((r2 or {}).get('mae'))} "
        f"vs global-k {fmt((r2 or {}).get('mae_vs_global_k'))} "
        f"vs per-neuron-k {fmt((r2 or {}).get('mae_vs_per_neuron_k'))}. "
        f"At A=1e5, MAE_sw={fmt((r5 or {}).get('mae'))}."
    )
    neuron_wins = False
    if r2 and r2.get("mae_vs_per_neuron_k") is not None and r2.get("mae_vs_global_k") is not None:
        neuron_wins = r2["mae_vs_per_neuron_k"] < 0.3 * r2["mae_vs_global_k"]
    report["failure_modes"] = (
        "Treating finite A as k=A/(A+1) under-predicts error whenever G_tot "
        "varies. Fine-bank physical G is the span."
    )
    report["dominant_error"] = (
        "Per-neuron loop load Rf G_tot_j in the TIA closed-loop factor."
    )
    report["physical_interpretation"] = (
        "The leftover TIA error is the same loading identity as Experiment 18, "
        "suppressed by A: k_j = A/(A+1+Rf G_tot_j) ≈ 1 - Rf G_tot_j/A. "
        "It is not ratiometric across neurons."
        if neuron_wins
        else "Inspect whether divider residuals dominate the per-neuron prediction."
    )
    report["hardware_level"] = (
        "LEVEL 2 behavioral TIA. A real op-amp would add the same G_tot "
        "into the loop equation."
    )
    report["conclusion"] = (
        "FINITE OPEN-LOOP GAIN IS NOT A GLOBAL SCALE ON THIS FABRIC."
        if neuron_wins
        else "Finite-A global-scale hypothesis is not cleanly confirmed; see numbers."
    )
    report["next_question"] = (
        "The research boundary is now: a virtual-ground I-to-V is required "
        "(Exp 18), current-mode W2 is more expensive (Exp 20), replica-null "
        "does not beat shared-tap Vos (Exp 19), and finite A is per-neuron "
        "(Exp 21). Device-level work should characterize ONE VG primitive, "
        "not invent a new encoding to chase MAE."
    )


def main() -> int:
    print("Experiment 21: finite TIA A is per-neuron", flush=True)
    ngspice = find_ngspice()
    CIRCUIT_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "experiment": 21,
        "title": "finite TIA gain is per-neuron, not a global scale",
        "frozen_weights": "Experiment 9 models/scaling/{A,F}.npz",
        "spice_source_of_truth": True,
        "python_does_not_correct_spice": True,
        "networks": {},
    }
    for net_id in TEST_IDS:
        spec = spec_by_id(net_id)
        weights = load_frozen_model(net_id)
        n_vec = N_TEST if net_id == "A" else N_F_SWEEP
        x = generate_inputs(spec["n_in"], n_vec, f"exp21_{net_id}")
        report["networks"][net_id] = run_net(ngspice, spec, weights, x)
    conclude(report)
    report["plots"] = write_plots(report)
    write_markdown(report)

    def default(o):
        if isinstance(o, (np.floating, np.integer)):
            return float(o)
        if isinstance(o, np.ndarray):
            return o.tolist()
        raise TypeError(type(o))

    REPORT_JSON.write_text(json.dumps(report, indent=2, default=default), encoding="utf-8")
    print(f"wrote {REPORT_JSON}", flush=True)
    print(report.get("conclusion"), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
