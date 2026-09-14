"""Experiment 62: documented precision-rectifier ReLU primitive.

Isolated ReLU only. Does not modify Experiments 1-61.
Does not invent diode parameters. Does not Python-correct SPICE.

Control: Experiment 4 B-source + teaching Dsi (regression).
Candidates: OPA189 macromodel + teaching Dsi, and OPA189 + TI 1N4148
extracted unmodified from the ngspice-tree TLC555.LIB.

Not silicon. Not a physical TIA. Miller family remains closed.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from benchmark_scaling import detect_spice_failure
from compile_xor import PROJECT_ROOT, find_ngspice, load_model
from exp39_pdk_o2_cell import last
from exp45_documented_tia import spiceinit_behavior
from offset_vg_search import run_ngspice_ex
from test_robustness import extract_all

CIRCUIT_DIR = PROJECT_ROOT / "circuits" / "exp62_relu"
RESULTS_DIR = PROJECT_ROOT / "results"
OPA189_LIB = PROJECT_ROOT / "models" / "vendor" / "ti" / "opa189" / "OPAx189.LIB"
DIODE_LIB = PROJECT_ROOT / "models" / "vendor" / "ti" / "1n4148" / "1N4148.LIB"
ERROR_LIMIT = 1.0e-3
RLOAD = 10_000.0
VSUPPLY = 15.0
XOR_Z_ATOL = 1.0e-9

# Extra rails around the frozen XOR hidden pre-activation range.
TABLE_EXTRA = (-3.7, -2.0, -1.0, -0.5, -0.1, -0.01, 0.0, 0.01, 0.1, 0.5, 1.0, 2.0)


def xor_hidden_preacts() -> list[float]:
    model = load_model()
    w1 = model["W1"]
    b1 = model["b1"]
    x = np.array([[0.0, 0.0], [0.0, 1.0], [1.0, 0.0], [1.0, 1.0]])
    z1 = x @ w1.T + b1
    return [float(v) for v in z1.ravel()]


def build_table() -> list[float]:
    vals = list(TABLE_EXTRA) + xor_hidden_preacts()
    uniq: list[float] = []
    for v in vals:
        if not any(math.isclose(v, u, rel_tol=0, abs_tol=XOR_Z_ATOL) for u in uniq):
            uniq.append(v)
    uniq.sort()
    return uniq


def emit_control_bsource(vin: float) -> str:
    return "\n".join(
        [
            "* Experiment 62 control: Exp4 B-source + teaching Dsi",
            "* Teaching diode. Not a vendor model.",
            f"Vin in 0 DC {vin:.15g}",
            (
                f"Bop amp 0 V = max(-{VSUPPLY:.15g}, "
                f"min({VSUPPLY:.15g}, 1e5 * v(in, out)))"
            ),
            "D1 amp out Dsi",
            f"Rload out 0 {RLOAD:.15g}",
            ".model Dsi D(Is=1e-14 N=1 Rs=1)",
            "",
            ".control",
            "set numdgt=15",
            "op",
            "print v(in) v(out) v(amp)",
            ".endc",
            "",
            ".end",
            "",
        ]
    )


def emit_opa189(vin: float, diode: str) -> str:
    opa = OPA189_LIB.as_posix()
    lines = [
        f"* Experiment 62 OPA189 superdiode ReLU diode={diode}",
        "* Level-1 documented macromodel. Not silicon. Not MOS.",
        f".include \"{opa}\"",
        f"Vin in 0 DC {vin:.15g}",
        f"Vdd vdd 0 DC {VSUPPLY:.15g}",
        f"Vss vss 0 DC {-VSUPPLY:.15g}",
        "Xamp in out vdd vss amp OPAx189",
    ]
    if diode == "teaching_dsi":
        lines += [
            "* Teaching diode (same card as Experiment 4). Isolates the op-amp host.",
            "D1 amp out Dsi",
            ".model Dsi D(Is=1e-14 N=1 Rs=1)",
        ]
    elif diode == "1n4148":
        dlib = DIODE_LIB.as_posix()
        lines += [
            f".include \"{dlib}\"",
            "* TI 1N4148 from ngspice-tree TLC555.LIB; parameters not invented.",
            "Xd amp out 1N4148",
        ]
    else:
        raise ValueError(diode)
    lines += [
        f"Rload out 0 {RLOAD:.15g}",
        "Cload out 0 1p",
        "",
        ".control",
        "set numdgt=15",
        "op",
        "print v(in) v(out) v(amp)",
        "print i(Vin) i(Vdd) i(Vss)",
        ".endc",
        "",
        ".end",
        "",
    ]
    return "\n".join(lines)


def run_one(ng, net: str, dest: Path, name: str, vin: float, pspice: bool) -> dict:
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / f"{name}.cir"
    path.write_text(net, encoding="utf-8")
    result = run_ngspice_ex(ng, path, timeout=90.0, pspice=pspice)
    text = f"{result.stdout or ''}\n{result.stderr or ''}"
    fail = detect_spice_failure(result)
    rec: dict = {
        "name": name,
        "vin": vin,
        "z_ref": max(0.0, vin),
        "path": str(path),
        "pspice": pspice,
        "python_corrected": False,
    }
    if fail:
        rec.update(
            {
                "failed": True,
                "failure_reason": fail,
                "y": None,
                "abs_err": None,
                "analog_pass": False,
            }
        )
        return rec
    y = last(extract_all(text, "v(out)"))
    if y is None:
        rec.update(
            {
                "failed": True,
                "failure_reason": "missing v(out)",
                "y": None,
                "abs_err": None,
                "analog_pass": False,
            }
        )
        return rec
    zref = max(0.0, vin)
    err = y - zref
    rec.update(
        {
            "failed": False,
            "failure_reason": None,
            "y": y,
            "v_amp": last(extract_all(text, "v(amp)")),
            "err": err,
            "abs_err": abs(err),
            "analog_pass": abs(err) <= ERROR_LIMIT,
            "i_dd": last(extract_all(text, "i(vdd)")),
        }
    )
    return rec


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
        "worst_vin": None
        if not ok
        else max(ok, key=lambda r: float(r["abs_err"]))["vin"],
    }


def main() -> None:
    if not DIODE_LIB.is_file():
        raise SystemExit(f"BLOCKED missing documented 1N4148: {DIODE_LIB}")
    if not OPA189_LIB.is_file():
        raise SystemExit(f"BLOCKED missing OPA189: {OPA189_LIB}")
    table = build_table()
    xor_z = xor_hidden_preacts()
    print(f"ReLU table n={len(table)} XOR hidden preacts n={len(xor_z)}", flush=True)

    CIRCUIT_DIR.mkdir(parents=True, exist_ok=True)
    spiceinit_behavior(CIRCUIT_DIR, "ps")
    ng = find_ngspice()

    fabrics = [
        {
            "id": "exp4_bsource_dsi",
            "kind": "BEHAVIORAL teaching (Exp4 regression)",
            "pspice": False,
            "emit": lambda vin: emit_control_bsource(vin),
        },
        {
            "id": "opa189_teaching_dsi",
            "kind": "MIXED-LEVEL OPA189 + teaching Dsi",
            "pspice": True,
            "emit": lambda vin: emit_opa189(vin, "teaching_dsi"),
        },
        {
            "id": "opa189_1n4148",
            "kind": "MIXED-LEVEL OPA189 + documented 1N4148",
            "pspice": True,
            "emit": lambda vin: emit_opa189(vin, "1n4148"),
        },
    ]

    all_rows: dict[str, list[dict]] = {}
    summaries: dict[str, dict] = {}
    for fab in fabrics:
        rows = []
        print(f"==== {fab['id']} ====", flush=True)
        for i, vin in enumerate(table):
            name = f"{fab['id']}_{i:02d}"
            rec = run_one(ng, fab["emit"](vin), CIRCUIT_DIR, name, vin, fab["pspice"])
            rec["fabric"] = fab["id"]
            rec["xor_hidden"] = any(
                math.isclose(vin, z, rel_tol=0, abs_tol=XOR_Z_ATOL) for z in xor_z
            )
            rows.append(rec)
            print(
                f"  vin={vin:+.6f} y={rec.get('y')} |err|={rec.get('abs_err')} "
                f"pass={rec.get('analog_pass')} fail={rec.get('failed')}",
                flush=True,
            )
        all_rows[fab["id"]] = rows
        summaries[fab["id"]] = summarize(rows)
        print(f"  summary {summaries[fab['id']]}", flush=True)

    ctrl = summaries["exp4_bsource_dsi"]
    host = summaries["opa189_teaching_dsi"]
    doc = summaries["opa189_1n4148"]
    xor_doc = [
        r
        for r in all_rows["opa189_1n4148"]
        if r.get("xor_hidden")
    ]
    xor_doc_pass = all(
        (not r.get("failed")) and r.get("analog_pass") for r in xor_doc
    )

    if not ctrl["all_pass"]:
        decision, label, status = (
            "E",
            "EXPERIMENT 4 CONTROL FAILED; DO NOT INTERPRET CANDIDATES",
            "NUMERICAL ISSUE",
        )
        nxt = "Reproduce Experiment 4 before any ReLU compiler promotion."
    elif doc["all_pass"] and xor_doc_pass:
        decision, label, status = (
            "A",
            "OPA189 + DOCUMENTED 1N4148 SUPERDIODE PASSES ISOLATED ReLU",
            "DEMONSTRATED",
        )
        nxt = (
            "Experiment 63: compile the frozen XOR 2-4-1 network onto "
            "OPA189 TIA + this ReLU + discrete signed resistors, then SPICE-validate."
        )
    elif host["all_pass"] and not doc["all_pass"]:
        decision, label, status = (
            "B",
            "OPA189 HOSTS TEACHING DIODE; DOCUMENTED 1N4148 MISSES 1 mV",
            "PARTIALLY VALIDATED",
        )
        nxt = (
            "Do not invent a better diode. Try the two-diode precision rectifier "
            "with the same 1N4148 card, or refuse the PCB ReLU mapping."
        )
    elif xor_doc_pass and not doc["all_pass"]:
        decision, label, status = (
            "B",
            "XOR HIDDEN RANGE PASSES; FULL TABLE HAS FAILURES",
            "PARTIALLY VALIDATED",
        )
        nxt = "Bound the passing input range and refuse compiler mappings outside it."
    else:
        decision, label, status = (
            "C",
            "DOCUMENTED SUPERDIODE FAILED THE ISOLATED ReLU GATE",
            "TECHNOLOGY BOUNDARY",
        )
        nxt = (
            "Close this single-diode OPA189 superdiode if the mechanism is "
            "saturation/leakage. Do not invent diode parameters."
        )

    report = {
        "experiment_id": "exp62",
        "kind": "documented precision-rectifier ReLU",
        "status": status,
        "decision": decision,
        "decision_label": label,
        "yield_claim": False,
        "silicon": False,
        "physical_tia_validated": False,
        "physical_relu_validated": bool(doc["all_pass"] and xor_doc_pass),
        "error_limit_V": ERROR_LIMIT,
        "diode_source": str(DIODE_LIB),
        "summaries": summaries,
        "xor_hidden_n": len(xor_doc),
        "xor_hidden_all_pass": xor_doc_pass,
        "rows": {k: v for k, v in all_rows.items()},
        "next_experiment": nxt,
        "conclusion": (
            f"Decision {decision} — {label}. "
            "Level-1 OPA189 + documented 1N4148 superdiode. Not silicon."
        ),
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / "exp62_physical_relu.json").write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8"
    )
    lines = [
        "# Experiment 62 — documented precision-rectifier ReLU",
        "",
        "Experiments 1-61 were not modified. Isolated ReLU. Not silicon.",
        "",
        f"**Status: {status}**",
        f"**Decision {decision} — {label}**",
        "",
        "Reference is mathematical `max(0, Vin)`. SPICE `v(out)` is the result.",
        "The 1N4148 card is extracted unmodified from TI TLC555.LIB in the ngspice tree.",
        "",
        "| Fabric | n | pass | MAE (mV) | max |err| (mV) | worst Vin |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for fab_id, s in summaries.items():
        mae = None if s["mae_V"] is None else s["mae_V"] * 1e3
        mx = None if s["max_abs_err_V"] is None else s["max_abs_err_V"] * 1e3
        lines.append(
            f"| {fab_id} | {s['n']} | {s['n_pass']}/{s['n']} | "
            f"{mae if mae is None else f'{mae:.4f}'} | "
            f"{mx if mx is None else f'{mx:.4f}'} | {s['worst_vin']} |"
        )
    lines += [
        "",
        f"XOR hidden pre-activation points on opa189_1n4148: "
        f"{sum(1 for r in xor_doc if r.get('analog_pass'))}/{len(xor_doc)} pass.",
        "",
        report["conclusion"],
        "",
        "## Next experiment",
        "",
        nxt,
        "",
    ]
    (RESULTS_DIR / "exp62_physical_relu.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"Experiment 62 Decision {decision} — {label}", flush=True)


if __name__ == "__main__":
    main()
