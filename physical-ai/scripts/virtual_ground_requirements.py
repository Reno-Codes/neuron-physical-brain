"""Experiment 22: virtual-ground TIA requirement extraction.

Architecture A (Experiment 17 feedback TIA) on frozen Experiment 9 weights.
This module does not retrain, edit weights, or correct SPICE outputs.

Closed-loop identities used as physics predictions (not SPICE fixes):

    k_j     = A / (A + 1 + Rf * G_phys,j)
    Vlin    ≈ k_j * z  +  Vos * k_j * (1 + Rf * G_phys,j)
            ≈ k_j * z  +  Vos * A * (1 + Rf * G_phys,j) / (A + 1 + Rf * G_phys,j)
    dVlin/dI_leak ≈ -Rf * k_j     (native TIA sign, before comparing to +z)

G_phys is the sum of weight/bias conductances on the summing node, including
fine-bank physical G. Shared-tap coupling is a full-network effect and is
not present in an isolated-neuron bench.

Single-pole TIA (bandwidth tests only), RC macromodel:

    V_int = -A * (Vsum - Vos)
    Vout  = V_int / (1 + s / (2 π f_p))     [series Rpole + Cpole, C open at DC]

That is a behavioral dominant pole, not a transistor GBW or datasheet f_T.
GBW proxy for this model is A * f_p.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from compile_xor import PROJECT_ROOT
from copy_minimizing import (
    _collect_encoded,
    _emit_compensated_divider,
    _emit_passive_invert,
)
from finite_a_scale import tia_k
from mismatch_fabric import path_sign
from passive_iv import neuron_gtot
from physical_iv_neuron import (
    DEFAULT_GAIN,
    IVParams,
    _collect_with_source,
    _emit_weights_src,
    _tap_loads_src,
    _uses,
    compile_iv,
    emit_tia,
)
from precision_architectures import ARCH_C_CFG


CIRCUIT_DIR = PROJECT_ROOT / "circuits" / "virtual_ground_requirements"
ERROR_LIMIT = 1.0e-3
INVERT_PINNED = 1.0e7  # keep invert residual off the TIA-A floor


@dataclass(frozen=True)
class VGParams:
    name: str
    amp_gain: float = DEFAULT_GAIN
    invert_gain: float = INVERT_PINNED
    rail: float = 15.0
    vos: float = 0.0
    i_leak: float = 0.0
    rout: float = 0.0
    pole_hz: float = 0.0
    clip_amp: bool = False
    linear: bool = True

    def iv(self) -> IVParams:
        return IVParams(
            name=self.name,
            amp_gain=self.amp_gain,
            invert_gain=self.invert_gain,
            rail=self.rail,
            vos=self.vos,
            i_leak=self.i_leak,
            rout=self.rout,
            clip_amp=self.clip_amp,
            linear=self.linear,
        )

    def public(self) -> dict:
        row = asdict(self)
        row["note"] = (
            "Behavioral TIA macromodel. pole_hz is a single open-loop pole, "
            "not transistor GBW. invert_gain is pinned high so invert "
            "residual is not mistaken for TIA A. Not a device model."
        )
        return row


def vos_to_vout_gain(amp_gain: float, rf: float, g_tot: float) -> float:
    """d Vlin / d Vos at I_src = 0. Exact from the TIA KCL + Vout = -A (Vsum-Vos)."""
    a = float(amp_gain)
    load = 1.0 + float(rf) * float(g_tot)
    return a * load / (a + load)


def leak_to_vout_gain(amp_gain: float, rf: float, g_tot: float) -> float:
    """d Vlin / d I_leak for current injected into the sum (B 0 vg I = I_leak).

    Native TIA sign is negative: extra current into the sum is inverted.
    """
    return -float(rf) * tia_k(amp_gain, rf, g_tot)


def finite_a_gain_error(amp_gain: float, rf: float, g_tot: float) -> float:
    """1 - k_j. Relative scale error on z if divider dest=0."""
    return 1.0 - tia_k(amp_gain, rf, g_tot)


def neuron_items(catalog: list[dict], tag: str) -> list[dict]:
    prefix = f"R{tag}"
    out = []
    for item in catalog:
        if item.get("role") not in {"weight", "bias"}:
            continue
        name = str(item["name"])
        if not name.startswith(prefix):
            continue
        rest = name[len(prefix):]
        if rest and rest[0] in "pnb":
            out.append(item)
    return out


def rank_neurons(
    spec: dict,
    catalog: list[dict],
    weights: dict[str, np.ndarray],
    inputs: np.ndarray,
    amp_gain: float = 1e5,
) -> list[dict]:
    """Rank every neuron by TIA loading / offset / leakage sensitivity."""
    cfg = ARCH_C_CFG[spec["id"]]
    x = np.atleast_2d(np.asarray(inputs, dtype=float))
    z1 = x @ weights["W1"].T + weights["b1"]
    h = np.maximum(0.0, z1)
    z2 = h @ weights["W2"].T + weights["b2"]
    rows = []
    tags = [f"h{j}" for j in range(1, spec["n_hidden"] + 1)]
    tags += [f"o{k}" for k in range(1, spec["n_out"] + 1)]
    for tag in tags:
        hidden = tag.startswith("h")
        idx = int(tag[1:]) - 1
        g_w = cfg.g_weight_1 if hidden else cfg.g_weight_2
        rf = 1.0 / float(g_w)
        items = neuron_items(catalog, tag)
        g_phys = neuron_gtot(catalog, tag)
        g_pos = g_neg = g_eff = 0.0
        n_fine = 0
        for item in items:
            g = float(item.get("G") or 1.0 / float(item["R"]))
            sign = path_sign(item) or item.get("path_sign")
            if sign == "p":
                g_pos += g
            elif sign == "n":
                g_neg += g
            g_eff += float(item.get("G_effective") or 0.0)
            if str(item.get("bank")) == "f":
                n_fine += 1
        z = z1[:, idx] if hidden else z2[:, idx]
        wrow = weights["W1"][idx] if hidden else weights["W2"][idx]
        bias = float(weights["b1"][idx] if hidden else weights["b2"][idx])
        l1 = sum(abs(float(w)) for w in wrow) + abs(bias)
        i_max = float(g_w) * l1
        k = tia_k(amp_gain, rf, g_phys)
        row = {
            "tag": tag,
            "layer": 1 if hidden else 2,
            "index": idx,
            "n_resistors": len(items),
            "n_fine_bank": n_fine,
            "G_phys_S": g_phys,
            "G_pos_S": g_pos,
            "G_neg_S": g_neg,
            "G_eff_S": g_eff,
            "Rf_ohm": rf,
            "Rf_Gtot": rf * g_phys,
            "k_at_A1e5": k,
            "finite_a_scale_error_at_A1e5": 1.0 - k,
            "vos_to_Vlin_V_per_V": vos_to_vout_gain(amp_gain, rf, g_phys),
            "Ileak_to_Vlin_V_per_A": leak_to_vout_gain(amp_gain, rf, g_phys),
            "z_min": float(np.min(z)),
            "z_max": float(np.max(z)),
            "z_abs_max": float(np.max(np.abs(z))),
            "l1_weight_mass": l1,
            "I_max_est_A": i_max,
            "relu_on_fraction": (
                float(np.mean(z > 0.0)) if hidden else None
            ),
        }
        rows.append(row)

    def pick(key, reverse=True):
        return max(rows, key=lambda r: r[key]) if reverse else min(rows, key=lambda r: r[key])

    hidden = [r for r in rows if r["layer"] == 1]
    by_load = sorted(rows, key=lambda r: r["Rf_Gtot"], reverse=True)
    median = sorted(hidden, key=lambda r: r["Rf_Gtot"])[len(hidden) // 2]
    return rows, {
        "worst_finite_gain": pick("Rf_Gtot"),
        "worst_offset": pick("vos_to_Vlin_V_per_V"),
        "worst_leakage": pick("Ileak_to_Vlin_V_per_A", reverse=False),
        "median_hidden": median,
        "highest_signal": pick("z_abs_max"),
        "ranking_note": (
            "Finite-A and Vos both worsen with Rf*G_phys (fine-bank physical G). "
            "Leakage-to-voltage is Rf*k_j and is worst on the lightest G_tot "
            "(largest closed-loop transimpedance). Isolated benches use that "
            "neuron's resistors; shared-tap coupling is full-network only."
        ),
        "top_finite_gain": [r["tag"] for r in by_load[:5]],
        "bottom_finite_gain": [r["tag"] for r in by_load[-5:]],
    }


def generate_isolated_neuron(
    n_src: int,
    wrow: np.ndarray,
    bias: float,
    g_weight: float,
    banks,
    params: VGParams,
    tag: str = "n1",
) -> tuple[str | None, list[dict], str | None]:
    """One Architecture-A neuron with the compiled conductance fabric."""
    catalog: list[dict] = []
    enc_layers, reason = _collect_encoded(
        np.atleast_2d(wrow), np.atleast_1d(np.array([bias], dtype=float)),
        g_weight, banks,
    )
    if reason or enc_layers is None:
        return None, catalog, reason
    src = _collect_with_source(enc_layers, 1, True)
    loads = _tap_loads_src(src)
    inv_a = params.invert_gain
    warr = np.asarray(wrow, dtype=float).reshape(-1)
    lines = [
        f"* Experiment 22 isolated TIA neuron {tag}",
        f"* frozen n={int(warr.size)} L1={float(np.sum(np.abs(warr)) + abs(float(bias))):.8g} "
        f"b={float(bias):.15g}",
        f"* A={params.amp_gain:g} vos={params.vos:g} Ileak={params.i_leak:g} "
        f"Rout={params.rout:g} fp={params.pole_hz:g} invertA={inv_a:g}",
        "* Behavioral TIA. Not transistor-level. Weights were not edited.",
        f"* shape: {n_src} -> 1 (linear Vlin vs z unless ReLU requested)",
        "",
    ]

    def need(*nodes: str) -> bool:
        return any(_uses(src, n) for n in nodes)

    for i in range(1, n_src + 1):
        lines.append(f"Vin{i} in{i} 0 DC 0")
        if need(f"in{i}n", f"tap{i}n"):
            _emit_passive_invert(
                lines, catalog, f"in{i}", f"in{i}n", f"inv{i}", 1, inv_a
            )
        if need(f"tap{i}"):
            reason = _emit_compensated_divider(
                lines, catalog, f"in{i}", f"tap{i}", f"div{i}",
                loads.get(f"tap{i}", 0.0), 1,
            )
            if reason:
                return None, catalog, reason
        if need(f"tap{i}n"):
            reason = _emit_compensated_divider(
                lines, catalog, f"in{i}n", f"tap{i}n", f"div{i}n",
                loads.get(f"tap{i}n", 0.0), 1,
            )
            if reason:
                return None, catalog, reason
    lines.append("Vref vref 0 DC 1")
    if need("vrefn", "taprefn"):
        _emit_passive_invert(lines, catalog, "vref", "vrefn", "invref", 1, inv_a)
    if need("tapref"):
        reason = _emit_compensated_divider(
            lines, catalog, "vref", "tapref", "divref",
            loads.get("tapref", 0.0), 1,
        )
        if reason:
            return None, catalog, reason
    if need("taprefn"):
        reason = _emit_compensated_divider(
            lines, catalog, "vrefn", "taprefn", "divrefn",
            loads.get("taprefn", 0.0), 1,
        )
        if reason:
            return None, catalog, reason
    lines.append("")
    _j, encoded = src[0]
    _emit_weights_src(lines, catalog, tag, wrow, encoded, g_weight, 1)
    emit_tia(
        lines, catalog, tag, g_weight, 1,
        params.amp_gain, params.rail, params.vos, params.rout,
        params.i_leak, params.clip_amp,
        out_node=f"{tag}lin",
    )
    if not params.linear:
        from physical_iv_neuron import _emit_relu_v
        _emit_relu_v(lines, tag, params.rail, False)
    lines += [
        ".control",
        "set numdgt=15",
        "op",
        f"print v({tag}lin)",
        f"print v({tag}p)",
        ".endc",
        ".end",
        "",
    ]
    net = "\n".join(lines)
    if params.pole_hz > 0.0:
        net = apply_tia_pole(net, params.pole_hz)
    return net, catalog, None


def apply_tia_pole(netlist: str, pole_hz: float, rpole: float = 1.0) -> str:
    """Insert a DC-preserving single-pole RC after each TIA voltage source.

    V_int = -A*(Vsum-Vos); Vout = V_int / (1 + s/(2 π f_p)) with C open at DC.
    Rpole defaults to 1 Ω so DC series error vs Rf (~33 kΩ) is ~30 ppm.
    Laplace E-sources are not used: ngspice rejected {-v(node)} substitution.
    """
    if pole_hz <= 0.0:
        return netlist
    wp = 2.0 * math.pi * float(pole_hz)
    cval = 1.0 / (float(rpole) * wp)
    out: list[str] = []
    for raw in netlist.splitlines():
        s = raw.strip()
        if not s or s.startswith("*"):
            out.append(raw)
            continue
        parts = s.split()
        name = parts[0]
        kind = name[0].upper()
        low = name.lower()
        is_tia = low.endswith("tia") and kind in {"E", "B"}
        if not is_tia or len(parts) < 2:
            out.append(raw)
            continue
        drv = parts[1]
        if drv.lower().endswith("ampint"):
            out.append(raw)
            continue
        stem = name[1:]
        if stem.lower().endswith("tia"):
            stem = stem[:-3]
        mid = f"{stem}ampint"
        rest = raw.split(None, 2)
        if len(rest) < 3:
            out.append(raw)
            continue
        out.append(
            f"* single-pole TIA {name}: fp={pole_hz:g} Hz Rpole={rpole:g} "
            f"C={cval:.6g} F (behavioral; DC C open; not transistor GBW)"
        )
        out.append(f"{rest[0]} {mid} {rest[2]}")
        out.append(f"R{name}pole {mid} {drv} {float(rpole):.15g}")
        out.append(f"C{name}pole {drv} 0 {cval:.15g}")
    ending = "\n" if netlist.endswith("\n") else ""
    return "\n".join(out) + ending


def closed_loop_tau(amp_gain: float, pole_hz: float, rf_gtot: float) -> float:
    """Approximate closed-loop time constant for the single-pole TIA macromodel."""
    wp = 2.0 * math.pi * max(float(pole_hz), 1e-18)
    load = 1.0 + float(rf_gtot)
    return load / (max(float(amp_gain), 1e-18) * wp)


def compile_network(spec, weights, params: VGParams, linear: bool | None = None):
    p = params.iv()
    if linear is not None:
        p = IVParams(
            name=p.name, amp_gain=p.amp_gain, invert_gain=p.invert_gain,
            rail=p.rail, vos=p.vos, i_leak=p.i_leak, rout=p.rout,
            clip_amp=p.clip_amp, linear=linear,
        )
    net, cat, reason = compile_iv("A", spec, weights, p)
    if net is not None and params.pole_hz > 0.0:
        net = apply_tia_pole(net, params.pole_hz)
    return net, cat, reason


def isolated_batch_control(inputs: np.ndarray, n_in: int, tag: str = "n1") -> str:
    lines = [".control", "set numdgt=15"]
    for x in inputs:
        for i, xi in enumerate(np.atleast_1d(x), start=1):
            if i > n_in:
                break
            lines.append(f"alter Vin{i} DC {float(xi):.15g}")
        lines.append("op")
        lines.append(f"print v({tag}lin)")
        lines.append(f"print v({tag}p)")
    lines.extend([".endc", "", ".end", ""])
    return "\n".join(lines)


def interpolate_threshold(
    rows: list[dict],
    value_key: str,
    metric_key: str,
    limit: float,
    decreasing: bool,
) -> dict | None:
    """Log-interpolate the first crossing. rows need not be unique."""
    usable = [
        r for r in rows
        if not r.get("failed") and r.get(metric_key) is not None
        and r.get(value_key) is not None
    ]
    if not usable:
        return None
    usable = sorted(usable, key=lambda r: float(r[value_key]))
    def ok(r):
        m = float(r[metric_key])
        return m <= limit if decreasing else m >= limit

    first = None
    prev = None
    for r in usable:
        if ok(r):
            first = r
            break
        prev = r
    if first is None:
        return {
            "status": "not_reached",
            "last_value": usable[-1][value_key],
            "last_metric": usable[-1][metric_key],
        }
    if prev is None:
        return {
            "status": "at_or_below_min_swept",
            "value": first[value_key],
            "metric": first[metric_key],
            "sampled": True,
        }
    x0, x1 = float(prev[value_key]), float(first[value_key])
    y0, y1 = float(prev[metric_key]), float(first[metric_key])
    if x0 <= 0 or x1 <= 0 or y1 == y0:
        xstar = x1
        method = "no_log_interp"
    else:
        t = (limit - y0) / (y1 - y0)
        t = min(1.0, max(0.0, t))
        logx = math.log(x0) + t * (math.log(x1) - math.log(x0))
        xstar = math.exp(logx)
        method = "log_interp"
    return {
        "status": "bracketed",
        "value": xstar,
        "metric": limit,
        "lo": {value_key: x0, metric_key: y0},
        "hi": {value_key: x1, metric_key: y1},
        "method": method,
        "sampled_pass": first[value_key],
    }


def max_tolerable(
    rows: list[dict],
    value_key: str,
    metric_key: str,
    limit: float,
    decreasing_metric: bool,
) -> dict | None:
    """Largest |parameter| that still meets the metric target.

    For offset/leakage, metric (MAE) increases with |value|. The last
    passing point is the maximum tolerable; interpolate to the first fail.
    """
    usable = [
        r for r in rows
        if not r.get("failed") and r.get(metric_key) is not None
        and r.get(value_key) is not None
    ]
    if not usable:
        return None
    usable = sorted(usable, key=lambda r: abs(float(r[value_key])))
    last_ok = None
    first_fail = None
    for r in usable:
        m = float(r[metric_key])
        good = m <= limit if decreasing_metric else m >= limit
        if good:
            last_ok = r
        else:
            first_fail = r
            break
    if last_ok is None:
        return {
            "status": "fails_at_min_swept",
            "first_fail": first_fail[value_key] if first_fail else None,
            "metric": first_fail[metric_key] if first_fail else None,
        }
    if first_fail is None:
        return {
            "status": "passes_through_max_swept",
            "value": last_ok[value_key],
            "metric": last_ok[metric_key],
        }
    x0, x1 = abs(float(last_ok[value_key])), abs(float(first_fail[value_key]))
    y0, y1 = float(last_ok[metric_key]), float(first_fail[metric_key])
    if x0 <= 0 or x1 <= 0 or y1 == y0:
        xstar = x0
        method = "last_pass"
    else:
        t = (limit - y0) / (y1 - y0)
        t = min(1.0, max(0.0, t))
        xstar = math.exp(math.log(x0) + t * (math.log(x1) - math.log(x0)))
        method = "log_interp"
    sign = 1.0 if float(last_ok[value_key]) >= 0 else -1.0
    return {
        "status": "bracketed",
        "value": sign * xstar,
        "abs_value": xstar,
        "lo": last_ok[value_key],
        "hi": first_fail[value_key],
        "method": method,
    }
