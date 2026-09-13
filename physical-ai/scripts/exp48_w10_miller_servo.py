"""Experiment 48: existing SKY130 Miller ± servo on W=10 o2.

H4 test. Same Exp39/41 sizes, no W/L search. Official sky130.lib tt.
Does not modify Experiments 1-47. Not silicon. Not a macromodel claim.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from compile_xor import PROJECT_ROOT, find_ngspice
from exp39_pdk_o2_cell import (
    ERROR_LIMIT,
    PDK_VERSION,
    discover_pdk,
    eval_cell,
    insert_miller,
    prepend_pdk,
    write_op_net,
)
from exp40_pdk_o2_cell import compile_o2_w2_1, prove_identity
from exp41_o2_residual import MILLER_SIZES, replace_resistors_w
from exp45_documented_tia import spiceinit_hsa

CIRCUIT_DIR = PROJECT_ROOT / "circuits" / "exp48_o2"
RESULTS_DIR = PROJECT_ROOT / "results"
Z_O2 = 2.459489570880132
Y_EXP41_MILLER = 1.832237285033
VSUPPLY = 2.5


def tag48(net: str) -> str:
    return net.replace(
        "* Experiment 39 SKY130 isolated frozen o2 cell",
        "* Experiment 48 W=10 SKY130 Miller ± servo · no W/L resize",
    )


def run_one(ng, net, hy, z0, name):
    path = CIRCUIT_DIR / f"{name}.cir"
    write_op_net(path, tag48(net), hy)
    rec = eval_cell(ng, path, z0, timeout=240.0)
    rec["name"] = name
    rec["python_corrected"] = False
    rec["vsupply"] = VSUPPLY
    rec["headroom_V"] = None if rec.get("y") is None else VSUPPLY - rec["y"]
    print(
        f"  {name} y={rec.get('y')} |err|={rec.get('abs_err')} pass={rec.get('analog_pass')} "
        f"vsum={rec.get('vsum')} a_eff={rec.get('a_eff')} headroom={rec.get('headroom_V')} "
        f"fail={rec.get('failure_reason')}",
        flush=True,
    )
    return rec


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
    pdk_w10 = prepend_pdk(w10, "tt", 27.0)
    CIRCUIT_DIR.mkdir(parents=True, exist_ok=True)
    spiceinit_hsa(CIRCUIT_DIR)
    ng = find_ngspice()

    print("W=10 Miller no servo (Exp41 repeat on same sizes)", flush=True)
    raw = run_one(
        ng,
        insert_miller(pdk_w10, MILLER_SIZES, servo=False, vsupply=VSUPPLY),
        ident["hy_at_imax"],
        z0,
        "w10_miller_noservo",
    )
    print("W=10 Miller + servo (Exp39 sizes, C=1 nF labeled hybrid)", flush=True)
    srv = run_one(
        ng,
        insert_miller(pdk_w10, MILLER_SIZES, servo=True, vsupply=VSUPPLY),
        ident["hy_at_imax"],
        z0,
        "w10_miller_servo",
    )

    raw_pass = bool(raw.get("analog_pass"))
    srv_pass = bool(srv.get("analog_pass"))
    y_raw = raw.get("y")
    y_srv = srv.get("y")
    swing_short = None if y_raw is None else (z0 - y_raw)
    headroom_srv = srv.get("headroom_V")
    rail_limited = (
        y_srv is not None
        and headroom_srv is not None
        and headroom_srv < 0.02
        and (z0 - y_srv) > ERROR_LIMIT
    )
    if srv_pass:
        decision, label, status = (
            "A",
            "EXISTING MILLER+SERVO MEETS 1 mV ON W=10 o2",
            "PARTIALLY VALIDATED",
        )
        nxt = (
            "Experiment 49: promote miller+servo (temp / 200 us / extra vectors). "
            "Do not invent W/L."
        )
    elif rail_limited:
        decision, label, status = (
            "T",
            "EXISTING MILLER SATURATES BEFORE 2.46 V ON ±2.5 V",
            "TECHNOLOGY BOUNDARY",
        )
        nxt = (
            "Experiment 49: documented rail-to-rail / higher-voltage PDK stage, "
            "or a frozen-map-preserving swing partition. Do not silently "
            "rescale weights. OPA189 remains the Level-1 host."
        )
    elif srv.get("y") is not None:
        decision, label, status = (
            "B",
            "MILLER+SERVO CONVERGED BUT MISSED THE 1 mV BAR",
            "CONTRADICTED",
        )
        nxt = "Experiment 49: quantify remaining servo error vs swing vs offset."
    else:
        decision, label, status = (
            "D",
            "MILLER+SERVO DID NOT YIELD A USABLE OP",
            "NUMERICAL ISSUE",
        )
        nxt = "Experiment 49: solver/operating-point on miller+servo W=10."

    report = {
        "experiment_id": "exp48",
        "kind": "H4 SKY130 Miller ± servo on W=10 o2",
        "status": status,
        "decision": decision,
        "decision_label": label,
        "physical_tia_validated": bool(srv_pass),
        "silicon": False,
        "sizes": MILLER_SIZES,
        "resized": False,
        "vsupply": VSUPPLY,
        "noservo": raw,
        "servo": srv,
        "swing_short_V": swing_short,
        "exp41_miller_y": Y_EXP41_MILLER,
        "matching": "UNRESOLVED",
        "next_experiment": nxt,
        "conclusion": (
            f"Decision {decision} — {label}. "
            "Sizes are the Experiment 39/41 set, not re-optimized. "
            f"No-servo y={y_raw}; servo y={srv.get('y')}. "
            "Not silicon."
        ),
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / "exp48_w10_miller_servo.json").write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8"
    )
    lines = [
        "# Experiment 48 — W=10 SKY130 Miller ± servo",
        "",
        "Experiments 1–47 were not modified. Frozen weights unchanged.",
        "Exp39/41 Miller sizes, no resize. Official sky130.lib tt.",
        "",
        f"**Status: {status}**",
        f"**Decision {decision} — {label}**",
        "",
        "| Config | y (V) | |err| (mV) | Vsum (V) | a_eff | headroom to +2.5 V | pass |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for r, lab in ((raw, "Miller no servo"), (srv, "Miller + servo")):
        ae = r.get("abs_err")
        lines.append(
            f"| {lab} | {r.get('y')} | {None if ae is None else ae*1e3:.3f} | "
            f"{r.get('vsum')} | {r.get('a_eff')} | {r.get('headroom_V')} | {r.get('analog_pass')} |"
        )
    lines += ["", report["conclusion"], "", "## Next experiment", "", nxt, ""]
    (RESULTS_DIR / "exp48_w10_miller_servo.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Experiment 48 Decision {decision} — {label}", flush=True)


if __name__ == "__main__":
    main()
