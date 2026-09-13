"""Experiment 26: device-level (MOS) virtual-ground neuron primitive.

Uses Berkeley BSIM3v3 modelcards that ship with the local ngspice tree
(examples/xspice/see/CMOSOpAmp). Those cards are teaching 0.35 µm-class
BSIM3, not a foundry PDK and not silicon. IHP SG13G2 is documented in
ngspice examples but is not installed (PDK_ROOT unset).

W/L stay inside the modelcard limits (L 0.35–20 µm, W 0.6–20 µm).
Multiplicity `m` is the only drive-current knob. Channel length L=1.4 µm
is taken from the ngspice CMOS-OP1 teaching netlist.

Frozen weights are not edited. SPICE is not Python-corrected.
"""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from compile_xor import PROJECT_ROOT
from offset_vg_search import VIN_DC, bake_vin_dc, bake_vin_pulse, run_ngspice_ex
from virtual_ground_requirements import INVERT_PINNED, VGParams, generate_isolated_neuron


CIRCUIT_DIR = PROJECT_ROOT / "circuits" / "device_neuron"
RESULTS_DIR = PROJECT_ROOT / "results"
TAG = "n1"

NG_CMOS = Path(r"C:\ngspice\examples\xspice\see\CMOSOpAmp")
MODEL_NMOS = NG_CMOS / "modelcard.nmos"
MODEL_PMOS = NG_CMOS / "modelcard.pmos"
IHP_HOWTO = Path(r"C:\ngspice\examples\IHPOpenSourcePDK\IHP-PDK-howto.txt")

E_TIA = re.compile(
    r"^(E)(\S+tia)\s+(\S+)\s+0\s+0\s+(\S+)\s+(\S+)\s*$",
    re.IGNORECASE,
)
B_TIA = re.compile(
    r"^(B)(\S+tia)\s+(\S+)\s+0\s+V\s*=\s*.*$",
    re.IGNORECASE,
)
B_VOS = re.compile(r"v\((\S+)\)\s*-\s*\(([^)]+)\)", re.IGNORECASE)

# CMOS-OP1 teaching sizes (µm). Documented, not invented from a blank page.
L_TEACH_M = 1.4
W_DIFF_M = 2.8
W_TAIL_M = 5.0
W_LOAD_M = 2.8
W_OUTP_M = 14.5
W_OUTN_M = 17.4
W_DIODE_M = 5.0

VOS_214 = 214.023e-6
ERROR_LIMIT = 1e-3
R_UNIT = 10_000.0  # tiling abstraction, ohms


@dataclass(frozen=True)
class MosParams:
    name: str
    vsupply: float = 2.5
    ibias: float = 40e-6
    m_diff: int = 2
    m_tail: int = 2
    m_out: int = 4
    cc_f: float = 2.0e-12
    l1_m: float = 1.4  # first-stage L in µm; CMOS-OP1 teaching length
    servo: bool = False
    servo_c: float = 1.0e-9
    servo_rin: float = 50_000.0
    servo_rleak: float = 100_000_000.0
    servo_m: int = 1
    servo_ibias: float = 20e-6
    vos_inject: float = 0.0
    dw_frac: float = 0.00185  # TIA buffer-null of teaching miller at Vin=0; not per-weight cal
    servo_dw_frac: float = 0.001487  # inverting-amp null of the miller servo at Vin=0
    temp_c: float = 27.0
    topology: str = "miller"  # miller | cascode
    linear: bool = True
    invert_gain: float = INVERT_PINNED

    @property
    def vdd(self) -> float:
        return float(self.vsupply)

    @property
    def vss(self) -> float:
        return -float(self.vsupply)

    def public(self) -> dict:
        row = asdict(self)
        row.update(
            {
                "level": 4,
                "kind": "bsim3v3_miller_tia",
                "model_nmos": str(MODEL_NMOS),
                "model_pmos": str(MODEL_PMOS),
                "model_note": (
                    "Berkeley BSIM3v3 v3.3.0 teaching cards shipped with ngspice "
                    "CMOSOpAmp. Lmin=0.35 Lmax=20 Wmin=0.6 Wmax=20 (µm). Tox=9 nm. "
                    "Not IHP SG13G2. Not silicon. L=1.4 µm from CMOS-OP1."
                ),
                "ihp_pdk_installed": False,
                "still_ideal": (
                    "Vin/Vref sources; Architecture-A invert VCVS; optional ReLU "
                    "B-source; ideal Ibias for MOS mirrors; servo/TIA capacitors "
                    "are lumped (not MIM layout)."
                ),
            }
        )
        return row


