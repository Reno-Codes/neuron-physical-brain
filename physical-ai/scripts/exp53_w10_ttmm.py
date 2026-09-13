"""Experiment 53: official SKY130 tt_mm mismatch on W=10 o2.

Behavioral TIA A=1e6 (Experiment 43 pass point). No resistor fitting.
No Python correction. Model AGAUSS, not foundry yield.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from compile_xor import PROJECT_ROOT, find_ngspice
from exp39_pdk_o2_cell import (
    ERROR_LIMIT,
    PDK_VERSION,
    discover_pdk,
    eval_cell,
    prepend_pdk,
    write_op_net,
)
from exp40_pdk_o2_cell import compile_o2_w2_1, prove_identity
from exp41_o2_residual import replace_resistors_w
from exp43_highgain_w10 import set_tia_gain
from exp45_documented_tia import spiceinit_hsa
from exp48_w10_miller_servo import Z_O2

CIRCUIT_DIR = PROJECT_ROOT / "circuits" / "exp53_o2"
RESULTS_DIR = PROJECT_ROOT / "results"
A = 1.0e6
N_MC = 8
Y_EXP43 = 2.459890565832


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
    w10, _ = replace_resistors_w(net0, cat, 10.0)
    net_a = set_tia_gain(w10, A)
    CIRCUIT_DIR.mkdir(parents=True, exist_ok=True)
    spiceinit_hsa(CIRCUIT_DIR)
    ng = find_ngspice()
    hy = ident["hy_at_imax"]

    path0 = CIRCUIT_DIR / "tt_nominal.cir"
    write_op_net(
        path0,
        prepend_pdk(net_a, "tt", 27.0).replace(
            "* Experiment 39 SKY130 isolated frozen o2 cell",
            "* Experiment 53 W=10 tt nominal A=1e6",
        ),
        hy,
    )
    nom = eval_cell(ng, path0, z0, timeout=180.0)
    nom.update({"name": "tt_nominal", "python_corrected": False})
    print(f"  nominal y={nom.get('y')} |err|={nom.get('abs_err')}", flush=True)

    rows = []
    for i in range(N_MC):
        path = CIRCUIT_DIR / f"ttmm_{i:03d}.cir"
        write_op_net(
            path,
            prepend_pdk(net_a, "tt_mm", 27.0).replace(
                "* Experiment 39 SKY130 isolated frozen o2 cell",
                f"* Experiment 53 W=10 tt_mm draw {i} A=1e6 · model AGAUSS",
            ),
            hy,
        )
        rec = eval_cell(ng, path, z0, timeout=180.0)
        rec.update({"draw": i, "python_corrected": False})
        rows.append(rec)
        print(f"  mm {i} y={rec.get('y')} |err|={rec.get('abs_err')} pass={rec.get('analog_pass')}", flush=True)

    ok = [r for r in rows if r.get("abs_err") is not None and not r.get("failed")]
    errs = [float(r["abs_err"]) for r in ok]
    n_pass = sum(1 for r in ok if r.get("analog_pass"))
    if not ok:
        decision, label, status = "E", "tt_mm DRAWS DID NOT CONVERGE", "NUMERICAL ISSUE"
        nxt = "Experiment 54: inspect tt_mm include; matching remains UNRESOLVED."
    elif n_pass == len(ok):
        decision, label, status = (
            "B",
            f"ALL {len(ok)} MODEL tt_mm DRAWS PASS 1 mV (NOT A YIELD CLAIM)",
            "PARTIALLY VALIDATED",
        )
        nxt = (
            "Experiment 54: more draws / Rf·G grouping. Still model AGAUSS, "
            "not silicon PCM. Miller-family TIA remains closed."
        )
    elif n_pass == 0:
        decision, label, status = (
            "D",
            "W=10 + A=1e6 FAILS EVERY tt_mm DRAW",
            "CLOSED NEGATIVE PATH",
        )
        nxt = "Experiment 54: leftover + mismatch cannot share the 1 mV bar at this area."
    else:
        decision, label, status = (
            "C",
            f"{n_pass}/{len(ok)} tt_mm DRAWS PASS; MATCHING UNRESOLVED",
            "TECHNOLOGY BOUNDARY",
        )
        nxt = "Experiment 54: more draws; do not treat this as yield."

    stats = None
    if errs:
        arr = np.array(errs)
        stats = {
            "n_ok": len(ok),
            "n_pass": n_pass,
            "mean": float(arr.mean()),
            "max": float(arr.max()),
            "std": float(arr.std()),
        }
    report = {
        "experiment_id": "exp53",
        "kind": "SKY130 tt_mm model mismatch on W=10 o2 at A=1e6",
        "status": status,
        "decision": decision,
        "decision_label": label,
        "yield_claim": False,
        "silicon": False,
        "A": A,
        "nominal": nom,
        "draws": [{"draw": r.get("draw"), "y": r.get("y"), "abs_err": r.get("abs_err"), "analog_pass": r.get("analog_pass"), "failed": r.get("failed")} for r in rows],
        "stats": stats,
        "matching": "UNRESOLVED",
        "next_experiment": nxt,
        "conclusion": (
            f"Decision {decision} — {label}. "
            "tt_mm is official model AGAUSS, not a foundry lot. "
            "OPA189 remains the Level-1 TIA host. Miller family remains closed."
        ),
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / "exp53_w10_ttmm.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    lines = [
        "# Experiment 53 — W=10 o2 tt_mm mismatch at A=1e6",
        "",
        "Experiments 1–52 were not modified. Behavioral TIA. Model AGAUSS, not yield.",
        "",
        f"**Status: {status}**",
        f"**Decision {decision} — {label}**",
        "",
        f"Nominal tt |err| = {None if nom.get('abs_err') is None else nom['abs_err']*1e3:.6f} mV",
        "",
        "| draw | y (V) | |err| (mV) | pass |",
        "| ---: | ---: | ---: | --- |",
    ]
    for r in rows:
        ae = r.get("abs_err")
        lines.append(
            f"| {r.get('draw')} | {r.get('y')} | {None if ae is None else ae*1e3:.6f} | {r.get('analog_pass')} |"
        )
    if stats:
        lines += [
            "",
            f"mean |err| = {stats['mean']*1e3:.6f} mV; max = {stats['max']*1e3:.6f} mV; "
            f"pass = {stats['n_pass']}/{stats['n_ok']}",
        ]
    lines += ["", report["conclusion"], "", "## Next experiment", "", nxt, ""]
    (RESULTS_DIR / "exp53_w10_ttmm.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"Experiment 53 Decision {decision} — {label}", flush=True)


if __name__ == "__main__":
    main()
