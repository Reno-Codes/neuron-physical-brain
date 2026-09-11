"""Experiment 13: precision-preserving physical architectures.

Frozen Experiment 9 models A and F. Weights are never edited.
Outputs are never corrected in Python. SPICE is the physical source of truth.

This is behavioral circuit analysis, not transistor-level design.
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
    CLASS_THRESHOLD,
    MATCH_TOL,
    N_ROBUST_INPUTS,
    N_ROBUST_TRIALS,
    N_TEST,
    ROBUST_TOLERANCE,
    classification_labels,
    error_stats,
    generate_inputs,
    make_rng,
    simulate_batch,
)
from compile_xor import PROJECT_ROOT, find_ngspice
from hardware_constrained_compiler import current_cost_estimate, load_frozen_model
from precision_architectures import (
    ARCH_SPECS,
    CIRCUIT_DIR,
    R_MAX,
    R_MIN,
    accounting,
    compile_architecture,
    config_for,
    hidden_preact_max,
    software_reference,
)
from test_hardware_constraints import measure_source_current, spec_by_id
from test_nonideal_network import class_margins
from test_robustness import sample_resistor_values


RESULTS_DIR = PROJECT_ROOT / "results"
REPORT_PATH = RESULTS_DIR / "precision_architectures_report.json"
ERROR_LIMIT = 1.0e-3
INPUT_NOISE = 0.001
TIMEOUT = 20.0
N_F_SWEEP = 40
TEST_IDS = ("A", "F")
ARCH_KEYS = ("A", "B", "C")
SCALE_PCTS = (0.0, 0.01, 0.1, 0.5, 1.0, 5.0)
LEAK_A = (0.0, 1e-9, 1e-8, 1e-7)
VOS_B = (0.0, 1e-5, 1e-4, 1e-3)
RAILS = (15.0, 5.0, 3.3)
RAIL_MARGIN = 0.05

# Combined robustness extras, architecture-specific.
ROBUST_LEAK = {"A": 1e-8, "C": 1e-8}
ROBUST_VOS = {"B": 1e-4}


def n_vectors(net_id: str, kind: str) -> int:
    if net_id == "A":
        return N_TEST
    if kind == "sweep":
        return N_F_SWEEP
    return N_TEST


def dest_path(net_id: str, arch: str, tag: str) -> Path:
    safe = tag.replace(" ", "_").replace("%", "pct").replace("+", "p")
    return CIRCUIT_DIR / f"{net_id}_{arch}_{safe}.cir"


def strip_heavy(record: dict) -> dict:
    return {k: v for k, v in record.items() if k not in {"catalog", "netlist"}}


def first_crossing(rows: list[dict], pred) -> dict | None:
    for rec in rows:
        if rec.get("failed"):
            continue
        if pred(rec):
            return {
                "name": rec.get("name"),
                "scale_pct": rec.get("scale_pct"),
                "mae": rec.get("mae"),
                "accuracy": rec.get("accuracy"),
            }
    return None


def evaluate(
    ngspice: Path,
    arch: str,
    spec: dict,
    weights: dict[str, np.ndarray],
    inputs: np.ndarray,
    dest: Path,
    name: str,
    scale_error: float = 0.0,
    i_leak: float = 0.0,
    v_offset: float = 0.0,
    rail: float = 15.0,
    linear: bool = False,
    relu_style: str = "direct",
    measure_i: bool = False,
) -> dict:
    zmax, hmax = hidden_preact_max(inputs, weights["W1"], weights["b1"])
    clipped = (not linear) and hmax > rail + 1e-12
    software = software_reference(
        inputs,
        weights["W1"],
        weights["b1"],
        weights["W2"],
        weights["b2"],
        linear=linear,
        hidden_rail=rail if clipped else None,
    )
    record = {
        "name": name,
        "arch": arch,
        "network": spec["id"],
        "scale_error": scale_error,
        "scale_pct": scale_error * 100.0,
        "i_leak": i_leak,
        "v_offset": v_offset,
        "rail": rail,
        "linear": linear,
        "relu_style": "none" if linear else relu_style,
        "software_reference": (
            "linear-no-ReLU"
            if linear
            else (
                "clipped-ReLU (hidden min(rail, relu(z)))"
                if clipped
                else "NumPy ReLU"
            )
        ),
        "hidden_preact_max": zmax,
        "hidden_relu_max": hmax,
        "clipped_software": clipped,
        "failed": False,
        "failure_reason": None,
        "n_convergence_failures": 0,
    }
    netlist, catalog, reason = compile_architecture(
        arch,
        spec,
        weights,
        scale_error=scale_error,
        i_leak=i_leak,
        v_offset=v_offset,
        rail=rail,
        linear=linear,
        relu_style=relu_style,
    )
    if reason or netlist is None:
        record["failed"] = True
        record["failure_reason"] = reason
        record["n_convergence_failures"] = 1
        return record
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(netlist, encoding="utf-8")
    n_weights = spec["n_in"] * spec["n_hidden"] + spec["n_hidden"] * spec["n_out"]
    record.update(accounting(netlist, catalog, n_weights))
    physical, runtime, spice_err, log = simulate_batch(
        ngspice, netlist, inputs, spec["n_out"], dest, timeout=TIMEOUT
    )
    record["spice_runtime_s"] = runtime
    if spice_err or physical is None:
        record["failed"] = True
        record["failure_reason"] = spice_err or "no physical outputs"
        record["n_convergence_failures"] = 1
        record["spice_log_tail"] = (log or "")[-500:]
        return record
    err = error_stats(physical, software)
    pred = classification_labels(physical)
    expected = classification_labels(software)
    n_fail = int(np.sum(pred != expected))
    margins = class_margins(physical, software)
    sat = int(np.sum(np.abs(physical) >= rail - RAIL_MARGIN))
    record.update(
        {
            "mae": err["mae"],
            "rms": err["rms"],
            "max_abs_error": err["max_abs_error"],
            "accuracy": float(1.0 - n_fail / max(len(expected), 1)),
            "n_class_failures": n_fail,
            "min_margin": float(np.min(margins)),
            "n_saturated_outputs": sat,
            "exceeds_error_limit": err["mae"] > ERROR_LIMIT,
            "classification_ok": n_fail == 0,
            "software_abs_max": float(np.max(np.abs(software))),
            "catalog": catalog,
            "netlist": netlist,
        }
    )
    if measure_i:
        source_i = measure_source_current(
            ngspice, netlist, inputs[0], dest.with_name(dest.stem + "_i.cir")
        )
        record["current_cost"] = current_cost_estimate(catalog, source_i)
        record["spice_source_current_A"] = source_i
    return record


def run_robustness(
    ngspice: Path,
    spec: dict,
    netlist: str,
    catalog: list[dict],
    subset_x: np.ndarray,
    software: np.ndarray,
    dest: Path,
    tag: str,
) -> dict:
    rng = make_rng("hw13", spec["id"], tag)
    expected = classification_labels(software)
    maes, accs = [], []
    failures = 0
    for trial in range(N_ROBUST_TRIALS):
        values = sample_resistor_values(catalog, ROBUST_TOLERANCE, rng)
        noisy = subset_x + rng.normal(0.0, INPUT_NOISE, size=subset_x.shape)
        physical, _runtime, spice_err, _log = simulate_batch(
            ngspice,
            netlist,
            noisy,
            spec["n_out"],
            dest,
            r_values=values,
            timeout=TIMEOUT,
        )
        if spice_err or physical is None:
            failures += 1
            continue
        stats = error_stats(physical, software)
        pred = classification_labels(physical)
        maes.append(stats["mae"])
        accs.append(float(np.mean(pred == expected)))
        if (trial + 1) % 25 == 0 or trial == 0:
            print(
                f"      robustness {tag} {trial + 1}/{N_ROBUST_TRIALS} "
                f"MAE={stats['mae']:.4e}",
                flush=True,
            )
    if not maes:
        return {
            "failed": True,
            "n_spice_failures": failures,
            "n_trials": N_ROBUST_TRIALS,
        }
    return {
        "failed": False,
        "tolerance": ROBUST_TOLERANCE,
        "scale_error": 0.001,
        "input_noise_sigma": INPUT_NOISE,
        "n_trials": N_ROBUST_TRIALS,
        "n_inputs": int(len(subset_x)),
        "n_spice_failures": failures,
        "mae_mean": float(np.mean(maes)),
        "mae_max": float(np.max(maes)),
        "accuracy_mean": float(np.mean(accs)),
        "accuracy_min": float(np.min(accs)),
    }


def load_prior() -> dict:
    prior = {
        "exp11_mae": {},
        "exp12_mae_0p1pct": {},
        "exp12_L3_mae": {},
        "exp12_L3_robust_mae_mean": {},
    }
    dr = RESULTS_DIR / "dynamic_range_report.json"
    ni = RESULTS_DIR / "nonideal_report.json"
    if dr.is_file():
        data = json.loads(dr.read_text(encoding="utf-8"))
        for row in data.get("networks", []):
            prior["exp11_mae"][row["id"]] = (
                (row.get("winner") or {}).get("mae")
                or (row.get("best") or {}).get("mae")
            )
    if ni.is_file():
        data = json.loads(ni.read_text(encoding="utf-8"))
        for row in data.get("networks", []):
            nid = row["id"]
            prior["exp12_L3_mae"][nid] = (row.get("levels") or {}).get("L3", {}).get(
                "mae"
            )
            prior["exp12_L3_robust_mae_mean"][nid] = (
                (row.get("combined_robustness") or {}).get("result") or {}
            ).get("mae_mean")
            for rec in (row.get("sweeps") or {}).get("gain_error", []):
                ge = (rec.get("params") or {}).get("gain_error")
                if ge == 0.001:
                    prior["exp12_mae_0p1pct"][nid] = rec.get("mae")
    return prior


def evaluate_pair(ngspice: Path, spec: dict) -> dict:
    weights = load_frozen_model(spec["id"])
    n_all = n_vectors(spec["id"], "full")
    n_sweep = n_vectors(spec["id"], "sweep")
    x_all = generate_inputs(spec["n_in"], n_all, spec["id"])
    x_sweep = x_all[:n_sweep]
    x_rob = x_all[:N_ROBUST_INPUTS]
    y_rob = software_reference(
        x_rob, weights["W1"], weights["b1"], weights["W2"], weights["b2"]
    )
    zmax, hmax = hidden_preact_max(x_all, weights["W1"], weights["b1"])
    print(
        f"\n=== Network {spec['id']} {spec['n_in']}->{spec['n_hidden']}->"
        f"{spec['n_out']}  test={n_all} sweep={n_sweep} "
        f"hidden_relu_max={hmax:.4g} ===",
        flush=True,
    )
    arches = {}
    for arch in ARCH_KEYS:
        cfg = config_for(arch, spec["id"])
        print(f"  compile {arch}: {cfg.label()}", flush=True)
        rec_full = evaluate(
            ngspice, arch, spec, weights, x_all,
            dest_path(spec["id"], arch, "nominal_full"),
            "nominal_full", measure_i=True,
        )
        print(
            f"    MODE B full  MAE={rec_full.get('mae')} "
            f"acc={rec_full.get('accuracy')} "
            f"R=[{rec_full.get('r_min')}, {rec_full.get('r_max')}] "
            f"fail={rec_full.get('failure_reason')}",
            flush=True,
        )
        rec_lin = evaluate(
            ngspice, arch, spec, weights, x_all,
            dest_path(spec["id"], arch, "nominal_linear"),
            "nominal_linear", linear=True, measure_i=False,
        )
        print(
            f"    MODE A linear MAE={rec_lin.get('mae')} "
            f"fail={rec_lin.get('failure_reason')}",
            flush=True,
        )
        rec_prec = None
        if arch == "A":
            rec_prec = evaluate(
                ngspice, arch, spec, weights, x_all,
                dest_path(spec["id"], arch, "precision_relu"),
                "precision_relu_15V", relu_style="precision",
            )
            print(
                f"    A precision-ReLU MAE={rec_prec.get('mae')} "
                f"fail={rec_prec.get('failure_reason')}",
                flush=True,
            )

        print(f"    scaling sweep {arch}", flush=True)
        scale_rows = []
        for pct in SCALE_PCTS:
            rec = evaluate(
                ngspice, arch, spec, weights, x_sweep,
                dest_path(spec["id"], arch, f"scale_{pct:g}pct"),
                f"scale_{pct:g}pct", scale_error=pct / 100.0,
            )
            print(
                f"      {pct:g}% MAE={rec.get('mae')} acc={rec.get('accuracy')} "
                f"fail={rec.get('failure_reason')}",
                flush=True,
            )
            scale_rows.append(strip_heavy(rec))

        print(f"    leakage/offset sweep {arch}", flush=True)
        leak_rows = []
        if arch == "B":
            for vos in VOS_B:
                rec = evaluate(
                    ngspice, arch, spec, weights, x_sweep,
                    dest_path(spec["id"], arch, f"vos_{vos:g}"),
                    f"vos_{vos:g}V", v_offset=vos,
                )
                print(
                    f"      Vos={vos:g} MAE={rec.get('mae')} "
                    f"acc={rec.get('accuracy')} fail={rec.get('failure_reason')}",
                    flush=True,
                )
                leak_rows.append(strip_heavy(rec))
        else:
            for amp in LEAK_A:
                rec = evaluate(
                    ngspice, arch, spec, weights, x_sweep,
                    dest_path(spec["id"], arch, f"leak_{amp:g}"),
                    f"leak_{amp:g}A", i_leak=amp,
                )
                print(
                    f"      Ileak={amp:g} MAE={rec.get('mae')} "
                    f"acc={rec.get('accuracy')} fail={rec.get('failure_reason')}",
                    flush=True,
                )
                leak_rows.append(strip_heavy(rec))

        print(f"    supply map {arch}", flush=True)
        supply_rows = []
        for rail in RAILS:
            for linear, mode in ((True, "linear"), (False, "full")):
                rec = evaluate(
                    ngspice, arch, spec, weights, x_sweep,
                    dest_path(spec["id"], arch, f"supply_{rail:g}_{mode}"),
                    f"supply_pm{rail:g}V_{mode}",
                    rail=rail, linear=linear,
                )
                print(
                    f"      +/-{rail:g} {mode} MAE={rec.get('mae')} "
                    f"acc={rec.get('accuracy')} clip={rec.get('clipped_software')} "
                    f"fail={rec.get('failure_reason')}",
                    flush=True,
                )
                supply_rows.append(strip_heavy(rec))

        arches[arch] = {
            "title": ARCH_SPECS[arch].title,
            "scale_mechanism": ARCH_SPECS[arch].scale_mechanism,
            "config": config_for(arch, spec["id"]).label(),
            "nominal_full": strip_heavy(rec_full),
            "nominal_linear": strip_heavy(rec_lin),
            "precision_relu": strip_heavy(rec_prec) if rec_prec else None,
            "scale_sweep": scale_rows,
            "leak_sweep": leak_rows,
            "supply_map": supply_rows,
            "nominal_netlist": rec_full.get("netlist"),
            "nominal_catalog": rec_full.get("catalog"),
        }

    return {
        "id": spec["id"],
        "label": f"{spec['id']} {spec['n_in']}->{spec['n_hidden']}->{spec['n_out']}",
        "n_test": n_all,
        "n_sweep": n_sweep,
        "hidden_preact_max": zmax,
        "hidden_relu_max": hmax,
        "architectures": arches,
        "x_rob": x_rob,
        "y_rob": y_rob,
        "weights": weights,
    }


def pick_best(rows: list[dict]) -> str:
    """Prefer F's 0.1% MAE, then A, then component count."""
    f_row = next((r for r in rows if r["id"] == "F"), None)
    scores = {}
    for key in ARCH_KEYS:
        rec = None
        if f_row:
            rec = next(
                (
                    s
                    for s in f_row["architectures"][key]["scale_sweep"]
                    if abs((s.get("scale_pct") or -1) - 0.1) < 1e-12
                ),
                None,
            )
        mae = rec.get("mae") if rec and not rec.get("failed") else 1e9
        compiled = True
        if f_row:
            nom = f_row["architectures"][key]["nominal_full"]
            compiled = (not nom.get("failed")) and nom.get("r_max", 1e99) <= R_MAX
        scores[key] = (0 if compiled else 1, mae if mae is not None else 1e9, key)
    return min(ARCH_KEYS, key=lambda k: scores[k])