def mos_include_block() -> list[str]:
    n = MODEL_NMOS.resolve().as_posix()
    p = MODEL_PMOS.resolve().as_posix()
    return [
        "* Experiment 26 MOS primitive. Models included, not copied.",
        f".include \"{n}\"",
        f".include \"{p}\"",
        "",
        ".subckt NCH D G S B W=1u L=1.4u m=1",
        "MN1 D G S B N1 W={W} L={L} M={m} AS={3*L*W} AD={3*L*W} PS={6*L+W} PD={6*L+W}",
        ".ends NCH",
        "",
        ".subckt PCH D G S B W=1u L=1.4u m=1",
        "MP1 D G S B P1 W={W} L={L} M={m} AS={3*L*W} AD={3*L*W} PS={6*L+W} PD={6*L+W}",
        ".ends PCH",
        "",
        "* Two-stage Miller CMOS OTA. Topology from ngspice CMOS-OP1, dual supply.",
        "* Bodies to rails. Analog ground is node 0.",
        ".subckt miller_tia inp inn out vdd vss",
        f".param L={L_TEACH_M}u WD={W_DIFF_M}u WT={W_TAIL_M}u WL={W_LOAD_M}u",
        f"+ WOP={W_OUTP_M}u WON={W_OUTN_M}u WDI={W_DIODE_M}u",
        "+ MD=2 MT=2 MO=4 CC=2p IBIAS=40u DW=0 L1=1.4u",
        "Ibias vdd vb {IBIAS}",
        "Xdiode vb vb vss vss NCH W={WDI} L={L} m={MT}",
        "Xtail vs vb vss vss NCH W={WT} L={L} m={MT}",
        "* Diode load on IN- drain (CMOS-OP1 polarity). DW unbalances the pair.",
        "Xdp dplus inp vs vss NCH W={WD*(1+DW)} L={L1} m={MD}",
        "Xdn dmin inn vs vss NCH W={WD*(1-DW)} L={L1} m={MD}",
        "Xln dmin dmin vdd vdd PCH W={WL} L={L1} m={MD}",
        "Xlp dplus dmin vdd vdd PCH W={WL} L={L1} m={MD}",
        "Xop out dplus vdd vdd PCH W={WOP} L={L} m={MO}",
        "Xon out vb vss vss NCH W={WON} L={L} m={MO}",
        "Cc dplus out {CC}",
        ".ends miller_tia",
        "",
        "* Telescopic-cascode first stage + Miller CS. Higher DC gain for o2 load.",
        ".subckt miller_cascode inp inn out vdd vss",
        f".param L={L_TEACH_M}u WD={W_DIFF_M}u WT={W_TAIL_M}u WL={W_LOAD_M}u",
        f"+ WOP={W_OUTP_M}u WON={W_OUTN_M}u WDI={W_DIODE_M}u WC={W_DIFF_M}u",
        "+ MD=2 MT=2 MO=4 CC=2p IBIAS=40u DW=0",
        "Ibias vdd vb {IBIAS}",
        "Xdiode vb vb vss vss NCH W={WDI} L={L} m={MT}",
        "Xstack vcn vcn vb vss NCH W={WDI} L={L} m={MT}",
        "Xtail vs vb vss vss NCH W={WT} L={L} m={MT}",
        "Xdp splus inp vs vss NCH W={WD*(1+DW)} L={L} m={MD}",
        "Xdn smin inn vs vss NCH W={WD*(1-DW)} L={L} m={MD}",
        "Xcn dplus vcn splus vss NCH W={WC} L={L} m={MD}",
        "Xcm dmin vcn smin vss NCH W={WC} L={L} m={MD}",
        "Xln dmin dmin vdd vdd PCH W={WL} L={L} m={MD}",
        "Xlp dplus dmin vdd vdd PCH W={WL} L={L} m={MD}",
        "Xop out dplus vdd vdd PCH W={WOP} L={L} m={MO}",
        "Xon out vb vss vss NCH W={WON} L={L} m={MO}",
        "Cc dplus out {CC}",
        ".ends miller_cascode",
        "",
        "* 5-transistor OTA used as a slow integrator (capacitive load).",
        ".subckt servo_ota inp inn out vdd vss",
        f".param L={L_TEACH_M}u WD={W_DIFF_M}u WT={W_TAIL_M}u WL={W_LOAD_M}u",
        "+ MD=1 MT=1 IBIAS=2u DW=0",
        "Ibias vdd vb {IBIAS}",
        "Xdiode vb vb vss vss NCH W={WT} L={L} m={MT}",
        "Xtail vs vb vss vss NCH W={WT} L={L} m={MT}",
        "Xdp dplus inp vs vss NCH W={WD*(1+DW)} L={L} m={MD}",
        "Xdn dmin inn vs vss NCH W={WD*(1-DW)} L={L} m={MD}",
        "Xlp dplus dplus vdd vdd PCH W={WL} L={L} m={MD}",
        "Xln out dplus vdd vdd PCH W={WL} L={L} m={MD}",
        ".ends servo_ota",
        "",
    ]


