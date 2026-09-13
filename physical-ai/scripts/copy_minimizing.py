"""Experiment 16: copy-minimizing fabrics on the ratiometric weight encoding.

Architecture D (baseline): Experiment 14 physical R_IV, dual CCCS copies
    for I+ minus I-, unity VCVS buffers on every divider tap, extra unity
    VCVS after I-to-V and ReLU.

Architecture I (current-mode): no dual current conveyors. Negative weights
    use a passive inverting amplifier (resistor ratio + high-gain VCVS).
    All signed currents meet on one 0 V summing node so I = V/R is exact.
    A single current dump onto physical R_IV does I-to-V. Fine-bank taps
    are load-compensated dividers with no isolation buffer. A finite-A
    feedback TIA was measured and rejected: the summing node sits at V/A
    and that residual unloads the unbuffered taps. ReLU B-source drives
    the next layer directly.

Architecture M (matched copies): Architecture D resistors and dividers,
    but I+ and I- are subtracted by one behavioral current source
        I = i(V+) - i(V-)
    so a single gain exists. Common copy error remains; polarity mismatch
    between two conveyors cannot exist.

Frozen Experiment 9 weights. No Python output correction. Behavioral
circuit analysis, not transistor-level or PCB design.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from compile_xor import OPAMP_GAIN, PROJECT_ROOT
from dynamic_range_compiler import (
    encode_parameters,
    range_violation,
    _emit_resistor,
)
from mismatch_fabric import path_sign, stamp_signs
from precision_architectures import (
    ARCH_C_CFG,
    DIVIDER_BETA,
    DIVIDER_RB,
    R_MAX,
    R_MIN,
    _count_devices,
)
from ratiometric_compiler import (
    annotate_catalog,
    compile_ratiometric,
    accounting as fabric_accounting,
)


CIRCUIT_DIR = PROJECT_ROOT / "circuits" / "copy_minimizing"
TIA_GAIN = float(OPAMP_GAIN)
R_INV = 10_000.0
ARCH_KEYS = ("D", "I", "M")


@dataclass(frozen=True)
class CopyParams:
    name: str
    copy_common: float = 0.0
    copy_polarity: float = 0.0
    buf_gain: float = 0.0
    invert_polarity: float = 0.0
    tia_vos: float = 0.0
    relu_vos: float = 0.0
    i_leak: float = 0.0

    def public(self) -> dict:
        row = asdict(self)
        row["note"] = (
            "copy_common scales the current-copy / subtractor (D/M) or the "
            "TIA open-loop gain (I). copy_polarity unbalances + vs - copies "
            "(D dual CCCS; I invert-pair R2; M has one subtractor). "
            "buf_gain scales leftover VCVS copies. invert_polarity is an "
            "I-only extra unbalance of the invert pair. tia_vos is TIA "
            "input offset. These are behavioral sources, not transistors."
        )
        return row


ARCH_PUBLIC = {
    "D": {
        "title": "Experiment 14 Architecture D (dual CCCS + buffered dividers)",
        "copy_mechanism": (
            "Two unity CCCS conveyors form I+ minus I- onto physical R_IV. "
            "Unity VCVS buffers isolate divider taps."
        ),
    },
    "I": {
        "title": "current-mode invert-and-sum, unbuffered compensated dividers",
        "copy_mechanism": (
            "Passive inverting amplifiers (R ratio) create -Vin. One 0 V "
            "summing node per neuron. One current dump onto physical R_IV. "
            "Fine taps load-compensated, no isolation buffer. No dual CCCS."
        ),
    },
    "M": {
        "title": "matched current subtractor on Architecture D fabric",
        "copy_mechanism": (
            "Same resistors and divider buffers as D. One B-source "
            "I = i(V+) - i(V-) replaces the dual CCCS pair."
        ),
    },
}


def _header(arch: str, spec: dict, extra: str) -> list[str]:
    meta = ARCH_PUBLIC[arch]
    return [
        f"* Physical AI - Experiment 16 architecture {arch}: {meta['title']}",
        f"* {meta['copy_mechanism']}",
        f"* Frozen Experiment 9 network {spec['id']}. Weights were not edited.",
        "* Behavioral circuit analysis. Not transistor-level or PCB power.",
        extra,
        f"* shape: {spec['n_in']} -> {spec['n_hidden']} -> {spec['n_out']}",
        "",
    ]


def _control(n_out: int) -> list[str]:
    lines = [".control", "set numdgt=15", "op"]
    for k in range(1, n_out + 1):
        lines.append(f"print v(o{k}lin)")
    lines.extend([".endc", ".end", ""])
    return lines


def compensated_ra(
    g_load: float,
    rb: float = DIVIDER_RB,
    beta: float = DIVIDER_BETA,
) -> tuple[float | None, str | None]:
    """Ra so loaded divider tap is still beta * Vsrc (dest ~ 0 V)."""
    g_rb = 1.0 / float(rb)
    denom = 1.0 - float(beta)
    if denom <= 0.0:
        return None, "beta >= 1"
    g_ra = (g_rb + float(g_load)) * float(beta) / denom
    if g_ra <= 0.0:
        return None, f"non-positive G_ra (G_load={g_load:.6g})"
    ra = 1.0 / g_ra
    if ra < R_MIN or ra > R_MAX:
        return None, f"compensated Ra={ra:.6g} outside [{R_MIN:g}, {R_MAX:g}]"
    return ra, None


def invert_r2(r1: float, amp_gain: float) -> float:
    """R2 so closed-loop invert is -1 for finite open-loop gain A.

    Vout = -Vin * k * A / (A + 1 + k), k=R2/R1.
    k = (A+1)/(A-1) gives Vout = -Vin.
    """
    a = float(amp_gain)
    return float(r1) * (a + 1.0) / (a - 1.0)


def _stamp(catalog: list[dict], start: int, layer: int, match_group: str | None = None) -> None:
    for item in catalog[start:]:
        item["layer"] = layer
        if match_group is not None:
            item["match_group"] = match_group


def _emit_passive_invert(
    lines: list[str],
    catalog: list[dict],
    src: str,
    dest: str,
    stem: str,
    layer: int,
    amp_gain: float,
) -> None:
    mid = f"{stem}m"
    r1 = R_INV
    r2 = invert_r2(r1, amp_gain)
    ra_name = f"R{stem}ia"
    rb_name = f"R{stem}ib"
    lines.append(
        f"* passive invert {src} -> {dest}: R2/R1={(r2 / r1):.12g} "
        f"closed-loop -1 at A={amp_gain:g}"
    )
    lines.append(f"{ra_name} {src} {mid} {r1:.15g}")
    lines.append(f"{rb_name} {dest} {mid} {r2:.15g}")
    lines.append(f"E{stem}amp {dest} 0 0 {mid} {amp_gain:.15g}")
    start = len(catalog)
    for name, res, which in ((ra_name, r1, "a"), (rb_name, r2, "b")):
        catalog.append(
            {
                "name": name,
                "comment": f"passive invert {stem}{which}",
                "role": "invert",
                "layer": layer,
                "match_group": f"inv_{stem}",
                "R": res,
                "G": 1.0 / res,
                "bank": "invert",
            }
        )
    _stamp(catalog, start, layer, f"inv_{stem}")


def _emit_compensated_divider(
    lines: list[str],
    catalog: list[dict],
    src: str,
    tap: str,
    stem: str,
    g_load: float,
    layer: int,
) -> str | None:
    ra, reason = compensated_ra(g_load)
    if reason or ra is None:
        return f"divider {stem}: {reason}"
    rb = DIVIDER_RB
    ra_name = f"R{stem}a"
    rb_name = f"R{stem}b"
    lines.append(
        f"* load-compensated divider {src}->{tap}: "
        f"G_load={g_load:.15g} Ra={ra:.15g} Rb={rb:.15g} "
        f"target beta={DIVIDER_BETA:g} (no tap buffer)"
    )
    lines.append(f"{ra_name} {src} {tap} {ra:.15g}")
    lines.append(f"{rb_name} {tap} 0 {rb:.15g}")
    start = len(catalog)
    for name, res, which in ((ra_name, ra, "a"), (rb_name, rb, "b")):
        catalog.append(
            {
                "name": name,
                "comment": f"compensated divider {stem}{which}",
                "role": "divider",
                "layer": layer,
                "match_group": f"div_{stem}",
                "R": res,
                "G": 1.0 / res,
                "bank": "divider",
                "g_load": g_load,
            }
        )
    _stamp(catalog, start, layer, f"div_{stem}")
    return None


def _emit_single_iv(
    lines: list[str],
    catalog: list[dict],
    tag: str,
    g_weight: float,
    layer: int,
    i_leak: float,
    vos: float,
) -> None:
    """Exact 0 V summing node + one current dump onto physical R_IV."""
    r_iv = 1.0 / float(g_weight)
    vg = f"{tag}p"
    lin = f"{tag}lin"
    lines.append(
        f"* single-copy I-to-V: 0 V sum {vg}, I dump onto R_IV={r_iv:.15g}"
    )
    lines.append(f"V{tag}p {vg} 0 DC 0")
    if vos == 0.0:
        lines.append(f"B{tag}iv 0 {lin} I = i(V{tag}p)")
    else:
        lines.append(
            f"B{tag}iv 0 {lin} I = i(V{tag}p) + ({vos:.15g})/{r_iv:.15g}"
        )
    lines.append(f"R{tag}iv {lin} 0 {r_iv:.15g}")
    catalog.append(
        {
            "name": f"R{tag}iv",
            "comment": f"{tag} physical single-copy I-to-V",
            "role": "reference",
            "layer": layer,
            "match_group": f"fab_L{layer}",
            "R": r_iv,
            "G": g_weight,
            "bank": "ref",
        }
    )
    if i_leak:
        lines.append(f"B{tag}leak 0 {lin} I = {i_leak:.15g}")


def _source_node_i(
    item: dict,
    layer: int,
) -> str:
    sign = item["sign"]
    bank = item["bank"]
    # w+ uses the uninverted source; w- uses the passive invert.
    # Then I through the 0 V summing node is Vin*(G+ - G-).
    if item["kind"] == "bias":
        if bank == "n":
            return "vref" if sign == "p" else "vrefn"
        return "tapref" if sign == "p" else "taprefn"
    idx = int(item["source_index"])
    if layer == 1:
        if bank == "n":
            return f"in{idx}" if sign == "p" else f"in{idx}n"
        return f"tap{idx}" if sign == "p" else f"tap{idx}n"
    if bank == "n":
        return f"h{idx}y" if sign == "p" else f"h{idx}yn"
    return f"htap{idx}" if sign == "p" else f"htap{idx}n"


def _collect_encoded(
    weight_rows: np.ndarray,
    biases: np.ndarray,
    g_w: float,
    banks,
) -> tuple[list[tuple[int, list[dict]]] | None, str | None]:
    out: list[tuple[int, list[dict]]] = []
    for j, (wrow, bias) in enumerate(zip(weight_rows, biases)):
        encoded, reason = encode_parameters(
            wrow, float(bias), g_w, banks, R_MIN, R_MAX
        )
        if reason is not None or encoded is None:
            return None, f"neuron {j + 1}: {reason or 'encode failed'}"
        out.append((j, encoded))
    return out, None


def _tap_loads(encoded_layers: list[tuple[int, list[dict]]], layer: int) -> dict[str, float]:
    loads: dict[str, float] = defaultdict(float)
    for _j, encoded in encoded_layers:
        for item in encoded:
            node = _source_node_i(item, layer)
            if node.startswith("tap") or node.startswith("htap"):
                loads[node] += 1.0 / float(item["R"])
    return dict(loads)


def _emit_i_weights(
    lines: list[str],
    catalog: list[dict],
    tag: str,
    wrow: np.ndarray,
    encoded: list[dict],
    g_w: float,
    layer: int,
) -> None:
    start = len(catalog)
    for item in encoded:
        dest = f"{tag}p"
        src = _source_node_i(item, layer)
        if item["kind"] == "bias":
            name = f"R{tag}b{item['sign']}{item['bank']}{item['branch']}"
            comment = (
                f"{tag} bias w{'+' if item['sign'] == 'p' else '-'}"
            )
        else:
            idx = int(item["source_index"])
            name = f"R{tag}{item['sign']}{idx}{item['bank']}{item['branch']}"
            comment = (
                f"{tag} input {idx} w={float(wrow[idx - 1]):+.15g} "
                f"w{'+' if item['sign'] == 'p' else '-'}"
            )
        _emit_resistor(lines, catalog, name, src, dest, item, comment, g_w, layer)
    _stamp(catalog, start, layer, f"fab_L{layer}")


def generate_i(
    spec: dict,
    weights: dict[str, np.ndarray],
    i_leak: float = 0.0,
    rail: float = 15.0,
    linear: bool = False,
    amp_gain: float = TIA_GAIN,
    tia_vos: float = 0.0,
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
    loads2 = _tap_loads(out_enc, 2)

    def uses_node(encoded_layers, layer, node: str) -> bool:
        for _j, encoded in encoded_layers:
            for item in encoded:
                if _source_node_i(item, layer) == node:
                    return True
        return False

    lines = _header(
        "I",
        spec,
        f"* invert A={amp_gain:g} R_INV={R_INV:g} Ileak={i_leak:g} "
        f"rail={rail:g} linear={linear} vos={tia_vos:g}",
    )
    for i in range(1, n_in + 1):
        lines.append(f"Vin{i} in{i} 0 DC 0")
        if uses_node(hidden_enc, 1, f"in{i}n") or uses_node(hidden_enc, 1, f"tap{i}n"):
            _emit_passive_invert(
                lines, catalog, f"in{i}", f"in{i}n", f"inv{i}", 1, amp_gain
            )
        if uses_node(hidden_enc, 1, f"tap{i}"):
            reason = _emit_compensated_divider(
                lines, catalog, f"in{i}", f"tap{i}", f"div{i}",
                loads1.get(f"tap{i}", 0.0), 1,
            )
            if reason:
                return None, catalog, reason
        if uses_node(hidden_enc, 1, f"tap{i}n"):
            reason = _emit_compensated_divider(
                lines, catalog, f"in{i}n", f"tap{i}n", f"div{i}n",
                loads1.get(f"tap{i}n", 0.0), 1,
            )
            if reason:
                return None, catalog, reason
    lines.append("Vref vref 0 DC 1")
    if uses_node(hidden_enc, 1, "vrefn") or uses_node(hidden_enc, 1, "taprefn") or uses_node(
        out_enc, 2, "vrefn"
    ) or uses_node(out_enc, 2, "taprefn"):
        _emit_passive_invert(lines, catalog, "vref", "vrefn", "invref", 1, amp_gain)
    if uses_node(hidden_enc, 1, "tapref") or uses_node(out_enc, 2, "tapref"):
        g_ref = loads1.get("tapref", 0.0) + loads2.get("tapref", 0.0)
        reason = _emit_compensated_divider(
            lines, catalog, "vref", "tapref", "divref", g_ref, 1
        )
        if reason:
            return None, catalog, reason
    if uses_node(hidden_enc, 1, "taprefn") or uses_node(out_enc, 2, "taprefn"):
        g_refn = loads1.get("taprefn", 0.0) + loads2.get("taprefn", 0.0)
        reason = _emit_compensated_divider(
            lines, catalog, "vrefn", "taprefn", "divrefn", g_refn, 1
        )
        if reason:
            return None, catalog, reason
    lines.append("")

    for j, encoded in hidden_enc:
        tag = f"h{j + 1}"
        _emit_i_weights(
            lines, catalog, tag, weights["W1"][j], encoded, cfg.g_weight_1, 1
        )
        _emit_single_iv(
            lines, catalog, tag, cfg.g_weight_1, 1, i_leak, tia_vos
        )
        if linear:
            lines.append(f"* linear hidden: layer 2 reads v({tag}lin)")
        else:
            lines.append(
                f"* direct bounded ReLU, no output buffer: "
                f"y=max(0, min({rail:g}, v({tag}lin)))"
            )
            lines.append(
                f"B{tag}relu {tag}y 0 V = max(0, min({rail:.15g}, v({tag}lin)))"
            )
        lines.append("")

    for j in range(1, n_hidden + 1):
        src = f"h{j}lin" if linear else f"h{j}y"
        if uses_node(out_enc, 2, f"h{j}yn") or uses_node(out_enc, 2, f"htap{j}n"):
            _emit_passive_invert(
                lines, catalog, src, f"h{j}yn", f"invh{j}", 2, amp_gain
            )
        if uses_node(out_enc, 2, f"htap{j}"):
            reason = _emit_compensated_divider(
                lines, catalog, src, f"htap{j}", f"divh{j}",
                loads2.get(f"htap{j}", 0.0), 2,
            )
            if reason:
                return None, catalog, reason
        if uses_node(out_enc, 2, f"htap{j}n"):
            reason = _emit_compensated_divider(
                lines, catalog, f"h{j}yn", f"htap{j}n", f"divh{j}n",
                loads2.get(f"htap{j}n", 0.0), 2,
            )
            if reason:
                return None, catalog, reason

    lines.append("")
    for k, encoded in out_enc:
        tag = f"o{k + 1}"
        _emit_i_weights(
            lines, catalog, tag, weights["W2"][k], encoded, cfg.g_weight_2, 2
        )
        _emit_single_iv(
            lines, catalog, tag, cfg.g_weight_2, 2, i_leak, tia_vos
        )
        lines.append("")

    lines.extend(_control(n_out))
    return "\n".join(lines), catalog, None


def _replace_dual_cccs(netlist: str) -> str:
    """Architecture M: one subtractor in place of F+ / F-."""
    out: list[str] = []
    pending_p: dict[str, tuple[str, str]] = {}
    for raw in netlist.splitlines():
        parts = raw.split()
        if (
            parts
            and parts[0].startswith("F")
            and not parts[0].startswith("Fcal")
            and len(parts) >= 5
        ):
            name = parts[0]
            if name.endswith("p") and parts[3].startswith("V"):
                tag = name[1:-1]
                pending_p[tag] = (parts[2], parts[3])  # diff, Vamp
                continue
            if name.endswith("n") and parts[3].startswith("V"):
                tag = name[1:-1]
                info = pending_p.pop(tag, None)
                if info is not None:
                    diff, vp = info
                    vn = parts[3]
                    out.append(
                        f"* matched subtractor {tag}: I = i({vp}) - i({vn})"
                    )
                    out.append(
                        f"B{tag}sub 0 {diff} I = i({vp}) - i({vn})"
                    )
                    continue
        out.append(raw)
    if pending_p:
        leftover = ", ".join(sorted(pending_p))
        raise RuntimeError(f"unmatched CCCS +path for tags: {leftover}")
    ending = "\n" if netlist.endswith("\n") else ""
    return "\n".join(out) + ending


def compile_copy(
    arch: str,
    spec: dict,
    weights: dict[str, np.ndarray],
    params: CopyParams | None = None,
    i_leak: float = 0.0,
    rail: float = 15.0,
    linear: bool = False,
) -> tuple[str | None, list[dict], str | None]:
    leak = i_leak
    vos = 0.0
    if params is not None:
        if params.i_leak:
            leak = params.i_leak
        vos = params.tia_vos
    if arch == "D":
        netlist, catalog, reason = compile_ratiometric(
            "D", spec, weights, i_leak=leak, rail=rail, linear=linear
        )
    elif arch == "I":
        netlist, catalog, reason = generate_i(
            spec, weights, i_leak=leak, rail=rail, linear=linear, tia_vos=vos
        )
    elif arch == "M":
        netlist, catalog, reason = compile_ratiometric(
            "D", spec, weights, i_leak=leak, rail=rail, linear=linear
        )
        if reason or netlist is None:
            return None, catalog, reason
        netlist = _replace_dual_cccs(netlist)
    else:
        raise KeyError(arch)
    if reason or netlist is None:
        return None, catalog, reason
    annotate_catalog(catalog)
    stamp_signs(catalog)
    violation = range_violation(catalog, R_MIN, R_MAX)
    if violation is not None:
        return None, catalog, violation
    if params is not None:
        # Leak / TIA Vos already compiled into I. Do not duplicate leak.
        apply = CopyParams(
            name=params.name,
            copy_common=params.copy_common,
            copy_polarity=params.copy_polarity,
            buf_gain=params.buf_gain,
            invert_polarity=params.invert_polarity,
            tia_vos=0.0,
            relu_vos=params.relu_vos,
            i_leak=0.0,
        )
        netlist = apply_copy_params(netlist, arch, apply)
    return netlist, catalog, None


def apply_copy_params(netlist: str, arch: str, params: CopyParams) -> str:
    """Rewrite leftover macromodels. Resistor topology stays."""
    out: list[str] = []
    for raw in netlist.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("*") or stripped.startswith("."):
            out.append(raw)
            continue
        parts = raw.split()
        kind = parts[0][0].upper()
        if kind == "F" and len(parts) >= 5:
            name = parts[0]
            gain = 1.0 + params.copy_common
            if name.endswith("p"):
                gain *= 1.0 + params.copy_polarity
            elif name.endswith("n"):
                gain *= 1.0 - params.copy_polarity
            out.append(f"{parts[0]} {parts[1]} {parts[2]} {parts[3]} {gain:.15g}")
            continue
        if kind == "B" and parts[0].endswith("sub") and "I" in parts:
            # Matched subtractor: polarity cannot unbalance a single gain.
            # copy_polarity is ignored here on purpose.
            joined = " ".join(parts)
            if params.copy_common == 0.0:
                out.append(raw)
            else:
                eq = joined.split("=", 1)[1].strip()
                out.append(
                    f"{parts[0]} {parts[1]} {parts[2]} I = "
                    f"({1.0 + params.copy_common:.15g})*({eq})"
                )
            continue
        if kind == "B" and parts[0].endswith("iv") and "I" in parts:
            joined = " ".join(parts)
            if params.copy_common == 0.0:
                out.append(raw)
            else:
                eq = joined.split("=", 1)[1].strip()
                out.append(
                    f"{parts[0]} {parts[1]} {parts[2]} I = "
                    f"({1.0 + params.copy_common:.15g})*({eq})"
                )
            continue
        if kind == "B" and "relu" in parts[0].lower() and params.relu_vos != 0.0:
            joined = " ".join(parts)
            vos = params.relu_vos
            if "v(" in joined:
                out.append(joined.replace("v(", f"({vos:.15g}) + v(", 1))
            else:
                out.append(raw)
            continue
        if kind == "E" and len(parts) >= 6:
            name = parts[0]
            gain = float(parts[5])
            if arch == "I" and name.endswith("amp"):
                # Closed-loop invert: open-loop 0.1% should be absorbed.
                # Apply copy_common here so the sweep can show that immunity.
                gain *= 1.0 + params.copy_common
                out.append(
                    f"{parts[0]} {parts[1]} {parts[2]} {parts[3]} {parts[4]} "
                    f"{gain:.15g}"
                )
                continue
            if params.buf_gain == 0.0:
                out.append(raw)
                continue
            gain *= 1.0 + params.buf_gain
            out.append(
                f"{parts[0]} {parts[1]} {parts[2]} {parts[3]} {parts[4]} "
                f"{gain:.15g}"
            )
            continue
        if (
            kind == "R"
            and params.invert_polarity != 0.0
            and parts[0].endswith("ib")
            and "inv" in parts[0].lower()
        ):
            r = float(parts[3]) * (1.0 + params.invert_polarity)
            out.append(f"{parts[0]} {parts[1]} {parts[2]} {r:.15g}")
            continue
        out.append(raw)
    # I polarity can also be requested via copy_polarity (same Rib scale).
    if arch == "I" and params.copy_polarity != 0.0 and params.invert_polarity == 0.0:
        rewritten = []
        for raw in out:
            parts = raw.split()
            if (
                parts
                and parts[0].startswith("R")
                and parts[0].endswith("ib")
                and "inv" in parts[0].lower()
                and len(parts) >= 4
            ):
                r = float(parts[3]) * (1.0 + params.copy_polarity)
                rewritten.append(f"{parts[0]} {parts[1]} {parts[2]} {r:.15g}")
            else:
                rewritten.append(raw)
        out = rewritten
    ending = "\n" if netlist.endswith("\n") else ""
    return "\n".join(out) + ending


def copy_inventory(netlist: str) -> dict:
    """Count leftover analog copy machines. Not transistor counts."""
    n_cccs = n_vcvs = n_b = n_h = 0
    n_sub = n_tia = n_invert_amp = n_unity_e = 0
    for raw in netlist.splitlines():
        line = raw.strip()
        if not line or line.startswith("*") or line.startswith("."):
            continue
        kind = line[0].upper()
        parts = line.split()
        name = parts[0]
        if kind == "F":
            n_cccs += 1
        elif kind == "E":
            n_vcvs += 1
            low = name.lower()
            if low.endswith("amp"):
                if "inv" in low:
                    n_invert_amp += 1
                else:
                    n_tia += 1
            else:
                n_unity_e += 1
        elif kind == "B":
            n_b += 1
            if name.endswith("sub"):
                n_sub += 1
            if name.endswith("iv"):
                n_sub += 1
            if name.endswith("amp"):
                n_tia += 1
        elif kind == "H":
            n_h += 1
    return {
        "active_cccs": n_cccs,
        "active_vcvs": n_vcvs,
        "active_behavioral": n_b,
        "active_transimpedance": n_h,
        "n_matched_subtractors": n_sub,
        "n_tia_opamps": n_tia,
        "n_invert_opamps": n_invert_amp,
        "n_unity_vcvs": n_unity_e,
        "n_current_copies": n_cccs + n_sub,
        "leftover_copy_blocks": n_cccs + n_sub + n_unity_e,
        "closed_loop_opamps": n_tia + n_invert_amp,
        "active_functional_blocks": n_cccs + n_vcvs + n_b + n_h,
        "active_note": (
            "Counts are behavioral controlled sources, not transistors. "
            "leftover_copy_blocks = CCCS + matched subtractors + unity VCVS. "
            "Closed-loop op-amps set a resistor ratio and are listed separately."
        ),
    }


def accounting(netlist: str, catalog: list[dict], n_weights: int) -> dict:
    base = fabric_accounting(netlist, catalog, n_weights)
    inv = copy_inventory(netlist)
    n_inv_r = sum(1 for c in catalog if c.get("role") == "invert")
    devices = _count_devices(netlist)
    return {
        **base,
        **devices,
        **inv,
        "n_invert_resistors": n_inv_r,
        "passive_resistors": devices["passive_resistors"],
    }
