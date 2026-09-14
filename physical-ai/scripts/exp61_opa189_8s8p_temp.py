"""Experiment 61: OPA189 + W=10 8s8p temperature gate.

Isolated catalog o2. Official R include. -40 / 27 / 85 C.
Does not modify Experiments 1-60. Not silicon. Not yield.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from compile_xor import PROJECT_ROOT, find_ngspice
from exp39_pdk_o2_cell import PDK_VERSION, discover_pdk
from exp40_pdk_o2_cell import compile_o2_w2_1, prove_identity
from exp41_o2_residual import replace_resistors_w
from exp43_highgain_w10 import set_tia_gain
from exp45_documented_tia import insert_macro, prepend_pdk_rc, run_cell, spiceinit_behavior
from exp46_tia_promotion import PRIMARY, cand
from exp48_w10_miller_servo import Z_O2
from exp54_resistor_tiling import check_geos, tile_same_units

CIRCUIT_DIR = PROJECT_ROOT / "circuits" / "exp61_o2"
RESULTS_DIR = PROJECT_ROOT / "results"
Y_EXP58 = 2.460173765013
REPEAT_ATOL_V = 1.0e-8
TEMPS = (-40.0, 27.0, 85.0)
ERROR_LIMIT = 1.0e-3


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
    net8 = tile_same_units(set_tia_gain(w10, 1.0e6), 8, 8)
    CIRCUIT_DIR.mkdir(parents=True, exist_ok=True)
    spiceinit_behavior(CIRCUIT_DIR, "ps")
    ng = find_ngspice()
    opa = cand(PRIMARY["id"])

    rows = []
    print("==== OPA189 W=10 8s8p temperature ====", flush=True)
    for t in TEMPS:
        fabric = insert_macro(prepend_pdk_rc(net8, t), opa, PRIMARY["vsupply"])
        rec = run_cell(ng, fabric, hy, z0, CIRCUIT_DIR, f"opa189_8s8p_T{t:g}", True)
        rec.update({"temp_C": t})
        rows.append(rec)
        print(
            f"  T={t} y={rec.get('y')} |err|={rec.get('abs_err')} "
            f"pass={rec.get('analog_pass')} fail={rec.get('failed')}",
            flush=True,
        )

    t27 = next((r for r in rows if r.get("temp_C") == 27.0), {})
    dy = None if t27.get("y") is None else float(t27["y"]) - Y_EXP58
    ok = [r for r in rows if not r.get("failed") and r.get("abs_err") is not None]
    n_pass = sum(1 for r in ok if r.get("analog_pass"))
    if dy is None or abs(dy) > REPEAT_ATOL_V:
        decision, label, status = (
            "E",
            "27 C DID NOT REPEAT EXPERIMENT 58",
            "NUMERICAL ISSUE",
        )
        nxt = "Re-run Experiment 58 before any compiler promotion."
    elif n_pass == len(ok) == 3:
        decision, label, status = (
            "A",
            "OPA189 + 8s8p PASSES -40/27/85 C ON ISOLATED o2",
            "DEMONSTRATED",
        )
        nxt = (
            "Experiment 62: documented precision-rectifier ReLU (OPA189 + diode) "
            "as a compiler primitive. Do not reopen miller."
        )
    elif n_pass >= 1:
        decision, label, status = (
            "B",
            f"TEMPERATURE MIXED {n_pass}/{len(ok)}; LEFTOVER/TCR LIMITED",
            "PARTIALLY VALIDATED",
        )
        nxt = "Experiment 62: still start physical ReLU primitive; leftover/TCR is documented."
    else:
        decision, label, status = (
            "C",
            "OPA189 + 8s8p FAILED THE TEMPERATURE GATE",
            "TECHNOLOGY BOUNDARY",
        )
        nxt = "Do not promote this fabric as a compiler default. Discrete-R PCB path remains open."

    report = {
        "experiment_id": "exp61",
        "kind": "OPA189 + W=10 8s8p isolated temperature",
        "status": status,
        "decision": decision,
        "decision_label": label,
        "yield_claim": False,
        "silicon": False,
        "physical_tia_validated": False,
        "repeat_27C_delta": dy,
        "rows": [
            {
                "temp_C": r.get("temp_C"),
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
    (RESULTS_DIR / "exp61_opa189_8s8p_temp.json").write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8"
    )
    lines = [
        "# Experiment 61 — OPA189 + 8s8p temperature",
        "",
        "Experiments 1-60 were not modified. Isolated o2. Not silicon.",
        "",
        f"**Status: {status}**",
        f"**Decision {decision} — {label}**",
        "",
        f"27 C repeat dY vs Exp58 = {dy}",
        "",
        "| T (C) | y (V) | |err| (mV) | pass |",
        "| ---: | ---: | ---: | --- |",
    ]
    for r in rows:
        ae = r.get("abs_err")
        lines.append(
            f"| {r.get('temp_C')} | {r.get('y')} | "
            f"{None if ae is None else ae * 1e3:.6f} | {r.get('analog_pass')} |"
        )
    lines += ["", report["conclusion"], "", "## Next experiment", "", nxt, ""]
    (RESULTS_DIR / "exp61_opa189_8s8p_temp.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"Experiment 61 Decision {decision} — {label}", flush=True)


if __name__ == "__main__":
    main()
