"""Exp 24F: servo + 0.5% R mismatch, 8 draws. Frozen weights. No Python correction."""

from __future__ import annotations

import json
import sys

import numpy as np

from benchmark_scaling import (
    classification_labels,
    error_stats,
    generate_inputs,
    simulate_batch,
)
from compile_xor import find_ngspice
from hardware_constrained_compiler import load_frozen_model
from offset_vg_search import CIRCUIT_DIR, E24Params, compile_network
from test_hardware_constraints import spec_by_id
from test_offset_vg_search import N_F, RESULTS_DIR, dest, software_for
from test_robustness import sample_resistor_values


def main() -> int:
    ng = find_ngspice()
    CIRCUIT_DIR.mkdir(parents=True, exist_ok=True)
    spec = spec_by_id("F")
    w = load_frozen_model("F")
    x = generate_inputs(spec["n_in"], N_F, "exp24_F")
    y, _ = software_for(w, x)
    params = E24Params(candidate="L", name="servoMC", vos=214.023e-6, linear=False, servo=True)
    net, cat, reason = compile_network(spec, w, params, linear=False)
    print("compile", reason, "nR", None if cat is None else len(cat), flush=True)
    if reason or net is None:
        return 1
    rng = np.random.default_rng(24)
    expected = classification_labels(y)
    maes, accs = [], []
    for i in range(8):
        values = sample_resistor_values(cat, 0.005, rng)
        physical, rt, err, _log = simulate_batch(
            ng, net, x, spec["n_out"], dest("mc", "servoR", i), r_values=values, timeout=180
        )
        if err or physical is None:
            print("draw", i, "FAIL", err, flush=True)
            continue
        st = error_stats(physical, y)
        pred = classification_labels(physical)
        acc = float(np.mean(pred == expected))
        maes.append(st["mae"])
        accs.append(acc)
        print(f"draw {i} MAE={st['mae']:.4e} acc={acc:.4f} t={rt:.2f}s", flush=True)
    rec = {
        "n_ok": len(maes),
        "mae_mean": float(np.mean(maes)) if maes else None,
        "mae_max": float(np.max(maes)) if maes else None,
        "acc_mean": float(np.mean(accs)) if accs else None,
    }
    path = RESULTS_DIR / "offset_vg_servo_mismatch.json"
    path.write_text(json.dumps(rec, indent=2), encoding="utf-8")
    print(rec, flush=True)
    print("wrote", path, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
