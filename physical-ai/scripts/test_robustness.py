"""Physical AI - Experiment 7: hardware-tolerance robustness of frozen XOR.

Models manufacturing variation of compiled weight/bias resistors and small
input-voltage noise. This is physical component tolerance, not software
regularization. The Experiment 6 model and compiler stay frozen.

    R_perturbed = R_nominal * (1 + u),  u ~ Uniform[-tol, +tol]
    Vin_noisy   = Vin_logical + N(0, sigma^2)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from compile_xor import (
    CIRCUIT_PATH,
    CLASS_THRESHOLD,
    PROJECT_ROOT,
    XOR_X,
    XOR_Y,
    apply_resistor_values,
    classify,
    find_ngspice,
    generate_circuit,
    load_model,
    run_ngspice,
    software_forward,
)
RESULTS_DIR = PROJECT_ROOT / "results"
ROBUST_CIRCUIT = PROJECT_ROOT / "circuits" / "generated_xor_robust.cir"
REPORT_PATH = RESULTS_DIR / "robustness_report.json"
ACCURACY_PLOT = RESULTS_DIR / "robustness_accuracy.png"
ERROR_PLOT = RESULTS_DIR / "robustness_error.png"

SEED = 7
N_TRIALS = 100
RESISTOR_TOLERANCES = (0.0, 0.01, 0.05, 0.10)
INPUT_SIGMAS = (0.0, 0.001, 0.010)
COMBINED_TOLERANCE = 0.05
COMBINED_SIGMA = 0.010


def extract_all(text: str, name: str) -> list[float]:
    import re

    escaped = re.escape(name)
    pattern = (
        rf"{escaped}\s*=\s*"
        rf"([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)"
    )
    return [float(m.group(1)) for m in re.finditer(pattern, text, flags=re.IGNORECASE)]


def margin(output: float, expected_class: int) -> float:
    """Positive if on the correct side of 0.5, negative if misclassified."""
    if expected_class == 1:
        return output - CLASS_THRESHOLD
    return CLASS_THRESHOLD - output


def sample_resistor_values(
    catalog: list[dict],
    tolerance: float,
    rng: np.random.Generator,
) -> dict[str, float]:
    values: dict[str, float] = {}
    for item in catalog:
        nominal = float(item["R"])
        u = float(rng.uniform(-tolerance, tolerance)) if tolerance > 0 else 0.0
        values[str(item["name"])] = nominal * (1.0 + u)
    return values


def four_input_control(inputs: np.ndarray) -> str:
    lines = [".control", "set numdgt=15"]
    for x in inputs:
        lines.append(f"alter Vin1 DC {float(x[0]):.15g}")
        lines.append(f"alter Vin2 DC {float(x[1]):.15g}")
        lines.append("op")
        lines.append("print v(o1lin)")
    lines.extend([".endc", "", ".end", ""])
    return "\n".join(lines)


def simulate_four_inputs(
    ngspice: Path,
    base_netlist: str,
    r_values: dict[str, float],
    inputs: np.ndarray,
    dest: Path | None = None,
) -> np.ndarray:
    """One ngspice process, four input voltage pairs, perturbed resistors."""
    path = dest or ROBUST_CIRCUIT
    head, sep, _tail = base_netlist.partition(".control")
    if not sep:
        raise RuntimeError("generated netlist has no .control section")
    net = apply_resistor_values(head, r_values)
    net = net.rstrip() + "\n" + four_input_control(inputs)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(net, encoding="utf-8")
    result = run_ngspice(ngspice, path)
    text = f"{result.stdout or ''}\n{result.stderr or ''}"
    if result.returncode != 0:
        raise RuntimeError(f"ngspice failed:\n{text}")
    ys = extract_all(text, "v(o1lin)")
    if len(ys) != 4:
        raise RuntimeError(f"expected 4 v(o1lin) values, got {len(ys)}\n{text}")
    return np.array(ys, dtype=float)


def summarize(
    physical: np.ndarray,
    software: np.ndarray,
    expected_cls: np.ndarray,
) -> dict:
    physical = physical.reshape(-1)
    software = software.reshape(-1)
    expected_cls = expected_cls.reshape(-1)
    pred = np.array([classify(float(y)) for y in physical], dtype=int)
    errors = np.abs(physical - software)
    margins = np.array(
        [margin(float(y), int(c)) for y, c in zip(physical, expected_cls)],
        dtype=float,
    )
    n_fail = int(np.sum(pred != expected_cls))
    n = physical.size
    min_i = int(np.argmin(margins))
    return {
        "n_evaluations": n,
        "accuracy": float(1.0 - n_fail / n),
        "n_failures": n_fail,
        "failure_rate": float(n_fail / n),
        "mae": float(np.mean(errors)),
        "rmse": float(np.sqrt(np.mean(errors**2))),
        "max_abs_error": float(np.max(errors)),
        "min_margin": float(np.min(margins)),
        "max_margin": float(np.max(margins)),
        "smallest_margin_input": XOR_X[min_i % 4].tolist(),
        "smallest_margin_index": min_i,
    }


def run_condition(
    ngspice: Path,
    base_netlist: str,
    catalog: list[dict],
    software: np.ndarray,
    expected_cls: np.ndarray,
    tolerance: float,
    sigma: float,
    n_trials: int,
    rng: np.random.Generator,
    name: str,
    dest: Path | None = None,
) -> tuple[dict, dict | None]:
    """Monte Carlo over resistor tolerance and optional input noise."""
    all_y: list[np.ndarray] = []
    worst: dict | None = None
    worst_score = -1.0

    for trial in range(n_trials):
        r_values = sample_resistor_values(catalog, tolerance, rng)
        if sigma > 0:
            noise = rng.normal(0.0, sigma, size=XOR_X.shape)
            inputs = XOR_X + noise
        else:
            inputs = XOR_X
        y_ph = simulate_four_inputs(ngspice, base_netlist, r_values, inputs, dest=dest)
        all_y.append(y_ph)

        pred = np.array([classify(float(y)) for y in y_ph], dtype=int)
        errors = np.abs(y_ph - software)
        n_fail = int(np.sum(pred != expected_cls))
        score = n_fail * 10.0 + float(np.max(errors))
        if score > worst_score:
            worst_score = score
            worst_i = int(np.argmax(errors))
            worst = {
                "condition": name,
                "master_seed": SEED,
                "trial_index": trial,
                "tolerance": tolerance,
                "input_noise_sigma": sigma,
                "input_vector": XOR_X[worst_i].tolist(),
                "software_output": float(software[worst_i]),
                "physical_output": float(y_ph[worst_i]),
                "output_error": float(errors[worst_i]),
                "expected_class": int(expected_cls[worst_i]),
                "physical_class": int(pred[worst_i]),
                "trial_outputs": [float(v) for v in y_ph],
            }

        if (trial + 1) % 20 == 0 or trial == 0:
            print(
                f"  {name}: trial {trial + 1}/{n_trials}",
                flush=True,
            )

    stacked = np.vstack(all_y)
    stats = summarize(stacked, np.tile(software, n_trials), np.tile(expected_cls, n_trials))
    stats.update(
        {
            "name": name,
            "resistor_tolerance": tolerance,
            "input_noise_sigma": sigma,
            "n_trials": n_trials,
        }
    )
    return stats, worst


ROBUSTNESS_JOBS = (
    [("resistor_0pct", 0.0, 0.0)]
    + [(f"resistor_{int(100 * t)}pct", t, 0.0) for t in RESISTOR_TOLERANCES if t > 0]
    + [(f"noise_{int(1000 * s)}mV", 0.0, s) for s in INPUT_SIGMAS if s > 0]
    + [("res5_noise10mV", COMBINED_TOLERANCE, COMBINED_SIGMA)]
)


def run_robustness_campaign(
    ngspice: Path,
    base_netlist: str,
    catalog: list[dict],
    software: np.ndarray,
    expected_cls: np.ndarray,
    *,
    n_trials: int = N_TRIALS,
    seed: int = SEED,
    dest: Path | None = None,
) -> tuple[list[dict], dict | None]:
    """Same Experiment 7 sweep; optional dest keeps the XOR netlist untouched."""
    rng = np.random.default_rng(seed)
    conditions: list[dict] = []
    worst_global: dict | None = None
    worst_score = -1.0
    for name, tol, sigma in ROBUSTNESS_JOBS:
        print(f"=== {name}: tolerance={100 * tol:.0f}%, sigma={sigma} V ===")
        stats, worst = run_condition(
            ngspice,
            base_netlist,
            catalog,
            software,
            expected_cls,
            tol,
            sigma,
            n_trials,
            rng,
            name,
            dest=dest,
        )
        conditions.append(stats)
        print(
            f"  accuracy={stats['accuracy'] * 100:.2f}%  "
            f"fail={stats['n_failures']}/{stats['n_evaluations']}  "
            f"mae={stats['mae']:.3e}  max|e|={stats['max_abs_error']:.3e}  "
            f"min_margin={stats['min_margin']:.4f}"
        )
        print()
        if worst is not None:
            flipped = worst["expected_class"] != worst["physical_class"]
            score = (1 if flipped else 0) * 10 + worst["output_error"]
            if score > worst_score:
                worst_score = score
                worst_global = worst
    return conditions, worst_global


def plot_accuracy(conditions: list[dict]) -> None:
    res_only = [c for c in conditions if c["input_noise_sigma"] == 0.0]
    fig, ax = plt.subplots(figsize=(8.0, 4.8))
    xs = [100.0 * c["resistor_tolerance"] for c in res_only]
    ys = [100.0 * c["accuracy"] for c in res_only]
    ax.plot(xs, ys, "o-", lw=2, label="Resistor tolerance only")
    combined = [c for c in conditions if c["name"] == "res5_noise10mV"]
    if combined:
        ax.scatter(
            [100.0 * combined[0]["resistor_tolerance"]],
            [100.0 * combined[0]["accuracy"]],
            s=90,
            zorder=3,
            label="5% resistors + 10 mV input noise",
        )
    noise_only = [
        c
        for c in conditions
        if c["resistor_tolerance"] == 0.0 and c["input_noise_sigma"] > 0
    ]
    for c in noise_only:
        ax.scatter(
            [0.0],
            [100.0 * c["accuracy"]],
            marker="D",
            zorder=3,
            label=f"Nominal R + {1000 * c['input_noise_sigma']:.0f} mV noise",
        )
    ax.set_xlabel("Resistor tolerance (%)")
    ax.set_ylabel("Physical classification accuracy (%)")
    ax.set_title("Physical AI - Experiment 7: accuracy vs hardware variation")
    ax.set_ylim(-2, 105)
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(ACCURACY_PLOT, dpi=150)
    plt.close(fig)


def plot_error(conditions: list[dict]) -> None:
    res_only = [c for c in conditions if c["input_noise_sigma"] == 0.0]
    fig, ax = plt.subplots(figsize=(8.0, 4.8))
    xs = [100.0 * c["resistor_tolerance"] for c in res_only]
    ax.plot(xs, [c["mae"] for c in res_only], "o-", lw=2, label="MAE")
    ax.plot(xs, [c["max_abs_error"] for c in res_only], "s--", lw=2, label="Max |error|")
    combined = [c for c in conditions if c["name"] == "res5_noise10mV"]
    if combined:
        ax.scatter(
            [5.0],
            [combined[0]["mae"]],
            s=80,
            zorder=3,
            label="5%+10mV MAE",
        )
        ax.scatter(
            [5.0],
            [combined[0]["max_abs_error"]],
            s=80,
            marker="D",
            zorder=3,
            label="5%+10mV max |error|",
        )
    ax.set_xlabel("Resistor tolerance (%)")
    ax.set_ylabel("Output error vs frozen software model")
    ax.set_title("Physical AI - Experiment 7: analog error vs hardware variation")
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(ERROR_PLOT, dpi=150)
    plt.close(fig)


def restore_nominal_circuit(w1, b1, w2, b2) -> None:
    net, _ = generate_circuit(XOR_X[0], w1, b1, w2, b2)
    CIRCUIT_PATH.write_text(net, encoding="utf-8")


def main() -> int:
    print("PHYSICAL AI EXPERIMENT 7")
    print("Hardware tolerance of the frozen Experiment 6 XOR circuit")
    print()
    print("This models manufacturing variation of compiled resistors")
    print("and analog input-voltage noise. Weights are not retrained.")
    print()
    print(f"seed: {SEED}")
    print(f"trials per condition: {N_TRIALS}")
    print(f"class threshold: {CLASS_THRESHOLD}")
    print()

    try:
        model = load_model()
        ngspice = find_ngspice()
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    w1, b1, w2, b2 = model["W1"], model["b1"], model["W2"], model["b2"]
    software = np.array(
        [software_forward(x, w1, b1, w2, b2) for x in XOR_X], dtype=float
    )
    expected_cls = np.array([classify(float(y)) for y in software], dtype=int)

    print("Frozen software reference:")
    for x, y, c, t in zip(XOR_X, software, expected_cls, XOR_Y):
        print(f"  {x.tolist()} -> y={y:.6f} class={c} target={t}")
    print()

    base_netlist, catalog = generate_circuit(XOR_X[0], w1, b1, w2, b2)
    print(f"Compiled weight/bias resistors: {len(catalog)}")
    print()

    print("=== Nominal baseline (0% tolerance, 0 V noise) ===")
    try:
        y_nom = simulate_four_inputs(ngspice, base_netlist, {}, XOR_X)
    except (OSError, RuntimeError) as exc:
        print(f"ERROR: nominal circuit failed: {exc}", file=sys.stderr)
        restore_nominal_circuit(w1, b1, w2, b2)
        return 1

    nom_cls = np.array([classify(float(y)) for y in y_nom], dtype=int)
    nom_stats = summarize(y_nom, software, expected_cls)
    print(f"{'Input':<10} {'Software':>10} {'Physical':>10} {'Scls':>5} {'Pcls':>5}")
    for x, ys, yp, sc, pc in zip(XOR_X, software, y_nom, expected_cls, nom_cls):
        print(
            f"{str(x.tolist()):<10} {ys:10.6f} {yp:10.6f} {sc:5d} {pc:5d}"
        )
    print(f"Nominal accuracy: {nom_stats['accuracy'] * 100:.0f}%")
    print()

    expected_map = {(0, 0): 0, (0, 1): 1, (1, 0): 1, (1, 1): 0}
    for x, pc in zip(XOR_X, nom_cls):
        key = (int(x[0]), int(x[1]))
        if pc != expected_map[key]:
            print("NOMINAL CIRCUIT FAILED")
            print("Not continuing Monte Carlo; Experiment 6 circuit is broken.")
            restore_nominal_circuit(w1, b1, w2, b2)
            return 1

    conditions, worst_global = run_robustness_campaign(
        ngspice,
        base_netlist,
        catalog,
        software,
        expected_cls,
    )

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    plot_accuracy(conditions)
    plot_error(conditions)

    report = {
        "experiment": 7,
        "seed": SEED,
        "n_trials": N_TRIALS,
        "model": str(PROJECT_ROOT / "models" / "xor_model.npz"),
        "class_threshold": CLASS_THRESHOLD,
        "n_compiled_resistors": len(catalog),
        "note": (
            "Resistor draws model manufacturing tolerance of compiled "
            "weight/bias conductances. Input noise models analog voltage error. "
            "The XOR model was not retrained."
        ),
        "nominal": {
            **nom_stats,
            "physical_outputs": [float(v) for v in y_nom],
            "software_outputs": [float(v) for v in software],
        },
        "conditions": conditions,
        "worst_case": worst_global,
        "plots": {
            "accuracy": str(ACCURACY_PLOT),
            "error": str(ERROR_PLOT),
        },
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    restore_nominal_circuit(w1, b1, w2, b2)

    def cond(name: str) -> dict:
        return next(c for c in conditions if c["name"] == name)

    print("PHYSICAL AI EXPERIMENT 7")
    print("========================")
    print()
    print("Nominal:")
    print(f"accuracy = {nom_stats['accuracy'] * 100:.2f}%")
    print()
    for label, key in (
        ("1% resistor tolerance", "resistor_1pct"),
        ("5% resistor tolerance", "resistor_5pct"),
        ("10% resistor tolerance", "resistor_10pct"),
        ("5% tolerance + 10mV input noise", "res5_noise10mV"),
    ):
        c = cond(key)
        print(f"{label}:")
        print(f"accuracy = {c['accuracy'] * 100:.2f}%")
        print(f"failure rate = {c['failure_rate'] * 100:.2f}%")
        print(f"max error = {c['max_abs_error']:.6e}")
        print()

    print("Worst case:")
    if worst_global:
        w = worst_global
        print(f"  master seed: {w['master_seed']}")
        print(f"  trial index: {w['trial_index']}")
        print(f"  condition: {w['condition']}")
        print(f"  tolerance: {100 * w['tolerance']:.1f}%")
        print(f"  input noise: {w['input_noise_sigma']} V")
        print(f"  input vector: {w['input_vector']}")
        print(f"  software output: {w['software_output']:.6f}")
        print(f"  physical output: {w['physical_output']:.6f}")
        print(f"  output error: {w['output_error']:.6e}")
        print(f"  expected class: {w['expected_class']}")
        print(f"  physical class: {w['physical_class']}")
    print()
    print(f"Wrote {REPORT_PATH}")
    print(f"Wrote {ACCURACY_PLOT}")
    print(f"Wrote {ERROR_PLOT}")
    print()

    any_limit = any(
        c["n_failures"] > 0
        for c in conditions
        if c["resistor_tolerance"] > 0 or c["input_noise_sigma"] > 0
    )
    if any_limit:
        print("ROBUSTNESS LIMIT FOUND")
        print("Classification failed under at least one hardware-variation condition.")
        print("The frozen network was not modified to hide that limit.")
    else:
        print("ROBUSTNESS TEST PASSED")
        print("All tested tolerances and noise levels kept 100% XOR accuracy.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
