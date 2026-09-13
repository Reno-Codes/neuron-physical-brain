"""Experiment 43: high-gain behavioral TIA + existing W=10 encode.

Demonstrates Experiment 42 Case C in SPICE, or shows it fails.
Does not modify Experiments 1-42. Does not edit weights.
Does not fit resistors. Does not Python-correct SPICE.
Does not resize MOS. Not a physical TIA validation.
"""

from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path

import numpy as np

from benchmark_scaling import generate_inputs
from compile_xor import PROJECT_ROOT, find_ngspice
from exp39_pdk_o2_cell import (
    ERROR_LIMIT,
    PDK_VERSION,
    TAG,
    discover_pdk,
    eval_cell,
    prepend_pdk,
    replace_resistors_with_pdk,
    write_op_net,
)
from exp40_pdk_o2_cell import CATALOG, compile_o2_w2_1, prove_identity
from exp41_o2_residual import replace_resistors_w

CIRCUIT_DIR = PROJECT_ROOT / "circuits" / "exp43_o2"
RESULTS_DIR = PROJECT_ROOT / "results"
REPORT_JSON = RESULTS_DIR / "exp43_highgain_w10.json"
REPORT_MD = RESULTS_DIR / "exp43_highgain_w10.md"

Z_O2 = 2.459489570880132
RFG = 140.89398023224967
A_PRED_CROSS = 128203.09751266832
A_REQUIRED_ANALYTICAL = 348844.87057165743

Y_EXP41_IDEAL = 2.457433737388
Y_EXP40_W1 = 2.45254388951
Y_EXP41_W10 = 2.458037812913
LEFTOVER_W10_EXP41 = Y_EXP41_W10 - Y_EXP41_IDEAL

A_SWEEP = [1.0e5, 1.28203e5, 2.0e5, 3.48845e5, 5.0e5, 1.0e6, 1.0e7]
W1_HIGH_A = [3.48845e5, 1.0e6, 1.0e7]

TIA_E = re.compile(
    r"^(E" + re.escape(TAG) + r"tia\s+\S+\s+0\s+0\s+\S+)\s+[0-9.+-eE]+\s*$",
    re.IGNORECASE,
)
BASELINE_ATOL_V = 1.0e-8


def spiceinit() -> None:
    CIRCUIT_DIR.mkdir(parents=True, exist_ok=True)
    text = (
        "set ngbehavior=hsa\nset skywaterpdk\nset ng_nomodcheck\n"
        "set num_threads=4\noption klu\nunset interactive\n"
    )
    (CIRCUIT_DIR / ".spiceinit").write_text(text, encoding="ascii")
    (CIRCUIT_DIR / "spiceinit").write_text(text, encoding="ascii")


def tag_exp43(net: str) -> str:
    return net.replace(
        "* Experiment 39 SKY130 isolated frozen o2 cell",
        "* Experiment 43 behavioral high-A + existing W=10 · not a physical TIA",
    )


def a_tag(A: float) -> str:
    return f"{A:.8g}".replace("+", "").replace(".", "p")


def set_tia_gain(net: str, A: float) -> str:
    """Change only the behavioral TIA VCVS. Invert A stays 1e7."""
    a_s = f"{float(A):.15g}"
    n_e = 0
    out = []
    for raw in net.splitlines():
        s = raw.strip()
        m = TIA_E.match(s)
        if m:
            out.append(f"{m.group(1)} {a_s}")
            n_e += 1
            continue
        if s.startswith("* feedback TIA"):
            out.append(re.sub(r"A=[0-9.+-eE]+", f"A={a_s}", raw, count=1))
            continue
        if s.startswith("* A=") and "invertA=" in s:
            out.append(re.sub(r"^(\* A=)[0-9.+-eE]+", rf"\g<1>{a_s}", raw, count=1))
            continue
        out.append(raw)
    if n_e != 1:
        raise RuntimeError(f"expected one En1tia, found {n_e}")
    return "\n".join(out) + ("\n" if net.endswith("\n") else "")


def run_cell(ng, fabric: str, net_a: str, hy, z_ref: float, name: str, extra=None):
    path = CIRCUIT_DIR / f"{name}.cir"
    write_op_net(path, tag_exp43(net_a), hy, extra_prints=extra)
    rec = eval_cell(ng, path, z_ref, extra_names=extra, timeout=300.0)
    rec["name"] = name
    rec["fabric"] = fabric
    rec["python_corrected"] = False
    print(
        f"  {name} y={rec.get('y')} err={rec.get('err')} "
        f"|err|={rec.get('abs_err')} pass={rec.get('analog_pass')} "
        f"a_eff={rec.get('a_eff')} fail={rec.get('failure_reason')}",
        flush=True,
    )
    return rec


