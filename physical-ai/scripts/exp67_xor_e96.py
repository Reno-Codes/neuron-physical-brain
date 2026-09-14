"""Experiment 67: E96 catalog snap of compiled XOR weight/bias resistors.

Does not edit frozen weights. Substitutes manufactured E96 values in SPICE
only. Invert/TIA/ReLU 10k parts are already E96. Not silicon.
"""

from __future__ import annotations

import csv
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

DEST = PROJECT_ROOT / "physical_design" / "xor_2_4_1"
CIRCUIT_DIR = PROJECT_ROOT / "circuits" / "exp67_xor_e96"
RESULTS_DIR = PROJECT_ROOT / "results"
SNAP_ROLES = {"weight", "bias"}


def snap_netlist(net: str, table: list[dict]) -> tuple[str, list[dict]]:
    changes = []
    lines = []
    by_ref = {row["ref"]: row for row in table}
    for raw in net.splitlines():
        parts = raw.split()
        if len(parts) >= 4 and parts[0] in by_ref:
            row = by_ref[parts[0]]
            if row.get("role") in SNAP_ROLES:
                exact = float(row["R_exact_ohm"])
                e96 = float(row["R_e96_ohm"])
                if e96 != exact:
                    parts[3] = f" {e96:.15g}"
                    # keep nodes; rebuild
                    lines.append(f"{parts[0]} {parts[1]} {parts[2]} {e96:.15g}")
                    changes.append(
                        {
                            "ref": parts[0],
                            "exact": exact,
                            "e96": e96,
                            "rel": (e96 - exact) / exact,
                        }
                    )
                    continue
        lines.append(raw)
    return "\n".join(lines) + "\n", changes


def main() -> None:
    net0 = (DEST / "netlist.cir").read_text(encoding="utf-8")
    with (DEST / "resistor_values.csv").open(encoding="utf-8") as fh:
        table = list(csv.DictReader(fh))
    net, changes = snap_netlist(net0, table)
    CIRCUIT_DIR.mkdir(parents=True, exist_ok=True)
    spiceinit_behavior(CIRCUIT_DIR, "ps")
    ng = find_ngspice()
    model = load_npz(PROJECT_ROOT / "models" / "xor_model.npz")
    _z, _h, y_ref = software_forward(model, XOR_X)
    print(f"E96 snaps n={len(changes)}", flush=True)
    rows = []
    for i, x in enumerate(XOR_X):
        path = CIRCUIT_DIR / f"xor_{i}.cir"
        path.write_text(set_inputs(net, x), encoding="utf-8")
        result = run_ngspice_ex(ng, path, timeout=180.0, pspice=True)
        text = f"{result.stdout or ''}\n{result.stderr or ''}"
        fail = detect_spice_failure(result)
        y = last(extract_all(text, "yo1"))
        rec = {
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
            f"  vec={i} y={y} |err|={rec.get('abs_err')} "
            f"class={rec.get('class')} pass={rec.get('analog_pass')}",
            flush=True,
        )
    ok = [r for r in rows if r.get("abs_err") is not None]
    n_pass = sum(1 for r in ok if r.get("analog_pass"))
    n_cls = sum(1 for r in ok if r.get("class_ok"))
    mae = float(np.mean([r["abs_err"] for r in ok])) if ok else None
    mx = max((r["abs_err"] for r in ok), default=None)
    if n_pass == 4 and n_cls == 4:
        decision, label, status = (
            "A",
            "E96 WEIGHT/BIAS SNAP STILL MATCHES FROZEN XOR",
            "DEMONSTRATED",
        )
        nxt = "First PCB may use E96 catalog parts for weights. Next is a real DAC/ADC hookup."
    elif n_cls == 4:
        decision, label, status = (
            "B",
            "E96 KEEPS CLASS; ANALOG 1 mV MISSED",
            "PARTIALLY VALIDATED",
        )
        nxt = "Use 0.1% / exact R for analog, or accept class-only E96. I/O interface is still the MVP blocker."
    else:
        decision, label, status = (
            "C",
            "E96 SNAP BREAKS XOR",
            "TECHNOLOGY BOUNDARY",
        )
        nxt = "Do not snap weights for the first board. Use exact compiled R."
    report = {
        "experiment_id": "exp67",
        "status": status,
        "decision": decision,
        "decision_label": label,
        "n_snaps": len(changes),
        "max_rel_snap": max((abs(c["rel"]) for c in changes), default=None),
        "changes": changes,
        "mae_V": mae,
        "max_abs_err_V": mx,
        "n_analog_pass": n_pass,
        "n_class_pass": n_cls,
        "rows": rows,
        "silicon": False,
        "weights_edited": False,
        "next_experiment": nxt,
        "conclusion": f"Decision {decision} — {label}. MIXED-LEVEL. Not silicon.",
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / "exp67_xor_e96.json").write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8"
    )
    mae_txt = "n/a" if mae is None else f"{mae * 1e3:.4f}"
    mx_txt = "n/a" if mx is None else f"{mx * 1e3:.4f}"
    lines = [
        "# Experiment 67 — E96 XOR resistor snap",
        "",
        "Experiments 1-66 were not modified. Frozen weights not edited. Not silicon.",
        "",
        f"**Status: {status}**",
        f"**Decision {decision} — {label}**",
        "",
        f"Snapped {len(changes)} weight/bias resistors to nearest E96.",
        f"XOR MAE = {mae_txt} mV; max |err| = {mx_txt} mV; analog {n_pass}/4; class {n_cls}/4.",
        "",
        "| vec | y_ref (V) | y (V) | |err| (mV) | class | pass |",
        "| ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for r in rows:
        ae = r.get("abs_err")
        lines.append(
            f"| {r['vector']} | {r['y_ref']:.9f} | {r.get('y')} | "
            f"{'n/a' if ae is None else f'{ae * 1e3:.4f}'} | {r.get('class')} | "
            f"{r.get('analog_pass')} |"
        )
    lines += ["", report["conclusion"], "", "## Next experiment", "", nxt, ""]
    (RESULTS_DIR / "exp67_xor_e96.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"Experiment 67 Decision {decision} — {label}", flush=True)


if __name__ == "__main__":
    main()