def attach_robustness(ngspice: Path, rows: list[dict], best: str) -> None:
    for row in rows:
        spec = spec_by_id(row["id"])
        weights = row["weights"]
        x_rob = row["x_rob"]
        y_rob = row["y_rob"]
        for arch in ("A", best) if best != "A" else ("A",):
            extras = {}
            if arch == "B":
                extras["v_offset"] = ROBUST_VOS["B"]
            else:
                extras["i_leak"] = ROBUST_LEAK[arch]
            print(
                f"  combined robustness {row['id']} arch {arch} "
                f"(5% R + 0.1% scale + extras + 1 mV noise)",
                flush=True,
            )
            rec = evaluate(
                ngspice,
                arch,
                spec,
                weights,
                x_rob,
                dest_path(row["id"], arch, "robust_base"),
                "robust_base",
                scale_error=0.001,
                **extras,
            )
            robust = None
            if rec.get("netlist") and rec.get("catalog") and not rec.get("failed"):
                robust = run_robustness(
                    ngspice,
                    spec,
                    rec["netlist"],
                    rec["catalog"],
                    x_rob,
                    y_rob,
                    dest_path(row["id"], arch, "robust_mc"),
                    f"{row['id']}{arch}",
                )
            row["architectures"][arch]["combined_robustness"] = {
                "base": strip_heavy(rec),
                "result": robust,
                "conditions": {
                    "resistor_tolerance": ROBUST_TOLERANCE,
                    "scale_error": 0.001,
                    "i_leak": extras.get("i_leak"),
                    "v_offset": extras.get("v_offset"),
                    "input_noise": INPUT_NOISE,
                },
            }


