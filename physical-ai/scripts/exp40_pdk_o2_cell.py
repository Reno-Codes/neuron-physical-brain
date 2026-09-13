"""Experiment 40: official SKY130A isolated catalog o2 (W2[1]).

Does not modify Experiment 39. Does not edit frozen weights.
Does not invent PDK parameters or mismatch PDFs.
SPICE is not Python-corrected.
Identity is verified numerically before any SPICE run.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

from benchmark_scaling import generate_inputs
from compile_xor import PROJECT_ROOT, find_ngspice
from exp39_pdk_o2_cell import (
    ERROR_LIMIT,
    PDK_LIB,
    PDK_VERSION,
    TAG,
    discover_pdk,
    eval_cell,
    lib_line,
    prepend_pdk,
    replace_resistors_with_pdk,
    run_cir,
    write_op_net,
)
from hardware_constrained_compiler import load_frozen_model
from inverter_requirement_extraction import compile_f
from offset_vg_search import bake_vin_dc
from passive_iv import neuron_gtot
from precision_architectures import ARCH_C_CFG
from virtual_ground_requirements import VGParams, generate_isolated_neuron, rank_neurons

CIRCUIT_DIR = PROJECT_ROOT / "circuits" / "exp40_o2"
RESULTS_DIR = PROJECT_ROOT / "results"
ROW_INDEX = 1
SIM_TARGET = "o2 / W2[1]"
FORBIDDEN_ROW = 2

CATALOG = {
    "tag": "o2",
    "index": 1,
    "Rf_Gtot": 140.89398023224967,
    "Gtot_S": 4.22681940696749e-3,
    "Imax_A": 202.805e-6,
    "z_abs_max_V": 2.459489570880132,
}
NETWORK_Z_ABS_MAX_V = 2.937183
IMAX_ATOL_A = 0.05e-6
ID_RTOL = 1e-12
ID_ATOL = 1e-15


def _die(msg: str) -> None:
    print(f"BLOCKED: {msg}", flush=True)
    raise SystemExit(2)


def prove_identity() -> dict:
    w = load_frozen_model("F")
    if "W2" not in w:
        _die("frozen F.npz missing W2")
    row_index = ROW_INDEX
    if row_index == FORBIDDEN_ROW:
        _die("compiler row is W2[2]")
    if row_index != 1:
        _die(f"compiler row is W2[{row_index}], not W2[1]")

    wrow = np.asarray(w["W2"][row_index], dtype=float)
    b2 = float(w["b2"][row_index])
    if np.array_equal(wrow, np.asarray(w["W2"][FORBIDDEN_ROW], dtype=float)):
        _die("W2[1] equals W2[2]; refusing ambiguous identity")

    cfg = ARCH_C_CFG["F"]
    g_w = float(cfg.g_weight_2)
    rf = 1.0 / g_w
    net, cat, spec = compile_f(w)
    x = generate_inputs(spec["n_in"], 40, "exp24_F")
    rows, picks = rank_neurons(spec, cat, w, x)
    o2 = next(r for r in rows if r["tag"] == "o2")
    if int(o2["index"]) != 1:
        _die(f"rank_neurons o2 index is {o2['index']}, expected 1")

    z1 = x @ w["W1"].T + w["b1"]
    hy = np.maximum(0.0, z1)
    z_o2 = hy @ wrow + b2
    imax_vec = int(np.argmax(np.abs(z_o2)))
    z_at = float(z_o2[imax_vec])
    z_abs_max = float(np.max(np.abs(z_o2)))
    l1 = float(np.sum(np.abs(wrow)) + abs(b2))
    imax = g_w * l1
    gtot = float(o2["G_phys_S"])
    rfg = rf * gtot

    checks = {
        "index": (row_index, CATALOG["index"], row_index == CATALOG["index"]),
        "Rf_Gtot": (rfg, CATALOG["Rf_Gtot"], math.isclose(rfg, CATALOG["Rf_Gtot"], rel_tol=ID_RTOL, abs_tol=1e-12)),
        "Gtot_S": (gtot, CATALOG["Gtot_S"], math.isclose(gtot, CATALOG["Gtot_S"], rel_tol=ID_RTOL, abs_tol=ID_ATOL)),
        "Imax_A": (imax, CATALOG["Imax_A"], abs(imax - CATALOG["Imax_A"]) <= IMAX_ATOL_A),
        "z_abs_max_V": (
            z_abs_max,
            CATALOG["z_abs_max_V"],
            math.isclose(z_abs_max, CATALOG["z_abs_max_V"], rel_tol=1e-12, abs_tol=1e-12),
        ),
    }
    failed = [k for k, v in checks.items() if not v[2]]
    if failed:
        _die(f"catalog mismatch on {failed}: { {k: checks[k][:2] for k in failed} }")

    print(f"SIM_TARGET = {SIM_TARGET}", flush=True)
    print(f"COMPILER_ROW_INDEX = {row_index}", flush=True)
    print(f"identity Rf*G={rfg:.12f} Gtot={gtot:.15e} Imax={imax:.9e} |z|max={z_abs_max:.12f}", flush=True)
    print(f"z_ref vector={imax_vec} z={z_at:.15g}", flush=True)
    if row_index == FORBIDDEN_ROW:
        _die("compiler received W2[2]")

    return {
        "sim_target": SIM_TARGET,
        "compiler_row_index": row_index,
        "forbidden_row_blocked": FORBIDDEN_ROW,
        "frozen_model": "models/scaling/F.npz seed 9",
        "tag": "o2",
        "W2_row": [float(v) for v in wrow],
        "b2": b2,
        "Rf_ohm": rf,
        "Gtot_S": gtot,
        "Rf_Gtot": rfg,
        "Imax_A": imax,
        "l1": l1,
        "z_abs_max_V": z_abs_max,
        "z_at_imax": z_at,
        "imax_vec": imax_vec,
        "hy_at_imax": [float(v) for v in hy[imax_vec]],
        "network_z_abs_max_V": float(picks["highest_signal"]["z_abs_max"]),
        "network_z_abs_max_tag": picks["highest_signal"]["tag"],
        "g_weight": g_w,
        "checks": {k: {"got": a, "catalog": b, "ok": c} for k, (a, b, c) in checks.items()},
        "weights": w,
    }


def compile_o2_w2_1(w) -> tuple[str, list, str]:
    idx = ROW_INDEX
    if idx == FORBIDDEN_ROW:
        _die("compile refused W2[2]")
    if idx != 1:
        _die(f"compile refused W2[{idx}]")
    print(f"compile generate_isolated_neuron consuming W2[{idx}] only", flush=True)
    cfg = ARCH_C_CFG["F"]
    net, cat, reason = generate_isolated_neuron(
        32,
        w["W2"][idx],
        float(w["b2"][idx]),
        cfg.g_weight_2,
        cfg.banks,
        VGParams(name="exp40", amp_gain=1e5, invert_gain=1e7, linear=True),
        tag=TAG,
    )
    if reason:
        _die(f"generate_isolated_neuron: {reason}")
    gtot = neuron_gtot(cat, TAG)
    rf = 1.0 / float(cfg.g_weight_2)
    rfg = rf * gtot
    if not math.isclose(rfg, CATALOG["Rf_Gtot"], rel_tol=1e-12, abs_tol=1e-9):
        _die(f"compiled catalog Rf*G={rfg} != o2 {CATALOG['Rf_Gtot']}")
    if not math.isclose(gtot, CATALOG["Gtot_S"], rel_tol=1e-12, abs_tol=1e-15):
        _die(f"compiled Gtot={gtot} != o2 {CATALOG['Gtot_S']}")
    return net, cat, reason


def inspect_deck(geos: list[dict], cat: list) -> dict:
    gtot = neuron_gtot(cat, TAG)
    rf = 1.0 / float(ARCH_C_CFG["F"].g_weight_2)
    rf_geo = next((g for g in geos if g["name"].endswith("f") or g["name"] == f"R{TAG}f"), None)
    n_w = sum(1 for it in cat if it.get("role") in {"weight", "bias"})
    rec = {
        "n_catalog": len(cat),
        "n_weight_bias": n_w,
        "n_pdk_devices": len(geos),
        "Gtot_S": gtot,
        "Rf_Gtot": rf * gtot,
        "rf_geo": rf_geo,
        "matches_o2_rfg": math.isclose(rf * gtot, CATALOG["Rf_Gtot"], rel_tol=1e-12, abs_tol=1e-9),
    }
    if not rec["matches_o2_rfg"]:
        _die(f"deck Rf*G={rec['Rf_Gtot']} is not catalog o2")
    if rec["n_pdk_devices"] < 50:
        _die(f"too few PDK resistors ({rec['n_pdk_devices']}); o3-sized fabric suspected")
    print(
        f"deck identity nR={rec['n_pdk_devices']} weight_bias={n_w} "
        f"Rf*G={rec['Rf_Gtot']:.12f} Rf_L={None if not rf_geo else rf_geo['l_um']}",
        flush=True,
    )
    return rec


def write_local_spiceinit() -> None:
    CIRCUIT_DIR.mkdir(parents=True, exist_ok=True)
    text = (
        "set ngbehavior=hsa\n"
        "set skywaterpdk\n"
        "set ng_nomodcheck\n"
        "set num_threads=4\n"
        "option klu\n"
        "unset interactive\n"
    )
    (CIRCUIT_DIR / ".spiceinit").write_text(text, encoding="ascii")
    (CIRCUIT_DIR / "spiceinit").write_text(text, encoding="ascii")


def decide(dc_rows: list[dict]) -> dict:
    pdk_r = any(d.get("analog_pass") for d in dc_rows if "pdk_r" in d.get("name", ""))
    mos = any(d.get("analog_pass") for d in dc_rows if "miller" in d.get("name", ""))
    if mos and pdk_r:
        letter, title = "A", "REAL PDK O2 CELL VALIDATED"
    elif pdk_r or mos:
        letter, title = "B", "O2 CELL WORKS BUT TECHNOLOGY DATA REMAINS MISSING"
    else:
        letter, title = "C", "PDK EXPOSES A TECHNOLOGY LIMIT"
    return {
        "letter": letter,
        "title": title,
        "pdk_r_pass": bool(pdk_r),
        "miller_pass": bool(mos),
        "rule": "analog_pass |y-z|<=1e-3 on pdk_r or miller inference DC; no override",
        "why": [
            "Official SKY130A ran on identity-verified catalog o2 / W2[1]."
            if True
            else "",
            "PDK-R behavioral TIA analog-pass."
            if pdk_r
            else "PDK-R behavioral TIA analog-pass failed or was not demonstrated.",
            "Miller analog-pass was not part of this first DC stop.",
            "MATCHING FEASIBILITY UNRESOLVED (inherited; no new statistical campaign).",
        ],
    }


def write_reports(report: dict) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / "exp40_pdk_o2_cell.json").write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8"
    )
    ident = report["identity"]
    dc = report["dc_results"]
    nom = next(d for d in dc if d["name"] == "pdk_r_behav_tt_27")
    lines = [
        "# Experiment 40 - SKY130A isolated catalog o2 (W2[1])",
        "",
        "Experiment 39 is closed and was not modified.",
        "Frozen Experiment 9 weights were not edited. SPICE is the source of truth.",
        "",
        f"## Decision: {report['decision']['letter']} - {report['decision']['title']}",
        "",
        f"- Automated `decide()`: **{report['decision']['letter']}**. No override.",
        f"- SIM_TARGET = `{ident['sim_target']}`. Compiler row = W2[{ident['compiler_row_index']}].",
        f"- Catalog o2 Rf·G = {ident['Rf_Gtot']:.12f}. Deck Rf·G = {report['deck']['Rf_Gtot']:.12f}.",
        f"- z_ref = {ident['z_at_imax']:.12f} V (F40 vector {ident['imax_vec']}, max |z_o2|).",
        f"- Analog: y = {nom.get('y')} err = {nom.get('err')} |err| = {nom.get('abs_err')} "
        f"pass = {nom.get('analog_pass')}.",
        "- Matching: **UNRESOLVED** (no new statistical evidence).",
        f"- Catalog o2 |z|max = {ident['z_abs_max_V']:.12f} V (software z of this cell).",
        f"- Network software |z|max = {ident['network_z_abs_max_V']:.6f} V "
        f"({ident['network_z_abs_max_tag']}); not a SKY130 node.",
        "",
        "## 1. Target identity proof",
        "",
        f"SIM_TARGET = {ident['sim_target']}",
        "",
        "| Check | Got | Catalog | OK |",
        "| --- | ---: | ---: | --- |",
    ]
    for k, row in ident["checks"].items():
        lines.append(f"| {k} | {row['got']} | {row['catalog']} | {row['ok']} |")
    lines += [
        "",
        "## 2. Weight extraction proof",
        "",
        f"- Frozen file: {ident['frozen_model']}",
        f"- Row passed to compiler: **W2[{ident['compiler_row_index']}]**",
        f"- b2 = {ident['b2']}",
        f"- W2[2] was not passed. Forbidden row {ident['forbidden_row_blocked']} is blocked.",
        "",
        "## 3. Catalog-vs-simulation truth table",
        "",
        "| Quantity | Catalog o2 (B) | This run (A) | Network (C) |",
        "| --- | ---: | ---: | ---: |",
        f"| W2 index | 1 | {ident['compiler_row_index']} | — |",
        f"| Rf·G | {CATALOG['Rf_Gtot']:.12f} | {report['deck']['Rf_Gtot']:.12f} | — |",
        f"| Gtot (S) | {CATALOG['Gtot_S']:.15e} | {report['deck']['Gtot_S']:.15e} | — |",
        f"| Imax (uA) | {CATALOG['Imax_A']*1e6:.3f} | {ident['Imax_A']*1e6:.3f} | "
        f"{ident['Imax_A']*1e6:.3f} (this neuron) |",
        f"| \|z\|max (V) | {CATALOG['z_abs_max_V']:.12f} | {ident['z_abs_max_V']:.12f} "
        f"(software z_o2) | {ident['network_z_abs_max_V']:.6f} |",
        f"| Analog \|y−z\| | — | {nom.get('abs_err')} | not run |",
        "",
        "## 4. Generated-deck identity",
        "",
        f"- Devices: {report['deck']['n_pdk_devices']} xhigh_po. Weight/bias: {report['deck']['n_weight_bias']}.",
        f"- Rf geometry: {report['deck']['rf_geo']}",
        f"- matches_o2_rfg: {report['deck']['matches_o2_rfg']}",
        "",
        "## 5–7. SPICE / analog error / corners",
        "",
        "| Test | y (V) | err (V) | \|err\| | pass |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    for d in dc:
        lines.append(
            f"| {d['name']} | {d.get('y')} | {d.get('err')} | {d.get('abs_err')} | {d.get('analog_pass')} |"
        )
    lines += [
        "",
        "## 8. Matching status",
        "",
        "**UNRESOLVED**. Experiment 39 status is inherited. No Monte Carlo and no invented PDF.",
        "",
        "## 9. Voltage status",
        "",
        f"- Catalog / software o2 |z|max = {ident['z_abs_max_V']:.12f} V.",
        f"- Simulated y (tt 27 C) = {nom.get('y')} V.",
        f"- Network software |z|max = {ident['network_z_abs_max_V']:.6f} V "
        f"({ident['network_z_abs_max_tag']}). Not a measured SKY130 output.",
        "",
        "## 10. Classification",
        "",
        f"- Identity instantiation: **{report['classification']['identity']}**",
        f"- Analog bar: **{report['classification']['analog_bar']}**",
        f"- Process corners: **{report['classification']['corners']}**",
        f"- Matching: **{report['classification']['matching']}**",
        f"- Miller / W=10 / MC n>=100 / MOS mismatch / F40: **NOT TESTED** (first-DC stop).",
        "",
        "## 11. Decision",
        "",
        f"**{report['decision']['letter']} — {report['decision']['title']}**",
        "",
        "Rule: analog_pass on PDK-R or miller inference DC. No forced B.",
        "",
        "## 12. Discrepancies",
        "",
        report.get("discrepancy") or "None beyond analog-bar vs 1e-3 if FAIL.",
        "",
        "W=10, miller, and optimization were not started.",
    ]
    (RESULTS_DIR / "exp40_pdk_o2_cell.md").write_text("\n".join(lines), encoding="utf-8")
    spec = [
        "# Experiment 40 minimum technology note",
        "",
        "Does not overwrite Experiment 39. No invented PDK parameters.",
        "",
        f"- SIM_TARGET = {SIM_TARGET}. Catalog o2 Rf·G = {CATALOG['Rf_Gtot']}.",
        f"- Analog bar |y−z| <= {ERROR_LIMIT}. Matching UNRESOLVED.",
        f"- Network software |z|max = {NETWORK_Z_ABS_MAX_V} V is not a SKY130 node.",
        f"- Decision {report['decision']['letter']}.",
        "",
    ]
    (RESULTS_DIR / "exp40_pdk_requirements.md").write_text("\n".join(spec), encoding="utf-8")


def main() -> None:
    print("==== Experiment 40 identity (no SPICE yet) ====", flush=True)
    ident = prove_identity()
    w = ident.pop("weights")
    pdk = discover_pdk()
    if not pdk.get("lib_exists"):
        _die("SKY130 lib missing")
    if pdk.get("ciel_current") != PDK_VERSION:
        _die(f"PDK hash {pdk.get('ciel_current')} != {PDK_VERSION}")
    print(f"PDK {pdk['variant']} {pdk['version']} lib_ok={pdk['lib_exists']}", flush=True)
    print(f"lib {PDK_LIB}", flush=True)

    print("==== compile W2[1] only ====", flush=True)
    net, cat, reason = compile_o2_w2_1(w)
    pdk_net, geos = replace_resistors_with_pdk(net, cat)
    deck = inspect_deck(geos, cat)

    write_local_spiceinit()
    ng = find_ngspice()
    hy = ident["hy_at_imax"]
    z_ref = ident["z_at_imax"]

    print("==== Phase 1–2 DC analog error (W=1 PDK R + behavioral TIA) ====", flush=True)
    dc_rows = []
    for corner in ("tt", "ll", "hh"):
        path = CIRCUIT_DIR / f"o2_pdk_r_behav_{corner}_t27.cir"
        body = prepend_pdk(pdk_net, corner, 27.0)
        body = body.replace(
            "* Experiment 39 SKY130 isolated frozen o2 cell",
            "* Experiment 40 SKY130 isolated catalog o2 / W2[1]",
        )
        write_op_net(path, body, hy, extra_prints=[f"i(V{TAG}dummy)"] if False else None)
        rec = eval_cell(ng, path, z_ref, timeout=240.0)
        rec["name"] = f"pdk_r_behav_{corner}_27"
        rec["corner"] = corner
        rec["temp_C"] = 27.0
        rec["implementation"] = "W=1 PDK xhigh_po + behavioral TIA A=1e5"
        dc_rows.append(rec)
        print(
            f"  {corner} y={rec.get('y')} err={rec.get('err')} "
            f"|err|={rec.get('abs_err')} pass={rec.get('analog_pass')} fail={rec.get('failure_reason')}",
            flush=True,
        )
        if rec.get("failed"):
            _die(f"SPICE failed on {corner}: {rec.get('failure_reason')}")

    nom = dc_rows[0]
    analog = "PASS" if nom.get("analog_pass") else "FAIL"
    corners_ok = all(
        (not r.get("failed")) and math.isclose(r["abs_err"], nom["abs_err"], rel_tol=0, abs_tol=1e-15)
        or (not r.get("failed"))
        for r in dc_rows
    )
    same_err = all(
        not r.get("failed") and r.get("abs_err") == nom.get("abs_err") for r in dc_rows
    )
    classification = {
        "identity": "PASS",
        "analog_bar": analog,
        "corners": "MEASURED" if all(not r.get("failed") for r in dc_rows) else "FAIL",
        "matching": "UNRESOLVED",
        "corners_identical_error": same_err,
    }
    decision = decide(dc_rows)
    discrepancy = (
        "Analog bar FAIL on identity-correct o2."
        if analog == "FAIL"
        else "None."
    )
    report = {
        "experiment_id": "exp40",
        "spice_source_of_truth": True,
        "frozen_weights_edited": False,
        "python_correction": False,
        "exp39_modified": False,
        "pdk": pdk,
        "identity": ident,
        "deck": deck,
        "dc_results": dc_rows,
        "classification": classification,
        "decision": decision,
        "matching": "UNRESOLVED",
        "discrepancy": discrepancy,
        "not_tested": [
            "W=10 geometry",
            "5V miller TIA",
            "MC n>=100",
            "MOS mismatch",
            "F40 classification",
            "temperature sweep",
            "circuit-level TCR",
        ],
    }
    write_reports(report)
    print("", flush=True)
    print(f"Experiment 40 decision: {decision['letter']}", flush=True)
    print(f"SIM_TARGET = {SIM_TARGET}", flush=True)
    print(f"analog |err|={nom.get('abs_err')} pass={nom.get('analog_pass')}", flush=True)
    print("matching: UNRESOLVED", flush=True)
    print("STOP: first correct o2 DC/identity complete. No optimization.", flush=True)


if __name__ == "__main__":
    main()
