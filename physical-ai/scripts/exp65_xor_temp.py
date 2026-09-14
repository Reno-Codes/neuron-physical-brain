"""Experiment 65: temperature gate the compiler XOR netlist.

-40 / 27 / 85 C. Discrete R are ideal (no invented TCR). Temperature
enters through the OPA189 and 1N4148 macromodels.

27 C must repeat Experiment 64. Does not edit frozen weights.
Does not modify Experiments 1-64. Not silicon.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmark_scaling import detect_spice_failure
from compile_xor import XOR_X, XOR_Y, classify, find_ngspice
from compiler.parser import load_npz, software_forward
from exp39_pdk_o2_cell import last
from exp45_documented_tia import spiceinit_behavior
from exp62_physical_relu import ERROR_LIMIT
from exp64_twodiode_xor import set_inputs
from offset_vg_search import run_ngspice_ex
from test_robustness import extract_all

DEST_NET = PROJECT_ROOT / "physical_design" / "xor_2_4_1" / "netlist.cir"
CIRCUIT_DIR = PROJECT_ROOT / "circuits" / "exp65_xor_temp"
RESULTS_DIR = PROJECT_ROOT / "results"
MODEL_PATH = PROJECT_ROOT / "models" / "xor_model.npz"
TEMPS = (-40.0, 27.0, 85.0)
Y_EXP64 = (0.001645123, 1.002511, 1.018006, 0.001645121)
REPEAT_ATOL_V = 5.0e-6


def set_temp(net: str, temp_c: float) -> str:
    lines = net.splitlines()
    out = []
    inserted = False
    for raw in lines:
        out.append(raw)
        if (not inserted) and raw.startswith(".include"):
            continue
        if (not inserted) and raw.startswith("Vdd"):
            out.insert(len(out) - 1, f".temp {temp_c:.8g}")
            inserted = True
    if not inserted:
        raise RuntimeError("could not insert .temp")
    return "\n".join(out) + "\n"


def main() -> None:
    if not DEST_NET.is_file():
        raise SystemExit("BLOCKED missing compiler netlist")
    net0 = DEST_NET.read_text(encoding="utf-8")
    CIRCUIT_DIR.mkdir(parents=True, exist_ok=True)
    spiceinit_behavior(CIRCUIT_DIR, "ps")
    ng = find_ngspice()
    model = load_npz(MODEL_PATH)
    _z1, _h, y_ref = software_forward(model, XOR_X)
    rows = []
    print("==== XOR compiler netlist temperature ====", flush=True)
    for temp in TEMPS:
        fabric = set_temp(net0, temp)
        for i, x in enumerate(XOR_X):
            net = set_inputs(fabric, x)
            path = CIRCUIT_DIR / f"T{temp:g}_{i}.cir"
            path.write_text(net, encoding="utf-8")
            result = run_ngspice_ex(ng, path, timeout=180.0, pspice=True)
            text = f"{result.stdout or ''}\n{result.stderr or ''}"
            fail = detect_spice_failure(result)
            y = last(extract_all(text, "yo1"))
            rec = {
                "temp_C": temp,
                "vector": i,
                "x": x.tolist(),
                "y_ref": float(y_ref[i, 0]),
                "y": y,
                "failed": bool(fail),
                "failure_reason": fail,
                "python_corrected": False,
            }
            if y is None:
                rec.update({"abs_err": None, "analog_pass": False, "class": None, "class_ok": False})
            else:
                rec["abs_err"] = abs(y - rec["y_ref"])
                rec["analog_pass"] = rec["abs_err"] <= ERROR_LIMIT
                rec["class"] = classify(y)
                rec["class_ok"] = rec["class"] == int(XOR_Y[i])
            rows.append(rec)
            print(
                f"  T={temp} vec={i} y={y} |err|={rec.get('abs_err')} "
                f"pass={rec.get('analog_pass')} fail={rec.get('failed')}",
                flush=True,
            )

    t27 = [r for r in rows if r.get("temp_C") == 27.0]
    dy27 = []
    for r, y0 in zip(t27, Y_EXP64):
        dy27.append(None if r.get("y") is None else float(r["y"]) - y0)
    ok = [r for r in rows if not r.get("failed") and r.get("abs_err") is not None]
    n_pass = sum(1 for r in ok if r.get("analog_pass"))
    n_cls = sum(1 for r in ok if r.get("class_ok"))
    repeat_ok = all(d is not None and abs(d) <= REPEAT_ATOL_V for d in dy27)
    if not repeat_ok:
        decision, label, status = (
            "E",
            "27 C DID NOT REPEAT EXPERIMENT 64",
            "NUMERICAL ISSUE",
        )
        nxt = "Re-run Experiment 64 before promoting the XOR compile."
    elif n_pass == 12 and n_cls == 12:
        decision, label, status = (
            "A",
            "COMPILER XOR PASSES -40/27/85 C",
            "DEMONSTRATED",
        )
        nxt = (
            "XOR compile is temperature-gated at mixed-level. Next: a real "
            "stimulus/read interface spec (DAC/ADC), not miller, not F40 MOS."
        )
    elif n_cls == 12:
        decision, label, status = (
            "B",
            "CLASS HOLDS AT ALL TEMPS; ANALOG 1 mV MISSED",
            "PARTIALLY VALIDATED",
        )
        nxt = "Bound the failing temperature. Discrete R still have no TCR card."
    else:
        decision, label, status = (
            "C",
            "COMPILER XOR FAILED THE TEMPERATURE GATE",
            "TECHNOLOGY BOUNDARY",
        )
        nxt = "Do not claim a wide-temperature PCB XOR until this is understood."

    mae = float(np.mean([r["abs_err"] for r in ok])) if ok else None
    report = {
        "experiment_id": "exp65",
        "kind": "compiler XOR temperature",
        "status": status,
        "decision": decision,
        "decision_label": label,
        "yield_claim": False,
        "silicon": False,
        "resistor_tcr_invented": False,
        "repeat_27C_delta": dy27,
        "n_analog_pass": n_pass,
        "n_class_pass": n_cls,
        "mae_V": mae,
        "rows": rows,
        "next_experiment": nxt,
        "conclusion": (
            f"Decision {decision} — {label}. MIXED-LEVEL. Ideal discrete R. Not silicon."
        ),
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / "exp65_xor_temp.json").write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8"
    )
    lines = [
        "# Experiment 65 — compiler XOR temperature",
        "",
        "Experiments 1-64 were not modified. Frozen xor_model.npz. Not silicon.",
        "",
        f"**Status: {status}**",
        f"**Decision {decision} — {label}**",
        "",
        "Discrete resistors have no TCR card (not invented). Temperature is in the OPA189 and 1N4148 macromodels.",
        f"27 C repeat vs Exp64 dy = {dy27}",
        "",
        "| T (C) | vec | y (V) | |err| (mV) | class | pass |",
        "| ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for r in rows:
        ae = r.get("abs_err")
        lines.append(
            f"| {r.get('temp_C')} | {r.get('vector')} | {r.get('y')} | "
            f"{'n/a' if ae is None else f'{ae * 1e3:.4f}'} | {r.get('class')} | "
            f"{r.get('analog_pass')} |"
        )
    lines += ["", report["conclusion"], "", "## Next experiment", "", nxt, ""]
    (RESULTS_DIR / "exp65_xor_temp.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"Experiment 65 Decision {decision} — {label}", flush=True)


if __name__ == "__main__":
    main()
