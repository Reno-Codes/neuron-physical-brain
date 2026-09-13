"""Experiment 15: local mismatch, signed-path offset, remaining active blocks.

Frozen Experiment 9 networks A and F. Architecture D from Experiment 14.
Weights are never edited. SPICE inference is never corrected in Python.

This is a behavioral mismatch study, not layout extraction or foundry data.
"""

from __future__ import annotations

import json
import math
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
from mismatch_fabric import (
    CIRCUIT_DIR,
    ActiveParams,
    compile_d,
    sample_independent,
    sample_signed_offset,
)
from precision_architectures import software_reference
from ratiometric_compiler import accounting
from test_hardware_constraints import measure_source_current, spec_by_id
from test_nonideal_network import class_margins


RESULTS_DIR = PROJECT_ROOT / "results"
REPORT_PATH = RESULTS_DIR / "mismatch_report.json"
ERROR_LIMIT = 1.0e-3
TIMEOUT = 20.0
INPUT_NOISE = 0.001
TILE_NS = (1, 2, 4)
TILE_PCTS = (0.5, 1.0)
SIGNED_PCTS = (0.0, 0.1, 0.5, 1.0, 2.0, 5.0)
CCCS_PCTS = (0.0, 0.01, 0.1, 0.5, 1.0)
BUF_PCTS = (0.0, 0.1, 0.5, 1.0)
RELU_VOS = (0.0, 1e-4, 1e-3, 1e-2)
N_F_SWEEP = 40
N_TRIALS = {"A": 20, "F": 15}


def dest(*parts: str) -> Path:
    name = "_".join(str(p).replace("%", "pct").replace(".", "p") for p in parts)
    return CIRCUIT_DIR / f"{name}.cir"


def fmt(value, spec=".4e") -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return format(value, spec)
    return str(value)


def evaluate_netlist(
    ngspice: Path,
    spec: dict,
    netlist: str,
    catalog: list[dict],
    inputs: np.ndarray,
    software: np.ndarray,
    path: Path,
    r_values: dict[str, float] | None = None,
) -> dict:
    physical, runtime, spice_err, _log = simulate_batch(
        ngspice, netlist, inputs, spec["n_out"], path,
        r_values=r_values, timeout=TIMEOUT,
    )
    rec = {"failed": False, "failure_reason": None, "spice_runtime_s": runtime}
    if spice_err or physical is None:
        rec["failed"] = True
        rec["failure_reason"] = spice_err or "no physical outputs"
        return rec
    err = error_stats(physical, software)
    pred = classification_labels(physical)
    expected = classification_labels(software)
    n_fail = int(np.sum(pred != expected))
    margins = class_margins(physical, software)
    rec.update(
        {
            "mae": err["mae"],
            "rms": err["rms"],
            "max_abs_error": err["max_abs_error"],
            "accuracy": float(1.0 - n_fail / max(len(expected), 1)),
            "n_class_failures": n_fail,
            "min_margin": float(np.min(margins)),
            "classification_ok": n_fail == 0,
            "exceeds_error_limit": err["mae"] > ERROR_LIMIT,
        }
    )
    return rec


