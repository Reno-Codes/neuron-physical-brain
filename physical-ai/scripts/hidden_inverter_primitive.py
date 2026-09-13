"""Experiment 32: documented hidden-inverter primitive helpers.

Frozen Experiment 9 weights. SPICE is the source of truth.
Does not overwrite Experiments 1–31. Does not transistorize Network F.
Does not invent MOS W/L, supply rails, or a foundry PDK.
"""

from __future__ import annotations

from pathlib import Path

from compile_xor import PROJECT_ROOT
from offset_vg_search import (
    MCP6041_PATH,
    OPA1611_PATH,
    OPA1656_PATH,
    OPA171_PATH,
    TLV6001_PATH,
    TLV9002_PATH,
)
from physical_invert import E_INV


CIRCUIT_DIR = PROJECT_ROOT / "circuits" / "exp32_hidden_inverter_primitive"
RESULTS_DIR = PROJECT_ROOT / "results"
ERROR_LIMIT = 1.0e-3
R_INV = 10_000.0
R_LOAD_W = 4914.013048625536
VIN_SWING = 2.6081758652291698


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


def _preamble_insert(netlist: str, preamble: list[str]) -> str:
    out = []
    inserted = False
    for raw in netlist.splitlines():
        s = raw.strip()
        if (not inserted) and s and not s.startswith("*") and preamble:
            out.extend(preamble)
            out.append("")
            inserted = True
        out.append(raw)
    ending = "\n" if netlist.endswith("\n") else ""
    return "\n".join(out) + ending


