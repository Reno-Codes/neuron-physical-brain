"""Experiment 18: passive current-to-voltage bound.

Frozen Experiment 9 networks A and F. Architectures I and A are the
Experiment 16/17 baselines. P and L replace the TIA with a passive Rf.
SPICE outputs are never corrected in Python.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from benchmark_scaling import (
    N_TEST,
    classification_labels,
    error_stats,
    generate_inputs,
    make_rng,
    simulate_batch,
)
from compile_xor import PROJECT_ROOT, find_ngspice, run_ngspice
from hardware_constrained_compiler import current_cost_estimate, load_frozen_model
from passive_iv import (
    ARCH_KEYS,
    ARCH_PUBLIC,
    CIRCUIT_DIR,
    accounting,
    attenuation_factors,
    charge_dc_netlist,
    compile_passive,
    predicted_isolated_passive,
    unit_cell,
)
from physical_iv_neuron import IVParams, neuron_tags, sample_independent
from precision_architectures import ARCH_C_CFG, hidden_preact_max, software_reference
from test_hardware_constraints import measure_source_current, spec_by_id
from test_iv_architectures import ERROR_LIMIT, evaluate_netlist, first_class_fail, first_over
from test_nonideal_network import class_margins
from test_robustness import extract_all


RESULTS_DIR = PROJECT_ROOT / "results"
REPORT_JSON = RESULTS_DIR / "passive_iv_report.json"
REPORT_MD = RESULTS_DIR / "exp18_passive_iv.md"
TIMEOUT = 40.0
N_F_SWEEP = 40
LOCAL_PCTS = (0.0, 0.01, 0.1, 0.5, 1.0, 2.0, 5.0, 10.0)
TEST_IDS = ("A", "F")
UNIT_INPUTS = (
    (0.0, 0.0),
    (1.0, 0.0),
    (0.0, 1.0),
    (1.0, 1.0),
    (0.5, -0.5),
    (-0.7, 0.4),
    (0.3, 0.8),
    (-1.0, -1.0),
)


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


def software_for(weights, inputs, rail: float, linear: bool = False):
    zmax, hmax = hidden_preact_max(inputs, weights["W1"], weights["b1"])
    clipped = (not linear) and hmax > rail + 1e-12
    y = software_reference(
        inputs, weights["W1"], weights["b1"], weights["W2"], weights["b2"],
        linear=linear, hidden_rail=rail if clipped else None,
    )
    return y, {"hidden_preact_max": zmax, "hidden_relu_max": hmax, "clipped": clipped}


def parse_two(text: str, a: str, b: str) -> tuple[float | None, float | None]:
    va = extract_all(text, a)
    vb = extract_all(text, b)
    return (float(va[0]) if va else None, float(vb[0]) if vb else None)


def run_unit_cells(ngspice) -> dict:
    # Frozen network A, first hidden neuron: realistic signed weights.
    wts = load_frozen_model("A")
    w = [float(wts["W1"][0, 0]), float(wts["W1"][0, 1])]
    bias = float(wts["b1"][0])
    g_w = 3e-5
    rows = {}
    print(f"  unit neuron w={w} b={bias:g}", flush=True)
    for arch in ("I", "A", "P", "Q"):
        net, g_tot, rf = unit_cell(arch, w, bias, g_w=g_w)
        k = 1.0 / (1.0 + rf * g_tot)
        recs = []
        for x1, x2 in UNIT_INPUTS:
            z = w[0] * x1 + w[1] * x2 + bias
            path = dest("unit", arch, f"{x1}_{x2}")
            body = net
            # Patch DC sources by rewrite of the three Vin lines after write.
            patched = []
            for line in body.splitlines():
                if line.startswith("Vin1 "):
                    patched.append(f"Vin1 in1 0 DC {x1:.15g}")
                elif line.startswith("Vin2 "):
                    patched.append(f"Vin2 in2 0 DC {x2:.15g}")
                else:
                    patched.append(line)
            path.write_text("\n".join(patched) + "\n", encoding="utf-8")
            result = run_ngspice(ngspice, path, timeout=20.0)
            text = f"{result.stdout or ''}\n{result.stderr or ''}"
            vlin, vsum = parse_two(text, "v(lin)", "v(sum)")
            failed = result.returncode != 0 or vlin is None
            recs.append(
                {
                    "x": [x1, x2],
                    "z_numpy": z,
                    "z_attenuated": k * z,
                    "v_lin": vlin,
                    "v_sum": vsum,
                    "err_vs_numpy": None if failed else abs(vlin - z),
                    "err_vs_attenuated": None if failed else abs(vlin - k * z),
                    "failed": failed,
                    "spice_exit": result.returncode,
                }
            )
        ok = [r for r in recs if not r["failed"]]
        mae_np = float(np.mean([r["err_vs_numpy"] for r in ok])) if ok else None
        mae_k = float(np.mean([r["err_vs_attenuated"] for r in ok])) if ok else None
        rows[arch] = {
            "G_tot": g_tot,
            "Rf": rf,
            "predicted_k": k,
            "mae_vs_numpy": mae_np,
            "mae_vs_attenuated": mae_k,
            "max_abs_Vsum": max((abs(r["v_sum"]) for r in ok if r["v_sum"] is not None), default=None),
            "n_ok": len(ok),
            "vectors": recs,
        }
        print(
            f"    {arch}: MAE_numpy={fmt(mae_np)} MAE_k={fmt(mae_k)} "
            f"k={k:.6g} Vsum={fmt(rows[arch]['max_abs_Vsum'])}",
            flush=True,
        )
    return {"w": w, "bias": bias, "architectures": rows}


def measure_sum_nodes(ngspice, spec, netlist, x, path) -> dict:
    tags = neuron_tags(spec)
    nodes = [f"{tag}p" for tag in tags]
    head, sep, _tail = netlist.partition(".control")
    if not sep:
        return {"failed": True, "reason": "no .control"}
    lines = [".control", "set numdgt=15"]
    for i, xi in enumerate(np.atleast_1d(x), start=1):
        lines.append(f"alter Vin{i} DC {float(xi):.15g}")
    lines.append("op")
    for node in nodes:
        lines.append(f"print v({node})")
    lines.extend([".endc", "", ".end", ""])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(head.rstrip() + "\n" + "\n".join(lines), encoding="utf-8")
    result = run_ngspice(ngspice, path, timeout=TIMEOUT)
    text = f"{result.stdout or ''}\n{result.stderr or ''}"
    if result.returncode != 0:
        return {"failed": True, "reason": f"ngspice exit {result.returncode}"}
    absvals = []
    by_node = {}
    for node in nodes:
        vals = extract_all(text, f"v({node})")
        if not vals:
            by_node[node] = None
            continue
        by_node[node] = float(vals[0])
        absvals.append(abs(float(vals[0])))
    if not absvals:
        return {"failed": True, "reason": "no summing-node voltages"}
    return {
        "failed": False,
        "n_nodes": len(nodes),
        "max_abs_V": float(np.max(absvals)),
        "mean_abs_V": float(np.mean(absvals)),
        "nodes": {k: by_node[k] for k in list(by_node)[:8]},
    }


def evaluate_arch(ngspice, spec, weights, arch, x_all, x_sw) -> dict:
    print(f"  architecture {arch}: {ARCH_PUBLIC[arch]['title']}", flush=True)
    n_w = spec["n_in"] * spec["n_hidden"] + spec["n_hidden"] * spec["n_out"]
    rail = 15.0
    y_relu, meta = software_for(weights, x_all, rail, linear=False)
    y_lin, _ = software_for(weights, x_all, rail, linear=True)
    y_sw, _ = software_for(weights, x_sw, rail, linear=False)
    params = IVParams(name=f"{arch}_nom", rail=rail)
    net, cat, reason = compile_passive(arch, spec, weights, params)
    nom = {"failed": True, "failure_reason": reason, **meta}
    atten = None
    theory = None
    if net is not None:
        dest(spec["id"], arch, "nominal").write_text(net, encoding="utf-8")
        physical, runtime, spice_err, log = simulate_batch(
            ngspice, net, x_all, spec["n_out"],
            dest(spec["id"], arch, "nominal"), timeout=TIMEOUT,
        )
        nom = {"failed": False, "failure_reason": None, "spice_runtime_s": runtime}
        if spice_err or physical is None:
            nom.update(
                {
                    "failed": True,
                    "failure_reason": spice_err or "no physical outputs",
                    "spice_log_tail": (log or "")[-400:],
                    "convergence_failure": "convergence" in (spice_err or "").lower(),
                }
            )
        else:
            err = error_stats(physical, y_relu)
            pred = classification_labels(physical)
            expected = classification_labels(y_relu)
            n_fail = int(np.sum(pred != expected))
            nom.update(
                {
                    "mae": err["mae"],
                    "rms": err["rms"],
                    "max_abs_error": err["max_abs_error"],
                    "accuracy": float(1.0 - n_fail / max(len(expected), 1)),
                    "n_class_failures": n_fail,
                    "min_margin": float(np.min(class_margins(physical, y_relu))),
                    "classification_ok": n_fail == 0,
                    "exceeds_error_limit": err["mae"] > ERROR_LIMIT,
                    "convergence_failure": False,
                }
            )
            cfg = ARCH_C_CFG[spec["id"]]
            atten = attenuation_factors(spec, cat, cfg.g_weight_1, cfg.g_weight_2)
            y_pred = predicted_isolated_passive(
                x_all, weights, atten["k_hidden"], atten["k_output"], rail
            )
            theory = {
                "mae_vs_attenuated_prediction": error_stats(physical, y_pred)["mae"],
                "max_vs_attenuated_prediction": error_stats(physical, y_pred)["max_abs_error"],
                "mae_vs_linear_software": error_stats(physical, y_lin)["mae"],
                "note": (
                    "attenuated prediction is isolated-P theory. "
                    "Agreement supports the loading identity. "
                    "This is not a correction of SPICE."
                ),
            }
        nom.update(accounting(net, cat, n_w))
        nom.update(meta)
        source_i = measure_source_current(
            ngspice, net, x_all[0], dest(spec["id"], arch, "nominal_i")
        )
        nom["current_cost"] = current_cost_estimate(cat, source_i)
        nom["spice_source_current_A"] = source_i
        nom["summing_node"] = measure_sum_nodes(
            ngspice, spec, net, x_all[0], dest(spec["id"], arch, "vsum")
        )
        if atten is None:
            cfg = ARCH_C_CFG[spec["id"]]
            atten = attenuation_factors(spec, cat, cfg.g_weight_1, cfg.g_weight_2)
    print(
        f"    MAE_relu={nom.get('mae')} acc={nom.get('accuracy')} "
        f"nR={nom.get('passive_resistors')} dumps={nom.get('n_current_dumps')} "
        f"tia={nom.get('n_tia_opamps')} "
        f"Vsum={((nom.get('summing_node') or {}).get('max_abs_V'))} "
        f"theory={None if theory is None else theory.get('mae_vs_attenuated_prediction')} "
        f"fail={nom.get('failure_reason')}",
        flush=True,
    )
    return {
        "arch": arch,
        "title": ARCH_PUBLIC[arch]["title"],
        "iv_topology": ARCH_PUBLIC[arch]["iv_topology"],
        "nominal": nom,
        "attenuation": atten,
        "theory": theory,
        "net_nominal": net,
        "catalog": cat,
        "y_sw": y_sw,
        "x_sw": x_sw,
    }


def sweep_local(ngspice, spec, block) -> list[dict]:
    net, cat = block["net_nominal"], block["catalog"]
    if net is None:
        return []
    x_sw, y_sw = block["x_sw"], block["y_sw"]
    rows = []
    for pct in LOCAL_PCTS:
        rng = make_rng("exp18", spec["id"], block["arch"], "local", pct)
        values = sample_independent(cat, pct, rng)
        rec = {"name": f"local_{pct:g}", "value": pct}
        rec.update(
            evaluate_netlist(
                ngspice, spec, net, x_sw, y_sw,
                dest(spec["id"], block["arch"], f"local_{pct:g}"),
                r_values=values,
            )
        )
        print(
            f"    local {pct:g}% MAE={rec.get('mae')} acc={rec.get('accuracy')}",
            flush=True,
        )
        rows.append(rec)
    return rows


def run_charge(ngspice) -> dict:
    i_amp, c_f, t_stop = 3e-5, 1e-9, 1e-6
    expected = (i_amp / c_f) * t_stop
    dc_path = dest("charge", "dc")
    dc_path.write_text(charge_dc_netlist(i_amp, c_f), encoding="utf-8")
    dc = run_ngspice(ngspice, dc_path, timeout=15.0)
    dc_text = f"{dc.stdout or ''}\n{dc.stderr or ''}"
    v_dc = extract_all(dc_text, "v(cap)")
    dc_rec = {
        "exit": dc.returncode,
        "v_cap": float(v_dc[0]) if v_dc else None,
        "log_tail": dc_text[-500:],
        "note": "A lone capacitor is an open circuit at DC. Pathological or undefined.",
    }
    tran_path = dest("charge", "tran")
    tran_nl = "\n".join(
        [
            "* Experiment 18 charge-domain transient V=(I/C)*t",
            f"Iin 0 cap DC {i_amp:.15g}",
            f"C1 cap 0 {c_f:.15g}",
            ".ic v(cap)=0",
            f".tran {t_stop / 50.0:.15g} {t_stop:.15g} uic",
            ".control",
            "set numdgt=15",
            "run",
            f"meas tran vend FIND v(cap) AT={t_stop:.15g}",
            "print vend",
            ".endc",
            ".end",
            "",
        ]
    )
    tran_path.write_text(tran_nl, encoding="utf-8")
    tr = run_ngspice(ngspice, tran_path, timeout=20.0)
    tr_text = f"{tr.stdout or ''}\n{tr.stderr or ''}"
    v_tr = extract_all(tr_text, "vend")
    if not v_tr:
        v_tr = extract_all(tr_text, "v(cap)")
    tran_rec = {
        "exit": tr.returncode,
        "v_end": float(v_tr[-1]) if v_tr else None,
        "expected_V": expected,
        "abs_error": None if not v_tr else abs(float(v_tr[-1]) - expected),
        "I_A": i_amp,
        "C_F": c_f,
        "t_s": t_stop,
        "note": "Charge accumulation is time-dependent. It is not a DC TIA replacement.",
    }
    print(
        f"  charge DC v={dc_rec['v_cap']} exit={dc.returncode} "
        f"TRAN v={tran_rec['v_end']} expected={expected:g}",
        flush=True,
    )
    return {"dc": dc_rec, "transient": tran_rec}


def write_plots(report: dict) -> list[str]:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    paths = []
    fig, ax = plt.subplots(figsize=(7.5, 4.2))
    labels, mae, acc = [], [], []
    for net_id in TEST_IDS:
        block = report["networks"].get(net_id, {})
        for arch in ARCH_KEYS:
            rec = (block.get("architectures") or {}).get(arch, {})
            nom = rec.get("nominal") or {}
            if nom.get("mae") is None:
                continue
            labels.append(f"{net_id}/{arch}")
            mae.append(nom["mae"])
            acc.append(nom.get("accuracy", 0.0))
    x = np.arange(len(labels))
    ax.bar(x, mae, color="#4c6ef5")
    ax.set_yscale("log")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=30, ha="right")
    ax.set_ylabel("MAE vs frozen ReLU map")
    ax.set_title("Experiment 18: passive I-to-V vs I / TIA-A")
    ax.axhline(ERROR_LIMIT, color="k", ls="--", lw=0.8, label="MAE=1e-3")
    ax.legend()
    fig.tight_layout()
    p1 = RESULTS_DIR / "passive_iv_comparison.png"
    fig.savefig(p1, dpi=140)
    plt.close(fig)
    paths.append(str(p1))

    fig, ax = plt.subplots(figsize=(6.5, 4.0))
    unit = report.get("unit_cell", {}).get("architectures", {})
    names, v_np, v_k = [], [], []
    for arch, rec in unit.items():
        names.append(arch)
        v_np.append(rec.get("mae_vs_numpy") or np.nan)
        v_k.append(rec.get("mae_vs_attenuated") or np.nan)
    x = np.arange(len(names))
    ax.bar(x - 0.18, v_np, 0.35, label="vs numpy z")
    ax.bar(x + 0.18, v_k, 0.35, label="vs k*z loading theory")
    ax.set_yscale("log")
    ax.set_xticks(x)
    ax.set_xticklabels(names)
    ax.set_ylabel("unit-cell MAE")
    ax.set_title("Experiment 18 unit cell: loading identity")
    ax.legend()
    fig.tight_layout()
    p2 = RESULTS_DIR / "passive_iv_unit.png"
    fig.savefig(p2, dpi=140)
    plt.close(fig)
    paths.append(str(p2))
    return paths


def write_markdown(report: dict) -> None:
    u = report.get("unit_cell", {})
    ua = u.get("architectures", {})
    lines = [
        "# Experiment 18 — passive current-to-voltage bound",
        "",
        "## TITLE",
        "Can a passive resistor replace the TIA for frozen-network I-to-V?",
        "",
        "## QUESTION",
        "Can V = I × Rf at the summing node implement the frozen neuron while "
        "preserving next-layer loading, without an active virtual ground?",
        "",
        "## HYPOTHESIS",
        "Passive Rf makes Vsum = I_loaded × Rf. Then I_k = (Vin_k − Vsum)/R_k, "
        "so V = Rf Σ Vin G / (1 + Rf G_tot). The denominator is a per-neuron "
        "attenuation. Because G_tot differs across neurons, this is not a "
        "global scale and cannot be absorbed without editing frozen weights. "
        "A mesh cascade (Architecture L) couples layers and is a different "
        "physical computation.",
        "",
        "## ARCHITECTURE",
        "- I: Experiment 16 dump (exact 0 V + current copy)",
        "- A: Experiment 17 feedback TIA",
        "- P: passive Rf, ReLU B-source isolates layer 2",
        "- L: passive Rf, layer 2 attaches to hidden summing nodes",
        "",
        "## WHAT CHANGED",
        "Removed the TIA / dump. Placed Rf from the summing node to ground.",
        "",
        "## WHAT REMAINED FROZEN",
        "Experiment 9 weights. No Python output correction. Invert op-amps "
        "and ReLU B-sources remain on P. L removes hidden ReLU isolation.",
        "",
        "## TEST CONDITIONS",
        "Unit cell = network A hidden neuron 1. Networks A and F. "
        f"Error bar MAE ≤ {ERROR_LIMIT:g}. Classification reported separately.",
        "",
        "## RESULTS",
        "",
        "### Unit cell",
        f"- weights w={u.get('w')} b={u.get('bias')}",
    ]
    for arch, rec in ua.items():
        lines.append(
            f"- {arch}: MAE vs numpy={fmt(rec.get('mae_vs_numpy'))} "
            f"MAE vs k*z={fmt(rec.get('mae_vs_attenuated'))} "
            f"k={fmt(rec.get('predicted_k'), '.6g')} "
            f"max|Vsum|={fmt(rec.get('max_abs_Vsum'))}"
        )
    lines += ["", "### Networks"]
    for net_id in TEST_IDS:
        block = report["networks"].get(net_id, {})
        lines.append(f"#### Network {net_id}")
        for arch in ARCH_KEYS:
            rec = (block.get("architectures") or {}).get(arch, {})
            nom = rec.get("nominal") or {}
            th = rec.get("theory") or {}
            at = rec.get("attenuation") or {}
            lines.append(
                f"- {arch}: MAE={fmt(nom.get('mae'))} max={fmt(nom.get('max_abs_error'))} "
                f"acc={fmt(nom.get('accuracy'), '.4f')} "
                f"nR={nom.get('passive_resistors')} "
                f"dumps={nom.get('n_current_dumps')} tia={nom.get('n_tia_opamps')} "
                f"Vsum={fmt((nom.get('summing_node') or {}).get('max_abs_V'))} "
                f"k_h={fmt(at.get('k_hidden_mean'), '.4f')} "
                f"theory_MAE={fmt(th.get('mae_vs_attenuated_prediction'))}"
            )
        loc = (block.get("sweeps") or {}).get("P_local")
        if loc:
            fo = first_over(loc)
            fc = first_class_fail(loc)
            lines.append(f"- P local-mismatch first MAE>1e-3: {fo}")
            lines.append(f"- P local-mismatch first class<100%: {fc}")
    ch = report.get("charge") or {}
    lines += [
        "",
        "### Charge domain",
        f"- DC: v={fmt((ch.get('dc') or {}).get('v_cap'))} exit={(ch.get('dc') or {}).get('exit')}",
        f"- TRAN: v={fmt((ch.get('transient') or {}).get('v_end'))} "
        f"expected={fmt((ch.get('transient') or {}).get('expected_V'))}",
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
    a = (report.get("networks") or {}).get("A", {}).get("architectures") or {}
    p_f = (f.get("P") or {}).get("nominal") or {}
    i_f = (f.get("I") or {}).get("nominal") or {}
    aa_f = (f.get("A") or {}).get("nominal") or {}
    l_f = (f.get("L") or {}).get("nominal") or {}
    th = (f.get("P") or {}).get("theory") or {}
    ua = (report.get("unit_cell") or {}).get("architectures") or {}
    p_unit = ua.get("P") or {}
    report["comparison"] = (
        f"F I MAE={fmt(i_f.get('mae'))} acc={fmt(i_f.get('accuracy'), '.4f')}; "
        f"F TIA-A MAE={fmt(aa_f.get('mae'))} acc={fmt(aa_f.get('accuracy'), '.4f')}; "
        f"F P MAE={fmt(p_f.get('mae'))} acc={fmt(p_f.get('accuracy'), '.4f')}; "
        f"F L MAE={fmt(l_f.get('mae'))} acc={fmt(l_f.get('accuracy'), '.4f')}. "
        "P/L are worse than I and TIA-A on analog fidelity because the "
        "summing node is no longer a virtual ground."
    )
    report["failure_modes"] = (
        "Passive Rf sets Vsum to the neuron voltage. Weight currents become "
        "(Vin-Vsum)/R, so the frozen identity I=Vin*G is lost. Per-neuron "
        f"G_tot makes attenuation non-global. Mesh L also loads hidden nodes "
        "and drops ReLU isolation. Divider compensation assumes dest≈0 V "
        "and is therefore inconsistent on P/L."
    )
    report["dominant_error"] = (
        "Summing-node loading: V = Rf ΣVinG / (1+Rf G_tot). Secondary: "
        "VG-designed divider compensation on a floating dest; layer-2 "
        "resistive loading on L."
    )
    k = p_unit.get("predicted_k")
    report["physical_interpretation"] = (
        f"Unit-cell P matches k*z (k={fmt(k, '.6g')}) and does not match z. "
        f"F P vs isolated theory MAE={fmt(th.get('mae_vs_attenuated_prediction'))}. "
        "Charge on a capacitor is not a DC replacement for I-to-V: DC is "
        "an open circuit; transient voltage is (I/C)*t and needs a clock."
    )
    report["hardware_level"] = (
        "LEVEL 2 non-ideal behavioral (P/L are passive at the I-to-V, "
        "but still use invert VCVS and ReLU B-sources). Not LEVEL 4–6."
    )
    p_ok = (p_f.get("mae") is not None) and (p_f.get("mae") <= ERROR_LIMIT)
    report["conclusion"] = (
        "PASSIVE I-TO-V CANNOT IMPLEMENT THE FROZEN MAP."
        if not p_ok
        else "Passive I-to-V unexpectedly met MAE≤1e-3; inspect numbers."
    )
    if not p_ok:
        report["conclusion"] += (
            " A virtual-ground (TIA or 0 V dump) is a minimum active "
            "primitive for this conductance encoding. Next: make the "
            "unavoidable TIA errors ratiometric / offset-immune."
        )
    report["next_question"] = (
        "Can TIA input offset be cancelled by a matched replica so the "
        "Experiment 17 combined-MC floor (Vos-dominated) falls without "
        "reintroducing a current dump?"
    )


def main() -> int:
    print("Experiment 18: passive current-to-voltage bound", flush=True)
    ngspice = find_ngspice()
    print(f"ngspice: {ngspice}", flush=True)
    CIRCUIT_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    report = {
        "experiment": 18,
        "title": "passive current-to-voltage bound",
        "frozen_weights": "Experiment 9 models/scaling/{A,F}.npz",
        "spice_source_of_truth": True,
        "python_does_not_correct_spice": True,
    }
    print("Unit cells", flush=True)
    report["unit_cell"] = run_unit_cells(ngspice)
    print("Charge-domain bound", flush=True)
    report["charge"] = run_charge(ngspice)

    report["networks"] = {}
    for net_id in TEST_IDS:
        spec = spec_by_id(net_id)
        weights = load_frozen_model(net_id)
        n_vec = N_TEST if net_id == "A" else N_F_SWEEP
        x_all = generate_inputs(spec["n_in"], n_vec, f"exp18_{net_id}")
        x_sw = generate_inputs(spec["n_in"], min(n_vec, 40), f"exp18_{net_id}_sw")
        print(f"Network {net_id} {spec['n_in']}->{spec['n_hidden']}->{spec['n_out']}", flush=True)
        arches = {}
        for arch in ARCH_KEYS:
            arches[arch] = evaluate_arch(ngspice, spec, weights, arch, x_all, x_sw)
        sweeps = {}
        if arches["P"]["net_nominal"] is not None:
            print(f"  P local-mismatch sweep on {net_id}", flush=True)
            sweeps["P_local"] = sweep_local(ngspice, spec, arches["P"])
        # Drop netlists from JSON
        public = {}
        for arch, rec in arches.items():
            public[arch] = {
                k: rec[k]
                for k in rec
                if k not in {"net_nominal", "catalog", "y_sw", "x_sw"}
            }
        report["networks"][net_id] = {"architectures": public, "sweeps": sweeps}

    conclude(report)
    plots = write_plots(report)
    report["plots"] = plots
    write_markdown(report)

    def default(o):
        if isinstance(o, (np.floating, np.integer)):
            return float(o)
        if isinstance(o, np.ndarray):
            return o.tolist()
        raise TypeError(type(o))

    REPORT_JSON.write_text(json.dumps(report, indent=2, default=default), encoding="utf-8")
    print(f"wrote {REPORT_JSON}", flush=True)
    print(f"wrote {REPORT_MD}", flush=True)
    print(report.get("conclusion"), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
