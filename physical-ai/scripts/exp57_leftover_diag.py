"""Experiment 57: diagnose the +0.48 mV xhigh_po leftover.

Does not modify Experiments 1-56. Behavioral TIA A=1e6. No tt_mm.
No resistor fitting. Ideal-R control plus input-scale sweep.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from compile_xor import PROJECT_ROOT, find_ngspice
from exp39_pdk_o2_cell import PDK_VERSION, discover_pdk, eval_cell, prepend_pdk, write_op_net
from exp40_pdk_o2_cell import compile_o2_w2_1, prove_identity
from exp41_o2_residual import replace_resistors_w
from exp43_highgain_w10 import set_tia_gain
from exp45_documented_tia import spiceinit_hsa
from exp54_resistor_tiling import A, Z_O2, check_geos, tile_same_units

CIRCUIT_DIR = PROJECT_ROOT / "circuits" / "exp57_o2"
RESULTS_DIR = PROJECT_ROOT / "results"
Y_W10 = 2.459890565832
Y_W20_8 = 2.459968223476
SCALES = [0.10, 0.25, 0.50, 1.00]
RFG = 140.89398023224967


def k_finite(a: float = A) -> float:
    return a / (a + 1.0 + RFG)


def run(ng, name: str, net: str, hy, z_ref: float) -> dict:
    path = CIRCUIT_DIR / f"{name}.cir"
    write_op_net(
        path,
        prepend_pdk(net, "tt", 27.0).replace(
            "* Experiment 39 SKY130 isolated frozen o2 cell",
            f"* Experiment 57 leftover {name}",
        ),
        hy,
    )
    rec = eval_cell(ng, path, z_ref, timeout=300.0)
    rec.update({"name": name, "python_corrected": False})
    print(
        f"  {name} z={z_ref:.9f} y={rec.get('y')} err={rec.get('err')} "
        f"|err|={rec.get('abs_err')}",
        flush=True,
    )
    return rec


def classify(rows: list[dict]) -> str:
    full = [r for r in rows if r.get("scale") == 1.0 and r.get("err") is not None]
    small = [r for r in rows if r.get("scale") == 0.1 and r.get("err") is not None]
    if not full or not small:
        return "E"
    # ratio-like: err scales with z; offset-like: err stays put
    ratios = []
    for fabric in ("ideal", "w10", "w20_8s8p"):
        f1 = next((r for r in full if r["fabric"] == fabric), None)
        f0 = next((r for r in small if r["fabric"] == fabric), None)
        if f1 and f0 and abs(float(f1["err"])) > 1e-6:
            ratios.append(abs(float(f0["err"]) / float(f1["err"])))
    if not ratios:
        return "E"
    mean_r = float(sum(ratios) / len(ratios))
    # scale 0.1 / scale 1.0; ratio-like ~0.1, offset-like ~1, VC even smaller
    if mean_r < 0.25:
        return "ratio"
    if mean_r > 0.7:
        return "offset"
    return "mixed"


def main() -> None:
    ident = prove_identity()
    w = ident.pop("weights")
    pdk = discover_pdk()
    if pdk.get("ciel_current") != PDK_VERSION:
        raise SystemExit("BLOCKED PDK")
    net0, cat, _ = compile_o2_w2_1(w)
    z0 = float(ident["z_at_imax"])
    if not math.isclose(z0, Z_O2, rel_tol=0, abs_tol=1e-12):
        raise SystemExit("BLOCKED z")
    b2 = float(ident["b2"])
    hy0 = np.asarray(ident["hy_at_imax"], dtype=float)
    CIRCUIT_DIR.mkdir(parents=True, exist_ok=True)
    spiceinit_hsa(CIRCUIT_DIR)
    ng = find_ngspice()

    w10, g10 = replace_resistors_w(net0, cat, 10.0)
    w20, g20 = replace_resistors_w(net0, cat, 20.0)
    check_geos(g10)
    check_geos(g20)
    nets = {
        "ideal": set_tia_gain(net0, A),
        "w10": set_tia_gain(w10, A),
        "w20_8s8p": tile_same_units(set_tia_gain(w20, A), 8, 8),
    }

    rows = []
    print("==== Input-scale leftover sweep A=1e6 tt ====", flush=True)
    for scale in SCALES:
        hy = hy0 * scale
        z_ref = scale * (z0 - b2) + b2
        for fabric, net in nets.items():
            rec = run(ng, f"{fabric}_s{scale:.2f}".replace(".", "p"), net, hy, z_ref)
            err = rec.get("err")
            rows.append(
                {
                    "fabric": fabric,
                    "scale": scale,
                    "z_ref": z_ref,
                    "y": rec.get("y"),
                    "err": err,
                    "abs_err": rec.get("abs_err"),
                    "err_over_z": None if err is None or z_ref == 0 else err / z_ref,
                    "analog_pass": rec.get("analog_pass"),
                    "failed": rec.get("failed"),
                    "k_z": k_finite() * z_ref,
                    "err_vs_kz": None if rec.get("y") is None else float(rec["y"]) - k_finite() * z_ref,
                }
            )

    full = {r["fabric"]: r for r in rows if r["scale"] == 1.0}
    if full.get("w10") and full["w10"].get("y") is not None:
        if abs(float(full["w10"]["y"]) - Y_W10) > 1e-8:
            print(f"  WARN w10 y={full['w10']['y']} vs Exp53 {Y_W10}", flush=True)
    if full.get("w20_8s8p") and full["w20_8s8p"].get("y") is not None:
        if abs(float(full["w20_8s8p"]["y"]) - Y_W20_8) > 5e-7:
            print(f"  WARN w20_8s8p y={full['w20_8s8p']['y']} vs Exp56 {Y_W20_8}", flush=True)

    decomp = {}
    if all(f in full and full[f].get("y") is not None for f in ("ideal", "w10", "w20_8s8p")):
        yi, yw, ya = (float(full[f]["y"]) for f in ("ideal", "w10", "w20_8s8p"))
        decomp = {
            "finite_A_ideal_minus_z_mV": (yi - z0) * 1e3,
            "w10_minus_ideal_mV": (yw - yi) * 1e3,
            "w20_8s8p_minus_ideal_mV": (ya - yi) * 1e3,
            "w20_8s8p_minus_w10_mV": (ya - yw) * 1e3,
            "analytic_kz_minus_z_mV": (k_finite() * z0 - z0) * 1e3,
        }

    kind = classify(rows)
    if kind == "ratio":
        decision, label, status = (
            "A",
            "LEFTOVER IS RATIO / ENCODE ERROR, NOT tt_mm",
            "DEMONSTRATED",
        )
        nxt = (
            "Experiment 58: host W=20 8s8p (or W=10 8s8p) on OPA189 with leftover "
            "stated as the analog floor. Do not enlarge arrays. Not silicon."
        )
    elif kind == "offset":
        decision, label, status = (
            "B",
            "LEFTOVER IS OFFSET-LIKE (DOES NOT SCALE WITH z)",
            "PARTIALLY VALIDATED",
        )
        nxt = "Experiment 58: search documented VC/head mechanism; do not invent W/L."
    elif kind == "mixed":
        decision, label, status = (
            "B",
            "LEFTOVER HAS BOTH RATIO AND ABSOLUTE PARTS",
            "PARTIALLY VALIDATED",
        )
        nxt = (
            "Experiment 58: OPA189 + large array with leftover budget stated; "
            "do not enlarge arrays further."
        )
    else:
        decision, label, status = (
            "E",
            "LEFTOVER SWEEP DID NOT CONVERGE",
            "NUMERICAL ISSUE",
        )
        nxt = "Re-run leftover diagnosis before any promotion."

    report = {
        "experiment_id": "exp57",
        "kind": "xhigh_po leftover diagnosis at A=1e6",
        "status": status,
        "decision": decision,
        "decision_label": label,
        "yield_claim": False,
        "silicon": False,
        "realism_level": 4,
        "leftover_kind": kind,
        "k_finite": k_finite(),
        "decomp_full_scale": decomp,
        "rows": rows,
        "physical_tia_validated": False,
        "miller_family": "CLOSED",
        "next_experiment": nxt,
        "conclusion": (
            f"Decision {decision} — {label}. "
            "Matching arrays are not the tool for this residual. "
            "OPA189 remains the Level-1 TIA host. Miller family remains closed."
        ),
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / "exp57_leftover_diag.json").write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8"
    )
    lines = [
        "# Experiment 57 — xhigh_po leftover diagnosis",
        "",
        "Experiments 1-56 were not modified. Behavioral TIA A=1e6. No tt_mm.",
        "",
        f"**Status: {status}**",
        f"**Decision {decision} — {label}**",
        "",
        f"Leftover class: **{kind}**",
        "",
        "## Full-scale decomposition (vec 19)",
        "",
        json.dumps(decomp, indent=2),
        "",
        "## Scale sweep",
        "",
        "| fabric | scale | z (V) | y (V) | err (mV) | err/z |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for r in rows:
        err = r.get("err")
        lines.append(
            f"| {r['fabric']} | {r['scale']} | {r['z_ref']:.9f} | {r.get('y')} | "
            f"{None if err is None else err * 1e3:.6f} | {r.get('err_over_z')} |"
        )
    lines += ["", report["conclusion"], "", "## Next experiment", "", nxt, ""]
    (RESULTS_DIR / "exp57_leftover_diag.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"Experiment 57 Decision {decision} — {label} kind={kind}", flush=True)


if __name__ == "__main__":
    main()
