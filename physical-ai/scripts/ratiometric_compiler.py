"""Experiment 14: ratiometric weight fabric and variation models.

Architecture C (baseline): Experiment 13 passive dividers + ideal H-source
    I-to-V. Effective scale is 1/G_WEIGHT, which is not a resistor, so a
    global resistor shift does not cancel.

Architecture D: same divider / weight encoding, but I-to-V is a physical
    resistor R_IV = 1/G_WEIGHT. Then

        V_lin = I_sum * R_IV = Vin * (R_IV / R_w) * bank_gain

    so the mathematical weight is a resistor ratio realized in SPICE.
    A common multiplicative shift on R_w and R_IV cancels.

Architecture E: Architecture C plus one-time compiled VCVS scale factors
    from dedicated SPICE calibration cells (not from inference outputs).
    Allowed constants: none, one global, or one per layer. Never one
    per weight.

This is a behavioral variation study, not a silicon mismatch model and
not a claim about 5% commercial through-hole resistors on a PCB.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from compile_xor import PROJECT_ROOT
from dynamic_range_compiler import encoding_stats, range_violation
from hardware_constrained_compiler import V_REP
from matter_compiler import total_conductance
from precision_architectures import (
    ARCH_C_CFG,
    DIVIDER_RA,
    DIVIDER_RB,
    R_MAX,
    R_MIN,
    _count_devices,
    _emit_direct_relu,
    _emit_divider,
    _emit_weight_resistors,
    bank_mass,
    generate_arch_b,
    generate_arch_c,
)


CIRCUIT_DIR = PROJECT_ROOT / "circuits" / "ratiometric"
MIN_SCALE = 0.1


@dataclass(frozen=True)
class VariationSpec:
    """One named random-variable model. Every draw is documented."""

    name: str
    kind: str
    percent: float
    local_percent: float = 0.0
    fixed_delta: float | None = None

    def label(self) -> str:
        if self.fixed_delta is not None:
            return f"{self.kind} fixed {self.fixed_delta:+.4g}"
        if self.kind == "independent":
            return f"independent +/-{self.percent:g}%"
        if self.kind == "global":
            return f"global U(+/-{self.percent:g}%)"
        if self.kind == "layer":
            return (
                f"layer U(+/-{self.percent:g}%) + local "
                f"U(+/-{self.local_percent:g}%)"
            )
        if self.kind == "matched":
            return (
                f"matched global/pair U(+/-{self.percent:g}%) + mismatch "
                f"U(+/-{self.local_percent:g}%)"
            )
        return self.kind


def annotate_catalog(catalog: list[dict]) -> list[dict]:
    """Add layer / match_group so variation models have explicit groups."""
    for item in catalog:
        name = str(item["name"])
        role = str(item.get("role", ""))
        layer = item.get("layer")
        if layer is None:
            if name.startswith("Rdivh") or name.startswith("Rdivh"):
                layer = 2
            elif "divh" in name:
                layer = 2
            else:
                layer = 1
            item["layer"] = int(layer)
        else:
            item["layer"] = int(layer)
        if role == "divider":
            stem = name[:-1] if name[-1] in "abAB" else name
            item["match_group"] = f"div_{stem}"
        elif role == "reference":
            item["match_group"] = f"fab_L{item['layer']}"
        else:
            item.setdefault("match_group", f"fab_L{item['layer']}")
    return catalog


def _stamp(catalog: list[dict], start: int, layer: int, match_group: str) -> None:
    for item in catalog[start:]:
        item["layer"] = layer
        item["match_group"] = match_group


def _emit_tagged_divider(
    lines, catalog, src, tap, buffered, stem, ra, rb, layer, match_group
) -> None:
    start = len(catalog)
    _emit_divider(lines, catalog, src, tap, buffered, stem, ra, rb)
    _stamp(catalog, start, layer, match_group)


def _emit_physical_iv(
    lines: list[str],
    catalog: list[dict],
    tag: str,
    g_weight: float,
    layer: int,
    i_leak: float,
    k_scale: float,
) -> None:
    r_iv = 1.0 / g_weight
    diff = f"{tag}d"
    raw = f"{tag}raw"
    lines.append(f"V{tag}p {tag}p 0 DC 0")
    lines.append(f"V{tag}n {tag}n 0 DC 0")
    lines.append(f"F{tag}p 0 {diff} V{tag}p 1")
    lines.append(f"F{tag}n {diff} 0 V{tag}n 1")
    lines.append(
        f"* ratiometric I-to-V: V = I * R_IV,  R_IV={r_iv:.15g} "
        f"(weight ~ R_IV / R_w)"
    )
    lines.append(f"R{tag}iv {diff} 0 {r_iv:.15g}")
    catalog.append(
        {
            "name": f"R{tag}iv",
            "comment": f"{tag} physical I-to-V reference",
            "role": "reference",
            "layer": layer,
            "match_group": f"fab_L{layer}",
            "R": r_iv,
            "G": g_weight,
            "bank": "ref",
        }
    )
    if i_leak:
        lines.append(f"B{tag}leak 0 {diff} I = {i_leak:.15g}")
    lines.append(f"E{tag}sc {raw} 0 {diff} 0 {k_scale:.15g}")
    lines.append(f"E{tag}lin {tag}lin 0 {raw} 0 1")


def _emit_ideal_iv(
    lines: list[str],
    tag: str,
    g_weight: float,
    i_leak: float,
    k_scale: float,
) -> None:
    r_iv = 1.0 / g_weight
    diff = f"{tag}d"
    raw = f"{tag}raw"
    lines.append(f"V{tag}p {tag}p 0 DC 0")
    lines.append(f"V{tag}n {tag}n 0 DC 0")
    lines.append(f"F{tag}p 0 {diff} V{tag}p 1")
    lines.append(f"F{tag}n {diff} 0 V{tag}n 1")
    lines.append(f"V{tag}d {diff} 0 DC 0")
    lines.append(f"H{tag} {raw} 0 V{tag}d {r_iv:.15g}")
    if i_leak:
        lines.append(f"B{tag}leak 0 {diff} I = {i_leak:.15g}")
    lines.append(f"E{tag}sc {tag}lin 0 {raw} 0 {k_scale:.15g}")


def _emit_cal_cell(
    lines: list[str],
    catalog: list[dict],
    layer: int,
    g_weight: float,
    physical_iv: bool,
) -> None:
    """Dedicated 1 V / R_IV / R_IV cell. Expected v(cal{L}lin) = 1.

    Shares the layer match group so it sees the same process as that
    layer's weight / reference fabric. Not used as a neural input.
    """
    r_iv = 1.0 / g_weight
    tag = f"cal{layer}"
    lines.append(f"* calibration cell layer {layer}: expected v({tag}lin)=1")
    lines.append(f"V{tag} {tag}in 0 DC 0")
    lines.append(f"R{tag}w {tag}in {tag}p {r_iv:.15g}")
    lines.append(f"V{tag}p {tag}p 0 DC 0")
    catalog.append(
        {
            "name": f"R{tag}w",
            "comment": f"layer {layer} calibration sense resistor",
            "role": "reference",
            "layer": layer,
            "match_group": f"fab_L{layer}",
            "R": r_iv,
            "G": g_weight,
            "bank": "cal",
        }
    )
    if physical_iv:
        lines.append(f"F{tag} 0 {tag}d V{tag}p 1")
        lines.append(f"R{tag}iv {tag}d 0 {r_iv:.15g}")
        catalog.append(
            {
                "name": f"R{tag}iv",
                "comment": f"layer {layer} calibration I-to-V",
                "role": "reference",
                "layer": layer,
                "match_group": f"fab_L{layer}",
                "R": r_iv,
                "G": g_weight,
                "bank": "cal",
            }
        )
        lines.append(f"E{tag} {tag}lin 0 {tag}d 0 1")
    else:
        lines.append(f"F{tag} 0 {tag}d V{tag}p 1")
        lines.append(f"V{tag}d {tag}d 0 DC 0")
        lines.append(f"H{tag} {tag}lin 0 V{tag}d {r_iv:.15g}")


def _control(n_out: int) -> list[str]:
    lines = [".control", "set numdgt=15", "op"]
    for k in range(1, n_out + 1):
        lines.append(f"print v(o{k}lin)")
    lines.extend([".endc", ".end", ""])
    return lines


def _header(arch: str, spec: dict, extra: str) -> list[str]:
    titles = {
        "C": "Experiment 13 Architecture C baseline (ideal H I-to-V)",
        "D": "ratiometric fabric (physical R_IV, weight ~ R_IV/R_w)",
        "E": "layer-calibration VCVS on Architecture C I-to-V",
        "B": "Experiment 13 Architecture B (voltage-domain, ideal H)",
    }
    return [
        f"* Physical AI - Experiment 14 architecture {arch}: {titles[arch]}",
        "* Frozen Experiment 9 weights. No Python output correction.",
        "* Behavioral variation study. Not transistor-level or PCB power.",
        extra,
        f"* shape: {spec['n_in']} -> {spec['n_hidden']} -> {spec['n_out']}",
        "",
    ]


def generate_fabric(
    spec: dict,
    weights: dict[str, np.ndarray],
    arch: str,
    scale_error: float = 0.0,
    i_leak: float = 0.0,
    rail: float = 15.0,
    linear: bool = False,
    k_layer1: float = 1.0,
    k_layer2: float = 1.0,
) -> tuple[str | None, list[dict], str | None]:
    """C / D / E from one encoder. arch in {C, D, E}."""
    if arch not in {"C", "D", "E"}:
        raise KeyError(arch)
    physical = arch == "D"
    include_cal = arch == "E"
    # E keeps the ideal H so a global R shift is visible and calibratable.
    cfg = ARCH_C_CFG[spec["id"]]
    catalog: list[dict] = []
    n_in, n_hidden, n_out = spec["n_in"], spec["n_hidden"], spec["n_out"]
    rb = DIVIDER_RB * (1.0 + scale_error)
    ra = DIVIDER_RA
    beta = rb / (ra + rb)
    lines = _header(
        arch,
        spec,
        f"* divider Ra={ra:g} Rb={rb:g} beta={beta:.8g} "
        f"Ileak={i_leak:g} rail={rail:g} linear={linear} "
        f"k1={k_layer1:.8g} k2={k_layer2:.8g} physical_iv={physical}",
    )
    for i in range(1, n_in + 1):
        lines.append(f"Vin{i} in{i} 0 DC 0")
        _emit_tagged_divider(
            lines, catalog, f"in{i}", f"tap{i}", f"inf{i}", f"div{i}",
            ra, rb, 1, f"div_div{i}",
        )
    lines.append("Vref vref 0 DC 1")
    _emit_tagged_divider(
        lines, catalog, "vref", "tapref", "vreff", "divref",
        ra, rb, 1, "div_divref",
    )
    lines.append("")

    def src_in(item: dict) -> str:
        bank = item["bank"]
        if item["kind"] == "bias":
            return {"n": "vref", "f": "vreff"}[bank]
        idx = int(item["source_index"])
        return {"n": f"in{idx}", "f": f"inf{idx}"}[bank]

    def emit_iv(tag, g_w, layer, k):
        if physical:
            _emit_physical_iv(lines, catalog, tag, g_w, layer, i_leak, k)
        else:
            _emit_ideal_iv(lines, tag, g_w, i_leak, k)

    for j in range(n_hidden):
        tag = f"h{j + 1}"
        start = len(catalog)
        reason = _emit_weight_resistors(
            lines, catalog, tag, weights["W1"][j], float(weights["b1"][j]),
            cfg.g_weight_1, 1, cfg.banks, src_in,
        )
        if reason:
            return None, catalog, f"hidden {j + 1}: {reason}"
        _stamp(catalog, start, 1, "fab_L1")
        emit_iv(tag, cfg.g_weight_1, 1, k_layer1)
        _emit_direct_relu(lines, tag, rail, linear)
        lines.append("")

    for j in range(1, n_hidden + 1):
        _emit_tagged_divider(
            lines, catalog, f"h{j}buf", f"htap{j}", f"h{j}f", f"divh{j}",
            ra, rb, 2, f"div_divh{j}",
        )

    def src_h(item: dict) -> str:
        bank = item["bank"]
        if item["kind"] == "bias":
            return {"n": "vref", "f": "vreff"}[bank]
        idx = int(item["source_index"])
        return {"n": f"h{idx}buf", "f": f"h{idx}f"}[bank]

    for k in range(n_out):
        tag = f"o{k + 1}"
        start = len(catalog)
        reason = _emit_weight_resistors(
            lines, catalog, tag, weights["W2"][k], float(weights["b2"][k]),
            cfg.g_weight_2, 2, cfg.banks, src_h,
        )
        if reason:
            return None, catalog, f"output {k + 1}: {reason}"
        _stamp(catalog, start, 2, "fab_L2")
        emit_iv(tag, cfg.g_weight_2, 2, k_layer2)
        lines.append("")

    if include_cal:
        _emit_cal_cell(lines, catalog, 1, cfg.g_weight_1, physical)
        _emit_cal_cell(lines, catalog, 2, cfg.g_weight_2, physical)
        lines.append("")

    lines.extend(_control(n_out))
    return "\n".join(lines), catalog, None


def compile_ratiometric(
    arch: str,
    spec: dict,
    weights: dict[str, np.ndarray],
    scale_error: float = 0.0,
    i_leak: float = 0.0,
    rail: float = 15.0,
    linear: bool = False,
    k_layer1: float = 1.0,
    k_layer2: float = 1.0,
) -> tuple[str | None, list[dict], str | None]:
    if arch == "B":
        netlist, catalog, reason = generate_arch_b(
            spec, weights, scale_error=scale_error, rail=rail, linear=linear
        )
    elif arch == "C":
        # Exact Experiment 13 C topology (ideal H, no extra scale E).
        netlist, catalog, reason = generate_arch_c(
            spec, weights,
            scale_error=scale_error, i_leak=i_leak, rail=rail, linear=linear,
        )
    elif arch in {"D", "E"}:
        netlist, catalog, reason = generate_fabric(
            spec, weights, arch,
            scale_error=scale_error, i_leak=i_leak, rail=rail, linear=linear,
            k_layer1=k_layer1, k_layer2=k_layer2,
        )
    else:
        raise KeyError(arch)
    if reason or netlist is None:
        return None, catalog, reason
    annotate_catalog(catalog)
    violation = range_violation(catalog, R_MIN, R_MAX)
    if violation is not None:
        return None, catalog, violation
    return netlist, catalog, None


def sample_variation(
    catalog: list[dict],
    spec: VariationSpec,
    rng: np.random.Generator,
) -> dict[str, float]:
    """Apply one variation model. Returns {Rname: R_actual}.

    Random variables (all Uniform, deterministic rng):

    independent:
        u_i ~ U(-p, p) per resistor.  R = Rnom * (1 + u_i)

    global (random):
        d_g ~ U(-p, p) once.  R = Rnom * (1 + d_g)

    global (fixed_delta):
        R = Rnom * (1 + fixed_delta)   [cancellation / deterministic shift]

    layer:
        d_L ~ U(-p, p) per layer
        e_i ~ U(-p_local, p_local) per resistor
        R = Rnom * (1 + d_L + e_i)

    matched:
        d_g ~ U(-p, p)
        d_m[g] ~ U(-p, p) per match_group
        e_i ~ U(-p_local, p_local)
        R = Rnom * (1 + d_g + d_m[g] + e_i)

        Architecture D puts each layer's weights and R_IV in the same
        match_group, so d_g and d_m cancel in R_IV/R_w. Divider Ra/Rb
        share a pair group, so beta is stable except for e_i.
    """
    p = spec.percent / 100.0
    p_loc = spec.local_percent / 100.0
    values: dict[str, float] = {}

    if spec.kind == "independent":
        for item in catalog:
            u = float(rng.uniform(-p, p)) if p else 0.0
            values[str(item["name"])] = float(item["R"]) * max(MIN_SCALE, 1.0 + u)
        return values

    if spec.kind == "global":
        if spec.fixed_delta is not None:
            delta = float(spec.fixed_delta)
        else:
            delta = float(rng.uniform(-p, p)) if p else 0.0
        scale = max(MIN_SCALE, 1.0 + delta)
        for item in catalog:
            values[str(item["name"])] = float(item["R"]) * scale
        return values

    if spec.kind == "layer":
        layers = {int(item.get("layer", 1)) for item in catalog}
        d_layer = {
            L: float(rng.uniform(-p, p)) if p else 0.0 for L in layers
        }
        for item in catalog:
            local = float(rng.uniform(-p_loc, p_loc)) if p_loc else 0.0
            delta = d_layer[int(item.get("layer", 1))] + local
            values[str(item["name"])] = float(item["R"]) * max(MIN_SCALE, 1.0 + delta)
        return values

    if spec.kind == "matched":
        d_g = float(rng.uniform(-p, p)) if p else 0.0
        groups = {str(item.get("match_group", "ungrouped")) for item in catalog}
        d_m = {g: float(rng.uniform(-p, p)) if p else 0.0 for g in groups}
        for item in catalog:
            local = float(rng.uniform(-p_loc, p_loc)) if p_loc else 0.0
            delta = d_g + d_m[str(item.get("match_group", "ungrouped"))] + local
            values[str(item["name"])] = float(item["R"]) * max(MIN_SCALE, 1.0 + delta)
        return values

    raise KeyError(spec.kind)


def accounting(netlist: str, catalog: list[dict], n_weights: int) -> dict:
    devices = _count_devices(netlist)
    stats = encoding_stats(catalog, n_weights) if catalog else {}
    g_total = total_conductance(catalog) if catalog else 0.0
    n_ref = sum(1 for c in catalog if c.get("role") == "reference")
    n_div = sum(1 for c in catalog if c.get("role") == "divider")
    groups = {str(c.get("match_group", "")) for c in catalog}
    n_pairs = sum(1 for g in groups if g.startswith("div_"))
    n_fab = sum(1 for g in groups if g.startswith("fab_"))
    return {
        **stats,
        **devices,
        "n_divider_resistors": n_div,
        "n_reference_resistors": n_ref,
        "n_matched_divider_pairs": n_pairs,
        "n_matched_fabric_groups": n_fab,
        "n_calibration_cells": sum(1 for c in catalog if c.get("bank") == "cal") // 2,
        "bank_geff_fraction": bank_mass(catalog),
        "total_conductance_S": g_total,
        "i_rel_A": g_total * V_REP,
        "energy_note": (
            "I_rel = SigmaG * 1 V is a relative signal-path metric. "
            "Not board power. Behavioral sources have no Iq."
        ),
    }


def fabric_public(arch: str) -> dict:
    return {
        "C": {
            "title": "Experiment 13 Architecture C (ideal H I-to-V)",
            "ratio_in_spice": (
                "Divider beta = Rb/(Ra+Rb) is a ratio. Weight scale "
                "uses an ideal H-source and does not cancel with R_w."
            ),
        },
        "D": {
            "title": "ratiometric fabric, physical R_IV",
            "ratio_in_spice": (
                "V_lin = I * R_IV with R_IV a catalog resistor. "
                "weight_effective ~ R_IV / R_w (times bank voltage gain)."
            ),
        },
        "E": {
            "title": "Architecture C + compiled layer VCVS calibration",
            "ratio_in_spice": (
                "Calibration constants come from dedicated SPICE cells "
                "and are compiled as VCVS gains. Not per-output software."
            ),
        },
        "B": {
            "title": "Experiment 13 Architecture B (voltage-domain, ideal H)",
            "ratio_in_spice": "Ideal H I-to-V; range copies are VCVS gains.",
        },
    }[arch]
