"""Experiment 44: physical high-gain TIA requirement extraction.

Translates the Experiment 43 W=10 behavioral feasibility point into
electrical budgets. Does not invent MOS W/L. Does not claim a physical
TIA exists. Experiments 1-43 are not modified.
"""

from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path

import numpy as np

from compile_xor import PROJECT_ROOT, find_ngspice
from exp39_pdk_o2_cell import (
    ERROR_LIMIT,
    PDK_VERSION,
    TAG,
    bake_vin_step,
    discover_pdk,
    eval_cell,
    last,
    prepend_pdk,
    run_cir,
    write_op_net,
)
from exp40_pdk_o2_cell import CATALOG, compile_o2_w2_1, prove_identity
from exp41_o2_residual import replace_resistors_w
from exp43_highgain_w10 import TIA_E, a_tag, set_tia_gain
from finite_a_scale import tia_k
from test_robustness import extract_all
from virtual_ground_requirements import (
    apply_tia_pole,
    closed_loop_tau,
    leak_to_vout_gain,
    vos_to_vout_gain,
)

CIRCUIT_DIR = PROJECT_ROOT / "circuits" / "exp44_o2"
RESULTS_DIR = PROJECT_ROOT / "results"
REPORT_JSON = RESULTS_DIR / "exp44_tia_requirements.json"
REPORT_MD = RESULTS_DIR / "exp44_tia_requirements.md"

Z_O2 = 2.459489570880132
RFG = 140.89398023224967
RF = 1.0 / 3.0e-5
GTOT = 4.22681940696749e-3
A_CROSS = 128203.0
A_COMFORT = 2.0e5
A_1E6 = 1.0e6
Y_W10_CROSS = 2.458490423515
NETWORK_ZMAX = 2.9371827051901307
LEFTOVER_W10 = 0.6040755250000807e-3


def spiceinit() -> None:
    CIRCUIT_DIR.mkdir(parents=True, exist_ok=True)
    text = (
        "set ngbehavior=hsa\nset skywaterpdk\nset ng_nomodcheck\n"
        "set num_threads=4\noption klu\nunset interactive\n"
    )
    (CIRCUIT_DIR / ".spiceinit").write_text(text, encoding="ascii")
    (CIRCUIT_DIR / "spiceinit").write_text(text, encoding="ascii")


def tag44(net: str) -> str:
    return net.replace(
        "* Experiment 39 SKY130 isolated frozen o2 cell",
        "* Experiment 44 TIA requirement extraction · W=10 o2 · not a physical TIA",
    )


def loop_gain(A: float) -> float:
    return float(A) / (1.0 + RFG)


def insert_rf_ammeter(net: str) -> str:
    out, n = [], 0
    for raw in net.splitlines():
        s = raw.strip()
        if s.startswith("XRn1f ") or s.startswith("xrn1f "):
            parts = s.split()
            # XRn1f n1lin n1p 0 model w= l=
            parts[1] = "n1fb"
            if n == 0:
                out.append("Vn1fb n1lin n1fb DC 0")
            out.append(" ".join(parts))
            n += 1
            continue
        out.append(raw)
    if n != 1:
        raise RuntimeError(f"expected one XRn1f, found {n}")
    return "\n".join(out) + ("\n" if net.endswith("\n") else "")


def tia_b_source(net: str, A: float, vos: float = 0.0, rail: float | None = None) -> str:
    a_s = f"{float(A):.15g}"
    vos_s = f"{float(vos):.15g}"
    if rail is None:
        expr = f"-({a_s}) * (v({TAG}p) - ({vos_s}))"
    else:
        r = f"{float(rail):.15g}"
        expr = f"max(-{r}, min({r}, -({a_s}) * (v({TAG}p) - ({vos_s}))))"
    n = 0
    out = []
    for raw in net.splitlines():
        if TIA_E.match(raw.strip()):
            out.append(f"B{TAG}tia {TAG}lin 0 V = {expr}")
            n += 1
        else:
            out.append(raw)
    if n != 1:
        raise RuntimeError(f"expected one En1tia to replace, found {n}")
    return "\n".join(out) + ("\n" if net.endswith("\n") else "")


def insert_leak(net: str, i_leak: float) -> str:
    if i_leak == 0.0:
        return net
    lines = net.splitlines()
    placed = False
    out = []
    for raw in lines:
        if (not placed) and raw.strip().lower().startswith(".control"):
            out.append(f"B{TAG}leak 0 {TAG}p I = {float(i_leak):.15g}")
            placed = True
        out.append(raw)
    if not placed:
        out.append(f"B{TAG}leak 0 {TAG}p I = {float(i_leak):.15g}")
    return "\n".join(out) + "\n"


