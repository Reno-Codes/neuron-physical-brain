"""Experiment 58: OPA189 TIA on leftover-limited tiled xhigh_po.

Hosts the Experiment 54/55 W=10 8s8p fabric on the Experiment 45/46
OPA189 macromodel. Official R .include (ps). Optional mc_mm_switch=1.

Does not modify Experiments 1-57. No resistor fitting. Not silicon.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from compile_xor import PROJECT_ROOT, find_ngspice
from exp39_pdk_o2_cell import PDK_VERSION, discover_pdk, write_op_net
from exp40_pdk_o2_cell import compile_o2_w2_1, prove_identity
from exp41_o2_residual import replace_resistors_w
from exp43_highgain_w10 import set_tia_gain
from exp45_documented_tia import (
    TAG,
    insert_macro,
    parse_op,
    prepend_pdk_rc,
    run_cell,
    run_cir,
    spiceinit_behavior,
)
from exp46_tia_promotion import PRIMARY, Y_EXP45_OPA189, cand
from exp48_w10_miller_servo import Z_O2
from exp54_resistor_tiling import check_geos, insert_seed, tile_same_units

CIRCUIT_DIR = PROJECT_ROOT / "circuits" / "exp58_o2"
RESULTS_DIR = PROJECT_ROOT / "results"
REPEAT_ATOL_V = 1.0e-8
N_MC = 8


def rc_mm(net: str, mm: bool) -> str:
    text = prepend_pdk_rc(net, 27.0)
    if mm:
        text = text.replace(".param mc_mm_switch=0", ".param mc_mm_switch=1")
        text = text.replace(".param MC_MM_SWITCH=0", ".param MC_MM_SWITCH=1")
    return text


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
    hy = ident["hy_at_imax"]
    w10, g10 = replace_resistors_w(net0, cat, 10.0)
    check_geos(g10)
    CIRCUIT_DIR.mkdir(parents=True, exist_ok=True)
    spiceinit_behavior(CIRCUIT_DIR, "ps")
    ng = find_ngspice()
    opa = cand(PRIMARY["id"])

    net_w10 = set_tia_gain(w10, 1.0e6)
    net_8 = tile_same_units(net_w10, 8, 8)
    fab_w10 = insert_macro(rc_mm(net_w10, False), opa, PRIMARY["vsupply"])
    fab_8 = insert_macro(rc_mm(net_8, False), opa, PRIMARY["vsupply"])

    print("==== OPA189 W=10 repeat ====", flush=True)
    dc = run_cell(ng, fab_w10, hy, z0, CIRCUIT_DIR, "opa189_w10_dc", True)
    if dc.get("y") is not None:
        dc["delta_vs_exp45"] = float(dc["y"]) - Y_EXP45_OPA189
        dc["repeat_ok"] = abs(dc["delta_vs_exp45"]) <= REPEAT_ATOL_V
    print(f"  W10 y={dc.get('y')} dY={dc.get('delta_vs_exp45')} ok={dc.get('repeat_ok')}", flush=True)

    print("==== OPA189 W=10 8s8p nominal ====", flush=True)
    nom = run_cell(ng, fab_8, hy, z0, CIRCUIT_DIR, "opa189_w10_8s8p_dc", True)
    print(f"  8s8p y={nom.get('y')} |err|={nom.get('abs_err')} fail={nom.get('failed')}", flush=True)

    draws = []
    if nom.get("failed") or nom.get("y") is None:
        print("8s8p OPA189 failed; skip tt_mm", flush=True)
    else:
        print(f"==== OPA189 8s8p mc_mm n={N_MC} ====", flush=True)
        fab_mm = insert_macro(rc_mm(net_8, True), opa, PRIMARY["vsupply"])
        tagged = fab_mm.replace(
            "* Experiment 39 SKY130 isolated frozen o2 cell",
            "* Experiment 58 OPA189 8s8p tt_mm · not silicon",
        )
        for i in range(N_MC):
            path = CIRCUIT_DIR / f"opa189_8s8p_mm_{i:03d}.cir"
            write_op_net(path, tagged, hy, extra_prints=[f"i(V{TAG}ib)", "i(Vddtia)"])
            insert_seed(path, 58000 + i)
            _r, text, fail = run_cir(ng, path, True, timeout=600.0)
            rec = parse_op(text, z0)
            rec.update({"draw": i, "failed": bool(fail) or rec.get("failed"), "path": str(path)})
            draws.append(rec)
            print(
                f"  MM {i} y={rec.get('y')} |err|={rec.get('abs_err')} "
                f"pass={rec.get('analog_pass')} fail={rec.get('failed')}",
                flush=True,
            )

    ok = [r for r in draws if r.get("abs_err") is not None and not r.get("failed")]
    n_pass = sum(1 for r in ok if r.get("analog_pass"))
    if dc.get("repeat_ok") and nom.get("analog_pass") and ok and n_pass == len(ok):
        decision, label, status = (
            "B",
            f"OPA189 + 8s8p PASSES NOMINAL AND {n_pass}/{len(ok)} mm DRAWS (NOT YIELD)",
            "PARTIALLY VALIDATED",
        )
        nxt = "Experiment 59: frozen F40 vectors on OPA189 + 8s8p. Still mixed-level."
    elif dc.get("repeat_ok") and nom.get("analog_pass"):
        decision, label, status = (
            "B",
            "OPA189 + 8s8p NOMINAL PASSES; mm SAMPLE MIXED OR SMALL (NOT YIELD)",
            "PARTIALLY VALIDATED",
        )
        nxt = "Experiment 59: more mm draws or F40 vectors. Leftover remains the floor."
    elif nom.get("analog_pass"):
        decision, label, status = (
            "B",
            "OPA189 + 8s8p NOMINAL PASSES; W=10 REPEAT OFF",
            "PARTIALLY VALIDATED",
        )
        nxt = "Experiment 59: inspect W=10 OPA189 repeat before promotion."
    elif nom.get("failed"):
        decision, label, status = (
            "E",
            "OPA189 + 8s8p DID NOT CONVERGE",
            "NUMERICAL ISSUE",
        )
        nxt = "Experiment 59: try OPA189 + 4s4p (1280 devices) under the same include."
    else:
        decision, label, status = (
            "C",
            "OPA189 + 8s8p NOMINAL MISSED THE 1 mV BAR",
            "TECHNOLOGY BOUNDARY",
        )
        nxt = "Leftover plus macromodel residual exceeded 1 mV. Do not claim a TIA pass."

    report = {
        "experiment_id": "exp58",
        "kind": "OPA189 Level-1 TIA on W=10 8s8p tiled xhigh_po",
        "status": status,
        "decision": decision,
        "decision_label": label,
        "yield_claim": False,
        "silicon": False,
        "realism_level": "1 TIA + 4 resistors",
        "physical_tia_validated": False,
        "miller_family": "CLOSED",
        "w10_repeat": {
            "y": dc.get("y"),
            "abs_err": dc.get("abs_err"),
            "delta_vs_exp45": dc.get("delta_vs_exp45"),
            "repeat_ok": dc.get("repeat_ok"),
            "failed": dc.get("failed"),
        },
        "nominal_8s8p": {
            "y": nom.get("y"),
            "abs_err": nom.get("abs_err"),
            "analog_pass": nom.get("analog_pass"),
            "failed": nom.get("failed"),
        },
        "mm": [
            {
                "draw": r.get("draw"),
                "y": r.get("y"),
                "abs_err": r.get("abs_err"),
                "analog_pass": r.get("analog_pass"),
                "failed": r.get("failed"),
            }
            for r in draws
        ],
        "next_experiment": nxt,
        "conclusion": (
            f"Decision {decision} — {label}. "
            "OPA189 is a Level-1 macromodel host, not silicon. "
            "Miller family remains closed."
        ),
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / "exp58_opa189_tiled.json").write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8"
    )
    lines = [
        "# Experiment 58 — OPA189 TIA on W=10 8s8p",
        "",
        "Experiments 1-57 were not modified. Level-1 macromodel. Not silicon.",
        "",
        f"**Status: {status}**",
        f"**Decision {decision} — {label}**",
        "",
        f"W=10 OPA189 y={dc.get('y')} dY vs Exp45={dc.get('delta_vs_exp45')}",
        f"8s8p OPA189 y={nom.get('y')} |err|={nom.get('abs_err')}",
        "",
        "| draw | y | |err| (mV) | pass |",
        "| ---: | ---: | ---: | --- |",
    ]
    for r in draws:
        ae = r.get("abs_err")
        lines.append(
            f"| {r.get('draw')} | {r.get('y')} | "
            f"{None if ae is None else ae * 1e3:.6f} | {r.get('analog_pass')} |"
        )
    lines += ["", report["conclusion"], "", "## Next experiment", "", nxt, ""]
    (RESULTS_DIR / "exp58_opa189_tiled.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"Experiment 58 Decision {decision} — {label}", flush=True)


if __name__ == "__main__":
    main()
