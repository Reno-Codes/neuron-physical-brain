"""Experiment 25: transient validation of the summing-node servo.

Frozen Experiment 9 weights. SPICE is never Python-corrected.
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
    classification_labels,
    detect_spice_failure,
    error_stats,
    generate_inputs,
    simulate_batch,
)
from compile_xor import PROJECT_ROOT, find_ngspice
from hardware_constrained_compiler import load_frozen_model
from offset_vg_search import bake_vin_dc, bake_vin_pulse, bake_vref_pulse
from physical_iv_neuron import IVParams, compile_iv
from precision_architectures import ARCH_C_CFG, hidden_preact_max, software_reference
from servo_transient import (
    CIRCUIT_DIR,
    ERROR_LIMIT,
    EXP24_C,
    EXP24_GM,
    RESULTS_DIR,
    TAG,
    VOS_214,
    E25Params,
    bake_vin_pwl,
    choose_tstep,
    choose_tstop,
    compile_iso,
    compile_net,
    op_control,
    parse_wrdata,
    run_ngspice_ex,
    settling_metrics,
    tran_wrdata_control,
)
from test_hardware_constraints import spec_by_id
from test_robustness import extract_all, sample_resistor_values
from virtual_ground_requirements import INVERT_PINNED, rank_neurons


REPORT_JSON = RESULTS_DIR / "servo_transient_report.json"
REPORT_MD = RESULTS_DIR / "exp25_servo_transient.md"
N_A = 100
N_F = 40
N_F_TRAN = 12
N_A_TRAN = 12
N_MC = 6
TIMEOUT_OP = 180.0
TIMEOUT_TRAN = 300.0
TAU_SWEEP = (1e-8, 1e-7, 1e-6, 1e-5, 1e-4, 1e-3, 1e-2)
GAIN_SWEEP = (1e4, 5e4, 1e5)
VOS_SWEEP = (0.0, 2.2e-5, 1e-4, VOS_214, 1e-3)
WAVE_NPZ = RESULTS_DIR / "servo_transient_waveforms.npz"


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
    if isinstance(value, bool):
        return str(value)
    return str(value)


def software_for(weights, inputs, rail: float = 15.0, linear: bool = False):
    zmax, hmax = hidden_preact_max(inputs, weights["W1"], weights["b1"])
    clipped = (not linear) and hmax > rail + 1e-12
    y = software_reference(
        inputs, weights["W1"], weights["b1"], weights["W2"], weights["b2"],
        linear=linear, hidden_rail=rail if clipped else None,
    )
    return y, {"hidden_preact_max": zmax, "hidden_relu_max": hmax, "clipped": clipped}


def iso_sources(spec, weights, pick, n_vec=16):
    hidden = pick["layer"] == 1
    if hidden:
        x = generate_inputs(spec["n_in"], n_vec, "exp25_iso_h")
        return x
    xh = generate_inputs(spec["n_in"], n_vec, "exp25_iso_h")
    z1 = xh @ weights["W1"].T + weights["b1"]
    return np.maximum(0.0, z1)


def pick_steps(x, wrow, bias):
    x = np.atleast_2d(np.asarray(x, dtype=float))
    z = x @ np.asarray(wrow, float) + float(bias)
    i_max = int(np.argmax(np.abs(z)))
    i_min = int(np.argmin(z))
    i_pos = int(np.argmax(z))
    zero = np.zeros(x.shape[1], dtype=float)
    unit = np.zeros(x.shape[1], dtype=float)
    unit[0] = 1.0
    return {
        "zero": zero,
        "unit": unit,
        "maxabs": x[i_max],
        "pos": x[i_pos],
        "neg": x[i_min],
        "z_zero": float(float(bias)),
        "z_unit": float(unit @ np.asarray(wrow, float) + bias),
        "z_maxabs": float(z[i_max]),
        "z_pos": float(z[i_pos]),
        "z_neg": float(z[i_min]),
    }


def simulate_op_net(ngspice, net, inputs, n_in, nodes, path, timeout=TIMEOUT_OP):
    head, sep, _ = net.partition(".control")
    if not sep:
        return None, "no .control"
    rows = []
    for i, x in enumerate(np.atleast_2d(np.asarray(inputs, dtype=float))):
        vec_path = path.with_name(f"{path.stem}_op{i}.cir")
        baked = bake_vin_dc(head, x[:n_in])
        vec_path.write_text(baked.rstrip() + "\n" + op_control(nodes), encoding="utf-8")
        result = run_ngspice_ex(ngspice, vec_path, timeout=timeout)
        text = f"{result.stdout or ''}\n{result.stderr or ''}"
        fail = detect_spice_failure(result)
        vals = [extract_all(text, f"v({n})") for n in nodes]
        if fail or any(not v for v in vals):
            return None, fail or f"vector {i}: missing print"
        rows.append([float(v[-1]) for v in vals])
    return np.array(rows, float), None


def eval_op_network(ngspice, spec, weights, params: E25Params, inputs, y, path):
    net, cat, reason = compile_net(spec, weights, params, linear=False)
    rec = {"failed": True, "failure_reason": reason, "params": params.public()}
    if reason or net is None:
        return rec, net, cat
    path.write_text(net, encoding="utf-8")
    nodes = [f"o{k}lin" for k in range(1, spec["n_out"] + 1)]
    arr, err = simulate_op_net(ngspice, net, inputs, spec["n_in"], nodes, path)
    if err or arr is None:
        rec["failure_reason"] = err
        return rec, net, cat
    st = error_stats(arr, y)
    pred = classification_labels(arr)
    expected = classification_labels(y)
    n_fail = int(np.sum(pred != expected))
    rec = {
        "failed": False,
        "failure_reason": None,
        "mae": st["mae"],
        "max_abs_error": st["max_abs_error"],
        "accuracy": float(1.0 - n_fail / max(len(expected), 1)),
        "n_class_failures": n_fail,
        "n_resistors": len(cat),
        "params": params.public(),
    }
    return rec, net, cat


def run_tran(
    ngspice,
    net,
    path: Path,
    nodes: list[str],
    t_stop: float,
    tstep: float,
    uic: bool = False,
    reltol: float | None = None,
):
    head, sep, _ = net.partition(".control")
    if not sep:
        return None, "no .control", ""
    wr = path.with_suffix(".dat")
    if wr.exists():
        wr.unlink()
    body = head
    path.write_text(
        body.rstrip() + "\n" + tran_wrdata_control(nodes, t_stop, tstep, wr, uic=uic, reltol=reltol),
        encoding="utf-8",
    )
    result = run_ngspice_ex(ngspice, path, timeout=TIMEOUT_TRAN)
    text = f"{result.stdout or ''}\n{result.stderr or ''}"
    fail = detect_spice_failure(result)
    if fail:
        return None, fail, text[-800:]
    arr, err = parse_wrdata(wr, len(nodes))
    if err or arr is None:
        return None, err or "parse", text[-800:]
    return arr, None, text[-200:]


def iso_tran_case(
    ngspice, spec, weights, pick, params: E25Params, xvec, z_ref, mode: str, t_delay=None
):
    hidden = pick["layer"] == 1
    idx = pick["index"]
    wrow = weights["W1"][idx] if hidden else weights["W2"][idx]
    bias = float(weights["b1"][idx] if hidden else weights["b2"][idx])
    cfg = ARCH_C_CFG[spec["id"]]
    g_w = cfg.g_weight_1 if hidden else cfg.g_weight_2
    n_src = spec["n_in"] if hidden else spec["n_hidden"]
    net, cat, reason = compile_iso(n_src, wrow, bias, g_w, cfg.banks, params, tag=TAG)
    rec = {
        "tag": pick["tag"],
        "mode": mode,
        "failed": bool(reason),
        "failure_reason": reason,
        "tau_s": params.tau_s,
        "A": params.amp_gain,
        "vos": params.vos,
        "tia_pole_hz": params.tia_pole_hz,
        "z_ref": float(z_ref),
        "n_resistors": len(cat) if cat else None,
    }
    if reason or net is None:
        return rec, None
    head, sep, _ = net.partition(".control")
    x = np.atleast_1d(np.asarray(xvec, dtype=float))[:n_src]
    tau = params.tau_s if params.servo else 1e-6
    if mode == "cold_uic":
        baked = bake_vin_dc(head, x)
        t_stop = choose_tstop(tau)
        tstep = choose_tstep(tau, t_stop)
        uic = True
    elif mode == "offset_then_step":
        delay = t_delay if t_delay is not None else 4.0 * max(tau, 1e-6)
        baked = bake_vin_pulse(head, x, delay, t_gap=0.0)
        t_stop = delay + choose_tstop(tau)
        tstep = choose_tstep(tau, t_stop)
        uic = False
    else:
        baked = bake_vin_dc(head, x)
        t_stop = choose_tstop(tau)
        tstep = choose_tstep(tau, t_stop)
        uic = False
    rec["t_stop_s"] = t_stop
    rec["tstep_s"] = tstep
    rec["uic"] = uic
    rec["t_delay_s"] = delay if mode == "offset_then_step" else 0.0
    path = dest("iso", pick["tag"], params.name, mode)
    full = baked.rstrip() + "\n.control\n.endc\n.end\n"
    nodes = [f"{TAG}lin", f"{TAG}p"]
    if params.servo:
        nodes.append(f"{TAG}int")
    arr, err, log = run_tran(ngspice, full, path, nodes, t_stop, tstep, uic=uic)
    if err or arr is None:
        rec.update({"failed": True, "failure_reason": err, "log_tail": log})
        return rec, None
    t, vlin, vsum = arr[:, 0], arr[:, 1], arr[:, 2]
    vint = arr[:, 3] if arr.shape[1] > 3 else np.zeros_like(t)
    sm = settling_metrics(t, vlin, y_ref=z_ref)
    rec.update(sm)
    rec["max_vsum"] = float(np.max(np.abs(vsum)))
    rec["final_vsum"] = float(vsum[-1])
    rec["max_vint"] = float(np.max(np.abs(vint)))
    rec["final_vint"] = float(vint[-1])
    rec["waveform"] = {"t": t, "vlin": vlin, "vsum": vsum, "vint": vint}
    rec["failed"] = bool(sm.get("diverged") or sm.get("oscillating"))
    delay_s = float(rec.get("t_delay_s") or 0.0)
    t_z = rec.get("t_vs_ref_1e3_s")
    rec["t_after_step_1e3_s"] = None if t_z is None else max(0.0, float(t_z) - delay_s)
    if rec["failed"] and not rec.get("failure_reason"):
        rec["failure_reason"] = "oscillation or divergence"
    return rec, rec["waveform"]


def net_tran_vectors(
    ngspice, spec, weights, params: E25Params, inputs, y, path, t_delay=None
):
    net, cat, reason = compile_net(spec, weights, params, linear=False)
    rec = {"failed": True, "failure_reason": reason, "params": params.public()}
    if reason or net is None:
        return rec, None
    path.write_text(net, encoding="utf-8")
    n_out = spec["n_out"]
    n_in = spec["n_in"]
    nodes = [f"o{k}lin" for k in range(1, n_out + 1)]
    tau = params.tau_s
    delay = t_delay if t_delay is not None else 4.0 * max(tau, 1e-6)
    t_stop = delay + choose_tstop(tau)
    tstep = choose_tstep(tau, t_stop)
    head, sep, _ = net.partition(".control")
    rows = []
    settle = []
    for i, x in enumerate(np.atleast_2d(np.asarray(inputs, dtype=float))):
        baked = bake_vin_pulse(head, x[:n_in], delay, t_gap=0.0)
        vec_path = path.with_name(f"{path.stem}_t{i}.cir")
        full = baked.rstrip() + "\n.control\n.endc\n.end\n"
        arr, err, log = run_tran(ngspice, full, vec_path, nodes, t_stop, tstep, uic=False)
        if err or arr is None:
            rec = {"failed": True, "failure_reason": f"vector {i}: {err}", "log_tail": log}
            return rec, None
        yhat = arr[-1, 1:]
        rows.append(yhat)
        yi = np.atleast_2d(y)[i]
        settle.append(settling_metrics(arr[:, 0], arr[:, 1], y_ref=float(yi[0])))
    physical = np.array(rows, float)
    st = error_stats(physical, y)
    pred = classification_labels(physical)
    expected = classification_labels(y)
    n_fail = int(np.sum(pred != expected))
    rec = {
        "failed": False,
        "failure_reason": None,
        "mae": st["mae"],
        "max_abs_error": st["max_abs_error"],
        "accuracy": float(1.0 - n_fail / max(len(expected), 1)),
        "n_class_failures": n_fail,
        "t_stop_s": t_stop,
        "tstep_s": tstep,
        "t_delay_s": delay,
        "n_resistors": len(cat),
        "params": params.public(),
        "mean_t_abs_1e3_s": float(
            np.mean([s["t_abs_1e3_s"] for s in settle if s.get("t_abs_1e3_s") is not None])
        )
        if any(s.get("t_abs_1e3_s") is not None for s in settle)
        else None,
        "n_oscillating": int(sum(1 for s in settle if s.get("oscillating"))),
    }
    return rec, physical


def net_pwl(
    ngspice, spec, weights, params: E25Params, series, y_series, path, t_hold
):
    net, cat, reason = compile_net(spec, weights, params, linear=False)
    rec = {"failed": True, "failure_reason": reason}
    if reason or net is None:
        return rec, None
    n_out = spec["n_out"]
    nodes = [f"o{k}lin" for k in range(1, n_out + 1)]
    head, sep, _ = net.partition(".control")
    baked = bake_vin_pwl(head, series, t_hold)
    t_stop = t_hold * len(series) + 1e-6
    tstep = choose_tstep(params.tau_s, t_stop)
    full = baked.rstrip() + "\n.control\n.endc\n.end\n"
    arr, err, log = run_tran(ngspice, full, path, nodes, t_stop, tstep, uic=False)
    if err or arr is None:
        rec.update({"failure_reason": err, "log_tail": log})
        return rec, None
    t = arr[:, 0]
    yhat = arr[:, 1:]
    samples = []
    for k, yk in enumerate(y_series):
        t_samp = (k + 0.92) * t_hold
        j = int(np.argmin(np.abs(t - t_samp)))
        samples.append(yhat[j])
        rec[f"seg{k}_t"] = float(t[j])
        rec[f"seg{k}_mae"] = float(np.mean(np.abs(yhat[j] - yk)))
        rec[f"seg{k}_max"] = float(np.max(np.abs(yhat[j] - yk)))
    rec.update({
        "failed": False,
        "failure_reason": None,
        "t_hold_s": t_hold,
        "t_stop_s": t_stop,
        "tstep_s": tstep,
        "n_segments": len(series),
        "waveform": {"t": t, "y": yhat},
        "final_mae": rec.get(f"seg{len(series)-1}_mae"),
    })
    return rec, arr


def save_report(report: dict) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    waves = {}

    def strip(obj):
        if isinstance(obj, dict):
            out = {}
            for k, v in obj.items():
                if k == "waveform" and isinstance(v, dict):
                    key = obj.get("name") or obj.get("tag") or obj.get("mode") or "w"
                    uniq = f"{key}_{len(waves)}"
                    packed = {}
                    for wk, wv in v.items():
                        packed[wk] = np.asarray(wv)
                    waves[uniq] = packed
                    out[k] = uniq
                else:
                    out[k] = strip(v)
            return out
        if isinstance(obj, list):
            return [strip(v) for v in obj]
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, (np.floating, np.integer)):
            return float(obj)
        return obj

    slim = strip(report)
    if waves:
        np.savez_compressed(WAVE_NPZ, **{k: json.dumps({ak: av.tolist() for ak, av in v.items()}) for k, v in waves.items()})
        # store arrays properly
        np.savez_compressed(
            WAVE_NPZ,
            **{f"{k}__{ak}": av for k, v in waves.items() for ak, av in v.items()},
        )
        slim["waveforms_file"] = str(WAVE_NPZ)

    def default(o):
        if isinstance(o, (np.floating, np.integer)):
            return float(o)
        if isinstance(o, np.ndarray):
            return o.tolist()
        if isinstance(o, Path):
            return str(o)
        raise TypeError(type(o))

    REPORT_JSON.write_text(json.dumps(slim, indent=2, default=default), encoding="utf-8")


def write_plots(report: dict) -> list[str]:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    paths = []

    def grab_wave(rec):
        w = rec.get("waveform") if isinstance(rec, dict) else None
        if not isinstance(w, dict):
            return None
        if "t" in w:
            return w
        return None

    # unit-cell overlay
    fig, axes = plt.subplots(3, 1, figsize=(8.2, 7.2), sharex=True)
    plotted = False
    for rec in report.get("unit_cell") or []:
        w = grab_wave(rec)
        if w is None:
            continue
        if rec.get("mode") != "offset_then_step":
            continue
        if rec.get("tag") != report.get("ranking", {}).get("worst"):
            continue
        if abs(rec.get("tau_s", 0) - 1e-3) > 1e-6 and abs(rec.get("tau_s", 0) - 1e-5) > 1e-7:
            if rec.get("vos") != VOS_214:
                continue
        t = np.asarray(w["t"])
        axes[0].plot(t * 1e3, w["vlin"], label=f"tau={rec['tau_s']:.1e} Vos={rec['vos']:.1e}")
        axes[1].plot(t * 1e3, np.asarray(w["vsum"]) * 1e3)
        axes[2].plot(t * 1e3, np.asarray(w["vint"]) * 1e3)
        plotted = True
    if plotted:
        axes[0].set_ylabel("Vlin (V)")
        axes[1].set_ylabel("Vsum (mV)")
        axes[2].set_ylabel("Vint (mV)")
        axes[2].set_xlabel("t (ms)")
        axes[0].set_title("o2 offset-then-step (selected tau)")
        axes[0].legend(fontsize=7)
        fig.tight_layout()
        p = RESULTS_DIR / "servo_transient_unit_step.png"
        fig.savefig(p, dpi=140)
        paths.append(str(p))
    plt.close(fig)

    sweep = report.get("tau_sweep") or []
    if sweep:
        fig, axes = plt.subplots(1, 2, figsize=(9.2, 3.8))
        taus = [r["tau_s"] for r in sweep if r.get("err_final_vs_ref") is not None]
        err = [r["err_final_vs_ref"] for r in sweep if r.get("err_final_vs_ref") is not None]
        ts = [r.get("t_after_step_1e3_s") or np.nan for r in sweep if r.get("err_final_vs_ref") is not None]
        if taus:
            axes[0].semilogx(taus, err, "o-")
            axes[0].axhline(ERROR_LIMIT, color="k", ls="--", lw=0.8)
            axes[0].set_xlabel("tau (s)")
            axes[0].set_ylabel("|Vlin-z| final")
            axes[0].set_title("o2 analog error vs servo tau")
            axes[1].loglog(taus, np.clip(ts, 1e-8, None), "o-")
            axes[1].set_xlabel("tau (s)")
            axes[1].set_ylabel("t to |Vlin-z|<1e-3 (s)")
            axes[1].set_title("settling vs tau")
        fig.tight_layout()
        p = RESULTS_DIR / "servo_transient_tau_sweep.png"
        fig.savefig(p, dpi=140)
        paths.append(str(p))
        plt.close(fig)

    sweep_p = report.get("tau_sweep_pole_1khz") or []
    if sweep_p:
        fig, axes = plt.subplots(1, 2, figsize=(9.2, 3.8))
        taus = [r["tau_s"] for r in sweep_p if r.get("err_final_vs_ref") is not None]
        err = [r["err_final_vs_ref"] for r in sweep_p if r.get("err_final_vs_ref") is not None]
        ts = [r.get("t_after_step_1e3_s") or np.nan for r in sweep_p if r.get("err_final_vs_ref") is not None]
        if taus:
            axes[0].semilogx(taus, err, "o-")
            axes[0].axhline(ERROR_LIMIT, color="k", ls="--", lw=0.8)
            axes[0].set_xlabel("tau (s)")
            axes[0].set_ylabel("|Vlin-z| final")
            axes[0].set_title("o2 + 1 kHz TIA pole vs servo tau")
            axes[1].loglog(taus, np.clip(ts, 1e-8, None), "o-")
            axes[1].set_xlabel("tau (s)")
            axes[1].set_ylabel("t after step to |Vlin-z|<1e-3 (s)")
            axes[1].set_title("nested-loop settling vs tau")
        fig.tight_layout()
        p = RESULTS_DIR / "servo_transient_tau_sweep_pole.png"
        fig.savefig(p, dpi=140)
        paths.append(str(p))
        plt.close(fig)

    multi = report.get("multi_input") or {}
    w = grab_wave(multi.get("A") or {})
    if w and "t" in w:
        fig, ax = plt.subplots(figsize=(7.6, 3.6))
        t = np.asarray(w["t"])
        y = np.asarray(w["y"])
        ax.plot(t * 1e3, y[:, 0], label="o1lin")
        ax.set_xlabel("t (ms)")
        ax.set_ylabel("Vlin (V)")
        ax.set_title("Network A multi-input PWL")
        ax.legend(fontsize=8)
        fig.tight_layout()
        p = RESULTS_DIR / "servo_transient_multi_input.png"
        fig.savefig(p, dpi=140)
        paths.append(str(p))
        plt.close(fig)

    budget = report.get("error_budget") or {}
    rows = [(k, v.get("mae")) for k, v in budget.items() if isinstance(v, dict) and v.get("mae") is not None]
    if rows:
        fig, ax = plt.subplots(figsize=(7.4, 3.8))
        xs = np.arange(len(rows))
        ax.bar(xs, [r[1] for r in rows], color="#4c6")
        ax.axhline(ERROR_LIMIT, color="k", ls="--", lw=0.8)
        ax.set_xticks(list(xs))
        ax.set_xticklabels([r[0] for r in rows], rotation=25, ha="right")
        ax.set_yscale("log")
        ax.set_ylabel("MAE")
        ax.set_title("Exp 25 error budget (settled TRAN or OP)")
        fig.tight_layout()
        p = RESULTS_DIR / "servo_transient_error_budget.png"
        fig.savefig(p, dpi=140)
        paths.append(str(p))
        plt.close(fig)
    return paths


def conclude(report: dict) -> None:
    ftran = report.get("network_F_tran") or {}
    atran = report.get("network_A_tran") or {}
    multi = report.get("multi_input") or {}
    f_ok = (
        not ftran.get("failed")
        and ftran.get("mae") is not None
        and ftran["mae"] <= ERROR_LIMIT
        and ftran.get("n_oscillating", 0) == 0
    )
    a_ok = (
        not atran.get("failed")
        and atran.get("mae") is not None
        and atran["mae"] <= ERROR_LIMIT
    )
    multi_a = multi.get("A") or {}
    nseg = int(multi_a.get("n_segments") or 0)
    seg_ok = nseg > 0 and all(
        (multi_a.get(f"seg{k}_mae") is not None and multi_a[f"seg{k}_mae"] <= ERROR_LIMIT)
        for k in range(nseg)
    )
    t_hold = multi_a.get("t_hold_s")
    static_only = bool(t_hold is not None and t_hold >= 5e-4)
    src = report.get("tau_selection_source")
    sweep = report.get("tau_sweep_pole_1khz") if src == "pole_1khz" else (report.get("tau_sweep") or [])
    analog_taus = [
        r for r in sweep
        if r.get("err_final_vs_ref") is not None
        and r["err_final_vs_ref"] <= ERROR_LIMIT
        and not r.get("oscillating")
        and not r.get("diverged")
    ]
    report["best_operating_point"] = {
        "tau_s": report.get("selected_tau_s"),
        "source": src,
        "tia_pole_hz": 1e3 if src == "pole_1khz" else 0.0,
        "vos": VOS_214,
        "amp_gain": 1e5,
        "kind": "LEVEL 2 OTA-C leaky integrator",
        "n_analog_stable_tau": len(analog_taus),
    }
    if analog_taus:
        fastest = min(analog_taus, key=lambda r: r["tau_s"])
        report["fastest_analog_tau_s"] = fastest["tau_s"]
    else:
        report["fastest_analog_tau_s"] = None
    if f_ok and a_ok and seg_ok and not static_only:
        status = "DYNAMIC SERVO VALIDATED"
        nxt = (
            "Experiment 26: mismatch-aware analog budget / tighter R, or a LEVEL 2 "
            "device-like VG unit cell. Do not rebuild encoding. Do not invent MOS W/L on F."
        )
    elif f_ok and a_ok:
        status = "DYNAMIC SERVO PARTIALLY VALIDATED"
        nxt = (
            "Experiment 26: treat the servo as static/calibrated inference (dwell >= several tau) "
            "or develop Vref-gated auto-zero timing. Nested-loop continuous inference is not proven. "
            "Do not invent MOS W/L on Network F."
        )
    else:
        status = "DYNAMIC SERVO FAILED"
        nxt = (
            "Experiment 26 should pivot to the Exp 24 Vref-gated auto-zero primitive "
            "(already TRAN analog-pass) and its hold/clock limits. Do not rebuild encoding."
        )
    report["final_status"] = status
    report["next_experiment"] = nxt
    report["static_calibrated_only"] = static_only and f_ok
    report["hardware_level"] = (
        "LEVEL 2 OTA-C leaky integrator + XSPICE limit TIA. Not LEVEL 3-6. "
        "Not board power or silicon."
    )


def write_markdown(report: dict) -> None:
    lines = [
        "==================================================",
        "EXPERIMENT 25",
        "TRANSIENT VALIDATION OF THE VIRTUAL-GROUND SERVO",
        "==================================================",
        "",
        "Frozen Experiment 9 weights. SPICE is the source of truth.",
        "Experiments 1–24 were not overwritten. Analog MAE and classification are separate.",
        "",
        "## 1. Objective",
        "Determine whether the Experiment 24 summing-node servo can function dynamically",
        "for analog inference (stability, settling, changing inputs) without Python correction",
        "or weight edits.",
        "",
        "## 2. Baseline reproduction",
        str(report.get("dc_baseline")),
        "",
        "## 3. Servo circuit definition",
        "LEVEL 2 OTA-C leaky integrator on each TIA:",
        "",
        "    I_c = gm * Vsum   onto C, leak R",
        "    dVint/dt = -(gm/C) Vsum - Vint/(R C)",
        "    Vplus = Vos + Vint",
        "    tau = C/gm     DC gain Vsum->Vint = gm*R",
        "",
        f"Exp 24 point: gm={EXP24_GM:g} C={EXP24_C:g} R=1e9  tau=1 ms.",
        "TIA is XSPICE limit (algebraic). Optional behavioral TIA pole from Exp 22.",
        "Not transistor fT. Integrator is finite-C, not an algebraic Laplace 1/s.",
        "",
        "## 4. Unit-cell transient results",
        str(report.get("unit_cell_summary")),
        "",
        "## 5. Stability sweep (o2, Vos=214 uV, A=1e5, offset-then-step)",
        "Algebraic XSPICE TIA (infinite BW except servo C):",
        "| tau (s) | failed | osc | |Vlin-z| | t_|z|<1e-3 | max|Vsum| | overshoot |",
        "|---:|---|---|---:|---:|---:|---:|",
    ]
    for r in report.get("tau_sweep") or []:
        lines.append(
            f"| {fmt(r.get('tau_s'))} | {r.get('failed')} | {r.get('oscillating')} | "
            f"{fmt(r.get('err_final_vs_ref'))} | {fmt(r.get('t_after_step_1e3_s'))} | "
            f"{fmt(r.get('max_vsum'))} | {fmt(r.get('overshoot_vs_final'))} |"
        )
    lines += [
        "",
        "Nested loop with behavioral TIA pole fp=1 kHz:",
        "| tau (s) | failed | osc | |Vlin-z| | t_|z|<1e-3 | max|Vsum| | overshoot |",
        "|---:|---|---|---:|---:|---:|---:|",
    ]
    for r in report.get("tau_sweep_pole_1khz") or []:
        lines.append(
            f"| {fmt(r.get('tau_s'))} | {r.get('failed')} | {r.get('oscillating')} | "
            f"{fmt(r.get('err_final_vs_ref'))} | {fmt(r.get('t_after_step_1e3_s'))} | "
            f"{fmt(r.get('max_vsum'))} | {fmt(r.get('overshoot_vs_final'))} |"
        )
    lines += [
        "",
        f"tau selection source: {report.get('tau_selection_source')}",
        "No-servo baselines:",
        str(report.get("tia_baselines")),
        "",
        "## 6. Gain × servo dynamics",
        str(report.get("gain_tau")),
        "",
        "## 7. Offset sweep",
        str(report.get("vos_sweep")),
        "",
        "## 8. Network A transient inference",
        str(report.get("network_A_tran")),
        "",
        "## 9. Network F transient inference",
        str(report.get("network_F_tran")),
        "",
        "## 10. Multiple-input behavior",
        str(report.get("multi_input")),
        "",
        "## 11. Auto-zero comparison",
        str(report.get("az_compare")),
        "",
        "## 12. Error budget",
        str(report.get("error_budget")),
        "",
        "## 13. Numerical validation",
        str(report.get("numerical")),
        "",
        "## 14. Failure cases",
        str(report.get("failures")),
        "",
        "## 15. Best operating point",
        str(report.get("best_operating_point")),
        f"fastest analog tau: {fmt(report.get('fastest_analog_tau_s'))} s",
        "",
        "## 16. Latency / settling requirements",
        str(report.get("latency")),
        "",
        "## 17. Physical realism level",
        report.get("hardware_level") or "",
        "",
        "## 18. Limitations",
        report.get("limitations") or "",
        "",
        "## 19. Honest recommendation for Experiment 26",
        report.get("next_experiment") or "",
        "",
        "## FINAL STATUS",
        report.get("final_status") or "",
        "",
        "SPICE is the source of truth. Frozen Experiment 9 weights were not edited.",
        "",
    ]
    REPORT_MD.write_text("\n".join(lines), encoding="utf-8")


def slim_cell(rec: dict) -> dict:
    skip = {"waveform"}
    return {k: v for k, v in rec.items() if k not in skip}


def main() -> int:
    print("Experiment 25: servo transient validation", flush=True)
    ngspice = find_ngspice()
    CIRCUIT_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    spec_a, spec_f = spec_by_id("A"), spec_by_id("F")
    wa, wf = load_frozen_model("A"), load_frozen_model("F")
    xa = generate_inputs(spec_a["n_in"], N_A, "exp24_A")
    xf = generate_inputs(spec_f["n_in"], N_F, "exp24_F")
    ya, _ = software_for(wa, xa)
    yf, _ = software_for(wf, xf)
    xa_t, ya_t = xa[:N_A_TRAN], ya[:N_A_TRAN]
    xf_t, yf_t = xf[:N_F_TRAN], yf[:N_F_TRAN]

    report = {
        "experiment": 25,
        "title": "transient validation of the virtual-ground servo",
        "spice_source_of_truth": True,
        "n_A_tran": N_A_TRAN,
        "n_F_tran": N_F_TRAN,
        "note_vectors": "TRAN uses the first N vectors of the Exp 24 generate_inputs sets.",
    }

    print("Phase 1: DC reproduction", flush=True)
    dc = {}
    for label, servo, vos, spec, w, x, y in (
        ("A_L0", False, 0.0, spec_a, wa, xa, ya),
        ("A_L214", False, VOS_214, spec_a, wa, xa, ya),
        ("A_servo214", True, VOS_214, spec_a, wa, xa, ya),
        ("F_L0", False, 0.0, spec_f, wf, xf, yf),
        ("F_L214", False, VOS_214, spec_f, wf, xf, yf),
        ("F_servo214", True, VOS_214, spec_f, wf, xf, yf),
    ):
        p = E25Params(name=f"dc_{label}", vos=vos, servo=servo, linear=False)
        rec, _, _ = eval_op_network(ngspice, spec, w, p, x, y, dest("dc", label))
        dc[label] = {k: rec.get(k) for k in ("mae", "max_abs_error", "accuracy", "failed", "failure_reason")}
        print(f"  {label} fail={rec.get('failed')} MAE={fmt(rec.get('mae'))} acc={rec.get('accuracy')}", flush=True)
    report["dc_baseline"] = dc
    servo_f = dc.get("F_servo214") or {}
    if servo_f.get("failed") or servo_f.get("mae") is None or servo_f["mae"] > 1e-6:
        report["final_status"] = "DYNAMIC SERVO FAILED"
        report["failures"] = "DC servo reproduction did not match Exp 24 (~1e-8 MAE). Stopped."
        conclude(report)
        write_markdown(report)
        save_report(report)
        print(report["failures"], flush=True)
        return 1

    print("Phase 2: rank + unit-cell", flush=True)
    _net, cat, _ = compile_iv("A", spec_f, wf, IVParams(name="rank", invert_gain=INVERT_PINNED))
    rows, selected = rank_neurons(spec_f, cat, wf, xf)
    by_tag = {r["tag"]: r for r in rows}
    o2 = selected["worst_finite_gain"]
    h16 = by_tag.get("h16") or selected["worst_leakage"]
    h21 = by_tag.get("h21") or selected["median_hidden"]
    report["ranking"] = {
        "worst": o2["tag"],
        "Rf_Gtot": o2.get("Rf_Gtot"),
        "h16": h16["tag"],
        "h16_Rf_Gtot": h16.get("Rf_Gtot"),
        "h21": h21["tag"],
        "h21_Rf_Gtot": h21.get("Rf_Gtot"),
    }
    print(f"  worst {o2['tag']} RfG={o2.get('Rf_Gtot')} {h16['tag']} {h21['tag']}", flush=True)

    cfg = ARCH_C_CFG["F"]
    xs0 = iso_sources(spec_f, wf, o2)
    wrow0 = wf["W2"][o2["index"]]
    bias0 = float(wf["b2"][o2["index"]])
    steps0 = pick_steps(xs0, wrow0, bias0)
    print("Phase 2a: no-servo L TIA baselines on o2", flush=True)
    baselines = []
    for name, vos, servo in (
        ("L0", 0.0, False),
        ("L214", VOS_214, False),
    ):
        p = E25Params(name=name, vos=vos, servo=servo, linear=True)
        rec, _ = iso_tran_case(
            ngspice, spec_f, wf, o2, p, steps0["maxabs"], steps0["z_maxabs"],
            "offset_then_step", t_delay=2e-5,
        )
        rec["step"] = "maxabs"
        rec["name"] = f"o2_base_{name}"
        baselines.append(slim_cell(rec))
        print(
            f"  o2 {name} fail={rec.get('failed')} |V-z|={fmt(rec.get('err_final_vs_ref'))} "
            f"osc={rec.get('oscillating')}",
            flush=True,
        )
    report["tia_baselines"] = baselines

    unit = []
    waves_keep = []
    p214 = E25Params(name="u214", vos=VOS_214, servo=True, linear=True, servo_c=EXP24_C, servo_gm=EXP24_GM)
    for pick in (o2, h16, h21):
        xs = iso_sources(spec_f, wf, pick)
        hidden = pick["layer"] == 1
        wrow = wf["W1"][pick["index"]] if hidden else wf["W2"][pick["index"]]
        bias = float(wf["b1"][pick["index"]] if hidden else wf["b2"][pick["index"]])
        steps = pick_steps(xs, wrow, bias)
        for mode, key in (
            ("cold_uic", "maxabs"),
            ("offset_then_step", "zero"),
            ("offset_then_step", "maxabs"),
            ("offset_then_step", "pos"),
            ("offset_then_step", "neg"),
            ("offset_then_step", "unit"),
        ):
            rec, w = iso_tran_case(
                ngspice, spec_f, wf, pick, p214, steps[key], steps[f"z_{key}"], mode
            )
            rec["step"] = key
            rec["name"] = f"{pick['tag']}_{mode}_{key}"
            if w is not None and pick["tag"] == o2["tag"] and key == "maxabs":
                waves_keep.append(rec)
            unit.append(slim_cell(rec))
            print(
                f"  {pick['tag']} {mode} {key} fail={rec.get('failed')} "
                f"|V-z|={fmt(rec.get('err_final_vs_ref'))} t1e3={fmt(rec.get('t_vs_ref_1e3_s'))} "
                f"osc={rec.get('oscillating')} {rec.get('failure_reason') or ''}",
                flush=True,
            )
    # keep a couple of full recs for plots
    report["unit_cell"] = waves_keep + unit
    report["unit_cell_summary"] = [
        {k: r.get(k) for k in (
            "tag", "mode", "step", "failed", "err_final_vs_ref", "t_after_step_1e3_s",
            "oscillating", "max_vsum", "tau_s", "failure_reason",
        )}
        for r in unit
    ]

    print("Phase 3: tau sweep on o2", flush=True)
    xs = iso_sources(spec_f, wf, o2)
    wrow = wf["W2"][o2["index"]]
    bias = float(wf["b2"][o2["index"]])
    steps = pick_steps(xs, wrow, bias)
    tau_rows = []
    for tau in TAU_SWEEP:
        p = E25Params(
            name=f"tau{tau:.0e}", vos=VOS_214, servo=True, linear=True,
            servo_gm=EXP24_GM, servo_c=tau * EXP24_GM,
        )
        rec, w = iso_tran_case(
            ngspice, spec_f, wf, o2, p, steps["maxabs"], steps["z_maxabs"], "offset_then_step"
        )
        rec["name"] = f"o2_tau_{tau:.0e}"
        tau_rows.append(rec)
        print(
            f"  tau={tau:.1e} fail={rec.get('failed')} |V-z|={fmt(rec.get('err_final_vs_ref'))} "
            f"t1e3={fmt(rec.get('t_vs_ref_1e3_s'))} osc={rec.get('oscillating')} "
            f"Vsum={fmt(rec.get('max_vsum'))}",
            flush=True,
        )
    report["tau_sweep"] = [slim_cell(r) for r in tau_rows]
    analog_ok = [
        r for r in tau_rows
        if r.get("err_final_vs_ref") is not None
        and r["err_final_vs_ref"] <= ERROR_LIMIT
        and not r.get("oscillating")
        and not r.get("diverged")
        and not r.get("failed")
    ]

    print("Phase 3b: tau sweep on o2 with TIA pole 1 kHz", flush=True)
    tau_pole_rows = []
    for tau in TAU_SWEEP:
        p = E25Params(
            name=f"ptau{tau:.0e}", vos=VOS_214, servo=True, linear=True,
            servo_gm=EXP24_GM, servo_c=tau * EXP24_GM, tia_pole_hz=1e3,
        )
        rec, w = iso_tran_case(
            ngspice, spec_f, wf, o2, p, steps["maxabs"], steps["z_maxabs"], "offset_then_step"
        )
        rec["name"] = f"o2_pole_tau_{tau:.0e}"
        tau_pole_rows.append(rec)
        print(
            f"  pole tau={tau:.1e} fail={rec.get('failed')} |V-z|={fmt(rec.get('err_final_vs_ref'))} "
            f"t1e3={fmt(rec.get('t_vs_ref_1e3_s'))} osc={rec.get('oscillating')}",
            flush=True,
        )
    report["tau_sweep_pole_1khz"] = [slim_cell(r) for r in tau_pole_rows]
    analog_ok_pole = [
        r for r in tau_pole_rows
        if r.get("err_final_vs_ref") is not None
        and r["err_final_vs_ref"] <= ERROR_LIMIT
        and not r.get("oscillating")
        and not r.get("diverged")
        and not r.get("failed")
    ]
    # Prefer a nested-loop (finite TIA pole) operating point when one exists.
    pick_from = analog_ok_pole or analog_ok
    report["tau_selection_source"] = (
        "pole_1khz" if analog_ok_pole else ("algebraic_tia" if analog_ok else "least_error")
    )
    if pick_from:
        best = min(pick_from, key=lambda r: (r["tau_s"], r.get("t_vs_ref_1e3_s") or 1e9))
    else:
        pool = tau_pole_rows + tau_rows
        best = min(
            (r for r in pool if r.get("err_final_vs_ref") is not None),
            key=lambda r: r["err_final_vs_ref"],
            default=tau_rows[-2] if len(tau_rows) >= 2 else tau_rows[0],
        )
    best_tau = float(best["tau_s"])
    best_c = best_tau * EXP24_GM
    print(f"  selected tau={best_tau:.3e} s from o2 sweep", flush=True)
    report["selected_tau_s"] = best_tau
    # keep waveform of selected and 1ms
    report["unit_cell"] = [
        r for r in (tau_rows + tau_pole_rows)
        if abs(r["tau_s"] - best_tau) < 1e-15 or abs(r["tau_s"] - 1e-3) < 1e-12
    ] + [r for r in report["unit_cell"] if isinstance(r, dict)]

    print("Phase 4: A x tau on o2", flush=True)
    gain_rows = []
    for a in GAIN_SWEEP:
        for tau in (best_tau, 1e-3):
            p = E25Params(
                name=f"a{a:g}_t{tau:.0e}", vos=VOS_214, servo=True, linear=True,
                amp_gain=a, servo_gm=EXP24_GM, servo_c=tau * EXP24_GM,
            )
            rec, _ = iso_tran_case(
                ngspice, spec_f, wf, o2, p, steps["maxabs"], steps["z_maxabs"], "offset_then_step"
            )
            gain_rows.append(slim_cell(rec))
            print(
                f"  A={a:g} tau={tau:.1e} |V-z|={fmt(rec.get('err_final_vs_ref'))} "
                f"osc={rec.get('oscillating')}",
                flush=True,
            )
    report["gain_tau"] = gain_rows

    print("Phase 5: Vos sweep", flush=True)
    vos_rows = []
    p_base = dict(servo=True, linear=True, servo_gm=EXP24_GM, servo_c=best_c)
    for vos in VOS_SWEEP:
        p = E25Params(name=f"vos{vos:.0e}", vos=vos, **p_base)
        rec, _ = iso_tran_case(
            ngspice, spec_f, wf, o2, p, steps["maxabs"], steps["z_maxabs"], "offset_then_step"
        )
        vos_rows.append(slim_cell(rec))
        print(
            f"  Vos={vos:.3e} |V-z|={fmt(rec.get('err_final_vs_ref'))} "
            f"t1e3={fmt(rec.get('t_vs_ref_1e3_s'))} vint={fmt(rec.get('max_vint'))}",
            flush=True,
        )
    report["vos_sweep"] = vos_rows

    # TIA pole check at 1 kHz
    print("Phase 5b: TIA pole 1 kHz at selected tau", flush=True)
    p_pole = E25Params(
        name="pole1k", vos=VOS_214, servo=True, linear=True,
        servo_gm=EXP24_GM, servo_c=best_c, tia_pole_hz=1e3,
    )
    rec_pole, _ = iso_tran_case(
        ngspice, spec_f, wf, o2, p_pole, steps["maxabs"], steps["z_maxabs"], "offset_then_step"
    )
    report["tia_pole_1khz"] = slim_cell(rec_pole)
    print(
        f"  pole 1kHz |V-z|={fmt(rec_pole.get('err_final_vs_ref'))} osc={rec_pole.get('oscillating')}",
        flush=True,
    )

    p_net = E25Params(
        name="net", vos=VOS_214, servo=True, linear=False,
        servo_gm=EXP24_GM, servo_c=best_c,
        tia_pole_hz=1e3 if report.get("tau_selection_source") == "pole_1khz" else 0.0,
    )
    print("Phase 6: Network A TRAN", flush=True)
    rec_a, _ = net_tran_vectors(ngspice, spec_a, wa, p_net, xa_t, ya_t, dest("A", "tran"))
    report["network_A_tran"] = rec_a
    print(
        f"  A TRAN fail={rec_a.get('failed')} MAE={fmt(rec_a.get('mae'))} "
        f"acc={rec_a.get('accuracy')} osc={rec_a.get('n_oscillating')}",
        flush=True,
    )

    print("Phase 7: Network F TRAN", flush=True)
    rec_f = {"failed": True, "failure_reason": "skipped: Network A TRAN failed"}
    if not rec_a.get("failed"):
        rec_f, _ = net_tran_vectors(ngspice, spec_f, wf, p_net, xf_t, yf_t, dest("F", "tran"))
    report["network_F_tran"] = rec_f
    print(
        f"  F TRAN fail={rec_f.get('failed')} MAE={fmt(rec_f.get('mae'))} "
        f"acc={rec_f.get('accuracy')} osc={rec_f.get('n_oscillating')}",
        flush=True,
    )

    print("Phase 8: multi-input", flush=True)
    t_hold = max(8.0 * best_tau, 5e-5)
    # A: three diverse vectors from the Exp 24 set
    ia = [0, min(3, len(xa) - 1), int(np.argmax(np.abs(ya)))]
    series_a = [xa[i] for i in ia]
    yser_a = [ya[i] for i in ia]
    rec_ma, _ = net_pwl(ngspice, spec_a, wa, p_net, series_a, yser_a, dest("A", "pwl"), t_hold)
    report["multi_input"] = {"A": slim_cell(rec_ma), "t_hold_s": t_hold}
    print(
        f"  A PWL segs MAE={[fmt(rec_ma.get(f'seg{k}_mae')) for k in range(3)]}",
        flush=True,
    )
    rec_mf = {"failed": True, "failure_reason": "skipped"}
    if not rec_f.get("failed"):
        iff = [0, min(3, len(xf) - 1), int(np.argmax(np.max(np.abs(yf), axis=1)))]
        series_f = [xf[i] for i in iff]
        yser_f = [yf[i] for i in iff]
        rec_mf, _ = net_pwl(ngspice, spec_f, wf, p_net, series_f, yser_f, dest("F", "pwl"), t_hold)
        print(
            f"  F PWL segs MAE={[fmt(rec_mf.get(f'seg{k}_mae')) for k in range(3)]}",
            flush=True,
        )
    report["multi_input"]["F"] = slim_cell(rec_mf)

    print("Phase 9: AZ-Vref vs servo on o2", flush=True)
    p_az = E25Params(
        name="azv", vos=VOS_214, servo=False, autozero=True, gate_vref=True,
        linear=True, t_az=2e-5, t_stop=8e-5,
    )
    net_az, _, raz = compile_iso(
        spec_f["n_hidden"], wrow, bias, cfg.g_weight_2, cfg.banks, p_az, tag=TAG
    )
    az_rec = {"failed": True, "failure_reason": raz}
    if net_az is not None:
        head, sep, _ = net_az.partition(".control")
        x = steps["maxabs"]
        baked = bake_vref_pulse(bake_vin_pulse(head, x, 2e-5), 2e-5)
        full = baked.rstrip() + "\n.control\n.endc\n.end\n"
        arr, err, log = run_tran(
            ngspice, full, dest("az", "o2"), [f"{TAG}lin", f"{TAG}p"],
            8e-5, 8e-5 / 400.0, uic=False,
        )
        if err or arr is None:
            az_rec = {"failed": True, "failure_reason": err, "log_tail": log}
        else:
            sm = settling_metrics(arr[:, 0], arr[:, 1], y_ref=steps["z_maxabs"])
            az_rec = {
                "failed": False,
                "kind": "Vref-gated auto-zero LEVEL 2 TRAN",
                "t_az_s": 2e-5,
                "t_stop_s": 8e-5,
                **sm,
                "max_vsum": float(np.max(np.abs(arr[:, 2]))),
            }
    report["az_compare"] = {
        "az_o2_maxabs": az_rec,
        "servo_o2_selected": slim_cell(best),
        "note": (
            "AZ uses a clocked sample at Vin=Vref=0 then inference. "
            "Servo is continuous nested feedback. Both LEVEL 2."
        ),
    }
    print(f"  AZ o2 |V-z|={fmt(az_rec.get('err_final_vs_ref'))} t1e3={fmt(az_rec.get('t_vs_ref_1e3_s'))}", flush=True)

    print("Phase 10: error budget", flush=True)
    budget = {}
    p_op = E25Params(name="bud", vos=VOS_214, servo=True, linear=False, servo_gm=EXP24_GM, servo_c=best_c)
    net_b, cat_b, rb = compile_net(spec_f, wf, p_op, linear=False)
    for tol, nmc, key in ((0.0, 1, "R0"), (0.001, N_MC, "R0p1pct"), (0.005, N_MC, "R0p5pct")):
        maes, accs = [], []
        expected = classification_labels(yf)
        rng = np.random.default_rng(25)
        for i in range(nmc):
            values = {} if tol <= 0 else sample_resistor_values(cat_b, tol, rng)
            physical, _rt, err, _ = simulate_batch(
                ngspice, net_b, xf, spec_f["n_out"], dest("mc", key, i),
                r_values=values, timeout=180.0,
            )
            if err or physical is None:
                continue
            st = error_stats(physical, yf)
            pred = classification_labels(physical)
            maes.append(st["mae"])
            accs.append(float(np.mean(pred == expected)))
        budget[key] = {
            "tol": tol, "n_ok": len(maes),
            "mae": float(np.mean(maes)) if maes else None,
            "mae_max": float(np.max(maes)) if maes else None,
            "accuracy": float(np.mean(accs)) if accs else None,
            "note": "settled OP of the same OTA-C servo (equivalent to waiting >> tau)",
        }
        print(f"  {key} MAE={fmt(budget[key]['mae'])} acc={budget[key]['accuracy']}", flush=True)
    p_leak = E25Params(
        name="leak", vos=VOS_214, servo=True, linear=False, i_leak=13e-9,
        servo_gm=EXP24_GM, servo_c=best_c,
    )
    rec_l, _, _ = eval_op_network(ngspice, spec_f, wf, p_leak, xf, yf, dest("leak", "13nA"))
    budget["leak_13nA_idealR"] = {
        "mae": rec_l.get("mae"), "accuracy": rec_l.get("accuracy"), "failed": rec_l.get("failed")
    }
    p_comb = E25Params(
        name="comb", vos=VOS_214, servo=True, linear=False, i_leak=13e-9,
        servo_gm=EXP24_GM, servo_c=best_c,
    )
    net_c, cat_c, _ = compile_net(spec_f, wf, p_comb, linear=False)
    rng = np.random.default_rng(26)
    values = sample_resistor_values(cat_c, 0.005, rng)
    physical, _rt, err, _ = simulate_batch(
        ngspice, net_c, xf, spec_f["n_out"], dest("mc", "comb"), r_values=values, timeout=180.0
    )
    if physical is not None:
        st = error_stats(physical, yf)
        pred = classification_labels(physical)
        budget["combined_214uV_13nA_0p5pct"] = {
            "mae": st["mae"],
            "accuracy": float(np.mean(pred == classification_labels(yf))),
        }
    else:
        budget["combined_214uV_13nA_0p5pct"] = {"failed": True, "failure_reason": err}
    report["error_budget"] = budget

    print("Phase 13: numerical timestep check", flush=True)
    p_num = E25Params(
        name="num", vos=VOS_214, servo=True, linear=True, servo_gm=EXP24_GM, servo_c=best_c
    )
    rec_n1, w1 = iso_tran_case(
        ngspice, spec_f, wf, o2, p_num, steps["maxabs"], steps["z_maxabs"], "offset_then_step"
    )
    # smaller step
    net_n, _, _ = compile_iso(
        spec_f["n_hidden"], wrow, bias, cfg.g_weight_2, cfg.banks, p_num, tag=TAG
    )
    num = {"baseline": slim_cell(rec_n1)}
    if net_n is not None:
        head, sep, _ = net_n.partition(".control")
        delay = 4.0 * max(best_tau, 1e-6)
        baked = bake_vin_pulse(head, steps["maxabs"], delay, t_gap=0.0)
        full = baked.rstrip() + "\n.control\n.endc\n.end\n"
        t_stop = delay + choose_tstop(best_tau)
        tstep = choose_tstep(best_tau, t_stop) / 5.0
        arr, err, log = run_tran(
            ngspice, full, dest("num", "fine"),
            [f"{TAG}lin", f"{TAG}p", f"{TAG}int"], t_stop, tstep, uic=False, reltol=1e-6,
        )
        if arr is None:
            num["fine"] = {"failed": True, "failure_reason": err}
        else:
            sm = settling_metrics(arr[:, 0], arr[:, 1], y_ref=steps["z_maxabs"])
            num["fine"] = slim_cell({"failed": False, **sm, "tstep_s": tstep})
            if rec_n1.get("y_final") is not None and sm.get("y_final") is not None:
                num["delta_y_final"] = abs(rec_n1["y_final"] - sm["y_final"])
    report["numerical"] = num
    print(f"  num delta y_final={fmt(num.get('delta_y_final'))}", flush=True)

    failures = []
    for r in unit + tau_rows:
        if r.get("failed") or r.get("oscillating") or r.get("diverged"):
            failures.append(
                f"{r.get('tag')} {r.get('mode')} {r.get('step')} tau={r.get('tau_s')} "
                f"{r.get('failure_reason')}"
            )
    report["failures"] = failures[:40] or "no unit-cell oscillations recorded"
    report["latency"] = {
        "selected_tau_s": best_tau,
        "recommended_dwell_s": t_hold,
        "network_A_t_stop_s": rec_a.get("t_stop_s"),
        "network_F_t_stop_s": rec_f.get("t_stop_s"),
        "exp22_10us_target": 1e-5,
        "meets_10us_if_tau_le_10us": best_tau <= 1e-5,
    }
    report["limitations"] = (
        "TIA is algebraic XSPICE limit unless pole test. Servo is OTA-C LEVEL 2. "
        "UIC cold-start and offset-then-step both reported. TRAN Network F uses "
        f"first {N_F_TRAN} of 40 Exp 24 vectors. Mismatch budget used settled OP "
        "(equivalent to t>>tau), plus TRAN MAE on the vector subset. "
        "B-source Vplus=Vos+Vint is unlimited; |Vint| is reported. "
        "Not transistor, PCB, or silicon."
    )

    conclude(report)
    report["plots"] = write_plots(report)
    write_markdown(report)
    save_report(report)
    print(f"wrote {REPORT_JSON}", flush=True)
    print(f"wrote {REPORT_MD}", flush=True)
    print(report.get("final_status"), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

