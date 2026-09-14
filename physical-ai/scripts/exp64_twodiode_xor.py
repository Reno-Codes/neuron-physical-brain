"""Experiment 64: inverting precision-rectifier ReLU, then compiler XOR.

Closed on this path:
- Exp63: single-diode superdiode OP/TRAN aborts on xh1d in the 4-ReLU netlist
- Exp64 first attempt: bidirectional clamp follower passed negatives (rejected)

This attempt: textbook two-diode inverting rectifier (same 1N4148 card).
Hidden TIA emits -z so y = max(-(-z), 0) = ReLU(z).

Does not modify Experiments 1-63. Does not edit frozen XOR weights.
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
from compiler.compile_physical import compile_mlp
from compiler.parser import software_forward
from compiler.primitives import DIODE_LIB, OPA189_LIB
from exp39_pdk_o2_cell import last
from exp45_documented_tia import spiceinit_behavior
from exp62_physical_relu import ERROR_LIMIT, build_table, xor_hidden_preacts
from offset_vg_search import run_ngspice_ex
from test_robustness import extract_all

CIRCUIT_DIR = PROJECT_ROOT / "circuits" / "exp64_xor"
DEST = PROJECT_ROOT / "physical_design" / "xor_2_4_1"
RESULTS_DIR = PROJECT_ROOT / "results"
MODEL_PATH = PROJECT_ROOT / "models" / "xor_model.npz"


def emit_inv_rect(vin: float) -> str:
    opa = OPA189_LIB.as_posix()
    dlib = DIODE_LIB.as_posix()
    return "\n".join(
        [
            "* Experiment 64 isolated inverting precision rectifier",
            "* dest = max(-vin, 0). Same 1N4148 card as Experiment 62.",
            f".include \"{opa}\"",
            f".include \"{dlib}\"",
            f"Vin in 0 DC {vin:.15g}",
            "Vdd vdd 0 DC 15",
            "Vss vss 0 DC -15",
            "R1 in inn 10000",
            "Xamp 0 inn vdd vss amp OPAx189",
            "Xd1 inn amp 1N4148",
            "Xd2 amp out 1N4148",
            "Rf out inn 10000",
            "Rload out 0 10000",
            "Cload out 0 1p",
            "",
            ".control",
            "set numdgt=15",
            "op",
            "print v(in) v(out) v(amp)",
            "print i(Vdd)",
            ".endc",
            "",
            ".end",
            "",
        ]
    )


def run_iso(ng, vin: float, dest: Path, name: str) -> dict:
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / f"{name}.cir"
    path.write_text(emit_inv_rect(vin), encoding="utf-8")
    result = run_ngspice_ex(ng, path, timeout=90.0, pspice=True)
    text = f"{result.stdout or ''}\n{result.stderr or ''}"
    fail = detect_spice_failure(result)
    zref = max(-vin, 0.0)
    rec: dict = {
        "name": name,
        "vin": vin,
        "z_ref": zref,
        "python_corrected": False,
    }
    if fail:
        rec.update({"failed": True, "failure_reason": fail, "y": None, "abs_err": None, "analog_pass": False})
        return rec
    y = last(extract_all(text, "v(out)"))
    if y is None:
        rec.update({"failed": True, "failure_reason": "missing v(out)", "y": None, "abs_err": None, "analog_pass": False})
        return rec
    err = y - zref
    rec.update(
        {
            "failed": False,
            "y": y,
            "v_amp": last(extract_all(text, "v(amp)")),
            "err": err,
            "abs_err": abs(err),
            "analog_pass": abs(err) <= ERROR_LIMIT,
        }
    )
    return rec


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


def summarize(rows: list[dict]) -> dict:
    ok = [r for r in rows if not r.get("failed") and r.get("abs_err") is not None]
    fails = [r for r in rows if r.get("failed")]
    n_pass = sum(1 for r in ok if r.get("analog_pass"))
    abs_err = [float(r["abs_err"]) for r in ok]
    return {
        "n": len(rows),
        "n_ok": len(ok),
        "n_fail": len(fails),
        "n_pass": n_pass,
        "all_pass": n_pass == len(rows) and not fails,
        "mae_V": float(np.mean(abs_err)) if abs_err else None,
        "max_abs_err_V": max(abs_err) if abs_err else None,
        "worst_vin": None if not ok else max(ok, key=lambda r: float(r["abs_err"]))["vin"],
    }


def main() -> None:
    CIRCUIT_DIR.mkdir(parents=True, exist_ok=True)
    spiceinit_behavior(CIRCUIT_DIR, "ps")
    ng = find_ngspice()
    table = build_table()
    xor_z = xor_hidden_preacts()
    print(f"==== isolated inverting rectifier n={len(table)} ====", flush=True)
    iso_rows = []
    for i, vin in enumerate(table):
        rec = run_iso(ng, vin, CIRCUIT_DIR, f"iso_{i:02d}")
        rec["xor_hidden"] = any(abs(vin - z) < 1e-9 for z in xor_z)
        iso_rows.append(rec)
        print(
            f"  vin={vin:+.6f} y={rec.get('y')} ref={rec.get('z_ref')} "
            f"|err|={rec.get('abs_err')} pass={rec.get('analog_pass')} fail={rec.get('failed')}",
            flush=True,
        )
    iso = summarize(iso_rows)
    print(f"  isolated summary {iso}", flush=True)
    if not iso["all_pass"]:
        decision, label, status = (
            "C",
            "INVERTING RECTIFIER FAILED ISOLATED GATE; DO NOT COMPILE XOR",
            "TECHNOLOGY BOUNDARY",
        )
        nxt = "Keep the 1N4148 card. Do not invent diode parameters."
        report = {
            "experiment_id": "exp64",
            "status": status,
            "decision": decision,
            "decision_label": label,
            "isolated": iso,
            "next_experiment": nxt,
        }
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        (RESULTS_DIR / "exp64_twodiode_xor.json").write_text(
            json.dumps(report, indent=2, default=str), encoding="utf-8"
        )
        print(f"Experiment 64 Decision {decision} — {label}", flush=True)
        return

    print("==== compile XOR with inverting-rectifier ReLU ====", flush=True)
    compiled = compile_mlp(
        MODEL_PATH,
        DEST,
        XOR_X,
        title="* Physical AI compiler MVP: frozen XOR 2-4-1 (inverting rectifier ReLU)",
    )
    net0 = (DEST / "netlist.cir").read_text(encoding="utf-8")
    if "Xh1d1" not in net0 or "Rh1r1" not in net0:
        raise SystemExit("BLOCKED: compiler netlist missing inverting rectifier")
    model = compiled["model"]
    _z1, h, y_ref = software_forward(model, XOR_X)
    rows = []
    for i, x in enumerate(XOR_X):
        net = set_inputs(net0, x)
        path = CIRCUIT_DIR / f"xor_{i}.cir"
        path.write_text(net, encoding="utf-8")
        print(f"SPICE XOR vector {i} x={x.tolist()}", flush=True)
        result = run_ngspice_ex(ng, path, timeout=300.0, pspice=True)
        text = f"{result.stdout or ''}\n{result.stderr or ''}"
        fail = detect_spice_failure(result)
        if fail is None and "timestep too small" in text.lower():
            fail = "ngspice OP timestep too small"
        y = last(extract_all(text, "yo1"))
        rec = {
            "vector": i,
            "x": x.tolist(),
            "y_ref": float(y_ref[i, 0]),
            "y": y,
            "analysis": "tran_2ms_uic",
            "h_ref": [float(v) for v in h[i]],
            "h": [last(extract_all(text, f"yh{j}")) for j in range(1, 5)],
            "z": [last(extract_all(text, f"zh{j}")) for j in range(1, 5)],
            "class_ref": int(XOR_Y[i]),
            "failed": bool(fail),
            "failure_reason": fail,
            "i_dd": last(extract_all(text, "i(vdd)")),
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
            f"fail={rec.get('failed')} i_dd={rec.get('i_dd')}",
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
            "First compiler-generated mixed-level XOR circuit is a PCB MVP "
            "candidate. Next: temperature on this netlist, then a real "
            "input interface. Do not reopen miller."
        )
    elif n_cls == 4:
        decision, label, status = (
            "B",
            "XOR CLASS HOLDS; ANALOG 1 mV MISSED",
            "PARTIALLY VALIDATED",
        )
        nxt = "Diagnose worst vector. Do not Python-correct v(o1lin)."
    elif any(r.get("failed") for r in rows):
        decision, label, status = (
            "E",
            "INVERTING-RECTIFIER XOR SPICE FAILED",
            "NUMERICAL ISSUE",
        )
        nxt = "Inspect OP / TRAN before changing frozen weights."
    else:
        decision, label, status = (
            "C",
            "COMPILER XOR DISAGREES WITH FROZEN SOFTWARE",
            "TECHNOLOGY BOUNDARY",
        )
        nxt = "Find the mechanism. Do not invent a mapping."

    report = {
        "experiment_id": "exp64",
        "kind": "inverting precision rectifier ReLU + compiler XOR",
        "status": status,
        "decision": decision,
        "decision_label": label,
        "yield_claim": False,
        "silicon": False,
        "physical_tia_validated": False,
        "closed_paths": [
            "Exp63 single-diode superdiode OP/TRAN abort on xh1d",
            "Exp64 clamp follower passed negatives (rejected)",
        ],
        "isolated": iso,
        "mae_V": mae,
        "max_abs_err_V": mx,
        "n_analog_pass": n_pass,
        "n_class_pass": n_cls,
        "rows": rows,
        "architecture": compiled["architecture"],
        "next_experiment": nxt,
        "conclusion": f"Decision {decision} — {label}. MIXED-LEVEL. Not silicon.",
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / "exp64_twodiode_xor.json").write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8"
    )
    mae_txt = "n/a" if mae is None else f"{mae * 1e3:.4f}"
    mx_txt = "n/a" if mx is None else f"{mx * 1e3:.4f}"
    lines = [
        "# Experiment 64 — inverting precision rectifier + compiler XOR",
        "",
        "Experiments 1-63 were not modified. Frozen xor_model.npz. Not silicon.",
        "",
        f"**Status: {status}**",
        f"**Decision {decision} — {label}**",
        "",
        "Closed: single-diode network OP abort; bidirectional clamp follower (negatives pass).",
        "Primitive: textbook two-diode inverting rectifier, documented 1N4148.",
        "Reference for isolated test is `max(-Vin, 0)`. Hidden TIA supplies `-z`.",
        "",
        f"Isolated: {iso['n_pass']}/{iso['n']} pass, "
        f"MAE={None if iso['mae_V'] is None else iso['mae_V']*1e3:.4f} mV.",
        "",
        f"XOR MAE = {mae_txt} mV; max |err| = {mx_txt} mV; "
        f"analog {n_pass}/4; class {n_cls}/4.",
        "",
        "| vec | x | y_ref (V) | y (V) | |err| (mV) | class | pass |",
        "| ---: | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for r in rows:
        ae = r.get("abs_err")
        lines.append(
            f"| {r['vector']} | {r['x']} | {r['y_ref']:.9f} | {r.get('y')} | "
            f"{'n/a' if ae is None else f'{ae * 1e3:.4f}'} | {r.get('class')} | "
            f"{r.get('analog_pass')} |"
        )
    lines += ["", report["conclusion"], "", "## Next experiment", "", nxt, ""]
    (RESULTS_DIR / "exp64_twodiode_xor.md").write_text("\n".join(lines), encoding="utf-8")
    (DEST / "validation_report.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"Experiment 64 Decision {decision} — {label}", flush=True)


if __name__ == "__main__":
    main()
