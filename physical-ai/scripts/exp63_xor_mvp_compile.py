"""Experiment 63: compile frozen XOR into physical artifacts and SPICE-validate.

Does not retrain. Does not edit frozen weights. Does not Python-correct
circuit outputs. Experiments 1-62 are not modified.

The PC applies Vin and reads v(o1lin). The circuit must compute XOR.
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
from compile_xor import XOR_X, XOR_Y, classify, find_ngspice, load_model
from compiler.compile_physical import compile_mlp
from compiler.parser import PhysicalMappingFailed, software_forward
from exp39_pdk_o2_cell import last
from exp45_documented_tia import spiceinit_behavior
from offset_vg_search import run_ngspice_ex
from test_robustness import extract_all

DEST = PROJECT_ROOT / "physical_design" / "xor_2_4_1"
CIRCUIT_DIR = PROJECT_ROOT / "circuits" / "exp63_xor_mvp"
RESULTS_DIR = PROJECT_ROOT / "results"
MODEL_PATH = PROJECT_ROOT / "models" / "xor_model.npz"
ERROR_LIMIT = 1.0e-3
VIN_LINE = "Vin{i} in{i} 0 DC 0"


def set_inputs(net: str, x: np.ndarray) -> str:
    out = []
    for raw in net.splitlines():
        s = raw.strip()
        replaced = False
        for i, val in enumerate(x, start=1):
            if s.startswith(f"Vin{i} "):
                out.append(f"Vin{i} in{i} 0 DC {float(val):.15g}")
                replaced = True
                break
        if not replaced:
            out.append(raw)
    return "\n".join(out) + ("\n" if net.endswith("\n") else "")


def refuse_unknown_activation() -> dict:
    bad = PROJECT_ROOT / "circuits" / "exp63_xor_mvp" / "_refuse_tanh.npz"
    bad.parent.mkdir(parents=True, exist_ok=True)
    model = load_model(MODEL_PATH)
    np.savez(
        bad,
        W1=model["W1"],
        b1=model["b1"],
        W2=model["W2"],
        b2=model["b2"],
        hidden_activation=np.array("tanh"),
        output_activation=np.array("linear"),
    )
    try:
        compile_mlp(bad, CIRCUIT_DIR / "_refuse_tanh", XOR_X)
        return {"refused": False, "reason": None}
    except PhysicalMappingFailed as exc:
        return {"refused": True, "reason": str(exc)}


def main() -> None:
    print("==== Experiment 63 XOR physical compile ====", flush=True)
    try:
        compiled = compile_mlp(
            MODEL_PATH,
            DEST,
            XOR_X,
            title="* Physical AI compiler MVP: frozen XOR 2-4-1",
        )
    except PhysicalMappingFailed as exc:
        print(f"PHYSICAL MAPPING FAILED: {exc}", flush=True)
        report = {
            "experiment_id": "exp63",
            "status": "PHYSICAL MAPPING FAILED",
            "decision": "C",
            "reason": str(exc),
        }
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        (RESULTS_DIR / "exp63_xor_mvp_compile.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
        raise SystemExit(1) from exc

    refuse = refuse_unknown_activation()
    print(f"refuse tanh: {refuse}", flush=True)
    if not refuse["refused"]:
        raise SystemExit("BLOCKED: compiler did not refuse unsupported tanh")

    net0 = (DEST / "netlist.cir").read_text(encoding="utf-8")
    CIRCUIT_DIR.mkdir(parents=True, exist_ok=True)
    spiceinit_behavior(CIRCUIT_DIR, "ps")
    ng = find_ngspice()
    model = compiled["model"]
    z1, h, y_ref = software_forward(model, XOR_X)

    rows = []
    for i, x in enumerate(XOR_X):
        net = set_inputs(net0, x)
        path = CIRCUIT_DIR / f"xor_{i}.cir"
        path.write_text(net, encoding="utf-8")
        print(f"SPICE XOR vector {i} x={x.tolist()}", flush=True)
        result = run_ngspice_ex(ng, path, timeout=300.0, pspice=True)
        text = f"{result.stdout or ''}\n{result.stderr or ''}"
        fail = detect_spice_failure(result)
        y = last(extract_all(text, "v(o1lin)"))
        href = [
            last(extract_all(text, f"v(h{j}y)"))
            for j in range(1, model["n_hidden"] + 1)
        ]
        rec = {
            "vector": i,
            "x": x.tolist(),
            "y_ref": float(y_ref[i, 0]),
            "y": y,
            "h_ref": [float(v) for v in h[i]],
            "h": href,
            "class_ref": int(XOR_Y[i]),
            "failed": bool(fail),
            "failure_reason": fail,
            "python_corrected": False,
        }
        if y is None:
            rec["failed"] = True
            rec["failure_reason"] = rec["failure_reason"] or "missing v(o1lin)"
            rec["abs_err"] = None
            rec["analog_pass"] = False
            rec["class"] = None
            rec["class_ok"] = False
        else:
            rec["abs_err"] = abs(y - rec["y_ref"])
            rec["analog_pass"] = rec["abs_err"] <= ERROR_LIMIT
            rec["class"] = classify(y)
            rec["class_ok"] = rec["class"] == rec["class_ref"]
        rows.append(rec)
        print(
            f"  y={y} y_ref={rec['y_ref']} |err|={rec.get('abs_err')} "
            f"class={rec.get('class')} pass={rec.get('analog_pass')} "
            f"fail={rec.get('failed')}",
            flush=True,
        )

    ok = [r for r in rows if not r.get("failed") and r.get("abs_err") is not None]
    n_pass = sum(1 for r in ok if r.get("analog_pass"))
    n_cls = sum(1 for r in ok if r.get("class_ok"))
    mae = float(np.mean([r["abs_err"] for r in ok])) if ok else None
    mx = max((r["abs_err"] for r in ok), default=None)

    if n_pass == 4 and n_cls == 4:
        decision, label, status = (
            "A",
            "COMPILER-GENERATED XOR CIRCUIT MATCHES FROZEN SOFTWARE",
            "DEMONSTRATED",
        )
        nxt = (
            "Promote this compile as the first PCB MVP candidate. "
            "Next: temperature on the XOR board netlist, then BOM-realizable "
            "E96 robustness. Do not jump to F40 transistorization."
        )
    elif n_cls == 4 and n_pass < 4:
        decision, label, status = (
            "B",
            "XOR CLASSIFICATION HOLDS; ANALOG 1 mV MISSED",
            "PARTIALLY VALIDATED",
        )
        nxt = "Diagnose worst vector (TIA leftover vs ReLU leakage vs invert error)."
    elif any(r.get("failed") for r in rows):
        decision, label, status = (
            "E",
            "SPICE FAILED ON COMPILER NETLIST",
            "NUMERICAL ISSUE",
        )
        nxt = "Inspect operating points before changing the frozen XOR weights."
    else:
        decision, label, status = (
            "C",
            "COMPILER XOR CIRCUIT DISAGREES WITH FROZEN SOFTWARE",
            "TECHNOLOGY BOUNDARY",
        )
        nxt = "Find the mechanism. Do not Python-correct v(o1lin)."

    report = {
        "experiment_id": "exp63",
        "kind": "compiler-generated XOR 2-4-1 physical compile + SPICE",
        "status": status,
        "decision": decision,
        "decision_label": label,
        "yield_claim": False,
        "silicon": False,
        "physical_tia_validated": False,
        "python_corrected": False,
        "refuse_unknown_activation": refuse,
        "dest": str(DEST),
        "mae_V": mae,
        "max_abs_err_V": mx,
        "n_analog_pass": n_pass,
        "n_class_pass": n_cls,
        "rows": rows,
        "architecture": compiled["architecture"],
        "next_experiment": nxt,
        "conclusion": (
            f"Decision {decision} — {label}. "
            "MIXED-LEVEL compiler output. Not silicon. Not firmware XOR."
        ),
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / "exp63_xor_mvp_compile.json").write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8"
    )

    val_lines = [
        "# Validation report — Experiment 63",
        "",
        f"**Status: {status}**",
        f"**Decision {decision} — {label}**",
        "",
        "Frozen software is the reference. `v(o1lin)` is the physical result.",
        "No Python correction.",
        "",
        f"MAE = {'n/a' if mae is None else f'{mae * 1e3:.4f}'} mV; "
        f"max |err| = {'n/a' if mx is None else f'{mx * 1e3:.4f}'} mV; "
        f"analog pass {n_pass}/4; class {n_cls}/4.",
        "",
        "| vec | x | y_ref (V) | y (V) | |err| (mV) | class | pass |",
        "| ---: | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for r in rows:
        ae = r.get("abs_err")
        val_lines.append(
            f"| {r['vector']} | {r['x']} | {r['y_ref']:.9f} | {r.get('y')} | "
            f"{None if ae is None else ae * 1e3:.4f} | {r.get('class')} | "
            f"{r.get('analog_pass')} |"
        )
    val_lines += ["", report["conclusion"], "", "## Next", "", nxt, ""]
    (DEST / "validation_report.md").write_text("\n".join(val_lines), encoding="utf-8")
    (RESULTS_DIR / "exp63_xor_mvp_compile.md").write_text(
        "\n".join(
            [
                "# Experiment 63 — compiler-generated XOR MVP",
                "",
                "Experiments 1-62 were not modified. Frozen xor_model.npz. Not silicon.",
                "",
                *val_lines[2:],
            ]
        ),
        encoding="utf-8",
    )
    print(f"Experiment 63 Decision {decision} — {label}", flush=True)


if __name__ == "__main__":
    main()
