"""Experiment 55: 64x documented resistor area under official tt_mm.

Follows Experiment 54: 16x 4s4p put mean |err| in the 1 mV bar but
5/16 draws still missed. Tests W=10 8s8p and W=20 4s4p (both ~64x)
plus W=20 2s2p (16x, fewer devices).

Does not modify Experiments 1-54. No resistor fitting. Not yield.
Behavioral TIA only. Miller family stays closed.
"""

from __future__ import annotations

import json
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from compile_xor import PROJECT_ROOT, find_ngspice
from exp39_pdk_o2_cell import (
    ERROR_LIMIT,
    PDK_VERSION,
    discover_pdk,
    eval_cell,
    prepend_pdk,
    write_op_net,
)
from exp40_pdk_o2_cell import compile_o2_w2_1, prove_identity
from exp41_o2_residual import replace_resistors_w
from exp43_highgain_w10 import set_tia_gain
from exp45_documented_tia import spiceinit_hsa
from exp54_resistor_tiling import (
    A,
    WORKERS,
    Y_EXP53_NOM,
    Z_O2,
    check_geos,
    insert_seed,
    inventory,
    summarize,
    tile_same_units,
)

CIRCUIT_DIR = PROJECT_ROOT / "circuits" / "exp55_o2"
RESULTS_DIR = PROJECT_ROOT / "results"
Y_EXP54_4S4P = 2.459965130621
NOM_ATOL_V = 1.0e-8
N_MC_64 = 16


def fabrics(net0: str, cat: list) -> dict:
    w10, g10 = replace_resistors_w(net0, cat, 10.0)
    check_geos(g10)
    w20, g20 = replace_resistors_w(net0, cat, 20.0)
    check_geos(g20)
    a10 = set_tia_gain(w10, A)
    a20 = set_tia_gain(w20, A)
    return {
        "w10_4s4p": {
            "label": "W=10 4s4p (Exp54 repeat)",
            "net": tile_same_units(a10, 4, 4),
            "area_mult": 16.0,
        },
        "w20_2s2p": {
            "label": "W=20 2s2p (16x, 320 devices)",
            "net": tile_same_units(a20, 2, 2),
            "area_mult": 16.0,
        },
        "w20_4s4p": {
            "label": "W=20 4s4p (64x, 1280 devices)",
            "net": tile_same_units(a20, 4, 4),
            "area_mult": 64.0,
        },
        "w10_8s8p": {
            "label": "W=10 8s8p (64x, 5120 devices)",
            "net": tile_same_units(a10, 8, 8),
            "area_mult": 64.0,
        },
    }


def run_nominal(ng, key: str, net: str, hy, z0: float) -> dict:
    inv = inventory(net)
    path = CIRCUIT_DIR / key / "tt_nominal.cir"
    path.parent.mkdir(parents=True, exist_ok=True)
    spiceinit_hsa(path.parent)
    write_op_net(
        path,
        prepend_pdk(net, "tt", 27.0).replace(
            "* Experiment 39 SKY130 isolated frozen o2 cell",
            f"* Experiment 55 {key} tt nominal A=1e6",
        ),
        hy,
    )
    rec = eval_cell(ng, path, z0, timeout=600.0)
    rec.update({"name": f"{key}_nominal", "config": key, "inventory": inv})
    print(
        f"  NOM {key} y={rec.get('y')} |err|={rec.get('abs_err')} "
        f"nR={inv.get('n')} fail={rec.get('failed')}",
        flush=True,
    )
    return rec


def run_one_local(ng, key: str, net: str, hy, z0: float, i: int, timeout: float) -> dict:
    path = CIRCUIT_DIR / key / f"ttmm_{i:03d}.cir"
    path.parent.mkdir(parents=True, exist_ok=True)
    spiceinit_hsa(path.parent)
    write_op_net(
        path,
        prepend_pdk(net, "tt_mm", 27.0).replace(
            "* Experiment 39 SKY130 isolated frozen o2 cell",
            f"* Experiment 55 {key} tt_mm draw {i} A=1e6 · model AGAUSS",
        ),
        hy,
    )
    insert_seed(path, 55000 + i)
    rec = eval_cell(ng, path, z0, timeout=timeout)
    rec.update({"draw": i, "config": key, "python_corrected": False, "seed": 55000 + i})
    print(
        f"  MM {key} {i} y={rec.get('y')} |err|={rec.get('abs_err')} "
        f"pass={rec.get('analog_pass')} fail={rec.get('failed')}",
        flush=True,
    )
    return rec


def run_mc_local(ng, key: str, net: str, hy, z0: float, n: int) -> list[dict]:
    timeout = 600.0 if "8s8p" in key else 360.0
    rows = [None] * n
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futs = {
            pool.submit(run_one_local, ng, key, net, hy, z0, i, timeout): i
            for i in range(n)
        }
        for fut in as_completed(futs):
            rec = fut.result()
            rows[int(rec["draw"])] = rec
    return [r for r in rows if r is not None]


