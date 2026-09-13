"""Experiment 23: documented virtual-ground primitives.

Does not retrain, edit weights, or correct SPICE outputs.
Does not copy manufacturer netlists into this repository; LEVEL 3
models are included from the local ngspice examples tree.

Candidates
----------
O-VF   XSPICE OTA used as a voltage-gain block (gm * rout = A, low rout)
O-hiZ  XSPICE OTA with high rout (physical 1-stage OTA; Rf shunts gain)
L      XSPICE limit: finite A, input offset, output rails
OPA171 TI Green-Williams-Lis macromodel (local ngspice example)
MCP6041 Microchip macromodel (local ngspice example; 6 V part)

LEVEL: O-VF / O-hiZ / L = 2 structured. OPA171 / MCP6041 = 3 macromodel.
Not LEVEL 4–6. Not board power. Not silicon.
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


CIRCUIT_DIR = PROJECT_ROOT / "circuits" / "virtual_ground_primitive"
NG_EXAMPLES = Path(r"C:\ngspice\examples\p-to-n-examples")
OPA171_PATH = NG_EXAMPLES / "OPA171.txt"
MCP6041_PATH = NG_EXAMPLES / "MCP6041.txt"

E_TIA = re.compile(
    r"^(E)(\S+tia)\s+(\S+)\s+0\s+0\s+(\S+)\s+(\S+)\s*$",
    re.IGNORECASE,
)
B_TIA = re.compile(
    r"^(B)(\S+tia)\s+(\S+)\s+0\s+V\s*=\s*.*$",
    re.IGNORECASE,
)
B_VOS = re.compile(
    r"v\((\S+)\)\s*-\s*\(([^)]+)\)",
    re.IGNORECASE,
)


CANDIDATES = {
    "O-VF": {
        "level": 2,
        "kind": "xspice_ota_voltage",
        "title": "XSPICE OTA as voltage-gain TIA (A = gm*rout, rout=1 ohm)",
        "source": "ngspice built-in analog code model `ota`",
        "note": (
            "A 1-stage OTA driving Rf would collapse to A~gm*Rf. "
            "O-VF sets rout=1 ohm so A=gm*rout survives Rf. That is a "
            "voltage op-amp equivalent, not a high-Z OTA."
        ),
        "needs_ps": False,
        "has_dynamics": False,
        "has_inherent_vos": False,
    },
    "O-hiZ": {
        "level": 2,
        "kind": "xspice_ota_hiz",
        "title": "XSPICE OTA high-Z (gm=1 mS, rout=1e12)",
        "source": "ngspice built-in analog code model `ota`",
        "note": "Physical single-stage OTA. Rf shunts rout. Expected VG failure.",
        "needs_ps": False,
        "has_dynamics": False,
        "has_inherent_vos": False,
    },
    "L": {
        "level": 2,
        "kind": "xspice_limit",
        "title": "XSPICE limit (finite A, in_offset, output rails)",
        "source": "ngspice built-in analog code model `limit`",
        "note": "Same DC TIA identity as Exp 17 VCVS, with explicit rails.",
        "needs_ps": False,
        "has_dynamics": False,
        "has_inherent_vos": False,
    },
    "OPA171": {
        "level": 3,
        "kind": "macro_opa171",
        "title": "TI OPA171 Green-Williams-Lis macromodel",
        "source": str(OPA171_PATH),
        "note": (
            "Not copied into this repo. Included from ngspice examples. "
            "36 V-class; model Vos ~214 uV. Requires ngbehavior=ps. "
            "A 1 pF output capacitor is added so the GWL operating-point "
            "analysis exists on this loaded TIA; that is not a datasheet CL."
        ),
        "needs_ps": True,
        "has_dynamics": True,
        "has_inherent_vos": True,
        "model_vos_V": 214.023e-6,
    },
    "MCP6041": {
        "level": 3,
        "kind": "macro_mcp6041",
        "title": "Microchip MCP6041 macromodel",
        "source": str(MCP6041_PATH),
        "note": (
            "Not copied into this repo. 6 V CMOS op-amp. Negative control "
            "for rails / GBW / offset versus Exp 22."
        ),
        "needs_ps": False,
        "has_dynamics": True,
        "has_inherent_vos": True,
    },
}


@dataclass(frozen=True)
class PrimParams:
    candidate: str
    name: str
    amp_gain: float = 1e5
    invert_gain: float = INVERT_PINNED
    rail: float = 15.0
    vos: float = 0.0
    vos_trim: float = 0.0
    i_leak: float = 0.0
    linear: bool = True
    vsupply: float = 15.0
    ota_rout: float = 1.0

    def vg(self) -> VGParams:
        return VGParams(
            name=self.name,
            amp_gain=self.amp_gain,
            invert_gain=self.invert_gain,
            rail=self.rail,
            vos=0.0,
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
            vos=0.0,
            i_leak=self.i_leak,
            linear=self.linear,
            clip_amp=False,
        )

    def public(self) -> dict:
        meta = CANDIDATES[self.candidate]
        row = asdict(self)
        row.update({k: meta[k] for k in meta})
        return row


def run_ngspice_ex(
    ngspice: Path,
    circuit: Path,
    timeout: float | None = None,
    pspice: bool = False,
):
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
    name = dev[1:] if dev[:1].upper() in "EB" else dev
    if name.lower().endswith("tia"):
        name = name[:-3]
    return name


def _plus_node(stem: str) -> str:
    return f"{stem}osp"


def emit_tia_block(
    stem: str,
    drv: str,
    vg: str,
    params: PrimParams,
) -> list[str]:
    kind = CANDIDATES[params.candidate]["kind"]
    plus = _plus_node(stem)
    vplus = float(params.vos) + float(params.vos_trim)
    lines = [
        f"* Exp 23 {params.candidate} TIA {stem} -> {drv}, vg={vg}",
        f"V{stem}os {plus} 0 DC {vplus:.15g}",
    ]
    if kind == "xspice_ota_voltage":
        gm = float(params.amp_gain) / max(float(params.ota_rout), 1e-18)
        lines.append(f"A{stem}tia {plus} {vg} {drv} otavf")
        lines.append(
            f"* A={params.amp_gain:g} = gm*rout, gm={gm:g}, rout={params.ota_rout:g}"
        )
    elif kind == "xspice_ota_hiz":
        lines.append(f"A{stem}tia {plus} {vg} {drv} otahiz")
    elif kind == "xspice_limit":
        lines.append(f"A{stem}tia %vd({plus} {vg}) {drv} limtia")
    elif kind == "macro_opa171":
        lines.append("* 1 pF output C so GWL OP exists; not a datasheet CL guarantee")
        lines.append(f"X{stem}tia {plus} {vg} vdd vss {drv} OPA171")
        lines.append(f"C{stem}load {drv} 0 1p")
    elif kind == "macro_mcp6041":
        lines.append(f"X{stem}tia {plus} {vg} vdd vss {drv} MCP6041")
    else:
        raise ValueError(kind)
    return lines


def global_preamble(params: PrimParams) -> list[str]:
    kind = CANDIDATES[params.candidate]["kind"]
    lines = [
        f"* Experiment 23 candidate {params.candidate}",
        f"* {CANDIDATES[params.candidate]['title']}",
        f"* source: {CANDIDATES[params.candidate]['source']}",
        f"* {CANDIDATES[params.candidate]['note']}",
        "* Weights were not edited. SPICE is not Python-corrected.",
    ]
    if kind == "macro_opa171":
        lines.append(f'.include "{OPA171_PATH.as_posix()}"')
    elif kind == "macro_mcp6041":
        lines.append(f'.include "{MCP6041_PATH.as_posix()}"')
    if kind in {"macro_opa171", "macro_mcp6041"}:
        vs = float(params.vsupply)
        lines.append(f"Vdd vdd 0 DC {vs:.15g}")
        lines.append(f"Vss vss 0 DC {-vs:.15g}")
    if kind == "xspice_ota_voltage":
        gm = float(params.amp_gain) / max(float(params.ota_rout), 1e-18)
        lines.append(
            f".model otavf ota (gm={gm:.15g} rout={float(params.ota_rout):.15g} rin=1e12)"
        )
    elif kind == "xspice_ota_hiz":
        lines.append(".model otahiz ota (gm=1e-3 rout=1e12 rin=1e12)")
    elif kind == "xspice_limit":
        lo, hi = -abs(float(params.rail)), abs(float(params.rail))
        lines.append(
            f".model limtia limit(gain={float(params.amp_gain):.15g} "
            f"in_offset=0.0 out_lower_limit={lo:.15g} "
            f"out_upper_limit={hi:.15g} fraction=false limit_range=0.05)"
        )
    return lines


def replace_behavioral_tias(netlist: str, params: PrimParams) -> str:
    """Replace E/B *tia voltage sources. Leave Rf and leak sources."""
    pre = global_preamble(params)
    out: list[str] = []
    inserted_pre = False
    n_rep = 0
    for raw in netlist.splitlines():
        s = raw.strip()
        if not inserted_pre and s and not s.startswith("*"):
            out.extend(pre)
            out.append("")
            inserted_pre = True
        m_e = E_TIA.match(s)
        m_b = B_TIA.match(s)
        if m_e:
            _kind, dev, drv, vg, _a = m_e.groups()
            out.extend(emit_tia_block(_stem(dev), drv, vg, params))
            n_rep += 1
            continue
        if m_b:
            _kind, dev, drv = m_b.group(1), m_b.group(2), m_b.group(3)
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


def isolated_neuron(n_src, wrow, bias, g_weight, banks, params: PrimParams, tag="n1"):
    net, cat, reason = generate_isolated_neuron(
        n_src, wrow, bias, g_weight, banks, params.vg(), tag=tag
    )
    if reason or net is None:
        return None, cat, reason
    return replace_behavioral_tias(net, params), cat, None


def compile_network(spec, weights, params: PrimParams, linear: bool | None = None):
    p = params.iv()
    if linear is not None:
        p = IVParams(
            name=p.name, amp_gain=p.amp_gain, invert_gain=p.invert_gain,
            rail=p.rail, vos=0.0, i_leak=p.i_leak, linear=linear,
        )
    net, cat, reason = compile_iv("A", spec, weights, p)
    if reason or net is None:
        return None, cat, reason
    return replace_behavioral_tias(net, params), cat, None


def candidate_needs_ps(name: str) -> bool:
    return bool(CANDIDATES[name]["needs_ps"])


VIN_DC = re.compile(r"^(Vin(\d+)\s+\S+\s+0\s+DC)\s+\S+", re.IGNORECASE | re.MULTILINE)


def bake_vin_dc(netlist: str, x) -> str:
    """Write the stimulus into Vin DC sources. One netlist = one operating point.

    GWL OPA171 can fail `alter` continuation on this loaded TIA even when the
    same DC sources in the netlist OP successfully. Baking Vin is the DC
    circuit under that vector, not a Python correction of Vlin.
    """
    vec = np.atleast_1d(np.asarray(x, dtype=float))

    def repl(m: re.Match) -> str:
        i = int(m.group(2))
        val = float(vec[i - 1]) if i <= len(vec) else 0.0
        return f"{m.group(1)} {val:.15g}"

    return VIN_DC.sub(repl, netlist)


def simple_op_control(nodes: list[str]) -> str:
    # GWL OPA171 on this loaded TIA aborted when control-section
    # rshunt/gmin/itl1 were set. Bare `op` is the documented DC analysis.
    lines = [
        ".control",
        "set numdgt=15",
        "op",
    ]
    for n in nodes:
        lines.append(f"print v({n})")
    lines.extend([".endc", "", ".end", ""])
    return "\n".join(lines)


def _alter_inputs(x, n_in: int) -> list[str]:
    lines = []
    for i, xi in enumerate(np.atleast_1d(x), start=1):
        if i > n_in:
            break
        lines.append(f"alter Vin{i} DC {float(xi):.15g}")
    return lines


def isolated_op_control(inputs, n_in: int, tag: str = "n1") -> str:
    """Independent DC OP per vector, homotoped from Vin=0.

    GWL OPA171 often solves the zero-input TIA and fails a cold OP at a
    large neural vector (singular cl_clamp). Ramp 0 -> 0.5 x -> x after
    reset. Not a Python correction of the settled voltages.
    """
    lines = [
        ".control",
        "set numdgt=15",
        "option reltol=1e-4",
        "option gmin=1e-11",
        "option rshunt=1e12",
        "option itl1=400",
    ]
    for x in inputs:
        lines.append("reset")
        lines.append("op")
        half = 0.5 * np.atleast_1d(x).astype(float)
        lines.extend(_alter_inputs(half, n_in))
        lines.append("op")
        lines.extend(_alter_inputs(x, n_in))
        lines.append("op")
        lines.append(f"print v({tag}lin)")
        lines.append(f"print v({tag}p)")
    lines.extend([".endc", "", ".end", ""])
    return "\n".join(lines)


def network_op_control(inputs, n_out: int) -> str:
    lines = [
        ".control",
        "set numdgt=15",
        "option reltol=1e-4",
        "option gmin=1e-11",
        "option rshunt=1e12",
        "option itl1=400",
    ]
    for x in inputs:
        n_in = len(np.atleast_1d(x))
        lines.append("reset")
        lines.append("op")
        half = 0.5 * np.atleast_1d(x).astype(float)
        lines.extend(_alter_inputs(half, n_in))
        lines.append("op")
        lines.extend(_alter_inputs(x, n_in))
        lines.append("op")
        for k in range(1, n_out + 1):
            lines.append(f"print v(o{k}lin)")
    lines.extend([".endc", "", ".end", ""])
    return "\n".join(lines)
