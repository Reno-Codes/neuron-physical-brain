"""Matter Compiler hardware-constrained mode (Experiment 10).

Frozen weights are never edited. The compiler searches physical scales:

    G_WEIGHT_layer  ->  R_w = 1 / (G_WEIGHT * |w|)
    G_BIAS_layer    ->  R_b = 1 / (G_BIAS * |b|)

and implements bias compensation in SPICE, not in Python:

    I_b_resistor = Vref * G_BIAS * |b|          (Vref = 1 V)
    I_b_injected = k * I_b_resistor
    k = G_WEIGHT / G_BIAS
    V_b = I_b_injected / G_WEIGHT = |b|

Each layer has transimpedance R_IV = 1/G_WEIGHT, so hidden voltages stay
in neural units. No inter-layer Python correction is applied.

Resistors outside [R_MIN, R_MAX] reject a candidate. Values are never clipped.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from compile_xor import PROJECT_ROOT, apply_resistor_values, generate_circuit
from matter_compiler import physical_cost, total_conductance


CIRCUIT_DIR = PROJECT_ROOT / "circuits" / "hardware_constrained"
MODEL_DIR = PROJECT_ROOT / "models" / "scaling"

CONSTRAINT_SETS = (
    {"name": "1k-1M", "r_min": 1.0e3, "r_max": 1.0e6},
    {"name": "10k-10M", "r_min": 1.0e4, "r_max": 1.0e7},
)

BASELINE_G = 1.0e-5
N_SCALE_POINTS = 3
V_REP = 1.0


@dataclass(frozen=True)
class HardwareConfig:
    g_weight_1: float
    g_bias_1: float
    g_weight_2: float
    g_bias_2: float
    r_min: float
    r_max: float
    range_name: str
    mode: str = "per_layer"

    def label(self) -> str:
        return (
            f"{self.range_name} {self.mode} "
            f"Gw1={self.g_weight_1:.3g} Gb1={self.g_bias_1:.3g} "
            f"Gw2={self.g_weight_2:.3g} Gb2={self.g_bias_2:.3g}"
        )

    def key(self) -> tuple:
        return (
            self.mode,
            self.g_weight_1,
            self.g_bias_1,
            self.g_weight_2,
            self.g_bias_2,
            self.r_min,
            self.r_max,
        )


def nonzero_abs(values: np.ndarray) -> np.ndarray:
    flat = np.abs(np.asarray(values, dtype=float).reshape(-1))
    return flat[flat > 0.0]


def feasible_g_interval(
    values: np.ndarray, r_min: float, r_max: float
) -> tuple[float, float] | None:
    """G such that every R = 1/(G*|p|) lies in [r_min, r_max]."""
    mag = nonzero_abs(values)
    if mag.size == 0:
        return None
    lo = 1.0 / (r_max * float(np.min(mag)))
    hi = 1.0 / (r_min * float(np.max(mag)))
    if lo > hi:
        return None
    return lo, hi


def pick_scales(lo: float, hi: float, n: int = N_SCALE_POINTS) -> list[float]:
    if lo > hi:
        return []
    lo_i = lo * (1.0 + 1e-9)
    hi_i = hi / (1.0 + 1e-9)
    if hi_i <= lo_i:
        mid = float(math.sqrt(max(lo, 0.0) * hi))
        return [mid] if lo <= mid <= hi else []
    return [float(v) for v in np.geomspace(lo_i, hi_i, n)]


def parameter_dynamic_range(weights: dict[str, np.ndarray]) -> dict:
    report = {}
    for name in ("W1", "b1", "W2", "b2"):
        mag = nonzero_abs(weights[name])
        report[name] = {
            "n_nonzero": int(mag.size),
            "min_abs": float(np.min(mag)),
            "max_abs": float(np.max(mag)),
            "ratio": float(np.max(mag) / np.min(mag)),
        }
    return report


def feasibility_report(
    weights: dict[str, np.ndarray], r_min: float, r_max: float
) -> dict:
    range_ratio = r_max / r_min
    spans = parameter_dynamic_range(weights)
    intervals = {}
    impossible = []
    for name in ("W1", "b1", "W2", "b2"):
        interval = feasible_g_interval(weights[name], r_min, r_max)
        intervals[name] = None if interval is None else {
            "g_min": interval[0],
            "g_max": interval[1],
        }
        if interval is None:
            impossible.append(
                f"{name} |p|_max/|p|_min={spans[name]['ratio']:.4g} "
                f"> R_MAX/R_MIN={range_ratio:.4g}"
            )
    shared_w = None
    if intervals["W1"] and intervals["W2"]:
        lo = max(intervals["W1"]["g_min"], intervals["W2"]["g_min"])
        hi = min(intervals["W1"]["g_max"], intervals["W2"]["g_max"])
        if lo <= hi:
            shared_w = {"g_min": lo, "g_max": hi}
    shared_b = None
    if intervals["b1"] and intervals["b2"]:
        lo = max(intervals["b1"]["g_min"], intervals["b2"]["g_min"])
        hi = min(intervals["b1"]["g_max"], intervals["b2"]["g_max"])
        if lo <= hi:
            shared_b = {"g_min": lo, "g_max": hi}
    return {
        "r_min": r_min,
        "r_max": r_max,
        "range_ratio": range_ratio,
        "parameter_spans": spans,
        "feasible_g": intervals,
        "shared_weight_g": shared_w,
        "shared_bias_g": shared_b,
        "per_layer_possible": intervals["W1"] is not None
        and intervals["W2"] is not None
        and intervals["b1"] is not None
        and intervals["b2"] is not None,
        "impossible_groups": impossible,
        "signal_normalization": {
            "used": False,
            "reason": (
                "A constant inter-layer gain k with next-layer weights w/k "
                "preserves math but does not change the intra-layer ratio "
                "max|w|/min|w|. That ratio is what the resistor window "
                "R_MAX/R_MIN must cover. Normalization is therefore omitted."
            ),
        },
    }


def range_violation(catalog: list[dict], r_min: float, r_max: float) -> str | None:
    for item in catalog:
        r = float(item["R"])
        if r < r_min:
            return f"{item['name']} R={r:.6g} < r_min={r_min:g}"
        if r > r_max:
            return f"{item['name']} R={r:.6g} > r_max={r_max:g}"
    return None


def iter_hardware_grid(
    weights: dict[str, np.ndarray], r_min: float, r_max: float, range_name: str
) -> list[HardwareConfig]:
    """Deterministic per-layer and shared-scale candidates inside feasible G."""
    w1, b1, w2, b2 = weights["W1"], weights["b1"], weights["W2"], weights["b2"]
    iw1 = feasible_g_interval(w1, r_min, r_max)
    ib1 = feasible_g_interval(b1, r_min, r_max)
    iw2 = feasible_g_interval(w2, r_min, r_max)
    ib2 = feasible_g_interval(b2, r_min, r_max)
    configs: list[HardwareConfig] = []
    seen: set[tuple] = set()

    def add(cfg: HardwareConfig) -> None:
        if cfg.key() not in seen:
            seen.add(cfg.key())
            configs.append(cfg)

    if iw1 and ib1 and iw2 and ib2:
        for gw1 in pick_scales(*iw1):
            for gb1 in pick_scales(*ib1):
                for gw2 in pick_scales(*iw2):
                    for gb2 in pick_scales(*ib2):
                        add(
                            HardwareConfig(
                                g_weight_1=gw1,
                                g_bias_1=gb1,
                                g_weight_2=gw2,
                                g_bias_2=gb2,
                                r_min=r_min,
                                r_max=r_max,
                                range_name=range_name,
                                mode="per_layer",
                            )
                        )

    if iw1 and iw2 and ib1 and ib2:
        shared_w_lo = max(iw1[0], iw2[0])
        shared_w_hi = min(iw1[1], iw2[1])
        shared_b_lo = max(ib1[0], ib2[0])
        shared_b_hi = min(ib1[1], ib2[1])
        if shared_w_lo <= shared_w_hi and shared_b_lo <= shared_b_hi:
            for gw in pick_scales(shared_w_lo, shared_w_hi):
                for gb in pick_scales(shared_b_lo, shared_b_hi):
                    add(
                        HardwareConfig(
                            g_weight_1=gw,
                            g_bias_1=gb,
                            g_weight_2=gw,
                            g_bias_2=gb,
                            r_min=r_min,
                            r_max=r_max,
                            range_name=range_name,
                            mode="shared",
                        )
                    )
    return configs


def compile_hardware(
    spec: dict,
    weights: dict[str, np.ndarray],
    config: HardwareConfig,
) -> tuple[str | None, list[dict], str | None]:
    dummy = np.zeros(spec["n_in"], dtype=float)
    title = (
        f"* Physical AI - Experiment 10: hardware-constrained {spec['id']}\n"
        f"* Frozen Experiment 9 weights. Mapping: {config.label()}\n"
        f"* Weights were not edited. Resistors are not clipped."
    )
    netlist, catalog = generate_circuit(
        dummy,
        weights["W1"],
        weights["b1"],
        weights["W2"],
        weights["b2"],
        g_scale=config.g_weight_1,
        control="outputs",
        title=title,
        g_weight_1=config.g_weight_1,
        g_bias_1=config.g_bias_1,
        g_weight_2=config.g_weight_2,
        g_bias_2=config.g_bias_2,
    )
    reason = range_violation(catalog, config.r_min, config.r_max)
    if reason is not None:
        return None, catalog, reason
    return netlist, catalog, None


def compile_baseline(spec: dict, weights: dict[str, np.ndarray]) -> tuple[str, list[dict]]:
    dummy = np.zeros(spec["n_in"], dtype=float)
    title = (
        f"* Physical AI - Experiment 10 baseline (Exp 9 mapping) {spec['id']}\n"
        f"* Unified G_SCALE={BASELINE_G:.15g}. No resistor-range constraint."
    )
    netlist, catalog = generate_circuit(
        dummy,
        weights["W1"],
        weights["b1"],
        weights["W2"],
        weights["b2"],
        g_scale=BASELINE_G,
        control="outputs",
        title=title,
    )
    return netlist, catalog


def current_cost_estimate(catalog: list[dict], spice_source_current: float | None) -> dict:
    g_total = total_conductance(catalog) if catalog else 0.0
    return {
        "label": "relative physical current cost",
        "note": (
            "I_rel = SigmaG * V_rep with V_rep=1 V. This is a relative "
            "conductance-derived metric, not measured board power. "
            "SPICE source current is the sum of |I| through Vin* and Vref "
            "at one representative operating point."
        ),
        "v_rep_V": V_REP,
        "total_conductance_S": g_total,
        "i_rel_A": g_total * V_REP,
        "spice_source_current_A": spice_source_current,
    }


def load_frozen_model(net_id: str) -> dict[str, np.ndarray]:
    path = MODEL_DIR / f"{net_id}.npz"
    if not path.is_file():
        raise FileNotFoundError(
            f"Frozen Experiment 9 model missing: {path}. "
            "Run scripts/benchmark_scaling.py first."
        )
    data = np.load(path)
    return {
        "W1": np.asarray(data["W1"], dtype=float),
        "b1": np.asarray(data["b1"], dtype=float).reshape(-1),
        "W2": np.asarray(data["W2"], dtype=float),
        "b2": np.asarray(data["b2"], dtype=float).reshape(-1),
    }


def config_public(config: HardwareConfig) -> dict:
    row = asdict(config)
    row["label"] = config.label()
    row["k1"] = config.g_weight_1 / config.g_bias_1
    row["k2"] = config.g_weight_2 / config.g_bias_2
    return row
