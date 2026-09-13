"""Experiment 52: two copies of existing sky_miller as a composite TIA.

No new W/L. Same Exp39 sizes. W=10 o2. Not silicon.
Tests whether A^2 can host the cell, or whether ~5.7 mV Vos still dominates.
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
    TAG,
    discover_pdk,
    eval_cell,
    miller_subckt,
    prepend_pdk,
    write_op_net,
)
from exp40_pdk_o2_cell import compile_o2_w2_1, prove_identity
from exp41_o2_residual import MILLER_SIZES, replace_resistors_w
from exp45_documented_tia import spiceinit_hsa
from exp48_w10_miller_servo import VSUPPLY, Z_O2

CIRCUIT_DIR = PROJECT_ROOT / "circuits" / "exp52_o2"
RESULTS_DIR = PROJECT_ROOT / "results"
VOS_LOADED = 5.7421875e-3
A_INC = 2507.2875480294997


def insert_cascade(netlist: str, vsupply: float = VSUPPLY) -> str:
    e_re = re.compile(
        rf"^(E)({re.escape(TAG)}tia)\s+(\S+)\s+0\s+0\s+(\S+)\s+(\S+)\s*$",
        re.IGNORECASE,
    )
    out, n, drv, vg = [], 0, f"{TAG}lin", f"{TAG}p"
    inserted = False
    for raw in netlist.splitlines():
        s = raw.strip()
        if not inserted and s and not s.startswith("*") and not s.startswith("."):
            out.extend(miller_subckt(MILLER_SIZES))
            out += [
                f"Vddtia vddtia 0 DC {vsupply:.8g}",
                f"Vsstia vsstia 0 DC {-vsupply:.8g}",
            ]
            inserted = True
        m = e_re.match(s)
        if m:
            drv, vg = m.group(3), m.group(4)
            n += 1
            continue
        out.append(raw)
    if n != 1:
        raise RuntimeError(f"expected one TIA, found {n}")
    inst = [
        f"* Experiment 52 two identical sky_miller cascade. No new W/L.",
        f"V{TAG}ib {vg} {TAG}inn DC 0",
        f"X{TAG}pre 0 {TAG}inn {TAG}mid vddtia vsstia sky_miller",
        f"X{TAG}out {TAG}mid 0 {drv} vddtia vsstia sky_miller",
    ]
    final, placed = [], False
    for line in out:
        if (not placed) and line.strip().lower().startswith(".control"):
            final.extend(inst)
            final.append("")
            placed = True
        final.append(line)
    if not placed:
        final.extend(inst)
    return "\n".join(final) + "\n"


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
    net = insert_cascade(prepend_pdk(w10, "tt", 27.0))
    CIRCUIT_DIR.mkdir(parents=True, exist_ok=True)
    spiceinit_hsa(CIRCUIT_DIR)
    ng = find_ngspice()
    path = CIRCUIT_DIR / "w10_cascade2.cir"
    tagged = net.replace(
        "* Experiment 39 SKY130 isolated frozen o2 cell",
        "* Experiment 52 two-copy miller TIA · no new W/L",
    )
    write_op_net(path, tagged, ident["hy_at_imax"], extra_prints=[f"v({TAG}mid)"])
    rec = eval_cell(ng, path, z0, extra_names=[f"v({TAG}mid)"], timeout=300.0)
    rec.update({"name": "w10_cascade2", "python_corrected": False, "resized": False})
    print(
        f"  cascade y={rec.get('y')} |err|={rec.get('abs_err')} pass={rec.get('analog_pass')} "
        f"vsum={rec.get('vsum')} mid={rec.get(f'v({TAG}mid)')} a_eff={rec.get('a_eff')}",
        flush=True,
    )
    if rec.get("analog_pass"):
        decision, label, status = (
            "A",
            "TWO-COPY MILLER TIA MEETS 1 mV ON W=10 o2",
            "PARTIALLY VALIDATED",
        )
        nxt = "Experiment 53: TRAN/temp/vectors on the two-copy TIA. Still not silicon."
    elif rec.get("y") is not None:
        decision, label, status = (
            "D",
            "TWO-COPY MILLER TIA MISSES; VOS OF THIS STAGE STILL DOMINATES",
            "CLOSED NEGATIVE PATH",
        )
        nxt = (
            "Experiment 53: close the unre-sized miller-family TIA. Keep OPA189 as "
            "Level-1 host. Next bottleneck is resistor matching (Track C) or a "
            "documented offset-cancellation primitive that does not invent W/L."
        )
    else:
        decision, label, status = (
            "E",
            "TWO-COPY MILLER TIA DID NOT CONVERGE",
            "NUMERICAL ISSUE",
        )
        nxt = "Experiment 53: inspect the cascade OP; do not invent W/L."

    report = {
        "experiment_id": "exp52",
        "kind": "Two identical sky_miller composite TIA on W=10 o2",
        "status": status,
        "decision": decision,
        "decision_label": label,
        "physical_tia_validated": bool(rec.get("analog_pass")),
        "resized": False,
        "exp51_A_inc": A_INC,
        "exp51_Vos_loaded": VOS_LOADED,
        "cell": rec,
        "matching": "UNRESOLVED",
        "next_experiment": nxt,
        "conclusion": (
            f"Decision {decision} — {label}. "
            f"Exp51 Vos~{VOS_LOADED*1e3:.2f} mV, A_inc~{A_INC:.4g}. "
            "No new W/L. Not silicon."
        ),
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / "exp52_cascade_miller.json").write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8"
    )
    ae = rec.get("abs_err")
    (RESULTS_DIR / "exp52_cascade_miller.md").write_text(
        "\n".join(
            [
                "# Experiment 52 — two-copy existing miller TIA",
                "",
                "Experiments 1–51 were not modified. No new W/L. Not silicon.",
                "",
                f"**Status: {status}**",
                f"**Decision {decision} — {label}**",
                "",
                f"- y = {rec.get('y')}",
                f"- |err| = {None if ae is None else ae*1e3:.6f} mV",
                f"- Vsum = {rec.get('vsum')}",
                f"- Vmid = {rec.get(f'v({TAG}mid)')}",
                f"- a_eff = {rec.get('a_eff')}",
                f"- analog_pass = {rec.get('analog_pass')}",
                "",
                report["conclusion"],
                "",
                "## Next experiment",
                "",
                nxt,
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(f"Experiment 52 Decision {decision} — {label}", flush=True)


if __name__ == "__main__":
    main()
