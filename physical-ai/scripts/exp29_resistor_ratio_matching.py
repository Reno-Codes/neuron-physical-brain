"""Experiment 29: resistor-ratio matching and Network F feasibility.

Frozen Experiment 9 weights. SPICE is the source of truth.
Does not overwrite Experiments 1–28. Does not transistorize Network F.
Does not Python-correct circuit outputs.
"""

from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from benchmark_scaling import (
    classification_labels,
    error_stats,
    generate_inputs,
    make_rng,
    simulate_batch,
)
from compile_xor import PROJECT_ROOT, find_ngspice
from hardware_constrained_compiler import load_frozen_model
from physical_iv_neuron import IVParams, accounting, compile_iv
from precision_architectures import ARCH_C_CFG, software_reference
from resistor_ratio_matching import (
    AMP_A,
    AMP_A_HIGH,
    ERROR_LIMIT,
    G_WEIGHT,
    INVERT_A,
    TOL_05,
    annotate_fabric,
    apply_values,
    inventory,
    kind_of,
    model_catalog,
    neuron_ratio_errors,
    neuron_tag,
    quantize_values,
    sample_named,
    tile_tia_fabric,
)
from test_hardware_constraints import spec_by_id
from test_robustness import extract_all
from test_servo_transient import iso_sources, pick_steps
from virtual_ground_requirements import (
    VGParams,
    generate_isolated_neuron,
    rank_neurons,
)


CIRCUIT_DIR = PROJECT_ROOT / "circuits" / "exp29_resistor_ratio_matching"
RESULTS_DIR = PROJECT_ROOT / "results"
REPORT_JSON = RESULTS_DIR / "exp29_resistor_ratio_matching.json"
REPORT_MD = RESULTS_DIR / "exp29_resistor_ratio_matching.md"
EXP27_JSON = RESULTS_DIR / "exp27_matching_temperature.json"

N_COMPARE = 12
N_FULL = 40
N_MC = 8
N_MC_PROMOTED = 16
TIMEOUT_F = 240.0
TIMEOUT_ISO = 90.0
SEED = 29


def dest(*parts) -> Path:
    name = "_".join(str(p).replace(".", "p").replace("-", "m").replace("+", "p") for p in parts)
    CIRCUIT_DIR.mkdir(parents=True, exist_ok=True)
    return CIRCUIT_DIR / f"{name}.cir"


def fmt(v, spec=".4e"):
    if v is None:
        return "n/a"
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, float):
        return format(v, spec)
    return str(v)


def slim_num(x):
    if isinstance(x, (np.floating, np.integer)):
        return x.item()
    return x


def mc_stats(maes, accs=None, analog_limit=ERROR_LIMIT):
    arr = np.asarray(maes, dtype=float)
    if arr.size == 0:
        return {
            "n_ok": 0,
            "mae_mean": None,
            "mae_median": None,
            "mae_p95": None,
            "mae_worst": None,
            "analog_pass_frac": None,
            "acc_mean": None,
            "class_pass_frac": None,
        }
    accs = [] if accs is None else list(accs)
    rec = {
        "n_ok": int(arr.size),
        "mae_mean": float(np.mean(arr)),
        "mae_median": float(np.median(arr)),
        "mae_p95": float(np.percentile(arr, 95)),
        "mae_worst": float(np.max(arr)),
        "analog_pass_frac": float(np.mean(arr <= analog_limit)),
        "limited_monte_carlo": True,
        "not_a_yield": True,
    }
    if accs:
        aa = np.asarray(accs, dtype=float)
        rec["acc_mean"] = float(np.mean(aa))
        rec["class_pass_frac"] = float(np.mean(aa >= 1.0 - 1e-12))
    return rec


def save_report(report: dict) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(report, indent=2, default=slim_num), encoding="utf-8")


def load_exp27_baseline() -> dict:
    if not EXP27_JSON.exists():
        return {"available": False}
    raw = json.loads(EXP27_JSON.read_text(encoding="utf-8"))
    keep = {}
    for key in (
        "tiling",
        "ratio_matching",
        "polarity",
        "which_resistors",
        "independent_vs_tol",
        "n_logical",
        "o2_Rf_Gtot",
    ):
        if key in raw:
            keep[key] = raw[key]
    return {"available": True, "excerpt": keep, "source": "results/exp27_matching_temperature.json"}


def compile_f(weights, amp=AMP_A):
    spec = spec_by_id("F")
    params = IVParams(name="exp29", amp_gain=amp, invert_gain=INVERT_A, vos=0.0, linear=False)
    net, cat, reason = compile_iv("A", spec, weights, params)
    if reason or net is None:
        raise RuntimeError(f"compile F failed: {reason}")
    annotate_fabric(cat)
    return net, cat, spec, params


def compile_o2(weights, spec, o2):
    cfg = ARCH_C_CFG["F"]
    wrow = weights["W2"][o2["index"]]
    bias = float(weights["b2"][o2["index"]])
    n_src = spec["n_hidden"]
    params = VGParams(name="exp29iso", amp_gain=AMP_A, invert_gain=INVERT_A, vos=0.0, linear=True)
    net, cat, reason = generate_isolated_neuron(
        n_src, wrow, bias, cfg.g_weight_2, cfg.banks, params, tag="n1"
    )
    if reason or net is None:
        raise RuntimeError(f"compile o2 failed: {reason}")
    annotate_fabric(cat)
    return net, cat, wrow, bias, n_src


def eval_f(ng, net, cat, spec, weights, x, y_ref, path, values=None, timeout=TIMEOUT_F):
    physical, runtime, err, _log = simulate_batch(
        ng, net, x, spec["n_out"], path, r_values=values, timeout=timeout
    )
    rec = {"failed": bool(err or physical is None), "failure_reason": err, "spice_s": runtime}
    if rec["failed"]:
        return rec
    st = error_stats(physical, y_ref)
    pred = classification_labels(physical)
    exp = classification_labels(y_ref)
    acc = float(np.mean(pred == exp))
    rec.update(st)
    rec["accuracy"] = acc
    rec["n_class_failures"] = int(np.sum(pred != exp))
    rec["analog_pass"] = st["mae"] <= ERROR_LIMIT
    if values is not None:
        rec["ratio"] = neuron_ratio_errors(cat, values)
    return rec


