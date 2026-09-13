"""Re-run Experiment 29 promoted Network F MC after correcting model selection.

Does not overwrite Experiments 1–28. Does not re-run the full campaign.
"""

from __future__ import annotations

import json
import sys

from benchmark_scaling import generate_inputs, make_rng
from compile_xor import find_ngspice
from exp29_resistor_ratio_matching import (
    N_COMPARE,
    N_FULL,
    N_MC,
    N_MC_PROMOTED,
    REPORT_JSON,
    SEED,
    compile_f,
    dest,
    eval_f,
    extract_requirement,
    implementation_blurbs,
    conclude,
    save_report,
    software_for,
    write_markdown,
    write_plots,
    run_mc_f,
)
from hardware_constrained_compiler import load_frozen_model
from resistor_ratio_matching import AMP_A_HIGH, G_WEIGHT, annotate_fabric, quantize_values
from test_hardware_constraints import spec_by_id


def main() -> int:
    report = json.loads(REPORT_JSON.read_text(encoding="utf-8"))
    ng = find_ngspice()
    spec = spec_by_id("F")
    wf = load_frozen_model("F")
    x40 = generate_inputs(spec["n_in"], N_FULL, "exp24_F")
    x12 = x40[:N_COMPARE]
    y40 = software_for(wf, x40)
    y12 = software_for(wf, x12)
    net, cat, spec, _ = compile_f(wf)

    print("finer quantization", flush=True)
    quant = list(report.get("quantization") or [])
    have = {r.get("g_unit_over_gw") for r in quant}
    for frac in (1 / 1024, 1 / 4096):
        if frac in have:
            continue
        g_u = G_WEIGHT * frac
        values, st = quantize_values(cat, g_u)
        rec = eval_f(ng, net, cat, spec, wf, x12, y12, dest("f", "quant", frac), values)
        rec.update(st)
        rec["g_unit_over_gw"] = frac
        rec["analog_pass"] = (not rec.get("failed")) and (rec.get("mae") or 9) <= 1e-3
        quant.append({k: rec.get(k) for k in (
            "g_unit_S", "g_unit_over_gw", "n_quantized", "n_unmatched_residual",
            "n_unit_elements", "mean_rel_g", "max_rel_g", "mae", "accuracy",
            "analog_pass", "failed", "failure_reason",
        )})
        print(f"  quant Gw*{frac:g} nU={st['n_unit_elements']} MAE={rec.get('mae')}", flush=True)
    report["quantization"] = quant

    promo_name = "ratio_matched_neuron"
    promo_kw = {}
    print(f"promoted {promo_name} F40 n={N_MC_PROMOTED}", flush=True)
    rng = make_rng("exp29", "promo2", promo_name, SEED)
    from exp29_resistor_ratio_matching import mc_stats
    from resistor_ratio_matching import sample_named

    maes, accs = [], []
    for i in range(N_MC_PROMOTED):
        values = sample_named(cat, promo_name, rng, spec=spec, **promo_kw)
        rec = eval_f(ng, net, cat, spec, wf, x40, y40, dest("f", "promo2", promo_name, i), values)
        if rec.get("failed"):
            print(f"  promo {i} FAIL {rec.get('failure_reason')}", flush=True)
            continue
        maes.append(rec["mae"])
        accs.append(rec["accuracy"])
        print(f"  promo {i + 1}/{N_MC_PROMOTED} MAE={rec['mae']:.4e} acc={rec['accuracy']:.3f}", flush=True)
    promo = mc_stats(maes, accs)
    promo.update({"model": promo_name, "kw": promo_kw, "n_vectors": N_FULL, "draws": maes})
    report["promoted_mc"] = promo

    print("ratio_matched_exp27 F40", flush=True)
    report["ratio_exp27_f40"] = run_mc_f(
        ng, net, cat, spec, wf, x40, y40, "ratio_matched_exp27", N_MC, "f40r27"
    )

    print("finite-A control A=1e7 neuron-ratio", flush=True)
    net_hi, cat_hi, spec_hi, _ = compile_f(wf, amp=AMP_A_HIGH)
    annotate_fabric(cat_hi)
    nom_hi = eval_f(ng, net_hi, cat_hi, spec_hi, wf, x12, y12, dest("f", "nom_a1e7_nr"))
    hi = run_mc_f(ng, net_hi, cat_hi, spec_hi, wf, x12, y12, promo_name, N_MC, "a1e7nr")
    report["finite_a_control"] = {
        "note": "Labeled control. Removes most of the A=1e5 floor. Not the primary claim.",
        "nominal_mae": nom_hi.get("mae"),
        **hi,
    }

    extract_requirement(report)
    implementation_blurbs(report, report.get("inventory") or {})
    status = conclude(report)
    write_plots(report)
    write_markdown(report)
    save_report(report)
    print(status, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
