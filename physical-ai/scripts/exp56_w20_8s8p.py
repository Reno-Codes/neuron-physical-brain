"""Experiment 56: W=20 8s8p (256x vs W=10) under official tt_mm.

Experiment 55 left one 8s8p miss at +1.360 mV with leftover +0.479 mV.
This tests whether documented width plus the same 8s8p instance count
clears the remaining high-side tail.

Does not modify Experiments 1-55. No resistor fitting. Not yield.
"""

from __future__ import annotations

import json
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from compile_xor import PROJECT_ROOT, find_ngspice
from exp39_pdk_o2_cell import PDK_VERSION, discover_pdk, eval_cell, prepend_pdk, write_op_net
from exp40_pdk_o2_cell import compile_o2_w2_1, prove_identity
from exp41_o2_residual import replace_resistors_w
from exp43_highgain_w10 import set_tia_gain
from exp45_documented_tia import spiceinit_hsa
from exp54_resistor_tiling import (
    A,
    WORKERS,
    Z_O2,
    check_geos,
    insert_seed,
    inventory,
    summarize,
    tile_same_units,
)
from exp55_large_array import Y_EXP54_4S4P

CIRCUIT_DIR = PROJECT_ROOT / "circuits" / "exp56_o2"
RESULTS_DIR = PROJECT_ROOT / "results"
Y_EXP55_8S8P = 2.459968859764
N_MC = 16
ERROR_LIMIT = 1.0e-3


def run_one(ng, key: str, net: str, hy, z0: float, i: int) -> dict:
    path = CIRCUIT_DIR / key / f"ttmm_{i:03d}.cir"
    path.parent.mkdir(parents=True, exist_ok=True)
    spiceinit_hsa(path.parent)
    write_op_net(
        path,
        prepend_pdk(net, "tt_mm", 27.0).replace(
            "* Experiment 39 SKY130 isolated frozen o2 cell",
            f"* Experiment 56 {key} tt_mm draw {i} A=1e6 · model AGAUSS",
        ),
        hy,
    )
    insert_seed(path, 56000 + i)
    rec = eval_cell(ng, path, z0, timeout=600.0)
    rec.update({"draw": i, "config": key, "python_corrected": False, "seed": 56000 + i})
    print(
        f"  MM {key} {i} y={rec.get('y')} |err|={rec.get('abs_err')} "
        f"pass={rec.get('analog_pass')} fail={rec.get('failed')}",
        flush=True,
    )
    return rec


