"""Experiment 27 helpers: resistor matching and temperature on the Exp 26 MOS cell.

Frozen Experiment 9 weights. SPICE is not Python-corrected.
Statistical matching models are labeled as such — not extracted layout.
Resistor TC is not invented: default ngspice R has no TCR, so .temp is MOS-only.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

import numpy as np

from compile_xor import PROJECT_ROOT, apply_resistor_values
from device_neuron import (
    ERROR_LIMIT,
    TAG,
    MosParams,
    compile_device_iso,
    parse_wrdata,
    tran_control,
)
from mismatch_fabric import path_sign, stamp_signs
from offset_vg_search import bake_vin_dc, bake_vin_pulse, bake_vref_pulse, run_ngspice_ex
from precision_architectures import ARCH_C_CFG
from servo_transient import bake_vin_pwl


CIRCUIT_DIR = PROJECT_ROOT / "circuits" / "exp27_matching_temperature"
RESULTS_DIR = PROJECT_ROOT / "results"
TOL_05 = 0.005
T_AZ = 2.0e-4


def dest(*parts) -> Path:
    name = "_".join(
        str(p).replace(".", "p").replace("-", "m").replace("+", "p") for p in parts
    )
    CIRCUIT_DIR.mkdir(parents=True, exist_ok=True)
    return CIRCUIT_DIR / f"{name}.cir"


def compile_iso(spec, weights, pick, params: MosParams):
    hidden = pick["layer"] == 1
    idx = pick["index"]
    wrow = weights["W1"][idx] if hidden else weights["W2"][idx]
    bias = float(weights["b1"][idx] if hidden else weights["b2"][idx])
    cfg = ARCH_C_CFG["F"]
    g_w = cfg.g_weight_1 if hidden else cfg.g_weight_2
    n_src = spec["n_in"] if hidden else spec["n_hidden"]
    net, cat, reason = compile_device_iso(n_src, wrow, bias, g_w, cfg.banks, params)
    if cat:
        stamp_signs(cat)
    return net, cat, reason, n_src, wrow, bias


def classify_item(item: dict) -> str:
    role = str(item.get("role") or "")
    name = str(item.get("name") or "")
    comment = str(item.get("comment") or "").lower()
    if role == "feedback" or "feedback" in comment:
        return "feedback"
    if role == "invert" or "invert" in comment:
        return "invert"
    if role == "divider" or "div" in comment:
        return "divider"
    if role in {"bias", "reference"} or "b+" in comment or "b-" in comment:
        return "bias"
    if role in {"weight", "w"} or "w+" in comment or "w-" in comment:
        return "weight"
    if name.endswith("f") and "n1" in name:
        return "feedback"
    if role:
        return role
    return "other"


def apply_servo_replica_ref(netlist: str, params: MosParams, tag: str = TAG) -> str:
    """CASE 2: replica of the SERVO miller sets servo IN+.

    Live servo remains in the loop. Equilibrium: Vsum → Vos_rep − Vos_servo ≈ 0
    if the two millers match at temperature. Not a Python Vos table.
    """
    srv = f"{tag}srv"
    ref = f"{tag}sref"
    lines = []
    found = False
    for raw in netlist.splitlines():
        if raw.strip().startswith(f"X{tag}srv "):
            lines.append(raw.replace(f"X{tag}srv 0 {tag}sint {srv} ", f"X{tag}srv {ref} {tag}sint {srv} ", 1))
            found = True
            continue
        lines.append(raw)
    if not found:
        raise RuntimeError("apply_servo_replica_ref: servo instance not found")
    extra = [
        f"* CASE 2: servo-miller replica buffer at 0 drives servo IN+ ({ref}).",
        f"* Same DW/Ibias as the servo, not the TIA. Continuous, no clock.",
        (
            f"X{tag}srep 0 {tag}srepinn {ref} vdd vss miller_tia "
            f"MD={max(params.servo_m, 2)} MT={max(params.servo_m, 2)} "
            f"MO={max(params.servo_m * 4, 4)} "
            f"CC={params.cc_f:.15g} IBIAS={params.servo_ibias:.15g} "
            f"DW={params.servo_dw_frac:.15g}"
        ),
        f"R{tag}srepfb {ref} {tag}srepinn 1",
        f"C{tag}srepc {ref} 0 1p",
    ]
    final = []
    placed = False
    for line in lines:
        if (not placed) and line.strip().lower().startswith(".control"):
            final.extend(extra)
            final.append("")
            placed = True
        final.append(line)
    if not placed:
        final.extend(extra)
    ending = "\n" if netlist.endswith("\n") else ""
    return "\n".join(final) + ending


def apply_replica_inplus(netlist: str, params: MosParams, tag: str = TAG) -> str:
    """Deprecated finite-A path: replica on TIA IN+ with servo disconnected.

    Kept for the negative-control measurement (no live servo → A~1e3 error).
    """
    plus = f"{tag}osp"
    srv = f"{tag}srv"
    rep = f"{tag}repout"
    lines = []
    for raw in netlist.splitlines():
        s = raw.strip()
        if s.lower().startswith("vosinj "):
            lines.append(f"Vosinj {plus} {rep} DC {float(params.vos_inject):.15g}")
            continue
        lines.append(raw)
    extra = [
        f"* NEGATIVE CONTROL: replica on TIA IN+, servo unused. Finite A remains.",
        (
            f"X{tag}rep 0 {tag}repinn {rep} vdd vss miller_tia "
            f"MD={params.m_diff} MT={params.m_tail} MO={params.m_out} "
            f"CC={params.cc_f:.15g} IBIAS={params.ibias:.15g} "
            f"DW={params.dw_frac:.15g} L1={params.l1_m}u"
        ),
        f"R{tag}rpfb {rep} {tag}repinn 1",
    ]
    final = []
    placed = False
    for line in lines:
        if (not placed) and line.strip().lower().startswith(".control"):
            final.extend(extra)
            final.append("")
            placed = True
        final.append(line)
    if not placed:
        final.extend(extra)
    ending = "\n" if netlist.endswith("\n") else ""
    return "\n".join(final) + ending


def _rf_value(netlist: str, tag: str = TAG) -> float:
    for raw in netlist.splitlines():
        parts = raw.split()
        if len(parts) >= 4 and parts[0].lower() == f"r{tag}f":
            return float(parts[3])
    raise RuntimeError(f"Rf r{tag}f not found")


def apply_sum_cds(
    netlist: str,
    params: MosParams,
    t_az: float = T_AZ,
    tag: str = TAG,
) -> str:
    """CASE 3: live servo + summing-node current CDS.

    During AZ (Vin=Vref=0) an NCH samples Vlin onto C. After AZ a PCH
    connects a replica of Rf from the held voltage to the summing node.
    KCL: I_comp = Vhold/Rf ⇒ ΔVlin = −Vhold. The miller stays a TIA.
    No VCVS. No Python Vos table. Clock is the same Vazclk as the sample.
    """
    lin = f"{tag}lin"
    hold = f"{tag}hold"
    clk = f"{tag}clk"
    comp = f"{tag}comp"
    rf = _rf_value(netlist, tag)
    extra = [
        f"* Exp 27 summing-node current CDS. Sample V({lin}) until t={t_az:g}s.",
        f"* Then inject Vhold/Rf into {tag}p with a PCH + Rf replica ({rf:.15g} Ω).",
        f"* Live servo remains. Miller used as TIA, not as a voltage difference amp.",
        f"Vazclk {clk} 0 PULSE({params.vdd:.15g} {params.vss:.15g} {t_az:.15g} 10n 10n 1 2)",
        f"X{tag}azsw {lin} {clk} {hold} vss NCH W=5u L=1.4u m=8",
        f"C{tag}hold {hold} 0 2n",
        f"X{tag}csw {hold} {clk} {comp} vdd PCH W=5u L=1.4u m=8",
        f"R{tag}comp {comp} {tag}p {rf:.15g}",
    ]
    final = []
    placed = False
    for line in netlist.splitlines():
        if (not placed) and line.strip().lower().startswith(".control"):
            final.extend(extra)
            final.append("")
            placed = True
        final.append(line)
    if not placed:
        final.extend(extra)
    ending = "\n" if netlist.endswith("\n") else ""
    return "\n".join(final) + ending


def apply_cap_cds_unbuf(
    netlist: str,
    params: MosParams,
    t_az: float = T_AZ,
    tag: str = TAG,
) -> str:
    """CASE 3: live servo + unbuffered capacitive CDS.

    TIA output renamed to {tag}raw. Ccds from raw to {tag}lin. During AZ an
    NCH shorts {tag}lin to analog ground 0. After AZ, Vlin = Vraw(t)−Vraw(az).
    Output is the capacitor plate: a real node voltage, high-Z, not a driven pad.
    """
    lin = f"{tag}lin"
    raw_n = f"{tag}raw"
    clk = f"{tag}clk"
    lines = []
    for raw in netlist.splitlines():
        s = raw.strip()
        if s.startswith(f"X{tag}tia "):
            lines.append(raw.replace(f" {lin} vdd vss ", f" {raw_n} vdd vss ", 1))
            continue
        parts = s.split()
        if len(parts) >= 4 and parts[0].lower() == f"r{tag}f":
            a, b, rval = parts[1], parts[2], parts[3]
            a2 = raw_n if a == lin else a
            b2 = raw_n if b == lin else b
            lines.append(f"{parts[0]} {a2} {b2} {rval}")
            continue
        lines.append(raw)
    extra = [
        f"* Exp 27 unbuffered capacitive CDS. AZ short of {lin} until t={t_az:g}s.",
        f"* After AZ, V({lin})=V({raw_n})-V({raw_n},az). High-Z capacitor plate.",
        f"Vazclk {clk} 0 PULSE({params.vdd:.15g} {params.vss:.15g} {t_az:.15g} 10n 10n 1 2)",
        f"C{tag}cds {raw_n} {lin} 2n",
        f"X{tag}azg {lin} {clk} 0 vss NCH W=5u L=1.4u m=8",
    ]
    final = []
    placed = False
    for line in lines:
        if (not placed) and line.strip().lower().startswith(".control"):
            final.extend(extra)
            final.append("")
            placed = True
        final.append(line)
    if not placed:
        final.extend(extra)
    ending = "\n" if netlist.endswith("\n") else ""
    return "\n".join(final) + ending


def apply_cap_cds(
    netlist: str,
    params: MosParams,
    t_az: float = T_AZ,
    tag: str = TAG,
) -> str:
    """Capacitive subtract + miller follower (alternate MOS CASE 3).

    Ccds sits between TIA raw and n1cap. During AZ, NCH shorts n1cap to 0.
    After AZ, V(n1cap)=Vraw(t)-Vraw(az). Miller buffers n1cap onto n1lin.
    """
    lin = f"{tag}lin"
    raw_n = f"{tag}raw"
    cap = f"{tag}cap"
    clk = f"{tag}clk"
    lines = []
    for raw in netlist.splitlines():
        s = raw.strip()
        if s.startswith(f"X{tag}tia "):
            lines.append(raw.replace(f" {lin} vdd vss ", f" {raw_n} vdd vss ", 1))
            continue
        parts = s.split()
        if len(parts) >= 4 and parts[0].lower() == f"r{tag}f":
            a, b, rval = parts[1], parts[2], parts[3]
            a2 = raw_n if a == lin else a
            b2 = raw_n if b == lin else b
            lines.append(f"{parts[0]} {a2} {b2} {rval}")
            continue
        lines.append(raw)
    extra = [
        f"* Exp 27 capacitive CDS + miller follower. AZ until t={t_az:g}s.",
        f"Vazclk {clk} 0 PULSE({params.vdd:.15g} {params.vss:.15g} {t_az:.15g} 10n 10n 1 2)",
        f"C{tag}cds {raw_n} {cap} 2n",
        f"X{tag}azg {cap} {clk} 0 vss NCH W=5u L=1.4u m=8",
        (
            f"X{tag}buf {cap} {tag}bufinn {lin} vdd vss miller_tia "
            f"MD={params.m_diff} MT={params.m_tail} MO={params.m_out} "
            f"CC={params.cc_f:.15g} IBIAS={params.ibias:.15g} "
            f"DW={params.dw_frac:.15g} L1={params.l1_m}u"
        ),
        f"R{tag}buffb {lin} {tag}bufinn 1",
        f"C{tag}bufc {lin} 0 1p",
    ]
    final = []
    placed = False
    for line in lines:
        if (not placed) and line.strip().lower().startswith(".control"):
            final.extend(extra)
            final.append("")
            placed = True
        final.append(line)
    if not placed:
        final.extend(extra)
    ending = "\n" if netlist.endswith("\n") else ""
    return "\n".join(final) + ending


def apply_output_cds(
    netlist: str,
    params: MosParams,
    t_az: float = T_AZ,
    tag: str = TAG,
    use_vcvs: bool = False,
) -> str:
    """CASE 3: live servo + output CDS. Sample Vlin at Vin=Vref=0, subtract.

    TIA output is renamed to {tag}raw. Rf stays on the TIA node.
    MOS NCH samples {tag}raw onto C. Subtractor is either a miller difference
    amp (device-level) or a labeled LEVEL 2 VCVS (reference only).
    """
    lin = f"{tag}lin"
    raw_n = f"{tag}raw"
    hold = f"{tag}hold"
    clk = f"{tag}clk"
    lines = []
    for raw in netlist.splitlines():
        s = raw.strip()
        if s.startswith(f"X{tag}tia "):
            lines.append(raw.replace(f" {lin} vdd vss ", f" {raw_n} vdd vss ", 1))
            continue
        parts = s.split()
        if len(parts) >= 4 and parts[0].lower() == f"r{tag}f":
            a, b, rval = parts[1], parts[2], parts[3]
            a2 = raw_n if a == lin else a
            b2 = raw_n if b == lin else b
            lines.append(f"{parts[0]} {a2} {b2} {rval}")
            continue
        lines.append(raw)
    extra = [
        f"* Exp 27 output CDS. Sample V({raw_n}) until t={t_az:g}s, Vlin=Vraw-Vhold.",
        f"Vazclk {clk} 0 PULSE({params.vdd:.15g} {params.vss:.15g} {t_az:.15g} 10n 10n 1 2)",
        f"X{tag}azsw {raw_n} {clk} {hold} vss NCH W=5u L=1.4u m=8",
        f"C{tag}hold {hold} 0 2n",
    ]
    if use_vcvs:
        extra += [
            f"* LEVEL 2 reference subtractor (labeled). Not the device-level claim.",
            f"E{tag}cds {lin} 0 {raw_n} {hold} 1",
        ]
    else:
        extra += [
            f"* MOS miller difference amp: V({lin}) ≈ V({raw_n})-V({hold})",
            f"R{tag}sa {hold} {tag}subn 50k",
            f"R{tag}sf {tag}subn {lin} 50k",
            f"R{tag}sb {raw_n} {tag}subp 50k",
            f"R{tag}sc {tag}subp 0 50k",
            (
                f"X{tag}cds {tag}subp {tag}subn {lin} vdd vss miller_tia "
                f"MD={params.m_diff} MT={params.m_tail} MO={params.m_out} "
                f"CC={params.cc_f:.15g} IBIAS={params.ibias:.15g} "
                f"DW={params.dw_frac:.15g} L1={params.l1_m}u"
            ),
        ]
    final = []
    placed = False
    for line in lines:
        if (not placed) and line.strip().lower().startswith(".control"):
            final.extend(extra)
            final.append("")
            placed = True
        final.append(line)
    if not placed:
        final.extend(extra)
    ending = "\n" if netlist.endswith("\n") else ""
    return "\n".join(final) + ending


def apply_mos_az_hold(netlist: str, params: MosParams, t_az: float = T_AZ, tag: str = TAG) -> str:
    """CASE 3: MOS switch holds Vsrv after an AZ interval. No VCVS subtract.

    Clock high (VDD): servo output connected to n1srv (sample).
    Clock low (VSS): hold on Caz. TIA IN+ stays at the held voltage.
    Ideal switch is not used. NCH is the same teaching card as the TIA.
    """
    srv = f"{tag}srv"
    srvo = f"{tag}srvo"
    clk = f"{tag}clk"
    old = f"X{tag}srv 0 {tag}sint {srv} "
    out = []
    found = False
    for raw in netlist.splitlines():
        if raw.strip().startswith(f"X{tag}srv "):
            out.append(raw.replace(f" {srv} vdd vss ", f" {srvo} vdd vss ", 1))
            found = True
            continue
        out.append(raw)
    if not found:
        raise RuntimeError("apply_mos_az_hold: servo instance not found")
    extra = [
        f"* Exp 27 MOS AZ hold. Sample until t={t_az:g}s, then hold V({srv}).",
        f"* NCH pass transistor from the BSIM3 teaching card. Not an ideal SW.",
        f"Vazclk {clk} 0 PULSE({params.vdd:.15g} {params.vss:.15g} {t_az:.15g} 10n 10n 1 2)",
        f"X{tag}azsw {srvo} {clk} {srv} vss NCH W=5u L=1.4u m=4",
        f"C{tag}az {srv} 0 10n",
    ]
    final = []
    placed = False
    for line in out:
        if (not placed) and line.strip().lower().startswith(".control"):
            final.extend(extra)
            final.append("")
            placed = True
        final.append(line)
    if not placed:
        final.extend(extra)
    ending = "\n" if netlist.endswith("\n") else ""
    return "\n".join(final) + ending


def sample_mismatch(cat, mode: str, tol: float, rng, n_tile: int = 1) -> dict[str, float]:
    """Return new R values. Every mode is a statistical model, not layout."""
    items = list(cat)
    values = {str(it["name"]): float(it["R"]) for it in items}
    if tol <= 0:
        return values
    scale = 1.0 / math.sqrt(max(int(n_tile), 1))
    sig = float(tol) * scale

    def u():
        return float(rng.uniform(-sig, sig))

    if mode == "independent":
        for it in items:
            values[str(it["name"])] = float(it["R"]) * (1.0 + u())
        return values

    if mode == "rf_only":
        for it in items:
            if classify_item(it) == "feedback":
                values[str(it["name"])] = float(it["R"]) * (1.0 + u())
        return values

    if mode == "weights_only":
        for it in items:
            if classify_item(it) in {"weight", "bias"}:
                values[str(it["name"])] = float(it["R"]) * (1.0 + u())
        return values

    if mode == "passive_only":
        for it in items:
            if classify_item(it) in {"invert", "divider"}:
                values[str(it["name"])] = float(it["R"]) * (1.0 + u())
        return values

    if mode == "common_mode":
        ucm = u()
        for it in items:
            values[str(it["name"])] = float(it["R"]) * (1.0 + ucm)
        return values

    if mode == "ratio_matched":
        # Shared fractional error on Rf + all weights/bias (G*Rf invariant).
        # Dividers and inverts get a matched pair error (R1 and R2 same u).
        u_tia = u()
        u_div = u()
        u_inv = u()
        for it in items:
            kind = classify_item(it)
            name = str(it["name"])
            r = float(it["R"])
            if kind in {"feedback", "weight", "bias"}:
                values[name] = r * (1.0 + u_tia + 0.15 * u())
            elif kind == "divider":
                values[name] = r * (1.0 + u_div + 0.15 * u())
            elif kind == "invert":
                values[name] = r * (1.0 + u_inv + 0.15 * u())
            else:
                values[name] = r * (1.0 + u())
        return values

    if mode == "centroid_stat":
        # Common-centroid-inspired: chip + pair + local. Not a fabricated layout.
        u_chip = u()
        pairs: dict[str, float] = {}
        for it in items:
            name = str(it["name"])
            key = re.sub(r"[pn]", "x", name, count=1)
            if key not in pairs:
                pairs[key] = u()
            values[name] = float(it["R"]) * (1.0 + u_chip + 0.35 * pairs[key] + 0.25 * u())
        return values

    if mode == "pos_only":
        for it in items:
            if path_sign(it) == "p":
                values[str(it["name"])] = float(it["R"]) * (1.0 + u())
        return values

    if mode == "neg_only":
        for it in items:
            if path_sign(it) == "n":
                values[str(it["name"])] = float(it["R"]) * (1.0 + u())
        return values

    if mode == "pn_independent":
        for it in items:
            if path_sign(it) in {"p", "n"}:
                values[str(it["name"])] = float(it["R"]) * (1.0 + u())
        return values

    if mode == "pn_correlated":
        # Same u on + and − of the same index (differential matching).
        shared: dict[str, float] = {}
        for it in items:
            sign = path_sign(it)
            if sign not in {"p", "n"}:
                continue
            key = re.sub(r"[pn]", "x", str(it["name"]), count=1)
            if key not in shared:
                shared[key] = u()
            values[str(it["name"])] = float(it["R"]) * (1.0 + shared[key])
        return values

    if mode == "pn_systematic":
        for it in items:
            sign = path_sign(it)
            if sign == "p":
                values[str(it["name"])] = float(it["R"]) * (1.0 + sig)
            elif sign == "n":
                values[str(it["name"])] = float(it["R"]) * (1.0 - sig)
        return values

    raise ValueError(f"unknown mismatch mode {mode}")


def conductance_error(cat, values: dict[str, float]) -> dict:
    rel = []
    for it in cat:
        r0 = float(it["R"])
        r1 = float(values.get(str(it["name"]), r0))
        g0, g1 = 1.0 / r0, 1.0 / r1
        rel.append((g1 - g0) / g0)
    arr = np.asarray(rel, dtype=float)
    return {
        "n": int(arr.size),
        "mean_dG_over_G": float(np.mean(arr)),
        "mae_dG_over_G": float(np.mean(np.abs(arr))),
        "max_abs_dG_over_G": float(np.max(np.abs(arr))) if arr.size else None,
    }


def run_op(ngspice, net, x, n_src, params: MosParams, path: Path, timeout=180.0):
    from benchmark_scaling import detect_spice_failure
    from test_robustness import extract_all

    head, sep, _ = net.partition(".control")
    baked = bake_vin_dc(head, np.atleast_1d(np.asarray(x, dtype=float))[:n_src])
    ctrl = (
        "\n.control\nset numdgt=15\nop\n"
        f"print v({TAG}lin)\nprint v({TAG}p)\nprint v({TAG}srv)\n"
        f"print i(V{TAG}ib)\nprint i(Vdd)\nprint i(Vss)\n.endc\n.end\n"
    )
    path.write_text(baked.rstrip() + ctrl, encoding="utf-8")
    result = run_ngspice_ex(ngspice, path, timeout=timeout)
    text = f"{result.stdout or ''}\n{result.stderr or ''}"
    fail = detect_spice_failure(result)
    rec = {"failed": bool(fail), "failure_reason": fail}
    if fail:
        rec["log_tail"] = text[-500:]
        return rec
    vlin = extract_all(text, f"v({TAG}lin)")
    vsum = extract_all(text, f"v({TAG}p)")
    vsrv = extract_all(text, f"v({TAG}srv)")
    idd = extract_all(text, "i(Vdd)")
    iss = extract_all(text, "i(Vss)")
    if not vlin:
        rec.update({"failed": True, "failure_reason": "missing vlin", "log_tail": text[-500:]})
        return rec
    y = float(vlin[-1])
    idd_a = -float(idd[-1]) if idd else None
    rec.update(
        {
            "failed": False,
            "y": y,
            "vsum": float(vsum[-1]) if vsum else None,
            "vsrv": float(vsrv[-1]) if vsrv else None,
            "idd_A": idd_a,
            "iss_A": float(iss[-1]) if iss else None,
            "p_sim_W": None if idd_a is None else abs(idd_a) * (params.vdd - params.vss),
        }
    )
    return rec


def attach_error(rec: dict, z_ref: float) -> dict:
    if rec.get("failed") or rec.get("y") is None:
        rec["abs_err_vs_z"] = None
        rec["analog_pass"] = False
        rec["sign_ok"] = None
        return rec
    y = float(rec["y"])
    z = float(z_ref)
    rec["z_ref"] = z
    rec["err_vs_z"] = y - z
    rec["abs_err_vs_z"] = abs(y - z)
    rec["analog_pass"] = abs(y - z) <= ERROR_LIMIT
    rec["sign_ok"] = True if abs(z) <= 1e-6 else ((y > 0) == (z > 0))
    return rec


def run_az_tran(
    ngspice,
    net,
    x,
    n_src,
    z_ref,
    params: MosParams,
    path: Path,
    t_az=T_AZ,
    t_hold=2e-4,
    timeout=180.0,
):
    from benchmark_scaling import detect_spice_failure

    head, sep, _ = net.partition(".control")
    baked = bake_vref_pulse(bake_vin_pulse(head, np.atleast_1d(np.asarray(x, dtype=float))[:n_src], t_az, 2e-6), t_az, 2e-6)
    wr = path.with_suffix(".dat")
    if wr.exists():
        wr.unlink()
    t_stop = t_az + t_hold + 4e-5
    tstep = max(t_stop / 400.0, 2e-7)
    nodes = [f"{TAG}lin", f"{TAG}p", f"{TAG}srv"]
    path.write_text(
        baked.rstrip()
        + "\n"
        + tran_control(nodes, tstep, t_stop, wr, extra_traces=["i(Vdd)"]),
        encoding="utf-8",
    )
    result = run_ngspice_ex(ngspice, path, timeout=timeout)
    fail = detect_spice_failure(result)
    rec = {
        "failed": bool(fail),
        "failure_reason": fail,
        "t_az_s": t_az,
        "t_hold_s": t_hold,
        "z_ref": float(z_ref),
    }
    if fail:
        return rec
    arr, err = parse_wrdata(wr, 4)
    if arr is None:
        rec.update({"failed": True, "failure_reason": err})
        return rec
    t, vlin, vsum, vsrv, idd = arr[:, 0], arr[:, 1], arr[:, 2], arr[:, 3], arr[:, 4]
    y = float(vlin[-1])
    rec.update(
        {
            "failed": False,
            "y": y,
            "vsum": float(vsum[-1]),
            "vsrv": float(vsrv[-1]),
            "max_vsum": float(np.max(np.abs(vsum))),
            "idd_A": float(-idd[-1]),
            "p_sim_W": abs(float(-idd[-1])) * (params.vdd - params.vss),
            "waveform": {"t": t, "vlin": vlin, "vsum": vsum, "vsrv": vsrv, "idd": idd},
        }
    )
    return attach_error(rec, z_ref)


def run_az_multi(
    ngspice,
    net,
    series,
    zrefs,
    n_src,
    params: MosParams,
    path: Path,
    t_az=T_AZ,
    t_hold=2e-4,
    timeout=180.0,
):
    from benchmark_scaling import detect_spice_failure

    # AZ window: all zeros, then the series. bake_vin_pwl on [zero]+series,
    # but Vref/clk still need an AZ interval first.
    zero = np.zeros(n_src, dtype=float)
    seq = [zero] + [np.atleast_1d(np.asarray(v, dtype=float))[:n_src] for v in series]
    head, sep, _ = net.partition(".control")
    baked = bake_vin_pwl(head, seq, t_hold)
    baked = bake_vref_pulse(baked, t_az, 0.0)
    wr = path.with_suffix(".dat")
    if wr.exists():
        wr.unlink()
    t_stop = t_hold * len(seq) + 5e-5
    tstep = 5e-7
    nodes = [f"{TAG}lin", f"{TAG}p", f"{TAG}srv"]
    path.write_text(
        baked.rstrip()
        + "\n"
        + tran_control(nodes, tstep, t_stop, wr, extra_traces=["i(Vdd)"]),
        encoding="utf-8",
    )
    result = run_ngspice_ex(ngspice, path, timeout=timeout)
    fail = detect_spice_failure(result)
    rec = {"failed": bool(fail), "failure_reason": fail, "t_hold_s": t_hold, "t_az_s": t_az}
    if fail:
        return rec
    arr, err = parse_wrdata(wr, 4)
    if arr is None:
        rec.update({"failed": True, "failure_reason": err})
        return rec
    t, vlin, vsum, vsrv, idd = arr[:, 0], arr[:, 1], arr[:, 2], arr[:, 3], arr[:, 4]
    segs = []
    for i, z in enumerate(zrefs):
        # End of inference i, before the next PWL edge (do not sample look-ahead).
        t_end = t_az + (i + 1) * t_hold
        mask = (t >= t_end - 2e-5) & (t <= t_end - 5e-7)
        if not np.any(mask):
            mask = (t >= t_end - 3 * tstep) & (t <= t_end)
        y = float(vlin[mask][-1]) if np.any(mask) else float(vlin[-1])
        segs.append(attach_error({"y": y, "failed": False}, z) | {"i": i, "t_end_s": t_end})
    rec.update(
        {
            "failed": False,
            "segments": segs,
            "all_pass": all(s.get("analog_pass") for s in segs),
            "max_abs_err": max((s.get("abs_err_vs_z") or 0.0) for s in segs),
            "waveform": {"t": t, "vlin": vlin, "vsum": vsum, "vsrv": vsrv, "idd": idd},
        }
    )
    return rec


def summarize_errs(recs: list[dict]) -> dict:
    errs = [r["abs_err_vs_z"] for r in recs if r.get("abs_err_vs_z") is not None]
    if not errs:
        return {"n_ok": 0, "mae": None, "median": None, "p95": None, "max": None, "pass_frac": None}
    arr = np.asarray(errs, dtype=float)
    return {
        "n_ok": int(arr.size),
        "mae": float(np.mean(arr)),
        "median": float(np.median(arr)),
        "p95": float(np.percentile(arr, 95)),
        "max": float(np.max(arr)),
        "pass_frac": float(np.mean(arr <= ERROR_LIMIT)),
        "sign_ok_frac": float(
            np.mean([1.0 if r.get("sign_ok") else 0.0 for r in recs if r.get("sign_ok") is not None])
        )
        if any(r.get("sign_ok") is not None for r in recs)
        else None,
    }
