"""Experiment 24 recovery: servo A/F + Vref-gated auto-zero.

Does not overwrite Experiments 1-23. Completes the Exp 24 run after the
JSON circular-reference crash. SPICE is never Python-corrected.
"""

from __future__ import annotations

import json
import sys

import numpy as np

from benchmark_scaling import generate_inputs
from compile_xor import find_ngspice
from hardware_constrained_compiler import load_frozen_model
from offset_vg_search import CIRCUIT_DIR, E24Params, count_blocks
from physical_iv_neuron import IVParams, compile_iv
from test_hardware_constraints import spec_by_id
from test_offset_vg_search import (
    N_A,
    N_F,
    REPORT_JSON,
    dest,
    eval_loaded_tag,
    eval_network,
    fmt,
    iso_eval,
    software_for,
)
from virtual_ground_requirements import INVERT_PINNED, rank_neurons


def slim(rec: dict) -> dict:
    keys = (
        "mae", "max_abs_error", "accuracy", "failed", "failure_reason",
        "mae_vs_z", "max_vs_z", "max_vsum", "mean_vsum",
        "loaded_mae_vs_y", "loaded_max_vs_y", "loaded_max_vsum",
        "vlin_abs_max", "z_abs_max", "blocks", "n_resistors", "n_vectors",
    )
    return {k: rec.get(k) for k in keys}


def main() -> int:
    print("Experiment 24 recovery: servo A/F and Vref-gated AZ", flush=True)
    ngspice = find_ngspice()
    CIRCUIT_DIR.mkdir(parents=True, exist_ok=True)
    spec_a, spec_f = spec_by_id("A"), spec_by_id("F")
    wa, wf = load_frozen_model("A"), load_frozen_model("F")
    xa = generate_inputs(spec_a["n_in"], N_A, "exp24_A")
    xf = generate_inputs(spec_f["n_in"], N_F, "exp24_F")
    ya, _ = software_for(wa, xa)
    yf, _ = software_for(wf, xf)
    x_load = xf[:8]
    y_load, _ = software_for(wf, x_load)

    _net, cat, _ = compile_iv("A", spec_f, wf, IVParams(name="rank", invert_gain=INVERT_PINNED))
    _rows, selected = rank_neurons(spec_f, cat, wf, xf)
    o2 = selected["worst_finite_gain"]
    iso_h = generate_inputs(spec_f["n_in"], 16, "exp24_iso_h")
    z1 = iso_h @ wf["W1"].T + wf["b1"]
    iso_o = np.maximum(0.0, z1[:16])

    def iso_x(pick):
        return iso_h if pick["layer"] == 1 else iso_o

    recovery = {"o2": o2["tag"], "Rf_Gtot": o2.get("Rf_Gtot")}

    p_srv_a = E24Params(candidate="L", name="servoA", vos=214.023e-6, linear=False, servo=True)
    rec_sa, _net_sa, _cat_sa = eval_network(
        ngspice, spec_a, wa, p_srv_a, xa, ya, dest("A", "SERVO214")
    )
    recovery["servo_A"] = slim(rec_sa)
    print(
        f"servo A fail={rec_sa.get('failed')} MAE={fmt(rec_sa.get('mae'))} "
        f"acc={rec_sa.get('accuracy')}",
        flush=True,
    )

    if rec_sa.get("failed"):
        recovery["servo_F"] = {"failed": True, "failure_reason": "skipped: Network A servo failed"}
    else:
        p_srv_f = E24Params(candidate="L", name="servoF", vos=214.023e-6, linear=False, servo=True)
        rec_sf, net_sf, cat_sf = eval_network(
            ngspice, spec_f, wf, p_srv_f, xf, yf, dest("F", "SERVO214")
        )
        recovery["servo_F"] = slim(rec_sf)
        if net_sf:
            recovery["servo_F_blocks"] = count_blocks(net_sf)
            recovery["servo_F_nR"] = len(cat_sf) if cat_sf else None
        print(
            f"servo F fail={rec_sf.get('failed')} MAE={fmt(rec_sf.get('mae'))} "
            f"acc={rec_sf.get('accuracy')}",
            flush=True,
        )

    p_azv = E24Params(
        candidate="L", name="azvref214", vos=214.023e-6, linear=True,
        autozero=True, gate_vref=True, t_az=2e-5, t_stop=8e-5,
    )
    rec_iso = iso_eval(ngspice, spec_f, wf, o2, p_azv, iso_x(o2))
    recovery["azvref_iso_o2"] = slim(rec_iso)
    print(
        f"AZ-Vref o2 fail={rec_iso.get('failed')} MAE_z={fmt(rec_iso.get('mae_vs_z'))}",
        flush=True,
    )

    p_azv_ld = E24Params(
        candidate="L", name="azvrefld", vos=214.023e-6, linear=False,
        autozero=True, gate_vref=True, t_az=2e-5, t_stop=8e-5,
    )
    rec_ld = eval_loaded_tag(ngspice, spec_f, wf, p_azv_ld, x_load, y_load, o2["tag"])
    recovery["azvref_loaded_o2"] = slim(rec_ld)
    print(
        f"AZ-Vref loaded o2 fail={rec_ld.get('failed')} "
        f"MAE_y={fmt(rec_ld.get('loaded_mae_vs_y'))}",
        flush=True,
    )

    p_azv_a = E24Params(
        candidate="L", name="azvrefA", vos=214.023e-6, linear=False,
        autozero=True, gate_vref=True, t_az=2e-5, t_stop=8e-5,
    )
    rec_a, _, _ = eval_network(ngspice, spec_a, wa, p_azv_a, xa, ya, dest("A", "AZVREF214"))
    recovery["azvref_A"] = slim(rec_a)
    print(
        f"AZ-Vref A fail={rec_a.get('failed')} MAE={fmt(rec_a.get('mae'))} "
        f"acc={rec_a.get('accuracy')}",
        flush=True,
    )
    if rec_a.get("mae") is not None and rec_a["mae"] <= 5e-3:
        p_azv_f = E24Params(
            candidate="L", name="azvrefF", vos=214.023e-6, linear=False,
            autozero=True, gate_vref=True, t_az=2e-5, t_stop=8e-5,
        )
        rec_f, _, _ = eval_network(ngspice, spec_f, wf, p_azv_f, xf, yf, dest("F", "AZVREF214"))
        recovery["azvref_F"] = slim(rec_f)
        print(
            f"AZ-Vref F fail={rec_f.get('failed')} MAE={fmt(rec_f.get('mae'))} "
            f"acc={rec_f.get('accuracy')}",
            flush=True,
        )
    else:
        recovery["azvref_F"] = {
            "failed": True,
            "failure_reason": "skipped: Network A AZ-Vref not close enough",
        }

    path = REPORT_JSON.with_name("offset_vg_search_recovery.json")
    path.write_text(json.dumps(recovery, indent=2, default=float), encoding="utf-8")
    print(f"wrote {path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
