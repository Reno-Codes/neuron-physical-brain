"""Experiment 30: Architecture A invert primitive helpers.

The compiled invert is a closed-loop gain −1 stage:

    R1 from src to mid, R2 from dest to mid, amp from 0 to dest sensing mid.
    invert_r2(R1, A) makes Vdest = −Vsrc for an ideal VCVS of gain A.

Frozen weights are not edited. SPICE is not Python-corrected.
Teaching-card MOS W/L come from Experiment 26 (CMOS-OP1), not a PDK.
"""

from __future__ import annotations

import math
import os
import re
from collections import defaultdict
from pathlib import Path

from compile_xor import PROJECT_ROOT
from copy_minimizing import R_INV, invert_r2
from device_neuron import MosParams, mos_include_block
from offset_vg_search import OPA1656_PATH
from virtual_ground_requirements import INVERT_PINNED


CIRCUIT_DIR = PROJECT_ROOT / "circuits" / "exp30_physical_invert_matching"
RESULTS_DIR = PROJECT_ROOT / "results"
ERROR_LIMIT = 1.0e-3
AMP_A = 1.0e5

E_INV = re.compile(
    r"^(E)(inv\S+)amp\s+(\S+)\s+0\s+0\s+(\S+)\s+(\S+)\s*$",
    re.IGNORECASE,
)
R_INV_LINE = re.compile(
    r"^(R)(inv\S+)i([ab])\s+(\S+)\s+(\S+)\s+(\S+)\s*$",
    re.IGNORECASE,
)


def classify_stem(stem: str) -> str:
    s = stem.lower()
    if s == "invref" or s.startswith("invref"):
        return "vref"
    if s.startswith("invh"):
        return "hidden"
    if re.match(r"inv\d+$", s):
        return "input"
    return "other"


def extract_inverts(netlist: str) -> list[dict]:
    """Parse compiled invert stages. 98 invert resistors = 49 amps on Network F."""
    amps = {}
    for raw in netlist.splitlines():
        m = E_INV.match(raw.strip())
        if not m:
            continue
        stem = m.group(2)
        amps[stem] = {
            "stem": stem,
            "kind": classify_stem(stem),
            "dest": m.group(3),
            "mid": m.group(4),
            "amp_gain": float(m.group(5)),
            "src": None,
            "r1": None,
            "r2": None,
            "r1_name": None,
            "r2_name": None,
        }
    for raw in netlist.splitlines():
        m = R_INV_LINE.match(raw.strip())
        if not m:
            continue
        stem, which = m.group(2), m.group(3).lower()
        if stem not in amps:
            continue
        node_a, node_b, r = m.group(4), m.group(5), float(m.group(6))
        if which == "a":
            amps[stem]["r1"] = r
            amps[stem]["r1_name"] = f"R{stem}ia"
            mid = amps[stem]["mid"]
            amps[stem]["src"] = node_a if node_b == mid else node_b
        else:
            amps[stem]["r2"] = r
            amps[stem]["r2_name"] = f"R{stem}ib"
    out = []
    for row in amps.values():
        r1, r2 = row.get("r1"), row.get("r2")
        row["ratio"] = None if not r1 or not r2 else r2 / r1
        out.append(row)
    out.sort(key=lambda r: (r["kind"], r["stem"]))
    return out


def invert_summary(stages: list[dict]) -> dict:
    by = defaultdict(int)
    for s in stages:
        by[s["kind"]] += 1
    r1s = [s["r1"] for s in stages if s.get("r1")]
    r2s = [s["r2"] for s in stages if s.get("r2")]
    ratios = [s["ratio"] for s in stages if s.get("ratio")]
    return {
        "n_invert_amps": len(stages),
        "n_invert_resistors": 2 * len(stages),
        "by_kind": dict(by),
        "r1_ohm": float(r1s[0]) if r1s else None,
        "r2_ohm_mean": float(sum(r2s) / len(r2s)) if r2s else None,
        "closed_loop_gain_target": -1.0,
        "ratio_r2_over_r1_mean": float(sum(ratios) / len(ratios)) if ratios else None,
        "note": (
            "Input and Vref inverts copy stimulus polarity. Hidden inverts "
            "copy a computed ReLU voltage. Those are different physical jobs."
        ),
    }


