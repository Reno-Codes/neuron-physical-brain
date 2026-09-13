"""Experiment 24: offset-corrected virtual-ground search.

Does not retrain, edit frozen weights, or Python-correct SPICE outputs.
Manufacturer models are included from the local ngspice tree, not copied.

LEVEL 2: XSPICE limit TIA, auto-zero S/H, chopper-average, servo integrator.
LEVEL 3: documented macromodels already installed with ngspice.
Not LEVEL 4-6. Not board power. Not silicon.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from compile_xor import PROJECT_ROOT, find_ngspice
from physical_iv_neuron import IVParams, compile_iv
from virtual_ground_requirements import INVERT_PINNED, VGParams, generate_isolated_neuron


CIRCUIT_DIR = PROJECT_ROOT / "circuits" / "offset_vg_search"
NG_P2N = Path(r"C:\ngspice\examples\p-to-n-examples")
NG_OPTRAN = Path(r"C:\ngspice\examples\optran\models")

OPA1656_PATH = NG_OPTRAN / "opa1656.lib"
OPA1611_PATH = NG_OPTRAN / "OPA1611.LIB"
OPA171_PATH = NG_P2N / "OPA171.txt"
MCP6041_PATH = NG_P2N / "MCP6041.txt"
TLV6001_PATH = NG_OPTRAN / "TLV6001.LIB"
TLV9002_PATH = NG_OPTRAN / "TLV9002.lib"

E_TIA = re.compile(
    r"^(E)(\S+tia)\s+(\S+)\s+0\s+0\s+(\S+)\s+(\S+)\s*$",
    re.IGNORECASE,
)
B_TIA = re.compile(r"^(B)(\S+tia)\s+(\S+)\s+0\s+V\s*=\s*.*$", re.IGNORECASE)
B_VOS = re.compile(r"v\((\S+)\)\s*-\s*\(([^)]+)\)", re.IGNORECASE)
VIN_DC = re.compile(r"^(Vin(\d+)\s+\S+\s+0\s+DC)\s+\S+", re.IGNORECASE | re.MULTILINE)
RF_LINE = re.compile(r"^(R(\S+)f)\s+(\S+)\s+(\S+)\s+(\S+)\s*$", re.IGNORECASE)


INVENTORY = {
    "L": {
        "level": 2,
        "kind": "xspice_limit",
        "title": "XSPICE limit TIA (programmable Vos)",
        "source": "ngspice built-in analog code model `limit`",
        "model_vos_V": None,
        "needs_ps": False,
        "vsupply": 15.0,
        "note": "Behavioral. Used as AZ/servo/chopper carrier and feasibility map.",
    },
    "OPA1656": {
        "level": 3,
        "kind": "macro_opa1656",
        "title": "TI OPA1656 Green-Williams-Lis macromodel",
        "source": str(OPA1656_PATH),
        "model_vos_V": 8.75e-6,
        "needs_ps": True,
        "vsupply": 15.0,
        "note": "FET-input audio op-amp. Model VNEG=-8.75 uV. Include, not copied.",
    },
    "OPA1611": {
        "level": 3,
        "kind": "macro_opa1611",
        "title": "TI OPA1611 Green-Williams-Lis macromodel",
        "source": str(OPA1611_PATH),
        "model_vos_V": 9.729e-5,
        "needs_ps": True,
        "vsupply": 15.0,
        "note": "Bipolar precision audio. Model Vos DC=97.29 uV. Ib=60 nA in model.",
    },
    "OPA171": {
        "level": 3,
        "kind": "macro_opa171",
        "title": "TI OPA171 (Experiment 23 negative control)",
        "source": str(OPA171_PATH),
        "model_vos_V": 214.023e-6,
        "needs_ps": True,
        "vsupply": 15.0,
        "note": "Already analog-failed in Exp 23. Ranked, not re-promoted.",
    },
    "MCP6041": {
        "level": 3,
        "kind": "macro_mcp6041",
        "title": "Microchip MCP6041 (Experiment 23 negative control)",
        "source": str(MCP6041_PATH),
        "model_vos_V": None,
        "needs_ps": False,
        "vsupply": 2.2,
        "note": "6 V CMOS. Exp 23 smoke Vsum ~1.9 mV. Ranked, not re-promoted.",
    },
    "TLV6001": {
        "level": 3,
        "kind": "skipped",
        "title": "TI TLV6001",
        "source": str(TLV6001_PATH),
        "model_vos_V": 595.218e-6,
        "needs_ps": True,
        "vsupply": 2.5,
        "note": "Vos 595 uV and ngspice notes OP only via optran. Not promoted.",
    },
    "TLV9002": {
        "level": 3,
        "kind": "skipped",
        "title": "TI TLV9002",
        "source": str(TLV9002_PATH),
        "model_vos_V": 396.11e-6,
        "needs_ps": True,
        "vsupply": 2.5,
        "note": "Vos 396 uV, worse than OPA171. Not promoted.",
    },
    "TL072": {
        "level": 3,
        "kind": "skipped",
        "title": "TL072 dual (ngspice optran example)",
        "source": str(NG_OPTRAN / "TL072-dual.lib"),
        "model_vos_V": None,
        "needs_ps": False,
        "vsupply": 15.0,
        "note": "JFET audio dual; typical Vos millivolts. Dual pinout, not a precision VG. Ranked out.",
    },
    "CMOSOpAmp": {
        "level": 4,
        "kind": "skipped",
        "title": "ngspice xspice/see CMOSOpAmp teaching netlist",
        "source": r"C:\ngspice\examples\xspice\see\CMOSOpAmp",
        "model_vos_V": None,
        "needs_ps": False,
        "vsupply": None,
        "note": "Device-level teaching amp with default W/L. Not used: would invent MOS parameters.",
    },
}


@dataclass(frozen=True)
class E24Params:
    candidate: str
    name: str
    amp_gain: float = 1e5
    invert_gain: float = INVERT_PINNED
    rail: float = 15.0
    vos: float = 0.0
    i_leak: float = 0.0
    linear: bool = True
    vsupply: float = 15.0
    autozero: bool = False
    servo: bool = False
    chopper: bool = False
    t_az: float = 5e-5
    t_stop: float = 2e-4
    c_hold: float = 10e-9
    servo_gm: float = 1e-3
    servo_c: float = 1e-6
    chop_period: float = 2e-5
    gate_vref: bool = False

    def vg(self) -> VGParams:
        return VGParams(
            name=self.name,
            amp_gain=self.amp_gain,
            invert_gain=self.invert_gain,
            rail=self.rail,
            vos=0.0 if self.candidate != "L" else self.vos,
            i_leak=self.i_leak,
            linear=self.linear,
            clip_amp=False,
        )

    def iv(self) -> IVParams:
        return IVParams(
            name=self.name,
            amp_gain=self.amp_gain,
            invert_gain=self.invert_gain,
            rail=self.rail,
            vos=0.0 if self.candidate != "L" else self.vos,
            i_leak=self.i_leak,
            linear=self.linear,
            clip_amp=False,
        )

    def public(self) -> dict:
        meta = INVENTORY[self.candidate]
        row = asdict(self)
        row.update({k: meta[k] for k in ("level", "kind", "title", "source", "model_vos_V", "note")})
        return row


def run_ngspice_ex(ngspice: Path, circuit: Path, timeout: float | None = None, pspice: bool = False):
    circuit = Path(circuit).resolve()
    cmd = [str(ngspice), "-b"]
    if pspice:
        cmd += ["-D", "ngbehavior=ps"]
    cmd.append(str(circuit))
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(circuit.parent),
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(
            args=exc.args or cmd,
            returncode=124,
            stdout=exc.stdout or "",
            stderr=(exc.stderr or "") + "\nngspice timed out",
        )


def _stem(dev: str) -> str:
    name = dev[1:] if dev[:1].upper() in "EBX" else dev
    if name.lower().endswith("tia"):
        name = name[:-3]
    return name


def emit_tia_block(stem: str, drv: str, vg: str, params: E24Params) -> list[str]:
    kind = INVENTORY[params.candidate]["kind"]
    plus = f"{stem}osp"
    lines = [
        f"* Exp 24 {params.candidate} TIA {stem} -> {drv}, vg={vg}",
        f"V{stem}os {plus} 0 DC {float(params.vos):.15g}",
    ]
    if kind == "xspice_limit":
        lines.append(f"A{stem}tia %vd({plus} {vg}) {drv} limtia")
    elif kind == "macro_opa1656":
        lines += [
            "* 1 pF output C so GWL OP exists; not datasheet CL",
            f"X{stem}tia {plus} {vg} vdd vss {drv} OPA1656",
            f"C{stem}load {drv} 0 1p",
        ]
    elif kind == "macro_opa1611":
        lines += [
            "* 1 pF output C so GWL OP exists; not datasheet CL",
            f"X{stem}tia {plus} {vg} vdd vss {drv} OPA1611",
            f"C{stem}load {drv} 0 1p",
        ]
    elif kind == "macro_opa171":
        lines += [
            f"X{stem}tia {plus} {vg} vdd vss {drv} OPA171",
            f"C{stem}load {drv} 0 1p",
        ]
    else:
        raise ValueError(kind)
    return lines


def global_preamble(params: E24Params) -> list[str]:
    meta = INVENTORY[params.candidate]
    kind = meta["kind"]
    lines = [
        f"* Experiment 24 candidate {params.candidate}",
        f"* {meta['title']}",
        f"* source: {meta['source']}",
        f"* {meta['note']}",
        "* Weights were not edited. SPICE is not Python-corrected.",
    ]
    includes = {
        "macro_opa1656": OPA1656_PATH,
        "macro_opa1611": OPA1611_PATH,
        "macro_opa171": OPA171_PATH,
    }
    if kind in includes:
        lines.append(f'.include "{includes[kind].as_posix()}"')
        vs = float(params.vsupply)
        lines.append(f"Vdd vdd 0 DC {vs:.15g}")
        lines.append(f"Vss vss 0 DC {-vs:.15g}")
    if kind == "xspice_limit":
        lo, hi = -abs(float(params.rail)), abs(float(params.rail))
        lines.append(
            f".model limtia limit(gain={float(params.amp_gain):.15g} "
            f"in_offset=0.0 out_lower_limit={lo:.15g} "
            f"out_upper_limit={hi:.15g} fraction=false limit_range=0.05)"
        )
    return lines


def replace_behavioral_tias(netlist: str, params: E24Params) -> str:
    pre = global_preamble(params)
    out: list[str] = []
    inserted = False
    n_rep = 0
    for raw in netlist.splitlines():
        s = raw.strip()
        if not inserted and s and not s.startswith("*"):
            out.extend(pre)
            out.append("")
            inserted = True
        m_e = E_TIA.match(s)
        m_b = B_TIA.match(s)
        if m_e:
            _k, dev, drv, vg, _a = m_e.groups()
            out.extend(emit_tia_block(_stem(dev), drv, vg, params))
            n_rep += 1
            continue
        if m_b:
            dev, drv = m_b.group(2), m_b.group(3)
            found = B_VOS.search(s)
            vg = found.group(1) if found else f"{_stem(dev)}p"
            out.extend(emit_tia_block(_stem(dev), drv, vg, params))
            n_rep += 1
            continue
        out.append(raw)
    if n_rep == 0:
        raise RuntimeError("no E/B TIA sources found to replace")
    ending = "\n" if netlist.endswith("\n") else ""
    return "\n".join(out) + ending


def apply_autozero(netlist: str, params: E24Params) -> str:
    """Sample Vlin at Vin=0 onto C, then subtract during inference.

    Correction is a circuit S/H + VCVS, not a Python subtraction of NumPy z.
    Clock: clk=1 (sample) until t_az, then hold. Vin steps from 0 to x at t_az.
    """
    out: list[str] = []
    stems: list[tuple[str, str, str]] = []  # stem, raw_node, vg
    inserted_clk = False
    for raw in netlist.splitlines():
        s = raw.strip()
        if not inserted_clk and s and not s.startswith("*"):
            out += [
                "* Exp 24 auto-zero: sample actual TIA output at Vin=0, subtract in SPICE",
                f"Vazclk clk 0 PULSE(1 0 {params.t_az:.15g} 10n 10n 1 2)",
                f".model azsw sw(vt=0.5 vh=0 ron=10 roff=1e12)",
                "",
            ]
            inserted_clk = True
        m_e = E_TIA.match(s)
        m_a = re.match(r"^(A)(\S+tia)\s+%vd\((\S+)\s+(\S+)\)\s+(\S+)\s+(\S+)\s*$", s, re.I)
        m_x = re.match(r"^(X)(\S+tia)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s*$", s, re.I)
        m_rf = RF_LINE.match(s)
        m_cload = re.match(r"^(C(\S+)load)\s+(\S+)\s+(\S+)\s+(\S+)\s*$", s, re.I)
        if m_e:
            _k, dev, drv, vg, rest = m_e.group(1), m_e.group(2), m_e.group(3), m_e.group(4), m_e.group(5)
            stem = _stem(dev)
            raw_n = f"{stem}raw"
            out.append(f"E{dev} {raw_n} 0 0 {vg} {rest}")
            stems.append((stem, raw_n, vg))
            continue
        if m_a:
            dev, plus, vg, drv, model = m_a.group(2), m_a.group(3), m_a.group(4), m_a.group(5), m_a.group(6)
            stem = _stem(dev)
            raw_n = f"{stem}raw"
            out.append(f"A{dev} %vd({plus} {vg}) {raw_n} {model}")
            stems.append((stem, raw_n, vg))
            continue
        if m_x:
            dev, plus, vg, vdd, vss, drv, model = m_x.groups()[1:]
            stem = _stem(dev)
            raw_n = f"{stem}raw"
            out.append(f"X{dev} {plus} {vg} {vdd} {vss} {raw_n} {model}")
            stems.append((stem, raw_n, vg))
            continue
        if m_rf:
            name, stem_f, n1, n2, rval = m_rf.groups()
            raw_n = f"{stem_f}raw"
            if n1.lower().endswith("lin"):
                out.append(f"{name} {raw_n} {n2} {rval}")
                continue
            if n2.lower().endswith("lin"):
                out.append(f"{name} {n1} {raw_n} {rval}")
                continue
        if m_cload:
            name, stem_f, n1, n2, cval = m_cload.groups()
            raw_n = f"{stem_f}raw"
            if n1.lower().endswith("lin"):
                out.append(f"{name} {raw_n} {n2} {cval}")
                continue
        out.append(raw)
    extra = []
    for stem, raw_n, _vg in stems:
        extra += [
            f"* auto-zero S/H {stem}: sample {raw_n} onto C, Vlin={raw_n}-Vhold",
            f"S{stem}az {raw_n} {stem}hold clk 0 azsw",
            f"C{stem}hold {stem}hold 0 {params.c_hold:.15g}",
            f"R{stem}hld {stem}hold 0 1e12",
            f"E{stem}az {stem}lin 0 {raw_n} {stem}hold 1",
        ]
    # Insert extra before .control
    final: list[str] = []
    placed = False
    for line in out:
        if (not placed) and line.strip().lower().startswith(".control"):
            final.extend(extra)
            final.append("")
            placed = True
        final.append(line)
    if not placed:
        final.extend(extra)
    if not stems:
        raise RuntimeError("auto-zero: no TIA outputs found")
    ending = "\n" if netlist.endswith("\n") else ""
    return "\n".join(final) + ending


def apply_servo(netlist: str, params: E24Params) -> str:
    """Slow integrator from Vsum onto IN+. DC OP nulls Vsum, which also nulls Vlin.

    This is the predicted mathematical failure: Vsum = Vos - Vlin/A mixes
    offset with legitimate finite-A residue. Not a Python correction.
    """
    out: list[str] = []
    inserted = False
    n = 0
    for raw in netlist.splitlines():
        s = raw.strip()
        if not inserted and s and not s.startswith("*"):
            out.append("* Exp 24 servo: integrate v(sum) onto IN+ (LEVEL 2)")
            inserted = True
        m_a = re.match(
            r"^(A)(\S+tia)\s+%vd\((\S+)\s+(\S+)\)\s+(\S+)\s+(\S+)\s*$", s, re.I
        )
        m_vplus = re.match(r"^(V)(\S+)os\s+(\S+)\s+0\s+DC\s+(\S+)\s*$", s, re.I)
        if m_vplus:
            stem = m_vplus.group(2)
            vos = m_vplus.group(4)
            out.append(f"V{stem}os {stem}osref 0 DC {vos}")
            continue
        if m_a:
            dev, plus, vg, drv, model = (
                m_a.group(2), m_a.group(3), m_a.group(4), m_a.group(5), m_a.group(6)
            )
            stem = _stem(dev)
            out.append(f"* servo on {stem}: Vsum>0 discharges int so IN+ falls (LEVEL 2)")
            out.append(f"G{stem}srv {stem}int 0 {vg} 0 {params.servo_gm:.15g}")
            out.append(f"C{stem}int {stem}int 0 {params.servo_c:.15g}")
            out.append(f"R{stem}int {stem}int 0 1e9")
            out.append(f"B{stem}plus {plus} 0 V = v({stem}osref) + v({stem}int)")
            out.append(f"A{dev} %vd({plus} {vg}) {drv} {model}")
            n += 1
            continue
        out.append(raw)
    if n == 0:
        raise RuntimeError("servo: no limit TIA found")
    ending = "\n" if netlist.endswith("\n") else ""
    return "\n".join(out) + ending


def apply_chopper_vos(netlist: str, params: E24Params) -> str:
    """Modulate IN+ Vos with a square wave. Average of Vlin over cycles is the DC inference.

    LEVEL 2 chopper-equivalent. Not a switched-capacitor IC. TIA inputs are not swapped
    (that would open the loop).
    """
    out: list[str] = []
    inserted = False
    n = 0
    half = 0.5 * float(params.chop_period)
    for raw in netlist.splitlines():
        s = raw.strip()
        if not inserted and s and not s.startswith("*"):
            out += [
                "* Exp 24 chopper-equivalent: Vos * square wave on IN+",
                f"Vchop chop 0 PULSE(-1 1 0 10n 10n {half:.15g} {params.chop_period:.15g})",
                "",
            ]
            inserted = True
        m_v = re.match(r"^(V)(\S+)os\s+(\S+)\s+0\s+DC\s+(\S+)\s*$", s, re.I)
        if m_v:
            stem, plus, vos = m_v.group(2), m_v.group(3), m_v.group(4)
            out.append(f"B{stem}os {plus} 0 V = ({vos}) * v(chop)")
            n += 1
            continue
        out.append(raw)
    if n == 0:
        raise RuntimeError("chopper: no Vos sources")
    ending = "\n" if netlist.endswith("\n") else ""
    return "\n".join(out) + ending


def bake_vref_pulse(netlist: str, t_az: float, t_gap: float = 2e-6) -> str:
    """Hold Vref=0 while AZ samples, then restore 1 V with the Vin step."""
    delay = float(t_az) + float(t_gap)
    pattern = re.compile(r"^(Vref\s+\S+\s+0\s+DC)\s+\S+", re.IGNORECASE | re.MULTILINE)

    def repl(m: re.Match) -> str:
        name_node = m.group(1).rsplit(" DC", 1)[0]
        return f"{name_node} PULSE(0 1 {delay:.15g} 10n 10n 1 2)"

    return pattern.sub(repl, netlist)


def bake_vin_dc(netlist: str, x) -> str:
    vec = np.atleast_1d(np.asarray(x, dtype=float))

    def repl(m: re.Match) -> str:
        i = int(m.group(2))
        val = float(vec[i - 1]) if i <= len(vec) else 0.0
        return f"{m.group(1)} {val:.15g}"

    return VIN_DC.sub(repl, netlist)


def bake_vin_pulse(netlist: str, x, t_az: float, t_gap: float = 2e-6) -> str:
    """Vin stays 0 while the AZ switch samples, then steps after the switch opens."""
    vec = np.atleast_1d(np.asarray(x, dtype=float))
    delay = float(t_az) + float(t_gap)

    def repl(m: re.Match) -> str:
        i = int(m.group(2))
        val = float(vec[i - 1]) if i <= len(vec) else 0.0
        prefix = m.group(1)  # "Vin1 in1 0 DC"
        name_node = prefix.rsplit(" DC", 1)[0]
        return (
            f"{name_node} PULSE(0 {val:.15g} {delay:.15g} 10n 10n 1 2)"
        )

    return VIN_DC.sub(repl, netlist)


def simple_op_control(nodes: list[str]) -> str:
    lines = [".control", "set numdgt=15", "op"]
    for n in nodes:
        lines.append(f"print v({n})")
    lines.extend([".endc", "", ".end", ""])
    return "\n".join(lines)


def simple_optran_control(nodes: list[str]) -> str:
    """GWL models in the local ngspice tree often prefer optran over op."""
    lines = [".control", "set numdgt=15", "optran 0 0 0 100n 10u 0"]
    for n in nodes:
        lines.append(f"print v({n})")
    lines.extend([".endc", "", ".end", ""])
    return "\n".join(lines)


def tran_meas_control(
    nodes: list[str],
    t_stop: float,
    t_meas: float,
    tstep: float | None = None,
    avg_start: float | None = None,
) -> str:
    step = tstep if tstep is not None else max(t_stop / 400.0, 1e-8)
    lines = [
        ".control",
        "set numdgt=15",
        f"tran {step:.15g} {t_stop:.15g}",
    ]
    for i, n in enumerate(nodes):
        if avg_start is not None:
            lines.append(
                f"meas tran m{i} AVG v({n}) FROM={float(avg_start):.15g} TO={float(t_stop):.15g}"
            )
        else:
            lines.append(f"meas tran m{i} FIND v({n}) AT={t_meas:.15g}")
        lines.append(f"print m{i}")
    lines.extend([".endc", "", ".end", ""])
    return "\n".join(lines)


def count_blocks(netlist: str) -> dict:
    n_tia = n_az_sw = n_hold_c = n_servo = n_chop = n_load_c = n_clk = 0
    for raw in netlist.splitlines():
        s = raw.strip().lower()
        if not s or s.startswith("*"):
            continue
        name = s.split()[0]
        if name.endswith("tia"):
            n_tia += 1
        if name.startswith("s") and name.endswith("az"):
            n_az_sw += 1
        if name.startswith("c") and name.endswith("hold"):
            n_hold_c += 1
        if name.startswith("c") and name.endswith("load"):
            n_load_c += 1
        if name.startswith("g") and "srv" in name:
            n_servo += 1
        if name == "vchop" or name == "vazclk":
            n_clk += 1
        if name.startswith("b") and name.endswith("os"):
            n_chop += 1
    return {
        "n_tia": n_tia,
        "n_autozero_switches": n_az_sw,
        "n_hold_caps": n_hold_c,
        "n_macro_load_caps": n_load_c,
        "n_servo_integrators": n_servo,
        "n_clocks": n_clk,
        "n_chopper_vos_modulators": n_chop,
    }


def compile_isolated(n_src, wrow, bias, g_weight, banks, params: E24Params, tag="n1"):
    net, cat, reason = generate_isolated_neuron(
        n_src, wrow, bias, g_weight, banks, params.vg(), tag=tag
    )
    if reason or net is None:
        return None, cat, reason
    net = replace_behavioral_tias(net, params)
    if params.autozero:
        net = apply_autozero(net, params)
    if params.servo:
        net = apply_servo(net, params)
    if params.chopper:
        net = apply_chopper_vos(net, params)
    return net, cat, None


def compile_network(spec, weights, params: E24Params, linear: bool | None = None):
    p = params.iv()
    if linear is not None:
        p = IVParams(
            name=p.name, amp_gain=p.amp_gain, invert_gain=p.invert_gain,
            rail=p.rail, vos=p.vos if params.candidate == "L" else 0.0,
            i_leak=p.i_leak, linear=linear, clip_amp=False,
        )
    net, cat, reason = compile_iv("A", spec, weights, p)
    if reason or net is None:
        return None, cat, reason
    net = replace_behavioral_tias(net, params)
    if params.autozero:
        net = apply_autozero(net, params)
    if params.servo:
        net = apply_servo(net, params)
    if params.chopper:
        net = apply_chopper_vos(net, params)
    return net, cat, None


def candidate_needs_ps(name: str) -> bool:
    return bool(INVENTORY[name].get("needs_ps"))
