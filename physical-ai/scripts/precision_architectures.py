"""Experiment 13: precision-preserving physical encodings.

Architecture A: Experiment 11 current-gain banks (G_eff = alpha / R).
    Every bank, including alpha=1, uses a CCCS. Scale error on those
    gains is the Experiment 12 sensitivity.

Architecture B: multi-reference voltage encoding.
    I = V_range / R. Fine/medium copies of each input are generated in
    SPICE (VCVS). The nominal path is a passive resistor from Vin.
    Scale error is applied only to the extra range references.

Architecture C: passive input dividers plus unity buffers.
    Shared per-input resistor dividers create a beta=1e-3 voltage domain
    with both divider R in [1 kOhm, 1 MOhm]. A unity VCVS isolates the
    tap so weight resistors do not load the ratio. No per-weight CCCS
    multiplier. Unity current conveyors remain only for I+ minus I-
    and I-to-V.

Layer-level factorization S*((W/S)*X) was investigated and not used as
a standalone architecture: dividing every weight by S does not reduce
max|w|/min|w|, so Network F still cannot fit in 1 kOhm-1 MOhm without
a multi-range encoding.

Direct bounded ReLU (no high-gain feedback loop):
    y = max(0, min(rail, z))
When |z| < rail this matches software ReLU. It is labeled separately
from the Experiment 12 precision rectifier.

This is behavioral circuit analysis, not transistor-level design.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from compile_xor import OPAMP_GAIN, PROJECT_ROOT, RLOAD
from dynamic_range_compiler import (
    RangeConfig,
    _emit_resistor,
    encode_parameters,
    encoding_stats,
    range_violation,
)
from hardware_constrained_compiler import V_REP
from matter_compiler import total_conductance
from nonideal_blocks import EXP11_A, EXP11_F


CIRCUIT_DIR = PROJECT_ROOT / "circuits" / "precision_architectures"
R_MIN = 1.0e3
R_MAX = 1.0e6

# Stiffest 1e-3 divider with both R in [1k, 1M]: Ra=999k, Rb=1k.
DIVIDER_BETA = 1.0e-3
DIVIDER_RA = 999_000.0
DIVIDER_RB = 1_000.0

ARCH_A_CFG = {"A": EXP11_A, "F": EXP11_F}
ARCH_B_CFG = {
    "A": RangeConfig(3e-6, 3e-6, (("f", 1e-4), ("m", 1e-2), ("n", 1.0))),
    "F": RangeConfig(3e-5, 3e-5, (("f", 1e-4), ("m", 1e-2), ("n", 1.0))),
}
# Passive beta cannot realize 1e-4 with both R in range. A uses the same
# G_WEIGHT as F so the tiny A biases fit on the 1e-3 bank without a 1e-6
# cascade (that domain would be ~1 uV and offset-fragile).
ARCH_C_CFG = {
    "A": RangeConfig(3e-5, 3e-5, (("f", 1e-3), ("n", 1.0))),
    "F": RangeConfig(3e-5, 3e-5, (("f", 1e-3), ("n", 1.0))),
}


@dataclass(frozen=True)
class ArchSpec:
    key: str
    title: str
    scale_mechanism: str


ARCH_SPECS = {
    "A": ArchSpec(
        "A",
        "current-gain multi-range (Experiment 11 baseline)",
        "CCCS alpha on every bank, including unity",
    ),
    "B": ArchSpec(
        "B",
        "multi-reference voltage encoding",
        "VCVS range copies; nominal path is passive",
    ),
    "C": ArchSpec(
        "C",
        "passive input dividers plus unity buffers",
        "resistor-divider voltage domains; no per-weight CCCS gain",
    ),
}


def config_for(arch: str, net_id: str) -> RangeConfig:
    return {"A": ARCH_A_CFG, "B": ARCH_B_CFG, "C": ARCH_C_CFG}[arch][net_id]


def software_reference(
    x: np.ndarray,
    w1: np.ndarray,
    b1: np.ndarray,
    w2: np.ndarray,
    b2: np.ndarray,
    linear: bool = False,
    hidden_rail: float | None = None,
) -> np.ndarray:
    x = np.atleast_2d(np.asarray(x, dtype=float))
    z1 = x @ w1.T + b1
    if linear:
        hidden = z1
    else:
        hidden = np.maximum(0.0, z1)
        if hidden_rail is not None:
            hidden = np.minimum(hidden, hidden_rail)
    return hidden @ w2.T + b2


def hidden_preact_max(
    x: np.ndarray, w1: np.ndarray, b1: np.ndarray
) -> tuple[float, float]:
    z1 = np.atleast_2d(np.asarray(x, dtype=float)) @ w1.T + b1
    return float(np.max(z1)), float(np.max(np.maximum(0.0, z1)))


def bank_mass(catalog: list[dict]) -> dict[str, float]:
    mass: dict[str, float] = {}
    for item in catalog:
        if item.get("role") not in {"weight", "bias"}:
            continue
        bank = str(item.get("bank", "?"))
        geff = item.get("G_effective")
        if geff is None:
            geff = float(item.get("alpha", 1.0)) / float(item["R"])
        mass[bank] = mass.get(bank, 0.0) + abs(float(geff))
    total = sum(mass.values()) or 1.0
    return {k: v / total for k, v in sorted(mass.items())}


def _header(arch: str, spec: dict, extra: str) -> list[str]:
    meta = ARCH_SPECS[arch]
    return [
        f"* Physical AI - Experiment 13 architecture {arch}: {meta.title}",
        f"* {meta.scale_mechanism}",
        f"* Frozen Experiment 9 network {spec['id']}. Weights were not edited.",
        "* Behavioral circuit analysis. Not transistor-level or PCB power.",
        extra,
        f"* shape: {spec['n_in']} -> {spec['n_hidden']} -> {spec['n_out']}",
        "",
    ]


def _emit_range_copy(
    lines: list[str], name: str, dest: str, src: str, gain: float, vos: float
) -> None:
    if vos == 0.0:
        lines.append(f"E{name} {dest} 0 {src} 0 {gain:.15g}")
        return
    lines.append(
        f"B{name} {dest} 0 V = {gain:.15g} * v({src}) + ({vos:.15g})"
    )


def _emit_direct_relu(lines: list[str], tag: str, rail: float, linear: bool) -> None:
    lin = f"{tag}lin"
    buf = f"{tag}buf"
    if linear:
        lines.append(f"E{tag} {buf} 0 {lin} 0 1")
        return
    y = f"{tag}y"
    lines.append(
        f"* direct bounded ReLU: y=max(0, min({rail:g}, v({lin}))) "
        "no high-gain op-amp loop"
    )
    lines.append(f"B{tag}relu {y} 0 V = max(0, min({rail:.15g}, v({lin})))")
    lines.append(f"E{tag} {buf} 0 {y} 0 1")


def _emit_precision_relu(lines: list[str], tag: str, rail: float) -> None:
    lin = f"{tag}lin"
    y = f"{tag}y"
    lines.append(
        f"B{tag} {tag}amp 0 V = max(-{rail:.15g}, min({rail:.15g}, "
        f"{OPAMP_GAIN:.15g} * v({lin}, {y})))"
    )
    lines.append(f"D{tag} {tag}amp {y} Dsi")
    lines.append(f"RL{tag} {y} 0 {RLOAD:.15g}")
    lines.append(f"E{tag} {tag}buf 0 {y} 0 1")


def _emit_unity_iv(lines: list[str], tag: str, g_weight: float) -> None:
    diff = f"{tag}d"
    lines.append(f"V{tag}p {tag}p 0 DC 0")
    lines.append(f"V{tag}n {tag}n 0 DC 0")
    lines.append(f"F{tag}p 0 {diff} V{tag}p 1")
    lines.append(f"F{tag}n {diff} 0 V{tag}n 1")
    lines.append(f"V{tag}d {diff} 0 DC 0")
    lines.append(f"H{tag} {tag}lin 0 V{tag}d {1.0 / g_weight:.15g}")


def _emit_divider(
    lines: list[str],
    catalog: list[dict],
    src: str,
    tap: str,
    buffered: str,
    stem: str,
    ra: float,
    rb: float,
) -> None:
    ra_name = f"R{stem}a"
    rb_name = f"R{stem}b"
    lines.append(f"{ra_name} {src} {tap} {ra:.15g}")
    lines.append(f"{rb_name} {tap} 0 {rb:.15g}")
    lines.append(f"E{stem} {buffered} 0 {tap} 0 1")
    for name, res, which in ((ra_name, ra, "a"), (rb_name, rb, "b")):
        catalog.append(
            {
                "name": name,
                "comment": f"passive divider {stem}{which}",
                "role": "divider",
                "R": res,
                "G": 1.0 / res,
                "bank": "divider",
            }
        )


def _emit_weight_resistors(
    lines: list[str],
    catalog: list[dict],
    tag: str,
    wrow: np.ndarray,
    bias: float,
    g_w: float,
    layer: int,
    banks: tuple[tuple[str, float], ...],
    src_fn,
) -> str | None:
    encoded, reason = encode_parameters(wrow, bias, g_w, banks, R_MIN, R_MAX)
    if reason is not None or encoded is None:
        return reason or "encode failed"
    for item in encoded:
        dest = f"{tag}{item['sign']}"
        src = src_fn(item)
        if item["kind"] == "bias":
            name = f"R{tag}b{item['sign']}{item['bank']}{item['branch']}"
            comment = (
                f"{tag} bias={bias:+.15g} b{'+' if item['sign'] == 'p' else '-'}"
            )
        else:
            idx = int(item["source_index"])
            name = f"R{tag}{item['sign']}{idx}{item['bank']}{item['branch']}"
            comment = (
                f"{tag} input {idx} w={float(wrow[idx - 1]):+.15g} "
                f"w{'+' if item['sign'] == 'p' else '-'}"
            )
        _emit_resistor(lines, catalog, name, src, dest, item, comment, g_w, layer)
    return None


def _control(n_out: int) -> list[str]:
    lines = [".control", "set numdgt=15", "op"]
    for k in range(1, n_out + 1):
        lines.append(f"print v(o{k}lin)")
    lines.extend([".endc", ".end", ""])
    return lines


def _count_devices(netlist: str) -> dict:
    counts: dict[str, int] = {}
    for raw in netlist.splitlines():
        line = raw.strip()
        if not line or line.startswith("*") or line.startswith("."):
            continue
        kind = line[0].upper()
        if kind in "RVFHBDEC":
            counts[kind] = counts.get(kind, 0) + 1
    return {
        "passive_resistors": counts.get("R", 0),
        "passive_diodes": counts.get("D", 0),
        "passive_caps": counts.get("C", 0),
        "active_cccs": counts.get("F", 0),
        "active_vcvs": counts.get("E", 0),
        "active_behavioral": counts.get("B", 0),
        "active_transimpedance": counts.get("H", 0),
        "active_functional_blocks": (
            counts.get("F", 0)
            + counts.get("E", 0)
            + counts.get("B", 0)
            + counts.get("H", 0)
        ),
        "active_note": (
            "Active counts are behavioral controlled sources, not transistors."
        ),
    }


def accounting(netlist: str, catalog: list[dict], n_weights: int) -> dict:
    devices = _count_devices(netlist)
    stats = encoding_stats(catalog, n_weights) if catalog else {}
    g_total = total_conductance(catalog) if catalog else 0.0
    n_div = sum(1 for c in catalog if c.get("role") == "divider")
    return {
        **stats,
        **devices,
        "n_divider_resistors": n_div,
        "bank_geff_fraction": bank_mass(catalog),
        "total_conductance_S": g_total,
        "i_rel_A": g_total * V_REP,
        "energy_note": (
            "I_rel = SigmaG * 1 V is a relative signal-path metric. "
            "It is not board power. Behavioral sources have no Iq."
        ),
    }


def generate_arch_a(
    spec: dict,
    weights: dict[str, np.ndarray],
    scale_error: float = 0.0,
    i_leak: float = 0.0,
    rail: float = 15.0,
    linear: bool = False,
    relu_style: str = "direct",
) -> tuple[str | None, list[dict], str | None]:
    """Experiment 11 banks. Scale error multiplies every CCCS alpha."""
    cfg = ARCH_A_CFG[spec["id"]]
    catalog: list[dict] = []
    n_in, n_hidden, n_out = spec["n_in"], spec["n_hidden"], spec["n_out"]
    use_precision = (not linear) and relu_style == "precision"
    lines = _header(
        "A",
        spec,
        f"* scale_error={scale_error:g} Ileak={i_leak:g} rail={rail:g} "
        f"linear={linear} relu={relu_style if not linear else 'none'}",
    )
    for i in range(1, n_in + 1):
        lines.append(f"Vin{i} in{i} 0 DC 0")
    lines.append("Vref vref 0 DC 1")
    lines.append("")
    input_nodes = [f"in{i}" for i in range(1, n_in + 1)]
    err = 1.0 + scale_error

    def emit_neuron(tag, nodes, wrow, bias, apply_hidden, g_w, layer) -> str | None:
        encoded, reason = encode_parameters(
            wrow, bias, g_w, cfg.banks, cfg.r_min, cfg.r_max
        )
        if reason is not None or encoded is None:
            return reason or "encode failed"
        used: set[tuple[str, str, float]] = set()
        for item in encoded:
            dest = f"{tag}{item['sign']}{item['bank']}"
            used.add((item["sign"], item["bank"], float(item["alpha"])))
            if item["kind"] == "weight":
                src = nodes[int(item["source_index"]) - 1]
                name = (
                    f"R{tag}{item['sign']}{item['source_index']}"
                    f"{item['bank']}{item['branch']}"
                )
                comment = (
                    f"{tag} input {item['source_index']} "
                    f"w={float(wrow[item['source_index'] - 1]):+.15g} "
                    f"w{'+' if item['sign'] == 'p' else '-'}"
                )
            else:
                src = "vref"
                name = f"R{tag}b{item['sign']}{item['bank']}{item['branch']}"
                comment = (
                    f"{tag} bias={bias:+.15g} "
                    f"b{'+' if item['sign'] == 'p' else '-'}"
                )
            _emit_resistor(lines, catalog, name, src, dest, item, comment, g_w, layer)
        diff = f"{tag}d"
        for sign, bank, alpha in sorted(used):
            node = f"{tag}{sign}{bank}"
            vs = f"V{tag}{sign}{bank}"
            lines.append(f"{vs} {node} 0 DC 0")
            gain = alpha * err
            if sign == "p":
                lines.append(f"F{tag}{sign}{bank} 0 {diff} {vs} {gain:.15g}")
            else:
                lines.append(f"F{tag}{sign}{bank} {diff} 0 {vs} {gain:.15g}")
        if i_leak:
            lines.append(f"B{tag}leak 0 {diff} I = {i_leak:.15g}")
        lines.append(f"V{tag}d {diff} 0 DC 0")
        lines.append(f"H{tag} {tag}lin 0 V{tag}d {1.0 / g_w:.15g}")
        if apply_hidden:
            if use_precision:
                _emit_precision_relu(lines, tag, rail)
            else:
                _emit_direct_relu(lines, tag, rail, linear)
        lines.append("")
        return None

    for j in range(n_hidden):
        reason = emit_neuron(
            f"h{j + 1}",
            input_nodes,
            weights["W1"][j],
            float(weights["b1"][j]),
            True,
            cfg.g_weight_1,
            1,
        )
        if reason:
            return None, catalog, f"hidden {j + 1}: {reason}"
    hidden = [f"h{j + 1}buf" for j in range(n_hidden)]
    for k in range(n_out):
        reason = emit_neuron(
            f"o{k + 1}",
            hidden,
            weights["W2"][k],
            float(weights["b2"][k]),
            False,
            cfg.g_weight_2,
            2,
        )
        if reason:
            return None, catalog, f"output {k + 1}: {reason}"
    if use_precision:
        lines.append(".model Dsi D(Is=1e-14 N=1 Rs=1)")
        lines.append("")
    lines.extend(_control(n_out))
    return "\n".join(lines), catalog, None


def generate_arch_b(
    spec: dict,
    weights: dict[str, np.ndarray],
    scale_error: float = 0.0,
    v_offset: float = 0.0,
    rail: float = 15.0,
    linear: bool = False,
) -> tuple[str | None, list[dict], str | None]:
    """Voltage-domain ranges. Nominal resistors attach to Vin, not a CCCS."""
    cfg = ARCH_B_CFG[spec["id"]]
    catalog: list[dict] = []
    n_in, n_hidden, n_out = spec["n_in"], spec["n_hidden"], spec["n_out"]
    lines = _header(
        "B",
        spec,
        f"* scale_error={scale_error:g} Vos={v_offset:g} rail={rail:g} "
        f"linear={linear}",
    )
    err = 1.0 + scale_error
    gains = {
        name: (alpha * err if alpha != 1.0 else 1.0) for name, alpha in cfg.banks
    }
    for i in range(1, n_in + 1):
        lines.append(f"Vin{i} in{i} 0 DC 0")
        if "f" in gains:
            _emit_range_copy(lines, f"fin{i}", f"inf{i}", f"in{i}", gains["f"], v_offset)
        if "m" in gains:
            _emit_range_copy(lines, f"med{i}", f"inm{i}", f"in{i}", gains["m"], v_offset)
    lines.append("Vref vref 0 DC 1")
    if "f" in gains:
        _emit_range_copy(lines, "reff", "vreff", "vref", gains["f"], v_offset)
    if "m" in gains:
        _emit_range_copy(lines, "refm", "vrefm", "vref", gains["m"], v_offset)
    lines.append("")

    def src_in(item: dict) -> str:
        bank = item["bank"]
        if item["kind"] == "bias":
            return {"n": "vref", "f": "vreff", "m": "vrefm"}[bank]
        idx = int(item["source_index"])
        return {"n": f"in{idx}", "f": f"inf{idx}", "m": f"inm{idx}"}[bank]

    for j in range(n_hidden):
        tag = f"h{j + 1}"
        reason = _emit_weight_resistors(
            lines, catalog, tag, weights["W1"][j], float(weights["b1"][j]),
            cfg.g_weight_1, 1, cfg.banks, src_in,
        )
        if reason:
            return None, catalog, f"hidden {j + 1}: {reason}"
        _emit_unity_iv(lines, tag, cfg.g_weight_1)
        _emit_direct_relu(lines, tag, rail, linear)
        lines.append("")

    for j in range(1, n_hidden + 1):
        src = f"h{j}buf"
        if "f" in gains:
            _emit_range_copy(lines, f"hfin{j}", f"h{j}f", src, gains["f"], v_offset)
        if "m" in gains:
            _emit_range_copy(lines, f"hmed{j}", f"h{j}m", src, gains["m"], v_offset)

    def src_h(item: dict) -> str:
        bank = item["bank"]
        if item["kind"] == "bias":
            return {"n": "vref", "f": "vreff", "m": "vrefm"}[bank]
        idx = int(item["source_index"])
        return {"n": f"h{idx}buf", "f": f"h{idx}f", "m": f"h{idx}m"}[bank]

    for k in range(n_out):
        tag = f"o{k + 1}"
        reason = _emit_weight_resistors(
            lines, catalog, tag, weights["W2"][k], float(weights["b2"][k]),
            cfg.g_weight_2, 2, cfg.banks, src_h,
        )
        if reason:
            return None, catalog, f"output {k + 1}: {reason}"
        _emit_unity_iv(lines, tag, cfg.g_weight_2)
        lines.append("")

    lines.extend(_control(n_out))
    return "\n".join(lines), catalog, None


def generate_arch_c(
    spec: dict,
    weights: dict[str, np.ndarray],
    scale_error: float = 0.0,
    i_leak: float = 0.0,
    rail: float = 15.0,
    linear: bool = False,
) -> tuple[str | None, list[dict], str | None]:
    """Passive dividers. Scale error perturbs divider Rb (beta)."""
    cfg = ARCH_C_CFG[spec["id"]]
    catalog: list[dict] = []
    n_in, n_hidden, n_out = spec["n_in"], spec["n_hidden"], spec["n_out"]
    rb = DIVIDER_RB * (1.0 + scale_error)
    ra = DIVIDER_RA
    beta = rb / (ra + rb)
    lines = _header(
        "C",
        spec,
        f"* divider Ra={ra:g} Rb={rb:g} beta={beta:.8g} "
        f"Ileak={i_leak:g} rail={rail:g} linear={linear}",
    )
    for i in range(1, n_in + 1):
        lines.append(f"Vin{i} in{i} 0 DC 0")
        _emit_divider(
            lines, catalog, f"in{i}", f"tap{i}", f"inf{i}", f"div{i}", ra, rb
        )
    lines.append("Vref vref 0 DC 1")
    _emit_divider(lines, catalog, "vref", "tapref", "vreff", "divref", ra, rb)
    lines.append("")

    def src_in(item: dict) -> str:
        bank = item["bank"]
        if item["kind"] == "bias":
            return {"n": "vref", "f": "vreff"}[bank]
        idx = int(item["source_index"])
        return {"n": f"in{idx}", "f": f"inf{idx}"}[bank]

    for j in range(n_hidden):
        tag = f"h{j + 1}"
        reason = _emit_weight_resistors(
            lines, catalog, tag, weights["W1"][j], float(weights["b1"][j]),
            cfg.g_weight_1, 1, cfg.banks, src_in,
        )
        if reason:
            return None, catalog, f"hidden {j + 1}: {reason}"
        _emit_unity_iv(lines, tag, cfg.g_weight_1)
        if i_leak:
            lines.append(f"B{tag}leak 0 {tag}d I = {i_leak:.15g}")
        _emit_direct_relu(lines, tag, rail, linear)
        lines.append("")

    for j in range(1, n_hidden + 1):
        _emit_divider(
            lines, catalog, f"h{j}buf", f"htap{j}", f"h{j}f", f"divh{j}", ra, rb
        )

    def src_h(item: dict) -> str:
        bank = item["bank"]
        if item["kind"] == "bias":
            return {"n": "vref", "f": "vreff"}[bank]
        idx = int(item["source_index"])
        return {"n": f"h{idx}buf", "f": f"h{idx}f"}[bank]

    for k in range(n_out):
        tag = f"o{k + 1}"
        reason = _emit_weight_resistors(
            lines, catalog, tag, weights["W2"][k], float(weights["b2"][k]),
            cfg.g_weight_2, 2, cfg.banks, src_h,
        )
        if reason:
            return None, catalog, f"output {k + 1}: {reason}"
        _emit_unity_iv(lines, tag, cfg.g_weight_2)
        if i_leak:
            lines.append(f"B{tag}leak 0 {tag}d I = {i_leak:.15g}")
        lines.append("")

    lines.extend(_control(n_out))
    return "\n".join(lines), catalog, None


def compile_architecture(
    arch: str,
    spec: dict,
    weights: dict[str, np.ndarray],
    scale_error: float = 0.0,
    i_leak: float = 0.0,
    v_offset: float = 0.0,
    rail: float = 15.0,
    linear: bool = False,
    relu_style: str = "direct",
) -> tuple[str | None, list[dict], str | None]:
    if arch == "A":
        netlist, catalog, reason = generate_arch_a(
            spec, weights,
            scale_error=scale_error, i_leak=i_leak, rail=rail,
            linear=linear, relu_style=relu_style,
        )
    elif arch == "B":
        netlist, catalog, reason = generate_arch_b(
            spec, weights,
            scale_error=scale_error, v_offset=v_offset, rail=rail,
            linear=linear,
        )
    elif arch == "C":
        netlist, catalog, reason = generate_arch_c(
            spec, weights,
            scale_error=scale_error, i_leak=i_leak, rail=rail,
            linear=linear,
        )
    else:
        raise KeyError(arch)
    if reason or netlist is None:
        return None, catalog, reason
    violation = range_violation(catalog, R_MIN, R_MAX)
    if violation is not None:
        return None, catalog, violation
    return netlist, catalog, None
