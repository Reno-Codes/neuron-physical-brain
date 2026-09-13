"""Experiment 28 helpers: output interface on the Exp 27 CDS neuron.

Frozen Experiment 9 weights. SPICE is not Python-corrected.
The CDS plate (n1lin after apply_cap_cds_unbuf) is the source of analog state.
Interface output is n1drv when present, else n1lin.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from compile_xor import PROJECT_ROOT
from device_neuron import ERROR_LIMIT, TAG, MosParams, parse_wrdata, tran_control
from matching_temperature import (
    T_AZ,
    apply_cap_cds,
    apply_cap_cds_unbuf,
    attach_error,
    compile_iso,
)
from offset_vg_search import bake_vin_pulse, bake_vref_pulse, run_ngspice_ex
from servo_transient import bake_vin_pwl


CIRCUIT_DIR = PROJECT_ROOT / "circuits" / "exp28_output_interface"
RESULTS_DIR = PROJECT_ROOT / "results"
CCDS = 2.0e-9
OUT = f"{TAG}drv"
PLATE = f"{TAG}lin"
RAW = f"{TAG}raw"


def dest(*parts) -> Path:
    name = "_".join(
        str(p).replace(".", "p").replace("-", "m").replace("+", "p") for p in parts
    )
    CIRCUIT_DIR.mkdir(parents=True, exist_ok=True)
    return CIRCUIT_DIR / f"{name}.cir"


def _insert(netlist: str, extra: list[str]) -> str:
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


def apply_load(netlist: str, node: str, r_ohm=None, c_f=None, tag: str = "ld") -> str:
    extra = [f"* Exp 28 output load on {node}"]
    if r_ohm is not None:
        extra.append(f"R{tag} {node} 0 {float(r_ohm):.15g}")
    if c_f is not None:
        extra.append(f"C{tag} {node} 0 {float(c_f):.15g}")
    return _insert(netlist, extra)


def apply_ileak(netlist: str, node: str, i_a: float, tag: str = "lk") -> str:
    extra = [
        f"* Exp 28 leakage current from {node} to 0 (sensitivity, not a PDK leak).",
        f"I{tag} {node} 0 DC {float(i_a):.15g}",
    ]
    return _insert(netlist, extra)


def apply_unbuf(netlist: str, params: MosParams, t_az: float = T_AZ) -> str:
    return apply_cap_cds_unbuf(netlist, params, t_az=t_az)


def apply_miller(netlist: str, params: MosParams, t_az: float = T_AZ) -> str:
    """Exp 27 miller follower. Plate is n1cap, driven out is n1lin."""
    return apply_cap_cds(netlist, params, t_az=t_az)


def apply_vcvs_buf(netlist: str, params: MosParams, t_az: float = T_AZ) -> str:
    """LEVEL 2 control: ideal unity buffer of the CDS plate. Not the device claim."""
    net = apply_cap_cds_unbuf(netlist, params, t_az=t_az)
    extra = [
        "* LEVEL 2 control: E-source unity buffer of the CDS plate. Labeled.",
        f"E{TAG}drv {OUT} 0 {PLATE} 0 1",
        f"C{TAG}drvc {OUT} 0 1p",
    ]
    return _insert(net, extra)


def apply_nmos_sf(
    netlist: str,
    params: MosParams,
    t_az: float = T_AZ,
    nested_cds: bool = True,
    body_to_source: bool = True,
) -> str:
    """NMOS source follower of the CDS plate. Optional nested capacitive CDS.

    Body-to-source removes the teaching-card body effect (4-terminal BSIM3).
    Nested CDS stores Vsf during AZ (n1lin=0) and subtracts it on the output plate.
    Remaining error is ΔVgs(Vin), not Vgs(0).
    """
    net = apply_cap_cds_unbuf(netlist, params, t_az=t_az)
    body = f"{TAG}sf" if body_to_source else "vss"
    extra = [
        f"* Exp 28 NMOS SF of {PLATE}. body={'source' if body_to_source else 'vss'}.",
        f"I{TAG}sfb vdd {TAG}sfb DC {params.ibias:.15g}",
        f"X{TAG}sfd {TAG}sfb {TAG}sfb vss vss NCH W=5u L=1.4u m=2",
        f"X{TAG}sfsnk {TAG}sf {TAG}sfb vss vss NCH W=5u L=1.4u m=2",
        f"X{TAG}sf vdd {PLATE} {TAG}sf {body} NCH W=20u L=1.4u m=8",
    ]
    if nested_cds:
        extra += [
            f"* Nested capacitive CDS of the SF output. Same AZ clock as the neuron.",
            f"C{TAG}nest {TAG}sf {OUT} 2n",
            f"X{TAG}azsf {OUT} {TAG}clk 0 vss NCH W=5u L=1.4u m=8",
        ]
    else:
        extra += [f"R{TAG}sftie {TAG}sf {OUT} 1"]
    return _insert(net, extra)


def apply_qamp(
    netlist: str,
    params: MosParams,
    t_az: float = T_AZ,
    c_couple: float = 2.0e-9,
    c_f: float = 1.0e-9,
    servo: bool = True,
    invert: bool = True,
    invert_servo: bool = False,
    invert_servo_c: float | None = None,
    invert_dw: float | None = None,
    ideal_reset: bool = False,
) -> str:
    """Capacitive couple the CDS plate into a virtual-ground miller charge amp.

    During AZ the plate is 0 and Cf is reset. After AZ:
      Vlin = Ccds/(Ccds+Ccouple) * (Vraw - Vraw_az)
      Vcout = -(Ccouple/Cf) * Vlin
    With Ccds=Ccouple=2 nF and Cf=1 nF, Vcout = -(Vraw-Vraw_az).
    The miller sees CM≈0 (the DW-nulled operating point), not |z|≈1.73 V.
    MOS invert restores Architecture A sign. Ideal-reset is a labeled LEVEL 2 control.
    """
    net = apply_cap_cds_unbuf(netlist, params, t_az=t_az)
    q = f"{TAG}q"
    cout = f"{TAG}cout"
    extra = [
        f"* Exp 28 VG charge amp. Ccouple={c_couple:.15g} Cf={c_f:.15g}.",
        f"* Miller IN- is {q} (virtual ground). Not a high-CM follower.",
        f"C{TAG}cpl {PLATE} {q} {c_couple:.15g}",
        f"C{TAG}qf {q} {cout} {c_f:.15g}",
    ]
    if ideal_reset:
        extra += [
            f"* LEVEL 2 control: ideal SW resets Cf during AZ. Labeled.",
            f"S{TAG}qrst {cout} {q} {TAG}clk 0 SWQ",
            f".model SWQ SW(Ron=10 Roff=1e12 Vt=0 Vh=0.1)",
        ]
    else:
        extra.append(f"X{TAG}qrst {cout} {TAG}clk {q} vss NCH W=5u L=1.4u m=8")
    dw = params.servo_dw_frac
    extra.append(
        f"X{TAG}qamp {TAG}qsrv {q} {cout} vdd vss miller_tia "
        f"MD={params.m_diff} MT={params.m_tail} MO={params.m_out} "
        f"CC={params.cc_f:.15g} IBIAS={params.ibias:.15g} "
        f"DW={dw:.15g} L1={params.l1_m}u"
    )
    if servo:
        extra += [
            f"R{TAG}qsi {q} {TAG}qsint {params.servo_rin:.15g}",
            f"C{TAG}qint {TAG}qsint {TAG}qsrv {params.servo_c:.15g}",
            f"R{TAG}qleak {TAG}qsint {TAG}qsrv {params.servo_rleak:.15g}",
            (
                f"X{TAG}qsrv 0 {TAG}qsint {TAG}qsrv vdd vss miller_tia "
                f"MD={max(params.servo_m, 2)} MT={max(params.servo_m, 2)} "
                f"MO={max(params.servo_m * 4, 4)} "
                f"CC={params.cc_f:.15g} IBIAS={params.servo_ibias:.15g} "
                f"DW={params.servo_dw_frac:.15g}"
            ),
            f".ic v({TAG}qsrv)=0",
        ]
    else:
        extra.append(f"R{TAG}qsrv {TAG}qsrv 0 1k")
    if invert:
        extra += [
            f"* MOS invert of charge-amp output (Architecture A sign). Same miller.",
            f"R{TAG}ia {cout} {TAG}iinn 50k",
            f"R{TAG}ib {TAG}iinn {OUT} 50k",
        ]
        idw = params.servo_dw_frac if invert_dw is None else float(invert_dw)
        if invert_servo:
            ic = params.servo_c if invert_servo_c is None else float(invert_servo_c)
            extra += [
                f"* MOS invert servo: hold {TAG}iinn at 0. Not a per-input trim.",
                f"R{TAG}isi {TAG}iinn {TAG}isint {params.servo_rin:.15g}",
                f"C{TAG}iint {TAG}isint {TAG}isrv {ic:.15g}",
                f"R{TAG}ileak {TAG}isint {TAG}isrv {params.servo_rleak:.15g}",
                (
                    f"X{TAG}isrv 0 {TAG}isint {TAG}isrv vdd vss miller_tia "
                    f"MD={max(params.servo_m, 2)} MT={max(params.servo_m, 2)} "
                    f"MO={max(params.servo_m * 4, 4)} "
                    f"CC={params.cc_f:.15g} IBIAS={params.servo_ibias:.15g} "
                    f"DW={idw:.15g}"
                ),
                f".ic v({TAG}isrv)=0",
                (
                    f"X{TAG}inv {TAG}isrv {TAG}iinn {OUT} vdd vss miller_tia "
                    f"MD={params.m_diff} MT={params.m_tail} MO={params.m_out} "
                    f"CC={params.cc_f:.15g} IBIAS={params.ibias:.15g} "
                    f"DW={idw:.15g} L1={params.l1_m}u"
                ),
            ]
        else:
            extra.append(
                f"X{TAG}inv 0 {TAG}iinn {OUT} vdd vss miller_tia "
                f"MD={params.m_diff} MT={params.m_tail} MO={params.m_out} "
                f"CC={params.cc_f:.15g} IBIAS={params.ibias:.15g} "
                f"DW={idw:.15g} L1={params.l1_m}u"
            )
    else:
        extra.append(f"R{TAG}qtie {cout} {OUT} 1")
    return _insert(net, extra)


def apply_qamp_l2_invert(netlist: str, params: MosParams, t_az: float = T_AZ) -> str:
    """Charge amp + LEVEL 2 invert. Isolates invert finite-A from the VG stage."""
    net = apply_qamp(netlist, params, t_az=t_az, invert=False)
    # apply_qamp(invert=False) ties n1cout to n1drv; remove that before E-source.
    lines = [ln for ln in net.splitlines() if not ln.startswith(f"R{TAG}qtie ")]
    net = "\n".join(lines) + ("\n" if net.endswith("\n") else "")
    extra = [
        "* LEVEL 2 invert of V(n1cout). Isolates MOS invert error. Labeled.",
        f"E{TAG}inv {OUT} 0 0 {TAG}cout 1",
    ]
    return _insert(net, extra)


def apply_qamp_invservo(netlist: str, params: MosParams, t_az: float = T_AZ) -> str:
    # invert_dw=0.0026: 27 °C inverting-amp self-balance of the output invert
    # (same class as Exp 26 servo_dw). Not per-input, not per-temperature.
    return apply_qamp(netlist, params, t_az=t_az, invert=True, invert_servo=True, invert_dw=0.0026)


CANDIDATES = {
    "unbuf": {
        "label": "high-Z CDS plate (Exp 27 baseline)",
        "apply": apply_unbuf,
        "out": PLATE,
        "plate": PLATE,
        "device_level": True,
    },
    "vcvs": {
        "label": "LEVEL 2 VCVS buffer (control)",
        "apply": apply_vcvs_buf,
        "out": OUT,
        "plate": PLATE,
        "device_level": False,
    },
    "miller": {
        "label": "Exp 27 miller follower",
        "apply": apply_miller,
        "out": PLATE,
        "plate": f"{TAG}cap",
        "device_level": True,
    },
    "sf_plain": {
        "label": "NMOS SF, no nested CDS",
        "apply": lambda n, p: apply_nmos_sf(n, p, nested_cds=False),
        "out": OUT,
        "plate": PLATE,
        "device_level": True,
    },
    "sf_nested": {
        "label": "NMOS SF + nested CDS, body=source",
        "apply": lambda n, p: apply_nmos_sf(n, p, nested_cds=True),
        "out": OUT,
        "plate": PLATE,
        "device_level": True,
    },
    "qamp": {
        "label": "VG charge amp + MOS invert + servo",
        "apply": lambda n, p: apply_qamp(n, p, invert=True),
        "out": OUT,
        "plate": PLATE,
        "device_level": True,
    },
    "qamp_invservo": {
        "label": "VG charge amp + MOS invert with servo",
        "apply": apply_qamp_invservo,
        "out": OUT,
        "plate": PLATE,
        "device_level": True,
    },
    "qamp_l2inv": {
        "label": "VG charge amp + LEVEL 2 invert",
        "apply": apply_qamp_l2_invert,
        "out": OUT,
        "plate": PLATE,
        "device_level": False,
    },
    "qamp_idealrst": {
        "label": "VG charge amp, LEVEL 2 reset SW + MOS invert",
        "apply": lambda n, p: apply_qamp(n, p, ideal_reset=True),
        "out": OUT,
        "plate": PLATE,
        "device_level": False,
    },
}


def run_iface(
    ngspice,
    net,
    x,
    n_src,
    z_ref,
    params: MosParams,
    path: Path,
    t_az=T_AZ,
    t_hold=2e-4,
    out_node: str = OUT,
    extra_nodes: list[str] | None = None,
    plate_node: str = PLATE,
    timeout=180.0,
):
    from benchmark_scaling import detect_spice_failure

    head, _, _ = net.partition(".control")
    baked = bake_vref_pulse(
        bake_vin_pulse(head, np.atleast_1d(np.asarray(x, dtype=float))[:n_src], t_az, 2e-6),
        t_az,
        2e-6,
    )
    wr = path.with_suffix(".dat")
    if wr.exists():
        wr.unlink()
    t_stop = t_az + t_hold + 4e-5
    tstep = max(t_stop / 400.0, 2e-7)
    nodes = [out_node, plate_node, RAW, f"{TAG}p", f"{TAG}srv"]
    for n in extra_nodes or []:
        if n not in nodes:
            nodes.append(n)
    path.write_text(
        baked.rstrip() + "\n" + tran_control(nodes, tstep, t_stop, wr, extra_traces=["i(Vdd)"]),
        encoding="utf-8",
    )
    result = run_ngspice_ex(ngspice, path, timeout=timeout)
    fail = detect_spice_failure(result)
    rec = {
        "failed": bool(fail),
        "failure_reason": fail,
        "t_az_s": t_az,
        "t_hold_s": t_hold,
        "out_node": out_node,
        "z_ref": float(z_ref),
    }
    if fail:
        return rec
    nvec = len(nodes) + 1
    arr, err = parse_wrdata(wr, nvec)
    if arr is None:
        rec.update({"failed": True, "failure_reason": err})
        return rec
    t = arr[:, 0]
    vout = arr[:, 1]
    vplate = arr[:, 2]
    vraw = arr[:, 3]
    vsum = arr[:, 4]
    vsrv = arr[:, 5]
    idd = arr[:, -1]
    y = float(vout[-1])
    y_plate = float(vplate[-1])
    rec.update(
        {
            "failed": False,
            "y": y,
            "y_plate": y_plate,
            "y_raw": float(vraw[-1]),
            "vsum": float(vsum[-1]),
            "vsrv": float(vsrv[-1]),
            "idd_A": float(-idd[-1]),
            "p_sim_W": abs(float(-idd[-1])) * (params.vdd - params.vss),
            "iface_err": y - y_plate if out_node != plate_node else 0.0,
            "abs_iface_err": abs(y - y_plate) if out_node != plate_node else 0.0,
            "waveform": {
                "t": t,
                "vout": vout,
                "vplate": vplate,
                "vraw": vraw,
                "vsum": vsum,
                "vsrv": vsrv,
                "idd": idd,
            },
        }
    )
    rec = attach_error(rec, z_ref)
    rec["plate_err"] = y_plate - float(z_ref)
    rec["abs_plate_err"] = abs(y_plate - float(z_ref))
    return rec


def sample_at(t, y, t_abs):
    mask = t <= t_abs
    if not np.any(mask):
        return float(y[0])
    return float(y[mask][-1])


def droop_from_wave(t, v, t_az, times):
    t0 = t_az + 2e-6
    v0 = sample_at(t, v, t0 + 5e-5)
    rows = []
    for dt in times:
        vt = sample_at(t, v, t0 + dt)
        rows.append({"t_s": dt, "v": vt, "droop": vt - v0})
    return {"v_ref": v0, "points": rows}


def run_multi(
    ngspice,
    net,
    series,
    zrefs,
    n_src,
    params: MosParams,
    path: Path,
    t_az=T_AZ,
    t_hold=2e-4,
    out_node: str = OUT,
    plate_node: str = PLATE,
    timeout=180.0,
):
    from benchmark_scaling import detect_spice_failure

    zero = np.zeros(n_src, dtype=float)
    seq = [zero] + [np.atleast_1d(np.asarray(v, dtype=float))[:n_src] for v in series]
    head, _, _ = net.partition(".control")
    baked = bake_vref_pulse(bake_vin_pwl(head, seq, t_hold), t_az, 0.0)
    wr = path.with_suffix(".dat")
    if wr.exists():
        wr.unlink()
    t_stop = t_hold * len(seq) + 5e-5
    tstep = 5e-7
    nodes = [out_node, plate_node, f"{TAG}p"]
    path.write_text(
        baked.rstrip() + "\n" + tran_control(nodes, tstep, t_stop, wr, extra_traces=["i(Vdd)"]),
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
    t, vout, vplate, vsum, idd = arr[:, 0], arr[:, 1], arr[:, 2], arr[:, 3], arr[:, 4]
    segs = []
    for i, z in enumerate(zrefs):
        t_end = t_az + (i + 1) * t_hold
        mask = (t >= t_end - 2e-5) & (t <= t_end - 5e-7)
        if not np.any(mask):
            mask = (t >= t_end - 3 * tstep) & (t <= t_end)
        y = float(vout[mask][-1]) if np.any(mask) else float(vout[-1])
        yp = float(vplate[mask][-1]) if np.any(mask) else float(vplate[-1])
        row = attach_error({"y": y, "failed": False}, z)
        row.update({"i": i, "t_end_s": t_end, "y_plate": yp, "iface_err": y - yp})
        segs.append(row)
    rec.update(
        {
            "failed": False,
            "segments": segs,
            "all_pass": all(s.get("analog_pass") for s in segs),
            "max_abs_err": max((s.get("abs_err_vs_z") or 0.0) for s in segs),
            "waveform": {"t": t, "vout": vout, "vplate": vplate, "vsum": vsum, "idd": idd},
        }
    )
    return rec