def run_mc(
    ngspice: Path,
    spec: dict,
    netlist: str,
    catalog: list[dict],
    inputs: np.ndarray,
    software: np.ndarray,
    path: Path,
    n_trials: int,
    seed_tag: str,
    sampler,
) -> dict:
    rng = make_rng("exp15", spec["id"], seed_tag)
    maes, accs, mx, margins = [], [], [], []
    failures = 0
    expected = classification_labels(software)
    for trial in range(n_trials):
        values, extra_x = sampler(catalog, rng, trial, inputs)
        physical, _rt, spice_err, _log = simulate_batch(
            ngspice, netlist, extra_x, spec["n_out"], path,
            r_values=values, timeout=TIMEOUT,
        )
        if spice_err or physical is None:
            failures += 1
            continue
        stats = error_stats(physical, software)
        pred = classification_labels(physical)
        maes.append(stats["mae"])
        mx.append(stats["max_abs_error"])
        accs.append(float(np.mean(pred == expected)))
        margins.append(float(np.min(class_margins(physical, software))))
        if trial == 0 or (trial + 1) % 25 == 0:
            print(
                f"      {seed_tag} {trial + 1}/{n_trials} MAE={stats['mae']:.4e}",
                flush=True,
            )
    if not maes:
        return {"failed": True, "n_spice_failures": failures, "n_trials": n_trials}
    return {
        "failed": False,
        "n_trials": n_trials,
        "n_ok": len(maes),
        "n_spice_failures": failures,
        "mae_mean": float(np.mean(maes)),
        "mae_std": float(np.std(maes)),
        "mae_max": float(np.max(maes)),
        "max_abs_error_mean": float(np.mean(mx)),
        "accuracy_mean": float(np.mean(accs)),
        "accuracy_min": float(np.min(accs)),
        "min_margin_min": float(np.min(margins)),
        "exceeds_error_limit": float(np.mean(maes)) > ERROR_LIMIT,
    }


def first_over(rows: list[dict], key: str = "mae") -> dict | None:
    for rec in rows:
        mae = rec.get(key, rec.get("mae_mean"))
        if rec.get("failed") or mae is None:
            continue
        if mae > ERROR_LIMIT:
            return {
                "name": rec.get("name"),
                "value": rec.get("value"),
                "mae": mae,
                "accuracy": rec.get("accuracy", rec.get("accuracy_mean")),
            }
    return None