def node_load_siemens(netlist: str, node: str) -> float:
    g = 0.0
    for raw in netlist.splitlines():
        parts = raw.split()
        if len(parts) < 4 or not parts[0].startswith("R"):
            continue
        if parts[1] == node or parts[2] == node:
            try:
                g += 1.0 / float(parts[3])
            except ValueError:
                continue
    return g


def attach_loads(netlist: str, stages: list[dict]) -> list[dict]:
    for s in stages:
        dest = s.get("dest")
        s["g_load_S"] = node_load_siemens(netlist, dest) if dest else None
        s["r_load_ohm"] = None if not s.get("g_load_S") else 1.0 / s["g_load_S"]
    return stages


def force_r1_equals_r2(netlist: str, stages: list[dict]) -> str:
    """Remove finite-A R2 compensation so the pair is a physical 1:1 ratio."""
    out = []
    r2_names = {s["r2_name"]: s["r1"] for s in stages if s.get("r2_name") and s.get("r1")}
    for raw in netlist.splitlines():
        parts = raw.split()
        if len(parts) >= 4 and parts[0] in r2_names:
            out.append(f"{parts[0]} {parts[1]} {parts[2]} {r2_names[parts[0]]:.15g}")
        else:
            out.append(raw)
    ending = "\n" if netlist.endswith("\n") else ""
    return "\n".join(out) + ending


def scale_invert_r2(netlist: str, stages: list[dict], rel: float) -> str:
    """Systematic invert closed-loop ratio error: R2 ← R2*(1+rel)."""
    names = {s["r2_name"]: float(s["r2"]) * (1.0 + float(rel)) for s in stages if s.get("r2_name") and s.get("r2")}
    out = []
    for raw in netlist.splitlines():
        parts = raw.split()
        if len(parts) >= 4 and parts[0] in names:
            out.append(f"{parts[0]} {parts[1]} {parts[2]} {names[parts[0]]:.15g}")
        else:
            out.append(raw)
    ending = "\n" if netlist.endswith("\n") else ""
    return "\n".join(out) + ending


def set_invert_vcvs_gain(netlist: str, gain: float) -> str:
    out = []
    for raw in netlist.splitlines():
        m = E_INV.match(raw.strip())
        if m:
            out.append(f"E{m.group(2)}amp {m.group(3)} 0 0 {m.group(4)} {float(gain):.15g}")
        else:
            out.append(raw)
    ending = "\n" if netlist.endswith("\n") else ""
    return "\n".join(out) + ending


def set_invert_vos(netlist: str, vos: float) -> str:
    """Replace invert VCVS with B-source: V = A*(Vos − v(mid))."""
    out = []
    for raw in netlist.splitlines():
        m = E_INV.match(raw.strip())
        if m:
            stem, dest, mid, a = m.group(2), m.group(3), m.group(4), float(m.group(5))
            out.append(
                f"B{stem}amp {dest} 0 V = -({a:.15g})*(v({mid})-({float(vos):.15g}))"
            )
        else:
            out.append(raw)
    ending = "\n" if netlist.endswith("\n") else ""
    return "\n".join(out) + ending


def _ensure_supplies(lines: list[str], vsupply: float, have: set[str]) -> list[str]:
    extra = []
    if "vdd" not in have:
        extra.append(f"Vdd vdd 0 DC {vsupply:.15g}")
        have.add("vdd")
    if "vss" not in have:
        extra.append(f"Vss vss 0 DC {-vsupply:.15g}")
        have.add("vss")
    return extra