def local_model_inventory() -> list[dict]:
    tl072 = Path(r"C:\ngspice\examples\optran\models\TL072-dual.lib")
    return [
        {
            "candidate": "XSPICE limit invert",
            "level": 2,
            "path": "ngspice built-in",
            "present": True,
            "doc_vos_V": 0.0,
            "vsupply": 15.0,
            "needs_ps": False,
            "gate_a": True,
            "note": "Exp 30/31 analog-pass at N=32. Behavioral, not a physical device.",
        },
        {
            "candidate": "OPA1656",
            "level": 3,
            "path": str(OPA1656_PATH),
            "present": OPA1656_PATH.exists(),
            "doc_vos_V": 8.75e-6,
            "vsupply": 15.0,
            "needs_ps": True,
            "gate_a": True,
            "note": "Exp 31: loaded invert mid ≈ 498 uV, N>=16 analog-fail.",
        },
        {
            "candidate": "OPA1611",
            "level": 3,
            "path": str(OPA1611_PATH),
            "present": OPA1611_PATH.exists(),
            "doc_vos_V": 9.729e-5,
            "vsupply": 15.0,
            "needs_ps": True,
            "gate_a": True,
            "note": "Exp 31 isolated |err|=576 uV. Datasheet-class Vos ≠ loaded residual.",
        },
        {
            "candidate": "OPA171",
            "level": 3,
            "path": str(OPA171_PATH),
            "present": OPA171_PATH.exists(),
            "doc_vos_V": 214.023e-6,
            "vsupply": 15.0,
            "needs_ps": True,
            "gate_a": True,
            "note": "Exp 23/24 TIA analog-fail. Ranked, not a low-offset candidate.",
        },
        {
            "candidate": "MCP6041",
            "level": 3,
            "path": str(MCP6041_PATH),
            "present": MCP6041_PATH.exists(),
            "doc_vos_V": None,
            "vsupply": 2.2,
            "needs_ps": False,
            "gate_a": True,
            "note": "6 V CMOS. Rails below 2.61 V hidden swing. Negative control.",
        },
        {
            "candidate": "TLV6001",
            "level": 3,
            "path": str(TLV6001_PATH),
            "present": TLV6001_PATH.exists(),
            "doc_vos_V": 595.218e-6,
            "vsupply": 2.5,
            "needs_ps": True,
            "gate_a": True,
            "note": "Vos 595 uV and +/-2.5 V. Below hidden swing. Ranked out.",
        },
        {
            "candidate": "TLV9002",
            "level": 3,
            "path": str(TLV9002_PATH),
            "present": TLV9002_PATH.exists(),
            "doc_vos_V": 396.11e-6,
            "vsupply": 2.5,
            "needs_ps": True,
            "gate_a": True,
            "note": "Vos 396 uV and +/-2.5 V. Ranked out.",
        },
        {
            "candidate": "TL072-dual",
            "level": 3,
            "path": str(tl072),
            "present": tl072.exists(),
            "doc_vos_V": None,
            "vsupply": 15.0,
            "needs_ps": False,
            "gate_a": True,
            "note": "JFET audio dual; typical Vos millivolts. Not a precision VG.",
        },
        {
            "candidate": "teaching miller",
            "level": 4,
            "path": r"C:\ngspice\examples\xspice\see\CMOSOpAmp",
            "present": True,
            "doc_vos_V": None,
            "vsupply": 2.5,
            "needs_ps": False,
            "gate_a": True,
            "note": "Exp 30/31 isolated invert transfer fail at fabric load/swing.",
        },
        {
            "candidate": "OPA1656 + shared replica mid on IN+",
            "level": 3,
            "path": str(OPA1656_PATH),
            "present": OPA1656_PATH.exists(),
            "doc_vos_V": 8.75e-6,
            "vsupply": 15.0,
            "needs_ps": True,
            "gate_a": True,
            "note": "Control: IN+ = replica mid. If Vos is input-referred this should add, not cancel.",
        },
        {
            "candidate": "OPA1656 + shared replica -mid on IN+",
            "level": 2,
            "path": "OPA1656 + VCVS sign flip of replica mid",
            "present": OPA1656_PATH.exists(),
            "doc_vos_V": 8.75e-6,
            "vsupply": 15.0,
            "needs_ps": True,
            "gate_a": True,
            "note": "Circuit cancellation. Sign flip is LEVEL 2. Amp still drives dest.",
        },
        {
            "candidate": "OPA1656 + replica output subtract",
            "level": 2,
            "path": "OPA1656 + B-source dest = raw - repout",
            "present": True,
            "doc_vos_V": None,
            "vsupply": 15.0,
            "needs_ps": True,
            "gate_a": True,
            "note": "DC AZ. B-source also hijacks fabric drive. Mechanism test only.",
        },
        {
            "candidate": "OPA1656 + LEVEL 2 invert servo",
            "level": 2,
            "path": "XSPICE/behavioral G-C + OPA1656",
            "present": True,
            "doc_vos_V": None,
            "vsupply": 15.0,
            "needs_ps": True,
            "gate_a": True,
            "note": "Circuit correction. Not a physical device primitive.",
        },
        {
            "candidate": "OPA1656 invert + OPA1656 follower",
            "level": 3,
            "path": str(OPA1656_PATH),
            "present": OPA1656_PATH.exists(),
            "doc_vos_V": 8.75e-6,
            "vsupply": 15.0,
            "needs_ps": True,
            "gate_a": True,
            "note": "Drive/offset split. Buffer is not assumed transparent.",
        },
    ]


def _opa_rails(name: str = "OPA1656") -> list[str]:
    path = OPA1656_PATH if name == "OPA1656" else OPA1611_PATH
    return [
        f'.include "{path.resolve().as_posix()}"',
        "Vdd vdd 0 DC 15",
        "Vss vss 0 DC -15",
    ]


def _replica_block(r1: float, r2: float, r_load: float, opa_name: str = "OPA1656") -> list[str]:
    return [
        f"Rra 0 rmid {r1:.15g}",
        f"Rrb rout rmid {r2:.15g}",
        f"Xrep 0 rmid vdd vss rout {opa_name}",
        "Crc rout 0 1p",
        f"Rrl rout 0 {r_load:.15g}",
    ]


