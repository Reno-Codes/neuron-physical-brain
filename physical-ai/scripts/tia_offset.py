"""Experiment 19: replica-null TIA offset cancellation.

Architecture A: Experiment 17 feedback TIA (baseline).
Architecture N: matched replica TIA. Dummy G_tot to 0 V, same A / Vos / Rf.
    Vlin = Vsig - Vrep in SPICE (unity differential VCVS).
Architecture U: same replica topology, but replica Vos = 0 while the
    signal TIA keeps Vos. Shows that cancellation requires matching.

Frozen Experiment 9 weights. No Python output correction.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from compile_xor import PROJECT_ROOT
from copy_minimizing import (
    _collect_encoded,
    _control,
    _emit_compensated_divider,
    _emit_passive_invert,
)
from dynamic_range_compiler import range_violation
from mismatch_fabric import stamp_signs
from physical_iv_neuron import (
    IVParams,
    _collect_with_source,
    _emit_relu_v,
    _emit_weights_src,
    _tap_loads_src,
    _uses,
    accounting as iv_accounting,
    compile_iv,
    emit_tia,
    iv_inventory,
)
from precision_architectures import ARCH_C_CFG, R_MAX, R_MIN
from ratiometric_compiler import annotate_catalog


CIRCUIT_DIR = PROJECT_ROOT / "circuits" / "tia_offset"
ARCH_KEYS = ("A", "N", "U")

ARCH_PUBLIC = {
    "A": {
        "title": "Experiment 17 Architecture A (feedback TIA)",
        "iv_topology": "Single TIA per neuron. Vos appears at the output.",
    },
    "N": {
        "title": "matched replica-null TIA",
        "iv_topology": (
            "Signal TIA plus a replica TIA loaded by dummy G_tot to 0 V. "
            "Same A, Rf, Vos. Vlin = Vsig - Vrep. Unity subtractor VCVS."
        ),
    },
    "U": {
        "title": "unmatched replica-null TIA (replica Vos = 0)",
        "iv_topology": (
            "Same replica topology as N, but replica Vos is forced to 0. "
            "Cancellation requires matched offsets."
        ),
    },
}


def emit_dummy_gtot(
    lines: list[str],
    catalog: list[dict],
    tag: str,
    layer: int,
    items: list[dict],
) -> None:
    """Copy each weight/bias conductance from 0 onto the replica sum."""
    lines.append(
        f"* replica dummy G_tot for {tag}: same R as weights/biases, dest=0"
    )
    for i, item in enumerate(items):
        name = f"R{tag}dmy{i:03d}"
        r = float(item["R"])
        lines.append(f"{name} 0 {tag}rp {r:.15g}")
        catalog.append(
            {
                "name": name,
                "comment": f"{tag} replica dummy of {item['name']}",
                "role": "replica",
                "layer": layer,
                "match_group": f"rep_{tag}",
                "R": r,
                "G": 1.0 / r,
                "bank": "replica",
            }
        )


def emit_replica_null(
    lines: list[str],
    catalog: list[dict],
    tag: str,
    g_weight: float,
    layer: int,
    params: IVParams,
    neuron_items: list[dict],
    unmatched: bool,
) -> None:
    vos_sig = params.vos
    if unmatched:
        vos_rep = 0.0 if params.vos_replica is None else float(params.vos_replica)
    else:
        vos_rep = params.vos if params.vos_replica is None else float(params.vos_replica)
    emit_dummy_gtot(lines, catalog, tag, layer, neuron_items)
    emit_tia(
        lines, catalog, tag, g_weight, layer,
        params.amp_gain, params.rail, vos_sig, params.rout,
        params.i_leak, params.clip_amp,
        out_node=f"{tag}sig", sum_node=f"{tag}p", suffix="",
    )
    emit_tia(
        lines, catalog, tag, g_weight, layer,
        params.amp_gain, params.rail, vos_rep, params.rout,
        params.i_leak, params.clip_amp,
        out_node=f"{tag}rep", sum_node=f"{tag}rp", suffix="r",
    )
    lines.append(
        f"* replica null {tag}: v({tag}lin)=v({tag}sig)-v({tag}rep) "
        f"Vos_sig={vos_sig:g} Vos_rep={vos_rep:g}"
    )
    lines.append(f"E{tag}null {tag}lin 0 {tag}sig {tag}rep 1")


def generate_n(
    arch: str,
    spec: dict,
    weights: dict[str, np.ndarray],
    params: IVParams,
) -> tuple[str | None, list[dict], str | None]:
    unmatched = arch == "U"
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

    h_src = _collect_with_source(hidden_enc, 1, True)
    o_src = _collect_with_source(out_enc, 2, True)
    loads1 = _tap_loads_src(h_src)
    loads2 = _tap_loads_src(o_src)
    inv_a = params.invert_gain

    lines = [
        f"* Physical AI - Experiment 19 architecture {arch}: "
        f"{ARCH_PUBLIC[arch]['title']}",
        f"* {ARCH_PUBLIC[arch]['iv_topology']}",
        f"* Frozen Experiment 9 network {spec['id']}. Weights were not edited.",
        "* Behavioral circuit analysis. Not transistor-level or PCB power.",
        f"* A_tia={params.amp_gain:g} vos={params.vos:g} "
        f"vos_replica={params.vos_replica} unmatched={unmatched} "
        f"rout={params.rout:g} Ileak={params.i_leak:g}",
        f"* shape: {n_in} -> {n_hidden} -> {n_out}",
        "",
    ]

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
        start = len(catalog)
        _emit_weights_src(
            lines, catalog, tag, weights["W1"][j], encoded, cfg.g_weight_1, 1
        )
        items = [c for c in catalog[start:] if c.get("role") in {"weight", "bias"}]
        emit_replica_null(
            lines, catalog, tag, cfg.g_weight_1, 1, params, items, unmatched
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
        start = len(catalog)
        _emit_weights_src(
            lines, catalog, tag, weights["W2"][k], encoded, cfg.g_weight_2, 2
        )
        items = [c for c in catalog[start:] if c.get("role") in {"weight", "bias"}]
        emit_replica_null(
            lines, catalog, tag, cfg.g_weight_2, 2, params, items, unmatched
        )
        lines.append("")

    lines.extend(_control(n_out))
    return "\n".join(lines), catalog, None


def compile_offset(
    arch: str,
    spec: dict,
    weights: dict[str, np.ndarray],
    params: IVParams | None = None,
) -> tuple[str | None, list[dict], str | None]:
    p = params or IVParams(name=arch)
    if arch == "A":
        return compile_iv("A", spec, weights, p)
    netlist, catalog, reason = generate_n(arch, spec, weights, p)
    if reason or netlist is None:
        return None, catalog, reason
    annotate_catalog(catalog)
    stamp_signs(catalog)
    fabric = [c for c in catalog if c.get("role") != "amp_rout"]
    violation = range_violation(fabric, R_MIN, R_MAX)
    if violation is not None:
        return None, catalog, violation
    if p.amp_gain_error or p.dump_gain_error:
        from physical_iv_neuron import apply_iv_params
        netlist = apply_iv_params(netlist, "A", p)
    return netlist, catalog, None


def offset_inventory(netlist: str) -> dict:
    inv = iv_inventory(netlist)
    n_null = sum(
        1
        for raw in netlist.splitlines()
        if raw.strip().startswith("E") and raw.split()[0].lower().endswith("null")
    )
    n_rep_tia = 0
    for raw in netlist.splitlines():
        parts = raw.split()
        if not parts:
            continue
        name = parts[0].lower()
        if name[:1] in "eb" and name.endswith("rtia"):
            n_rep_tia += 1
    return {
        **inv,
        "n_null_subtractors": n_null,
        "n_replica_tia": n_rep_tia,
        "n_signal_tia": inv["n_tia_opamps"] - n_rep_tia,
    }


def accounting(netlist: str, catalog: list[dict], n_weights: int) -> dict:
    base = iv_accounting(netlist, catalog, n_weights)
    extra = offset_inventory(netlist)
    n_dmy = sum(1 for c in catalog if c.get("role") == "replica")
    return {
        **base,
        **extra,
        "n_replica_dummy_resistors": n_dmy,
        "offset_note": (
            "Replica TIA + dummy G_tot + unity subtractor. "
            "Not a current dump. Behavioral, not transistors."
        ),
    }


def unit_cell_offset(
    arch: str,
    w: list[float],
    bias: float,
    vos: float,
    g_w: float = 3e-5,
    tia_a: float = 1e5,
) -> str:
    rf = 1.0 / g_w
    w1, w2 = float(w[0]), float(w[1])
    parts = {
        "w1p": max(w1, 0.0),
        "w1n": max(-w1, 0.0),
        "w2p": max(w2, 0.0),
        "w2n": max(-w2, 0.0),
        "bp": max(bias, 0.0),
        "bn": max(-bias, 0.0),
    }

    def rmag(mag: float) -> float:
        return 1.0 / (g_w * mag)

    lines = [
        f"* Experiment 19 unit cell {arch} vos={vos:g}",
        "Vin1 in1 0 DC 0",
        "Vin2 in2 0 DC 0",
        "Vref vref 0 DC 1",
    ]
    if parts["w1n"] or parts["w2n"] or parts["bn"]:
        lines += [
            "Ria in1 m1 10000",
            "Rib in1n m1 10000.200002",
            "Einv1 in1n 0 0 m1 1e5",
            "Ria2 in2 m2 10000",
            "Rib2 in2n m2 10000.200002",
            "Einv2 in2n 0 0 m2 1e5",
            "Riar vref mr 10000",
            "Ribr vrefn mr 10000.200002",
            "Einvr vrefn 0 0 mr 1e5",
        ]
    dest = "sum"
    mapping = (
        ("Rw1p", "in1", parts["w1p"]),
        ("Rw1n", "in1n", parts["w1n"]),
        ("Rw2p", "in2", parts["w2p"]),
        ("Rw2n", "in2n", parts["w2n"]),
        ("Rbp", "vref", parts["bp"]),
        ("Rbn", "vrefn", parts["bn"]),
    )
    rs = []
    for name, src, mag in mapping:
        if mag > 0.0:
            r = rmag(mag)
            rs.append(r)
            lines.append(f"{name} {src} {dest} {r:.15g}")

    def tia(out, vg, stem, vos_v):
        if vos_v == 0.0:
            lines.append(f"E{stem}tia {out} 0 0 {vg} {tia_a:.15g}")
        else:
            lines.append(
                f"B{stem}tia {out} 0 V = -({tia_a:.15g}) * "
                f"(v({vg}) - ({vos_v:.15g}))"
            )
        lines.append(f"R{stem}f {out} {vg} {rf:.15g}")

    if arch == "A":
        tia("raw", dest, "s", vos)
        lines += [
            "Rra raw midr 10000",
            "Rrb lin midr 10000.200002",
            "Esgn lin 0 0 midr 1e5",
        ]
    else:
        tia("sig", dest, "s", vos)
        for i, r in enumerate(rs):
            lines.append(f"Rdmy{i} 0 rp {r:.15g}")
        vos_r = 0.0 if arch == "U" else vos
        tia("rep", "rp", "r", vos_r)
        lines += [
            "Enull raw 0 sig rep 1",
            "Rra raw midr 10000",
            "Rrb lin midr 10000.200002",
            "Esgn lin 0 0 midr 1e5",
        ]
    lines += [
        ".control",
        "set numdgt=15",
        "op",
        "print v(lin)",
        "print v(sum)",
        ".endc",
        ".end",
        "",
    ]
    return "\n".join(lines)