def replace_inverts(
    netlist: str,
    stages: list[dict],
    mode: str,
    amp_gain: float = 1e5,
    vos: float = 0.0,
    mos: MosParams | None = None,
    invert_dw: float = 0.0026,
    servo: bool = False,
) -> str:
    """Replace selected invert E-sources. TIA E-sources stay."""
    stems = {s["stem"] for s in stages}
    by_stem = {s["stem"]: s for s in stages}
    have = {p.split()[0].lower() for p in netlist.splitlines() if p.split()}
    preamble: list[str] = []
    if mode in {"miller", "miller_servo"}:
        preamble.extend(mos_include_block())
        vs = 2.5 if mos is None else float(mos.vsupply)
        preamble.extend(_ensure_supplies([], vs, have))
        mos = mos or MosParams(name="inv")
    if mode == "opa1656":
        preamble.append(f'.include "{OPA1656_PATH.resolve().as_posix()}"')
        preamble.extend(_ensure_supplies([], 15.0, have))
        preamble.append("* 1 pF on each OPA invert so GWL OP exists; not datasheet CL")
    if mode == "limit":
        lo, hi = -15.0, 15.0
        preamble.append(
            f".model liminv limit(gain={float(amp_gain):.15g} "
            f"in_offset={float(vos):.15g} out_lower_limit={lo:.15g} "
            f"out_upper_limit={hi:.15g} fraction=false limit_range=0.05)"
        )

    out: list[str] = []
    inserted = False
    for raw in netlist.splitlines():
        s = raw.strip()
        if (not inserted) and s and not s.startswith("*") and preamble:
            out.extend(preamble)
            out.append("")
            inserted = True
        m = E_INV.match(s)
        if m and m.group(2) in stems:
            st = by_stem[m.group(2)]
            out.extend(_emit_replacement(st, mode, amp_gain, vos, mos, invert_dw, servo))
            continue
        if mode == "stimulus_polarity" and s:
            rm = R_INV_LINE.match(s)
            if rm and rm.group(2) in stems and classify_stem(rm.group(2)) in {"input", "vref"}:
                out.append(f"* stimulus polarity: removed {s}")
                continue
        out.append(raw)
    ending = "\n" if netlist.endswith("\n") else ""
    return "\n".join(out) + ending


def _emit_replacement(st, mode, amp_gain, vos, mos, invert_dw, servo) -> list[str]:
    stem, dest, mid, src = st["stem"], st["dest"], st["mid"], st.get("src") or "0"
    kind = st["kind"]
    if mode == "stimulus_polarity":
        if kind not in {"input", "vref"}:
            return [f"E{stem}amp {dest} 0 0 {mid} {amp_gain:.15g}"]
        return [
            f"* stimulus polarity pair: V({dest}) = -V({src}). Not a neuron invert.",
            f"E{stem}pol {dest} 0 {src} 0 -1",
        ]
    if mode == "passive_divider":
        return [
            f"* PASSIVE FAIL: grounded divider cannot invert about 0.",
            f"* left R1/R2 in place; amp removed so dest is a resistive tap.",
            f"R{stem}gnd {dest} 0 1e12",
        ]
    if mode == "limit":
        return [
            f"* XSPICE limit invert {stem} (LEVEL 2). Rails ±15 V.",
            f"A{stem}inv %vd(0 {mid}) {dest} liminv",
        ]
    if mode == "opa1656":
        return [
            f"* OPA1656 invert {stem} (LEVEL 3 macromodel, include not copy).",
            f"X{stem}inv 0 {mid} vdd vss {dest} OPA1656",
            f"C{stem}cl {dest} 0 1p",
        ]
    if mode in {"miller", "miller_servo"}:
        p = mos or MosParams(name="inv")
        dw = invert_dw
        use_servo = mode == "miller_servo" or servo
        lines = [f"* teaching-card miller invert {stem}. ±{p.vsupply} V. Not a PDK."]
        inn = mid
        inp = "0"
        if use_servo:
            lines += [
                f"R{stem}isi {mid} {stem}sint {p.servo_rin:.15g}",
                f"C{stem}iint {stem}sint {stem}srv {p.servo_c:.15g}",
                f"R{stem}ileak {stem}sint {stem}srv {p.servo_rleak:.15g}",
                (
                    f"X{stem}isrv 0 {stem}sint {stem}srv vdd vss miller_tia "
                    f"MD={max(p.servo_m, 2)} MT={max(p.servo_m, 2)} "
                    f"MO={max(p.servo_m * 4, 4)} "
                    f"CC={p.cc_f:.15g} IBIAS={p.servo_ibias:.15g} DW={dw:.15g}"
                ),
                f".ic v({stem}srv)=0",
            ]
            inp = f"{stem}srv"
        lines.append(
            f"X{stem}inv {inp} {inn} {dest} vdd vss miller_tia "
            f"MD={p.m_diff} MT={p.m_tail} MO={p.m_out} "
            f"CC={p.cc_f:.15g} IBIAS={p.ibias:.15g} DW={dw:.15g} L1={p.l1_m}u"
        )
        return lines
    return [f"E{stem}amp {dest} 0 0 {mid} {amp_gain:.15g}"]


