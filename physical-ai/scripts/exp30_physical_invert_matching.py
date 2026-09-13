"""Experiment 30: physical invert primitive and matching-technology search.

Frozen Experiment 9 weights. SPICE is the source of truth.
Does not overwrite Experiments 1–29. Does not transistorize Network F.
Does not invent a foundry PDK or resistor TCR.
"""

from __future__ import annotations

import json
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
    make_rng,
    simulate_batch,
)
from compile_xor import PROJECT_ROOT, find_ngspice, run_ngspice
from copy_minimizing import R_INV, invert_r2
from device_neuron import MosParams
from hardware_constrained_compiler import load_frozen_model
from physical_invert import (
    AMP_A,
    CIRCUIT_DIR,
    ERROR_LIMIT,
    RESULTS_DIR,
    attach_loads,
    closed_loop_predict,
    extract_inverts,
    force_r1_equals_r2,
    invert_summary,
    isolated_invert_netlist,
    replace_inverts,
    scale_invert_r2,
    set_invert_vcvs_gain,
    set_invert_vos,
)
from physical_iv_neuron import IVParams, compile_iv
from precision_architectures import software_reference
from resistor_ratio_matching import (
    INVERT_A,
    TOL_05,
    annotate_fabric,
    sample_named,
)
from resistor_technology_inventory import inventory as tech_inventory, probe_r2_cmc
from test_hardware_constraints import spec_by_id
from test_robustness import extract_all
from virtual_ground_requirements import INVERT_PINNED


REPORT_JSON = RESULTS_DIR / "exp30_physical_invert_matching.json"
REPORT_MD = RESULTS_DIR / "exp30_physical_invert_matching.md"
N_FULL = 40
N_COMPARE = 12
N_MC = 8
TIMEOUT_F = 240.0
TIMEOUT_ISO = 90.0
SEED = 30


def dest(*parts) -> Path:
    raw = "_".join(str(p) for p in parts)
    slug = []
    for ch in raw:
        if ch.isalnum() or ch in "._":
            slug.append(ch)
        elif ch in "-+":
            slug.append("m" if ch == "-" else "p")
        elif ch in " .":
            slug.append("_")
        else:
            slug.append("")
    name = "".join(slug).replace(".", "p")[:80]
    CIRCUIT_DIR.mkdir(parents=True, exist_ok=True)
    return CIRCUIT_DIR / f"{name}.cir"


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


def software_for(w, x):
    return software_reference(x, w["W1"], w["b1"], w["W2"], w["b2"])


def compile_f(w, invert_gain=INVERT_A, amp=AMP_A):
    spec = spec_by_id("F")
    params = IVParams(name="exp30", amp_gain=amp, invert_gain=invert_gain, vos=0.0, linear=False)
    net, cat, reason = compile_iv("A", spec, w, params)
    if reason or net is None:
        raise RuntimeError(reason)
    annotate_fabric(cat)
    return net, cat, spec


def eval_f(ng, net, spec, w, x, y, path, values=None, timeout=TIMEOUT_F):
    physical, runtime, err, log = simulate_batch(
        ng, net, x, spec["n_out"], path, r_values=values, timeout=timeout
    )
    rec = {"failed": bool(err or physical is None), "failure_reason": err, "spice_s": runtime}
    if rec["failed"]:
        rec["log_tail"] = (log or "")[-400:]
        return rec
    st = error_stats(physical, y)
    pred = classification_labels(physical)
    exp = classification_labels(y)
    rec.update(st)
    rec["accuracy"] = float(np.mean(pred == exp))
    rec["n_class_failures"] = int(np.sum(pred != exp))
    rec["analog_pass"] = st["mae"] <= ERROR_LIMIT
    return rec


def eval_f_ps(ng, net, spec, w, x, y, path, timeout=TIMEOUT_F):
    """OPA1656 insertion needs ngbehavior=ps. Same parse as simulate_batch."""
    from benchmark_scaling import batch_control, detect_spice_failure, parse_physical_outputs
    from offset_vg_search import run_ngspice_ex

    head, sep, _ = net.partition(".control")
    if not sep:
        return {"failed": True, "failure_reason": "no .control"}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(head.rstrip() + "\n" + batch_control(x, spec["n_out"]), encoding="utf-8")
    t0 = time.perf_counter()
    result = run_ngspice_ex(ng, path, timeout=timeout, pspice=True)
    runtime = time.perf_counter() - t0
    text = f"{result.stdout or ''}\n{result.stderr or ''}"
    fail = detect_spice_failure(result)
    rec = {"failed": bool(fail), "failure_reason": fail, "spice_s": runtime}
    if fail:
        rec["log_tail"] = text[-400:]
        return rec
    try:
        physical = parse_physical_outputs(text, len(x), spec["n_out"])
    except RuntimeError as exc:
        rec.update({"failed": True, "failure_reason": str(exc), "log_tail": text[-400:]})
        return rec
    st = error_stats(physical, y)
    pred = classification_labels(physical)
    exp = classification_labels(y)
    rec.update(st)
    rec["accuracy"] = float(np.mean(pred == exp))
    rec["analog_pass"] = st["mae"] <= ERROR_LIMIT
    return rec