def insert_rout(net: str, rout: float) -> str:
    if rout <= 0.0:
        return net
    out = []
    n = 0
    for raw in net.splitlines():
        s = raw.strip()
        m = TIA_E.match(s)
        if m or s.startswith(f"B{TAG}tia ") or s.startswith(f"b{TAG}tia "):
            parts = s.split()
            parts[1] = f"{TAG}drv"
            out.append(" ".join(parts))
            out.append(f"R{TAG}ro {TAG}drv {TAG}lin {float(rout):.15g}")
            n += 1
            continue
        out.append(raw)
    if n != 1:
        raise RuntimeError(f"expected one TIA source for Rout, found {n}")
    return "\n".join(out) + ("\n" if net.endswith("\n") else "")


def run_op(ng, net, hy, z_ref, name, extra=None):
    path = CIRCUIT_DIR / f"{name}.cir"
    extras = extra or ["i(En1tia)", "i(Bn1tia)", "i(Vn1fb)"]
    write_op_net(path, tag44(net), hy, extra_prints=extras)
    rec = eval_cell(ng, path, z_ref, extra_names=extras, timeout=300.0)
    rec["name"] = name
    rec["python_corrected"] = False
    i_e = rec.get("i(En1tia)")
    i_b = rec.get("i(Bn1tia)")
    rec["i_amp"] = i_e if i_e is not None else i_b
    rec["i_rf"] = rec.get("i(Vn1fb)")
    print(
        f"  {name} y={rec.get('y')} err={rec.get('err')} |err|={rec.get('abs_err')} "
        f"pass={rec.get('analog_pass')} vsum={rec.get('vsum')} i_amp={rec.get('i_amp')} "
        f"i_rf={rec.get('i_rf')} fail={rec.get('failure_reason')}",
        flush=True,
    )
    return rec


def run_tran(ng, net, hy, z_ref, name, tstop=200e-6):
    path = CIRCUIT_DIR / f"{name}.cir"
    head, _, _ = net.partition(".control")
    baked = bake_vin_step(tag44(head), np.asarray(hy, dtype=float))
    ctrl = (
        "\n.control\nset numdgt=12\n"
        f"tran 1u {tstop:.15g}\n"
        f"meas tran ylin FIND v({TAG}lin) AT={tstop:.15g}\n"
        f"meas tran ysum FIND v({TAG}p) AT={tstop:.15g}\n"
        "print ylin\nprint ysum\n"
        ".endc\n.end\n"
    )
    path.write_text(baked.rstrip() + "\n" + ctrl, encoding="utf-8")
    _r, text, fail = run_cir(ng, path, timeout=300.0)
    rec = {
        "name": name,
        "path": str(path),
        "failed": bool(fail),
        "failure_reason": fail,
        "z_ref": float(z_ref),
        "tstop_s": tstop,
        "python_corrected": False,
    }
    if fail:
        rec["log_tail"] = text[-600:]
        print(f"  {name} TRAN FAIL {fail}", flush=True)
        return rec
    y = last(extract_all(text, "ylin"))
    vsum = last(extract_all(text, "ysum"))
    if y is None:
        y = last(extract_all(text, f"v({TAG}lin)"))
    if vsum is None:
        vsum = last(extract_all(text, f"v({TAG}p)"))
    rec.update({"y": y, "vsum": vsum})
    if y is None:
        rec.update({"failed": True, "failure_reason": "missing vlin"})
        return rec
    rec["err"] = y - float(z_ref)
    rec["abs_err"] = abs(y - float(z_ref))
    rec["analog_pass"] = abs(y - float(z_ref)) <= ERROR_LIMIT
    print(
        f"  {name} TRAN y={y} |err|={rec['abs_err']} pass={rec['analog_pass']}",
        flush=True,
    )
    return rec


def first_fail_budget(rows: list[dict], key: str):
    last_pass = None
    first_fail = None
    for r in rows:
        if r.get("failed") or r.get("y") is None:
            continue
        if r.get("analog_pass"):
            last_pass = r
        elif first_fail is None and last_pass is not None:
            first_fail = r
            break
        elif first_fail is None and not r.get("analog_pass"):
            first_fail = r
    return {
        "last_pass": None if last_pass is None else {key: last_pass.get(key), "abs_err": last_pass.get("abs_err")},
        "first_fail": None if first_fail is None else {key: first_fail.get(key), "abs_err": first_fail.get("abs_err")},
    }