def evaluate_network(ngspice: Path, spec: dict) -> dict:
    weights = load_frozen_model(spec["id"])
    n_full = N_TEST
    n_sw = N_TEST if spec["id"] == "A" else N_F_SWEEP
    n_mc = N_ROBUST_INPUTS
    n_trials = N_TRIALS[spec["id"]]
    x_all = generate_inputs(spec["n_in"], n_full, spec["id"])
    x_sw, x_mc = x_all[:n_sw], x_all[:n_mc]
    y_all = software_reference(
        x_all, weights["W1"], weights["b1"], weights["W2"], weights["b2"]
    )
    y_sw = software_reference(
        x_sw, weights["W1"], weights["b1"], weights["W2"], weights["b2"]
    )
    y_mc = software_reference(
        x_mc, weights["W1"], weights["b1"], weights["W2"], weights["b2"]
    )
    n_w = spec["n_in"] * spec["n_hidden"] + spec["n_hidden"] * spec["n_out"]
    print(
        f"\n=== Network {spec['id']} {spec['n_in']}->{spec['n_hidden']}->"
        f"{spec['n_out']}  full={n_full} sweep={n_sw} mc={n_mc} ===",
        flush=True,
    )

    print("  nominal D", flush=True)
    net0, cat0, meta0 = compile_d(spec, weights, tile_n=1)
    nom = {
        "failed": True,
        "failure_reason": meta0.get("compile_reason"),
        "tile": meta0.get("tile"),
    }
    if net0 is not None:
        dest(spec["id"], "D", "nominal").write_text(net0, encoding="utf-8")
        nom = evaluate_netlist(
            ngspice, spec, net0, cat0, x_all, y_all, dest(spec["id"], "D", "nominal")
        )
        nom.update(accounting(net0, cat0, n_w))
        nom["tile"] = meta0.get("tile")
        source_i = measure_source_current(
            ngspice, net0, x_all[0], dest(spec["id"], "D", "nominal_i")
        )
        nom["current_cost"] = current_cost_estimate(cat0, source_i)
        nom["spice_source_current_A"] = source_i
    print(
        f"    MAE={nom.get('mae')} nR={nom.get('passive_resistors')} "
        f"fail={nom.get('failure_reason')}",
        flush=True,
    )

    print("  unit-resistor tiling", flush=True)
    tiling = []
    for n in TILE_NS:
        net, cat, meta = compile_d(spec, weights, tile_n=n)
        if net is None:
            tiling.append({"n": n, "failed": True, "failure_reason": meta.get("compile_reason")})
            print(f"    N={n} compile fail {meta.get('compile_reason')}", flush=True)
            continue
        dest(spec["id"], "D", f"tile{n}").write_text(net, encoding="utf-8")
        base = evaluate_netlist(
            ngspice, spec, net, cat, x_sw, y_sw, dest(spec["id"], "D", f"tile{n}_nom")
        )
        acc = accounting(net, cat, n_w)
        print(
            f"    N={n} nominal MAE={base.get('mae')} nR={acc.get('passive_resistors')} "
            f"tile={meta.get('tile')}",
            flush=True,
        )
        pct_rows = []
        for pct in TILE_PCTS:
            def sampler(catalog, rng, _trial, inputs, p=pct):
                return sample_independent(catalog, p, rng), inputs

            row = run_mc(
                ngspice, spec, net, cat, x_mc, y_mc,
                dest(spec["id"], "D", f"tile{n}_ind{pct:g}"),
                n_trials, f"tile{n}_{pct:g}", sampler,
            )
            row["percent"] = pct
            print(
                f"      independent {pct:g}% MAE_mean={row.get('mae_mean')} "
                f"acc={row.get('accuracy_mean')}",
                flush=True,
            )
            pct_rows.append(row)
        tiling.append(
            {
                "n": n,
                "failed": False,
                "tile": meta.get("tile"),
                "nominal": base,
                "accounting": {
                    "passive_resistors": acc.get("passive_resistors"),
                    "n_reference_resistors": acc.get("n_reference_resistors"),
                    "total_conductance_S": acc.get("total_conductance_S"),
                    "active_functional_blocks": acc.get("active_functional_blocks"),
                },
                "independent": pct_rows,
            }
        )

    print("  signed-path offset", flush=True)
    signed = {"systematic": [], "random": []}
    net, cat, meta = compile_d(spec, weights, tile_n=1)
    for pct in SIGNED_PCTS:
        values = sample_signed_offset(cat, pct, make_rng("sig", spec["id"], pct), "systematic")
        rec = evaluate_netlist(
            ngspice, spec, net, cat, x_sw, y_sw,
            dest(spec["id"], "D", f"sign_sys_{pct:g}"),
            r_values=values,
        )
        rec["name"] = f"systematic_{pct:g}pct"
        rec["value"] = pct
        print(
            f"    systematic {pct:g}% MAE={rec.get('mae')} acc={rec.get('accuracy')}",
            flush=True,
        )
        signed["systematic"].append(rec)
    for pct in (0.5, 1.0, 5.0):
        def sampler(catalog, rng, _trial, inputs, p=pct):
            return sample_signed_offset(catalog, p, rng, "random"), inputs

        row = run_mc(
            ngspice, spec, net, cat, x_mc, y_mc,
            dest(spec["id"], "D", f"sign_rnd_{pct:g}"),
            n_trials, f"signrnd{pct:g}", sampler,
        )
        row["percent"] = pct
        print(f"    random +/- {pct:g}% MAE_mean={row.get('mae_mean')}", flush=True)
        signed["random"].append(row)

    print("  active-block sweeps", flush=True)
    active = {"cccs_common": [], "cccs_polarity": [], "buffer_gain": [], "relu_vos": []}
    for pct in CCCS_PCTS:
        params = ActiveParams(name=f"cccs_common_{pct:g}pct", cccs_common=pct / 100.0)
        net, cat, meta = compile_d(spec, weights, active=params)
        rec = evaluate_netlist(
            ngspice, spec, net, cat, x_sw, y_sw, dest(spec["id"], "D", params.name)
        )
        rec.update({"name": params.name, "value": pct, "params": params.public()})
        print(f"    CCCS common {pct:g}% MAE={rec.get('mae')} acc={rec.get('accuracy')}", flush=True)
        active["cccs_common"].append(rec)
    for pct in CCCS_PCTS:
        params = ActiveParams(name=f"cccs_polarity_{pct:g}pct", cccs_polarity=pct / 100.0)
        net, cat, meta = compile_d(spec, weights, active=params)
        rec = evaluate_netlist(
            ngspice, spec, net, cat, x_sw, y_sw, dest(spec["id"], "D", params.name)
        )
        rec.update({"name": params.name, "value": pct, "params": params.public()})
        print(f"    CCCS polarity {pct:g}% MAE={rec.get('mae')} acc={rec.get('accuracy')}", flush=True)
        active["cccs_polarity"].append(rec)
    for pct in BUF_PCTS:
        params = ActiveParams(name=f"buf_gain_{pct:g}pct", buf_gain=pct / 100.0)
        net, cat, meta = compile_d(spec, weights, active=params)
        rec = evaluate_netlist(
            ngspice, spec, net, cat, x_sw, y_sw, dest(spec["id"], "D", params.name)
        )
        rec.update({"name": params.name, "value": pct, "params": params.public()})
        print(f"    buffer gain {pct:g}% MAE={rec.get('mae')} acc={rec.get('accuracy')}", flush=True)
        active["buffer_gain"].append(rec)
    for vos in RELU_VOS:
        params = ActiveParams(name=f"relu_vos_{vos:g}V", relu_vos=vos)
        net, cat, meta = compile_d(spec, weights, active=params)
        rec = evaluate_netlist(
            ngspice, spec, net, cat, x_sw, y_sw, dest(spec["id"], "D", params.name)
        )
        rec.update({"name": params.name, "value": vos, "params": params.public()})
        print(f"    ReLU Vos={vos:g} MAE={rec.get('mae')} acc={rec.get('accuracy')}", flush=True)
        active["relu_vos"].append(rec)

    firsts = {
        "cccs_common": first_over(active["cccs_common"]),
        "cccs_polarity": first_over(active["cccs_polarity"]),
        "buffer_gain": first_over(active["buffer_gain"]),
        "relu_vos": first_over(active["relu_vos"]),
        "signed_systematic": first_over(signed["systematic"]),
    }

    return {
        "id": spec["id"],
        "label": f"{spec['id']} {spec['n_in']}->{spec['n_hidden']}->{spec['n_out']}",
        "n_full": n_full,
        "n_sweep": n_sw,
        "n_mc": n_mc,
        "n_trials": n_trials,
        "nominal": nom,
        "tiling": tiling,
        "signed": signed,
        "active": active,
        "first_crossings": firsts,
        "spec": spec,
        "weights": weights,
        "x_mc": x_mc,
        "y_mc": y_mc,
    }


