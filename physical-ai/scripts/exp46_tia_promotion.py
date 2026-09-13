"""Experiment 46: promote Experiment 45 OPA189 TIA on W=10 o2.

Isolated cell only. Same frozen o2 / official tt R include / W=10 encode.
No resistor fitting. No Python correction. No MOS W/L. Not silicon.
Does not modify Experiments 1-45.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from compile_xor import PROJECT_ROOT, find_ngspice
from exp39_pdk_o2_cell import (
    ERROR_LIMIT,
    PDK_VERSION,
    TAG,
    bake_vin_step,
    discover_pdk,
    last,
)
from exp40_pdk_o2_cell import compile_o2_w2_1, prove_identity
from exp41_o2_residual import replace_resistors_w
from exp43_highgain_w10 import select_vectors
from exp45_documented_tia import (
    CANDIDATES,
    insert_macro,
    prepend_pdk_rc,
    run_cell,
    spiceinit_behavior,
)
from test_robustness import extract_all
from benchmark_scaling import detect_spice_failure
from offset_vg_search import run_ngspice_ex

CIRCUIT_DIR = PROJECT_ROOT / "circuits" / "exp46_o2"
RESULTS_DIR = PROJECT_ROOT / "results"
REPORT_JSON = RESULTS_DIR / "exp46_tia_promotion.json"
REPORT_MD = RESULTS_DIR / "exp46_tia_promotion.md"
Z_O2 = 2.459489570880132
Y_EXP45_OPA189 = 2.460095443162
REPEAT_ATOL_V = 1.0e-8
TEMPS = (-40.0, 27.0, 85.0)
TSTOP = 200e-6

PRIMARY = {"id": "OPA189", "vsupply": 15.0}
ALSO = (
    {"id": "OPA189", "vsupply": 5.0},
    {"id": "OPA388", "vsupply": 2.5},
)


def cand(cid: str) -> dict:
    return next(c for c in CANDIDATES if c["id"] == cid)


def write_tran(path: Path, net: str, hy, tstop: float = TSTOP, method: str | None = None) -> None:
    head, _, _ = net.partition(".control")
    baked = bake_vin_step(head, hy)
    opt = f"option method={method}\n" if method else ""
    ctrl = (
        "\n.control\nset numdgt=12\n"
        f"{opt}tran 1u {tstop:.15g}\n"
        f"meas tran ylin FIND v({TAG}lin) AT={tstop:.15g}\n"
        f"meas tran ysum FIND v({TAG}p) AT={tstop:.15g}\n"
        "print ylin\nprint ysum\n"
        ".endc\n.end\n"
    )
    path.write_text(baked.rstrip() + "\n" + ctrl, encoding="utf-8")


def run_tran(ng, net, hy, z_ref, name, method=None, timeout=420.0) -> dict:
    path = CIRCUIT_DIR / f"{name}.cir"
    tagged = net.replace(
        "* Experiment 45 SKY130 tt R+C via official .include (no .lib section)",
        "* Experiment 46 TIA promotion TRAN · not silicon",
    )
    write_tran(path, tagged, hy, TSTOP, method)
    result = run_ngspice_ex(ng, path, timeout=timeout, pspice=True)
    text = f"{result.stdout or ''}\n{result.stderr or ''}"
    fail = detect_spice_failure(result)
    rec = {
        "name": name,
        "path": str(path),
        "failed": bool(fail),
        "failure_reason": fail,
        "z_ref": float(z_ref),
        "tstop_s": TSTOP,
        "method": method or "default",
        "python_corrected": False,
    }
    if fail:
        rec["log_tail"] = text[-700:]
        print(f"  {name} TRAN FAIL {fail}", flush=True)
        return rec
    y = last(extract_all(text, "ylin"))
    vsum = last(extract_all(text, "ysum"))
    rec.update({"y": y, "vsum": vsum})
    if y is None:
        rec.update({"failed": True, "failure_reason": "missing ylin", "log_tail": text[-700:]})
        print(f"  {name} missing ylin", flush=True)
        return rec
    rec["err"] = y - float(z_ref)
    rec["abs_err"] = abs(y - float(z_ref))
    rec["analog_pass"] = rec["abs_err"] <= ERROR_LIMIT
    print(
        f"  {name} y={y} |err|={rec['abs_err']} pass={rec['analog_pass']} vsum={vsum}",
        flush=True,
    )
    return rec


def decide(report: dict) -> tuple[str, str, str]:
    dc = report.get("dc_repeat") or {}
    vecs = [r for r in (report.get("vectors") or []) if not r.get("failed") and r.get("y") is not None]
    trans = [r for r in (report.get("transients") or []) if not r.get("failed") and r.get("y") is not None]
    temps = [r for r in (report.get("temps") or []) if not r.get("failed") and r.get("y") is not None]
    extra_dc = [r for r in (report.get("supply_dc") or []) if not r.get("failed") and r.get("y") is not None]

    if not dc.get("analog_pass"):
        return "B", "PRIMARY DC DID NOT REPEAT THE EXPERIMENT 45 PASS", "CONTRADICTED"
    vec_pass = all(r.get("analog_pass") for r in vecs) if vecs else False
    tran_pass = any(r.get("analog_pass") for r in trans)
    temp_pass = all(r.get("analog_pass") for r in temps) if temps else False
    if vec_pass and tran_pass and temp_pass:
        return (
            "A",
            "OPA189 TIA PROMOTED ON ISOLATED W=10 o2 (DC/TRAN/TEMP)",
            "PARTIALLY VALIDATED",
        )
    if vec_pass and (tran_pass or temp_pass):
        return (
            "C",
            "OPA189 TIA PARTIALLY PROMOTED; ONE LADDER STEP INCOMPLETE",
            "PARTIALLY VALIDATED",
        )
    if extra_dc and any(r.get("analog_pass") for r in extra_dc) and dc.get("analog_pass"):
        return (
            "C",
            "OPA189 TIA DC HOLDS; DYNAMICS OR TEMPERATURE INCOMPLETE",
            "PARTIALLY VALIDATED",
        )
    return "C", "DC REPEAT ONLY; PROMOTION LADDER INCOMPLETE", "PARTIALLY VALIDATED"


def write_reports(report: dict) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    lines = [
        "# Experiment 46 — OPA189 TIA promotion on W=10 o2",
        "",
        "Experiments 1–45 were not modified. Frozen weights unchanged.",
        "Official tt resistor include from Experiment 45. No MOS W/L.",
        "No Python correction. Not silicon. Isolated cell only.",
        "",
        f"**Status: {report['status']}**",
        f"**Decision {report['decision']} — {report['decision_label']}**",
        "",
        "## DC repeat (vec 19, OPA189 ±15 V)",
        "",
    ]
    d = report.get("dc_repeat") or {}
    lines.append(
        f"- y = {d.get('y')}  |err| = {None if d.get('abs_err') is None else d['abs_err']*1e3:.6f} mV  "
        f"pass = {d.get('analog_pass')}  Δ vs Exp45 = {d.get('delta_vs_exp45')}"
    )
    lines += [
        "",
        "## Frozen F40 vectors (OPA189 ±15 V)",
        "",
        "| vector | role | z (V) | y (V) | |err| (mV) | pass |",
        "| ---: | --- | ---: | ---: | ---: | --- |",
    ]
    for r in report.get("vectors") or []:
        if r.get("failed") and r.get("y") is None:
            lines.append(
                f"| {r.get('vector')} | {r.get('role')} | {r.get('z_ref')} | "
                f"FAIL {r.get('failure_reason')} | — | no |"
            )
        else:
            ae = r.get("abs_err")
            lines.append(
                f"| {r.get('vector')} | {r.get('role')} | {r.get('z_ref')} | {r.get('y')} | "
                f"{None if ae is None else ae*1e3:.6f} | {r.get('analog_pass')} |"
            )
    lines += [
        "",
        "## 200 µs transient (vec 19)",
        "",
        "| name | method | y (V) | |err| (mV) | pass |",
        "| --- | --- | ---: | ---: | --- |",
    ]
    for r in report.get("transients") or []:
        if r.get("failed") and r.get("y") is None:
            lines.append(f"| {r.get('name')} | {r.get('method')} | FAIL {r.get('failure_reason')} | — | no |")
        else:
            ae = r.get("abs_err")
            lines.append(
                f"| {r.get('name')} | {r.get('method')} | {r.get('y')} | "
                f"{None if ae is None else ae*1e3:.6f} | {r.get('analog_pass')} |"
            )
    lines += [
        "",
        "## Temperature DC (vec 19, OPA189 ±15 V)",
        "",
        "| T (C) | y (V) | |err| (mV) | Vsum (V) | pass |",
        "| ---: | ---: | ---: | ---: | --- |",
    ]
    for r in report.get("temps") or []:
        if r.get("failed") and r.get("y") is None:
            lines.append(f"| {r.get('temp_c')} | FAIL {r.get('failure_reason')} | — | — | no |")
        else:
            ae = r.get("abs_err")
            lines.append(
                f"| {r.get('temp_c')} | {r.get('y')} | "
                f"{None if ae is None else ae*1e3:.6f} | {r.get('vsum')} | {r.get('analog_pass')} |"
            )
    lines += [
        "",
        "## Extra supplies (DC vec 19)",
        "",
        "| Candidate | ±V | y (V) | |err| (mV) | pass |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    for r in report.get("supply_dc") or []:
        if r.get("failed") and r.get("y") is None:
            lines.append(
                f"| {r.get('id')} | {r.get('vsupply')} | FAIL {r.get('failure_reason')} | — | no |"
            )
        else:
            ae = r.get("abs_err")
            lines.append(
                f"| {r.get('id')} | {r.get('vsupply')} | {r.get('y')} | "
                f"{None if ae is None else ae*1e3:.6f} | {r.get('analog_pass')} |"
            )
    lines += [
        "",
        report["conclusion"],
        "",
        "- Physical TIA validated: **NO** (macromodel ≠ PDK MOS ≠ silicon)",
        "- Matching: **UNRESOLVED**",
        "- Network F: **NOT TESTED**",
        "- Experiment 40 Decision C: **unchanged**",
        "- Experiment 45 Decision A: **unchanged** (isolated DC)",
        "",
    ]
    if report.get("next_experiment"):
        lines += ["## Next experiment", "", report["next_experiment"], ""]
    REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


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
    CIRCUIT_DIR.mkdir(parents=True, exist_ok=True)
    spiceinit_behavior(CIRCUIT_DIR, "ps")
    ng = find_ngspice()
    opa = cand(PRIMARY["id"])
    fabric = insert_macro(prepend_pdk_rc(w10, 27.0), opa, PRIMARY["vsupply"])

    print("DC repeat OPA189 ±15 vec 19", flush=True)
    dc = run_cell(ng, fabric, ident["hy_at_imax"], z0, CIRCUIT_DIR, "opa189_pm15_dc_v19", True)
    dc.update({"id": "OPA189", "vsupply": 15.0, "vector": 19})
    if dc.get("y") is not None:
        dc["delta_vs_exp45"] = dc["y"] - Y_EXP45_OPA189
        dc["repeat_ok"] = abs(dc["y"] - Y_EXP45_OPA189) <= REPEAT_ATOL_V

    print("Frozen F40 vectors", flush=True)
    vecs = []
    for vec in select_vectors(ident, w):
        rec = run_cell(
            ng, fabric, vec["hy"], vec["z"], CIRCUIT_DIR,
            f"opa189_pm15_dc_v{vec['vector']}", True,
        )
        rec.update({"id": "OPA189", "vsupply": 15.0, "vector": vec["vector"], "role": vec["role"]})
        vecs.append(rec)

    print("200 us TRAN vec 19", flush=True)
    trans = []
    tr = run_tran(ng, fabric, ident["hy_at_imax"], z0, "opa189_pm15_tran200u")
    tr.update({"id": "OPA189", "vsupply": 15.0})
    trans.append(tr)
    if tr.get("failed"):
        print("TRAN default failed; retry method=gear", flush=True)
        trg = run_tran(ng, fabric, ident["hy_at_imax"], z0, "opa189_pm15_tran200u_gear", method="gear")
        trg.update({"id": "OPA189", "vsupply": 15.0})
        trans.append(trg)

    print("Temperature DC", flush=True)
    temps = []
    for t in TEMPS:
        net_t = insert_macro(prepend_pdk_rc(w10, t), opa, 15.0)
        rec = run_cell(ng, net_t, ident["hy_at_imax"], z0, CIRCUIT_DIR, f"opa189_pm15_T{t:g}", True)
        rec.update({"id": "OPA189", "vsupply": 15.0, "temp_c": t, "vector": 19})
        temps.append(rec)

    print("Extra supplies", flush=True)
    extras = []
    for spec in ALSO:
        c = cand(spec["id"])
        net = insert_macro(prepend_pdk_rc(w10, 27.0), c, spec["vsupply"])
        rec = run_cell(
            ng, net, ident["hy_at_imax"], z0, CIRCUIT_DIR,
            f"{spec['id'].lower()}_pm{spec['vsupply']:g}_dc_v19", True,
        )
        rec.update({"id": spec["id"], "vsupply": spec["vsupply"], "vector": 19})
        extras.append(rec)

    report = {
        "experiment_id": "exp46",
        "kind": "Level 1 macromodel promotion (isolated W=10 o2)",
        "physical_tia_validated": False,
        "silicon": False,
        "encode": "Exp41 W=10 + Exp45 official tt R include",
        "identity": {"sim_target": "o2 / W2[1]", "z_o2": z0},
        "dc_repeat": dc,
        "vectors": vecs,
        "transients": trans,
        "temps": temps,
        "supply_dc": extras,
        "exp40_decision_unchanged": "C",
        "exp45_decision_unchanged": "A",
        "matching": "UNRESOLVED",
        "python_corrected": False,
    }
    decision, label, status = decide(report)
    report["decision"] = decision
    report["decision_label"] = label
    report["status"] = status
    report["conclusion"] = (
        f"Decision {decision} — {label}. "
        "OPA189 remains a vendor macromodel, not a SKY130 MOS TIA and not silicon. "
        "Network F was not tested. Matching remains unresolved."
    )
    if decision == "A":
        report["next_experiment"] = (
            "Experiment 47: multi-copy / representative insertion of the same "
            "OPA189 TIA, still on frozen Architecture A, without claiming Network F "
            "or silicon. In parallel, resistor matching remains UNRESOLVED."
        )
    else:
        report["next_experiment"] = (
            "Experiment 47: diagnose the failed promotion step (TRAN, temp, or "
            "vector) with solver-policy checks before any MOS resize."
        )
    write_reports(report)
    print(f"Experiment 46 Decision {decision} — {label}", flush=True)


if __name__ == "__main__":
    main()