def mos_area_proxy_m2(params: MosParams) -> dict:
    """Drawn W*L * m, µm². Not silicon area."""
    l = L_TEACH_M
    tia = (
        params.m_tail * W_DIODE_M * l
        + params.m_tail * W_TAIL_M * l
        + params.m_diff * W_DIFF_M * l * 2
        + params.m_diff * W_LOAD_M * l * 2
        + params.m_out * W_OUTP_M * l
        + params.m_out * W_OUTN_M * l
    )
    servo = 0.0
    if params.servo:
        servo = (
            params.servo_m * W_DIODE_M * l
            + params.servo_m * W_TAIL_M * l
            + params.servo_m * W_DIFF_M * l * 2
            + params.servo_m * W_LOAD_M * l * 2
        )
    return {
        "tia_WL_um2": tia,
        "servo_WL_um2": servo,
        "total_WL_um2": tia + servo,
        "n_mos_tia": 2 + 2 * params.m_diff + params.m_out,  # crude count of instances
        "note": "sum of drawn W*L*m on the teaching card. Not die area, not fill, not wells.",
    }


def compile_fabric(n_src, wrow, bias, g_weight, banks, linear=True, tag=TAG):
    net, cat, reason = generate_isolated_neuron(
        n_src, wrow, bias, g_weight, banks,
        VGParams(name="fab", invert_gain=INVERT_PINNED, linear=linear, vos=0.0),
        tag=tag,
    )
    return net, cat, reason


