"""Experiment 25: finite-dynamic summing-node servo (LEVEL 2).

OTA-C leaky integrator on Vsum driving TIA IN+. Explicit R and C.
Not transistor-level. Frozen weights are not edited. SPICE is not
Python-corrected.

tau_servo = C / gm.  Exp 24 used gm=1e-3, C=1e-6, Rleak=1e9 (tau=1 ms).
"""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from compile_xor import PROJECT_ROOT
from offset_vg_search import (
    E24Params,
    VIN_DC,
    bake_vin_dc,
    bake_vin_pulse,
    bake_vref_pulse,
    compile_isolated,
    compile_network,
    run_ngspice_ex,
)
from virtual_ground_requirements import INVERT_PINNED


CIRCUIT_DIR = PROJECT_ROOT / "circuits" / "servo_transient"
RESULTS_DIR = PROJECT_ROOT / "results"
TAG = "n1"
VOS_214 = 214.023e-6
ERROR_LIMIT = 1e-3
EXP24_GM = 1e-3
EXP24_C = 1e-6
EXP24_R = 1e9

A_TIA = re.compile(
    r"^(A)(\S+tia)\s+%vd\((\S+)\s+(\S+)\)\s+(\S+)\s+(\S+)\s*$",
    re.IGNORECASE,
)
V_OS = re.compile(
    r"^(V)(\S+)os\s+(\S+)\s+0\s+DC\s+(\S+)\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class E25Params:
    name: str
    amp_gain: float = 1e5
    invert_gain: float = INVERT_PINNED
    rail: float = 15.0
    vos: float = 0.0
    i_leak: float = 0.0
    linear: bool = True
    servo: bool = True
    servo_gm: float = EXP24_GM
    servo_c: float = EXP24_C
    servo_r: float = EXP24_R
    tia_pole_hz: float = 0.0
    autozero: bool = False
    gate_vref: bool = False
    t_az: float = 2e-5
    t_stop: float = 8e-5

    @property
    def tau_s(self) -> float:
        g = max(float(self.servo_gm), 1e-18)
        return float(self.servo_c) / g

    def e24(self) -> E24Params:
        return E24Params(
            candidate="L",
            name=self.name,
            amp_gain=self.amp_gain,
            invert_gain=self.invert_gain,
            rail=self.rail,
            vos=self.vos,
            i_leak=self.i_leak,
            linear=self.linear,
            autozero=self.autozero,
            servo=False,
            gate_vref=self.gate_vref,
            t_az=self.t_az,
            t_stop=self.t_stop,
            servo_gm=self.servo_gm,
            servo_c=self.servo_c,
        )

    def public(self) -> dict:
        row = asdict(self)
        row["tau_s"] = self.tau_s
        row["ft_integrator_hz"] = float(self.servo_gm) / (
            2.0 * math.pi * max(float(self.servo_c), 1e-30)
        )
        row["dc_gain_vsum_to_int"] = float(self.servo_gm) * float(self.servo_r)
        row["level"] = 2
        row["kind"] = "ota_c_leaky_integrator"
        row["note"] = (
            "LEVEL 2 OTA-C servo: I=gm*Vsum onto C, leak R, Vplus=Vos+Vint. "
            "Not a device op-amp. tau=C/gm."
        )
        return row


def _stem(dev: str) -> str:
    name = dev[1:] if dev[:1].upper() in "EBX" else dev
    if name.lower().endswith("tia"):
        name = name[:-3]
    return name


def apply_servo_dynamic(netlist: str, params: E25Params) -> str:
    """OTA-C leaky integrator: dVint/dt = -(gm/C) Vsum - Vint/(R C)."""
    out: list[str] = []
    inserted = False
    stems: list[str] = []
    n = 0
    tau = params.tau_s
    for raw in netlist.splitlines():
        s = raw.strip()
        if not inserted and s and not s.startswith("*"):
            out += [
                "* Exp 25 OTA-C servo (LEVEL 2). Finite C. Not an algebraic integrator.",
                f"* gm={params.servo_gm:.15g} C={params.servo_c:.15g} Rleak={params.servo_r:.15g}",
                f"* tau=C/gm={tau:.15g} s  DC_gain=gm*R={params.servo_gm * params.servo_r:.15g}",
                "",
            ]
            inserted = True
        m_v = V_OS.match(s)
        m_a = A_TIA.match(s)
        if m_v:
            stem = m_v.group(2)
            vos = m_v.group(4)
            out.append(f"V{stem}os {stem}osref 0 DC {vos}")
            continue
        if m_a:
            dev, plus, vg, drv, model = (
                m_a.group(2), m_a.group(3), m_a.group(4), m_a.group(5), m_a.group(6)
            )
            stem = _stem(dev)
            stems.append(stem)
            out.append(f"* servo {stem}: Vsum>0 discharges C so IN+ falls")
            out.append(
                f"G{stem}srv {stem}int 0 {vg} 0 {float(params.servo_gm):.15g}"
            )
            out.append(f"C{stem}int {stem}int 0 {float(params.servo_c):.15g}")
            out.append(f"R{stem}int {stem}int 0 {float(params.servo_r):.15g}")
            out.append(
                f"B{stem}plus {plus} 0 V = v({stem}osref) + v({stem}int)"
            )
            out.append(f"A{dev} %vd({plus} {vg}) {drv} {model}")
            n += 1
            continue
        out.append(raw)
    if n == 0:
        raise RuntimeError("servo: no limit TIA found")
    ic = [f".ic v({s}int)=0" for s in stems]
    final: list[str] = []
    placed = False
    for line in out:
        if (not placed) and line.strip().lower().startswith(".control"):
            final.extend(ic)
            final.append("")
            placed = True
        final.append(line)
    if not placed:
        final.extend(ic)
    ending = "\n" if netlist.endswith("\n") else ""
    return "\n".join(final) + ending


def compile_iso(n_src, wrow, bias, g_weight, banks, params: E25Params, tag=TAG):
    net, cat, reason = compile_isolated(
        n_src, wrow, bias, g_weight, banks, params.e24(), tag=tag
    )
    if reason or net is None:
        return None, cat, reason
    if params.servo:
        net = apply_servo_dynamic(net, params)
    if params.tia_pole_hz > 0.0:
        net = apply_tia_pole_limit(net, params.tia_pole_hz)
    return net, cat, None


def compile_net(spec, weights, params: E25Params, linear: bool | None = None):
    lin = params.linear if linear is None else linear
    p24 = params.e24()
    net, cat, reason = compile_network(spec, weights, p24, linear=lin)
    if reason or net is None:
        return None, cat, reason
    if params.servo:
        net = apply_servo_dynamic(net, params)
    if params.tia_pole_hz > 0.0:
        net = apply_tia_pole_limit(net, params.tia_pole_hz)
    return net, cat, None


def apply_tia_pole_limit(netlist: str, pole_hz: float, rpole: float = 1.0) -> str:
    """DC-preserving single-pole RC after each XSPICE limit TIA output.

    Exp 22 apply_tia_pole only matches E/B sources. After Exp 24 replacement the
    TIA is `A*tia %vd(...) drv limtia`. Behavioral; not transistor fT.
    """
    if pole_hz <= 0.0:
        return netlist
    wp = 2.0 * math.pi * float(pole_hz)
    cval = 1.0 / (float(rpole) * wp)
    out: list[str] = []
    n = 0
    for raw in netlist.splitlines():
        s = raw.strip()
        m_a = A_TIA.match(s)
        if not m_a:
            out.append(raw)
            continue
        dev, plus, vg, drv, model = (
            m_a.group(2), m_a.group(3), m_a.group(4), m_a.group(5), m_a.group(6)
        )
        if drv.lower().endswith("ampint"):
            out.append(raw)
            continue
        stem = _stem(dev)
        mid = f"{stem}ampint"
        out.append(
            f"* Exp 25 TIA pole {dev}: fp={pole_hz:g} Hz Rpole={rpole:g} "
            f"C={cval:.6g} F (behavioral RC; not transistor GBW)"
        )
        out.append(f"A{dev} %vd({plus} {vg}) {mid} {model}")
        out.append(f"R{dev}pole {mid} {drv} {float(rpole):.15g}")
        out.append(f"C{dev}pole {drv} 0 {cval:.15g}")
        n += 1
    if n == 0:
        raise RuntimeError("tia pole: no XSPICE limit TIA found")
    ending = "\n" if netlist.endswith("\n") else ""
    return "\n".join(out) + ending


def servo_int_nodes(netlist: str) -> list[str]:
    nodes = []
    for raw in netlist.splitlines():
        s = raw.strip()
        if s.upper().startswith("C") and "int" in s.lower().split()[0].lower():
            parts = s.split()
            if len(parts) >= 2:
                nodes.append(parts[1])
    return nodes


def bake_vin_pwl(netlist: str, series, t_hold: float, t_rise: float = 10e-9) -> str:
    """series: list of input vectors. Each dwells t_hold, then ramps t_rise."""
    seq = [np.atleast_1d(np.asarray(v, dtype=float)) for v in series]
    n_in = max(len(v) for v in seq)

    def repl(m: re.Match) -> str:
        i = int(m.group(2))
        prefix = m.group(1)
        name_node = prefix.rsplit(" DC", 1)[0]
        pts: list[str] = []
        t = 0.0
        for k, vec in enumerate(seq):
            val = float(vec[i - 1]) if i <= len(vec) else 0.0
            if k == 0:
                pts += [f"{t:.15g}", f"{val:.15g}"]
            else:
                t += t_rise
                pts += [f"{t:.15g}", f"{val:.15g}"]
            t += t_hold
            pts += [f"{t:.15g}", f"{val:.15g}"]
        return f"{name_node} PWL({ ' '.join(pts) })"

    return VIN_DC.sub(repl, netlist)


def op_control(nodes: list[str]) -> str:
    lines = [".control", "set numdgt=15", "op"]
    for n in nodes:
        lines.append(f"print v({n})")
    lines.extend([".endc", "", ".end", ""])
    return "\n".join(lines)


def tran_wrdata_control(
    nodes: list[str],
    t_stop: float,
    tstep: float,
    wrpath: Path,
    uic: bool = False,
    reltol: float | None = None,
) -> str:
    lines = [".control", "set numdgt=15", "set wr_singlescale"]
    if reltol is not None:
        lines.append(f"option reltol={float(reltol):.15g}")
    uic_s = " uic" if uic else ""
    lines.append(f"tran {tstep:.15g} {t_stop:.15g}{uic_s}")
    vecs = " ".join(f"v({n})" for n in nodes)
    wrname = wrpath.name if wrpath.parent == CIRCUIT_DIR else wrpath.as_posix()
    lines.append(f"wrdata {wrname} {vecs}")
    for n in nodes:
        lines.append(f"print v({n})")
    lines.extend([".endc", "", ".end", ""])
    return "\n".join(lines)


def parse_wrdata(path: Path, n_nodes: int) -> tuple[np.ndarray | None, str | None]:
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
        if not vals:
            continue
        rows.append(vals)
    if not rows:
        return None, "empty wrdata"
    arr = np.array(rows, dtype=float)
    if arr.ndim != 2:
        return None, "bad wrdata shape"
    # wr_singlescale: t, y1, y2, ...
    if arr.shape[1] == n_nodes + 1:
        return arr, None
    # paired time columns: t y1 t y2 ...
    if arr.shape[1] == 2 * n_nodes:
        t = arr[:, 0]
        cols = [arr[:, 2 * i + 1] for i in range(n_nodes)]
        return np.column_stack([t] + cols), None
    return None, f"wrdata cols={arr.shape[1]} expected {n_nodes + 1} or {2 * n_nodes}"


def choose_tstep(tau: float, t_stop: float, max_points: int = 1200) -> float:
    """Resolve ~25 samples per tau without exploding wrdata length."""
    by_tau = max(float(tau) / 25.0, 1e-10)
    by_span = float(t_stop) / 400.0
    floor = float(t_stop) / float(max(max_points, 100))
    return float(max(min(by_tau, by_span), floor, 1e-10))


def choose_tstop(tau: float, extra: float = 0.0) -> float:
    return float(max(12.0 * max(tau, 1e-9), extra + 8.0 * max(tau, 1e-9), 2e-5))


def settling_metrics(t: np.ndarray, y: np.ndarray, y_ref: float | None = None) -> dict:
    t = np.asarray(t, dtype=float)
    y = np.asarray(y, dtype=float)
    if len(t) < 4:
        return {"failed": True, "reason": "short waveform"}
    yf = float(y[-1])
    abs_e = np.abs(y - yf)
    last = max(len(y) // 5, 4)
    tail_std = float(np.std(y[-last:]))
    tail_pp = float(np.ptp(y[-last:]))
    overshoot = float(np.max(y) - yf) if yf >= 0 else float(yf - np.min(y))
    peak = float(np.max(np.abs(y)))

    def first_stay(limit: float):
        inside = abs_e <= limit
        if not np.any(inside):
            return None
        for i in range(len(inside)):
            if np.all(inside[i:]):
                return float(t[i])
        return None

    rel_lim = max(0.01 * abs(yf), 1e-6)
    t_abs = first_stay(ERROR_LIMIT)
    t_rel = first_stay(rel_lim)
    t_z = None
    if y_ref is not None:
        ez = np.abs(y - float(y_ref))
        inside = ez <= ERROR_LIMIT
        if np.any(inside):
            for i in range(len(inside)):
                if np.all(inside[i:]):
                    t_z = float(t[i])
                    break
    crossings = int(np.sum(np.diff(np.signbit(y[-last:] - yf))))
    oscillating = bool(tail_pp > 5e-3 and crossings >= 4)
    diverged = bool(peak > 20.0 or not np.isfinite(peak))
    return {
        "failed": diverged,
        "y_final": yf,
        "y_abs_max": peak,
        "overshoot_vs_final": overshoot,
        "tail_std": tail_std,
        "tail_pp": tail_pp,
        "tail_crossings": crossings,
        "oscillating": oscillating,
        "diverged": diverged,
        "t_abs_1e3_s": t_abs,
        "t_rel_1pct_s": t_rel,
        "t_vs_ref_1e3_s": t_z,
        "err_final_vs_ref": (
            None if y_ref is None else float(abs(yf - float(y_ref)))
        ),
    }
