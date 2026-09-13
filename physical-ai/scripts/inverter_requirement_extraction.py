"""Experiment 31: hidden-inverter requirement extraction helpers.

Frozen Experiment 9 weights. SPICE is the source of truth.
Does not overwrite Experiments 1–30. Does not transistorize Network F.
Does not invent MOS W/L, supply rails, or a foundry PDK.
"""

from __future__ import annotations

import re
from pathlib import Path

from compile_xor import PROJECT_ROOT
from copy_minimizing import R_INV
from device_neuron import MosParams, mos_include_block
from offset_vg_search import OPA1656_PATH, OPA1611_PATH
from physical_invert import (
    AMP_A,
    E_INV,
    ERROR_LIMIT,
    attach_loads,
    extract_inverts,
    invert_summary,
    replace_inverts,
)
from physical_iv_neuron import IVParams, compile_iv
from resistor_ratio_matching import INVERT_A, annotate_fabric
from test_hardware_constraints import spec_by_id


CIRCUIT_DIR = PROJECT_ROOT / "circuits" / "exp31_hidden_inverter_drive"
RESULTS_DIR = PROJECT_ROOT / "results"

E_INV_ANY = re.compile(
    r"^(E)(inv\S+)amp\s+(\S+)\s+0\s+0\s+(\S+)\s+(\S+)\s*$",
    re.IGNORECASE,
)


def dest(*parts) -> Path:
    raw = "_".join(str(p) for p in parts)
    slug = []
    for ch in raw:
        if ch.isalnum() or ch in "._":
            slug.append(ch)
        elif ch in "-+":
            slug.append("m" if ch == "-" else "p")
        elif ch in " .":
            slug.append("_")
        else:
            slug.append("")
    CIRCUIT_DIR.mkdir(parents=True, exist_ok=True)
    return CIRCUIT_DIR / f"{''.join(slug).replace('.', 'p')[:90]}.cir"


def compile_f(w, invert_gain=INVERT_A, amp=AMP_A):
    spec = spec_by_id("F")
    params = IVParams(name="exp31", amp_gain=amp, invert_gain=invert_gain, vos=0.0, linear=False)
    net, cat, reason = compile_iv("A", spec, w, params)
    if reason or net is None:
        raise RuntimeError(reason)
    annotate_fabric(cat)
    return net, cat, spec


def hidden_stages(net: str) -> list[dict]:
    return [s for s in attach_loads(net, extract_inverts(net)) if s["kind"] == "hidden"]


def rank_hidden(hidden: list[dict], hy, key: str) -> list[dict]:
    """key='hy_max' or 'g_load'."""
    rows = []
    for s in hidden:
        j = int(s["stem"].replace("invh", "")) - 1
        rows.append(
            {
                **s,
                "j": j,
                "hy_max": float(hy[:, j].max()) if hy is not None else 0.0,
            }
        )
    if key == "hy_max":
        rows.sort(key=lambda r: r["hy_max"], reverse=True)
    else:
        rows.sort(key=lambda r: r.get("g_load_S") or 0.0, reverse=True)
    return rows


def first_order_current(vin: float, r2: float, r_load: float) -> float:
    """Amp current for Vout=-Vin, mid≈0: |I| = |Vin| (1/R2 + 1/Rload)."""
    return abs(float(vin)) * (1.0 / float(r2) + 1.0 / float(r_load))


def force_hidden_r1_equals_r2(netlist: str, stages: list[dict]) -> str:
    names = {s["r2_name"]: s["r1"] for s in stages if s.get("r2_name") and s.get("r1")}
    out = []
    for raw in netlist.splitlines():
        parts = raw.split()
        if len(parts) >= 4 and parts[0] in names:
            out.append(f"{parts[0]} {parts[1]} {parts[2]} {names[parts[0]]:.15g}")
        else:
            out.append(raw)
    ending = "\n" if netlist.endswith("\n") else ""
    return "\n".join(out) + ending


def _preamble_insert(netlist: str, preamble: list[str]) -> str:
    if not preamble:
        return netlist
    out = []
    inserted = False
    for raw in netlist.splitlines():
        s = raw.strip()
        if (not inserted) and s and not s.startswith("*"):
            out.extend(preamble)
            out.append("")
            inserted = True
        out.append(raw)
    ending = "\n" if netlist.endswith("\n") else ""
    return "\n".join(out) + ending