def replace_tia_with_mos(netlist: str, params: MosParams, tag=TAG) -> str:
    """Replace E/B TIA with miller_tia. Keep Rf and the resistor fabric."""
    out: list[str] = []
    inserted = False
    n_rep = 0
    vg_node = f"{tag}p"
    drv = f"{tag}lin"
    for raw in netlist.splitlines():
        s = raw.strip()
        if not inserted and s and not s.startswith("*"):
            out.extend(mos_include_block())
            out += [
                f"* Experiment 26 device TIA  VDD={params.vdd:g} VSS={params.vss:g}",
                f"* Ibias={params.ibias:g} m_diff={params.m_diff} m_out={params.m_out} Cc={params.cc_f:g}",
                f"* servo={params.servo} vos_inject={params.vos_inject:g} dw_frac={params.dw_frac:g}",
                "* Weights were not edited. SPICE is not Python-corrected.",
                f"Vdd vdd 0 DC {params.vdd:.15g}",
                f"Vss vss 0 DC {params.vss:.15g}",
                f".temp {params.temp_c:.15g}",
                ".options reltol=1e-6 abstol=1e-12 vntol=1e-8",
                "",
            ]
            inserted = True
        m_e = E_TIA.match(s)
        m_b = B_TIA.match(s)
        if m_e:
            drv = m_e.group(3)
            vg_node = m_e.group(4)
            n_rep += 1
            continue
        if m_b:
            drv = m_b.group(3)
            found = B_VOS.search(s)
            vg_node = found.group(1) if found else f"{tag}p"
            n_rep += 1
            continue
        out.append(raw)
    if n_rep == 0:
        raise RuntimeError("device_neuron: no E/B TIA to replace")
    plus = f"{tag}osp"
    srv = f"{tag}srv"
    inn = f"{tag}inn"
    sub = "miller_cascode" if params.topology == "cascode" else "miller_tia"
    l1_arg = "" if params.topology == "cascode" else f" L1={params.l1_m}u"
    inst = [
        "",
        f"* MOS TIA + optional MOS servo. IN- sense at {vg_node} (sum). OUT = {drv}.",
        f"* TIA subckt={sub} topology={params.topology}",
        f"* V{tag}ib is a 0 V ammeter: i(V{tag}ib) = current from sum into MOS IN-.",
        f"V{tag}ib {vg_node} {inn} DC 0",
        f"Vosinj {plus} {srv} DC {float(params.vos_inject):.15g}",
        (
            f"X{tag}tia {plus} {inn} {drv} vdd vss {sub} "
            f"MD={params.m_diff} MT={params.m_tail} MO={params.m_out} "
            f"CC={params.cc_f:.15g} IBIAS={params.ibias:.15g} "
            f"DW={params.dw_frac:.15g}{l1_arg}"
        ),
    ]
    if params.servo:
        # MOS miller leaky integrator (same BSIM devices). 5T OTA output cannot
        # sit at analog ground 0; the two-stage miller can (buffer test).
        rin = float(params.servo_rin)
        rleak = float(params.servo_rleak)  # DC servo gain Rin:Rleak
        inst += [
            f"* MOS miller leaky integrator servo: tau~Rin*C={rin * params.servo_c:.3g} s",
            f"R{tag}si {vg_node} {tag}sint {rin:.15g}",
            f"C{tag}int {tag}sint {srv} {params.servo_c:.15g}",
            f"R{tag}leak {tag}sint {srv} {rleak:.15g}",
            (
                f"X{tag}srv 0 {tag}sint {srv} vdd vss miller_tia "
                f"MD={max(params.servo_m, 2)} MT={max(params.servo_m, 2)} MO={max(params.servo_m * 4, 4)} "
                f"CC={params.cc_f:.15g} IBIAS={params.servo_ibias:.15g} DW={params.servo_dw_frac:.15g}"
            ),
            f".ic v({srv})=0",
        ]
    else:
        inst.append(f"R{tag}srv {srv} 0 1e3")
    # splice instances before .control
    final: list[str] = []
    placed = False
    for line in out:
        if (not placed) and line.strip().lower().startswith(".control"):
            final.extend(inst)
            final.append("")
            placed = True
        final.append(line)
    if not placed:
        final.extend(inst)
    ending = "\n" if netlist.endswith("\n") else ""
    return "\n".join(final) + ending


def compile_device_iso(n_src, wrow, bias, g_weight, banks, params: MosParams, tag=TAG):
    net, cat, reason = compile_fabric(
        n_src, wrow, bias, g_weight, banks, linear=params.linear, tag=tag
    )
    if reason or net is None:
        return None, cat, reason
    net = replace_tia_with_mos(net, params, tag=tag)
    return net, cat, None


def n_units_for_r(r: float, r_unit: float = R_UNIT) -> int:
    r = max(float(r), 1.0)
    if r >= r_unit:
        return max(1, int(round(r / r_unit)))
    return max(1, int(round(r_unit / r)))


def tiling_catalog(cat: list[dict], r_unit: float = R_UNIT) -> dict:
    n_tot = 0
    rows = []
    for item in cat:
        r = float(item["R"])
        n = n_units_for_r(r, r_unit)
        n_tot += n
        rows.append({"name": item["name"], "R": r, "n_units": n})
    return {
        "r_unit_ohm": r_unit,
        "n_resistors_logical": len(cat),
        "n_unit_elements": n_tot,
        "mismatch_sigma_reduction": (
            "each logical R perturbed with tol/sqrt(n_units); "
            "this is a statistical tiling model, not extracted layout"
        ),
    }