def decide(nominal: dict, stats: dict) -> tuple[str, str, str, str]:
    a64 = stats.get("w20_4s4p") or stats.get("w10_8s8p") or {}
    b64 = stats.get("w10_8s8p") or {}
    c16 = stats.get("w20_2s2p") or {}
    base = stats.get("w10_4s4p") or {}

    def rate(s):
        return float(s.get("pass_rate") or 0.0)

    def mean(s):
        return float(s.get("mean") or 1e9)

    allpass = [k for k, s in stats.items() if s and rate(s) >= 0.999]
    if allpass:
        return (
            "B",
            f"{', '.join(allpass)} ALL {N_MC_64} DRAWS PASS (NOT YIELD)",
            "PARTIALLY VALIDATED",
            "Experiment 56: host the passing array on OPA189, then a frozen F40 vector. Still model AGAUSS.",
        )
    best = min(stats.items(), key=lambda kv: mean(kv[1]) if kv[1] else 1e9)
    if best[1] and mean(best[1]) <= ERROR_LIMIT and rate(best[1]) >= 0.85:
        return (
            "B",
            f"{best[0]} MEAN IN BAR, PASS {best[1]['n_pass']}/{best[1]['n_ok']} (NOT YIELD)",
            "PARTIALLY VALIDATED",
            "Experiment 56: more draws on the best 64x array; leftover floor may now dominate tails.",
        )
    if a64 and mean(a64) < 0.7 * (mean(base) if base else 1.0):
        return (
            "C",
            "64x AREA REDUCES ERROR FURTHER BUT SAMPLE STILL MIXED",
            "TECHNOLOGY BOUNDARY",
            "Experiment 56: leftover vs tail split; do not invent Pelgrom. Miller stays closed.",
        )
    return (
        "C",
        "64x DOCUMENTED AREA DID NOT CLEAR THE 1 mV SAMPLE",
        "TECHNOLOGY BOUNDARY",
        "Experiment 56: leftover floor / head term / other documented resistor family. Not yield.",
    )


def write_reports(report: dict) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / "exp55_large_array.json").write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8"
    )
    lines = [
        "# Experiment 55 — 64x documented resistor area under tt_mm",
        "",
        "Experiments 1-54 were not modified. Behavioral TIA. Model AGAUSS, not yield.",
        "",
        f"**Status: {report['status']}**",
        f"**Decision {report['decision']} — {report['decision_label']}**",
        "",
        "## Nominal leftover",
        "",
        "| config | y (V) | |err| (mV) | pass | n devices |",
        "| --- | ---: | ---: | --- | ---: |",
    ]
    for key, rec in report["nominal"].items():
        ae = rec.get("abs_err")
        inv = rec.get("inventory") or {}
        lines.append(
            f"| {key} | {rec.get('y')} | "
            f"{None if ae is None else ae * 1e3:.6f} | {rec.get('analog_pass')} | "
            f"{inv.get('n')} |"
        )
    lines += [
        "",
        "## tt_mm cell |y-z| (not yield)",
        "",
        "| config | n | pass | mean (mV) | max (mV) | std (mV) |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for key, st in report["stats"].items():
        if not st:
            continue
        lines.append(
            f"| {key} | {st['n_ok']} | {st['n_pass']}/{st['n_ok']} | "
            f"{st['mean']*1e3:.6f} | {st['max']*1e3:.6f} | {st['std']*1e3:.6f} |"
        )
    lines += ["", report["conclusion"], "", "## Next experiment", "", report["next_experiment"], ""]
    (RESULTS_DIR / "exp55_large_array.md").write_text("\n".join(lines), encoding="utf-8")


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
    fabs = fabrics(net0, cat)

    print("==== Nominal tt ====", flush=True)
    nominal = {}
    skipped = []
    for key in ["w10_4s4p", "w20_2s2p", "w20_4s4p", "w10_8s8p"]:
        rec = run_nominal(ng, key, fabs[key]["net"], hy, z0)
        nominal[key] = rec
        if rec.get("failed"):
            skipped.append(key)
            print(f"  SKIP MC {key} (nominal failed)", flush=True)

    y4 = nominal["w10_4s4p"].get("y")
    if y4 is None or abs(float(y4) - Y_EXP54_4S4P) > 5e-7:
        print(f"  WARN 4s4p nominal y={y4} vs Exp54 {Y_EXP54_4S4P}", flush=True)

    stats = {}
    draws = {}
    order = [k for k in ["w10_4s4p", "w20_2s2p", "w20_4s4p", "w10_8s8p"] if k not in skipped]
    for key in order:
        print(f"==== tt_mm {key} n={N_MC_64} ====", flush=True)
        rows = run_mc_local(ng, key, fabs[key]["net"], hy, z0, N_MC_64)
        draws[key] = [
            {
                "draw": r.get("draw"),
                "y": r.get("y"),
                "abs_err": r.get("abs_err"),
                "analog_pass": r.get("analog_pass"),
                "failed": r.get("failed"),
            }
            for r in rows
        ]
        stats[key] = summarize(rows)
        print(f"  STAT {key} {stats[key]}", flush=True)

    decision, label, status, nxt = decide(nominal, stats)
    report = {
        "experiment_id": "exp55",
        "kind": "64x documented SKY130 resistor area under tt_mm",
        "status": status,
        "decision": decision,
        "decision_label": label,
        "yield_claim": False,
        "silicon": False,
        "realism_level": 4,
        "A": A,
        "N_MC": N_MC_64,
        "skipped": skipped,
        "baseline": {
            "exp54_4s4p_y": Y_EXP54_4S4P,
            "exp53_w10_y": Y_EXP53_NOM,
            "this_4s4p_y": nominal.get("w10_4s4p", {}).get("y"),
        },
        "inventory": {k: inventory(fabs[k]["net"]) for k in fabs},
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
    write_reports(report)
    print(f"Experiment 55 Decision {decision} — {label}", flush=True)


if __name__ == "__main__":
    main()