def patch_invert_amps(
    netlist: str,
    stages: list[dict],
    kind: str,
    amp_gain: float = 1e5,
    vos: float = 0.0,
    rout: float = 0.0,
    imax: float | None = None,
    rail: float | None = None,
    opa_path: Path | None = None,
    opa_name: str = "OPA1656",
    vsupply: float = 15.0,
    independent_supplies: bool = False,
) -> str:
    """Replace selected invert E-sources with a documented or labeled behavioral amp."""
    stems = {s["stem"] for s in stages}
    by = {s["stem"]: s for s in stages}
    preamble: list[str] = []
    have = {p.split()[0].lower() for p in netlist.splitlines() if p.split()}

    if kind in {"opa", "opa_indep"}:
        path = (opa_path or OPA1656_PATH).resolve().as_posix()
        preamble.append(f'.include "{path}"')
        if kind == "opa" and not independent_supplies:
            if "vdd" not in have:
                preamble.append(f"Vdd vdd 0 DC {vsupply:.15g}")
            if "vss" not in have:
                preamble.append(f"Vss vss 0 DC {-vsupply:.15g}")
        preamble.append("* 1 pF on each OPA invert so GWL OP exists; not datasheet CL")
    elif kind == "rail":
        lo = -float(rail)
        hi = float(rail)
        preamble.append(
            f".model liminv31 limit(gain={float(amp_gain):.15g} "
            f"in_offset={float(vos):.15g} out_lower_limit={lo:.15g} "
            f"out_upper_limit={hi:.15g} fraction=false limit_range=0.05)"
        )
    elif kind == "miller_buffered":
        preamble.extend(mos_include_block())
        if "vdd" not in have:
            preamble.append("Vdd vdd 0 DC 2.5")
        if "vss" not in have:
            preamble.append("Vss vss 0 DC -2.5")
        preamble.append("* miller invert + miller follower. CMOS-OP1 W/L, not invented.")

    out: list[str] = []
    inserted = False
    for raw in netlist.splitlines():
        s = raw.strip()
        if (not inserted) and s and not s.startswith("*") and preamble:
            out.extend(preamble)
            out.append("")
            inserted = True
        m = E_INV_ANY.match(s)
        if not m or m.group(2) not in stems:
            out.append(raw)
            continue
        st = by[m.group(2)]
        out.extend(
            _emit(
                st,
                kind,
                amp_gain,
                vos,
                rout,
                imax,
                opa_name,
                vsupply,
                independent_supplies or kind == "opa_indep",
            )
        )
    ending = "\n" if netlist.endswith("\n") else ""
    return "\n".join(out) + ending


def _emit(st, kind, amp_gain, vos, rout, imax, opa_name, vsupply, indep) -> list[str]:
    stem, dest, mid = st["stem"], st["dest"], st["mid"]
    a = float(amp_gain)
    if kind == "vcvs":
        if vos:
            return [
                f"B{stem}amp {dest} 0 V = -({a:.15g})*(v({mid})-({float(vos):.15g}))"
            ]
        return [f"E{stem}amp {dest} 0 0 {mid} {a:.15g}"]
    if kind == "rout":
        nint = f"{stem}nint"
        lines = [f"E{stem}amp {nint} 0 0 {mid} {a:.15g}"]
        if vos:
            lines = [
                f"B{stem}amp {nint} 0 V = -({a:.15g})*(v({mid})-({float(vos):.15g}))"
            ]
        lines.append(f"R{stem}out {nint} {dest} {float(rout):.15g}")
        return lines
    if kind == "ilimit":
        nint = f"{stem}nint"
        im = float(imax)
        return [
            f"* current-limited invert {stem}: |I|<= {im:g} A (labeled behavioral)",
            f"E{stem}amp {nint} 0 0 {mid} {a:.15g}",
            (
                f"B{stem}drv {dest} {nint} I = ({im:.15g})*"
                f"tanh((v({nint})-v({dest}))/1e-3)"
            ),
        ]
    if kind == "rail":
        return [
            f"* rail-limited invert {stem}",
            f"A{stem}inv %vd(0 {mid}) {dest} liminv31",
        ]
    if kind in {"opa", "opa_indep"}:
        if indep:
            vdd, vss = f"{stem}vdd", f"{stem}vss"
            return [
                f"V{stem}dd {vdd} 0 DC {vsupply:.15g}",
                f"V{stem}ss {vss} 0 DC {-vsupply:.15g}",
                f"X{stem}inv 0 {mid} {vdd} {vss} {dest} {opa_name}",
                f"C{stem}cl {dest} 0 1p",
            ]
        return [
            f"X{stem}inv 0 {mid} vdd vss {dest} {opa_name}",
            f"C{stem}cl {dest} 0 1p",
        ]
    if kind == "miller_buffered":
        p = MosParams(name="inv31")
        nint = f"{stem}nint"
        return [
            f"* miller invert {stem} + miller unity follower on dest. ±2.5 V.",
            (
                f"X{stem}inv 0 {mid} {nint} vdd vss miller_tia "
                f"MD={p.m_diff} MT={p.m_tail} MO={p.m_out} "
                f"CC={p.cc_f:.15g} IBIAS={p.ibias:.15g} DW=0.0026 L1={p.l1_m}u"
            ),
            (
                f"X{stem}buf {nint} {dest} {dest} vdd vss miller_tia "
                f"MD={p.m_diff} MT={p.m_tail} MO={p.m_out} "
                f"CC={p.cc_f:.15g} IBIAS={p.ibias:.15g} DW=0.0026 L1={p.l1_m}u"
            ),
        ]
    return [f"E{stem}amp {dest} 0 0 {mid} {a:.15g}"]


