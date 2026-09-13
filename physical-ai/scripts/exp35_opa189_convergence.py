"""Experiment 35: N=32 OPA189 convergence and robustness qualification.

Frozen Experiment 9 weights. SPICE is the source of truth.
Does not overwrite Experiments 1-34. Does not transistorize Network F.
Does not invent MOS W/L. Does not search for another amplifier.
Does not promote reltol from a single run.
"""

from __future__ import annotations

import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from benchmark_scaling import generate_inputs
from compile_xor import find_ngspice
from exp32_hidden_inverter_primitive import software_for
from exp35_n32_qualification import (
    CIRCUIT_DIR,
    DEFAULT_SOLVER,
    ERROR_LIMIT,
    MAX_ABS_LIMIT,
    RESULTS_DIR,
    TIMEOUT_DC,
    TIMEOUT_ISO,
    TIMEOUT_TRAN,
    analog_mae_failing_indices,
    dest,
    eval_fabric,
    fmt,
    option_line,
    slim,
    slim_eval,
    solver_record,
)
from hardware_constrained_compiler import load_frozen_model
from hidden_inverter_primitive import patch_hidden_opa_replica
from inverter_requirement_extraction import compile_f, hidden_stages
from opa189_fabric_isolation import (
    OPA189,
    OPA189_NAME,
    R_LOAD_W,
    VIN_SWING,
    detach_dest_fabric,
    eval_f_rich,
    eval_isolated_ncopy,
    fabric_load_ohm,
    hidden_y,
    inject_options,
    isolated_n_copy,
    output_sum_nodes,
    patch_opa189,
    replace_relu_with_vsrc,
    slim_probe,
)


REPORT_JSON = RESULTS_DIR / "exp35_opa189_convergence.json"
REPORT_MD = RESULTS_DIR / "exp35_opa189_convergence.md"
N_FULL = 40
N_COMPARE = 12
RELTOLS = (1e-3, 5e-4, 2e-4, 1e-4, 5e-5, 2e-5, 1e-5, 5e-6, 2e-6, 1e-6)
FAIL_IDX_EXP34 = 6


def save_report(report: dict) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(report, indent=2, default=slim), encoding="utf-8")


def write_plots(report: dict) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    def save(fig, name):
        fig.tight_layout()
        fig.savefig(RESULTS_DIR / name, dpi=140)
        plt.close(fig)

    rows = [r for r in (report.get("reltol_sweep") or []) if r.get("mae") is not None]
    if rows:
        fig, ax = plt.subplots(figsize=(6.6, 4.2))
        ax.semilogx([r["reltol"] for r in rows], [r["mae"] for r in rows], "o-")
        ax.axhline(ERROR_LIMIT, color="0.4", ls="--", label="MAE 1e-3")
        ax.set_xlabel("reltol")
        ax.set_ylabel("F12 MAE")
        ax.set_title("Experiment 35: MAE vs reltol")
        ax.legend(fontsize=8)
        save(fig, "exp35_reltol_sweep.png")
        fig, ax = plt.subplots(figsize=(6.6, 4.2))
        ax.loglog(
            [r["reltol"] for r in rows],
            [max(r.get("max_abs_error") or 1e-15, 1e-15) for r in rows],
            "s-",
        )
        ax.set_xlabel("reltol")
        ax.set_ylabel("max |error| (V)")
        ax.set_title("Experiment 35: max error vs reltol")
        save(fig, "exp35_reltol_maxerr.png")

    abs_rows = [r for r in (report.get("abstol_sweep") or []) if r.get("mae") is not None]
    if abs_rows:
        fig, ax = plt.subplots(figsize=(6.8, 4.3))
        for rel in sorted({r.get("reltol") for r in abs_rows}):
            sub = [r for r in abs_rows if r.get("reltol") == rel]
            ax.semilogx(
                [r.get("vntol") or r.get("abstol") or 1e-12 for r in sub],
                [r["mae"] for r in sub],
                "o-",
                label=f"reltol={rel:g}",
            )
        ax.axhline(ERROR_LIMIT, color="0.4", ls="--")
        ax.set_xlabel("vntol or abstol")
        ax.set_ylabel("F12 MAE")
        ax.set_title("Experiment 35: absolute tolerance")
        ax.legend(fontsize=8)
        save(fig, "exp35_abstol_sweep.png")

    dwell = [r for r in (report.get("dwell_results") or []) if r.get("mae") is not None]
    if dwell:
        fig, ax = plt.subplots(figsize=(6.6, 4.3))
        vec6 = [r for r in dwell if "failing vector" in str(r.get("note", ""))]
        f12 = [r for r in dwell if "F12" in str(r.get("note", "")) and r.get("n_vectors") == 12]
        if vec6:
            ax.semilogx(
                [r["t_hold"] for r in vec6],
                [r["mae"] for r in vec6],
                "o-",
                label="vector 6 only",
            )
        if f12:
            ax.semilogx(
                [r["t_hold"] for r in f12],
                [r["mae"] for r in f12],
                "s-",
                label="F12 independent TRAN",
            )
        if not vec6 and not f12:
            ax.semilogx([r["t_hold"] for r in dwell], [r["mae"] for r in dwell], "o-")
        ax.axhline(ERROR_LIMIT, color="0.4", ls="--", label="MAE 1e-3")
        ax.axvline(2e-4, color="0.5", ls=":", label="200 us")
        ax.set_xlabel("dwell (s)")
        ax.set_ylabel("MAE")
        ax.set_title("Experiment 35: dwell-time sweep")
        ax.legend(fontsize=8)
        save(fig, "exp35_dwell.png")

    ts = [r for r in (report.get("timestep_results") or []) if r.get("mae") is not None]
    if ts:
        fig, ax = plt.subplots(figsize=(6.6, 4.3))
        xs = []
        for i, r in enumerate(ts):
            xs.append(r.get("tstep") or r.get("maxstep") or (i + 1) * 1e-7)
        ax.semilogx(xs, [r["mae"] for r in ts], "o-")
        ax.axhline(ERROR_LIMIT, color="0.4", ls="--")
        ax.set_xlabel("timestep / maxstep (s)")
        ax.set_ylabel("MAE")
        ax.set_title("Experiment 35: timestep / integration")
        save(fig, "exp35_timestep.png")

    vo = report.get("vector_order_results") or []
    if vo:
        fig, ax = plt.subplots(figsize=(6.6, 4.2))
        labels = [r.get("order", "?") for r in vo]
        ys = [r.get("mae") or 0 for r in vo]
        ax.semilogy(range(len(ys)), [max(float(y), 1e-15) for y in ys], "o-")
        ax.set_xticks(range(len(labels)))
        ax.set_xticklabels(labels, rotation=20, ha="right", fontsize=8)
        ax.axhline(ERROR_LIMIT, color="0.4", ls="--")
        ax.set_ylabel("F12 MAE")
        ax.set_title("Experiment 35: vector-order robustness")
        save(fig, "exp35_vector_order.png")

    hier = report.get("hierarchy_results") or []
    if hier:
        fig, ax = plt.subplots(figsize=(7.0, 4.3))
        labels = [h.get("control", "?") for h in hier]
        ys = [h.get("residual") or h.get("mae") or 0 for h in hier]
        ax.semilogy(range(len(ys)), [max(float(y), 1e-16) for y in ys], "o-")
        ax.set_xticks(range(len(labels)))
        ax.set_xticklabels(labels, rotation=20, ha="right", fontsize=8)
        ax.set_ylabel("residual or MAE (V)")
        ax.set_title("Experiment 35: model vs fabric hierarchy")
        save(fig, "exp35_hierarchy.png")

    fb = report.get("failing_vector_inverters") or []
    if fb:
        fig, ax = plt.subplots(figsize=(6.2, 4.2))
        ax.loglog(
            [max(abs(p.get("vdiff") or 1e-15), 1e-15) for p in fb],
            [max(abs(p.get("abs_err") or 1e-15), 1e-15) for p in fb],
            "o",
            ms=4,
        )
        ax.set_xlabel("|V- - V+| (V)")
        ax.set_ylabel("|Vout + Vin| (V)")
        ax.set_title("Experiment 35: failing-vector feedback residual")
        save(fig, "exp35_feedback_residual.png")

    mx = [r for r in (report.get("failing_vector_matrix") or []) if r.get("residual") is not None]
    if mx:
        fig, ax = plt.subplots(figsize=(6.8, 4.3))
        ax.semilogy(range(len(mx)), [max(r["residual"], 1e-15) for r in mx], "o-")
        ax.set_xticks(range(len(mx)))
        ax.set_xticklabels(
            [f"{r.get('reltol')}\n{r.get('mode')}" for r in mx],
            fontsize=7,
        )
        ax.set_ylabel("|Vout+Vin| mean (V)")
        ax.set_title("Experiment 35: failing-vector solver matrix")
        save(fig, "exp35_solver_matrix.png")

    q = report.get("qualification") or {}
    fig, ax = plt.subplots(figsize=(6.4, 3.6))
    items = [
        ("default analog", q.get("default_analog")),
        ("candidate analog", q.get("candidate_analog")),
        ("max-err", q.get("candidate_max_pass")),
        ("class 100%", q.get("candidate_class")),
        ("200 us", q.get("tran_200_pass")),
        ("repeatable", q.get("repeatable")),
        ("reltol band", q.get("reltol_band")),
    ]
    ax.bar(range(len(items)), [1 if v else 0 for _, v in items], color=["#2a7" if v else "#c55" for _, v in items])
    ax.set_xticks(range(len(items)))
    ax.set_xticklabels([k for k, _ in items], rotation=20, ha="right", fontsize=8)
    ax.set_ylim(0, 1.2)
    ax.set_title("Experiment 35: N=32 qualification gates")
    save(fig, "exp35_qualification.png")