def isolated_invert(
    vin: float,
    kind: str = "opa1656",
    r_load: float = R_LOAD_W,
    r1: float = R_INV,
    r2: float = R_INV,
    t_hold: float | None = None,
) -> str:
    """Isolated gain=-1 invert. Feedback closes on `fb`; dest is `out`."""
    fb = "raw" if kind == "replica_sub" else "out"
    lines = [
        f"* Experiment 32 isolated invert kind={kind} Vin={vin:g} Rload={r_load:g}",
        f"Vin in 0 DC {vin:.15g}",
        f"R1 in mid {r1:.15g}",
        f"R2 {fb} mid {r2:.15g}",
        f"Rload out 0 {r_load:.15g}",
    ]
    if kind == "opa1656":
        lines += _opa_rails() + ["Xinv 0 mid vdd vss out OPA1656", "Ccl out 0 1p"]
    elif kind == "opa1611":
        lines += _opa_rails("OPA1611") + ["Xinv 0 mid vdd vss out OPA1611", "Ccl out 0 1p"]
    elif kind == "replica":
        lines += (
            _opa_rails()
            + ["* IN+ = replica mid (expected to add if Vos is input-referred)"]
            + _replica_block(r1, r2, r_load)
            + ["Xinv rmid mid vdd vss out OPA1656", "Ccl out 0 1p"]
        )
    elif kind == "replica_neg":
        lines += (
            _opa_rails()
            + ["* IN+ = -replica mid (LEVEL 2 sign of LEVEL 3 pedestal)"]
            + _replica_block(r1, r2, r_load)
            + ["Eref inp 0 rmid 0 -1", "Xinv inp mid vdd vss out OPA1656", "Ccl out 0 1p"]
        )
    elif kind == "replica_sub":
        lines += (
            _opa_rails()
            + ["* dest = raw - replica_out. B-source also drives the load."]
            + _replica_block(r1, r2, r_load)
            + [
                "Xinv 0 mid vdd vss raw OPA1656",
                "Ccl raw 0 1p",
                "Bcorr out 0 V = v(raw)-v(rout)",
            ]
        )
    elif kind == "replica_disabled":
        lines += (
            _opa_rails()
            + ["* replica present; cancellation disabled"]
            + _replica_block(r1, r2, r_load)
            + ["Xinv 0 mid vdd vss out OPA1656", "Ccl out 0 1p"]
        )
    elif kind == "servo":
        lines += _opa_rails() + [
            "* LEVEL 2 invert servo: IN+ integrates (v(out)+v(in))",
            "Berr err 0 V = v(out)+v(in)",
            "Gsrv inp 0 err 0 2e-4",
            "Csrv inp 0 20n",
            "Rleak inp 0 1e9",
            "Xinv inp mid vdd vss out OPA1656",
            "Ccl out 0 1p",
        ]
    elif kind == "opa_follow_in":
        lines += _opa_rails() + [
            "* follower inside invert loop; R2 from dest",
            "Xinv 0 mid vdd vss nint OPA1656",
            "Ccli nint 0 1p",
            "Xbuf nint out vdd vss out OPA1656",
            "Ccl out 0 1p",
        ]
    elif kind == "opa_follow_out":
        lines += _opa_rails() + [
            "* follower outside invert loop; R2 from nint, dest = follower",
            "Xinv 0 mid vdd vss nint OPA1656",
            "Ccli nint 0 1p",
            f"R2x nint mid {r2:.15g}",
            "Xbuf nint out vdd vss out OPA1656",
            "Ccl out 0 1p",
        ]
        # header already has R2 out mid; for outside-loop the invert R2 must be nint.
        # Drop the dest-feedback R2 by commenting it after the fact below.
    elif kind == "limit":
        lines += [
            ".model limiso limit(gain=1e5 in_offset=0 out_lower_limit=-15 "
            "out_upper_limit=15 fraction=false limit_range=0.05)",
            "Ainv %vd(0 mid) out limiso",
        ]
    elif kind == "passive":
        lines += ["* no amp: grounded divider"]
    elif kind == "miller":
        from device_neuron import MosParams, mos_include_block

        p = MosParams(name="iso32")
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
    else:
        raise ValueError(kind)
    if kind == "opa_follow_out":
        lines = [ln if not ln.startswith("R2 out ") else "* " + ln for ln in lines]
    extra = ["print i(Rload)"]
    if kind.startswith("replica"):
        extra += ["print v(rmid)", "print v(rout)"]
    if kind == "replica_neg":
        extra.append("print v(inp)")
    if kind == "servo":
        extra += ["print v(inp)", "print v(err)"]
    if kind.startswith("opa_follow"):
        extra.append("print v(nint)")
    if kind not in {"passive", "limit"}:
        extra.append("print i(Vdd)")
    if t_hold is None:
        ctrl = [
            ".control",
            "set numdgt=15",
            "op",
            "print v(out)",
            "print v(mid)",
            "print v(in)",
            *extra,
            ".endc",
            ".end",
            "",
        ]
    else:
        extra_m = []
        if kind.startswith("replica"):
            extra_m += [
                f"meas tran vrmid_end find v(rmid) at={t_hold:.15g}",
                "print vrmid_end",
            ]
        ctrl = [
            ".control",
            "set numdgt=15",
            f"tran {max(t_hold / 200.0, 1e-7):.15g} {t_hold:.15g}",
            f"meas tran vout_end find v(out) at={t_hold:.15g}",
            f"meas tran vmid_end find v(mid) at={t_hold:.15g}",
            "print vout_end",
            "print vmid_end",
            *extra_m,
            ".endc",
            ".end",
            "",
        ]
    return "\n".join(lines + ctrl)