def invert_probe_control(inputs, n_out: int, stages: list[dict], supplies=False) -> str:
    """Batch OP with fabric outputs plus per-hidden invert probes."""
    lines = [".control", "set numdgt=15"]
    for x in inputs:
        for i, xi in enumerate(__import__("numpy").atleast_1d(x), start=1):
            lines.append(f"alter Vin{i} DC {float(xi):.15g}")
        lines.append("op")
        for k in range(1, n_out + 1):
            lines.append(f"print v(o{k}lin)")
        for s in stages:
            lines.append(f"print v({s['src']})")
            lines.append(f"print v({s['dest']})")
            lines.append(f"print v({s['mid']})")
        if supplies:
            lines.append("print i(Vdd)")
            lines.append("print i(Vss)")
    lines.extend([".endc", "", ".end", ""])
    return "\n".join(lines)


def isolated_drive_netlist(
    vin: float,
    r1: float,
    r2: float,
    r_load: float,
    kind: str = "vcvs",
    amp_gain: float = 1e5,
    imax: float | None = None,
    rout: float = 0.0,
    rail: float | None = None,
    t_hold: float | None = None,
    mos: MosParams | None = None,
) -> str:
    """Isolated invert with a 0 V current sense on the amp output."""
    lines = [
        f"* Experiment 31 isolated invert kind={kind}",
        f"* Vin={vin:g} R1={r1:g} R2={r2:g} Rload={r_load:g}",
        f"Vin in 0 DC {vin:.15g}",
        f"Rinvbia in mid {r1:.15g}",
        f"Rinvbib out mid {r2:.15g}",
        f"Rload out 0 {r_load:.15g}",
    ]
    if kind == "vcvs":
        lines += [
            "Eamp nout 0 0 mid " + f"{amp_gain:.15g}",
            "Vsense nout out 0",
        ]
    elif kind == "ilimit":
        lines += [
            f"Eamp nout 0 0 mid {amp_gain:.15g}",
            (
                f"Bdrv out nout I = ({float(imax):.15g})*"
                f"tanh((v(nout)-v(out))/1e-3)"
            ),
            "Vsense nout nout 0",
        ]
    elif kind == "rout":
        lines += [
            f"Eamp nout 0 0 mid {amp_gain:.15g}",
            f"Rout nout out {float(rout):.15g}",
        ]
    elif kind == "rail":
        lo, hi = -float(rail), float(rail)
        lines += [
            f".model limiso limit(gain={amp_gain:.15g} in_offset=0 "
            f"out_lower_limit={lo:.15g} out_upper_limit={hi:.15g} "
            f"fraction=false limit_range=0.05)",
            "Ainv %vd(0 mid) out limiso",
        ]
    elif kind == "opa1656":
        lines += [
            f'.include "{OPA1656_PATH.resolve().as_posix()}"',
            "Vdd vdd 0 DC 15",
            "Vss vss 0 DC -15",
            "Xinv 0 mid vdd vss out OPA1656",
            "Ccl out 0 1p",
        ]
    elif kind == "opa1611":
        lines += [
            f'.include "{OPA1611_PATH.resolve().as_posix()}"',
            "Vdd vdd 0 DC 15",
            "Vss vss 0 DC -15",
            "Xinv 0 mid vdd vss out OPA1611",
            "Ccl out 0 1p",
        ]
    elif kind == "miller":
        p = mos or MosParams(name="iso31")
        lines += mos_include_block()
        lines += [
            "Vdd vdd 0 DC 2.5",
            "Vss vss 0 DC -2.5",
            (
                f"Xinv 0 mid out vdd vss miller_tia "
                f"MD={p.m_diff} MT={p.m_tail} MO={p.m_out} "
                f"CC={p.cc_f:.15g} IBIAS={p.ibias:.15g} DW=0.0026 L1={p.l1_m}u"
            ),
        ]
    elif kind == "miller_buffered":
        p = mos or MosParams(name="iso31")
        lines += mos_include_block()
        lines += [
            "Vdd vdd 0 DC 2.5",
            "Vss vss 0 DC -2.5",
            (
                f"Xinv 0 mid nint vdd vss miller_tia "
                f"MD={p.m_diff} MT={p.m_tail} MO={p.m_out} "
                f"CC={p.cc_f:.15g} IBIAS={p.ibias:.15g} DW=0.0026 L1={p.l1_m}u"
            ),
            (
                f"Xbuf nint out out vdd vss miller_tia "
                f"MD={p.m_diff} MT={p.m_tail} MO={p.m_out} "
                f"CC={p.cc_f:.15g} IBIAS={p.ibias:.15g} DW=0.0026 L1={p.l1_m}u"
            ),
        ]
    else:
        raise ValueError(kind)
    currents = []
    if kind == "vcvs":
        currents.append("print i(Vsense)")
    if kind in {"opa1656", "opa1611", "miller", "miller_buffered"}:
        currents.extend(["print i(Vdd)", "print i(Vss)"])
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
            ".endc",
            ".end",
            "",
        ]
    return "\n".join(lines + ctrl)


