"""Experiment 23 follow-up: OPA171 OP recovery, IN+ trim, documented-Vos injection.

Does not overwrite Experiment 22. Merges into Experiment 23 artifacts.
GWL macromodels use independent `reset; op` per vector (no UIC: the model
contains 1 F capacitors; UIC would not be a DC operating point).
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

from benchmark_scaling import classification_labels, error_stats, generate_inputs
from compile_xor import PROJECT_ROOT, find_ngspice
from hardware_constrained_compiler import load_frozen_model
from physical_iv_neuron import IVParams, compile_iv
from precision_architectures import ARCH_C_CFG
from test_hardware_constraints import spec_by_id
from test_robustness import sample_resistor_values
from test_virtual_ground_primitive import (
    ERROR_LIMIT,
    N_A,
    N_F,
    RAIL,
    REPORT_JSON,
    REPORT_MD,
    TAG,
    conclude,
    dest,
    eval_network,
    fmt,
    iso_eval,
    software_for,
    write_markdown,
    write_plots,
)
from virtual_ground_primitive import CIRCUIT_DIR, PrimParams
from virtual_ground_requirements import INVERT_PINNED, rank_neurons


TIMEOUT_A = 600.0
OPA171_VOS = 214.023e-6
N_MC = 8
R_TOL = 0.005


def load_report() -> dict:
    return json.loads(REPORT_JSON.read_text(encoding="utf-8"))


def save_report(report: dict) -> None:
    conclude(report)
    report["plots"] = write_plots(report)
    write_markdown(report)

    def default(o):
        if isinstance(o, (np.floating, np.integer)):
            return float(o)
        if isinstance(o, np.ndarray):
            return o.tolist()
        raise TypeError(type(o))

    REPORT_JSON.write_text(json.dumps(report, indent=2, default=default), encoding="utf-8")
    print(f"wrote {REPORT_JSON}", flush=True)
    print(f"wrote {REPORT_MD}", flush=True)
    print(report.get("final_status"), flush=True)
    print(report.get("conclusion"), flush=True)


def eval_network_long(ngspice, spec, weights, params, inputs, y, path, measure_vsum=False):
    from test_virtual_ground_primitive import TIMEOUT_MACRO
    import test_virtual_ground_primitive as t

    old = t.TIMEOUT_MACRO
    t.TIMEOUT_MACRO = TIMEOUT_A
    try:
        return eval_network(ngspice, spec, weights, params, inputs, y, path, measure_vsum=measure_vsum)
    finally:
        t.TIMEOUT_MACRO = old


def mc_l(ngspice, spec, weights, inputs, y, vos, i_leak, mismatch, seed, name):
    from benchmark_scaling import simulate_batch

    params = PrimParams(candidate="L", name=name, vos=vos, i_leak=i_leak, linear=False)
    net, cat, reason = __import__(
        "virtual_ground_primitive", fromlist=["compile_network"]
    ).compile_network(spec, weights, params, linear=False)
    rec = {
        "name": name,
        "vos": vos,
        "i_leak": i_leak,
        "mismatch": mismatch,
        "n_draws": 1 if not mismatch else N_MC,
        "failed": bool(reason),
        "failure_reason": reason,
    }
    if reason or net is None:
        return rec
    rng = np.random.default_rng(seed)
    maes, accs, fails = [], [], 0
    n_out = spec["n_out"]
    expected = classification_labels(y)
    draws = N_MC if mismatch else 1
    for i in range(draws):
        values = sample_resistor_values(cat, R_TOL, rng) if mismatch else {}
        physical, runtime, err, _ = simulate_batch(
            ngspice, net, inputs, n_out, dest("mc", name, i), r_values=values, timeout=60.0
        )
        if err or physical is None:
            fails += 1
            continue
        stats = error_stats(physical, y)
        pred = classification_labels(physical)
        maes.append(stats["mae"])
        accs.append(float(np.mean(pred == expected)))
    rec["n_spice_fail"] = fails
    rec["mae_mean"] = float(np.mean(maes)) if maes else None
    rec["mae_max"] = float(np.max(maes)) if maes else None
    rec["acc_mean"] = float(np.mean(accs)) if accs else None
    rec["failed"] = not maes
    return rec


def main() -> int:
    print("Experiment 23 recovery: OPA171 reset-OP + documented Vos", flush=True)
    ngspice = find_ngspice()
    report = load_report()
    spec_a = spec_by_id("A")
    spec_f = spec_by_id("F")
    wa, wf = load_frozen_model("A"), load_frozen_model("F")
    xa = generate_inputs(spec_a["n_in"], N_A, "exp23_A")
    xf = generate_inputs(spec_f["n_in"], N_F, "exp23_F")
    ya, _ = software_for(wa, xa)
    yf, _ = software_for(wf, xf)

    net_f, cat_f, _ = compile_iv("A", spec_f, wf, IVParams(name="rank", invert_gain=INVERT_PINNED))
    _rows, selected = rank_neurons(spec_f, cat_f, wf, xf)
    o2 = selected["worst_finite_gain"]
    h16 = selected["worst_leakage"]
    h21 = selected["median_hidden"]
    iso_h = generate_inputs(spec_f["n_in"], 16, "exp23_iso_h")
    z1 = iso_h @ wf["W1"].T + wf["b1"]
    iso_o = np.maximum(0.0, z1[:16])

    def iso_x(pick):
        return iso_h if pick["layer"] == 1 else iso_o

    print("OPA171 isolated o2 with independent reset OP", flush=True)
    p_uc = PrimParams(candidate="OPA171", name="uc_reset", linear=True, vsupply=15.0)
    rec_o2 = iso_eval(ngspice, spec_f, wf, o2, p_uc, iso_x(o2))
    print(
        f"  o2 OPA171 fail={rec_o2.get('failed')} MAE_z={fmt(rec_o2.get('mae_vs_z'))} "
        f"Vsum={fmt(rec_o2.get('max_vsum'))} {rec_o2.get('failure_reason')}",
        flush=True,
    )
    report.setdefault("unit_cell", {})["OPA171_reset_op"] = rec_o2

    print("OPA171 IN+ trim via zero-input signed Vsum", flush=True)
    from test_virtual_ground_primitive import simulate_isolated

    wrow = wf["W2"][o2["index"]]
    bias = float(wf["b2"][o2["index"]])
    cfg = ARCH_C_CFG["F"]
    from virtual_ground_primitive import isolated_neuron

    net0, _, rsn = isolated_neuron(32, wrow, bias, cfg.g_weight_2, cfg.banks, p_uc, tag=TAG)
    signed_vsum = None
    if net0 and not rsn:
        vlin, vsum, err, _ = simulate_isolated(
            ngspice, net0, np.zeros((1, 32)), 32, dest("trim", "measure_reset"), pspice=True
        )
        if vsum is not None and not err:
            signed_vsum = float(vsum[0])
    trim_v = -signed_vsum if signed_vsum is not None else -OPA171_VOS
    p_trim = PrimParams(candidate="OPA171", name="trim_reset", vos_trim=trim_v, linear=True)
    rec_t = iso_eval(ngspice, spec_f, wf, o2, p_trim, iso_x(o2))
    report["trim_reset"] = {
        "measured_vsum_zero_in": signed_vsum,
        "trim_voltage": trim_v,
        "isolated": rec_t,
        "note": (
            "IN+ DC source = -Vsum at zero input, measured in SPICE. "
            "Not Python output correction. Same trim on every identical macromodel. "
            "Would not cancel uncorrelated per-chip Vos without per-amp measurement."
        ),
    }
    print(
        f"  Vsum0={fmt(signed_vsum)} trim={fmt(trim_v)} "
        f"MAE_z={fmt(rec_t.get('mae_vs_z'))} fail={rec_t.get('failed')} "
        f"{rec_t.get('failure_reason')}",
        flush=True,
    )

    print("Representative F neurons OPA171 reset-OP", flush=True)
    rep = report.get("rep_F") or {}
    for pick in (h16, h21, o2):
        rec = iso_eval(
            ngspice, spec_f, wf, pick,
            PrimParams(candidate="OPA171", name="rep_reset", linear=True),
            iso_x(pick),
        )
        rep.setdefault(pick["tag"], {})["OPA171_reset_op"] = {
            k: rec.get(k) for k in ("mae_vs_z", "max_vsum", "failed", "failure_reason")
        }
        print(
            f"  {pick['tag']} OPA171 MAE_z={fmt(rec.get('mae_vs_z'))} "
            f"Vsum={fmt(rec.get('max_vsum'))} fail={rec.get('failed')}",
            flush=True,
        )
    report["rep_F"] = rep

    print("Network A OPA171 reset-OP", flush=True)
    net_a = report.get("network_A") or {}
    rec_a, _, _ = eval_network_long(
        ngspice, spec_a, wa,
        PrimParams(candidate="OPA171", name="A_reset", linear=False, vsupply=15.0),
        xa, ya, dest("A", "OPA171_reset"),
    )
    net_a["OPA171_reset_op"] = {k: rec_a.get(k) for k in (
        "mae", "max_abs_error", "accuracy", "failed", "failure_reason"
    )}
    print(
        f"  A OPA171 fail={rec_a.get('failed')} MAE={fmt(rec_a.get('mae'))} "
        f"acc={rec_a.get('accuracy')} {rec_a.get('failure_reason')}",
        flush=True,
    )
    if rec_t.get("mae_vs_z") is not None:
        rec_at, _, _ = eval_network_long(
            ngspice, spec_a, wa,
            PrimParams(
                candidate="OPA171", name="A_trim_reset", linear=False,
                vsupply=15.0, vos_trim=trim_v,
            ),
            xa, ya, dest("A", "OPA171_trim_reset"),
        )
        net_a["OPA171_trim_reset"] = {k: rec_at.get(k) for k in (
            "mae", "max_abs_error", "accuracy", "failed", "failure_reason"
        )}
        print(
            f"  A OPA171_trim fail={rec_at.get('failed')} MAE={fmt(rec_at.get('mae'))} "
            f"acc={rec_at.get('accuracy')} {rec_at.get('failure_reason')}",
            flush=True,
        )
    report["network_A"] = net_a

    print("L with OPA171 documented Vos=214.023 uV (LEVEL 2 injection of LEVEL 3 spec)", flush=True)
    vos_inj = {}
    for net_id, spec, w, x, y in (
        ("A", spec_a, wa, xa, ya),
        ("F", spec_f, wf, xf, yf),
    ):
        rec, _, _ = eval_network(
            ngspice, spec, w,
            PrimParams(candidate="L", name=f"{net_id}_vos214u", vos=OPA171_VOS, linear=False),
            x, y, dest(net_id, "L_vos214u"),
        )
        vos_inj[net_id] = {k: rec.get(k) for k in (
            "mae", "max_abs_error", "accuracy", "failed", "failure_reason"
        )}
        print(
            f"  {net_id} L Vos=214uV MAE={fmt(rec.get('mae'))} acc={rec.get('accuracy')} "
            f"fail={rec.get('failed')}",
            flush=True,
        )
    report["documented_vos_injection"] = {
        "vos_V": OPA171_VOS,
        "source": "OPA171.txt V_OS 214.023e-6, injected on L IN+",
        "networks": vos_inj,
        "note": (
            "This is not an OPA171 result. It asks whether the documented "
            "macromodel offset, applied to the converging XSPICE limit TIA, "
            "meets Exp 22 analog MAE. SPICE is uncorrected."
        ),
    }

    print("Network F L leakage-only and mismatch-only (small, nominal L already passed)", flush=True)
    mc = {
        "nominal_L": report.get("network_F", {}).get("L"),
        "offset_214uV": vos_inj.get("F"),
        "leakage_13nA": mc_l(ngspice, spec_f, wf, xf, yf, 0.0, 13e-9, False, 23, "F_lk13n"),
        "mismatch_0p5pct": mc_l(ngspice, spec_f, wf, xf, yf, 0.0, 0.0, True, 23, "F_mm5"),
        "combined_214uV_13nA_0p5pct": mc_l(
            ngspice, spec_f, wf, xf, yf, OPA171_VOS, 13e-9, True, 24, "F_comb"
        ),
    }
    print(
        f"  leak MAE={fmt(mc['leakage_13nA'].get('mae_mean'))} "
        f"mm MAE={fmt(mc['mismatch_0p5pct'].get('mae_mean'))} "
        f"comb MAE={fmt(mc['combined_214uV_13nA_0p5pct'].get('mae_mean'))}",
        flush=True,
    )
    report["monte_carlo_F_L"] = mc

    net_f_res = report.get("network_F") or {}
    if not rec_a.get("failed"):
        print("Full Network F OPA171 reset-OP", flush=True)
        rec_f, _, _ = eval_network_long(
            ngspice, spec_f, wf,
            PrimParams(candidate="OPA171", name="F_reset", linear=False, vsupply=15.0),
            xf, yf, dest("F", "OPA171_reset"),
        )
        net_f_res["OPA171_reset_op"] = {k: rec_f.get(k) for k in (
            "mae", "max_abs_error", "accuracy", "failed", "failure_reason"
        )}
        print(
            f"  F OPA171 fail={rec_f.get('failed')} MAE={fmt(rec_f.get('mae'))} "
            f"acc={rec_f.get('accuracy')} {rec_f.get('failure_reason')}",
            flush=True,
        )
    else:
        net_f_res["OPA171_reset_op"] = {
            "failed": True,
            "failure_reason": "skipped: Network A OPA171 reset-OP failed",
        }
    report["network_F"] = net_f_res

    # Prefer reset-OP OPA171 numbers in the primary Network A slot if they exist.
    if rec_a.get("mae") is not None:
        net_a["OPA171"] = net_a.get("OPA171_reset_op") or net_a.get("OPA171")
        report["network_A"] = net_a
    if rec_t.get("mae_vs_z") is not None:
        report["trim"] = report.get("trim_reset")
    if rec_o2.get("mae_vs_z") is not None:
        report["unit_cell"]["OPA171"] = rec_o2

    report["recovery_note"] = (
        "OPA171 alter-continuation hit GWL cl_clamp singularities. "
        "Recovery bakes Vin DC into one netlist per vector. Control-section "
        "rshunt/gmin also aborted some OPs; the working DC analysis is a bare op. "
        "UIC was not used (GWL 1 F capacitors). Vlin is still the SPICE solution."
    )
    save_report(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
