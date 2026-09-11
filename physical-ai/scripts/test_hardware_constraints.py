"""Experiment 10: hardware-constrained Matter Compiler.

Uses frozen Experiment 9 models A and F. Weights are not edited.
Resistor values are never clipped. SPICE is the physical source of truth.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from benchmark_scaling import (
    MATCH_TOL,
    N_ROBUST_INPUTS,
    N_ROBUST_TRIALS,
    N_TEST,
    NETWORKS,
    ROBUST_TOLERANCE,
    classification_labels,
    error_stats,
    generate_inputs,
    make_rng,
    simulate_batch,
    software_forward_batch,
)
from compile_xor import PROJECT_ROOT, find_ngspice, run_ngspice
from hardware_constrained_compiler import (
    BASELINE_G,
    CIRCUIT_DIR,
    CONSTRAINT_SETS,
    HardwareConfig,
    compile_baseline,
    compile_hardware,
    config_public,
    current_cost_estimate,
    feasibility_report,
    iter_hardware_grid,
    load_frozen_model,
    range_violation,
)
from matter_compiler import physical_cost, total_conductance
from test_robustness import extract_all, sample_resistor_values


RESULTS_DIR = PROJECT_ROOT / "results"
REPORT_PATH = RESULTS_DIR / "hardware_constraints_report.json"
PLOT_PATH = RESULTS_DIR / "hardware_constraints_comparison.png"
N_SEARCH = 8
TEST_IDS = ("A", "F")


def spec_by_id(net_id: str) -> dict:
    for spec in NETWORKS:
        if spec["id"] == net_id:
            return spec
    raise KeyError(net_id)


def resistor_stats(catalog: list[dict]) -> dict:
    rs = [float(item["R"]) for item in catalog]
    weights = [float(item["R"]) for item in catalog if item.get("role") == "weight"]
    biases = [float(item["R"]) for item in catalog if item.get("role") == "bias"]
    return {
        "n_resistors": len(catalog),
        "r_min": min(rs) if rs else None,
        "r_max": max(rs) if rs else None,
        "r_mean": float(np.mean(rs)) if rs else None,
        "weight_r_min": min(weights) if weights else None,
        "weight_r_max": max(weights) if weights else None,
        "bias_r_min": min(biases) if biases else None,
        "bias_r_max": max(biases) if biases else None,
        "total_conductance": total_conductance(catalog) if catalog else None,
    }


def evaluate_netlist(
    ngspice: Path,
    netlist: str,
    catalog: list[dict],
    spec: dict,
    inputs: np.ndarray,
    software: np.ndarray,
    dest: Path,
    r_min: float | None = None,
    r_max: float | None = None,
) -> dict:
    violation = None
    if r_min is not None and r_max is not None:
        violation = range_violation(catalog, r_min, r_max)
    record = {
        **resistor_stats(catalog),
        "constraints_satisfied": violation is None,
        "reject_reason": violation,
        "failed": False,
        "failure_reason": None,
        "spice_runtime_s": None,
    }
    if violation is not None:
        record["failed"] = True
        record["failure_reason"] = violation
        return record
    physical, runtime, spice_err, _log = simulate_batch(
        ngspice, netlist, inputs, spec["n_out"], dest
    )
    record["spice_runtime_s"] = runtime
    if spice_err or physical is None:
        record["failed"] = True
        record["failure_reason"] = spice_err or "no physical outputs"
        return record
    stats = error_stats(physical, software)
    pred = classification_labels(physical)
    expected = classification_labels(software)
    n_fail = int(np.sum(pred != expected))
    acc = float(1.0 - n_fail / max(len(expected), 1))
    record.update(
        {
            "mae": stats["mae"],
            "rms": stats["rms"],
            "max_abs_error": stats["max_abs_error"],
            "accuracy": acc,
            "n_class_failures": n_fail,
            "matched_software": stats["max_abs_error"] <= MATCH_TOL,
            "score": physical_cost(
                acc,
                n_fail,
                stats["mae"],
                stats["max_abs_error"],
                float(record["total_conductance"] or 0.0),
                int(record["n_resistors"]),
                rejected=False,
            ),
        }
    )
    return record


def measure_source_current(
    ngspice: Path,
    netlist: str,
    x: np.ndarray,
    dest: Path,
) -> float | None:
    head, sep, _tail = netlist.partition(".control")
    if not sep:
        return None
    lines = [".control", "set numdgt=15"]
    for i, xi in enumerate(np.atleast_1d(x), start=1):
        lines.append(f"alter Vin{i} DC {float(xi):.15g}")
    lines.append("op")
    n_in = int(np.atleast_1d(x).size)
    for i in range(1, n_in + 1):
        lines.append(f"print i(Vin{i})")
    lines.append("print i(Vref)")
    lines.extend([".endc", "", ".end", ""])
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(head.rstrip() + "\n" + "\n".join(lines), encoding="utf-8")
    result = run_ngspice(ngspice, dest)
    text = f"{result.stdout or ''}\n{result.stderr or ''}"
    if result.returncode != 0:
        return None
    currents = []
    for i in range(1, n_in + 1):
        currents.extend(extract_all(text, f"i(vin{i})"))
    currents.extend(extract_all(text, "i(vref)"))
    if not currents:
        return None
    return float(np.sum(np.abs(currents)))


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
    rng = make_rng("hw10", spec["id"], tag)
    expected = classification_labels(software)
    maes, maxes, accs = [], [], []
    failures = 0
    t0 = time.perf_counter()
    for trial in range(N_ROBUST_TRIALS):
        values = sample_resistor_values(catalog, ROBUST_TOLERANCE, rng)
        physical, _runtime, spice_err, _log = simulate_batch(
            ngspice, netlist, subset_x, spec["n_out"], dest, r_values=values
        )
        if spice_err or physical is None:
            failures += 1
            continue
        stats = error_stats(physical, software)
        pred = classification_labels(physical)
        maes.append(stats["mae"])
        maxes.append(stats["max_abs_error"])
        accs.append(float(np.mean(pred == expected)))
        if (trial + 1) % 25 == 0 or trial == 0:
            print(
                f"        robustness {tag} {trial + 1}/{N_ROBUST_TRIALS} "
                f"MAE={stats['mae']:.4e}",
                flush=True,
            )
    runtime = time.perf_counter() - t0
    if not maes:
        return {
            "tolerance": ROBUST_TOLERANCE,
            "n_trials": N_ROBUST_TRIALS,
            "n_inputs": int(len(subset_x)),
            "n_spice_failures": failures,
            "spice_runtime_s": runtime,
            "failed": True,
        }
    return {
        "tolerance": ROBUST_TOLERANCE,
        "n_trials": N_ROBUST_TRIALS,
        "n_inputs": int(len(subset_x)),
        "n_spice_failures": failures,
        "spice_runtime_s": runtime,
        "failed": False,
        "mae_mean": float(np.mean(maes)),
        "mae_max": float(np.max(maes)),
        "max_abs_error_mean": float(np.mean(maxes)),
        "max_abs_error_worst": float(np.max(maxes)),
        "accuracy_mean": float(np.mean(accs)),
        "accuracy_min": float(np.min(accs)),
    }


def search_constraint(
    ngspice: Path,
    spec: dict,
    weights: dict[str, np.ndarray],
    constraint: dict,
    search_x: np.ndarray,
    software_search: np.ndarray,
) -> dict:
    r_min, r_max = constraint["r_min"], constraint["r_max"]
    feas = feasibility_report(weights, r_min, r_max)
    grid = iter_hardware_grid(weights, r_min, r_max, constraint["name"])
    print(
        f"    {constraint['name']}: per-layer possible="
        f"{feas['per_layer_possible']} candidates={len(grid)}",
        flush=True,
    )
    if feas["impossible_groups"]:
        for item in feas["impossible_groups"]:
            print(f"      infeasible group: {item}", flush=True)

    dest = CIRCUIT_DIR / f"{spec['id']}_{constraint['name']}_search.cir"
    records = []
    best = None
    for cfg in grid:
        netlist, catalog, reason = compile_hardware(spec, weights, cfg)
        rec = {
            "config": config_public(cfg),
            "rejected": reason is not None,
            "reject_reason": reason,
            "n_resistors": len(catalog),
        }
        if reason is not None:
            rec["score"] = physical_cost(0.0, len(search_x), 0.0, 0.0, 0.0, 0, True)
            records.append(rec)
            continue
        physical, runtime, spice_err, _log = simulate_batch(
            ngspice, netlist, search_x, spec["n_out"], dest
        )
        rec["spice_runtime_s"] = runtime
        if spice_err or physical is None:
            rec["spice_error"] = spice_err or "no physical outputs"
            rec["score"] = physical_cost(0.0, len(search_x), 0.0, 0.0, 0.0, 0, True)
            records.append(rec)
            continue
        stats = error_stats(physical, software_search)
        pred = classification_labels(physical)
        expected = classification_labels(software_search)
        n_fail = int(np.sum(pred != expected))
        acc = float(1.0 - n_fail / max(len(expected), 1))
        g_total = total_conductance(catalog)
        score = physical_cost(
            acc, n_fail, stats["mae"], stats["max_abs_error"],
            g_total, len(catalog), rejected=False,
        )
        rec.update(
            {
                "mae": stats["mae"],
                "max_abs_error": stats["max_abs_error"],
                "accuracy": acc,
                "n_failures": n_fail,
                "total_conductance": g_total,
                "score": score,
            }
        )
        records.append(rec)
        if best is None or score < best["score"]:
            best = {
                **rec,
                "hardware_config": cfg,
                "catalog": catalog,
                "netlist": netlist,
            }
        print(
            f"      {cfg.mode} Gw1={cfg.g_weight_1:.3g} Gb1={cfg.g_bias_1:.3g} "
            f"Gw2={cfg.g_weight_2:.3g} Gb2={cfg.g_bias_2:.3g} "
            f"MAE={stats['mae']:.3e} score={score:.4g}",
            flush=True,
        )

    return {
        "constraint": constraint,
        "feasibility": feas,
        "n_candidates": len(grid),
        "n_spice_evaluated": sum(1 for r in records if r.get("mae") is not None),
        "n_rejected_range": sum(1 for r in records if r.get("rejected")),
        "candidates": [
            {k: v for k, v in r.items() if k not in {"catalog", "netlist", "hardware_config"}}
            for r in records
        ],
        "best": best,
    }


def evaluate_network(ngspice: Path, spec: dict) -> dict:
    weights = load_frozen_model(spec["id"])
    x_all = generate_inputs(spec["n_in"], N_TEST, spec["id"])
    x_search = x_all[:N_SEARCH]
    x_robust = x_all[:N_ROBUST_INPUTS]
    y_all = software_forward_batch(
        x_all, weights["W1"], weights["b1"], weights["W2"], weights["b2"]
    )
    y_search = software_forward_batch(
        x_search, weights["W1"], weights["b1"], weights["W2"], weights["b2"]
    )
    y_robust = software_forward_batch(
        x_robust, weights["W1"], weights["b1"], weights["W2"], weights["b2"]
    )

    print(f"\n=== {spec['id']} {spec['n_in']}->{spec['n_hidden']}->{spec['n_out']} ===")
    print("  frozen model:", f"models/scaling/{spec['id']}.npz")

    base_net, base_cat = compile_baseline(spec, weights)
    base_dest = CIRCUIT_DIR / f"{spec['id']}_baseline.cir"
    print("  baseline Exp 9 mapping G=1e-5 (unconstrained)")
    baseline = evaluate_netlist(
        ngspice, base_net, base_cat, spec, x_all, y_all, base_dest
    )
    baseline["mapping"] = f"unified G_SCALE={BASELINE_G:g}"
    baseline["would_satisfy_constraints"] = {
        c["name"]: range_violation(base_cat, c["r_min"], c["r_max"]) is None
        for c in CONSTRAINT_SETS
    }
    baseline["current_cost"] = current_cost_estimate(
        base_cat,
        measure_source_current(
            ngspice, base_net, x_all[0], CIRCUIT_DIR / f"{spec['id']}_baseline_i.cir"
        ),
    )
    print(
        f"    R=[{baseline['r_min']:.3e}, {baseline['r_max']:.3e}] "
        f"SigmaG={baseline['total_conductance']:.4e} "
        f"MAE={baseline.get('mae')} max={baseline.get('max_abs_error')}",
        flush=True,
    )
    print("  baseline robustness")
    baseline["robustness"] = run_robustness(
        ngspice, spec, base_net, base_cat, x_robust, y_robust,
        CIRCUIT_DIR / f"{spec['id']}_baseline_robust.cir",
        "baseline",
    )

    constrained = []
    for constraint in CONSTRAINT_SETS:
        search = search_constraint(
            ngspice, spec, weights, constraint, x_search, y_search
        )
        best = search.pop("best")
        row = {
            "constraint": constraint,
            "search": search,
            "found_valid_mapping": False,
            "constraints_satisfied": False,
        }
        if best is None:
            row["limit"] = (
                "No candidate respected the resistor window under separate "
                "bias scaling and optional per-layer G_WEIGHT/G_BIAS. "
                "Resistors were not clipped."
            )
            print(f"    LIMIT: no valid mapping for {constraint['name']}")
            constrained.append(row)
            continue

        cfg: HardwareConfig = best["hardware_config"]
        dest = CIRCUIT_DIR / f"{spec['id']}_{constraint['name']}.cir"
        dest.write_text(best["netlist"], encoding="utf-8")
        print(f"    verifying winner {cfg.label()}")
        verified = evaluate_netlist(
            ngspice, best["netlist"], best["catalog"], spec, x_all, y_all,
            dest, r_min=cfg.r_min, r_max=cfg.r_max,
        )
        verified["mapping"] = cfg.label()
        verified["config"] = config_public(cfg)
        verified["current_cost"] = current_cost_estimate(
            best["catalog"],
            measure_source_current(
                ngspice, best["netlist"], x_all[0],
                CIRCUIT_DIR / f"{spec['id']}_{constraint['name']}_i.cir",
            ),
        )
        verified["circuit_path"] = str(dest.relative_to(PROJECT_ROOT)).replace("\\", "/")
        print(
            f"      satisfied={verified['constraints_satisfied']} "
            f"MAE={verified.get('mae')} max={verified.get('max_abs_error')} "
            f"R=[{verified.get('r_min')}, {verified.get('r_max')}]",
            flush=True,
        )
        if verified.get("constraints_satisfied") and not verified.get("failed"):
            print("    constrained robustness")
            verified["robustness"] = run_robustness(
                ngspice, spec, best["netlist"], best["catalog"],
                x_robust, y_robust,
                CIRCUIT_DIR / f"{spec['id']}_{constraint['name']}_robust.cir",
                constraint["name"],
            )
        row.update(
            {
                "found_valid_mapping": bool(
                    verified.get("constraints_satisfied")
                    and not verified.get("failed")
                    and verified.get("matched_software")
                ),
                "constraints_satisfied": bool(verified.get("constraints_satisfied")),
                "result": verified,
            }
        )
        constrained.append(row)

    return {
        "id": spec["id"],
        "label": f"{spec['id']} {spec['n_in']}->{spec['n_hidden']}->{spec['n_out']}",
        "n_in": spec["n_in"],
        "n_hidden": spec["n_hidden"],
        "n_out": spec["n_out"],
        "n_test": N_TEST,
        "model_path": f"models/scaling/{spec['id']}.npz",
        "parameter_spans": feasibility_report(weights, 1e3, 1e6)["parameter_spans"],
        "baseline": baseline,
        "constrained": constrained,
    }


def make_plot(rows: list[dict]) -> None:
    labels = []
    rmax_b, rmax_t, rmax_r = [], [], []
    mae_b, mae_t, mae_r = [], [], []
    g_b, g_t, g_r = [], [], []
    for row in rows:
        labels.append(row["id"])
        b = row["baseline"]
        rmax_b.append(b.get("r_max") or np.nan)
        mae_b.append(b.get("mae") or np.nan)
        g_b.append(b.get("total_conductance") or np.nan)
        tight = next(
            (c["result"] for c in row["constrained"] if c["constraint"]["name"] == "1k-1M" and "result" in c),
            {},
        )
        relax = next(
            (c["result"] for c in row["constrained"] if c["constraint"]["name"] == "10k-10M" and "result" in c),
            {},
        )
        rmax_t.append(tight.get("r_max") if tight.get("constraints_satisfied") else np.nan)
        rmax_r.append(relax.get("r_max") if relax.get("constraints_satisfied") else np.nan)
        mae_t.append(tight.get("mae") if tight.get("constraints_satisfied") else np.nan)
        mae_r.append(relax.get("mae") if relax.get("constraints_satisfied") else np.nan)
        g_t.append(tight.get("total_conductance") if tight.get("constraints_satisfied") else np.nan)
        g_r.append(relax.get("total_conductance") if relax.get("constraints_satisfied") else np.nan)

    x = np.arange(len(labels))
    width = 0.25
    fig, axes = plt.subplots(1, 3, figsize=(11.2, 4.2))
    series = (
        (axes[0], "R_max (Ohm)", [rmax_b, rmax_t, rmax_r], True),
        (axes[1], "MAE vs NumPy", [mae_b, mae_t, mae_r], True),
        (axes[2], "Sigma G (S)", [g_b, g_t, g_r], True),
    )
    names = ("baseline", "1k-1M", "10k-10M")
    colors = ("#4a4a4a", "#1f4e79", "#7a9e4e")
    for ax, ylabel, groups, logy in series:
        for i, (vals, name, color) in enumerate(zip(groups, names, colors)):
            ax.bar(x + (i - 1) * width, vals, width, label=name, color=color)
        ax.set_xticks(x, labels)
        ax.set_ylabel(ylabel)
        if logy:
            ax.set_yscale("log")
        ax.grid(True, axis="y", alpha=0.3)
    axes[0].legend(fontsize=8)
    fig.suptitle("Experiment 10: baseline vs hardware-constrained mappings")
    fig.tight_layout()
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(PLOT_PATH, dpi=140)
    plt.close(fig)


def fmt_range(lo, hi) -> str:
    if lo is None or hi is None:
        return "n/a"
    return f"{lo:.3e} .. {hi:.3e} Ohm"


def fmt_num(value, spec=".4e") -> str:
    if value is None:
        return "n/a"
    return format(value, spec)


def print_report(rows: list[dict]) -> None:
    print("\nEXPERIMENT 10")
    print("HARDWARE-CONSTRAINED MATTER COMPILER")
    for row in rows:
        print(f"\nNETWORK {row['label']}")
        b = row["baseline"]
        print("BASELINE:")
        print(f"  resistor range: {fmt_range(b.get('r_min'), b.get('r_max'))}")
        print(f"  total conductance: {fmt_num(b.get('total_conductance'))} S")
        print(f"  MAE: {fmt_num(b.get('mae'))}")
        print(f"  max error: {fmt_num(b.get('max_abs_error'))}")
        print(f"  accuracy: {fmt_num(b.get('accuracy'), '.4f')}")
        br = b.get("robustness") or {}
        print(
            f"  robustness: MAE_mean={fmt_num(br.get('mae_mean'))} "
            f"acc_mean={fmt_num(br.get('accuracy_mean'), '.4f')} "
            f"acc_min={fmt_num(br.get('accuracy_min'), '.4f')}"
        )
        cc = b.get("current_cost") or {}
        print(
            f"  relative current cost I_rel={fmt_num(cc.get('i_rel_A'))} A "
            f"(V_rep={cc.get('v_rep_V')} V); "
            f"SPICE |Isource|={fmt_num(cc.get('spice_source_current_A'))} A"
        )
        for item in row["constrained"]:
            name = item["constraint"]["name"]
            print(f"\nCONSTRAINED {name}:")
            if "result" not in item:
                print("  resistor range: no valid mapping")
                print("  total conductance: n/a")
                print("  MAE: n/a")
                print("  max error: n/a")
                print("  accuracy: n/a")
                print("  constraints satisfied: no")
                print(f"  limit: {item.get('limit')}")
                continue
            c = item["result"]
            print(f"  resistor range: {fmt_range(c.get('r_min'), c.get('r_max'))}")
            print(f"  total conductance: {fmt_num(c.get('total_conductance'))} S")
            print(f"  MAE: {fmt_num(c.get('mae'))}")
            print(f"  max error: {fmt_num(c.get('max_abs_error'))}")
            print(f"  accuracy: {fmt_num(c.get('accuracy'), '.4f')}")
            print(
                "  constraints satisfied: "
                + ("yes" if item.get("constraints_satisfied") else "no")
            )
            cr = c.get("robustness") or {}
            print(
                f"  robustness: MAE_mean={fmt_num(cr.get('mae_mean'))} "
                f"acc_mean={fmt_num(cr.get('accuracy_mean'), '.4f')} "
                f"acc_min={fmt_num(cr.get('accuracy_min'), '.4f')}"
            )
            cc = c.get("current_cost") or {}
            print(
                f"  relative current cost I_rel={fmt_num(cc.get('i_rel_A'))} A; "
                f"SPICE |Isource|={fmt_num(cc.get('spice_source_current_A'))} A"
            )
            if c.get("config"):
                print(f"  mapping: {c['config']['label']}")


def verdict(rows: list[dict]) -> dict:
    found = []
    limits = []
    for row in rows:
        for item in row["constrained"]:
            tag = f"{row['id']} {item['constraint']['name']}"
            if item.get("found_valid_mapping"):
                found.append(tag)
            else:
                limits.append(tag)
    if found:
        text = "EXPERIMENT 10 PASSED"
        detail = (
            "Hardware-constrained mappings exist for: "
            + ", ".join(found)
            + ("; limits recorded for: " + ", ".join(limits) if limits else "")
        )
    elif limits:
        text = "HARDWARE LIMIT FOUND"
        detail = (
            "No mapping in the searched scale family satisfied the resistor "
            "windows without changing frozen weights or clipping R."
        )
    else:
        text = "HARDWARE LIMIT FOUND"
        detail = "No constrained evaluations were produced."
    return {"verdict": text, "detail": detail, "successes": found, "limits": limits}


def main() -> int:
    ngspice = find_ngspice()
    CIRCUIT_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    print("Physical AI - Experiment 10: hardware-constrained Matter Compiler")
    print(f"ngspice: {ngspice}")
    print("Frozen models: models/scaling/{A,F}.npz")
    print("Transforms: separate G_WEIGHT/G_BIAS, optional per-layer scales")
    print("Resistors are never clipped.")

    rows = [evaluate_network(ngspice, spec_by_id(net_id)) for net_id in TEST_IDS]
    make_plot(rows)
    summary = verdict(rows)
    report = {
        "experiment": 10,
        "match_tolerance": MATCH_TOL,
        "baseline_g_scale": BASELINE_G,
        "constraint_sets": list(CONSTRAINT_SETS),
        "fairness": (
            "Frozen Experiment 9 weights. Only physical scales searched. "
            "No clipping, no Python output correction."
        ),
        "bias_compensation": (
            "Separate bias ammeter and CCCS gain k=G_WEIGHT/G_BIAS with "
            "Vref=1 V so V_b = b in SPICE."
        ),
        "networks": rows,
        "summary": summary,
        "plot": str(PLOT_PATH.relative_to(PROJECT_ROOT)).replace("\\", "/"),
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print_report(rows)
    print(f"\nWrote {REPORT_PATH}")
    print(f"Wrote {PLOT_PATH}")
    print("\n" + summary["verdict"])
    print(summary["detail"])
    return 0 if summary["successes"] else 1


if __name__ == "__main__":
    sys.exit(main())