def isolated_history_tran(
    kind: str = "replica_neg",
    r_load: float = R_LOAD_W,
    dwell: float = 2e-4,
    amps: tuple[float, float, float] = (0.0, VIN_SWING, 1.0),
) -> str:
    """A -> B -> C -> A isolated invert TRAN. Sample at end of each dwell."""
    t = 0.0
    pwl = [(0.0, amps[0])]
    samples = []
    seq = [amps[0], amps[1], amps[2], amps[0]]
    for i, a in enumerate(seq):
        t_end = (i + 1) * dwell
        if i:
            pwl.append((t + 1e-6, a))
        pwl.append((t_end, a))
        samples.append((f"s{i}", t_end, a))
        t = t_end
    pwl_s = " ".join(f"{tt:.15g} {vv:.15g}" for tt, vv in pwl)
    body = isolated_invert(0.0, kind=kind, r_load=r_load)
    head, _, _ = body.partition(".control")
    head = head.replace("Vin in 0 DC 0", f"Vin in 0 PWL({pwl_s})", 1)
    meas = []
    for name, ts, _a in samples:
        meas += [
            f"meas tran v{name} find v(out) at={ts:.15g}",
            f"print v{name}",
        ]
    ctrl = [
        ".control",
        "set numdgt=15",
        f"tran {max(t / 400.0, 1e-7):.15g} {t:.15g}",
        *meas,
        ".endc",
        ".end",
        "",
    ]
    return head.rstrip() + "\n" + "\n".join(ctrl)


def isolated_az_tran(
    vin: float,
    r_load: float = R_LOAD_W,
    t_az: float = 2e-4,
    t_hold: float = 2e-4,
) -> str:
    """Two-phase AZ: src=0, store dest, then apply Vin and subtract stored dest.

    Subtraction is in-circuit (B-source). LEVEL 2 correction of a LEVEL 3 amp.
    """
    t_inf = t_az + t_hold
    return "\n".join(
        [
            f"* Experiment 32 isolated AZ invert Vin={vin:g}",
            f"Vin in 0 PWL(0 0 {t_az:.15g} 0 {t_az + 1e-6:.15g} {vin:.15g} {t_inf:.15g} {vin:.15g})",
            f"R1 in mid {R_INV:.15g}",
            f"R2 raw mid {R_INV:.15g}",
            f"Rload raw 0 {r_load:.15g}",
            f'.include "{OPA1656_PATH.resolve().as_posix()}"',
            "Vdd vdd 0 DC 15",
            "Vss vss 0 DC -15",
            "Xinv 0 mid vdd vss raw OPA1656",
            "Ccl raw 0 1p",
            "* AZ hold: sample raw while Vin=0",
            "Saz raw hold 0 azc SWAZ",
            ".model SWAZ sw vt=0.5 vh=0.1 ron=1 roff=1e12",
            f"Vaz azc 0 PWL(0 1 {t_az:.15g} 1 {t_az + 1e-6:.15g} 0 {t_inf:.15g} 0)",
            "Chold hold 0 10n",
            "Rhold hold 0 1e9",
            "Bcorr out 0 V = v(raw)-v(hold)",
            ".control",
            "set numdgt=15",
            f"tran {max(t_inf / 400.0, 1e-7):.15g} {t_inf:.15g}",
            f"meas tran vout_end find v(out) at={t_inf:.15g}",
            f"meas tran vraw_end find v(raw) at={t_inf:.15g}",
            f"meas tran vhold find v(hold) at={t_inf:.15g}",
            "print vout_end",
            "print vraw_end",
            "print vhold",
            ".endc",
            ".end",
            "",
        ]
    )