def sample_tiled_resistors(cat, tolerance, rng, r_unit=R_UNIT):
    """Uniform local mismatch with tiling reduction. Not a foundry mismatch PDF."""
    values = {}
    for item in cat:
        n = n_units_for_r(float(item["R"]), r_unit)
        sig = float(tolerance) / math.sqrt(n) if tolerance > 0 else 0.0
        u = float(rng.uniform(-sig, sig)) if sig > 0 else 0.0
        values[str(item["name"])] = float(item["R"]) * (1.0 + u)
    return values


def op_control(nodes: list[str], extra_prints: list[str] | None = None) -> str:
    lines = [".control", "set numdgt=15", "op"]
    for n in nodes:
        lines.append(f"print v({n})")
    for p in extra_prints or []:
        lines.append(f"print {p}")
    lines.extend([".endc", "", ".end", ""])
    return "\n".join(lines)


def ac_control(vin_name: str, out_node: str, vg_node: str) -> str:
    return "\n".join(
        [
            ".control",
            "set numdgt=15",
            "ac dec 20 1 100Meg",
            f"print v({out_node})",
            f"print v({vg_node})",
            ".endc",
            "",
            ".end",
            "",
        ]
    )


def tran_control(
    nodes: list[str],
    tstep: float,
    tstop: float,
    wrpath: Path,
    uic=False,
    extra_traces: list[str] | None = None,
) -> str:
    uic_s = " uic" if uic else ""
    traces = [f"v({n})" for n in nodes] + list(extra_traces or [])
    lines = [
        ".control",
        "set numdgt=15",
        "set wr_singlescale",
        f"tran {tstep:.15g} {tstop:.15g}{uic_s}",
        f"wrdata {wrpath.name} " + " ".join(traces),
    ]
    for n in nodes:
        lines.append(f"print v({n})")
    for tr in extra_traces or []:
        lines.append(f"print {tr}")
    lines.extend([".endc", "", ".end", ""])
    return "\n".join(lines)


def parse_wrdata(path: Path, n_nodes: int):
    if not path.exists():
        return None, f"missing wrdata {path}"
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or s.startswith("*"):
            continue
        parts = s.replace(",", " ").split()
        try:
            vals = [float(p) for p in parts]
        except ValueError:
            continue
        if vals:
            rows.append(vals)
    if not rows:
        return None, "empty wrdata"
    arr = np.array(rows, dtype=float)
    if arr.shape[1] == n_nodes + 1:
        return arr, None
    if arr.shape[1] == 2 * n_nodes:
        cols = [arr[:, 2 * i + 1] for i in range(n_nodes)]
        return np.column_stack([arr[:, 0]] + cols), None
    return None, f"wrdata cols={arr.shape[1]}"


def open_loop_amp_netlist(params: MosParams) -> str:
    """Unity-gain buffer + TF + small DC sweep. No neural fabric."""
    lines = [
        "* Experiment 26 miller_tia open-loop / buffer characterization",
        *mos_include_block(),
        f"Vdd vdd 0 DC {params.vdd:.15g}",
        f"Vss vss 0 DC {params.vss:.15g}",
        f".temp {params.temp_c:.15g}",
        "Vin inp 0 DC 0 AC 1",
        (
            f"Xbuf inp inn out vdd vss miller_tia "
            f"MD={params.m_diff} MT={params.m_tail} MO={params.m_out} "
            f"CC={params.cc_f:.15g} IBIAS={params.ibias:.15g} DW={params.dw_frac:.15g}"
        ),
        "* unity-gain buffer: inn tied to out",
        "Rfb out inn 1",
        "Cl out 0 1p",
        "",
        ".control",
        "set numdgt=15",
        "op",
        "print v(out)",
        "print v(inn)",
        "print i(Vdd)",
        "print i(Vss)",
        "tf v(out) Vin",
        "ac dec 20 1 100Meg",
        "print v(out)",
        ".endc",
        ".end",
        "",
    ]
    return "\n".join(lines)


def tf_gain_from_text(text: str) -> float | None:
    """Parse ngspice `transfer_function` / `output_impedance` block."""
    m = re.search(
        r"transfer_function\s*=\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)",
        text,
        re.I,
    )
    if m:
        return float(m.group(1))
    return None


