"""Experiment 20: current-mode cascade bound.

Question: can hidden I-to-V be removed by staying in current until after
the nonlinearity, then feeding the next layer without converting to voltage?

Architecture I: Experiment 16 dump baseline (hidden voltage exists).
Architecture J: hidden 0 V node + current ReLU. Each W2 weight is a CCCS
    that copies I_y with gain w. Output neurons still dump onto R_IV.
    This delays voltage conversion but explodes current copies.
Architecture S: hidden 0 V + current ReLU, then a resistive current
    splitter into the next 0 V sums. I_k = I_y * G_k / G_tot, which is
    not I_y * w_k for unnormalized frozen W2.

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
    _emit_i_weights,
    _emit_single_iv,
    _source_node_i,
    _tap_loads,
    compile_copy,
)
from dynamic_range_compiler import range_violation
from mismatch_fabric import stamp_signs
from physical_iv_neuron import DEFAULT_GAIN, IVParams, accounting as iv_accounting
from precision_architectures import ARCH_C_CFG, R_MAX, R_MIN
from ratiometric_compiler import annotate_catalog


CIRCUIT_DIR = PROJECT_ROOT / "circuits" / "current_cascade"
ARCH_KEYS = ("I", "J", "S")

ARCH_PUBLIC = {
    "I": {
        "title": "Experiment 16 Architecture I (voltage after every neuron)",
        "topology": "0 V sum, current dump, voltage ReLU, next resistors",
    },
    "J": {
        "title": "current-mode hidden + per-weight CCCS",
        "topology": (
            "Hidden: 0 V + I_y=max(0,I_sum). Each W2 weight is a CCCS "
            "copy of I_y. Output: dump onto R_IV. No hidden TIA."
        ),
    },
    "S": {
        "title": "current-mode hidden + resistive current splitter",
        "topology": (
            "Hidden: 0 V + I_y into a resistor star. Next 0 V nodes take "
            "I_k = I_y * G_k/G_tot. Not a frozen matrix multiply."
        ),
    },
}


def generate_j(
    spec: dict,
    weights: dict[str, np.ndarray],
    params: IVParams,
) -> tuple[str | None, list[dict], str | None]:
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

    loads1 = _tap_loads(hidden_enc, 1)
    inv_a = params.invert_gain

    def uses(layer_enc, layer, node):
        for _j, encoded in layer_enc:
            for item in encoded:
                if _source_node_i(item, layer) == node:
                    return True
        return False

    lines = [
        f"* Physical AI - Experiment 20 architecture J: {ARCH_PUBLIC['J']['title']}",
        f"* {ARCH_PUBLIC['J']['topology']}",
        f"* Frozen Experiment 9 network {spec['id']}. Weights were not edited.",
        "* Behavioral circuit analysis. Not transistor-level or PCB power.",
        f"* invert A={inv_a:g} rail={params.rail:g}",
        f"* shape: {n_in} -> {n_hidden} -> {n_out}",
        "",
    ]
    for i in range(1, n_in + 1):
        lines.append(f"Vin{i} in{i} 0 DC 0")
        if uses(hidden_enc, 1, f"in{i}n") or uses(hidden_enc, 1, f"tap{i}n"):
            _emit_passive_invert(
                lines, catalog, f"in{i}", f"in{i}n", f"inv{i}", 1, inv_a
            )
        if uses(hidden_enc, 1, f"tap{i}"):
            reason = _emit_compensated_divider(
                lines, catalog, f"in{i}", f"tap{i}", f"div{i}",
                loads1.get(f"tap{i}", 0.0), 1,
            )
            if reason:
                return None, catalog, reason
        if uses(hidden_enc, 1, f"tap{i}n"):
            reason = _emit_compensated_divider(
                lines, catalog, f"in{i}n", f"tap{i}n", f"div{i}n",
                loads1.get(f"tap{i}n", 0.0), 1,
            )
            if reason:
                return None, catalog, reason
    lines.append("Vref vref 0 DC 1")
    need_vrefn = bool(np.any(np.asarray(weights["b2"], dtype=float) < 0.0))
    if uses(hidden_enc, 1, "vrefn") or uses(hidden_enc, 1, "taprefn") or need_vrefn:
        _emit_passive_invert(lines, catalog, "vref", "vrefn", "invref", 1, inv_a)
    if uses(hidden_enc, 1, "tapref"):
        reason = _emit_compensated_divider(
            lines, catalog, "vref", "tapref", "divref",
            loads1.get("tapref", 0.0), 1,
        )
        if reason:
            return None, catalog, reason
    if uses(hidden_enc, 1, "taprefn"):
        reason = _emit_compensated_divider(
            lines, catalog, "vrefn", "taprefn", "divrefn",
            loads1.get("taprefn", 0.0), 1,
        )
        if reason:
            return None, catalog, reason
    lines.append("")

    # Hidden: 0 V + current ReLU sensed by a 0 V dump of I_y.
    for j, encoded in hidden_enc:
        tag = f"h{j + 1}"
        _emit_i_weights(
            lines, catalog, tag, weights["W1"][j], encoded, cfg.g_weight_1, 1
        )
        lines.append(f"V{tag}p {tag}p 0 DC 0")
        lines.append(
            f"B{tag}crelu 0 {tag}iy I = max(0, i(V{tag}p))"
        )
        lines.append(f"V{tag}iy {tag}iy 0 DC 0")
        lines.append(
            f"* current-mode hidden {tag}: I_y = max(0, I_sum), "
            f"no hidden voltage"
        )
        lines.append("")

    # Output biases still need vref paths (voltage-mode bias onto 0 V output).
    # W2 weights are CCCS from each hidden I_y.
    g2 = cfg.g_weight_2
    for k in range(n_out):
        tag = f"o{k + 1}"
        wrow = weights["W2"][k]
        bias = float(weights["b2"][k])
        for j in range(n_hidden):
            w = float(wrow[j])
            if abs(w) < 1e-18:
                continue
            # I_contrib = w * I_y. Sense I_y through Vh{j}iy.
            # Sign: positive w injects into op; negative extracts.
            gain = w
            lines.append(
                f"F{tag}h{j + 1} 0 {tag}p Vh{j + 1}iy {gain:.15g}"
            )
        # Bias current I = b * G_WEIGHT into the 0 V output node.
        # Same physics as Vref/R when R fits 1k-1M. Small b would need
        # R > 1M, so the current is stated directly. Frozen b, not a fit.
        if abs(bias) > 1e-18:
            i_b = g2 * bias
            lines.append(
                f"* output bias current {tag}: I={i_b:.15g} = b*{g2:.15g} "
                f"(b={bias:.15g} frozen)"
            )
            lines.append(f"B{tag}bias 0 {tag}p I = {i_b:.15g}")
        _emit_single_iv(lines, catalog, tag, g2, 2, params.i_leak, params.vos)
        lines.append("")

    # Fine-bank W2 is ignored: CCCS uses the full frozen w, not the
    # resistor encoding. That is a current-gain copy, which is the point.
    lines.extend(_control(n_out))
    return "\n".join(lines), catalog, None


def generate_s(
    spec: dict,
    weights: dict[str, np.ndarray],
    params: IVParams,
) -> tuple[str | None, list[dict], str | None]:
    """Current splitter: I_k = I_y * |w_k| / sum|w| with sign via dest."""
    cfg = ARCH_C_CFG[spec["id"]]
    catalog: list[dict] = []
    n_in, n_hidden, n_out = spec["n_in"], spec["n_hidden"], spec["n_out"]
    hidden_enc, reason = _collect_encoded(
        weights["W1"], weights["b1"], cfg.g_weight_1, cfg.banks
    )
    if reason or hidden_enc is None:
        return None, catalog, f"layer 1: {reason}"
    loads1 = _tap_loads(hidden_enc, 1)
    inv_a = params.invert_gain

    def uses(node):
        for _j, encoded in hidden_enc:
            for item in encoded:
                if _source_node_i(item, 1) == node:
                    return True
        return False

    lines = [
        f"* Physical AI - Experiment 20 architecture S: {ARCH_PUBLIC['S']['title']}",
        f"* {ARCH_PUBLIC['S']['topology']}",
        f"* Frozen Experiment 9 network {spec['id']}. Weights were not edited.",
        f"* shape: {n_in} -> {n_hidden} -> {n_out}",
        "",
    ]
    for i in range(1, n_in + 1):
        lines.append(f"Vin{i} in{i} 0 DC 0")
        if uses(f"in{i}n") or uses(f"tap{i}n"):
            _emit_passive_invert(
                lines, catalog, f"in{i}", f"in{i}n", f"inv{i}", 1, inv_a
            )
        if uses(f"tap{i}"):
            reason = _emit_compensated_divider(
                lines, catalog, f"in{i}", f"tap{i}", f"div{i}",
                loads1.get(f"tap{i}", 0.0), 1,
            )
            if reason:
                return None, catalog, reason
        if uses(f"tap{i}n"):
            reason = _emit_compensated_divider(
                lines, catalog, f"in{i}n", f"tap{i}n", f"div{i}n",
                loads1.get(f"tap{i}n", 0.0), 1,
            )
            if reason:
                return None, catalog, reason
    lines.append("Vref vref 0 DC 1")
    need_vrefn = bool(np.any(np.asarray(weights["b2"], dtype=float) < 0.0))
    if uses("vrefn") or uses("taprefn") or need_vrefn:
        _emit_passive_invert(lines, catalog, "vref", "vrefn", "invref", 1, inv_a)
    if uses("tapref"):
        reason = _emit_compensated_divider(
            lines, catalog, "vref", "tapref", "divref",
            loads1.get("tapref", 0.0), 1,
        )
        if reason:
            return None, catalog, reason
    if uses("taprefn"):
        reason = _emit_compensated_divider(
            lines, catalog, "vrefn", "taprefn", "divrefn",
            loads1.get("taprefn", 0.0), 1,
        )
        if reason:
            return None, catalog, reason
    lines.append("")

    g2 = cfg.g_weight_2
    for j, encoded in hidden_enc:
        tag = f"h{j + 1}"
        _emit_i_weights(
            lines, catalog, tag, weights["W1"][j], encoded, cfg.g_weight_1, 1
        )
        lines.append(f"V{tag}p {tag}p 0 DC 0")
        lines.append(f"B{tag}crelu 0 {tag}spl I = max(0, i(V{tag}p))")
        wcol = weights["W2"][:, j]
        # Splitter resistors from {tag}spl to each output 0 V node.
        for k, w in enumerate(wcol):
            mag = abs(float(w))
            if mag < 1e-18:
                continue
            r = 1.0 / (g2 * mag)
            dest = f"o{k + 1}p" if w >= 0 else f"o{k + 1}n"
            name = f"R{tag}s{k + 1}"
            lines.append(f"{name} {tag}spl {dest} {r:.15g}")
            catalog.append(
                {
                    "name": name,
                    "comment": f"splitter {tag}->o{k + 1} w={float(w):+.15g}",
                    "role": "weight",
                    "layer": 2,
                    "match_group": "split",
                    "R": r,
                    "G": 1.0 / r,
                    "bank": "n",
                }
            )
        lines.append("")

    for k in range(n_out):
        tag = f"o{k + 1}"
        bias = float(weights["b2"][k])
        if abs(bias) > 1e-18:
            r_b = 1.0 / (g2 * abs(bias))
            src = "vref" if bias > 0 else "vrefn"
            lines.append(f"R{tag}b {src} {tag}p {r_b:.15g}")
        # Difference I+ - I- then dump. Negative split dest is {tag}n.
        lines.append(f"V{tag}p {tag}p 0 DC 0")
        lines.append(f"V{tag}n {tag}n 0 DC 0")
        lines.append(f"B{tag}sub 0 {tag}lin I = i(V{tag}p) - i(V{tag}n)")
        lines.append(f"R{tag}iv {tag}lin 0 {1.0 / g2:.15g}")
        catalog.append(
            {
                "name": f"R{tag}iv",
                "comment": f"{tag} I-to-V",
                "role": "reference",
                "layer": 2,
                "match_group": "fab_L2",
                "R": 1.0 / g2,
                "G": g2,
                "bank": "ref",
            }
        )
        lines.append("")

    lines.extend(_control(n_out))
    return "\n".join(lines), catalog, None


def compile_cascade(
    arch: str,
    spec: dict,
    weights: dict[str, np.ndarray],
    params: IVParams | None = None,
) -> tuple[str | None, list[dict], str | None]:
    p = params or IVParams(name=arch)
    if arch == "I":
        return compile_copy("I", spec, weights)
    if arch == "J":
        netlist, catalog, reason = generate_j(spec, weights, p)
    elif arch == "S":
        netlist, catalog, reason = generate_s(spec, weights, p)
    else:
        raise KeyError(arch)
    if reason or netlist is None:
        return None, catalog, reason
    annotate_catalog(catalog)
    stamp_signs(catalog)
    # J CCCS gains are not resistors; skip range on empty extras.
    if catalog:
        fabric = [c for c in catalog if c.get("role") != "amp_rout"]
        if fabric:
            violation = range_violation(fabric, R_MIN, R_MAX)
            if violation is not None:
                return None, catalog, violation
    return netlist, catalog, None


def split_unit_cell(i_y: float, w1: float, w2: float, g_w: float = 3e-5) -> str:
    """I_y into two resistors to 0 V. Prints i(V1), i(V2)."""
    r1 = 1.0 / (g_w * abs(w1))
    r2 = 1.0 / (g_w * abs(w2))
    return "\n".join(
        [
            f"* Experiment 20 current-split unit Iy={i_y:g} w=[{w1:g},{w2:g}]",
            f"Iy 0 mid DC {i_y:.15g}",
            f"R1 mid n1 {r1:.15g}",
            f"R2 mid n2 {r2:.15g}",
            "V1 n1 0 DC 0",
            "V2 n2 0 DC 0",
            ".control",
            "set numdgt=15",
            "op",
            "print i(V1)",
            "print i(V2)",
            ".endc",
            ".end",
            "",
        ]
    )


def cccs_unit_cell(i_y: float, w1: float, w2: float) -> str:
    """One current copy per weight: I_k = w_k * I_y."""
    return "\n".join(
        [
            f"* Experiment 20 CCCS unit Iy={i_y:g} w=[{w1:g},{w2:g}]",
            f"Iy 0 sense DC {i_y:.15g}",
            "Vsense sense 0 DC 0",
            f"F1 0 o1 Vsense {w1:.15g}",
            f"F2 0 o2 Vsense {w2:.15g}",
            "V1 o1 0 DC 0",
            "V2 o2 0 DC 0",
            ".control",
            "set numdgt=15",
            "op",
            "print i(V1)",
            "print i(V2)",
            ".endc",
            ".end",
            "",
        ]
    )


def accounting(netlist: str, catalog: list[dict], n_weights: int) -> dict:
    base = iv_accounting(netlist, catalog, n_weights)
    n_f = sum(
        1
        for raw in netlist.splitlines()
        if raw.strip()[:1].upper() == "F" and not raw.strip().startswith("*")
    )
    n_crelu = sum(
        1
        for raw in netlist.splitlines()
        if raw.strip().startswith("B") and "crelu" in raw.lower()
    )
    base["n_cccs"] = n_f
    base["n_current_relu"] = n_crelu
    base["cascade_note"] = (
        "J uses one CCCS per W2 weight. S uses a resistor splitter. "
        "Neither is a transistor current mirror."
    )
    return base