def tiling_gain(tiling: list[dict], pct: float) -> dict:
    mae1 = None
    rows = []
    for block in tiling:
        if block.get("failed"):
            continue
        rec = next((r for r in block.get("independent") or [] if r.get("percent") == pct), None)
        if rec and rec.get("mae_mean") is not None:
            if block["n"] == 1:
                mae1 = rec["mae_mean"]
            rows.append({"n": block["n"], "mae_mean": rec["mae_mean"]})
    out = []
    for row in rows:
        pred = mae1 / math.sqrt(row["n"]) if mae1 else None
        out.append(
            {
                **row,
                "mae_n1": mae1,
                "sqrt_prediction": pred,
                "ratio_to_n1": (row["mae_mean"] / mae1) if mae1 else None,
                "ideal_ratio": 1.0 / math.sqrt(row["n"]),
            }
        )
    return {"percent": pct, "points": out}


def combined_mc(ngspice: Path, rows: list[dict]) -> dict:
    """0.5% independent tiles + 0.1% CCCS common + 1 mV ReLU Vos + 1 mV noise."""
    params = ActiveParams(
        name="combined", cccs_common=0.001, relu_vos=0.001, i_leak=1e-8
    )
    out = {}
    for row in rows:
        spec, weights = row["spec"], row["weights"]
        x, y = row["x_mc"], row["y_mc"]
        for n in (1, 4):
            print(f"  combined {spec['id']} N={n}", flush=True)
            net, cat, meta = compile_d(
                spec, weights, tile_n=n, active=params, scale_error=0.001
            )
            if net is None:
                out[f"{spec['id']}_N{n}"] = {"failed": True, "reason": meta}
                continue

            def sampler(catalog, rng, _trial, inputs):
                values = sample_independent(catalog, 0.5, rng)
                noisy = inputs + rng.normal(0.0, INPUT_NOISE, size=inputs.shape)
                return values, noisy

            rec = run_mc(
                ngspice, spec, net, cat, x, y,
                dest(spec["id"], "D", f"comb_N{n}"),
                N_ROBUST_TRIALS, f"comb{spec['id']}N{n}", sampler,
            )
            rec["tile_n"] = n
            rec["tile"] = meta.get("tile")
            rec["conditions"] = {
                "independent_resistor_pct": 0.5,
                "cccs_common": 0.001,
                "relu_vos_V": 0.001,
                "i_leak_A": 1e-8,
                "scale_error": 0.001,
                "input_noise_V": INPUT_NOISE,
            }
            out[f"{spec['id']}_N{n}"] = rec
            print(
                f"    MAE_mean={rec.get('mae_mean')} acc={rec.get('accuracy_mean')}",
                flush=True,
            )
    return out