def summarize(rows: list[dict], prior: dict, best: str) -> dict:
    table = []
    for arch in ARCH_KEYS:
        f = next(r for r in rows if r["id"] == "F")["architectures"][arch]
        a = next(r for r in rows if r["id"] == "A")["architectures"][arch]
        scale = {s.get("scale_pct"): s for s in f["scale_sweep"]}
        mae_0 = (scale.get(0.0) or {}).get("mae")
        mae_01 = (scale.get(0.1) or {}).get("mae")
        mae_1 = (scale.get(1.0) or {}).get("mae")
        first_mae = first_crossing(
            f["scale_sweep"], lambda r: (r.get("mae") or 0) > ERROR_LIMIT
        )
        first_cls = first_crossing(
            f["scale_sweep"],
            lambda r: r.get("accuracy") is not None and r["accuracy"] < 1.0,
        )
        working = [
            s
            for s in f["supply_map"]
            if (not s.get("failed"))
            and s.get("linear") is False
            and s.get("classification_ok")
        ]
        lowest = min((s["rail"] for s in working), default=None)
        nom = f["nominal_full"]
        table.append(
            {
                "architecture": arch,
                "title": f["title"],
                "resistor_range": [nom.get("r_min"), nom.get("r_max")],
                "mae_nominal_F": nom.get("mae"),
                "mae_nominal_A": a["nominal_full"].get("mae"),
                "mae_0p1pct_F": mae_01,
                "mae_1pct_F": mae_1,
                "mae_0pct_F": mae_0,
                "first_mae_over_1e-3_F": first_mae,
                "first_class_fail_F": first_cls,
                "lowest_working_supply_F": lowest,
                "passive_resistors_F": nom.get("passive_resistors"),
                "active_functional_blocks_F": nom.get("active_functional_blocks"),
                "runtime_s_F": nom.get("spice_runtime_s"),
                "compiled_1k_1M_F": (
                    not nom.get("failed")
                    and nom.get("r_min") is not None
                    and nom["r_min"] >= R_MIN
                    and nom["r_max"] <= R_MAX
                ),
            }
        )

    f_best = next(r for r in rows if r["id"] == "F")["architectures"][best]
    a_best = next(r for r in rows if r["id"] == "A")["architectures"][best]
    s01 = next(
        (s for s in f_best["scale_sweep"] if abs((s.get("scale_pct") or -1) - 0.1) < 1e-12),
        {},
    )
    improved = (
        (not f_best["nominal_full"].get("failed"))
        and f_best["nominal_full"].get("r_max", 1e99) <= R_MAX
        and s01.get("mae") is not None
        and s01["mae"] <= ERROR_LIMIT
        and best != "A"
    )
    # Also improved if B/C beat A's 0.1% MAE even if still above 1e-3.
    a_s01 = next(
        (
            s
            for s in next(r for r in rows if r["id"] == "F")["architectures"]["A"][
                "scale_sweep"
            ]
            if abs((s.get("scale_pct") or -1) - 0.1) < 1e-12
        ),
        {},
    )
    better_than_baseline = (
        s01.get("mae") is not None
        and a_s01.get("mae") is not None
        and s01["mae"] < 0.5 * a_s01["mae"]
    )
    if improved:
        verdict = "PRECISION ARCHITECTURE IMPROVED"
    elif better_than_baseline:
        verdict = "PRECISION ARCHITECTURE IMPROVED"
    else:
        verdict = "PRECISION LIMIT CONFIRMED"

    first_mae = first_crossing(
        f_best["scale_sweep"], lambda r: (r.get("mae") or 0) > ERROR_LIMIT
    )
    first_cls = first_crossing(
        f_best["scale_sweep"] + a_best["scale_sweep"],
        lambda r: r.get("accuracy") is not None and r["accuracy"] < 1.0,
    )
    working = [
        s
        for s in f_best["supply_map"] + a_best["supply_map"]
        if (not s.get("failed")) and s.get("linear") is False and s.get("classification_ok")
    ]
    lowest = min((s["rail"] for s in working), default=None)
    return {
        "table": table,
        "best_architecture": best,
        "verdict": verdict,
        "result_0p1pct_F": s01,
        "first_mae_over_1e-3": first_mae,
        "first_classification_failure": first_cls,
        "lowest_working_supply": lowest,
        "prior": prior,
        "layer_factorization_note": (
            "S*((W/S)*X) does not change max|w|/min|w|. Network F ratios "
            "are ~1420:1 and ~1482:1 versus R_MAX/R_MIN=1000, so layer-level "
            "factorization alone cannot replace multi-range encoding."
        ),
        "fairness": (
            "Architecture A scale error multiplies every CCCS alpha, including "
            "unity, matching Experiment 12. Architectures B and C apply scale "
            "error only to the extra range references / divider ratio. That "
            "difference is the scientific claim, not a Python correction."
        ),
    }


