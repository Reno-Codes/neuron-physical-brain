"""Experiment 37 helpers: TIA requirement extraction and miller insertion.

Frozen Experiment 9 weights. SPICE is the source of truth.
Does not overwrite Experiments 1-36. Does not invent MOS W/L or a PDK.
Reuses the documented Experiment 26 miller TIA + miller servo primitive.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np

from compile_xor import PROJECT_ROOT, apply_resistor_values
from device_neuron import (
    TAG,
    MosParams,
    compile_device_iso,
    mos_include_block,
    tran_control,
    parse_wrdata,
)
from exp35_n32_qualification import option_line
from matching_temperature import classify_item
from opa189_fabric_isolation import inject_options
from offset_vg_search import bake_vin_dc, bake_vin_pulse, run_ngspice_ex
from precision_architectures import ARCH_C_CFG


CIRCUIT_DIR = PROJECT_ROOT / "circuits" / "exp37_physical_tia_integration"
RESULTS_DIR = PROJECT_ROOT / "results"
ERROR_LIMIT = 1.0e-3
QUAL_RELTOL = 5e-5
QUAL_METHOD = "gear"
VOS_214 = 214.023e-6
# Experiment 22 uncorrected Vos ceiling that a summing-node servo must absorb.
VOS_CEILING = 22e-6
LEAK_CEILING_A = 13e-9


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
    return CIRCUIT_DIR / f"{''.join(slug).replace('.', 'p')[:100]}.cir"


def servo_params(**kwargs) -> MosParams:
    rec = dict(kwargs)
    rec.setdefault("name", "exp37")
    rec.setdefault("servo", True)
    return MosParams(**rec)


def noservo_params(**kwargs) -> MosParams:
    rec = dict(kwargs)
    rec.setdefault("name", "exp37ns")
    rec.setdefault("servo", False)
    return MosParams(**rec)


def replace_one_neuron_tia(
    netlist: str,
    tag: str,
    params: MosParams,
    rails: str = "independent_2v5",
) -> str:
    """Replace only E/B {tag}tia. Keep OPA189 ±15 V rails off the teaching miller.

    independent_2v5: documented Exp 26 ±2.5 V on vddtia/vsstia.
    shared_15: reuse fabric vdd/vss (overvoltage diagnostic only).
    """
    e_re = re.compile(
        rf"^(E)({re.escape(tag)}tia)\s+(\S+)\s+0\s+0\s+(\S+)\s+(\S+)\s*$",
        re.IGNORECASE,
    )
    b_re = re.compile(rf"^(B)({re.escape(tag)}tia)\s+(\S+)\s+0\s+V\s*=", re.IGNORECASE)
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
                f"* Exp 37 one-neuron miller TIA tag={tag} rails={rails}",
                "* Documented Exp 26 W/L/DW. Weights not edited.",
                f".temp {params.temp_c:.15g}",
                "",
            ]
            if rails == "independent_2v5":
                out += [
                    f"Vddtia vddtia 0 DC {params.vdd:.15g}",
                    f"Vsstia vsstia 0 DC {params.vss:.15g}",
                ]
            inserted = True
        m_e = e_re.match(s)
        m_b = b_re.match(s)
        if m_e:
            drv = m_e.group(3)
            vg_node = m_e.group(4)
            n_rep += 1
            continue
        if m_b:
            drv = m_b.group(3)
            n_rep += 1
            continue
        out.append(raw)
    if n_rep != 1:
        raise RuntimeError(f"expected one TIA for {tag}, found {n_rep}")
    vdd, vss = ("vddtia", "vsstia") if rails == "independent_2v5" else ("vdd", "vss")
    plus = f"{tag}osp"
    srv = f"{tag}srv"
    inn = f"{tag}inn"
    inst = [
        "",
        f"* MOS TIA on {tag}: IN-={vg_node} OUT={drv} rails={vdd}/{vss}",
        f"V{tag}ib {vg_node} {inn} DC 0",
        f"Vosinj{tag} {plus} {srv} DC {float(params.vos_inject):.15g}",
        (
            f"X{tag}tia {plus} {inn} {drv} {vdd} {vss} miller_tia "
            f"MD={params.m_diff} MT={params.m_tail} MO={params.m_out} "
            f"CC={params.cc_f:.15g} IBIAS={params.ibias:.15g} "
            f"DW={params.dw_frac:.15g} L1={params.l1_m}u"
        ),
    ]
    if params.servo:
        inst += [
            f"R{tag}si {vg_node} {tag}sint {params.servo_rin:.15g}",
            f"C{tag}int {tag}sint {srv} {params.servo_c:.15g}",
            f"R{tag}leak {tag}sint {srv} {params.servo_rleak:.15g}",
            (
                f"X{tag}srv 0 {tag}sint {srv} {vdd} {vss} miller_tia "
                f"MD={max(params.servo_m, 2)} MT={max(params.servo_m, 2)} "
                f"MO={max(params.servo_m * 4, 4)} "
                f"CC={params.cc_f:.15g} IBIAS={params.servo_ibias:.15g} "
                f"DW={params.servo_dw_frac:.15g}"
            ),
            f".ic v({srv})=0",
        ]
    else:
        inst.append(f"R{tag}srv {srv} 0 1e3")
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


def strip_hardcoded_options(netlist: str) -> str:
    lines = [ln for ln in netlist.splitlines() if not ln.strip().lower().startswith(".options")]
    ending = "\n" if netlist.endswith("\n") else ""
    return "\n".join(lines) + ending


def requirement_row_summary(rows: list[dict], picks: dict) -> dict:
    o2 = next(r for r in rows if r["tag"] == "o2")
    rf = [r["Rf_ohm"] for r in rows]
    g = [r["G_phys_S"] for r in rows]
    rfg = [r["Rf_Gtot"] for r in rows]
    z = [r["z_abs_max"] for r in rows]
    imax = [r["I_max_est_A"] for r in rows]
    return {
        "n_neurons": len(rows),
        "worst_RfG": picks["worst_finite_gain"]["tag"],
        "worst_RfG_value": picks["worst_finite_gain"]["Rf_Gtot"],
        "worst_G": max(rows, key=lambda r: r["G_phys_S"])["tag"],
        "worst_G_S": max(g),
        "lightest_G": min(rows, key=lambda r: r["G_phys_S"])["tag"],
        "Rf_ohm_min": min(rf),
        "Rf_ohm_max": max(rf),
        "G_phys_min_S": min(g),
        "G_phys_max_S": max(g),
        "RfG_min": min(rfg),
        "RfG_max": max(rfg),
        "I_max_est_A": max(imax),
        "z_abs_max_V": max(z),
        "highest_signal": picks["highest_signal"]["tag"],
        "o2_RfG": o2["Rf_Gtot"],
        "o2_G_phys_S": o2["G_phys_S"],
        "o2_z_abs_max": o2["z_abs_max"],
        "o2_is_worst_RfG": picks["worst_finite_gain"]["tag"] == "o2",
        "vos_ceiling_V": VOS_CEILING,
        "leak_ceiling_A": LEAK_CEILING_A,
        "vsum_req_note": (
            "Servo must hold Vsum so |Vlin-z|<=1e-3. Exp 26 o2 servo Vsum ~0.67 uV. "
            "Uncorrected Vos ceiling ~22 uV (Exp 22). 214 uV is the representative raw offset."
        ),
        "loop_gain_note": (
            "Behavioral Architecture A uses A=1e5. Isolated miller no-servo A_eff~1.7e3 on o2. "
            "Servo is required for analog pass on the worst neuron."
        ),
        "dwell_s": 2e-4,
        "temp_C": [-40.0, 27.0, 85.0],
        "output_load_note": (
            "Architecture A hidden ReLU is a B-source: it isolates h*lin from the "
            "OPA189 invert and layer-2 fabric. Output-neuron TIA load is Rf plus "
            "that neuron's summing fabric. Shared-fabric coupling is through the "
            "input taps / hidden voltages, not TIA output current into invert."
        ),
    }


def replace_neuron_tias(
    netlist: str,
    tags: list[str],
    params: MosParams,
    rails: str = "independent_2v5",
) -> str:
    net = netlist
    for i, tag in enumerate(tags):
        if i == 0:
            net = replace_one_neuron_tia(net, tag, params, rails=rails)
            continue
        # Models / rails already present. Replace only this TIA instance.
        e_re = re.compile(
            rf"^(E)({re.escape(tag)}tia)\s+(\S+)\s+0\s+0\s+(\S+)\s+(\S+)\s*$",
            re.IGNORECASE,
        )
        b_re = re.compile(rf"^(B)({re.escape(tag)}tia)\s+(\S+)\s+0\s+V\s*=", re.IGNORECASE)
        kept: list[str] = []
        n_rep = 0
        vg_node = f"{tag}p"
        drv = f"{tag}lin"
        for raw in net.splitlines():
            s = raw.strip()
            m_e = e_re.match(s)
            m_b = b_re.match(s)
            if m_e:
                drv = m_e.group(3)
                vg_node = m_e.group(4)
                n_rep += 1
                continue
            if m_b:
                drv = m_b.group(3)
                n_rep += 1
                continue
            kept.append(raw)
        if n_rep != 1:
            raise RuntimeError(f"expected one TIA for {tag}, found {n_rep}")
        vdd, vss = ("vddtia", "vsstia") if rails == "independent_2v5" else ("vdd", "vss")
        plus = f"{tag}osp"
        srv = f"{tag}srv"
        inn = f"{tag}inn"
        inst = [
            "",
            f"* MOS TIA on {tag}: IN-={vg_node} OUT={drv} rails={vdd}/{vss}",
            f"V{tag}ib {vg_node} {inn} DC 0",
            f"Vosinj{tag} {plus} {srv} DC {float(params.vos_inject):.15g}",
            (
                f"X{tag}tia {plus} {inn} {drv} {vdd} {vss} miller_tia "
                f"MD={params.m_diff} MT={params.m_tail} MO={params.m_out} "
                f"CC={params.cc_f:.15g} IBIAS={params.ibias:.15g} "
                f"DW={params.dw_frac:.15g} L1={params.l1_m}u"
            ),
        ]
        if params.servo:
            inst += [
                f"R{tag}si {vg_node} {tag}sint {params.servo_rin:.15g}",
                f"C{tag}int {tag}sint {srv} {params.servo_c:.15g}",
                f"R{tag}leak {tag}sint {srv} {params.servo_rleak:.15g}",
                (
                    f"X{tag}srv 0 {tag}sint {srv} {vdd} {vss} miller_tia "
                    f"MD={max(params.servo_m, 2)} MT={max(params.servo_m, 2)} "
                    f"MO={max(params.servo_m * 4, 4)} "
                    f"CC={params.cc_f:.15g} IBIAS={params.servo_ibias:.15g} "
                    f"DW={params.servo_dw_frac:.15g}"
                ),
                f".ic v({srv})=0",
            ]
        else:
            inst.append(f"R{tag}srv {srv} 0 1e3")
        final: list[str] = []
        placed = False
        for line in kept:
            if (not placed) and line.strip().lower().startswith(".control"):
                final.extend(inst)
                final.append("")
                placed = True
            final.append(line)
        if not placed:
            final.extend(inst)
        ending = "\n" if net.endswith("\n") else ""
        net = "\n".join(final) + ending
    return net


def compile_iso_neuron(spec, weights, pick, params: MosParams):
    hidden = pick["layer"] == 1
    idx = pick["index"]
    wrow = weights["W1"][idx] if hidden else weights["W2"][idx]
    bias = float(weights["b1"][idx] if hidden else weights["b2"][idx])
    cfg = ARCH_C_CFG["F"]
    g_w = cfg.g_weight_1 if hidden else cfg.g_weight_2
    n_src = spec["n_in"] if hidden else spec["n_hidden"]
    net, cat, reason = compile_device_iso(n_src, wrow, bias, g_w, cfg.banks, params)
    return net, cat, reason, n_src, wrow, bias


def iso_ratio_values(cat, mode: str, tol: float, rng) -> dict[str, float]:
    """Controlled resistor tests. Not a yield campaign."""
    out = {}
    loc = 0.15 * float(tol)
    if mode == "common_mode":
        for it in cat:
            out[str(it["name"])] = float(it["R"]) * (1.0 + float(tol))
        return out
    if mode == "independent":
        for it in cat:
            out[str(it["name"])] = float(it["R"]) * (1.0 + float(rng.uniform(-tol, tol)))
        return out
    # ratio_matched: shared Rf·G scale + 15% leftover local on weight/bias/Rf
    u = float(rng.uniform(-tol, tol))
    for it in cat:
        name = str(it["name"])
        r = float(it["R"])
        k = classify_item(it)
        if k in {"feedback", "weight", "bias"}:
            out[name] = r * (1.0 + u) * (1.0 + float(rng.uniform(-loc, loc)))
        else:
            out[name] = r * (1.0 + u)
    return out


def slim_iso(rec: dict) -> dict:
    drop = {"params", "log_tail", "waveform"}
    return {k: v for k, v in rec.items() if k not in drop}


def eval_iso_op_exp37(
    ngspice,
    spec,
    weights,
    pick,
    params: MosParams,
    xvec,
    z_ref,
    path,
    r_values=None,
    options: str | None = None,
    extra_net=None,
    timeout: float = 180.0,
    strip_options: bool = False,
):
    from benchmark_scaling import detect_spice_failure
    from test_robustness import extract_all

    net, cat, reason, n_src, _wrow, _bias = compile_iso_neuron(spec, weights, pick, params)
    rec = {
        "tag": pick["tag"],
        "failed": bool(reason),
        "failure_reason": reason,
        "z_ref": float(z_ref),
        "n_resistors": len(cat) if cat else None,
        "option_line": options,
        "servo": bool(params.servo),
        "temp_c": float(params.temp_c),
        "vos_inject": float(params.vos_inject),
    }
    if reason or net is None:
        return rec, cat
    if extra_net:
        net = extra_net(net, params)
    if r_values:
        net = apply_resistor_values(net, r_values)
    if options or strip_options:
        net = strip_hardcoded_options(net)
        if options:
            net = inject_options(net, options)
    head, sep, _ = net.partition(".control")
    x = np.atleast_1d(np.asarray(xvec, dtype=float))[:n_src]
    baked = bake_vin_dc(head, x)
    ctrl = (
        "\n.control\nset numdgt=15\nop\n"
        f"print v({TAG}lin)\nprint v({TAG}p)\nprint v({TAG}srv)\n"
        f"print i(V{TAG}ib)\nprint i(Vdd)\nprint i(Vss)\n.endc\n.end\n"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(baked.rstrip() + ctrl, encoding="utf-8")
    result = run_ngspice_ex(ngspice, path, timeout=timeout)
    text = f"{result.stdout or ''}\n{result.stderr or ''}"
    fail = detect_spice_failure(result)
    vlin = extract_all(text, f"v({TAG}lin)")
    vsum = extract_all(text, f"v({TAG}p)")
    vsrv = extract_all(text, f"v({TAG}srv)")
    iib = extract_all(text, f"i(v{TAG}ib)")
    idd = extract_all(text, "i(Vdd)")
    if fail or not vlin:
        rec.update({"failed": True, "failure_reason": fail or "missing vlin", "log_tail": text[-500:]})
        return rec, cat
    y = float(vlin[-1])
    vsum_v = float(vsum[-1]) if vsum else None
    a_eff = None
    if vsum_v not in (None, 0.0) and abs(vsum_v) > 1e-18:
        a_eff = abs(y / vsum_v)
    rec.update(
        {
            "failed": False,
            "y": y,
            "vsum": vsum_v,
            "vsrv": float(vsrv[-1]) if vsrv else None,
            "i_sum_to_inn_A": float(iib[-1]) if iib else None,
            "err_vs_z": y - float(z_ref),
            "abs_err_vs_z": abs(y - float(z_ref)),
            "a_eff_closed_loop": a_eff,
            "idd_A": -float(idd[-1]) if idd else None,
            "analog_pass": abs(y - float(z_ref)) <= ERROR_LIMIT,
        }
    )
    return rec, cat


def eval_iso_tran_exp37(
    ngspice,
    spec,
    weights,
    pick,
    params: MosParams,
    xvec,
    z_ref,
    path,
    t_delay: float = 1e-5,
    t_stop: float = 2e-4,
    options: str | None = None,
    extra_net=None,
    timeout: float = 180.0,
):
    from benchmark_scaling import detect_spice_failure

    net, cat, reason, n_src, _wrow, _bias = compile_iso_neuron(spec, weights, pick, params)
    rec = {
        "tag": pick["tag"],
        "failed": bool(reason),
        "z_ref": float(z_ref),
        "t_delay_s": t_delay,
        "t_stop_s": t_stop,
        "option_line": options,
        "servo": bool(params.servo),
        "temp_c": float(params.temp_c),
    }
    if reason or net is None:
        rec["failure_reason"] = reason
        return rec
    if extra_net:
        net = extra_net(net, params)
    if options:
        net = inject_options(strip_hardcoded_options(net), options)
    head, sep, _ = net.partition(".control")
    x = np.atleast_1d(np.asarray(xvec, dtype=float))[:n_src]
    baked = bake_vin_pulse(head, x, t_delay, t_gap=0.0)
    wr = path.with_suffix(".dat")
    if wr.exists():
        wr.unlink()
    tstep = max(t_stop / 400.0, 1e-7)
    nodes = [f"{TAG}lin", f"{TAG}p", f"{TAG}srv"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        baked.rstrip() + "\n" + tran_control(nodes, tstep, t_stop, wr, extra_traces=["i(Vdd)"]),
        encoding="utf-8",
    )
    result = run_ngspice_ex(ngspice, path, timeout=timeout)
    fail = detect_spice_failure(result)
    if fail:
        rec.update({"failed": True, "failure_reason": fail})
        return rec
    arr, err = parse_wrdata(wr, 4)
    if arr is None:
        rec.update({"failed": True, "failure_reason": err})
        return rec
    t, vlin, vsum, vsrv = arr[:, 0], arr[:, 1], arr[:, 2], arr[:, 3]
    y = float(vlin[-1])
    rec.update(
        {
            "failed": False,
            "y_final": y,
            "abs_err_vs_z": abs(y - float(z_ref)),
            "vsum_final": float(vsum[-1]),
            "vsrv_final": float(vsrv[-1]),
            "max_vsum": float(np.max(np.abs(vsum))),
            "swing_vlin": float(np.max(np.abs(vlin))),
            "analog_pass": abs(y - float(z_ref)) <= ERROR_LIMIT,
        }
    )
    return rec


def insertion_probe_control(inputs, n_out: int, tag: str, invert_stage: dict | None) -> str:
    lines = [".control", "set numdgt=15"]
    for x in inputs:
        for i, xi in enumerate(np.atleast_1d(x), start=1):
            lines.append(f"alter Vin{i} DC {float(xi):.15g}")
        lines.append("op")
        for k in range(1, n_out + 1):
            lines.append(f"print v(o{k}lin)")
        lines.append(f"print v({tag}lin)")
        lines.append(f"print v({tag}p)")
        lines.append(f"print v({tag}srv)")
        if invert_stage:
            lines.append(f"print v({invert_stage['src']})")
            lines.append(f"print v({invert_stage['dest']})")
            lines.append(f"print v({invert_stage['mid']})")
    lines.extend([".endc", "", ".end", ""])
    return "\n".join(lines)


def eval_insertion(
    ng,
    net: str,
    spec: dict,
    x,
    y,
    path,
    tag: str,
    invert_stage: dict | None = None,
    options: str | None = None,
    timeout: float = 360.0,
    z_neuron=None,
):
    import time

    from benchmark_scaling import (
        classification_labels,
        detect_spice_failure,
        error_stats,
        parse_physical_outputs,
    )
    from test_robustness import extract_all

    head, sep, _ = net.partition(".control")
    if not sep:
        return {"failed": True, "failure_reason": "no .control"}
    body = inject_options(head, options) if options else head
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body.rstrip() + "\n" + insertion_probe_control(x, spec["n_out"], tag, invert_stage), encoding="utf-8")
    t0 = time.perf_counter()
    result = run_ngspice_ex(ng, path, timeout=timeout, pspice=True)
    runtime = time.perf_counter() - t0
    text = f"{result.stdout or ''}\n{result.stderr or ''}"
    fail = detect_spice_failure(result)
    rec = {
        "failed": bool(fail),
        "failure_reason": fail,
        "spice_s": runtime,
        "option_line": options,
        "tag": tag,
        "mode": "op",
    }
    if fail:
        rec["log_tail"] = text[-500:]
        return rec
    try:
        physical = parse_physical_outputs(text, len(x), spec["n_out"])
    except RuntimeError as exc:
        rec.update({"failed": True, "failure_reason": str(exc), "log_tail": text[-400:]})
        return rec
    y = np.atleast_2d(np.asarray(y, dtype=float))
    st = error_stats(physical, y)
    rec.update(st)
    rec["accuracy"] = float(np.mean(classification_labels(physical) == classification_labels(y)))
    rec["analog_pass"] = st["mae"] <= ERROR_LIMIT
    rec["per_vector_mae"] = np.mean(np.abs(physical - y), axis=1).tolist()
    rec["per_vector_max"] = np.max(np.abs(physical - y), axis=1).tolist()
    rec["worst_vector"] = int(np.argmax(rec["per_vector_max"]))
    rec["n_vectors"] = len(x)
    vlin = extract_all(text, f"v({tag}lin)")
    vsum = extract_all(text, f"v({tag}p)")
    vsrv = extract_all(text, f"v({tag}srv)")
    if vlin:
        rec["vlin"] = [float(v) for v in vlin]
        rec["tia_swing"] = float(np.max(np.abs(vlin)))
        if z_neuron is not None:
            z = np.atleast_1d(np.asarray(z_neuron, dtype=float))[: len(vlin)]
            rec["vlin_err_mae"] = float(np.mean(np.abs(np.asarray(vlin, float) - z)))
            rec["vlin_err_max"] = float(np.max(np.abs(np.asarray(vlin, float) - z)))
    if vsum:
        rec["vsum"] = [float(v) for v in vsum]
        rec["vsum_mae"] = float(np.mean(np.abs(vsum)))
        rec["vsum_max"] = float(np.max(np.abs(vsum)))
    if vsrv:
        rec["vsrv_max"] = float(np.max(np.abs(vsrv)))
    if invert_stage:
        vin = extract_all(text, f"v({invert_stage['src']})")
        vout = extract_all(text, f"v({invert_stage['dest']})")
        vmid = extract_all(text, f"v({invert_stage['mid']})")
        if vin and vout and len(vin) == len(vout):
            err = np.asarray(vout, float) + np.asarray(vin, float)
            rec["invert_residual_mae"] = float(np.mean(np.abs(err)))
            rec["invert_residual_max"] = float(np.max(np.abs(err)))
        if vmid:
            rec["invert_vmid_mae"] = float(np.mean(np.abs(vmid)))
    return rec