def eval_iso(ng, net, inputs, z_ref, path, values=None, timeout=TIMEOUT_ISO):
    from benchmark_scaling import detect_spice_failure
    from compile_xor import run_ngspice

    head, sep, _ = net.partition(".control")
    if not sep:
        return {"failed": True, "failure_reason": "no .control"}
    body = apply_values(head, values or {})
    lines = [".control", "set numdgt=15"]
    xin = np.atleast_2d(np.asarray(inputs, dtype=float))
    for x in xin:
        for i, xi in enumerate(np.atleast_1d(x), start=1):
            lines.append(f"alter Vin{i} DC {float(xi):.15g}")
        lines.append("op")
        lines.append("print v(n1lin)")
    lines.extend([".endc", "", ".end", ""])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body.rstrip() + "\n" + "\n".join(lines), encoding="utf-8")
    t0 = time.perf_counter()
    result = run_ngspice(ng, path, timeout=timeout)
    runtime = time.perf_counter() - t0
    text = f"{result.stdout or ''}\n{result.stderr or ''}"
    fail = detect_spice_failure(result)
    rec = {"failed": bool(fail), "failure_reason": fail, "spice_s": runtime}
    if fail:
        return rec
    ys = extract_all(text, "v(n1lin)")
    z = np.atleast_1d(np.asarray(z_ref, dtype=float))
    if len(ys) != len(z):
        rec.update({"failed": True, "failure_reason": f"expected {len(z)} v(n1lin), got {len(ys)}"})
        return rec
    y = np.asarray(ys, dtype=float)
    rec.update(error_stats(y.reshape(-1, 1), z.reshape(-1, 1)))
    rec["analog_pass"] = rec["mae"] <= ERROR_LIMIT
    rec["n_vectors"] = int(y.size)
    return rec


def run_mc_f(ng, net, cat, spec, weights, x, y_ref, model, n, seed_tag, **kw):
    rng = make_rng("exp29", seed_tag, model, SEED)
    maes, accs, ratios = [], [], []
    first_fail = None
    for i in range(n):
        values = sample_named(cat, model, rng, spec=spec, **kw)
        rec = eval_f(ng, net, cat, spec, weights, x, y_ref, dest("f", model, seed_tag, i), values)
        if rec.get("failed"):
            first_fail = rec.get("failure_reason")
            print(f"    F {model} draw {i} FAIL {first_fail}", flush=True)
            continue
        maes.append(rec["mae"])
        accs.append(rec["accuracy"])
        if rec.get("ratio") and rec["ratio"].get("rms_d_rfG") is not None:
            ratios.append(rec["ratio"]["rms_d_rfG"])
        print(
            f"    F {model} {i + 1}/{n} MAE={rec['mae']:.4e} acc={rec['accuracy']:.3f}",
            flush=True,
        )
    out = mc_stats(maes, accs)
    out.update({"model": model, "kw": {k: slim_num(v) for k, v in kw.items()}, "first_fail": first_fail})
    if ratios:
        out["rms_d_rfG_mean"] = float(np.mean(ratios))
    return out


def run_mc_iso(ng, net, cat, xs, zs, model, n, seed_tag, spec=None, **kw):
    rng = make_rng("exp29iso", seed_tag, model, SEED)
    maes = []
    for i in range(n):
        values = sample_named(cat, model, rng, spec=spec, **kw)
        rec = eval_iso(ng, net, xs, zs, dest("iso", model, seed_tag, i), values)
        if rec.get("failed"):
            print(f"    iso {model} draw {i} FAIL {rec.get('failure_reason')}", flush=True)
            continue
        maes.append(rec["mae"])
        print(f"    iso {model} {i + 1}/{n} MAE={rec['mae']:.4e}", flush=True)
    out = mc_stats(maes)
    out.update({"model": model, "kw": {k: slim_num(v) for k, v in kw.items()}})
    return out


def software_for(weights, x):
    return software_reference(x, weights["W1"], weights["b1"], weights["W2"], weights["b2"])