def analyze(rows: list[dict], combined: dict) -> dict:
    f = next(r for r in rows if r["id"] == "F")
    a = next(r for r in rows if r["id"] == "A")
    # First active block: earliest sweep name whose first crossing exists,
    # preferring the smallest relative error among CCCS/buffer, then ReLU volts.
    order = []
    for sec, scale in (
        ("cccs_common", 1.0),
        ("cccs_polarity", 1.0),
        ("buffer_gain", 1.0),
    ):
        hit = f["first_crossings"].get(sec)
        if hit and hit.get("value") is not None:
            order.append((hit["value"], sec, hit))
    relu = f["first_crossings"].get("relu_vos")
    first_block = min(order, key=lambda t: t[0])[1] if order else None
    if first_block is None and relu:
        first_block = "relu_vos"

    tile_f = tiling_gain(f["tiling"], 1.0)
    n4 = next((p for p in tile_f["points"] if p["n"] == 4), None)
    improved = (
        n4
        and n4.get("ratio_to_n1") is not None
        and n4["ratio_to_n1"] <= 0.7
    )
    comb_d1 = combined.get("F_N1") or {}
    comb_d4 = combined.get("F_N4") or {}
    return {
        "first_sensitive_block": first_block or "none below 1e-3 in tested range",
        "first_crossings_F": f["first_crossings"],
        "first_crossings_A": a["first_crossings"],
        "tiling_1pct_F": tile_f,
        "tiling_reduces_mismatch": bool(improved),
        "combined_F_N1": comb_d1.get("mae_mean"),
        "combined_F_N4": comb_d4.get("mae_mean"),
        "signed_note": (
            "Signed-path error is an offset. A single layer gain constant "
            "cannot cancel I+ vs I- imbalance."
        ),
        "verdict": (
            "MISMATCH FLOOR MEASURED"
            if not improved
            else "TILING REDUCES LOCAL MISMATCH"
        ),
    }