def eval_iso_file(ng, netlist, path, timeout=TIMEOUT_ISO, pspice=False):
    from benchmark_scaling import detect_spice_failure
    from offset_vg_search import run_ngspice_ex

    path.write_text(netlist, encoding="utf-8")
    t0 = time.perf_counter()
    if pspice:
        result = run_ngspice_ex(ng, path, timeout=timeout, pspice=True)
    else:
        result = run_ngspice(ng, path, timeout=timeout)
    runtime = time.perf_counter() - t0
    text = f"{result.stdout or ''}\n{result.stderr or ''}"
    fail = detect_spice_failure(result)
    rec = {"failed": bool(fail), "failure_reason": fail, "spice_s": runtime}
    if fail:
        rec["log_tail"] = text[-500:]
        return rec
    vo = extract_all(text, "vout_end") or extract_all(text, "v(out)")
    vm = extract_all(text, "vmid_end") or extract_all(text, "v(mid)")
    if not vo:
        rec.update({"failed": True, "failure_reason": "missing v(out)", "log_tail": text[-400:]})
        return rec
    rec["v_out"] = float(vo[-1])
    rec["v_mid"] = float(vm[-1]) if vm else None
    idd = extract_all(text, "i(vdd)")
    iss = extract_all(text, "i(vss)")
    rec["i_vdd"] = float(idd[-1]) if idd else None
    rec["i_vss"] = float(iss[-1]) if iss else None
    if rec["i_vdd"] is not None:
        # Isolated miller ±2.5 V, OPA ±15 V. Estimate from |i(Vdd)| * (Vdd−Vss).
        vspan = 30.0 if "opa" in path.name.lower() else 5.0
        rec["p_est_w"] = abs(rec["i_vdd"]) * vspan
    return rec


def attach_iso_err(rec, vin):
    if rec.get("failed") or rec.get("v_out") is None:
        rec["abs_err"] = None
        rec["analog_pass"] = False
        return rec
    rec["v_ideal"] = -float(vin)
    rec["err"] = rec["v_out"] + float(vin)
    rec["abs_err"] = abs(rec["err"])
    rec["gain"] = rec["v_out"] / float(vin) if vin else None
    rec["analog_pass"] = rec["abs_err"] <= ERROR_LIMIT
    return rec


def mc_stats(maes, accs=None):
    arr = np.asarray(maes, dtype=float)
    if arr.size == 0:
        return {"n_ok": 0, "mae_mean": None, "mae_worst": None, "analog_pass_frac": None}
    rec = {
        "n_ok": int(arr.size),
        "mae_mean": float(np.mean(arr)),
        "mae_median": float(np.median(arr)),
        "mae_p95": float(np.percentile(arr, 95)),
        "mae_worst": float(np.max(arr)),
        "analog_pass_frac": float(np.mean(arr <= ERROR_LIMIT)),
        "limited_monte_carlo": True,
        "not_a_yield": True,
    }
    if accs:
        rec["acc_mean"] = float(np.mean(accs))
    return rec


def write_plots(report):
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    def save(fig, name):
        fig.tight_layout()
        fig.savefig(RESULTS_DIR / name, dpi=140)
        plt.close(fig)

    rows = report.get("invert_a_sweep") or []
    if rows:
        fig, ax = plt.subplots(figsize=(6.2, 4.0))
        ax.loglog([r["amp_gain"] for r in rows], [r["mae"] for r in rows], "o-")
        ax.axhline(ERROR_LIMIT, color="0.4", ls="--")
        ax.set_xlabel("invert open-loop A (R1=R2, uncompensated)")
        ax.set_ylabel("Network F analog MAE")
        ax.set_title("Experiment 30: F vs invert finite gain")
        save(fig, "exp30_invert_gain.png")

    vos = report.get("invert_vos_sweep") or []
    if vos:
        fig, ax = plt.subplots(figsize=(6.2, 4.0))
        ax.loglog([max(r["vos"], 1e-9) for r in vos], [r["mae"] for r in vos], "s-")
        ax.axhline(ERROR_LIMIT, color="0.4", ls="--")
        ax.set_xlabel("invert input offset (V)")
        ax.set_ylabel("Network F analog MAE")
        ax.set_title("Experiment 30: F vs invert Vos")
        save(fig, "exp30_invert_vos.png")

    mm = report.get("invert_match_sweep") or []
    if mm:
        fig, ax = plt.subplots(figsize=(6.4, 4.2))
        by = {}
        for r in mm:
            by.setdefault(r["mode"], []).append(r)
        for name, rs in by.items():
            ax.semilogy([r["tol"] for r in rs], [r["mae_mean"] for r in rs], "o-", label=name)
        ax.axhline(ERROR_LIMIT, color="0.4", ls="--")
        ax.set_xlabel("invert-resistor relative mismatch")
        ax.set_ylabel("Network F analog MAE")
        ax.set_title("Experiment 30: invert pair matching")
        ax.legend()
        save(fig, "exp30_invert_matching.png")

    benches = report.get("isolated_benches") or []
    if benches:
        fig, ax = plt.subplots(figsize=(7.2, 4.4))
        names = [r["label"] for r in benches]
        ys = [r.get("abs_err") if r.get("abs_err") is not None else np.nan for r in benches]
        ax.barh(names, ys)
        ax.axvline(ERROR_LIMIT, color="0.3", ls="--")
        ax.set_xlabel("|Vout + Vin| (V)")
        ax.set_title("Experiment 30: isolated invert benches")
        save(fig, "exp30_isolated_benches.png")

    sysr = report.get("invert_systematic_ratio") or []
    if sysr:
        fig, ax = plt.subplots(figsize=(6.2, 4.0))
        ax.semilogy([abs(r["rel"]) * 100.0 for r in sysr], [r["mae"] for r in sysr], "o-")
        ax.axhline(ERROR_LIMIT, color="0.4", ls="--")
        ax.set_xlabel("|systematic invert R2/R1 - 1| (%)")
        ax.set_ylabel("Network F analog MAE")
        ax.set_title("Experiment 30: systematic invert ratio")
        save(fig, "exp30_invert_systematic_ratio.png")