def candidate_inventory() -> list[dict]:
    return [
        {
            "candidate": "XSPICE limit invert",
            "level": 2,
            "voltage_range": "+/-15 V programmable",
            "output_drive": "behavioral, unlimited",
            "offset": "programmable",
            "gain": "programmable",
            "supply": "none",
            "stability": "Exp 30 F40 analog-pass",
            "suitability": "Requirement carrier, not a physical device",
        },
        {
            "candidate": "TI OPA1656 GWL macromodel",
            "level": 3,
            "voltage_range": "+/-15 V",
            "output_drive": "audio op-amp; isolated worst-case analog-pass",
            "offset": "model VNEG=8.75 uV; isolated mid ~498 uV under invert load",
            "gain": "datasheet high A_ol; invert A_eff ~5e3 under 4.9 kOhm",
            "supply": "+/-15 V shared or per-instance",
            "stability": "GWL needs 1 pF; 32-instance analog-fail in Exp 30",
            "suitability": "Isolated control. Not promoted at 32 without a mechanism test.",
        },
        {
            "candidate": "TI OPA1611 GWL macromodel",
            "level": 3,
            "voltage_range": "+/-15 V",
            "output_drive": "audio op-amp",
            "offset": "model Vos ~97 uV",
            "gain": "high A_ol macromodel",
            "supply": "+/-15 V",
            "stability": "needs ngbehavior=ps",
            "suitability": "Documented alternate. Higher model Vos than OPA1656.",
        },
        {
            "candidate": "Teaching miller (CMOS-OP1 W/L)",
            "level": 4,
            "voltage_range": "+/-2.5 V",
            "output_drive": "fails ~4.9 kOhm at 1.5-2.6 V (Exp 30)",
            "offset": "DW=0.0026 27 C null",
            "gain": "finite; unloaded invert still ~6 mV at 1.5 V",
            "supply": "+/-2.5 V documented card",
            "stability": "isolated OP used in Exp 26-28",
            "suitability": "Cannot meet extracted hidden swing/load. W/L not invented.",
        },
        {
            "candidate": "Miller invert + miller follower",
            "level": 4,
            "voltage_range": "+/-2.5 V",
            "output_drive": "follower is the same documented output stage",
            "offset": "two miller residuals",
            "gain": "buffer inside the invert loop",
            "supply": "+/-2.5 V",
            "stability": "unknown until isolated bench",
            "suitability": "Documented composition only. Rails still +/-2.5 V.",
        },
        {
            "candidate": "Behavioral I-limited / Rout / rail invert",
            "level": 2,
            "voltage_range": "swept",
            "output_drive": "swept Imax / Rout / rail",
            "offset": "optional",
            "gain": "optional",
            "supply": "none",
            "stability": "requirement extraction only",
            "suitability": "Not a physical circuit. Do not promote.",
        },
    ]
