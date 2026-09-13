"""Experiment 18: passive current-to-voltage bound.

Question: can V = I * Rf at the summing node replace the Experiment 17
TIA without an active virtual-ground amplifier, while still implementing
the frozen neural map?

Architecture I: Experiment 16 dump (exact 0 V node + current copy).
Architecture A: Experiment 17 feedback TIA.
Architecture P: passive Rf from the summing node to ground. A B-source
    ReLU isolates the next layer, so layer-2 resistors do not load the
    hidden sums. This isolates the I = (Vin - Vsum)/R error.
Architecture L: passive Rf on every neuron and no hidden ReLU isolation.
    Layer-2 weight resistors attach to the hidden summing nodes. The
    circuit is a coupled resistor mesh, not a layered MLP.

Frozen Experiment 9 weights. No Python output correction.
The attenuated-map prediction is a physics hypothesis check, not a
correction applied to SPICE outputs.
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
    DEFAULT_GAIN,
    IVParams,
    _add_r,
    _collect_with_source,
    _emit_relu_v,
    _emit_weights_src,
    _tap_loads_src,
    _uses,
    accounting as iv_accounting,
    compile_iv,
    iv_inventory,
)
from precision_architectures import ARCH_C_CFG, R_MAX, R_MIN
from ratiometric_compiler import annotate_catalog


CIRCUIT_DIR = PROJECT_ROOT / "circuits" / "passive_iv"
ARCH_KEYS = ("I", "A", "P", "L")

ARCH_PUBLIC = {
    "I": {
        "title": "Experiment 16 Architecture I (current dump)",
        "iv_topology": "0 V node + behavioral current dump onto R_IV",
    },
    "A": {
        "title": "Experiment 17 Architecture A (feedback TIA)",
        "iv_topology": "inverting TIA, Rf feedback, finite A uncompensated",
    },
    "P": {
        "title": "passive Rf I-to-V, ReLU-isolated next layer",
        "iv_topology": (
            "Rf from sum node to ground. Vsum = I_loaded * Rf. "
            "No TIA and no current dump. Hidden ReLU is a B-source, "
            "so layer 2 does not load the hidden sums."
        ),
    },
    "L": {
        "title": "passive mesh cascade (layer 2 loads hidden sums)",
        "iv_topology": (
            "No hidden ReLU buffer. Layer-2 resistors attach to hidden "
            "summing nodes. Coupled resistor mesh, not a layered MLP."
        ),
    },
}


def mesh_hidden_src(node: str) -> str:
    """Read layer-2 sources from hidden summing nodes, not ReLU buffers."""
    if node.startswith("h") and node.endswith("yn"):
        return f"{node[:-2]}pn"
    if node.startswith("h") and node.endswith("y"):
        return f"{node[:-1]}p"
    return node


def emit_passive_rf(
    lines: list[str],
    catalog: list[dict],
    tag: str,
    g_weight: float,
    layer: int,
    i_leak: float,
) -> None:
    rf = 1.0 / float(g_weight)
    vg = f"{tag}p"
    lines.append(
        f"* PASSIVE I-to-V {tag}: {vg} --Rf={rf:.15g}--> 0  "
        f"(no amplifier; V = I_loaded * Rf)"
    )
    lines.append(f"R{tag}f {vg} 0 {rf:.15g}")
    _add_r(
        catalog, f"R{tag}f", f"{tag} passive Rf",
        "feedback", layer, f"fab_L{layer}", rf, "ref",
    )
    # Name alias only. 0 V between lin and p is not a gain copy.
    lines.append(f"V{tag}alias {tag}lin {vg} DC 0")
    if i_leak:
        lines.append(f"B{tag}leak 0 {vg} I = {i_leak:.15g}")


def generate_passive(
    arch: str,
    spec: dict,
    weights: dict[str, np.ndarray],
    params: IVParams,
) -> tuple[str | None, list[dict], str | None]:
    if arch not in {"P", "L"}:
        raise KeyError(arch)
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

    mesh = arch == "L"
    h_src = _collect_with_source(hidden_enc, 1, False)
    o_src = _collect_with_source(out_enc, 2, False)
    if mesh:
        rewritten = []
        for j, encoded in o_src:
            rows = []
            for item in encoded:
                row = dict(item)
                row["_src"] = mesh_hidden_src(row["_src"])
                rows.append(row)
            rewritten.append((j, rows))
        o_src = rewritten

    loads1 = _tap_loads_src(h_src)
    loads2 = _tap_loads_src(o_src)
    inv_a = params.invert_gain

    lines = [
        f"* Physical AI - Experiment 18 architecture {arch}: "
        f"{ARCH_PUBLIC[arch]['title']}",
        f"* {ARCH_PUBLIC[arch]['iv_topology']}",
        f"* Frozen Experiment 9 network {spec['id']}. Weights were not edited.",
        "* Behavioral circuit analysis. Not transistor-level or PCB power.",
        f"* invert A={inv_a:g} Ileak={params.i_leak:g} rail={params.rail:g} "
        f"linear={params.linear} mesh={mesh}",
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
        _emit_weights_src(
            lines, catalog, tag, weights["W1"][j], encoded, cfg.g_weight_1, 1
        )
        emit_passive_rf(
            lines, catalog, tag, cfg.g_weight_1, 1, params.i_leak
        )
        if mesh:
            lines.append(
                f"* mesh hidden: no ReLU. layer 2 attaches to {tag}p"
            )
        else:
            _emit_relu_v(lines, tag, params.rail, params.linear)
        lines.append("")

    for j in range(1, n_hidden + 1):
        if mesh:
            src = f"h{j}p"
            inv_dest = f"h{j}pn"
            if need(f"h{j}pn", f"htap{j}n"):
                _emit_passive_invert(
                    lines, catalog, src, inv_dest, f"invh{j}", 2, inv_a
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
                    lines, catalog, inv_dest, f"htap{j}n", f"divh{j}n",
                    loads2.get(f"htap{j}n", 0.0), 2,
                )
                if reason:
                    return None, catalog, reason
        else:
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
        emit_passive_rf(
            lines, catalog, tag, cfg.g_weight_2, 2, params.i_leak
        )
        lines.append("")

    lines.extend(_control(n_out))
    return "\n".join(lines), catalog, None


def compile_passive(
    arch: str,
    spec: dict,
    weights: dict[str, np.ndarray],
    params: IVParams | None = None,
) -> tuple[str | None, list[dict], str | None]:
    p = params or IVParams(name=arch)
    if arch in {"I", "A"}:
        return compile_iv(arch, spec, weights, p)
    netlist, catalog, reason = generate_passive(arch, spec, weights, p)
    if reason or netlist is None:
        return None, catalog, reason
    annotate_catalog(catalog)
    stamp_signs(catalog)
    fabric = [c for c in catalog if c.get("role") != "amp_rout"]
    violation = range_violation(fabric, R_MIN, R_MAX)
    if violation is not None:
        return None, catalog, violation
    return netlist, catalog, None


def neuron_gtot(catalog: list[dict], tag: str) -> float:
    """Physical conductance of weight/bias resistors on one neuron."""
    prefix = f"R{tag}"
    g = 0.0
    for item in catalog:
        if item.get("role") not in {"weight", "bias"}:
            continue
        name = str(item["name"])
        if not name.startswith(prefix):
            continue
        rest = name[len(prefix):]
        if not rest or rest[0] not in "pnb":
            continue
        g += float(item.get("G") or 1.0 / float(item["R"]))
    return g


def attenuation_factors(
    spec: dict, catalog: list[dict], g_w1: float, g_w2: float
) -> dict:
    """k = 1 / (1 + Rf * G_tot) for isolated passive I-to-V."""
    k_h = []
    g_h = []
    for j in range(1, spec["n_hidden"] + 1):
        g = neuron_gtot(catalog, f"h{j}")
        rf = 1.0 / float(g_w1)
        k_h.append(1.0 / (1.0 + rf * g) if (1.0 + rf * g) else None)
        g_h.append(g)
    k_o = []
    g_o = []
    for k in range(1, spec["n_out"] + 1):
        g = neuron_gtot(catalog, f"o{k}")
        rf = 1.0 / float(g_w2)
        k_o.append(1.0 / (1.0 + rf * g) if (1.0 + rf * g) else None)
        g_o.append(g)
    return {
        "k_hidden": k_h,
        "k_output": k_o,
        "G_hidden": g_h,
        "G_output": g_o,
        "Rf_hidden": 1.0 / float(g_w1),
        "Rf_output": 1.0 / float(g_w2),
        "k_hidden_mean": float(np.mean(k_h)) if k_h else None,
        "k_hidden_min": float(np.min(k_h)) if k_h else None,
        "k_hidden_max": float(np.max(k_h)) if k_h else None,
        "k_output_mean": float(np.mean(k_o)) if k_o else None,
        "note": (
            "Predicted V = k * z with k = 1/(1+Rf G_tot) if every source "
            "shares Vsum and dest-at-0 divider compensation is ignored. "
            "This is a physics prediction, not a SPICE correction."
        ),
    }


def predicted_isolated_passive(
    inputs: np.ndarray,
    weights: dict[str, np.ndarray],
    k_h: list[float],
    k_o: list[float],
    rail: float,
    linear: bool = False,
) -> np.ndarray:
    """Layered map with per-neuron passive attenuation. Not a SPICE fix."""
    x = np.atleast_2d(np.asarray(inputs, dtype=float))
    z1 = x @ weights["W1"].T + weights["b1"]
    h = z1 * np.asarray(k_h, dtype=float)
    if not linear:
        h = np.maximum(0.0, np.minimum(rail, h))
    z2 = h @ weights["W2"].T + weights["b2"]
    return z2 * np.asarray(k_o, dtype=float)


def unit_cell(
    arch: str,
    w: list[float],
    bias: float,
    g_w: float = 3e-5,
    tia_a: float = DEFAULT_GAIN,
    r_next: float | None = None,
) -> tuple[str, float, float]:
    """2-input signed neuron. Nodes: sum, lin. Optional next-layer load."""
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
        f"* Experiment 18 unit cell {arch}",
        f"* math y = {w1:g}*x1 + {w2:g}*x2 + {bias:g}",
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
    for name, src, mag in mapping:
        if mag > 0.0:
            lines.append(f"{name} {src} {dest} {rmag(mag):.15g}")

    g_tot = g_w * sum(parts.values())
    lines.append(f"* G_tot={g_tot:.15g} Rf={rf:.15g} RfG={rf * g_tot:.15g}")

    if arch == "P":
        lines += [
            f"Rf {dest} 0 {rf:.15g}",
            f"Vwire lin {dest} DC 0",
        ]
    elif arch == "Q":
        # Passive I-to-V plus one next-layer resistor to a 0 V next sum.
        lines += [
            f"Rf {dest} 0 {rf:.15g}",
            f"Vwire lin {dest} DC 0",
            f"Rnext lin next {float(r_next or rf):.15g}",
            "Vnext next 0 DC 0",
        ]
        g_tot = g_tot + 1.0 / float(r_next or rf)
    elif arch == "I":
        lines += [
            f"Vsense {dest} 0 DC 0",
            "Biv 0 lin I = i(Vsense)",
            f"Riv lin 0 {rf:.15g}",
        ]
    elif arch == "A":
        lines += [
            f"Etia raw 0 0 {dest} {tia_a:.15g}",
            f"Rfb raw {dest} {rf:.15g}",
            "Rra raw midr 10000",
            "Rrb lin midr 10000.200002",
            "Esgn lin 0 0 midr 1e5",
        ]
    else:
        raise KeyError(arch)

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
    return "\n".join(lines), g_tot, rf


def charge_dc_netlist(i_amp: float = 3e-5, c_f: float = 1e-9) -> str:
    return "\n".join(
        [
            "* Experiment 18 charge-domain DC (capacitor is open)",
            f"Iin 0 cap DC {i_amp:.15g}",
            f"C1 cap 0 {c_f:.15g}",
            ".ic v(cap)=0",
            ".control",
            "set numdgt=15",
            "op",
            "print v(cap)",
            ".endc",
            ".end",
            "",
        ]
    )


def charge_tran_netlist(
    i_amp: float = 3e-5, c_f: float = 1e-9, t_stop: float = 1e-6
) -> str:
    return "\n".join(
        [
            "* Experiment 18 charge-domain transient V=(I/C)*t",
            f"Iin 0 cap DC {i_amp:.15g}",
            f"C1 cap 0 {c_f:.15g}",
            ".ic v(cap)=0",
            f".tran {t_stop / 100.0:.15g} {t_stop:.15g} uic",
            ".control",
            "set numdgt=15",
            "run",
            f"print v(cap)",
            ".endc",
            ".end",
            "",
        ]
    )


def accounting(netlist: str, catalog: list[dict], n_weights: int) -> dict:
    base = iv_accounting(netlist, catalog, n_weights)
    inv = iv_inventory(netlist)
    n_alias = sum(
        1
        for raw in netlist.splitlines()
        if raw.strip().startswith("V") and "alias" in raw.lower()
    )
    base["n_name_aliases"] = n_alias
    base["n_tia_opamps"] = inv["n_tia_opamps"]
    base["n_current_dumps"] = inv["n_current_dumps"]
    base["leftover_current_copies"] = inv["leftover_current_copies"]
    base["note_aliases"] = (
        "V*alias is a 0 V name wire so the harness can print v(*lin). "
        "It is not a current-to-voltage gain copy."
    )
    return base