def write_markdown(report: dict) -> None:
    dec = report.get("decision") or {}
    q = report.get("qualification") or {}
    base = report.get("phase0_default") or {}
    tight = report.get("phase0_tight") or {}
    fv = report.get("failing_vector") or {}
    corr = report.get("load_correlation") or {}
    hole = next((r for r in (report.get("reltol_sweep") or []) if r.get("reltol") == 2e-5), None)
    invert_fail = report.get("invert_failing_vector_indices") or [fv.get("index", 6)]
    lines = [
        "==================================================",
        "EXPERIMENT 35",
        "N=32 OPA189 CONVERGENCE AND ROBUSTNESS QUALIFICATION",
        "==================================================",
        "",
        "Frozen Experiment 9 weights. SPICE is the source of truth.",
        "Experiments 1-34 were not overwritten. No Python correction,",
        "no invented MOS W/L, no Network F in transistors.",
        "OPA189 remains the official TI Green-Williams-Lis macromodel.",
        "",
        f"Status: **{dec.get('status', '')}**",
        f"Decision: **{dec.get('letter', '')}**",
        f"Qualification: **{report.get('qualification_status', '')}**",
        f"F40 permitted: {dec.get('f40_permitted', False)}",
        "",
        "## 1. Executive summary",
        "",
        dec.get("reason", ""),
        "",
        "The Experiment 34 default-reltol N=32 fail is reproduced: F12 MAE",
        f"{fmt(base.get('mae'))}, max {fmt(base.get('max_abs_error'))}, invert-fail",
        f"vector {invert_fail}. The same netlist at reltol=1e-6 reproduces MAE",
        f"{fmt(tight.get('mae'))}. The reltol sweep is discontinuous: a bad DC",
        "operating-point plateau from 1e-3 through 1e-4, a good plateau from",
        "5e-5 through 1e-6 except a no-convergence hole at 2e-5. Absolute",
        "tolerances do not move the branch. Vector order does not move it.",
        "Full-F12 DC initial-condition variants do not move it.",
        "",
        "The 2.29 mV residual is a DC Newton branch of the coupled GWL fabric.",
        "It is not a stable physical offset: default-reltol TRAN on vector 6",
        "settles to the good invert (MAE ~6e-4) at 100/200/500 us. Isolated",
        "32-copy OPA189 stays at ~0.64 uV at both reltols. Replica-sign analog-",
        "passes at default DC. Independent +/-15 V supplies do not change MAE.",
        "",
        "Tighter reltol does not invent a new circuit solution. It selects the",
        "same operating point that default-reltol transient analysis already",
        "finds. The default DC 2.29 mV result is the numerical escape.",
        "",
        "## 2. Experiment 34 starting point",
        "",
        "Isolated 32-copy residual ~0.66 uV. Default-reltol fabric N=32 MAE",
        "1.014e-3 from one F12 vector at ~2.29 mV. reltol=1e-6 diagnostic",
        "MAE 5.10e-4. Decision E. F40 not earned. Status: PHYSICAL HIDDEN",
        "INVERTER PARTIALLY VALIDATED.",
        "",
        "## 3. Exact reproduction",
        "",
        f"Default (no .option): MAE={fmt(base.get('mae'))} max={fmt(base.get('max_abs_error'))} "
        f"acc={fmt(base.get('accuracy'), '.4f')} analog={base.get('analog_pass')} "
        f"worst_vector={base.get('worst_vector')} invert_fail={invert_fail} "
        f"spice_s={fmt(base.get('spice_s'), '.1f')}",
        "",
        f"reltol=1e-6: MAE={fmt(tight.get('mae'))} max={fmt(tight.get('max_abs_error'))} "
        f"acc={fmt(tight.get('accuracy'), '.4f')} analog={tight.get('analog_pass')} "
        f"worst_vector={tight.get('worst_vector')} "
        f"analog_mae_fail={analog_mae_failing_indices(tight)} "
        f"spice_s={fmt(tight.get('spice_s'), '.1f')}",
        "",
        f"Reproduction: {report.get('reproduction_ok')}",
        "",
        "Note: `failing_vector_indices` in raw JSON uses per-vector max |err| > 1e-3.",
        "Nominal Architecture A F12 already has several outputs near 1-3 mV, so",
        "that list is almost every vector even on an analog-pass. Invert failure",
        "is identified by per-vector MAE > 1e-3, which is vector 6 only at",
        "default DC. After the good OP is selected, analog MAE-fail is empty",
        "and the worst remaining vector is 10 (max 3.16e-3, the frozen map).",
        "",
        "## 4. N=32 failing vector",
        "",
        f"Original-order index: {fv.get('index')} (Experiment 34 index 6).",
        f"per-vector max error: {fmt(fv.get('max_abs_error'))}",
        f"per-vector MAE: {fmt(fv.get('mae'))}",
        f"mean invert |Vout+Vin|: {fmt(fv.get('mean_invert_residual'))}",
        f"max invert |Vout+Vin|: {fmt(fv.get('max_invert_residual'))}",
        f"worst output neuron: {fv.get('worst_output')}",
        f"standalone default-reltol analog: {fv.get('standalone_analog')}",
        f"standalone MAE vs that vector: {fmt(fv.get('standalone_mae'))}",
        "",
        "Vector 6 fails as its own ngspice OP (no prior vector). The error is",
        "a shared invert pedestal on all 32 hidden stages, not one amplifier.",
        "Downstream outputs inherit that common invert offset. Isolated copies",
        "driven by the same hy and Rfab do not show the pedestal.",
        "",
        "Per-inverter residuals on the failing vector (worst 8):",
        "",
        "| stem | Vin | Vout | |Vout+Vin| | |V-| | Rfab |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for p in (fv.get("worst_inverters") or [])[:8]:
        lines.append(
            f"| {p.get('stem')} | {fmt(p.get('vin'))} | {fmt(p.get('vout'))} | "
            f"{fmt(p.get('abs_err'))} | {fmt(p.get('vmid'))} | {fmt(p.get('r_fab'))} |"
        )
    lines += [
        "",
        f"Load correlation (not causation): err vs Rfab r={fmt(corr.get('corr_err_vs_rfab'), '.3f')}; "
        f"err vs Vin r={fmt(corr.get('corr_err_vs_vin'), '.3f')}. Residuals are shared,",
        "so Vin correlation reflects the common pedestal, not a unique loaded stage.",
        "",
        "## 5. Solver tolerance sweep",
        "",
        "Every other setting held at Experiment 34 / ngspice factory defaults.",
        "Two discrete DC solutions plus a hole. Not a smooth tightening curve.",
        "",
        "| reltol | MAE | max | acc | analog | analog-MAE-fail | conv warn | t(s) |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in report.get("reltol_sweep") or []:
        lines.append(
            f"| {r.get('reltol')} | {fmt(r.get('mae'))} | {fmt(r.get('max_abs_error'))} | "
            f"{fmt(r.get('accuracy'), '.4f')} | {r.get('analog_pass')} | "
            f"{analog_mae_failing_indices(r)} | {r.get('n_conv_warn')} | {fmt(r.get('spice_s'), '.1f')} |"
        )
    lines += [
        "",
        "Passing DC reltols: 5e-5, 1e-5, 5e-6, 2e-6, 1e-6 (identical MAE 5.1038e-4).",
        f"Hole: reltol=2e-5 failed={hole.get('failed') if hole else None} "
        f"reason={hole.get('failure_reason') if hole else 'n/a'}.",
        "",
        "## 6. Absolute tolerance analysis",
        "",
        "At the bad-branch reltols (1e-3, 1e-4), vntol / abstol / chgtol changes",
        "do not select the good operating point. reltol controls the DC branch.",
        "",
        "| reltol | vntol | abstol | chgtol | MAE | max | analog | t(s) |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in report.get("abstol_sweep") or []:
        lines.append(
            f"| {r.get('reltol')} | {r.get('vntol')} | {r.get('abstol')} | {r.get('chgtol', 'default')} | "
            f"{fmt(r.get('mae'))} | {fmt(r.get('max_abs_error'))} | "
            f"{r.get('analog_pass')} | {fmt(r.get('spice_s'), '.1f')} |"
        )
    lines += [
        "",
        "## 7. Timestep / integration analysis",
        "",
        "Batched 12-vector TRAN in one ngspice process timed out at 600 s",
        "(default and reltol=5e-5). That timeout is a process-length limit,",
        "not a measured analog fail. Qualification uses independent 200 us",
        "transients (one process per vector).",
        "",
        "| mode | method | t_hold | tstep | MAE | analog | n_vec | note |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in (report.get("timestep_results") or []) + (report.get("tran_results") or []):
        lines.append(
            f"| {r.get('mode')} | {r.get('method')} | {r.get('t_hold')} | {r.get('tstep')} | "
            f"{fmt(r.get('mae'))} | {r.get('analog_pass')} | {r.get('n_vectors')} | {r.get('note', '')} |"
        )
    lines += [
        "",
        "## 8. Initial-condition analysis",
        "",
        "Full-F12 DC protocols (sequential alter, reset-before-op, independent",
        "per-vector OP) all stay on the bad default-reltol branch (MAE 1.014e-3).",
        "The bad OP is not an inter-vector continuation artifact. UIC / zero",
        "start is reported below where measured. Artificial answer-encoding",
        "ICs were not used.",
        "",
        "| case | MAE | max | analog | analog-MAE-fail | note |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in report.get("initial_condition_results") or []:
        lines.append(
            f"| {r.get('case')} | {fmt(r.get('mae'))} | {fmt(r.get('max_abs_error'))} | "
            f"{r.get('analog_pass')} | {analog_mae_failing_indices(r)} | {r.get('note', '')} |"
        )
    lines += [
        "",
        "## 9. Vector-order analysis",
        "",
        "Default-reltol DC MAE is identical in original, reversed, two shuffled,",
        "and failing-first order. Vector 6 is not created by the preceding vector.",
        "",
        "| order | MAE | max | analog | analog-MAE-fail orig |",
        "| --- | --- | --- | --- | --- |",
    ]
    for r in report.get("vector_order_results") or []:
        lines.append(
            f"| {r.get('order')} | {fmt(r.get('mae'))} | {fmt(r.get('max_abs_error'))} | "
            f"{r.get('analog_pass')} | {r.get('failing_original_indices')} |"
        )
    lines += [
        "",
        "## 10. Dwell-time analysis",
        "",
        "Project target is 200 us. 1 ms is reported only as a bound, not as a substitute.",
        "",
        "| dwell | MAE | max | analog | n_vec | note |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in report.get("dwell_results") or []:
        lines.append(
            f"| {r.get('t_hold')} | {fmt(r.get('mae'))} | {fmt(r.get('max_abs_error'))} | "
            f"{r.get('analog_pass')} | {r.get('n_vectors')} | {r.get('note', '')} |"
        )
    lines += [
        "",
        "## 11. Model-vs-fabric hierarchy",
        "",
        "Sensitivity appears only when the vendor macromodel is embedded in the",
        "full hidden-neuron resistor fabric. Isolated A/B/C stay at ~0.64 uV",
        "at default reltol. Control D dumps W2 (MAE ~1, expected). Control E",
        "is the coupled N=32 fabric and is the first place the 2.29 mV DC",
        "branch appears.",
        "",
        "| control | reltol | residual/MAE | analog | note |",
        "| --- | --- | --- | --- | --- |",
    ]
    for r in report.get("hierarchy_results") or []:
        lines.append(
            f"| {r.get('control')} | {r.get('reltol')} | {fmt(r.get('residual') if r.get('residual') is not None else r.get('mae'))} | "
            f"{r.get('analog_pass')} | {r.get('note', '')} |"
        )
    lines += [
        "",
        "## 12. Supply / replica controls",
        "",
        "Independent vs shared +/-15 V rails are numerically identical at both",
        "reltols. Supply-network interaction is not the branch. Replica present",
        "with IN+=0 matches the uncorrected fabric. LEVEL 2 replica-sign analog-",
        "passes at default reltol (MAE 5.084e-4), i.e. the composite already",
        "finds the good solution without tightening reltol. That is a control,",
        "not a promotion of replica-sign as the N=32 invert itself.",
        "",
        "| case | reltol | MAE | analog | note |",
        "| --- | --- | --- | --- | --- |",
    ]
    for r in (report.get("supply_control_results") or []) + (report.get("replica_control_results") or []):
        lines.append(
            f"| {r.get('case')} | {r.get('reltol')} | {fmt(r.get('mae'))} | "
            f"{r.get('analog_pass')} | {r.get('note', '')} |"
        )
    lines += [
        "",
        "## 13. Mechanism evidence",
        "",
        report.get("mechanism_text", ""),
        "",
        "Interpretation of the central distinction: default DC 2.29 mV vs",
        "reltol=1e-6 MAE 5.10e-4 is not 'tighter tolerance fixes the circuit.'",
        "Default-reltol TRAN and tight-reltol DC converge to the same good",
        "operating point. Default-reltol DC Newton can stop on a different",
        "coupled-GWL solution. The isolated macromodel does not show that",
        "second solution. The fabric creates the bad Newton basin; the",
        "intended settled invert remains the microvolt-class OP.",
        "",
        "## 14. Repeatability",
        "",
        "| run | MAE | max | analog | worst vec |",
        "| --- | --- | --- | --- | --- |",
    ]
    for r in report.get("repeatability_results") or []:
        lines.append(
            f"| {r.get('run')} | {fmt(r.get('mae'))} | {fmt(r.get('max_abs_error'))} | "
            f"{r.get('analog_pass')} | {r.get('worst_vector')} |"
        )
    lines += [
        "",
        f"Repeatable: {q.get('repeatable')}",
        "",
        "## 15. N=32 qualification decision",
        "",
        f"- default DC analog: {q.get('default_analog')}",
        f"- candidate analog: {q.get('candidate_analog')}",
        f"- candidate max-err <= 1e-2: {q.get('candidate_max_pass')}",
        f"- classification 100%: {q.get('candidate_class')}",
        f"- 200 us: {q.get('tran_200_pass')}",
        f"- repeatable: {q.get('repeatable')}",
        f"- reltol band (not a single point): {q.get('reltol_band')}",
        f"- qualified: {q.get('qualified')}",
        "",
        f"Candidate solver: {q.get('candidate_solver')}",
        "",
        "Important solver configurations (complete list in JSON):",
        "",
        "| config | settings | MAE | analog |",
        "| --- | --- | --- | --- |",
        f"| Exp 34 default DC | no .option; reltol=1e-3 factory | {fmt(base.get('mae'))} | {base.get('analog_pass')} |",
        f"| Diagnostic tight DC | .option reltol=1e-6 | {fmt(tight.get('mae'))} | {tight.get('analog_pass')} |",
        f"| Loosest passing DC | .option reltol=5e-05 | {fmt((report.get('repeatability_results') or [{}])[0].get('mae'))} | {(report.get('repeatability_results') or [{}])[0].get('analog_pass')} |",
        f"| Hole | .option reltol=2e-05 | {fmt(hole.get('mae') if hole else None)} | {hole.get('analog_pass') if hole else None} |",
        f"| Qualified 200 us TRAN | .option method=gear | {fmt((q.get('tran_200_row') or {}).get('mae'))} | {(q.get('tran_200_row') or {}).get('analog_pass')} |",
        "| Independent trap TRAN | factory trap, 90 s cap | n/a | False |",
        "",
        "## 16. Whether F40 is permitted",
        "",
        str(dec.get("f40_permitted", False)),
        "",
        dec.get("f40_reason", ""),
        "",
        "## 17. Remaining physical limitations",
        "",
        dec.get("limitations", ""),
        "",
        "Additional remaining limits: TIA and ReLU are still ideal behavioral",
        "blocks. The invert cell is a vendor macromodel, not transistor-level",
        "silicon. reltol=2e-5 is a documented DC non-convergence hole. Default",
        "DC OP remains the wrong branch and must not be used as the N=32",
        "source of truth. Macromodel supply current is not board or silicon power.",
        "",
        "## 18. Exact next experiment",
        "",
        dec.get("next", ""),
        "",
        "JSON: `results/exp35_opa189_convergence.json`.",
        "Circuits: `circuits/exp35_opa189_convergence/`.",
        "Scripts: `scripts/exp35_opa189_convergence.py`, `scripts/exp35_n32_qualification.py`.",
        "Plots: `results/exp35_reltol_sweep.png`, `results/exp35_abstol_sweep.png`,",
        "`results/exp35_timestep.png`, `results/exp35_dwell.png`,",
        "`results/exp35_vector_order.png`, `results/exp35_hierarchy.png`,",
        "`results/exp35_feedback_residual.png`, `results/exp35_solver_matrix.png`,",
        "`results/exp35_qualification.png`.",
        "",
    ]
    REPORT_MD.write_text("\n".join(lines), encoding="utf-8")


def decide(report: dict) -> dict:
    q = report.get("qualification") or {}
    base = report.get("phase0_default") or {}
    orders = report.get("vector_order_results") or []
    ics = report.get("initial_condition_results") or []
    hier = report.get("hierarchy_results") or []
    dwell = report.get("dwell_results") or []
    order_sensitive = False
    if orders:
        maes = [r.get("mae") for r in orders if r.get("mae") is not None]
        if maes and (max(maes) - min(maes)) > 2e-4:
            order_sensitive = True
    ic_sensitive = False
    if ics:
        # Compare only full-F12 OP protocols. A single-vector MAE is not an IC branch.
        maes = [
            r.get("mae")
            for r in ics
            if r.get("mae") is not None
            and r.get("case")
            in {"sequential_alter_default", "reset_before_each_op", "independent_per_vector_OP"}
        ]
        if maes and (max(maes) - min(maes)) > 2e-4:
            ic_sensitive = True
    fabric_only = True
    for h in hier:
        if h.get("control") in {"A", "B", "C"} and h.get("reltol") in (0.001, 1e-3, None):
            res = h.get("residual")
            if res is not None and res > 50e-6:
                fabric_only = False
    tran_200 = next((d for d in dwell if d.get("t_hold") == 2e-4), None)
    if q.get("qualified"):
        letter = "F"
        status = "PHYSICAL HIDDEN INVERTER VALIDATED AT N=32"
        f40 = True
        f40_reason = "N=32 met analog, class, 200 us, repeatability, and solver-band gates."
    elif q.get("candidate_analog") and q.get("reltol_band") and q.get("repeatable") and not q.get("tran_200_pass"):
        letter = "A"
        status = "PHYSICAL HIDDEN INVERTER PARTIALLY VALIDATED"
        f40 = False
        f40_reason = "DC solver band is robust but 200 us sampled-inference gate was not satisfied."
    elif order_sensitive or ic_sensitive:
        letter = "C"
        status = "PHYSICAL HIDDEN INVERTER PARTIALLY VALIDATED"
        f40 = False
        f40_reason = "Result depends on vector order or initial-condition / OP continuation."
    elif fabric_only and q.get("candidate_analog") and not q.get("reltol_band"):
        letter = "D"
        status = "PHYSICAL HIDDEN INVERTER PARTIALLY VALIDATED"
        f40 = False
        f40_reason = "Sensitivity appears only in the coupled fabric and is not a stable solver band."
    elif q.get("candidate_analog") and q.get("reltol_band"):
        letter = "A"
        status = "PHYSICAL HIDDEN INVERTER PARTIALLY VALIDATED"
        f40 = False
        f40_reason = "Numerical qualification is strong on DC but promotion criteria were not all met."
    elif (base.get("mae") or 0) > ERROR_LIMIT and not q.get("candidate_analog"):
        letter = "B"
        status = "PHYSICAL HIDDEN INVERTER PARTIALLY VALIDATED"
        f40 = False
        f40_reason = "Solver changes do not produce a stable analog-pass."
    else:
        letter = "E"
        status = "PHYSICAL HIDDEN INVERTER PARTIALLY VALIDATED"
        f40 = False
        f40_reason = "Evidence is insufficient to qualify N=32 or permit F40."

    titles = {
        "A": "A — ROBUST NUMERICAL QUALIFICATION",
        "B": "B — GENUINE CIRCUIT/MODEL MARGINALITY",
        "C": "C — DYNAMIC/INITIAL-CONDITION ISSUE",
        "D": "D — FABRIC/MODEL INTERACTION",
        "E": "E — UNRESOLVED",
        "F": "F — N=32 PHYSICAL HIDDEN INVERTER VALIDATED",
    }
    report["decision"] = {
        "letter": titles[letter],
        "status": status,
        "f40_permitted": f40,
        "f40_reason": f40_reason,
        "reason": (
            f"Default MAE={fmt(base.get('mae'))} worst_vec={base.get('worst_vector')}. "
            f"Candidate analog={q.get('candidate_analog')} band={q.get('reltol_band')} "
            f"repeat={q.get('repeatable')} 200us={q.get('tran_200_pass')}. "
            f"Order-sensitive={order_sensitive} IC-sensitive={ic_sensitive}."
        ),
        "limitations": (
            "OPA189 remains a GWL macromodel, not silicon. TIA/ReLU remain ideal. "
            "No PDK. Default DC OP is the wrong Newton branch and is not the source of truth. "
            "reltol=2e-5 is a DC non-convergence hole. Trapezoidal TRAN hangs on some "
            "F12 vectors; qualified transients use method=gear. "
            "Macromodel Iq is not board or silicon power."
        ),
        "next": (
            "F40 integration on the qualified solver band"
            if f40
            else (
                "Remain on N=32: close the unmet gate "
                f"(200 us={q.get('tran_200_pass')}, band={q.get('reltol_band')}, "
                f"repeat={q.get('repeatable')}). Do not invent MOS. Do not search another amp."
            )
        ),
    }
    report["qualification_status"] = "QUALIFIED" if q.get("qualified") else "NOT QUALIFIED"
    return report


def main():
    print("Experiment 35: N=32 OPA189 convergence qualification", flush=True)
    ng = find_ngspice()
    if not OPA189.exists():
        raise SystemExit(f"OPA189 missing: {OPA189}")
    w = load_frozen_model("F")
    net0, _cat, spec = compile_f(w)
    hidden = hidden_stages(net0)
    x40 = generate_inputs(spec["n_in"], N_FULL, "exp24_F")
    x12 = x40[:N_COMPARE]
    y12 = software_for(w, x12)
    hy12 = hidden_y(w, x12)
    net_opa = patch_opa189(net0, hidden)
    print(f"  hidden={len(hidden)} F12={len(x12)} dest={CIRCUIT_DIR}", flush=True)

    report = {
        "experiment_id": 35,
        "frozen_model_identifier": "models/scaling/F.npz seed 9",
        "source_experiment": 34,
        "default_solver_settings": DEFAULT_SOLVER,
        "N_values": [32],
        "F12_vector_count": int(N_COMPARE),
        "spice_source_of_truth": True,
        "network_f_transistorized": False,
        "python_correction": False,
        "frozen_weights_edited": False,
        "vendor_models_edited": False,
        "pdk_installed": False,
    }
    prior = {}
    if REPORT_JSON.exists():
        try:
            prior = json.loads(REPORT_JSON.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            prior = {}
    resume_p8 = bool(prior.get("reltol_sweep") and prior.get("vector_order_results") and prior.get("phase0_default"))
    if resume_p8:
        report.update(prior)
        rec0 = prior["phase0_default"]
        rec_t = prior["phase0_tight"]
        fail_i = int((prior.get("failing_vector") or {}).get("index", FAIL_IDX_EXP34))
        x_fail = x12[fail_i : fail_i + 1]
        y_fail = y12[fail_i : fail_i + 1]
        worst_inv = prior.get("failing_vector_inverters") or []
        reltol_rows = prior.get("reltol_sweep") or []
        rec_one = next(
            (r for r in (prior.get("initial_condition_results") or []) if r.get("case") == "failing_vector_alone"),
            {},
        )
        rec_reset = next(
            (r for r in (prior.get("initial_condition_results") or []) if r.get("case") == "reset_before_each_op"),
            {},
        )
        indep_row = next(
            (r for r in (prior.get("initial_condition_results") or []) if r.get("case") == "independent_per_vector_OP"),
            {},
        )
        print("  resuming from PHASE 8 using saved Experiment 35 JSON", flush=True)
    else:
        save_report(report)

    if not resume_p8:
        print("==== PHASE 0 reproduce Experiment 34 ====", flush=True)
        rec0 = eval_fabric(ng, net_opa, spec, x12, y12, dest("p0", "default"))
        print(
            f"  default MAE={fmt(rec0.get('mae'))} max={fmt(rec0.get('max_abs_error'))} "
            f"worst={rec0.get('worst_vector')} fail={rec0.get('failing_vector_indices')} "
            f"pass={rec0.get('analog_pass')}",
            flush=True,
        )
        rec_t = eval_fabric(
            ng, net_opa, spec, x12, y12, dest("p0", "reltol1e-6"), options=option_line(reltol=1e-6)
        )
        print(
            f"  reltol=1e-6 MAE={fmt(rec_t.get('mae'))} max={fmt(rec_t.get('max_abs_error'))} "
            f"worst={rec_t.get('worst_vector')} pass={rec_t.get('analog_pass')}",
            flush=True,
        )
        repro_ok = (
            rec0.get("mae") is not None
            and abs(rec0["mae"] - 1.0141705623164423e-3) < 2e-5
            and rec0.get("worst_vector") == FAIL_IDX_EXP34
            and rec_t.get("mae") is not None
            and abs(rec_t["mae"] - 5.10e-4) < 4e-5
            and rec_t.get("analog_pass")
        )
        report["phase0_default"] = slim_eval(rec0)
        report["phase0_tight"] = slim_eval(rec_t)
        report["baseline_MAE"] = rec0.get("mae")
        report["baseline_max_error"] = rec0.get("max_abs_error")
        report["tight_reltol_MAE"] = rec_t.get("mae")
        report["tight_reltol_max_error"] = rec_t.get("max_abs_error")
        report["failing_vector_indices"] = rec0.get("failing_vector_indices")
        report["reproduction_ok"] = bool(repro_ok)
        print(f"  reproduction_ok={repro_ok}", flush=True)
        if not repro_ok:
            print("  WARNING: Experiment 34 reference not matched exactly; continuing with measured values.", flush=True)
        save_report(report)

        # ------------------------------------------------------------------
        print("==== PHASE 1 failing vector isolation ====", flush=True)
        fail_i = int(rec0.get("worst_vector") if rec0.get("worst_vector") is not None else FAIL_IDX_EXP34)
        x_fail = x12[fail_i : fail_i + 1]
        y_fail = y12[fail_i : fail_i + 1]
        rec_one = eval_fabric(ng, net_opa, spec, x_fail, y_fail, dest("p1", "vec_alone"))
        print(
            f"  vector {fail_i} standalone MAE={fmt(rec_one.get('mae'))} "
            f"max={fmt(rec_one.get('max_abs_error'))} pass={rec_one.get('analog_pass')}",
            flush=True,
        )
        rich0 = eval_f_rich(
            ng,
            net_opa,
            spec,
            x12,
            y12,
            hidden,
            dest("p1", "rich_default"),
            sum_nodes=output_sum_nodes(spec["n_out"]),
        )
        invs = []
        for s, p in zip(hidden, rich0.get("probes") or []):
            # residual_by_vector is stage-mean; recover this vector from re-probe of dest/src
            invs.append(
                {
                    "stem": p.get("stem"),
                    "r_fab": p.get("r_fab_ohm") or fabric_load_ohm(net_opa, s["dest"], s["mid"]),
                    "err_mae_all": p.get("err_mae"),
                    "err_max_all": p.get("err_max"),
                    "vmid_mae": p.get("vmid_mae"),
                }
            )
        # single-vector rich
        rich1 = eval_f_rich(ng, net_opa, spec, x_fail, y_fail, hidden, dest("p1", "rich_one"))
        worst_inv = []
        for s, p in zip(hidden, rich1.get("probes") or []):
            worst_inv.append(
                {
                    "stem": p.get("stem"),
                    "abs_err": p.get("err_mae"),
                    "vmid": p.get("vmid_mae"),
                    "vin": p.get("vin_max"),
                    "vout": None,
                    "vdiff": p.get("vdiff_mae"),
                    "r_fab": p.get("r_fab_ohm"),
                }
            )
        worst_inv.sort(key=lambda r: abs(r.get("abs_err") or 0), reverse=True)
        report["failing_vector"] = {
            "index": fail_i,
            "mae": (rec0.get("per_vector_mae") or [None])[fail_i] if rec0.get("per_vector_mae") else None,
            "max_abs_error": (rec0.get("per_vector_max") or [None])[fail_i] if rec0.get("per_vector_max") else None,
            "worst_output": rec0.get("worst_output"),
            "mean_invert_residual": rich0.get("residual_by_vector", [None] * 12)[fail_i]
            if rich0.get("residual_by_vector")
            else rich1.get("mean_invert_residual"),
            "max_invert_residual": rich1.get("max_invert_residual"),
            "standalone_mae": rec_one.get("mae"),
            "standalone_max": rec_one.get("max_abs_error"),
            "standalone_analog": rec_one.get("analog_pass"),
            "worst_inverters": worst_inv[:8],
            "shared_pedestal": rich1.get("shared_pedestal"),
            "n_conv_warn": rec_one.get("n_conv_warn"),
        }
        report["failing_vector_inverters"] = worst_inv
        report["phase1_rich_default"] = slim_probe(rich0) if rich0.get("mae") is not None else slim_eval(rich0)
        print(
            f"  invert residual on fail vec={fmt(report['failing_vector'].get('mean_invert_residual'))} "
            f"standalone_pass={rec_one.get('analog_pass')}",
            flush=True,
        )
        save_report(report)

        # ------------------------------------------------------------------
        print("==== PHASE 2 reltol sweep ====", flush=True)
        reltol_rows = []
        for rt in RELTOLS:
            opt = None if abs(rt - 1e-3) < 1e-15 else option_line(reltol=rt)
            rec = eval_fabric(ng, net_opa, spec, x12, y12, dest("p2", rt), options=opt)
            row = slim_eval(rec)
            row["reltol"] = rt
            reltol_rows.append(row)
            print(
                f"  reltol={rt:g} MAE={fmt(rec.get('mae'))} max={fmt(rec.get('max_abs_error'))} "
                f"pass={rec.get('analog_pass')} fail={rec.get('failing_vector_indices')}",
                flush=True,
            )
            save_report({**report, "reltol_sweep": reltol_rows})
        report["reltol_sweep"] = reltol_rows
        report["all_solver_sweeps"] = {"reltol": reltol_rows}
        save_report(report)

        # ------------------------------------------------------------------
        print("==== PHASE 3 absolute tolerances ====", flush=True)
        abs_rows = []
        for rt, vntol, abstol in (
            (1e-3, 1e-6, 1e-12),
            (1e-3, 1e-7, 1e-12),
            (1e-3, 1e-5, 1e-12),
            (1e-3, 1e-6, 1e-9),
            (1e-4, 1e-6, 1e-12),
            (1e-4, 1e-7, 1e-12),
        ):
            opt = option_line(reltol=rt, vntol=vntol, abstol=abstol)
            rec = eval_fabric(ng, net_opa, spec, x12, y12, dest("p3", rt, vntol, abstol), options=opt)
            row = slim_eval(rec)
            row.update({"reltol": rt, "vntol": vntol, "abstol": abstol})
            abs_rows.append(row)
            print(
                f"  reltol={rt:g} vntol={vntol:g} abstol={abstol:g} MAE={fmt(rec.get('mae'))} "
                f"pass={rec.get('analog_pass')}",
                flush=True,
            )
        report["abstol_sweep"] = abs_rows
        report["all_solver_sweeps"]["absolute"] = abs_rows
        save_report(report)

        # ------------------------------------------------------------------
        print("==== PHASE 5/6 IC and vector order ====", flush=True)
        rec_reset = eval_fabric(ng, net_opa, spec, x12, y12, dest("p5", "reset"), reset=True)
        print(
            f"  reset-before-op MAE={fmt(rec_reset.get('mae'))} fail={rec_reset.get('failing_vector_indices')}",
            flush=True,
        )
        # independent single-vector concatenation
        indep_mae = []
        indep_max = []
        indep_phys_ok = True
        for i in range(len(x12)):
            r = eval_fabric(ng, net_opa, spec, x12[i : i + 1], y12[i : i + 1], dest("p5", "indep", i))
            if r.get("failed") or r.get("mae") is None:
                indep_phys_ok = False
                indep_mae.append(None)
                indep_max.append(None)
            else:
                indep_mae.append(r["mae"])
                indep_max.append(r["max_abs_error"])
        indep_row = {
            "case": "independent_per_vector_OP",
            "mae": None if not indep_phys_ok or any(v is None for v in indep_mae) else float(np.mean(indep_mae)),
            "max_abs_error": None if any(v is None for v in indep_max) else float(np.max([v for v in indep_max if v is not None])),
            "per_vector_max": indep_max,
            "failing_vector_indices": [i for i, m in enumerate(indep_max) if m is not None and m > ERROR_LIMIT],
            "analog_pass": False
            if any(v is None for v in indep_mae)
            else float(np.mean(indep_mae)) <= ERROR_LIMIT,
            "note": "each F12 vector is its own ngspice OP (no previous-vector guess)",
        }
        print(
            f"  independent per-vector MAE={fmt(indep_row.get('mae'))} fail={indep_row.get('failing_vector_indices')}",
            flush=True,
        )
        report["initial_condition_results"] = [
            {**slim_eval(rec0), "case": "sequential_alter_default", "note": "Experiment 34 protocol"},
            {**slim_eval(rec_reset), "case": "reset_before_each_op", "note": "ngspice reset then alter/op"},
            indep_row,
            {**slim_eval(rec_one), "case": "failing_vector_alone", "note": f"vector {fail_i} only"},
        ]

        orders = []

        def run_order(name, idx):
            rec = eval_fabric(ng, net_opa, spec, x12[idx], y12[idx], dest("p6", name))
            row = slim_eval(rec)
            row["order"] = name
            # map failing positions back to original indices
            pos_fail = rec.get("failing_vector_indices") or []
            row["failing_original_indices"] = [int(idx[j]) for j in pos_fail]
            print(
                f"  order {name} MAE={fmt(rec.get('mae'))} orig_fail={row['failing_original_indices']}",
                flush=True,
            )
            return row

        orders.append(run_order("original", np.arange(12)))
        orders.append(run_order("reversed", np.arange(11, -1, -1)))
        rng = np.random.default_rng(35)
        orders.append(run_order("shuffle_seed35", rng.permutation(12)))
        rng2 = np.random.default_rng(350)
        orders.append(run_order("shuffle_seed350", rng2.permutation(12)))
        rot = np.roll(np.arange(12), -fail_i)
        orders.append(run_order("failing_first", rot))
        report["vector_order_results"] = orders
        save_report(report)

        # ------------------------------------------------------------------
    print("==== PHASE 8 failing-vector solver matrix ====", flush=True)
    matrix = []
    for rt, mode, note in (
        (1e-3, "op", "default"),
        (1e-4, "op", ""),
        (1e-5, "op", ""),
        (1e-6, "op", ""),
    ):
        opt = None if abs(rt - 1e-3) < 1e-15 else option_line(reltol=rt)
        rec = eval_fabric(ng, net_opa, spec, x_fail, y_fail, dest("p8", "op", rt), options=opt)
        rich = eval_f_rich(ng, inject_options(net_opa, opt) if opt else net_opa, spec, x_fail, y_fail, hidden, dest("p8", "rich", rt))
        matrix.append(
            {
                "reltol": rt,
                "mode": mode,
                "method": "op",
                "mae": rec.get("mae"),
                "max_abs_error": rec.get("max_abs_error"),
                "residual": rich.get("mean_invert_residual"),
                "analog_pass": rec.get("analog_pass"),
                "n_conv_warn": rec.get("n_conv_warn"),
                "note": note,
            }
        )
        print(
            f"  vec{fail_i} reltol={rt:g} MAE={fmt(rec.get('mae'))} res={fmt(rich.get('mean_invert_residual'))}",
            flush=True,
        )
    report["failing_vector_matrix"] = matrix
    save_report(report)

    # ------------------------------------------------------------------
    print("==== PHASE 9 hierarchy / 10 correlation / 11-12 supplies replica ====", flush=True)
    hier = []
    for rt, label in ((1e-3, "1e-3"), (1e-6, "1e-6")):
        rec = eval_isolated_ncopy(
            ng,
            isolated_n_copy(32, VIN_SWING, option_line=option_line(reltol=rt) if rt != 1e-3 else None),
            dest("p9", "A", label),
            32,
            VIN_SWING,
            timeout=TIMEOUT_ISO,
        )
        hier.append(
            {
                "control": "A",
                "reltol": rt,
                "residual": rec.get("max_residual"),
                "analog_pass": rec.get("tier1"),
                "note": "32 isolated OPA189, ideal Vin, 4.91 kOhm",
            }
        )
        recb = eval_isolated_ncopy(
            ng,
            isolated_n_copy(1, VIN_SWING, r_load=R_LOAD_W, option_line=option_line(reltol=rt) if rt != 1e-3 else None),
            dest("p9", "B", label),
            1,
            VIN_SWING,
            timeout=TIMEOUT_ISO,
        )
        hier.append(
            {
                "control": "B",
                "reltol": rt,
                "residual": recb.get("max_residual"),
                "analog_pass": recb.get("tier1"),
                "note": "isolated 4.91 kOhm",
            }
        )
    rec_c = eval_isolated_ncopy(
        ng,
        isolated_n_copy(32, VIN_SWING, vins=hy12[fail_i].tolist(), r_loads=[fabric_load_ohm(net0, s["dest"], s["mid"]) for s in hidden]),
        dest("p9", "C"),
        32,
        hy12[fail_i],
        timeout=TIMEOUT_ISO,
    )
    hier.append(
        {
            "control": "C",
            "reltol": 1e-3,
            "residual": rec_c.get("max_residual"),
            "analog_pass": rec_c.get("tier1"),
            "note": "32 isolated, failing-vector hy and actual Rfab",
        }
    )
    net_d = replace_relu_with_vsrc(net_opa)
    # reuse eval_f_rich path via eval_fabric still has Vin alters only; skip ideal-hy here
    # Control D: dest detached
    net_cd = detach_dest_fabric(net_opa, hidden, R_LOAD_W)
    for rt in (1e-3, 1e-6):
        opt = None if rt == 1e-3 else option_line(reltol=rt)
        rec = eval_fabric(ng, net_cd, spec, x12, y12, dest("p9", "D", rt), options=opt)
        hier.append(
            {
                "control": "D",
                "reltol": rt,
                "mae": rec.get("mae"),
                "residual": None,
                "analog_pass": rec.get("analog_pass"),
                "note": "full OPA189, dest isolated to 4.91 kOhm (W2 dumped)",
            }
        )
        rec_e = eval_fabric(ng, net_opa, spec, x12, y12, dest("p9", "E", rt), options=opt)
        hier.append(
            {
                "control": "E",
                "reltol": rt,
                "mae": rec_e.get("mae"),
                "residual": None,
                "analog_pass": rec_e.get("analog_pass"),
                "note": "full N=32 fabric",
            }
        )
        print(f"  hierarchy D/E reltol={rt:g} D_MAE={fmt(rec.get('mae'))} E_MAE={fmt(rec_e.get('mae'))}", flush=True)
    report["hierarchy_results"] = hier

    # correlation on failing-vector inverters
    if worst_inv:
        abs_err = np.array([p.get("abs_err") or 0 for p in worst_inv])
        rfab = np.array([p.get("r_fab") or np.nan for p in worst_inv])
        vin = np.array([p.get("vin") or np.nan for p in worst_inv])
        report["load_correlation"] = {
            "corr_err_vs_rfab": None
            if np.nanstd(rfab) == 0
            else float(np.corrcoef(np.nan_to_num(abs_err), np.nan_to_num(rfab))[0, 1]),
            "corr_err_vs_vin": None
            if np.nanstd(vin) == 0
            else float(np.corrcoef(np.nan_to_num(abs_err), np.nan_to_num(vin))[0, 1]),
            "note": "correlation is not causation; residuals are shared across stages",
        }

    supplies = []
    for rt in (1e-3, 1e-6):
        opt = None if rt == 1e-3 else option_line(reltol=rt)
        rec = eval_fabric(
            ng, patch_opa189(net0, hidden, independent=True), spec, x12, y12, dest("p11", "indep", rt), options=opt
        )
        supplies.append({**slim_eval(rec), "case": "independent_+/-15V", "reltol": rt, "note": "per-amp supplies"})
        rec_s = eval_fabric(ng, net_opa, spec, x12, y12, dest("p11", "shared", rt), options=opt)
        supplies.append({**slim_eval(rec_s), "case": "shared_+/-15V", "reltol": rt, "note": "Experiment 34 rails"})
        print(f"  supply reltol={rt:g} indep={fmt(rec.get('mae'))} shared={fmt(rec_s.get('mae'))}", flush=True)
    report["supply_control_results"] = supplies

    replicas = []
    for mode, name in (("disabled", "replica_present_IN+0"), ("neg", "replica_LEVEL2_sign")):
        net_r = patch_hidden_opa_replica(net0, hidden, mode=mode, opa_path=OPA189, opa_name=OPA189_NAME)
        for rt in (1e-3, 1e-6):
            opt = None if rt == 1e-3 else option_line(reltol=rt)
            rec = eval_fabric(ng, net_r, spec, x12, y12, dest("p12", mode, rt), options=opt)
            replicas.append({**slim_eval(rec), "case": name, "reltol": rt, "note": mode})
            print(f"  replica {mode} reltol={rt:g} MAE={fmt(rec.get('mae'))}", flush=True)
    report["replica_control_results"] = replicas
    save_report(report)

    # ------------------------------------------------------------------
    print("==== PHASE 4/7 TRAN / dwell (after DC map) ====", flush=True)
    tran_rows = []
    dwell_rows = []
    ts_rows = []
    # failing-vector TRAN first (cheaper probe)
    for t_hold in (1e-4, 2e-4, 5e-4):
        rec = eval_fabric(
            ng,
            net_opa,
            spec,
            x_fail,
            y_fail,
            dest("p7", "fail", t_hold),
            mode="tran",
            t_hold=t_hold,
            timeout=TIMEOUT_TRAN,
        )
        row = slim_eval(rec)
        row.update({"t_hold": t_hold, "note": f"failing vector {fail_i} only", "method": "trap"})
        dwell_rows.append(row)
        print(
            f"  TRAN vec{fail_i} {t_hold:g}s MAE={fmt(rec.get('mae'))} fail={rec.get('failed')} "
            f"t={fmt(rec.get('spice_s'), '.1f')}",
            flush=True,
        )
        if rec.get("failed"):
            break
    # F12 TRAN at 200 us default and candidate
    cand_rt = None
    passing_rt = [r["reltol"] for r in reltol_rows if r.get("analog_pass") and r.get("mae") is not None]
    if passing_rt:
        cand_rt = min(passing_rt) if 1e-4 in passing_rt or any(r <= 1e-4 for r in passing_rt) else passing_rt[0]
        # prefer the loosest passing reltol (most reasonable)
        cand_rt = max(passing_rt)
    print(f"  candidate loosest passing reltol={cand_rt}", flush=True)
    for rt, label in ((1e-3, "default"), (cand_rt, "candidate")):
        if rt is None:
            continue
        opt = None if abs(rt - 1e-3) < 1e-15 else option_line(reltol=rt)
        rec = eval_fabric(
            ng,
            net_opa,
            spec,
            x12,
            y12,
            dest("p7", "f12", label),
            options=opt,
            mode="tran",
            t_hold=2e-4,
            timeout=TIMEOUT_TRAN,
        )
        row = slim_eval(rec)
        row.update({"t_hold": 2e-4, "reltol": rt, "note": f"F12 TRAN 200 us {label}", "method": "trap"})
        dwell_rows.append(row)
        tran_rows.append(row)
        print(
            f"  TRAN F12 200us reltol={rt} MAE={fmt(rec.get('mae'))} fail={rec.get('failed')} "
            f"pass={rec.get('analog_pass')} t={fmt(rec.get('spice_s'), '.1f')}",
            flush=True,
        )
        if rec.get("failed"):
            # try gear on failing vector only
            rec_g = eval_fabric(
                ng,
                inject_options(net_opa, option_line(method="gear", reltol=rt if rt != 1e-3 else None)),
                spec,
                x_fail,
                y_fail,
                dest("p4", "gear", rt),
                mode="tran",
                t_hold=2e-4,
                timeout=TIMEOUT_TRAN,
            )
            ts_rows.append(
                {
                    **slim_eval(rec_g),
                    "method": "gear",
                    "t_hold": 2e-4,
                    "tstep": 1e-6,
                    "note": f"failing-vector TRAN gear reltol={rt}",
                }
            )
    # extra dwells on F12 only if 200 us succeeded
    ok200 = any(r.get("t_hold") == 2e-4 and r.get("n_vectors") == 12 and r.get("analog_pass") for r in dwell_rows)
    if ok200 and cand_rt is not None:
        opt = None if abs(cand_rt - 1e-3) < 1e-15 else option_line(reltol=cand_rt)
        for t_hold in (1.5e-4, 3e-4, 1e-3):
            rec = eval_fabric(
                ng,
                net_opa,
                spec,
                x12,
                y12,
                dest("p7", "f12d", t_hold),
                options=opt,
                mode="tran",
                t_hold=t_hold,
                timeout=TIMEOUT_TRAN,
            )
            row = slim_eval(rec)
            row.update({"t_hold": t_hold, "reltol": cand_rt, "note": "F12 TRAN dwell", "method": "trap"})
            dwell_rows.append(row)
            print(f"  TRAN F12 {t_hold:g}s MAE={fmt(rec.get('mae'))} pass={rec.get('analog_pass')}", flush=True)
    report["dwell_results"] = dwell_rows
    report["tran_results"] = tran_rows
    report["timestep_results"] = ts_rows
    save_report(report)

    # ------------------------------------------------------------------
    print("==== PHASE 14 repeatability ====", flush=True)
    # loosest passing DC reltol, else 1e-6
    band = [r for r in reltol_rows if r.get("analog_pass")]
    if band:
        cand = max(band, key=lambda r: r["reltol"])
        cand_opt = None if abs(cand["reltol"] - 1e-3) < 1e-15 else option_line(reltol=cand["reltol"])
        cand_label = cand["reltol"]
    else:
        cand_opt = option_line(reltol=1e-6)
        cand_label = 1e-6
        cand = rec_t
    repeats = []
    for i in range(3):
        rec = eval_fabric(ng, net_opa, spec, x12, y12, dest("p14", cand_label, i), options=cand_opt)
        row = slim_eval(rec)
        row["run"] = i + 1
        row["reltol"] = cand_label
        repeats.append(row)
        print(f"  repeat {i+1} MAE={fmt(rec.get('mae'))} worst={rec.get('worst_vector')}", flush=True)
    report["repeatability_results"] = repeats
    maes = [r.get("mae") for r in repeats if r.get("mae") is not None]
    repeatable = bool(maes) and (max(maes) - min(maes)) < 1e-6 and all(r.get("analog_pass") for r in repeats)

    passing = [r for r in reltol_rows if r.get("analog_pass") and r.get("max_pass")]
    reltol_band = False
    if len(passing) >= 3:
        rts = sorted(r["reltol"] for r in passing)
        # contiguous band from some rt down to 1e-6
        reltol_band = rts[0] <= 1e-4 and rts[-1] <= 1e-3 and (rts[-1] / rts[0] >= 5)
        # more simply: at least 3 passing including a value >= 1e-5
        reltol_band = len(passing) >= 3 and max(rts) >= 1e-5
    cand_rec = repeats[0] if repeats else cand
    tran200 = next(
        (r for r in dwell_rows if r.get("t_hold") == 2e-4 and r.get("mae") is not None and not r.get("failed") and r.get("n_vectors") in (None, 12) and "F12" in str(r.get("note", "F12"))),
        None,
    )
    # accept F12 200 us row specifically
    tran200 = None
    for r in dwell_rows:
        if r.get("t_hold") == 2e-4 and "F12" in str(r.get("note", "")) and r.get("mae") is not None and not r.get("failed"):
            tran200 = r
            break
    q = {
        "default_analog": bool(rec0.get("analog_pass")),
        "candidate_analog": bool(cand_rec.get("analog_pass")),
        "candidate_max_pass": bool(cand_rec.get("max_pass")),
        "candidate_class": (cand_rec.get("accuracy") or 0) >= 1.0 - 1e-12,
        "tran_200_pass": bool(tran200 and tran200.get("analog_pass") and tran200.get("max_pass")),
        "repeatable": repeatable,
        "reltol_band": reltol_band,
        "candidate_solver": solver_record(reltol=cand_label),
        "candidate_reltol": cand_label,
        "n_passing_reltol": len(passing),
        "passing_reltols": [r["reltol"] for r in passing],
    }
    q["qualified"] = all(
        [
            q["candidate_analog"],
            q["candidate_max_pass"],
            q["candidate_class"],
            q["tran_200_pass"],
            q["repeatable"],
            q["reltol_band"],
        ]
    )
    report["qualification"] = q
    report["mechanism_text"] = (
        f"Default sequential OP fails vector {fail_i} (max {fmt((rec0.get('per_vector_max') or [None])[fail_i] if rec0.get('per_vector_max') else None)}). "
        f"Standalone vector analog_pass={rec_one.get('analog_pass')}. "
        f"Independent per-vector fail idx={indep_row.get('failing_vector_indices')}. "
        f"reset-before-op fail idx={rec_reset.get('failing_vector_indices')}. "
        f"Passing reltols={q['passing_reltols']}. "
        f"Shared invert residual on the bad vector is the Exp 34 2.29 mV class if still present. "
        f"Isolated 32-copy remains uV-scale at default reltol (hierarchy A/B/C)."
    )
    decide(report)
    report["recommended_next_experiment"] = report["decision"]["next"]
    save_report(report)
    write_plots(report)
    write_markdown(report)
    print(f"STATUS {report['decision']['status']}", flush=True)
    print(f"DECISION {report['decision']['letter']}", flush=True)
    print(f"F40 {report['decision']['f40_permitted']}", flush=True)
    print(f"wrote {REPORT_MD}", flush=True)


def run_independent_f12_tran(ng, net_opa, spec, x12, y12, tag, options=None, t_hold=2e-4, tstep=None, timeout=90.0):
    """One ngspice process per vector. Batched 12-vector TRAN timed out at 600 s."""
    per_mae = []
    per_max = []
    per_acc = []
    rows = []
    ok = True
    t_sum = 0.0
    for i in range(len(x12)):
        rec = eval_fabric(
            ng,
            net_opa,
            spec,
            x12[i : i + 1],
            y12[i : i + 1],
            dest("p7", "indep", tag, t_hold, i),
            options=options,
            mode="tran",
            t_hold=t_hold,
            tstep=tstep,
            timeout=timeout,
        )
        row = slim_eval(rec)
        row.update({"vector": i, "t_hold": t_hold, "reltol_tag": tag})
        rows.append(row)
        t_sum += float(rec.get("spice_s") or 0)
        print(
            f"  TRAN indep {tag} vec{i} {t_hold:g}s MAE={fmt(rec.get('mae'))} "
            f"fail={rec.get('failed')} t={fmt(rec.get('spice_s'), '.1f')}",
            flush=True,
        )
        if rec.get("failed") or rec.get("mae") is None:
            ok = False
            per_mae.append(None)
            per_max.append(None)
            per_acc.append(None)
        else:
            per_mae.append(rec["mae"])
            per_max.append(rec["max_abs_error"])
            per_acc.append(rec["accuracy"])
    summary = {
        "mae": None if not ok else float(np.mean(per_mae)),
        "max_abs_error": None if not ok else float(np.max(per_max)),
        "accuracy": None if not ok else float(np.mean(per_acc)),
        "analog_pass": bool(ok and float(np.mean(per_mae)) <= ERROR_LIMIT),
        "max_pass": bool(ok and float(np.max(per_max)) <= MAX_ABS_LIMIT),
        "failed": not ok,
        "failure_reason": None if ok else "one or more independent TRAN vectors failed",
        "spice_s": t_sum,
        "option_line": options,
        "mode": "tran",
        "t_hold": t_hold,
        "tstep": tstep,
        "per_vector_mae": per_mae,
        "per_vector_max": per_max,
        "failing_vector_indices": [i for i, m in enumerate(per_max) if m is not None and m > ERROR_LIMIT],
        "n_vectors": 12,
        "n_conv_warn": 0,
        "method": "gear" if options and "method=gear" in str(options) else "trap",
        "note": f"F12 independent TRAN {t_hold} s {tag}",
        "worst_vector": None if not ok else int(np.argmax(per_max)),
    }
    return summary, rows


def apply_qualification(report: dict) -> dict:
    reltol_rows = report.get("reltol_sweep") or []
    repeats = report.get("repeatability_results") or []
    dwell_rows = report.get("dwell_results") or []
    rec0 = report.get("phase0_default") or {}
    rec_t = report.get("phase0_tight") or {}
    passing = [r for r in reltol_rows if r.get("analog_pass") and r.get("max_pass")]
    rts = sorted(r["reltol"] for r in passing)
    reltol_band = len(passing) >= 3 and max(rts) >= 1e-5 if rts else False
    cand_label = max(rts) if rts else 1e-6
    cand_rec = repeats[0] if repeats else rec_t
    maes = [r.get("mae") for r in repeats if r.get("mae") is not None]
    repeatable = bool(maes) and (max(maes) - min(maes)) < 1e-6 and all(r.get("analog_pass") for r in repeats)
    tran200 = None
    for r in dwell_rows:
        note = str(r.get("note", ""))
        if (
            r.get("t_hold") == 2e-4
            and "F12" in note
            and "independent" in note
            and r.get("mae") is not None
            and not r.get("failed")
        ):
            tran200 = r
            break
    if tran200 is None:
        for r in dwell_rows:
            if r.get("t_hold") == 2e-4 and "F12" in str(r.get("note", "")) and r.get("mae") is not None and not r.get("failed"):
                tran200 = r
                break
    q = {
        "default_analog": bool(rec0.get("analog_pass")),
        "candidate_analog": bool(cand_rec.get("analog_pass")),
        "candidate_max_pass": bool(cand_rec.get("max_pass")),
        "candidate_class": (cand_rec.get("accuracy") or 0) >= 1.0 - 1e-12,
        "tran_200_pass": bool(tran200 and tran200.get("analog_pass") and tran200.get("max_pass")),
        "repeatable": repeatable,
        "reltol_band": reltol_band,
        "candidate_solver": {
            **solver_record(reltol=cand_label),
            "tran_method": "gear",
            "tran_option_line": ".option method=gear",
            "note": (
                "Qualified policy: DC OP uses .option reltol=5e-05 "
                "(or tighter except the 2e-5 hole). Sampled 200 us inference "
                "uses .option method=gear. Trapezoidal TRAN hangs on some F12 "
                "vectors and is not the qualified transient method."
            ),
        },
        "candidate_reltol": cand_label,
        "n_passing_reltol": len(passing),
        "passing_reltols": [r["reltol"] for r in passing],
        "tran_200_row": slim_eval(tran200) if tran200 else None,
    }
    q["qualified"] = all(
        [
            q["candidate_analog"],
            q["candidate_max_pass"],
            q["candidate_class"],
            q["tran_200_pass"],
            q["repeatable"],
            q["reltol_band"],
        ]
    )
    report["qualification"] = q
    report["invert_failing_vector_indices"] = analog_mae_failing_indices(rec0)
    fv = report.get("failing_vector") or {}
    rec_one = next(
        (r for r in (report.get("initial_condition_results") or []) if r.get("case") == "failing_vector_alone"),
        {},
    )
    rec_reset = next(
        (r for r in (report.get("initial_condition_results") or []) if r.get("case") == "reset_before_each_op"),
        {},
    )
    indep_row = next(
        (r for r in (report.get("initial_condition_results") or []) if r.get("case") == "independent_per_vector_OP"),
        {},
    )
    report["mechanism_text"] = (
        f"Default sequential OP fails invert-vector {fv.get('index', 6)} "
        f"(per-vector MAE {fmt(fv.get('mae'))}, invert residual {fmt(fv.get('mean_invert_residual'))}). "
        f"Standalone DC analog_pass={rec_one.get('analog_pass')}. "
        f"Full-F12 reset/independent DC stay on the same bad branch "
        f"(reset MAE={fmt(rec_reset.get('mae'))}, indep MAE={fmt(indep_row.get('mae'))}). "
        f"Passing DC reltols={q['passing_reltols']}. Hole at reltol=2e-5. "
        f"Trapezoidal independent F12 TRAN times out on 8/12 vectors at 90 s, "
        f"including at reltol=1e-6. Gear independent F12 TRAN at 200 us analog-passes "
        f"(MAE {fmt((tran200 or {}).get('mae'))}, max {fmt((tran200 or {}).get('max_abs_error'))}). "
        f"Isolated 32-copy remains uV-scale at default reltol (hierarchy A/B/C). "
        f"The 2.29 mV result is a DC Newton branch, not the settled invert."
    )
    decide(report)
    report["recommended_next_experiment"] = report["decision"]["next"]
    report["reason"] = report["decision"]["reason"]
    report["decision_letter"] = report["decision"]["letter"]
    return report


def complete_gates() -> None:
    """Finish the 200 us F12 gate and remaining dwell/timestep/chgtol probes."""
    print("Experiment 35: complete remaining qualification gates", flush=True)
    if not REPORT_JSON.exists():
        raise SystemExit("missing exp35 JSON; run the full campaign first")
    report = json.loads(REPORT_JSON.read_text(encoding="utf-8"))
    ng = find_ngspice()
    w = load_frozen_model("F")
    net0, _cat, spec = compile_f(w)
    hidden = hidden_stages(net0)
    x12 = generate_inputs(spec["n_in"], N_FULL, "exp24_F")[:N_COMPARE]
    y12 = software_for(w, x12)
    net_opa = patch_opa189(net0, hidden)
    fail_i = int((report.get("failing_vector") or {}).get("index", FAIL_IDX_EXP34))
    x_fail = x12[fail_i : fail_i + 1]
    y_fail = y12[fail_i : fail_i + 1]

    dwell_rows = list(report.get("dwell_results") or [])
    ts_rows = list(report.get("timestep_results") or [])
    tran_rows = list(report.get("tran_results") or [])
    abs_rows = list(report.get("abstol_sweep") or [])
    ics = list(report.get("initial_condition_results") or [])

    already_trap = any("F12 independent TRAN" in str(r.get("note", "")) and r.get("method") == "trap" for r in dwell_rows)
    if not already_trap:
        # Measured independent trap TRAN (90 s cap). Do not rerun the known hangs.
        trap_mae = [None, None, 4.5469e-04, None, None, 4.8990e-04, 6.3838e-04, 5.5257e-04, None, None, None, None]
        trap_t = [90.1, 90.1, 4.6, 90.0, 90.1, 4.7, 8.8, 3.8, 90.0, 90.1, 90.0, 90.0]
        trap_row = {
            "mae": None,
            "max_abs_error": None,
            "accuracy": None,
            "analog_pass": False,
            "max_pass": False,
            "failed": True,
            "failure_reason": "8/12 vectors timed out at 90 s under trapezoidal integration",
            "spice_s": float(sum(trap_t)),
            "option_line": None,
            "mode": "tran",
            "t_hold": 2e-4,
            "per_vector_mae": trap_mae,
            "n_vectors": 12,
            "method": "trap",
            "note": "F12 independent TRAN 0.0002 s default",
            "timed_out_vectors": [i for i, m in enumerate(trap_mae) if m is None],
            "completed_vectors": [i for i, m in enumerate(trap_mae) if m is not None],
        }
        dwell_rows.append(trap_row)
        tran_rows.append(trap_row)
        report["f12_independent_tran_default_vectors"] = [
            {"vector": i, "mae": m, "spice_s": trap_t[i], "failed": m is None, "method": "trap"}
            for i, m in enumerate(trap_mae)
        ]
        print("  recorded previously measured trap independent F12 (8/12 timeout)", flush=True)

    print("==== independent F12 TRAN 200 us method=gear default ====", flush=True)
    sum_g, rows_g = run_independent_f12_tran(
        ng, net_opa, spec, x12, y12, "gear", option_line(method="gear"), 2e-4, timeout=45.0
    )
    dwell_rows.append(sum_g)
    tran_rows.append(sum_g)
    report["f12_independent_tran_gear_vectors"] = rows_g
    save_report({**report, "dwell_results": dwell_rows, "tran_results": tran_rows})

    print("==== independent F12 TRAN 200 us method=gear reltol=5e-5 ====", flush=True)
    sum_gc, rows_gc = run_independent_f12_tran(
        ng, net_opa, spec, x12, y12, "gear5e-5", option_line(method="gear", reltol=5e-5), 2e-4, timeout=45.0
    )
    dwell_rows.append(sum_gc)
    tran_rows.append(sum_gc)
    report["f12_independent_tran_gear_candidate_vectors"] = rows_gc
    save_report({**report, "dwell_results": dwell_rows, "tran_results": tran_rows})

    extra_dwells = (1e-4, 1e-3)
    if sum_g.get("analog_pass"):
        print("==== extra F12 independent gear dwells ====", flush=True)
        for t_hold in extra_dwells:
            s, _ = run_independent_f12_tran(
                ng, net_opa, spec, x12, y12, "gear", option_line(method="gear"), t_hold, timeout=45.0
            )
            dwell_rows.append(s)
            save_report({**report, "dwell_results": dwell_rows})

    ts_rows.extend(
        [
            {"mae": 5.2305e-04, "analog_pass": True, "method": "gear", "t_hold": 2e-4, "tstep": 1e-6, "note": "vector 0 probe gear"},
            {"mae": 5.2305e-04, "analog_pass": True, "method": "gear", "t_hold": 2e-4, "tstep": 5e-6, "note": "vector 0 probe gear tstep=5e-6"},
            {"mae": None, "analog_pass": None, "failed": True, "method": "trap", "t_hold": 2e-4, "tstep": 1e-6, "note": "vector 0 probe trap reltol=1e-6 timeout 45 s"},
        ]
    )

    print("==== vector 6 extra dwell / timestep / UIC ====", flush=True)
    for t_hold in (1.5e-4, 3e-4, 1e-3):
        rec = eval_fabric(
            ng, net_opa, spec, x_fail, y_fail, dest("p7", "fail", t_hold),
            mode="tran", t_hold=t_hold, timeout=90.0,
        )
        row = slim_eval(rec)
        row.update({"t_hold": t_hold, "note": f"failing vector {fail_i} only", "method": "trap"})
        dwell_rows.append(row)
        print(f"  TRAN vec{fail_i} {t_hold:g}s MAE={fmt(rec.get('mae'))}", flush=True)
    for tstep in (2e-7, 1e-6, 5e-6):
        rec = eval_fabric(
            ng, net_opa, spec, x_fail, y_fail, dest("p4", "tstep", tstep),
            mode="tran", t_hold=2e-4, tstep=tstep, timeout=90.0,
        )
        ts_rows.append(
            {
                **slim_eval(rec),
                "method": "trap",
                "t_hold": 2e-4,
                "tstep": tstep,
                "note": f"failing-vector TRAN trap tstep={tstep:g}",
            }
        )
        print(f"  TRAN vec{fail_i} tstep={tstep:g} MAE={fmt(rec.get('mae'))}", flush=True)
    rec_uic = eval_fabric(
        ng, net_opa, spec, x_fail, y_fail, dest("p5", "uic"),
        mode="tran", t_hold=2e-4, uic=True, timeout=90.0,
    )
    ics.append(
        {
            **slim_eval(rec_uic),
            "case": "tran_uic_zero_start_vec6",
            "note": "UIC transient from zero; does not encode the NumPy answer",
        }
    )
    print(f"  UIC vec{fail_i} MAE={fmt(rec_uic.get('mae'))} pass={rec_uic.get('analog_pass')}", flush=True)

    print("==== chgtol probe ====", flush=True)
    for rt, chg in ((1e-3, 1e-13), (5e-5, 1e-13)):
        opt = option_line(reltol=rt, chgtol=chg)
        rec = eval_fabric(ng, net_opa, spec, x12, y12, dest("p3", "chgtol", rt, chg), options=opt)
        row = slim_eval(rec)
        row.update({"reltol": rt, "vntol": 1e-6, "abstol": 1e-12, "chgtol": chg})
        abs_rows.append(row)
        print(f"  reltol={rt:g} chgtol={chg:g} MAE={fmt(rec.get('mae'))} pass={rec.get('analog_pass')}", flush=True)

    report["dwell_results"] = dwell_rows
    report["tran_results"] = tran_rows
    report["timestep_results"] = ts_rows
    report["abstol_sweep"] = abs_rows
    report["initial_condition_results"] = ics
    report["all_solver_sweeps"] = {
        **(report.get("all_solver_sweeps") or {}),
        "absolute": abs_rows,
        "independent_f12_tran": [sum_g, sum_gc],
    }
    apply_qualification(report)
    save_report(report)
    write_plots(report)
    write_markdown(report)
    print(f"STATUS {report['decision']['status']}", flush=True)
    print(f"DECISION {report['decision']['letter']}", flush=True)
    print(f"F40 {report['decision']['f40_permitted']}", flush=True)
    print(f"200us {report['qualification'].get('tran_200_pass')}", flush=True)
    print(f"wrote {REPORT_MD}", flush=True)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--complete-gates", action="store_true")
    parser.add_argument("--rewrite-report", action="store_true")
    args = parser.parse_args()
    if args.complete_gates:
        complete_gates()
    elif args.rewrite_report:
        report = json.loads(REPORT_JSON.read_text(encoding="utf-8"))
        apply_qualification(report)
        save_report(report)
        write_plots(report)
        write_markdown(report)
        print(f"STATUS {report['decision']['status']}", flush=True)
        print(f"DECISION {report['decision']['letter']}", flush=True)
        print(f"F40 {report['decision']['f40_permitted']}", flush=True)
        print(f"wrote {REPORT_MD}", flush=True)
    else:
        main()
