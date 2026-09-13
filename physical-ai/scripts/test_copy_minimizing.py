"""Experiment 16: copy-minimizing fabrics.

Frozen Experiment 9 networks A and F. Architectures D (baseline), I
(current-mode invert-and-TIA), M (matched subtractor). Weights are never
edited. SPICE outputs are never corrected in Python.

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
from copy_minimizing import (
    ARCH_KEYS,
    ARCH_PUBLIC,
    CIRCUIT_DIR,
    CopyParams,
    accounting,
    compile_copy,
)
from hardware_constrained_compiler import current_cost_estimate, load_frozen_model
from mismatch_fabric import sample_independent
from precision_architectures import software_reference
from test_hardware_constraints import measure_source_current, spec_by_id
from test_nonideal_network import class_margins


RESULTS_DIR = PROJECT_ROOT / "results"
REPORT_PATH = RESULTS_DIR / "copy_minimizing_report.json"
ERROR_LIMIT = 1.0e-3
TIMEOUT = 30.0
INPUT_NOISE = 0.001
N_F_SWEEP = 40
N_TRIALS = {"A": 20, "F": 15}
COPY_PCTS = (0.0, 0.1, 0.5, 1.0)
TEST_IDS = ("A", "F")


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
    inputs: np.ndarray,
    software: np.ndarray,
    path: Path,
    r_values: dict[str, float] | None = None,
) -> dict:
    physical, runtime, spice_err, log = simulate_batch(
        ngspice, netlist, inputs, spec["n_out"], path,
        r_values=r_values, timeout=TIMEOUT,
    )
    rec = {"failed": False, "failure_reason": None, "spice_runtime_s": runtime}
    if spice_err or physical is None:
        rec["failed"] = True
        rec["failure_reason"] = spice_err or "no physical outputs"
        rec["spice_log_tail"] = (log or "")[-400:]
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
) -> dict:
    rng = make_rng("exp16", spec["id"], seed_tag)
    maes, accs, mx, margins = [], [], [], []
    failures = 0
    expected = classification_labels(software)
    for trial in range(n_trials):
        values = sample_independent(catalog, 0.5, rng)
        noisy = inputs + rng.normal(0.0, INPUT_NOISE, size=inputs.shape)
        physical, _rt, spice_err, _log = simulate_batch(
            ngspice, netlist, noisy, spec["n_out"], path,
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
        if trial == 0 or (trial + 1) % 15 == 0:
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


def first_over(rows: list[dict]) -> dict | None:
    for rec in rows:
        mae = rec.get("mae", rec.get("mae_mean"))
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


def sweep_copy(
    ngspice: Path,
    spec: dict,
    weights: dict[str, np.ndarray],
    arch: str,
    inputs: np.ndarray,
    software: np.ndarray,
    field: str,
    values: tuple,
) -> list[dict]:
    rows = []
    for value in values:
        kwargs = {field: (value / 100.0 if field != "tia_vos" else value)}
        if field == "tia_vos":
            kwargs = {"tia_vos": value}
        params = CopyParams(name=f"{arch}_{field}_{value:g}", **kwargs)
        net, cat, reason = compile_copy(arch, spec, weights, params=params)
        rec = {
            "name": params.name,
            "value": value,
            "field": field,
            "failed": False,
            "failure_reason": reason,
            "params": params.public(),
        }
        if reason or net is None:
            rec["failed"] = True
            rows.append(rec)
            print(f"    {params.name} compile fail {reason}", flush=True)
            continue
        dest(spec["id"], arch, params.name).write_text(net, encoding="utf-8")
        rec.update(
            evaluate_netlist(
                ngspice, spec, net, inputs, software,
                dest(spec["id"], arch, params.name),
            )
        )
        print(
            f"    {params.name} MAE={rec.get('mae')} acc={rec.get('accuracy')}",
            flush=True,
        )
        rows.append(rec)
    return rows


def evaluate_arch(
    ngspice: Path,
    spec: dict,
    weights: dict[str, np.ndarray],
    arch: str,
    x_all: np.ndarray,
    y_all: np.ndarray,
    x_sw: np.ndarray,
    y_sw: np.ndarray,
    x_mc: np.ndarray,
    y_mc: np.ndarray,
    n_w: int,
    n_trials: int,
) -> dict:
    print(f"  architecture {arch}: {ARCH_PUBLIC[arch]['title']}", flush=True)
    net0, cat0, reason0 = compile_copy(arch, spec, weights)
    nom = {"failed": True, "failure_reason": reason0}
    if net0 is not None:
        dest(spec["id"], arch, "nominal").write_text(net0, encoding="utf-8")
        nom = evaluate_netlist(
            ngspice, spec, net0, x_all, y_all, dest(spec["id"], arch, "nominal")
        )
        nom.update(accounting(net0, cat0, n_w))
        source_i = measure_source_current(
            ngspice, net0, x_all[0], dest(spec["id"], arch, "nominal_i")
        )
        nom["current_cost"] = current_cost_estimate(cat0, source_i)
        nom["spice_source_current_A"] = source_i
    print(
        f"    nominal MAE={nom.get('mae')} nR={nom.get('passive_resistors')} "
        f"CCCS={nom.get('active_cccs')} VCVS={nom.get('active_vcvs')} "
        f"copies={nom.get('leftover_copy_blocks')} "
        f"fail={nom.get('failure_reason')}",
        flush=True,
    )

    print("    copy_common sweep", flush=True)
    common = sweep_copy(
        ngspice, spec, weights, arch, x_sw, y_sw, "copy_common", COPY_PCTS
    )
    print("    copy_polarity sweep", flush=True)
    polarity = sweep_copy(
        ngspice, spec, weights, arch, x_sw, y_sw, "copy_polarity", COPY_PCTS
    )
    print("    buffer leftover sweep", flush=True)
    buffer = sweep_copy(
        ngspice, spec, weights, arch, x_sw, y_sw, "buf_gain", COPY_PCTS
    )

    print("    combined 0.1% copies + 0.5% R MC", flush=True)
    params = CopyParams(
        name="combined",
        copy_common=0.001,
        copy_polarity=0.001,
        buf_gain=0.001,
        relu_vos=0.001,
    )
    netc, catc, reasonc = compile_copy(arch, spec, weights, params=params)
    if reasonc or netc is None:
        combined = {"failed": True, "failure_reason": reasonc}
    else:
        dest(spec["id"], arch, "combined").write_text(netc, encoding="utf-8")
        combined = run_mc(
            ngspice, spec, netc, catc, x_mc, y_mc,
            dest(spec["id"], arch, "combined"),
            n_trials, f"{spec['id']}{arch}comb",
        )
        combined["conditions"] = {
            "independent_resistor_pct": 0.5,
            "copy_common": 0.001,
            "copy_polarity": 0.001,
            "buf_gain": 0.001,
            "relu_vos_V": 0.001,
            "input_noise_V": INPUT_NOISE,
        }
    print(
        f"    combined MAE_mean={combined.get('mae_mean')} "
        f"acc={combined.get('accuracy_mean')}",
        flush=True,
    )

    return {
        "arch": arch,
        "title": ARCH_PUBLIC[arch]["title"],
        "copy_mechanism": ARCH_PUBLIC[arch]["copy_mechanism"],
        "nominal": nom,
        "copy_common": common,
        "copy_polarity": polarity,
        "buf_gain": buffer,
        "combined": combined,
        "first_crossings": {
            "copy_common": first_over(common),
            "copy_polarity": first_over(polarity),
            "buf_gain": first_over(buffer),
        },
    }


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
    arches = {}
    for arch in ARCH_KEYS:
        arches[arch] = evaluate_arch(
            ngspice, spec, weights, arch,
            x_all, y_all, x_sw, y_sw, x_mc, y_mc, n_w, n_trials,
        )
    return {
        "id": spec["id"],
        "label": f"{spec['id']} {spec['n_in']}->{spec['n_hidden']}->{spec['n_out']}",
        "n_full": n_full,
        "n_sweep": n_sw,
        "n_mc": n_mc,
        "n_trials": n_trials,
        "architectures": arches,
    }


def _mae_at(rows: list[dict], value: float) -> float | None:
    for rec in rows:
        if rec.get("failed"):
            continue
        if rec.get("value") == value and rec.get("mae") is not None:
            return rec["mae"]
    return None


def analyze(rows: list[dict]) -> dict:
    f = next(r for r in rows if r["id"] == "F")
    a = next(r for r in rows if r["id"] == "A")
    table = {}
    for net in (a, f):
        table[net["id"]] = {}
        for arch, block in net["architectures"].items():
            nom = block["nominal"]
            table[net["id"]][arch] = {
                "nominal_mae": nom.get("mae"),
                "leftover_copy_blocks": nom.get("leftover_copy_blocks"),
                "active_cccs": nom.get("active_cccs"),
                "n_unity_vcvs": nom.get("n_unity_vcvs"),
                "n_current_copies": nom.get("n_current_copies"),
                "closed_loop_opamps": nom.get("closed_loop_opamps"),
                "passive_resistors": nom.get("passive_resistors"),
                "copy_common_0.1": _mae_at(block["copy_common"], 0.1),
                "copy_polarity_0.1": _mae_at(block["copy_polarity"], 0.1),
                "buf_gain_0.1": _mae_at(block["buf_gain"], 0.1),
                "combined_mae": (block["combined"] or {}).get("mae_mean"),
                "combined_acc": (block["combined"] or {}).get("accuracy_mean"),
                "first_crossings": block["first_crossings"],
            }

    def score(arch: str) -> float:
        rec = table["F"][arch]
        vals = [
            rec.get("copy_common_0.1") or 0.0,
            rec.get("copy_polarity_0.1") or 0.0,
            rec.get("buf_gain_0.1") or 0.0,
        ]
        return max(vals)

    winner = min(ARCH_KEYS, key=score)
    d_worst = score("D")
    w_worst = score(winner)
    improved = winner != "D" and w_worst < d_worst * 0.5
    immune_notes = []
    for arch in ARCH_KEYS:
        rec = table["F"][arch]
        for field, label in (
            ("copy_common_0.1", "copy_common"),
            ("copy_polarity_0.1", "copy_polarity"),
            ("buf_gain_0.1", "buf_gain"),
        ):
            mae = rec.get(field)
            if mae is not None and mae <= ERROR_LIMIT:
                immune_notes.append(f"F-{arch} {label} 0.1% MAE={mae:.3e} under bar")
    return {
        "by_network": table,
        "winner_on_F_worst_0p1": winner,
        "F_D_worst_0p1": d_worst,
        "F_winner_worst_0p1": w_worst,
        "copy_minimizing_improved": bool(improved),
        "under_bar_at_0p1": immune_notes,
        "verdict": (
            "COPY-MINIMIZING ARCHITECTURE IMPROVED"
            if improved
            else "COPY FLOOR STILL SET BY LEFTOVER BLOCKS"
        ),
    }


def make_plots(rows: list[dict]) -> dict[str, str]:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    colors = {"D": "#1f4e79", "I": "#b85c38", "M": "#2e7d4f"}
    styles = {"A": "-", "F": "--"}

    fig, axes = plt.subplots(1, 2, figsize=(8.8, 4.2))
    for ax, net_id, title in (
        (axes[0], "A", "Network A leftover blocks"),
        (axes[1], "F", "Network F leftover blocks"),
    ):
        row = next(r for r in rows if r["id"] == net_id)
        labels = ["CCCS", "unity VCVS", "current copies", "closed-loop opamp"]
        x = np.arange(len(labels))
        w = 0.25
        for i, arch in enumerate(ARCH_KEYS):
            nom = row["architectures"][arch]["nominal"]
            ys = [
                nom.get("active_cccs") or 0,
                nom.get("n_unity_vcvs") or 0,
                nom.get("n_current_copies") or 0,
                nom.get("closed_loop_opamps") or 0,
            ]
            ax.bar(x + (i - 1) * w, ys, w, label=arch, color=colors[arch])
        ax.set_xticks(x, labels, rotation=15, ha="right")
        ax.set_ylabel("count")
        ax.set_title(title)
        ax.legend()
        ax.grid(True, axis="y", alpha=0.3)
    fig.tight_layout()
    p1 = RESULTS_DIR / "copy_minimizing_blocks.png"
    fig.savefig(p1, dpi=140)
    plt.close(fig)

    fig, axes = plt.subplots(1, 3, figsize=(10.6, 3.8))
    for ax, field, title in (
        (axes[0], "copy_common", "copy common / TIA open-loop"),
        (axes[1], "copy_polarity", "copy polarity / invert pair"),
        (axes[2], "buf_gain", "leftover unity VCVS"),
    ):
        for row in rows:
            for arch, block in row["architectures"].items():
                recs = block[field]
                xs = [r["value"] for r in recs if not r.get("failed") and r.get("mae") is not None]
                ys = [max(r["mae"], 1e-16) for r in recs if not r.get("failed") and r.get("mae") is not None]
                ax.plot(
                    xs, ys,
                    styles[row["id"]],
                    color=colors[arch],
                    marker="o",
                    label=f"{row['id']}-{arch}",
                    linewidth=1.8,
                )
        ax.axhline(ERROR_LIMIT, color="#a33", linestyle=":")
        ax.set_yscale("log")
        ax.set_xlabel("error (%)")
        ax.set_ylabel("MAE")
        ax.set_title(title)
        ax.grid(True, which="both", alpha=0.3)
    axes[2].legend(fontsize=7, loc="best")
    fig.suptitle("Experiment 16 leftover-copy sensitivity")
    fig.tight_layout()
    p2 = RESULTS_DIR / "copy_minimizing_sweeps.png"
    fig.savefig(p2, dpi=140)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8.2, 4.4))
    labels = [
        "nom", "common 0.1%", "polarity 0.1%", "buffer 0.1%", "comb 0.5%R",
    ]
    x = np.arange(len(labels))
    w = 0.12
    idx = 0
    for row in rows:
        for arch, block in row["architectures"].items():
            nom = block["nominal"].get("mae")
            c = _mae_at(block["copy_common"], 0.1)
            p = _mae_at(block["copy_polarity"], 0.1)
            b = _mae_at(block["buf_gain"], 0.1)
            comb = (block["combined"] or {}).get("mae_mean")
            ys = [nom, c, p, b, comb]
            ax.bar(
                x + (idx - 2.5) * w,
                [v if v is not None else np.nan for v in ys],
                w,
                label=f"{row['id']}-{arch}",
                color=colors[arch],
                alpha=0.55 if row["id"] == "A" else 0.95,
            )
            idx += 1
    ax.set_yscale("log")
    ax.set_xticks(x, labels, rotation=15, ha="right")
    ax.axhline(ERROR_LIMIT, color="#333", linestyle="--")
    ax.set_ylabel("MAE")
    ax.set_title("Experiment 16 comparison")
    ax.legend(fontsize=7, ncol=3)
    ax.grid(True, axis="y", alpha=0.3)
    fig.tight_layout()
    p3 = RESULTS_DIR / "copy_minimizing_comparison.png"
    fig.savefig(p3, dpi=140)
    plt.close(fig)

    return {
        "blocks": str(p1.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        "sweeps": str(p2.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        "comparison": str(p3.relative_to(PROJECT_ROOT)).replace("\\", "/"),
    }


def print_final(rows: list[dict], summary: dict, plots: dict) -> None:
    print("\n==================================================")
    print("EXPERIMENT 16")
    print("COPY-MINIMIZING FABRIC")
    print("==================================================")
    for row in rows:
        print(f"\nNETWORK {row['label']}")
        for arch, block in row["architectures"].items():
            nom = block["nominal"]
            print(
                f"  {arch}: MAE={fmt(nom.get('mae'))} "
                f"acc={fmt(nom.get('accuracy'), '.4f')} "
                f"nR={nom.get('passive_resistors')} "
                f"CCCS={nom.get('active_cccs')} "
                f"unityE={nom.get('n_unity_vcvs')} "
                f"copies={nom.get('leftover_copy_blocks')} "
                f"opamps={nom.get('closed_loop_opamps')}"
            )
            print(
                f"      0.1% common={fmt(_mae_at(block['copy_common'], 0.1))} "
                f"polarity={fmt(_mae_at(block['copy_polarity'], 0.1))} "
                f"buffer={fmt(_mae_at(block['buf_gain'], 0.1))} "
                f"comb={fmt((block['combined'] or {}).get('mae_mean'))} "
                f"acc={fmt((block['combined'] or {}).get('accuracy_mean'), '.4f')}"
            )
    print(f"\nWINNER ON F WORST 0.1%: {summary['winner_on_F_worst_0p1']}")
    print(f"F D worst 0.1% MAE: {fmt(summary['F_D_worst_0p1'])}")
    print(f"F winner worst 0.1% MAE: {fmt(summary['F_winner_worst_0p1'])}")
    print("UNDER BAR AT 0.1%:")
    for note in summary["under_bar_at_0p1"]:
        print(f"  {note}")
    print("\nFINAL STATUS:")
    print(summary["verdict"])
    print(f"\nWrote {REPORT_PATH}")
    for path in plots.values():
        print(f"Wrote {path}")


def main() -> int:
    ngspice = find_ngspice()
    CIRCUIT_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    print("Physical AI - Experiment 16")
    print("COPY-MINIMIZING FABRIC")
    print("Behavioral circuit analysis. Not transistor-level or PCB.")
    print(f"ngspice: {ngspice}")

    rows = [evaluate_network(ngspice, spec_by_id(net_id)) for net_id in TEST_IDS]
    plots = make_plots(rows)
    summary = analyze(rows)
    report = {
        "experiment": 16,
        "analysis": "copy-minimizing fabrics on Experiment 14 Architecture D encoding",
        "error_limit": ERROR_LIMIT,
        "fairness": (
            "Frozen Experiment 9 weights. No Python output correction. "
            "A finite-A feedback TIA was tried on Architecture I and "
            "rejected: the summing node sits at V/A and breaks unbuffered "
            "divider math (MAE scaled as ~1/A). I therefore uses a 0 V "
            "summing node plus one current dump onto physical R_IV. "
            "copy_polarity on M is ignored (one gain cannot unbalance). "
            "copy_polarity on I unbalances the invert-pair R2. "
            "Not layout. Not foundry PCM."
        ),
        "architectures": ARCH_PUBLIC,
        "networks": rows,
        "plots": plots,
        "summary": summary,
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print_final(rows, summary, plots)
    return 0


if __name__ == "__main__":
    sys.exit(main())
