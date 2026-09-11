"""Experiment 14: one-time layer / global calibration.

Calibration is a manufacturing/startup measurement in SPICE, then a
small number of constants are compiled into VCVS gains.

Not allowed: editing trained weights, per-input correction, or digitally
fixing each neural output after inference.

Modes
-----
none:     0 measurements, 0 constants (k1=k2=1)
global:   1 measurement (output-layer cal cell), 1 constant applied to
          both layers. Corrects a uniform process gain if ReLU sees a
          positive scale (relu(s*z) = s*relu(z) for s>0).
layer:    2 measurements, 2 constants (one per layer).

The cal cells are dedicated 1 V / R_IV paths. They are not the network
outputs. Expected v(calLlin) = 1.0 at nominal.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

from benchmark_scaling import (
    classification_labels,
    error_stats,
    generate_inputs,
    make_rng,
    simulate_batch,
)
from compile_xor import PROJECT_ROOT, apply_resistor_values, find_ngspice, run_ngspice
from hardware_constrained_compiler import load_frozen_model
from precision_architectures import software_reference
from ratiometric_compiler import CIRCUIT_DIR, VariationSpec, compile_ratiometric, sample_variation
from test_hardware_constraints import spec_by_id
from test_nonideal_network import class_margins
from test_robustness import extract_all


TIMEOUT = 20.0
ERROR_LIMIT = 1.0e-3
CAL_MODES = ("none", "global", "layer")


def measure_cal_gains(
    ngspice: Path,
    netlist: str,
    r_values: dict[str, float] | None,
    dest: Path,
) -> tuple[float, float, dict]:
    """SPICE measurement of dedicated cal cells. Vin and Vref held at 0."""
    head, sep, _tail = netlist.partition(".control")
    if not sep:
        raise RuntimeError("netlist has no .control section")
    body = apply_resistor_values(head, r_values or {})
    lines = [
        ".control",
        "set numdgt=15",
        "alter Vcal1 DC 1",
        "alter Vcal2 DC 1",
        "alter Vref DC 0",
    ]
    # Zero every Vin* present in the deck.
    for raw in head.splitlines():
        parts = raw.split()
        if parts and parts[0].startswith("Vin") and parts[0][3:].isdigit():
            lines.append(f"alter {parts[0]} DC 0")
    lines.extend(
        [
            "op",
            "print v(cal1lin)",
            "print v(cal2lin)",
            ".endc",
            "",
            ".end",
            "",
        ]
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(body.rstrip() + "\n" + "\n".join(lines), encoding="utf-8")
    result = run_ngspice(ngspice, dest, timeout=TIMEOUT)
    text = f"{result.stdout or ''}\n{result.stderr or ''}"
    if result.returncode != 0:
        return 1.0, 1.0, {
            "failed": True,
            "reason": f"ngspice exit {result.returncode}",
            "v_cal1": None,
            "v_cal2": None,
        }
    v1s = extract_all(text, "v(cal1lin)")
    v2s = extract_all(text, "v(cal2lin)")
    if not v1s or not v2s:
        return 1.0, 1.0, {
            "failed": True,
            "reason": "missing v(cal1lin)/v(cal2lin)",
            "v_cal1": None,
            "v_cal2": None,
        }
    v1, v2 = float(v1s[0]), float(v2s[0])
    meta = {"failed": False, "reason": None, "v_cal1": v1, "v_cal2": v2}
    if abs(v1) < 1e-9 or abs(v2) < 1e-9:
        meta["failed"] = True
        meta["reason"] = "calibration cell voltage near zero"
        return 1.0, 1.0, meta
    return 1.0 / v1, 1.0 / v2, meta


def constants_for_mode(mode: str, k1: float, k2: float) -> tuple[float, float, int, int]:
    """Return (k_layer1, k_layer2, n_measurements, n_constants)."""
    if mode == "none":
        return 1.0, 1.0, 0, 0
    if mode == "global":
        return k2, k2, 1, 1
    if mode == "layer":
        return k1, k2, 2, 2
    raise KeyError(mode)


def evaluate_calibrated(
    ngspice: Path,
    spec: dict,
    weights: dict[str, np.ndarray],
    inputs: np.ndarray,
    software: np.ndarray,
    dest: Path,
    mode: str,
    variation: VariationSpec | None,
    trial: int,
    scale_error: float = 0.0,
    i_leak: float = 0.0,
) -> dict:
    net0, catalog, reason = compile_ratiometric(
        "E", spec, weights, scale_error=scale_error, i_leak=i_leak
    )
    record: dict = {
        "mode": mode,
        "variation": None if variation is None else variation.label(),
        "failed": False,
        "failure_reason": None,
        "n_measurements": 0,
        "n_constants": 0,
        "k_layer1": 1.0,
        "k_layer2": 1.0,
    }
    if reason or net0 is None:
        record["failed"] = True
        record["failure_reason"] = reason
        return record

    r_values = None
    if variation is not None:
        rng = make_rng("exp14cal", spec["id"], variation.kind, variation.percent, trial)
        r_values = sample_variation(catalog, variation, rng)

    if mode == "none":
        k1, k2 = 1.0, 1.0
        n_meas, n_const = 0, 0
        cal_meta = {"failed": False, "v_cal1": None, "v_cal2": None, "skipped": True}
    else:
        k1_m, k2_m, cal_meta = measure_cal_gains(
            ngspice, net0, r_values, dest.with_name(dest.stem + "_meas.cir")
        )
        if cal_meta.get("failed"):
            record["failed"] = True
            record["failure_reason"] = cal_meta.get("reason")
            record["calibration"] = cal_meta
            return record
        k1, k2, n_meas, n_const = constants_for_mode(mode, k1_m, k2_m)

    net, catalog2, reason = compile_ratiometric(
        "E", spec, weights,
        scale_error=scale_error, i_leak=i_leak,
        k_layer1=k1, k_layer2=k2,
    )
    if reason or net is None:
        record["failed"] = True
        record["failure_reason"] = reason
        return record

    physical, runtime, spice_err, _log = simulate_batch(
        ngspice, net, inputs, spec["n_out"], dest,
        r_values=r_values, timeout=TIMEOUT,
    )
    record.update(
        {
            "n_measurements": n_meas,
            "n_constants": n_const,
            "k_layer1": k1,
            "k_layer2": k2,
            "calibration": cal_meta,
            "spice_runtime_s": runtime,
        }
    )
    if spice_err or physical is None:
        record["failed"] = True
        record["failure_reason"] = spice_err or "no physical outputs"
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
            "n_class_failures": n_fail,
            "min_margin": float(np.min(margins)),
            "exceeds_error_limit": err["mae"] > ERROR_LIMIT,
            "classification_ok": n_fail == 0,
        }
    )
    return record


def run_calibration_suite(
    ngspice: Path,
    networks: dict[str, dict],
    n_trials_random: int = 8,
) -> dict:
    """Compare none / global / layer under several variation conditions."""
    conditions = [
        ("nominal", None, 1),
        ("global_fixed_p5", VariationSpec("g5", "global", 5.0, fixed_delta=0.05), 1),
        ("global_fixed_p10", VariationSpec("g10", "global", 10.0, fixed_delta=0.10), 1),
        ("layer_5_local_0p5", VariationSpec("ly", "layer", 5.0, local_percent=0.5), n_trials_random),
        ("independent_5", VariationSpec("ind", "independent", 5.0), n_trials_random),
    ]
    out: dict[str, dict] = {}
    for net_id, bundle in networks.items():
        spec = bundle["spec"]
        weights = bundle["weights"]
        x = bundle["x_cal"]
        y = software_reference(
            x, weights["W1"], weights["b1"], weights["W2"], weights["b2"]
        )
        print(f"  calibration suite network {net_id}", flush=True)
        net_rows = {}
        for cond_name, var, n_trials in conditions:
            print(f"    {cond_name}", flush=True)
            modes = {}
            for mode in CAL_MODES:
                trials = []
                for t in range(n_trials):
                    dest = CIRCUIT_DIR / f"{net_id}_E_cal_{cond_name}_{mode}_{t}.cir"
                    rec = evaluate_calibrated(
                        ngspice, spec, weights, x, y, dest, mode, var, t
                    )
                    trials.append(rec)
                    if rec.get("failed"):
                        print(
                            f"      {mode} t{t} FAIL {rec.get('failure_reason')}",
                            flush=True,
                        )
                    elif t == 0 or n_trials == 1:
                        print(
                            f"      {mode} MAE={rec.get('mae')} "
                            f"k1={rec.get('k_layer1'):.6g} "
                            f"k2={rec.get('k_layer2'):.6g} "
                            f"meas={rec.get('n_measurements')}",
                            flush=True,
                        )
                ok = [r for r in trials if not r.get("failed") and r.get("mae") is not None]
                modes[mode] = {
                    "n_trials": n_trials,
                    "n_ok": len(ok),
                    "mae_mean": float(np.mean([r["mae"] for r in ok])) if ok else None,
                    "mae_max": float(np.max([r["mae"] for r in ok])) if ok else None,
                    "max_abs_error_mean": (
                        float(np.mean([r["max_abs_error"] for r in ok])) if ok else None
                    ),
                    "accuracy_mean": (
                        float(np.mean([r["accuracy"] for r in ok])) if ok else None
                    ),
                    "n_measurements": (ok[0]["n_measurements"] if ok else None),
                    "n_constants": (ok[0]["n_constants"] if ok else None),
                    "k_layer1_mean": (
                        float(np.mean([r["k_layer1"] for r in ok])) if ok else None
                    ),
                    "k_layer2_mean": (
                        float(np.mean([r["k_layer2"] for r in ok])) if ok else None
                    ),
                    "trials": trials if n_trials == 1 else [
                        {k: v for k, v in r.items() if k != "calibration"}
                        for r in trials
                    ],
                }
            net_rows[cond_name] = modes
        out[net_id] = net_rows
    return out


def main() -> int:
    from benchmark_scaling import N_TEST

    ngspice = find_ngspice()
    CIRCUIT_DIR.mkdir(parents=True, exist_ok=True)
    print("Physical AI - Experiment 14 (calibration only)")
    networks = {}
    for net_id in ("A", "F"):
        spec = spec_by_id(net_id)
        weights = load_frozen_model(net_id)
        n = N_TEST if net_id == "A" else 40
        x = generate_inputs(spec["n_in"], n, net_id)
        networks[net_id] = {"spec": spec, "weights": weights, "x_cal": x}
    suite = run_calibration_suite(ngspice, networks)
    print("\nONE CONSTANT PER LAYER vs GLOBAL vs NONE")
    for net_id, rows in suite.items():
        print(f"\nNetwork {net_id}")
        for cond, modes in rows.items():
            print(f"  {cond}")
            for mode, rec in modes.items():
                print(
                    f"    {mode}: MAE={rec.get('mae_mean')} "
                    f"acc={rec.get('accuracy_mean')} "
                    f"meas={rec.get('n_measurements')} "
                    f"const={rec.get('n_constants')}"
                )
    return 0


if __name__ == "__main__":
    sys.exit(main())
