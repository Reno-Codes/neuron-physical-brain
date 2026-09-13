"""Experiment 20: current-mode cascade bound.

Frozen Experiment 9 networks A and F. Architecture I is the voltage-after-
every-neuron baseline. J copies hidden current with one CCCS per W2 weight.
S uses a resistive current splitter. SPICE is never Python-corrected.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from benchmark_scaling import generate_inputs
from compile_xor import PROJECT_ROOT, find_ngspice, run_ngspice
from current_cascade import (
    ARCH_KEYS,
    ARCH_PUBLIC,
    CIRCUIT_DIR,
    accounting,
    cccs_unit_cell,
    compile_cascade,
    split_unit_cell,
)
from hardware_constrained_compiler import current_cost_estimate, load_frozen_model
from physical_iv_neuron import IVParams
from precision_architectures import hidden_preact_max, software_reference
from test_hardware_constraints import measure_source_current, spec_by_id
from test_iv_architectures import ERROR_LIMIT, N_F_SWEEP, N_TEST, evaluate_netlist
from test_robustness import extract_all


RESULTS_DIR = PROJECT_ROOT / "results"
REPORT_JSON = RESULTS_DIR / "current_cascade_report.json"
REPORT_MD = RESULTS_DIR / "exp20_current_cascade.md"
TEST_IDS = ("A", "F")


def dest(*parts: str) -> Path:
    name = "_".join(
        str(p).replace("%", "pct").replace(".", "p").replace("+", "p") for p in parts
    )
    CIRCUIT_DIR.mkdir(parents=True, exist_ok=True)
    return CIRCUIT_DIR / f"{name}.cir"


def fmt(value, spec=".4e") -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return format(value, spec)
    return str(value)


def software_for(weights, inputs, rail: float = 15.0):
    zmax, hmax = hidden_preact_max(inputs, weights["W1"], weights["b1"])
    clipped = hmax > rail + 1e-12
    y = software_reference(
        inputs, weights["W1"], weights["b1"], weights["W2"], weights["b2"],
        linear=False, hidden_rail=rail if clipped else None,
    )
    return y, {"hidden_preact_max": zmax, "hidden_relu_max": hmax, "clipped": clipped}


def run_units(ngspice) -> dict:
    i_y, w1, w2 = 3e-5, 0.3, 0.5
    gtot = abs(w1) + abs(w2)
    want_split = (i_y * abs(w1) / gtot, i_y * abs(w2) / gtot)
    want_cccs = (w1 * i_y, w2 * i_y)
    want_frozen = (w1 * i_y, w2 * i_y)

    def run(nl, path, a, b):
        path.write_text(nl, encoding="utf-8")
        result = run_ngspice(ngspice, path, timeout=15.0)
        text = f"{result.stdout or ''}\n{result.stderr or ''}"
        i1 = extract_all(text, a)
        i2 = extract_all(text, b)
        return {
            "exit": result.returncode,
            "i1": float(i1[0]) if i1 else None,
            "i2": float(i2[0]) if i2 else None,
        }

    split = run(split_unit_cell(i_y, w1, w2), dest("unit", "split"), "i(v1)", "i(v2)")
    cccs = run(cccs_unit_cell(i_y, w1, w2), dest("unit", "cccs"), "i(v1)", "i(v2)")
    rec = {
        "I_y": i_y,
        "w": [w1, w2],
        "wanted_frozen_I": want_frozen,
        "wanted_split_I": want_split,
        "wanted_cccs_I": want_cccs,
        "split": split,
        "cccs": cccs,
    }
    if split["i1"] is not None:
        rec["split_err_vs_frozen"] = abs(split["i1"] - want_frozen[0]) + abs(
            split["i2"] - want_frozen[1]
        )
        rec["split_err_vs_partition"] = abs(split["i1"] - want_split[0]) + abs(
            split["i2"] - want_split[1]
        )
    if cccs["i1"] is not None:
        rec["cccs_err_vs_frozen"] = abs(cccs["i1"] - want_frozen[0]) + abs(
            cccs["i2"] - want_frozen[1]
        )
    print(
        f"  split I={split['i1']},{split['i2']} "
        f"err_frozen={fmt(rec.get('split_err_vs_frozen'))} "
        f"err_part={fmt(rec.get('split_err_vs_partition'))}",
        flush=True,
    )
    print(
        f"  CCCS  I={cccs['i1']},{cccs['i2']} "
        f"err_frozen={fmt(rec.get('cccs_err_vs_frozen'))}",
        flush=True,
    )
    return rec


def evaluate_arch(ngspice, spec, weights, arch, x_all) -> dict:
    print(f"  architecture {arch}: {ARCH_PUBLIC[arch]['title']}", flush=True)
    n_w = spec["n_in"] * spec["n_hidden"] + spec["n_hidden"] * spec["n_out"]
    y_all, meta = software_for(weights, x_all)
    net, cat, reason = compile_cascade(arch, spec, weights, IVParams(name=arch))
    nom = {"failed": True, "failure_reason": reason, **meta}
    if net is not None:
        dest(spec["id"], arch, "nominal").write_text(net, encoding="utf-8")
        nom = evaluate_netlist(
            ngspice, spec, net, x_all, y_all, dest(spec["id"], arch, "nominal")
        )
        nom.update(accounting(net, cat, n_w))
        nom.update(meta)
        source_i = measure_source_current(
            ngspice, net, x_all[0], dest(spec["id"], arch, "nominal_i")
        )
        nom["current_cost"] = current_cost_estimate(cat, source_i)
    print(
        f"    MAE={nom.get('mae')} acc={nom.get('accuracy')} "
        f"nR={nom.get('passive_resistors')} CCCS={nom.get('n_cccs')} "
        f"crelu={nom.get('n_current_relu')} dumps={nom.get('n_current_dumps')} "
        f"fail={nom.get('failure_reason')}",
        flush=True,
    )
    return {"arch": arch, "title": ARCH_PUBLIC[arch]["title"], "nominal": nom}


def write_plots(report: dict) -> list[str]:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    labels, mae, copies = [], [], []
    for net_id in TEST_IDS:
        for arch in ARCH_KEYS:
            nom = (
                report["networks"].get(net_id, {}).get("architectures", {})
                .get(arch, {})
                .get("nominal")
                or {}
            )
            if nom.get("mae") is None:
                continue
            labels.append(f"{net_id}/{arch}")
            mae.append(nom["mae"])
            copies.append(nom.get("n_cccs") or 0)
    fig, ax = plt.subplots(figsize=(7.0, 4.0))
    ax.bar(np.arange(len(labels)), mae, color="#7048e8")
    ax.set_yscale("log")
    ax.set_xticks(np.arange(len(labels)))
    ax.set_xticklabels(labels, rotation=30, ha="right")
    ax.set_ylabel("MAE vs frozen ReLU map")
    ax.set_title("Experiment 20: current-mode cascade")
    ax.axhline(ERROR_LIMIT, color="k", ls="--", lw=0.8)
    fig.tight_layout()
    p1 = RESULTS_DIR / "current_cascade_mae.png"
    fig.savefig(p1, dpi=140)
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(7.0, 4.0))
    ax.bar(np.arange(len(labels)), copies, color="#e67700")
    ax.set_xticks(np.arange(len(labels)))
    ax.set_xticklabels(labels, rotation=30, ha="right")
    ax.set_ylabel("CCCS count")
    ax.set_title("Experiment 20: current copies vs architecture")
    fig.tight_layout()
    p2 = RESULTS_DIR / "current_cascade_copies.png"
    fig.savefig(p2, dpi=140)
    plt.close(fig)
    return [str(p1), str(p2)]


def write_markdown(report: dict) -> None:
    u = report.get("unit") or {}
    lines = [
        "# Experiment 20 — current-mode cascade bound",
        "",
        "## TITLE",
        "Can hidden current-to-voltage conversion be removed by cascading in current?",
        "",
        "## QUESTION",
        "After Experiment 18 showed passive V=IR cannot implement the frozen map, "
        "can weighted current → physical ReLU → next weighted current avoid a "
        "voltage conversion at every neuron?",
        "",
        "## HYPOTHESIS",
        "A resistive current splitter implements I_k = I_y * G_k/G_tot, not "
        "I_k = w_k * I_y, unless each row of W2 is normalized (it is not). "
        "Arbitrary frozen W2 in current mode requires a current copy/gain per "
        "weight. That explodes the copy count the project has been removing.",
        "",
        "## ARCHITECTURE",
        "- I: Experiment 16 dump (voltage after every neuron)",
        "- J: hidden current ReLU + one CCCS per W2 weight + output dump",
        "- S: hidden current ReLU + resistive current splitter + output dump",
        "",
        "## WHAT CHANGED",
        "Hidden I-to-V / voltage ReLU removed on J and S. Layer 2 is current-mode.",
        "",
        "## WHAT REMAINED FROZEN",
        "Experiment 9 weights. No Python correction. Output still needs I-to-V "
        "to compare against the voltage-domain software map.",
        "",
        "## TEST CONDITIONS",
        "Unit current cell plus networks A and F vs the frozen ReLU map.",
        "",
        "## RESULTS",
        "",
        "### Unit cell",
        f"- I_y={u.get('I_y')} w={u.get('w')}",
        f"- wanted frozen I={u.get('wanted_frozen_I')}",
        f"- wanted split I={u.get('wanted_split_I')}",
        f"- split measured I1={fmt((u.get('split') or {}).get('i1'))} "
        f"I2={fmt((u.get('split') or {}).get('i2'))} "
        f"err_vs_frozen={fmt(u.get('split_err_vs_frozen'))} "
        f"err_vs_partition={fmt(u.get('split_err_vs_partition'))}",
        f"- CCCS measured I1={fmt((u.get('cccs') or {}).get('i1'))} "
        f"I2={fmt((u.get('cccs') or {}).get('i2'))} "
        f"err_vs_frozen={fmt(u.get('cccs_err_vs_frozen'))}",
        "",
        "### Networks",
    ]
    for net_id in TEST_IDS:
        lines.append(f"#### Network {net_id}")
        for arch in ARCH_KEYS:
            nom = (
                report["networks"].get(net_id, {}).get("architectures", {})
                .get(arch, {})
                .get("nominal")
                or {}
            )
            lines.append(
                f"- {arch}: MAE={fmt(nom.get('mae'))} "
                f"acc={fmt(nom.get('accuracy'), '.4f')} "
                f"CCCS={nom.get('n_cccs')} crelu={nom.get('n_current_relu')} "
                f"dumps={nom.get('n_current_dumps')} nR={nom.get('passive_resistors')} "
                f"fail={nom.get('failure_reason')}"
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
    f = (report.get("networks") or {}).get("F", {}).get("architectures") or {}
    i_n = (f.get("I") or {}).get("nominal") or {}
    j_n = (f.get("J") or {}).get("nominal") or {}
    s_n = (f.get("S") or {}).get("nominal") or {}
    u = report.get("unit") or {}
    report["comparison"] = (
        f"F I MAE={fmt(i_n.get('mae'))} CCCS={i_n.get('n_cccs')}; "
        f"F J MAE={fmt(j_n.get('mae'))} CCCS={j_n.get('n_cccs')}; "
        f"F S MAE={fmt(s_n.get('mae'))} CCCS={s_n.get('n_cccs')}. "
        "Exp 16 I has 0 CCCS and 48 dumps. Exp 17 A has 0 dumps and 48 TIA."
    )
    report["failure_modes"] = (
        "S computes a normalized current partition, not W2. J implements W2 "
        "but needs one current-copy gain per hidden-to-output weight "
        f"(F: {j_n.get('n_cccs')} CCCS). 0.1% copy error would return the "
        "Experiment 12/16 bottleneck at much larger count."
    )
    report["dominant_error"] = (
        "S: current-division identity I*G/G_tot. J: leftover CCCS copy gain "
        "plus output dump. I: leftover dump only."
    )
    report["physical_interpretation"] = (
        f"Unit split matches G/G_tot (err={fmt(u.get('split_err_vs_partition'))}) "
        f"and mismatches w*I (err={fmt(u.get('split_err_vs_frozen'))}). "
        f"Unit CCCS matches w*I (err={fmt(u.get('cccs_err_vs_frozen'))}). "
        "Kirchhoff current division is ratiometric and physically elegant, "
        "but it is not an unnormalized matrix multiply."
    )
    report["hardware_level"] = (
        "LEVEL 2 behavioral. J's CCCS would become MOS current mirrors with "
        "per-weight gain — not justified as a path that *reduces* active blocks."
    )
    j_mae = j_n.get("mae")
    j_cccs = j_n.get("n_cccs") or 0
    s_mae = s_n.get("mae")
    report["conclusion"] = (
        "CURRENT-MODE CASCADE CANNOT REMOVE COPIES FOR FROZEN W2. "
        "A splitter is the wrong math. A CCCS fabric restores the copy "
        f"explosion ({j_cccs} on F). Hidden voltage conversion remains the "
        "cheaper way to apply an arbitrary next-layer weight matrix."
    )
    if j_mae is not None and j_mae <= ERROR_LIMIT and j_cccs > 48:
        report["conclusion"] += (
            f" J analog MAE={fmt(j_mae)} is fine and irrelevant: it loses "
            "on active-block count."
        )
    if s_mae is not None and s_mae > ERROR_LIMIT:
        report["conclusion"] += f" S MAE={fmt(s_mae)} confirms the partition error."
    report["next_question"] = (
        "Given VG is required (Exp 18) and current cascade is not cheaper "
        "(Exp 20), what is the minimum active primitive of one neuron, and "
        "can finite TIA A be treated as a common-mode scale?"
    )


def main() -> int:
    print("Experiment 20: current-mode cascade bound", flush=True)
    ngspice = find_ngspice()
    print(f"ngspice: {ngspice}", flush=True)
    CIRCUIT_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "experiment": 20,
        "title": "current-mode cascade bound",
        "frozen_weights": "Experiment 9 models/scaling/{A,F}.npz",
        "spice_source_of_truth": True,
        "python_does_not_correct_spice": True,
    }
    print("Unit cells", flush=True)
    report["unit"] = run_units(ngspice)
    report["networks"] = {}
    for net_id in TEST_IDS:
        spec = spec_by_id(net_id)
        weights = load_frozen_model(net_id)
        n_vec = N_TEST if net_id == "A" else N_F_SWEEP
        x_all = generate_inputs(spec["n_in"], n_vec, f"exp20_{net_id}")
        print(f"Network {net_id}", flush=True)
        arches = {}
        for arch in ARCH_KEYS:
            arches[arch] = evaluate_arch(ngspice, spec, weights, arch, x_all)
        report["networks"][net_id] = {"architectures": arches}

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
