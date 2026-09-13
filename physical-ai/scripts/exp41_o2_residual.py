"""Experiment 41: decompose Experiment 40 o2 residual.

Does not modify Experiments 39 or 40. Does not edit weights.
Does not change the 1 mV bar. Diagnostics are not a design solution.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

from compile_xor import PROJECT_ROOT, find_ngspice
from exp39_pdk_o2_cell import (
    ERROR_LIMIT,
    PDK_VERSION,
    RES_MODEL,
    TAG,
    XHIGH_PELGROM,
    discover_pdk,
    eval_cell,
    insert_miller,
    pelgrom_sigma,
    prepend_pdk,
    replace_resistors_with_pdk,
    write_op_net,
    xhigh_r_pred,
)
from exp40_pdk_o2_cell import CATALOG, compile_o2_w2_1, prove_identity
from offset_vg_search import bake_vin_dc

CIRCUIT_DIR = PROJECT_ROOT / "circuits" / "exp41_o2"
RESULTS_DIR = PROJECT_ROOT / "results"

Z_O2 = 2.459489570880132
Y_EXP40 = 2.45254388951
ERR_EXP40 = Y_EXP40 - Z_O2
A_BEHAV = 1.0e5
RFG = CATALOG["Rf_Gtot"]
RF = 1.0 / 3.0e-5

MILLER_SIZES = {
    "L": 1.0,
    "WT": 3.029,
    "WD": 6.059,
    "WL": 6.059,
    "WON": 12.118,
    "WOP": 24.236,
    "IBIAS": 8e-05,
    "CC": 2e-12,
    "servo_c": 1e-09,
}


def finite_a_analytic() -> dict:
    k = A_BEHAV / (A_BEHAV + 1.0 + RFG)
    y_pred = k * Z_O2
    err_a = y_pred - Z_O2
    unexplained = Y_EXP40 - y_pred
    rec = {
        "label": "analytical",
        "A": A_BEHAV,
        "Rf_G": RFG,
        "k": k,
        "z_o2": Z_O2,
        "y_pred_finite_A": y_pred,
        "y_exp40": Y_EXP40,
        "err_finite_A_V": err_a,
        "err_finite_A_mV": err_a * 1e3,
        "err_exp40_V": ERR_EXP40,
        "err_exp40_mV": ERR_EXP40 * 1e3,
        "unexplained_after_finite_A_V": unexplained,
        "unexplained_after_finite_A_mV": unexplained * 1e3,
        "finite_A_explains_all_6p946mV": abs(err_a) >= abs(ERR_EXP40) * 0.99
        and math.isclose(Y_EXP40, y_pred, rel_tol=0, abs_tol=2e-4),
        "finite_A_alone_exceeds_1mV_bar": abs(err_a) > ERROR_LIMIT,
        "fraction_of_total": abs(err_a) / abs(ERR_EXP40),
    }
    print("==== Step 1 finite-A (analytical, no SPICE) ====", flush=True)
    print(f"  k={k:.12f}", flush=True)
    print(f"  y_pred=k*z={y_pred:.12f} V  finite-A err={err_a*1e3:.6f} mV", flush=True)
    print(f"  y_exp40={Y_EXP40:.12f} V  total err={ERR_EXP40*1e3:.6f} mV", flush=True)
    print(
        f"  unexplained after finite-A={unexplained*1e3:.6f} mV  "
        f"finite-A fraction={rec['fraction_of_total']:.4f}",
        flush=True,
    )
    print(
        f"  Can finite A explain 6.946 mV? NO. It predicts {abs(err_a)*1e3:.3f} mV "
        f"and already exceeds the 1 mV bar.",
        flush=True,
    )
    return rec


def spiceinit() -> None:
    CIRCUIT_DIR.mkdir(parents=True, exist_ok=True)
    text = (
        "set ngbehavior=hsa\nset skywaterpdk\nset ng_nomodcheck\n"
        "set num_threads=4\noption klu\nunset interactive\n"
    )
    (CIRCUIT_DIR / ".spiceinit").write_text(text, encoding="ascii")
    (CIRCUIT_DIR / "spiceinit").write_text(text, encoding="ascii")


def tag_exp41(net: str) -> str:
    return net.replace(
        "* Experiment 39 SKY130 isolated frozen o2 cell",
        "* Experiment 41 diagnostic · catalog o2 / W2[1] · not a design solution",
    )


def geometry_for_r_w(r_ohm: float, w: float) -> tuple[float, float]:
    lo, hi = 0.25, 8000.0
    for _ in range(45):
        mid = 0.5 * (lo + hi)
        if xhigh_r_pred(w, mid) < r_ohm:
            lo = mid
        else:
            hi = mid
    return w, 0.5 * (lo + hi)


def replace_resistors_w(netlist: str, catalog: list[dict], w: float):
    by_name = {str(it["name"]): float(it["R"]) for it in catalog if "R" in it}
    r_re = re.compile(r"^(R)(\S+)\s+(\S+)\s+(\S+)\s+([0-9.+-eE]+)\s*$", re.IGNORECASE)
    out, geos = [], []
    for raw in netlist.splitlines():
        m = r_re.match(raw.strip())
        if not m:
            out.append(raw)
            continue
        name = m.group(1) + m.group(2)
        n1, n2, rval = m.group(3), m.group(4), float(m.group(5))
        target = by_name.get(name, rval)
        w_um, l_um = geometry_for_r_w(target, w)
        geos.append(
            {
                "name": name,
                "R_target": target,
                "w_um": w_um,
                "l_um": l_um,
                "R_pred": xhigh_r_pred(w_um, l_um),
                "pelgrom_sigma": pelgrom_sigma(w_um, l_um),
            }
        )
        out.append(f"* PDK {RES_MODEL} {name} W={w_um:g} L={l_um:.8g}")
        out.append(f"X{name} {n1} {n2} 0 {RES_MODEL} w={w_um:.8g} l={l_um:.8g}")
    return "\n".join(out) + "\n", geos


def run_named(ng, path: Path, net: str, hy, z_ref: float, name: str, extra=None, extra_names=None):
    write_op_net(path, tag_exp41(net), hy, extra_prints=extra)
    rec = eval_cell(ng, path, z_ref, extra_names=extra_names, timeout=300.0)
    rec["name"] = name
    rec["kind"] = "controlled diagnostic"
    print(
        f"  {name} y={rec.get('y')} err={rec.get('err')} |err|={rec.get('abs_err')} "
        f"pass={rec.get('analog_pass')} fail={rec.get('failure_reason')}",
        flush=True,
    )
    return rec


def vc_bench(ng, w: float, l: float, volts: list[float]) -> list[dict]:
    rows = []
    for v in volts:
        path = CIRCUIT_DIR / f"rf_vc_w{w:g}_v{v}.cir"
        path.write_text(
            "\n".join(
                [
                    "* Experiment 41 Rf voltage-coefficient diagnostic",
                    f'.lib "{Path(r"C:/dev/pdk/sky130A/libs.tech/ngspice/sky130.lib.spice").as_posix()}" tt',
                    ".temp 27",
                    f"Vr r 0 DC {v:.8g}",
                    "Vm m 0 DC 0",
                    f"Xrf r m 0 {RES_MODEL} w={w:.8g} l={l:.8g}",
                    ".control",
                    "set numdgt=12",
                    "op",
                    "print i(Vr)",
                    ".endc",
                    ".end",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        from exp39_pdk_o2_cell import last, run_cir
        from test_robustness import extract_all

        _r, text, fail = run_cir(ng, path, timeout=60.0)
        i = last(extract_all(text, "i(vr)"))
        rmeas = abs(v / i) if i not in (None, 0.0) else None
        rows.append({"V": v, "I": i, "R_ohm": rmeas, "failed": bool(fail)})
        print(f"  VC V={v} R={rmeas} fail={fail}", flush=True)
    return rows


def write_reports(report: dict) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / "exp41_o2_residual.json").write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8"
    )
    fa = report["finite_a"]
    tab = report["diagnostic_table"]
    w10 = report["diagnostics"].get("w10") or {}
    mill = report["diagnostics"].get("miller") or {}
    ideal = report["diagnostics"].get("ideal_r") or {}
    lines = [
        "# Experiment 41 — o2 residual decomposition (CLOSED diagnostic)",
        "",
        "Experiments 39 and 40 were not modified. Weights and the 1 mV bar were not changed.",
        "Diagnostics are not a design solution. Experiment 40 Decision C is unchanged.",
        "",
        "## Central question",
        "",
        "Why is catalog o2 6.946 mV from z_o2, and how much is amplifier finite-A",
        "versus the current PDK resistor implementation?",
        "",
        "## Baseline (Experiment 40, not rerun)",
        "",
        f"- Target o2 / W2[1]. Rf·G = {RFG}. z_o2 = {Z_O2} V.",
        f"- y = {Y_EXP40} V. err = {ERR_EXP40} V = {ERR_EXP40*1e3:.9f} mV. Analog bar **FAIL**.",
        "- Decision C stands.",
        "",
        "## Step 1 — finite-A (analytical, before SPICE)",
        "",
        f"- k = A/(A+1+Rf·G) = {fa['k']:.12f} at A={A_BEHAV:.0e}.",
        f"- Predicted finite-A output k·z = {fa['y_pred_finite_A']:.12f} V.",
        f"- Finite-A error = {fa['err_finite_A_mV']:.6f} mV "
        f"({fa['fraction_of_total']*100:.1f}% of 6.946 mV).",
        f"- Unexplained after finite-A vs Exp40 y: {fa['unexplained_after_finite_A_mV']:.6f} mV.",
        "- **Finite A cannot explain 6.946 mV.** It predicts ~3.485 mV and already",
        "  exceeds the 1 mV bar even with ideal resistors.",
        "",
        "## Diagnostics",
        "",
        f"- Ideal lumped R + behavioral TIA: y={ideal.get('y')} |err|={ideal.get('abs_err')} "
        f"pass={ideal.get('analog_pass')} (finite-A in SPICE).",
        f"- W=10 same-family encode: y={w10.get('y')} err={w10.get('err')} "
        f"|err|={w10.get('abs_err')} pass={w10.get('analog_pass')}.",
        f"- Exp39 Miller sizes, no resize: y={mill.get('y')} err={mill.get('err')} "
        f"|err|={mill.get('abs_err')} pass={mill.get('analog_pass')} "
        f"i_in={mill.get('i(Vn1ib)')} Idd={mill.get('i(Vddtia)')}.",
        "",
    ]
    if w10.get("analog_pass"):
        lines.append(
            "**Diagnostic configuration (W=10) passes the analog bar; "
            "Experiment 40 baseline remains FAIL.**"
        )
        lines.append("")
    if mill.get("analog_pass"):
        lines.append(
            "**Diagnostic configuration (Miller) passes the analog bar; "
            "Experiment 40 baseline remains FAIL.**"
        )
        lines.append("")
    lines += [
        "## Mechanism table",
        "",
        "| Mechanism | Predicted contribution | Measured contribution | Residual explained |",
        "| --- | ---: | ---: | ---: |",
    ]
    for row in tab:
        lines.append(
            f"| {row['mechanism']} | {row['predicted']} | {row['measured']} | {row['explained']} |"
        )
    lines += [
        "",
        "## Conclusion",
        "",
        report["conclusion"],
        "",
        "## Status",
        "",
        "- Experiment 40 Decision C: unchanged.",
        "- Matching: **UNRESOLVED**.",
        "- F40 classification: **NOT TESTED**.",
        "- Temperature: **NOT TESTED**.",
        "- Network-F 2.937183 V hosting: **NOT DEMONSTRATED**.",
        "- W=10 / Miller: **controlled diagnostics**, not a new design result.",
        "",
        "## Geometry vs matching (not conflated)",
        "",
        report.get("geometry_note", ""),
        "",
        "No Experiment 42. No optimization.",
    ]
    (RESULTS_DIR / "exp41_o2_residual.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    fa = finite_a_analytic()
    print("==== identity W2[1] ====", flush=True)
    ident = prove_identity()
    w = ident.pop("weights")
    pdk = discover_pdk()
    if pdk.get("ciel_current") != PDK_VERSION:
        raise SystemExit(f"BLOCKED PDK hash {pdk.get('ciel_current')}")
    net, cat, _reason = compile_o2_w2_1(w)
    hy = ident["hy_at_imax"]
    z_ref = float(ident["z_at_imax"])
    if not math.isclose(z_ref, Z_O2, rel_tol=0, abs_tol=1e-12):
        raise SystemExit(f"BLOCKED z_ref {z_ref} != {Z_O2}")

    spiceinit()
    ng = find_ngspice()
    diags = {}

    print("==== Diagnostic: ideal lumped R + behavioral TIA (finite-A in SPICE) ====", flush=True)
    path = CIRCUIT_DIR / "o2_ideal_r_behav_tt_27.cir"
    diags["ideal_r"] = run_named(
        ng, path, prepend_pdk(net, "tt", 27.0), hy, z_ref, "ideal_r_behav_tt_27"
    )

    print("==== Step 2: W=10 same-family encode (diagnostic) ====", flush=True)
    pdk10, geos10 = replace_resistors_w(net, cat, 10.0)
    diags["w10"] = run_named(
        ng,
        CIRCUIT_DIR / "o2_pdk_r_w10_tt_27.cir",
        prepend_pdk(pdk10, "tt", 27.0),
        hy,
        z_ref,
        "pdk_r_w10_tt_27",
    )
    diags["w10"]["geometry"] = "W=10 um established Exp39 encode; diagnostic not optimization"
    rf10 = next((g for g in geos10 if g["name"] == "Rn1f"), None)

    print("==== Step 3: Exp39 5V Miller sizes, no resize (diagnostic) ====", flush=True)
    pdk1, _ = replace_resistors_with_pdk(net, cat)
    miller_net = insert_miller(pdk1, MILLER_SIZES, servo=False, vsupply=2.5)
    diags["miller"] = run_named(
        ng,
        CIRCUIT_DIR / "o2_miller_noservo_tt_27.cir",
        prepend_pdk(miller_net, "tt", 27.0),
        hy,
        z_ref,
        "miller_noservo_tt_27",
        extra=["i(Vddtia)", "i(Vsstia)", f"i(V{TAG}ib)"],
        extra_names=["i(Vddtia)", "i(Vsstia)", f"i(V{TAG}ib)"],
    )
    diags["miller"]["sizes"] = MILLER_SIZES

    print("==== Step 4: Rf voltage-coefficient benches ====", flush=True)
    vc1 = vc_bench(ng, 1.0, 15.7170614549824, [0.2, 1.0, 2.45254388951])
    vc10 = vc_bench(ng, 10.0, float(rf10["l_um"]) if rf10 else 165.627705, [0.2, 1.0, 2.45254388951])

    y_k = fa["y_pred_finite_A"]
    y_id = diags["ideal_r"].get("y")
    y10 = diags["w10"].get("y")
    ym = diags["miller"].get("y")
    meas_a = (y_id - Z_O2) if y_id is not None else None
    leftover_w1 = Y_EXP40 - y_k
    leftover_w10 = (y10 - y_k) if y10 is not None else None
    leftover_id = (y_id - y_k) if y_id is not None else None
    r02 = next(r["R_ohm"] for r in vc1 if r["V"] == 0.2)
    r245 = next(r["R_ohm"] for r in vc1 if abs(r["V"] - 2.45254388951) < 1e-9)
    vc_frac = (r245 - r02) / r02 if r02 else None

    # Geometry sensitivity: leftover after finite-A at W=1 vs W=10. Not an optimum search.
    geo_note = (
        f"Deterministic leftover after finite-A: W=1 {leftover_w1*1e3:.3f} mV; "
        f"W=10 {None if leftover_w10 is None else leftover_w10*1e3:.3f} mV. "
        "This is not matching. Pelgrom at used Rf W=1 WL=15.72 um2 remains "
        f"sigma={XHIGH_PELGROM/math.sqrt(15.7170614549824):.4%} (1σ body); "
        "matching UNRESOLVED. A W that shrinks leftover is not a 0.075% proof."
    )

    tab = [
        {
            "mechanism": "Finite A",
            "predicted": f"{fa['err_finite_A_mV']:.3f} mV (k*z − z)",
            "measured": "n/a" if meas_a is None else f"{meas_a*1e3:.3f} mV (ideal-R SPICE − z)",
            "explained": f"{fa['fraction_of_total']*100:.1f}% of Exp40 |err|; cannot explain all 6.946 mV",
        },
        {
            "mechanism": "Resistor heads/length encoding",
            "predicted": "xhigh_po L-encode matches R_target at V=0 pred eq.; leftover is heads+unmodeled vs that eq.",
            "measured": "n/a"
            if leftover_w10 is None
            else f"W=1 leftover {leftover_w1*1e3:.3f} mV; W=10 leftover {leftover_w10*1e3:.3f} mV (vs k*z)",
            "explained": "W=10 vs W=1 isolates geometry/heads (same A, same weights)",
        },
        {
            "mechanism": "Voltage coefficient",
            "predicted": "card voltco; Exp39 1.0→2.5 V R drop ~0.18% on W=1 L=15.72",
            "measured": f"Rf W=1 R(0.2V)={r02:.2f} Ω R(2.45V)={r245:.2f} Ω dR/R={vc_frac}",
            "explained": "partial; common-mode VC on all xhigh_po tends to cancel in Rf·G; leftover is differential VC vs L",
        },
        {
            "mechanism": "Transistor operating point",
            "predicted": "not in Exp40 baseline (behavioral TIA)",
            "measured": "n/a"
            if ym is None
            else f"Miller y={ym} |err|={diags['miller'].get('abs_err')} (diagnostic)",
            "explained": "Exp40 residual is not a FET OP effect; Miller is a separate diagnostic",
        },
        {
            "mechanism": "Interaction",
            "predicted": "finite-A × PDK R scale error add in |y−z|",
            "measured": f"3.485 mV + {leftover_w1*1e3:.3f} mV ≈ {ERR_EXP40*1e3:.3f} mV",
            "explained": "sum matches Exp40 total within rounding",
        },
        {
            "mechanism": "Other",
            "predicted": "invert VCVS, 27 C vs tnom 25 C",
            "measured": f"ideal-R vs k*z = {leftover_id if leftover_id is None else leftover_id*1e3:.4f} mV",
            "explained": "small if ideal-R tracks k*z",
        },
    ]

    conclusion = (
        f"Experiment 40 |y−z| = {ERR_EXP40*1e3:.3f} mV splits as finite-A "
        f"{fa['err_finite_A_mV']:.3f} mV (amplifier implementation, A=1e5, "
        f"uncompensated Architecture A on Rf·G=140.894) plus about "
        f"{leftover_w1*1e3:.3f} mV deterministic PDK xhigh_po leftover at W=1 "
        f"(heads / length encode / differential VC). Finite A alone already "
        f"fails the 1 mV bar. W=10 and Miller are diagnostics only. "
        f"Matching remains UNRESOLVED. Experiment 40 Decision C is unchanged."
    )

    report = {
        "experiment_id": "exp41",
        "exp39_modified": False,
        "exp40_modified": False,
        "exp40_decision_unchanged": "C",
        "kind": "controlled diagnostic",
        "finite_a": fa,
        "identity": {k: ident[k] for k in ident if k != "W2_row" and k != "hy_at_imax"},
        "pdk": {"version": pdk["version"], "ciel_current": pdk["ciel_current"]},
        "diagnostics": diags,
        "vc_w1": vc1,
        "vc_w10": vc10,
        "diagnostic_table": tab,
        "geometry_note": geo_note,
        "conclusion": conclusion,
        "matching": "UNRESOLVED",
        "network_2937_hosting": "NOT DEMONSTRATED",
        "not_tested": ["F40 classification", "temperature", "Monte Carlo", "MOS mismatch"],
    }
    write_reports(report)
    print("", flush=True)
    print("Experiment 41 diagnostic complete. Experiment 40 Decision C unchanged.", flush=True)
    print("STOP. No optimization.", flush=True)


if __name__ == "__main__":
    main()