def buffer_netlist(params: MosParams, vin: float, ac: bool = False) -> str:
    """Unity-gain buffer. Still LEVEL 4 teaching-card MOS. No neural fabric."""
    ac_line = "Vin inp 0 DC 0 AC 1" if ac else f"Vin inp 0 DC {vin:.15g}"
    ctrl = [
        ".control",
        "set numdgt=15",
        "op",
        "print v(out)",
        "print v(inn)",
        "print i(Vdd)",
        "print i(Vss)",
    ]
    if ac:
        ctrl += [
            "tf v(out) Vin",
            "ac dec 20 1 100Meg",
            "print v(out)",
        ]
    ctrl += [".endc", ".end", ""]
    return "\n".join(
        [
            "* Experiment 26 miller unity-gain buffer characterization",
            *mos_include_block(),
            f"Vdd vdd 0 DC {params.vdd:.15g}",
            f"Vss vss 0 DC {params.vss:.15g}",
            f".temp {params.temp_c:.15g}",
            ac_line,
            (
                f"Xbuf inp inn out vdd vss miller_tia "
                f"MD={params.m_diff} MT={params.m_tail} MO={params.m_out} "
                f"CC={params.cc_f:.15g} IBIAS={params.ibias:.15g} "
                f"DW={params.dw_frac:.15g} L1={params.l1_m}u"
            ),
            "Rfb out inn 1",
            "Cl out 0 1p",
            "",
            *ctrl,
        ]
    )


def simple_tia_netlist(params: MosParams, vin: float, rf: float, rin: float) -> str:
    """Single-resistor TIA, no frozen fabric. Behavioral comparison aid."""
    return "\n".join(
        [
            "* Experiment 26 simple MOS TIA (not the o2 fabric)",
            *mos_include_block(),
            f"Vdd vdd 0 DC {params.vdd:.15g}",
            f"Vss vss 0 DC {params.vss:.15g}",
            f".temp {params.temp_c:.15g}",
            f"Vin in 0 DC {vin:.15g}",
            f"Rin in vg {rin:.15g}",
            f"Rf out vg {rf:.15g}",
            "Vosinj osp srv DC 0",
            "Rsrv srv 0 1e3",
            (
                f"Xtia osp vg out vdd vss miller_tia "
                f"MD={params.m_diff} MT={params.m_tail} MO={params.m_out} "
                f"CC={params.cc_f:.15g} IBIAS={params.ibias:.15g} "
                f"DW={params.dw_frac:.15g} L1={params.l1_m}u"
            ),
            "",
            ".control",
            "set numdgt=15",
            "op",
            "print v(out)",
            "print v(vg)",
            "print i(Vdd)",
            ".endc",
            ".end",
            "",
        ]
    )


def loop_gain_netlist(params: MosParams) -> str:
    """DC-closed / AC-open miller characterization (L-break). Not a PDK GM/ID."""
    return "\n".join(
        [
            "* Experiment 26 miller L-break loop-ish AC (teaching card)",
            "* Lfb shorts out->inn at DC (unity buffer). AC: L open, inn AC-grounded via Vcm.",
            *mos_include_block(),
            f"Vdd vdd 0 DC {params.vdd:.15g}",
            f"Vss vss 0 DC {params.vss:.15g}",
            f".temp {params.temp_c:.15g}",
            "Vcm inn 0 DC 0",
            "Vin inp 0 DC 0 AC 1",
            (
                f"Xamp inp inn out vdd vss miller_tia "
                f"MD={params.m_diff} MT={params.m_tail} MO={params.m_out} "
                f"CC={params.cc_f:.15g} IBIAS={params.ibias:.15g} "
                f"DW={params.dw_frac:.15g} L1={params.l1_m}u"
            ),
            "Rout out 0 100k",
            "Cl out 0 1p",
            "",
            ".control",
            "set numdgt=15",
            "op",
            "print v(out)",
            "print v(inn)",
            "dc Vin -1m 1m 50u",
            "print v(out)",
            "ac dec 20 1 100Meg",
            "print v(out)",
            ".endc",
            ".end",
            "",
        ]
    )
