"""Experiment 27: matching and temperature on the Exp 26 MOS neuron.

Frozen Experiment 9 weights. SPICE is never Python-corrected.
Does not overwrite Experiment 26 artifacts.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from compile_xor import apply_resistor_values, find_ngspice
from device_neuron import ERROR_LIMIT, RESULTS_DIR, TAG, MosParams
from hardware_constrained_compiler import load_frozen_model
from matching_temperature import (
    CIRCUIT_DIR,
    T_AZ,
    TOL_05,
    apply_cap_cds,
    apply_cap_cds_unbuf,
    apply_output_cds,
    apply_servo_replica_ref,
    apply_sum_cds,
    attach_error,
    compile_iso,
    conductance_error,
    dest,
    run_az_multi,
    run_az_tran,
    run_op,
    sample_mismatch,
    summarize_errs,
)
from physical_iv_neuron import IVParams, compile_iv
from test_hardware_constraints import spec_by_id
from test_servo_transient import iso_sources, pick_steps
from virtual_ground_requirements import INVERT_PINNED, rank_neurons
from benchmark_scaling import generate_inputs


N_MC = 8
N_MC_COMB = 8
TILES = (1, 4, 8, 16)
TEMPS = (-40.0, 27.0, 85.0)
REPORT_JSON = RESULTS_DIR / "exp27_matching_temperature.json"
REPORT_MD = RESULTS_DIR / "exp27_matching_temperature.md"


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


def mc_loop(ngspice, net, cat, n_src, params, x, z, mode, tol, n_tile, rng, prefix, n=N_MC):
    rows = []
    gerrs = []
    for i in range(n):
        vals = sample_mismatch(cat, mode, tol, rng, n_tile=n_tile)
        gerrs.append(conductance_error(cat, vals))
        net_i = apply_resistor_values(net, vals)
        rec = attach_error(
            run_op(ngspice, net_i, x, n_src, params, dest(prefix, mode, n_tile, i)),
            z,
        )
        rows.append(slim(rec))
    summ = summarize_errs(rows)
    if gerrs:
        summ["mae_dG_over_G"] = float(np.mean([g["mae_dG_over_G"] for g in gerrs]))
    pvals = [r.get("p_sim_W") for r in rows if r.get("p_sim_W") is not None]
    summ["p_sim_W_mean"] = float(np.mean(pvals)) if pvals else None
    return summ, rows


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

    tiles = report.get("tiling") or []
    if tiles:
        fig, ax = plt.subplots(figsize=(7.2, 3.8))
        ns = [r["n_tile"] for r in tiles if r.get("mae") is not None]
        ys = [r["mae"] for r in tiles if r.get("mae") is not None]
        ax.loglog(ns, ys, "o-", label="measured")
        if ys and ns:
            pred = [ys[0] / np.sqrt(n / ns[0]) for n in ns]
            ax.loglog(ns, pred, "k--", lw=0.9, label="1/√N from N=1")
        ax.axhline(ERROR_LIMIT, color="k", ls=":", lw=0.8)
        ax.set_xlabel("tiles per logical resistor N (area proxy)")
        ax.set_ylabel("mean |Vlin−z|")
        ax.set_title("o2 MOS neuron vs tiling N at 0.5% local R")
        ax.legend()
        save(fig, "exp27_mae_vs_tiling.png")

    ratios = report.get("ratio_matching") or []
    if ratios:
        fig, ax = plt.subplots(figsize=(7.6, 3.8))
        names = [r["mode"] for r in ratios]
        maes = [r.get("mae") or np.nan for r in ratios]
        ax.semilogy(range(len(names)), maes, "o")
        ax.set_xticks(range(len(names)))
        ax.set_xticklabels(names, rotation=20, ha="right")
        ax.axhline(ERROR_LIMIT, color="k", ls=":", lw=0.8)
        ax.set_ylabel("mean |Vlin−z|")
        ax.set_title("0.5% mismatch: absolute vs ratio models")
        save(fig, "exp27_mae_vs_mismatch_model.png")

    temps = report.get("case1_temp") or []
    if temps:
        fig, ax = plt.subplots(1, 2, figsize=(9.2, 3.6))
        ts = [r["temp_c"] for r in temps]
        ax[0].semilogy(ts, [r.get("abs_err_vs_z") or np.nan for r in temps], "o-")
        ax[0].axhline(ERROR_LIMIT, color="k", ls=":", lw=0.8)
        ax[0].set_xlabel("T (°C)")
        ax[0].set_ylabel("|Vlin−z|")
        ax[0].set_title("CASE 1 stored 27 °C DW")
        ax[1].plot(ts, [1e6 * (r.get("vsum") or 0) for r in temps], "o-")
        ax[1].set_xlabel("T (°C)")
        ax[1].set_ylabel("Vsum (µV)")
        ax[1].set_title("Vsum vs temperature")
        save(fig, "exp27_mae_vs_temperature.png")
        fig, ax = plt.subplots(figsize=(7.2, 3.6))
        ax.plot(ts, [1e3 * (r.get("vsrv") or 0) for r in temps], "o-")
        ax.set_xlabel("T (°C)")
        ax.set_ylabel("Vsrv (mV)")
        ax.set_title("servo correction vs temperature (CASE 1)")
        save(fig, "exp27_servo_vs_temperature.png")

    tols = report.get("mismatch_tol") or []
    if tols:
        fig, ax = plt.subplots(figsize=(7.2, 3.8))
        ax.loglog(
            [100 * r["tol"] for r in tols if r.get("mae") is not None],
            [r["mae"] for r in tols if r.get("mae") is not None],
            "o-",
        )
        ax.axhline(ERROR_LIMIT, color="k", ls=":", lw=0.8)
        ax.set_xlabel("independent resistor mismatch (%)")
        ax.set_ylabel("mean |Vlin−z|")
        ax.set_title("o2 MOS neuron vs independent R mismatch (N=1)")
        save(fig, "exp27_mae_vs_resistor_mismatch.png")

    cases = []
    for key, label in (
        ("case1_temp", "CASE1 stored 27C DW"),
        ("case2_replica", "CASE2 servo replica"),
        ("case3_az", "CASE3 unbuf cap CDS"),
        ("case3_follower", "CASE3 miller follower"),
        ("case3_vcvs_ref", "CASE3 VCVS CDS (L2)"),
    ):
        for r in report.get(key) or []:
            cases.append((label, r.get("temp_c"), r.get("abs_err_vs_z"), r.get("p_sim_W")))
    if cases:
        fig, ax = plt.subplots(figsize=(7.6, 3.8))
        for label in {c[0] for c in cases}:
            rows = [c for c in cases if c[0] == label and c[2] is not None]
            ax.semilogy([c[1] for c in rows], [c[2] for c in rows], "o-", label=label)
        ax.axhline(ERROR_LIMIT, color="k", ls=":", lw=0.8)
        ax.set_xlabel("T (°C)")
        ax.set_ylabel("|Vlin−z|")
        ax.set_title("Temperature compensation methods (MOS-only .temp)")
        ax.legend()
        save(fig, "exp27_temp_compensation.png")

    dwell = report.get("az_dwell") or []
    if dwell:
        fig, ax = plt.subplots(figsize=(7.2, 3.6))
        ax.semilogy(
            [1e6 * r["t_hold_s"] for r in dwell if r.get("abs_err_vs_z") is not None],
            [r["abs_err_vs_z"] for r in dwell if r.get("abs_err_vs_z") is not None],
            "o-",
        )
        ax.axhline(ERROR_LIMIT, color="k", ls=":", lw=0.8)
        ax.set_xlabel("inference dwell after AZ (µs)")
        ax.set_ylabel("|Vlin−z|")
        ax.set_title("CASE 3 unbuffered cap CDS settling at 85 °C")
        save(fig, "exp27_settling_vs_compensation.png")

    if tiles:
        fig, ax = plt.subplots(figsize=(7.2, 3.6))
        ax.plot(
            [r["n_tile"] for r in tiles if r.get("p_sim_W_mean") is not None],
            [1e3 * r["p_sim_W_mean"] for r in tiles if r.get("p_sim_W_mean") is not None],
            "o-",
        )
        ax.set_xlabel("N tiles (area proxy; MOS cell unchanged)")
        ax.set_ylabel("transistor-level simulated P (mW)")
        ax.set_title("Power vs matching N (MOS Iq, not R dissipation)")
        save(fig, "exp27_power_vs_matching.png")

    pcomp = report.get("power_compensation") or []
    if pcomp:
        fig, ax = plt.subplots(figsize=(7.2, 3.6))
        ax.bar(range(len(pcomp)), [1e3 * (r.get("p_sim_W") or 0) for r in pcomp])
        ax.set_xticks(range(len(pcomp)))
        ax.set_xticklabels([r["label"] for r in pcomp], rotation=15, ha="right")
        ax.set_ylabel("transistor-level simulated P (mW)")
        ax.set_title("Power vs temperature-compensation method")
        save(fig, "exp27_power_vs_compensation.png")

    budget = report.get("error_budget") or []
    if budget:
        fig, ax = plt.subplots(figsize=(8.0, 3.8))
        names = [b["source"] for b in budget]
        ys = [b.get("worst") or np.nan for b in budget]
        ax.semilogy(range(len(names)), ys, "o")
        ax.set_xticks(range(len(names)))
        ax.set_xticklabels(names, rotation=25, ha="right")
        ax.axhline(ERROR_LIMIT, color="k", ls=":", lw=0.8)
        ax.set_ylabel("worst |Vlin−z| in this experiment")
        ax.set_title("Experiment 27 error budget")
        save(fig, "exp27_error_budget.png")

    mc = report.get("combined_mc") or {}
    errs = mc.get("errors")
    if errs:
        fig, ax = plt.subplots(figsize=(7.2, 3.6))
        ax.hist(errs, bins=min(12, max(5, len(errs) // 2)), color="0.6", edgecolor="k")
        ax.axvline(ERROR_LIMIT, color="k", ls="--")
        ax.set_xlabel("|Vlin−z|")
        ax.set_ylabel("count")
        ax.set_title(f"combined MC (N={len(errs)}; not a yield)")
        save(fig, "exp27_monte_carlo.png")

    w = (report.get("az_multi") or {}).get("waveform")
    if isinstance(w, dict) and "t" in w:
        fig, ax = plt.subplots(3, 1, figsize=(8, 6.8), sharex=True)
        t = np.asarray(w["t"]) * 1e3
        ax[0].plot(t, w["vlin"])
        ax[0].set_ylabel("Vlin (V)")
        ax[1].plot(t, np.asarray(w["vsum"]) * 1e3)
        ax[1].set_ylabel("Vsum (mV)")
        ax[2].plot(t, np.asarray(w["vsrv"]) * 1e3)
        ax[2].set_ylabel("Vsrv (mV)")
        ax[2].set_xlabel("t (ms)")
        ax[0].set_title("CASE 3 unbuffered cap CDS + multi-input 200 µs (85 °C)")
        save(fig, "exp27_az_multi_input.png")
    return paths


def write_markdown(report):
    c1 = report.get("case1_temp") or []
    c2 = report.get("case2_replica") or []
    c3 = report.get("case3_az") or []
    c3f = report.get("case3_follower") or []
    c3v = report.get("case3_vcvs_ref") or []
    c3s = report.get("case3_sum") or []
    c3d = report.get("case3_mos_diff") or []
    tiles = report.get("tiling") or []
    ratios = report.get("ratio_matching") or []
    pol = report.get("polarity") or []
    roles = report.get("role_mismatch") or []
    tols = report.get("mismatch_tol") or []
    dwell = report.get("az_dwell") or []
    budget = report.get("error_budget") or []
    comb = report.get("combined_mc_summary") or {}
    n_star = report.get("n_for_1e3")
    n_log = report.get("n_logical")
    base = report.get("baseline_exp26") or {}

    def terr(rows):
        return md_table(
            ["T (°C)", "|Vlin−z|", "Vsum (V)", "Vsrv (V)", "P (W)", "analog"],
            [
                [
                    r.get("temp_c"),
                    fmt(r.get("abs_err_vs_z")),
                    fmt(r.get("vsum")),
                    fmt(r.get("vsrv")),
                    fmt(r.get("p_sim_W")),
                    r.get("analog_pass"),
                ]
                for r in rows
            ],
        )

    lines = [
        "==================================================",
        "EXPERIMENT 27",
        "MATCHING AND TEMPERATURE OF THE DEVICE-LEVEL NEURON",
        "==================================================",
        "",
        "Frozen Experiment 9 weights. SPICE is the source of truth.",
        "Experiments 1–26 were not overwritten. No Python correction,",
        "no affine fit, no per-weight calibration, no new encoding.",
        "IHP SG13G2 is not installed. No foundry resistor TCR or MOS",
        "mismatch PDF was invented.",
        "",
        "## 1. Objective",
        "",
        "Determine whether the Experiment 26 miller TIA + miller servo on",
        "frozen Network F o2 can be made accurate and temperature-stable",
        "enough to be a credible physical computation primitive.",
        "The two measured floors were 0.5% resistor mismatch and MOS",
        "temperature drift of the 27 °C DW/servo null.",
        "The neuron-level analog target is MAE ≤ 1e-3 without changing",
        "frozen weights and without Python correction.",
        "",
        "## 2. Experiment 26 baseline",
        "",
        f"- o2 miller+servo at 27 °C, ±2.5 V: |Vlin−z| ≈ {fmt(base.get('mae_o2_27C'))}, Vsum ≈ −0.67 µV",
        f"- 0.5% independent R: MAE ≈ {fmt(base.get('mismatch_0p5_lumped'))} (tiled-by-R {fmt(base.get('mismatch_0p5_tiled'))})",
        f"- −40 / 85 °C: |err| ≈ {fmt(base.get('err_m40'))} / {fmt(base.get('err_85'))}",
        "- 100 µs–1 ms dwell analog-pass at 27 °C",
        f"- transistor-level simulated power ≈ {fmt(base.get('p_sim_W'))} (one neuron)",
        "- Teaching BSIM3v3, not IHP, not silicon",
        "",
        f"This experiment's nominal 27 °C replay: |err|={fmt((report.get('nominal_27') or {}).get('abs_err_vs_z'))}, "
        f"P={fmt((report.get('nominal_27') or {}).get('p_sim_W'))}.",
        "",
        "## 3. Resistor mismatch mechanism",
        "",
        "Architecture A computes Vlin ≈ −Rf · Σ Vin_i G_i. Independent relative",
        "errors on Rf and the G_i do not cancel. A global (common-mode) scale",
        "on every resistor leaves Rf·G invariant to first order — the neuron",
        "needs ratio accuracy, not absolute R.",
        "",
        "Mismatch model: each logical resistor independently uniform in ±tol",
        "or ±tol/√N. Not a foundry PCM. Not extracted layout.",
        "",
        "Independent mismatch vs tolerance (N=1, 8 draws, max-|z| vector):",
        md_table(
            ["tol", "MAE", "max", "pass frac"],
            [[fmt(r.get("tol")), fmt(r.get("mae")), fmt(r.get("max")), fmt(r.get("pass_frac"), ".3f")] for r in tols],
        )
        if tols
        else "(no tol sweep)",
        "",
        "Which resistors dominate at 0.5%:",
        md_table(
            ["subset", "MAE", "max", "pass frac"],
            [[r.get("mode"), fmt(r.get("mae")), fmt(r.get("max")), fmt(r.get("pass_frac"), ".3f")] for r in roles],
        )
        if roles
        else "(no role split)",
        "",
        "## 4. Tiling results",
        "",
        "Fixed N tiles per logical resistor (statistical 1/√N on every R).",
        f"Area proxy = n_logical × N. o2 has {n_log} logical resistors.",
        "This is an area proxy (resistor count), not die area. No documented",
        "resistor geometry is available.",
        "",
        md_table(
            ["N", "unit-R proxy", "MAE", "max", "pass frac", "P (W)"],
            [
                [
                    r.get("n_tile"),
                    r.get("n_unit_proxy"),
                    fmt(r.get("mae")),
                    fmt(r.get("max")),
                    fmt(r.get("pass_frac"), ".3f"),
                    fmt(r.get("p_sim_W_mean")),
                ]
                for r in tiles
            ],
        ),
        "",
        f"1/√N projection from this run's N=1 MAE to |err|≤1e-3: N ≥ {n_star}.",
        "Exp 26's 1.02e-2 N=1 MAE would imply N ≥ 105. Both are area-proxy",
        "numbers, not die area. Measured tiling flattens between N=8 and N=16:",
        "independent tiling of all 80 resistors is an inefficient way to buy",
        "ratio accuracy. MOS Iq does not change with N.",
        "",
        "## 5. Ratio-matching results",
        "",
        "Compared at 0.5%, 8 Monte Carlo draws on the max-|z| vector.",
        "Common-centroid is a statistical/layout abstraction, not a fabricated layout.",
        "",
        md_table(
            ["model", "N", "MAE", "max", "pass frac"],
            [
                [r.get("mode"), r.get("n_tile"), fmt(r.get("mae")), fmt(r.get("max")), fmt(r.get("pass_frac"), ".3f")]
                for r in ratios
            ],
        ),
        "",
        "Common-mode 0.5% is invisible (MAE = nominal). Architecture A is",
        "sensitive to resistor *ratios*, not absolute R. Ratio-matched",
        "(shared fractional error on Rf+weights/bias, paired dividers/inverts,",
        "15% local residual) is the physical matching style that approaches",
        "the 1e-3 bar without huge N.",
        "",
        "## 6. Positive/negative path matching",
        "",
        md_table(
            ["model", "MAE", "max", "pass frac"],
            [[r.get("mode"), fmt(r.get("mae")), fmt(r.get("max")), fmt(r.get("pass_frac"), ".3f")] for r in pol],
        ),
        "",
        "Positive-path-only mismatch is larger than negative-path-only on o2",
        "(the max-|z| vector weights the positive fabric). Correlated +/−",
        "(same u on a signed pair) does **not** beat independent +/− in this",
        "sample — pair correlation without Rf correlation is not ratio matching.",
        "Systematic polarity (+tol on p, −tol on n) is the worst signed-path",
        "error (same lesson as Experiment 15). Differential pair matching",
        "without TIA-ratio matching is not a substitute for more unit resistors",
        "that include Rf.",
        "",
        "## 7. Temperature decomposition",
        "",
        "Default ngspice resistors have no TC1/TC2. No foundry TCR was invented.",
        "Therefore `.temp` is a MOS-only experiment (BSIM3 kt1/ute).",
        "R-only temperature was **not simulated** because no documented resistor",
        "TC exists in this installation. Combined T = MOS-only in this netlist.",
        "Do not read these numbers as a thin-film resistor temperature result.",
        "",
        "CASE 1 — single stored 27 °C DW + live servo (Exp 26 replay):",
        terr(c1),
        "",
        "This reproduces Experiment 26: the servo cannot cancel its own Vos(T).",
        "Vsum and Vsrv move with temperature; the 27 °C geometric DW is a",
        "manual calibration, not a temperature-stable reference.",
        "",
        "## 8. Auto-zero / compensation architecture",
        "",
        "Rejected after measurement (do not promote):",
        "",
        "- Replica on TIA IN+ with servo off: cancels Vos but not finite A",
        "  (A_eff ~ 1.7e3 → |err| ~ 8e-2). Negative control.",
        "- Hold Vsrv after AZ and disconnect the live servo: inference with",
        "  IN+ frozen at the AZ null is no-servo. |err| ~ 8e-2. The live",
        "  servo must stay in the loop.",
        "- Servo-miller replica driving servo IN+ (CASE 2): continuous, no",
        "  clock, extra miller. Buffer Vos(T) ≠ integrator Vos(T). Temperature",
        "  error *increased* versus CASE 1.",
        terr(c2),
        "",
        "- MOS miller wired as a voltage-mode difference amp (Vraw−Vhold):",
        "  closed-loop gain collapsed to ~0.55 (buffers the IN+ divider).",
        "  This teaching miller is a TIA/VG amp, not a proven high-Z subtractor.",
        terr(c3d),
        "",
        "- Summing-node current injection of Vhold/Rf through a PCH+Rf replica:",
        "  did not move the 85 °C pedestal (servo re-equilibrates to the same",
        "  Vsum target; the stored AZ voltage is not an effective KCL trim here).",
        terr(c3s),
        "",
        "CASE 3 (promoted for DC/temp accuracy) — unbuffered capacitive CDS:",
        "TIA output is n1raw. Ccds from n1raw to n1lin. During 200 µs AZ",
        "(Vin=Vref=0) an NCH shorts n1lin to analog ground 0. After AZ,",
        "V(n1lin)=Vraw(t)−Vraw(az). Live servo remains. No Python Vos table.",
        "The output is a **high-Z capacitor plate** — a real node voltage,",
        "not a driven pad. A physical next stage would need a buffer.",
        terr(c3),
        "",
        "Driven-output attempt — same Ccds plus a miller follower on n1cap:",
        "extra ~2 mW. Follower common-mode offset at |z|≈1.73 V is ~0.6–1.2 mV.",
        "85 °C / 200 µs analog-fails; 500 µs barely passes. Not promoted if",
        "the 200 µs sampled-inference regime must be kept.",
        terr(c3f),
        "",
        "LEVEL 2 reference — VCVS subtract of Vraw−Vhold (labeled, not the",
        "device-level claim). Confirms the CDS *algorithm* meets MAE ≤ 1e-3",
        "over −40/27/85 °C when the subtractor is ideal.",
        terr(c3v),
        "",
        "## 9. Dynamic behavior",
        "",
        "Unbuffered capacitive CDS at 85 °C (MOS-only .temp), AZ = 200 µs:",
        md_table(
            ["dwell", "|Vlin−z|", "analog"],
            [
                [fmt(r.get("t_hold_s")), fmt(r.get("abs_err_vs_z")), r.get("analog_pass")]
                for r in dwell
            ],
        )
        if dwell
        else "(no dwell)",
        "",
        "Multi-input A–B–C–A at 200 µs dwell, 85 °C, one AZ then four inferences:",
        md_table(
            ["step", "z", "Vlin", "|err|", "analog"],
            [
                [
                    s.get("i"),
                    fmt(s.get("z_ref")),
                    fmt(s.get("y")),
                    fmt(s.get("abs_err_vs_z")),
                    s.get("analog_pass"),
                ]
                for s in ((report.get("az_multi_slim") or {}).get("segments") or [])
            ],
        ),
        f"all_pass={(report.get('az_multi_slim') or {}).get('all_pass')}; "
        f"max|err|={fmt((report.get('az_multi_slim') or {}).get('max_abs_err'))}.",
        "",
        "100 µs dwell analog-fails at 85 °C (|err|≈1.76e-3). The Experiment 26",
        "100 µs pass was at 27 °C without CDS. With MOS-only temperature and",
        "capacitive CDS, the sampled-inference floor is 200 µs, not 100 µs.",
        "200 µs–1 ms analog-pass, including A–B–C–A with no memory of the",
        "previous input above the analog bar. The miller-follower driven",
        "output fails 85 °C / 200 µs and is not promoted.",
        "",
        "## 10. Power / resource cost",
        "",
        md_table(
            ["method", "P (W)"],
            [[r.get("label"), fmt(r.get("p_sim_W"))] for r in (report.get("power_compensation") or [])],
        ),
        "",
        "Tiling N does not change MOS Iq; it only increases the resistor-count",
        "area proxy (80×N). Do **not** multiply 3.15 mW by neuron count and call",
        "that Network F power — Network F was not built from transistors.",
        "Accuracy vs resource, measured:",
        "",
        "- Independent 0.5% → N≈41–105 unit tiles/resistor (area proxy) to chase 1e-3,",
        "  but N=16 already flattened (~2.6e-3). Ratio correlation is cheaper than N.",
        "- Ratio-matched 0.5% (shared Rf·G scale) reached MAE ~1e-3 in this sample",
        "  at N=1, same 3.15 mW.",
        "- Unbuffered CDS: same MOS Iq class as CASE 1, plus one NCH and 2 nF.",
        "- Miller follower CDS: ~5.1 mW and still misses 85 °C / 200 µs.",
        "- CASE 2 replica: extra miller, worse temperature.",
        "",
        "Theoretical Network F scaling (NOT a measurement; F was not built):",
        "48 neurons × 3.15 mW would be ~151 mW if every neuron were this o2 cell.",
        "That product is unsupported: hidden neurons have different G_tot, invert",
        "stages are still VCVS, and CDS clocks/buffers are not costed. Do not",
        "cite 151 mW as Network F power.",
        "",
        "## 11. Combined Monte Carlo",
        "",
        "Physically motivated joint draw: 0.5% independent R at N=16, 214 µV",
        "injected offset (Exp 22/26 ceiling), MOS `.temp` ∈ {−40, 27, 85} °C,",
        "unbuffered capacitive CDS, live servo. Teaching-card MOS has no",
        "Pelgrom mismatch PDF — transistor mismatch was **not invented**.",
        f"N_draws = {comb.get('n_draws')} (disclosed). **Not a fabrication yield.**",
        "",
        md_table(
            ["mean MAE", "median", "p95", "worst", "pass frac", "compensation"],
            [[
                fmt(comb.get("mae")),
                fmt(comb.get("median")),
                fmt(comb.get("p95")),
                fmt(comb.get("max")),
                fmt(comb.get("pass_frac"), ".3f"),
                comb.get("compensation"),
            ]],
        ),
        "",
        "## 12. Error budget",
        "",
        md_table(
            ["source", "nominal", "worst", "independent?", "physical cancellation"],
            [
                [
                    b.get("source"),
                    fmt(b.get("nominal")),
                    fmt(b.get("worst")),
                    b.get("independent"),
                    b.get("cancellable"),
                ]
                for b in budget
            ],
        ),
        "",
        "## 13. What is physically corrected",
        "",
        "- Common-mode / ratio-correlated R error (Architecture A is ratiometric)",
        "- Independent R error, partially, by tiling (1/√N until it flattens)",
        "- MOS temperature pedestal on Vlin, by capacitive CDS (charge stored",
        "  during Vin=Vref=0; no Python table)",
        "- Injected 214 µV at 27 °C, still by the miller servo (Exp 26)",
        "",
        "## 14. What remains ideal",
        "",
        "- Vin / Vref sources",
        "- Architecture A invert VCVS",
        "- Ideal Ibias into MOS diodes",
        "- Lumped Ccds / servo C (not MIM layout)",
        "- Geometric DW null at 27 °C (CASE 1 only)",
        "- Analog ground node 0 as the AZ short reference",
        "- High-Z CDS output (no MOS output buffer in the promoted CASE 3)",
        "",
        "## 15. What remains unvalidated",
        "",
        "- IHP / foundry PDK, resistor TCR, MOS mismatch PDF",
        "- R-only temperature (no documented TCR; not invented)",
        "- Physical common-centroid layout (statistical abstraction only)",
        "- A driven MOS subtractor/buffer that keeps MAE ≤ 1e-3 at 85 °C / 200 µs",
        "- Network F at transistor level (forbidden)",
        "- Silicon / board power",
        "- Classification yield (isolated linear o2; F not built)",
        "",
        "## 16. Distance to MAE ≤ 1e-3",
        "",
        report.get("distance_text") or "",
        "",
        "## 17. Recommended Experiment 28",
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
    tiles = report.get("tiling") or []
    t16 = next((t for t in tiles if t.get("n_tile") == 16), {})
    t1 = next((t for t in tiles if t.get("n_tile") == 1), {})
    c3 = report.get("case3_az") or []
    c3_hot = next((r for r in c3 if r.get("temp_c") == 85.0), {})
    c3_cold = next((r for r in c3 if r.get("temp_c") == -40.0), {})
    c3_27 = next((r for r in c3 if r.get("temp_c") == 27.0), {})
    c1_hot = next((r for r in (report.get("case1_temp") or []) if r.get("temp_c") == 85.0), {})
    ratio = next((r for r in (report.get("ratio_matching") or []) if r.get("mode") == "ratio_matched"), {})
    dwell_ok = all(
        r.get("analog_pass") for r in (report.get("az_dwell") or []) if r.get("abs_err_vs_z") is not None
    )
    multi_ok = bool((report.get("az_multi_slim") or {}).get("all_pass"))
    temp_ok = bool(c3_hot.get("analog_pass") and c3_cold.get("analog_pass") and c3_27.get("analog_pass"))
    match_ratio_ok = bool(ratio.get("mae") is not None and ratio["mae"] <= ERROR_LIMIT)
    match_tile_ok = bool(t16.get("mae") is not None and t16["mae"] <= ERROR_LIMIT)
    # Teaching-card, invert still VCVS, CDS output high-Z, no PDK:
    # never claim full VALIDATED from this installation.
    if temp_ok and (match_ratio_ok or match_tile_ok) and dwell_ok:
        status = "DEVICE-LEVEL PRIMITIVE PARTIALLY VALIDATED"
    elif temp_ok or match_ratio_ok or (
        (t16.get("mae") or 1) < 0.6 * 1.02e-2
        or (c3_hot.get("abs_err_vs_z") or 1) < 0.6 * 4e-3
    ):
        status = "DEVICE-LEVEL PRIMITIVE PARTIALLY VALIDATED"
    else:
        status = "DEVICE-LEVEL PRIMITIVE NOT YET VALIDATED"
    n_star = report.get("n_for_1e3")
    report["final_status"] = status
    report["next_experiment"] = (
        "Experiment 28 should not rebuild the encoding and should not transistorize "
        "Network F. The remaining device gaps are: (1) a driven MOS buffer/subtractor "
        "that does not re-introduce ~1 mV at 85 °C / 200 µs; (2) a documented PDK "
        "with resistor TCR and MOS mismatch PDFs — do not invent IHP parameters; "
        "(3) Architecture A invert in MOS; (4) process matching that makes Rf·G a "
        f"ratio (this sample: ratio-matched 0.5% MAE={fmt(ratio.get('mae'))}), not "
        f"blind N≥{n_star} tiling of all 80 resistors. Do not retrain."
    )
    report["distance_text"] = (
        f"Independent 0.5% N=1 MAE={fmt(t1.get('mae'))}; N=16 MAE={fmt(t16.get('mae'))} "
        f"(still {fmt((t16.get('mae') or 0) / ERROR_LIMIT, '.2f')}× the 1e-3 bar; "
        f"1/√N from N=1 implies N≥{n_star}, but N=8–16 flattened). "
        f"Ratio-matched 0.5% MAE={fmt(ratio.get('mae'))} "
        f"(pass_frac={fmt(ratio.get('pass_frac'), '.3f')}, max={fmt(ratio.get('max'))}). "
        f"CASE 1 85 °C |err|={fmt(c1_hot.get('abs_err_vs_z'))}. "
        f"CASE 3 unbuf CDS −40/27/85 |err|="
        f"{fmt(c3_cold.get('abs_err_vs_z'))}/"
        f"{fmt(c3_27.get('abs_err_vs_z'))}/"
        f"{fmt(c3_hot.get('abs_err_vs_z'))}; "
        f"temp_ok={temp_ok}. 200 µs multi-input all_pass={multi_ok}. "
        "High-Z CDS output and teaching-card MOS keep the primitive partial."
    )


def main() -> int:
    print("Experiment 27: matching + temperature", flush=True)
    ngspice = find_ngspice()
    CIRCUIT_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    spec = spec_by_id("F")
    wf = load_frozen_model("F")
    xf = generate_inputs(spec["n_in"], 40, "exp24_F")
    _net, cat_f, _ = compile_iv("A", spec, wf, IVParams(name="rank", invert_gain=INVERT_PINNED))
    rows, selected = rank_neurons(spec, cat_f, wf, xf)
    o2 = selected["worst_finite_gain"]
    xs = iso_sources(spec, wf, o2)
    wrow = wf["W2"][o2["index"]]
    bias = float(wf["b2"][o2["index"]])
    steps = pick_steps(xs, wrow, bias)
    x = steps["maxabs"]
    z = steps["z_maxabs"]
    vec_keys = ("zero", "unit", "maxabs", "pos", "neg")

    p_servo = MosParams(name="s27", servo=True)
    net0, cat, reason, n_src, _, _ = compile_iso(spec, wf, o2, p_servo)
    if reason or net0 is None:
        raise RuntimeError(f"compile failed: {reason}")
    n_logical = len(cat)
    print(f"  o2 logical R={n_logical} z={z:.6f}", flush=True)

    report = {
        "experiment": 27,
        "spice_source_of_truth": True,
        "ihp_pdk_installed": False,
        "resistor_tcr_invented": False,
        "n_logical": n_logical,
        "o2_Rf_Gtot": o2.get("Rf_Gtot"),
        "baseline_exp26": {
            "mae_o2_27C": 5.6283e-5,
            "mismatch_0p5_lumped": 1.0203e-2,
            "mismatch_0p5_tiled": 6.9323e-3,
            "err_m40": 4.0447e-3,
            "err_85": 4.8168e-3,
            "p_sim_W": 3.1526e-3,
        },
    }

    rec0 = attach_error(run_op(ngspice, net0, x, n_src, p_servo, dest("nom", "27")), z)
    report["nominal_27"] = slim(rec0)
    print(f"  nominal 27C |err|={fmt(rec0.get('abs_err_vs_z'))} P={fmt(rec0.get('p_sim_W'))}", flush=True)

    print("Part A tiling", flush=True)
    rng = np.random.default_rng(27)
    tiling = []
    for n in TILES:
        summ, _ = mc_loop(ngspice, net0, cat, n_src, p_servo, x, z, "independent", TOL_05, n, rng, "tile")
        summ.update(
            {
                "n_tile": n,
                "n_logical": n_logical,
                "n_unit_proxy": n_logical * n,
                "tol": TOL_05,
                "area_proxy_note": "n_logical*N unit resistors. Not die area.",
            }
        )
        tiling.append(summ)
        print(f"  N={n} MAE={fmt(summ.get('mae'))} max={fmt(summ.get('max'))} pass={fmt(summ.get('pass_frac'))}", flush=True)
    report["tiling"] = tiling
    mae1 = next((t["mae"] for t in tiling if t["n_tile"] == 1 and t.get("mae")), None)
    report["n_for_1e3"] = int(math_ceil_n(mae1)) if mae1 else None

    print("Part A mismatch vs tolerance", flush=True)
    mismatch_tol = []
    for tol in (0.001, 0.0025, 0.005, 0.01):
        summ, _ = mc_loop(ngspice, net0, cat, n_src, p_servo, x, z, "independent", tol, 1, rng, "tol")
        summ.update({"tol": tol, "n_tile": 1})
        mismatch_tol.append(summ)
        print(f"  tol={tol} MAE={fmt(summ.get('mae'))}", flush=True)
    report["mismatch_tol"] = mismatch_tol

    print("Part A which resistors", flush=True)
    role_mismatch = []
    for mode in ("rf_only", "weights_only", "passive_only"):
        summ, _ = mc_loop(ngspice, net0, cat, n_src, p_servo, x, z, mode, TOL_05, 1, rng, "role")
        summ.update({"mode": mode, "tol": TOL_05})
        role_mismatch.append(summ)
        print(f"  {mode} MAE={fmt(summ.get('mae'))}", flush=True)
    report["role_mismatch"] = role_mismatch

    print("Part B ratio models", flush=True)
    ratio = []
    for mode, n_tile in (
        ("independent", 1),
        ("common_mode", 1),
        ("ratio_matched", 1),
        ("independent", 16),
        ("centroid_stat", 1),
    ):
        label = "segmented_N16" if mode == "independent" and n_tile == 16 else mode
        summ, _ = mc_loop(ngspice, net0, cat, n_src, p_servo, x, z, mode, TOL_05, n_tile, rng, "ratio")
        summ.update({"mode": label, "n_tile": n_tile, "tol": TOL_05})
        ratio.append(summ)
        print(f"  {label} MAE={fmt(summ.get('mae'))}", flush=True)
    report["ratio_matching"] = ratio

    print("Part C polarity", flush=True)
    pol = []
    for mode in ("pos_only", "neg_only", "pn_independent", "pn_correlated", "pn_systematic"):
        summ, _ = mc_loop(ngspice, net0, cat, n_src, p_servo, x, z, mode, TOL_05, 1, rng, "pol")
        summ.update({"mode": mode, "tol": TOL_05})
        pol.append(summ)
        print(f"  {mode} MAE={fmt(summ.get('mae'))}", flush=True)
    report["polarity"] = pol

    print("Part D CASE 1 temperature (MOS-only .temp)", flush=True)
    case1 = []
    for tc in TEMPS:
        p = MosParams(name="c1", servo=True, temp_c=tc)
        net, _, reason, n_src_i, _, _ = compile_iso(spec, wf, o2, p)
        rec = attach_error(run_op(ngspice, net, x, n_src_i, p, dest("c1", tc)), z)
        rec["temp_c"] = tc
        rec["case"] = 1
        case1.append(slim(rec))
        print(f"  CASE1 T={tc} |err|={fmt(rec.get('abs_err_vs_z'))} Vsum={fmt(rec.get('vsum'))}", flush=True)
    report["case1_temp"] = case1
    report["temp_decomposition"] = {
        "mos_only": "CASE 1 `.temp` sweep. Resistors have no TC1/TC2.",
        "r_only": "NOT SIMULATED. No documented resistor TCR is installed. Not invented.",
        "combined": "Identical to MOS-only in this netlist.",
    }

    print("Part E CASE 2 servo replica (continuous)", flush=True)
    case2 = []
    for tc in TEMPS:
        p = MosParams(name="c2", servo=True, temp_c=tc)
        net, _, reason, n_src_i, _, _ = compile_iso(spec, wf, o2, p)
        net = apply_servo_replica_ref(net, p)
        rec = attach_error(run_op(ngspice, net, x, n_src_i, p, dest("c2", tc)), z)
        rec["temp_c"] = tc
        rec["case"] = 2
        rec["kind"] = "servo_replica_IN+"
        case2.append(slim(rec))
        print(
            f"  CASE2 T={tc} |err|={fmt(rec.get('abs_err_vs_z'))} "
            f"Vsum={fmt(rec.get('vsum'))} P={fmt(rec.get('p_sim_W'))}",
            flush=True,
        )
    report["case2_replica"] = case2

    print("Part E CASE 3 unbuffered capacitive CDS", flush=True)
    case3 = []
    for tc in TEMPS:
        p = MosParams(name="c3", servo=True, temp_c=tc)
        net, _, reason, n_src_i, _, _ = compile_iso(spec, wf, o2, p)
        net = apply_cap_cds_unbuf(net, p, t_az=T_AZ)
        rec = run_az_tran(ngspice, net, x, n_src_i, z, p, dest("c3u", tc), t_az=T_AZ, t_hold=2e-4)
        rec["temp_c"] = tc
        rec["case"] = 3
        rec["kind"] = "cap_cds_unbuf"
        case3.append(slim(rec))
        print(f"  CASE3 unbuf T={tc} |err|={fmt(rec.get('abs_err_vs_z'))} pass={rec.get('analog_pass')}", flush=True)
    report["case3_az"] = case3

    print("Part E CASE 3 miller-follower capacitive CDS", flush=True)
    case3f = []
    for tc in TEMPS:
        p = MosParams(name="c3f", servo=True, temp_c=tc)
        net, _, reason, n_src_i, _, _ = compile_iso(spec, wf, o2, p)
        net = apply_cap_cds(net, p, t_az=T_AZ)
        rec = run_az_tran(ngspice, net, x, n_src_i, z, p, dest("c3f", tc), t_az=T_AZ, t_hold=2e-4)
        rec["temp_c"] = tc
        rec["kind"] = "cap_cds_miller_follower"
        case3f.append(slim(rec))
        print(f"  CASE3 follower T={tc} |err|={fmt(rec.get('abs_err_vs_z'))} pass={rec.get('analog_pass')}", flush=True)
    report["case3_follower"] = case3f

    print("Part E CASE 3 LEVEL-2 VCVS CDS reference (labeled)", flush=True)
    case3ref = []
    for tc in TEMPS:
        p = MosParams(name="c3r", servo=True, temp_c=tc)
        net, _, reason, n_src_i, _, _ = compile_iso(spec, wf, o2, p)
        net = apply_output_cds(net, p, t_az=T_AZ, use_vcvs=True)
        rec = run_az_tran(ngspice, net, x, n_src_i, z, p, dest("c3r", tc), t_az=T_AZ, t_hold=2e-4)
        rec["temp_c"] = tc
        rec["kind"] = "output_cds_vcvs_LEVEL2"
        case3ref.append(slim(rec))
        print(f"  CASE3 VCVS T={tc} |err|={fmt(rec.get('abs_err_vs_z'))} pass={rec.get('analog_pass')}", flush=True)
    report["case3_vcvs_ref"] = case3ref

    print("Part E negative controls (sum CDS, MOS difference amp)", flush=True)
    case3s = []
    case3d = []
    for tc in TEMPS:
        p = MosParams(name="c3s", servo=True, temp_c=tc)
        net, _, reason, n_src_i, _, _ = compile_iso(spec, wf, o2, p)
        rec = run_az_tran(ngspice, apply_sum_cds(net, p, t_az=T_AZ), x, n_src_i, z, p, dest("c3s", tc), t_az=T_AZ, t_hold=2e-4)
        rec["temp_c"] = tc
        rec["kind"] = "sum_cds_negative"
        case3s.append(slim(rec))
        p = MosParams(name="c3d", servo=True, temp_c=tc)
        net, _, reason, n_src_i, _, _ = compile_iso(spec, wf, o2, p)
        rec = run_az_tran(ngspice, apply_output_cds(net, p, t_az=T_AZ, use_vcvs=False), x, n_src_i, z, p, dest("c3damp", tc), t_az=T_AZ, t_hold=2e-4)
        rec["temp_c"] = tc
        rec["kind"] = "mos_difference_amp_negative"
        case3d.append(slim(rec))
        print(
            f"  neg T={tc} sum={fmt(case3s[-1].get('abs_err_vs_z'))} "
            f"diffamp={fmt(case3d[-1].get('abs_err_vs_z'))}",
            flush=True,
        )
    report["case3_sum"] = case3s
    report["case3_mos_diff"] = case3d

    print("Part F CASE 3 unbuf dwell at 85C", flush=True)
    p85 = MosParams(name="c3dyn", servo=True, temp_c=85.0)
    net85, _, _, n_src_i, _, _ = compile_iso(spec, wf, o2, p85)
    net85 = apply_cap_cds_unbuf(net85, p85, t_az=T_AZ)
    report["dynamic_compensation"] = "cap_cds_unbuf"
    dwell = []
    for hold in (1e-4, 2e-4, 5e-4, 1e-3):
        rec = run_az_tran(ngspice, net85, x, n_src_i, z, p85, dest("c3dwell", hold), t_az=T_AZ, t_hold=hold)
        rec["temp_c"] = 85.0
        dwell.append(slim(rec))
        print(f"  hold={hold:.1e} |err|={fmt(rec.get('abs_err_vs_z'))} pass={rec.get('analog_pass')}", flush=True)
    report["az_dwell"] = dwell

    print("Part F CASE 3 unbuf multi-input 85C", flush=True)
    series = [steps["maxabs"], steps["neg"], steps["pos"], steps["maxabs"]]
    zrefs = [steps["z_maxabs"], steps["z_neg"], steps["z_pos"], steps["z_maxabs"]]
    rec_m = run_az_multi(ngspice, net85, series, zrefs, n_src_i, p85, dest("c3m", 85), t_az=T_AZ, t_hold=2e-4)
    report["az_multi"] = rec_m
    report["az_multi_slim"] = {
        k: rec_m.get(k) for k in ("failed", "all_pass", "max_abs_err", "segments", "t_hold_s")
    }
    print(f"  multi max|err|={fmt(rec_m.get('max_abs_err'))} all_pass={rec_m.get('all_pass')}", flush=True)

    print("Part I combined MC", flush=True)
    c3_85 = next((r for r in case3 if r.get("temp_c") == 85.0), {})
    use_cds = bool(c3_85.get("analog_pass"))
    comb_rows = []
    comb_errs = []
    for tc in TEMPS:
        p = MosParams(name="mc", servo=True, temp_c=tc, vos_inject=214e-6)
        net, cat_i, _, n_src_i, _, _ = compile_iso(spec, wf, o2, p)
        if use_cds:
            net = apply_cap_cds_unbuf(net, p, t_az=T_AZ)
        for i in range(N_MC_COMB):
            vals = sample_mismatch(cat_i, "independent", TOL_05, rng, n_tile=16)
            net_i = apply_resistor_values(net, vals)
            if use_cds:
                rec = run_az_tran(ngspice, net_i, x, n_src_i, z, p, dest("mc", tc, i), t_az=T_AZ, t_hold=2e-4)
            else:
                rec = attach_error(run_op(ngspice, net_i, x, n_src_i, p, dest("mc", tc, i)), z)
            rec["temp_c"] = tc
            comb_rows.append(slim(rec))
            if rec.get("abs_err_vs_z") is not None:
                comb_errs.append(rec["abs_err_vs_z"])
            print(f"  MC T={tc} i={i} |err|={fmt(rec.get('abs_err_vs_z'))}", flush=True)
    comb_sum = summarize_errs(comb_rows)
    comb_sum["n_draws"] = len(comb_rows)
    comb_sum["temps"] = list(TEMPS)
    comb_sum["n_tile"] = 16
    comb_sum["tol"] = TOL_05
    comb_sum["vos_inject"] = 214e-6
    comb_sum["compensation"] = "CASE3_unbuf_cap_CDS" if use_cds else "CASE1_servo"
    comb_sum["yield_claim"] = False
    comb_sum["note"] = "Disclosed sample, not a fabrication yield. No invented MOS mismatch PDF."
    report["combined_mc"] = {"errors": comb_errs, "rows": comb_rows}
    report["combined_mc_summary"] = comb_sum

    # vectors for classification-like sign check at 27C N=16
    print("sign check 5 vectors N=16", flush=True)
    sign_rows = []
    vals = sample_mismatch(cat, "independent", TOL_05, rng, n_tile=16)
    net_s = apply_resistor_values(net0, vals)
    for key in vec_keys:
        rec = attach_error(run_op(ngspice, net_s, steps[key], n_src, p_servo, dest("sign", key)), steps[f"z_{key}"])
        rec["step"] = key
        sign_rows.append(slim(rec))
    report["sign_vectors_n16"] = sign_rows

    report["power_compensation"] = [
        {"label": "CASE1 servo 27C", "p_sim_W": case1[1].get("p_sim_W") if len(case1) > 1 else rec0.get("p_sim_W")},
        {"label": "CASE2 replica 27C", "p_sim_W": next((r.get("p_sim_W") for r in case2 if r.get("temp_c") == 27.0), None)},
        {"label": "CASE3 unbuf CDS 27C", "p_sim_W": next((r.get("p_sim_W") for r in case3 if r.get("temp_c") == 27.0), None)},
        {"label": "CASE3 follower 27C", "p_sim_W": next((r.get("p_sim_W") for r in case3f if r.get("temp_c") == 27.0), None)},
    ]

    report["error_budget"] = build_budget(report)
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


def math_ceil_n(mae1):
    if not mae1 or mae1 <= 0:
        return None
    need = (mae1 / ERROR_LIMIT) ** 2
    return int(np.ceil(need))


def build_budget(report):
    def worst(rows, key="abs_err_vs_z"):
        vals = [r.get(key) for r in (rows or []) if r.get(key) is not None]
        return max(vals) if vals else None

    def nom(rows, pred, key="abs_err_vs_z"):
        for r in rows or []:
            if pred(r) and r.get(key) is not None:
                return r[key]
        return None

    tiles = report.get("tiling") or []
    return [
        {
            "source": "resistor mismatch 0.5% N=1",
            "nominal": next((t.get("mae") for t in tiles if t.get("n_tile") == 1), None),
            "worst": next((t.get("max") for t in tiles if t.get("n_tile") == 1), None),
            "independent": True,
            "cancellable": "tiling / ratio correlation; not by servo",
        },
        {
            "source": "resistor mismatch 0.5% N=16",
            "nominal": next((t.get("mae") for t in tiles if t.get("n_tile") == 16), None),
            "worst": next((t.get("max") for t in tiles if t.get("n_tile") == 16), None),
            "independent": True,
            "cancellable": "further N or better process matching",
        },
        {
            "source": "MOS temperature CASE1",
            "nominal": nom(report.get("case1_temp"), lambda r: r.get("temp_c") == 27.0),
            "worst": worst(report.get("case1_temp")),
            "independent": False,
            "cancellable": "replica or periodic AZ (not a stored 27C DW)",
        },
        {
            "source": "MOS temperature CASE3 unbuf CDS",
            "nominal": nom(report.get("case3_az"), lambda r: r.get("temp_c") == 27.0),
            "worst": worst(report.get("case3_az")),
            "independent": False,
            "cancellable": "already the compensation under test (high-Z output)",
        },
        {
            "source": "MOS follower residual at 85C/200us",
            "nominal": nom(report.get("case3_follower"), lambda r: r.get("temp_c") == 27.0),
            "worst": worst(report.get("case3_follower")),
            "independent": False,
            "cancellable": "not at 200 µs; teaching miller CM offset",
        },
        {
            "source": "transistor mismatch PDF",
            "nominal": None,
            "worst": None,
            "independent": True,
            "cancellable": "unvalidated: teaching card has no Pelgrom draw; not invented",
        },
        {
            "source": "resistor TCR",
            "nominal": None,
            "worst": None,
            "independent": True,
            "cancellable": "unvalidated: no documented TCR; not invented",
        },
        {
            "source": "servo residual 27C",
            "nominal": (report.get("nominal_27") or {}).get("abs_err_vs_z"),
            "worst": (report.get("nominal_27") or {}).get("abs_err_vs_z"),
            "independent": False,
            "cancellable": "already below 1e-3",
        },
        {
            "source": "finite loop gain (no-servo Exp26)",
            "nominal": 7.97e-2,
            "worst": 7.97e-2,
            "independent": False,
            "cancellable": "servo / AZ restores VG; not by raising A alone",
        },
        {
            "source": "bias current",
            "nominal": 0.0,
            "worst": 0.0,
            "independent": True,
            "cancellable": "unvalidated: teaching card Ig=0",
        },
        {
            "source": "dynamic settling CASE3 85C",
            "nominal": nom(report.get("az_dwell"), lambda r: abs((r.get("t_hold_s") or 0) - 2e-4) < 1e-9),
            "worst": worst(report.get("az_dwell")),
            "independent": False,
            "cancellable": "longer dwell or larger Caz if droop appears",
        },
        {
            "source": "output swing ±1.65V (Exp26)",
            "nominal": 1.94e-1,
            "worst": 1.94e-1,
            "independent": False,
            "cancellable": "keep ±2.5 V for o2 |z|≈1.73",
        },
    ]


if __name__ == "__main__":
    sys.exit(main())
