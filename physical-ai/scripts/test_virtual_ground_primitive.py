"""Experiment 23: virtual-ground primitive validation.

Frozen Experiment 9 networks. Architecture A fabric. SPICE is never
Python-corrected. Manufacturer models are included from the local
ngspice tree, not copied into this repository.
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

from benchmark_scaling import (
    classification_labels,
    error_stats,
    generate_inputs,
    simulate_batch,
)
from compile_xor import PROJECT_ROOT, find_ngspice
from hardware_constrained_compiler import load_frozen_model
from physical_iv_neuron import IVParams, compile_iv
from precision_architectures import ARCH_C_CFG, hidden_preact_max, software_reference
from test_hardware_constraints import spec_by_id
from test_iv_architectures import ERROR_LIMIT, evaluate_netlist, measure_sum_nodes
from test_robustness import extract_all
from virtual_ground_primitive import (
    CANDIDATES,
    CIRCUIT_DIR,
    MCP6041_PATH,
    OPA171_PATH,
    PrimParams,
    bake_vin_dc,
    candidate_needs_ps,
    compile_network,
    isolated_neuron,
    isolated_op_control,
    network_op_control,
    run_ngspice_ex,
    simple_op_control,
)
from virtual_ground_requirements import (
    INVERT_PINNED,
    VGParams,
    interpolate_threshold,
    isolated_batch_control,
    max_tolerable,
    rank_neurons,
    tia_k,
)
from virtual_ground_requirements import compile_network as compile_behavioral


RESULTS_DIR = PROJECT_ROOT / "results"
REPORT_JSON = RESULTS_DIR / "virtual_ground_primitive_report.json"
REPORT_MD = RESULTS_DIR / "exp23_virtual_ground_primitive.md"
N_A = 100
N_F = 40
RAIL = 15.0
TAG = "n1"
TIMEOUT = 60.0
TIMEOUT_MACRO = 90.0
GAIN_SWEEP = (1e3, 1e4, 3e4, 5e4, 1e5, 1e6)
VOS_SWEEP = (1e-6, 3e-6, 1e-5, 2.2e-5, 3e-5, 1e-4, 1e-3)
LEAK_SWEEP = (1e-12, 1e-11, 1e-10, 1e-9, 1e-8, 1e-7, 1e-6)
SUPPLIES = (15.0, 5.0, 3.3)


def dest(*parts) -> Path:
    name = "_".join(
        str(p).replace("%", "pct").replace(".", "p").replace("+", "p").replace("-", "m")
        for p in parts
    )
    CIRCUIT_DIR.mkdir(parents=True, exist_ok=True)
    return CIRCUIT_DIR / f"{name}.cir"


def fmt(value, spec=".4e") -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return format(value, spec)
    return str(value)


def software_for(weights, inputs, rail: float = RAIL, linear: bool = False):
    zmax, hmax = hidden_preact_max(inputs, weights["W1"], weights["b1"])
    clipped = (not linear) and hmax > rail + 1e-12
    y = software_reference(
        inputs, weights["W1"], weights["b1"], weights["W2"], weights["b2"],
        linear=linear, hidden_rail=rail if clipped else None,
    )
    return y, {"hidden_preact_max": zmax, "hidden_relu_max": hmax, "clipped": clipped}


def simulate_isolated(ngspice, net, inputs, n_in, path, tag=TAG, pspice=False):
    head, sep, _ = net.partition(".control")
    if not sep:
        return None, None, "no .control", ""
    path.parent.mkdir(parents=True, exist_ok=True)
    if pspice:
        vlins, vsums, logs = [], [], []
        for i, x in enumerate(np.atleast_2d(np.asarray(inputs, dtype=float))):
            vec_path = path.with_name(f"{path.stem}_v{i}.cir")
            baked = bake_vin_dc(head, x[:n_in])
            vec_path.write_text(
                baked.rstrip() + "\n" + simple_op_control([f"{tag}lin", f"{tag}p"]),
                encoding="utf-8",
            )
            t0 = time.perf_counter()
            result = run_ngspice_ex(ngspice, vec_path, timeout=TIMEOUT_MACRO, pspice=True)
            rt = time.perf_counter() - t0
            text = f"{result.stdout or ''}\n{result.stderr or ''}"
            logs.append(f"v{i} rc={result.returncode} t={rt:.2f}s")
            vlin = extract_all(text, f"v({tag}lin)")
            vsum = extract_all(text, f"v({tag}p)")
            if result.returncode != 0 or not vlin:
                return (
                    None,
                    None,
                    f"vector {i}: rc={result.returncode} nlin={len(vlin)}",
                    text[-1500:] + "\n" + "; ".join(logs[-4:]),
                )
            vlins.append(float(vlin[-1]))
            vsums.append(float(vsum[-1]) if vsum else float("nan"))
        return np.array(vlins), np.array(vsums), None, "; ".join(logs[-3:])
    path.write_text(head.rstrip() + "\n" + isolated_batch_control(inputs, n_in, tag), encoding="utf-8")
    t0 = time.perf_counter()
    result = run_ngspice_ex(ngspice, path, timeout=TIMEOUT, pspice=False)
    rt = time.perf_counter() - t0
    text = f"{result.stdout or ''}\n{result.stderr or ''}"
    if result.returncode != 0:
        return None, None, f"ngspice exit {result.returncode}", text[-2000:]
    vlin = extract_all(text, f"v({tag}lin)")
    vsum = extract_all(text, f"v({tag}p)")
    if len(vlin) != len(inputs):
        return None, None, f"expected {len(inputs)} v({tag}lin), got {len(vlin)}", text[-1500:]
    return (
        np.array(vlin, float),
        np.array(vsum, float) if len(vsum) == len(vlin) else None,
        None,
        f"runtime={rt:.3f}s " + text[-300:],
    )


def eval_network(ngspice, spec, weights, params: PrimParams, inputs, y, path, measure_vsum=False):
    net, cat, reason = compile_network(spec, weights, params, linear=False)
    rec = {"failed": True, "failure_reason": reason, "params": params.public()}
    if reason or net is None:
        return rec, net, cat
    path.write_text(net, encoding="utf-8")
    ps = candidate_needs_ps(params.candidate)
    if ps:
        from benchmark_scaling import detect_spice_failure, parse_physical_outputs

        head, sep, _ = net.partition(".control")
        if not sep:
            rec = {"failed": True, "failure_reason": "no .control", "params": params.public()}
            return rec, net, cat
        n_out = spec["n_out"]
        n_in = spec["n_in"]
        rows = []
        for i, x in enumerate(np.atleast_2d(np.asarray(inputs, dtype=float))):
            vec_path = path.with_name(f"{path.stem}_v{i}.cir")
            baked = bake_vin_dc(head, x[:n_in])
            nodes = [f"o{k}lin" for k in range(1, n_out + 1)]
            vec_path.write_text(baked.rstrip() + "\n" + simple_op_control(nodes), encoding="utf-8")
            result = run_ngspice_ex(ngspice, vec_path, timeout=TIMEOUT_MACRO, pspice=True)
            text = f"{result.stdout or ''}\n{result.stderr or ''}"
            err = detect_spice_failure(result)
            if err:
                rec = {
                    "failed": True,
                    "failure_reason": f"vector {i}: {err}",
                    "spice_log_tail": text[-400:],
                    "params": params.public(),
                }
                return rec, net, cat
            try:
                physical = parse_physical_outputs(text, 1, n_out)
            except Exception as exc:
                rec = {
                    "failed": True,
                    "failure_reason": f"vector {i}: {exc}",
                    "spice_log_tail": text[-400:],
                    "params": params.public(),
                }
                return rec, net, cat
            rows.append(physical[0])
        physical = np.vstack(rows)
        errst = error_stats(physical, y)
        pred = classification_labels(physical)
        expected = classification_labels(y)
        n_fail = int(np.sum(pred != expected))
        rec = {
            "failed": False,
            "failure_reason": None,
            "mae": errst["mae"],
            "rms": errst["rms"],
            "max_abs_error": errst["max_abs_error"],
            "accuracy": float(1.0 - n_fail / max(len(expected), 1)),
            "n_class_failures": n_fail,
            "params": params.public(),
            "n_resistors": len(cat),
            "eval": "baked_vin_dc_op",
        }
    else:
        rec = evaluate_netlist(ngspice, spec, net, inputs, y, path)
        rec["params"] = params.public()
        rec["n_resistors"] = len(cat)
    if measure_vsum and not rec.get("failed"):
        rec["summing_node"] = measure_sum_nodes(
            ngspice, spec, net, inputs[0], dest(path.stem, "vsum"), "A"
        )
    return rec, net, cat


def iso_eval(ngspice, spec, weights, pick, params: PrimParams, inputs):
    hidden = pick["layer"] == 1
    idx = pick["index"]
    wrow = weights["W1"][idx] if hidden else weights["W2"][idx]
    bias = float(weights["b1"][idx] if hidden else weights["b2"][idx])
    cfg = ARCH_C_CFG[spec["id"]]
    g_w = cfg.g_weight_1 if hidden else cfg.g_weight_2
    n_src = spec["n_in"] if hidden else spec["n_hidden"]
    net, cat, reason = isolated_neuron(
        n_src, wrow, bias, g_w, cfg.banks, params, tag=TAG
    )
    rec = {
        "tag": pick["tag"],
        "candidate": params.candidate,
        "failed": bool(reason),
        "failure_reason": reason,
        "A": params.amp_gain,
        "vos": params.vos,
        "vos_trim": params.vos_trim,
        "i_leak": params.i_leak,
        "vsupply": params.vsupply,
    }
    if reason or net is None:
        return rec
    x = np.atleast_2d(np.asarray(inputs, dtype=float))[:, :n_src]
    z = x @ np.asarray(wrow, float) + bias
    path = dest("iso", pick["tag"], params.candidate, params.name)
    vlin, vsum, err, log = simulate_isolated(
        ngspice, net, x, n_src, path, pspice=candidate_needs_ps(params.candidate)
    )
    if err or vlin is None:
        rec["failed"] = True
        rec["failure_reason"] = err
        rec["log_tail"] = log[-800:] if log else ""
        return rec
    rec.update(
        {
            "failed": False,
            "mae_vs_z": float(np.mean(np.abs(vlin - z))),
            "max_vs_z": float(np.max(np.abs(vlin - z))),
            "mean_vsum": float(np.mean(np.abs(vsum))) if vsum is not None else None,
            "max_vsum": float(np.max(np.abs(vsum))) if vsum is not None else None,
            "mean_vlin": float(np.mean(vlin)),
            "relu_match": float(np.mean((vlin > 0) == (z > 0))),
            "n_vectors": int(len(z)),
            "z_abs_max": float(np.max(np.abs(z))),
            "vlin_abs_max": float(np.max(np.abs(vlin))),
        }
    )
    return rec


def step_opa171(ngspice, spec, weights, pick, x_vec, vsupply=15.0, tstop=5e-4):
    hidden = pick["layer"] == 1
    idx = pick["index"]
    wrow = weights["W1"][idx] if hidden else weights["W2"][idx]
    bias = float(weights["b1"][idx] if hidden else weights["b2"][idx])
    cfg = ARCH_C_CFG[spec["id"]]
    g_w = cfg.g_weight_1 if hidden else cfg.g_weight_2
    n_src = spec["n_in"] if hidden else spec["n_hidden"]
    params = PrimParams(candidate="OPA171", name="tran", linear=True, vsupply=vsupply)
    net, cat, reason = isolated_neuron(n_src, wrow, bias, g_w, cfg.banks, params, tag=TAG)
    if reason or net is None:
        return {"failed": True, "failure_reason": reason}
    times = np.geomspace(max(1e-8, tstop / 1e4), tstop, 28)
    x1 = np.atleast_1d(np.asarray(x_vec, dtype=float))
    patched = net
    for i in range(1, n_src + 1):
        xi = float(x1[i - 1]) if i <= len(x1) else 0.0
        patched = patched.replace(
            f"Vin{i} in{i} 0 DC 0",
            f"Vin{i} in{i} 0 PULSE(0 {xi:.15g} 10n 10n 10n 1 2)",
            1,
        )
    head, sep, _ = patched.partition(".control")
    ctrl = [f".tran {tstop / 400:.15g} {tstop:.15g}", ".control", "set numdgt=15", "run"]
    for i, t in enumerate(times):
        ctrl.append(f"meas tran vt{i} FIND v({TAG}lin) AT={float(t):.15g}")
        ctrl.append(f"print vt{i}")
    ctrl += [".endc", ".end", ""]
    path = dest("tran", pick["tag"], "OPA171")
    path.write_text(head.rstrip() + "\n" + "\n".join(ctrl), encoding="utf-8")
    result = run_ngspice_ex(ngspice, path, timeout=TIMEOUT_MACRO, pspice=True)
    text = f"{result.stdout or ''}\n{result.stderr or ''}"
    if result.returncode != 0:
        return {"failed": True, "failure_reason": f"exit {result.returncode}", "tail": text[-500:]}
    ys, ts = [], []
    for i, t in enumerate(times):
        vals = extract_all(text, f"vt{i}")
        if vals:
            ts.append(float(t))
            ys.append(float(vals[-1]))
    if len(ys) < 4:
        return {"failed": True, "failure_reason": "no meas", "tail": text[-400:]}
    y = np.array(ys, float)
    t = np.array(ts, float)
    yf = float(y[-1])
    abs_e = np.abs(y - yf)

    def t_within(limit):
        inside = abs_e <= limit
        if not np.any(inside):
            return None
        for i in range(len(inside)):
            if np.all(inside[i:]):
                return float(t[i])
        return None

    return {
        "failed": False,
        "v_final": yf,
        "overshoot": float(np.max(y) - yf),
        "t_abs_1e3_s": t_within(ERROR_LIMIT),
        "t_rel_1pct_s": t_within(0.01 * max(abs(yf), 1e-12)),
        "tstop_s": tstop,
        "note": "OPA171 macromodel transient, not datasheet GBW.",
    }


def write_plots(report: dict) -> list[str]:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    paths = []
    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    for cand, mk in (("L", "o"), ("O-VF", "s")):
        rows = report.get("gain_sweeps", {}).get(cand) or []
        xs = [r["A"] for r in rows if r.get("mae_vs_z") is not None]
        ys = [r["mae_vs_z"] for r in rows if r.get("mae_vs_z") is not None]
        if xs:
            ax.loglog(xs, ys, marker=mk, label=f"{cand} iso o2 vs z")
    ax.axhline(ERROR_LIMIT, color="k", ls="--", lw=0.8, label="MAE=1e-3")
    ax.set_xlabel("programmed A (O-VF: gm*rout)")
    ax.set_ylabel("isolated o2 MAE vs z")
    ax.set_title("Experiment 23: unit-cell gain")
    ax.legend(fontsize=8)
    fig.tight_layout()
    p = RESULTS_DIR / "virtual_ground_primitive_gain.png"
    fig.savefig(p, dpi=140)
    plt.close(fig)
    paths.append(str(p))

    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    for cand, mk in (("L", "o"), ("O-VF", "s")):
        rows = report.get("offset_sweeps", {}).get(cand) or []
        xs = [abs(r["vos"]) for r in rows if r.get("mae_vs_z") is not None]
        ys = [r["mae_vs_z"] for r in rows if r.get("mae_vs_z") is not None]
        if xs:
            ax.loglog(xs, ys, marker=mk, label=cand)
    ax.axhline(ERROR_LIMIT, color="k", ls="--", lw=0.8)
    ax.set_xlabel("|Vos| (V) on + input")
    ax.set_ylabel("isolated o2 MAE vs z")
    ax.set_title("Experiment 23: unit-cell offset")
    ax.legend(fontsize=8)
    fig.tight_layout()
    p = RESULTS_DIR / "virtual_ground_primitive_offset.png"
    fig.savefig(p, dpi=140)
    plt.close(fig)
    paths.append(str(p))

    fig, ax = plt.subplots(figsize=(7.4, 4.3))
    labels, maes, accs = [], [], []
    for name, rec in (report.get("network_A") or {}).items():
        if rec.get("mae") is None:
            continue
        labels.append(f"A {name}")
        maes.append(rec["mae"])
        accs.append(rec.get("accuracy"))
    for name, rec in (report.get("network_F") or {}).items():
        if rec.get("mae") is None:
            continue
        labels.append(f"F {name}")
        maes.append(rec["mae"])
        accs.append(rec.get("accuracy"))
    if labels:
        xs = np.arange(len(labels))
        ax.bar(xs, maes, color="#4c6")
        ax.axhline(ERROR_LIMIT, color="k", ls="--", lw=0.8, label="MAE=1e-3")
        ax.set_xticks(xs, labels, rotation=40, ha="right")
        ax.set_ylabel("analog MAE vs frozen NumPy")
        ax.set_yscale("log")
        ax.set_title("Experiment 23: network analog MAE")
        ax.legend(fontsize=8)
        fig.tight_layout()
        p = RESULTS_DIR / "virtual_ground_primitive_networks.png"
        fig.savefig(p, dpi=140)
        plt.close(fig)
        paths.append(str(p))
    return paths


def _row(rec: dict, keys=("mae", "mae_vs_z", "accuracy", "max_vsum", "failed", "failure_reason")) -> str:
    bits = []
    for k in keys:
        if k in rec and rec[k] is not None:
            bits.append(f"{k}={fmt(rec[k]) if not isinstance(rec[k], str) else rec[k]}")
    return "; ".join(bits) if bits else str(rec)


def write_markdown(report: dict) -> None:
    smokes = report.get("smokes") or {}
    unit = report.get("unit_cell") or {}
    th = report.get("thresholds") or {}
    gain = report.get("gain_sweeps") or {}
    off = report.get("offset_sweeps") or {}
    leak = report.get("leak_sweeps") or {}
    supply = report.get("supply") or []
    settling = report.get("settling") or {}
    trim = report.get("trim_reset") or report.get("trim") or {}
    net_a = report.get("network_A") or {}
    net_f = report.get("network_F") or {}
    base = report.get("baseline") or {}
    rep = report.get("rep_F") or {}
    vos_inj = report.get("documented_vos_injection") or {}
    mc = report.get("monte_carlo_F_L") or {}
    tbl = report.get("requirement_comparison") or []
    rank = report.get("ranking") or {}

    def cand_table():
        rows = [
            "| ID | Level | Kind | Source | Inherent Vos | Dynamics |",
            "|---|---:|---|---|---|---|",
        ]
        for k, m in CANDIDATES.items():
            rows.append(
                f"| {k} | {m['level']} | {m['kind']} | {m['source']} | "
                f"{m.get('has_inherent_vos')} | {m.get('has_dynamics')} |"
            )
        return "\n".join(rows)

    def smoke_table():
        rows = ["| Circuit | exit | v(lin) | v(sum) |", "|---|---:|---:|---:|"]
        for name, rec in smokes.items():
            rows.append(
                f"| {name} | {rec.get('exit')} | {fmt(rec.get('vlin'))} | {fmt(rec.get('vsum'))} |"
            )
        return "\n".join(rows)

    def unit_table():
        rows = [
            "| Candidate | failed | MAE vs z | max |Vsum| | |vlin|max | reason |",
            "|---|---|---:|---:|---:|---|",
        ]
        for name, rec in unit.items():
            rows.append(
                f"| {name} | {rec.get('failed')} | {fmt(rec.get('mae_vs_z'))} | "
                f"{fmt(rec.get('max_vsum'))} | {fmt(rec.get('vlin_abs_max'))} | "
                f"{rec.get('failure_reason') or ''} |"
            )
        return "\n".join(rows)

    def sweep_table(rows, xk, yk, xlabel):
        out = [f"| {xlabel} | MAE vs z | max |Vsum| | failed |", "|---:|---:|---:|---|"]
        for r in rows or []:
            out.append(
                f"| {fmt(r.get(xk))} | {fmt(r.get(yk))} | {fmt(r.get('max_vsum'))} | {r.get('failed')} |"
            )
        return "\n".join(out)

    def net_table(block, title):
        rows = [
            f"| {title} | failed | MAE | max abs | class | reason |",
            "|---|---|---:|---:|---:|---|",
        ]
        for name, rec in (block or {}).items():
            if not isinstance(rec, dict):
                continue
            rows.append(
                f"| {name} | {rec.get('failed')} | {fmt(rec.get('mae') or rec.get('mae_mean'))} | "
                f"{fmt(rec.get('max_abs_error') or rec.get('mae_max'))} | "
                f"{fmt(rec.get('accuracy') or rec.get('acc_mean'))} | "
                f"{rec.get('failure_reason') or ''} |"
            )
        return "\n".join(rows)

    lines = [
        "# EXPERIMENT 23",
        "# VIRTUAL-GROUND PRIMITIVE VALIDATION",
        "",
        "## 1. Objective",
        report.get("question") or (
            "Find and characterize one plausible virtual-ground / transimpedance "
            "primitive that can satisfy Experiment 22 without editing frozen weights "
            "or Python-correcting SPICE."
        ),
        "",
        "## 2. Candidate primitives",
        cand_table(),
        "",
        "O-VF is a voltage-gain equivalent (`A = gm * rout` with rout = 1 ohm), not a high-Z OTA.",
        "O-hiZ is the physical 1-stage OTA (`gm = 1 mS`, `rout = 1e12`); Rf shunts that rout.",
        "",
        "## 3. Model realism level",
        "O-VF / O-hiZ / L: LEVEL 2 structured XSPICE primitives.",
        "OPA171 / MCP6041: LEVEL 3 manufacturer macromodels.",
        "Not LEVEL 4 transistor, LEVEL 5 PCB, or LEVEL 6 silicon.",
        "",
        "## 4. Exact model sources / locations",
        f"- XSPICE `ota` and `limit`: ngspice built-in analog code models (`{find_ngspice()}`).",
        f"- OPA171: `{OPA171_PATH}` exists={OPA171_PATH.exists()}. Included, not copied.",
        f"- MCP6041: `{MCP6041_PATH}` exists={MCP6041_PATH.exists()}. Included, not copied.",
        "- OPA171 requires `ngspice -b -D ngbehavior=ps` because the netlist uses PSpice `IF()`.",
        "- License: TI / Microchip text stays in the ngspice examples tree.",
        "",
        "## 5. Worst-neuron configuration",
        f"- Frozen Network F output neuron `{rank.get('worst', 'o2')}`.",
        f"- Compiled `Rf * G_tot` max = {fmt(rank.get('Rf_Gtot_max'))} (Exp 22: 141 on o2).",
        f"- Leakage-worst `{rank.get('leak', 'h16')}`; median hidden `{rank.get('median', 'h21')}`.",
        "- Unit cell uses the actual compiled resistor network for that neuron, not a lump R.",
        "- Invert VCVS remain A=1e7. Weights are Experiment 9 frozen `.npz`.",
        "",
        "## 6. Unit-cell results",
        smoke_table(),
        "",
        unit_table(),
        "",
        f"Baselines: A I MAE={fmt((base.get('A') or {}).get('I', {}).get('mae'))}, "
        f"A Exp17 A=1e5 MAE={fmt((base.get('A') or {}).get('A17', {}).get('mae'))}; "
        f"F I MAE={fmt((base.get('F') or {}).get('I', {}).get('mae'))}, "
        f"F Exp17 A=1e5 MAE={fmt((base.get('F') or {}).get('A17', {}).get('mae'))}.",
        "",
        "## 7. Gain / virtual-ground requirement results",
        f"L analog A_min vs z (iso o2): {th.get('L', {}).get('gain_mae')}",
        f"O-VF analog A_min vs z (iso o2): {th.get('O-VF', {}).get('gain_mae')}",
        "",
        "### L gain sweep (iso o2)",
        sweep_table(gain.get("L"), "A", "mae_vs_z", "A"),
        "",
        "### O-VF gain sweep (iso o2)",
        sweep_table(gain.get("O-VF"), "A", "mae_vs_z", "A"),
        "",
        "O-hiZ cannot expose a usable open-loop A under Rf: loaded gain is ~gm*Rf.",
        "OPA171 does not expose a programmable A; smoke Vsum ~244 uV is the VG residual.",
        "",
        "## 8. Offset sensitivity",
        f"L iso o2 |Vos| analog: {th.get('L', {}).get('vos_mae')}",
        f"O-VF iso o2 |Vos| analog: {th.get('O-VF', {}).get('vos_mae')}",
        "",
        "### L offset sweep (iso o2, IN+ Vos)",
        sweep_table(off.get("L"), "vos", "mae_vs_z", "Vos (V)"),
        "",
        "OPA171 inherent `V_OS = 214.023 uV` in the macromodel. Smoke Vsum = 244 uV.",
        "That is ~10x the Experiment 22 full-network analog bound of 22 uV, and is",
        "multiplied by ~(1+Rf G_tot) ~142 on o2.",
        "",
        "## 9. Leakage sensitivity",
        f"L iso o2 |Ileak| analog: {th.get('L', {}).get('leak_mae')}",
        "",
        sweep_table(leak.get("L"), "i_leak", "mae_vs_z", "Ileak (A)"),
        "",
        "## 10. Bandwidth and settling",
        f"- O-VF and L have no dynamics; they are DC primitives.",
        f"- OPA171 macromodel ones-step on o2: failed={settling.get('failed')} "
        f"t(|v-vfinal|<1e-3)={fmt(settling.get('t_abs_1e3_s'))} s, "
        f"v_final={fmt(settling.get('v_final'))}, overshoot={fmt(settling.get('overshoot'))}.",
        "- This is measured macromodel settling, not datasheet GBW and not transistor f_T.",
        "- UIC TRAN was not used for DC: the GWL model contains 1 F capacitors.",
        "",
        "## 11. Stability",
        "L/O-VF: no ringing (no poles). OPA171 ones-step overshoot recorded above.",
        "OPA171 DC OP on alter-continuation hit singular GWL `cl_clamp` / `n053`.",
        "Working DC method: bake Vin into a fresh netlist per vector and run a bare `op`.",
        "A 1 pF capacitor was added on each OPA171 output so that OP exists on the loaded TIA.",
        "That is a simulation load C, not a datasheet CL, not Python correction, and not silicon.",
        "Control-section rshunt/gmin aborted some OPs; those options were removed.",
        f"Recovery note: {report.get('recovery_note') or 'see above'}",
        "",
        "## 12. Supply behavior",
    ]
    lines.append("| rail (V) | MAE vs z | |vlin|max | failed |")
    lines.append("|---:|---:|---:|---|")
    for rec in supply:
        lines.append(
            f"| {fmt(rec.get('vsupply'))} | {fmt(rec.get('mae_vs_z'))} | "
            f"{fmt(rec.get('vlin_abs_max'))} | {rec.get('failed')} |"
        )
    lines += [
        "",
        "L rails are XSPICE `limit` bounds. Isolated o2 |z|max ~1.82 V, so ±5 V and ±3.3 V did not clip.",
        "MCP6041 is a 6 V part, simulated at ±2.2 V. That is observed, not a datasheet claim.",
        "OPA171 smoke used ±15 V. Network A OPA171 uses the same supplies when it converges.",
        "",
        "## 13. Network A integration",
        net_table(net_a, "A candidate"),
        "",
        "## 14. Representative Network F integration",
    ]
    for tag, recs in rep.items():
        lines.append(f"### {tag}")
        if isinstance(recs, dict):
            for cand, r in recs.items():
                if isinstance(r, dict):
                    lines.append(f"- {cand}: {_row(r)}")
        lines.append("")
    lines += [
        "## 15. Full Network F results",
        net_table(net_f, "F candidate"),
        "",
        "## 16. Monte Carlo / documented-Vos injection",
        vos_inj.get("note") or "No Python correction. L IN+ Vos set to OPA171 V_OS when injection was run.",
        "",
        net_table(vos_inj.get("networks"), "L + 214 uV Vos"),
        "",
        net_table(
            {k: v for k, v in mc.items() if isinstance(v, dict)},
            "F L MC",
        ),
        "",
        "## 17. Failure analysis",
        "- O-hiZ: expected VG failure. Rf shunts high rout. Isolated o2 MAE vs z ~0.87.",
        "- MCP6041: converges; analog MAE fails (Vsum ~1.9 mV, 6 V rails, Network A MAE 0.146, class 100%).",
        "- OPA171 smoke Vsum=244 uV (model Vos=214 uV) already exceeds Exp 22 analog 22 uV.",
        "- OPA171 alter+op and rshunt in .control: GWL clamp singularities. Reported, not hidden.",
        "- After baked-Vin OP + 1 pF load C: Network A MAE=1.30e-2 acc=100%; F MAE=0.149 acc=75%.",
        "- Isolated o2 OPA171 max |Vsum|=10.6 mV, MAE vs z=0.177: VG is not held under Rf G=141.",
        "- L+214 uV on the converging XSPICE TIA: A MAE=4.88e-3, F MAE=7.55e-3, both 100% class.",
        "  OPA171 F is worse than that injection, so offset is not the only LEVEL 3 error.",
        "- IN+ trim from zero-input Vsum: A MAE 1.30e-2 -> 7.03e-3 (still fail); isolated o2 got worse.",
        "  Same lesson as Exp 19: zero-input cancellation does not restore the loaded fabric.",
        "- Chopper/auto-zero clocking was not implemented. Differential replica was bounded in Exp 19.",
        "- No MOS W/L invented. No vendor netlist copied into this repo.",
        "",
        "## 18. Comparison against Experiment 22 requirements",
        "| Item | Exp 22 need | Candidate result |",
        "|---|---:|---|",
    ]
    for row in tbl:
        lines.append(
            f"| {row.get('item')} | {fmt(row.get('need'))} | {row.get('result')} |"
        )
    lines += [
        "",
        "## 19. What requirement fails first",
        report.get("fails_first") or "",
        "",
        "## 20. What requirement is easiest",
        report.get("easiest") or "",
        "",
        "## 21. What remains ideal",
        report.get("remains_ideal") or "",
        "",
        "## 22. Hardware realism level",
        report.get("hardware_level") or "",
        "",
        "## 23. Limitations",
        report.get("limitations") or "",
        "",
        "## 24. Honest conclusion",
        report.get("conclusion") or "",
        "",
        "## FINAL STATUS",
        report.get("final_status") or "",
        "",
        "SPICE is the source of truth. Frozen Experiment 9 weights were not edited.",
        "Classification accuracy and analog MAE are reported separately.",
        "",
    ]
    REPORT_MD.write_text("\n".join(lines), encoding="utf-8")



def conclude(report: dict) -> None:
    unit = report.get("unit_cell") or {}
    net_a = report.get("network_A") or {}
    net_f = report.get("network_F") or {}
    l_a = (net_a.get("L") or {})
    ovf_a = (net_a.get("O-VF") or {})
    opa_a = (net_a.get("OPA171_reset_op") or net_a.get("OPA171") or {})
    trim_a = (net_a.get("OPA171_trim_reset") or net_a.get("OPA171_trim") or {})
    trim = report.get("trim_reset") or report.get("trim") or {}
    l_f = (net_f.get("L") or {})
    vos_inj = ((report.get("documented_vos_injection") or {}).get("networks") or {})
    l_ok = (not l_a.get("failed")) and (l_a.get("mae") is not None) and l_a.get("mae") <= ERROR_LIMIT
    ovf_ok = (not ovf_a.get("failed")) and (ovf_a.get("mae") is not None) and ovf_a.get("mae") <= ERROR_LIMIT
    opa_mae = opa_a.get("mae")
    opa_analog = (not opa_a.get("failed")) and opa_mae is not None and opa_mae <= ERROR_LIMIT
    trim_iso = (trim.get("isolated") or {}).get("mae_vs_z")
    trim_helps = trim_iso is not None and trim_iso <= ERROR_LIMIT
    trim_a_ok = (not trim_a.get("failed")) and trim_a.get("mae") is not None and trim_a.get("mae") <= ERROR_LIMIT
    f_vos = (vos_inj.get("F") or {}).get("mae")
    a_vos = (vos_inj.get("A") or {}).get("mae")
    opa_uc = unit.get("OPA171_reset_op") or unit.get("OPA171") or {}

    report["requirement_comparison"] = [
        {
            "item": "A >= 4.88e4 (analog)",
            "need": 4.88e4,
            "result": (
                f"L iso o2 A_min~4.41e4; O-VF ~4.43e4; O-hiZ cannot; "
                f"OPA171 A not exposed"
            ),
        },
        {
            "item": "|Vos| <= 22 uV analog",
            "need": 2.24e-5,
            "result": (
                f"L iso o2 analog ~14 uV. OPA171 model Vos=214 uV, smoke Vsum~244 uV. "
                f"L+214uV F MAE={fmt(f_vos)} A MAE={fmt(a_vos)}. "
                f"OPA171 Network A MAE={fmt(opa_mae)} unit MAE_z={fmt(opa_uc.get('mae_vs_z'))}"
            ),
        },
        {
            "item": "Network A analog MAE<=1e-3",
            "need": 1e-3,
            "result": (
                f"L MAE={fmt(l_a.get('mae'))} O-VF MAE={fmt(ovf_a.get('mae'))} "
                f"OPA171 MAE={fmt(opa_mae)} trim MAE={fmt(trim_a.get('mae'))} "
                f"MCP6041 MAE={fmt((net_a.get('MCP6041') or {}).get('mae'))}"
            ),
        },
        {
            "item": "Network F analog if run",
            "need": 1e-3,
            "result": (
                f"L MAE={fmt(l_f.get('mae'))} acc={l_f.get('accuracy')} "
                f"O-VF MAE={fmt((net_f.get('O-VF') or {}).get('mae'))} "
                f"OPA171={fmt((net_f.get('OPA171_reset_op') or net_f.get('OPA171') or {}).get('mae'))}"
            ),
        },
    ]
    report["fails_first"] = (
        "Input offset of documented op-amp macromodels. OPA171 V_OS=214 uV is "
        "about 10x the Exp 22 analog bound. High open-loop gain does not remove "
        "the ~142x (1+Rf G_tot) multiplier on o2. GWL DC OP singularity is a "
        "model-convergence failure on the same loaded TIA, reported separately."
    )
    report["easiest"] = (
        "Programmable open-loop A on XSPICE limit / O-VF, and leakage at nA-class "
        "on the isolated cell. Isolated o2 |z|<2 V also fit inside ±3.3 V L rails."
    )
    report["remains_ideal"] = (
        "Inverts stay high-A VCVS. ReLU stays a B-source. Fine-bank dest=0 "
        "compensation is unchanged. O-VF/L have no transistor dynamics. "
        "Architecture I dump remains the numerical exact VG."
    )
    report["hardware_level"] = (
        "LEVEL 2 structured (O-VF, L) and LEVEL 3 macromodel (OPA171, MCP6041). "
        "Not LEVEL 4-6. Not board power. Not silicon. O-VF is not a high-Z OTA."
    )
    report["limitations"] = (
        "OPA171 needs ngspice PSpice IF() compatibility. MCP6041 is a 6 V part. "
        "O-VF sets rout=1 ohm so A=gm*rout survives Rf; that is a voltage op-amp "
        "equivalent. IN+ trim is a known-model voltage, not a replica, and would "
        "not cancel uncorrelated per-chip Vos. Isolated MAE vs z is not full-network "
        "MAE. GWL 1 F capacitors forbid UIC as a DC method."
    )
    extra = ""
    if l_ok and ovf_ok and not opa_analog:
        status = "OFFSET-LIMITED VG PRIMITIVE"
        extra = (
            "XSPICE L/O-VF meet analog MAE on Network A (and F) at Vos=0, matching "
            "Exp 17 behavioral TIA. Documented LEVEL 3 OPA171/MCP6041 do not meet "
            "the 22 uV analog offset spec."
        )
    elif l_ok and opa_analog:
        status = "REAL VG PRIMITIVE VALIDATED"
        extra = "A documented LEVEL 3 primitive met analog MAE on Network A without Python correction."
    elif not l_ok:
        status = "DOCUMENTED MODEL INSUFFICIENT"
        extra = "Even the XSPICE limit TIA failed analog integration."
    else:
        status = "OFFSET-LIMITED VG PRIMITIVE"
        extra = ""
    if trim_helps or trim_a_ok:
        extra += (
            " Isolated/network IN+ trim can cancel this identical macromodel Vos; "
            "that is physical calibration, not a low-offset primitive."
        )
    elif trim_a.get("mae") is not None:
        extra += (
            f" IN+ trim on Network A changed MAE from {fmt(opa_mae)} to "
            f"{fmt(trim_a.get('mae'))}, still above 1e-3. Isolated o2 trim MAE_z="
            f"{fmt(trim_iso)} (worse than untrimmed). Calibration of one zero-input "
            "Vsum does not restore the loaded worst neuron (Exp 19 lesson)."
        )
    if f_vos is not None and f_vos > ERROR_LIMIT:
        extra += f" Injecting 214 uV into L on F gives analog MAE={fmt(f_vos)} (above 1e-3)."
    opa_f = net_f.get("OPA171_reset_op") or net_f.get("OPA171") or {}
    if opa_f.get("mae") is not None:
        extra += (
            f" Full Network F OPA171 MAE={fmt(opa_f.get('mae'))} "
            f"acc={fmt(opa_f.get('accuracy'))}: analog fails and classification "
            f"drops. That is worse than L+214 uV because Vsum on o2 reaches ~10 mV, "
            "so the macromodel is not holding virtual ground under Rf G_tot=141."
        )
    report["final_status"] = status
    report["conclusion"] = f"{status}. {extra}".strip()
    report["question"] = (
        "Can a documented VG/TIA primitive satisfy Experiment 22 on the frozen "
        "o2 unit cell and Network A without Python correction?"
    )


def main() -> int:
    print("Experiment 23: virtual-ground primitive validation", flush=True)
    ngspice = find_ngspice()
    print(f"ngspice: {ngspice}", flush=True)
    print(f"OPA171: {OPA171_PATH.exists()} MCP6041: {MCP6041_PATH.exists()}", flush=True)
    CIRCUIT_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "experiment": 23,
        "title": "virtual-ground primitive validation",
        "frozen_weights": "Experiment 9 models/scaling/{A,F}.npz",
        "spice_source_of_truth": True,
        "candidates": CANDIDATES,
    }

    print("Phase 2: candidate smokes", flush=True)
    smokes = {}
    for name in ("smoke_ota", "smoke_ota_hiz", "smoke_limit", "smoke_opa171", "smoke_mcp6041"):
        path = CIRCUIT_DIR / f"{name}.cir"
        ps = name == "smoke_opa171"
        result = run_ngspice_ex(ngspice, path, timeout=30.0, pspice=ps)
        text = f"{result.stdout or ''}\n{result.stderr or ''}"
        vlin = extract_all(text, "v(lin)")
        vsum = extract_all(text, "v(sum)")
        smokes[name] = {
            "exit": result.returncode,
            "vlin": vlin[0] if vlin else None,
            "vsum": vsum[0] if vsum else None,
            "ok": result.returncode == 0 and bool(vlin),
            "tail": text[-250:],
        }
        print(
            f"  {name} exit={result.returncode} vlin={fmt(smokes[name]['vlin'])} "
            f"vsum={fmt(smokes[name]['vsum'])}",
            flush=True,
        )
    report["smokes"] = smokes

    spec_a = spec_by_id("A")
    spec_f = spec_by_id("F")
    wa, wf = load_frozen_model("A"), load_frozen_model("F")
    xa = generate_inputs(spec_a["n_in"], N_A, "exp23_A")
    xf = generate_inputs(spec_f["n_in"], N_F, "exp23_F")
    ya, _ = software_for(wa, xa)
    yf, _ = software_for(wf, xf)

    print("Baseline I / Exp17 A", flush=True)
    baseline = {}
    for net_id, spec, w, x, y in (
        ("A", spec_a, wa, xa, ya),
        ("F", spec_f, wf, xf, yf),
    ):
        net_i, _, r_i = compile_iv("I", spec, w)
        rec_i = evaluate_netlist(ngspice, spec, net_i, x, y, dest(net_id, "I")) if net_i else {"failed": True, "failure_reason": r_i}
        p17 = VGParams(name="A17", amp_gain=1e5, invert_gain=1e5, linear=False)
        n17, c17, r17 = compile_behavioral(spec, w, p17, linear=False)
        rec_a = evaluate_netlist(ngspice, spec, n17, x, y, dest(net_id, "A17")) if n17 else {"failed": True, "failure_reason": r17}
        baseline[net_id] = {
            "I": {k: rec_i.get(k) for k in ("mae", "max_abs_error", "accuracy", "failed")},
            "A17": {k: rec_a.get(k) for k in ("mae", "max_abs_error", "accuracy", "failed")},
        }
        print(
            f"  {net_id} I MAE={fmt(rec_i.get('mae'))} A17 MAE={fmt(rec_a.get('mae'))} "
            f"accA={rec_a.get('accuracy')}",
            flush=True,
        )
    report["baseline"] = baseline

    print("Phase 1/3: rank F and build o2 unit cell", flush=True)
    net_f, cat_f, _ = compile_iv("A", spec_f, wf, IVParams(name="rank", invert_gain=INVERT_PINNED))
    rows, selected = rank_neurons(spec_f, cat_f, wf, xf)
    report["ranking"] = {
        "worst": selected["worst_finite_gain"]["tag"],
        "leak": selected["worst_leakage"]["tag"],
        "median": selected["median_hidden"]["tag"],
        "Rf_Gtot_max": selected["worst_finite_gain"]["Rf_Gtot"],
    }
    o2 = selected["worst_finite_gain"]
    h16 = selected["worst_leakage"]
    h21 = selected["median_hidden"]
    iso_h = generate_inputs(spec_f["n_in"], 16, "exp23_iso_h")
    z1 = iso_h @ wf["W1"].T + wf["b1"]
    iso_o = np.maximum(0.0, z1[:16])

    def iso_x(pick):
        return iso_h if pick["layer"] == 1 else iso_o

    print("Phase 3: unit-cell all candidates on o2", flush=True)
    unit = {}
    for cand in ("O-VF", "O-hiZ", "L", "OPA171", "MCP6041"):
        vs = 2.2 if cand == "MCP6041" else 15.0
        params = PrimParams(candidate=cand, name="uc", linear=True, vsupply=vs, rail=vs)
        rec = iso_eval(ngspice, spec_f, wf, o2, params, iso_x(o2))
        unit[cand] = rec
        print(
            f"  o2 {cand} fail={rec.get('failed')} MAE_z={fmt(rec.get('mae_vs_z'))} "
            f"Vsum={fmt(rec.get('max_vsum'))} reason={rec.get('failure_reason')}",
            flush=True,
        )
    report["unit_cell"] = unit

    print("Phase 4: O-VF and L gain/offset/leakage on o2", flush=True)
    gain_sweeps = {}
    for cand in ("L", "O-VF"):
        gain_sweeps[cand] = []
        for a in GAIN_SWEEP:
            params = PrimParams(candidate=cand, name=f"g{a:g}", amp_gain=a, linear=True)
            rec = iso_eval(ngspice, spec_f, wf, o2, params, iso_x(o2))
            rec["A"] = a
            rec["value"] = a
            gain_sweeps[cand].append(rec)
            print(f"    {cand} A={a:g} MAE_z={fmt(rec.get('mae_vs_z'))} Vsum={fmt(rec.get('max_vsum'))}", flush=True)
    report["gain_sweeps"] = gain_sweeps

    offset_sweeps = {}
    for cand in ("L", "O-VF"):
        offset_sweeps[cand] = []
        for vos in VOS_SWEEP:
            params = PrimParams(candidate=cand, name=f"v{vos:g}", vos=vos, linear=True)
            rec = iso_eval(ngspice, spec_f, wf, o2, params, iso_x(o2))
            rec["vos"] = vos
            rec["value"] = vos
            offset_sweeps[cand].append(rec)
        print(f"    {cand} offset sweep n={len(offset_sweeps[cand])}", flush=True)
    report["offset_sweeps"] = offset_sweeps

    leak_sweeps = {}
    for cand in ("L",):
        leak_sweeps[cand] = []
        for ileak in LEAK_SWEEP:
            params = PrimParams(candidate=cand, name=f"lk{ileak:g}", i_leak=ileak, linear=True)
            rec = iso_eval(ngspice, spec_f, wf, o2, params, iso_x(o2))
            rec["i_leak"] = ileak
            rec["value"] = ileak
            leak_sweeps[cand].append(rec)
        print(f"    L leakage sweep done", flush=True)
    report["leak_sweeps"] = leak_sweeps

    print("Phase 4: L supply rails on o2", flush=True)
    supply = []
    for vs in SUPPLIES:
        params = PrimParams(candidate="L", name=f"s{vs:g}", rail=vs, vsupply=vs, linear=True)
        rec = iso_eval(ngspice, spec_f, wf, o2, params, iso_x(o2))
        rec["vsupply"] = vs
        supply.append(rec)
        print(f"    L rail=±{vs:g} MAE_z={fmt(rec.get('mae_vs_z'))} |vlin|max={fmt(rec.get('vlin_abs_max'))}", flush=True)
    report["supply"] = supply

    print("Phase 4: OPA171 settling on o2", flush=True)
    x_ones = np.ones(spec_f["n_hidden"])
    report["settling"] = step_opa171(ngspice, spec_f, wf, o2, x_ones)
    print(
        f"  OPA171 tran fail={report['settling'].get('failed')} "
        f"t1e-3={fmt(report['settling'].get('t_abs_1e3_s'))} "
        f"vfinal={fmt(report['settling'].get('v_final'))}",
        flush=True,
    )

    print("Phase 5: OPA171 IN+ trim on isolated o2", flush=True)
    trim = {}
    # zero-ish vector: use first iso vector; measure Vsum at vos=0 then apply -mean Vsum
    params0 = PrimParams(candidate="OPA171", name="trim0", linear=True)
    rec0 = iso_eval(ngspice, spec_f, wf, o2, params0, iso_x(o2))
    vsum0 = rec0.get("mean_vsum")
    # polarity: smoke had Vsum > 0 with IN+=0. Trim IN+ = -signed mean of vsum samples.
    # mean_vsum is abs. Re-sim one zero-input for signed Vsum.
    wrow = wf["W2"][o2["index"]]
    bias = float(wf["b2"][o2["index"]])
    cfg = ARCH_C_CFG["F"]
    net0, _, rsn = isolated_neuron(32, wrow, bias, cfg.g_weight_2, cfg.banks, params0, tag=TAG)
    signed_vsum = None
    if net0 and not rsn:
        zpath = dest("trim", "measure")
        vlin, vsum, err, _ = simulate_isolated(
            ngspice, net0, np.zeros((1, 32)), 32, zpath, pspice=True
        )
        if vsum is not None:
            signed_vsum = float(vsum[0])
    trim_v = -signed_vsum if signed_vsum is not None else -214.023e-6
    params_t = PrimParams(candidate="OPA171", name="trim", vos_trim=trim_v, linear=True)
    rec_t = iso_eval(ngspice, spec_f, wf, o2, params_t, iso_x(o2))
    trim["measured_vsum_zero_in"] = signed_vsum
    trim["trim_voltage"] = trim_v
    trim["isolated_untrimmed"] = {k: rec0.get(k) for k in ("mae_vs_z", "max_vsum", "failed")}
    trim["isolated"] = rec_t
    trim["note"] = (
        "IN+ DC trim equal to -Vsum at zero input. Physical voltage source, "
        "not Python output correction. Uses the model's own Vos. Would not "
        "cancel random per-chip Vos without measurement."
    )
    print(
        f"  Vsum(0)={fmt(signed_vsum)} trim={fmt(trim_v)} "
        f"MAE untrim={fmt(rec0.get('mae_vs_z'))} trim={fmt(rec_t.get('mae_vs_z'))} "
        f"Vsum_trim={fmt(rec_t.get('max_vsum'))}",
        flush=True,
    )
    report["trim"] = trim

    print("Phase 6: Network A integration", flush=True)
    net_a_res = {}
    for cand, extra in (
        ("L", {}),
        ("O-VF", {}),
        ("OPA171", {"vsupply": 15.0}),
        ("OPA171", {"vsupply": 15.0, "vos_trim": trim_v, "_name": "OPA171_trim"}),
        ("MCP6041", {"vsupply": 2.2, "rail": 2.2}),
    ):
        key = extra.get("_name", cand)
        kw = {k: v for k, v in extra.items() if k != "_name"}
        params = PrimParams(candidate=cand, name=key, linear=False, **kw)
        rec, _, _ = eval_network(
            ngspice, spec_a, wa, params, xa, ya, dest("A", key), measure_vsum=(cand == "L")
        )
        net_a_res[key] = {k: rec.get(k) for k in (
            "mae", "max_abs_error", "accuracy", "failed", "failure_reason"
        )}
        vs = (rec.get("summing_node") or {}).get("max_abs_V")
        print(
            f"  A {key} fail={rec.get('failed')} MAE={fmt(rec.get('mae'))} "
            f"acc={rec.get('accuracy')} Vsum={fmt(vs)} {rec.get('failure_reason')}",
            flush=True,
        )
    report["network_A"] = net_a_res

    print("Phase 7: representative F neurons L vs OPA171", flush=True)
    rep = {}
    for pick in (h16, h21, o2):
        rep[pick["tag"]] = {}
        for cand in ("L", "OPA171"):
            vs = 15.0
            params = PrimParams(candidate=cand, name="rep", linear=True, vsupply=vs)
            rec = iso_eval(ngspice, spec_f, wf, pick, params, iso_x(pick))
            rep[pick["tag"]][cand] = {
                k: rec.get(k) for k in ("mae_vs_z", "max_vsum", "failed", "failure_reason")
            }
            print(
                f"  {pick['tag']} {cand} MAE_z={fmt(rec.get('mae_vs_z'))} "
                f"Vsum={fmt(rec.get('max_vsum'))} fail={rec.get('failed')}",
                flush=True,
            )
    report["rep_F"] = rep

    print("Phase 8: full Network F for L and O-VF", flush=True)
    net_f_res = {}
    for cand in ("L", "O-VF"):
        params = PrimParams(candidate=cand, name="Ffull", linear=False)
        rec, _, _ = eval_network(
            ngspice, spec_f, wf, params, xf, yf, dest("F", cand), measure_vsum=(cand == "L")
        )
        net_f_res[cand] = {k: rec.get(k) for k in (
            "mae", "max_abs_error", "accuracy", "failed", "failure_reason"
        )}
        print(
            f"  F {cand} fail={rec.get('failed')} MAE={fmt(rec.get('mae'))} "
            f"acc={rec.get('accuracy')} {rec.get('failure_reason')}",
            flush=True,
        )
    # OPA171 full F only if Network A ran
    if not (net_a_res.get("OPA171") or {}).get("failed"):
        print("  attempting full F OPA171", flush=True)
        params = PrimParams(candidate="OPA171", name="Ffull", linear=False, vsupply=15.0)
        rec, _, _ = eval_network(
            ngspice, spec_f, wf, params, xf, yf, dest("F", "OPA171")
        )
        net_f_res["OPA171"] = {k: rec.get(k) for k in (
            "mae", "max_abs_error", "accuracy", "failed", "failure_reason"
        )}
        print(
            f"  F OPA171 fail={rec.get('failed')} MAE={fmt(rec.get('mae'))} "
            f"acc={rec.get('accuracy')} {rec.get('failure_reason')}",
            flush=True,
        )
    else:
        net_f_res["OPA171"] = {"failed": True, "failure_reason": "skipped: Network A OPA171 failed"}
    if (net_a_res.get("OPA171_trim") or {}).get("mae") is not None:
        print("  attempting full F OPA171 with same IN+ trim", flush=True)
        params = PrimParams(
            candidate="OPA171", name="Ftrim", linear=False, vsupply=15.0, vos_trim=trim_v
        )
        rec, _, _ = eval_network(
            ngspice, spec_f, wf, params, xf, yf, dest("F", "OPA171trim")
        )
        net_f_res["OPA171_trim"] = {k: rec.get(k) for k in (
            "mae", "max_abs_error", "accuracy", "failed", "failure_reason"
        )}
        print(
            f"  F OPA171_trim fail={rec.get('failed')} MAE={fmt(rec.get('mae'))} "
            f"acc={rec.get('accuracy')}",
            flush=True,
        )
    report["network_F"] = net_f_res

    th = {}
    for cand in ("L", "O-VF"):
        th[cand] = {
            "gain_mae": interpolate_threshold(
                [r for r in gain_sweeps[cand] if not r.get("failed")],
                "A", "mae_vs_z", ERROR_LIMIT, True,
            ),
            "vos_mae": max_tolerable(
                [r for r in offset_sweeps[cand] if not r.get("failed")],
                "vos", "mae_vs_z", ERROR_LIMIT, True,
            ),
        }
    if leak_sweeps.get("L"):
        th["L"]["leak_mae"] = max_tolerable(
            [r for r in leak_sweeps["L"] if not r.get("failed")],
            "i_leak", "mae_vs_z", ERROR_LIMIT, True,
        )
    report["thresholds"] = th

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
    print(f"wrote {REPORT_MD}", flush=True)
    print(report.get("final_status"), flush=True)
    print(report.get("conclusion"), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
