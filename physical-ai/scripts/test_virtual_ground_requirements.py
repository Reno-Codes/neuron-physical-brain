"""Experiment 22: virtual-ground TIA requirement extraction.

Frozen Experiment 9 networks A and F. Architecture I and Architecture A
baselines are reproduced first. SPICE is never Python-corrected.
Device-level MOS is not used.
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
from compile_xor import PROJECT_ROOT, apply_resistor_values, find_ngspice, run_ngspice
from hardware_constrained_compiler import load_frozen_model
from physical_iv_neuron import IVParams, compile_iv, neuron_tags
from precision_architectures import ARCH_C_CFG, hidden_preact_max, software_reference
from test_hardware_constraints import spec_by_id
from test_iv_architectures import ERROR_LIMIT, evaluate_netlist, measure_sum_nodes
from test_nonideal_network import class_margins
from test_robustness import extract_all
from finite_a_scale import neuron_k_factors, predict_neuron
from passive_iv import neuron_gtot
from virtual_ground_requirements import (
    CIRCUIT_DIR,
    INVERT_PINNED,
    VGParams,
    apply_tia_pole,
    closed_loop_tau,
    compile_network,
    finite_a_gain_error,
    generate_isolated_neuron,
    interpolate_threshold,
    isolated_batch_control,
    leak_to_vout_gain,
    max_tolerable,
    rank_neurons,
    tia_k,
    vos_to_vout_gain,
)


RESULTS_DIR = PROJECT_ROOT / "results"
REPORT_JSON = RESULTS_DIR / "virtual_ground_requirements_report.json"
REPORT_MD = RESULTS_DIR / "exp22_virtual_ground_requirements.md"
WORST_JSON = RESULTS_DIR / "virtual_ground_worst_neurons.json"
TIMEOUT = 45.0
N_A = 100
N_F = 40
RAIL = 15.0
TAG = "n1"

GAIN_SWEEP = (1e2, 3e2, 1e3, 3e3, 1e4, 3e4, 1e5, 3e5, 1e6, 3e6, 1e7)
VOS_ABS = (1e-6, 3e-6, 1e-5, 3e-5, 1e-4, 3e-4, 1e-3, 3e-3, 1e-2)
LEAK_ABS = (1e-12, 1e-11, 1e-10, 1e-9, 1e-8, 1e-7, 1e-6)
ROUT_SWEEP = (0.0, 10.0, 100.0, 1e3, 1e4, 1e5)
POLE_HZ = (10.0, 100.0, 1e3, 1e4, 1e5, 1e6)
POLE_SUBSET = (10.0, 1e3, 1e5)
COMB_A = (1e3, 1e4, 1e5, 1e6)
COMB_VOS = (0.0, 1e-4, 1e-3)
COMB_LEAK = (0.0, 1e-9, 1e-8)


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


def simulate_isolated(ngspice, net, inputs, n_in, path, tag=TAG):
    head, sep, _ = net.partition(".control")
    if not sep:
        return None, None, "no .control", ""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(head.rstrip() + "\n" + isolated_batch_control(inputs, n_in, tag), encoding="utf-8")
    t0 = time.perf_counter()
    result = run_ngspice(ngspice, path, timeout=TIMEOUT)
    rt = time.perf_counter() - t0
    text = f"{result.stdout or ''}\n{result.stderr or ''}"
    if result.returncode != 0:
        return None, None, f"ngspice exit {result.returncode}", text[-1500:]
    vlin = extract_all(text, f"v({tag}lin)")
    vsum = extract_all(text, f"v({tag}p)")
    if len(vlin) != len(inputs):
        return None, None, f"expected {len(inputs)} v({tag}lin), got {len(vlin)}", text[-1500:]
    return np.array(vlin, float), np.array(vsum, float) if len(vsum) == len(vlin) else None, None, text[-500:]


def eval_network(ngspice, spec, weights, params: VGParams, inputs, y, path, measure_vsum=False):
    net, cat, reason = compile_network(spec, weights, params, linear=False)
    rec = {"failed": True, "failure_reason": reason, "params": params.public()}
    if reason or net is None:
        return rec, net, cat
    path.write_text(net, encoding="utf-8")
    rec = evaluate_netlist(ngspice, spec, net, inputs, y, path)
    rec["params"] = params.public()
    rec["n_resistors"] = len(cat)
    if measure_vsum and not rec.get("failed"):
        rec["summing_node"] = measure_sum_nodes(
            ngspice, spec, net, inputs[0], dest(path.stem, "vsum"), "A"
        )
    rec["failure_reason"] = rec.get("failure_reason")
    return rec, net, cat


def smoke_pole(ngspice) -> dict:
    """RC single-pole TIA smoke: DC must match the no-C OP; TRAN must settle."""
    fp, a, rf, r1 = 1e4, 1e5, 1e4, 1e4
    cval = 1.0 / (2.0 * math.pi * fp)
    k = tia_k(a, rf, 1.0 / r1)
    expected = -k * (rf / r1)  # Vin=1, inverting textbook TIA
    body = "\n".join(
        [
            "* Experiment 22 RC single-pole TIA smoke test",
            "* C open at DC. Not a transistor op-amp.",
            "Vin in 0 DC 1",
            f"Rw in sum {r1}",
            f"Etia int 0 0 sum {a}",
            "Rpole int lin 1",
            f"Clin lin 0 {cval:.15g}",
            f"Rf lin sum {rf}",
            ".control",
            "set numdgt=15",
            "op",
            "print v(lin)",
            "print v(sum)",
            ".endc",
            ".end",
            "",
        ]
    )
    path = dest("smoke", "pole_dc")
    path.write_text(body, encoding="utf-8")
    result = run_ngspice(ngspice, path, timeout=15.0)
    text = f"{result.stdout or ''}\n{result.stderr or ''}"
    vlin = extract_all(text, "v(lin)")
    rec = {
        "exit": result.returncode,
        "v_lin_dc": float(vlin[0]) if vlin else None,
        "expected_dc": expected,
        "ok": result.returncode == 0 and bool(vlin),
        "tail": text[-400:],
        "model": "RC series pole after VCVS, C open at DC",
    }
    if rec["v_lin_dc"] is not None:
        rec["dc_err"] = abs(rec["v_lin_dc"] - expected)
        rec["ok"] = rec["ok"] and rec["dc_err"] < 1e-3
    pulse = body.replace("Vin in 0 DC 1", "Vin in 0 PULSE(0 1 1n 1n 1n 1 2)")
    pulse = pulse.replace(".control", ".tran 50n 50u\n.control\nrun")
    pulse = pulse.replace("op", "meas tran vend FIND v(lin) AT=50u")
    ppath = dest("smoke", "pole_tran")
    ppath.write_text(pulse, encoding="utf-8")
    tr = run_ngspice(ngspice, ppath, timeout=20.0)
    ttext = f"{tr.stdout or ''}\n{tr.stderr or ''}"
    vend = extract_all(ttext, "vend")
    rec["tran_exit"] = tr.returncode
    rec["tran_vend"] = float(vend[-1]) if vend else None
    rec["tran_ok"] = tr.returncode == 0 and bool(vend)
    if rec["tran_vend"] is not None and rec["v_lin_dc"] is not None:
        rec["tran_vs_dc"] = abs(rec["tran_vend"] - rec["v_lin_dc"])
        rec["tran_ok"] = rec["tran_ok"] and rec["tran_vs_dc"] < 5e-3
    print(
        f"  pole smoke DC vlin={rec['v_lin_dc']} exit={rec['exit']} "
        f"TRAN vend={rec['tran_vend']} exit={tr.returncode}",
        flush=True,
    )
    return rec


def isolated_eval(ngspice, spec, weights, pick, params, inputs):
    hidden = pick["layer"] == 1
    idx = pick["index"]
    wrow = weights["W1"][idx] if hidden else weights["W2"][idx]
    bias = float(weights["b1"][idx] if hidden else weights["b2"][idx])
    cfg = ARCH_C_CFG[spec["id"]]
    g_w = cfg.g_weight_1 if hidden else cfg.g_weight_2
    n_src = spec["n_in"] if hidden else spec["n_hidden"]
    net, cat, reason = generate_isolated_neuron(
        n_src, wrow, bias, g_w, cfg.banks, params, tag=TAG
    )
    rec = {
        "tag": pick["tag"],
        "failed": bool(reason),
        "failure_reason": reason,
        "A": params.amp_gain,
        "vos": params.vos,
        "i_leak": params.i_leak,
        "rout": params.rout,
    }
    if reason or net is None:
        return rec
    x = np.atleast_2d(np.asarray(inputs, dtype=float))[:, :n_src]
    z = x @ np.asarray(wrow, float) + bias
    path = dest("iso", pick["tag"], params.name)
    vlin, vsum, err, _log = simulate_isolated(ngspice, net, x, n_src, path)
    if err or vlin is None:
        rec["failed"] = True
        rec["failure_reason"] = err
        return rec
    g_phys = neuron_gtot(cat, TAG)
    rf = 1.0 / float(g_w)
    k = tia_k(params.amp_gain, rf, g_phys)
    pred = k * z + params.vos * vos_to_vout_gain(params.amp_gain, rf, g_phys)
    pred = pred + params.i_leak * leak_to_vout_gain(params.amp_gain, rf, g_phys)
    rec.update(
        {
            "failed": False,
            "mae_vs_z": float(np.mean(np.abs(vlin - z))),
            "max_vs_z": float(np.max(np.abs(vlin - z))),
            "mae_vs_theory": float(np.mean(np.abs(vlin - pred))),
            "max_vs_theory": float(np.max(np.abs(vlin - pred))),
            "mean_vsum": float(np.mean(np.abs(vsum))) if vsum is not None else None,
            "max_vsum": float(np.max(np.abs(vsum))) if vsum is not None else None,
            "k_theory": k,
            "relu_match": float(np.mean((vlin > 0) == (z > 0))),
            "n_vectors": int(len(z)),
        }
    )
    return rec


def step_transient(
    ngspice, spec, weights, pick, params, x_vec, tstop=None, x0_vec=None, label="step",
):
    """Step inputs x0 → x1. Measure settling of v(n1lin)."""
    hidden = pick["layer"] == 1
    idx = pick["index"]
    wrow = weights["W1"][idx] if hidden else weights["W2"][idx]
    bias = float(weights["b1"][idx] if hidden else weights["b2"][idx])
    cfg = ARCH_C_CFG[spec["id"]]
    g_w = cfg.g_weight_1 if hidden else cfg.g_weight_2
    n_src = spec["n_in"] if hidden else spec["n_hidden"]
    net, cat, reason = generate_isolated_neuron(
        n_src, wrow, bias, g_w, cfg.banks, params, tag=TAG
    )
    if reason or net is None:
        return {"failed": True, "failure_reason": reason, "label": label}
    tau = closed_loop_tau(params.amp_gain, params.pole_hz, pick["Rf_Gtot"])
    if tstop is None:
        tstop = min(0.05, max(5e-5, 30.0 * tau))
    times = np.geomspace(max(1e-9, tstop / 1e5), tstop, 40)
    x1 = np.atleast_1d(np.asarray(x_vec, dtype=float))
    x0 = np.zeros_like(x1) if x0_vec is None else np.atleast_1d(np.asarray(x0_vec, dtype=float))
    patched = net
    for i in range(1, n_src + 1):
        xi = float(x1[i - 1]) if i <= len(x1) else 0.0
        x0i = float(x0[i - 1]) if i <= len(x0) else 0.0
        patched = patched.replace(
            f"Vin{i} in{i} 0 DC 0",
            f"Vin{i} in{i} 0 PULSE({x0i:.15g} {xi:.15g} 1n 1n 1n 1 2)",
            1,
        )
    head, sep, _ = patched.partition(".control")
    if not sep:
        return {"failed": True, "failure_reason": "no .control", "label": label}
    ctrl = [
        f".tran {tstop / 400.0:.15g} {tstop:.15g}",
        ".control",
        "set numdgt=15",
        "run",
    ]
    for i, t in enumerate(times):
        ctrl.append(f"meas tran vt{i} FIND v({TAG}lin) AT={float(t):.15g}")
        ctrl.append(f"print vt{i}")
    ctrl += [".endc", ".end", ""]
    path = dest("tran", pick["tag"], params.name, label)
    path.write_text(head.rstrip() + "\n" + "\n".join(ctrl), encoding="utf-8")
    result = run_ngspice(ngspice, path, timeout=max(TIMEOUT, 20.0 + 2000.0 * tstop))
    text = f"{result.stdout or ''}\n{result.stderr or ''}"
    if result.returncode != 0:
        return {
            "failed": True,
            "failure_reason": f"ngspice exit {result.returncode}",
            "tail": text[-400:],
            "label": label,
            "tstop_s": tstop,
        }
    ys = []
    ts = []
    for i, t in enumerate(times):
        vals = extract_all(text, f"vt{i}")
        if vals:
            ts.append(float(t))
            ys.append(float(vals[-1]))
    if len(ys) < 4:
        return {
            "failed": True,
            "failure_reason": "no meas samples",
            "tail": text[-400:],
            "label": label,
        }
    y = np.array(ys, float)
    t = np.array(ts, float)
    yf = float(y[-1])
    z = float(np.dot(x1[:n_src], np.asarray(wrow, float)) + bias)
    abs_e = np.abs(y - yf)

    def t_within(limit):
        inside = abs_e <= limit
        if not np.any(inside):
            return None
        for i in range(len(inside)):
            if np.all(inside[i:]):
                return float(t[i])
        return None

    step = max(abs(yf), 1e-12)
    return {
        "failed": False,
        "label": label,
        "tstop_s": tstop,
        "tau_cl_s": tau,
        "v_final": yf,
        "z": z,
        "final_err_vs_z": abs(yf - z),
        "overshoot": float(np.max(y) - yf) if yf >= 0 else float(yf - np.min(y)),
        "ringing": bool(np.max(y) > yf + 0.02 * step and np.min(y) < yf - 0.02 * step),
        "t_abs_1e3_s": t_within(ERROR_LIMIT),
        "t_rel_1pct_s": t_within(0.01 * step),
        "t_rel_0p1pct_s": t_within(0.001 * step),
        "pole_hz": params.pole_hz,
        "A": params.amp_gain,
        "gbw_proxy_hz": params.amp_gain * params.pole_hz,
        "note": (
            "gbw_proxy = A * f_p for this single-pole macromodel. "
            "Not a transistor unity-gain frequency."
        ),
    }


def write_plots(report: dict) -> list[str]:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    paths = []

    def xy(rows, vk, mk):
        xs, ys = [], []
        for r in rows or []:
            if r.get("failed") or r.get(mk) is None:
                continue
            xs.append(abs(r[vk]) if vk in r else r.get("A"))
            ys.append(r[mk])
        return xs, ys

    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    for net_id, mk in (("A", "o"), ("F", "s")):
        rows = report.get("gain", {}).get(net_id) or []
        xs = [r["A"] for r in rows if r.get("mae") is not None]
        ys = [r["mae"] for r in rows if r.get("mae") is not None]
        if xs:
            ax.loglog(xs, ys, marker=mk, label=f"{net_id} MAE")
    iso = (report.get("gain") or {}).get("isolated") or {}
    for tag, rows in iso.items():
        xs = [r["A"] for r in rows if not r.get("failed") and r.get("mae_vs_z") is not None]
        ys = [r["mae_vs_z"] for r in rows if not r.get("failed") and r.get("mae_vs_z") is not None]
        if xs:
            ax.loglog(xs, ys, marker=".", ls=":", label=f"iso {tag} vs z")
    ax.axhline(ERROR_LIMIT, color="k", ls="--", lw=0.8, label="MAE=1e-3")
    ax.set_xlabel("TIA open-loop A")
    ax.set_ylabel("MAE vs frozen map")
    ax.set_title("Experiment 22: open-loop gain requirement")
    ax.legend(fontsize=8)
    fig.tight_layout()
    p = RESULTS_DIR / "virtual_ground_gain.png"
    fig.savefig(p, dpi=140)
    plt.close(fig)
    paths.append(str(p))

    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    for net_id, ls in (("A", "-"), ("F", "--")):
        for sign, mk in ((1.0, "o"), (-1.0, "v")):
            rows = [
                r for r in (report.get("offset", {}).get(net_id) or [])
                if r.get("mae") is not None
                and (1.0 if r.get("vos", 0) >= 0 else -1.0) == sign
            ]
            if not rows:
                continue
            ax.loglog(
                [abs(r["vos"]) for r in rows],
                [r["mae"] for r in rows],
                ls, marker=mk,
                label=f"{net_id} Vos {'+' if sign > 0 else '-'}",
            )
    ax.axhline(ERROR_LIMIT, color="k", ls="--", lw=0.8)
    ax.set_xlabel("|Vos| (V)")
    ax.set_ylabel("MAE")
    ax.set_title("Experiment 22: input offset requirement")
    ax.legend(fontsize=7)
    fig.tight_layout()
    p = RESULTS_DIR / "virtual_ground_offset.png"
    fig.savefig(p, dpi=140)
    plt.close(fig)
    paths.append(str(p))

    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    for net_id, ls in (("A", "-"), ("F", "--")):
        for sign, mk in ((1.0, "o"), (-1.0, "v")):
            rows = [
                r for r in (report.get("leakage", {}).get(net_id) or [])
                if r.get("mae") is not None
                and (1.0 if r.get("i_leak", 0) >= 0 else -1.0) == sign
            ]
            if not rows:
                continue
            ax.loglog(
                [abs(r["i_leak"]) for r in rows],
                [r["mae"] for r in rows],
                ls, marker=mk,
                label=f"{net_id} Ileak {'+' if sign > 0 else '-'}",
            )
    ax.axhline(ERROR_LIMIT, color="k", ls="--", lw=0.8)
    ax.set_xlabel("|I_leak| (A)")
    ax.set_ylabel("MAE")
    ax.set_title("Experiment 22: input leakage requirement")
    ax.legend(fontsize=7)
    fig.tight_layout()
    p = RESULTS_DIR / "virtual_ground_leakage.png"
    fig.savefig(p, dpi=140)
    plt.close(fig)
    paths.append(str(p))

    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    bw = report.get("bandwidth", {}).get("isolated") or []
    plotted = False
    for lab, mk in (("unit_ones", "o"), ("max_z", "s"), ("bipolar", "v"), ("A1e4", "^")):
        rows = [r for r in bw if not r.get("failed") and r.get("label", "step") == lab]
        if not rows:
            rows = [r for r in bw if not r.get("failed") and lab == "unit_ones" and r.get("t_abs_1e3_s") is not None] if lab == "unit_ones" else []
        xs = [r["pole_hz"] for r in rows if r.get("t_abs_1e3_s") is not None]
        ys = [r["t_abs_1e3_s"] for r in rows if r.get("t_abs_1e3_s") is not None]
        if xs:
            ax.loglog(xs, ys, marker=mk, label=f"{lab} |err|<1e-3")
            plotted = True
    ax.set_xlabel("open-loop pole f_p (Hz)")
    ax.set_ylabel("settling time (s)")
    ax.set_title("Experiment 22: behavioral single-pole settling")
    if plotted:
        ax.legend(fontsize=8)
    fig.tight_layout()
    p = RESULTS_DIR / "virtual_ground_bandwidth.png"
    fig.savefig(p, dpi=140)
    plt.close(fig)
    paths.append(str(p))

    comb = report.get("combined", {}).get("gain_offset") or []
    if comb:
        fig, ax = plt.subplots(figsize=(6.8, 4.4))
        As = sorted({r["A"] for r in comb if r.get("mae") is not None})
        Vs = sorted({r["vos"] for r in comb if r.get("mae") is not None})
        z = np.full((len(Vs), len(As)), np.nan)
        for r in comb:
            if r.get("mae") is None:
                continue
            i = Vs.index(r["vos"])
            j = As.index(r["A"])
            z[i, j] = r["mae"]
        im = ax.imshow(np.log10(np.clip(z, 1e-16, None)), origin="lower", aspect="auto",
                       extent=[-0.5, len(As) - 0.5, -0.5, len(Vs) - 0.5], cmap="magma")
        ax.set_xticks(range(len(As)))
        ax.set_xticklabels([f"{a:.0e}" for a in As], rotation=30)
        ax.set_yticks(range(len(Vs)))
        ax.set_yticklabels([f"{v:.0e}" for v in Vs])
        ax.set_xlabel("A")
        ax.set_ylabel("Vos (V)")
        ax.set_title("Experiment 22: log10 MAE, A × Vos on F")
        fig.colorbar(im, ax=ax, label="log10 MAE")
        fig.tight_layout()
        p = RESULTS_DIR / "virtual_ground_requirement_map.png"
        fig.savefig(p, dpi=140)
        plt.close(fig)
        paths.append(str(p))
    return paths


def _th_txt(th: dict | None, kind: str) -> str:
    if not th:
        return "n/a"
    if kind == "mae" or kind == "gain":
        val = th.get("value")
        sp = th.get("sampled_pass")
        return f"{fmt(val)} (sampled pass {fmt(sp)}, {th.get('status')})"
    absv = th.get("abs_value")
    if absv is not None:
        return f"{fmt(absv)} ({th.get('status')}, last pass {fmt(th.get('lo'))})"
    return str(th)


def write_markdown(report: dict) -> None:
    tbl = report.get("requirement_table") or []
    sel = (report.get("ranking") or {}).get("selected") or {}
    th = report.get("thresholds") or {}
    base = report.get("baseline") or {}
    lines = [
        "# Experiment 22 — virtual-ground requirement extraction",
        "",
        "## TITLE",
        "What specifications must a physical virtual-ground TIA satisfy?",
        "",
        "## QUESTION",
        "Given that this conductance fabric needs a VG I-to-V at each neuron, "
        "what open-loop gain, offset, leakage, output resistance, and "
        "behavioral bandwidth does that primitive need for MAE <= 1e-3 and "
        "for 100% classification on the frozen A/F benchmarks?",
        "",
        "## HYPOTHESIS",
        "Finite A is set by the worst-neuron Rf G_tot (Exp 21). Offset maps "
        "as Vos*(1+Rf G_tot)*k and is tighter than classification. Leakage "
        "maps as ~I_leak*Rf. Bandwidth is a new dynamic requirement and is "
        "behavioral (single pole), not transistor GBW. Shared-tap coupling "
        "makes full-network offset stricter than the isolated neuron.",
        "",
        "## ARCHITECTURE",
        "Experiment 17 Architecture A. Invert A pinned at 1e7 for TIA sweeps. "
        "Baselines use invert A = 1e5 to match Experiment 17.",
        "",
        "## WHAT CHANGED",
        "Requirement extraction. No new weight encoding. No MOS devices.",
        "",
        "## WHAT REMAINED FROZEN",
        "Experiment 9 weights. Fabric. Direct bounded ReLU on full networks.",
        "",
        "## TEST CONDITIONS",
        "Networks A (100 vec) and F (40 vec). Isolated worst/median neurons. "
        "Analog bar MAE <= 1e-3. Classification = 100% vs frozen software.",
        "",
        "## RESULTS",
        "",
        "### Baseline verification",
    ]
    for net_id in ("A", "F"):
        b = base.get(net_id) or {}
        i = b.get("I") or {}
        a = b.get("A_1e5") or {}
        vs = b.get("A_vsum") or {}
        lines.append(
            f"- Network {net_id}: Arch I MAE={fmt(i.get('mae'))} acc={i.get('accuracy')}; "
            f"Arch A A=1e5 MAE={fmt(a.get('mae'))} acc={a.get('accuracy')}; "
            f"max |Vsum|={fmt(vs.get('max_abs_V'))}"
        )
    lines += ["", "### Worst-neuron analysis"]
    for key, row in sel.items():
        if isinstance(row, dict) and "tag" in row:
            lines.append(
                f"- {key}: {row['tag']} RfG={fmt(row.get('Rf_Gtot'), '.3g')} "
                f"VosGain={fmt(row.get('vos_to_Vlin_V_per_V'), '.3g')} "
                f"G_phys={fmt(row.get('G_phys_S'))}"
            )
    rk = report.get("ranking") or {}
    lines.append(
        f"- Rf G_tot span: {fmt(rk.get('Rf_Gtot_min'), '.3g')} .. "
        f"{fmt(rk.get('Rf_Gtot_max'), '.3g')} (ratio {fmt(rk.get('G_phys_ratio'), '.3g')})"
    )
    lines += ["", "### Open-loop gain"]
    for net_id in ("A", "F"):
        g = (th.get("gain") or {}).get(net_id) or {}
        lines.append(
            f"- Network {net_id} analog A={_th_txt(g.get('mae'), 'gain')}; "
            f"class A={_th_txt(g.get('class'), 'gain')}"
        )
    lines += ["", "### Offset"]
    for net_id in ("A", "F"):
        o = (th.get("offset") or {}).get(net_id) or {}
        lines.append(
            f"- Network {net_id} analog |Vos|={_th_txt(o.get('mae'), 'off')}; "
            f"class |Vos|={_th_txt(o.get('class'), 'off')}"
        )
    lines += ["", "### Leakage"]
    for net_id in ("A", "F"):
        o = (th.get("leakage") or {}).get(net_id) or {}
        lines.append(
            f"- Network {net_id} analog |Ileak|={_th_txt(o.get('mae'), 'off')}; "
            f"class |Ileak|={_th_txt(o.get('class'), 'off')}"
        )
    lines += [
        "",
        "### Output resistance",
        str((report.get("thresholds") or {}).get("rout")),
        "",
        "### Bandwidth/settling",
        str(report.get("bandwidth", {}).get("summary")),
        "",
        "### Combined maps",
        str(report.get("combined", {}).get("summary")),
        "",
        "### Design rule (k_j vs SPICE)",
        str(report.get("design_rule")),
        "",
        "### Isolated vs full-network Vos at 1 mV",
        str(report.get("isolated_vs_network_vos_1mV")),
        "",
        "### Full-network validation",
    ]
    val = report.get("validation") or {}
    for net_id in ("A", "F"):
        for name, rec in (val.get(net_id) or {}).items():
            if not isinstance(rec, dict):
                continue
            lines.append(
                f"- {net_id} {name}: MAE={fmt(rec.get('mae'))} "
                f"max={fmt(rec.get('max_abs_error'))} acc={rec.get('accuracy')} "
                f"A={fmt(rec.get('A'), '.4g')}"
            )
    lines += [
        "",
        "## Requirement table",
        "",
        "| Parameter | Analog threshold | Classification threshold | Conservative point | Dominant failure |",
        "|---|---:|---:|---:|---|",
    ]
    for row in tbl:
        lines.append(
            f"| {row.get('parameter')} | {fmt(row.get('analog'))} | "
            f"{fmt(row.get('classification'))} | {fmt(row.get('conservative'))} | "
            f"{row.get('mechanism')} |"
        )
    if report.get("conservative_notes"):
        lines += ["", "Conservative-point notes:", report["conservative_notes"]]
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
        "## FINAL STATUS",
        report.get("final_status") or "",
        "",
    ]
    REPORT_MD.write_text("\n".join(lines), encoding="utf-8")


def conclude(report: dict) -> None:
    th = report.get("thresholds") or {}
    gF = (th.get("gain") or {}).get("F") or {}
    oF = (th.get("offset") or {}).get("F") or {}
    lF = (th.get("leakage") or {}).get("F") or {}
    a_mae = ((gF.get("mae") or {}).get("value") or (gF.get("mae") or {}).get("sampled_pass"))
    a_cls = ((gF.get("class") or {}).get("value") or (gF.get("class") or {}).get("sampled_pass"))
    vos_mae = ((oF.get("mae") or {}).get("abs_value") or (oF.get("mae") or {}).get("value"))
    vos_cls = ((oF.get("class") or {}).get("abs_value") or (oF.get("class") or {}).get("value"))
    leak_mae = ((lF.get("mae") or {}).get("abs_value") or (lF.get("mae") or {}).get("value"))
    leak_cls = ((lF.get("class") or {}).get("abs_value") or (lF.get("class") or {}).get("value"))

    def cons_gain(x):
        if x is None:
            return None
        return float(10 ** math.ceil(math.log10(x) + 1e-12)) if x > 0 else None

    # Conservative analog gain: next decade that was actually simulated and passed.
    cons_a = None
    cons_notes = []
    if a_mae:
        decade = cons_gain(a_mae)
        gain_rows = report.get("gain", {}).get("F") or []
        passing = [r for r in gain_rows if r.get("mae") is not None and r["mae"] <= ERROR_LIMIT]
        if decade and any(r["A"] >= decade * 0.99 and r.get("mae", 9) <= ERROR_LIMIT for r in passing):
            cons_a = decade
            cons_notes.append(
                f"Gain conservative={decade:g} is the next decade above analog A={a_mae:.4g} "
                "that was actually simulated on F and met MAE<=1e-3 (not an invented factor of 10)."
            )
        elif passing:
            cons_a = max(r["A"] for r in passing)
            cons_notes.append(f"Gain conservative={cons_a:g} is the largest swept A that passed MAE.")

    def decade_below_if_passed(analog, rows, key, name):
        if analog is None:
            return None
        target = analog / 10.0
        passed = [
            r for r in rows
            if not r.get("failed") and r.get("mae") is not None
            and abs(float(r.get(key) or 0)) <= target * 1.05
            and r["mae"] <= ERROR_LIMIT
        ]
        if not passed:
            cons_notes.append(
                f"{name}: analog/10={target:.4g} was not confirmed as passing in the sweep; "
                "no conservative point claimed."
            )
            return None
        cons_notes.append(
            f"{name} conservative={target:.4g} is analog/10; swept points at or below that "
            "still met MAE<=1e-3."
        )
        return target

    vos_cons = decade_below_if_passed(
        vos_mae if isinstance(vos_mae, (int, float)) else None,
        report.get("offset", {}).get("F") or [],
        "vos",
        "Vos",
    )
    leak_cons = decade_below_if_passed(
        leak_mae if isinstance(leak_mae, (int, float)) else None,
        report.get("leakage", {}).get("F") or [],
        "i_leak",
        "Ileak",
    )

    bw = report.get("bandwidth", {}).get("summary") or {}
    rout_th = th.get("rout") or {}

    report["requirement_table"] = [
        {
            "parameter": "Open-loop gain A",
            "analog": a_mae,
            "classification": a_cls,
            "conservative": cons_a,
            "mechanism": "finite VG loading k=A/(A+1+Rf G_tot), worst neuron",
        },
        {
            "parameter": "Input offset Vos (V)",
            "analog": vos_mae,
            "classification": vos_cls,
            "conservative": vos_cons,
            "mechanism": "Vsum displacement + shared-tap coupling on the fabric",
        },
        {
            "parameter": "Input leakage (A)",
            "analog": leak_mae,
            "classification": leak_cls,
            "conservative": leak_cons,
            "mechanism": "I_leak * Rf * k_j into Vlin, then ReLU / layer 2",
        },
        {
            "parameter": "Open-loop pole f_p (Hz)",
            "analog": bw.get("fp_for_1e3"),
            "classification": bw.get("fp_for_class_note"),
            "conservative": bw.get("fp_conservative"),
            "mechanism": "incomplete single-pole settling (behavioral, not GBW)",
        },
        {
            "parameter": "Output resistance (ohm)",
            "analog": rout_th.get("analog"),
            "classification": rout_th.get("classification"),
            "conservative": rout_th.get("conservative"),
            "mechanism": rout_th.get("mechanism") or "loop-gain loss after Rout",
        },
    ]
    report["conservative_notes"] = " ".join(cons_notes)
    report["comparison"] = (
        f"Exp 17 F A=1e5 MAE~5e-4, class 100% at A>=1e4. "
        f"This run analog A_min={fmt(a_mae)} class A_min={fmt(a_cls)} "
        f"Vos_analog={fmt(vos_mae)} Ileak_analog={fmt(leak_mae)}."
    )
    report["failure_modes"] = (
        "Classification survives analog failure. Isolated MAE vs a neuron's z "
        "is not the same metric as F output MAE; the table uses full-network F. "
        "Settling is a behavioral single-pole macromodel, not an op-amp datasheet."
    )
    report["dominant_error"] = (
        "DC analog floor: Vos through (1+Rf G_tot) and per-neuron finite A. "
        "Classification floor: much larger Vos / much smaller A."
    )
    report["physical_interpretation"] = (
        "The VG primitive must hold Vsum << neural LSB. Fine-bank physical G "
        "makes that harder on some neurons (Rf G_tot up to tens). Offset is "
        "not a global output shift: ReLU and shared taps make it neuron-wise."
    )
    report["hardware_level"] = (
        "LEVEL 2 requirement extraction on a behavioral TIA. Not LEVEL 4-6. "
        "A real op-amp/OTA must meet these numbers under this G_tot, not in "
        "an unloaded textbook TIA."
    )
    extracted = a_mae is not None and vos_mae is not None
    bw_ok = bool((report.get("bandwidth") or {}).get("isolated"))
    if extracted and bw_ok:
        status = "REQUIREMENTS EXTRACTED"
    elif extracted:
        status = "PARTIAL REQUIREMENTS EXTRACTED"
    else:
        status = "PARTIAL REQUIREMENTS EXTRACTED"
    report["final_status"] = status
    report["conclusion"] = (
        f"{status}. Analog (MAE<=1e-3 on F) needs A~{fmt(a_mae)} "
        f"and |Vos|<={fmt(vos_mae)} and |Ileak|<={fmt(leak_mae)}. "
        f"Classification is looser (A~{fmt(a_cls)}, larger Vos/Ileak). "
        "Conservative analog gain is the next decade that was actually "
        "simulated and passed."
        if extracted else "See missing thresholds."
    )
    report["next_question"] = (
        "Experiment 23 should take ONE documented VG primitive (op-amp or "
        "OTA macromodel with known A, Vos, Ib, fu) and test it as a unit "
        "cell against this table. Do not embed MOS in Network F first. "
        "A vendor MCP6041 example exists under ngspice/examples but was not "
        "copied into this repo. The built-in XSPICE OTA is the cleanest "
        "next macromodel."
    )


def main() -> int:
    print("Experiment 22: virtual-ground requirement extraction", flush=True)
    ngspice = find_ngspice()
    print(f"ngspice: {ngspice}", flush=True)
    CIRCUIT_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "experiment": 22,
        "title": "virtual-ground requirement extraction",
        "frozen_weights": "Experiment 9 models/scaling/{A,F}.npz",
        "spice_source_of_truth": True,
        "python_does_not_correct_spice": True,
        "device_level": "deferred",
    }

    print("Single-pole RC smoke test", flush=True)
    report["pole_smoke"] = smoke_pole(ngspice)
    report["laplace_smoke"] = report["pole_smoke"]  # backward-compatible key

    nets = {}
    for net_id in ("A", "F"):
        spec = spec_by_id(net_id)
        weights = load_frozen_model(net_id)
        n_vec = N_A if net_id == "A" else N_F
        x = generate_inputs(spec["n_in"], n_vec, f"exp22_{net_id}")
        y, meta = software_for(weights, x)
        x_sw = x if net_id == "A" else x
        nets[net_id] = {
            "spec": spec, "weights": weights, "x": x, "y": y, "meta": meta, "x_sw": x_sw,
        }

    print("Baseline verification", flush=True)
    baseline = {}
    for net_id, pack in nets.items():
        spec, w, x, y = pack["spec"], pack["weights"], pack["x"], pack["y"]
        net_i, cat_i, r_i = compile_iv("I", spec, w)
        rec_i = evaluate_netlist(ngspice, spec, net_i, x, y, dest(net_id, "I", "base")) if net_i else {"failed": True, "failure_reason": r_i}
        p17 = VGParams(name="A17", amp_gain=1e5, invert_gain=1e5, linear=False)
        rec_a, _, cat_a = eval_network(ngspice, spec, w, p17, x, y, dest(net_id, "A", "base"), measure_vsum=True)
        baseline[net_id] = {
            "I": {k: rec_i.get(k) for k in ("mae", "max_abs_error", "accuracy", "failed", "failure_reason")},
            "A_1e5": {k: rec_a.get(k) for k in ("mae", "max_abs_error", "accuracy", "failed", "failure_reason")},
            "A_vsum": rec_a.get("summing_node"),
        }
        print(
            f"  {net_id} I MAE={fmt(rec_i.get('mae'))} acc={rec_i.get('accuracy')} "
            f"A MAE={fmt(rec_a.get('mae'))} acc={rec_a.get('accuracy')}",
            flush=True,
        )
        if net_id == "F":
            pack["catalog_A"] = cat_a
    report["baseline"] = baseline

    print("Phase 1: rank Network F neurons", flush=True)
    f = nets["F"]
    net_f, cat_f, reason_f = compile_iv(
        "A", f["spec"], f["weights"], IVParams(name="rank", invert_gain=INVERT_PINNED)
    )
    if reason_f or cat_f is None:
        print(f"  rank compile failed: {reason_f}", flush=True)
        cat_f = f.get("catalog_A") or []
    rows, selected = rank_neurons(f["spec"], cat_f, f["weights"], f["x"])
    ranking = {"neurons": rows, "selected": selected, "note": selected.get("ranking_note")}
    WORST_JSON.write_text(json.dumps({"selected": selected, "neurons": rows}, indent=2, default=float), encoding="utf-8")
    report["ranking"] = {
        "selected": {
            k: selected[k] for k in selected if k != "ranking_note"
        },
        "note": selected.get("ranking_note"),
        "n_neurons": len(rows),
        "Rf_Gtot_min": min(r["Rf_Gtot"] for r in rows),
        "Rf_Gtot_max": max(r["Rf_Gtot"] for r in rows),
        "G_phys_ratio": max(r["G_phys_S"] for r in rows) / max(min(r["G_phys_S"] for r in rows), 1e-18),
    }
    print(
        f"  worst A: {selected['worst_finite_gain']['tag']} "
        f"RfG={selected['worst_finite_gain']['Rf_Gtot']:.3g} "
        f"worst leak: {selected['worst_leakage']['tag']} "
        f"median: {selected['median_hidden']['tag']}",
        flush=True,
    )
    picks = [
        selected["worst_finite_gain"],
        selected["worst_leakage"],
        selected["median_hidden"],
    ]
    # unique tags
    seen = set()
    picks_u = []
    for p in picks:
        if p["tag"] not in seen:
            seen.add(p["tag"])
            picks_u.append(p)

    iso_inputs_h = generate_inputs(f["spec"]["n_in"], 16, "exp22_iso_h")
    z1 = iso_inputs_h @ f["weights"]["W1"].T + f["weights"]["b1"]
    iso_inputs_o = np.maximum(0.0, z1[:16])

    def iso_x(pick):
        return iso_inputs_h if pick["layer"] == 1 else iso_inputs_o

    print("Phase 2–3: isolated + network gain sweep", flush=True)
    gain = {"isolated": {}, "A": [], "F": []}
    for pick in picks_u:
        gain["isolated"][pick["tag"]] = []
        for a in GAIN_SWEEP:
            params = VGParams(name=f"g{a:g}", amp_gain=a)
            rec = isolated_eval(ngspice, f["spec"], f["weights"], pick, params, iso_x(pick))
            rec["value"] = a
            rec["A"] = a
            gain["isolated"][pick["tag"]].append(rec)
            print(
                f"    iso {pick['tag']} A={a:g} MAE_z={fmt(rec.get('mae_vs_z'))} "
                f"theory={fmt(rec.get('mae_vs_theory'))} Vsum={fmt(rec.get('max_vsum'))}",
                flush=True,
            )
    for net_id, pack in nets.items():
        for a in GAIN_SWEEP:
            params = VGParams(name=f"g{a:g}", amp_gain=a, linear=False)
            rec, _, _ = eval_network(
                ngspice, pack["spec"], pack["weights"], params,
                pack["x"], pack["y"], dest(net_id, "gain", f"{a:g}"),
                measure_vsum=(a in (1e3, 1e5, 1e7)),
            )
            rec["A"] = a
            rec["value"] = a
            gain[net_id].append(rec)
            print(
                f"    net {net_id} A={a:g} MAE={fmt(rec.get('mae'))} "
                f"acc={rec.get('accuracy')} Vsum={((rec.get('summing_node') or {}).get('max_abs_V'))}",
                flush=True,
            )
    report["gain"] = gain

    # Refine F gain around analog crossing
    print("  refine F gain around MAE=1e-3", flush=True)
    usable = [r for r in gain["F"] if r.get("mae") is not None]
    usable = sorted(usable, key=lambda r: r["A"])
    extra = []
    for i in range(len(usable) - 1):
        a0, a1 = usable[i]["A"], usable[i + 1]["A"]
        m0, m1 = usable[i]["mae"], usable[i + 1]["mae"]
        if (m0 - ERROR_LIMIT) * (m1 - ERROR_LIMIT) <= 0 and a0 != a1:
            amid = math.sqrt(a0 * a1)
            params = VGParams(name=f"gref{amid:g}", amp_gain=amid, linear=False)
            rec, _, _ = eval_network(
                ngspice, f["spec"], f["weights"], params, f["x"], f["y"],
                dest("F", "gainref", f"{amid:g}"),
            )
            rec["A"] = amid
            rec["value"] = amid
            extra.append(rec)
            print(f"    refine A={amid:g} MAE={fmt(rec.get('mae'))} acc={rec.get('accuracy')}", flush=True)
            # second split if still bracketed
            if rec.get("mae") is not None:
                if rec["mae"] > ERROR_LIMIT:
                    amid2 = math.sqrt(amid * a1)
                else:
                    amid2 = math.sqrt(a0 * amid)
                params = VGParams(name=f"gref2{amid2:g}", amp_gain=amid2, linear=False)
                rec2, _, _ = eval_network(
                    ngspice, f["spec"], f["weights"], params, f["x"], f["y"],
                    dest("F", "gainref2", f"{amid2:g}"),
                )
                rec2["A"] = amid2
                rec2["value"] = amid2
                extra.append(rec2)
                print(f"    refine2 A={amid2:g} MAE={fmt(rec2.get('mae'))}", flush=True)
            break
    gain["F"].extend(extra)

    print("Phase 4: offset sweep", flush=True)
    offset = {"isolated": {}, "A": [], "F": []}
    worst_off = selected["worst_offset"]
    offset["isolated"][worst_off["tag"]] = []
    for vos in VOS_ABS:
        for sgn in (1.0, -1.0):
            v = sgn * vos
            params = VGParams(name=f"vos{v:g}", amp_gain=1e5, vos=v)
            rec = isolated_eval(ngspice, f["spec"], f["weights"], worst_off, params, iso_x(worst_off))
            rec["vos"] = v
            rec["value"] = v
            offset["isolated"][worst_off["tag"]].append(rec)
    for net_id, pack in nets.items():
        for vos in VOS_ABS:
            for sgn in (1.0, -1.0):
                v = sgn * vos
                params = VGParams(name=f"vos{v:g}", amp_gain=1e5, vos=v, linear=False)
                rec, _, _ = eval_network(
                    ngspice, pack["spec"], pack["weights"], params,
                    pack["x"], pack["y"], dest(net_id, "vos", f"{v:g}"),
                )
                rec["vos"] = v
                rec["value"] = v
                offset[net_id].append(rec)
                if abs(math.log10(vos) - round(math.log10(vos))) < 1e-9:
                    print(
                        f"    {net_id} Vos={v:.3g} MAE={fmt(rec.get('mae'))} acc={rec.get('accuracy')}",
                        flush=True,
                    )
    report["offset"] = offset

    print("Phase 5: leakage sweep", flush=True)
    leakage = {"isolated": {}, "A": [], "F": []}
    worst_lk = selected["worst_leakage"]
    leakage["isolated"][worst_lk["tag"]] = []
    for ileak in LEAK_ABS:
        for sgn in (1.0, -1.0):
            i = sgn * ileak
            params = VGParams(name=f"lk{i:g}", amp_gain=1e5, i_leak=i)
            rec = isolated_eval(ngspice, f["spec"], f["weights"], worst_lk, params, iso_x(worst_lk))
            rec["i_leak"] = i
            rec["value"] = i
            leakage["isolated"][worst_lk["tag"]].append(rec)
    for net_id, pack in nets.items():
        for ileak in LEAK_ABS:
            for sgn in (1.0, -1.0):
                i = sgn * ileak
                params = VGParams(name=f"lk{i:g}", amp_gain=1e5, i_leak=i, linear=False)
                rec, _, _ = eval_network(
                    ngspice, pack["spec"], pack["weights"], params,
                    pack["x"], pack["y"], dest(net_id, "leak", f"{i:g}"),
                )
                rec["i_leak"] = i
                rec["value"] = i
                leakage[net_id].append(rec)
        print(
            f"    {net_id} leakage sweep done n={len(leakage[net_id])}",
            flush=True,
        )
    report["leakage"] = leakage

    print("Phase 6: output resistance", flush=True)
    rout = {"F": []}
    for ro in ROUT_SWEEP:
        params = VGParams(name=f"ro{ro:g}", amp_gain=1e5, rout=ro, linear=False)
        rec, _, _ = eval_network(
            ngspice, f["spec"], f["weights"], params, f["x"], f["y"], dest("F", "rout", f"{ro:g}")
        )
        rec["rout"] = ro
        rec["value"] = ro
        rout["F"].append(rec)
        print(f"    Rout={ro:g} MAE={fmt(rec.get('mae'))} acc={rec.get('accuracy')}", flush=True)
    report["rout"] = rout

    print("Phase 7: bandwidth / settling", flush=True)
    bw_iso = []
    worst_g = selected["worst_finite_gain"]
    n_src_w = f["spec"]["n_in"] if worst_g["layer"] == 1 else f["spec"]["n_hidden"]
    x_ones = np.ones(n_src_w)
    # vector that maximizes |z| on the worst neuron from the isolated batch
    x_iso = iso_x(worst_g)
    wrow_w = f["weights"]["W1"][worst_g["index"]] if worst_g["layer"] == 1 else f["weights"]["W2"][worst_g["index"]]
    z_iso = x_iso @ np.asarray(wrow_w, float) + float(
        f["weights"]["b1"][worst_g["index"]] if worst_g["layer"] == 1 else f["weights"]["b2"][worst_g["index"]]
    )
    x_maxz = x_iso[int(np.argmax(np.abs(z_iso)))]
    smoke_ok = bool(report["pole_smoke"].get("ok")) and bool(report["pole_smoke"].get("tran_ok"))
    if not smoke_ok:
        report["bandwidth"] = {
            "isolated": [],
            "summary": {
                "status": "pole_transient_unavailable",
                "smoke": report["pole_smoke"],
            },
        }
        print("  RC pole transient failed smoke test; skipping BW sweep", flush=True)
    else:
        for fp in POLE_HZ:
            params = VGParams(name=f"fp{fp:g}", amp_gain=1e5, pole_hz=fp, linear=True)
            rec = step_transient(
                ngspice, f["spec"], f["weights"], worst_g, params, x_ones, label="unit_ones",
            )
            rec["pole_hz"] = fp
            bw_iso.append(rec)
            print(
                f"    ones A=1e5 fp={fp:g} fail={rec.get('failed')} "
                f"t1e-3={fmt(rec.get('t_abs_1e3_s'))} "
                f"t0.1%={fmt(rec.get('t_rel_0p1pct_s'))} "
                f"final_err={fmt(rec.get('final_err_vs_z'))} "
                f"gbw={fmt(rec.get('gbw_proxy_hz'))}",
                flush=True,
            )
        for fp in POLE_SUBSET:
            params = VGParams(name=f"fpz{fp:g}", amp_gain=1e5, pole_hz=fp, linear=True)
            rec = step_transient(
                ngspice, f["spec"], f["weights"], worst_g, params, x_maxz, label="max_z",
            )
            rec["pole_hz"] = fp
            bw_iso.append(rec)
            print(
                f"    max|z| fp={fp:g} fail={rec.get('failed')} "
                f"t1e-3={fmt(rec.get('t_abs_1e3_s'))}",
                flush=True,
            )
        for fp in (10.0, 1e3):
            params = VGParams(name=f"fpb{fp:g}", amp_gain=1e5, pole_hz=fp, linear=True)
            rec = step_transient(
                ngspice, f["spec"], f["weights"], worst_g, params, x_maxz,
                x0_vec=-np.asarray(x_maxz, float), label="bipolar",
            )
            rec["pole_hz"] = fp
            bw_iso.append(rec)
            print(
                f"    bipolar fp={fp:g} fail={rec.get('failed')} "
                f"t1e-3={fmt(rec.get('t_abs_1e3_s'))}",
                flush=True,
            )
        for fp in POLE_SUBSET:
            params = VGParams(name=f"fpc{fp:g}", amp_gain=1e4, pole_hz=fp, linear=True)
            rec = step_transient(
                ngspice, f["spec"], f["weights"], worst_g, params, x_ones, label="A1e4",
            )
            rec["pole_hz"] = fp
            bw_iso.append(rec)
            print(
                f"    A=1e4 fp={fp:g} fail={rec.get('failed')} "
                f"t1e-3={fmt(rec.get('t_abs_1e3_s'))}",
                flush=True,
            )
        report["bandwidth"] = {"isolated": bw_iso}

    print("Phase 8: combined A×Vos and A×Ileak on F", flush=True)
    comb_vo, comb_lk = [], []
    for a in COMB_A:
        for vos in COMB_VOS:
            params = VGParams(name=f"cA{a:g}v{vos:g}", amp_gain=a, vos=vos, linear=False)
            rec, _, _ = eval_network(
                ngspice, f["spec"], f["weights"], params, f["x"], f["y"],
                dest("F", "comb", f"A{a:g}", f"v{vos:g}"),
            )
            rec["A"] = a
            rec["vos"] = vos
            comb_vo.append(rec)
        for ileak in COMB_LEAK:
            params = VGParams(name=f"cA{a:g}i{ileak:g}", amp_gain=a, i_leak=ileak, linear=False)
            rec, _, _ = eval_network(
                ngspice, f["spec"], f["weights"], params, f["x"], f["y"],
                dest("F", "comb", f"A{a:g}", f"i{ileak:g}"),
            )
            rec["A"] = a
            rec["i_leak"] = ileak
            comb_lk.append(rec)
        print(f"    combined A={a:g} done", flush=True)

    def _mae_at(rows, **kw):
        for r in rows:
            if r.get("failed") or r.get("mae") is None:
                continue
            if all(abs(float(r.get(k, 0)) - float(v)) <= 1e-18 + 1e-9 * abs(float(v)) for k, v in kw.items()):
                return r["mae"], r.get("accuracy")
        return None, None

    vo_1m = []
    for a in COMB_A:
        m, acc = _mae_at(comb_vo, A=a, vos=1e-3)
        vo_1m.append(f"A={a:g}->MAE={fmt(m)} acc={acc}")
    lk_1e8 = []
    for a in COMB_A:
        m, acc = _mae_at(comb_lk, A=a, i_leak=1e-8)
        lk_1e8.append(f"A={a:g}->MAE={fmt(m)}")
    report["combined"] = {
        "gain_offset": [
            {k: r.get(k) for k in ("A", "vos", "mae", "accuracy", "failed")}
            for r in comb_vo
        ],
        "gain_leak": [
            {k: r.get(k) for k in ("A", "i_leak", "mae", "accuracy", "failed")}
            for r in comb_lk
        ],
        "summary": (
            "Vos=1 mV on F: " + "; ".join(vo_1m) +
            ". High A does not cancel 1 mV Vos. Ileak=10 nA: " + "; ".join(lk_1e8) +
            ". Leakage is only weakly A-dependent once A >> Rf G_tot."
        ),
    }

    # Thresholds
    def class_ok(r):
        return (r.get("accuracy") or 0) >= 1.0 - 1e-12

    th = {"gain": {}, "offset": {}, "leakage": {}, "rout": {}}
    for net_id in ("A", "F"):
        th["gain"][net_id] = {
            "mae": interpolate_threshold(gain[net_id], "A", "mae", ERROR_LIMIT, True),
            "class": interpolate_threshold(
                [
                    {**r, "acc100": 1.0 if class_ok(r) else 0.0}
                    for r in gain[net_id]
                ],
                "A",
                "acc100",
                1.0,
                False,
            ),
        }
        th["offset"][net_id] = {
            "mae_pos": max_tolerable(
                [r for r in offset[net_id] if (r.get("vos") or 0) >= 0],
                "vos", "mae", ERROR_LIMIT, True,
            ),
            "mae_neg": max_tolerable(
                [r for r in offset[net_id] if (r.get("vos") or 0) <= 0],
                "vos", "mae", ERROR_LIMIT, True,
            ),
            "class_pos": max_tolerable(
                [{**r, "acc100": 1.0 if class_ok(r) else 0.0} for r in offset[net_id] if (r.get("vos") or 0) >= 0],
                "vos", "acc100", 1.0, False,
            ),
            "class_neg": max_tolerable(
                [{**r, "acc100": 1.0 if class_ok(r) else 0.0} for r in offset[net_id] if (r.get("vos") or 0) <= 0],
                "vos", "acc100", 1.0, False,
            ),
        }
        # tighter analog of the two signs
        mp, mn = th["offset"][net_id]["mae_pos"], th["offset"][net_id]["mae_neg"]
        th["offset"][net_id]["mae"] = min(
            [x for x in (mp, mn) if x and x.get("abs_value") is not None],
            key=lambda x: x["abs_value"],
            default=mp or mn,
        ) if (mp or mn) else None
        cp, cn = th["offset"][net_id]["class_pos"], th["offset"][net_id]["class_neg"]
        def abs_of(x):
            if not x:
                return None
            return x.get("abs_value") if x.get("abs_value") is not None else abs(x.get("value") or 0)
        cands = [c for c in (cp, cn) if c]
        th["offset"][net_id]["class"] = min(cands, key=lambda x: abs_of(x) or 9) if cands else None

        th["leakage"][net_id] = {
            "mae_pos": max_tolerable(
                [r for r in leakage[net_id] if (r.get("i_leak") or 0) >= 0],
                "i_leak", "mae", ERROR_LIMIT, True,
            ),
            "mae_neg": max_tolerable(
                [r for r in leakage[net_id] if (r.get("i_leak") or 0) <= 0],
                "i_leak", "mae", ERROR_LIMIT, True,
            ),
            "class_pos": max_tolerable(
                [{**r, "acc100": 1.0 if class_ok(r) else 0.0} for r in leakage[net_id] if (r.get("i_leak") or 0) >= 0],
                "i_leak", "acc100", 1.0, False,
            ),
            "class_neg": max_tolerable(
                [{**r, "acc100": 1.0 if class_ok(r) else 0.0} for r in leakage[net_id] if (r.get("i_leak") or 0) <= 0],
                "i_leak", "acc100", 1.0, False,
            ),
        }
        lp, ln = th["leakage"][net_id]["mae_pos"], th["leakage"][net_id]["mae_neg"]
        leak_cands = [x for x in (lp, ln) if x and x.get("abs_value") is not None]
        th["leakage"][net_id]["mae"] = min(leak_cands, key=lambda x: x["abs_value"]) if leak_cands else (lp or ln)
        lcp, lcn = th["leakage"][net_id]["class_pos"], th["leakage"][net_id]["class_neg"]
        lcands = [c for c in (lcp, lcn) if c]
        th["leakage"][net_id]["class"] = min(lcands, key=lambda x: abs_of(x) or 9) if lcands else None

    rout_mae = max_tolerable(rout["F"], "rout", "mae", ERROR_LIMIT, True)
    rout_cls = max_tolerable(
        [{**r, "acc100": 1.0 if class_ok(r) else 0.0} for r in rout["F"]],
        "rout", "acc100", 1.0, False,
    )
    # If MAE never exceeds 1e-3 over the sweep, Rout is not the analog limiter
    # at A=1e5 (finite-A floor already ~5e-4).
    all_pass = all((r.get("mae") or 9) <= ERROR_LIMIT for r in rout["F"] if not r.get("failed"))
    th["rout"] = {
        "analog": None if all_pass else (rout_mae or {}).get("abs_value") or (rout_mae or {}).get("value"),
        "classification": (rout_cls or {}).get("value") if rout_cls and rout_cls.get("status") != "fails_at_min_swept" else None,
        "conservative": None,
        "mechanism": (
            "Negligible vs finite-A floor at A=1e5 over 0–100 kΩ in this macromodel"
            if all_pass
            else "Rout reduces loop gain"
        ),
        "raw": rout_mae,
    }
    report["thresholds"] = th

    if report.get("bandwidth", {}).get("isolated"):
        unit = [
            r for r in report["bandwidth"]["isolated"]
            if not r.get("failed") and r.get("label", "unit_ones") == "unit_ones"
        ]
        windows = (1e-5, 1e-4, 1e-3)
        fp_by_window = {}
        gbw_by_window = {}
        for w in windows:
            fp_by_window[w] = None
            gbw_by_window[w] = None
            for r in sorted(unit, key=lambda r: r["pole_hz"]):
                tset = r.get("t_abs_1e3_s")
                if tset is not None and tset <= w:
                    fp_by_window[w] = r["pole_hz"]
                    gbw_by_window[w] = r.get("gbw_proxy_hz")
                    break
        fp_1e3 = fp_by_window[1e-5]
        fp_interp = fp_1e3
        unit_sorted = sorted(
            [r for r in unit if r.get("t_abs_1e3_s") is not None],
            key=lambda r: r["pole_hz"],
        )
        for lo, hi in zip(unit_sorted, unit_sorted[1:]):
            t0, t1 = lo["t_abs_1e3_s"], hi["t_abs_1e3_s"]
            if (t0 - 1e-5) * (t1 - 1e-5) <= 0 and t0 > 0 and t1 > 0:
                frac = (math.log(1e-5) - math.log(t0)) / (math.log(t1) - math.log(t0))
                frac = min(1.0, max(0.0, frac))
                fp_interp = math.exp(
                    math.log(lo["pole_hz"]) + frac * (math.log(hi["pole_hz"]) - math.log(lo["pole_hz"]))
                )
                break
        swept_ok = sorted(
            r["pole_hz"] for r in unit
            if r.get("t_abs_1e3_s") is not None and r["t_abs_1e3_s"] <= 1e-5
        )
        cons_fp = swept_ok[0] if swept_ok else fp_1e3
        report["bandwidth"]["summary"] = {
            "fp_for_1e3": fp_interp,
            "fp_sampled_pass_10us": fp_1e3,
            "gbw_proxy_for_10us": (fp_interp * 1e5) if fp_interp else gbw_by_window[1e-5],
            "fp_for_100us": fp_by_window[1e-4],
            "fp_for_1ms": fp_by_window[1e-3],
            "fp_for_class_note": "DC classification is independent of f_p once settled",
            "fp_conservative": cons_fp,
            "window_s": 1e-5,
            "note": (
                "f_p such that |v-vfinal|<1e-3 of the settled value (not of z) "
                "within 10 us on the worst-G_tot isolated neuron, A=1e5, unit step. "
                "Analog f_p is log-interpolated. Conservative f_p is the first "
                "swept pole that met the window. gbw_proxy = A * f_p, not "
                "transistor f_T. Finite-A DC error vs z remains after settling."
            ),
        }

    print("Design-rule check: per-neuron k_j vs F SPICE MAE", flush=True)
    cfg_f = ARCH_C_CFG["F"]
    design_rows = []
    for rec in sorted(gain["F"], key=lambda r: r.get("A") or 0):
        a = rec.get("A")
        if a is None or rec.get("mae") is None:
            continue
        if a not in GAIN_SWEEP and abs(math.log10(a) - round(math.log10(a))) > 0.05:
            continue
        net_k, cat_k, rsn = compile_iv(
            "A", f["spec"], f["weights"],
            IVParams(name=f"k{a:g}", amp_gain=a, invert_gain=INVERT_PINNED),
        )
        if rsn or cat_k is None:
            continue
        fac = neuron_k_factors(f["spec"], cat_k, a, cfg_f.g_weight_1, cfg_f.g_weight_2)
        yk = predict_neuron(f["weights"], f["x"], fac, RAIL)
        mae_k = float(np.mean(np.abs(yk - f["y"])))
        design_rows.append({
            "A": a,
            "spice_mae": rec["mae"],
            "kj_theory_mae_vs_frozen": mae_k,
            "spice_minus_kj": rec["mae"] - mae_k,
            "k_hidden_min": fac["k_hidden_min"],
            "k_output_min": fac["k_output_min"],
            "Rf_Gtot_hidden_max": fac["Rf_Gtot_hidden_max"],
        })
    iso_theory = {}
    for tag, rows in (gain.get("isolated") or {}).items():
        ok = [r for r in rows if not r.get("failed") and r.get("mae_vs_theory") is not None]
        if ok:
            iso_theory[tag] = {
                "max_mae_vs_theory": max(r["mae_vs_theory"] for r in ok),
                "mae_vs_z_at_A1e5": next(
                    (r["mae_vs_z"] for r in ok if abs(r["A"] - 1e5) < 1), None
                ),
            }
    report["design_rule"] = {
        "formula": "k_j = A / (A + 1 + Rf * G_phys_j)",
        "network_F": design_rows,
        "isolated_vs_theory": iso_theory,
        "note": (
            "kj_theory_mae is the frozen-map error of the per-neuron scale "
            "model (not a SPICE correction). spice_minus_kj is leftover "
            "shared-tap / invert / ReLU discrepancy."
        ),
    }

    print("Phase 9: full-network validation points", flush=True)
    a_mae = (th["gain"]["F"].get("mae") or {}).get("sampled_pass") or (th["gain"]["F"].get("mae") or {}).get("value")
    a_cls = (th["gain"]["F"].get("class") or {}).get("sampled_pass") or (th["gain"]["F"].get("class") or {}).get("value")
    val = {}
    points = {
        "I_ideal": None,
        "A_class": a_cls,
        "A_analog": a_mae,
        "A_1e5_exp17": 1e5,
        "A_1e6": 1e6,
    }
    for net_id, pack in nets.items():
        val[net_id] = {}
        rec_i = baseline[net_id]["I"]
        val[net_id]["I_ideal"] = rec_i
        for name, aval in points.items():
            if name == "I_ideal" or aval is None:
                continue
            params = VGParams(name=name, amp_gain=float(aval), linear=False)
            rec, _, _ = eval_network(
                ngspice, pack["spec"], pack["weights"], params,
                pack["x"], pack["y"], dest(net_id, "val", name),
            )
            val[net_id][name] = {
                k: rec.get(k) for k in ("mae", "max_abs_error", "accuracy", "failed", "A")
            }
            val[net_id][name]["A"] = float(aval)
            print(
                f"    {net_id} {name} A={aval:g} MAE={fmt(rec.get('mae'))} acc={rec.get('accuracy')}",
                flush=True,
            )
    report["validation"] = val

    # Isolated vs network offset comparison at 1 mV
    iso_1m = [
        r for r in offset["isolated"].get(worst_off["tag"], [])
        if abs((r.get("vos") or 0) - 1e-3) < 1e-9
    ]
    net_1m = [r for r in offset["F"] if abs((r.get("vos") or 0) - 1e-3) < 1e-9]
    report["isolated_vs_network_vos_1mV"] = {
        "isolated_mae_vs_z": iso_1m[0].get("mae_vs_z") if iso_1m else None,
        "F_mae": net_1m[0].get("mae") if net_1m else None,
        "note": (
            "Isolated MAE is vs that neuron's software z; F MAE is vs the frozen "
            "network outputs. Not a like-for-like tightness ranking."
        ),
    }

    conclude(report)
    report["plots"] = write_plots(report)
    write_markdown(report)

    def default(o):
        if isinstance(o, (np.floating, np.integer)):
            return float(o)
        if isinstance(o, np.ndarray):
            return o.tolist()
        raise TypeError(type(o))

    # Slim ranking from the big report (full list is in WORST_JSON)
    slim = dict(report)
    if "ranking" in slim and "neurons" in (slim.get("ranking") or {}):
        slim["ranking"] = {k: v for k, v in slim["ranking"].items() if k != "neurons"}
    REPORT_JSON.write_text(json.dumps(slim, indent=2, default=default), encoding="utf-8")
    print(f"wrote {REPORT_JSON}", flush=True)
    print(f"wrote {REPORT_MD}", flush=True)
    print(report.get("final_status"), flush=True)
    print(report.get("conclusion"), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
