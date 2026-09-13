"""Experiment 21: is finite TIA open-loop gain a global scale?

Architecture A (Experiment 17). Frozen weights. No Python SPICE correction.

Hypothesis check:
    k_global = A / (A + 1)
    k_j      = A / (A + 1 + Rf * G_tot_j)

If G_tot varies across neurons (fine-bank physical G), finite A is a
per-neuron attenuation, not a common-mode / ratiometric error.
F argmax can still survive a global scale; A y>=0.5 cannot.
Per-neuron k_j can flip both.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from compile_xor import PROJECT_ROOT
from passive_iv import neuron_gtot, predicted_isolated_passive
from physical_iv_neuron import IVParams, compile_iv
from precision_architectures import ARCH_C_CFG


CIRCUIT_DIR = PROJECT_ROOT / "circuits" / "finite_a_scale"


def tia_k(amp_gain: float, rf: float, g_tot: float) -> float:
    return float(amp_gain) / (float(amp_gain) + 1.0 + float(rf) * float(g_tot))


def neuron_k_factors(
    spec: dict, catalog: list[dict], amp_gain: float, g_w1: float, g_w2: float
) -> dict:
    rf1 = 1.0 / float(g_w1)
    rf2 = 1.0 / float(g_w2)
    k_h, g_h = [], []
    for j in range(1, spec["n_hidden"] + 1):
        g = neuron_gtot(catalog, f"h{j}")
        k_h.append(tia_k(amp_gain, rf1, g))
        g_h.append(g)
    k_o, g_o = [], []
    for k in range(1, spec["n_out"] + 1):
        g = neuron_gtot(catalog, f"o{k}")
        k_o.append(tia_k(amp_gain, rf2, g))
        g_o.append(g)
    k_glob = float(amp_gain) / (float(amp_gain) + 1.0)
    return {
        "k_hidden": k_h,
        "k_output": k_o,
        "G_hidden": g_h,
        "G_output": g_o,
        "k_global": k_glob,
        "k_hidden_min": float(np.min(k_h)),
        "k_hidden_max": float(np.max(k_h)),
        "k_hidden_mean": float(np.mean(k_h)),
        "k_output_min": float(np.min(k_o)),
        "k_output_max": float(np.max(k_o)),
        "G_hidden_min": float(np.min(g_h)),
        "G_hidden_max": float(np.max(g_h)),
        "Rf_Gtot_hidden_max": rf1 * float(np.max(g_h)),
        "note": (
            "k_j = A/(A+1+Rf G_tot_j). Fine-bank physical G makes G_tot "
            "span neurons. This is a physics prediction, not a SPICE fix."
        ),
    }


def predict_global(weights, inputs, k: float, rail: float) -> np.ndarray:
    kh = [k] * weights["W1"].shape[0]
    ko = [k] * weights["W2"].shape[0]
    return predicted_isolated_passive(inputs, weights, kh, ko, rail)


def predict_neuron(weights, inputs, factors: dict, rail: float) -> np.ndarray:
    return predicted_isolated_passive(
        inputs, weights, factors["k_hidden"], factors["k_output"], rail
    )


def compile_a(spec, weights, amp_gain: float):
    params = IVParams(name=f"A_{amp_gain:g}", amp_gain=amp_gain)
    return compile_iv("A", spec, weights, params)