def isolated_invert_netlist(
    mode: str,
    vin: float,
    r1: float,
    r2: float,
    r_load: float,
    amp_gain: float = 1e5,
    vos: float = 0.0,
    mos: MosParams | None = None,
    invert_dw: float = 0.0026,
    servo: bool = False,
    t_hold: float | None = None,
    temp_c: float | None = None,
) -> str:
    """One invert with the compiled R1/R2 and a resistive load from the fabric."""
    st = {
        "stem": "invb",
        "kind": "bench",
        "dest": "out",
        "mid": "mid",
        "src": "in",
        "r1": r1,
        "r2": r2,
    }
    lines = [
        f"* Experiment 30 isolated invert bench mode={mode}",
        f"* Vin={vin:g} R1={r1:g} R2={r2:g} Rload={r_load:g} A={amp_gain:g}",
        "* Frozen-map invert identity: Vout should equal -Vin.",
        f"Vin in 0 DC {vin:.15g}",
        f"Rinvbia in mid {r1:.15g}",
        f"Rinvbib out mid {r2:.15g}",
        f"Rload out 0 {r_load:.15g}",
    ]
    if temp_c is not None:
        lines.append(f".temp {float(temp_c):.15g}")
    if mode == "vcvs":
        if vos:
            lines.append(f"Binvbamp out 0 V = -({amp_gain:.15g})*(v(mid)-({vos:.15g}))")
        else:
            lines.append(f"Einvbamp out 0 0 mid {amp_gain:.15g}")
        body = "\n".join(lines)
    elif mode == "passive_divider":
        lines += [
            "* no amplifier — dest is the R1/R2 tap to ground through Rload",
        ]
        body = "\n".join(lines)
    else:
        fake = "\n".join(lines + [f"Einvbamp out 0 0 mid {amp_gain:.15g}", ".end"])
        body = replace_inverts(
            fake, [st], mode, amp_gain=amp_gain, vos=vos, mos=mos,
            invert_dw=invert_dw, servo=servo,
        )
        # Strip only a trailing .end line. Do not substring-replace .ends in subckts.
        raw_lines = body.splitlines()
        while raw_lines and raw_lines[-1].strip().lower() in {".end", ""}:
            if raw_lines[-1].strip().lower() == ".end":
                raw_lines.pop()
            else:
                raw_lines.pop()
        body = "\n".join(raw_lines).rstrip()
    currents = (
        ["print i(Vdd)", "print i(Vss)"]
        if mode in {"miller", "miller_servo", "opa1656"}
        else []
    )
    if t_hold is None:
        ctrl = [
            ".control",
            "set numdgt=15",
            "op",
            "print v(out)",
            "print v(mid)",
            "print v(in)",
            *currents,
            ".endc",
            ".end",
            "",
        ]
    else:
        ctrl = [
            ".control",
            "set numdgt=15",
            f"tran {max(t_hold / 200.0, 1e-7):.15g} {t_hold:.15g}",
            f"meas tran vout_end find v(out) at={t_hold:.15g}",
            f"meas tran vmid_end find v(mid) at={t_hold:.15g}",
            "print vout_end",
            "print vmid_end",
            *currents,
            ".endc",
            ".end",
            "",
        ]
    return body.rstrip() + "\n" + "\n".join(ctrl)


def closed_loop_predict(vin: float, r1: float, r2: float, amp_gain: float) -> float:
    """Unloaded invert: Vout = −Vin * k * A / (A + 1 + k), k=R2/R1."""
    k = float(r2) / float(r1)
    a = float(amp_gain)
    return -float(vin) * k * a / (a + 1.0 + k)