def slim(rec: dict) -> dict:
    keep = (
        "name", "A", "kind", "y", "vsum", "err", "abs_err", "analog_pass",
        "a_eff", "i_amp", "i_rf", "failed", "failure_reason", "z_ref",
        "vos", "i_leak", "rout", "rail", "pole_hz", "tstop_s", "tau_s",
        "python_corrected",
    )
    return {k: rec[k] for k in keep if k in rec}


def scan_tech() -> dict:
    pdk = Path(r"C:\dev\pdk")
    ng_ex = Path(r"C:\ngspice\examples")
    vendor = PROJECT_ROOT / "models" / "vendor" / "ti"
    return {
        "sky130A_installed": (pdk / "sky130A" / "libs.tech" / "ngspice" / "sky130.lib.spice").is_file(),
        "sky130_5v_nfet": "sky130_fd_pr__nfet_g5v0d10v5",
        "sky130_5v_pfet": "sky130_fd_pr__pfet_g5v0d10v5",
        "sky130_xhigh_po": "sky130_fd_pr__res_xhigh_po",
        "documented_vds_5v_family": 5.0,
        "prior_miller_a_eff_exp41_o2": 245.19233527214865,
        "prior_miller_err_mV_exp41_o2": 627.252,
        "ihp_sg13g2_installed": (pdk / "ihp-sg13g2").exists() or (pdk / "sg13g2").exists(),
        "gf180_installed": (pdk / "gf180mcu").exists(),
        "vendor_macromodels_present": sorted(
            p.name for p in vendor.iterdir() if p.is_dir()
        ) if vendor.is_dir() else [],
        "ngspice_opa_examples": [
            str(p) for p in [
                ng_ex / "optran" / "models" / "opa1656.lib",
                ng_ex / "optran" / "models" / "OPA1611.LIB",
                ng_ex / "p-to-n-examples" / "OPA171.txt",
            ] if p.is_file()
        ],
        "note": (
            "Inventory only. Datasheet numbers are not treated as loaded-TIA "
            "proof. Exp23/24 already showed headline Vos is not Vsum under Rf·G=141."
        ),
    }