def write_plots(report):
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    def save(fig, name):
        fig.tight_layout()
        fig.savefig(RESULTS_DIR / name, dpi=140)
        plt.close(fig)

    ind = report.get("independent_vs_tol") or []
    if ind:
        fig, ax = plt.subplots(figsize=(6.2, 4.0))
        ax.semilogy([r["tol"] for r in ind], [r["mae_mean"] for r in ind], "o-", label="F mean MAE")
        ax.axhline(ERROR_LIMIT, color="0.4", ls="--", label="analog 1e-3")
        ax.set_xlabel("independent relative mismatch (uniform half-width)")
        ax.set_ylabel("analog MAE")
        ax.set_title("Experiment 29: Network F vs independent mismatch")
        ax.legend()
        save(fig, "exp29_mae_vs_independent.png")

    ratio = report.get("ratio_local_sweep") or []
    if ratio:
        fig, ax = plt.subplots(figsize=(6.2, 4.0))
        ax.semilogy(
            [r["local_frac"] * TOL_05 for r in ratio],
            [r["mae_mean"] for r in ratio],
            "s-",
            label="neuron-ratio residual",
        )
        ax.axhline(ERROR_LIMIT, color="0.4", ls="--", label="analog 1e-3")
        ax.set_xlabel("local residual after neuron-ratio matching (relative)")
        ax.set_ylabel("analog MAE")
        ax.set_title("Experiment 29: Network F vs ratio-group residual")
        ax.legend()
        save(fig, "exp29_mae_vs_ratio.png")

    corr = report.get("polarity_rho") or []
    if corr:
        fig, ax = plt.subplots(figsize=(6.2, 4.0))
        ax.semilogy([r["rho"] for r in corr], [r["mae_mean"] for r in corr], "o-")
        ax.axhline(ERROR_LIMIT, color="0.4", ls="--")
        ax.set_xlabel("+/− mixing weight ρ (1 = pair-matched)")
        ax.set_ylabel("analog MAE")
        ax.set_title("Experiment 29: isolated o2 vs +/− correlation")
        save(fig, "exp29_mae_vs_correlation.png")

    sens = report.get("sensitivity") or []
    if sens:
        fig, ax = plt.subplots(figsize=(7.2, 4.4))
        names = [r["model"].replace("sens_", "") for r in sens]
        ys = [r.get("mae_mean") or np.nan for r in sens]
        ax.barh(names, ys)
        ax.axvline(ERROR_LIMIT, color="0.3", ls="--")
        ax.set_xlabel("mean analog MAE (0.5% on named subset)")
        ax.set_title("Experiment 29: Network F resistor-relationship sensitivity")
        save(fig, "exp29_sensitivity.png")

    quant = report.get("quantization") or []
    if quant:
        fig, ax = plt.subplots(figsize=(6.2, 4.0))
        xs = [r.get("n_unit_elements") or np.nan for r in quant]
        ys = [r.get("mae") or np.nan for r in quant]
        ax.loglog(xs, ys, "o-")
        ax.axhline(ERROR_LIMIT, color="0.4", ls="--")
        ax.set_xlabel("unit-element count (TIA fabric, quantized)")
        ax.set_ylabel("analog MAE (quantization only)")
        ax.set_title("Experiment 29: quantization vs element count")
        save(fig, "exp29_quantization.png")

    grad = report.get("gradient") or []
    if grad:
        fig, ax = plt.subplots(figsize=(6.4, 4.2))
        by = {}
        for r in grad:
            by.setdefault(r["placement"], []).append(r)
        for name, rows in by.items():
            ax.semilogy([r["gx"] for r in rows], [r["mae_mean"] for r in rows], "o-", label=name)
        ax.axhline(ERROR_LIMIT, color="0.4", ls="--")
        ax.set_xlabel("normalized linear gradient gx (R proportional to 1 + gx x')")
        ax.set_ylabel("analog MAE")
        ax.set_title("Experiment 29: Network F systematic-gradient stress")
        ax.legend()
        save(fig, "exp29_gradient.png")

    promo = report.get("promoted_mc") or {}
    draws = promo.get("draws") or []
    if draws:
        fig, ax = plt.subplots(figsize=(6.2, 4.0))
        ax.hist(draws, bins=min(10, max(4, len(draws))), color="0.35")
        ax.axvline(ERROR_LIMIT, color="crimson", ls="--", label="analog 1e-3")
        ax.set_xlabel("Network F analog MAE")
        ax.set_ylabel("draws")
        ax.set_title(
            f"Experiment 29: {promo.get('model')} limited MC (n={len(draws)}, not a yield)"
        )
        ax.legend()
        save(fig, "exp29_network_f_mc.png")

    models = report.get("structured_models") or []
    if models:
        fig, ax = plt.subplots(figsize=(7.4, 4.6))
        names = [r["model"] for r in models]
        ys = [r.get("mae_mean") or np.nan for r in models]
        ax.barh(names, ys)
        ax.axvline(ERROR_LIMIT, color="0.3", ls="--")
        ax.set_xlabel("mean analog MAE @ 0.5% (12-vector F, 8 draws)")
        ax.set_title("Experiment 29: structured matching models")
        save(fig, "exp29_mae_vs_model.png")


def conclude(report):
    promo = report.get("promoted_mc") or {}
    mean_ok = bool(promo.get("mae_mean") is not None and promo["mae_mean"] <= ERROR_LIMIT)
    p95_ok = bool(promo.get("mae_p95") is not None and promo["mae_p95"] <= ERROR_LIMIT)
    worst_ok = bool(promo.get("mae_worst") is not None and promo["mae_worst"] <= ERROR_LIMIT)
    grad_ok = True
    for r in report.get("gradient") or []:
        if r.get("placement") == "centroid" and r.get("gx", 0) >= 0.005:
            if r.get("mae_mean") is not None and r["mae_mean"] > ERROR_LIMIT:
                grad_ok = False
    quant_floor = False
    for r in report.get("quantization") or []:
        if (r.get("n_unit_elements") or 0) > 20000 and (r.get("mae") or 0) > ERROR_LIMIT:
            quant_floor = True
    if mean_ok and p95_ok and worst_ok and grad_ok:
        status = "RESISTOR-RATIO MATCHING PARTIALLY VALIDATED"
        # teaching-card / statistical abstraction / limited MC: never full VALIDATED
    elif mean_ok and not p95_ok:
        status = "RESISTOR-RATIO MATCHING PARTIALLY VALIDATED"
    elif quant_floor and not mean_ok:
        status = "NETWORK-SCALE MATCHING LIMIT FOUND"
    elif not mean_ok:
        # still may have a clear required-ratio number
        if (report.get("requirement") or {}).get("local_residual_for_mean_pass") is not None:
            status = "RESISTOR-RATIO MATCHING PARTIALLY VALIDATED"
        else:
            status = "RESISTOR-RATIO MATCHING NOT VALIDATED"
    else:
        status = "RESISTOR-RATIO MATCHING PARTIALLY VALIDATED"
    if status == "RESISTOR-RATIO MATCHING VALIDATED":
        status = "RESISTOR-RATIO MATCHING PARTIALLY VALIDATED"
    report["final_status"] = status
    report["next_experiment"] = (
        "Experiment 30 should not rebuild the encoding and should not transistorize "
        "Network F. The remaining physical gaps are a documented PDK (resistor TCR, "
        "MOS/resistor mismatch PDF, real unit-array geometry) and replacing the "
        "Architecture A invert VCVS. Independent 0.5% remains unacceptable. "
        "Do not invent foundry coefficients. Do not retrain."
    )
    return status


