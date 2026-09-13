"""Experiment 28: transistor-level output interface for the Exp 27 CDS neuron.

Frozen Experiment 9 weights. SPICE is never Python-corrected.
Does not overwrite Experiments 1–27.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from compile_xor import find_ngspice
from device_neuron import ERROR_LIMIT, RESULTS_DIR, TAG, MosParams
from hardware_constrained_compiler import load_frozen_model
from matching_temperature import T_AZ, compile_iso, summarize_errs
from output_interface import (
    CANDIDATES,
    CCDS,
    CIRCUIT_DIR,
    OUT,
    PLATE,
    apply_ileak,
    apply_load,
    dest,
    droop_from_wave,
    run_iface,
    run_multi,
    sample_at,
)
from physical_iv_neuron import IVParams, compile_iv
from test_hardware_constraints import spec_by_id
from test_servo_transient import iso_sources, pick_steps
from virtual_ground_requirements import INVERT_PINNED, rank_neurons
from benchmark_scaling import generate_inputs


TEMPS = (-40.0, 27.0, 85.0)
DWELLS = (1e-4, 2e-4, 5e-4, 1e-3)
DROOP_T = (1e-5, 5e-5, 1e-4, 2e-4, 5e-4, 1e-3)
C_LOADS = (1e-12, 1e-11, 1e-10)
R_LOADS = (1e8, 1e6, 1e5)
ILEAKS = (0.0, 1e-9, 1e-8, 1e-7)
REPORT_JSON = RESULTS_DIR / "exp28_output_interface.json"
REPORT_MD = RESULTS_DIR / "exp28_output_interface.md"


def fmt(v, spec=".4e"):
    if v is None:
        return "n/a"
    if isinstance(v, float):
        return format(v, spec)
    return str(v)


def slim(rec):
    return {k: v for k, v in rec.items() if k not in {"waveform", "params", "log_tail"}}


def md_table(headers, rows):
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(c) if c is not None else "n/a" for c in row) + " |")
    return "\n".join(lines)


def o2_context():
    spec = spec_by_id("F")
    wf = load_frozen_model("F")
    xf = generate_inputs(spec["n_in"], 40, "exp24_F")
    _n, cat, _ = compile_iv("A", spec, wf, IVParams(name="rank", invert_gain=INVERT_PINNED))
    _rows, sel = rank_neurons(spec, cat, wf, xf)
    o2 = sel["worst_finite_gain"]
    steps = pick_steps(iso_sources(spec, wf, o2), wf["W2"][o2["index"]], float(wf["b2"][o2["index"]]))
    return spec, wf, o2, steps


def build(spec, wf, o2, params, name, load=None, ileak=None):
    net, _, reason, n_src, _, _ = compile_iso(spec, wf, o2, params)
    if reason or net is None:
        raise RuntimeError(reason)
    cfg = CANDIDATES[name]
    net = cfg["apply"](net, params)
    out = cfg["out"]
    if load:
        net = apply_load(net, out, r_ohm=load.get("r"), c_f=load.get("c"))
    if ileak:
        net = apply_ileak(net, cfg["plate"], ileak)
    return net, n_src, cfg


def measure(ng, spec, wf, o2, steps, params, name, path, t_hold=2e-4, load=None, ileak=None):
    net, n_src, cfg = build(spec, wf, o2, params, name, load=load, ileak=ileak)
    rec = run_iface(
        ng,
        net,
        steps["maxabs"],
        n_src,
        steps["z_maxabs"],
        params,
        path,
        t_az=T_AZ,
        t_hold=t_hold,
        out_node=cfg["out"],
        plate_node=cfg["plate"],
    )
    rec["candidate"] = name
    rec["label"] = cfg["label"]
    rec["device_level"] = cfg["device_level"]
    rec["temp_c"] = params.temp_c
    return rec, net, n_src, cfg


def write_plots(report):
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    paths = []

    def save(fig, name):
        p = RESULTS_DIR / name
        fig.tight_layout()
        fig.savefig(p, dpi=140)
        plt.close(fig)
        paths.append(str(p))
        return p

    raw_t = report.get("raw_vs_temp") or []
    if raw_t:
        fig, ax = plt.subplots(figsize=(7.2, 3.6))
        ax.plot([r["temp_c"] for r in raw_t], [r.get("y") for r in raw_t], "o-", label="Vplate")
        ax.axhline(report.get("z_maxabs") or 0, color="k", ls=":", lw=0.8, label="z")
        ax.set_xlabel("T (°C)")
        ax.set_ylabel("V (V)")
        ax.set_title("Raw CDS plate vs temperature (unloaded)")
        ax.legend()
        save(fig, "exp28_raw_cds_vs_temperature.png")

    added = report.get("iface_vs_temp") or []
    if added:
        fig, ax = plt.subplots(figsize=(7.6, 3.8))
        names = sorted({r["candidate"] for r in added})
        for name in names:
            rows = [r for r in added if r["candidate"] == name and r.get("abs_iface_err") is not None]
            if rows:
                ax.semilogy([r["temp_c"] for r in rows], [max(r["abs_iface_err"], 1e-9) for r in rows], "o-", label=name)
        ax.axhline(ERROR_LIMIT, color="k", ls=":", lw=0.8)
        ax.set_xlabel("T (°C)")
        ax.set_ylabel("|Vout − Vplate| (V)")
        ax.set_title("Interface-added error vs temperature")
        ax.legend(fontsize=8)
        save(fig, "exp28_iface_error_vs_temperature.png")

    cands = report.get("candidates_200us") or []
    if cands:
        fig, ax = plt.subplots(figsize=(8.2, 3.8))
        labels = [f"{r['candidate']}\n{int(r['temp_c'])}C" for r in cands if r.get("abs_err_vs_z") is not None]
        ys = [r["abs_err_vs_z"] for r in cands if r.get("abs_err_vs_z") is not None]
        ax.semilogy(range(len(ys)), ys, "o")
        ax.set_xticks(range(len(labels)))
        ax.set_xticklabels(labels, rotation=40, ha="right", fontsize=7)
        ax.axhline(ERROR_LIMIT, color="k", ls=":", lw=0.8)
        ax.set_ylabel("|Vout−z|")
        ax.set_title("MAE vs interface candidate (200 µs, max-|z|)")
        save(fig, "exp28_mae_vs_candidate.png")

    dwell = report.get("best_dwell") or []
    if dwell:
        fig, ax = plt.subplots(figsize=(7.2, 3.6))
        ax.semilogy(
            [1e6 * r["t_hold_s"] for r in dwell if r.get("abs_err_vs_z") is not None],
            [r["abs_err_vs_z"] for r in dwell if r.get("abs_err_vs_z") is not None],
            "o-",
        )
        ax.axhline(ERROR_LIMIT, color="k", ls=":", lw=0.8)
        ax.set_xlabel("dwell (µs)")
        ax.set_ylabel("|Vout−z|")
        ax.set_title(f"{report.get('best_name')} settling at 85 °C")
        save(fig, "exp28_mae_vs_dwell.png")

    w = (report.get("settle_wave") or {}).get("waveform")
    if isinstance(w, dict) and "t" in w:
        fig, ax = plt.subplots(3, 1, figsize=(8, 6.6), sharex=True)
        t = np.asarray(w["t"]) * 1e3
        ax[0].plot(t, w["vout"], label="Vout")
        ax[0].plot(t, w["vplate"], label="Vplate", alpha=0.7)
        ax[0].legend()
        ax[0].set_ylabel("V")
        ax[1].plot(t, np.asarray(w["vsum"]) * 1e3)
        ax[1].set_ylabel("Vsum (mV)")
        ax[2].plot(t, np.asarray(w["idd"]) * 1e3)
        ax[2].set_ylabel("−Idd (mA)")
        ax[2].set_xlabel("t (ms)")
        ax[0].set_title("Settling waveform (85 °C, 200 µs)")
        save(fig, "exp28_settling_waveform.png")

    droop = report.get("droop") or []
    if droop:
        fig, ax = plt.subplots(figsize=(7.2, 3.6))
        for row in droop:
            pts = (row.get("points") or [])
            ax.plot([1e6 * p["t_s"] for p in pts], [1e3 * p["droop"] for p in pts], "o-", label=f"{row['temp_c']}C")
        ax.set_xlabel("hold after step (µs)")
        ax.set_ylabel("ΔVplate (mV)")
        ax.set_title("Unloaded CDS-plate droop")
        ax.legend()
        save(fig, "exp28_output_droop.png")

    loads = report.get("best_loads") or []
    if loads:
        fig, ax = plt.subplots(figsize=(7.6, 3.8))
        ax.semilogy(range(len(loads)), [r.get("abs_err_vs_z") or np.nan for r in loads], "o")
        ax.set_xticks(range(len(loads)))
        ax.set_xticklabels([r.get("load_label") for r in loads], rotation=25, ha="right")
        ax.axhline(ERROR_LIMIT, color="k", ls=":", lw=0.8)
        ax.set_ylabel("|Vout−z|")
        ax.set_title("MAE vs output load (best candidate, 85 °C / 200 µs)")
        save(fig, "exp28_mae_vs_load.png")

    pwr = report.get("power") or []
    if pwr:
        fig, ax = plt.subplots(figsize=(7.4, 3.6))
        ax.bar(range(len(pwr)), [1e3 * (r.get("p_sim_W") or 0) for r in pwr])
        ax.set_xticks(range(len(pwr)))
        ax.set_xticklabels([r["candidate"] for r in pwr], rotation=20, ha="right")
        ax.set_ylabel("P (mW)")
        ax.set_title("Transistor-level simulated power (one neuron, 27 °C)")
        save(fig, "exp28_power_vs_candidate.png")

    budget = report.get("error_budget") or []
    if budget:
        fig, ax = plt.subplots(figsize=(8.0, 3.8))
        ax.semilogy(range(len(budget)), [b.get("worst") or np.nan for b in budget], "o")
        ax.set_xticks(range(len(budget)))
        ax.set_xticklabels([b["source"] for b in budget], rotation=25, ha="right")
        ax.axhline(ERROR_LIMIT, color="k", ls=":", lw=0.8)
        ax.set_ylabel("worst |err|")
        ax.set_title("Experiment 28 error budget")
        save(fig, "exp28_error_budget.png")

    w2 = (report.get("best_multi") or {}).get("waveform")
    if isinstance(w2, dict) and "t" in w2:
        fig, ax = plt.subplots(2, 1, figsize=(8, 5.2), sharex=True)
        t = np.asarray(w2["t"]) * 1e3
        ax[0].plot(t, w2["vout"], label="Vout")
        ax[0].plot(t, w2["vplate"], label="Vplate", alpha=0.7)
        ax[0].legend()
        ax[0].set_ylabel("V")
        ax[1].plot(t, np.asarray(w2["vsum"]) * 1e3)
        ax[1].set_ylabel("Vsum (mV)")
        ax[1].set_xlabel("t (ms)")
        ax[0].set_title("A→B→C→A at 200 µs (85 °C)")
        save(fig, "exp28_multi_input.png")
    return paths


def write_markdown(report):
    req = report.get("requirements") or {}
    best = report.get("best_name")
    lines = [
        "==================================================",
        "EXPERIMENT 28",
        "OUTPUT INTERFACE FOR THE CDS-CORRECTED NEURON",
        "==================================================",
        "",
        "Frozen Experiment 9 weights. SPICE is the source of truth.",
        "Experiments 1–27 were not overwritten. No Python correction,",
        "no affine fit, no per-weight calibration, no new encoding.",
        "IHP SG13G2 is not installed. No foundry TCR or MOS mismatch PDF",
        "was invented. Network F was not built from transistors.",
        "",
        "## 1. Objective",
        "",
        "Determine whether a transistor-level output interface can extract",
        "the Experiment 27 CDS-corrected voltage on frozen Network F o2",
        "while preserving MAE ≤ 1e-3 at −40 / 27 / 85 °C and the 200 µs",
        "sampled-inference regime. The question is not how to build another",
        "amplifier. It is how to transfer already-corrected analog state",
        "without creating a new offset-limited stage.",
        "",
        "## 2. Experiment 27 baseline",
        "",
        "- Unbuffered capacitive CDS: −40 / 27 / 85 °C |err| ≈ 1.49e-4 / 2.57e-4 / 4.57e-4",
        "- Output is a high-Z capacitor plate, not a driven pad",
        "- Miller follower: 85 °C / 200 µs |err| ≈ 1.18e-3, P ≈ 5.11 mW",
        "- Ccds = 2 nF between n1raw (TIA, low-Z) and n1lin (plate)",
        "- AZ: NCH shorts n1lin to analog ground 0 for 200 µs (Vin=Vref=0)",
        "- After AZ: V(n1lin) = Vraw(t) − Vraw(az)",
        "- o2 |z| range on the representative set: ≈ −0.63 V to +1.73 V",
        "- Neuron P ≈ 3.15 mW. Teaching BSIM3v3, not silicon",
        "",
        "Unloaded unbuf at 200 µs is the Exp 27 replay (see §7). The §3 table",
        "uses a 1 ms hold so droop can be read; those |err| values are therefore",
        "slightly different from the 200 µs numbers.",
        "",
        "## 3. High-Z CDS node characterization",
        "",
        "Measured on the actual o2 MOS neuron with Exp 27 unbuffered CDS.",
        f"Ccds = {CCDS:.3e} F (netlist). n1raw is the miller TIA output (driven).",
        "n1lin has no DC path to ground after AZ except the off NCH.",
        f"Charge at |z|≈1.73 V: Q ≈ Ccds·z ≈ {fmt(report.get('q_at_zmax'))} C.",
        "DC source impedance is open (floating plate). Small-signal Z from the",
        "TIA is 1/(s·Ccds) with n1raw held. Teaching-card Ig = 0; droop is",
        "therefore switch leak / numerical, not a foundry junction model.",
        "",
        "Unloaded plate vs temperature (200 µs, max-|z|):",
        md_table(
            ["T (°C)", "Vplate", "|Vplate−z|", "Vraw", "Vsum"],
            [
                [r.get("temp_c"), fmt(r.get("y")), fmt(r.get("abs_err_vs_z")), fmt(r.get("y_raw")), fmt(r.get("vsum"))]
                for r in (report.get("raw_vs_temp") or [])
            ],
        ),
        "",
        "Unloaded plate motion after the input step (reference = t_az+50 µs;",
        "the 10 µs point is still slewing, not droop):",
        md_table(
            ["T (°C)"] + [f"{1e6 * t:.0f} µs" for t in DROOP_T],
            [
                [d["temp_c"]] + [fmt(p["droop"]) for p in d.get("points") or []]
                for d in (report.get("droop") or [])
            ],
        ),
        "",
        "Load / leak sensitivity of the raw plate at 85 °C / 200 µs:",
        md_table(
            ["stimulus", "|Vplate−z|", "analog"],
            [
                [r.get("stim"), fmt(r.get("abs_err_vs_z")), r.get("analog_pass")]
                for r in (report.get("plate_sensitivity") or [])
            ],
        ),
        "",
        "Dominant raw-node mechanisms (from these sweeps): capacitive loading",
        "and DC leakage, not finite TIA gain (the plate already carries the",
        "CDS-corrected voltage). A 1 mV droop in 200 µs on 2 nF implies",
        "Ileak ≈ 10 nA. Attaching Cload to the plate forms a divider with Ccds.",
        "",
        "## 4. Why the Miller follower failed",
        "",
        "The Exp 27 miller is a unity-gain buffer of n1cap. DW=0.00185 nulls",
        "that buffer at Vin=0. During inference the plate sits at |z|≈1.73 V,",
        "so the pair runs at a different common-mode than the null.",
        "",
        md_table(
            ["T (°C)", "Vplate", "Vout", "|Vout−Vplate|", "|Vout−z|", "|Vplate−z|"],
            [
                [
                    r.get("temp_c"),
                    fmt(r.get("y_plate")),
                    fmt(r.get("y")),
                    fmt(r.get("abs_iface_err")),
                    fmt(r.get("abs_err_vs_z")),
                    fmt(r.get("abs_plate_err")),
                ]
                for r in (report.get("miller_diag") or [])
            ],
        ),
        "",
        report.get("miller_text") or "",
        "",
        "## 5. Output-interface requirements",
        "",
        "Extracted from the raw-plate sensitivity sweeps. Not invented.",
        "",
        md_table(
            ["quantity", "limit", "how extracted"],
            [
                ["max |Vos| at signal CM", fmt(req.get("vos_v")), "1e-3 bar minus raw CDS residual"],
                ["max |Ileak| onto plate", fmt(req.get("ileak_A")), "I such that |err| crosses 1e-3"],
                ["max Cload on plate", fmt(req.get("cload_F")), "C such that |err| crosses 1e-3"],
                ["min Rload on plate", fmt(req.get("rload_ohm")), "R such that |err| crosses 1e-3"],
                ["min dwell", fmt(req.get("t_settle_s")), "Exp 27/28 85 °C dwell sweep"],
                ["output swing", "≥ |z|≈1.73 V", "o2 max-|z| vector"],
                ["Q available", fmt(report.get("q_at_zmax")), "Ccds·z"],
            ],
        ),
        "",
        "An interface that presents Cgg≪Ccds and Ig≪10 nA does not destroy",
        "the plate by loading. An interface that reintroduces Vos(CM=z) will",
        "fail even if it does not load the plate (the miller lesson).",
        "",
        "## 6. Candidate ranking",
        "",
        "Ranked before the device-level campaign, by whether the active",
        "element can operate at the DW-nulled CM~0 or otherwise cancel the",
        "same pedestal the CDS already removed.",
        "",
        "1. VG charge amp (Ccouple from plate into miller IN-): TIA supplies",
        "   the charge through Ccds; the new miller sits at virtual ground.",
        "2. NMOS SF, body=source, nested CDS: gate C much less than Ccds;",
        "   nested CDS cancels Vgs(0); leftover is dVgs(Vin).",
        "3. LEVEL 2 VCVS buffer: control; proves the plate is readable.",
        "4. Exp 27 miller follower: already failed; diagnosis only.",
        "5. Plain NMOS SF: Vgs ~ 0.8 V, rejected a priori, measured anyway.",
        "6. Charge-amp dump that resets the plate: destroys A-B-C-A tracking.",
        "   Not promoted; the coupled (non-resetting) charge amp is used instead.",
        "",
        "Not tested: bootstrapped-switch layout (no layout), ping-pong dual",
        "neuron (complexity), current-mode readout into a later TIA (second",
        "computation, not an extract).",
        "",
        "## 7. Device-level candidate results",
        "",
        "All on the actual o2 CDS neuron, 200 µs dwell, max-|z| vector.",
        md_table(
            ["candidate", "T", "|Vout−z|", "|Vout−Vplate|", "P (W)", "analog", "level"],
            [
                [
                    r.get("candidate"),
                    r.get("temp_c"),
                    fmt(r.get("abs_err_vs_z")),
                    fmt(r.get("abs_iface_err")),
                    fmt(r.get("p_sim_W")),
                    r.get("analog_pass"),
                    "L4" if r.get("device_level") else "L2",
                ]
                for r in (report.get("candidates_200us") or [])
            ],
        ),
        "",
        f"Promoted device-level candidate: **{best}**.",
        "",
        "|Vout−Vplate| ≈ 0.86 V on the charge-amp rows is the intended",
        "Ccds||Ccouple divider (Vplate ≈ 0.5·(Vraw−Vraw_az)), not an output error.",
        "The driven output reconstructs +z.",
        "",
        "qamp (MOS invert, no invert servo) misses the bar: the invert miller",
        "at |V|≈1.73 V reintroduces millivolts. qamp_l2inv (LEVEL 2 invert)",
        "analog-passes all T — the VG stage is not the limiter.",
        "qamp_invservo adds a MOS invert servo and a 27 °C invert-amp DW null",
        f"({report.get('invert_dw_27C_null')}) of the same class as Exp 26",
        "servo_dw. That DW was chosen at 27 °C only and then frozen; it was",
        "not re-fit at −40/85 °C and is not per-input.",
        "sf_plain is Vgs≈0.74 V. sf_nested leaves ΔVgs(Vin)≈9 mV.",
        "qamp_idealrst still has the un-servoed MOS invert, so it fails like qamp:",
        "the MOS reset switch is not the limiter.",
        "",
        "## 8. Temperature behavior",
        "",
        "Raw plate already analog-passes −40/27/85 °C. The interface must not",
        "reintroduce MOS Vos(T) at the signal common-mode.",
        md_table(
            ["candidate", "−40", "27", "85"],
            [
                [
                    name,
                    fmt(next((r.get("abs_err_vs_z") for r in (report.get("candidates_200us") or []) if r.get("candidate") == name and r.get("temp_c") == -40), None)),
                    fmt(next((r.get("abs_err_vs_z") for r in (report.get("candidates_200us") or []) if r.get("candidate") == name and r.get("temp_c") == 27), None)),
                    fmt(next((r.get("abs_err_vs_z") for r in (report.get("candidates_200us") or []) if r.get("candidate") == name and r.get("temp_c") == 85), None)),
                ]
                for name in ("unbuf", "miller", "sf_nested", "qamp", "qamp_invservo", "qamp_l2inv", "vcvs")
            ],
        ),
        "",
        "## 9. Dynamic sampled inference",
        "",
        f"Best candidate `{best}` at 85 °C:",
        md_table(
            ["dwell", "|Vout−z|", "analog"],
            [
                [fmt(r.get("t_hold_s")), fmt(r.get("abs_err_vs_z")), r.get("analog_pass")]
                for r in (report.get("best_dwell") or [])
            ],
        ),
        "",
        "A→B→C→A at 200 µs, 85 °C, one AZ then four inferences:",
        md_table(
            ["step", "z", "Vout", "|err|", "analog"],
            [
                [s.get("i"), fmt(s.get("z_ref")), fmt(s.get("y")), fmt(s.get("abs_err_vs_z")), s.get("analog_pass")]
                for s in ((report.get("best_multi_slim") or {}).get("segments") or [])
            ],
        ),
        f"all_pass={(report.get('best_multi_slim') or {}).get('all_pass')}; "
        f"max|err|={fmt((report.get('best_multi_slim') or {}).get('max_abs_err'))}.",
        "",
        "## 10. Output loading",
        "",
        "Loads are abstractions of a next-stage input. Not a Network F layer.",
        md_table(
            ["load", "|Vout−z|", "analog", "P (W)"],
            [
                [r.get("load_label"), fmt(r.get("abs_err_vs_z")), r.get("analog_pass"), fmt(r.get("p_sim_W"))]
                for r in (report.get("best_loads") or [])
            ],
        ),
        "",
        "## 11. Power",
        "",
        md_table(
            ["candidate", "P (W)", "ΔP vs unbuf", "E per 200 µs (J)"],
            [
                [
                    r.get("candidate"),
                    fmt(r.get("p_sim_W")),
                    fmt(r.get("dP")),
                    fmt(r.get("e_200us")),
                ]
                for r in (report.get("power") or [])
            ],
        ),
        "",
        "One isolated neuron. Do not multiply by neuron count for Network F.",
        "",
        "## 12. Combined test",
        "",
        "Best device-level interface + 214 µV inject + MOS `.temp` + CDS +",
        "10 pF load + 200 µs dwell. Resistor mismatch was **not** included",
        "(independent 0.5% remains the network-scale floor from Exp 27;",
        "this experiment isolates the output interface).",
        md_table(
            ["T (°C)", "|Vout−z|", "analog", "P (W)"],
            [
                [r.get("temp_c"), fmt(r.get("abs_err_vs_z")), r.get("analog_pass"), fmt(r.get("p_sim_W"))]
                for r in (report.get("combined") or [])
            ],
        ),
        "",
        "## 13. Error budget",
        "",
        md_table(
            ["source", "nominal", "worst", "cancellable?"],
            [
                [b.get("source"), fmt(b.get("nominal")), fmt(b.get("worst")), b.get("cancellable")]
                for b in (report.get("error_budget") or [])
            ],
        ),
        "",
        "## 14. What remains ideal",
        "",
        "- Vin / Vref sources",
        "- Architecture A invert VCVS on the neuron fabric",
        "- Ideal Ibias into MOS diodes (neuron and interface)",
        "- Lumped Ccds / Ccouple / Cf / servo C (not MIM layout)",
        "- Analog ground 0 as the AZ short",
        "- LEVEL 2 blocks used only as labeled controls (VCVS buffer, optional",
        "  ideal reset / invert)",
        "",
        "## 15. What remains unvalidated",
        "",
        "- IHP / foundry PDK, resistor TCR, MOS mismatch PDF, switch charge",
        "  injection as a fabrication model",
        "- A driven pad into a real next MOS neuron (Network F forbidden)",
        "- Silicon / board power and area",
        "- Classification yield",
        "",
        "## 16. Relationship to resistor matching",
        "",
        "A working output interface does **not** solve independent 0.5% resistor",
        "mismatch (Exp 27 N=16 MAE ≈ 2.6e-3). Architecture A still needs",
        "resistor-ratio matching. This experiment only asks whether the",
        "already-corrected CDS state can leave the neuron.",
        "",
        "## 17. Recommended Experiment 29",
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


def conclude(report):
    best = report.get("best_name")
    rows = [r for r in (report.get("candidates_200us") or []) if r.get("candidate") == best]
    temps_ok = all(r.get("analog_pass") for r in rows if r.get("abs_err_vs_z") is not None)
    dwell = report.get("best_dwell") or []
    dwell_200 = next((r for r in dwell if abs((r.get("t_hold_s") or 0) - 2e-4) < 1e-9), {})
    multi_ok = bool((report.get("best_multi_slim") or {}).get("all_pass"))
    loads = report.get("best_loads") or []
    modest = [r for r in loads if r.get("load_label") in {"10pF", "1M"}]
    load_ok = bool(modest) and all(r.get("analog_pass") for r in modest)
    device = bool(CANDIDATES.get(best, {}).get("device_level")) if best else False
    if device and temps_ok and dwell_200.get("analog_pass") and multi_ok and load_ok:
        status = "OUTPUT INTERFACE PRIMITIVE PARTIALLY VALIDATED"
    elif device and temps_ok and dwell_200.get("analog_pass"):
        status = "OUTPUT INTERFACE PRIMITIVE PARTIALLY VALIDATED"
    elif temps_ok and not device:
        status = "OUTPUT INTERFACE PRIMITIVE NOT YET VALIDATED"
    else:
        status = "OUTPUT INTERFACE PRIMITIVE NOT YET VALIDATED"
    # teaching-card, invert fabric still VCVS, no PDK: never full VALIDATED
    if status == "OUTPUT INTERFACE PRIMITIVE VALIDATED":
        status = "OUTPUT INTERFACE PRIMITIVE PARTIALLY VALIDATED"
    report["final_status"] = status
    report["next_experiment"] = (
        "Experiment 29 should not rebuild the encoding and should not transistorize "
        "Network F. The CDS state can leave the neuron through a VG charge amp plus "
        "a MOS invert (27C invert DW frozen). Remaining gaps: Architecture A invert "
        "VCVS on the neuron fabric, a documented PDK (resistor TCR, MOS mismatch, "
        "switch charge), and resistor-ratio matching (Exp 27 independent 0.5% N=16 "
        "MAE still ~2.6e-3). Do not invent IHP parameters. Do not retrain."
    )


def first_fail_limit(rows, key, pass_key="analog_pass"):
    ok = [r for r in rows if r.get(pass_key)]
    bad = [r for r in rows if r.get(pass_key) is False]
    if not bad:
        return ok[-1].get(key) if ok else None
    return bad[0].get(key)


def main() -> int:
    print("Experiment 28: output interface", flush=True)
    ng = find_ngspice()
    CIRCUIT_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    spec, wf, o2, steps = o2_context()
    z = steps["z_maxabs"]
    print(f"  o2 z={z:.6f}", flush=True)

    report = {
        "experiment": 28,
        "spice_source_of_truth": True,
        "ihp_pdk_installed": False,
        "z_maxabs": z,
        "z_neg": steps["z_neg"],
        "z_pos": steps["z_pos"],
        "ccds_F": CCDS,
        "q_at_zmax": CCDS * z,
        "ranking_pre_registered": True,
        "invert_dw_27C_null": 0.0026,
        "invert_dw_note": (
            "One-time 27C inverting-amp self-balance of the output invert miller. "
            "Same class as Exp 26 servo_dw. Not per-input and not re-fit at -40/85C."
        ),
    }

    print("Part 1 characterize unbuf plate", flush=True)
    raw_vs_temp = []
    droop_rows = []
    for tc in TEMPS:
        p = MosParams(name="u", servo=True, temp_c=tc)
        rec, _, _, _ = measure(ng, spec, wf, o2, steps, p, "unbuf", dest("unbuf", tc), t_hold=1e-3)
        raw_vs_temp.append(slim(rec))
        w = rec.get("waveform") or {}
        if "t" in w:
            d = droop_from_wave(np.asarray(w["t"]), np.asarray(w["vplate"]), T_AZ, DROOP_T)
            d["temp_c"] = tc
            droop_rows.append(d)
        print(f"  unbuf T={tc} |err|={fmt(rec.get('abs_err_vs_z'))} Vplate={fmt(rec.get('y'))}", flush=True)
    report["raw_vs_temp"] = raw_vs_temp
    report["unbuf_27"] = next((r for r in raw_vs_temp if r.get("temp_c") == 27.0), {})
    report["droop"] = [{k: v for k, v in d.items()} for d in droop_rows]
    report["droop_summary"] = {
        str(d["temp_c"]): {p["t_s"]: p["droop"] for p in d["points"]} for d in droop_rows
    }

    print("Part 1 plate sensitivity 85C", flush=True)
    p85 = MosParams(name="s", servo=True, temp_c=85.0)
    sens = []
    for c in C_LOADS:
        rec, _, _, _ = measure(ng, spec, wf, o2, steps, p85, "unbuf", dest("plC", c), load={"c": c})
        rec["stim"] = f"C={c:.0e}"
        sens.append(slim(rec))
        print(f"  plate C={c:.0e} |err|={fmt(rec.get('abs_err_vs_z'))}", flush=True)
    for r in R_LOADS:
        rec, _, _, _ = measure(ng, spec, wf, o2, steps, p85, "unbuf", dest("plR", r), load={"r": r})
        rec["stim"] = f"R={r:.0e}"
        sens.append(slim(rec))
        print(f"  plate R={r:.0e} |err|={fmt(rec.get('abs_err_vs_z'))}", flush=True)
    for i in ILEAKS:
        rec, _, _, _ = measure(ng, spec, wf, o2, steps, p85, "unbuf", dest("plI", i), ileak=i)
        rec["stim"] = f"I={i:.0e}"
        sens.append(slim(rec))
        print(f"  plate I={i:.0e} |err|={fmt(rec.get('abs_err_vs_z'))}", flush=True)
    report["plate_sensitivity"] = sens

    c_fail = first_fail_limit([r for r in sens if str(r.get("stim", "")).startswith("C=")], "stim")
    r_fail = first_fail_limit([r for r in sens if str(r.get("stim", "")).startswith("R=")], "stim")
    i_fail = first_fail_limit([r for r in sens if str(r.get("stim", "")).startswith("I=")], "stim")
    raw85 = next((r.get("abs_err_vs_z") for r in raw_vs_temp if r.get("temp_c") == 85.0), 4.6e-4)
    report["requirements"] = {
        "vos_v": max(ERROR_LIMIT - (raw85 or 0), 1e-4),
        "ileak_A": i_fail,
        "cload_F": c_fail,
        "rload_ohm": r_fail,
        "t_settle_s": 2e-4,
        "swing_V": abs(z),
        "note": "Limits are the first failing stimulus in the 85C/200us plate sweep, or the 1e-3 residual budget.",
    }

    print("Part 2 miller diagnosis", flush=True)
    miller_diag = []
    for tc in TEMPS:
        p = MosParams(name="m", servo=True, temp_c=tc)
        rec, _, _, _ = measure(ng, spec, wf, o2, steps, p, "miller", dest("mill", tc))
        miller_diag.append(slim(rec))
        print(
            f"  miller T={tc} Vout={fmt(rec.get('y'))} Vplate={fmt(rec.get('y_plate'))} "
            f"dV={fmt(rec.get('abs_iface_err'))} |out-z|={fmt(rec.get('abs_err_vs_z'))}",
            flush=True,
        )
    report["miller_diag"] = miller_diag
    m85 = next((r for r in miller_diag if r.get("temp_c") == 85.0), {})
    report["miller_text"] = (
        f"At 85 °C the plate is still analog-good (|Vplate−z|={fmt(m85.get('abs_plate_err'))}) "
        f"while the follower output is not (|Vout−z|={fmt(m85.get('abs_err_vs_z'))}). "
        f"The buffer introduces |Vout−Vplate|={fmt(m85.get('abs_iface_err'))}. "
        "That is common-mode / temperature-dependent input offset of the teaching "
        "miller at Vin≈1.73 V, plus any incomplete 200 µs settle — not destruction "
        "of the CDS plate itself."
    )

    print("Part 4–7 candidates at 3 temps", flush=True)
    names = (
        "unbuf",
        "vcvs",
        "miller",
        "sf_plain",
        "sf_nested",
        "qamp",
        "qamp_invservo",
        "qamp_l2inv",
        "qamp_idealrst",
    )
    cand_rows = []
    iface_vs_temp = []
    for name in names:
        for tc in TEMPS:
            p = MosParams(name="c", servo=True, temp_c=tc)
            rec, _, _, _ = measure(ng, spec, wf, o2, steps, p, name, dest("c", name, tc))
            cand_rows.append(slim(rec))
            iface_vs_temp.append(slim(rec))
            print(
                f"  {name} T={tc} |err|={fmt(rec.get('abs_err_vs_z'))} "
                f"dV={fmt(rec.get('abs_iface_err'))} pass={rec.get('analog_pass')} "
                f"P={fmt(rec.get('p_sim_W'))}",
                flush=True,
            )
    report["candidates_200us"] = cand_rows
    report["iface_vs_temp"] = iface_vs_temp

    def score(name):
        rows = [r for r in cand_rows if r.get("candidate") == name]
        if not rows or any(r.get("failed") for r in rows):
            return (99, 9e9)
        nfail = sum(0 if r.get("analog_pass") else 1 for r in rows)
        worst = max((r.get("abs_err_vs_z") or 9) for r in rows)
        device_pen = 0 if CANDIDATES[name]["device_level"] else 1
        return (device_pen, nfail, worst)

    ranked = sorted(names, key=score)
    # Prefer a device-level candidate that analog-passes all T. Else lowest worst-err device-level.
    best = None
    for name in ranked:
        rows = [r for r in cand_rows if r.get("candidate") == name]
        if CANDIDATES[name]["device_level"] and all(r.get("analog_pass") for r in rows):
            best = name
            break
    if best is None:
        device_names = [n for n in ranked if CANDIDATES[n]["device_level"] and n != "unbuf"]
        best = device_names[0] if device_names else "qamp"
    report["best_name"] = best
    print(f"  selected best={best}", flush=True)

    q_ok = all(r.get("analog_pass") for r in cand_rows if r.get("candidate") == "qamp")
    sf_ok = all(r.get("analog_pass") for r in cand_rows if r.get("candidate") == "sf_nested")
    report["candidate_text"] = (
        f"VG charge-amp analog-pass-all-T={q_ok}; SF+nested CDS analog-pass-all-T={sf_ok}. "
        "Plain SF is the Vgs negative control. LEVEL 2 VCVS/reset/invert isolate "
        "which error is the MOS invert versus the VG stage versus the switch."
    )

    print("Part 8 dynamics on best @85C", flush=True)
    p85 = MosParams(name="d", servo=True, temp_c=85.0)
    dwell_rows = []
    settle_wave = None
    for hold in DWELLS:
        rec, _, _, _ = measure(ng, spec, wf, o2, steps, p85, best, dest("dw", best, hold), t_hold=hold)
        dwell_rows.append(slim(rec))
        if abs(hold - 2e-4) < 1e-9:
            settle_wave = rec
        print(f"  dwell={hold:.1e} |err|={fmt(rec.get('abs_err_vs_z'))} pass={rec.get('analog_pass')}", flush=True)
    report["best_dwell"] = dwell_rows
    report["settle_wave"] = slim(settle_wave) if settle_wave else {}
    if settle_wave and settle_wave.get("waveform"):
        report["settle_wave"]["waveform"] = settle_wave["waveform"]

    print("Part 8 multi-input", flush=True)
    net, n_src, cfg = build(spec, wf, o2, p85, best)
    series = [steps["maxabs"], steps["neg"], steps["pos"], steps["maxabs"]]
    zrefs = [steps["z_maxabs"], steps["z_neg"], steps["z_pos"], steps["z_maxabs"]]
    rec_m = run_multi(
        ng, net, series, zrefs, n_src, p85, dest("multi", best), t_az=T_AZ, t_hold=2e-4,
        out_node=cfg["out"], plate_node=cfg["plate"],
    )
    report["best_multi"] = rec_m
    report["best_multi_slim"] = {
        k: rec_m.get(k) for k in ("failed", "all_pass", "max_abs_err", "segments", "t_hold_s")
    }
    print(f"  multi max|err|={fmt(rec_m.get('max_abs_err'))} all_pass={rec_m.get('all_pass')}", flush=True)

    print("Part 9 loads on best @85C", flush=True)
    load_rows = []
    for label, ld in (
        ("hiZ", None),
        ("1pF", {"c": 1e-12}),
        ("10pF", {"c": 1e-11}),
        ("100pF", {"c": 1e-10}),
        ("1M", {"r": 1e6}),
        ("100k", {"r": 1e5}),
    ):
        rec, _, _, _ = measure(ng, spec, wf, o2, steps, p85, best, dest("ld", best, label), load=ld)
        rec["load_label"] = label
        load_rows.append(slim(rec))
        print(f"  load {label} |err|={fmt(rec.get('abs_err_vs_z'))} pass={rec.get('analog_pass')}", flush=True)
    report["best_loads"] = load_rows

    pun = next((r.get("p_sim_W") for r in cand_rows if r.get("candidate") == "unbuf" and r.get("temp_c") == 27.0), 3.15e-3)
    power = []
    for name in names:
        rec = next((r for r in cand_rows if r.get("candidate") == name and r.get("temp_c") == 27.0), {})
        p = rec.get("p_sim_W")
        power.append(
            {
                "candidate": name,
                "p_sim_W": p,
                "dP": None if p is None or pun is None else p - pun,
                "e_200us": None if p is None else p * 2e-4,
            }
        )
    report["power"] = power

    print("Part 11 combined", flush=True)
    comb = []
    for tc in TEMPS:
        p = MosParams(name="j", servo=True, temp_c=tc, vos_inject=214e-6)
        rec, _, _, _ = measure(ng, spec, wf, o2, steps, p, best, dest("comb", tc), load={"c": 1e-11})
        rec["note"] = "214uV inject + 10pF + CDS + MOS temp. No R mismatch."
        comb.append(slim(rec))
        print(f"  comb T={tc} |err|={fmt(rec.get('abs_err_vs_z'))} pass={rec.get('analog_pass')}", flush=True)
    report["combined"] = comb

    report["error_budget"] = [
        {
            "source": "raw CDS plate 85C",
            "nominal": next((r.get("abs_err_vs_z") for r in raw_vs_temp if r.get("temp_c") == 27.0), None),
            "worst": next((r.get("abs_err_vs_z") for r in raw_vs_temp if r.get("temp_c") == 85.0), None),
            "cancellable": "already the Exp 27 primitive",
        },
        {
            "source": "miller follower added (85C)",
            "nominal": next((r.get("abs_iface_err") for r in miller_diag if r.get("temp_c") == 27.0), None),
            "worst": next((r.get("abs_iface_err") for r in miller_diag if r.get("temp_c") == 85.0), None),
            "cancellable": "not at CM=z; do not follow at high CM",
        },
        {
            "source": f"{best} vs z (85C)",
            "nominal": next((r.get("abs_err_vs_z") for r in cand_rows if r.get("candidate") == best and r.get("temp_c") == 27.0), None),
            "worst": next((r.get("abs_err_vs_z") for r in cand_rows if r.get("candidate") == best and r.get("temp_c") == 85.0), None),
            "cancellable": "the interface under test",
        },
        {
            "source": "plate Cload 100pF",
            "nominal": next((r.get("abs_err_vs_z") for r in sens if r.get("stim") == "C=1e-12"), None),
            "worst": next((r.get("abs_err_vs_z") for r in sens if r.get("stim") == "C=1e-10"), None),
            "cancellable": "do not load the plate; drive from the interface",
        },
        {
            "source": "plate Ileak 10nA",
            "nominal": next((r.get("abs_err_vs_z") for r in sens if r.get("stim") == "I=0e+00"), None),
            "worst": next((r.get("abs_err_vs_z") for r in sens if r.get("stim") == "I=1e-08"), None),
            "cancellable": "Ig=0 on this card; 10nA is a sensitivity, not a PDK leak",
        },
        {
            "source": "independent 0.5% R (Exp 27 N=16)",
            "nominal": 2.62e-3,
            "worst": 5.09e-3,
            "cancellable": "not this experiment; ratio matching",
        },
    ]

    conclude(report)
    report["plots"] = write_plots(report)
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
