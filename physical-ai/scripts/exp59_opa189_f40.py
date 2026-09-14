"""Experiment 59: frozen F40 vectors on OPA189 + W=10 8s8p.

Isolated cell. Same official R include / ps policy as Experiment 58.
Does not modify Experiments 1-58. Not silicon.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from compile_xor import PROJECT_ROOT, find_ngspice
from exp39_pdk_o2_cell import PDK_VERSION, discover_pdk
from exp40_pdk_o2_cell import compile_o2_w2_1, prove_identity
from exp41_o2_residual import replace_resistors_w
from exp43_highgain_w10 import select_vectors, set_tia_gain
from exp45_documented_tia import insert_macro, prepend_pdk_rc, run_cell, spiceinit_behavior
from exp46_tia_promotion import PRIMARY, Y_EXP45_OPA189, cand
from exp48_w10_miller_servo import Z_O2
from exp54_resistor_tiling import check_geos, tile_same_units

CIRCUIT_DIR = PROJECT_ROOT / "circuits" / "exp59_o2"
RESULTS_DIR = PROJECT_ROOT / "results"
Y_EXP58_8S8P = 2.460173765013
REPEAT_ATOL_V = 1.0e-8


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
    w10, g10 = replace_resistors_w(net0, cat, 10.0)
    check_geos(g10)
    CIRCUIT_DIR.mkdir(parents=True, exist_ok=True)
    spiceinit_behavior(CIRCUIT_DIR, "ps")
    ng = find_ngspice()
    opa = cand(PRIMARY["id"])
    net_8 = tile_same_units(set_tia_gain(w10, 1.0e6), 8, 8)
    fabric = insert_macro(prepend_pdk_rc(net_8, 27.0), opa, PRIMARY["vsupply"])

    print("==== Repeat Exp58 8s8p vec 19 ====", flush=True)
    rep = run_cell(ng, fabric, ident["hy_at_imax"], z0, CIRCUIT_DIR, "opa189_8s8p_v19", True)
    dy = None if rep.get("y") is None else float(rep["y"]) - Y_EXP58_8S8P
    print(f"  v19 y={rep.get('y')} dY={dy}", flush=True)

    print("==== Frozen F40 vectors ====", flush=True)
    rows = []
    for vec in select_vectors(ident, w):
        rec = run_cell(
            ng,
            fabric,
            vec["hy"],
            vec["z"],
            CIRCUIT_DIR,
            f"opa189_8s8p_v{vec['vector']}",
            True,
        )
        rec.update({"vector": vec["vector"], "role": vec["role"], "z": vec["z"]})
        rows.append(rec)
        print(
            f"  v{vec['vector']} {vec['role']} z={vec['z']} y={rec.get('y')} "
            f"|err|={rec.get('abs_err')} pass={rec.get('analog_pass')}",
            flush=True,
        )

    ok = [r for r in rows if not r.get("failed") and r.get("abs_err") is not None]
    n_pass = sum(1 for r in ok if r.get("analog_pass"))
    if dy is not None and abs(dy) > REPEAT_ATOL_V:
        decision, label, status = (
            "E",
            "VEC 19 DID NOT REPEAT EXPERIMENT 58",
            "NUMERICAL ISSUE",
        )
        nxt = "Re-run Experiment 58 nominal before any vector claim."
    elif ok and n_pass == len(ok):
        decision, label, status = (
            "A",
            "OPA189 + 8s8p PASSES THE FROZEN F40 VECTOR SET (ISOLATED)",
            "DEMONSTRATED",
        )
        nxt = (
            "Experiment 60: insert tiled o2 (or OPA189 o2) into Network F. "
            "Mixed-level. Not W=10 fabric on every neuron. Not silicon."
        )
    elif n_pass >= 1:
        decision, label, status = (
            "B",
            f"OPA189 + 8s8p PASSES {n_pass}/{len(ok)} F40 VECTORS",
            "PARTIALLY VALIDATED",
        )
        nxt = "Worst vector is leftover-limited. Do not claim full-vector promotion."
    else:
        decision, label, status = (
            "C",
            "OPA189 + 8s8p MISSED THE F40 VECTOR SET",
            "TECHNOLOGY BOUNDARY",
        )
        nxt = "Leftover on a non-19 vector exceeded 1 mV. Inspect z and leftover sign."

    report = {
        "experiment_id": "exp59",
        "kind": "OPA189 + W=10 8s8p frozen F40 vectors",
        "status": status,
        "decision": decision,
        "decision_label": label,
        "yield_claim": False,
        "silicon": False,
        "physical_tia_validated": False,
        "repeat": {"y": rep.get("y"), "delta_vs_exp58": dy, "abs_err": rep.get("abs_err")},
        "vectors": [
            {
                "vector": r.get("vector"),
                "role": r.get("role"),
                "z": r.get("z"),
                "y": r.get("y"),
                "abs_err": r.get("abs_err"),
                "analog_pass": r.get("analog_pass"),
                "failed": r.get("failed"),
            }
            for r in rows
        ],
        "next_experiment": nxt,
        "conclusion": (
            f"Decision {decision} — {label}. "
            "Level-1 TIA + Level-4 tiled R. Not silicon. Miller family closed."
        ),
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / "exp59_opa189_f40.json").write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8"
    )
    lines = [
        "# Experiment 59 — OPA189 + 8s8p frozen F40 vectors",
        "",
        "Experiments 1-58 were not modified. Isolated cell. Not silicon.",
        "",
        f"**Status: {status}**",
        f"**Decision {decision} — {label}**",
        "",
        f"Vec 19 repeat dY vs Exp58 = {dy}",
        "",
        "| vector | role | z (V) | y (V) | |err| (mV) | pass |",
        "| ---: | --- | ---: | ---: | ---: | --- |",
    ]
    for r in rows:
        ae = r.get("abs_err")
        lines.append(
            f"| {r.get('vector')} | {r.get('role')} | {r.get('z')} | {r.get('y')} | "
            f"{None if ae is None else ae * 1e3:.6f} | {r.get('analog_pass')} |"
        )
    lines += ["", report["conclusion"], "", "## Next experiment", "", nxt, ""]
    (RESULTS_DIR / "exp59_opa189_f40.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"Experiment 59 Decision {decision} — {label}", flush=True)


if __name__ == "__main__":
    main()