def slim(rec: dict) -> dict:
    keep = (
        "name",
        "fabric",
        "A",
        "path",
        "failed",
        "failure_reason",
        "z_ref",
        "y",
        "vsum",
        "err",
        "abs_err",
        "analog_pass",
        "a_eff",
        "repeat_of",
        "vector",
        "kind",
        "python_corrected",
    )
    return {k: rec[k] for k in keep if k in rec}


def decompose(w_rec: dict, ideal_rec: dict) -> dict:
    if w_rec.get("y") is None or ideal_rec.get("y") is None:
        return {"ok": False}
    z = float(w_rec["z_ref"])
    y_w = float(w_rec["y"])
    y_i = float(ideal_rec["y"])
    total = y_w - z
    finite_a = y_i - z
    leftover = y_w - y_i
    return {
        "ok": True,
        "A": w_rec.get("A"),
        "fabric": w_rec.get("fabric"),
        "total_mV": total * 1e3,
        "finite_A_ideal_fabric_mV": finite_a * 1e3,
        "deterministic_resistor_mV": leftover * 1e3,
        "sum_parts_mV": (finite_a + leftover) * 1e3,
        "identity_holds": math.isclose(total, finite_a + leftover, rel_tol=0, abs_tol=1e-15),
        "leftover_vs_exp41_w10_mV": leftover * 1e3 - LEFTOVER_W10_EXP41 * 1e3,
    }


def baseline_ok(y, y_ref) -> bool:
    return y is not None and abs(float(y) - float(y_ref)) <= BASELINE_ATOL_V


def select_vectors(ident: dict, w) -> list[dict]:
    x = generate_inputs(16, 40, "exp24_F")
    z1 = x @ w["W1"].T + w["b1"]
    hy = np.maximum(0.0, z1)
    wrow = np.asarray(ident["W2_row"], dtype=float)
    z = hy @ wrow + float(ident["b2"])
    imax = int(np.argmax(np.abs(z)))
    ineg = int(np.argmin(z))
    absz = np.abs(z)
    mid_candidates = [i for i in range(len(z)) if i != imax and absz[i] >= 0.2]
    imid = int(min(mid_candidates, key=lambda i: abs(absz[i] - 1.0))) if mid_candidates else 0
    low_candidates = [i for i in range(len(z)) if i != imax and 0.05 <= absz[i] <= 0.8]
    ilow = int(min(low_candidates, key=lambda i: absz[i])) if low_candidates else imid

    def pack(idx: int, role: str) -> dict:
        return {
            "vector": idx,
            "role": role,
            "z": float(z[idx]),
            "hy": [float(v) for v in hy[idx]],
            "from": "frozen F40 exp24_F inputs; W2[1] not edited",
        }

    chosen = [pack(imax, "max_|z|_established_o2")]
    if ineg != imax:
        chosen.append(pack(ineg, "most_negative_z"))
    if imid not in {imax, ineg}:
        chosen.append(pack(imid, "mid_|z|"))
    if ilow not in {imax, ineg, imid}:
        chosen.append(pack(ilow, "lower_|z|"))
    return chosen


def classify(report: dict) -> str:
    w10 = [r for r in report["w10_sweep"] if not r.get("failed") and r.get("y") is not None]
    ideal = [r for r in report["ideal_sweep"] if not r.get("failed") and r.get("y") is not None]
    w1 = [r for r in report["w1_points"] if not r.get("failed") and r.get("y") is not None]
    if report.get("solver_inconsistent"):
        return "D"
    high_w10 = [r for r in w10 if r["A"] >= A_PRED_CROSS]
    high_ideal = [r for r in ideal if r["A"] >= A_REQUIRED_ANALYTICAL]
    w10_pass = any(r.get("analog_pass") for r in high_w10)
    ideal_pass = any(r.get("analog_pass") for r in high_ideal)
    w10_floor = None
    if any(abs(r["A"] - 1e7) < 1 for r in w10):
        w10_floor = next(r for r in w10 if abs(r["A"] - 1e7) < 1).get("abs_err")
    w1_floor = None
    if any(abs(r["A"] - 1e7) < 1 for r in w1):
        w1_floor = next(r for r in w1 if abs(r["A"] - 1e7) < 1).get("abs_err")
    if w10_pass and report["gates"]["weights_unchanged"] and report["gates"]["w10_unfitted"]:
        if report["gates"]["no_python_correction"] and report["gates"]["reproducible"]:
            if w1_floor is not None and w1_floor > ERROR_LIMIT and ideal_pass:
                return "A"
    if ideal_pass and not w10_pass:
        return "B"
    if (w10_floor is not None and w10_floor > 1.2e-3) or (
        high_w10 and all((r.get("abs_err") or 9) > 1.2e-3 for r in high_w10)
    ):
        return "C"
    if not w10_pass:
        return "B" if ideal_pass else "C"
    return "D"