def main() -> None:
    ident = prove_identity()
    w = ident.pop("weights")
    pdk = discover_pdk()
    if pdk.get("ciel_current") != PDK_VERSION:
        raise SystemExit("BLOCKED PDK")
    net0, cat, _ = compile_o2_w2_1(w)
    z0 = float(ident["z_at_imax"])
    if not math.isclose(z0, Z_O2, rel_tol=0, abs_tol=1e-12):
        raise SystemExit("BLOCKED z")
    hy = ident["hy_at_imax"]
    CIRCUIT_DIR.mkdir(parents=True, exist_ok=True)
    spiceinit_hsa(CIRCUIT_DIR)
    ng = find_ngspice()

    w10, g10 = replace_resistors_w(net0, cat, 10.0)
    w20, g20 = replace_resistors_w(net0, cat, 20.0)
    check_geos(g10)
    check_geos(g20)
    net8 = tile_same_units(set_tia_gain(w10, A), 8, 8)
    netw = tile_same_units(set_tia_gain(w20, A), 8, 8)

    print("==== Nominal tt ====", flush=True)
    nominal = {}
    for key, net in [("w10_8s8p", net8), ("w20_8s8p", netw)]:
        path = CIRCUIT_DIR / key / "tt_nominal.cir"
        path.parent.mkdir(parents=True, exist_ok=True)
        spiceinit_hsa(path.parent)
        write_op_net(
            path,
            prepend_pdk(net, "tt", 27.0).replace(
                "* Experiment 39 SKY130 isolated frozen o2 cell",
                f"* Experiment 56 {key} tt nominal A=1e6",
            ),
            hy,
        )
        rec = eval_cell(ng, path, z0, timeout=600.0)
        rec["inventory"] = inventory(net)
        nominal[key] = rec
        print(
            f"  NOM {key} y={rec.get('y')} |err|={rec.get('abs_err')} "
            f"nR={rec['inventory'].get('n')}",
            flush=True,
        )

    y8 = nominal["w10_8s8p"].get("y")
    if y8 is None or abs(float(y8) - Y_EXP55_8S8P) > 5e-7:
        print(f"  WARN 8s8p nominal y={y8} vs Exp55 {Y_EXP55_8S8P}", flush=True)

    stats = {}
    draws = {}
    signed = {}
    for key, net in [("w20_8s8p", netw)]:
        print(f"==== tt_mm {key} n={N_MC} ====", flush=True)
        rows = [None] * N_MC
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futs = {pool.submit(run_one, ng, key, net, hy, z0, i): i for i in range(N_MC)}
            for fut in as_completed(futs):
                rec = fut.result()
                rows[int(rec["draw"])] = rec
        rows = [r for r in rows if r is not None]
        stats[key] = summarize(rows)
        draws[key] = [
            {
                "draw": r.get("draw"),
                "y": r.get("y"),
                "err": None if r.get("y") is None else float(r["y"]) - z0,
                "abs_err": r.get("abs_err"),
                "analog_pass": r.get("analog_pass"),
                "failed": r.get("failed"),
            }
            for r in rows
        ]
        errs = [d["err"] for d in draws[key] if d["err"] is not None]
        signed[key] = {
            "n_pos": int(sum(1 for e in errs if e > 0)),
            "n_neg": int(sum(1 for e in errs if e < 0)),
            "mean_signed_mV": float(sum(errs) / len(errs) * 1e3) if errs else None,
            "max_pos_mV": float(max(errs) * 1e3) if errs else None,
            "min_neg_mV": float(min(errs) * 1e3) if errs else None,
        }
        print(f"  STAT {key} {stats[key]} signed={signed[key]}", flush=True)

    st = stats.get("w20_8s8p") or {}
    n_pass = int(st.get("n_pass") or 0)
    n_ok = int(st.get("n_ok") or 0)
    mean = float(st.get("mean") or 1e9)
    if n_ok and n_pass == n_ok:
        decision, label, status = (
            "B",
            f"W=20 8s8p ALL {n_ok} DRAWS PASS (NOT YIELD)",
            "PARTIALLY VALIDATED",
        )
        nxt = (
            "Experiment 57: host W=20 8s8p on OPA189 TIA (isolated o2), "
            "then a frozen F40 vector. Still model AGAUSS. Not silicon."
        )
    elif n_ok and mean <= ERROR_LIMIT and n_pass >= n_ok - 1:
        decision, label, status = (
            "B",
            f"W=20 8s8p {n_pass}/{n_ok}; LEFTOVER FLOOR LIKELY DOMINATES (NOT YIELD)",
            "PARTIALLY VALIDATED",
        )
        nxt = (
            "Experiment 57: leftover diagnosis (ideal R vs xhigh_po at A=1e6) "
            "and/or documented resistor-family alternative. Do not invent W/L."
        )
    else:
        decision, label, status = (
            "C",
            "W=20 8s8p DID NOT CLEAR THE 1 mV SAMPLE",
            "TECHNOLOGY BOUNDARY",
        )
        nxt = "Experiment 57: leftover / family search. Matching still UNRESOLVED as yield."

    report = {
        "experiment_id": "exp56",
        "kind": "W=20 8s8p 256x documented area under tt_mm",
        "status": status,
        "decision": decision,
        "decision_label": label,
        "yield_claim": False,
        "silicon": False,
        "realism_level": 4,
        "A": A,
        "N_MC": N_MC,
        "baseline": {
            "exp55_8s8p_y": Y_EXP55_8S8P,
            "this_8s8p_y": nominal["w10_8s8p"].get("y"),
            "exp54_4s4p_y": Y_EXP54_4S4P,
        },
        "inventory": {"w10_8s8p": inventory(net8), "w20_8s8p": inventory(netw)},
        "nominal": {
            k: {
                "y": v.get("y"),
                "abs_err": v.get("abs_err"),
                "analog_pass": v.get("analog_pass"),
                "failed": v.get("failed"),
                "inventory": v.get("inventory"),
            }
            for k, v in nominal.items()
        },
        "stats": stats,
        "signed": signed,
        "draws": draws,
        "physical_tia_validated": False,
        "miller_family": "CLOSED",
        "next_experiment": nxt,
        "conclusion": (
            f"Decision {decision} — {label}. "
            "tt_mm is official model AGAUSS, not a foundry lot. "
            "OPA189 remains the Level-1 TIA host. Miller family remains closed."
        ),
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / "exp56_w20_8s8p.json").write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8"
    )
    lines = [
        "# Experiment 56 — W=20 8s8p under tt_mm",
        "",
        "Experiments 1-55 were not modified. Behavioral TIA. Model AGAUSS, not yield.",
        "",
        f"**Status: {status}**",
        f"**Decision {decision} — {label}**",
        "",
        "## Nominal leftover",
        "",
        "| config | y (V) | |err| (mV) | n devices |",
        "| --- | ---: | ---: | ---: |",
    ]
    for key, rec in nominal.items():
        ae = rec.get("abs_err")
        inv = rec.get("inventory") or {}
        lines.append(
            f"| {key} | {rec.get('y')} | "
            f"{None if ae is None else ae * 1e3:.6f} | {inv.get('n')} |"
        )
    lines += [
        "",
        "## tt_mm W=20 8s8p",
        "",
        f"pass = {n_pass}/{n_ok}; mean = {mean*1e3:.6f} mV; "
        f"max = {float(st.get('max') or 0)*1e3:.6f} mV",
        "",
        f"signed: {signed.get('w20_8s8p')}",
        "",
        report["conclusion"],
        "",
        "## Next experiment",
        "",
        nxt,
        "",
    ]
    (RESULTS_DIR / "exp56_w20_8s8p.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"Experiment 56 Decision {decision} — {label}", flush=True)


if __name__ == "__main__":
    main()
