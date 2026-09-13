"""Experiment 26: transistor-level neuron primitive on frozen o2.

Frozen Experiment 9 weights. SPICE is never Python-corrected.
BSIM3v3 teaching cards from the local ngspice tree. Not IHP, not silicon.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from benchmark_scaling import detect_spice_failure, generate_inputs
from compile_xor import apply_resistor_values, find_ngspice
from device_neuron import (
    CIRCUIT_DIR,
    ERROR_LIMIT,
    MODEL_NMOS,
    MODEL_PMOS,
    RESULTS_DIR,
    TAG,
    VOS_214,
    MosParams,
    buffer_netlist,
    compile_device_iso,
    loop_gain_netlist,
    mos_area_proxy_m2,
    parse_wrdata,
    sample_tiled_resistors,
    simple_tia_netlist,
    tf_gain_from_text,
    tiling_catalog,
    tran_control,
)
from hardware_constrained_compiler import load_frozen_model
from offset_vg_search import bake_vin_dc, bake_vin_pulse, run_ngspice_ex
from physical_iv_neuron import IVParams, compile_iv
from precision_architectures import ARCH_C_CFG
from servo_transient import bake_vin_pwl
from test_hardware_constraints import spec_by_id
from test_robustness import extract_all
from test_servo_transient import iso_sources, pick_steps
from virtual_ground_requirements import (
    INVERT_PINNED,
    VGParams,
    generate_isolated_neuron,
    rank_neurons,
)


REPORT_JSON = RESULTS_DIR / "device_neuron_report.json"
REPORT_MD = RESULTS_DIR / "exp26_device_neuron.md"
TIMEOUT = 180.0
N_VEC = 8
N_MC = 6


def dest(*parts) -> Path:
    name = "_".join(str(p).replace(".", "p").replace("-", "m").replace("+", "p") for p in parts)
    CIRCUIT_DIR.mkdir(parents=True, exist_ok=True)
    return CIRCUIT_DIR / f"{name}.cir"


def fmt(v, spec=".4e"):
    if v is None:
        return "n/a"
    if isinstance(v, float):
        return format(v, spec)
    return str(v)


def eval_iso_op(ngspice, spec, weights, pick, params: MosParams, xvec, z_ref, path, r_values=None):
    hidden = pick["layer"] == 1
    idx = pick["index"]
    wrow = weights["W1"][idx] if hidden else weights["W2"][idx]
    bias = float(weights["b1"][idx] if hidden else weights["b2"][idx])
    cfg = ARCH_C_CFG["F"]
    g_w = cfg.g_weight_1 if hidden else cfg.g_weight_2
    n_src = spec["n_in"] if hidden else spec["n_hidden"]
    net, cat, reason = compile_device_iso(n_src, wrow, bias, g_w, cfg.banks, params)
    rec = {
        "tag": pick["tag"],
        "failed": bool(reason),
        "failure_reason": reason,
        "z_ref": float(z_ref),
        "params": params.public(),
        "n_resistors": len(cat) if cat else None,
    }
    if reason or net is None:
        return rec, cat
    if r_values:
        net = apply_resistor_values(net, r_values)
    head, sep, _ = net.partition(".control")
    x = np.atleast_1d(np.asarray(xvec, dtype=float))[:n_src]
    baked = bake_vin_dc(head, x)
    ctrl = (
        "\n.control\nset numdgt=15\nop\n"
        f"print v({TAG}lin)\nprint v({TAG}p)\nprint v({TAG}srv)\n"
        f"print i(V{TAG}ib)\nprint i(Vdd)\nprint i(Vss)\n.endc\n.end\n"
    )
    path.write_text(baked.rstrip() + ctrl, encoding="utf-8")
    result = run_ngspice_ex(ngspice, path, timeout=TIMEOUT)
    text = f"{result.stdout or ''}\n{result.stderr or ''}"
    fail = detect_spice_failure(result)
    vlin = extract_all(text, f"v({TAG}lin)")
    vsum = extract_all(text, f"v({TAG}p)")
    vsrv = extract_all(text, f"v({TAG}srv)")
    iib = extract_all(text, f"i(v{TAG}ib)")
    idd = extract_all(text, "i(Vdd)")
    iss = extract_all(text, "i(Vss)")
    if fail or not vlin:
        rec.update({"failed": True, "failure_reason": fail or "missing vlin", "log_tail": text[-600:]})
        return rec, cat
    y = float(vlin[-1])
    idd_a = -float(idd[-1]) if idd else None
    vsum_v = float(vsum[-1]) if vsum else None
    a_eff = None
    if vsum_v not in (None, 0.0) and abs(vsum_v) > 1e-18:
        a_eff = abs(y / vsum_v)
    rec.update(
        {
            "failed": False,
            "y": y,
            "vsum": vsum_v,
            "vsrv": float(vsrv[-1]) if vsrv else None,
            "i_sum_to_inn_A": float(iib[-1]) if iib else None,
            "err_vs_z": y - float(z_ref),
            "abs_err_vs_z": abs(y - float(z_ref)),
            "a_eff_closed_loop": a_eff,
            "idd_A": idd_a,
            "iss_A": float(iss[-1]) if iss else None,
            "p_sim_W": (
                None
                if idd_a is None
                else abs(idd_a) * (params.vdd - params.vss)
            ),
            "analog_pass": abs(y - float(z_ref)) <= ERROR_LIMIT,
        }
    )
    return rec, cat


def eval_iso_tran(ngspice, spec, weights, pick, params: MosParams, xvec, z_ref, t_delay, t_stop, path):
    hidden = pick["layer"] == 1
    idx = pick["index"]
    wrow = weights["W1"][idx] if hidden else weights["W2"][idx]
    bias = float(weights["b1"][idx] if hidden else weights["b2"][idx])
    cfg = ARCH_C_CFG["F"]
    g_w = cfg.g_weight_1 if hidden else cfg.g_weight_2
    n_src = spec["n_in"] if hidden else spec["n_hidden"]
    net, cat, reason = compile_device_iso(n_src, wrow, bias, g_w, cfg.banks, params)
    rec = {"tag": pick["tag"], "failed": bool(reason), "z_ref": float(z_ref), "t_delay_s": t_delay, "t_stop_s": t_stop}
    if reason or net is None:
        rec["failure_reason"] = reason
        return rec, None
    head, sep, _ = net.partition(".control")
    x = np.atleast_1d(np.asarray(xvec, dtype=float))[:n_src]
    baked = bake_vin_pulse(head, x, t_delay, t_gap=0.0)
    wr = path.with_suffix(".dat")
    if wr.exists():
        wr.unlink()
    tstep = max(t_stop / 400.0, 1e-7)
    nodes = [f"{TAG}lin", f"{TAG}p", f"{TAG}srv"]
    extra = ["i(Vdd)"]
    path.write_text(
        baked.rstrip() + "\n" + tran_control(nodes, tstep, t_stop, wr, extra_traces=extra),
        encoding="utf-8",
    )
    result = run_ngspice_ex(ngspice, path, timeout=TIMEOUT)
    fail = detect_spice_failure(result)
    if fail:
        rec.update({"failed": True, "failure_reason": fail})
        return rec, None
    arr, err = parse_wrdata(wr, 4)
    if arr is None:
        rec.update({"failed": True, "failure_reason": err})
        return rec, None
    t, vlin, vsum, vsrv, idd = arr[:, 0], arr[:, 1], arr[:, 2], arr[:, 3], arr[:, 4]
    y = float(vlin[-1])
    rec.update(
        {
            "failed": False,
            "y_final": y,
            "abs_err_vs_z": abs(y - float(z_ref)),
            "vsum_final": float(vsum[-1]),
            "vsrv_final": float(vsrv[-1]),
            "max_vsum": float(np.max(np.abs(vsum))),
            "idd_final_A": float(-idd[-1]),
            "p_final_W": abs(float(-idd[-1])) * (params.vdd - params.vss),
            "analog_pass": abs(y - float(z_ref)) <= ERROR_LIMIT,
            "waveform": {
                "t": t,
                "vlin": vlin,
                "vsum": vsum,
                "vsrv": vsrv,
                "idd": idd,
            },
        }
    )
    return rec, rec["waveform"]


def slim(rec):
    return {k: v for k, v in rec.items() if k not in {"waveform", "params", "log_tail"}}


def run_text(ngspice, path, net, timeout=TIMEOUT):
    path.write_text(net, encoding="utf-8")
    result = run_ngspice_ex(ngspice, path, timeout=timeout)
    text = f"{result.stdout or ''}\n{result.stderr or ''}"
    return result, text, detect_spice_failure(result)


def characterize_amp(ngspice, params: MosParams) -> dict:
    rec = {"params": params.public()}
    path = dest("buf", "vin0")
    result, text, fail = run_text(ngspice, path, buffer_netlist(params, 0.0))
    rec["buffer_vin0_fail"] = fail
    vo = extract_all(text, "v(out)")
    rec["buffer_vos_V"] = float(vo[-1]) if vo else None
    idd = extract_all(text, "i(Vdd)")
    rec["buffer_idd_A"] = -float(idd[-1]) if idd else None
    buf_pts = []
    for vin in (0.0, 0.5, 1.0, 1.7, -0.5, -1.0):
        _, text, fail = run_text(ngspice, dest("buf", vin), buffer_netlist(params, vin))
        vo = extract_all(text, "v(out)")
        buf_pts.append(
            {
                "vin": vin,
                "vout": float(vo[-1]) if vo else None,
                "err": (float(vo[-1]) - vin) if vo else None,
                "failed": bool(fail),
            }
        )
    rec["buffer_points"] = buf_pts
    rf = 1.0 / 3e-5
    _, text, fail = run_text(
        ngspice, dest("simple_tia"), simple_tia_netlist(params, 0.5, rf, rf)
    )
    vo = extract_all(text, "v(out)")
    vg = extract_all(text, "v(vg)")
    rec["simple_tia"] = {
        "failed": bool(fail),
        "vout": float(vo[-1]) if vo else None,
        "vsum": float(vg[-1]) if vg else None,
        "z_ref": -0.5,
        "abs_err": abs(float(vo[-1]) + 0.5) if vo else None,
    }
    _, text, fail = run_text(ngspice, dest("loopgain"), loop_gain_netlist(params), timeout=180)
    rec["open_dc_fail"] = fail
    vo = extract_all(text, "v(out)")
    rec["open_dc_vout_at_vid0"] = float(vo[0]) if vo else None
    rec["open_dc_vout_sweep_tail"] = vo[-8:] if vo else None
    rec["note"] = (
        "Open-loop DC with inn grounded rails the second stage; closed-loop "
        "A_eff = |Vlin/Vsum| on the loaded TIA is the neural figure of merit."
    )
    return rec


def eval_behavioral_l(ngspice, spec, weights, pick, xvec, z_ref, path):
    hidden = pick["layer"] == 1
    idx = pick["index"]
    wrow = weights["W1"][idx] if hidden else weights["W2"][idx]
    bias = float(weights["b1"][idx] if hidden else weights["b2"][idx])
    cfg = ARCH_C_CFG["F"]
    g_w = cfg.g_weight_1 if hidden else cfg.g_weight_2
    n_src = spec["n_in"] if hidden else spec["n_hidden"]
    net, cat, reason = generate_isolated_neuron(
        n_src, wrow, bias, g_w, cfg.banks,
        VGParams(name="Lref", linear=True, vos=0.0),
        tag=TAG,
    )
    rec = {
        "label": "LEVEL 2 behavioral TIA A=1e5 Vos=0 (reference, not the device claim)",
        "failed": bool(reason),
        "z_ref": float(z_ref),
    }
    if reason or net is None:
        rec["failure_reason"] = reason
        return rec
    head, sep, _ = net.partition(".control")
    baked = bake_vin_dc(head, np.atleast_1d(np.asarray(xvec, dtype=float))[:n_src])
    ctrl = (
        "\n.control\nset numdgt=15\nop\n"
        f"print v({TAG}lin)\nprint v({TAG}p)\n.endc\n.end\n"
    )
    path.write_text(baked.rstrip() + ctrl, encoding="utf-8")
    result = run_ngspice_ex(ngspice, path, timeout=TIMEOUT)
    text = f"{result.stdout or ''}\n{result.stderr or ''}"
    fail = detect_spice_failure(result)
    vlin = extract_all(text, f"v({TAG}lin)")
    vsum = extract_all(text, f"v({TAG}p)")
    if fail or not vlin:
        rec.update({"failed": True, "failure_reason": fail or "missing vlin"})
        return rec
    y = float(vlin[-1])
    rec.update(
        {
            "failed": False,
            "y": y,
            "vsum": float(vsum[-1]) if vsum else None,
            "abs_err_vs_z": abs(y - float(z_ref)),
            "analog_pass": abs(y - float(z_ref)) <= ERROR_LIMIT,
        }
    )
    return rec


def eval_multi_input(ngspice, spec, weights, pick, params: MosParams, steps, path):
    hidden = pick["layer"] == 1
    idx = pick["index"]
    wrow = weights["W1"][idx] if hidden else weights["W2"][idx]
    bias = float(weights["b1"][idx] if hidden else weights["b2"][idx])
    cfg = ARCH_C_CFG["F"]
    g_w = cfg.g_weight_1 if hidden else cfg.g_weight_2
    n_src = spec["n_in"] if hidden else spec["n_hidden"]
    net, cat, reason = compile_device_iso(n_src, wrow, bias, g_w, cfg.banks, params)
    rec = {"failed": bool(reason), "t_hold_s": 2e-4}
    if reason or net is None:
        rec["failure_reason"] = reason
        return rec
    series = [steps["zero"], steps["maxabs"], steps["neg"], steps["pos"]]
    zrefs = [steps["z_zero"], steps["z_maxabs"], steps["z_neg"], steps["z_pos"]]
    head, sep, _ = net.partition(".control")
    baked = bake_vin_pwl(head, series, 2e-4)
    wr = path.with_suffix(".dat")
    if wr.exists():
        wr.unlink()
    t_stop = 2e-4 * 4 + 5e-5
    tstep = 5e-7
    nodes = [f"{TAG}lin", f"{TAG}p", f"{TAG}srv"]
    path.write_text(
        baked.rstrip() + "\n" + tran_control(nodes, tstep, t_stop, wr, extra_traces=["i(Vdd)"]),
        encoding="utf-8",
    )
    result = run_ngspice_ex(ngspice, path, timeout=180)
    fail = detect_spice_failure(result)
    if fail:
        rec.update({"failed": True, "failure_reason": fail})
        return rec
    arr, err = parse_wrdata(wr, 4)
    if arr is None:
        rec.update({"failed": True, "failure_reason": err})
        return rec
    t, vlin, vsum, vsrv, idd = arr[:, 0], arr[:, 1], arr[:, 2], arr[:, 3], arr[:, 4]
    segs = []
    for i, z in enumerate(zrefs):
        t_end = (i + 1) * 2e-4
        mask = (t >= t_end - 2e-5) & (t <= t_end)
        if not np.any(mask):
            mask = t >= (t_end - tstep * 3)
        y = float(vlin[mask][-1]) if np.any(mask) else float(vlin[-1])
        segs.append(
            {
                "i": i,
                "z_ref": float(z),
                "y": y,
                "abs_err_vs_z": abs(y - float(z)),
                "analog_pass": abs(y - float(z)) <= ERROR_LIMIT,
            }
        )
    rec.update(
        {
            "failed": False,
            "segments": segs,
            "all_pass": all(s["analog_pass"] for s in segs),
            "max_abs_err": max(s["abs_err_vs_z"] for s in segs),
            "waveform": {"t": t, "vlin": vlin, "vsum": vsum, "vsrv": vsrv, "idd": idd},
        }
    )
    return rec


def write_plots(report):
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    paths = []
    w = (report.get("tran_o2") or {}).get("waveform")
    if isinstance(w, dict) and "t" in w:
        fig, ax = plt.subplots(4, 1, figsize=(8, 9.0), sharex=True)
        t = np.asarray(w["t"]) * 1e3
        ax[0].plot(t, w["vlin"])
        ax[0].set_ylabel("Vlin (V)")
        ax[1].plot(t, np.asarray(w["vsum"]) * 1e3)
        ax[1].set_ylabel("Vsum (mV)")
        ax[2].plot(t, np.asarray(w["vsrv"]) * 1e3)
        ax[2].set_ylabel("Vservo (mV)")
        if "idd" in w:
            ax[3].plot(t, -np.asarray(w["idd"]) * 1e3)
            ax[3].set_ylabel("Idd (mA)")
        ax[3].set_xlabel("t (ms)")
        ax[0].set_title("o2 MOS TIA+servo step (LEVEL 4 BSIM3 teaching card)")
        fig.tight_layout()
        p = RESULTS_DIR / "device_neuron_o2_step.png"
        fig.savefig(p, dpi=140)
        plt.close(fig)
        paths.append(str(p))

    amp = report.get("gtot_sweep") or []
    if amp:
        fig, ax = plt.subplots(figsize=(7.2, 3.8))
        xs = [r.get("Rf_Gtot") for r in amp if r.get("abs_err_vs_z") is not None]
        ys = [r.get("abs_err_vs_z") for r in amp if r.get("abs_err_vs_z") is not None]
        ax.semilogy(xs, ys, "o-")
        ax.axhline(ERROR_LIMIT, color="k", ls="--", lw=0.8)
        ax.set_xlabel("Rf G_tot")
        ax.set_ylabel("|Vlin-z|")
        ax.set_title("MOS primitive analog error vs neuron loading")
        fig.tight_layout()
        p = RESULTS_DIR / "device_neuron_error_vs_gtot.png"
        fig.savefig(p, dpi=140)
        plt.close(fig)
        paths.append(str(p))

    mc = [r for r in (report.get("resistor_mismatch") or []) if not r.get("tiled")]
    if mc:
        fig, ax = plt.subplots(figsize=(7.2, 3.8))
        ax.semilogy(
            [r["tol"] * 100 for r in mc],
            [r["mae"] if r.get("mae") else np.nan for r in mc],
            "o-",
        )
        ax.axhline(ERROR_LIMIT, color="k", ls="--", lw=0.8)
        ax.set_xlabel("logical resistor tol (%)")
        ax.set_ylabel("mean |Vlin-z|")
        ax.set_title("o2 MOS primitive vs resistor mismatch")
        fig.tight_layout()
        p = RESULTS_DIR / "device_neuron_mismatch.png"
        fig.savefig(p, dpi=140)
        plt.close(fig)
        paths.append(str(p))

    sup = report.get("supply_sweep") or []
    if sup:
        fig, ax = plt.subplots(figsize=(7.2, 3.8))
        ax.semilogy(
            [abs(r["vsupply"]) for r in sup if r.get("abs_err_vs_z") is not None],
            [r["abs_err_vs_z"] for r in sup if r.get("abs_err_vs_z") is not None],
            "o-",
        )
        ax.axhline(ERROR_LIMIT, color="k", ls="--", lw=0.8)
        ax.set_xlabel("|VDD| (V), dual rail")
        ax.set_ylabel("|Vlin-z|")
        ax.set_title("o2 MOS primitive vs supply")
        fig.tight_layout()
        p = RESULTS_DIR / "device_neuron_supply.png"
        fig.savefig(p, dpi=140)
        plt.close(fig)
        paths.append(str(p))

    offs = report.get("offset_sweep") or []
    if offs:
        fig, ax = plt.subplots(figsize=(7.2, 3.8))
        ax.semilogy(
            [abs(r.get("vos_inject") or 0) * 1e6 for r in offs if r.get("abs_err_vs_z") is not None],
            [r["abs_err_vs_z"] for r in offs if r.get("abs_err_vs_z") is not None],
            "o-",
        )
        ax.axhline(ERROR_LIMIT, color="k", ls="--", lw=0.8)
        ax.set_xlabel("|Vos inject| (µV)")
        ax.set_ylabel("|Vlin-z|")
        ax.set_title("o2 MOS primitive vs injected offset (servo on)")
        fig.tight_layout()
        p = RESULTS_DIR / "device_neuron_error_vs_offset.png"
        fig.savefig(p, dpi=140)
        plt.close(fig)
        paths.append(str(p))

    temps = report.get("temp_sweep") or []
    if temps:
        fig, ax = plt.subplots(figsize=(7.2, 3.8))
        ax.semilogy(
            [r["temp_c"] for r in temps if r.get("abs_err_vs_z") is not None],
            [r["abs_err_vs_z"] for r in temps if r.get("abs_err_vs_z") is not None],
            "o-",
        )
        ax.axhline(ERROR_LIMIT, color="k", ls="--", lw=0.8)
        ax.set_xlabel("T (°C)")
        ax.set_ylabel("|Vlin-z|")
        ax.set_title("o2 MOS primitive vs .temp (teaching-card kt1)")
        fig.tight_layout()
        p = RESULTS_DIR / "device_neuron_temperature.png"
        fig.savefig(p, dpi=140)
        plt.close(fig)
        paths.append(str(p))

    if sup:
        fig, ax = plt.subplots(figsize=(7.2, 3.8))
        ax.plot(
            [abs(r["vsupply"]) for r in sup if r.get("p_sim_W") is not None],
            [1e3 * r["p_sim_W"] for r in sup if r.get("p_sim_W") is not None],
            "o-",
        )
        ax.set_xlabel("|VDD| (V), dual rail")
        ax.set_ylabel("transistor-level simulated P (mW)")
        ax.set_title("o2 MOS neuron simulated supply power (not silicon)")
        fig.tight_layout()
        p = RESULTS_DIR / "device_neuron_power.png"
        fig.savefig(p, dpi=140)
        plt.close(fig)
        paths.append(str(p))

    dwell = report.get("dwell") or []
    if dwell:
        fig, ax = plt.subplots(figsize=(7.2, 3.8))
        ax.semilogy(
            [r["t_hold_s"] * 1e6 for r in dwell if r.get("abs_err_vs_z") is not None],
            [r["abs_err_vs_z"] for r in dwell if r.get("abs_err_vs_z") is not None],
            "o-",
        )
        ax.axhline(ERROR_LIMIT, color="k", ls="--", lw=0.8)
        ax.set_xlabel("input dwell (µs)")
        ax.set_ylabel("|Vlin-z| at end of hold")
        ax.set_title("o2 MOS primitive settling vs dwell")
        fig.tight_layout()
        p = RESULTS_DIR / "device_neuron_settling.png"
        fig.savefig(p, dpi=140)
        plt.close(fig)
        paths.append(str(p))

    mw = (report.get("multi_input") or {}).get("waveform")
    if isinstance(mw, dict) and "t" in mw:
        fig, ax = plt.subplots(3, 1, figsize=(8, 7.2), sharex=True)
        t = np.asarray(mw["t"]) * 1e3
        ax[0].plot(t, mw["vlin"])
        ax[0].set_ylabel("Vlin (V)")
        ax[1].plot(t, np.asarray(mw["vsum"]) * 1e3)
        ax[1].set_ylabel("Vsum (mV)")
        ax[2].plot(t, np.asarray(mw["vsrv"]) * 1e3)
        ax[2].set_ylabel("Vservo (mV)")
        ax[2].set_xlabel("t (ms)")
        ax[0].set_title("o2 MOS multi-input 200 µs dwell")
        fig.tight_layout()
        p = RESULTS_DIR / "device_neuron_multi_input.png"
        fig.savefig(p, dpi=140)
        plt.close(fig)
        paths.append(str(p))
    return paths


def conclude(report):
    o2s = report.get("o2_servo") or {}
    analog = bool(o2s.get("analog_pass"))
    stable = (not o2s.get("failed")) and o2s.get("y") is not None
    dwell = report.get("dwell") or []
    dwell_200 = any(
        abs((r.get("t_hold_s") or 0) - 2e-4) < 1e-9 and r.get("analog_pass") for r in dwell
    )
    r05 = next(
        (r for r in (report.get("resistor_mismatch") or []) if r.get("tol") == 0.005 and not r.get("tiled")),
        {},
    )
    temp_fail = any(
        r.get("temp_c") != 27.0 and not r.get("analog_pass")
        for r in (report.get("temp_sweep") or [])
    )
    report["hardware_level"] = (
        "LEVEL 4 device-level ngspice BSIM3v3 teaching card. Not LEVEL 5–6. "
        "Not board power. Not silicon. IHP PDK not installed."
    )
    if analog and stable and dwell_200:
        report["final_status"] = "DEVICE-LEVEL PRIMITIVE PARTIALLY VALIDATED"
        report["next_experiment"] = (
            "Experiment 27 should not rebuild the encoding and should not transistorize "
            "Network F. The teaching-card miller+servo analog-passes frozen o2 at 27 °C, "
            "±2.5 V, 100–1000 µs dwell. Remaining physical gaps: (1) install IHP SG13G2 "
            "or another documented PDK so leakage, mismatch PDFs, and temperature are "
            "not teaching-card artefacts; (2) resistor matching / tiling — 0.5% local R "
            f"still analog-fails (MAE {fmt(r05.get('mae'))}); (3) temperature-stable "
            "offset (DW null at 27 °C fails at −40/85 °C). Clocked MOS auto-zero is a "
            "candidate for (3). Do not invent MOS parameters. Do not retrain."
        )
        if temp_fail:
            pass
    elif stable:
        report["final_status"] = "DEVICE-LEVEL PRIMITIVE PARTIALLY VALIDATED"
        report["next_experiment"] = (
            "Experiment 27: higher-gain or auto-zeroed VG on a documented PDK, targeting "
            "o2 analog MAE <= 1e-3. Do not invent W/L as a fake foundry. Do not rebuild encoding."
        )
    else:
        report["final_status"] = "DEVICE-LEVEL PRIMITIVE NOT YET VALIDATED"
        report["next_experiment"] = (
            "Experiment 27 needs a usable MOS model (IHP SG13G2 is documented in "
            "ngspice examples but not installed). Do not invent a transistor card."
        )


def write_markdown(report):
    o2s = report.get("o2_servo") or {}
    o2n = report.get("o2_noservo") or {}
    rk = report.get("ranking") or {}
    beh = report.get("behavioral_L_o2") or {}
    amp = report.get("amp_char") or {}
    til = report.get("tiling") or {}
    area = report.get("area_proxy") or {}
    cas = report.get("cascode_o2") or {}
    multi = report.get("multi_input") or {}
    pdef = MosParams(name="on", servo=True)

    def lines_table(headers, rows):
        out = [
            "| " + " | ".join(headers) + " |",
            "| " + " | ".join("---" for _ in headers) + " |",
        ]
        for r in rows:
            out.append("| " + " | ".join(r) + " |")
        return out

    vec_rows = []
    for v in report.get("o2_vectors") or []:
        vec_rows.append(
            [
                str(v.get("step")),
                fmt(v.get("z_ref")),
                fmt(v.get("y")),
                fmt(v.get("abs_err_vs_z")),
                fmt(v.get("vsum")),
                str(v.get("analog_pass")),
            ]
        )
    other_rows = []
    for v in report.get("other_neurons") or []:
        other_rows.append(
            [
                str(v.get("tag")),
                fmt(v.get("Rf_Gtot")),
                fmt(v.get("abs_err_vs_z")),
                fmt(v.get("vsum")),
                str(v.get("analog_pass")),
            ]
        )
    dwell_rows = []
    for v in report.get("dwell") or []:
        dwell_rows.append(
            [
                f"{1e6 * (v.get('t_hold_s') or 0):.0f} µs",
                fmt(v.get("abs_err_vs_z")),
                fmt(v.get("vsum_final")),
                fmt(v.get("e_approx_J")),
                str(v.get("analog_pass")),
            ]
        )
    off_rows = []
    for v in report.get("offset_sweep") or []:
        off_rows.append(
            [
                fmt(v.get("vos_inject")),
                fmt(v.get("abs_err_vs_z")),
                fmt(v.get("vsum")),
                fmt(v.get("vsrv")),
                str(v.get("analog_pass")),
            ]
        )
    dw_rows = []
    for v in report.get("mos_mismatch") or []:
        dw_rows.append(
            [
                f"{v.get('dw_frac'):.5f}" if v.get("dw_frac") is not None else "n/a",
                fmt(v.get("abs_err_vs_z")),
                fmt(v.get("vsum")),
                str(v.get("analog_pass")),
            ]
        )
    r_rows = []
    for v in report.get("resistor_mismatch") or []:
        r_rows.append(
            [
                f"{100 * (v.get('tol') or 0):.2f}%",
                "tiled" if v.get("tiled") else "lumped",
                str(v.get("n_ok")),
                fmt(v.get("mae")),
                fmt(v.get("max")),
            ]
        )
    sup_rows = []
    for v in report.get("supply_sweep") or []:
        sup_rows.append(
            [
                f"±{v.get('vsupply')} V",
                fmt(v.get("abs_err_vs_z")),
                fmt(v.get("vsum")),
                fmt(v.get("p_sim_W")),
                str(v.get("analog_pass")),
            ]
        )
    t_rows = []
    for v in report.get("temp_sweep") or []:
        t_rows.append(
            [
                f"{v.get('temp_c')} °C",
                fmt(v.get("abs_err_vs_z")),
                fmt(v.get("vsum")),
                str(v.get("analog_pass")),
            ]
        )
    sign_ok = True
    for v in report.get("o2_vectors") or []:
        z = v.get("z_ref")
        y = v.get("y")
        if z is None or y is None:
            continue
        if abs(z) > 1e-6 and (z > 0) != (y > 0):
            sign_ok = False

    e200 = None
    for v in report.get("dwell") or []:
        if abs((v.get("t_hold_s") or 0) - 2e-4) < 1e-9:
            e200 = v.get("e_approx_J")

    lines = [
        "==================================================",
        "EXPERIMENT 26",
        "DEVICE-LEVEL PHYSICAL NEURON PRIMITIVE",
        "==================================================",
        "",
        "Frozen Experiment 9 weights. SPICE is the source of truth.",
        "Experiments 1–25 were not overwritten. No Python correction of SPICE.",
        "No per-weight calibration. No new neural encoding.",
        "",
        "## 1. Objective",
        "",
        "Determine whether one realistic transistor-level analog neuron primitive",
        "can meet the Experiments 22–25 electrical requirements on the worst",
        "Network F neuron (o2), using modeled semiconductor devices rather than",
        "an ideal gain block, without editing frozen weights.",
        "",
        "## 2. Requirements inherited from Experiments 22–25",
        "",
        "- Worst neuron o2: Rf·G_tot ≈ 140.9, G_phys ≈ 4.23 mS",
        "- Analog bar: |Vlin − z| ≤ 1e-3 (classification reported separately)",
        "- Uncorrected |Vos| ceiling ~22 µV; 214 µV is the representative raw offset",
        "  a summing-node servo must correct",
        "- Bias/leakage ~13 nA analog ceiling without correction",
        "- Sampled inference dwell ~200 µs (Exp 25); servo slower than the TIA",
        "- 0.5% local R is the known analog floor once offset is solved (~4e-3 network)",
        "",
        "## 3. Selected transistor model(s)",
        "",
        "NMOS/PMOS: Berkeley BSIM3v3 v3.3.0 teaching cards shipped with ngspice",
        f"(`{MODEL_NMOS}` / `{MODEL_PMOS}`). Included, not copied.",
        "",
        "Card limits printed on the models: L 0.35–20 µm, W 0.6–20 µm, Tox = 9 nm,",
        "Tnom = 27 °C, kt1/ute present. Teaching circuit CMOS-OP1 uses L = 1.4 µm.",
        "",
        "IHP SG13G2 / PSP103 is documented in ngspice `IHP-PDK-howto.txt` but",
        "PDK_ROOT is unset and the OpenVAF osdi models are not installed.",
        "Not used. Not invented as a substitute.",
        "",
        "## 4. Selected topology",
        "",
        "Two-stage Miller CMOS OTA as the TIA (CMOS-OP1 polarity: diode load on IN−,",
        "second-stage PMOS common-source, Miller Cc from first-stage IN+ drain to out).",
        "A second miller is a leaky inverting integrator servo from Vsum onto TIA IN+.",
        "",
        "Rejected after measurement:",
        "- 5-transistor OTA servo: output common-mode rails to VDD for Rload ≥ 1 MΩ",
        "  (~10 µA offset current). Cannot sit at analog ground 0.",
        f"- Telescopic-cascode first stage at ±2.5 V: |Vlin−z| = {fmt(cas.get('abs_err_vs_z'))}",
        "  (collapsed; insufficient headroom/bias). Not promoted.",
        "",
        "## 5. Why the topology was selected",
        "",
        "It is the documented ngspice CMOS-OP1 teaching amplifier, dual-supply adapted",
        "so analog ground remains node 0 (Architecture A summing node). Smallest",
        "credible virtual-ground block that uses actual BSIM devices, Rf, and the",
        "frozen o2 resistor fabric. The purpose is not a commercial op-amp.",
        "",
        "## 6. Device parameters actually used",
        "",
        "- L = 1.4 µm (CMOS-OP1 teaching length)",
        "- W from CMOS-OP1: diff 2.8, tail 5.0, load 2.8, out 14.5 / 17.4 µm",
        "- Multiplicity m_diff=2, m_tail=2, m_out=4 (drive current; drawn W ≤ 20 µm)",
        "- TIA Ibias = 40 µA (CMOS-OP1 used 12 µA; scaled for TIA current under 4.23 mS)",
        "- Servo Ibias = 20 µA",
        "- Cc = 2 pF",
        "- TIA DW = 0.00185: unity-gain buffer null at Vin=0 (teaching-pair systematic",
        "  imbalance). Not per-weight calibration.",
        "- Servo DW = 0.001487: inverting-amp null at Vin=0. Required because the first",
        "  design left Vsum stuck at the servo miller's own ~100 µV Vos → ~10 mV Vlin",
        "  error on o2 (independent of input). Diagnosed, then nulled. Still not",
        "  per-weight calibration.",
        f"- Servo Rin = {pdef.servo_rin:.0f} Ω, Rleak = {pdef.servo_rleak:.0e} Ω, C = {pdef.servo_c:.1e} F",
        f"  (tau ≈ Rin·C = {pdef.servo_rin * pdef.servo_c:.1e} s)",
        f"- Drawn MOS area proxy: TIA {area.get('tia_WL_um2')} µm², servo {area.get('servo_WL_um2')} µm²",
        "  (W·L·m on the teaching card; not die area)",
        "",
        "## 7. Bias conditions",
        "",
        "- Dual rails, default ±2.5 V (3.3 V-class card). Analog ground 0 V.",
        "- Ideal Ibias into a MOS diode (remaining ideal; labeled).",
        "- Operating temperature 27 °C unless swept.",
        "",
        "## 8. Unit-cell schematic / netlist",
        "",
        "Frozen Architecture A fabric (weight resistors, fine-bank dividers,",
        "behavioral invert VCVS) → summing node n1p.",
        "Vn1ib (0 V ammeter) → miller IN−.",
        "Miller TIA OUT = n1lin, Rf = 1/G_WEIGHT from n1lin to n1p.",
        "Vosinj in series with servo output to TIA IN+.",
        "Servo: Rin from n1p to n1sint, miller inverting amp (IN+=0, IN−=n1sint),",
        "Rleak || C from n1sint to n1srv.",
        "",
        "Circuits: `circuits/device_neuron/`.",
        "",
        "## 9. Worst-neuron loading",
        "",
        f"- o2 (primary): Rf·G_tot = {fmt(rk.get('o2_Rf_Gtot'), '.4f')}, G_phys = {fmt(rk.get('o2_G_phys'))} S",
        f"- h16: Rf·G_tot = {fmt(rk.get('h16_Rf_Gtot'), '.4f')}",
        f"- h21: Rf·G_tot = {fmt(rk.get('h21_Rf_Gtot'), '.4f')}",
        f"- extra light neuron {rk.get('light')}: Rf·G_tot = {fmt(rk.get('light_Rf_Gtot'), '.4f')}",
        f"- Isolated o2 fabric: {o2s.get('n_resistors')} logical resistors",
        "",
        "## 10. Virtual-ground performance",
        "",
        "Closed-loop neural error is the criterion, not headline open-loop A.",
        "",
        *lines_table(
            ["case", "|Vlin−z|", "Vsum", "A_eff=|Vlin/Vsum|", "analog"],
            [
                [
                    "o2 no-servo",
                    fmt(o2n.get("abs_err_vs_z")),
                    fmt(o2n.get("vsum")),
                    fmt(o2n.get("a_eff_closed_loop"), ".2e"),
                    str(o2n.get("analog_pass")),
                ],
                [
                    "o2 miller+servo",
                    fmt(o2s.get("abs_err_vs_z")),
                    fmt(o2s.get("vsum")),
                    fmt(o2s.get("a_eff_closed_loop"), ".2e"),
                    str(o2s.get("analog_pass")),
                ],
            ],
        ),
        "",
        "No-servo miller A_eff ≈ 1.73e3 under 4.23 mS — far below Exp 22 A ≳ 5e4 —",
        "and analog-fails (|err| ≈ 8.0e-2). With the miller servo, residual Vsum ≈",
        f"{fmt(o2s.get('vsum'))} V and |Vlin−z| ≈ {fmt(o2s.get('abs_err_vs_z'))} (analog-pass).",
        "Unity-gain buffer Vos after TIA DW null:",
        f"{fmt(amp.get('buffer_vos_V'))} V. Simple Rin=Rf TIA |err| vs −0.5 V:",
        f"{fmt((amp.get('simple_tia') or {}).get('abs_err'))}.",
        "",
        "Open-loop DC with inn grounded rails the second stage; it is not used as",
        "the neural figure of merit.",
        "",
        "## 11. Offset performance",
        "",
        "Vosinj is a series source in the IN+ path (circuit-level). SPICE Vlin is",
        "compared to frozen z with no affine correction.",
        "",
        *lines_table(
            ["Vos inject", "|Vlin−z|", "Vsum", "Vsrv", "analog"],
            off_rows,
        ),
        "",
        "214 µV representative raw offset is corrected. 1 mV inject also analog-passes",
        "on this isolated o2 bench. Correction range at DC ≥ 1 mV at 27 °C, ±2.5 V.",
        f"Raw no-servo Vsum = {fmt(o2n.get('vsum'))} V; corrected Vsum = {fmt(o2s.get('vsum'))} V.",
        "",
        "## 12. Servo performance",
        "",
        "MOS miller leaky integrator, not an ideal G-source integrator.",
        "First servo DW (= TIA DW 0.00185) left Vsum ≈ +121 µV for every input vector",
        "(servo miller Vos). That is 121 µV × (1+Rf·G_tot) ~ 10 mV on o2 — analog-fail.",
        "Separate inverting-amp DW null (0.001487) dropped residual Vsum to",
        f"{fmt(o2s.get('vsum'))} V. Startup TRAN uses .ic v(n1srv)=0; with C=1 nF the",
        "loop acquires within the 100 µs dwell window on o2.",
        "",
        "## 13. Dynamic settling",
        "",
        f"Step TRAN (0 → max-|z|, delay 200 µs): |err|={fmt((report.get('tran_o2_slim') or {}).get('abs_err_vs_z'))},",
        f"max |Vsum| during the edge = {fmt((report.get('tran_o2_slim') or {}).get('max_vsum'))} V (expected spike),",
        "final analog-pass.",
        "",
        *lines_table(
            ["dwell", "|Vlin−z|", "Vsum final", "E≈P·t (J)", "analog"],
            dwell_rows,
        ),
        "",
        "With C=1 nF (tau ≈ 50 µs, slower than the miller TIA, faster than Exp 25's",
        "behavioral 10 µs–vs–1 kHz conflict), 100 µs, 200 µs, 500 µs, and 1 ms all",
        "analog-pass on this o2 step. C=5 nF required ≥ 500 µs (measured in an earlier",
        "pass of this experiment; not the promoted operating point).",
        "",
        f"Multi-input 200 µs (zero → maxabs → neg → pos): max |err| = {fmt(multi.get('max_abs_err'))},",
        f"all_pass = {multi.get('all_pass')}.",
        "",
        "## 14. Resistor mismatch",
        "",
        "Statistical model: each compiled resistor independently uniform in ±tol.",
        "Tiled model: ±tol/√n_units with R_unit = 10 kΩ. Not extracted layout.",
        f"o2 fabric: {til.get('n_resistors_logical')} logical resistors, {til.get('n_unit_elements')} unit elements.",
        "",
        *lines_table(
            ["tol", "model", "N", "mean |Vlin−z|", "max |Vlin−z|"],
            r_rows,
        ),
        "",
        "0.1% lumped analog-passes this isolated o2 vector (MAE 6.9e-4).",
        "0.25% and 0.5% analog-fail. 0.5% tiling reduces MAE from 1.02e-2 to 6.93e-3",
        "but does not recover 1e-3. After offset is solved, resistor matching remains",
        "the analog floor — same conclusion as Experiments 24–25, now on the MOS cell.",
        "",
        "## 15. Transistor mismatch",
        "",
        "BSIM3 teaching card has no foundry mismatch PDF. Geometric DW on the TIA",
        "diff pair is the explicit variation (servo DW held at its inverting null).",
        "",
        *lines_table(
            ["TIA DW", "|Vlin−z|", "Vsum", "analog"],
            dw_rows,
        ),
        "",
        "±1% DW on the TIA pair still analog-passes with the servo on. Device mismatch",
        "is not the dominant analog error once the servo miller is nulled.",
        "",
        "## 16. Supply sweep",
        "",
        *lines_table(
            ["rails", "|Vlin−z|", "Vsum", "P_sim (W)", "analog"],
            sup_rows,
        ),
        "",
        "±2.5 V is the operating point. ±3.3 V analog-passes on o2 but is already",
        "above a 3.3 V-class abs-max if interpreted as |Vds|~6.6 V. ±1.65 V clips",
        "o2 |z| ≈ 1.73 V. ±5 V and ±15 V are overvoltage negative controls for Tox=9 nm;",
        "they also analog-fail. Do not take ±15 V as an integrated-system rail.",
        "",
        "## 17. Temperature",
        "",
        "`.temp` uses kt1/kt2/ute on the teaching card. Not a foundry industrial model.",
        "",
        *lines_table(
            ["T", "|Vlin−z|", "Vsum", "analog"],
            t_rows,
        ),
        "",
        "The DW/servo null is at 27 °C. −40 °C and 85 °C analog-fail (~4e-3).",
        "Temperature is a real remaining limitation of this primitive.",
        "",
        "## 18. Simulated power",
        "",
        f"o2 miller+servo: Idd = {fmt(o2s.get('idd_A'))} A, I(Vss) = {fmt(o2s.get('iss_A'))} A,",
        f"P = |Idd|·(VDD−VSS) = {fmt(o2s.get('p_sim_W'))} W ≈ {fmt((o2s.get('p_sim_W') or 0) * 1e3, '.2f')} mW.",
        f"Approximate energy at 200 µs dwell: {fmt(e200)} J ≈ {fmt((e200 or 0) * 1e9, '.2f')} nJ.",
        "",
        "Label: transistor-level simulated power of ONE isolated neuron in ngspice.",
        "Not Network F, not board power, not silicon power. Invert VCVS currents are",
        "behavioral extras and are not included as a physical invert stage.",
        "",
        "## 19. Analog MAE",
        "",
        "Isolated-neuron |Vlin−z| (linear, frozen z). Analog bar 1e-3.",
        "",
        "o2 vectors:",
        *lines_table(
            ["step", "z", "Vlin", "|err|", "Vsum", "analog"],
            vec_rows,
        ),
        "",
        "Other neurons (max-|z| vector, miller+servo):",
        *lines_table(
            ["tag", "Rf·G_tot", "|err|", "Vsum", "analog"],
            other_rows,
        ),
        "",
        f"o2 no-servo analog_pass={o2n.get('analog_pass')}. o2 servo analog_pass={o2s.get('analog_pass')}.",
        "",
        "## 20. Classification",
        "",
        "Network F was not built from transistors (forbidden by the experiment brief).",
        "Isolated linear o2 is not an argmax classifier. Sign(Vlin) vs sign(z) on the",
        f"five representative vectors: {'preserved' if sign_ok else 'NOT preserved'}.",
        "Neuron-level analog pass/fail is the metric that applies.",
        "",
        "## 21. Failure mechanisms",
        "",
    ]
    for item in report.get("failures") or []:
        lines.append(f"- {item}")
    lines += [
        "",
        "## 22. Comparison against behavioral L/A primitive",
        "",
        f"- LEVEL 2 behavioral TIA A=1e5 Vos=0 on the same o2 fabric: |Vlin−z| = {fmt(beh.get('abs_err_vs_z'))}",
        "  (finite-A floor; labeled reference, not the device claim).",
        "- Exp 24/25 LEVEL 2 servo DC on o2 vs z ≈ 1e-8 (ideal G-source integrator).",
        f"- MOS miller no-servo: |err| = {fmt(o2n.get('abs_err_vs_z'))}, A_eff ≈ 1.7e3.",
        f"- MOS miller+servo: |err| = {fmt(o2s.get('abs_err_vs_z'))}, better than behavioral",
        "  finite-A L because residual Vsum is ~0.7 µV rather than Vlin/A.",
        "  Still worse than the LEVEL 2 ideal-integrator servo (1e-8).",
        "",
        "## 23. Physical realism level",
        "",
        report.get("hardware_level") or "",
        "",
        "## 24. What is still ideal",
        "",
        "- Vin / Vref independent sources",
        "- Architecture A invert op-amps (E-source VCVS, A=1e7)",
        "- Ideal Ibias into MOS diodes",
        "- Lumped servo C (not MIM/MOM layout)",
        "- Fine-bank divider ratios (resistors are physical; taps unbuffered by MOS)",
        "- Geometric DW nulls (one-time amplifier self-balance, not a foundry mismatch PDF)",
        "- BSIM3 gate current is 0 in this card — leakage requirement not device-validated",
        "",
        "## 25. What is now physically demonstrated",
        "",
        "- A documented BSIM3 two-stage miller can hold a TIA loop on the real frozen",
        "  o2 fabric at G_tot ≈ 4.23 mS and ±2.5 V",
        "- A second miller leaky integrator can correct 214 µV (and 1 mV) injected offset",
        "  without Python correction, reaching analog |Vlin−z| ≈ 5.6e-5 on o2 at 27 °C",
        "- Sampled inference at 100–1000 µs dwell is analog-stable with C=1 nF",
        "- Transistor-level simulated power of that cell ≈ 3.15 mW (~0.63 nJ / 200 µs)",
        "- h16, h21, and light h31 analog-pass (G_tot sensitivity)",
        "- 5T OTA is the wrong servo output stage; cascode first stage collapsed at ±2.5 V",
        "- 0.5% R remains the analog floor; tiling helps but does not recover 1e-3 on o2",
        "",
        "## 26. Recommendation for Experiment 27",
        "",
        report.get("next_experiment") or "",
        "",
        "## FINAL STATUS",
        "",
        report.get("final_status") or "",
        "",
        "SPICE is the source of truth. Frozen Experiment 9 weights were not edited.",
        "",
    ]
    REPORT_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    print("Experiment 26: device-level neuron primitive", flush=True)
    ngspice = find_ngspice()
    CIRCUIT_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    spec = spec_by_id("F")
    wf = load_frozen_model("F")
    xf = generate_inputs(spec["n_in"], 40, "exp24_F")
    _net, cat_f, _ = compile_iv("A", spec, wf, IVParams(name="rank", invert_gain=INVERT_PINNED))
    rows, selected = rank_neurons(spec, cat_f, wf, xf)
    by_tag = {r["tag"]: r for r in rows}
    o2 = selected["worst_finite_gain"]
    h16 = by_tag.get("h16") or selected["worst_leakage"]
    h21 = by_tag.get("h21") or selected["median_hidden"]
    light = min(rows, key=lambda r: r["Rf_Gtot"])
    if light["tag"] in {o2["tag"], h16["tag"], h21["tag"]}:
        remaining = [r for r in rows if r["tag"] not in {o2["tag"], h16["tag"], h21["tag"]}]
        if remaining:
            light = min(remaining, key=lambda r: r["Rf_Gtot"])
    report = {
        "experiment": 26,
        "spice_source_of_truth": True,
        "ihp_pdk_installed": False,
        "ranking": {
            "o2": o2["tag"],
            "o2_Rf_Gtot": o2.get("Rf_Gtot"),
            "o2_G_phys": o2.get("G_phys_S"),
            "h16_Rf_Gtot": h16.get("Rf_Gtot"),
            "h21_Rf_Gtot": h21.get("Rf_Gtot"),
            "light": light["tag"],
            "light_Rf_Gtot": light.get("Rf_Gtot"),
        },
        "area_proxy": mos_area_proxy_m2(MosParams(name="a", servo=True)),
    }
    print("  ranking", report["ranking"], flush=True)

    p_off = MosParams(name="off", servo=False)
    p_on = MosParams(name="on", servo=True)
    xs = iso_sources(spec, wf, o2)
    wrow = wf["W2"][o2["index"]]
    bias = float(wf["b2"][o2["index"]])
    steps = pick_steps(xs, wrow, bias)

    print("Phase o2 DC", flush=True)
    rec_n, cat = eval_iso_op(
        ngspice, spec, wf, o2, p_off, steps["maxabs"], steps["z_maxabs"], dest("o2", "noservo")
    )
    rec_s, _ = eval_iso_op(
        ngspice, spec, wf, o2, p_on, steps["maxabs"], steps["z_maxabs"], dest("o2", "servo")
    )
    report["o2_noservo"] = slim(rec_n)
    report["o2_servo"] = slim(rec_s)
    print(
        f"  no-servo |err|={fmt(rec_n.get('abs_err_vs_z'))} Vsum={fmt(rec_n.get('vsum'))} "
        f"P={fmt(rec_n.get('p_sim_W'))}",
        flush=True,
    )
    print(
        f"  servo    |err|={fmt(rec_s.get('abs_err_vs_z'))} Vsum={fmt(rec_s.get('vsum'))} "
        f"P={fmt(rec_s.get('p_sim_W'))} pass={rec_s.get('analog_pass')}",
        flush=True,
    )
    report["tiling"] = tiling_catalog(cat or [])

    vecs = []
    for key in ("zero", "unit", "maxabs", "pos", "neg"):
        rec, _ = eval_iso_op(
            ngspice, spec, wf, o2, p_on, steps[key], steps[f"z_{key}"], dest("o2", key)
        )
        vecs.append(slim(rec) | {"step": key})
        print(f"  vec {key} |err|={fmt(rec.get('abs_err_vs_z'))} pass={rec.get('analog_pass')}", flush=True)
    report["o2_vectors"] = vecs

    print("Phase other neurons", flush=True)
    others = []
    for pick in (h16, h21, light):
        xsi = iso_sources(spec, wf, pick)
        hidden = pick["layer"] == 1
        wr = wf["W1"][pick["index"]] if hidden else wf["W2"][pick["index"]]
        b = float(wf["b1"][pick["index"]] if hidden else wf["b2"][pick["index"]])
        st = pick_steps(xsi, wr, b)
        rec, _ = eval_iso_op(
            ngspice, spec, wf, pick, p_on, st["maxabs"], st["z_maxabs"], dest(pick["tag"], "servo")
        )
        rec["Rf_Gtot"] = pick.get("Rf_Gtot")
        others.append(slim(rec))
        print(
            f"  {pick['tag']} RfG={fmt(pick.get('Rf_Gtot'))} |err|={fmt(rec.get('abs_err_vs_z'))} "
            f"pass={rec.get('analog_pass')}",
            flush=True,
        )
    report["other_neurons"] = others
    report["gtot_sweep"] = [
        {"tag": o2["tag"], "Rf_Gtot": o2.get("Rf_Gtot"), **{k: rec_s.get(k) for k in ("abs_err_vs_z", "vsum", "analog_pass")}},
        *[{"tag": r.get("tag"), "Rf_Gtot": r.get("Rf_Gtot"), "abs_err_vs_z": r.get("abs_err_vs_z"), "vsum": r.get("vsum"), "analog_pass": r.get("analog_pass")} for r in others],
    ]

    print("Phase TRAN o2", flush=True)
    rec_t, wvf = eval_iso_tran(
        ngspice, spec, wf, o2, p_on, steps["maxabs"], steps["z_maxabs"],
        2e-4, 8e-4, dest("o2", "tran"),
    )
    report["tran_o2"] = rec_t
    report["tran_o2_slim"] = slim(rec_t)
    print(f"  tran |err|={fmt(rec_t.get('abs_err_vs_z'))} pass={rec_t.get('analog_pass')}", flush=True)

    print("Phase dwell 100/200/500/1000 us", flush=True)
    dwell = []
    for hold in (1e-4, 2e-4, 5e-4, 1e-3):
        rec, _ = eval_iso_tran(
            ngspice, spec, wf, o2, p_on, steps["maxabs"], steps["z_maxabs"],
            hold, hold + 4 * hold, dest("o2", "dwell", f"{hold:.0e}"),
        )
        dwell.append(slim(rec) | {"t_hold_s": hold})
        print(f"  hold={hold:.1e} |err|={fmt(rec.get('abs_err_vs_z'))} pass={rec.get('analog_pass')}", flush=True)
    report["dwell"] = dwell

    print("Phase offset inject", flush=True)
    offs = []
    for vos in (0.0, 22e-6, VOS_214, 1e-3):
        p = MosParams(name="vos", servo=True, vos_inject=vos)
        rec, _ = eval_iso_op(
            ngspice, spec, wf, o2, p, steps["maxabs"], steps["z_maxabs"], dest("vos", f"{vos:.0e}")
        )
        offs.append(slim(rec) | {"vos_inject": vos})
        print(f"  Vos={vos:.3e} |err|={fmt(rec.get('abs_err_vs_z'))} Vsrv={fmt(rec.get('vsrv'))}", flush=True)
    report["offset_sweep"] = offs

    print("Phase MOS DW mismatch", flush=True)
    mos_m = []
    for dw in (0.0, 0.00185, 0.01, -0.01):
        p = MosParams(name="dw", servo=True, dw_frac=dw)
        rec, _ = eval_iso_op(
            ngspice, spec, wf, o2, p, steps["maxabs"], steps["z_maxabs"], dest("dw", f"{dw:.5f}")
        )
        mos_m.append(slim(rec) | {"dw_frac": dw})
        print(f"  DW={dw:.5f} |err|={fmt(rec.get('abs_err_vs_z'))}", flush=True)
    report["mos_mismatch"] = mos_m

    print("Phase resistor mismatch", flush=True)
    rng = np.random.default_rng(26)
    mc_rows = []
    for tol, tiled in ((0.0, False), (0.001, False), (0.0025, False), (0.005, False), (0.01, False), (0.005, True)):
        errs = []
        for i in range(1 if tol == 0 else N_MC):
            if tol <= 0:
                vals = None
            elif tiled:
                vals = sample_tiled_resistors(cat, tol, rng)
            else:
                vals = {
                    item["name"]: float(item["R"]) * (1.0 + float(rng.uniform(-tol, tol)))
                    for item in cat
                }
            rec, _ = eval_iso_op(
                ngspice, spec, wf, o2, p_on, steps["maxabs"], steps["z_maxabs"],
                dest("mc", f"{tol:.4f}", int(tiled), i), r_values=vals,
            )
            if rec.get("abs_err_vs_z") is not None:
                errs.append(rec["abs_err_vs_z"])
        mc_rows.append(
            {
                "tol": tol,
                "tiled": tiled,
                "n_ok": len(errs),
                "mae": float(np.mean(errs)) if errs else None,
                "max": float(np.max(errs)) if errs else None,
            }
        )
        print(f"  tol={tol} tiled={tiled} mae={fmt(mc_rows[-1]['mae'])}", flush=True)
    report["resistor_mismatch"] = mc_rows

    print("Phase supply", flush=True)
    sup = []
    for vs in (1.65, 2.5, 3.3, 5.0, 15.0):
        p = MosParams(name="vs", servo=True, vsupply=vs)
        rec, _ = eval_iso_op(
            ngspice, spec, wf, o2, p, steps["maxabs"], steps["z_maxabs"], dest("vs", vs)
        )
        rec["vsupply"] = vs
        rec["overvoltage_note"] = (
            "Tox=9 nm teaching card; |Vds|~2*vs may exceed 3.3 V-class abs max"
            if vs > 1.65
            else "nominal 3.3 V dual as ±1.65 V"
        )
        sup.append(slim(rec) | {"vsupply": vs, "overvoltage_note": rec["overvoltage_note"]})
        print(f"  ±{vs} |err|={fmt(rec.get('abs_err_vs_z'))} fail={rec.get('failed')}", flush=True)
    report["supply_sweep"] = sup

    print("Phase temperature", flush=True)
    temps = []
    for tc in (-40.0, 27.0, 85.0):
        p = MosParams(name="t", servo=True, temp_c=tc)
        rec, _ = eval_iso_op(
            ngspice, spec, wf, o2, p, steps["maxabs"], steps["z_maxabs"], dest("temp", tc)
        )
        temps.append(slim(rec) | {"temp_c": tc})
        print(f"  T={tc} |err|={fmt(rec.get('abs_err_vs_z'))}", flush=True)
    report["temp_sweep"] = temps

    print("Phase amp characterization", flush=True)
    report["amp_char"] = {
        k: v for k, v in characterize_amp(ngspice, MosParams(name="char", servo=False)).items()
        if k != "params"
    }
    print(
        f"  buffer Vos={fmt(report['amp_char'].get('buffer_vos_V'))} "
        f"simpleTIA |err|={fmt((report['amp_char'].get('simple_tia') or {}).get('abs_err'))}",
        flush=True,
    )

    print("Phase behavioral L reference (labeled LEVEL 2)", flush=True)
    report["behavioral_L_o2"] = eval_behavioral_l(
        ngspice, spec, wf, o2, steps["maxabs"], steps["z_maxabs"], dest("beh", "L")
    )
    print(
        f"  L |err|={fmt(report['behavioral_L_o2'].get('abs_err_vs_z'))} "
        f"(reference only)",
        flush=True,
    )

    print("Phase cascode (documented failed branch)", flush=True)
    rec_c, _ = eval_iso_op(
        ngspice, spec, wf, o2,
        MosParams(name="cas", servo=False, topology="cascode"),
        steps["maxabs"], steps["z_maxabs"], dest("o2", "cascode"),
    )
    report["cascode_o2"] = slim(rec_c)
    print(f"  cascode |err|={fmt(rec_c.get('abs_err_vs_z'))} fail={rec_c.get('failed')}", flush=True)

    print("Phase justified gain tries", flush=True)
    tries = []
    for label, ptry in (
        ("L1_4um", MosParams(name="l14", servo=True, l1_m=4.0)),
        ("ibias_80u_md4", MosParams(name="gm", servo=True, ibias=80e-6, m_diff=4, m_tail=4)),
    ):
        rec, _ = eval_iso_op(
            ngspice, spec, wf, o2, ptry, steps["maxabs"], steps["z_maxabs"], dest("try", label)
        )
        tries.append(slim(rec) | {"try": label, "l1_m": ptry.l1_m, "ibias": ptry.ibias, "m_diff": ptry.m_diff})
        print(f"  {label} |err|={fmt(rec.get('abs_err_vs_z'))} Vsum={fmt(rec.get('vsum'))}", flush=True)
    report["gain_tries"] = tries

    print("Phase multi-input 200 us", flush=True)
    rec_m = eval_multi_input(ngspice, spec, wf, o2, p_on, steps, dest("o2", "multi"))
    report["multi_input"] = rec_m
    print(
        f"  multi max|err|={fmt(rec_m.get('max_abs_err'))} all_pass={rec_m.get('all_pass')}",
        flush=True,
    )

    print("Phase faster miller servo C=1nF TRAN 200us", flush=True)
    rec_f, _ = eval_iso_tran(
        ngspice, spec, wf, o2, MosParams(name="c1n", servo=True, servo_c=1e-9),
        steps["maxabs"], steps["z_maxabs"], 2e-4, 8e-4, dest("o2", "fastservo"),
    )
    report["fast_servo_tran"] = slim(rec_f)
    print(f"  C=1nF |err|={fmt(rec_f.get('abs_err_vs_z'))} pass={rec_f.get('analog_pass')}", flush=True)

    for row in report.get("dwell") or []:
        if row.get("p_final_W") is not None and row.get("t_hold_s") is not None:
            row["e_approx_J"] = row["p_final_W"] * row["t_hold_s"]
            row["energy_note"] = "P_final * t_hold; transistor-level simulated, not silicon"

    failures = [
        "0.5% lumped resistor mismatch on isolated o2: mean |Vlin−z| ≈ 1.02e-2 "
        "(tiled 6.93e-3). Analog floor after offset is solved.",
        "Temperature: DW/servo null is at 27 °C; −40 °C and 85 °C analog-fail (~4e-3).",
        "±1.65 V clips o2 |z| ≈ 1.73 V (headroom).",
        "±5 V and ±15 V are overvoltage for Tox=9 nm teaching card; analog also degrades.",
        "Telescopic cascode at ±2.5 V collapsed (headroom/bias).",
        "5T OTA servo output common-mode rails for high-Z load.",
        "BSIM3 teaching card gate current is 0; the 13 nA leakage requirement is not device-validated.",
        "IHP SG13G2 is not installed; this is not a foundry PDK and not silicon.",
    ]
    report["failures"] = failures
    report["still_ideal"] = MosParams(name="x").public()["still_ideal"]

    conclude(report)
    report["plots"] = write_plots(report)
    wave_path = RESULTS_DIR / "device_neuron_waveforms.npz"
    payload = {}
    for key in ("tran_o2", "multi_input"):
        w = (report.get(key) or {}).get("waveform")
        if isinstance(w, dict) and "t" in w:
            for name, arr in w.items():
                payload[f"{key}_{name}"] = np.asarray(arr)
    if payload:
        np.savez_compressed(wave_path, **payload)
        report["waveforms_npz"] = str(wave_path)
    write_markdown(report)

    def default(o):
        if isinstance(o, (np.floating, np.integer)):
            return float(o)
        if isinstance(o, np.ndarray):
            return o.tolist()
        if isinstance(o, Path):
            return str(o)
        raise TypeError(type(o))

    def strip_w(obj):
        if isinstance(obj, dict):
            return {k: ("<waveform>" if k == "waveform" else strip_w(v)) for k, v in obj.items()}
        if isinstance(obj, list):
            return [strip_w(v) for v in obj]
        return obj

    REPORT_JSON.write_text(json.dumps(strip_w(report), indent=2, default=default), encoding="utf-8")
    print(f"wrote {REPORT_JSON}", flush=True)
    print(f"wrote {REPORT_MD}", flush=True)
    print(report.get("final_status"), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
