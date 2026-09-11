"""Matter Compiler dynamic-range encoding (Experiment 11).

A mathematical weight is not forced onto one resistor at one layer scale.

    G_required = G_WEIGHT * |w|
    G_required = sum_i (alpha_i / R_i)

Each physical resistor stays in [R_MIN, R_MAX]. Branch currents are copied
onto the neuron difference node by CCCS gains (conductance banks) and
summed by KCL in SPICE.

    I_injected = alpha * (V / R) = V * G_required
    V_lin = I_total / G_WEIGHT = x*w + b

Parallel branches on one bank handle large G_required.
A finer bank (smaller alpha) handles small G_required.
Parallel branches alone cannot represent a conductance below 1/R_MAX.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from compile_xor import (
    OPAMP_GAIN,
    OPAMP_RAIL,
    PROJECT_ROOT,
    RLOAD,
    split_weight,
)
from hardware_constrained_compiler import V_REP, load_frozen_model, nonzero_abs
from matter_compiler import total_conductance


CIRCUIT_DIR = PROJECT_ROOT / "circuits" / "dynamic_range"
R_MIN = 1.0e3
R_MAX = 1.0e6
MAX_PARALLEL = 8
G_WEIGHT_GRID = (1e-6, 3e-6, 1e-5, 3e-5, 1e-4)
BANK_SETS = (
    (("n", 1.0),),
    (("f", 1e-3), ("n", 1.0)),
    (("f", 1e-4), ("m", 1e-2), ("n", 1.0)),
)


@dataclass(frozen=True)
class RangeConfig:
    g_weight_1: float
    g_weight_2: float
    banks: tuple[tuple[str, float], ...]
    r_min: float = R_MIN
    r_max: float = R_MAX

    def label(self) -> str:
        bank_s = "+".join(f"{n}:{a:g}" for n, a in self.banks)
        return f"Gw1={self.g_weight_1:.3g} Gw2={self.g_weight_2:.3g} banks={bank_s}"

    def key(self) -> tuple:
        return (self.g_weight_1, self.g_weight_2, self.banks, self.r_min, self.r_max)


def decompose_required_g(
    g_req: float,
    banks: tuple[tuple[str, float], ...],
    r_min: float = R_MIN,
    r_max: float = R_MAX,
    max_parallel: int = MAX_PARALLEL,
) -> tuple[list[dict] | None, str | None]:
    """Split G_required into in-range resistors and bank gains.

    Returns (branches, None) or (None, reason). Never clips R into range.
    """
    if g_req <= 0.0:
        return [], None

    # Prefer larger alpha: smaller physical conductance for the same G_req.
    for name, alpha in sorted(banks, key=lambda item: -item[1]):
        resistance = alpha / g_req
        if r_min <= resistance <= r_max:
            return (
                [{"bank": name, "alpha": float(alpha), "R": float(resistance)}],
                None,
            )

    too_small = all((alpha / g_req) > r_max for _name, alpha in banks)
    if too_small:
        return None, (
            f"G_req={g_req:.6g} is below every bank: even smallest alpha "
            f"needs R > R_MAX={r_max:g}"
        )

    name, alpha = max(banks, key=lambda item: item[1])
    g_phys = g_req / alpha
    g_max = 1.0 / r_min
    g_min = 1.0 / r_max
    n = int(math.ceil(g_phys / g_max - 1e-15))
    n = max(n, 1)
    if n > max_parallel:
        return None, (
            f"G_req={g_req:.6g} needs {n} parallel branches "
            f"(cap {max_parallel}) on bank {name}"
        )
    g_each = g_phys / n
    if g_each < g_min:
        return None, (
            f"parallel split on bank {name} produced G={g_each:.6g} < 1/R_MAX"
        )
    resistance = 1.0 / g_each
    if resistance < r_min or resistance > r_max:
        return None, (
            f"parallel R={resistance:.6g} outside [{r_min:g}, {r_max:g}]"
        )
    return (
        [{"bank": name, "alpha": float(alpha), "R": float(resistance)}] * n,
        None,
    )


def encode_parameters(
    weights: np.ndarray,
    bias: float,
    g_weight: float,
    banks: tuple[tuple[str, float], ...],
    r_min: float,
    r_max: float,
) -> tuple[list[dict] | None, str | None]:
    encoded: list[dict] = []
    for i, wi in enumerate(weights, start=1):
        w_plus, w_minus = split_weight(float(wi))
        for sign, mag in (("p", w_plus), ("n", w_minus)):
            if mag <= 0.0:
                continue
            branches, reason = decompose_required_g(
                g_weight * mag, banks, r_min, r_max
            )
            if reason is not None:
                return None, f"input {i} w={wi:+.6g} {sign}: {reason}"
            for k, br in enumerate(branches, start=1):
                encoded.append(
                    {
                        "kind": "weight",
                        "source_index": i,
                        "sign": sign,
                        "weight_comp": mag,
                        "branch": k,
                        **br,
                    }
                )
    b_plus, b_minus = split_weight(float(bias))
    for sign, mag in (("p", b_plus), ("n", b_minus)):
        if mag <= 0.0:
            continue
        branches, reason = decompose_required_g(
            g_weight * mag, banks, r_min, r_max
        )
        if reason is not None:
            return None, f"bias={bias:+.6g} {sign}: {reason}"
        for k, br in enumerate(branches, start=1):
            encoded.append(
                {
                    "kind": "bias",
                    "source_index": 0,
                    "sign": sign,
                    "weight_comp": mag,
                    "branch": k,
                    **br,
                }
            )
    return encoded, None


def _emit_resistor(
    lines: list[str],
    catalog: list[dict],
    name: str,
    src: str,
    dest: str,
    item: dict,
    comment: str,
    g_weight: float,
    layer: int,
) -> None:
    r = float(item["R"])
    alpha = float(item["alpha"])
    g_phys = 1.0 / r
    lines.append(
        f"* {comment}  bank={item['bank']} alpha={alpha:.15g} "
        f"R={r:.15g} G_phys={g_phys:.15g} G_eff={alpha * g_phys:.15g}"
    )
    lines.append(f"{name} {src} {dest} {r:.15g}")
    catalog.append(
        {
            "name": name,
            "comment": comment,
            "role": item["kind"],
            "layer": layer,
            "bank": item["bank"],
            "alpha": alpha,
            "R": r,
            "G": g_phys,
            "G_effective": alpha * g_phys,
            "g_scale": g_weight,
            "weight_comp": item["weight_comp"],
        }
    )


def emit_banked_neuron(
    lines: list[str],
    tag: str,
    input_nodes: list[str],
    weights: np.ndarray,
    bias: float,
    vref: str,
    apply_relu: bool,
    catalog: list[dict],
    g_weight: float,
    banks: tuple[tuple[str, float], ...],
    r_min: float,
    r_max: float,
    layer: int,
) -> str | None:
    encoded, reason = encode_parameters(
        weights, bias, g_weight, banks, r_min, r_max
    )
    if reason is not None or encoded is None:
        return reason or "encode failed"

    diff = f"{tag}d"
    lin = f"{tag}lin"
    y = f"{tag}y"
    buf = f"{tag}buf"
    lines.append(f"* --- neuron {tag} (multi-range banks) ---")
    lines.append(
        f"* I_inj = alpha * V / R,  V_lin = I_sum / G_WEIGHT, "
        f"G_WEIGHT={g_weight:.15g}"
    )

    used_banks: set[tuple[str, str, float]] = set()
    for item in encoded:
        sign = item["sign"]
        bank = item["bank"]
        alpha = float(item["alpha"])
        dest = f"{tag}{sign}{bank}"
        used_banks.add((sign, bank, alpha))
        if item["kind"] == "weight":
            src = input_nodes[int(item["source_index"]) - 1]
            name = f"R{tag}{sign}{item['source_index']}{bank}{item['branch']}"
            comment = (
                f"{tag} input {item['source_index']} "
                f"w={float(weights[item['source_index'] - 1]):+.15g} "
                f"w{'+' if sign == 'p' else '-'}"
            )
        else:
            src = vref
            name = f"R{tag}b{sign}{bank}{item['branch']}"
            comment = (
                f"{tag} bias={bias:+.15g} b{'+' if sign == 'p' else '-'}"
            )
        _emit_resistor(
            lines, catalog, name, src, dest, item, comment, g_weight, layer
        )

    for sign, bank, alpha in sorted(used_banks):
        node = f"{tag}{sign}{bank}"
        lines.append(f"V{tag}{sign}{bank} {node} 0 DC 0")
        if sign == "p":
            lines.append(f"F{tag}{sign}{bank} 0 {diff} V{tag}{sign}{bank} {alpha:.15g}")
        else:
            lines.append(f"F{tag}{sign}{bank} {diff} 0 V{tag}{sign}{bank} {alpha:.15g}")

    lines.append(f"V{tag}d {diff} 0 DC 0")
    lines.append(f"H{tag} {lin} 0 V{tag}d {1.0 / g_weight:.15g}")
    if apply_relu:
        lines.append(
            f"B{tag} {tag}amp 0 V = max(-{OPAMP_RAIL:.15g}, "
            f"min({OPAMP_RAIL:.15g}, {OPAMP_GAIN:.15g} * v({lin}, {y})))"
        )
        lines.append(f"D{tag} {tag}amp {y} Dsi")
        lines.append(f"RL{tag} {y} 0 {RLOAD:.15g}")
        lines.append(f"E{tag} {buf} 0 {y} 0 1")
    lines.append("")
    return None


def generate_banked_circuit(
    x: np.ndarray,
    w1: np.ndarray,
    b1: np.ndarray,
    w2: np.ndarray,
    b2: np.ndarray,
    config: RangeConfig,
    title: str | None = None,
) -> tuple[str | None, list[dict], str | None]:
    catalog: list[dict] = []
    n_in = int(w1.shape[1])
    n_hidden = int(w1.shape[0])
    n_out = int(w2.shape[0])
    header = title or "* Physical AI - Experiment 11: multi-range weight encoding"
    lines = [
        header,
        "* Frozen weights. Multi-range banks + optional parallel branches.",
        "* Currents sum in SPICE. Resistors are not clipped.",
        f"* {config.label()}",
        f"* R window [{config.r_min:g}, {config.r_max:g}]",
        f"* shape: {n_in} -> {n_hidden} -> {n_out}",
        "",
    ]
    x = np.atleast_1d(np.asarray(x, dtype=float))
    for i in range(1, n_in + 1):
        xi = float(x[i - 1]) if i - 1 < x.size else 0.0
        lines.append(f"Vin{i} in{i} 0 DC {xi:.15g}")
    lines.append("Vref vref 0 DC 1")
    lines.append("")

    input_nodes = [f"in{i}" for i in range(1, n_in + 1)]
    for j in range(n_hidden):
        reason = emit_banked_neuron(
            lines, f"h{j + 1}", input_nodes, w1[j], float(b1[j]),
            "vref", True, catalog, config.g_weight_1, config.banks,
            config.r_min, config.r_max, 1,
        )
        if reason:
            return None, catalog, f"hidden {j + 1}: {reason}"
    hidden_nodes = [f"h{j + 1}buf" for j in range(n_hidden)]
    for k in range(n_out):
        reason = emit_banked_neuron(
            lines, f"o{k + 1}", hidden_nodes, w2[k], float(b2[k]),
            "vref", False, catalog, config.g_weight_2, config.banks,
            config.r_min, config.r_max, 2,
        )
        if reason:
            return None, catalog, f"output {k + 1}: {reason}"

    lines.append(".model Dsi D(Is=1e-14 N=1 Rs=1)")
    lines.append("")
    lines.append(".control")
    lines.append("set numdgt=15")
    lines.append("op")
    for k in range(1, n_out + 1):
        lines.append(f"print v(o{k}lin)")
    lines.append(".endc")
    lines.append("")
    lines.append(".end")
    lines.append("")
    return "\n".join(lines), catalog, None


def range_violation(catalog: list[dict], r_min: float, r_max: float) -> str | None:
    for item in catalog:
        r = float(item["R"])
        if r < r_min:
            return f"{item['name']} R={r:.6g} < r_min={r_min:g}"
        if r > r_max:
            return f"{item['name']} R={r:.6g} > r_max={r_max:g}"
    return None


def encoding_stats(catalog: list[dict], n_weights: int) -> dict:
    rs = [float(item["R"]) for item in catalog]
    banks = sorted({str(item.get("bank", "")) for item in catalog})
    n_res = len(catalog)
    return {
        "n_resistors": n_res,
        "n_weight_resistors": sum(1 for c in catalog if c.get("role") == "weight"),
        "n_bias_resistors": sum(1 for c in catalog if c.get("role") == "bias"),
        "n_banks_used": len(banks),
        "banks_used": banks,
        "r_min": min(rs) if rs else None,
        "r_max": max(rs) if rs else None,
        "total_conductance": total_conductance(catalog) if catalog else None,
        "resistors_per_weight": n_res / n_weights if n_weights else None,
        "weight_resistors_per_weight": (
            sum(1 for c in catalog if c.get("role") == "weight") / n_weights
            if n_weights
            else None
        ),
        "i_rel_A": (total_conductance(catalog) * V_REP) if catalog else None,
    }


def iter_range_grid() -> list[RangeConfig]:
    configs: list[RangeConfig] = []
    seen: set[tuple] = set()
    for banks in BANK_SETS:
        for gw1 in G_WEIGHT_GRID:
            for gw2 in G_WEIGHT_GRID:
                cfg = RangeConfig(g_weight_1=gw1, g_weight_2=gw2, banks=banks)
                if cfg.key() not in seen:
                    seen.add(cfg.key())
                    configs.append(cfg)
    return configs


def compile_dynamic(
    spec: dict,
    weights: dict[str, np.ndarray],
    config: RangeConfig,
) -> tuple[str | None, list[dict], str | None]:
    dummy = np.zeros(spec["n_in"], dtype=float)
    title = (
        f"* Physical AI - Experiment 11: {spec['id']} multi-range encoding\n"
        f"* Frozen Experiment 9 weights. {config.label()}\n"
        "* Weights were not edited. Resistors were not clipped."
    )
    netlist, catalog, reason = generate_banked_circuit(
        dummy,
        weights["W1"],
        weights["b1"],
        weights["W2"],
        weights["b2"],
        config,
        title=title,
    )
    if reason is not None:
        return None, catalog, reason
    violation = range_violation(catalog, config.r_min, config.r_max)
    if violation is not None:
        return None, catalog, violation
    return netlist, catalog, None


def representation_limits(weights: dict[str, np.ndarray]) -> dict:
    spans = {}
    for name in ("W1", "b1", "W2", "b2"):
        mag = nonzero_abs(weights[name])
        spans[name] = {
            "min_abs": float(np.min(mag)),
            "max_abs": float(np.max(mag)),
            "ratio": float(np.max(mag) / np.min(mag)),
        }
    return {
        "parameter_spans": spans,
        "allowed_resistor_ratio": R_MAX / R_MIN,
        "parallel_only_note": (
            "G = G1+G2+... can increase conductance (large weights) but "
            "cannot create a conductance below 1/R_MAX (small weights)."
        ),
        "bank_note": (
            "Fine banks use CCCS gain alpha<1 so G_eff=alpha/R can be smaller "
            "than 1/R_MAX while every physical R stays in range. Currents "
            "still add at the SPICE difference node."
        ),
    }


def config_public(config: RangeConfig) -> dict:
    row = asdict(config)
    row["label"] = config.label()
    row["banks"] = [[name, alpha] for name, alpha in config.banks]
    return row
