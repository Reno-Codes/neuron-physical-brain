"""Experiment 14: ratiometric weight fabric and variation models.

Frozen Experiment 9 networks A and F. Weights are never edited.
Inference outputs are never corrected in Python. SPICE is the source of truth.

This is a behavioral variation study. It does not claim that 5% commercial
resistors behave like silicon mismatch, and it is not a PCB or foundry model.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from benchmark_scaling import (
    N_ROBUST_INPUTS,
    N_ROBUST_TRIALS,
    N_TEST,
    classification_labels,
    error_stats,
    generate_inputs,
    make_rng,
    simulate_batch,
)
from compile_xor import PROJECT_ROOT, find_ngspice
from hardware_constrained_compiler import current_cost_estimate, load_frozen_model
from precision_architectures import software_reference
from ratiometric_compiler import (
    CIRCUIT_DIR,
    VariationSpec,
    accounting,
    annotate_catalog,
    compile_ratiometric,
    fabric_public,
    sample_variation,
)
from test_hardware_constraints import measure_source_current, spec_by_id
from test_layer_calibration import run_calibration_suite
from test_nonideal_network import class_margins


RESULTS_DIR = PROJECT_ROOT / "results"
REPORT_PATH = RESULTS_DIR / "ratiometric_report.json"
ERROR_LIMIT = 1.0e-3
ERROR_LIMIT_COARSE = 1.0e-2
INPUT_NOISE = 0.001
TIMEOUT = 20.0
N_F_SWEEP = 40
N_CORR = 20
N_MISMATCH = 15
TEST_IDS = ("A", "F")
ARCH_MAIN = ("C", "D")
MISMATCH_PCTS = (0.0, 0.1, 0.5, 1.0, 2.0, 5.0)
IND_PCTS = (1.0, 5.0, 10.0)
GLOBAL_FIXED = (-0.10, -0.05, 0.01, 0.05, 0.10)


def dest_path(*parts: str) -> Path:
    name = "_".join(p.replace("%", "pct").replace("+", "p").replace("-", "m") for p in parts)
    return CIRCUIT_DIR / f"{name}.cir"


def strip_heavy(record: dict) -> dict:
    return {k: v for k, v in record.items() if k not in {"catalog", "netlist"}}


def n_eval(net_id: str, kind: str) -> int:
    if kind == "full":
        return N_TEST
    if kind == "sweep":
        return N_TEST if net_id == "A" else N_F_SWEEP
    return N_ROBUST_INPUTS


def evaluate_nominal(
    ngspice: Path,
    arch: str,
    spec: dict,
    weights: dict[str, np.ndarray],
    inputs: np.ndarray,
    dest: Path,
    measure_i: bool = False,
    **compile_kw,
) -> dict:
    software = software_reference(
        inputs, weights["W1"], weights["b1"], weights["W2"], weights["b2"]
    )
    netlist, catalog, reason = compile_ratiometric(arch, spec, weights, **compile_kw)
    record = {
        "arch": arch,
        "network": spec["id"],
        "failed": False,
        "failure_reason": None,
        **fabric_public(arch),
    }
    if reason or netlist is None:
        record["failed"] = True
        record["failure_reason"] = reason
        return record
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(netlist, encoding="utf-8")
    n_w = spec["n_in"] * spec["n_hidden"] + spec["n_hidden"] * spec["n_out"]
    record.update(accounting(netlist, catalog, n_w))
    physical, runtime, spice_err, _log = simulate_batch(
        ngspice, netlist, inputs, spec["n_out"], dest, timeout=TIMEOUT
    )
    record["spice_runtime_s"] = runtime
    if spice_err or physical is None:
        record["failed"] = True
        record["failure_reason"] = spice_err
        return record
    err = error_stats(physical, software)
    pred = classification_labels(physical)
    expected = classification_labels(software)
    n_fail = int(np.sum(pred != expected))
    margins = class_margins(physical, software)
    record.update(
        {
            "mae": err["mae"],
            "rms": err["rms"],
            "max_abs_error": err["max_abs_error"],
            "accuracy": float(1.0 - n_fail / max(len(expected), 1)),
            "min_margin": float(np.min(margins)),
            "n_class_failures": n_fail,
            "classification_ok": n_fail == 0,
            "netlist": netlist,
            "catalog": catalog,
        }
    )
    if measure_i:
        source_i = measure_source_current(
            ngspice, netlist, inputs[0], dest.with_name(dest.stem + "_i.cir")
        )
        record["current_cost"] = current_cost_estimate(catalog, source_i)
        record["spice_source_current_A"] = source_i
    return record


def run_trials(
    ngspice: Path,
    arch: str,
    spec: dict,
    weights: dict[str, np.ndarray],
    inputs: np.ndarray,
    software: np.ndarray,
    netlist: str,
    catalog: list[dict],
    variation: VariationSpec,
    n_trials: int,
    dest: Path,
    seed_tag: str,
    input_noise: float = 0.0,
    compile_kw: dict | None = None,
) -> dict:
    if compile_kw:
        netlist2, catalog2, reason = compile_ratiometric(
            arch, spec, weights, **compile_kw
        )
        if reason or netlist2 is None:
            return {"failed": True, "failure_reason": reason, "n_trials": n_trials}
        netlist, catalog = netlist2, annotate_catalog(catalog2)
    rng = make_rng("exp14", spec["id"], arch, seed_tag, variation.kind, variation.percent)
    maes, rms, mx, accs, margins = [], [], [], [], []
    failures = 0
    expected = classification_labels(software)
    for trial in range(n_trials):
        values = sample_variation(catalog, variation, rng)
        noisy = inputs
        if input_noise:
            noisy = inputs + rng.normal(0.0, input_noise, size=inputs.shape)
        physical, _rt, spice_err, _log = simulate_batch(
            ngspice, netlist, noisy, spec["n_out"], dest,
            r_values=values, timeout=TIMEOUT,
        )
        if spice_err or physical is None:
            failures += 1
            continue
        stats = error_stats(physical, software)
        pred = classification_labels(physical)
        maes.append(stats["mae"])
        rms.append(stats["rms"])
        mx.append(stats["max_abs_error"])
        accs.append(float(np.mean(pred == expected)))
        margins.append(float(np.min(class_margins(physical, software))))
        if trial == 0 or (trial + 1) % 25 == 0:
            print(
                f"      {arch} {seed_tag} {trial + 1}/{n_trials} "
                f"MAE={stats['mae']:.4e}",
                flush=True,
            )
    if not maes:
        return {
            "failed": True,
            "n_spice_failures": failures,
            "n_trials": n_trials,
            "variation": variation.label(),
        }
    return {
        "failed": False,
        "variation": variation.label(),
        "kind": variation.kind,
        "percent": variation.percent,
        "local_percent": variation.local_percent,
        "fixed_delta": variation.fixed_delta,
        "n_trials": n_trials,
        "n_ok": len(maes),
        "n_spice_failures": failures,
        "n_inputs": int(len(inputs)),
        "mae_mean": float(np.mean(maes)),
        "mae_std": float(np.std(maes)),
        "mae_max": float(np.max(maes)),
        "rms_mean": float(np.mean(rms)),
        "max_abs_error_mean": float(np.mean(mx)),
        "max_abs_error_max": float(np.max(mx)),
        "accuracy_mean": float(np.mean(accs)),
        "accuracy_min": float(np.min(accs)),
        "min_margin_mean": float(np.mean(margins)),
        "min_margin_min": float(np.min(margins)),
        "exceeds_1e-3": float(np.mean(maes)) > ERROR_LIMIT,
        "exceeds_1e-2": float(np.mean(maes)) > ERROR_LIMIT_COARSE,
    }


def sample_structured(catalog: list[dict], rng: np.random.Generator) -> dict[str, float]:
    """Realistic structured draw. Documented random variables:

    d_g ~ U(-0.05, 0.05)          global process
    d_L[layer] ~ U(-0.02, 0.02)   layer-correlated
    e_i ~ U(-0.01, 0.01)          local mismatch
    R = Rnom * (1 + d_g + d_L + e_i)
    """
    d_g = float(rng.uniform(-0.05, 0.05))
    layers = {int(item.get("layer", 1)) for item in catalog}
    d_l = {L: float(rng.uniform(-0.02, 0.02)) for L in layers}
    values = {}
    for item in catalog:
        local = float(rng.uniform(-0.01, 0.01))
        delta = d_g + d_l[int(item.get("layer", 1))] + local
        values[str(item["name"])] = float(item["R"]) * max(0.1, 1.0 + delta)
    return values


def run_structured_mc(
    ngspice: Path,
    arch: str,
    spec: dict,
    weights: dict[str, np.ndarray],
    inputs: np.ndarray,
    software: np.ndarray,
    dest: Path,
    n_trials: int,
) -> dict:
    netlist, catalog, reason = compile_ratiometric(
        arch, spec, weights, scale_error=0.001, i_leak=1e-8
    )
    if reason or netlist is None:
        return {"failed": True, "failure_reason": reason}
    catalog = annotate_catalog(catalog)
    rng = make_rng("exp14real", spec["id"], arch)
    expected = classification_labels(software)
    maes, accs, margins = [], [], []
    failures = 0
    for trial in range(n_trials):
        values = sample_structured(catalog, rng)
        noisy = inputs + rng.normal(0.0, INPUT_NOISE, size=inputs.shape)
        physical, _rt, spice_err, _log = simulate_batch(
            ngspice, netlist, noisy, spec["n_out"], dest,
            r_values=values, timeout=TIMEOUT,
        )
        if spice_err or physical is None:
            failures += 1
            continue
        stats = error_stats(physical, software)
        pred = classification_labels(physical)
        maes.append(stats["mae"])
        accs.append(float(np.mean(pred == expected)))
        margins.append(float(np.min(class_margins(physical, software))))
        if trial == 0 or (trial + 1) % 25 == 0:
            print(
                f"      structured {arch} {spec['id']} {trial + 1}/{n_trials} "
                f"MAE={stats['mae']:.4e}",
                flush=True,
            )
    if not maes:
        return {"failed": True, "n_spice_failures": failures, "n_trials": n_trials}
    return {
        "failed": False,
        "n_trials": n_trials,
        "n_ok": len(maes),
        "n_spice_failures": failures,
        "conditions": {
            "global": "U(-5%, +5%)",
            "layer": "U(-2%, +2%)",
            "local_mismatch": "U(-1%, +1%)",
            "scale_error": 0.001,
            "i_leak": 1e-8,
            "input_noise": INPUT_NOISE,
            "note": (
                "Structured process + mismatch. Not independent 5% on every R. "
                "Not a foundry PCM model."
            ),
        },
        "mae_mean": float(np.mean(maes)),
        "mae_max": float(np.max(maes)),
        "accuracy_mean": float(np.mean(accs)),
        "accuracy_min": float(np.min(accs)),
        "min_margin_min": float(np.min(margins)),
    }


def first_crossing(rows: list[dict], key: str, limit: float) -> dict | None:
    for rec in rows:
        mae = rec.get("mae_mean")
        if mae is None or rec.get("failed"):
            continue
        if mae > limit:
            return {
                "percent": rec.get("percent"),
                "mae_mean": mae,
                "accuracy_mean": rec.get("accuracy_mean"),
            }
    return None


def evaluate_network(ngspice: Path, spec: dict) -> dict:
    weights = load_frozen_model(spec["id"])
    x_all = generate_inputs(spec["n_in"], n_eval(spec["id"], "full"), spec["id"])
    x_sw = x_all[: n_eval(spec["id"], "sweep")]
    x_mc = x_all[:N_ROBUST_INPUTS]
    y_all = software_reference(
        x_all, weights["W1"], weights["b1"], weights["W2"], weights["b2"]
    )
    y_sw = software_reference(
        x_sw, weights["W1"], weights["b1"], weights["W2"], weights["b2"]
    )
    y_mc = software_reference(
        x_mc, weights["W1"], weights["b1"], weights["W2"], weights["b2"]
    )
    print(
        f"\n=== Network {spec['id']} {spec['n_in']}->{spec['n_hidden']}->"
        f"{spec['n_out']} full={len(x_all)} sweep={len(x_sw)} mc={len(x_mc)} ===",
        flush=True,
    )

    arches: dict[str, dict] = {}
    for arch in ("C", "D", "B"):
        print(f"  nominal {arch}", flush=True)
        rec = evaluate_nominal(
            ngspice, arch, spec, weights, x_all,
            dest_path(spec["id"], arch, "nominal"),
            measure_i=True,
        )
        print(
            f"    MAE={rec.get('mae')} acc={rec.get('accuracy')} "
            f"R=[{rec.get('r_min')}, {rec.get('r_max')}] "
            f"nR={rec.get('passive_resistors')} "
            f"fail={rec.get('failure_reason')}",
            flush=True,
        )
        arches[arch] = {
            "nominal": strip_heavy(rec),
            "netlist": rec.get("netlist"),
            "catalog": rec.get("catalog"),
        }

    for arch in ARCH_MAIN:
        netlist = arches[arch]["netlist"]
        catalog = arches[arch]["catalog"]
        if not netlist or not catalog:
            continue

        print(f"  independent sweep {arch}", flush=True)
        ind_rows = []
        for pct in IND_PCTS:
            var = VariationSpec(f"ind{pct}", "independent", pct)
            row = run_trials(
                ngspice, arch, spec, weights, x_mc, y_mc, netlist, catalog,
                var, N_CORR, dest_path(spec["id"], arch, f"ind_{pct:g}"),
                f"ind{pct:g}",
            )
            print(f"    +/-{pct:g}% MAE_mean={row.get('mae_mean')} acc={row.get('accuracy_mean')}", flush=True)
            ind_rows.append(row)
        arches[arch]["independent"] = ind_rows

        print(f"  global fixed shifts {arch}", flush=True)
        glob_rows = []
        for delta in GLOBAL_FIXED:
            var = VariationSpec(f"g{delta}", "global", abs(delta) * 100.0, fixed_delta=delta)
            row = run_trials(
                ngspice, arch, spec, weights, x_sw, y_sw, netlist, catalog,
                var, 1, dest_path(spec["id"], arch, f"gfix_{delta:+.4g}"),
                f"gfix{delta:+.4g}",
            )
            print(
                f"    {delta:+.0%} MAE={row.get('mae_mean')} acc={row.get('accuracy_mean')}",
                flush=True,
            )
            glob_rows.append(row)
        arches[arch]["global_fixed"] = glob_rows

        print(f"  correlation study 5% {arch}", flush=True)
        corr = {}
        for kind, local in (
            ("independent", 0.0),
            ("global", 0.0),
            ("layer", 0.5),
            ("matched", 0.5),
        ):
            var = VariationSpec(f"corr_{kind}", kind, 5.0, local_percent=local)
            row = run_trials(
                ngspice, arch, spec, weights, x_mc, y_mc, netlist, catalog,
                var, N_CORR, dest_path(spec["id"], arch, f"corr_{kind}"),
                f"corr_{kind}",
            )
            print(
                f"    {kind} MAE_mean={row.get('mae_mean')} acc={row.get('accuracy_mean')}",
                flush=True,
            )
            corr[kind] = row
        arches[arch]["correlation_5pct"] = corr

        print(f"  layer-correlated local-mismatch sizes {arch}", flush=True)
        layer_local = []
        for local, tag in ((0.1, "small"), (1.0, "moderate"), (5.0, "large")):
            var = VariationSpec(f"ly_{tag}", "layer", 5.0, local_percent=local)
            row = run_trials(
                ngspice, arch, spec, weights, x_mc, y_mc, netlist, catalog,
                var, N_MISMATCH, dest_path(spec["id"], arch, f"ly_{tag}"),
                f"ly_{tag}",
            )
            row["local_label"] = tag
            print(f"    {tag} local {local:g}% MAE={row.get('mae_mean')}", flush=True)
            layer_local.append(row)
        arches[arch]["layer_local_sizes"] = layer_local

        print(f"  local mismatch sweep {arch}", flush=True)
        mm_rows = []
        for pct in MISMATCH_PCTS:
            var = VariationSpec(f"mm{pct}", "independent", pct)
            row = run_trials(
                ngspice, arch, spec, weights, x_mc, y_mc, netlist, catalog,
                var, N_MISMATCH, dest_path(spec["id"], arch, f"mm_{pct:g}"),
                f"mm{pct:g}",
            )
            print(f"    local {pct:g}% MAE={row.get('mae_mean')} acc={row.get('accuracy_mean')}", flush=True)
            mm_rows.append(row)
        arches[arch]["mismatch_sweep"] = mm_rows
        arches[arch]["first_mae_1e-3"] = first_crossing(mm_rows, "mae_mean", ERROR_LIMIT)
        arches[arch]["first_mae_1e-2"] = first_crossing(mm_rows, "mae_mean", ERROR_LIMIT_COARSE)
        arches[arch]["first_class_drop"] = next(
            (
                {
                    "percent": r.get("percent"),
                    "accuracy_mean": r.get("accuracy_mean"),
                    "accuracy_min": r.get("accuracy_min"),
                }
                for r in mm_rows
                if (r.get("accuracy_mean") is not None and r["accuracy_mean"] < 0.999)
            ),
            None,
        )

    return {
        "id": spec["id"],
        "label": f"{spec['id']} {spec['n_in']}->{spec['n_hidden']}->{spec['n_out']}",
        "n_full": int(len(x_all)),
        "n_sweep": int(len(x_sw)),
        "n_mc": int(len(x_mc)),
        "architectures": arches,
        "spec": spec,
        "weights": weights,
        "x_mc": x_mc,
        "y_mc": y_mc,
        "x_cal": x_sw,
    }


def pick_best(rows: list[dict]) -> str:
    f = next(r for r in rows if r["id"] == "F")
    scores = {}
    for arch in ARCH_MAIN:
        glob = None
        for rec in f["architectures"][arch].get("global_fixed") or []:
            if rec.get("fixed_delta") == 0.05:
                glob = rec.get("mae_mean")
        matched = (f["architectures"][arch].get("correlation_5pct") or {}).get(
            "matched", {}
        ).get("mae_mean")
        scores[arch] = glob if glob is not None else (matched if matched is not None else 1e9)
    return min(ARCH_MAIN, key=lambda a: scores[a] if scores[a] is not None else 1e9)


def make_plots(rows: list[dict], cal: dict, best: str) -> dict[str, str]:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    colors = {"C": "#1f4e79", "D": "#2e7d4f", "B": "#c47b17", "E": "#8c2d4a"}
    kinds = ("independent", "global", "layer", "matched")

    fig, axes = plt.subplots(1, 2, figsize=(8.8, 4.2))
    for ax, net_id in zip(axes, ("A", "F")):
        row = next(r for r in rows if r["id"] == net_id)
        x = np.arange(len(kinds))
        w = 0.35
        for i, arch in enumerate(ARCH_MAIN):
            ys = []
            for k in kinds:
                rec = (row["architectures"][arch].get("correlation_5pct") or {}).get(k, {})
                ys.append(rec.get("mae_mean") or np.nan)
            ax.bar(x + (i - 0.5) * w, ys, w, label=arch, color=colors[arch])
        ax.axhline(ERROR_LIMIT, color="#333", linestyle="--", linewidth=1)
        ax.set_yscale("log")
        ax.set_xticks(x, list(kinds), rotation=20, ha="right")
        ax.set_ylabel("MAE mean")
        ax.set_title(f"Network {net_id}  5% models")
        ax.legend()
        ax.grid(True, axis="y", alpha=0.3)
    fig.suptitle("Variation models (behavioral)")
    fig.tight_layout()
    p1 = RESULTS_DIR / "ratiometric_variation_models.png"
    fig.savefig(p1, dpi=140)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(7.6, 4.4))
    for row in rows:
        for arch in ARCH_MAIN:
            recs = row["architectures"][arch].get("global_fixed") or []
            xs = [100.0 * (r.get("fixed_delta") or 0.0) for r in recs]
            ys = [r.get("mae_mean") if not r.get("failed") else np.nan for r in recs]
            ax.plot(
                xs, ys, "o-",
                color=colors[arch],
                linestyle="-" if row["id"] == "A" else "--",
                label=f"{row['id']}-{arch}",
                linewidth=2,
            )
    ax.axhline(ERROR_LIMIT, color="#a33", linestyle=":", label="MAE=1e-3")
    ax.set_yscale("log")
    ax.set_xlabel("global resistor shift (%)")
    ax.set_ylabel("MAE")
    ax.set_title("Global shift cancellation")
    ax.legend(fontsize=8, ncol=2)
    ax.grid(True, which="both", alpha=0.3)
    fig.tight_layout()
    p2 = RESULTS_DIR / "ratiometric_global_cancellation.png"
    fig.savefig(p2, dpi=140)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(7.6, 4.4))
    for row in rows:
        for arch in ARCH_MAIN:
            recs = row["architectures"][arch].get("mismatch_sweep") or []
            xs, ys = [], []
            for r in recs:
                if r.get("failed") or r.get("mae_mean") is None:
                    continue
                xs.append(max(float(r["percent"]), 1e-3))
                ys.append(r["mae_mean"])
            if xs:
                ax.plot(
                    xs, ys, "o-",
                    color=colors[arch],
                    linestyle="-" if row["id"] == "A" else "--",
                    label=f"{row['id']}-{arch}",
                    linewidth=2,
                )
    ax.axhline(ERROR_LIMIT, color="#a33", linestyle=":")
    ax.axhline(ERROR_LIMIT_COARSE, color="#a33", linestyle="--")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("independent local mismatch (%)")
    ax.set_ylabel("MAE mean")
    ax.set_title("Local mismatch sweep")
    ax.legend(fontsize=8, ncol=2)
    ax.grid(True, which="both", alpha=0.3)
    fig.tight_layout()
    p3 = RESULTS_DIR / "ratiometric_mismatch_sweep.png"
    fig.savefig(p3, dpi=140)
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(8.8, 4.2))
    conds = ["nominal", "global_fixed_p5", "global_fixed_p10", "layer_5_local_0p5", "independent_5"]
    modes = ("none", "global", "layer")
    mw = 0.25
    for ax, net_id in zip(axes, ("A", "F")):
        x = np.arange(len(conds))
        for i, mode in enumerate(modes):
            ys = []
            for c in conds:
                rec = ((cal.get(net_id) or {}).get(c) or {}).get(mode) or {}
                ys.append(rec.get("mae_mean") if rec.get("mae_mean") is not None else np.nan)
            ax.bar(x + (i - 1) * mw, ys, mw, label=mode)
        ax.set_yscale("log")
        ax.set_xticks(x, conds, rotation=25, ha="right", fontsize=7)
        ax.set_title(f"Network {net_id} calibration")
        ax.axhline(ERROR_LIMIT, color="#333", linestyle="--", linewidth=1)
        ax.legend(fontsize=8)
        ax.grid(True, axis="y", alpha=0.3)
    fig.suptitle("Architecture E compiled calibration")
    fig.tight_layout()
    p4 = RESULTS_DIR / "ratiometric_calibration.png"
    fig.savefig(p4, dpi=140)
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(8.6, 4.2))
    labels = ["nom", "ind 5%", "global +5%", "matched 5%"]
    for ax, net_id in zip(axes, ("A", "F")):
        row = next(r for r in rows if r["id"] == net_id)
        x = np.arange(len(labels))
        w = 0.35
        for i, arch in enumerate(ARCH_MAIN):
            nom = row["architectures"][arch]["nominal"].get("mae")
            ind = None
            for r in row["architectures"][arch].get("independent") or []:
                if r.get("percent") == 5.0:
                    ind = r.get("mae_mean")
            g5 = None
            for r in row["architectures"][arch].get("global_fixed") or []:
                if r.get("fixed_delta") == 0.05:
                    g5 = r.get("mae_mean")
            mat = (row["architectures"][arch].get("correlation_5pct") or {}).get(
                "matched", {}
            ).get("mae_mean")
            ys = [nom or np.nan, ind or np.nan, g5 or np.nan, mat or np.nan]
            ax.bar(x + (i - 0.5) * w, ys, w, label=arch, color=colors[arch])
        ax.set_yscale("log")
        ax.set_xticks(x, labels)
        ax.set_title(f"Network {net_id} (best={best})")
        ax.axhline(ERROR_LIMIT, color="#333", linestyle="--", linewidth=1)
        ax.legend()
        ax.grid(True, axis="y", alpha=0.3)
    fig.suptitle("Architecture comparison")
    fig.tight_layout()
    p5 = RESULTS_DIR / "ratiometric_architecture_comparison.png"
    fig.savefig(p5, dpi=140)
    plt.close(fig)

    return {
        "variation_models": str(p1.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        "global_cancellation": str(p2.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        "mismatch": str(p3.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        "calibration": str(p4.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        "comparison": str(p5.relative_to(PROJECT_ROOT)).replace("\\", "/"),
    }


def public_network(row: dict) -> dict:
    arches = {}
    for key, block in row["architectures"].items():
        arches[key] = {k: v for k, v in block.items() if k not in {"netlist", "catalog"}}
    return {
        "id": row["id"],
        "label": row["label"],
        "n_full": row["n_full"],
        "n_sweep": row["n_sweep"],
        "n_mc": row["n_mc"],
        "architectures": arches,
    }


def fmt(value, spec=".4e") -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return format(value, spec)
    return str(value)


def _g5(block: dict) -> dict:
    for r in block.get("global_fixed") or []:
        if r.get("fixed_delta") == 0.05:
            return r
    return {}


def _ind5(block: dict) -> dict:
    for r in block.get("independent") or []:
        if r.get("percent") == 5.0:
            return r
    return {}


def _pm10(block: dict) -> tuple[dict, dict]:
    plus, minus = {}, {}
    for r in block.get("global_fixed") or []:
        if r.get("fixed_delta") == 0.10:
            plus = r
        if r.get("fixed_delta") == -0.10:
            minus = r
    return plus, minus


def analyze(rows: list[dict], cal: dict, best: str, structured: dict) -> dict:
    f = next(r for r in rows if r["id"] == "F")
    c, d = f["architectures"]["C"], f["architectures"]["D"]
    d_g5 = _g5(d).get("mae_mean")
    c_ind = _ind5(c).get("mae_mean")
    d_ind = _ind5(d).get("mae_mean")
    e_layer_g5 = (
        ((cal.get("F") or {}).get("global_fixed_p5") or {}).get("layer") or {}
    ).get("mae_mean")
    e_none_g5 = (
        ((cal.get("F") or {}).get("global_fixed_p5") or {}).get("none") or {}
    ).get("mae_mean")
    structured_mae = (structured.get("F") or {}).get("mae_mean")

    d_cancels = d_g5 is not None and d_g5 < 1e-3
    better_structured = structured_mae is not None and structured_mae < 0.014
    e_helps = (
        e_layer_g5 is not None
        and e_none_g5 is not None
        and e_layer_g5 < 0.3 * e_none_g5
    )
    if d_cancels and better_structured:
        verdict = "RATIOMETRIC ARCHITECTURE IMPROVED"
    elif e_helps and not d_cancels:
        verdict = "CALIBRATION REQUIRED"
    else:
        verdict = "RATIOMETRIC ADVANTAGE NOT OBSERVED"
    return {
        "best_architecture": best,
        "verdict": verdict,
        "exp13_independent_5pct_mae_F": 0.028,
        "C_independent_5pct_mae_F": c_ind,
        "D_independent_5pct_mae_F": d_ind,
        "D_global_plus5_mae_F": d_g5,
        "E_layer_global_plus5_mae_F": e_layer_g5,
        "structured_mae_F": structured_mae,
        "note": (
            "Independent 5% is a pessimistic discrete-resistor model. "
            "Global / layer / matched models describe correlated process "
            "plus local mismatch. They are not interchangeable."
        ),
    }


def print_final(rows: list[dict], cal: dict, structured: dict, summary: dict, plots: dict) -> None:
    a = next(r for r in rows if r["id"] == "A")
    f = next(r for r in rows if r["id"] == "F")
    print("\n==================================================")
    print("EXPERIMENT 14")
    print("RATIOMETRIC WEIGHT FABRIC")
    print("==================================================")
    for title, key in (
        ("BASELINE ARCHITECTURE C", "C"),
        ("ARCHITECTURE D RATIOMETRIC", "D"),
    ):
        print(f"\n{title}:")
        for row in (a, f):
            nom = row["architectures"][key]["nominal"]
            print(
                f"  {row['label']}: MAE={fmt(nom.get('mae'))} "
                f"max={fmt(nom.get('max_abs_error'))} "
                f"acc={fmt(nom.get('accuracy'), '.4f')} "
                f"R={fmt(nom.get('r_min'))}..{fmt(nom.get('r_max'))} "
                f"nR={nom.get('passive_resistors')} "
                f"nRef={nom.get('n_reference_resistors')} "
                f"active={nom.get('active_functional_blocks')} "
                f"H={nom.get('active_transimpedance')} "
                f"SigmaG={fmt(nom.get('total_conductance_S'))} "
                f"Istim={fmt(nom.get('spice_source_current_A'))} "
                f"t={fmt(nom.get('spice_runtime_s'), '.3f')} s"
            )
            print(f"    {nom.get('ratio_in_spice')}")

    print("\nARCHITECTURE E CALIBRATED:")
    print("  measurements: 0 (none), 1 (global, output cal cell), 2 (one per layer)")
    print("  constants compiled as VCVS gains. Trained weights unchanged.")
    for net_id in ("A", "F"):
        print(f"  Network {net_id}")
        for cond in ("nominal", "global_fixed_p5", "global_fixed_p10", "independent_5"):
            modes = (cal.get(net_id) or {}).get(cond) or {}
            bits = []
            for mode in ("none", "global", "layer"):
                rec = modes.get(mode) or {}
                bits.append(f"{mode} MAE={fmt(rec.get('mae_mean'))}")
            print(f"    {cond}: " + " | ".join(bits))

    print("\nINDEPENDENT VARIATION:")
    for row in (a, f):
        for arch in ARCH_MAIN:
            recs = row["architectures"][arch].get("independent") or []
            parts = [
                f"{r.get('percent'):g}% MAE={fmt(r.get('mae_mean'))} "
                f"acc={fmt(r.get('accuracy_mean'), '.4f')}"
                for r in recs
            ]
            print(f"  {row['id']}-{arch}: " + "; ".join(parts))

    print("\nGLOBAL CORRELATED VARIATION:")
    for row in (a, f):
        for arch in ARCH_MAIN:
            rec = _g5(row["architectures"][arch])
            print(
                f"  {row['id']}-{arch} fixed +5%: MAE={fmt(rec.get('mae_mean'))} "
                f"acc={fmt(rec.get('accuracy_mean'), '.4f')}"
            )
            rnd = (row["architectures"][arch].get("correlation_5pct") or {}).get("global", {})
            print(
                f"  {row['id']}-{arch} random U(+/-5%): MAE={fmt(rnd.get('mae_mean'))} "
                f"acc={fmt(rnd.get('accuracy_mean'), '.4f')}"
            )

    print("\nLAYER-CORRELATED VARIATION:")
    for row in (a, f):
        for arch in ARCH_MAIN:
            rec = (row["architectures"][arch].get("correlation_5pct") or {}).get("layer", {})
            print(
                f"  {row['id']}-{arch}: MAE={fmt(rec.get('mae_mean'))} "
                f"acc={fmt(rec.get('accuracy_mean'), '.4f')}"
            )

    print("\nMATCHED-PAIR VARIATION:")
    for row in (a, f):
        for arch in ARCH_MAIN:
            rec = (row["architectures"][arch].get("correlation_5pct") or {}).get("matched", {})
            print(
                f"  {row['id']}-{arch}: MAE={fmt(rec.get('mae_mean'))} "
                f"acc={fmt(rec.get('accuracy_mean'), '.4f')}"
            )

    print("\nGLOBAL SHIFT CANCELLATION:")
    for row in (a, f):
        for arch in ARCH_MAIN:
            plus, minus = _pm10(row["architectures"][arch])
            print(
                f"  {row['id']}-{arch} +10% MAE={fmt(plus.get('mae_mean'))}  "
                f"-10% MAE={fmt(minus.get('mae_mean'))}"
            )

    print("\nLOCAL MISMATCH LIMIT:")
    for row in (a, f):
        for arch in ARCH_MAIN:
            blk = row["architectures"][arch]
            print(
                f"  {row['id']}-{arch}: first MAE>1e-3={blk.get('first_mae_1e-3')}  "
                f"first MAE>1e-2={blk.get('first_mae_1e-2')}  "
                f"class drop={blk.get('first_class_drop')}"
            )

    print("\nONE CONSTANT PER LAYER RESULT:")
    for net_id in ("A", "F"):
        g5 = (cal.get(net_id) or {}).get("global_fixed_p5") or {}
        print(
            f"  {net_id} global +5%: none={fmt((g5.get('none') or {}).get('mae_mean'))} "
            f"global={fmt((g5.get('global') or {}).get('mae_mean'))} "
            f"layer={fmt((g5.get('layer') or {}).get('mae_mean'))}"
        )

    print("\nBEST REALISTIC MONTE CARLO RESULT:")
    print(f"  best architecture: {summary['best_architecture']}")
    for net_id, rec in structured.items():
        print(
            f"  {net_id}: MAE_mean={fmt(rec.get('mae_mean'))} "
            f"MAE_max={fmt(rec.get('mae_max'))} "
            f"acc_mean={fmt(rec.get('accuracy_mean'), '.4f')} "
            f"acc_min={fmt(rec.get('accuracy_min'), '.4f')}"
        )
        print(f"    conditions: {(rec or {}).get('conditions')}")

    print("\nFINAL STATUS:")
    print(summary["verdict"])
    print(summary["note"])
    print(f"\nWrote {REPORT_PATH}")
    for path in plots.values():
        print(f"Wrote {path}")


def main() -> int:
    ngspice = find_ngspice()
    CIRCUIT_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    print("Physical AI - Experiment 14")
    print("RATIOMETRIC WEIGHT FABRIC AND VARIATION MODELS")
    print("Analysis: behavioral variation study")
    print("Not transistor-level. Not PCB. Not foundry mismatch.")
    print(f"ngspice: {ngspice}")

    rows = [evaluate_network(ngspice, spec_by_id(net_id)) for net_id in TEST_IDS]
    best = pick_best(rows)
    print(f"\nBest by global +5% cancellation: {best}", flush=True)

    print("\nArchitecture E calibration suite", flush=True)
    cal_networks = {
        row["id"]: {
            "spec": row["spec"],
            "weights": row["weights"],
            "x_cal": row["x_cal"],
        }
        for row in rows
    }
    cal = run_calibration_suite(ngspice, cal_networks, n_trials_random=8)

    print("\nStructured realistic Monte Carlo", flush=True)
    structured = {}
    for row in rows:
        for arch in (best, "C") if best != "C" else ("C",):
            print(f"  {row['id']} arch {arch}", flush=True)
            rec = run_structured_mc(
                ngspice, arch, row["spec"], row["weights"],
                row["x_mc"], row["y_mc"],
                dest_path(row["id"], arch, "structured"),
                N_ROBUST_TRIALS,
            )
            key = row["id"] if arch == best else f"{row['id']}_{arch}"
            structured[key] = rec
            if arch == best:
                structured[row["id"]] = rec

    plots = make_plots(rows, cal, best)
    summary = analyze(rows, cal, best, structured)
    report = {
        "experiment": 14,
        "analysis": "behavioral variation study",
        "error_limit": ERROR_LIMIT,
        "random_variables": {
            "independent": "u_i ~ U(-p,p) per resistor",
            "global_random": "one d_g ~ U(-p,p) for all R",
            "global_fixed": "R *= (1 + delta) exactly",
            "layer": "d_L ~ U(-p,p) per layer + e_i ~ U(-p_local,p_local)",
            "matched": "d_g + d_match[group] + e_i; D shares group across R_w and R_IV",
            "structured_mc": "d_g~U(-5%,5%) + d_L~U(-2%,2%) + e_i~U(-1%,1%) + 0.1% scale + 10 nA + 1 mV",
        },
        "networks": [public_network(r) for r in rows],
        "calibration": cal,
        "structured_monte_carlo": structured,
        "plots": plots,
        "summary": summary,
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print_final(rows, cal, structured, summary, plots)
    return 0 if summary["verdict"].endswith("IMPROVED") else 1


if __name__ == "__main__":
    sys.exit(main())
