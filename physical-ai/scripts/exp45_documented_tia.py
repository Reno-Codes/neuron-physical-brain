"""Experiment 45: documented macromodel TIA vs Experiment 44 budgets.

Same frozen o2 / W=10 encode. No resistor fitting. No Python correction.
No MOS W/L. Vendor models are LEVEL 3 macromodels, not silicon.

Phase 1 (preserved): circuits/exp45_o2 .spiceinit used ngbehavior=hsa.
That blocked TI GWL PARAMS: parse. Not a circuit result.

Phase 2: circuits/exp45_o2/phase2 uses ngbehavior=ps + skywaterpdk.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from benchmark_scaling import detect_spice_failure
from compile_xor import PROJECT_ROOT, find_ngspice
from exp39_pdk_o2_cell import (
    ERROR_LIMIT,
    PDK_LIB,
    PDK_VERSION,
    TAG,
    discover_pdk,
    last,
    prepend_pdk,
    write_op_net,
)
from exp40_pdk_o2_cell import compile_o2_w2_1, prove_identity
from exp41_o2_residual import replace_resistors_w
from exp43_highgain_w10 import TIA_E, set_tia_gain
from offset_vg_search import OPA1656_PATH, OPA171_PATH, run_ngspice_ex
from test_robustness import extract_all

CIRCUIT_DIR = PROJECT_ROOT / "circuits" / "exp45_o2"
PHASE2_DIR = CIRCUIT_DIR / "phase2"
PHASE3_ALL = CIRCUIT_DIR / "phase3_all"
PHASE3_RC = CIRCUIT_DIR / "phase3_rc"
RESULTS_DIR = PROJECT_ROOT / "results"
REPORT_JSON = RESULTS_DIR / "exp45_documented_tia.json"
REPORT_MD = RESULTS_DIR / "exp45_documented_tia.md"
PHASE1_ARCHIVE = RESULTS_DIR / "exp45_phase1_parse_fail.json"
Z_O2 = 2.459489570880132
Y_EXP41_W10 = 2.458037812913
CONTROL_ATOL_V = 1.0e-6
PDK_TECH = PDK_LIB.parent

CANDIDATES = [
    {
        "id": "OPA189",
        "lib": PROJECT_ROOT / "models" / "vendor" / "ti" / "opa189" / "OPAx189.LIB",
        "subckt": "OPAx189",
        "kind": "LEVEL 3 TI GWL (unmodified vendor zip)",
        "supplies": (15.0, 5.0),
        "needs_ps": True,
        "doc_vos_V": -1.86843e-6,
        "vabsmax": 18.0,
    },
    {
        "id": "OPA192",
        "lib": PROJECT_ROOT / "models" / "vendor" / "ti" / "opa192" / "OPAx192.LIB",
        "subckt": "OPAx192",
        "kind": "LEVEL 3 TI GWL (unmodified vendor zip)",
        "supplies": (15.0,),
        "needs_ps": True,
        "doc_vos_V": -2.88e-6,
        "vabsmax": 18.0,
    },
    {
        "id": "OPA388",
        "lib": PROJECT_ROOT / "models" / "vendor" / "ti" / "opa388" / "OPAx388.LIB",
        "subckt": "OPAx388",
        "kind": "LEVEL 3 TI GWL (unmodified vendor zip); 5.5 V abs max",
        "supplies": (2.5,),
        "needs_ps": True,
        "doc_vos_V": -300.202e-9,
        "vabsmax": 2.75,
    },
    {
        "id": "OPA1656",
        "lib": OPA1656_PATH,
        "subckt": "OPA1656",
        "kind": "LEVEL 3 ngspice-tree GWL (Exp23/24 TIA history)",
        "supplies": (15.0,),
        "needs_ps": True,
        "doc_vos_V": 8.75e-6,
        "vabsmax": 18.0,
    },
    {
        "id": "OPA171",
        "lib": OPA171_PATH,
        "subckt": "OPA171",
        "kind": "LEVEL 3 ngspice-tree GWL (Exp23 isolated o2 fail)",
        "supplies": (15.0,),
        "needs_ps": True,
        "doc_vos_V": 214.023e-6,
        "vabsmax": 18.0,
    },
]


def spiceinit_hsa(dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    text = (
        "set ngbehavior=hsa\nset skywaterpdk\nset ng_nomodcheck\n"
        "set num_threads=4\noption klu\nunset interactive\n"
    )
    (dest / ".spiceinit").write_text(text, encoding="ascii")
    (dest / "spiceinit").write_text(text, encoding="ascii")


def spiceinit_ps(dest: Path) -> None:
    spiceinit_behavior(dest, "ps")


def spiceinit_behavior(dest: Path, behavior: str) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    text = (
        f"set ngbehavior={behavior}\nset skywaterpdk\nset ng_nomodcheck\n"
        "set num_threads=4\noption klu\nunset interactive\n"
    )
    (dest / ".spiceinit").write_text(text, encoding="ascii")
    (dest / "spiceinit").write_text(text, encoding="ascii")


def prepend_pdk_rc(netlist: str, temp_c: float = 27.0) -> str:
    """Official tt resistor cards without PSpice-breaking .lib <corner> syntax.

    Files are the same ones sky130.lib.spice tt uses for xhigh_po:
    sky130_fd_pr__model__linear.model.spice and the r+c typical cards.
    MOSFET corner includes are omitted because this cell has no MOS.
    """
    head = [
        "* Experiment 45 SKY130 tt R+C via official .include (no .lib section)",
        f"* PDK {PDK_TECH.as_posix()}",
        "* Frozen weights were not edited. SPICE is not Python-corrected.",
        ".param mc_mm_switch=0",
        ".param MC_MM_SWITCH=0",
        ".param mc_pr_switch=0",
        f'.include "{(PDK_TECH / "sky130_fd_pr__model__linear.model.spice").as_posix()}"',
        f'.include "{(PDK_TECH / "r+c" / "res_typical__cap_typical.spice").as_posix()}"',
        f'.include "{(PDK_TECH / "r+c" / "res_typical__cap_typical__lin.spice").as_posix()}"',
        f".temp {temp_c:.8g}",
        "",
    ]
    body = []
    skipped_temp = False
    for raw in netlist.splitlines():
        s = raw.strip().lower()
        if s.startswith(".temp") and not skipped_temp:
            skipped_temp = True
            continue
        if s.startswith(".lib "):
            continue
        body.append(raw)
    return "\n".join(head + body) + ("\n" if netlist.endswith("\n") else "")


def first_error(text: str) -> str:
    for raw in text.splitlines():
        s = raw.strip()
        if s.lower().startswith("error:"):
            return s[:240]
    return ""


def insert_macro(net: str, cand: dict, vsupply: float) -> str:
    lib = Path(cand["lib"]).as_posix()
    n = 0
    out = []
    inserted = False
    for raw in net.splitlines():
        s = raw.strip()
        if (not inserted) and s and not s.startswith("*") and not s.startswith("."):
            out += [
                f"* Experiment 45 phase2 {cand['id']} TIA · {cand['kind']}",
                f".include \"{lib}\"",
                f"Vddtia vddtia 0 DC {vsupply:.8g}",
                f"Vsstia vsstia 0 DC {-vsupply:.8g}",
            ]
            inserted = True
        if TIA_E.match(s):
            parts = s.split()
            drv, vg = parts[1], parts[4]
            out.append(f"V{TAG}ib {vg} {TAG}inn DC 0")
            out.append(
                f"X{TAG}tia 0 {TAG}inn vddtia vsstia {drv} {cand['subckt']}"
            )
            out.append(f"C{TAG}load {drv} 0 1p")
            n += 1
            continue
        out.append(raw)
    if n != 1:
        raise RuntimeError(f"expected one En1tia, found {n}")
    return "\n".join(out) + "\n"


def parse_op(text: str, z_ref: float | None) -> dict:
    rec: dict = {}
    y = last(extract_all(text, f"v({TAG}lin)"))
    vsum = last(extract_all(text, f"v({TAG}p)"))
    rec.update({"y": y, "vsum": vsum})
    if y is None:
        rec.update({"failed": True, "failure_reason": "missing vlin"})
        return rec
    if z_ref is not None:
        rec["err"] = y - float(z_ref)
        rec["abs_err"] = abs(y - float(z_ref))
        rec["analog_pass"] = abs(y - float(z_ref)) <= ERROR_LIMIT
        rec["z_ref"] = float(z_ref)
    rec["a_eff"] = abs(y / vsum) if vsum not in (None, 0.0) else None
    rec["i_in"] = last(extract_all(text, f"i(v{TAG}ib)"))
    rec["i_dd"] = last(extract_all(text, "i(vddtia)"))
    rec["failed"] = False
    rec["failure_reason"] = None
    return rec


def run_cir(ng, path: Path, pspice: bool, timeout: float = 360.0):
    result = run_ngspice_ex(ng, path, timeout=timeout, pspice=pspice)
    text = f"{result.stdout or ''}\n{result.stderr or ''}"
    fail = detect_spice_failure(result)
    return result, text, fail


def run_cell(ng, net: str, hy, z_ref, dest: Path, name: str, pspice: bool) -> dict:
    path = dest / f"{name}.cir"
    tagged = net.replace(
        "* Experiment 39 SKY130 isolated frozen o2 cell",
        "* Experiment 45 documented macromodel TIA · not silicon",
    )
    write_op_net(path, tagged, hy, extra_prints=[f"i(V{TAG}ib)", "i(Vddtia)"])
    _r, text, fail = run_cir(ng, path, pspice)
    rec = {
        "name": name,
        "path": str(path),
        "pspice": pspice,
        "phase": 2,
        "python_corrected": False,
        "log_error": first_error(text),
    }
    if fail:
        rec.update(
            {
                "failed": True,
                "failure_reason": fail,
                "log_tail": text[-700:],
                "z_ref": float(z_ref),
            }
        )
        print(f"  {name} FAIL {fail} {rec['log_error']}", flush=True)
        return rec
    rec.update(parse_op(text, z_ref))
    if rec.get("y") is None:
        rec["log_tail"] = text[-700:]
        print(f"  {name} missing vlin {rec.get('log_error')}", flush=True)
        return rec
    print(
        f"  {name} y={rec['y']} |err|={rec.get('abs_err')} pass={rec.get('analog_pass')} "
        f"vsum={rec.get('vsum')} a_eff={rec.get('a_eff')}",
        flush=True,
    )
    return rec


def write_smoke(dest: Path, cand: dict, vsupply: float, with_pdk: bool) -> Path:
    lib = Path(cand["lib"]).as_posix()
    lines = [
        f"* Experiment 45 smoke {cand['id']} follower - not the o2 cell",
        f".include \"{lib}\"",
    ]
    if with_pdk:
        lines.append(f'.lib "{PDK_LIB.as_posix()}" tt')
        lines.append(".temp 27")
    lines += [
        f"Vdd vdd 0 DC {vsupply:.8g}",
        f"Vss vss 0 DC {-vsupply:.8g}",
        "Vin in 0 DC 1",
        f"Xamp in out vdd vss out {cand['subckt']}",
        "Cload out 0 1p",
        ".control",
        "set numdgt=12",
        "op",
        "print v(out)",
        "print v(in)",
        ".endc",
        ".end",
        "",
    ]
    tag = "pdk" if with_pdk else "bare"
    path = dest / f"smoke_{cand['id'].lower()}_{tag}_pm{vsupply:g}.cir"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def run_smoke(ng, dest: Path, cand: dict, vsupply: float, with_pdk: bool) -> dict:
    path = write_smoke(dest, cand, vsupply, with_pdk)
    _r, text, fail = run_cir(ng, path, pspice=True)
    rec = {
        "name": path.stem,
        "path": str(path),
        "id": cand["id"],
        "kind": "smoke_follower",
        "with_pdk_lib": with_pdk,
        "vsupply": vsupply,
        "pspice": True,
        "phase": 2,
        "python_corrected": False,
        "log_error": first_error(text),
    }
    if fail:
        rec.update({"failed": True, "failure_reason": fail, "log_tail": text[-700:]})
        print(f"  {path.stem} FAIL {fail} {rec['log_error']}", flush=True)
        return rec
    y = last(extract_all(text, "v(out)"))
    vin = last(extract_all(text, "v(in)"))
    rec.update({"y": y, "vin": vin, "failed": y is None})
    if y is None:
        rec["failure_reason"] = "missing v(out)"
        rec["log_tail"] = text[-700:]
        print(f"  {path.stem} missing v(out)", flush=True)
        return rec
    rec["abs_err"] = abs(y - 1.0)
    rec["follower_ok"] = abs(y - 1.0) < 1e-3
    print(f"  {path.stem} vout={y} |vout-1|={rec['abs_err']}", flush=True)
    return rec


def archive_phase1() -> list:
    if not REPORT_JSON.is_file():
        return []
    prev = json.loads(REPORT_JSON.read_text(encoding="utf-8"))
    if not PHASE1_ARCHIVE.is_file():
        PHASE1_ARCHIVE.write_text(json.dumps(prev, indent=2), encoding="utf-8")
    rows = prev.get("rows") or []
    for r in rows:
        r.setdefault("phase", 1)
        r.setdefault("mechanism", "spiceinit ngbehavior=hsa blocked PARAMS: parse")
    return rows


def decide(phase2_cells: list, smokes: list) -> tuple[str, str, str]:
    any_pass = any(r.get("analog_pass") for r in phase2_cells)
    any_valid = any(r.get("y") is not None and not r.get("failed") for r in phase2_cells)
    smoke_ok = any(s.get("follower_ok") for s in smokes)
    if any_pass:
        return (
            "A",
            "DOCUMENTED MACROMODEL MEETS 1 mV ON W=10 o2",
            "PARTIALLY VALIDATED",
        )
    if any_valid:
        return (
            "B",
            "MACROMODEL CONVERGED BUT MISSED THE 1 mV BAR",
            "CONTRADICTED",
        )
    if smoke_ok:
        return (
            "D",
            "MACROMODEL PARSES ISOLATED BUT LOADED W=10 CELL DID NOT CONVERGE",
            "NUMERICAL ISSUE",
        )
    return (
        "D",
        "MACROMODEL DID NOT YIELD A USABLE OP",
        "NUMERICAL ISSUE",
    )


def write_reports(report: dict) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    lines = [
        "# Experiment 45 — documented macromodel TIA on W=10 o2",
        "",
        "Experiments 1–44 were not modified. Frozen weights unchanged.",
        "No MOS W/L. No Python correction. Not silicon. Not a PDK MOS TIA.",
        "",
        f"**Status: {report['status']}**",
        f"**Decision {report['decision']} — {report['decision_label']}**",
        "",
        "## Phase 1 — parser conflict (preserved)",
        "",
        "First attempt wrote `set ngbehavior=hsa` into `circuits/exp45_o2/.spiceinit`.",
        "That overrode `ngspice -D ngbehavior=ps`. TI GWL `PARAMS:` lines were",
        "parsed as unknown subcircuit names. No operating point was obtained.",
        "This is a numerical/parser issue, not a measured analog error.",
        "",
        "| Candidate | ±V | pspice | result |",
        "| --- | ---: | --- | --- |",
    ]
    for r in report.get("phase1_rows") or []:
        lines.append(
            f"| {r.get('id')} | {r.get('vsupply')} | {r.get('pspice')} | "
            f"FAIL {r.get('failure_reason')} |"
        )
    lines += [
        "",
        "## Phase 2 — `ngbehavior=ps` + `skywaterpdk`",
        "",
        "Working directory: `circuits/exp45_o2/phase2`. Home `.spiceinit` was not edited.",
        "",
        "### Phase 2 smoke (open-loop, not a follower)",
        "",
        "First smoke grounded IN+ and drove IN− to 1 V, so the output is not",
        "required to track 1 V. It only proved `ngbehavior=ps` can parse OPAx189.",
        "",
        "| Smoke | ±V | PDK .lib | v(out) | |vout−1| | ok |",
        "| --- | ---: | --- | ---: | ---: | --- |",
    ]
    for s in report.get("smokes") or []:
        if s.get("failed") and s.get("y") is None:
            lines.append(
                f"| {s.get('id')} | {s.get('vsupply')} | {s.get('with_pdk_lib')} | "
                f"FAIL {s.get('failure_reason')} | — | no |"
            )
        else:
            lines.append(
                f"| {s.get('id')} | {s.get('vsupply')} | {s.get('with_pdk_lib')} | "
                f"{s.get('y')} | {None if s.get('abs_err') is None else s['abs_err']*1e3:.6f} mV | "
                f"{s.get('follower_ok')} |"
            )
    lines += [
        "",
        "### Loaded W=10 catalog o2 (vec 19, z = +2.459489570880132 V)",
        "",
        "| Candidate | ±V | y (V) | |err| (mV) | Vsum (V) | a_eff | pass |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for r in report.get("phase2_cells") or []:
        if r.get("failed") and r.get("y") is None:
            lines.append(
                f"| {r.get('id')} | {r.get('vsupply')} | FAIL {r.get('failure_reason')} | "
                f"— | — | — | no |"
            )
        else:
            ae = r.get("abs_err")
            lines.append(
                f"| {r.get('id')} | {r.get('vsupply')} | {r.get('y')} | "
                f"{None if ae is None else ae * 1e3:.6f} | {r.get('vsum')} | "
                f"{r.get('a_eff')} | {r.get('analog_pass')} |"
            )
    lines += [
        "",
        report["conclusion"],
        "",
        "- Physical TIA validated: **NO** (macromodel ≠ PDK MOS ≠ silicon)",
        "- Matching: **UNRESOLVED**",
        "- Experiment 40 Decision C: **unchanged**",
        "- Experiment 43 Decision A: **unchanged** (behavioral feasibility)",
        "- Experiment 44 Decision R: **unchanged** (requirements)",
        "",
    ]
    p3 = report.get("phase3")
    if p3:
        lines += [
            "",
            "## Phase 3 — mixed parser / official R include",
            "",
            f"Include mode: `{p3.get('include_mode')}`.",
            "",
        ]
        ctrl = p3.get("control") or {}
        lines += [
            "### Behavioral W=10 control (A=1e5 vs Experiment 41 y)",
            "",
            f"- y = {ctrl.get('y')}",
            f"- Δ vs Exp41 = {ctrl.get('delta_vs_exp41')}",
            f"- fabric_match (≤1 µV) = {ctrl.get('fabric_match')}",
            "",
            "### Phase 3 loaded cells",
            "",
            "| Candidate | ±V | include | y (V) | |err| (mV) | Vsum (V) | pass |",
            "| --- | ---: | --- | ---: | ---: | ---: | --- |",
        ]
        for r in p3.get("cells") or []:
            if r.get("failed") and r.get("y") is None:
                lines.append(
                    f"| {r.get('id')} | {r.get('vsupply')} | {r.get('include')} | "
                    f"FAIL {r.get('failure_reason')} | — | — | no |"
                )
            else:
                ae = r.get("abs_err")
                lines.append(
                    f"| {r.get('id')} | {r.get('vsupply')} | {r.get('include')} | "
                    f"{r.get('y')} | {None if ae is None else ae * 1e3:.6f} | "
                    f"{r.get('vsum')} | {r.get('analog_pass')} |"
                )
    if report.get("next_experiment"):
        lines += ["", "## Next experiment", "", report["next_experiment"], ""]
    REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main_phase12(ng, w10, hy, z0) -> None:
    phase1_rows = archive_phase1()
    spiceinit_hsa(CIRCUIT_DIR)
    spiceinit_ps(PHASE2_DIR)
    ng = find_ngspice()

    smokes = []
    opa189 = next(c for c in CANDIDATES if c["id"] == "OPA189")
    print("Phase 2 smoke OPA189 follower", flush=True)
    smokes.append(run_smoke(ng, PHASE2_DIR, opa189, 15.0, with_pdk=False))
    if smokes[-1].get("follower_ok"):
        smokes.append(run_smoke(ng, PHASE2_DIR, opa189, 15.0, with_pdk=True))

    phase2_cells = []
    pdk_w10 = prepend_pdk(w10, "tt", 27.0)
    for cand in CANDIDATES:
        if not Path(cand["lib"]).is_file():
            phase2_cells.append(
                {
                    "id": cand["id"],
                    "failed": True,
                    "failure_reason": "lib missing",
                    "phase": 2,
                }
            )
            continue
        for vs in cand["supplies"]:
            if vs > cand["vabsmax"]:
                continue
            net = insert_macro(pdk_w10, cand, vs)
            name = f"{cand['id'].lower()}_w10_pm{vs:g}_ps"
            rec = run_cell(ng, net, hy, z0, PHASE2_DIR, name, pspice=True)
            rec.update(
                {
                    "id": cand["id"],
                    "vsupply": vs,
                    "kind": cand["kind"],
                    "doc_vos_V": cand["doc_vos_V"],
                }
            )
            phase2_cells.append(rec)
            if rec.get("y") is not None:
                break

    decision, label, status = decide(phase2_cells, smokes)
    any_pass = any(r.get("analog_pass") for r in phase2_cells)
    if any_pass:
        nxt = (
            "Experiment 46: promote the passing macromodel through the load / "
            "200 µs / temperature / multi-vector ladder on the same W=10 o2 "
            "cell. Still not silicon. Do not skip to Network F."
        )
    elif any(r.get("y") is not None and not r.get("failed") for r in phase2_cells):
        nxt = (
            "Experiment 46: H4 summing-node servo / auto-zero on the same "
            "W=10 SKY130 o2 cell (no GWL required). Documented macromodel "
            "Vos floors that miss 1 mV are a Level-1 bound, not a MOS search."
        )
    else:
        nxt = (
            "Experiment 46: H4 summing-node servo / auto-zero on the same "
            "W=10 SKY130 o2 cell using LEVEL 2 primitives already shown on "
            "ideal-R (Exp24/26). Do not transistor-resize the Exp39 Miller "
            "as the first move."
        )

    report = {
        "experiment_id": "exp45",
        "kind": "Level 1 documented macromodel search",
        "status": status,
        "decision": decision,
        "decision_label": label,
        "physical_tia_validated": False,
        "silicon": False,
        "encode": "Exp41 W=10, not fitted",
        "identity": {"sim_target": "o2 / W2[1]", "z_o2": z0},
        "phase1_mechanism": (
            "circuits/exp45_o2 .spiceinit set ngbehavior=hsa and overrode "
            "-D ngbehavior=ps; TI GWL PARAMS: parsed as unknown subckts"
        ),
        "phase1_rows": phase1_rows,
        "smokes": smokes,
        "phase2_cells": phase2_cells,
        "rows": phase2_cells,
        "exp40_decision_unchanged": "C",
        "matching": "UNRESOLVED",
        "next_experiment": nxt,
        "conclusion": (
            f"Decision {decision} — {label}. "
            "Phase 1 is a parser failure, not an analog measurement. "
            "Phase 2 is the scientific attempt. "
            "This is a vendor macromodel result, not a PDK transistor TIA "
            "and not silicon. PHYSICAL TIA VALIDATED remains no unless a "
            "loaded W=10 o2 cell actually passed."
        ),
    }
    write_reports(report)
    print(f"Experiment 45 Decision {decision} — {label}", flush=True)


def run_phase3(ng, w10: str, hy, z0: float, prev: dict) -> dict:
    """Resolve .lib-tt vs PARAMS conflict. Do not overwrite phase 1/2 rows."""
    phase3 = {"probes": [], "control": None, "cells": [], "include_mode": None}

    print("Phase 3a: ngbehavior=all + original .lib tt + OPA189", flush=True)
    spiceinit_behavior(PHASE3_ALL, "all")
    opa189 = next(c for c in CANDIDATES if c["id"] == "OPA189")
    net_all = insert_macro(prepend_pdk(w10, "tt", 27.0), opa189, 15.0)
    rec_all = run_cell(ng, net_all, hy, z0, PHASE3_ALL, "opa189_w10_pm15_all", pspice=True)
    rec_all.update({"id": "OPA189", "vsupply": 15.0, "phase": 3, "include": "lib_tt"})
    phase3["probes"].append(rec_all)

    print("Phase 3b: behavioral W=10 control on official R .include", flush=True)
    spiceinit_behavior(PHASE3_RC, "ps")
    net_ctrl = prepend_pdk_rc(set_tia_gain(w10, 1.0e5))
    rec_ctrl = run_cell(ng, net_ctrl, hy, z0, PHASE3_RC, "control_w10_A1e5_rc", pspice=True)
    rec_ctrl.update(
        {
            "id": "behavioral_A1e5",
            "phase": 3,
            "include": "official_r_include",
            "y_exp41": Y_EXP41_W10,
        }
    )
    if rec_ctrl.get("y") is not None:
        rec_ctrl["delta_vs_exp41"] = rec_ctrl["y"] - Y_EXP41_W10
        rec_ctrl["fabric_match"] = abs(rec_ctrl["y"] - Y_EXP41_W10) <= CONTROL_ATOL_V
    phase3["control"] = rec_ctrl
    print(
        f"  control fabric_match={rec_ctrl.get('fabric_match')} "
        f"delta={rec_ctrl.get('delta_vs_exp41')}",
        flush=True,
    )

    if rec_all.get("y") is not None:
        phase3["include_mode"] = "lib_tt_ngbehavior_all"
        phase3["cells"].append(rec_all)
        fabric = prepend_pdk(w10, "tt", 27.0)
        dest = PHASE3_ALL
        beh = "all"
    elif rec_ctrl.get("fabric_match"):
        phase3["include_mode"] = "official_r_include_ps"
        fabric = prepend_pdk_rc(w10)
        dest = PHASE3_RC
        beh = "ps"
    else:
        print("Phase 3: trying OPA189 on R-include even if control missed", flush=True)
        phase3["include_mode"] = "official_r_include_unverified"
        fabric = prepend_pdk_rc(w10)
        dest = PHASE3_RC
        beh = "ps"

    spiceinit_behavior(dest, beh)
    for cand in CANDIDATES:
        if any(r.get("id") == cand["id"] and r.get("y") is not None for r in phase3["cells"]):
            continue
        if not Path(cand["lib"]).is_file():
            continue
        for vs in cand["supplies"]:
            if vs > cand["vabsmax"]:
                continue
            net = insert_macro(fabric, cand, vs)
            name = f"{cand['id'].lower()}_w10_pm{vs:g}_p3"
            rec = run_cell(ng, net, hy, z0, dest, name, pspice=True)
            rec.update(
                {
                    "id": cand["id"],
                    "vsupply": vs,
                    "kind": cand["kind"],
                    "doc_vos_V": cand["doc_vos_V"],
                    "phase": 3,
                    "include": phase3["include_mode"],
                }
            )
            phase3["cells"].append(rec)
            if rec.get("y") is not None:
                break

    prev["phase3"] = phase3
    cells = phase3["cells"]
    decision, label, status = decide(cells, prev.get("smokes") or [])
    prev.update(
        {
            "status": status,
            "decision": decision,
            "decision_label": label,
            "rows": cells,
            "next_experiment": (
                "Experiment 46: promote the passing macromodel on this W=10 cell "
                "(200 us / temp / extra frozen vectors). Still not silicon."
                if any(r.get("analog_pass") for r in cells)
                else (
                    "Experiment 46: H4 summing-node servo / auto-zero on the same "
                    "W=10 SKY130 o2 cell. Level-1 GWL is either unhostable with "
                    "SKY130 .lib syntax or misses the 1 mV bar."
                )
            ),
            "conclusion": (
                f"Decision {decision} — {label}. "
                "Phase 1: hsa blocked PARAMS. Phase 2: ps parsed OPA189 but "
                ".lib tt was read as include-file 'tt'. Phase 3 tested "
                f"{phase3['include_mode']}. PHYSICAL TIA VALIDATED remains no "
                "unless a loaded W=10 o2 cell analog-passed. Not silicon."
            ),
        }
    )
    return prev


def main() -> None:
    import sys

    phase3_only = "--phase3" in sys.argv
    ident = prove_identity()
    w = ident.pop("weights")
    pdk = discover_pdk()
    if pdk.get("ciel_current") != PDK_VERSION:
        raise SystemExit("BLOCKED PDK")
    net0, cat, _ = compile_o2_w2_1(w)
    hy = ident["hy_at_imax"]
    z0 = float(ident["z_at_imax"])
    if not math.isclose(z0, Z_O2, rel_tol=0, abs_tol=1e-12):
        raise SystemExit("BLOCKED z")
    w10, _ = replace_resistors_w(net0, cat, 10.0)
    ng = find_ngspice()

    if phase3_only and REPORT_JSON.is_file():
        prev = json.loads(REPORT_JSON.read_text(encoding="utf-8"))
        report = run_phase3(ng, w10, hy, z0, prev)
        write_reports(report)
        print(
            f"Experiment 45 Decision {report['decision']} — {report['decision_label']}",
            flush=True,
        )
        return

    main_phase12(ng, w10, hy, z0)


if __name__ == "__main__":
    main()