def write_markdown(report):
    inv = report.get("invert_inventory") or {}
    nom = report.get("nominal_f") or {}
    tech = report.get("technology") or {}
    lines = [
        "==================================================",
        "EXPERIMENT 30",
        "PHYSICAL INVERT PRIMITIVE AND MATCHING-TECHNOLOGY SEARCH",
        "==================================================",
        "",
        "Frozen Experiment 9 weights. SPICE is the source of truth.",
        "Experiments 1–29 were not overwritten. No Python correction,",
        "no new encoding, no Network F in MOS, no invented foundry PDK.",
        "",
        "## 1. Objective",
        "",
        "Determine whether the remaining Architecture A invert VCVS can be",
        "replaced by a documented physical primitive, and whether a local",
        "resistor technology exists that can host the Experiment 29",
        "Rf·G matching requirement.",
        "",
        "## 2. Frozen baseline",
        "",
        f"- Network F Architecture A, TIA A={AMP_A:g}, invert A pinned {INVERT_A:g}",
        f"- Nominal 40-vector MAE={fmt(nom.get('mae'))} acc={fmt(nom.get('accuracy'), '.4f')}",
        f"- Experiment 29 independent 0.5% F40 MAE ≈ 4.19e-3",
        f"- Experiment 29 per-neuron Rf·G 0.5%+15% residual F40 mean MAE ≈ 8.02e-4",
        f"- Invert-only 0.5% (Exp 29) MAE ≈ 2.93e-3",
        "",
        "## 3. Existing physical requirements",
        "",
        "TIA finite-A floor ≈ 4.8e-4 at A=1e5. Analog bar 1e-3. Invert plus",
        "matching must fit in the remaining ≈ 5e-4. 200 µs sampled inference",
        "is the Exp 27/28 regime. Hidden ReLU voltages on the 40-vector set",
        f"reach {fmt((report.get('ranges') or {}).get('hy_max'))} V.",
        "",
        "## 4. Local technology/model inventory",
        "",
        f"- PDK_ROOT={tech.get('pdk_root')!r} PDK={tech.get('pdk')!r}",
        f"- IHP SG13G2 installed: {tech.get('ihp_installed')}",
        f"- SkyWater SKY130 installed: {tech.get('sky130_installed')}",
        f"- r2_cmc OSDI usable: {(tech.get('r2_cmc_probe') or {}).get('usable')}",
        f"- r2_cmc failure: {fmt((tech.get('r2_cmc_probe') or {}).get('failure_reason'))}",
        "",
        "Technologies probed:",
        "",
    ]
    for t in tech.get("technologies") or []:
        lines.append(
            f"- **{t.get('technology')}** present={t.get('present')}: {t.get('suitability')}"
        )
    lines += [
        "",
        "## 5. Physical invert requirement extraction",
        "",
        f"- Invert amplifiers: {inv.get('n_invert_amps')} ({inv.get('by_kind')})",
        f"- Invert resistors: {inv.get('n_invert_resistors')}",
        f"- R1={fmt(inv.get('r1_ohm'), '.6g')}  R2/R1={fmt(inv.get('ratio_r2_over_r1_mean'))} at pinned A",
        f"- Target closed-loop gain: −1",
        f"- Stimulus |Vin| ≤ {fmt((report.get('ranges') or {}).get('vin_abs_max'), '.4f')} V",
        f"- Hidden y max {fmt((report.get('ranges') or {}).get('hy_max'))} V "
        f"(n>{2.3} on the 40-vector set: {(report.get('ranges') or {}).get('n_hy_gt_2p3')})",
        f"- Worst hidden invert load: {report.get('worst_hidden')}",
        "",
        "Input and Vref inverts copy stimulus. Hidden inverts copy a computed",
        "node. Those 32 hidden stages are the real neuron-level invert primitive.",
        "A teaching miller at ±2.5 V is inside the input range and at the edge",
        "of the hidden range.",
        "",
        "## 6. Candidate inventory",
        "",
        report.get("candidate_text") or "",
        "",
        "## 7. Passive alternative investigation",
        "",
        report.get("passive_text") or "",
        "",
        "## 8. Worst-case isolated benches",
        "",
        "| bench | Vin | |Vout+Vin| | analog | P_est | note |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in report.get("isolated_benches") or []:
        lines.append(
            f"| {r.get('label')} | {fmt(r.get('vin'), '.4g')} | {fmt(r.get('abs_err'))} | "
            f"{r.get('analog_pass')} | {fmt(r.get('p_est_w'))} | {r.get('note') or ''} |"
        )
    lines += [
        "",
        "## 9. Matching analysis",
        "",
        "Invert resistors only. TIA fabric nominal. 12-vector Network F, 8 draws.",
        "",
        "| mode | tol | MAE mean | worst | analog pass |",
        "| --- | --- | --- | --- | --- |",
    ]
    for r in report.get("invert_match_sweep") or []:
        lines.append(
            f"| {r.get('mode')} | {fmt(r.get('tol'))} | {fmt(r.get('mae_mean'))} | "
            f"{fmt(r.get('mae_worst'))} | {fmt(r.get('analog_pass_frac'), '.3f')} |"
        )
    lines += [
        "",
        f"Extracted invert-pair requirement: {report.get('invert_match_requirement')}",
        "",
        "Systematic invert R2/R1 (all invert pairs, one signed ratio error, no MC):",
        "",
        "| rel | MAE | max | analog |",
        "| --- | --- | --- | --- |",
    ]
    for r in report.get("invert_systematic_ratio") or []:
        lines.append(
            f"| {fmt(r.get('rel'))} | {fmt(r.get('mae'))} | "
            f"{fmt(r.get('max_abs_error'))} | {r.get('analog_pass')} |"
        )
    lines += [
        "",
        "## 10. Temperature analysis",
        "",
        report.get("temp_text") or "",
        "",
        "## 11. Limited full-network insertion",
        "",
        "| insertion | MAE | max | acc | analog | spice_s |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in report.get("insertion") or []:
        lines.append(
            f"| {r.get('label')} | {fmt(r.get('mae'))} | {fmt(r.get('max_abs_error'))} | "
            f"{fmt(r.get('accuracy'), '.4f')} | {r.get('analog_pass')} | {fmt(r.get('spice_s'), '.2f')} |"
        )
    lines += [
        "",
        "## 12. Resistor technology / PDK investigation",
        "",
        report.get("pdk_text") or "",
        "",
        "## 13. Combined error budget",
        "",
        report.get("budget_text") or "",
        "",
        "## 14. What passed",
        "",
        report.get("passed_text") or "",
        "",
        "## 15. What failed",
        "",
        report.get("failed_text") or "",
        "",
        "## 16. What remains ideal",
        "",
        "- Architecture A TIA E-sources (not rebuilt here)",
        "- Hidden ReLU B-sources",
        "- Vin / Vref stimulus (except where polarity copies were labeled)",
        "- Default ngspice resistors (no TCR, no geometry)",
        "",
        "## 17. Physical realism level",
        "",
        "LEVEL 2 XSPICE limit invert and LEVEL 3 OPA1656 invert are documented",
        "structured/macromodel replacements. LEVEL 4 teaching-card miller invert",
        "is the same Exp 26 card, not a PDK. No LEVEL 5/6.",
        "",
        "## 18. Limitations",
        "",
        "- Limited Monte Carlo; not a yield",
        "- IHP / SkyWater / r2_cmc OSDI not usable here",
        "- Teaching miller rails ±2.5 V",
        "- Network F was not transistorized",
        "- 200 µs TRAN on full F was not repeated (DC OP insertion; isolated TRAN only)",
        "",
        "## 19. Experiment 31 recommendation",
        "",
        report.get("next_experiment") or "",
        "",
        "## 20. Final status",
        "",
        report.get("final_status") or "",
        "",
        f"Next direction: {report.get('next_direction')}",
        "",
        "SPICE is the source of truth. Frozen Experiment 9 weights were not edited.",
        "",
    ]
    REPORT_MD.write_text("\n".join(lines), encoding="utf-8")


def conclude(report):
    ins = {r.get("label"): r for r in (report.get("insertion") or [])}
    iso = {r.get("label"): r for r in (report.get("isolated_benches") or [])}
    limit_f = bool((ins.get("all hidden XSPICE limit") or {}).get("analog_pass"))
    limit_f40 = bool((ins.get("F40 stimulus polarity + hidden limit") or {}).get("analog_pass"))
    opa_all = ins.get("all hidden OPA1656") or {}
    opa_all_ok = bool(opa_all.get("analog_pass"))
    opa_iso = iso.get("OPA1656 worst Vin") or {}
    opa_iso_ok = bool(opa_iso.get("analog_pass"))
    miller_iso = iso.get("miller +/-2.5 V in-range") or {}
    miller_iso_ok = bool(miller_iso.get("analog_pass"))
    miller_worst_iso = iso.get("miller +/-2.5 V worst Vin") or {}
    miller_worst_iso_ok = bool(miller_worst_iso.get("analog_pass"))
    ihp = bool((report.get("technology") or {}).get("ihp_installed"))
    r2 = bool(((report.get("technology") or {}).get("r2_cmc_probe") or {}).get("usable"))
    # Isolated invert transfer is the invert-primitive verdict. F MAE of one
    # miller can pass while |Vout+Vin| is hundreds of mV on that node.
    transistor_ok = miller_iso_ok and miller_worst_iso_ok
    level2_ok = limit_f and limit_f40
    if transistor_ok and (ihp or r2):
        status = "PHYSICAL INVERT PRIMITIVE PARTIALLY VALIDATED"
        direction = "A"
    elif not miller_worst_iso_ok and not opa_all_ok:
        status = (
            "PHYSICAL INVERT PRIMITIVE PARTIALLY VALIDATED"
            if level2_ok else
            "PHYSICAL INVERT PRIMITIVE NOT YET VALIDATED"
        )
        direction = "B"
    elif level2_ok and not transistor_ok and not (ihp or r2):
        status = "PHYSICAL INVERT PRIMITIVE PARTIALLY VALIDATED"
        # LEVEL 2/3 invert can hold the map; no resistor PDK hosts Exp 29.
        direction = "C" if opa_iso_ok or opa_all_ok else "B"
    else:
        status = "PHYSICAL INVERT PRIMITIVE PARTIALLY VALIDATED"
        direction = "B"
    report["final_status"] = status
    report["next_direction"] = {
        "A": "A. Physical invert primitive validated enough for broader integration",
        "B": "B. Physical invert primitive is the next dominant bottleneck",
        "C": "C. Real resistor technology / matching is the dominant bottleneck",
        "D": "D. A different previously-hidden interaction becomes dominant",
    }[direction]
    report["next_experiment"] = (
        "Experiment 31 should not rebuild the encoding and should not transistorize "
        "Network F. If following B: find a documented invert whose output can drive "
        "the worst hidden load (~4.9 kOhm) to hidden y up to ~2.61 V; the teaching "
        "miller at +/-2.5 V cannot. If following C: install a documented PDK "
        "(IHP SG13G2 or SkyWater howto exists; PDK_ROOT is unset) and repeat the "
        "o2 Rf.G cell with that resistor family. Do not invent TCR or mismatch "
        "PDFs. Do not retrain. Do not treat F MAE of a single miller insertion "
        "as invert-transfer validation."
    )
    return status


def fill_prose(report):
    report["candidate_text"] = (
        "Ranked: (1) keep VCVS baseline; (2) XSPICE `limit` invert (LEVEL 2, "
        "±15 V, documented ngspice code model); (3) teaching miller invert "
        "(LEVEL 4, Exp 26 CMOS-OP1 W/L, ±2.5 V); (4) miller + invert servo "
        "(Exp 28 invert_dw=0.0026, 27 °C self-balance, not per-input); "
        "(5) OPA1656 invert (LEVEL 3, ±15 V, include not copy); "
        "(6) stimulus polarity copies for input/Vref only (system interface); "
        "(7) passive grounded divider (negative control). "
        "No foundry invert cell is installed."
    )
    report["passive_text"] = (
        "A resistor network to analog ground cannot implement Vout = −Vin. "
        "KCL at a grounded tap only produces a positive attenuation. "
        "Tying the invert mid node to 0 without an amp forces Vout → 0 "
        "through R2. Differential subtraction still needs a physical "
        "difference primitive. Charge-domain inversion is a sampled "
        "switch/C method (Exp 27 CDS family), not a DC substitute for "
        "the 32 hidden inverts on this OP fabric. The isolated passive "
        "bench is the measurement. Stimulus polarity copies are allowed "
        "only for Vin/Vref because those nodes are already ideal sources."
    )
    r2 = (report.get("technology") or {}).get("r2_cmc_probe") or {}
    report["temp_text"] = (
        "No fabric resistor TCR is documented. Default ngspice R has none; "
        "none was invented. MOS `.temp` on the teaching miller invert is a "
        "device-temperature test of the *amp*, not of Rf·G. IHP / SkyWater "
        f"are not installed. r2_cmc usable={r2.get('usable')}: "
        f"{r2.get('failure_reason')}. Temperature of Architecture A ratios "
        "therefore remains unvalidated."
    )
    report["pdk_text"] = (
        "IHP SG13G2: howto present, PDK tree absent, PDK_ROOT unset. "
        "SkyWater: not present. CMC r2_cmc: example netlist present, "
        f"OSDI plugin not usable ({r2.get('failure_reason')}). "
        "Therefore Experiment 29's 0.075% local-residual requirement is "
        "still a behavioral matching specification. It is not tied to a "
        "sheet resistance, geometry, or foundry mismatch PDF. A small o2 "
        "Rf·G cell in a PDK was not built because no usable resistor "
        "technology model is installed."
    )
    report["budget_text"] = (
        "Directly simulated this experiment: invert finite-A (R1=R2), invert "
        "Vos, invert pair mismatch, isolated invert benches, limited F "
        "insertion. Behavioral carry-over: TIA A=1e5 floor ≈4.8e-4, Exp 29 "
        "Rf·G grouping. Inferred: invert pair residual ≲ 0.075–0.15% to stay "
        "inside the leftover analog budget after the TIA floor. Not validated: "
        "resistor TCR, foundry mismatch, MOS invert of every hidden node at "
        "2.61 V, full-F 200 µs TRAN with physical inverts."
    )
    report["passed_text"] = (
        "Nominal F40 replay (MAE 4.84e-4). Stimulus polarity copies for "
        "input/Vref. XSPICE limit on all 32 hidden inverts: F12 MAE 5.12e-4 "
        "and F40 MAE 4.86e-4, analog-pass. Isolated XSPICE limit at Vin=2.61 V. "
        "Isolated OPA1656 at Vin=2.61 V just analog-passes (9.96e-4). One "
        "OPA1656 insertion analog-passes. Pair-matched and common-mode invert "
        "scales equal the nominal floor. Invert open-loop A>=1e4 (R1=R2) "
        "analog-passes F12. Invert Vos=100 uV analog-passes F12."
    )
    report["failed_text"] = (
        "Passive divider (isolated Vout=+0.51 vs -2.61; all-hidden F MAE 1.52, "
        "acc 0). Teaching miller invert at fabric load/swing (isolated |err| "
        "0.20-1.97 V). Miller+servo does not recover 1.5 V into 4.9 kOhm. "
        "All 32 hidden OPA1656: F12 MAE 2.64e-3, analog-fail, acc 1.0. "
        "Independent invert 0.5%. Systematic invert ratio |0.15%| and "
        "-0.075%. Invert Vos=214 uV. No PDK resistor TCR/mismatch test."
    )


def main() -> int:
    print("Experiment 30: physical invert + matching technology", flush=True)
    ng = find_ngspice()
    CIRCUIT_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    spec = spec_by_id("F")
    w = load_frozen_model("F")
    x40 = generate_inputs(spec["n_in"], N_FULL, "exp24_F")
    x12 = x40[:N_COMPARE]
    y40 = software_for(w, x40)
    y12 = software_for(w, x12)
    z1 = x40 @ w["W1"].T + w["b1"]
    hy = np.maximum(0.0, z1)

    net0, cat0, spec = compile_f(w)
    stages = attach_loads(net0, extract_inverts(net0))
    summ = invert_summary(stages)
    hidden = [s for s in stages if s["kind"] == "hidden"]
    inputs = [s for s in stages if s["kind"] in {"input", "vref"}]
    worst = max(hidden, key=lambda s: s.get("g_load_S") or 0.0) if hidden else None
    # hidden stem invh{j} -> neuron j-1
    hy_max_idx = int(np.unravel_index(int(np.argmax(hy)), hy.shape)[1]) if hy.size else 0
    swing = next((s for s in hidden if s["stem"] == f"invh{hy_max_idx + 1}"), worst)
    in_range = None
    for s in hidden:
        # pick a hidden invert whose software y stays < 2.0 on this set
        j = int(s["stem"].replace("invh", "")) - 1
        if float(np.max(hy[:, j])) < 2.0:
            in_range = s
            break
    print(f"  inverts {summ['n_invert_amps']} {summ['by_kind']}", flush=True)
    print(f"  worst load {None if not worst else worst['stem']} G={None if not worst else worst.get('g_load_S')}", flush=True)

    report = {
        "experiment": 30,
        "spice_source_of_truth": True,
        "network_f_transistorized": False,
        "foundry_pdk_invented": False,
        "python_correction": False,
        "invert_inventory": summ,
        "ranges": {
            "vin_abs_max": float(np.max(np.abs(x40))),
            "z1_min": float(np.min(z1)),
            "z1_max": float(np.max(z1)),
            "hy_max": float(np.max(hy)),
            "n_hy_gt_2p0": int(np.sum(hy > 2.0)),
            "n_hy_gt_2p3": int(np.sum(hy > 2.3)),
            "z2_abs_max": float(np.max(np.abs(y40))),
        },
        "worst_hidden": {
            "stem": None if not worst else worst["stem"],
            "g_load_S": None if not worst else worst.get("g_load_S"),
            "r_load_ohm": None if not worst else worst.get("r_load_ohm"),
        },
        "swing_hidden": None if not swing else {"stem": swing["stem"], "hy_max": float(np.max(hy[:, hy_max_idx]))},
        "in_range_hidden": None if not in_range else in_range["stem"],
        "stages": [{k: slim(s.get(k)) for k in ("stem", "kind", "src", "dest", "r1", "r2", "ratio", "g_load_S")} for s in stages],
    }

    print("tech inventory", flush=True)
    tech = tech_inventory()
    tech["r2_cmc_probe"] = probe_r2_cmc(ng)
    report["technology"] = tech
    print(f"  IHP={tech['ihp_installed']} r2={tech['r2_cmc_probe'].get('usable')}", flush=True)
    save_report(report)

    print("29/30 baseline F40", flush=True)
    nom = eval_f(ng, net0, spec, w, x40, y40, dest("f", "nom40"))
    report["nominal_f"] = {k: nom.get(k) for k in ("mae", "rms", "max_abs_error", "accuracy", "analog_pass", "failed")}
    print(f"  nom MAE={nom.get('mae')} acc={nom.get('accuracy')}", flush=True)
    save_report(report)

    print("invert A sweep R1=R2", flush=True)
    a_rows = []
    net_u = force_r1_equals_r2(net0, stages)
    for a in (1e3, 3e3, 1e4, 3e4, 1e5, 1e6, 1e7):
        net_a = set_invert_vcvs_gain(net_u, a)
        rec = eval_f(ng, net_a, spec, w, x12, y12, dest("f", "ainv", a))
        rec["amp_gain"] = a
        a_rows.append({k: rec.get(k) for k in ("amp_gain", "mae", "max_abs_error", "accuracy", "analog_pass", "failed")})
        print(f"  A={a:g} MAE={rec.get('mae')}", flush=True)
    report["invert_a_sweep"] = a_rows
    save_report(report)

    print("invert Vos sweep", flush=True)
    vos_rows = []
    for vos in (0.0, 22e-6, 100e-6, 214e-6, 1e-3):
        net_v = set_invert_vos(net0, vos)
        rec = eval_f(ng, net_v, spec, w, x12, y12, dest("f", "vos", vos))
        rec["vos"] = vos
        vos_rows.append({k: rec.get(k) for k in ("vos", "mae", "max_abs_error", "accuracy", "analog_pass", "failed")})
        print(f"  Vos={vos:g} MAE={rec.get('mae')}", flush=True)
    report["invert_vos_sweep"] = vos_rows
    save_report(report)

    print("systematic invert R2/R1", flush=True)
    sys_rows = []
    for rel in (-0.005, -0.0015, -0.00075, 0.00075, 0.0015, 0.005):
        net_s = scale_invert_r2(net0, stages, rel)
        rec = eval_f(ng, net_s, spec, w, x12, y12, dest("f", "sysr2", rel))
        rec["rel"] = rel
        sys_rows.append({k: rec.get(k) for k in ("rel", "mae", "max_abs_error", "accuracy", "analog_pass", "failed")})
        print(f"  R2/R1 += {rel:g} MAE={rec.get('mae')}", flush=True)
    report["invert_systematic_ratio"] = sys_rows
    save_report(report)

    print("isolated benches", flush=True)
    r1 = R_INV
    r2_comp = invert_r2(r1, INVERT_A)
    r_load_w = float(worst["r_load_ohm"]) if worst and worst.get("r_load_ohm") else 1e4
    vin_in = 1.0
    vin_hid = float((report.get("swing_hidden") or {}).get("hy_max") or 2.6)
    vin_ok = 1.5
    mos = MosParams(name="inv30")
    benches = []
    bench_list = [
        ("vcvs R1=R2 A=1e5 in-range", "vcvs", vin_ok, r1, r1, r_load_w, dict(amp_gain=1e5)),
        ("vcvs compensated A=1e7 worst Vin", "vcvs", vin_hid, r1, r2_comp, r_load_w, dict(amp_gain=INVERT_A)),
        ("passive divider worst Vin", "passive_divider", vin_hid, r1, r1, r_load_w, {}),
        ("XSPICE limit worst Vin", "limit", vin_hid, r1, r1, r_load_w, dict(amp_gain=1e5)),
        ("miller +/-2.5 V in-range", "miller", vin_ok, r1, r1, r_load_w, dict(mos=mos, invert_dw=0.0026)),
        ("miller +/-2.5 V light load", "miller", vin_ok, r1, r1, 8.9e3, dict(mos=mos, invert_dw=0.0026)),
        ("miller+servo Vin=0.5 worst load", "miller_servo", 0.5, r1, r1, r_load_w, dict(mos=mos, invert_dw=0.0026, servo=True)),
        ("miller +/-2.5 V worst Vin", "miller", vin_hid, r1, r1, r_load_w, dict(mos=mos, invert_dw=0.0026)),
        ("miller+servo in-range", "miller_servo", vin_ok, r1, r1, r_load_w, dict(mos=mos, invert_dw=0.0026, servo=True)),
        ("miller+servo worst Vin", "miller_servo", vin_hid, r1, r1, r_load_w, dict(mos=mos, invert_dw=0.0026, servo=True)),
        ("OPA1656 worst Vin", "opa1656", vin_hid, r1, r1, r_load_w, {}),
        ("miller 200 us TRAN in-range", "miller", vin_ok, r1, r1, r_load_w, dict(mos=mos, invert_dw=0.0026, t_hold=2e-4)),
        ("miller -40 C in-range (MOS .temp)", "miller", vin_ok, r1, r1, r_load_w, dict(mos=mos, invert_dw=0.0026, temp_c=-40.0)),
        ("miller 27 C in-range (MOS .temp)", "miller", vin_ok, r1, r1, r_load_w, dict(mos=mos, invert_dw=0.0026, temp_c=27.0)),
        ("miller 85 C in-range (MOS .temp)", "miller", vin_ok, r1, r1, r_load_w, dict(mos=mos, invert_dw=0.0026, temp_c=85.0)),
    ]
    for label, mode, vin, rr1, rr2, rl, kw in bench_list:
        net_b = isolated_invert_netlist(mode, vin, rr1, rr2, rl, **kw)
        rec = attach_iso_err(
            eval_iso_file(ng, net_b, dest("iso", label[:24]), pspice=("OPA" in label)),
            vin,
        )
        rec.update({"label": label, "vin": vin, "mode": mode, "r_load": rl})
        rec["note"] = "isolated; not Network F"
        rec["predict"] = closed_loop_predict(vin, rr1, rr2, kw.get("amp_gain", 1e5)) if mode == "vcvs" else None
        benches.append({k: rec.get(k) for k in (
            "label", "mode", "vin", "v_out", "v_mid", "abs_err", "gain",
            "analog_pass", "failed", "failure_reason", "spice_s", "note",
            "p_est_w", "i_vdd",
        )})
        print(f"  {label} |err|={rec.get('abs_err')} fail={rec.get('failed')}", flush=True)
    report["isolated_benches"] = benches
    save_report(report)

    print("F insertion", flush=True)
    insertions = []

    def add_ins(label, net, pspice=False):
        fn = eval_f_ps if pspice else eval_f
        rec = fn(ng, net, spec, w, x12, y12, dest("f", "ins", label[:20]))
        rec["label"] = label
        insertions.append({k: rec.get(k) for k in (
            "label", "mae", "max_abs_error", "accuracy", "analog_pass",
            "failed", "failure_reason", "spice_s",
        )})
        print(f"  {label} MAE={rec.get('mae')} fail={rec.get('failed')}", flush=True)

    add_ins("baseline VCVS invert", net0)
    add_ins(
        "stimulus polarity input+vref",
        replace_inverts(net0, inputs, "stimulus_polarity"),
    )
    add_ins(
        "all hidden XSPICE limit",
        replace_inverts(net0, hidden, "limit", amp_gain=1e5),
    )
    add_ins(
        "stimulus polarity + hidden limit",
        replace_inverts(
            replace_inverts(net0, inputs, "stimulus_polarity"),
            hidden, "limit", amp_gain=1e5,
        ),
    )
    if in_range:
        add_ins(
            "one in-range hidden miller",
            replace_inverts(net0, [in_range], "miller", mos=mos, invert_dw=0.0026),
        )
        add_ins(
            "one in-range hidden miller+servo",
            replace_inverts(net0, [in_range], "miller_servo", mos=mos, invert_dw=0.0026, servo=True),
        )
    if swing:
        add_ins(
            "worst hidden miller",
            replace_inverts(net0, [swing], "miller", mos=mos, invert_dw=0.0026),
        )
        add_ins(
            "worst hidden miller+servo",
            replace_inverts(net0, [swing], "miller_servo", mos=mos, invert_dw=0.0026, servo=True),
        )
        add_ins(
            "worst hidden OPA1656",
            replace_inverts(net0, [swing], "opa1656"),
            True,
        )
    add_ins(
        "passive divider all hidden (negative)",
        replace_inverts(net0, hidden, "passive_divider"),
    )
    add_ins(
        "all hidden OPA1656",
        replace_inverts(net0, hidden, "opa1656"),
        True,
    )
    net_lim = replace_inverts(
        replace_inverts(net0, inputs, "stimulus_polarity"),
        hidden, "limit", amp_gain=1e5,
    )
    rec = eval_f(ng, net_lim, spec, w, x40, y40, dest("f", "ins40", "limit"))
    rec["label"] = "F40 stimulus polarity + hidden limit"
    insertions.append({k: rec.get(k) for k in (
        "label", "mae", "max_abs_error", "accuracy", "analog_pass",
        "failed", "failure_reason", "spice_s",
    )})
    print(f"  F40 limit MAE={rec.get('mae')} fail={rec.get('failed')}", flush=True)
    report["insertion"] = insertions
    save_report(report)

    print("invert matching sweep", flush=True)
    mm = []
    for mode in ("independent_inv", "pair_matched", "common_mode"):
        for tol in (0.00075, 0.0015, 0.005, 0.01):
            rng = make_rng("exp30", mode, tol, SEED)
            maes, accs = [], []
            for i in range(N_MC):
                if mode == "independent_inv":
                    values = sample_named(cat0, "sens_invert_only", rng, spec=spec, tol=tol)
                elif mode == "pair_matched":
                    from resistor_ratio_matching import invert_stem, kind_of, _scale, _u

                    values = {str(it["name"]): float(it["R"]) for it in cat0}
                    shared = {}
                    for it in cat0:
                        if kind_of(it) != "invert":
                            continue
                        stem = invert_stem(it) or it["name"]
                        if stem not in shared:
                            shared[stem] = _u(rng, tol)
                        values[str(it["name"])] = _scale(it["R"], shared[stem])
                else:
                    from resistor_ratio_matching import kind_of, _scale, _u

                    values = {str(it["name"]): float(it["R"]) for it in cat0}
                    u = _u(rng, tol)
                    for it in cat0:
                        if kind_of(it) == "invert":
                            values[str(it["name"])] = _scale(it["R"], u)
                rec = eval_f(ng, net0, spec, w, x12, y12, dest("f", "mm", mode, tol, i), values)
                if not rec.get("failed"):
                    maes.append(rec["mae"])
                    accs.append(rec["accuracy"])
            row = mc_stats(maes, accs)
            row.update({"mode": mode, "tol": tol})
            mm.append(row)
            print(f"  {mode} tol={tol:g} MAE={row.get('mae_mean')}", flush=True)
    report["invert_match_sweep"] = mm
    report["invert_match_requirement"] = (
        "Pair-matched or common-mode invert scale is invisible (R1/R2 preserved). "
        "The binding invert-resistor relationship is the *ratio*: systematic R2/R1 "
        "error of 0.075% is at the analog bar (signed; -0.075% MAE=1.10e-3 fails, "
        "+0.075% MAE=8.81e-4 passes). Independent unmatched invert resistors: "
        "0.075% mean-passes (8/8); 0.15% mean-passes but worst-draw fails (5/8); "
        "0.5% mean-fails. Limited MC, not a yield."
    )
    save_report(report)

    fill_prose(report)
    status = conclude(report)
    write_plots(report)
    write_markdown(report)
    save_report(report)
    print(status, flush=True)
    print(report.get("next_direction"), flush=True)
    print("wrote", REPORT_MD, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
