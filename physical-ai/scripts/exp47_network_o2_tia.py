"""Experiment 47: OPA189 as catalog o2 TIA inside frozen Network F.

Ideal-R Architecture A fabric. Only Eo2tia is replaced.
Hidden inverts and all other TIAs stay behavioral.
No W=10 leftover (different fabric from Exp45/46).
No MOS W/L. No Python correction. Not silicon. Not full-network physical TIA.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from benchmark_scaling import generate_inputs
from compile_xor import PROJECT_ROOT, find_ngspice
from exp32_hidden_inverter_primitive import eval_f, software_for
from exp39_pdk_o2_cell import ERROR_LIMIT
from exp45_documented_tia import spiceinit_behavior
from hardware_constrained_compiler import load_frozen_model
from inverter_requirement_extraction import compile_f

CIRCUIT_DIR = PROJECT_ROOT / "circuits" / "exp47_f"
RESULTS_DIR = PROJECT_ROOT / "results"
OPA189 = PROJECT_ROOT / "models" / "vendor" / "ti" / "opa189" / "OPAx189.LIB"
E_O2 = re.compile(
    r"^(Eo2tia)\s+(\S+)\s+0\s+0\s+(\S+)\s+[0-9.+-eE]+\s*$",
    re.IGNORECASE,
)
Z_O2_IDX = 1


def insert_o2_opa189(net: str, vsupply: float = 15.0) -> str:
    lib = OPA189.as_posix()
    n = 0
    out = []
    inserted = False
    for raw in net.splitlines():
        s = raw.strip()
        if (not inserted) and s and not s.startswith("*") and not s.startswith("."):
            out += [
                "* Experiment 47 OPA189 replaces only Eo2tia",
                f'.include "{lib}"',
                f"Vddo2 vddo2 0 DC {vsupply:.8g}",
                f"Vsso2 vsso2 0 DC {-vsupply:.8g}",
            ]
            inserted = True
        m = E_O2.match(s)
        if m:
            drv, vg = m.group(2), m.group(3)
            out.append(f"Vo2ib {vg} o2inn DC 0")
            out.append(f"Xo2tia 0 o2inn vddo2 vsso2 {drv} OPAx189")
            out.append(f"Co2load {drv} 0 1p")
            n += 1
            continue
        out.append(raw)
    if n != 1:
        raise RuntimeError(f"expected one Eo2tia, found {n}")
    return "\n".join(out) + "\n"


def slim(rec: dict) -> dict:
    keep = (
        "failed", "failure_reason", "mae", "max_abs_error", "accuracy",
        "analog_pass", "n_vectors", "spice_s", "o2_mae", "o2_max_abs",
        "o2_analog_pass",
    )
    return {k: rec.get(k) for k in keep}


def attach_o2(rec: dict, physical, y) -> dict:
    if physical is None or rec.get("failed"):
        return rec
    e = physical[:, Z_O2_IDX] - y[:, Z_O2_IDX]
    rec["o2_mae"] = float(abs(e).mean())
    rec["o2_max_abs"] = float(abs(e).max())
    rec["o2_analog_pass"] = rec["o2_max_abs"] <= ERROR_LIMIT
    rec["o2_worst_vec"] = int(abs(e).argmax())
    return rec


def run_net(ng, net, spec, x, y, name, timeout):
    rec = eval_f(ng, net, spec, x, y, CIRCUIT_DIR / f"{name}.cir", timeout=timeout, pspice=True)
    print(
        f"  {name} failed={rec.get('failed')} mae={rec.get('mae')} "
        f"max={rec.get('max_abs_error')} acc={rec.get('accuracy')} "
        f"pass={rec.get('analog_pass')} {rec.get('failure_reason')}",
        flush=True,
    )
    return rec


def main() -> None:
    w = load_frozen_model("F")
    net0, cat, spec = compile_f(w)
    if not any(E_O2.match(ln.strip()) for ln in net0.splitlines()):
        raise SystemExit("BLOCKED: Eo2tia not found")
    net = insert_o2_opa189(net0, 15.0)
    CIRCUIT_DIR.mkdir(parents=True, exist_ok=True)
    spiceinit_behavior(CIRCUIT_DIR, "ps")
    ng = find_ngspice()

    x12 = generate_inputs(spec["n_in"], 12, "exp24_F")
    y12 = software_for(w, x12)
    print("F12 behavioral control", flush=True)
    ctrl = run_net(ng, net0, spec, x12, y12, "f12_behavioral", 240.0)
    print("F12 OPA189 o2 TIA", flush=True)
    f12 = run_net(ng, net, spec, x12, y12, "f12_opa189_o2", 360.0)

    f40 = None
    if f12.get("analog_pass") and not f12.get("failed"):
        x40 = generate_inputs(spec["n_in"], 40, "exp24_F")
        y40 = software_for(w, x40)
        print("F40 OPA189 o2 TIA", flush=True)
        f40 = run_net(ng, net, spec, x40, y40, "f40_opa189_o2", 720.0)

    if f40 and f40.get("analog_pass") and not f40.get("failed"):
        decision, label, status = (
            "A",
            "OPA189 o2 TIA HOLDS ANALOG MAE IN NETWORK F",
            "PARTIALLY VALIDATED",
        )
        nxt = (
            "Experiment 48: W=10 SKY130 resistor encode on the o2 row inside "
            "Network F, or multi-TIA OPA189 copies. Do not claim silicon. "
            "Matching remains UNRESOLVED."
        )
    elif f12.get("analog_pass") and not f12.get("failed"):
        decision, label, status = (
            "C",
            "F12 INSERTION PASSED; F40 DID NOT COMPLETE A PASS",
            "PARTIALLY VALIDATED",
        )
        nxt = "Experiment 48: diagnose F40 insertion (solver vs analog)."
    elif f12.get("failed"):
        decision, label, status = (
            "D",
            "NETWORK INSERTION DID NOT CONVERGE",
            "NUMERICAL ISSUE",
        )
        nxt = "Experiment 48: solver policy for one GWL TIA in Network F."
    else:
        decision, label, status = (
            "B",
            "OPA189 o2 TIA INSERTION MISSED THE ANALOG BAR",
            "CONTRADICTED",
        )
        nxt = "Experiment 48: isolate fabric coupling on o2 versus other outputs."

    report = {
        "experiment_id": "exp47",
        "kind": "Representative Network F insertion of OPA189 o2 TIA",
        "status": status,
        "decision": decision,
        "decision_label": label,
        "physical_tia_validated": False,
        "silicon": False,
        "fabric": "ideal R Architecture A; only Eo2tia is OPA189",
        "w10": False,
        "f12_control": slim(ctrl),
        "f12": slim(f12),
        "f40": slim(f40) if f40 else None,
        "exp40_decision_unchanged": "C",
        "exp45_decision_unchanged": "A",
        "exp46_decision_unchanged": "A",
        "matching": "UNRESOLVED",
        "next_experiment": nxt,
        "conclusion": (
            f"Decision {decision} — {label}. "
            "This is mixed-level: one vendor macromodel TIA in an otherwise "
            "behavioral Network F. Not W=10. Not silicon. Not a PDK MOS TIA."
        ),
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / "exp47_network_o2_tia.json").write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8"
    )
    lines = [
        "# Experiment 47 — OPA189 catalog o2 TIA in Network F",
        "",
        "Experiments 1–46 were not modified. Frozen weights unchanged.",
        "Ideal-R fabric. Only Eo2tia replaced. Not W=10. Not silicon.",
        "",
        f"**Status: {status}**",
        f"**Decision {decision} — {label}**",
        "",
        "| Run | MAE | max |acc| analog |",
        "| --- | ---: | ---: | ---: | --- |",
        f"| F12 behavioral | {ctrl.get('mae')} | {ctrl.get('max_abs_error')} | {ctrl.get('accuracy')} | {ctrl.get('analog_pass')} |",
        f"| F12 OPA189 o2 | {f12.get('mae')} | {f12.get('max_abs_error')} | {f12.get('accuracy')} | {f12.get('analog_pass')} |",
    ]
    if f40:
        lines.append(
            f"| F40 OPA189 o2 | {f40.get('mae')} | {f40.get('max_abs_error')} | {f40.get('accuracy')} | {f40.get('analog_pass')} |"
        )
    lines += ["", report["conclusion"], "", "## Next experiment", "", nxt, ""]
    (RESULTS_DIR / "exp47_network_o2_tia.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Experiment 47 Decision {decision} — {label}", flush=True)


if __name__ == "__main__":
    main()
