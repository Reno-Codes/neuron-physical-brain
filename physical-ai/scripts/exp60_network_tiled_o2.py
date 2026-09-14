"""Experiment 60: OPA189 + tiled Ro2* row inside frozen Network F.

Only catalog o2 weight/bias/Rf resistors become W=10 8s8p xhigh_po.
All other neurons stay ideal-R / behavioral. Eo2tia becomes OPA189.

Does not modify Experiments 1-59. No resistor fitting. Not silicon.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from compile_xor import PROJECT_ROOT, find_ngspice
from exp32_hidden_inverter_primitive import eval_f, software_for
from exp39_pdk_o2_cell import RES_MODEL, xhigh_r_pred
from exp41_o2_residual import geometry_for_r_w
from exp45_documented_tia import prepend_pdk_rc, spiceinit_behavior
from exp47_network_o2_tia import insert_o2_opa189, slim
from exp54_resistor_tiling import check_geos, tile_same_units
from hardware_constrained_compiler import load_frozen_model
from inverter_requirement_extraction import compile_f
from benchmark_scaling import generate_inputs

CIRCUIT_DIR = PROJECT_ROOT / "circuits" / "exp60_f"
RESULTS_DIR = PROJECT_ROOT / "results"
R_RE = re.compile(r"^(R)(\S+)\s+(\S+)\s+(\S+)\s+([0-9.+-eE]+)\s*$", re.IGNORECASE)


def replace_named_w(netlist: str, catalog: list[dict], names: set[str], w: float):
    by_name = {str(it["name"]): float(it["R"]) for it in catalog if "R" in it}
    out, geos = [], []
    for raw in netlist.splitlines():
        m = R_RE.match(raw.strip())
        if not m:
            out.append(raw)
            continue
        name = m.group(1) + m.group(2)
        if name not in names:
            out.append(raw)
            continue
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
            }
        )
        out.append(f"* PDK {RES_MODEL} {name} W={w_um:g} L={l_um:.8g}")
        out.append(f"X{name} {n1} {n2} 0 {RES_MODEL} w={w_um:.8g} l={l_um:.8g}")
    return "\n".join(out) + "\n", geos


def main() -> None:
    w = load_frozen_model("F")
    net0, cat, spec = compile_f(w)
    names = {str(it["name"]) for it in cat if str(it.get("name", "")).lower().startswith("ro2")}
    if len(names) < 30:
        raise SystemExit(f"BLOCKED o2 row too small n={len(names)}")
    pdk_row, geos = replace_named_w(net0, cat, names, 10.0)
    check_geos(geos)
    tiled = tile_same_units(pdk_row, 8, 8)
    net = insert_o2_opa189(prepend_pdk_rc(tiled, 27.0), 15.0)
    CIRCUIT_DIR.mkdir(parents=True, exist_ok=True)
    spiceinit_behavior(CIRCUIT_DIR, "ps")
    ng = find_ngspice()

    x12 = generate_inputs(spec["n_in"], 12, "exp24_F")
    y12 = software_for(w, x12)
    def run_net(netlist: str, xx, yy, name: str, timeout: float) -> dict:
        rec = eval_f(
            ng, netlist, spec, xx, yy, CIRCUIT_DIR / f"{name}.cir",
            timeout=timeout, pspice=True,
        )
        print(
            f"  {name} failed={rec.get('failed')} mae={rec.get('mae')} "
            f"max={rec.get('max_abs_error')} acc={rec.get('accuracy')} "
            f"pass={rec.get('analog_pass')} {rec.get('failure_reason')}",
            flush=True,
        )
        return rec

    print(f"o2 PDK resistors {len(names)} -> tiled {len(names)*64}", flush=True)
    print("F12 behavioral control (ideal R, no OPA)", flush=True)
    ctrl = run_net(net0, x12, y12, "f12_behavioral", 240.0)
    print("F12 OPA189 + tiled Ro2", flush=True)
    f12 = run_net(net, x12, y12, "f12_opa189_tiled_o2", 480.0)

    f40 = None
    if f12.get("analog_pass") and not f12.get("failed"):
        x40 = generate_inputs(spec["n_in"], 40, "exp24_F")
        y40 = software_for(w, x40)
        print("F40 OPA189 + tiled Ro2", flush=True)
        f40 = run_net(net, x40, y40, "f40_opa189_tiled_o2", 900.0)

    if f40 and f40.get("analog_pass") and not f40.get("failed"):
        decision, label, status = (
            "A",
            "OPA189 + TILED o2 ROW HOLDS NETWORK F ANALOG MAE",
            "DEMONSTRATED",
        )
        nxt = (
            "Experiment 61: temperature or extra mm draws on this mixed Network F, "
            "or leave matching as leftover-limited. Not silicon."
        )
    elif f12.get("analog_pass") and not f12.get("failed"):
        decision, label, status = (
            "B",
            "F12 MIXED INSERTION PASSED; F40 DID NOT",
            "PARTIALLY VALIDATED",
        )
        nxt = "Experiment 61: diagnose F40 (solver vs leftover on another output)."
    elif f12.get("failed"):
        decision, label, status = (
            "E",
            "NETWORK INSERTION DID NOT CONVERGE",
            "NUMERICAL ISSUE",
        )
        nxt = "Experiment 61: 4s4p o2 row or official-include solver policy."
    else:
        decision, label, status = (
            "C",
            "TILED o2 ROW MISSED THE NETWORK ANALOG BAR",
            "TECHNOLOGY BOUNDARY",
        )
        nxt = "Leftover on o2 or coupling to other outputs. Isolated pass does not imply network pass."

    report = {
        "experiment_id": "exp60",
        "kind": "Network F insertion of OPA189 + W=10 8s8p Ro2 row",
        "status": status,
        "decision": decision,
        "decision_label": label,
        "yield_claim": False,
        "silicon": False,
        "physical_tia_validated": False,
        "n_o2_resistors": len(names),
        "n_tiled_instances": len(names) * 64,
        "f12_control": slim(ctrl),
        "f12": slim(f12),
        "f40": slim(f40) if f40 else None,
        "next_experiment": nxt,
        "conclusion": (
            f"Decision {decision} — {label}. "
            "Mixed-level: tiled PDK o2 row + one OPA189 TIA in otherwise "
            "behavioral Network F. Not silicon. Miller family closed."
        ),
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / "exp60_network_tiled_o2.json").write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8"
    )
    lines = [
        "# Experiment 60 — OPA189 + tiled o2 row in Network F",
        "",
        "Experiments 1-59 were not modified. Mixed-level. Not silicon.",
        "",
        f"**Status: {status}**",
        f"**Decision {decision} — {label}**",
        "",
        f"o2 logical resistors = {len(names)}; tiled instances = {len(names)*64}",
        "",
        "| Run | MAE | max | acc | analog |",
        "| --- | ---: | ---: | ---: | --- |",
        f"| F12 behavioral | {ctrl.get('mae')} | {ctrl.get('max_abs_error')} | {ctrl.get('accuracy')} | {ctrl.get('analog_pass')} |",
        f"| F12 OPA189+tiled o2 | {f12.get('mae')} | {f12.get('max_abs_error')} | {f12.get('accuracy')} | {f12.get('analog_pass')} |",
    ]
    if f40:
        lines.append(
            f"| F40 OPA189+tiled o2 | {f40.get('mae')} | {f40.get('max_abs_error')} | {f40.get('accuracy')} | {f40.get('analog_pass')} |"
        )
    lines += ["", report["conclusion"], "", "## Next experiment", "", nxt, ""]
    (RESULTS_DIR / "exp60_network_tiled_o2.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"Experiment 60 Decision {decision} — {label}", flush=True)


if __name__ == "__main__":
    main()
