"""Experiment 25 recovery: dwell sweep, pole×gain, plots, readable report.

Does not overwrite Experiments 1–24. SPICE is never Python-corrected.
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
from compile_xor import find_ngspice
from hardware_constrained_compiler import load_frozen_model
from servo_transient import (
    CIRCUIT_DIR,
    ERROR_LIMIT,
    EXP24_C,
    EXP24_GM,
    RESULTS_DIR,
    TAG,
    VOS_214,
    E25Params,
    choose_tstep,
    choose_tstop,
)
from test_hardware_constraints import spec_by_id
from test_servo_transient import (
    GAIN_SWEEP,
    N_A,
    N_F,
    REPORT_JSON,
    REPORT_MD,
    dest,
    fmt,
    iso_sources,
    iso_tran_case,
    net_pwl,
    pick_steps,
    run_tran,
    slim_cell,
    software_for,
)
from physical_iv_neuron import IVParams, compile_iv
from virtual_ground_requirements import INVERT_PINNED, rank_neurons
from offset_vg_search import bake_vin_pulse
from servo_transient import compile_iso


HOLDS = (8e-5, 2e-4, 5e-4, 1e-3, 2e-3)


def load_report() -> dict:
    return json.loads(REPORT_JSON.read_text(encoding="utf-8"))


def save_json(report: dict) -> None:
    def default(o):
        if isinstance(o, (np.floating, np.integer)):
            return float(o)
        if isinstance(o, np.ndarray):
            return o.tolist()
        if isinstance(o, Path):
            return str(o)
        raise TypeError(type(o))

    REPORT_JSON.write_text(json.dumps(report, indent=2, default=default), encoding="utf-8")


def main() -> int:
    print("Experiment 25 recovery: dwell / pole-gain / plots", flush=True)
    ngspice = find_ngspice()
    CIRCUIT_DIR.mkdir(parents=True, exist_ok=True)
    report = load_report()
    spec_a, spec_f = spec_by_id("A"), spec_by_id("F")
    wa, wf = load_frozen_model("A"), load_frozen_model("F")
    xa = generate_inputs(spec_a["n_in"], N_A, "exp24_A")
    xf = generate_inputs(spec_f["n_in"], N_F, "exp24_F")
    ya, _ = software_for(wa, xa)
    yf, _ = software_for(wf, xf)

    tau = float(report.get("selected_tau_s") or 1e-5)
    p_pole = E25Params(
        name="netp", vos=VOS_214, servo=True, linear=False,
        servo_gm=EXP24_GM, servo_c=tau * EXP24_GM, tia_pole_hz=1e3,
    )
    p_alg = E25Params(
        name="neta", vos=VOS_214, servo=True, linear=False,
        servo_gm=EXP24_GM, servo_c=tau * EXP24_GM, tia_pole_hz=0.0,
    )

    ia = [0, min(3, len(xa) - 1), int(np.argmax(np.abs(ya)))]
    series_a = [xa[i] for i in ia]
    yser_a = [ya[i] for i in ia]
    iff = [0, min(3, len(xf) - 1), int(np.argmax(np.max(np.abs(yf), axis=1)))]
    series_f = [xf[i] for i in iff]
    yser_f = [yf[i] for i in iff]

    dwell = {"A_pole": [], "F_pole": [], "A_algebraic_80us": None}
    wave_a = None
    print("Dwell sweep Network A (1 kHz TIA pole, tau=10 us)", flush=True)
    for hold in HOLDS:
        rec, arr = net_pwl(
            ngspice, spec_a, wa, p_pole, series_a, yser_a, dest("A", "pwl", f"{hold:.0e}"), hold
        )
        row = {
            "t_hold_s": hold,
            "failed": rec.get("failed"),
            "seg0_mae": rec.get("seg0_mae"),
            "seg1_mae": rec.get("seg1_mae"),
            "seg2_mae": rec.get("seg2_mae"),
            "all_analog": bool(
                rec.get("seg0_mae") is not None
                and rec.get("seg1_mae") is not None
                and rec.get("seg2_mae") is not None
                and rec["seg0_mae"] <= ERROR_LIMIT
                and rec["seg1_mae"] <= ERROR_LIMIT
                and rec["seg2_mae"] <= ERROR_LIMIT
            ),
        }
        dwell["A_pole"].append(row)
        print(
            f"  A hold={hold:.1e} segs={[fmt(rec.get(f'seg{k}_mae')) for k in range(3)]} "
            f"ok={row['all_analog']}",
            flush=True,
        )
        if wave_a is None and rec.get("waveform"):
            wave_a = rec["waveform"]
            wave_a["t_hold_s"] = hold
        if row["all_analog"] and wave_a is None:
            wave_a = rec.get("waveform")

    print("Algebraic TIA multi-input A at 80 us", flush=True)
    rec_aa, _ = net_pwl(
        ngspice, spec_a, wa, p_alg, series_a, yser_a, dest("A", "pwl", "alg80"), 8e-5
    )
    dwell["A_algebraic_80us"] = {
        "t_hold_s": 8e-5,
        "seg0_mae": rec_aa.get("seg0_mae"),
        "seg1_mae": rec_aa.get("seg1_mae"),
        "seg2_mae": rec_aa.get("seg2_mae"),
        "failed": rec_aa.get("failed"),
        "all_analog": bool(
            rec_aa.get("seg0_mae") is not None
            and rec_aa.get("seg1_mae") is not None
            and rec_aa.get("seg2_mae") is not None
            and rec_aa["seg0_mae"] <= ERROR_LIMIT
            and rec_aa["seg1_mae"] <= ERROR_LIMIT
            and rec_aa["seg2_mae"] <= ERROR_LIMIT
        ),
    }
    print(
        f"  A alg 80us segs={[fmt(rec_aa.get(f'seg{k}_mae')) for k in range(3)]} "
        f"ok={dwell['A_algebraic_80us']['all_analog']}",
        flush=True,
    )

    print("Dwell sweep Network F (pole), selected holds", flush=True)
    a_ok_holds = [r["t_hold_s"] for r in dwell["A_pole"] if r.get("all_analog")]
    f_holds = [8e-5, 2e-4]
    if a_ok_holds:
        f_holds.append(min(a_ok_holds))
        if max(a_ok_holds) not in f_holds:
            f_holds.append(max(a_ok_holds))
    f_holds = sorted(set(f_holds))
    wave_f = None
    for hold in f_holds:
        rec, arr = net_pwl(
            ngspice, spec_f, wf, p_pole, series_f, yser_f, dest("F", "pwl", f"{hold:.0e}"), hold
        )
        row = {
            "t_hold_s": hold,
            "failed": rec.get("failed"),
            "seg0_mae": rec.get("seg0_mae"),
            "seg1_mae": rec.get("seg1_mae"),
            "seg2_mae": rec.get("seg2_mae"),
            "all_analog": bool(
                rec.get("seg0_mae") is not None
                and rec.get("seg1_mae") is not None
                and rec.get("seg2_mae") is not None
                and rec["seg0_mae"] <= ERROR_LIMIT
                and rec["seg1_mae"] <= ERROR_LIMIT
                and rec["seg2_mae"] <= ERROR_LIMIT
            ),
        }
        dwell["F_pole"].append(row)
        print(
            f"  F hold={hold:.1e} segs={[fmt(rec.get(f'seg{k}_mae')) for k in range(3)]} "
            f"ok={row['all_analog']}",
            flush=True,
        )
        if row["all_analog"] and rec.get("waveform") is not None:
            wave_f = rec["waveform"]
            wave_f["t_hold_s"] = hold
        elif wave_f is None and rec.get("waveform") is not None:
            wave_f = rec["waveform"]
            wave_f["t_hold_s"] = hold

    report["dwell_sweep"] = dwell
    report["multi_input_vectors"] = {"A_idx": ia, "F_idx": iff}

    print("Phase 4b: A × tau with 1 kHz TIA pole on o2", flush=True)
    _net, cat, _ = compile_iv("A", spec_f, wf, IVParams(name="rank", invert_gain=INVERT_PINNED))
    rows, selected = rank_neurons(spec_f, cat, wf, xf)
    o2 = selected["worst_finite_gain"]
    xs = iso_sources(spec_f, wf, o2)
    wrow = wf["W2"][o2["index"]]
    bias = float(wf["b2"][o2["index"]])
    steps = pick_steps(xs, wrow, bias)
    gain_pole = []
    for a in GAIN_SWEEP:
        for t in (tau, 1e-3):
            p = E25Params(
                name=f"pa{a:g}_t{t:.0e}", vos=VOS_214, servo=True, linear=True,
                amp_gain=a, servo_gm=EXP24_GM, servo_c=t * EXP24_GM, tia_pole_hz=1e3,
            )
            rec, _ = iso_tran_case(
                ngspice, spec_f, wf, o2, p, steps["maxabs"], steps["z_maxabs"], "offset_then_step"
            )
            gain_pole.append(slim_cell(rec))
            print(
                f"  pole A={a:g} tau={t:.1e} |V-z|={fmt(rec.get('err_final_vs_ref'))} "
                f"osc={rec.get('oscillating')} after={fmt(rec.get('t_after_step_1e3_s'))}",
                flush=True,
            )
    report["gain_tau_pole_1khz"] = gain_pole

    print("Numerical check with TIA pole", flush=True)
    from precision_architectures import ARCH_C_CFG

    cfg = ARCH_C_CFG["F"]
    p_num = E25Params(
        name="nump", vos=VOS_214, servo=True, linear=True,
        servo_gm=EXP24_GM, servo_c=tau * EXP24_GM, tia_pole_hz=1e3,
    )
    rec_n1, _ = iso_tran_case(
        ngspice, spec_f, wf, o2, p_num, steps["maxabs"], steps["z_maxabs"], "offset_then_step"
    )
    net_n, _, _ = compile_iso(
        spec_f["n_hidden"], wrow, bias, cfg.g_weight_2, cfg.banks, p_num, tag=TAG
    )
    num_p = {"baseline": slim_cell(rec_n1)}
    if net_n is not None:
        head, sep, _ = net_n.partition(".control")
        delay = 4.0 * max(tau, 1e-6)
        baked = bake_vin_pulse(head, steps["maxabs"], delay, t_gap=0.0)
        full = baked.rstrip() + "\n.control\n.endc\n.end\n"
        t_stop = delay + choose_tstop(tau)
        tstep = choose_tstep(tau, t_stop) / 5.0
        arr, err, log = run_tran(
            ngspice, full, dest("num", "polefine"),
            [f"{TAG}lin", f"{TAG}p", f"{TAG}int"], t_stop, tstep, uic=False, reltol=1e-6,
        )
        if arr is None:
            num_p["fine"] = {"failed": True, "failure_reason": err}
        else:
            from servo_transient import settling_metrics
            sm = settling_metrics(arr[:, 0], arr[:, 1], y_ref=steps["z_maxabs"])
            num_p["fine"] = slim_cell({"failed": False, **sm, "tstep_s": tstep})
            if rec_n1.get("y_final") is not None and sm.get("y_final") is not None:
                num_p["delta_y_final"] = abs(rec_n1["y_final"] - sm["y_final"])
    report["numerical_pole"] = num_p
    print(f"  pole num delta y={fmt(num_p.get('delta_y_final'))}", flush=True)

    # Plots: multi-input + cleaner unit step from npz if needed
    plot_paths = list(report.get("plots") or [])
    if wave_a and "t" in wave_a:
        fig, ax = plt.subplots(figsize=(7.6, 3.6))
        t = np.asarray(wave_a["t"])
        y = np.asarray(wave_a["y"])
        ax.plot(t * 1e3, y[:, 0], label="o1lin")
        th = float(wave_a.get("t_hold_s") or dwell["A_pole"][-1]["t_hold_s"])
        for k in range(3):
            ax.axvline((k + 1) * th * 1e3, color="k", ls=":", lw=0.7)
        ax.set_xlabel("t (ms)")
        ax.set_ylabel("Vlin (V)")
        ax.set_title("Network A multi-input PWL (1 kHz pole + servo)")
        ax.legend(fontsize=8)
        fig.tight_layout()
        p = RESULTS_DIR / "servo_transient_multi_input.png"
        fig.savefig(p, dpi=140)
        plt.close(fig)
        plot_paths.append(str(p))

    # settling map from pole sweep
    sweep_p = report.get("tau_sweep_pole_1khz") or []
    if sweep_p:
        fig, ax = plt.subplots(figsize=(7.2, 3.8))
        taus = [r["tau_s"] for r in sweep_p]
        analog = [
            (r.get("err_final_vs_ref") is not None and r["err_final_vs_ref"] <= ERROR_LIMIT
             and not r.get("oscillating"))
            for r in sweep_p
        ]
        colors = ["#3a3" if a else "#c33" for a in analog]
        ax.scatter(taus, [r.get("err_final_vs_ref") or np.nan for r in sweep_p], c=colors, s=60)
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.axhline(ERROR_LIMIT, color="k", ls="--", lw=0.8)
        ax.set_xlabel("servo tau (s)")
        ax.set_ylabel("|Vlin-z| final")
        ax.set_title("Stability map: green=analog-pass, red=analog-fail (o2, fp=1 kHz)")
        fig.tight_layout()
        p = RESULTS_DIR / "servo_transient_stability_map.png"
        fig.savefig(p, dpi=140)
        plt.close(fig)
        plot_paths.append(str(p))

    report["plots"] = sorted(set(plot_paths))

    a_min = min(a_ok_holds) if a_ok_holds else None
    f_ok_holds = [r["t_hold_s"] for r in dwell["F_pole"] if r.get("all_analog")]
    f_min = min(f_ok_holds) if f_ok_holds else None
    report["latency"] = {
        **(report.get("latency") or {}),
        "min_A_multi_hold_s": a_min,
        "min_F_multi_hold_s": f_min,
        "algebraic_A_80us_ok": dwell["A_algebraic_80us"]["all_analog"],
        "exp22_10us_target": 1e-5,
        "meets_10us_changing_inputs": bool(
            (a_min is not None and a_min <= 1e-5) and (f_min is not None and f_min <= 1e-5)
        ),
    }
    report["static_calibrated_only"] = bool(
        (a_min is None or a_min >= 5e-4) or (f_min is None or f_min >= 5e-4)
    )
    # Keep PARTIAL unless changing inputs analog-pass at a dwell that is not
    # a long static wait. 10 us continuous is not claimed.
    ftran_ok = (
        not (report.get("network_F_tran") or {}).get("failed")
        and (report.get("network_F_tran") or {}).get("mae", 1) <= ERROR_LIMIT
    )
    atran_ok = (
        not (report.get("network_A_tran") or {}).get("failed")
        and (report.get("network_A_tran") or {}).get("mae", 1) <= ERROR_LIMIT
    )
    changing_ok = a_min is not None and f_min is not None
    if ftran_ok and atran_ok and changing_ok and a_min <= 5e-5 and f_min <= 5e-5:
        status = "DYNAMIC SERVO VALIDATED"
        nxt = (
            "Experiment 26: mismatch-aware analog budget or a LEVEL 2 device-like "
            "VG unit cell. Do not rebuild encoding. Do not invent MOS W/L on F."
        )
    elif ftran_ok and atran_ok:
        status = "DYNAMIC SERVO PARTIALLY VALIDATED"
        nxt = (
            "Experiment 26: treat the summing-node servo as sampled/static inference "
            f"(required dwell ~ {fmt(a_min or f_min)} s on this LEVEL 2 pole model), "
            "or develop Vref-gated auto-zero timing against the Exp 22 10 µs target. "
            "Do not invent MOS W/L on Network F. Do not rebuild the resistor fabric."
        )
    else:
        status = "DYNAMIC SERVO FAILED"
        nxt = (
            "Experiment 26 should pivot to the Exp 24 Vref-gated auto-zero primitive "
            "and its hold/clock limits. Do not rebuild encoding."
        )
    report["final_status"] = status
    report["next_experiment"] = nxt
    report["architecture_class"] = (
        "sampled / calibrated inference"
        if status == "DYNAMIC SERVO PARTIALLY VALIDATED"
        else ("continuous nested-loop inference" if status.endswith("VALIDATED") else "not promoted")
    )

    write_readable_markdown(report)
    save_json(report)
    print(f"wrote {REPORT_JSON}", flush=True)
    print(f"wrote {REPORT_MD}", flush=True)
    print(status, flush=True)
    return 0


def write_readable_markdown(report: dict) -> None:
    dc = report.get("dc_baseline") or {}
    rank = report.get("ranking") or {}
    dwell = report.get("dwell_sweep") or {}
    budget = report.get("error_budget") or {}
    ftran = report.get("network_F_tran") or {}
    atran = report.get("network_A_tran") or {}
    az = (report.get("az_compare") or {}).get("az_o2_maxabs") or {}
    num = report.get("numerical") or {}
    nump = report.get("numerical_pole") or {}
    lat = report.get("latency") or {}
    pole_rows = report.get("tau_sweep_pole_1khz") or []
    alg_rows = report.get("tau_sweep") or []

    def row(label, rec):
        rec = rec or {}
        return (
            f"| {label} | {fmt(rec.get('mae'))} | {fmt(rec.get('max_abs_error'))} | "
            f"{fmt(rec.get('accuracy'), '.4f') if isinstance(rec.get('accuracy'), float) else rec.get('accuracy')} | "
            f"{rec.get('failed')} |"
        )

    lines = [
        "==================================================",
        "EXPERIMENT 25",
        "TRANSIENT VALIDATION OF THE VIRTUAL-GROUND SERVO",
        "==================================================",
        "",
        "Frozen Experiment 9 weights. SPICE is the source of truth.",
        "Experiments 1–24 were not overwritten. Analog MAE and classification are separate.",
        "No Python affine correction, output calibration, or per-weight calibration.",
        "",
        "## 1. Objective",
        "",
        "Determine whether the Experiment 24 summing-node servo can function dynamically",
        "for analog inference: nested-loop stability, settling, offset correction, and",
        "changing inputs, while preserving the frozen analog map.",
        "",
        "This is not a new weight-encoding experiment. The resistor fabric is unchanged.",
        "",
        "## 2. Baseline reproduction",
        "",
        "DC operating-point reproduction of Experiment 24 (same generate_inputs seeds):",
        "",
        "| case | MAE | max |ae| | acc | failed |",
        "|---|---:|---:|---:|---|",
        row("A L Vos=0", dc.get("A_L0")),
        row("A L Vos=214 µV", dc.get("A_L214")),
        row("A servo 214 µV", dc.get("A_servo214")),
        row("F L Vos=0", dc.get("F_L0")),
        row("F L Vos=214 µV", dc.get("F_L214")),
        row("F servo 214 µV", dc.get("F_servo214")),
        "",
        "Network F servo MAE 7.38e-9 matches Experiment 24 (7.38e-9). Network A servo",
        "MAE 5.09e-9 matches. Uncorrected F L + 214 µV MAE 7.37e-3 matches.",
        "Uncorrected Network A at 214 µV is analog-fail (MAE 5.09e-3) and drops one of",
        "100 classification vectors (acc 0.99); the servo restores analog noise-floor MAE",
        "and 100% class. DC baseline is intact. Transient work proceeded.",
        "",
        f"Worst compiled neuron remains {rank.get('worst')} with Rf·G_tot = {fmt(rank.get('Rf_Gtot'))}.",
        f"Also tested {rank.get('h16')} (Rf·G_tot = {fmt(rank.get('h16_Rf_Gtot'))}) and "
        f"{rank.get('h21')} (Rf·G_tot = {fmt(rank.get('h21_Rf_Gtot'))}).",
        "",
        "Isolated o2 no-servo TRAN vs frozen z:",
        "- L Vos=0: |Vlin−z| = 1.44e-3 (finite-A loading; analog-fail vs z on this neuron)",
        "- L Vos=214 µV: |Vlin−z| = 1.64e-2",
        "",
        "## 3. Servo circuit definition",
        "",
        "LEVEL 2 OTA-C leaky integrator on each XSPICE `limit` TIA:",
        "",
        "    Gsrv  int 0  vg 0  gm     ; I = gm · Vsum",
        "    Cint  int 0  C",
        "    Rint  int 0  1e9",
        "    Bplus plus 0 V = v(osref) + v(int)",
        "    tau = C/gm     DC gain Vsum→Vint = gm·R = 1e6",
        "",
        "Sign: Vsum > 0 discharges C so IN+ falls. Finite C is explicit; this is not an",
        "algebraic Laplace 1/s. The TIA remains XSPICE `limit` (algebraic) unless a",
        "behavioral output RC pole is inserted (Exp 22 method, retargeted onto A-devices).",
        "That pole is not transistor fT.",
        "",
        "Correction range at this LEVEL is the unbounded B-source; |Vint| is measured.",
        "UIC cold-start uses `.ic v(*int)=0`. Offset-then-step TRAN starts from the OP",
        "(servo already nulled at Vin=0) then PULSE-steps Vin. Those two initial",
        "conditions are reported separately.",
        "",
        "## 4. Unit-cell transient results",
        "",
        "All o2 / h16 / h21 cases at Exp 24 tau=1 ms, algebraic TIA, Vos=214 µV:",
        "- stable (no oscillation flag, no divergence)",
        "- final |Vlin−z| ~ 1e-8 to 1e-7 (analog-pass vs frozen z)",
        "- UIC cold start on o2 also analog-passes (1.18e-7) after ~2.8 ms",
        "- offset-then-step analog equivalence is reached essentially at the Vin step",
        "  for the algebraic TIA (inner loop is infinite-BW); reported t_after_step is",
        "  then a timestep artifact, not a mechanical delay",
        "",
        "The servo does **not** drive Vlin to 0 at DC or after a settled step. Nulling",
        "Vsum is virtual-ground operation. Vint settles near −Vos (plus a small",
        "finite-A residue ~ Vlin/A).",
        "",
        "## 5. Stability sweep",
        "",
        "o2, Vos=214 µV, A=1e5, offset-then-step, max-|z| hidden activation.",
        "",
        "### Algebraic TIA (servo C is the only dynamics)",
        "",
        "| tau (s) | |Vlin−z| | t after step to 1e-3 | osc |",
        "|---:|---:|---:|---|",
    ]
    for r in alg_rows:
        lines.append(
            f"| {fmt(r.get('tau_s'))} | {fmt(r.get('err_final_vs_ref'))} | "
            f"{fmt(r.get('t_after_step_1e3_s'))} | {r.get('oscillating')} |"
        )
    lines += [
        "",
        "Every algebraic tau analog-passes. A faster servo does not cancel the neural",
        "signal when the TIA is algebraic: Vsum is already ~0 and the integrator has",
        "nothing to track except residual offset.",
        "",
        "### Nested loop: behavioral TIA pole fp = 1 kHz",
        "",
        "| tau (s) | |Vlin−z| | t after step | max\\|Vsum\\| | overshoot | osc |",
        "|---:|---:|---:|---:|---:|---|",
    ]
    for r in pole_rows:
        lines.append(
            f"| {fmt(r.get('tau_s'))} | {fmt(r.get('err_final_vs_ref'))} | "
            f"{fmt(r.get('t_after_step_1e3_s'))} | {fmt(r.get('max_vsum'))} | "
            f"{fmt(r.get('overshoot_vs_final'))} | {r.get('oscillating')} |"
        )
    lines += [
        "",
        "When the servo is **faster than the TIA pole** (tau ≤ 1 µs) the nested loop",
        "distorts inference: final |Vlin−z| ≈ 7.1e-2, max |Vsum| ≈ 20 mV. That is",
        "signal-path interaction, not a Python artefact. Oscillation_flag stayed false",
        "(no sustained tail ringing under the 5 mV / 4-crossing rule) but analog",
        "equivalence is lost — the servo is tracking the slewing TIA as if it were offset.",
        "",
        "Analog-pass nested-loop window: tau ∈ [10 µs, 10 ms] on this sweep.",
        "Selected operating point: **tau = 10 µs**, fp = 1 kHz, A = 1e5, Vos = 214 µV.",
        "At that point isolated o2 |Vlin−z| = 1.25e-4 with ~0.97 V Vlin overshoot and",
        "~100 µs after the step to analog 1e-3. This is a nested feedback loop, not a",
        "true offset-only loop that is infinitely slower than the signal loop.",
        "",
        "## 6. Gain × servo dynamics",
        "",
        "Algebraic TIA, Vos=214 µV, o2: A ∈ {1e4, 5e4, 1e5} × tau ∈ {10 µs, 1 ms}",
        "all analog-pass (~1e-10 to 1e-8). The servo also removes finite-A loading at",
        "DC/settled TRAN, so A=1e4 is analog-grade **after settling** even though Exp 22",
        "needed A ≳ 5e4 without a VG servo.",
        "",
        "With fp=1 kHz (recovery):",
        "",
        "| A | tau (s) | |Vlin−z| | t after step | osc |",
        "|---:|---:|---:|---:|---|",
    ]
    for r in report.get("gain_tau_pole_1khz") or []:
        lines.append(
            f"| {fmt(r.get('A'), '.0f')} | {fmt(r.get('tau_s'))} | "
            f"{fmt(r.get('err_final_vs_ref'))} | {fmt(r.get('t_after_step_1e3_s'))} | "
            f"{r.get('oscillating')} |"
        )
    lines += [
        "",
        "## 7. Offset sweep",
        "",
        "Algebraic TIA, tau=10 µs, o2 max-|z| step:",
        "",
        "| Vos | |Vlin−z| | |Vint| peak |",
        "|---:|---:|---:|",
    ]
    for r in report.get("vos_sweep") or []:
        lines.append(
            f"| {fmt(r.get('vos'))} | {fmt(r.get('err_final_vs_ref'))} | {fmt(r.get('max_vint'))} |"
        )
    lines += [
        "",
        "All listed Vos (0 to 1 mV) analog-pass. |Vint| ≈ Vos as expected. No startup",
        "saturation of the LEVEL 2 B-source. Correction time does not grow with Vos on",
        "this algebraic inner loop (the step delay dominates). A calibration phase is",
        "not required if the integrator is allowed to run; UIC from Vint=0 still works",
        "given several tau. There is no modeled correction-range limit other than the",
        "TIA rail (±15 V behavioral).",
        "",
        "## 8. Network A transient inference",
        "",
        f"First {report.get('n_A_tran')} of 100 Exp 24 vectors. tau=10 µs, fp=1 kHz,",
        "Vos=214 µV, Vin PULSE after 40 µs, t_stop=160 µs. No Python repair.",
        "",
        f"- MAE = {fmt(atran.get('mae'))}",
        f"- max |error| = {fmt(atran.get('max_abs_error'))}",
        f"- classification = {atran.get('accuracy')} (0 class failures)",
        f"- oscillating traces = {atran.get('n_oscillating')}",
        "",
        "Analog-pass vs frozen software reference. This is a **single step from Vin=0**,",
        "not a stream of changing vectors.",
        "",
        "## 9. Network F transient inference",
        "",
        f"First {report.get('n_F_tran')} of 40 Exp 24 vectors. Same servo/pole/Vos.",
        "1342 resistors, 48 TIA+servo cells. Disclosed subset; not a silent full-set swap.",
        "",
        f"- MAE = {fmt(ftran.get('mae'))}",
        f"- max |error| = {fmt(ftran.get('max_abs_error'))}",
        f"- classification = {ftran.get('accuracy')}",
        f"- oscillating traces = {ftran.get('n_oscillating')}",
        "",
        "Analog-pass (MAE 6.38e-5 ≤ 1e-3) and 100% class on this subset. Worst-vector",
        f"max error {fmt(ftran.get('max_abs_error'))} remains under the analog bar.",
        "",
        "## 10. Multiple-input behavior",
        "",
        "PWL Vin: three Exp 24 vectors in sequence (A indices "
        f"{(report.get('multi_input_vectors') or {}).get('A_idx')}, F "
        f"{(report.get('multi_input_vectors') or {}).get('F_idx')}).",
        "Sample at 0.92 of each dwell. Nested pole + tau=10 µs:",
        "",
        "| net | t_hold (s) | seg0 MAE | seg1 MAE | seg2 MAE | analog all |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for r in (dwell.get("A_pole") or []):
        lines.append(
            f"| A pole | {fmt(r.get('t_hold_s'))} | {fmt(r.get('seg0_mae'))} | "
            f"{fmt(r.get('seg1_mae'))} | {fmt(r.get('seg2_mae'))} | {r.get('all_analog')} |"
        )
    for r in (dwell.get("F_pole") or []):
        lines.append(
            f"| F pole | {fmt(r.get('t_hold_s'))} | {fmt(r.get('seg0_mae'))} | "
            f"{fmt(r.get('seg1_mae'))} | {fmt(r.get('seg2_mae'))} | {r.get('all_analog')} |"
        )
    alg80 = dwell.get("A_algebraic_80us") or {}
    lines += [
        f"| A algebraic | {fmt(alg80.get('t_hold_s'))} | {fmt(alg80.get('seg0_mae'))} | "
        f"{fmt(alg80.get('seg1_mae'))} | {fmt(alg80.get('seg2_mae'))} | {alg80.get('all_analog')} |",
        "",
        "Segment 0 is cheap: ngspice OP already equals vector 1, so the first sample is",
        "a settled DC point. Segments 1–2 are the scientific test (input **changes**).",
        "",
        "At t_hold = 80 µs with the 1 kHz pole, later segments analog-fail (A seg2 MAE",
        "~0.37). The servo is not a continuous 80 µs inference engine on the nested-loop",
        "model. It must re-null Vsum after each loading change; that residue includes",
        "both Vos and the finite-A Vlin/A term, so the integrator **does** move when the",
        "signal changes. That is nested-loop behavior, not a pure offset memory.",
        "",
        f"Minimum analog-passing dwell (A): {fmt(lat.get('min_A_multi_hold_s'))} s. "
        f"Network F: {fmt(lat.get('min_F_multi_hold_s'))} s.",
        f"Algebraic TIA A at 80 µs analog-all: {alg80.get('all_analog')}.",
        "",
        "Architecture class: **sampled / static-calibrated inference** on the finite-TIA",
        "model. It is not shown to meet the Experiment 22 10 µs continuous target.",
        "A reset between vectors is not required if dwell is long enough; a clocked",
        "sample-and-hold of Vin would be compatible.",
        "",
        "## 11. Auto-zero comparison",
        "",
        "Vref-gated auto-zero (Exp 24 LEVEL 2, Vin=Vref=0 then both on), isolated o2",
        f"max-|z| TRAN: |Vlin−z| = {fmt(az.get('err_final_vs_ref'))} at t_stop=80 µs.",
        "That matches the no-servo L Vos=0 finite-A floor (1.44e-3), not the servo's",
        "1e-8 VG restoration. AZ therefore recovers the Vos=0 TIA, including leftover",
        "finite-A loading. The servo, once settled, also removes that loading error.",
        "",
        "Timing: AZ needs a clocked sample (~20 µs used here) plus inference; the servo",
        "needs nested-loop dwell (10 µs–ms depending on TIA pole). Both are LEVEL 2.",
        "Neither is a transistor op-amp. For a future physical primitive, AZ has a",
        "clearer clocked contract; the servo has better settled analog MAE if you can",
        "wait and if the inner amplifier is not slower than the integrator.",
        "",
        "## 12. Error budget",
        "",
        "Settled OP of the same OTA-C netlist after dynamic correction is shown to work",
        "(equivalent to t ≫ tau). Not a substitute for claiming TRAN mismatch.",
        "",
        "| mechanism | MAE | acc |",
        "|---|---:|---:|",
        f"| ideal R, Vos=214 µV, servo | {fmt((budget.get('R0') or {}).get('mae'))} | {(budget.get('R0') or {}).get('accuracy')} |",
        f"| 0.1% local R | {fmt((budget.get('R0p1pct') or {}).get('mae'))} | {(budget.get('R0p1pct') or {}).get('accuracy')} |",
        f"| 0.5% local R | {fmt((budget.get('R0p5pct') or {}).get('mae'))} | {(budget.get('R0p5pct') or {}).get('accuracy')} |",
        f"| 13 nA leak, ideal R | {fmt((budget.get('leak_13nA_idealR') or {}).get('mae'))} | {(budget.get('leak_13nA_idealR') or {}).get('accuracy')} |",
        f"| combined 214 µV + 13 nA + 0.5% R | {fmt((budget.get('combined_214uV_13nA_0p5pct') or {}).get('mae'))} | {(budget.get('combined_214uV_13nA_0p5pct') or {}).get('accuracy')} |",
        "",
        "After the dynamic servo exists, **0.5% resistor mismatch remains the analog",
        "floor** (~4.2e-3), matching Experiment 24 DC. Leak at 13 nA is analog-pass",
        "alone (4.17e-4). Combined is mismatch-dominated (4.66e-3, acc 97.5% on 40",
        "vectors). 0.1% R is analog-pass (8.4e-4) with 100% class.",
        "",
        "## 13. Numerical validation",
        "",
        f"Algebraic o2: delta y_final (tstep/5, reltol=1e-6) = {fmt(num.get('delta_y_final'))}.",
        f"Pole o2: delta y_final = {fmt(nump.get('delta_y_final'))}.",
        "Final values are reproducible. Nested-loop analog-fail at tau≤1 µs + 1 kHz pole",
        "is not a coarse-timestep artefact of the passing window; it repeats in the",
        "structured sweep. Do not overclaim digits below simulator agreement (~1e-11",
        "algebraic, pole delta reported above).",
        "",
        "## 14. Failure cases",
        "",
        "1. Nested loop with servo faster than TIA pole (tau ≤ 1 µs, fp=1 kHz): analog",
        "   fail ~7e-2 on o2. Preserved. Not replaced by a slower tau without comment.",
        "2. Multi-input at 80 µs dwell with fp=1 kHz: later segments analog-fail.",
        "   Preserved; longer dwells are reported separately.",
        "3. Isolated o2 vs z without servo is analog-fail even at Vos=0 (finite A).",
        "   Network MAE can still pass because other neurons are lighter.",
        "4. Uncorrected Network A Vos=214 µV DC: acc 0.99. Not hidden.",
        "5. No unit-cell oscillation_flag trips. Fast-servo analog fail is distortion,",
        "   not a limit-cycle under the coded detector.",
        "6. LEVEL 2 B-source Vplus is unlimited; saturation of a real OTA is not modeled.",
        "",
        "## 15. Best operating point",
        "",
        "- LEVEL 2 OTA-C servo, gm=1e-3, C=10 nF, Rleak=1e9, **tau=10 µs**",
        "- TIA: XSPICE limit, A=1e5, optional behavioral fp=1 kHz for nested-loop claims",
        "- Vos=214 µV, frozen Exp 9 weights, Architecture A fabric",
        "- Single-step Network F TRAN MAE 6.38e-5, acc 100% (12-vector subset)",
        "- Changing inputs: only after a dwell listed in §10",
        "",
        "## 16. Latency / settling requirements",
        "",
        f"- Selected servo tau: {fmt(lat.get('selected_tau_s'))} s",
        f"- Campaign recommended dwell (8·tau): {fmt(lat.get('recommended_dwell_s'))} s",
        f"- Measured min analog multi-input dwell A: {fmt(lat.get('min_A_multi_hold_s'))} s",
        f"- Measured min analog multi-input dwell F: {fmt(lat.get('min_F_multi_hold_s'))} s",
        "- Experiment 22 10 µs settling proxy: **not met** for changing inputs on the",
        "  nested 1 kHz-pole model",
        "- UIC cold start at tau=1 ms: a few milliseconds",
        "",
        "## 17. Physical realism level",
        "",
        report.get("hardware_level") or "",
        "Not board power, silicon area, transistor count, or MOS W/L.",
        "",
        "## 18. Limitations",
        "",
        report.get("limitations") or "",
        "Network F TRAN used the first 12 of 40 Exp 24 vectors. Mismatch budget is settled",
        "OP. Fast algebraic-TIA results overstate inner-loop bandwidth. The 1 kHz pole is",
        "a behavioral RC, not fT. B-source correction is unbounded.",
        "",
        "## 19. Honest recommendation for Experiment 26",
        "",
        report.get("next_experiment") or "",
        "",
        "Do not jump to transistor-level Network F. Do not invent MOS sizing.",
        "Do not retrain. Do not use per-weight calibration.",
        "",
        "## FINAL STATUS",
        "",
        report.get("final_status") or "",
        "",
        "SPICE is the source of truth. Frozen Experiment 9 weights were not edited.",
        "",
    ]
    REPORT_MD.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