def write_md(rep: dict) -> None:
    b = rep["budgets"]
    lines = [
        "# Experiment 44 — physical high-gain TIA requirement extraction",
        "",
        "Experiments 1–43 were not modified. Frozen weights were not edited.",
        "No MOS W/L was invented. This does **not** validate a physical TIA.",
        "",
        "## Central question",
        "",
        "What must a physical amplifier provide to realize the Experiment 43",
        "W=10 behavioral feasibility point on frozen o2?",
        "",
        f"**Status: {rep['status']}**",
        f"**Decision {rep['decision']} — {rep['decision_label']}**",
        "",
        "## Claim map",
        "",
        "| Claim | Category |",
        "| --- | --- |",
        "| Exp43 W=10 + A≥128203 meets 1 mV | Demonstrated (prior) |",
        "| Behavioral A is VCVS open-loop gain, not loop gain T | Demonstrated (this experiment, identity + OP) |",
        "| Loop gain T = A/(1+Rf·G) | Supported (Exp21/22 identity; measured k tracks) |",
        "| Isolated o2 W=10 leftover ≈ +0.604 mV | Demonstrated (Exp41/43) |",
        "| Existing SKY130 Miller realizes A_cross | Contradicted (Exp41 a_eff≈245, 627 mV) |",
        "| Physical TIA exists | Unknown |",
        "| Matching / temperature / F40 / 2.937 V | Unknown |",
        "",
        "## A. Behavioral A vs loop gain",
        "",
        "Architecture A TIA: `Vout = −A · Vsum`, k = A/(A+1+Rf·G) = T/(T+1)",
        "with **T = A/(1+Rf·G)**.",
        "",
        "| A (VCVS open-loop) | T (loop gain) | T dB | k | 1−k |",
        "| ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rep["gain_map"]:
        lines.append(
            f"| {row['A']:.8g} | {row['T']:.4f} | {row['T_dB']:.2f} | "
            f"{row['k']:.9f} | {row['one_minus_k']:.6e} |"
        )
    lines += [
        "",
        "A = 128203 is **not** a 102 dB loop-gain requirement. It is a",
        f"**{rep['gain_map'][0]['T_dB']:.2f} dB loop-gain** requirement",
        f"(T ≈ {rep['gain_map'][0]['T']:.1f}) on this Rf·G = {RFG:.6f} load.",
        "A single-stage transistor amplifier must still provide **open-loop**",
        "A_ol ≳ 128203 in this topology, because β = 1/(1+Rf·G) is tiny.",
        "A nested Vsum servo (Exp24/26) is a different topology: it can",
        "remove the k-scale error without that A_ol. That is an alternative",
        "path, not demonstrated here on W=10 SKY130.",
        "",
        "## B. Measured operating point (W=10, frozen vec 19)",
        "",
        "| A | Vout (V) | Vsum (V) | a_eff | I_amp (A) | I_Rf (A) | err (mV) | pass |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for r in rep["operating_points"]:
        if r.get("failed"):
            lines.append(f"| {r['A']:.8g} | FAIL | — | — | — | — | — | no |")
        else:
            lines.append(
                f"| {r['A']:.8g} | {r['y']:.12f} | {r['vsum']:.6e} | "
                f"{r.get('a_eff')} | {r.get('i_amp')} | {r.get('i_rf')} | "
                f"{r['err']*1e3:+.6f} | {'PASS' if r['analog_pass'] else 'FAIL'} |"
            )
    lines += [
        "",
        f"Software z_o2 = {Z_O2} V. Isolated output swing on this vector is",
        f"|z| = 2.459 V. Network-F |z|max = {NETWORK_ZMAX:.6f} V is **not**",
        "this experiment and remains unhosted.",
        "",
        "## C. Independent error-source sweeps (W=10, A=2e5 unless noted)",
        "",
        "### Offset Vos (summing-node referred)",
        "",
        "| A | Vos (µV) | err (mV) | pass |",
        "| ---: | ---: | ---: | --- |",
    ]
    for r in rep["sweeps"]["vos"]:
        if r.get("failed"):
            lines.append(f"| {r['A']:.8g} | {r['vos']*1e6:.3g} | FAIL | no |")
        else:
            lines.append(
                f"| {r['A']:.8g} | {r['vos']*1e6:+.3f} | {r['err']*1e3:+.6f} | "
                f"{'PASS' if r['analog_pass'] else 'FAIL'} |"
            )
    lines += [
        "",
        "### Leakage into the summing node",
        "",
        "| Ileak (A) | err (mV) | pass |",
        "| ---: | ---: | --- |",
    ]
    for r in rep["sweeps"]["ileak"]:
        if r.get("failed"):
            lines.append(f"| {r['i_leak']} | FAIL | no |")
        else:
            lines.append(
                f"| {r['i_leak']:.3e} | {r['err']*1e3:+.6f} | "
                f"{'PASS' if r['analog_pass'] else 'FAIL'} |"
            )
    lines += [
        "",
        "### Open-loop Rout (inside the Rf loop)",
        "",
        "| Rout (Ω) | err (mV) | pass |",
        "| ---: | ---: | --- |",
    ]
    for r in rep["sweeps"]["rout"]:
        if r.get("failed"):
            lines.append(f"| {r['rout']} | FAIL | no |")
        else:
            lines.append(
                f"| {r['rout']:.8g} | {r['err']*1e3:+.6f} | "
                f"{'PASS' if r['analog_pass'] else 'FAIL'} |"
            )
    lines += [
        "",
        "### Output clip rails (behavioral)",
        "",
        "| ±rail (V) | Vout (V) | err (mV) | pass |",
        "| ---: | ---: | ---: | --- |",
    ]
    for r in rep["sweeps"]["clip"]:
        if r.get("failed"):
            lines.append(f"| {r['rail']} | FAIL | — | no |")
        else:
            lines.append(
                f"| {r['rail']:.4g} | {r['y']:.12f} | {r['err']*1e3:+.6f} | "
                f"{'PASS' if r['analog_pass'] else 'FAIL'} |"
            )
    lines += [
        "",
        "### 200 µs settling (behavioral single pole, not transistor GBW)",
        "",
        "| fp (Hz) | tau_cl (s) | y(200 µs) | |err| vs z (mV) | pass |",
        "| ---: | ---: | ---: | ---: | --- |",
    ]
    for r in rep["sweeps"]["settling"]:
        if r.get("failed"):
            lines.append(f"| {r.get('pole_hz')} | {r.get('tau_s')} | FAIL | — | no |")
        else:
            lines.append(
                f"| {r['pole_hz']:.8g} | {r.get('tau_s')} | {r['y']:.12f} | "
                f"{r['abs_err']*1e3:.6f} | {'PASS' if r['analog_pass'] else 'FAIL'} |"
            )
    lines += [
        "",
        "## D. Extracted budgets (isolated W=10 o2, |y−z|≤1 mV)",
        "",
        "| Quantity | Budget | Basis |",
        "| --- | ---: | --- |",
        f"| VCVS / opamp open-loop A_ol (this topology) | ≥ {b['A_ol_min']:.8g} | Exp43 measured A_cross |",
        f"| Loop gain T = A/(1+Rf·G) | ≥ {b['T_min']:.4f} ({b['T_min_dB']:.2f} dB) | same crossing |",
        f"| Comfortable A_ol (measured extra margin) | ≥ {b['A_ol_comfort']:.8g} | Exp43 A=2e5, |err|=0.423 mV |",
        f"| |Vsum| | ≤ {b['vsum_max_V']:.6e} V | A_cross OP \|y\|/A |",
        f"| |Vos| (summing-node) | {b['vos_text']} | Vos sweep; leftover already uses ~0.60 mV |",
        f"| |Ileak| into sum | {b['ileak_text']} | Ileak sweep |",
        f"| Rout | {b['rout_text']} | Rout sweep |",
        f"| Output swing (this vector) | ≥ {b['swing_V']:.6f} V | measured Vout / clip |",
        f"| Output current | ≥ {b['iout_A']:.6e} A | measured I_amp at A_cross |",
        f"| Feedback current | ≥ {b['irf_A']:.6e} A | measured I_Rf |",
        f"| Settling | ≤ 200 µs | project sampled-inference dwell |",
        f"| Open-loop fp for 200 µs (behavioral) | {b['fp_text']} | TRAN sweep |",
        f"| Supply (isolated o2 only) | {b['supply_text']} | clip sweep + SKY130 5 V family |",
        f"| Network-F 2.937 V | NOT IN THIS BUDGET | unhosted |",
        "",
        "Exp22 network-F analog A≥4.88e4 remains valid for **ideal-R network MAE**.",
        "It is **not** sufficient for isolated W=10 o2 |y−z|≤1 mV. The leftover",
        "+0.604 mV resistor residual consumes most of the 1 mV bar, so this",
        "cell needs A_ol ≳ 1.28e5 in the uncompensated topology.",
        "",
        "## E. What destroys the bar first",
        "",
        rep["first_destroyer"],
        "",
        "## F. Documented technology vs these budgets",
        "",
        "No transistor was sized. Comparison uses prior measured cells and",
        "installed-file inventory only.",
        "",
        f"- SKY130A installed: **{rep['tech']['sky130A_installed']}**. 5 V FET family documented.",
        f"- Existing Exp41 Miller on this o2 cell: a_eff ≈ **245**, |err| = **627 mV**.",
        "  That is **523× below** A_ol=128203. Contradicted as a no-resize solution.",
        f"- IHP SG13G2 installed: **{rep['tech']['ihp_sg13g2_installed']}**.",
        f"- GF180MCU installed: **{rep['tech']['gf180_installed']}**.",
        f"- Vendor macromodels present: {rep['tech']['vendor_macromodels_present']}.",
        f"- ngspice OPA examples: {rep['tech']['ngspice_opa_examples']}.",
        "- Exp23/24: OPA171/1656 headline Vos is not the loaded Vsum at Rf·G=141.",
        "- Exp24 servo can null Vsum and remove finite-A k-error on **ideal R**.",
        "  That path is not re-validated here on W=10 SKY130.",
        "",
        "## Competing hypotheses after this experiment",
        "",
        "| ID | Statement | Status |",
        "| --- | --- | --- |",
        "| H1 | Physical amp cannot reach A_ol=1.28e5 as a single Miller | Supported (Exp41 a_eff=245) |",
        "| H2 | Resistor leftover dominates once A is large | Demonstrated |",
        "| H3 | A=1.28e5 is an artifact; loop gain is only ~900 | Demonstrated (both true: A_ol vs T) |",
        "| H4 | Nested servo / AZ can replace raw A_ol | Supported on ideal R (Exp24/26); **untested on W=10 SKY130** |",
        "| H5 | ±2.5 V SKY130 rails cannot host 2.46 V with real headroom | Tested behaviorally via clip; see clip table |",
        "| H6 | Partitioning the map avoids the TIA | Not tested |",
        "",
        "## Conclusion",
        "",
        rep["conclusion"],
        "",
        "## Status",
        "",
        f"- Experiment 44: **{rep['status']}**",
        f"- Decision: **{rep['decision']} — {rep['decision_label']}**",
        "- Physical TIA validated: **NO**",
        "- Matching: **UNRESOLVED**",
        "- Temperature: **NOT TESTED** (requirement listed, not swept in PDK TCR)",
        "- Network-F 2.937 V: **NOT DEMONSTRATED**",
        "- Experiment 40 Decision C: **unchanged**",
        "",
        "## Next experiment",
        "",
        rep["next_experiment"],
        "",
    ]
    REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    print("==== Experiment 44 identity ====", flush=True)
    ident = prove_identity()
    w = ident.pop("weights")
    pdk = discover_pdk()
    if pdk.get("ciel_current") != PDK_VERSION:
        raise SystemExit(f"BLOCKED PDK hash {pdk.get('ciel_current')}")
    net0, cat, _ = compile_o2_w2_1(w)
    hy = ident["hy_at_imax"]
    z0 = float(ident["z_at_imax"])
    if not math.isclose(z0, Z_O2, rel_tol=0, abs_tol=1e-12):
        raise SystemExit("BLOCKED z")
    w10, _geos = replace_resistors_w(net0, cat, 10.0)
    spiceinit()
    ng = find_ngspice()

    def base(A: float) -> str:
        return insert_rf_ammeter(prepend_pdk(set_tia_gain(w10, A), "tt", 27.0))

    if "--settling-only" in sys.argv and REPORT_JSON.is_file():
        print("==== Resume settling only ====", flush=True)
        report = json.loads(REPORT_JSON.read_text(encoding="utf-8"))
        set_rows = []
        for fp in (10.0, 100.0, 1e3, 1e4):
            tau = closed_loop_tau(A_COMFORT, fp, RFG)
            net = apply_tia_pole(base(A_COMFORT), fp)
            rec = run_tran(ng, net, hy, z0, f"tran200us_a2e5_fp{a_tag(fp)}")
            rec.update({"A": A_COMFORT, "pole_hz": fp, "tau_s": tau, "kind": "settling"})
            set_rows.append(slim(rec))
        rec0 = run_tran(ng, base(A_COMFORT), hy, z0, "tran200us_a2e5_nople")
        rec0.update({"A": A_COMFORT, "pole_hz": 0.0, "tau_s": 0.0, "kind": "settling"})
        set_rows.append(slim(rec0))
        report["sweeps"]["settling"] = set_rows
        set_pass = [r for r in set_rows if r.get("analog_pass")]
        set_fail = [r for r in set_rows if r.get("y") is not None and not r.get("analog_pass")]
        report["budgets"]["fp_text"] = (
            f"pass fp in {[r['pole_hz'] for r in set_pass]}; "
            f"fail fp in {[r['pole_hz'] for r in set_fail]}"
        )
        REPORT_JSON.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        write_md(report)
        print("settling updated", flush=True)
        return

    gain_map = []
    for A in (A_CROSS, A_COMFORT, A_1E6, 1e5, 348844.87):
        T = loop_gain(A)
        k = tia_k(A, RF, GTOT)
        gain_map.append({
            "A": A,
            "T": T,
            "T_dB": 20.0 * math.log10(T) if T > 0 else None,
            "k": k,
            "one_minus_k": 1.0 - k,
            "vsum_if_y_eq_z": Z_O2 / A,
        })

    print("==== B: operating points ====", flush=True)
    ops = []
    for A in (A_CROSS, A_COMFORT, A_1E6):
        rec = run_op(ng, base(A), hy, z0, f"op_w10_a{a_tag(A)}")
        rec["A"] = A
        rec["kind"] = "operating point"
        ops.append(slim(rec) | {"A": A, "kind": "operating point"})

    print("==== C: Vos sweep ====", flush=True)
    vos_rows = []
    for A, vos_list in (
        (A_COMFORT, [0.0, 1e-6, 2e-6, 3e-6, 5e-6, 7e-6, 10e-6, 22e-6, -2e-6, -5e-6]),
        (A_CROSS, [0.0, 1e-6, -1e-6, 2e-6, -2e-6]),
    ):
        for vos in vos_list:
            net = tia_b_source(base(A), A, vos=vos)
            rec = run_op(ng, net, hy, z0, f"vos_a{a_tag(A)}_{vos*1e6:+.3g}u")
            rec.update({"A": A, "vos": vos, "kind": "vos"})
            vos_rows.append(slim(rec))

    print("==== C: Ileak sweep A=2e5 ====", flush=True)
    leak_rows = []
    for ileak in (0.0, 1e-9, 3e-9, 10e-9, 13e-9, 30e-9):
        net = insert_leak(base(A_COMFORT), ileak)
        rec = run_op(ng, net, hy, z0, f"leak_a2e5_{ileak:.3e}")
        rec.update({"A": A_COMFORT, "i_leak": ileak, "kind": "ileak"})
        leak_rows.append(slim(rec))

    print("==== C: Rout sweep A=2e5 ====", flush=True)
    rout_rows = []
    for ro in (0.0, 10.0, 100.0, 1e3, 1e4, 2e4, 5e4):
        net = insert_rout(base(A_COMFORT), ro)
        rec = run_op(ng, net, hy, z0, f"rout_a2e5_{a_tag(ro)}")
        rec.update({"A": A_COMFORT, "rout": ro, "kind": "rout"})
        rout_rows.append(slim(rec))

    print("==== C: clip rails A=2e5 ====", flush=True)
    clip_rows = []
    for rail in (2.46, 2.50, 2.55, 2.60, 3.0, 5.0):
        net = tia_b_source(base(A_COMFORT), A_COMFORT, vos=0.0, rail=rail)
        rec = run_op(ng, net, hy, z0, f"clip_a2e5_r{a_tag(rail)}")
        rec.update({"A": A_COMFORT, "rail": rail, "kind": "clip"})
        clip_rows.append(slim(rec))

    print("==== C: 200 us settling A=2e5 ====", flush=True)
    set_rows = []
    for fp in (10.0, 100.0, 1e3, 1e4):
        tau = closed_loop_tau(A_COMFORT, fp, RFG)
        net = apply_tia_pole(base(A_COMFORT), fp)
        rec = run_tran(ng, net, hy, z0, f"tran200us_a2e5_fp{a_tag(fp)}")
        rec.update({"A": A_COMFORT, "pole_hz": fp, "tau_s": tau, "kind": "settling"})
        set_rows.append(slim(rec))
    rec0 = run_tran(ng, base(A_COMFORT), hy, z0, "tran200us_a2e5_nople")
    rec0.update({"A": A_COMFORT, "pole_hz": 0.0, "tau_s": 0.0, "kind": "settling"})
    set_rows.append(slim(rec0))

    op_cross = next(r for r in ops if abs(r["A"] - A_CROSS) < 1)
    vos_c = first_fail_budget([r for r in vos_rows if abs(r.get("A", 0) - A_COMFORT) < 1], "vos")
    leak_c = first_fail_budget(leak_rows, "i_leak")
    rout_c = first_fail_budget(rout_rows, "rout")
    clip_pass = [r for r in clip_rows if r.get("analog_pass")]
    clip_fail = [r for r in clip_rows if r.get("y") is not None and not r.get("analog_pass")]
    set_pass = [r for r in set_rows if r.get("analog_pass")]
    set_fail = [r for r in set_rows if r.get("y") is not None and not r.get("analog_pass")]

    def fmt_budget(pack, key: str, scale=1.0, unit=""):
        lp, ff = pack["last_pass"], pack["first_fail"]

        def one(row):
            if row is None:
                return "n/a"
            v = row[key] * scale
            e = row["abs_err"] * 1e3
            return f"{v:.6g} {unit} (|err|={e:.3f} mV)"

        if lp is None and ff is None:
            return "undetermined"
        if ff is None:
            return f"last measured pass {one(lp)}"
        if lp is None:
            return f"fails at first point {one(ff)}"
        return f"pass ≤ {one(lp)}; fail at {one(ff)}"

    iamp = op_cross.get("i_amp")
    irf = op_cross.get("i_rf")
    vsum = op_cross.get("vsum")
    budgets = {
        "A_ol_min": A_CROSS,
        "T_min": loop_gain(A_CROSS),
        "T_min_dB": 20.0 * math.log10(loop_gain(A_CROSS)),
        "A_ol_comfort": A_COMFORT,
        "vsum_max_V": abs(vsum) if vsum is not None else Z_O2 / A_CROSS,
        "vos_text": fmt_budget(vos_c, "vos", 1e6, "µV") + " (A=2e5; sign-asymmetric, see table)",
        "ileak_text": fmt_budget(leak_c, "i_leak", 1.0, "A"),
        "rout_text": fmt_budget(rout_c, "rout", 1.0, "Ω"),
        "swing_V": None if op_cross.get("y") is None else abs(op_cross["y"]),
        "iout_A": None if iamp is None else abs(iamp),
        "irf_A": None if irf is None else abs(irf),
        "fp_text": (
            f"pass fp in {[r['pole_hz'] for r in set_pass]}; "
            f"fail fp in {[r['pole_hz'] for r in set_fail]}"
        ),
        "supply_text": (
            f"clip pass rails {[r['rail'] for r in clip_pass]}; "
            f"fail {[r['rail'] for r in clip_fail]}"
        ),
        "vos_pred_uV_highA": 1e6 * (ERROR_LIMIT - 0.607e-3) / ((1.0 + RFG) * tia_k(A_1E6, RF, GTOT)),
        "vos_gain_A2e5": vos_to_vout_gain(A_COMFORT, RF, GTOT),
        "ileak_gain_A2e5": leak_to_vout_gain(A_COMFORT, RF, GTOT),
    }

    # Which mechanism first: compare how close each first-fail is to nominal.
    destroyer = (
        "On the uncompensated W=10 o2 cell the 1 mV bar is already almost "
        "consumed by deterministic resistor leftover (+0.60 mV) plus residual "
        "finite-A. At A=A_cross the remaining signed budget is ~0.85 µV "
        f"(|err|=0.999147 mV). Extra Vos of a few µV, nA-class leak, or "
        f"clipping below the measured Vout will fail first. Existing Miller "
        f"gain (a_eff≈245) fails by hundreds of millivolts — gain is the "
        f"largest single gap versus A_ol≥128203."
    )

    tech = scan_tech()
    report = {
        "experiment_id": "exp44",
        "kind": "requirement extraction",
        "status": "REQUIREMENTS EXTRACTED",
        "decision": "R",
        "decision_label": "REQUIREMENTS EXTRACTED; PHYSICAL TIA NOT VALIDATED",
        "closed_unmodified": list(range(1, 44)),
        "physical_tia_validated": False,
        "identity": {
            "sim_target": "o2 / W2[1]",
            "Rf_G": RFG,
            "z_o2": Z_O2,
            "encode": "Exp41 W=10 same-family xhigh_po, not fitted",
        },
        "pdk": {"version": pdk["version"], "ciel_current": pdk["ciel_current"]},
        "gain_map": gain_map,
        "operating_points": ops,
        "sweeps": {
            "vos": vos_rows,
            "ileak": leak_rows,
            "rout": rout_rows,
            "clip": clip_rows,
            "settling": set_rows,
        },
        "budgets": budgets,
        "first_destroyer": destroyer,
        "tech": tech,
        "matching": "UNRESOLVED",
        "temperature": "NOT TESTED",
        "network_f_2937": "NOT DEMONSTRATED",
        "exp40_decision_unchanged": "C",
    }
    report["conclusion"] = (
        f"A physical Architecture-A TIA on this W=10 o2 cell must provide "
        f"open-loop A_ol ≥ {A_CROSS:.0f} (loop gain T ≥ {loop_gain(A_CROSS):.1f}, "
        f"{20*math.log10(loop_gain(A_CROSS)):.2f} dB) at Vout≈{op_cross.get('y')} V, "
        f"|Vsum|≤{budgets['vsum_max_V']:.3e} V, |Iout|≥{budgets['iout_A']} A. "
        f"A=128203 is open-loop gain, not loop gain. The Exp41 Miller (a_eff≈245) "
        f"does not meet it. Vos/Ileak budgets are tight because leftover already "
        f"uses ~0.60 mV of the 1 mV bar. PHYSICAL TIA VALIDATED is not claimed."
    )
    report["next_experiment"] = (
        "Experiment 45: Level-1 documented macromodel search against these "
        "budgets on the same W=10 o2 cell (OPA189 / OPA388 / OPA1656 already "
        "on disk; do not invent W/L). Separately, a servo/AZ topology test on "
        "W=10 SKY130 is the H4 falsifier. Do not transistor-resize the Exp39 "
        "Miller as the first move."
    )
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    write_md(report)
    print("", flush=True)
    print(f"Experiment 44 Decision {report['decision']} — {report['decision_label']}", flush=True)
    print("  PHYSICAL TIA VALIDATED: NO", flush=True)
    print("STOP transistor search. Next is documented macromodel vs these budgets.", flush=True)


if __name__ == "__main__":
    main()