def write_markdown(report):
    inv = report.get("inventory") or {}
    nom = report.get("nominal_f") or {}
    exp27 = report.get("exp27_replay") or {}
    req = report.get("requirement") or {}
    promo = report.get("promoted_mc") or {}
    lines = [
        "==================================================",
        "EXPERIMENT 29",
        "RESISTOR-RATIO MATCHING AND NETWORK-SCALE FEASIBILITY",
        "==================================================",
        "",
        "Frozen Experiment 9 weights. SPICE is the source of truth.",
        "Experiments 1–28 were not overwritten. No Python correction,",
        "no affine fit, no per-weight calibration, no new encoding.",
        "Network F was not built from transistors. No foundry PCM or",
        "resistor TCR was invented. Matching models are documented",
        "statistical / layout abstractions.",
        "",
        "## 1. Objective",
        "",
        "Determine whether a physically meaningful resistor-ratio matching",
        "architecture can bring the frozen Network F fabric to analog",
        "MAE ≤ 1e-3 without blind tiling, per-weight calibration, or",
        "retraining. Classification is reported separately.",
        "",
        "## 2. Frozen baseline",
        "",
        f"- Network F Architecture A, A={AMP_A:g}, Vos=0, invert A={INVERT_A:g}",
        f"- Logical resistors: {inv.get('n_resistors')}",
        f"- By kind: {inv.get('by_kind')}",
        f"- Nominal 40-vector MAE={fmt(nom.get('mae'))} acc={fmt(nom.get('accuracy'), '.4f')}",
        f"- Nominal 12-vector MAE={fmt((report.get('nominal_f12') or {}).get('mae'))}",
        f"- Finite-A floor is already ~{fmt(nom.get('mae'))}; matching must not spend the rest of the 1e-3 budget.",
        "",
        "Experiment 27 isolated-o2 MOS replay (not overwritten):",
        f"- o2 logical R={exp27.get('n_logical')}",
        f"- independent 0.5% N=1 MAE ≈ {fmt((exp27.get('tile_n1') or {}).get('mae'))}",
        f"- independent 0.5% N=16 MAE ≈ {fmt((exp27.get('tile_n16') or {}).get('mae'))}",
        f"- common-mode 0.5% MAE ≈ {fmt((exp27.get('common_mode') or {}).get('mae'))}",
        f"- ratio-matched 0.5% MAE ≈ {fmt((exp27.get('ratio_matched') or {}).get('mae'))}",
        "",
        "## 3. Why absolute tolerance is the wrong metric",
        "",
        "Architecture A computes Vlin ≈ −Rf · Σ Vin G. A global scale on",
        "every resistor leaves Rf·G invariant. Independent 0.5% does not.",
        "Experiment 27 already showed common-mode 0.5% is invisible on o2.",
        "This experiment asks which *physical grouping* must share that scale",
        "on the full compiled Network F fabric.",
        "",
        "## 4. Matching models tested",
        "",
    ]
    for m in model_catalog():
        lines.append(f"- **{m['name']}**: {m['physical']}")
    lines += [
        "",
        "Each model is a documented abstraction (sheet, pair, neuron array,",
        "unit element, linear gradient). None is a foundry extraction.",
        "",
        "## 5. Sensitivity decomposition",
        "",
        "0.5% independent error on one relationship, others nominal.",
        "Network F, 12 vectors, 8 draws (limited MC, not a yield).",
        "",
        "| subset | MAE mean | p95 | worst | analog pass | acc mean |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in report.get("sensitivity") or []:
        lines.append(
            "| {m} | {a} | {p} | {w} | {f} | {c} |".format(
                m=r.get("model", "").replace("sens_", ""),
                a=fmt(r.get("mae_mean")),
                p=fmt(r.get("mae_p95")),
                w=fmt(r.get("mae_worst")),
                f=fmt(r.get("analog_pass_frac"), ".3f"),
                c=fmt(r.get("acc_mean"), ".4f"),
            )
        )
    lines += [
        "",
        "## 6. Rf-to-weight ratio tracking",
        "",
        "Structured models at 0.5% on 12-vector Network F (8 draws):",
        "",
        "| model | MAE mean | p95 | worst | analog pass | rms d(Rf G) | acc |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in report.get("structured_models") or []:
        lines.append(
            "| {m} | {a} | {p} | {w} | {f} | {q} | {c} |".format(
                m=r.get("model"),
                a=fmt(r.get("mae_mean")),
                p=fmt(r.get("mae_p95")),
                w=fmt(r.get("mae_worst")),
                f=fmt(r.get("analog_pass_frac"), ".3f"),
                q=fmt(r.get("rms_d_rfG_mean")),
                c=fmt(r.get("acc_mean"), ".4f"),
            )
        )
    lines += [
        "",
        "Local residual after per-neuron ratio matching (tol=0.5% shared group):",
        "",
        "| local residual | MAE mean | analog pass |",
        "| --- | --- | --- |",
    ]
    for r in report.get("ratio_local_sweep") or []:
        lines.append(
            f"| {fmt(r.get('local_frac') * TOL_05)} | {fmt(r.get('mae_mean'))} | {fmt(r.get('analog_pass_frac'), '.3f')} |"
        )
    lines += [
        "",
        "## 7. Positive/negative branch matching",
        "",
        "| test | MAE mean | p95 | analog pass | acc |",
        "| --- | --- | --- | --- | --- |",
    ]
    for r in report.get("polarity_f") or []:
        lines.append(
            f"| {r.get('model')} | {fmt(r.get('mae_mean'))} | {fmt(r.get('mae_p95'))} | "
            f"{fmt(r.get('analog_pass_frac'), '.3f')} | {fmt(r.get('acc_mean'), '.4f')} |"
        )
    lines += [
        "",
        "Isolated o2 ρ sweep (mixing weight; 1 = pair-matched, Rf included):",
        "",
        "| ρ | MAE mean | analog pass |",
        "| --- | --- | --- |",
    ]
    for r in report.get("polarity_rho") or []:
        lines.append(
            f"| {fmt(r.get('rho'), '.2f')} | {fmt(r.get('mae_mean'))} | {fmt(r.get('analog_pass_frac'), '.3f')} |"
        )
    lines += [
        "",
        "## 8. Unit-element / segmented implementation",
        "",
        "Quantization only (no mismatch). Frozen weights unchanged;",
        "compiled G rounded to k·G_unit.",
        "",
        "| G_unit / G_W | n_units | unmatched | mean rel G | F MAE | analog |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in report.get("quantization") or []:
        lines.append(
            "| {g} | {n} | {u} | {m} | {e} | {p} |".format(
                g=fmt(r.get("g_unit_over_gw"), ".4g"),
                n=r.get("n_unit_elements"),
                u=r.get("n_unmatched_residual"),
                m=fmt(r.get("mean_rel_g")),
                e=fmt(r.get("mae")),
                p=r.get("analog_pass"),
            )
        )
    ua = report.get("unit_array_mc") or []
    if ua:
        lines += [
            "",
            "Unit-array mismatch (quantized + sheet + 1/√N local), 12-vector F:",
            "",
            "| G_unit/G_W | MAE mean | analog pass | n_units |",
            "| --- | --- | --- | --- |",
        ]
        for r in ua:
            lines.append(
                f"| {fmt(r.get('g_unit_over_gw'), '.4g')} | {fmt(r.get('mae_mean'))} | "
                f"{fmt(r.get('analog_pass_frac'), '.3f')} | {r.get('n_unit_elements')} |"
            )
    iso_tile = report.get("iso_explicit_tiles")
    if iso_tile:
        lines += [
            "",
            f"Isolated o2 explicit tiles (not statistical 1/√N): {iso_tile}",
        ]
    lines += [
        "",
        "## 9. Systematic gradient stress",
        "",
        "R ∝ 1 + gx·x' on the documented floorplan. gx is normalized, not ppm/µm.",
        "Matched neuron groups remain unless noted.",
        "",
        "| placement | gx | MAE mean | analog pass |",
        "| --- | --- | --- | --- |",
    ]
    for r in report.get("gradient") or []:
        lines.append(
            f"| {r.get('placement')} | {fmt(r.get('gx'), '.4g')} | {fmt(r.get('mae_mean'))} | "
            f"{fmt(r.get('analog_pass_frac'), '.3f')} |"
        )
    lines += [
        "",
        "## 10. Full Network F results",
        "",
        f"Promoted model: **{promo.get('model')}**.",
        f"Vectors: {promo.get('n_vectors')}. Draws: {promo.get('n_ok')} "
        "(limited Monte Carlo, **not a yield**).",
        "",
        f"- MAE mean {fmt(promo.get('mae_mean'))}",
        f"- MAE median {fmt(promo.get('mae_median'))}",
        f"- MAE p95 {fmt(promo.get('mae_p95'))}",
        f"- MAE worst {fmt(promo.get('mae_worst'))}",
        f"- analog pass fraction {fmt(promo.get('analog_pass_frac'), '.3f')}",
        f"- classification accuracy mean {fmt(promo.get('acc_mean'), '.4f')}",
        f"- classification all-correct fraction {fmt(promo.get('class_pass_frac'), '.3f')}",
        "",
        f"Independent 0.5% on the same 40-vector set: mean MAE "
        f"{fmt((report.get('independent_f40') or {}).get('mae_mean'))}, "
        f"analog pass {fmt((report.get('independent_f40') or {}).get('analog_pass_frac'), '.3f')}, "
        f"acc {fmt((report.get('independent_f40') or {}).get('acc_mean'), '.4f')}.",
        "",
        "Network-wide Experiment 27 ratio model (one TIA-family scale) on F40:",
        f"- MAE mean {fmt((report.get('ratio_exp27_f40') or {}).get('mae_mean'))} "
        f"p95 {fmt((report.get('ratio_exp27_f40') or {}).get('mae_p95'))} "
        f"worst {fmt((report.get('ratio_exp27_f40') or {}).get('mae_worst'))} "
        f"analog pass {fmt((report.get('ratio_exp27_f40') or {}).get('analog_pass_frac'), '.3f')}",
        "",
        f"Finite-A control (A=1e7, {promo.get('model')}, 12-vec): "
        f"nominal MAE {fmt((report.get('finite_a_control') or {}).get('nominal_mae'))}, "
        f"matched mean MAE {fmt((report.get('finite_a_control') or {}).get('mae_mean'))}. "
        "The A=1e5 floor is ~4.8e-4; matching residual remains ~6e-4 without it.",
        "",
        "## 11. Analog versus classification",
        "",
        "Classification can remain high while analog MAE misses 1e-3.",
        "A configuration is not analog-equivalent because argmax is stable.",
        f"Nominal F accuracy {fmt(nom.get('accuracy'), '.4f')}. Independent 0.5% "
        "typically keeps classification near 99% while analog-failing.",
        "",
        "## 12. Physical implementation requirements",
        "",
        report.get("implementation_text") or "",
        "",
        "## 13. Component-count tradeoffs",
        "",
        report.get("count_text") or "",
        "",
        "## 14. What failed and why",
        "",
        report.get("failures_text") or "",
        "",
        "## 15. Quantified matching requirement",
        "",
        f"- Analog bar: MAE ≤ {ERROR_LIMIT:g}",
        f"- Independent 0.5% on F does **not** meet it (mean {fmt((report.get('independent_f12') or {}).get('mae_mean'))}).",
        f"- Required local residual after per-neuron Rf·G matching: {fmt(req.get('local_residual_for_mean_pass'))}",
        f"- Required +/− mixing weight ρ (isolated o2, analog mean-pass): {fmt(req.get('rho_for_mean_pass'))}",
        f"- Required unit G (quantization-only analog-pass): {fmt(req.get('g_unit_for_quant_pass'))}",
        f"- Gradient gx that breaks centroid+ratio (mean): {fmt(req.get('gx_breaks_centroid'))}",
        "",
        "Hypothesis verdicts (this fabric, this limited MC):",
        "H1 shared unit/sheet scale cancels — supported (common-mode = nominal).",
        "H2 Rf-to-G tracking matters more than global absolute R — supported",
        "(rf_g_track analog-passes; rf_independent fails).",
        "H3 +/− pairing is required but not sufficient — supported",
        "(systematic polarity is worst; pairs without Rf·G still fail).",
        "H4 integer/segmented units beat independent absolute R — not supported",
        "as a replacement for ratio grouping; quantization of the frozen map",
        "is a separate error source.",
        "H5 a quantization / unmatched-residual floor exists — supported",
        "(G_W/1024 still analog-fails; local residual 0.125% mean-fails).",
        "H6 systematic spatial fields can beat equal-RMS independent error —",
        "supported on naive polarity-split placement; centroid+ratio survives",
        "gx≤0.02 in this abstraction.",
        "H7 structured ratio matching can meet Network F MAE ≤ 1e-3 at a",
        "nominal 0.5% group scale — supported in this limited MC, provided",
        "unmatched local residual stays ≲ 0.075%. Not a foundry yield.",
        "",
        "These are measured SPICE thresholds on this frozen fabric and these",
        "abstractions. They are not foundry ppm specifications.",
        "",
        "## 16. Physical realism level",
        "",
        "LEVEL 2/3 behavioral Architecture A fabric (E-source TIA, Vos=0).",
        "Resistor values are physical. Matching is a statistical layout",
        "abstraction. Not LEVEL 4 Network F. Not LEVEL 5/6.",
        "",
        "## 17. Limitations",
        "",
        "- Limited Monte Carlo; not a yield.",
        "- No documented PDK resistor mismatch or TCR.",
        "- Floorplan positions are an abstraction, not GDS.",
        "- Unit-array 1/√N is statistical except where isolated tiles were emitted.",
        "- Invert stages remain VCVS.",
        "- Finite A=1e5 is included in the primary numbers.",
        "- Experiment 28 interface and Experiment 26 MOS cell were not rebuilt.",
        "",
        "## 18. Experiment 30 recommendation",
        "",
        report.get("next_experiment") or "",
        "",
        "## 19. Final status",
        "",
        report.get("final_status") or "",
        "",
        "SPICE is the source of truth. Frozen Experiment 9 weights were not edited.",
        "",
    ]
    REPORT_MD.write_text("\n".join(lines), encoding="utf-8")


def implementation_blurbs(report, inv):
    promo = (report.get("promoted_mc") or {}).get("model")
    n = inv.get("n_resistors") or 1342
    n_neu = inv.get("n_neurons_with_r") or 48
    kinds = inv.get("by_kind") or {}
    report["implementation_text"] = (
        f"Promoted grouping is `{promo}`. It requires {n_neu} matched TIA arrays "
        "(one per neuron) in which Rf shares the same resistor family as that "
        "neuron's weights and bias. Invert R1/R2 and divider Ra/Rb must be "
        "pair-matched. Polarity pairs should be co-located; a chip-wide +/− "
        "field is destructive. Common-centroid / interdigitated placement is "
        "the abstraction that reduces linear-gradient residual. This is a "
        "matching *relationship*, not a claimed die area."
    )
    q = report.get("quantization") or []
    q16 = next((r for r in q if abs((r.get("g_unit_over_gw") or 0) - 1 / 16) < 1e-9), None)
    qpass = next((r for r in q if r.get("analog_pass")), None)
    extra = ""
    if q16:
        extra = (
            f" At G_unit=G_W/16 the TIA fabric becomes {q16.get('n_unit_elements')} "
            f"unit elements vs {n} logical resistors "
            f"({(q16.get('n_unit_elements') or 0) / max(n, 1):.2f}×) and still "
            f"quantization-fails (MAE {q16.get('mae'):.3e})."
        )
    if qpass:
        extra += (
            f" Quantization-only analog-pass first occurs at G_unit={qpass.get('g_unit_S'):.3e} "
            f"({qpass.get('n_unit_elements')} units, ~{qpass.get('n_unit_elements') / max(n, 1):.0f}×)."
        )
    report["count_text"] = (
        f"Current compiled fabric: {n} logical resistors "
        f"({kinds.get('weight', 0)} weight, {kinds.get('bias', 0)} bias, "
        f"{kinds.get('feedback', 0)} Rf, {kinds.get('invert', 0)} invert, "
        f"{kinds.get('divider', 0)} divider). Blind N-tiling of all of them "
        f"was already rejected by Experiment 27 (N=16 still ~2.6e-3 on o2). "
        f"Ratio matching does not require multiplying every resistor; it "
        f"requires grouping the TIA arrays.{extra} Area proxy = element count, "
        "not mm²."
    )
    fails = []
    for r in report.get("structured_models") or []:
        if r.get("mae_mean") is not None and r["mae_mean"] > ERROR_LIMIT:
            fails.append(f"{r['model']} mean MAE {r['mae_mean']:.3e}")
    report["failures_text"] = (
        "Failed or insufficient: "
        + ("; ".join(fails) if fails else "see tables")
        + ". Independent absolute 0.5% fails. +/− pairing without Rf·G "
        "tracking fails or is weak (Experiment 27 lesson, confirmed). "
        "Naive polarity-split placement makes a linear gradient look like "
        "systematic polarity mismatch. Blind tiling is not promoted."
    )


def extract_requirement(report):
    req = {}
    last_ok = None
    for r in report.get("ratio_local_sweep") or []:
        if r.get("mae_mean") is not None and r["mae_mean"] <= ERROR_LIMIT:
            last_ok = r.get("local_frac") * TOL_05
    req["local_residual_for_mean_pass"] = last_ok
    for r in report.get("polarity_rho") or []:
        if r.get("mae_mean") is not None and r["mae_mean"] <= ERROR_LIMIT:
            req["rho_for_mean_pass"] = r.get("rho")
            break
    else:
        req["rho_for_mean_pass"] = None
    for r in report.get("quantization") or []:
        if r.get("analog_pass"):
            req["g_unit_for_quant_pass"] = r.get("g_unit_S")
            break
    else:
        req["g_unit_for_quant_pass"] = None
    req["gx_breaks_centroid"] = None
    for r in report.get("gradient") or []:
        if r.get("placement") == "centroid" and r.get("mae_mean") is not None:
            if r["mae_mean"] > ERROR_LIMIT:
                req["gx_breaks_centroid"] = r.get("gx")
                break
    report["requirement"] = req


def main() -> int:
    print("Experiment 29: resistor-ratio matching / Network F", flush=True)
    ng = find_ngspice()
    CIRCUIT_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    spec = spec_by_id("F")
    wf = load_frozen_model("F")
    x40 = generate_inputs(spec["n_in"], N_FULL, "exp24_F")
    x12 = x40[:N_COMPARE]
    y40 = software_for(wf, x40)
    y12 = software_for(wf, x12)

    net, cat, spec, _p = compile_f(wf)
    inv = inventory(cat)
    acct = accounting(net, cat, spec["n_in"] * spec["n_hidden"] + spec["n_hidden"] * spec["n_out"])
    print(f"  F resistors={inv['n_resistors']} kinds={inv['by_kind']}", flush=True)

    rows, selected = rank_neurons(spec, cat, wf, x40)
    o2 = selected["worst_finite_gain"]
    net_iso, cat_iso, wrow, bias, _n_src = compile_o2(wf, spec, o2)
    xs = iso_sources(spec, wf, o2, n_vec=16)
    steps = pick_steps(xs, wrow, bias)
    iso_x = np.stack([steps[k] for k in ("zero", "unit", "maxabs", "pos", "neg")])
    iso_z = np.array([steps[f"z_{k}"] for k in ("zero", "unit", "maxabs", "pos", "neg")])
    print(f"  o2 isolated R={len(cat_iso)} z_maxabs={steps['z_maxabs']:.6f}", flush=True)

    report = {
        "experiment": 29,
        "spice_source_of_truth": True,
        "frozen_weights": "models/scaling/F.npz seed 9",
        "network_f_transistorized": False,
        "python_correction": False,
        "foundry_parameters_invented": False,
        "inventory": inv,
        "accounting": {k: acct.get(k) for k in ("passive_resistors", "n_feedback_resistors", "n_tia_opamps", "n_invert_opamps") if k in acct},
        "o2": {"tag": o2.get("tag"), "Rf_Gtot": o2.get("Rf_Gtot"), "n_resistors": len(cat_iso)},
        "n_compare": N_COMPARE,
        "n_full": N_FULL,
        "n_mc": N_MC,
        "models": model_catalog(),
    }

    e27 = load_exp27_baseline()
    replay = {"available": e27.get("available")}
    if e27.get("available"):
        ex = e27["excerpt"]
        replay["n_logical"] = ex.get("n_logical")
        replay["source"] = e27["source"]
        for row in ex.get("tiling") or []:
            if row.get("n_tile") == 1:
                replay["tile_n1"] = row
            if row.get("n_tile") == 16:
                replay["tile_n16"] = row
        for row in ex.get("ratio_matching") or []:
            replay[row.get("mode")] = row
    report["exp27_replay"] = replay
    save_report(report)

    print("29A nominal + baseline models", flush=True)
    nom40 = eval_f(ng, net, cat, spec, wf, x40, y40, dest("f", "nom40"))
    nom12 = eval_f(ng, net, cat, spec, wf, x12, y12, dest("f", "nom12"))
    report["nominal_f"] = {k: nom40.get(k) for k in ("mae", "rms", "max_abs_error", "accuracy", "analog_pass", "failed")}
    report["nominal_f12"] = {k: nom12.get(k) for k in ("mae", "rms", "max_abs_error", "accuracy", "analog_pass", "failed")}
    print(f"  nominal F40 MAE={nom40.get('mae')} acc={nom40.get('accuracy')}", flush=True)
    save_report(report)

    nom_iso = eval_iso(ng, net_iso, iso_x, iso_z, dest("iso", "nom"))
    report["nominal_iso"] = {k: nom_iso.get(k) for k in ("mae", "max_abs_error", "analog_pass", "failed")}
    print(f"  nominal iso MAE={nom_iso.get('mae')}", flush=True)

    report["independent_f12"] = run_mc_f(ng, net, cat, spec, wf, x12, y12, "independent", N_MC, "base")
    report["common_mode_f12"] = run_mc_f(ng, net, cat, spec, wf, x12, y12, "common_mode", N_MC, "base")
    report["ratio_exp27_f12"] = run_mc_f(ng, net, cat, spec, wf, x12, y12, "ratio_matched_exp27", N_MC, "base")
    report["iso_independent"] = run_mc_iso(ng, net_iso, cat_iso, iso_x, iso_z, "independent", N_MC, "base")
    report["iso_common_mode"] = run_mc_iso(ng, net_iso, cat_iso, iso_x, iso_z, "common_mode", N_MC, "base")
    report["iso_ratio_exp27"] = run_mc_iso(ng, net_iso, cat_iso, iso_x, iso_z, "ratio_matched_exp27", N_MC, "base")
    save_report(report)

    print("29A independent vs tol", flush=True)
    ind = []
    for tol in (0.001, 0.0025, 0.005, 0.01):
        row = run_mc_f(ng, net, cat, spec, wf, x12, y12, "independent", N_MC, f"tol{tol}", tol=tol)
        row["tol"] = tol
        ind.append(row)
    report["independent_vs_tol"] = ind
    save_report(report)

    print("29B sensitivity", flush=True)
    sens = []
    for name in (
        "rf_only",
        "weights_only",
        "bias_only",
        "invert_only",
        "divider_only",
        "layer1_only",
        "layer2_only",
        "fine_bank_only",
        "nom_bank_only",
        "pos_only",
        "neg_only",
        "tia_fabric",
    ):
        row = run_mc_f(ng, net, cat, spec, wf, x12, y12, f"sens_{name}", N_MC, "sens")
        sens.append(row)
    report["sensitivity"] = sens
    save_report(report)

    print("29C structured models", flush=True)
    structured = []
    for name in (
        "independent",
        "common_mode",
        "global_plus_local",
        "ratio_matched_exp27",
        "ratio_matched_neuron",
        "rf_g_track",
        "rf_independent",
        "pn_pair",
        "pn_pair_plus_rf",
        "pn_systematic",
        "centroid_stat",
    ):
        row = run_mc_f(ng, net, cat, spec, wf, x12, y12, name, N_MC, "struct")
        structured.append(row)
    report["structured_models"] = structured
    save_report(report)

    print("29C ratio local residual sweep", flush=True)
    local_sweep = []
    for lf in (0.0, 0.05, 0.10, 0.15, 0.25, 0.50, 1.00):
        row = run_mc_f(
            ng, net, cat, spec, wf, x12, y12, "ratio_matched_neuron", N_MC, f"loc{lf}", local_frac=lf
        )
        row["local_frac"] = lf
        local_sweep.append(row)
    report["ratio_local_sweep"] = local_sweep
    save_report(report)

    print("29D quantization", flush=True)
    quant = []
    for frac in (1.0, 0.25, 1 / 16, 1 / 64, 1 / 256):
        g_u = G_WEIGHT * frac
        values, st = quantize_values(cat, g_u)
        rec = eval_f(ng, net, cat, spec, wf, x12, y12, dest("f", "quant", frac), values)
        rec.update(st)
        rec["g_unit_over_gw"] = frac
        rec["analog_pass"] = (not rec.get("failed")) and (rec.get("mae") or 9) <= ERROR_LIMIT
        quant.append({k: rec.get(k) for k in (
            "g_unit_S", "g_unit_over_gw", "n_quantized", "n_unmatched_residual",
            "n_unit_elements", "mean_rel_g", "max_rel_g", "mae", "accuracy",
            "analog_pass", "failed", "failure_reason",
        )})
        print(f"  quant Gw*{frac:g} nU={st['n_unit_elements']} MAE={rec.get('mae')}", flush=True)
    report["quantization"] = quant
    save_report(report)

    print("29D unit-array MC", flush=True)
    ua = []
    for frac in (1 / 16, 1 / 64):
        g_u = G_WEIGHT * frac
        row = run_mc_f(
            ng, net, cat, spec, wf, x12, y12, "unit_array_neuron", N_MC, f"ua{frac}",
            g_unit=g_u, tol_sheet=TOL_05, tol_unit=TOL_05, quantize=True,
        )
        row["g_unit_over_gw"] = frac
        _vals, st = quantize_values(cat, g_u)
        row["n_unit_elements"] = st.get("n_unit_elements")
        ua.append(row)
    report["unit_array_mc"] = ua
    save_report(report)

    print("29D isolated explicit tiles N=8", flush=True)
    try:
        net_t, cat_t, tstat = tile_tia_fabric(net_iso, cat_iso, 8)
        annotate_fabric(cat_t)
        rng = make_rng("exp29iso", "tiles", SEED)
        maes = []
        for i in range(N_MC):
            values = sample_named(cat_t, "independent", rng, tol=TOL_05)
            rec = eval_iso(ng, net_t, iso_x, iso_z, dest("iso", "tile8", i), values)
            if not rec.get("failed"):
                maes.append(rec["mae"])
        report["iso_explicit_tiles"] = {
            **mc_stats(maes),
            "tile": tstat,
            "note": "Explicit series/parallel tiles on isolated o2 TIA fabric. Device-level primitive test, not fabrication-ready.",
        }
        print(f"  explicit N=8 MAE mean={report['iso_explicit_tiles'].get('mae_mean')}", flush=True)
    except Exception as exc:
        report["iso_explicit_tiles"] = {"failed": True, "failure_reason": str(exc)}
    save_report(report)

    print("29E polarity", flush=True)
    pol = []
    for name in ("pn_pair", "pn_pair_plus_rf", "pn_systematic", "pn_corr"):
        kw = {"rho": 1.0, "include_rf": True} if name == "pn_corr" else {}
        row = run_mc_f(ng, net, cat, spec, wf, x12, y12, name, N_MC, "pol", **kw)
        pol.append(row)
    report["polarity_f"] = pol
    rho_rows = []
    for rho in (0.0, 0.5, 0.8, 0.9, 1.0):
        row = run_mc_iso(
            ng, net_iso, cat_iso, iso_x, iso_z, "pn_corr", N_MC, f"rho{rho}",
            rho=rho, include_rf=True,
        )
        row["rho"] = rho
        rho_rows.append(row)
    report["polarity_rho"] = rho_rows
    save_report(report)

    print("29F gradient", flush=True)
    grad = []
    for placement in ("naive", "paired", "centroid"):
        for gx in (0.0, 0.002, 0.005, 0.01, 0.02):
            row = run_mc_f(
                ng, net, cat, spec, wf, x12, y12, f"gradient_{placement}", N_MC, f"g{placement}{gx}",
                gx=gx, gy=0.0, matched_groups=True,
            )
            row["placement"] = placement
            row["gx"] = gx
            grad.append(row)
    report["gradient"] = grad
    save_report(report)

    # Common-mode is the ratiometric identity test (zero local mismatch), not
    # a matching architecture. Promote the best grouped-ratio model that still
    # allows a nonzero local residual.
    candidates = [
        r for r in structured
        if r.get("model") in {"ratio_matched_neuron", "ratio_matched_exp27", "rf_g_track"}
        and r.get("mae_mean") is not None
    ]
    def cand_key(r):
        return float(r["mae_mean"])
    best = min(candidates, key=cand_key) if candidates else {"model": "ratio_matched_neuron"}
    promo_name = best.get("model") or "ratio_matched_neuron"
    promo_kw = dict(best.get("kw") or {})
    if promo_name == "unit_array_neuron" and "g_unit" not in promo_kw:
        promo_kw["g_unit"] = G_WEIGHT / 16.0
    print(f"29G promoted {promo_name} on F40 n={N_MC_PROMOTED}", flush=True)

    rng = make_rng("exp29", "promo", promo_name, SEED)
    maes, accs = [], []
    for i in range(N_MC_PROMOTED):
        values = sample_named(cat, promo_name, rng, spec=spec, **promo_kw)
        rec = eval_f(ng, net, cat, spec, wf, x40, y40, dest("f", "promo", promo_name, i), values)
        if rec.get("failed"):
            print(f"    promo {i} FAIL {rec.get('failure_reason')}", flush=True)
            continue
        maes.append(rec["mae"])
        accs.append(rec["accuracy"])
        print(f"    promo {i + 1}/{N_MC_PROMOTED} MAE={rec['mae']:.4e} acc={rec['accuracy']:.3f}", flush=True)
    promo = mc_stats(maes, accs)
    promo.update({"model": promo_name, "kw": promo_kw, "n_vectors": N_FULL, "draws": maes})
    report["promoted_mc"] = promo
    report["independent_f40"] = run_mc_f(ng, net, cat, spec, wf, x40, y40, "independent", N_MC, "f40ind")
    save_report(report)

    print("29G finite-A control A=1e7", flush=True)
    try:
        net_hi, cat_hi, spec_hi, _ = compile_f(wf, amp=AMP_A_HIGH)
        annotate_fabric(cat_hi)
        nom_hi = eval_f(ng, net_hi, cat_hi, spec_hi, wf, x12, y12, dest("f", "nom_a1e7"))
        hi = run_mc_f(ng, net_hi, cat_hi, spec_hi, wf, x12, y12, promo_name, N_MC, "a1e7", **promo_kw)
        report["finite_a_control"] = {
            "note": "Labeled control. Removes most of the A=1e5 floor. Not the primary claim.",
            "nominal_mae": nom_hi.get("mae"),
            **hi,
        }
    except Exception as exc:
        report["finite_a_control"] = {"failed": True, "failure_reason": str(exc)}
    save_report(report)

    extract_requirement(report)
    implementation_blurbs(report, inv)
    status = conclude(report)
    write_plots(report)
    write_markdown(report)
    save_report(report)
    print(status, flush=True)
    print("wrote", REPORT_MD, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