def write_md(report: dict) -> None:
    dec = report["decision"]
    labels = {
        "A": "FEASIBILITY DEMONSTRATED",
        "B": "HIGH GAIN ALONE IS NOT ENOUGH",
        "C": "EXPERIMENT 42 PROJECTION FAILED",
        "D": "NUMERICAL / MODEL ISSUE",
    }
    lines = [
        "# Experiment 43 — high-gain behavioral TIA + existing W=10",
        "",
        "Experiments 1–42 were not modified. Frozen weights were not edited.",
        "Resistors were not fitted. SPICE was not Python-corrected.",
        "No MOS W/L search. This is **not** a physical TIA validation.",
        "",
        "## Central question",
        "",
        "Is Experiment 42 Case C (existing W=10 encode + sufficiently high",
        "behavioral A) actually demonstrable in SPICE at |Vout − z_o2| ≤ 1 mV?",
        "",
        f"**Decision {dec} — {labels[dec]}**",
        "",
        "BEHAVIORAL HIGH-GAIN + W=10 is a separate claim from",
        "**PHYSICAL TIA VALIDATED**. The latter is **not** claimed.",
        "",
        "## Identity",
        "",
        f"- SIM_TARGET = {report['identity']['sim_target']}",
        f"- Rf·G = {report['identity']['Rf_Gtot']}",
        f"- z_o2 (vec {report['identity']['imax_vec']}) = {report['identity']['z_at_imax']}",
        f"- Compiler row W2[1] only. W2[2] blocked.",
        f"- PDK {report['pdk']['ciel_current']}",
        "",
        "## Netlist / model changes (this experiment only)",
        "",
        "- Compile the same isolated o2 cell as Experiments 40/41 (behavioral TIA).",
        "- Patch **only** `En1tia` open-loop A. Invert VCVS remains A=1e7.",
        "- W=10: Experiment 41 same-family `xhigh_po` encode, no L/W refit.",
        "- W=1: Experiment 40 `replace_resistors_with_pdk`.",
        "- Ideal R: catalog lumped resistors, unchanged values.",
        "- Official SKY130A tt, .temp 27. Solver: ngspice_con, `option klu`,",
        "  `set ngbehavior=hsa`, `set skywaterpdk`, `set ng_nomodcheck`, DC `op`,",
        "  `set numdgt=12`. No new .options tolerances.",
        "",
        "## Baseline reproduction (A=1e5, not overwriting 40/41)",
        "",
        "| Config | This y (V) | Prior y (V) | \\|err\\| (mV) | Match \\|Δy\\|≤10 nV | Pass |",
        "| --- | ---: | ---: | ---: | --- | --- |",
    ]
    for row in report["baselines"]:
        lines.append(
            f"| {row['fabric']} | {row.get('y')} | {row['prior_y']} | "
            f"{None if row.get('abs_err') is None else row['abs_err']*1e3:.6f} | "
            f"{row['matches_prior']} | {row.get('analog_pass')} |"
        )
    lines += [
        "",
        "## Primary sweep — existing W=10",
        "",
        "| A | Vout (V) | z_o2 (V) | err (mV) | \\|err\\| (mV) | pass |",
        "| ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for r in report["w10_sweep"]:
        if r.get("failed"):
            lines.append(f"| {r['A']:.8g} | FAIL {r.get('failure_reason')} | {r['z_ref']} | — | — | no |")
        else:
            lines.append(
                f"| {r['A']:.8g} | {r['y']:.12f} | {r['z_ref']:.12f} | "
                f"{r['err']*1e3:+.6f} | {r['abs_err']*1e3:.6f} | "
                f"{'PASS' if r['analog_pass'] else 'FAIL'} |"
            )
    lines += [
        "",
        "## Control A — ideal resistors",
        "",
        "| A | Vout (V) | err (mV) | \\|err\\| (mV) | pass |",
        "| ---: | ---: | ---: | ---: | --- |",
    ]
    for r in report["ideal_sweep"]:
        if r.get("failed"):
            lines.append(f"| {r['A']:.8g} | FAIL {r.get('failure_reason')} | — | — | no |")
        else:
            lines.append(
                f"| {r['A']:.8g} | {r['y']:.12f} | {r['err']*1e3:+.6f} | "
                f"{r['abs_err']*1e3:.6f} | {'PASS' if r['analog_pass'] else 'FAIL'} |"
            )
    lines += [
        "",
        "## Control B — existing W=1 at high A",
        "",
        "| A | Vout (V) | err (mV) | \\|err\\| (mV) | leftover vs ideal (mV) | pass |",
        "| ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for r in report["w1_points"]:
        decomp = next((d for d in report["decomposition"] if d.get("fabric") == "W=1" and d.get("A") == r.get("A")), {})
        if r.get("failed"):
            lines.append(f"| {r['A']:.8g} | FAIL | — | — | — | no |")
        else:
            lines.append(
                f"| {r['A']:.8g} | {r['y']:.12f} | {r['err']*1e3:+.6f} | "
                f"{r['abs_err']*1e3:.6f} | {decomp.get('deterministic_resistor_mV')} | "
                f"{'PASS' if r['analog_pass'] else 'FAIL'} |"
            )
    lines += [
        "",
        "## Control C — A=1e7 asymptotic trio",
        "",
        "| Fabric | Vout (V) | err (mV) | \\|err\\| (mV) | pass |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    for r in report["control_c"]:
        if r.get("failed"):
            lines.append(f"| {r['fabric']} | FAIL | — | — | no |")
        else:
            lines.append(
                f"| {r['fabric']} | {r['y']:.12f} | {r['err']*1e3:+.6f} | "
                f"{r['abs_err']*1e3:.6f} | {'PASS' if r['analog_pass'] else 'FAIL'} |"
            )
    xc = report.get("a_cross") or {}
    lines += [
        "",
        "## Gain-boundary extraction",
        "",
        f"- Experiment 42 predicted A_cross ≈ {A_PRED_CROSS:.6f}",
        f"- Measured last FAIL A = {xc.get('A_last_fail')}",
        f"- Measured first PASS A = {xc.get('A_first_pass')}",
        f"- Measured A_cross (bisection midpoint / first pass) = {xc.get('A_cross')}",
        f"- Predicted − measured = {xc.get('prediction_minus_measured')}",
        "- Model was not adjusted to force agreement.",
        "",
        "## Error decomposition (W=10 vs ideal R at same A)",
        "",
        "| A | total (mV) | finite-A / ideal (mV) | resistor leftover (mV) | leftover − Exp41 +0.604 (mV) |",
        "| ---: | ---: | ---: | ---: | ---: |",
    ]
    for d in report["decomposition"]:
        if d.get("fabric") != "W=10" or not d.get("ok"):
            continue
        lines.append(
            f"| {d['A']:.8g} | {d['total_mV']:+.6f} | {d['finite_A_ideal_fabric_mV']:+.6f} | "
            f"{d['deterministic_resistor_mV']:+.6f} | {d['leftover_vs_exp41_w10_mV']:+.6f} |"
        )
    lines += [
        "",
        "## Repeat run",
        "",
    ]
    rp = report.get("repeat") or {}
    lines.append(
        f"- Repeat of `{rp.get('repeat_of')}`: y={rp.get('y')} "
        f"|err|={None if rp.get('abs_err') is None else rp['abs_err']*1e3:.6f} mV "
        f"Δy={rp.get('delta_y')} reproducible={report['gates']['reproducible']}"
    )
    lines += [
        "",
        "## Sensitivity (frozen F40 vectors, same W=10 encode)",
        "",
        f"Operating A = {report.get('sensitivity_A')}",
        "",
        "| Vector | Role | z (V) | Vout (V) | err (mV) | pass |",
        "| ---: | --- | ---: | ---: | ---: | --- |",
    ]
    for r in report.get("sensitivity") or []:
        if r.get("failed"):
            lines.append(f"| {r.get('vector')} | {r.get('role')} | {r.get('z_ref')} | FAIL | — | no |")
        else:
            lines.append(
                f"| {r.get('vector')} | {r.get('role')} | {r['z_ref']:.12f} | "
                f"{r['y']:.12f} | {r['err']*1e3:+.6f} | "
                f"{'PASS' if r['analog_pass'] else 'FAIL'} |"
            )
    lines += [
        "",
        "## Gates",
        "",
    ]
    for k, v in report["gates"].items():
        lines.append(f"- {k}: **{v}**")
    lines += [
        "",
        "## Demonstrated versus projected",
        "",
        f"- Experiment 42 Case C: {report['case_c_status']}",
        f"- Behavioral high-gain + W=10 feasibility: {report['behavioral_claim']}",
        "- Physical TIA validated: **NO**",
        "- Matching: **UNRESOLVED**",
        "- Temperature: **NOT TESTED**",
        "- Network-F 2.937 V hosting: **NOT DEMONSTRATED**",
        "- F40 network: **NOT TESTED**",
        "",
        "## Conclusion",
        "",
        report["conclusion"],
        "",
    ]
    if dec == "A":
        lines += [
            "## Recommended Experiment 44 (not started)",
            "",
            "Extract what a physical amplifier must provide to realize the",
            "measured behavioral A_cross at the actual o2 operating point:",
            "",
            "- required open-loop / effective loop gain",
            "- output swing at the measured operating point",
            "- input / summing-node error budget",
            "- output current",
            "- bandwidth / 200 µs settling",
            "- temperature range",
            "- PDK supply / device-limit compatibility",
            "",
            "Do not start transistor redesign in Experiment 43.",
            "",
        ]
    lines += [
        "## Status",
        "",
        "- Experiment 40 Decision C: **unchanged**",
        "- Experiment 42 boundary: **unchanged** (now measured, not rewritten)",
        f"- Experiment 43 decision: **{dec} — {labels[dec]}**",
        "- PHYSICAL TIA VALIDATED: **NO**",
        "",
        "No Experiment 44 started. No MOS optimization.",
        "",
    ]
    REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def save(report: dict) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")


def finish_sensitivity(report: dict, ng, fabric_net, ident: dict, w) -> None:
    sens_A = float(report.get("sensitivity_A") or 1e6)
    if not report.get("sensitivity"):
        print(f"==== Sensitivity W=10 A={sens_A:.8g} frozen F40 vectors ====", flush=True)
        wrow = np.asarray(w["W2"][1], dtype=float)
        ident_for_sel = {"W2_row": [float(v) for v in wrow], "b2": ident["b2"]}
        vecs = select_vectors(ident_for_sel, w)
        for vec in vecs:
            rec = run_cell(
                ng,
                "W=10",
                fabric_net("W=10", sens_A),
                vec["hy"],
                vec["z"],
                f"w10_sens_v{vec['vector']}_a{a_tag(sens_A)}",
            )
            rec["A"] = sens_A
            rec["vector"] = vec["vector"]
            rec["role"] = vec["role"]
            rec["kind"] = "sensitivity"
            report["sensitivity"].append(
                slim(rec)
                | {
                    "A": sens_A,
                    "vector": vec["vector"],
                    "role": vec["role"],
                    "kind": "sensitivity",
                    "from": vec["from"],
                }
            )
            save(report)

    w10_any_pass = any(r.get("analog_pass") for r in report["w10_sweep"])
    report["decision"] = classify(report)
    if report["decision"] == "A" and w10_any_pass:
        report["case_c_status"] = "DEMONSTRATED in SPICE (behavioral TIA + existing W=10)"
        report["behavioral_claim"] = "BEHAVIORAL HIGH-GAIN + W=10 FEASIBILITY DEMONSTRATED"
    elif report["decision"] == "B":
        report["case_c_status"] = "NOT demonstrated; high A is not enough for W=10"
        report["behavioral_claim"] = "NOT DEMONSTRATED"
    elif report["decision"] == "C":
        report["case_c_status"] = "NOT demonstrated; measured W=10 did not enter the predicted region"
        report["behavioral_claim"] = "NOT DEMONSTRATED"
    else:
        report["case_c_status"] = "NOT demonstrated; solver/model inconsistency"
        report["behavioral_claim"] = "NOT DEMONSTRATED"

    leftover_note = ""
    w10_dec = [d for d in report["decomposition"] if d.get("ok") and d.get("fabric") == "W=10"]
    if w10_dec:
        leftover_note = (
            f" W=10 leftover ranged "
            f"{min(d['deterministic_resistor_mV'] for d in w10_dec):+.4f} to "
            f"{max(d['deterministic_resistor_mV'] for d in w10_dec):+.4f} mV "
            f"(Exp41 reference +{LEFTOVER_W10_EXP41*1e3:.4f} mV)."
        )
    labels = {
        "A": "FEASIBILITY DEMONSTRATED",
        "B": "HIGH GAIN ALONE IS NOT ENOUGH",
        "C": "EXPERIMENT 42 PROJECTION FAILED",
        "D": "NUMERICAL / MODEL ISSUE",
    }
    report["conclusion"] = (
        f"Decision {report['decision']} — {labels[report['decision']]}. "
        f"Case C status: {report['case_c_status']}. "
        f"Measured A_cross={report['a_cross'].get('A_cross')}; "
        f"Exp42 prediction {A_PRED_CROSS:.3f}; "
        f"difference {report['a_cross'].get('prediction_minus_measured')}. "
        f"PHYSICAL TIA VALIDATED is not claimed.{leftover_note}"
    )
    save(report)
    write_md(report)
    print("", flush=True)
    print(f"Experiment 43 Decision {report['decision']} — {labels[report['decision']]}", flush=True)
    print(f"  Case C: {report['case_c_status']}", flush=True)
    print("  PHYSICAL TIA VALIDATED: NO", flush=True)
    print("STOP. No Experiment 44. No MOS redesign.", flush=True)


def main() -> None:
    print("==== Experiment 43 identity ====", flush=True)
    ident = prove_identity()
    w = ident.pop("weights")
    pdk = discover_pdk()
    if pdk.get("ciel_current") != PDK_VERSION:
        raise SystemExit(f"BLOCKED PDK hash {pdk.get('ciel_current')}")
    net0, cat, _reason = compile_o2_w2_1(w)
    hy0 = ident["hy_at_imax"]
    z0 = float(ident["z_at_imax"])
    if not math.isclose(z0, Z_O2, rel_tol=0, abs_tol=1e-12):
        raise SystemExit(f"BLOCKED z_ref {z0} != {Z_O2}")
    if not math.isclose(float(ident["Rf_Gtot"]), RFG, rel_tol=0, abs_tol=1e-12):
        raise SystemExit("BLOCKED Rf·G")

    spiceinit()
    ng = find_ngspice()
    w1_net, geos1 = replace_resistors_with_pdk(net0, cat)
    w10_net, geos10 = replace_resistors_w(net0, cat, 10.0)
    rf10 = next((g for g in geos10 if g["name"] == "Rn1f"), None)
    rf1 = next((g for g in geos1 if g["name"] == "Rn1f"), None)

    report = {
        "experiment_id": "exp43",
        "kind": "behavioral feasibility demonstration",
        "closed_experiments_unmodified": list(range(1, 43)),
        "exp40_decision_unchanged": "C",
        "physical_tia_validated": False,
        "matching": "UNRESOLVED",
        "temperature": "NOT TESTED",
        "f40": "NOT TESTED",
        "network_f_2937_hosting": "NOT DEMONSTRATED",
        "identity": {k: ident[k] for k in ident if k not in {"W2_row", "hy_at_imax"}},
        "pdk": {"version": pdk["version"], "ciel_current": pdk["ciel_current"]},
        "encoding": {
            "w1_n": len(geos1),
            "w10_n": len(geos10),
            "w1_rf": rf1,
            "w10_rf": rf10,
            "w10_source": "Experiment 41 same-family encode; not fitted",
        },
        "solver": {
            "ngspice": str(ng),
            "analysis": "op",
            "options": ["klu", "ngbehavior=hsa", "skywaterpdk", "ng_nomodcheck", "numdgt=12"],
            "corner": "tt",
            "temp_C": 27.0,
        },
        "baselines": [],
        "w10_sweep": [],
        "ideal_sweep": [],
        "w1_points": [],
        "control_c": [],
        "decomposition": [],
        "a_cross": {},
        "repeat": {},
        "sensitivity": [],
        "gates": {
            "weights_unchanged": True,
            "w10_unfitted": True,
            "no_python_correction": True,
            "reproducible": False,
            "baseline_reproduced": False,
        },
        "solver_inconsistent": False,
    }

    def fabric_net(kind: str, A: float) -> str:
        src = {"ideal": net0, "W=1": w1_net, "W=10": w10_net}[kind]
        return prepend_pdk(set_tia_gain(src, A), "tt", 27.0)

    resume = "--resume" in sys.argv and REPORT_JSON.is_file()
    if resume:
        report = json.loads(REPORT_JSON.read_text(encoding="utf-8"))
        print("==== Resume: skip completed sweeps ====", flush=True)
        if report.get("repeat"):
            print("==== Sensitivity only ====", flush=True)
            finish_sensitivity(report, ng, fabric_net, ident, w)
            return

    print("==== Baseline reproduction A=1e5 ====", flush=True)
    for fabric, prior, srcname in (
        ("ideal", Y_EXP41_IDEAL, "baseline_ideal_a1e5"),
        ("W=1", Y_EXP40_W1, "baseline_w1_a1e5"),
        ("W=10", Y_EXP41_W10, "baseline_w10_a1e5"),
    ):
        rec = run_cell(ng, fabric, fabric_net(fabric, 1e5), hy0, z0, srcname)
        rec["A"] = 1e5
        rec["kind"] = "baseline reproduction"
        rec["prior_y"] = prior
        rec["matches_prior"] = baseline_ok(rec.get("y"), prior)
        report["baselines"].append(slim(rec) | {"prior_y": prior, "matches_prior": rec["matches_prior"]})
        save(report)

    report["gates"]["baseline_reproduced"] = all(b["matches_prior"] for b in report["baselines"])
    if not report["gates"]["baseline_reproduced"]:
        print("WARNING: baseline y did not match prior experiment within 10 nV", flush=True)

    by_ideal = {}
    print("==== Control A: ideal R A sweep ====", flush=True)
    for A in A_SWEEP:
        rec = run_cell(ng, "ideal", fabric_net("ideal", A), hy0, z0, f"ideal_a{a_tag(A)}")
        rec["A"] = A
        rec["kind"] = "control A"
        by_ideal[A] = rec
        report["ideal_sweep"].append(slim(rec) | {"A": A, "kind": "control A"})
        save(report)

    print("==== Primary: W=10 A sweep ====", flush=True)
    by_w10 = {}
    for A in A_SWEEP:
        rec = run_cell(ng, "W=10", fabric_net("W=10", A), hy0, z0, f"w10_a{a_tag(A)}")
        rec["A"] = A
        rec["kind"] = "primary W=10"
        by_w10[A] = rec
        report["w10_sweep"].append(slim(rec) | {"A": A, "kind": "primary W=10"})
        if A in by_ideal:
            report["decomposition"].append(decompose(rec, by_ideal[A]))
        save(report)

    print("==== Control B: W=1 high A ====", flush=True)
    by_w1 = {}
    rec = run_cell(ng, "W=1", fabric_net("W=1", 1e5), hy0, z0, "w1_a1e5_ctrl")
    rec["A"] = 1e5
    rec["kind"] = "control B"
    by_w1[1e5] = rec
    report["w1_points"].append(slim(rec) | {"A": 1e5, "kind": "control B"})
    if 1e5 in by_ideal:
        report["decomposition"].append(decompose(rec, by_ideal[1e5]))
    save(report)
    for A in W1_HIGH_A:
        rec = run_cell(ng, "W=1", fabric_net("W=1", A), hy0, z0, f"w1_a{a_tag(A)}")
        rec["A"] = A
        rec["kind"] = "control B"
        by_w1[A] = rec
        report["w1_points"].append(slim(rec) | {"A": A, "kind": "control B"})
        if A in by_ideal:
            report["decomposition"].append(decompose(rec, by_ideal[A]))
        elif abs(A - 1e7) < 1 and 1e7 in by_ideal:
            report["decomposition"].append(decompose(rec, by_ideal[1e7]))
        save(report)

    print("==== Control C: A=1e7 trio ====", flush=True)
    for fabric, store in (("ideal", by_ideal), ("W=1", by_w1), ("W=10", by_w10)):
        rec = store[1e7]
        report["control_c"].append(slim(rec) | {"A": 1e7, "kind": "control C", "fabric": fabric})

    print("==== Focused A_cross bisection on W=10 ====", flush=True)
    ordered = sorted([r for r in report["w10_sweep"] if r.get("y") is not None], key=lambda r: r["A"])
    last_fail = None
    first_pass = None
    for r in ordered:
        if not r.get("analog_pass"):
            last_fail = r
        elif first_pass is None:
            first_pass = r
            break
    a_cross = {
        "predicted_A": A_PRED_CROSS,
        "A_last_fail": None if last_fail is None else last_fail["A"],
        "A_first_pass": None if first_pass is None else first_pass["A"],
        "bisection": [],
    }
    if last_fail is not None and first_pass is not None:
        lo, hi = float(last_fail["A"]), float(first_pass["A"])
        mid_rec = first_pass
        for step in range(8):
            if hi - lo < 200.0:
                break
            mid = 0.5 * (lo + hi)
            rec = run_cell(ng, "W=10", fabric_net("W=10", mid), hy0, z0, f"w10_bisect_{step}_a{a_tag(mid)}")
            rec["A"] = mid
            rec["kind"] = "A_cross bisection"
            report["w10_sweep"].append(slim(rec) | {"A": mid, "kind": "A_cross bisection"})
            # ideal at mid for leftover
            irec = run_cell(ng, "ideal", fabric_net("ideal", mid), hy0, z0, f"ideal_bisect_{step}_a{a_tag(mid)}")
            irec["A"] = mid
            report["ideal_sweep"].append(slim(irec) | {"A": mid, "kind": "A_cross bisection"})
            report["decomposition"].append(decompose(rec, irec))
            a_cross["bisection"].append(
                {"A": mid, "abs_err": rec.get("abs_err"), "pass": rec.get("analog_pass")}
            )
            if rec.get("analog_pass"):
                hi = mid
                first_pass = rec
                mid_rec = rec
            else:
                lo = mid
                last_fail = rec
            save(report)
        a_cross["A_last_fail"] = None if last_fail is None else last_fail["A"]
        a_cross["A_first_pass"] = None if first_pass is None else first_pass["A"]
        a_cross["A_cross"] = a_cross["A_first_pass"]
        if a_cross["A_cross"] is not None:
            a_cross["prediction_minus_measured"] = A_PRED_CROSS - float(a_cross["A_cross"])
        a_cross["abs_err_at_first_pass"] = None if first_pass is None else first_pass.get("abs_err")
        _ = mid_rec
    elif first_pass is None:
        a_cross["A_cross"] = None
        a_cross["note"] = "W=10 never crossed 1 mV in the measured sweep"
    else:
        a_cross["A_cross"] = first_pass["A"]
        a_cross["note"] = "no failing point above the lowest A; crossing at or below first point"
    report["a_cross"] = a_cross
    save(report)

    passing = [
        r
        for r in report["w10_sweep"]
        if r.get("analog_pass") and r.get("y") is not None and r.get("kind") != "A_cross bisection"
    ]
    if not passing:
        passing = [r for r in report["w10_sweep"] if r.get("analog_pass") and r.get("y") is not None]
    best = None
    if passing:
        prefer = [r for r in passing if abs(r["A"] - 1e6) < 1]
        best = prefer[0] if prefer else min(passing, key=lambda r: r["abs_err"])
    sens_A = 1e6 if best is None else float(best["A"])
    if best is None:
        sens_A = 1e7
    report["sensitivity_A"] = sens_A

    print(f"==== Repeat run W=10 A={sens_A:.8g} ====", flush=True)
    name = f"w10_repeat_a{a_tag(sens_A)}"
    rec = run_cell(ng, "W=10", fabric_net("W=10", sens_A), hy0, z0, name)
    rec["A"] = sens_A
    rec["repeat_of"] = f"w10_a{a_tag(sens_A)}"
    orig = next((r for r in report["w10_sweep"] if abs(r["A"] - sens_A) < 1e-6 and r.get("kind") == "primary W=10"), None)
    dy = None if orig is None or rec.get("y") is None or orig.get("y") is None else float(rec["y"]) - float(orig["y"])
    report["repeat"] = slim(rec) | {"A": sens_A, "repeat_of": rec["repeat_of"], "delta_y": dy}
    report["gates"]["reproducible"] = dy is not None and abs(dy) <= 1e-9
    if dy is not None and abs(dy) > 1e-8:
        report["solver_inconsistent"] = True
    save(report)

    finish_sensitivity(report, ng, fabric_net, ident, w)


if __name__ == "__main__":
    main()
