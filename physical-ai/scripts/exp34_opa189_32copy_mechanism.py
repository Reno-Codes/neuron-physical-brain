"""Experiment 34: 32-copy OPA189 residual mechanism and fabric loading isolation.

Frozen Experiment 9 weights. SPICE is the source of truth.
Does not overwrite Experiments 1-33. Does not transistorize Network F.
Does not invent MOS W/L. Does not search for another amplifier.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from compile_xor import find_ngspice
from exp32_hidden_inverter_primitive import eval_f, software_for
from hardware_constrained_compiler import load_frozen_model
from hidden_inverter_primitive import patch_hidden_opa_replica
from inverter_requirement_extraction import compile_f, hidden_stages, rank_hidden
from opa189_fabric_isolation import (
    CIRCUIT_DIR,
    ERROR_LIMIT,
    OPA189,
    OPA189_NAME,
    R_INV,
    R_LOAD_W,
    RESULTS_DIR,
    TIER1_RESIDUAL,
    TIMEOUT_ISO,
    TIMEOUT_NCOPY,
    TIMEOUT_OPA,
    VIN_SWING,
    buffer_opa_output,
    dest,
    detach_dest_fabric,
    eval_f_ideal_hy,
    eval_f_rich,
    eval_isolated_ncopy,
    eval_named_nodes,
    fabric_load_ohm,
    force_nodes_zero,
    force_r1_r2,
    hidden_sum_nodes,
    hidden_y,
    inject_options,
    isolated_n_copy,
    isolated_one_stage_from_fabric,
    output_sum_nodes,
    patch_opa189,
    replace_relu_with_vsrc,
    set_cl_cap,
    slim_probe,
)
from physical_invert import replace_inverts
from benchmark_scaling import generate_inputs


REPORT_JSON = RESULTS_DIR / "exp34_opa189_32copy_mechanism.json"
REPORT_MD = RESULTS_DIR / "exp34_opa189_32copy_mechanism.md"
N_FULL = 40
N_COMPARE = 12
VINS_ISO = (0.0, 1.0, 1.5, 2.0, VIN_SWING)


def fmt(v, spec=".4e"):
    if v is None:
        return "n/a"
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, float):
        return format(v, spec)
    return str(v)


def slim(x):
    if isinstance(x, (np.floating, np.integer)):
        return x.item()
    return x


def save_report(report: dict) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(report, indent=2, default=slim), encoding="utf-8")


def mae_row(rec, **extra):
    row = {
        k: rec.get(k)
        for k in (
            "mae",
            "max_abs_error",
            "accuracy",
            "analog_pass",
            "failed",
            "failure_reason",
            "spice_s",
            "mean_invert_residual",
            "max_invert_residual",
            "mean_vmid",
        )
    }
    row.update(extra)
    return row


def run_ncopy_grid(ng, label, shared, vins=VINS_ISO, ns=(1, 2, 4, 8, 16, 32), **kwargs):
    rows = []
    for n in ns:
        for vin in vins:
            net = isolated_n_copy(n, vin, shared_supply=shared, **kwargs)
            rec = eval_isolated_ncopy(
                ng, net, dest("ncopy", label, n, vin), n, vin, timeout=TIMEOUT_NCOPY
            )
            rec.update({"n": n, "vin": vin, "shared_supply": shared, "label": label})
            rows.append(
                {
                    "n": n,
                    "vin": vin,
                    "shared_supply": shared,
                    "mean_residual": rec.get("mean_residual"),
                    "max_residual": rec.get("max_residual"),
                    "mean_vmid": rec.get("mean_vmid"),
                    "tier1": rec.get("tier1"),
                    "failed": rec.get("failed"),
                    "failure_reason": rec.get("failure_reason"),
                    "spice_s": rec.get("spice_s"),
                    "i_vdd": rec.get("i_vdd"),
                }
            )
            print(
                f"  {label} N={n} Vin={vin:g} mean|err|={fmt(rec.get('mean_residual'))} "
                f"max={fmt(rec.get('max_residual'))} fail={rec.get('failed')}",
                flush=True,
            )
    return rows


def write_plots(report):
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    def save(fig, name):
        fig.tight_layout()
        fig.savefig(RESULTS_DIR / name, dpi=140)
        plt.close(fig)

    fig, ax = plt.subplots(figsize=(6.8, 4.3))
    for key, style, name in (
        ("reproduce_unprobed", "o-", "OPA189 fabric (unprobed MAE)"),
    ):
        rows = report.get(key) or []
        xs = [r["n"] for r in rows if r.get("mae") is not None]
        ys = [r["mae"] for r in rows if r.get("mae") is not None]
        if xs:
            ax.plot(xs, ys, style, label=name)
    ncopy = report.get("isolated_ncopy_shared") or []
    by_n = {}
    for r in ncopy:
        if r.get("max_residual") is None:
            continue
        by_n.setdefault(r["n"], []).append(r["max_residual"])
    if by_n:
        xs = sorted(by_n)
        ax.plot(xs, [max(by_n[n]) for n in xs], "s--", label="isolated N-copy max |err|")
    ax.axhline(ERROR_LIMIT, color="0.4", ls="--", label="MAE 1e-3")
    ax.set_xlabel("N")
    ax.set_ylabel("error (V)")
    ax.set_title("Experiment 34: scaling reference")
    ax.legend(fontsize=8)
    save(fig, "exp34_scaling_reference.png")

    hier = report.get("hierarchy") or []
    if hier:
        fig, ax = plt.subplots(figsize=(7.2, 4.4))
        labels = [h.get("level", "?") for h in hier]
        ys = [h.get("max_residual") or h.get("mean_invert_residual") or 0 for h in hier]
        ax.semilogy(range(len(ys)), [max(y, 1e-15) for y in ys], "o-")
        ax.set_xticks(range(len(labels)))
        ax.set_xticklabels(labels, rotation=20, ha="right", fontsize=8)
        ax.axhline(TIER1_RESIDUAL, color="0.3", ls="--")
        ax.set_ylabel("|Vout+Vin| (V)")
        ax.set_title("Experiment 34: isolated-to-fabric hierarchy")
        save(fig, "exp34_hierarchy.png")

    fb = report.get("feedback_points") or []
    if fb:
        fig, ax = plt.subplots(figsize=(6.2, 4.2))
        ax.loglog(
            [max(p["vdiff"], 1e-15) for p in fb],
            [max(p["abs_err"], 1e-15) for p in fb],
            "o",
            ms=4,
        )
        ax.set_xlabel("|V- - V+| (V)")
        ax.set_ylabel("|Vout + Vin| (V)")
        ax.set_title("Experiment 34: feedback-node correlation")
        save(fig, "exp34_feedback_correlation.png")

    load = report.get("load_sweep") or []
    if load:
        fig, ax = plt.subplots(figsize=(6.4, 4.2))
        ax.loglog(
            [r["r_load"] for r in load if r.get("abs_err") is not None],
            [max(r["abs_err"], 1e-15) for r in load if r.get("abs_err") is not None],
            "o-",
        )
        ax.axhline(TIER1_RESIDUAL, color="0.3", ls="--")
        ax.set_xlabel("Rload (Ohm)")
        ax.set_ylabel("|Vout + Vin| (V)")
        ax.set_title("Experiment 34: isolated load sweep")
        save(fig, "exp34_load_sweep.png")

    cm = report.get("common_mode") or []
    if cm:
        fig, ax = plt.subplots(figsize=(6.4, 4.2))
        ax.semilogy(
            [r["vcm"] for r in cm if r.get("loop_err") is not None],
            [max(abs(r["loop_err"]), 1e-15) for r in cm if r.get("loop_err") is not None],
            "o-",
        )
        ax.set_xlabel("IN+ common-mode (V)")
        ax.set_ylabel("|Vout + Vin - 2*Vcm| (V)")
        ax.set_title("Experiment 34: isolated common-mode")
        save(fig, "exp34_common_mode.png")

    xn = report.get("cross_neuron") or []
    if xn:
        fig, ax = plt.subplots(figsize=(6.4, 4.2))
        xs = [r.get("n_active") for r in xn if r.get("mean_invert_residual") is not None]
        ys = [r["mean_invert_residual"] for r in xn if r.get("mean_invert_residual") is not None]
        if xs:
            ax.semilogy(xs, [max(y, 1e-15) for y in ys], "o-")
        ax.set_xlabel("active hidden neurons")
        ax.set_ylabel("mean invert residual (V)")
        ax.set_title("Experiment 34: cross-neuron coupling")
        save(fig, "exp34_cross_neuron.png")

    sh = report.get("shared_nodes") or []
    if sh:
        fig, ax = plt.subplots(figsize=(6.8, 4.3))
        labels = [r["node"] for r in sh]
        ys = [r.get("mean_invert_residual") or r.get("mae") or 0 for r in sh]
        ax.semilogy(range(len(ys)), [max(float(y), 1e-15) for y in ys], "o-")
        ax.set_xticks(range(len(labels)))
        ax.set_xticklabels(labels, rotation=20, ha="right", fontsize=8)
        ax.set_ylabel("residual or MAE (V)")
        ax.set_title("Experiment 34: shared-node replacements")
        save(fig, "exp34_shared_node.png")

    bud = report.get("mechanism_budget") or []
    if bud:
        fig, ax = plt.subplots(figsize=(7.2, 4.4))
        labels = [b["mechanism"] for b in bud]
        ys = [abs(b.get("residual_V") or 0) for b in bud]
        ax.semilogy(range(len(ys)), [max(y, 1e-16) for y in ys], "o-")
        ax.set_xticks(range(len(labels)))
        ax.set_xticklabels(labels, rotation=25, ha="right", fontsize=8)
        ax.set_ylabel("residual (V)")
        ax.set_title("Experiment 34: mechanism budget")
        save(fig, "exp34_mechanism_budget.png")


def write_markdown(report):
    dec = report.get("decision") or {}
    lines = [
        "==================================================",
        "EXPERIMENT 34",
        "32-COPY OPA189 RESIDUAL MECHANISM AND FABRIC",
        "LOADING ISOLATION",
        "==================================================",
        "",
        "Frozen Experiment 9 weights. SPICE is the source of truth.",
        "Experiments 1-33 were not overwritten. No Python correction,",
        "no invented MOS W/L, no Network F in transistors.",
        "No new amplifier search.",
        "",
        f"Status: **{dec.get('status', '')}**",
        f"Decision: **{dec.get('letter', '')}**",
        "",
        "## 1. Objective",
        "",
        "Determine why an isolated OPA189 invert residual of ~0.66 uV",
        "becomes ~575 uV mean when 32 copies sit in the Architecture A",
        "hidden-inverter fabric.",
        "",
        "## 2. Experiment 33 baseline reproduction",
        "",
        "| N | MAE | max | acc | analog | mean invert residual | max invert residual |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in report.get("reproduce_unprobed") or []:
        p = (report.get("reproduce_probed") or {}).get(str(r.get("n")))
        lines.append(
            f"| {r.get('n')} | {fmt(r.get('mae'))} | {fmt(r.get('max_abs_error'))} | "
            f"{fmt(r.get('accuracy'), '.4f')} | {r.get('analog_pass')} | "
            f"{fmt((p or {}).get('mean_invert_residual'))} | "
            f"{fmt((p or {}).get('max_invert_residual'))} |"
        )
    lines += [
        "",
        "## 3. Isolated-to-fabric hierarchy",
        "",
        "| level | residual | note |",
        "| --- | --- | --- |",
    ]
    for h in report.get("hierarchy") or []:
        lines.append(
            f"| {h.get('level')} | {fmt(h.get('max_residual') or h.get('mean_invert_residual'))} | {h.get('note', '')} |"
        )
    lines += [
        "",
        "## 4. N-scaling with ideal loads",
        "",
        "| N | Vin | shared | mean |err| | max |err| | tier1 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in (report.get("isolated_ncopy_shared") or []) + (report.get("isolated_ncopy_indep") or []):
        if r.get("vin") not in (0.0, VIN_SWING) and r.get("n") not in (1, 32):
            continue
        lines.append(
            f"| {r.get('n')} | {r.get('vin')} | {r.get('shared_supply')} | "
            f"{fmt(r.get('mean_residual'))} | {fmt(r.get('max_residual'))} | {r.get('tier1')} |"
        )
    lines += [
        "",
        "If isolated N=32 stays at uV, the OPA189 model does not grow a",
        "575 uV pedestal merely from instance count.",
        "",
        "## 5. Feedback-node analysis",
        "",
    ]
    fb_sum = report.get("feedback_summary") or {}
    lines += [
        f"mean |Vout+Vin| = {fmt(fb_sum.get('mean_abs_err'))}",
        f"mean |V- - V+| = {fmt(fb_sum.get('mean_vdiff'))}",
        f"corr(|err|, |vdiff|) = {fmt(fb_sum.get('corr'))}",
        f"shared across stages = {fb_sum.get('shared_pedestal')}",
        "",
        "## 6. Input impedance analysis",
        "",
        "| case | residual | note |",
        "| --- | --- | --- |",
    ]
    for r in report.get("input_z") or []:
        lines.append(f"| {r.get('case')} | {fmt(r.get('residual'))} | {r.get('note', '')} |")
    lines += [
        "",
        "## 7. Common-mode analysis",
        "",
        "| Vcm | Vout+Vin | loop err (Vout+Vin-2 Vcm) |",
        "| --- | --- | --- |",
    ]
    for r in report.get("common_mode") or []:
        lines.append(
            f"| {r.get('vcm')} | {fmt(r.get('abs_err'))} | {fmt(r.get('loop_err'))} |"
        )
    lines += [
        "",
        "## 8. Output-load analysis",
        "",
        "| Rload | |err| | Iout |",
        "| --- | --- | --- |",
    ]
    for r in report.get("load_sweep") or []:
        lines.append(f"| {r.get('r_load')} | {fmt(r.get('abs_err'))} | {fmt(r.get('i_out'))} |")
    lines += [
        "",
        "## 9. Resistor-fabric coupling",
        "",
        "| case | residual | MAE | analog |",
        "| --- | --- | --- | --- |",
    ]
    for r in report.get("fabric_cases") or []:
        lines.append(
            f"| {r.get('case')} | {fmt(r.get('mean_invert_residual'))} | "
            f"{fmt(r.get('mae'))} | {r.get('analog_pass')} |"
        )
    lines += [
        "",
        "## 10. Cross-neuron coupling",
        "",
        "| n_active | residual | MAE | note |",
        "| --- | --- | --- | --- |",
    ]
    for r in report.get("cross_neuron") or []:
        lines.append(
            f"| {r.get('n_active')} | {fmt(r.get('mean_invert_residual'))} | "
            f"{fmt(r.get('mae'))} | {r.get('note', '')} |"
        )
    lines += [
        "",
        "## 11. Shared reference/bias analysis",
        "",
        "| node | residual | MAE |",
        "| --- | --- | --- |",
    ]
    for r in report.get("shared_nodes") or []:
        lines.append(
            f"| {r.get('node')} | {fmt(r.get('mean_invert_residual'))} | {fmt(r.get('mae'))} |"
        )
    lines += [
        "",
        "## 12. Replica interaction",
        "",
        "| case | residual | MAE | analog |",
        "| --- | --- | --- | --- |",
    ]
    for r in report.get("replica") or []:
        lines.append(
            f"| {r.get('case')} | {fmt(r.get('mean_invert_residual'))} | "
            f"{fmt(r.get('mae'))} | {r.get('analog_pass')} |"
        )
    lines += [
        "",
        "## 13. Capacitive effects",
        "",
        "| Ccl | DC |err| | 200 us |err| |",
        "| --- | --- | --- |",
    ]
    for r in report.get("capacitance") or []:
        lines.append(
            f"| {r.get('cl_f')} | {fmt(r.get('dc_err'))} | {fmt(r.get('tran_err'))} |"
        )
    lines += [
        "",
        "## 14. Numerical/model diagnostics",
        "",
        "| where | reltol | residual | MAE | analog |",
        "| --- | --- | --- | --- | --- |",
    ]
    for r in report.get("numerical") or []:
        lines.append(
            f"| {r.get('where')} | {r.get('reltol')} | {fmt(r.get('residual'))} | "
            f"{fmt(r.get('mae'))} | {r.get('analog_pass')} |"
        )
    lines += [
        "",
        "## 15. Mechanism attribution",
        "",
        "| mechanism | residual contribution |",
        "| --- | --- |",
    ]
    for b in report.get("mechanism_budget") or []:
        lines.append(f"| {b.get('mechanism')} | {fmt(b.get('residual_V'))} |")
    lines += [
        "",
        f"Dominant: {dec.get('dominant_mechanism', '')}",
        "",
        "## 16. Mitigation experiment",
        "",
        "| mitigation | residual | N=32 MAE | analog | note |",
        "| --- | --- | --- | --- | --- |",
    ]
    for r in report.get("mitigation") or []:
        lines.append(
            f"| {r.get('name')} | {fmt(r.get('mean_invert_residual'))} | "
            f"{fmt(r.get('mae'))} | {r.get('analog_pass')} | {r.get('note', '')} |"
        )
    n32 = report.get("n32_validation") or {}
    f12 = report.get("f12") or {}
    lines += [
        "",
        "## 17. N=32 validation",
        "",
        f"MAE={fmt(n32.get('mae'))} analog={n32.get('analog_pass')} "
        f"residual={fmt(n32.get('mean_invert_residual'))}",
        "",
        "## 18. F12 result",
        "",
        f"MAE={fmt(f12.get('mae'))} acc={fmt(f12.get('accuracy'), '.4f')} "
        f"analog={f12.get('analog_pass')}",
        "",
        "## 19. F40 gate status",
        "",
        report.get("f40_gate", "F40 not earned; N=32 F12 did not pass."),
        "",
        "## 20. Power",
        "",
    ]
    pwr = report.get("power") or {}
    lines += [
        f"one primitive ~ {fmt(pwr.get('p_one_W'))} W (macromodel Iq, +/-15 V).",
        f"32 hidden estimate ~ {fmt(pwr.get('p_32_W'))} W. Not full-F silicon.",
        "",
        "## 21. Realism level",
        "",
        dec.get("realism_level", "LEVEL 3 vendor macromodel"),
        "",
        "## 22. Remaining ideal blocks",
        "",
        dec.get("remaining_ideal", "TIA VCVS, ReLU B-source, stimulus sources."),
        "",
        "## 23. Limitations",
        "",
        dec.get("limitations", ""),
        "",
        "## 24. Experiment 35 recommendation",
        "",
        dec.get("next", ""),
        "",
        "## 25. Final status",
        "",
        f"**{dec.get('letter', '')} — {dec.get('status', '')}**",
        "",
        dec.get("reason", ""),
        "",
        "JSON: `results/exp34_opa189_32copy_mechanism.json`.",
        "Circuits: `circuits/exp34_opa189_32copy_mechanism/`.",
        "Scripts: `scripts/exp34_opa189_32copy_mechanism.py`,",
        "`scripts/opa189_fabric_isolation.py`.",
        "",
    ]
    REPORT_MD.write_text("\n".join(lines), encoding="utf-8")


def decide(report):
    iso32 = [
        r
        for r in (report.get("isolated_ncopy_shared") or [])
        if r.get("n") == 32 and r.get("max_residual") is not None
    ]
    iso32_max = max((r["max_residual"] for r in iso32), default=None)
    n32 = report.get("n32_validation") or {}
    mit_pass = any(r.get("analog_pass") for r in (report.get("mitigation") or []) if r.get("physical"))
    num = report.get("numerical") or []
    fab_num = [r for r in num if r.get("where") == "fabric_n32" and r.get("mae") is not None]
    num_sensitive = False
    if len(fab_num) >= 2:
        maes = [r["mae"] for r in fab_num]
        num_sensitive = max(maes) > 0 and (max(maes) - min(maes)) / max(maes) > 0.25
    cases = {c.get("case"): c for c in (report.get("fabric_cases") or [])}
    e_res = (cases.get("E") or {}).get("mean_invert_residual")
    c_res = (cases.get("C") or {}).get("mean_invert_residual")
    a_res = (cases.get("A") or {}).get("mean_invert_residual")
    fb = report.get("feedback_summary") or {}
    replica = report.get("replica") or []
    replica_shift = False
    if replica:
        base = next((r for r in replica if r.get("case") == "A"), None)
        for r in replica:
            if base and r is not base and r.get("mean_invert_residual") and base.get("mean_invert_residual"):
                if abs(r["mean_invert_residual"] - base["mean_invert_residual"]) > 50e-6:
                    replica_shift = True
    n32_pass = bool(n32.get("analog_pass")) and (n32.get("mae") or 1) <= ERROR_LIMIT

    letter = "E"
    dominant = "no single physical mechanism isolated"
    if n32_pass and mit_pass:
        letter = "F"
        dominant = "N=32 physical inverter integration validated"
    elif num_sensitive:
        letter = "E"
        dominant = (
            "numerical / GWL OP of the coupled fabric (same topology; "
            "reltol changes residual; not promoted)"
        )
    elif iso32_max is not None and iso32_max > 50e-6:
        letter = "B"
        dominant = "multi-instance OPA189 model interaction"
    elif e_res and c_res and c_res < 0.2 * e_res:
        letter = "A"
        dominant = "fabric / dest loading"
    elif a_res and e_res and a_res < 0.2 * e_res:
        letter = "A"
        dominant = "hidden-input / ReLU-fabric drive"
    elif (fb.get("corr") or 0) > 0.85 and (fb.get("mean_vdiff") or 0) > 50e-6:
        letter = "C"
        dominant = "common-mode / feedback-node displacement"
    elif replica_shift:
        letter = "D"
        dominant = "replica / reference network"

    status = (
        "N=32 PHYSICAL INVERTER INTEGRATION VALIDATED"
        if letter == "F"
        else "PHYSICAL HIDDEN INVERTER PARTIALLY VALIDATED"
    )
    if letter == "A":
        title = "FABRIC LOADING IS THE DOMINANT BOTTLENECK"
    elif letter == "B":
        title = "MULTI-INSTANCE MODEL INTERACTION IS THE DOMINANT BOTTLENECK"
    elif letter == "C":
        title = "COMMON-MODE / FEEDBACK INTERACTION IS THE DOMINANT BOTTLENECK"
    elif letter == "D":
        title = "REPLICA / REFERENCE NETWORK IS THE DOMINANT BOTTLENECK"
    elif letter == "F":
        title = "N=32 PHYSICAL INVERTER INTEGRATION VALIDATED"
    else:
        title = "NO SINGLE MECHANISM IDENTIFIED; FURTHER PHYSICAL MODEL IS REQUIRED"

    report["decision"] = {
        "letter": f"{letter}. {title}",
        "status": status,
        "dominant_mechanism": dominant,
        "reason": (
            f"Isolated N=32 max residual {fmt(iso32_max)}. "
            f"Fabric N=32 MAE {fmt(n32.get('mae'))} residual "
            f"{fmt(n32.get('mean_invert_residual'))}. "
            f"Numerical sensitivity={num_sensitive}. "
            f"Dominant: {dominant}."
        ),
        "realism_level": "LEVEL 3 vendor macromodel (GWL, static Vos)",
        "remaining_ideal": "TIA VCVS, ReLU B-source unless replaced as a diagnostic, stimulus sources.",
        "limitations": (
            "Not silicon. Not a PDK. Solver-tolerance changes are diagnostic only "
            "and do not promote a pass. A LEVEL 2 dest buffer is not a physical primitive."
        ),
        "next": (
            "If the 575 uV pedestal is fabric loading, the next experiment is a "
            "documented physical dest isolation / buffer, not another op-amp search. "
            "If it is numerical/GWL, the next experiment is a documented model whose "
            "multi-instance OP is trustworthy, or a PDK primitive. Do not invent MOS."
        ),
    }
    return report


def main():
    print("Experiment 34: 32-copy OPA189 residual mechanism", flush=True)
    ng = find_ngspice()
    if not OPA189.exists():
        raise SystemExit(f"OPA189 missing: {OPA189}")
    w = load_frozen_model("F")
    net0, _cat, spec = compile_f(w)
    hidden = hidden_stages(net0)
    x40 = generate_inputs(spec["n_in"], N_FULL, "exp24_F")
    x12 = x40[:N_COMPARE]
    y12 = software_for(w, x12)
    hy40 = hidden_y(w, x40)
    hy12 = hidden_y(w, x12)
    ranked = rank_hidden(hidden, hy40, "hy_max")
    worst = ranked[0]
    r_fabs = [fabric_load_ohm(net0, s["dest"], s["mid"]) for s in hidden]
    print(
        f"  hidden={len(hidden)} worst={worst['stem']} hy_max={float(np.max(hy40)):.4f} "
        f"Rfab min={min(r_fabs):.1f} worst_stage_Rfab={fabric_load_ohm(net0, worst['dest'], worst['mid']):.1f}",
        flush=True,
    )

    report = {
        "experiment": 34,
        "spice_source_of_truth": True,
        "network_f_transistorized": False,
        "python_correction": False,
        "frozen_weights_edited": False,
        "vendor_models_edited": False,
        "pdk_installed": False,
        "worst_stage": {
            "stem": worst["stem"],
            "r_load_ohm": worst.get("r_load_ohm"),
            "r_fab_ohm": fabric_load_ohm(net0, worst["dest"], worst["mid"]),
            "hy_max": worst.get("hy_max"),
        },
        "r_fab_min_ohm": min(r_fabs),
        "r_fab_max_ohm": max(r_fabs),
    }
    save_report(report)

    # ------------------------------------------------------------------
    print("==== PHASE 1 reproduce Exp33 OPA189 N-scale ====", flush=True)
    unprobed = []
    probed_map = {}
    for n in (1, 8, 16, 32):
        subset = hidden if n == 32 else ranked[:n]
        net_n = patch_opa189(net0, subset)
        rec = eval_f(ng, net_n, spec, x12, y12, dest("f", "repro", n), timeout=TIMEOUT_OPA, pspice=True)
        rec["n"] = n
        unprobed.append(mae_row(rec, n=n))
        print(f"  unprobed N={n} MAE={fmt(rec.get('mae'))} pass={rec.get('analog_pass')}", flush=True)
        if n in (1, 16, 32):
            rich = eval_f_rich(
                ng,
                net_n,
                spec,
                x12,
                y12,
                subset,
                dest("f", "repro_p", n),
                sum_nodes=output_sum_nodes(spec["n_out"]) if n == 32 else None,
            )
            probed_map[str(n)] = slim_probe(rich)
            print(
                f"  probed N={n} MAE={fmt(rich.get('mae'))} mean_res={fmt(rich.get('mean_invert_residual'))} "
                f"max_res={fmt(rich.get('max_invert_residual'))} shared={rich.get('shared_pedestal')}",
                flush=True,
            )
            if n == 32:
                report["n32_nodes"] = {
                    "residual_by_vector": rich.get("residual_by_vector"),
                    "sum_nodes": rich.get("sum_nodes"),
                    "worst_probes": (slim_probe(rich).get("worst_probes")),
                    "shared_pedestal": rich.get("shared_pedestal"),
                    "residual_std_across_stages": rich.get("residual_std_across_stages"),
                }
                fb_pts = []
                for p in rich.get("probes") or []:
                    fb_pts.append(
                        {
                            "stem": p["stem"],
                            "abs_err": p["err_mae"],
                            "vdiff": p.get("vdiff_mae") or p.get("vmid_mae") or 0.0,
                        }
                    )
                report["feedback_points"] = fb_pts
                if fb_pts:
                    ae = np.array([p["abs_err"] for p in fb_pts])
                    vd = np.array([p["vdiff"] for p in fb_pts])
                    corr = None
                    if len(ae) > 2 and float(np.std(ae)) > 0 and float(np.std(vd)) > 0:
                        corr = float(np.corrcoef(ae, vd)[0, 1])
                    report["feedback_summary"] = {
                        "mean_abs_err": float(np.mean(ae)),
                        "mean_vdiff": float(np.mean(vd)),
                        "corr": corr,
                        "shared_pedestal": rich.get("shared_pedestal"),
                    }
    report["reproduce_unprobed"] = unprobed
    report["reproduce_probed"] = probed_map
    n32_base = next((r for r in unprobed if r.get("n") == 32), {})
    report["n32_validation"] = n32_base
    report["f12"] = n32_base
    save_report(report)

    # ------------------------------------------------------------------
    print("==== PHASE 2 isolated multi-instance ideal-load control ====", flush=True)
    report["isolated_ncopy_shared"] = run_ncopy_grid(ng, "shared", True)
    report["isolated_ncopy_indep"] = run_ncopy_grid(
        ng, "indep", False, vins=(0.0, VIN_SWING), ns=(1, 8, 32)
    )
    actual_loads = [fabric_load_ohm(net0, s["dest"], s["mid"]) for s in hidden]
    hy_vec = hy12[int(np.argmax(np.max(hy12, axis=1)))]
    net_act = isolated_n_copy(
        32,
        0.0,
        shared_supply=True,
        vins=hy_vec.tolist(),
        r_loads=actual_loads,
    )
    rec_act = eval_isolated_ncopy(ng, net_act, dest("ncopy", "actual_hy_load"), 32, hy_vec)
    report["isolated_ncopy_actual_hy_load"] = {
        "mean_residual": rec_act.get("mean_residual"),
        "max_residual": rec_act.get("max_residual"),
        "mean_vmid": rec_act.get("mean_vmid"),
        "failed": rec_act.get("failed"),
        "note": "32 isolated OPA189, software hy and actual dest Rfab, no neural coupling",
    }
    print(
        f"  actual hy+Rfab N=32 mean|err|={fmt(rec_act.get('mean_residual'))} "
        f"max={fmt(rec_act.get('max_residual'))}",
        flush=True,
    )
    save_report(report)

    # ------------------------------------------------------------------
    print("==== PHASE 3 hierarchy ====", flush=True)
    hierarchy = []
    for level, vin, rl, note in (
        ("L0_noload", VIN_SWING, 1e9, "isolated, almost no load"),
        ("L1_4k91", VIN_SWING, R_LOAD_W, "isolated representative 4.91 kOhm"),
    ):
        rec = eval_isolated_ncopy(
            ng,
            isolated_n_copy(1, vin, r_load=rl),
            dest("hier", level),
            1,
            vin,
        )
        hierarchy.append(
            {
                "level": level,
                "max_residual": rec.get("max_residual"),
                "mean_residual": rec.get("mean_residual"),
                "note": note,
                "failed": rec.get("failed"),
            }
        )
        print(f"  {level} |err|={fmt(rec.get('max_residual'))}", flush=True)

    for far_v, name in ((0.0, "L2_actualR_far0"), (500e-6, "L2_actualR_far500uV")):
        rec = eval_named_nodes(
            ng,
            isolated_one_stage_from_fabric(net0, worst, VIN_SWING, far_v=far_v),
            dest("hier", name),
            VIN_SWING,
            worst["dest"],
            worst["mid"],
            worst["src"],
        )
        hierarchy.append(
            {
                "level": name,
                "max_residual": rec.get("abs_err"),
                "note": f"one stage actual dest R, far={far_v:g} V, Vin=2.61",
                "failed": rec.get("failed"),
            }
        )
        print(f"  {name} |err|={fmt(rec.get('abs_err'))}", flush=True)

    hierarchy.append(
        {
            "level": "L3_ncopy_actual",
            "max_residual": rec_act.get("max_residual"),
            "mean_invert_residual": rec_act.get("mean_residual"),
            "note": "32 isolated copies, actual hy and Rfab",
        }
    )
    p32 = probed_map.get("32") or {}
    hierarchy.append(
        {
            "level": "L4_fabric32",
            "max_residual": p32.get("max_invert_residual"),
            "mean_invert_residual": p32.get("mean_invert_residual"),
            "note": "all 32 OPA189 in frozen Network F fabric",
        }
    )
    report["hierarchy"] = hierarchy
    save_report(report)

    # ------------------------------------------------------------------
    print("==== PHASE 4 fabric replacement A-E ====", flush=True)
    fabric_cases = []
    net_opa = patch_opa189(net0, hidden)

    net_a = replace_relu_with_vsrc(net_opa)
    rec_a = eval_f_ideal_hy(ng, net_a, spec, x12, y12, hy12, hidden, dest("fab", "A"))
    fabric_cases.append({**mae_row(rec_a), "case": "A", "note": "ideal hy V-sources, real invert R, real dest fabric"})
    print(f"  CASE A residual={fmt(rec_a.get('mean_invert_residual'))} MAE={fmt(rec_a.get('mae'))}", flush=True)

    net_b = force_r1_r2(net_opa, hidden, R_INV, R_INV)
    rec_b = eval_f_rich(ng, net_b, spec, x12, y12, hidden, dest("fab", "B"))
    fabric_cases.append({**mae_row(rec_b), "case": "B", "note": "ideal R1=R2=10k, real hidden src"})
    print(f"  CASE B residual={fmt(rec_b.get('mean_invert_residual'))} MAE={fmt(rec_b.get('mae'))}", flush=True)

    net_c = detach_dest_fabric(net_opa, hidden, R_LOAD_W)
    rec_c = eval_f_rich(ng, net_c, spec, x12, y12, hidden, dest("fab", "C"))
    fabric_cases.append({**mae_row(rec_c), "case": "C", "note": "real R1/R2, dest isolated to 4.91 kOhm"})
    print(f"  CASE C residual={fmt(rec_c.get('mean_invert_residual'))} MAE={fmt(rec_c.get('mae'))}", flush=True)

    net_d = detach_dest_fabric(replace_relu_with_vsrc(net_opa), hidden, R_LOAD_W)
    rec_d = eval_f_ideal_hy(ng, net_d, spec, x12, y12, hy12, hidden, dest("fab", "D"))
    fabric_cases.append({**mae_row(rec_d), "case": "D", "note": "ideal hy + dest 4.91 kOhm"})
    print(f"  CASE D residual={fmt(rec_d.get('mean_invert_residual'))} MAE={fmt(rec_d.get('mae'))}", flush=True)

    rec_e = probed_map.get("32") or {}
    fabric_cases.append(
        {
            "case": "E",
            "mae": rec_e.get("mae"),
            "analog_pass": rec_e.get("analog_pass"),
            "mean_invert_residual": rec_e.get("mean_invert_residual"),
            "max_invert_residual": rec_e.get("max_invert_residual"),
            "note": "complete actual fabric (phase 1 probe)",
        }
    )
    report["fabric_cases"] = fabric_cases
    save_report(report)

    # ------------------------------------------------------------------
    print("==== PHASE 5 input Z / CM / load / cap / numerical isolated ====", flush=True)
    inz = []
    for rs, name in ((0.0, "ideal_Vsrc_Rs=0"), (100.0, "Rs=100"), (1000.0, "Rs=1k"), (10_000.0, "Rs=10k")):
        rec = eval_isolated_ncopy(
            ng,
            isolated_n_copy(1, VIN_SWING, r_src=rs),
            dest("inz", rs),
            1,
            VIN_SWING,
        )
        copies = rec.get("copies") or []
        cmd = abs(copies[0]["v_out"] + VIN_SWING) if copies else rec.get("max_residual")
        inz.append({"case": name, "residual": cmd, "note": "isolated; residual vs commanded Vin"})
    inz.append(
        {
            "case": "CASE_A_ideal_hy_in_fabric",
            "residual": rec_a.get("mean_invert_residual"),
            "note": "fabric, ReLU replaced by V",
        }
    )
    inz.append(
        {
            "case": "CASE_E_relu_drive",
            "residual": rec_e.get("mean_invert_residual"),
            "note": "fabric, actual ReLU B-source",
        }
    )
    report["input_z"] = inz

    cm_rows = []
    for vcm in (-1.0, -0.1, 0.0, 100e-6, 500e-6, 0.01, 0.1, 1.0):
        rec = eval_isolated_ncopy(
            ng,
            isolated_n_copy(1, VIN_SWING, vcm=vcm),
            dest("cm", vcm),
            1,
            VIN_SWING,
        )
        abs_err = rec.get("max_residual")
        copies = rec.get("copies") or []
        vout_plus_vin = copies[0]["v_out"] + copies[0]["vin"] if copies else None
        loop = None if vout_plus_vin is None else vout_plus_vin - 2.0 * vcm
        cm_rows.append(
            {
                "vcm": vcm,
                "abs_err": abs_err,
                "loop_err": None if loop is None else abs(loop),
                "failed": rec.get("failed"),
            }
        )
        print(f"  CM {vcm:g} |Vout+Vin|={fmt(abs_err)} loop={fmt(None if loop is None else abs(loop))}", flush=True)
    report["common_mode"] = cm_rows

    load_rows = []
    for rl in (100e3, 10e3, R_LOAD_W, 2e3, 1e3):
        rec = eval_isolated_ncopy(
            ng, isolated_n_copy(1, VIN_SWING, r_load=rl), dest("load", rl), 1, VIN_SWING
        )
        iout = None
        if rec.get("copies"):
            iout = abs(rec["copies"][0]["v_out"]) / rl
        load_rows.append({"r_load": rl, "abs_err": rec.get("max_residual"), "i_out": iout})
        print(f"  Rload={rl:g} |err|={fmt(rec.get('max_residual'))}", flush=True)
    report["load_sweep"] = load_rows

    cap_rows = []
    for cl in (0.0, 0.1e-12, 1e-12, 10e-12):
        rec_dc = eval_isolated_ncopy(
            ng, isolated_n_copy(1, VIN_SWING, cl_f=max(cl, 1e-18)), dest("cldc", cl), 1, VIN_SWING
        )
        rec_tr = eval_isolated_ncopy(
            ng,
            isolated_n_copy(1, VIN_SWING, cl_f=max(cl, 1e-18), t_hold=200e-6),
            dest("cltr", cl),
            1,
            VIN_SWING,
        )
        cap_rows.append(
            {
                "cl_f": cl,
                "dc_err": rec_dc.get("max_residual"),
                "tran_err": rec_tr.get("max_residual"),
            }
        )
        print(f"  Ccl={cl:g} DC={fmt(rec_dc.get('max_residual'))} TRAN={fmt(rec_tr.get('max_residual'))}", flush=True)
    report["capacitance"] = cap_rows

    num_rows = []
    for reltol in (1e-3, 1e-4, 1e-6):
        rec = eval_isolated_ncopy(
            ng,
            isolated_n_copy(32, VIN_SWING, option_line=f".option reltol={reltol:g}"),
            dest("num", "iso32", reltol),
            32,
            VIN_SWING,
        )
        num_rows.append(
            {
                "where": "isolated_n32",
                "reltol": reltol,
                "residual": rec.get("max_residual"),
                "mae": None,
                "analog_pass": rec.get("tier1"),
            }
        )
        print(f"  iso32 reltol={reltol:g} max|err|={fmt(rec.get('max_residual'))}", flush=True)
    report["numerical"] = num_rows
    save_report(report)

    # ------------------------------------------------------------------
    print("==== PHASE 6 cross-neuron / shared node / replica ====", flush=True)
    cross = []
    for n in (1, 8, 16, 32):
        p = probed_map.get(str(n))
        if n == 8:
            net_n = patch_opa189(net0, ranked[:8])
            rich = eval_f_rich(ng, net_n, spec, x12, y12, ranked[:8], dest("xn", 8))
            p = slim_probe(rich)
        if p:
            cross.append(
                {
                    "n_active": n,
                    "mean_invert_residual": p.get("mean_invert_residual"),
                    "mae": p.get("mae"),
                    "note": "OPA on N worst; others remain VCVS",
                }
            )
    # 32 OPA present, only worst neuron live
    live_tag = f"h{int(worst['stem'].replace('invh', ''))}"
    zero_tags = {f"h{j}" for j in range(1, 33)} - {live_tag}
    net_quiet = replace_relu_with_vsrc(net_opa, zero_tags)
    rec_q = eval_f_rich(ng, net_quiet, spec, x12, y12, hidden, dest("xn", "quiet"))
    cross.append(
        {
            "n_active": 1,
            "mean_invert_residual": rec_q.get("mean_invert_residual"),
            "mae": rec_q.get("mae"),
            "note": "32 OPA present; only worst ReLU live, others hy=0",
        }
    )
    print(f"  quiet-others residual={fmt(rec_q.get('mean_invert_residual'))} MAE={fmt(rec_q.get('mae'))}", flush=True)
    report["cross_neuron"] = cross

    shared = []
    shared.append(
        {
            "node": "baseline_shared_vdd",
            "mean_invert_residual": rec_e.get("mean_invert_residual"),
            "mae": n32_base.get("mae"),
        }
    )
    rec_ind = eval_f(
        ng,
        patch_opa189(net0, hidden, independent=True),
        spec,
        x12,
        y12,
        dest("f", "indep32"),
        timeout=TIMEOUT_OPA,
        pspice=True,
    )
    shared.append({"node": "independent_+/-15V", "mae": rec_ind.get("mae"), "mean_invert_residual": None})
    print(f"  indep supplies MAE={fmt(rec_ind.get('mae'))}", flush=True)
    net_vg = force_nodes_zero(net_opa, output_sum_nodes(spec["n_out"]), prefix="vgout")
    rec_vg = eval_f_rich(ng, net_vg, spec, x12, y12, hidden, dest("share", "vgout"))
    shared.append(
        {
            "node": "output_summing_nodes_forced_0",
            "mean_invert_residual": rec_vg.get("mean_invert_residual"),
            "mae": rec_vg.get("mae"),
        }
    )
    print(f"  force o*p=0 residual={fmt(rec_vg.get('mean_invert_residual'))}", flush=True)
    net_hg = force_nodes_zero(net_opa, hidden_sum_nodes(32), prefix="vghid")
    rec_hg = eval_f_rich(ng, net_hg, spec, x12, y12, hidden, dest("share", "vghid"))
    shared.append(
        {
            "node": "hidden_summing_nodes_forced_0",
            "mean_invert_residual": rec_hg.get("mean_invert_residual"),
            "mae": rec_hg.get("mae"),
        }
    )
    print(f"  force h*p=0 residual={fmt(rec_hg.get('mean_invert_residual'))}", flush=True)
    report["shared_nodes"] = shared

    replica = []
    replica.append({**mae_row(rec_e), "case": "A", "note": "no replica (phase 1)"})
    # reuse phase-1 E as case A; run B and C
    rec_rb = eval_f(
        ng,
        patch_hidden_opa_replica(net0, hidden, mode="disabled", opa_path=OPA189, opa_name=OPA189_NAME),
        spec,
        x12,
        y12,
        dest("rep", "B"),
        timeout=TIMEOUT_OPA,
        pspice=True,
    )
    replica.append({**mae_row(rec_rb), "case": "B", "note": "replica present, IN+=0"})
    print(f"  replica B MAE={fmt(rec_rb.get('mae'))}", flush=True)
    rec_rc = eval_f(
        ng,
        patch_hidden_opa_replica(net0, hidden, mode="neg", opa_path=OPA189, opa_name=OPA189_NAME),
        spec,
        x12,
        y12,
        dest("rep", "C"),
        timeout=TIMEOUT_OPA,
        pspice=True,
    )
    replica.append({**mae_row(rec_rc), "case": "C", "note": "replica + LEVEL 2 sign"})
    print(f"  replica C MAE={fmt(rec_rc.get('mae'))}", flush=True)
    replica.append(
        {
            "case": "D",
            "mae": None,
            "mean_invert_residual": None,
            "note": "physical OPA189 sign was isolated-only in Exp 33; not inserted at N=32",
        }
    )
    report["replica"] = replica
    save_report(report)

    # ------------------------------------------------------------------
    print("==== PHASE 7 fabric numerical + capacitance-on-fabric ====", flush=True)
    for reltol in (1e-3, 1e-6):
        net_t = inject_options(net_opa, f".option reltol={reltol:g}")
        rec_t = eval_f(ng, net_t, spec, x12, y12, dest("num", "fab", reltol), timeout=TIMEOUT_OPA, pspice=True)
        rich_t = None
        if not rec_t.get("failed"):
            rich_t = eval_f_rich(ng, net_t, spec, x12, y12, hidden, dest("num", "fabp", reltol))
        num_rows.append(
            {
                "where": "fabric_n32",
                "reltol": reltol,
                "residual": None if not rich_t else rich_t.get("mean_invert_residual"),
                "mae": rec_t.get("mae"),
                "analog_pass": rec_t.get("analog_pass"),
                "failed": rec_t.get("failed"),
            }
        )
        print(
            f"  fabric reltol={reltol:g} MAE={fmt(rec_t.get('mae'))} "
            f"res={fmt(None if not rich_t else rich_t.get('mean_invert_residual'))}",
            flush=True,
        )
    report["numerical"] = num_rows
    net_c0 = set_cl_cap(net_opa, 1e-18)
    rec_c0 = eval_f(ng, net_c0, spec, x12, y12, dest("cl", "fab0"), timeout=TIMEOUT_OPA, pspice=True)
    cap_rows.append(
        {
            "cl_f": 0.0,
            "dc_err": rec_c0.get("mae"),
            "tran_err": None,
            "note": "fabric N=32 Ccl~0, MAE listed in dc_err",
        }
    )
    report["capacitance"] = cap_rows
    save_report(report)

    # ------------------------------------------------------------------
    print("==== PHASE 8 mitigation ====", flush=True)
    mitigations = []
    net_buf = buffer_opa_output(net_opa, hidden)
    rec_buf = eval_f(ng, net_buf, spec, x12, y12, dest("mit", "buf"), timeout=TIMEOUT_OPA, pspice=True)
    rich_buf = eval_f_rich(ng, net_buf, spec, x12, y12, hidden, dest("mit", "bufp")) if not rec_buf.get("failed") else {}
    mitigations.append(
        {
            "name": "LEVEL2 dest VCVS buffer",
            **mae_row(rec_buf),
            "mean_invert_residual": rich_buf.get("mean_invert_residual"),
            "physical": False,
            "note": "OPA sees only R2/Ccl; fabric sees buffered dest. Not a physical primitive.",
        }
    )
    print(
        f"  dest buffer MAE={fmt(rec_buf.get('mae'))} res={fmt(rich_buf.get('mean_invert_residual'))} "
        f"pass={rec_buf.get('analog_pass')}",
        flush=True,
    )
    net_rr = force_r1_r2(net_opa, hidden, R_INV, R_INV)
    rec_rr = eval_f(ng, net_rr, spec, x12, y12, dest("mit", "r1r2"), timeout=TIMEOUT_OPA, pspice=True)
    mitigations.append({**mae_row(rec_rr), "name": "force R1=R2=10k", "physical": True, "note": "topology-preserving ratio"})
    print(f"  R1=R2 MAE={fmt(rec_rr.get('mae'))}", flush=True)
    report["mitigation"] = mitigations
    if rec_buf.get("analog_pass"):
        report["n32_validation"] = {**mae_row(rec_buf), "mean_invert_residual": rich_buf.get("mean_invert_residual")}
        report["f12"] = report["n32_validation"]
        report["f40_gate"] = (
            "N=32 F12 analog-pass only with a LEVEL 2 dest buffer. "
            "That is not a physical primitive, so F40 is not earned."
        )
    else:
        report["f40_gate"] = "F40 not earned; uncorrected N=32 F12 did not analog-pass."
    save_report(report)

    # power
    iso_p = next(
        (
            r
            for r in (report.get("isolated_ncopy_shared") or [])
            if r.get("n") == 1 and r.get("vin") == VIN_SWING and r.get("i_vdd") is not None
        ),
        {},
    )
    i_one = abs(iso_p.get("i_vdd") or 1.3e-3)
    report["power"] = {
        "i_one_A": i_one,
        "p_one_W": i_one * 30.0,
        "p_32_W": i_one * 30.0 * 32,
        "note": "macromodel supply current, not silicon",
    }

    # mechanism budget from A/B differences
    def res_of(case):
        row = next((c for c in fabric_cases if c.get("case") == case), {})
        return row.get("mean_invert_residual")

    iso_l1 = next((h.get("max_residual") for h in hierarchy if h.get("level") == "L1_4k91"), 0.7e-6)
    iso_n32 = max((r.get("max_residual") or 0) for r in (report.get("isolated_ncopy_shared") or []) if r.get("n") == 32) if report.get("isolated_ncopy_shared") else None
    budget = [
        {"mechanism": "isolated OPA189", "residual_V": iso_l1},
        {"mechanism": "multi-instance GWL (ideal load)", "residual_V": iso_n32},
        {"mechanism": "actual hy+Rfab isolated", "residual_V": rec_act.get("max_residual")},
        {"mechanism": "CASE A ideal hy", "residual_V": res_of("A")},
        {"mechanism": "CASE B ideal R1/R2", "residual_V": res_of("B")},
        {"mechanism": "CASE C ideal dest load", "residual_V": res_of("C")},
        {"mechanism": "CASE D ideal in+out", "residual_V": res_of("D")},
        {"mechanism": "CASE E full fabric", "residual_V": res_of("E")},
        {"mechanism": "LEVEL2 dest buffer", "residual_V": rich_buf.get("mean_invert_residual")},
    ]
    report["mechanism_budget"] = budget
    report["f40"] = {"ran": False, "reason": report.get("f40_gate")}
    decide(report)
    save_report(report)
    write_plots(report)
    write_markdown(report)
    print(f"STATUS {report['decision']['status']}", flush=True)
    print(f"DECISION {report['decision']['letter']}", flush=True)
    print(f"wrote {REPORT_MD}", flush=True)


if __name__ == "__main__":
    main()