def patch_hidden_opa_replica(
    netlist: str,
    stages: list[dict],
    mode: str = "neg",
    r_load: float = R_LOAD_W,
    opa_path: Path | None = None,
    opa_name: str = "OPA1656",
    vsupply: float = 15.0,
) -> str:
    """Replace selected invert E-sources with OPA plus a shared zero-input replica.

    modes:
      mid       IN+ = replica mid
      neg       IN+ = -replica mid (LEVEL 2 sign)
      sub       dest = raw - replica_out (LEVEL 2 B-source; hijacks drive)
      disabled  replica present, IN+ = 0
    """
    path = (opa_path or OPA1656_PATH).resolve().as_posix()
    stems = {s["stem"] for s in stages}
    by = {s["stem"]: s for s in stages}
    preamble = [
        f'.include "{path}"',
        f"Vdd vdd 0 DC {vsupply:.15g}",
        f"Vss vss 0 DC {-vsupply:.15g}",
        "* shared zero-input replica invert (same macromodel, same R1/R2/load)",
        f"Rrepia 0 repmid {R_INV:.15g}",
        f"Rrepib repout repmid {R_INV:.15g}",
        f"Xrepinv 0 repmid vdd vss repout {opa_name}",
        "Crepc repout 0 1p",
        f"Rrepload repout 0 {float(r_load):.15g}",
    ]
    if mode == "neg":
        preamble += [
            "* LEVEL 2 sign of replica mid -> shared IN+",
            "Erepinp inpref 0 repmid 0 -1",
        ]
    preamble.append("* 1 pF on each OPA invert so GWL OP exists")
    if mode == "mid":
        inp = "repmid"
    elif mode == "neg":
        inp = "inpref"
    else:
        inp = "0"
    out = []
    inserted = False
    for raw in netlist.splitlines():
        s = raw.strip()
        if (not inserted) and s and not s.startswith("*"):
            out.extend(preamble)
            out.append("")
            inserted = True
        m = E_INV.match(s)
        if m and m.group(2) in stems:
            st = by[m.group(2)]
            stem, dest, mid = st["stem"], st["dest"], st["mid"]
            if mode == "sub":
                rawn = f"{stem}raw"
                out += [
                    f"X{stem}inv 0 {mid} vdd vss {rawn} {opa_name}",
                    f"C{stem}cl {rawn} 0 1p",
                    f"B{stem}corr {dest} 0 V = v({rawn})-v(repout)",
                ]
            else:
                out += [
                    f"X{stem}inv {inp} {mid} vdd vss {dest} {opa_name}",
                    f"C{stem}cl {dest} 0 1p",
                ]
            continue
        out.append(raw)
    ending = "\n" if netlist.endswith("\n") else ""
    return "\n".join(out) + ending


def patch_hidden_opa_servo(netlist: str, stages: list[dict]) -> str:
    """LEVEL 2 G-C servo on IN+ of each hidden OPA invert. Not a physical primitive."""
    stems = {s["stem"] for s in stages}
    by = {s["stem"]: s for s in stages}
    preamble = [
        f'.include "{OPA1656_PATH.resolve().as_posix()}"',
        "Vdd vdd 0 DC 15",
        "Vss vss 0 DC -15",
        "* LEVEL 2 invert servo: IN+ integrates v(dest)+v(src)",
    ]
    out = []
    inserted = False
    for raw in netlist.splitlines():
        s = raw.strip()
        if (not inserted) and s and not s.startswith("*"):
            out.extend(preamble)
            out.append("")
            inserted = True
        m = E_INV.match(s)
        if m and m.group(2) in stems:
            st = by[m.group(2)]
            stem, dest, mid, src = st["stem"], st["dest"], st["mid"], st["src"]
            inp = f"{stem}inp"
            out += [
                f"B{stem}err {stem}err 0 V = v({dest})+v({src})",
                f"G{stem}srv {inp} 0 {stem}err 0 2e-4",
                f"C{stem}srv {inp} 0 20n",
                f"R{stem}lk {inp} 0 1e9",
                f"X{stem}inv {inp} {mid} vdd vss {dest} OPA1656",
                f"C{stem}cl {dest} 0 1p",
            ]
            continue
        out.append(raw)
    ending = "\n" if netlist.endswith("\n") else ""
    return "\n".join(out) + ending
