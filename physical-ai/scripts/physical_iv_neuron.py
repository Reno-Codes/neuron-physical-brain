"""Experiment 17: physical current-to-voltage neuron.

Architecture I (baseline): Experiment 16 invert-and-sum fabric. Exact 0 V
    summing node. One behavioral current dump onto physical R_IV.
    This is the leftover copy.

Architecture A (feedback TIA): same weight fabric, but I-to-V is an
    inverting transimpedance loop. The op-amp holds the summing node;
    transimpedance is the feedback resistor. Finite open-loop gain is
    left uncompensated (no Python scale). Weight polarity is flipped so
    Vlin = +I * Rf * A/(A+1).

Architecture B (ratiometric TIA): unflipped weights. TIA produces
    -I * Rf. A passive invert (R2/R1) restores the sign. The I-to-V
    gain is the physical product Rf * (R2/R1). Common resistor shift
    cancels in SPICE.

Architecture C (current-mode ReLU): hidden nonlinearity is
    I_y = max(0, I_sum) in SPICE, then a TIA. Output neurons use A.
    This tests whether I-to-V can move after a current-domain ReLU.
    It does not remove a controlled source.

Frozen Experiment 9 weights. No Python output correction.
Behavioral circuit analysis, not transistor-level design.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from compile_xor import OPAMP_GAIN, PROJECT_ROOT
from copy_minimizing import (
    _collect_encoded,
    _control,
    _emit_compensated_divider,
    _emit_passive_invert,
    _source_node_i,
    accounting as copy_accounting,
    compile_copy,
    generate_i,
)
from dynamic_range_compiler import range_violation
from mismatch_fabric import stamp_signs
from precision_architectures import ARCH_C_CFG, R_MAX, R_MIN, _count_devices
from ratiometric_compiler import annotate_catalog


CIRCUIT_DIR = PROJECT_ROOT / "circuits" / "physical_iv"
ARCH_KEYS = ("I", "A", "B", "C")
DEFAULT_GAIN = float(OPAMP_GAIN)
R_RATIO = 10_000.0


@dataclass(frozen=True)
class IVParams:
    name: str
    amp_gain: float = DEFAULT_GAIN
    invert_gain: float = DEFAULT_GAIN
    rail: float = 15.0
    vos: float = 0.0
    vos_replica: float | None = None
    rout: float = 0.0
    i_leak: float = 0.0
    amp_gain_error: float = 0.0
    dump_gain_error: float = 0.0
    clip_amp: bool = False
    linear: bool = False

    def public(self) -> dict:
        row = asdict(self)
        row["note"] = (
            "amp_gain is TIA open-loop A. amp_gain_error multiplies A. "
            "dump_gain_error multiplies Architecture I current dumps. "
            "vos is TIA input offset. vos_replica is the replica TIA "
            "offset (None = matched to vos). rout is series ohms at the "
            "amp output inside the loop. Not transistors."
        )
        return row


ARCH_PUBLIC = {
    "I": {
        "title": "Experiment 16 Architecture I (current dump onto R_IV)",
        "iv_topology": (
            "0 V voltage source summing node. Behavioral I dump onto "
            "physical R_IV. Leftover copy is the dump."
        ),
    },
    "A": {
        "title": "feedback resistor TIA",
        "iv_topology": (
            "Inverting TIA. Vout = I * Rf * A/(A+1). Summing node held "
            "by the amplifier, not by a 0 V source. Rf = 1/G_WEIGHT."
        ),
    },
    "B": {
        "title": "ratiometric TIA (Rf * R2/R1)",
        "iv_topology": (
            "Inverting TIA then passive invert. "
            "Vout = I * Rf * (R2/R1) * closed-loop residuals. "
            "Common resistor shift cancels."
        ),
    },
    "C": {
        "title": "current-mode ReLU then TIA",
        "iv_topology": (
            "Hidden: I_y = max(0, I_sum) in SPICE, then TIA. "
            "Output: feedback TIA. Current-domain ReLU is a B-source."
        ),
    },
}


def _header(arch: str, spec: dict, extra: str) -> list[str]:
    meta = ARCH_PUBLIC[arch]
    return [
        f"* Physical AI - Experiment 17 architecture {arch}: {meta['title']}",
        f"* {meta['iv_topology']}",
        f"* Frozen Experiment 9 network {spec['id']}. Weights were not edited.",
        "* Behavioral circuit analysis. Not transistor-level or PCB power.",
        extra,
        f"* shape: {spec['n_in']} -> {spec['n_hidden']} -> {spec['n_out']}",
        "",
    ]


def flip_node(node: str) -> str:
    """Swap a source with its inverted twin."""
    if node == "tapref":
        return "taprefn"
    if node == "taprefn":
        return "tapref"
    if node == "vref":
        return "vrefn"
    if node == "vrefn":
        return "vref"
    if node.startswith("htap"):
        return node[:-1] if node.endswith("n") else node + "n"
    if node.startswith("tap"):
        return node[:-1] if node.endswith("n") else node + "n"
    if node.startswith("in"):
        return node[:-1] if node.endswith("n") else node + "n"
    if node.startswith("h") and node.endswith("yn"):
        return node[:-1]
    if node.startswith("h") and node.endswith("y"):
        return node + "n"
    return node


def source_node(item: dict, layer: int, flip: bool) -> str:
    node = _source_node_i(item, layer)
    return flip_node(node) if flip else node


def _collect_with_source(encoded_layers, layer: int, flip: bool):
    """Re-wrap encoded items so load math sees the emitted source node."""
    out = []
    for j, encoded in encoded_layers:
        rewritten = []
        for item in encoded:
            row = dict(item)
            row["_src"] = source_node(item, layer, flip)
            rewritten.append(row)
        out.append((j, rewritten))
    return out


def _tap_loads_src(encoded_layers) -> dict[str, float]:
    loads: dict[str, float] = {}
    for _j, encoded in encoded_layers:
        for item in encoded:
            node = item["_src"]
            if node.startswith("tap") or node.startswith("htap"):
                loads[node] = loads.get(node, 0.0) + 1.0 / float(item["R"])
    return loads


def _uses(encoded_layers, node: str) -> bool:
    for _j, encoded in encoded_layers:
        for item in encoded:
            if item["_src"] == node:
                return True
    return False


def _emit_weights_src(
    lines, catalog, tag, wrow, encoded, g_w, layer
) -> None:
    from copy_minimizing import _stamp
    from dynamic_range_compiler import _emit_resistor

    start = len(catalog)
    for item in encoded:
        dest = f"{tag}p"
        src = item["_src"]
        if item["kind"] == "bias":
            name = f"R{tag}b{item['sign']}{item['bank']}{item['branch']}"
            comment = f"{tag} bias w{'+' if item['sign'] == 'p' else '-'}"
        else:
            idx = int(item["source_index"])
            name = f"R{tag}{item['sign']}{idx}{item['bank']}{item['branch']}"
            comment = (
                f"{tag} input {idx} w={float(wrow[idx - 1]):+.15g} "
                f"w{'+' if item['sign'] == 'p' else '-'}"
            )
        _emit_resistor(lines, catalog, name, src, dest, item, comment, g_w, layer)
    _stamp(catalog, start, layer, f"fab_L{layer}")


def _add_r(catalog, name, comment, role, layer, match_group, resistance, bank):
    catalog.append(
        {
            "name": name,
            "comment": comment,
            "role": role,
            "layer": layer,
            "match_group": match_group,
            "R": resistance,
            "G": 1.0 / resistance,
            "bank": bank,
        }
    )


def emit_tia(
    lines: list[str],
    catalog: list[dict],
    tag: str,
    g_weight: float,
    layer: int,
    amp_gain: float,
    rail: float,
    vos: float,
    rout: float,
    i_leak: float,
    clip: bool,
    out_node: str,
    sum_node: str | None = None,
    suffix: str = "",
) -> None:
    """Inverting TIA: V(out) = -I_into_sum * Rf * A/(A+1). No Python scale."""
    rf = 1.0 / float(g_weight)
    vg = sum_node or f"{tag}p"
    stem = f"{tag}{suffix}"
    drv = f"{stem}drv" if rout > 0.0 else out_node
    lines.append(
        f"* feedback TIA {stem}: Rf={rf:.15g} A={amp_gain:g} "
        f"V({out_node}) = -I({vg})*Rf*A/(A+1)  (uncompensated)"
    )
    a_eff = float(amp_gain)
    if clip or vos != 0.0:
        vos_s = f"{vos:.15g}"
        if clip:
            expr = (
                f"max(-{rail:.15g}, min({rail:.15g}, "
                f"-({a_eff:.15g}) * (v({vg}) - ({vos_s}))))"
            )
        else:
            expr = f"-({a_eff:.15g}) * (v({vg}) - ({vos_s}))"
        lines.append(f"B{stem}tia {drv} 0 V = {expr}")
    else:
        lines.append(f"E{stem}tia {drv} 0 0 {vg} {a_eff:.15g}")
    if rout > 0.0:
        lines.append(f"R{stem}ro {drv} {out_node} {rout:.15g}")
        _add_r(
            catalog, f"R{stem}ro", f"{stem} TIA Rout",
            "amp_rout", layer, f"fab_L{layer}", rout, "rout",
        )
    lines.append(f"R{stem}f {out_node} {vg} {rf:.15g}")
    _add_r(
        catalog, f"R{stem}f", f"{stem} TIA feedback",
        "feedback", layer, f"fab_L{layer}", rf, "ref",
    )
    if i_leak:
        lines.append(f"B{stem}leak 0 {vg} I = {i_leak:.15g}")


def emit_ratio_restore(
    lines: list[str],
    catalog: list[dict],
    tag: str,
    src: str,
    dest: str,
    layer: int,
    amp_gain: float,
) -> None:
    """Passive invert so Vdest = -Vsrc at finite A (R2/R1 compensated)."""
    from copy_minimizing import invert_r2

    mid = f"{tag}rm"
    r1 = R_RATIO
    r2 = invert_r2(r1, amp_gain)
    lines.append(
        f"* ratiometric sign restore {src}->{dest}: "
        f"R2/R1={(r2 / r1):.12g} at A={amp_gain:g}"
    )
    lines.append(f"R{tag}ra {src} {mid} {r1:.15g}")
    lines.append(f"R{tag}rb {dest} {mid} {r2:.15g}")
    lines.append(f"E{tag}sgn {dest} 0 0 {mid} {amp_gain:.15g}")
    _add_r(
        catalog, f"R{tag}ra", f"{tag} ratio R1",
        "ratio", layer, f"ratio_{tag}", r1, "ratio",
    )
    _add_r(
        catalog, f"R{tag}rb", f"{tag} ratio R2",
        "ratio", layer, f"ratio_{tag}", r2, "ratio",
    )


def emit_current_relu_tia(
    lines: list[str],
    catalog: list[dict],
    tag: str,
    g_weight: float,
    layer: int,
    params: IVParams,
) -> None:
    """0 V sense, current ReLU, then TIA on the rectified current."""
    rf = 1.0 / float(g_weight)
    lines.append(
        f"* current-mode ReLU + TIA {tag}: "
        f"I_y=max(0, i(V{tag}p)), then feedback TIA Rf={rf:.15g}"
    )
    lines.append(f"V{tag}p {tag}p 0 DC 0")
    lines.append(f"B{tag}crelu {tag}ir 0 I = max(0, i(V{tag}p))")
    emit_tia(
        lines, catalog, tag, g_weight, layer,
        params.amp_gain, params.rail, params.vos, params.rout,
        params.i_leak, params.clip_amp,
        out_node=f"{tag}lin", sum_node=f"{tag}ir",
    )


def _emit_relu_v(lines: list[str], tag: str, rail: float, linear: bool) -> None:
    if linear:
        lines.append(f"* linear hidden: layer 2 reads v({tag}lin)")
        return
    lines.append(
        f"* direct bounded ReLU: y=max(0, min({rail:g}, v({tag}lin)))"
    )
    lines.append(
        f"B{tag}relu {tag}y 0 V = max(0, min({rail:.15g}, v({tag}lin)))"
    )


def generate_iv(
    arch: str,
    spec: dict,
    weights: dict[str, np.ndarray],
    params: IVParams,
) -> tuple[str | None, list[dict], str | None]:
    if arch == "I":
        netlist, catalog, reason = generate_i(
            spec, weights,
            i_leak=params.i_leak, rail=params.rail,
            linear=params.linear, amp_gain=params.invert_gain,
            tia_vos=params.vos,
        )
        return netlist, catalog, reason

    cfg = ARCH_C_CFG[spec["id"]]
    catalog: list[dict] = []
    n_in, n_hidden, n_out = spec["n_in"], spec["n_hidden"], spec["n_out"]
    hidden_enc, reason = _collect_encoded(
        weights["W1"], weights["b1"], cfg.g_weight_1, cfg.banks
    )
    if reason or hidden_enc is None:
        return None, catalog, f"layer 1: {reason}"
    out_enc, reason = _collect_encoded(
        weights["W2"], weights["b2"], cfg.g_weight_2, cfg.banks
    )
    if reason or out_enc is None:
        return None, catalog, f"layer 2: {reason}"

    # A and C-output flip so TIA sign is +I*Rf. B keeps natural sign
    # and restores it with R2/R1. C hidden uses 0 V sense (no flip).
    flip_h = arch == "A"
    flip_o = arch in {"A", "C"}
    h_src = _collect_with_source(hidden_enc, 1, flip_h)
    o_src = _collect_with_source(out_enc, 2, flip_o)
    loads1 = _tap_loads_src(h_src)
    loads2 = _tap_loads_src(o_src)

    lines = _header(
        arch, spec,
        f"* A_tia={params.amp_gain:g} A_inv={params.invert_gain:g} "
        f"rail={params.rail:g} vos={params.vos:g} rout={params.rout:g} "
        f"Ileak={params.i_leak:g} clip={params.clip_amp} "
        f"linear={params.linear}",
    )
    inv_a = params.invert_gain

    def need(*nodes: str) -> bool:
        return any(_uses(h_src, n) or _uses(o_src, n) for n in nodes)

    for i in range(1, n_in + 1):
        lines.append(f"Vin{i} in{i} 0 DC 0")
        if need(f"in{i}n", f"tap{i}n"):
            _emit_passive_invert(
                lines, catalog, f"in{i}", f"in{i}n", f"inv{i}", 1, inv_a
            )
        if need(f"tap{i}"):
            reason = _emit_compensated_divider(
                lines, catalog, f"in{i}", f"tap{i}", f"div{i}",
                loads1.get(f"tap{i}", 0.0), 1,
            )
            if reason:
                return None, catalog, reason
        if need(f"tap{i}n"):
            reason = _emit_compensated_divider(
                lines, catalog, f"in{i}n", f"tap{i}n", f"div{i}n",
                loads1.get(f"tap{i}n", 0.0), 1,
            )
            if reason:
                return None, catalog, reason
    lines.append("Vref vref 0 DC 1")
    if need("vrefn", "taprefn"):
        _emit_passive_invert(lines, catalog, "vref", "vrefn", "invref", 1, inv_a)
    if need("tapref"):
        g_ref = loads1.get("tapref", 0.0) + loads2.get("tapref", 0.0)
        reason = _emit_compensated_divider(
            lines, catalog, "vref", "tapref", "divref", g_ref, 1
        )
        if reason:
            return None, catalog, reason
    if need("taprefn"):
        g_refn = loads1.get("taprefn", 0.0) + loads2.get("taprefn", 0.0)
        reason = _emit_compensated_divider(
            lines, catalog, "vrefn", "taprefn", "divrefn", g_refn, 1
        )
        if reason:
            return None, catalog, reason
    lines.append("")

    for j, encoded in h_src:
        tag = f"h{j + 1}"
        _emit_weights_src(
            lines, catalog, tag, weights["W1"][j], encoded, cfg.g_weight_1, 1
        )
        if arch == "C" and not params.linear:
            emit_current_relu_tia(lines, catalog, tag, cfg.g_weight_1, 1, params)
            lines.append(
                f"B{tag}relu {tag}y 0 V = max(0, min({params.rail:.15g}, "
                f"v({tag}lin)))"
            )
            # Current ReLU already max(0,I). Voltage bound still clips rails.
        elif arch == "B":
            emit_tia(
                lines, catalog, tag, cfg.g_weight_1, 1,
                params.amp_gain, params.rail, params.vos, params.rout,
                params.i_leak, params.clip_amp,
                out_node=f"{tag}raw",
            )
            emit_ratio_restore(
                lines, catalog, tag, f"{tag}raw", f"{tag}lin", 1, inv_a
            )
            _emit_relu_v(lines, tag, params.rail, params.linear)
        else:
            emit_tia(
                lines, catalog, tag, cfg.g_weight_1, 1,
                params.amp_gain, params.rail, params.vos, params.rout,
                params.i_leak, params.clip_amp,
                out_node=f"{tag}lin",
            )
            _emit_relu_v(lines, tag, params.rail, params.linear)
        lines.append("")

    for j in range(1, n_hidden + 1):
        src = f"h{j}lin" if params.linear else f"h{j}y"
        if need(f"h{j}yn", f"htap{j}n"):
            _emit_passive_invert(
                lines, catalog, src, f"h{j}yn", f"invh{j}", 2, inv_a
            )
        if need(f"htap{j}"):
            reason = _emit_compensated_divider(
                lines, catalog, src, f"htap{j}", f"divh{j}",
                loads2.get(f"htap{j}", 0.0), 2,
            )
            if reason:
                return None, catalog, reason
        if need(f"htap{j}n"):
            reason = _emit_compensated_divider(
                lines, catalog, f"h{j}yn", f"htap{j}n", f"divh{j}n",
                loads2.get(f"htap{j}n", 0.0), 2,
            )
            if reason:
                return None, catalog, reason
    lines.append("")

    for k, encoded in o_src:
        tag = f"o{k + 1}"
        _emit_weights_src(
            lines, catalog, tag, weights["W2"][k], encoded, cfg.g_weight_2, 2
        )
        if arch == "B":
            emit_tia(
                lines, catalog, tag, cfg.g_weight_2, 2,
                params.amp_gain, params.rail, params.vos, params.rout,
                params.i_leak, params.clip_amp,
                out_node=f"{tag}raw",
            )
            emit_ratio_restore(
                lines, catalog, tag, f"{tag}raw", f"{tag}lin", 2, inv_a
            )
        else:
            emit_tia(
                lines, catalog, tag, cfg.g_weight_2, 2,
                params.amp_gain, params.rail, params.vos, params.rout,
                params.i_leak, params.clip_amp,
                out_node=f"{tag}lin",
            )
        lines.append("")

    lines.extend(_control(n_out))
    return "\n".join(lines), catalog, None


def apply_iv_params(netlist: str, arch: str, params: IVParams) -> str:
    """Apply leftover macromodel errors. Resistor topology stays."""
    a_scale = 1.0 + params.amp_gain_error
    d_scale = 1.0 + params.dump_gain_error
    out: list[str] = []
    for raw in netlist.splitlines():
        parts = raw.split()
        if not parts or raw.strip().startswith("*") or raw.strip().startswith("."):
            out.append(raw)
            continue
        kind = parts[0][0].upper()
        name = parts[0]
        if kind == "E" and name.endswith("tia") and len(parts) >= 6 and a_scale != 1.0:
            gain = float(parts[5]) * a_scale
            out.append(
                f"{parts[0]} {parts[1]} {parts[2]} {parts[3]} {parts[4]} "
                f"{gain:.15g}"
            )
            continue
        if kind == "B" and name.endswith("tia") and a_scale != 1.0 and "V =" in raw:
            # Scale the open-loop A inside the expression.
            out.append(raw.replace(f"-({params.amp_gain:.15g})",
                                   f"-({params.amp_gain * a_scale:.15g})", 1))
            continue
        if kind == "B" and name.endswith("iv") and "I" in parts and d_scale != 1.0:
            eq = raw.split("=", 1)[1].strip()
            out.append(
                f"{parts[0]} {parts[1]} {parts[2]} I = ({d_scale:.15g})*({eq})"
            )
            continue
        out.append(raw)
    ending = "\n" if netlist.endswith("\n") else ""
    return "\n".join(out) + ending


def compile_iv(
    arch: str,
    spec: dict,
    weights: dict[str, np.ndarray],
    params: IVParams | None = None,
) -> tuple[str | None, list[dict], str | None]:
    p = params or IVParams(name=arch)
    if arch == "I":
        from copy_minimizing import CopyParams

        netlist, catalog, reason = compile_copy(
            "I", spec, weights,
            params=CopyParams(
                name=p.name,
                copy_common=p.dump_gain_error,
                tia_vos=p.vos,
                i_leak=p.i_leak,
            ),
            i_leak=p.i_leak,
            rail=p.rail,
            linear=p.linear,
        )
        return netlist, catalog, reason

    netlist, catalog, reason = generate_iv(arch, spec, weights, p)
    if reason or netlist is None:
        return None, catalog, reason
    annotate_catalog(catalog)
    stamp_signs(catalog)
    fabric = [c for c in catalog if c.get("role") != "amp_rout"]
    violation = range_violation(fabric, R_MIN, R_MAX)
    if violation is not None:
        return None, catalog, violation
    if p.amp_gain_error or p.dump_gain_error:
        netlist = apply_iv_params(netlist, arch, p)
    return netlist, catalog, None


def iv_inventory(netlist: str) -> dict:
    n_tia = n_dump = n_crelu = n_vrelu = n_inv = n_sgn = 0
    n_cccs = n_e = n_b = n_h = n_d = 0
    for raw in netlist.splitlines():
        line = raw.strip()
        if not line or line.startswith("*") or line.startswith("."):
            continue
        kind = line[0].upper()
        name = line.split()[0]
        low = name.lower()
        if kind == "F":
            n_cccs += 1
        elif kind == "E":
            n_e += 1
            if low.endswith("tia"):
                n_tia += 1
            elif "inv" in low and low.endswith("amp"):
                n_inv += 1
            elif low.endswith("sgn"):
                n_sgn += 1
        elif kind == "B":
            n_b += 1
            if low.endswith("tia"):
                n_tia += 1
            elif low.endswith("iv"):
                n_dump += 1
            elif low.endswith("crelu"):
                n_crelu += 1
            elif "relu" in low:
                n_vrelu += 1
        elif kind == "H":
            n_h += 1
        elif kind == "D":
            n_d += 1
    n_iv = n_tia + n_dump
    return {
        "n_current_dumps": n_dump,
        "n_tia_opamps": n_tia,
        "n_iv_stages": n_iv,
        "n_invert_opamps": n_inv,
        "n_ratio_restores": n_sgn,
        "n_current_relu": n_crelu,
        "n_voltage_relu": n_vrelu,
        "n_diodes": n_d,
        "active_cccs": n_cccs,
        "active_vcvs": n_e,
        "active_behavioral": n_b,
        "active_transimpedance": n_h,
        "active_functional_blocks": n_cccs + n_e + n_b + n_h,
        "leftover_current_copies": n_dump + n_crelu,
        "closed_loop_opamps": n_tia + n_inv + n_sgn,
        "active_note": (
            "Behavioral controlled sources, not transistors. "
            "leftover_current_copies = I dumps + current-mode ReLU B-sources. "
            "TIA / invert op-amps set resistor-ratio loops."
        ),
    }


def accounting(netlist: str, catalog: list[dict], n_weights: int) -> dict:
    base = copy_accounting(netlist, catalog, n_weights)
    inv = iv_inventory(netlist)
    n_fb = sum(1 for c in catalog if c.get("role") == "feedback")
    n_ratio = sum(1 for c in catalog if c.get("role") == "ratio")
    devices = _count_devices(netlist)
    return {
        **base,
        **devices,
        **inv,
        "n_feedback_resistors": n_fb,
        "n_ratio_resistors": n_ratio,
        "passive_resistors": devices["passive_resistors"],
    }


def sample_feedback_absolute(catalog: list[dict], percent: float, rng) -> dict[str, float]:
    """Perturb only TIA feedback resistors. Architecture I uses R*iv."""
    p = percent / 100.0
    values = {str(item["name"]): float(item["R"]) for item in catalog}
    for item in catalog:
        role = str(item.get("role", ""))
        name = str(item["name"])
        is_fb = role == "feedback" or (
            role == "reference" and name.endswith("iv")
        )
        if not is_fb:
            continue
        u = float(rng.uniform(-p, p)) if p else 0.0
        values[name] = float(item["R"]) * max(0.1, 1.0 + u)
    return values


def sample_feedback_ratiometric(
    catalog: list[dict], percent: float, rng
) -> dict[str, float]:
    """Same relative draw on weights, biases, feedback, and references.

    Dividers and invert/ratio pairs are left nominal so this test isolates
    the R_f / R_w identity.
    """
    p = percent / 100.0
    values = {str(item["name"]): float(item["R"]) for item in catalog}
    roles = {"weight", "bias", "feedback", "reference"}
    u = float(rng.uniform(-p, p)) if p else 0.0
    for item in catalog:
        if str(item.get("role", "")) not in roles:
            continue
        values[str(item["name"])] = float(item["R"]) * max(0.1, 1.0 + u)
    return values


def sample_global_fixed(catalog: list[dict], delta: float) -> dict[str, float]:
    scale = max(0.1, 1.0 + float(delta))
    return {str(item["name"]): float(item["R"]) * scale for item in catalog}


def sample_independent(catalog: list[dict], percent: float, rng) -> dict[str, float]:
    p = percent / 100.0
    values = {}
    for item in catalog:
        u = float(rng.uniform(-p, p)) if p else 0.0
        values[str(item["name"])] = float(item["R"]) * max(0.1, 1.0 + u)
    return values


def neuron_tags(spec: dict) -> list[str]:
    tags = [f"h{j}" for j in range(1, spec["n_hidden"] + 1)]
    tags.extend(f"o{k}" for k in range(1, spec["n_out"] + 1))
    return tags
