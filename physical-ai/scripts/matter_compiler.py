"""Matter Compiler v1: map a frozen neural network onto physical structure.

A conventional compiler emits instructions. This compiler emits a SPICE
conductance network. The trained weights are immutable; only physical
mapping parameters (G_SCALE, resistor quantization, allowed R range)
are compilation targets.

Scoring is explicit: wrong classifications are rejected first. Among
correct mappings, lower analog error and lower total conductance win.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from compile_xor import (
    CLASS_THRESHOLD,
    G_SCALE,
    PROJECT_ROOT,
    XOR_X,
    apply_resistor_values,
    classify,
    generate_circuit,
    software_forward,
)
from test_robustness import simulate_four_inputs, summarize


SEARCH_CIRCUIT = PROJECT_ROOT / "circuits" / "generated_xor_search.cir"
OPTIMIZED_CIRCUIT = PROJECT_ROOT / "circuits" / "generated_xor_optimized.cir"

# Cost weights. Classification failures dominate every other term.
COST_REJECTED = 1.0e9
COST_WRONG_BASE = 1.0e6
COST_PER_WRONG = 1.0e5
W_MAX_ERROR = 100.0
W_MAE = 10.0
W_TOTAL_G = 50.0
W_N_RESISTORS = 0.01

G_SCALE_GRID = (1e-5, 3e-5, 1e-4, 3e-4, 1e-3)
QUANT_GRID = (
    ("exact", 0.0),
    ("1%", 0.01),
    ("2%", 0.02),
    ("5%", 0.05),
    ("10%", 0.10),
)
RANGE_GRID = (
    ("unconstrained", None, None),
    ("1k-10M", 1.0e3, 1.0e7),
    ("1k-1M", 1.0e3, 1.0e6),
    ("10k-1M", 1.0e4, 1.0e6),
)


@dataclass(frozen=True)
class CompileConfig:
    g_scale: float = G_SCALE
    quant_name: str = "exact"
    quant_step: float = 0.0
    range_name: str = "unconstrained"
    r_min: float | None = None
    r_max: float | None = None

    def label(self) -> str:
        return (
            f"G={self.g_scale:.3g} quant={self.quant_name} "
            f"range={self.range_name}"
        )


def quantize_resistance(resistance: float, step: float) -> float:
    """Snap R onto a geometric grid with relative step (e.g. 0.05 = 5%)."""
    if resistance <= 0:
        raise ValueError("resistance must be positive")
    if step <= 0:
        return resistance
    ratio = 1.0 + step
    exponent = round(math.log(resistance) / math.log(ratio))
    return ratio**exponent


def resistor_values_from_catalog(
    catalog: list[dict],
    config: CompileConfig,
) -> tuple[dict[str, float], list[dict], str | None]:
    values: dict[str, float] = {}
    compiled: list[dict] = []
    for item in catalog:
        r_nom = float(item["R"])
        r = quantize_resistance(r_nom, config.quant_step)
        if config.r_min is not None and r < config.r_min:
            return {}, [], f"{item['name']} R={r:.6g} < r_min={config.r_min:g}"
        if config.r_max is not None and r > config.r_max:
            return {}, [], f"{item['name']} R={r:.6g} > r_max={config.r_max:g}"
        values[str(item["name"])] = r
        row = dict(item)
        row["R_nominal"] = r_nom
        row["R"] = r
        row["G"] = 1.0 / r
        compiled.append(row)
    return values, compiled, None


def compile_mapping(
    w1: np.ndarray,
    b1: np.ndarray,
    w2: np.ndarray,
    b2: np.ndarray,
    config: CompileConfig,
) -> tuple[str | None, list[dict], str | None]:
    netlist, catalog = generate_circuit(
        XOR_X[0], w1, b1, w2, b2, g_scale=config.g_scale
    )
    values, compiled, reason = resistor_values_from_catalog(catalog, config)
    if reason is not None:
        return None, compiled, reason
    netlist = apply_resistor_values(netlist, values)
    header = (
        f"* Matter Compiler v1 mapping: {config.label()}\n"
        f"* Frozen model weights were not changed.\n"
    )
    return header + netlist, compiled, None


def total_conductance(catalog: list[dict]) -> float:
    return float(sum(1.0 / float(item["R"]) for item in catalog))


def resistor_span(catalog: list[dict]) -> tuple[float, float]:
    rs = [float(item["R"]) for item in catalog]
    return min(rs), max(rs)


def physical_cost(
    accuracy: float,
    n_failures: int,
    mae: float,
    max_error: float,
    g_total: float,
    n_resistors: int,
    rejected: bool,
) -> float:
    """Lower is better. Wrong classes beat every analog/current term."""
    if rejected:
        return COST_REJECTED
    if n_failures > 0 or accuracy < 1.0:
        return COST_WRONG_BASE + COST_PER_WRONG * n_failures + W_MAX_ERROR * max_error
    return (
        W_MAX_ERROR * max_error
        + W_MAE * mae
        + W_TOTAL_G * g_total
        + W_N_RESISTORS * n_resistors
    )


def evaluate_mapping(
    ngspice: Path,
    w1: np.ndarray,
    b1: np.ndarray,
    w2: np.ndarray,
    b2: np.ndarray,
    software: np.ndarray,
    expected_cls: np.ndarray,
    config: CompileConfig,
    dest: Path = SEARCH_CIRCUIT,
) -> dict:
    netlist, catalog, reason = compile_mapping(w1, b1, w2, b2, config)
    record = {
        "config": asdict(config),
        "label": config.label(),
        "rejected": reason is not None,
        "reject_reason": reason,
        "physical_outputs": None,
        "software_outputs": [float(v) for v in software],
        "n_resistors": len(catalog),
        "total_conductance": None,
        "r_min_used": None,
        "r_max_used": None,
        "accuracy": 0.0,
        "n_failures": 4,
        "mae": None,
        "max_abs_error": None,
        "score": COST_REJECTED,
    }
    if netlist is None:
        return record

    y_ph = simulate_four_inputs(ngspice, netlist, {}, XOR_X, dest=dest)
    stats = summarize(y_ph, software, expected_cls)
    g_total = total_conductance(catalog)
    rmin, rmax = resistor_span(catalog)
    score = physical_cost(
        stats["accuracy"],
        stats["n_failures"],
        stats["mae"],
        stats["max_abs_error"],
        g_total,
        len(catalog),
        rejected=False,
    )
    record.update(
        {
            "physical_outputs": [float(v) for v in y_ph],
            "total_conductance": g_total,
            "r_min_used": rmin,
            "r_max_used": rmax,
            "accuracy": stats["accuracy"],
            "n_failures": stats["n_failures"],
            "mae": stats["mae"],
            "max_abs_error": stats["max_abs_error"],
            "min_margin": stats["min_margin"],
            "score": score,
            "catalog": [
                {"name": str(c["name"]), "R": float(c["R"]), "G": float(c["G"])}
                for c in catalog
            ],
        }
    )
    return record


def baseline_config() -> CompileConfig:
    return CompileConfig()


def iter_search_grid() -> list[CompileConfig]:
    configs: list[CompileConfig] = []
    for g in G_SCALE_GRID:
        for qname, qstep in QUANT_GRID:
            for rname, rmin, rmax in RANGE_GRID:
                configs.append(
                    CompileConfig(
                        g_scale=g,
                        quant_name=qname,
                        quant_step=qstep,
                        range_name=rname,
                        r_min=rmin,
                        r_max=rmax,
                    )
                )
    return configs


def software_reference(w1, b1, w2, b2) -> tuple[np.ndarray, np.ndarray]:
    software = np.array(
        [software_forward(x, w1, b1, w2, b2) for x in XOR_X], dtype=float
    )
    expected = np.array([classify(float(y)) for y in software], dtype=int)
    return software, expected


def write_optimized_circuit(
    w1, b1, w2, b2, config: CompileConfig, path: Path = OPTIMIZED_CIRCUIT
) -> Path:
    netlist, _catalog, reason = compile_mapping(w1, b1, w2, b2, config)
    if netlist is None:
        raise RuntimeError(f"cannot write optimized circuit: {reason}")
    path.write_text(netlist, encoding="utf-8")
    return path