def make_plots(rows: list[dict], combined: dict) -> dict[str, str]:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    colors = {"A": "#1f4e79", "F": "#2e7d4f"}

    fig, ax = plt.subplots(figsize=(7.4, 4.4))
    for row in rows:
        xs, ys, pred = [], [], []
        gain = tiling_gain(row["tiling"], 1.0)
        for p in gain["points"]:
            xs.append(p["n"])
            ys.append(p["mae_mean"])
            if p.get("sqrt_prediction") is not None:
                pred.append(p["sqrt_prediction"])
        ax.plot(xs, ys, "o-", color=colors[row["id"]], label=f"{row['id']} 1% meas", linewidth=2)
        if pred:
            ax.plot(
                xs, pred, "--", color=colors[row["id"]], alpha=0.6,
                label=f"{row['id']} 1/sqrt(N)",
            )
    ax.axhline(ERROR_LIMIT, color="#a33", linestyle=":")
    ax.set_xscale("log", base=2)
    ax.set_yscale("log")
    ax.set_xlabel("tiles per resistor N")
    ax.set_ylabel("MAE mean, independent 1%")
    ax.set_title("Unit-resistor tiling")
    ax.legend(fontsize=8)
    ax.grid(True, which="both", alpha=0.3)
    fig.tight_layout()
    p1 = RESULTS_DIR / "mismatch_tiling.png"
    fig.savefig(p1, dpi=140)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(7.4, 4.4))
    for row in rows:
        recs = row["signed"]["systematic"]
        xs = [r["value"] for r in recs if not r.get("failed") and r.get("mae") is not None]
        ys = [r["mae"] for r in recs if not r.get("failed") and r.get("mae") is not None]
        ax.plot(xs, ys, "o-", color=colors[row["id"]], label=f"{row['id']} systematic", linewidth=2)
        rnd = row["signed"]["random"]
        xr = [r["percent"] for r in rnd if not r.get("failed")]
        yr = [r["mae_mean"] for r in rnd if not r.get("failed")]
        ax.plot(xr, yr, "s--", color=colors[row["id"]], alpha=0.7, label=f"{row['id']} random")
    ax.axhline(ERROR_LIMIT, color="#a33", linestyle=":")
    ax.set_yscale("log")
    ax.set_xlabel("signed-path mismatch (%)")
    ax.set_ylabel("MAE")
    ax.set_title("I+ vs I- offset")
    ax.legend(fontsize=8)
    ax.grid(True, which="both", alpha=0.3)
    fig.tight_layout()
    p2 = RESULTS_DIR / "mismatch_signed_offset.png"
    fig.savefig(p2, dpi=140)
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(8.8, 4.2))
    for ax, key, title, xlabel in (
        (axes[0], "cccs_common", "CCCS common gain", "error (%)"),
        (axes[1], "cccs_polarity", "CCCS polarity mismatch", "error (%)"),
    ):
        for row in rows:
            recs = row["active"][key]
            xs = [r["value"] for r in recs if not r.get("failed") and r.get("mae") is not None]
            ys = [max(r["mae"], 1e-16) for r in recs if not r.get("failed") and r.get("mae") is not None]
            ax.plot(xs, ys, "o-", color=colors[row["id"]], label=row["id"], linewidth=2)
        ax.axhline(ERROR_LIMIT, color="#a33", linestyle=":")
        ax.set_yscale("log")
        ax.set_xlabel(xlabel)
        ax.set_ylabel("MAE")
        ax.set_title(title)
        ax.legend()
        ax.grid(True, which="both", alpha=0.3)
    fig.suptitle("Active blocks on Architecture D")
    fig.tight_layout()
    p3 = RESULTS_DIR / "mismatch_active_blocks.png"
    fig.savefig(p3, dpi=140)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(7.6, 4.3))
    labels = ["nom", "ind 1% N=1", "ind 1% N=4", "sign 1%", "CCCS 0.1%", "comb N=1", "comb N=4"]
    x = np.arange(len(labels))
    w = 0.35
    for i, row in enumerate(rows):
        nom = row["nominal"].get("mae")
        g1 = tiling_gain(row["tiling"], 1.0)
        m1 = next((p["mae_mean"] for p in g1["points"] if p["n"] == 1), np.nan)
        m4 = next((p["mae_mean"] for p in g1["points"] if p["n"] == 4), np.nan)
        sig = next(
            (r.get("mae") for r in row["signed"]["systematic"] if r.get("value") == 1.0),
            np.nan,
        )
        cccs = next(
            (r.get("mae") for r in row["active"]["cccs_common"] if r.get("value") == 0.1),
            np.nan,
        )
        c1 = (combined.get(f"{row['id']}_N1") or {}).get("mae_mean")
        c4 = (combined.get(f"{row['id']}_N4") or {}).get("mae_mean")
        ys = [nom, m1, m4, sig, cccs, c1, c4]
        ax.bar(x + (i - 0.5) * w, [v if v is not None else np.nan for v in ys], w, label=row["id"])
    ax.set_yscale("log")
    ax.set_xticks(x, labels, rotation=20, ha="right")
    ax.axhline(ERROR_LIMIT, color="#333", linestyle="--")
    ax.set_ylabel("MAE")
    ax.set_title("Experiment 15 comparison")
    ax.legend()
    ax.grid(True, axis="y", alpha=0.3)
    fig.tight_layout()
    p4 = RESULTS_DIR / "mismatch_limit_map.png"
    fig.savefig(p4, dpi=140)
    plt.close(fig)
    return {
        "tiling": str(p1.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        "signed": str(p2.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        "active": str(p3.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        "comparison": str(p4.relative_to(PROJECT_ROOT)).replace("\\", "/"),
    }


def public_row(row: dict) -> dict:
    return {
        k: v
        for k, v in row.items()
        if k not in {"spec", "weights", "x_mc", "y_mc"}
    }


def print_final(rows: list[dict], combined: dict, summary: dict, plots: dict) -> None:
    print("\n==================================================")
    print("EXPERIMENT 15")
    print("MISMATCH-LIMITED RATIOMETRIC FABRIC")
    print("==================================================")
    for row in rows:
        nom = row["nominal"]
        print(f"\nNETWORK {row['label']}")
        print(
            f"  nominal D: MAE={fmt(nom.get('mae'))} acc={fmt(nom.get('accuracy'), '.4f')} "
            f"nR={nom.get('passive_resistors')} SigmaG={fmt(nom.get('total_conductance_S'))}"
        )
        print("  TILING (independent 1%):")
        for p in tiling_gain(row["tiling"], 1.0)["points"]:
            print(
                f"    N={p['n']}: MAE={fmt(p['mae_mean'])} "
                f"ratio_to_N1={fmt(p.get('ratio_to_n1'), '.3f')} "
                f"1/sqrt(N)={fmt(p.get('ideal_ratio'), '.3f')}"
            )
        print("  SIGNED-PATH SYSTEMATIC:")
        for rec in row["signed"]["systematic"]:
            print(f"    {rec.get('value')}% MAE={fmt(rec.get('mae'))} acc={fmt(rec.get('accuracy'), '.4f')}")
        print("  ACTIVE FIRST CROSSINGS:", row["first_crossings"])
    print("\nCOMBINED (0.5% R + 0.1% CCCS + 1 mV ReLU + 1 mV noise):")
    for key, rec in combined.items():
        print(
            f"  {key}: MAE_mean={fmt(rec.get('mae_mean'))} "
            f"acc={fmt(rec.get('accuracy_mean'), '.4f')} "
            f"acc_min={fmt(rec.get('accuracy_min'), '.4f')}"
        )
    print(f"\nFIRST SENSITIVE BLOCK: {summary['first_sensitive_block']}")
    print(f"TILING 1% ON F: {summary['tiling_1pct_F']}")
    print("\nFINAL STATUS:")
    print(summary["verdict"])
    print(summary["signed_note"])
    print(f"\nWrote {REPORT_PATH}")
    for path in plots.values():
        print(f"Wrote {path}")


def main() -> int:
    ngspice = find_ngspice()
    CIRCUIT_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    print("Physical AI - Experiment 15")
    print("MISMATCH-LIMITED RATIOMETRIC FABRIC")
    print("Behavioral mismatch study. Not layout. Not foundry PCM.")
    print(f"ngspice: {ngspice}")

    rows = [evaluate_network(ngspice, spec_by_id(net_id)) for net_id in ("A", "F")]
    print("\nCombined Monte Carlo", flush=True)
    combined = combined_mc(ngspice, rows)
    plots = make_plots(rows, combined)
    summary = analyze(rows, combined)
    report = {
        "experiment": 15,
        "analysis": "behavioral mismatch study on Experiment 14 Architecture D",
        "error_limit": ERROR_LIMIT,
        "fairness": (
            "Frozen Experiment 9 weights. No Python output correction. "
            "Tiling stays inside 1 kOhm-1 MOhm. Active errors are macromodel "
            "parameters, not transistors."
        ),
        "networks": [public_row(r) for r in rows],
        "combined": combined,
        "plots": plots,
        "summary": summary,
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print_final(rows, combined, summary, plots)
    return 0


if __name__ == "__main__":
    sys.exit(main())
