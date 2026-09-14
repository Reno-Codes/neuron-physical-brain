"""Experiment 66: bound the Experiment 65 85 C analog miss.

55 C and 70 C on the same compiler XOR netlist. Frozen weights unchanged.
Does not invent resistor TCR. Not silicon.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from compile_xor import XOR_X, find_ngspice
from exp65_xor_temp import set_inputs, set_temp
from benchmark_scaling import detect_spice_failure
from compiler.parser import load_npz, software_forward
from exp39_pdk_o2_cell import last
from exp45_documented_tia import spiceinit_behavior
from exp62_physical_relu import ERROR_LIMIT
from offset_vg_search import run_ngspice_ex
from test_robustness import extract_all
from compile_xor import XOR_Y, classify

DEST_NET = PROJECT_ROOT / "physical_design" / "xor_2_4_1" / "netlist.cir"
CIRCUIT_DIR = PROJECT_ROOT / "circuits" / "exp66_xor_temp"
RESULTS_DIR = PROJECT_ROOT / "results"
TEMPS = (55.0, 70.0)


def main() -> None:
    net0 = DEST_NET.read_text(encoding="utf-8")
    CIRCUIT_DIR.mkdir(parents=True, exist_ok=True)
    spiceinit_behavior(CIRCUIT_DIR, "ps")
    ng = find_ngspice()
    model = load_npz(PROJECT_ROOT / "models" / "xor_model.npz")
    _z, _h, y_ref = software_forward(model, XOR_X)
    rows = []
    print("==== XOR temperature bound 55/70 C ====", flush=True)
    for temp in TEMPS:
        fabric = set_temp(net0, temp)
        for i, x in enumerate(XOR_X):
            path = CIRCUIT_DIR / f"T{temp:g}_{i}.cir"
            path.write_text(set_inputs(fabric, x), encoding="utf-8")
            result = run_ngspice_ex(ng, path, timeout=180.0, pspice=True)
            text = f"{result.stdout or ''}\n{result.stderr or ''}"
            fail = detect_spice_failure(result)
            y = last(extract_all(text, "yo1"))
            rec = {
                "temp_C": temp,
                "vector": i,
                "y_ref": float(y_ref[i, 0]),
                "y": y,
                "failed": bool(fail),
            }
            if y is None:
                rec.update({"abs_err": None, "analog_pass": False, "class_ok": False})
            else:
                rec["abs_err"] = abs(y - rec["y_ref"])
                rec["analog_pass"] = rec["abs_err"] <= ERROR_LIMIT
                rec["class"] = classify(y)
                rec["class_ok"] = rec["class"] == int(XOR_Y[i])
            rows.append(rec)
            print(
                f"  T={temp} vec={i} y={y} |err|={rec.get('abs_err')} "
                f"pass={rec.get('analog_pass')}",
                flush=True,
            )
    ok = [r for r in rows if r.get("abs_err") is not None]
    n_pass = sum(1 for r in ok if r.get("analog_pass"))
    n_cls = sum(1 for r in ok if r.get("class_ok"))
    p55 = all(r.get("analog_pass") for r in ok if r["temp_C"] == 55.0)
    p70 = all(r.get("analog_pass") for r in ok if r["temp_C"] == 70.0)
    if p55 and p70:
        decision, label, status = (
            "A",
            "ANALOG 1 mV HOLDS AT 55 C AND 70 C; 85 C REMAINS THE BOUNDARY",
            "DEMONSTRATED",
        )
        nxt = (
            "Promote XOR compile analog range as -40 to 70 C (ideal discrete R). "
            "85 C is class-only. Next MVP step is the DAC/ADC interface, not more temp points."
        )
    elif p55 and not p70:
        decision, label, status = (
            "B",
            "ANALOG HOLDS AT 55 C; 70 C MISSES",
            "PARTIALLY VALIDATED",
        )
        nxt = "Document 55 C as the analog ceiling. Move to the I/O interface."
    else:
        decision, label, status = (
            "B",
            "85 C MISS EXTENDS BELOW 70 C",
            "PARTIALLY VALIDATED",
        )
        nxt = "Room-temperature XOR compile still stands. Do not polish temperature further before I/O."
    report = {
        "experiment_id": "exp66",
        "status": status,
        "decision": decision,
        "decision_label": label,
        "n_analog_pass": n_pass,
        "n_class_pass": n_cls,
        "rows": rows,
        "next_experiment": nxt,
        "silicon": False,
        "conclusion": f"Decision {decision} — {label}. MIXED-LEVEL. Not silicon.",
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / "exp66_xor_temp_bound.json").write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8"
    )
    lines = [
        "# Experiment 66 — XOR temperature bound",
        "",
        "Experiments 1-65 were not modified. Not silicon.",
        "",
        f"**Status: {status}**",
        f"**Decision {decision} — {label}**",
        "",
        "| T (C) | vec | |err| (mV) | pass |",
        "| ---: | ---: | ---: | --- |",
    ]
    for r in rows:
        ae = r.get("abs_err")
        lines.append(
            f"| {r['temp_C']} | {r['vector']} | "
            f"{'n/a' if ae is None else f'{ae * 1e3:.4f}'} | {r.get('analog_pass')} |"
        )
    lines += ["", report["conclusion"], "", "## Next experiment", "", nxt, ""]
    (RESULTS_DIR / "exp66_xor_temp_bound.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"Experiment 66 Decision {decision} — {label}", flush=True)


if __name__ == "__main__":
    main()