def make_plots(rows: list[dict], best: str) -> dict[str, str]:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    colors = {"A": "#1f4e79", "B": "#c47b17", "C": "#2e7d4f"}
    styles = {"A": "-", "F": "--"}

    fig, ax = plt.subplots(figsize=(7.6, 4.4))
    for row in rows:
        for arch in ARCH_KEYS:
            sweep = row["architectures"][arch]["scale_sweep"]
            xs, ys = [], []
            for rec in sweep:
                if rec.get("failed") or rec.get("mae") is None:
                    continue
                xs.append(max(rec["scale_pct"], 1e-4))
                ys.append(rec["mae"])
            if xs:
                ax.plot(
                    xs,
                    ys,
                    "o" + styles[row["id"]],
                    color=colors[arch],
                    label=f"{row['id']}-{arch}",
                    linewidth=2,
                )
    ax.axhline(ERROR_LIMIT, color="#a33", linestyle=":", label="MAE=1e-3")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("scale / reference error (%)")
    ax.set_ylabel("MAE vs software")
    ax.set_title("Experiment 13 scaling-error sensitivity")
    ax.legend(fontsize=8, ncol=3)
    ax.grid(True, which="both", alpha=0.3)
    fig.tight_layout()
    p1 = RESULTS_DIR / "precision_scaling_sensitivity.png"
    fig.savefig(p1, dpi=140)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(7.6, 4.4))
    for row in rows:
        for arch in ARCH_KEYS:
            sweep = row["architectures"][arch]["leak_sweep"]
            xs, ys = [], []
            for rec in sweep:
                if rec.get("failed") or rec.get("mae") is None:
                    continue
                x = rec.get("v_offset") if arch == "B" else rec.get("i_leak")
                xs.append(max(float(x), 1e-12))
                ys.append(rec["mae"])
            if xs:
                ax.plot(
                    xs,
                    ys,
                    "o" + styles[row["id"]],
                    color=colors[arch],
                    label=f"{row['id']}-{arch}",
                    linewidth=2,
                )
    ax.axhline(ERROR_LIMIT, color="#a33", linestyle=":", label="MAE=1e-3")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("leakage (A) or range offset (V)")
    ax.set_ylabel("MAE vs software")
    ax.set_title("Experiment 13 leakage / offset sensitivity")
    ax.legend(fontsize=8, ncol=3)
    ax.grid(True, which="both", alpha=0.3)
    fig.tight_layout()
    p2 = RESULTS_DIR / "precision_leakage_sensitivity.png"
    fig.savefig(p2, dpi=140)
    plt.close(fig)

    # Supply map: rows = net/arch/mode, cols = rails.
    labels = []
    grid = []
    for row in rows:
        for arch in ARCH_KEYS:
            for mode, linear in (("full", False), ("lin", True)):
                labels.append(f"{row['id']}-{arch}-{mode}")
                vals = []
                for rail in RAILS:
                    rec = next(
                        (
                            s
                            for s in row["architectures"][arch]["supply_map"]
                            if s.get("rail") == rail and s.get("linear") is linear
                        ),
                        {},
                    )
                    if rec.get("failed"):
                        vals.append(3)
                    elif rec.get("accuracy") is not None and rec["accuracy"] < 1.0:
                        vals.append(2)
                    elif rec.get("exceeds_error_limit"):
                        vals.append(1)
                    else:
                        vals.append(0)
                grid.append(vals)
    fig, ax = plt.subplots(figsize=(6.4, 7.2))
    im = ax.imshow(np.array(grid), aspect="auto", cmap="YlOrRd", vmin=0, vmax=3)
    ax.set_yticks(range(len(labels)), labels, fontsize=7)
    ax.set_xticks(range(len(RAILS)), [f"+/-{r:g} V" for r in RAILS])
    ax.set_title("0=ok  1=MAE>1e-3  2=class fail  3=SPICE fail")
    fig.colorbar(im, ax=ax, fraction=0.04)
    fig.tight_layout()
    p3 = RESULTS_DIR / "precision_supply_map.png"
    fig.savefig(p3, dpi=140)
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(8.6, 4.2))
    x = np.arange(len(ARCH_KEYS))
    for ax, net_id, title in (
        (axes[0], "A", "Network A"),
        (axes[1], "F", "Network F"),
    ):
        row = next(r for r in rows if r["id"] == net_id)
        mae0, mae01, mae1 = [], [], []
        for arch in ARCH_KEYS:
            sweep = {s.get("scale_pct"): s for s in row["architectures"][arch]["scale_sweep"]}
            mae0.append((sweep.get(0.0) or {}).get("mae") or np.nan)
            mae01.append((sweep.get(0.1) or {}).get("mae") or np.nan)
            mae1.append((sweep.get(1.0) or {}).get("mae") or np.nan)
        w = 0.25
        ax.bar(x - w, mae0, w, label="0%", color="#4c78a8")
        ax.bar(x, mae01, w, label="0.1%", color="#f58518")
        ax.bar(x + w, mae1, w, label="1%", color="#e45756")
        ax.axhline(ERROR_LIMIT, color="#333", linestyle="--", linewidth=1)
        ax.set_yscale("log")
        ax.set_xticks(x, list(ARCH_KEYS))
        ax.set_ylabel("MAE")
        ax.set_title(title)
        ax.grid(True, axis="y", alpha=0.3)
        ax.legend(fontsize=8)
    fig.suptitle(f"Architecture comparison (best={best})")
    fig.tight_layout()
    p4 = RESULTS_DIR / "precision_architecture_comparison.png"
    fig.savefig(p4, dpi=140)
    plt.close(fig)

    return {
        "scaling": str(p1.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        "leakage": str(p2.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        "supply": str(p3.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        "comparison": str(p4.relative_to(PROJECT_ROOT)).replace("\\", "/"),
    }


def fmt(value, spec=".4e") -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return format(value, spec)
    return str(value)


def print_arch_block(title: str, a: dict, f: dict) -> None:
    print(f"\n{title}:")
    print(f"  mechanism: {f['scale_mechanism']}")
    print(f"  mapping: {f['config']}")
    an, fn = a["nominal_full"], f["nominal_full"]
    print(
        f"  Network A nominal: MAE={fmt(an.get('mae'))} acc={fmt(an.get('accuracy'), '.4f')} "
        f"R={fmt(an.get('r_min'))}..{fmt(an.get('r_max'))} "
        f"Rcount={an.get('passive_resistors')} active={an.get('active_functional_blocks')}"
    )
    print(
        f"  Network F nominal: MAE={fmt(fn.get('mae'))} acc={fmt(fn.get('accuracy'), '.4f')} "
        f"R={fmt(fn.get('r_min'))}..{fmt(fn.get('r_max'))} "
        f"Rcount={fn.get('passive_resistors')} active={fn.get('active_functional_blocks')} "
        f"runtime={fmt(fn.get('spice_runtime_s'), '.3f')} s"
    )
    print(f"  F bank G_eff fraction: {fn.get('bank_geff_fraction')}")
    print(
        f"  F linear-core MAE={fmt(f['nominal_linear'].get('mae'))}  "
        f"full-net MAE={fmt(fn.get('mae'))}"
    )
    s01 = next((s for s in f["scale_sweep"] if abs((s.get("scale_pct") or -1) - 0.1) < 1e-12), {})
    s1 = next((s for s in f["scale_sweep"] if abs((s.get("scale_pct") or -1) - 1.0) < 1e-12), {})
    print(f"  F MAE at 0.1% scale: {fmt(s01.get('mae'))} acc={fmt(s01.get('accuracy'), '.4f')}")
    print(f"  F MAE at 1% scale:   {fmt(s1.get('mae'))} acc={fmt(s1.get('accuracy'), '.4f')}")


def print_final(rows: list[dict], summary: dict, plots: dict) -> None:
    a_row = next(r for r in rows if r["id"] == "A")
    f_row = next(r for r in rows if r["id"] == "F")
    print("\n==================================================")
    print("EXPERIMENT 13")
    print("PRECISION-PRESERVING PHYSICAL ARCHITECTURES")
    print("==================================================")
    print_arch_block("CURRENT-GAIN BASELINE", a_row["architectures"]["A"], f_row["architectures"]["A"])
    print_arch_block("ARCHITECTURE B", a_row["architectures"]["B"], f_row["architectures"]["B"])
    print_arch_block("ARCHITECTURE C", a_row["architectures"]["C"], f_row["architectures"]["C"])
    print(f"\nBEST ARCHITECTURE: {summary['best_architecture']}")
    print(f"0.1% ERROR RESULT: {summary['result_0p1pct_F']}")
    print(f"FIRST MAE > 1e-3: {summary['first_mae_over_1e-3']}")
    print(f"FIRST CLASSIFICATION FAILURE: {summary['first_classification_failure']}")
    print(f"LOWEST WORKING SUPPLY: {summary['lowest_working_supply']}")
    best = summary["best_architecture"]
    fn = f_row["architectures"][best]["nominal_full"]
    an = f_row["architectures"]["A"]["nominal_full"]
    print(
        "COMPONENT OVERHEAD: "
        f"best F resistors={fn.get('passive_resistors')} "
        f"(baseline {an.get('passive_resistors')}) "
        f"active={fn.get('active_functional_blocks')} "
        f"(baseline {an.get('active_functional_blocks')}) "
        f"SigmaG={fmt(fn.get('total_conductance_S'))} S "
        f"(baseline {fmt(an.get('total_conductance_S'))} S)"
    )
    print("\nComparison table (Network F):")
    print(
        "Arch  Rmin        Rmax        MAE0        MAE0.1%     MAE1%       "
        "first>1e-3   class_fail   Vmin   R     Act   t_s"
    )
    for row in summary["table"]:
        fm = row["first_mae_over_1e-3_F"]
        fc = row["first_class_fail_F"]
        print(
            f"{row['architecture']:<5} "
            f"{fmt(row['resistor_range'][0]):<11} "
            f"{fmt(row['resistor_range'][1]):<11} "
            f"{fmt(row['mae_nominal_F']):<11} "
            f"{fmt(row['mae_0p1pct_F']):<11} "
            f"{fmt(row['mae_1pct_F']):<11} "
            f"{str((fm or {}).get('name')):<12} "
            f"{str((fc or {}).get('name')):<12} "
            f"{fmt(row['lowest_working_supply_F'], 'g'):<6} "
            f"{str(row['passive_resistors_F']):<5} "
            f"{str(row['active_functional_blocks_F']):<5} "
            f"{fmt(row['runtime_s_F'], '.3f')}"
        )
    print("\nFINAL STATUS:")
    print(summary["verdict"])
    print(summary["fairness"])
    print(summary["layer_factorization_note"])
    print(f"\nWrote {REPORT_PATH}")
    for path in plots.values():
        print(f"Wrote {path}")


def public_rows(rows: list[dict]) -> list[dict]:
    out = []
    for row in rows:
        arches = {}
        for key, block in row["architectures"].items():
            arches[key] = {
                k: v
                for k, v in block.items()
                if k not in {"nominal_netlist", "nominal_catalog"}
            }
        out.append(
            {
                "id": row["id"],
                "label": row["label"],
                "n_test": row["n_test"],
                "n_sweep": row["n_sweep"],
                "hidden_preact_max": row["hidden_preact_max"],
                "hidden_relu_max": row["hidden_relu_max"],
                "architectures": arches,
            }
        )
    return out


def main() -> int:
    ngspice = find_ngspice()
    CIRCUIT_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    print("Physical AI - Experiment 13")
    print("PRECISION-PRESERVING PHYSICAL ARCHITECTURES")
    print("Analysis type: behavioral circuit analysis")
    print("Not transistor-level. Not PCB/silicon feasibility.")
    print(f"ngspice: {ngspice}")
    print(f"resistor window: {R_MIN:g} .. {R_MAX:g} Ohm")

    prior = load_prior()
    rows = [evaluate_pair(ngspice, spec_by_id(net_id)) for net_id in TEST_IDS]
    best = pick_best(rows)
    print(f"\nBest architecture so far: {best}", flush=True)
    attach_robustness(ngspice, rows, best)
    plots = make_plots(rows, best)
    summary = summarize(rows, prior, best)
    report = {
        "experiment": 13,
        "analysis": "behavioral circuit analysis",
        "error_limit": ERROR_LIMIT,
        "resistor_window_ohm": [R_MIN, R_MAX],
        "networks": public_rows(rows),
        "plots": plots,
        "summary": summary,
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print_final(rows, summary, plots)
    return 0 if summary["verdict"].endswith("IMPROVED") else 1


if __name__ == "__main__":
    sys.exit(main())
