"""Experiment 54: documented SKY130 resistor area / unit tiling under tt_mm.

Reproduces Experiment 53 W=10 + A=1e6, then tests official-model
geometry that does not invent W/L, Pelgrom constants, or yield.

Does not modify Experiments 1-53. Does not edit frozen weights.
Does not fit resistors after observing outputs. Behavioral TIA only.
"""

from __future__ import annotations

import json
import math
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np

from compile_xor import PROJECT_ROOT, find_ngspice
from exp39_pdk_o2_cell import (
    ERROR_LIMIT,
    PDK_VERSION,
    RES_MODEL,
    XHIGH_PELGROM,
    discover_pdk,
    eval_cell,
    last,
    prepend_pdk,
    run_cir,
    write_op_net,
    xhigh_r_pred,
)
from exp40_pdk_o2_cell import compile_o2_w2_1, prove_identity
from exp41_o2_residual import geometry_for_r_w, replace_resistors_w
from exp43_highgain_w10 import set_tia_gain
from exp45_documented_tia import spiceinit_hsa
from test_robustness import extract_all

CIRCUIT_DIR = PROJECT_ROOT / "circuits" / "exp54_o2"
RESULTS_DIR = PROJECT_ROOT / "results"
A = 1.0e6
Z_O2 = 2.459489570880132
Y_EXP53_NOM = 2.459890565832
NOM_ATOL_V = 1.0e-8
N_MC = 16
N_MC_RATIO = 24
WORKERS = 4
REND_MM_A = 0.0472  # official rend_mm = 0.0472/sqrt(w) on the installed card

X_RE = re.compile(
    rf"^X(\S+)\s+(\S+)\s+(\S+)\s+0\s+{re.escape(RES_MODEL)}\s+w=(\S+)\s+l=(\S+)\s*$",
    re.IGNORECASE,
)


def tag(net: str, note: str) -> str:
    return net.replace(
        "* Experiment 39 SKY130 isolated frozen o2 cell",
        f"* Experiment 54 {note}",
    )


def insert_seed(path: Path, seed: int) -> None:
    text = path.read_text(encoding="utf-8")
    text = text.replace(
        ".control\nset numdgt=12\n",
        f".control\nset numdgt=12\nset seed={int(seed)}\n",
        1,
    )
    path.write_text(text, encoding="utf-8")


def inventory(net: str) -> dict:
    inst = []
    for raw in net.splitlines():
        m = X_RE.match(raw.strip())
        if not m:
            continue
        w = float(m.group(4))
        l = float(m.group(5))
        inst.append({"name": m.group(1), "w_um": w, "l_um": l, "wl_um2": w * l})
    if not inst:
        return {"n": 0}
    wl = [x["wl_um2"] for x in inst]
    return {
        "n": len(inst),
        "w_um_unique": sorted({x["w_um"] for x in inst}),
        "l_min_um": min(x["l_um"] for x in inst),
        "l_max_um": max(x["l_um"] for x in inst),
        "wl_min_um2": min(wl),
        "wl_max_um2": max(wl),
        "wl_sum_um2": float(sum(wl)),
        "wl_median_um2": float(np.median(wl)),
        "body_sigma_median": float(XHIGH_PELGROM / math.sqrt(max(np.median(wl), 1e-12))),
        "head_sigma_w": float(REND_MM_A / math.sqrt(max(inst[0]["w_um"], 1e-12))),
    }


def tile_same_units(net: str, n_series: int, n_parallel: int) -> str:
    """Series-parallel array of identical W/L units. Equivalent R includes heads."""
    if n_series < 1 or n_parallel < 1:
        raise ValueError("tile counts must be >= 1")
    if n_series == 1 and n_parallel == 1:
        return net
    out = []
    for raw in net.splitlines():
        m = X_RE.match(raw.strip())
        if not m:
            out.append(raw)
            continue
        name, n1, n2, w, l = m.groups()
        out.append(
            f"* tile {name} {n_series}s x {n_parallel}p same W={w} L={l}"
        )
        for p in range(n_parallel):
            nodes = [n1]
            for s in range(n_series - 1):
                nodes.append(f"{name}t{p}s{s}")
            nodes.append(n2)
            for s in range(n_series):
                out.append(
                    f"X{name}p{p}s{s} {nodes[s]} {nodes[s + 1]} 0 "
                    f"{RES_MODEL} w={w} l={l}"
                )
    return "\n".join(out) + "\n"


def encode_series_split(netlist: str, catalog: list[dict], w: float, n_ser: int) -> tuple[str, list]:
    """n series units each targeting R/n (shorter L). Same total area, more heads."""
    by_name = {str(it["name"]): float(it["R"]) for it in catalog if "R" in it}
    r_re = re.compile(r"^(R)(\S+)\s+(\S+)\s+(\S+)\s+([0-9.+-eE]+)\s*$", re.IGNORECASE)
    out, geos = [], []
    for raw in netlist.splitlines():
        m = r_re.match(raw.strip())
        if not m:
            out.append(raw)
            continue
        name = m.group(1) + m.group(2)
        n1, n2, rval = m.group(3), m.group(4), float(m.group(5))
        target = by_name.get(name, rval)
        unit_r = target / float(n_ser)
        w_um, l_um = geometry_for_r_w(unit_r, w)
        geos.append(
            {
                "name": name,
                "R_target": target,
                "unit_R": unit_r,
                "w_um": w_um,
                "l_um": l_um,
                "R_pred_unit": xhigh_r_pred(w_um, l_um),
                "n_ser": n_ser,
            }
        )
        out.append(f"* series-split {name} n={n_ser} W={w_um:g} L={l_um:.8g} unitR={unit_r:.8g}")
        nodes = [n1]
        for s in range(n_ser - 1):
            nodes.append(f"{name}ss{s}")
        nodes.append(n2)
        for s in range(n_ser):
            out.append(
                f"X{name}s{s} {nodes[s]} {nodes[s + 1]} 0 "
                f"{RES_MODEL} w={w_um:.8g} l={l_um:.8g}"
            )
    return "\n".join(out) + "\n", geos


def check_geos(geos: list[dict], rel_tol: float = 2e-3) -> None:
    for g in geos:
        pred = float(g.get("R_pred") or g.get("R_pred_unit", 0.0))
        tgt = float(g.get("unit_R") if "unit_R" in g else g["R_target"])
        if tgt <= 0:
            continue
        rel = abs(pred - tgt) / tgt
        if rel > rel_tol:
            raise SystemExit(
                f"BLOCKED encode clip {g['name']} pred={pred} target={tgt} rel={rel}"
            )


def fabrics(net0: str, cat: list[dict]) -> dict:
    w10, g10 = replace_resistors_w(net0, cat, 10.0)
    check_geos(g10)
    w20, g20 = replace_resistors_w(net0, cat, 20.0)
    check_geos(g20)
    s4, gs4 = encode_series_split(net0, cat, 10.0, 4)
    check_geos(gs4)
    a = set_tia_gain(w10, A)
    return {
        "w10": {
            "label": "W=10 single (Exp53 baseline)",
            "net": a,
            "geos": g10,
            "n_series": 1,
            "n_parallel": 1,
            "kind": "width",
            "area_mult": 1.0,
        },
        "w20": {
            "label": "W=20 single (same-family encode)",
            "net": set_tia_gain(w20, A),
            "geos": g20,
            "n_series": 1,
            "n_parallel": 1,
            "kind": "width",
            "area_mult": 4.0,
        },
        "w10_2s2p": {
            "label": "W=10 2s×2p same-unit array",
            "net": tile_same_units(a, 2, 2),
            "geos": g10,
            "n_series": 2,
            "n_parallel": 2,
            "kind": "unit_array",
            "area_mult": 4.0,
        },
        "w10_4s4p": {
            "label": "W=10 4s×4p same-unit array",
            "net": tile_same_units(a, 4, 4),
            "geos": g10,
            "n_series": 4,
            "n_parallel": 4,
            "kind": "unit_array",
            "area_mult": 16.0,
        },
        "w10_s4": {
            "label": "W=10 4-series of R/4 (same-area control)",
            "net": set_tia_gain(s4, A),
            "geos": gs4,
            "n_series": 4,
            "n_parallel": 1,
            "kind": "series_split",
            "area_mult": 1.0,
        },
    }


def summarize(rows: list[dict]) -> dict | None:
    ok = [r for r in rows if r.get("abs_err") is not None and not r.get("failed")]
    if not ok:
        return None
    errs = np.array([float(r["abs_err"]) for r in ok], dtype=float)
    return {
        "n_ok": len(ok),
        "n_fail_conv": sum(1 for r in rows if r.get("failed")),
        "n_pass": int(sum(1 for r in ok if r.get("analog_pass"))),
        "mean": float(errs.mean()),
        "median": float(np.median(errs)),
        "max": float(errs.max()),
        "std": float(errs.std(ddof=1) if len(errs) > 1 else 0.0),
        "pass_rate": float(sum(1 for r in ok if r.get("analog_pass"))) / len(ok),
    }


def run_nominal(ng, key: str, fab: dict, hy, z0: float) -> dict:
    inv = inventory(fab["net"])
    path = CIRCUIT_DIR / key / "tt_nominal.cir"
    path.parent.mkdir(parents=True, exist_ok=True)
    spiceinit_hsa(path.parent)
    write_op_net(
        path,
        prepend_pdk(fab["net"], "tt", 27.0).replace(
            "* Experiment 39 SKY130 isolated frozen o2 cell",
            f"* Experiment 54 {key} tt nominal A=1e6",
        ),
        hy,
    )
    rec = eval_cell(ng, path, z0, timeout=300.0)
    rec.update(
        {
            "name": f"{key}_nominal",
            "config": key,
            "python_corrected": False,
            "inventory": inv,
        }
    )
    print(
        f"  NOM {key} y={rec.get('y')} |err|={rec.get('abs_err')} "
        f"nR={inv.get('n')} WLsum={inv.get('wl_sum_um2')}",
        flush=True,
    )
    return rec


def run_one_draw(ng, key: str, net: str, hy, z0: float, i: int, timeout: float) -> dict:
    path = CIRCUIT_DIR / key / f"ttmm_{i:03d}.cir"
    path.parent.mkdir(parents=True, exist_ok=True)
    spiceinit_hsa(path.parent)
    write_op_net(
        path,
        prepend_pdk(net, "tt_mm", 27.0).replace(
            "* Experiment 39 SKY130 isolated frozen o2 cell",
            f"* Experiment 54 {key} tt_mm draw {i} A=1e6 · model AGAUSS",
        ),
        hy,
    )
    insert_seed(path, 54000 + i)
    rec = eval_cell(ng, path, z0, timeout=timeout)
    rec.update({"draw": i, "config": key, "python_corrected": False, "seed": 54000 + i})
    print(
        f"  MM {key} {i} y={rec.get('y')} |err|={rec.get('abs_err')} "
        f"pass={rec.get('analog_pass')} fail={rec.get('failed')}",
        flush=True,
    )
    return rec


def run_mc(ng, key: str, net: str, hy, z0: float, n: int) -> list[dict]:
    timeout = 360.0 if "4s4p" in key else 180.0
    rows = [None] * n
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futs = {
            pool.submit(run_one_draw, ng, key, net, hy, z0, i, timeout): i
            for i in range(n)
        }
        for fut in as_completed(futs):
            rec = fut.result()
            rows[int(rec["draw"])] = rec
    return [r for r in rows if r is not None]


def ratio_net(w: float, l: float, n_series: int, n_parallel: int) -> str:
    base = (
        f"Xr1 a b 0 {RES_MODEL} w={w:.8g} l={l:.8g}\n"
        f"Xr2 c d 0 {RES_MODEL} w={w:.8g} l={l:.8g}\n"
    )
    return tile_same_units(base, n_series, n_parallel)


def eval_ratio(ng, key: str, net: str, i: int, corner: str) -> dict:
    path = CIRCUIT_DIR / "ratio" / key / f"{corner}_{i:03d}.cir"
    path.parent.mkdir(parents=True, exist_ok=True)
    spiceinit_hsa(path.parent)
    lines = [
        f"* Experiment 54 1:1 invert-unit ratio {key} {corner} {i}",
        f'.lib "C:/dev/pdk/sky130A/libs.tech/ngspice/sky130.lib.spice" {corner}',
        ".temp 27",
        "V1 a 0 DC 1",
        "Vm1 b 0 DC 0",
        "V2 c 0 DC 1",
        "Vm2 d 0 DC 0",
        net.rstrip(),
        ".control",
        "set numdgt=12",
        f"set seed={54100 + i}",
        "op",
        "print i(Vm1)",
        "print i(Vm2)",
        ".endc",
        ".end",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    _r, text, fail = run_cir(ng, path, timeout=60.0)
    i1 = last(extract_all(text, "i(vm1)"))
    i2 = last(extract_all(text, "i(vm2)"))
    r1 = abs(1.0 / i1) if i1 not in (None, 0.0) else None
    r2 = abs(1.0 / i2) if i2 not in (None, 0.0) else None
    rel = None
    if r1 and r2:
        rel = (r1 - r2) / (0.5 * (r1 + r2))
    rec = {
        "config": key,
        "draw": i,
        "corner": corner,
        "failed": bool(fail),
        "R1": r1,
        "R2": r2,
        "rel": rel,
        "abs_rel": abs(rel) if rel is not None else None,
    }
    print(
        f"  RATIO {key} {corner} {i} rel={rel} |rel|={rec['abs_rel']}",
        flush=True,
    )
    return rec


def decide(nom: dict, stats: dict) -> tuple[str, str, str, str]:
    """Return decision, label, status, next_experiment."""
    w10 = stats.get("w10") or {}
    arr = stats.get("w10_4s4p") or {}
    arr2 = stats.get("w10_2s2p") or {}
    w20 = stats.get("w20") or {}
    s4 = stats.get("w10_s4") or {}
    nom_w10 = nom.get("w10") or {}
    leftover_ok = (
        nom_w10.get("abs_err") is not None and float(nom_w10["abs_err"]) <= ERROR_LIMIT
    )

    def rate(s):
        return float(s.get("pass_rate") or 0.0)

    def mean(s):
        return float(s.get("mean") or 1e9)

    if not leftover_ok:
        return (
            "E",
            "W=10 NOMINAL DID NOT REPEAT EXP53",
            "NUMERICAL ISSUE",
            "Re-check Experiment 53 nominal before any tiling claim.",
        )
    if not w10:
        return (
            "E",
            "W=10 tt_mm DRAWS DID NOT CONVERGE",
            "NUMERICAL ISSUE",
            "Inspect tt_mm decks. Matching remains UNRESOLVED.",
        )

    tiled_better = arr and mean(arr) < 0.6 * mean(w10) and rate(arr) > rate(w10) + 0.15
    tiled_pass = arr and rate(arr) >= 0.999 and mean(arr) <= ERROR_LIMIT
    mid_pass = arr2 and rate(arr2) >= 0.999 and mean(arr2) <= ERROR_LIMIT
    wide_pass = w20 and rate(w20) >= 0.999 and mean(w20) <= ERROR_LIMIT
    series_helps = s4 and mean(s4) < 0.6 * mean(w10)

    if tiled_pass or mid_pass:
        return (
            "B",
            "SAME-W UNIT ARRAY PASSES ALL DRAWS IN THIS SAMPLE (NOT YIELD)",
            "PARTIALLY VALIDATED",
            "Experiment 55: host the passing array on OPA189 TIA, then a frozen F40 vector set. Still model AGAUSS.",
        )
    if wide_pass and not tiled_better:
        return (
            "B",
            "W=20 WIDTH SCALE PASSES THIS SAMPLE; UNIT ARRAY NOT EQUIVALENT",
            "PARTIALLY VALIDATED",
            "Experiment 55: separate leftover change from mismatch at W=20; do not treat as yield.",
        )
    if tiled_better and arr and mean(arr) <= ERROR_LIMIT:
        return (
            "B",
            "4s4p MEAN |err| IN 1 mV BAR BUT SAMPLE NOT ALL-PASS (NOT YIELD)",
            "PARTIALLY VALIDATED",
            "Experiment 55: more 4s4p draws and/or 8s8p if pass rate is still mixed.",
        )
    if tiled_better:
        return (
            "C",
            "UNIT ARRAY REDUCES MODEL MISMATCH BUT NOT TO THE 1 mV BAR",
            "TECHNOLOGY BOUNDARY",
            "Experiment 55: larger documented array (8s8p) or W=20+array; still not yield.",
        )
    if series_helps and not tiled_better:
        return (
            "C",
            "SERIES-SPLIT MOVED ERROR; AREA AVERAGING DID NOT DOMINATE",
            "TECHNOLOGY BOUNDARY",
            "Experiment 55: inspect head-mismatch fraction; do not blindly segment.",
        )
    if arr and w10 and abs(mean(arr) - mean(w10)) / max(mean(w10), 1e-12) < 0.25:
        return (
            "C",
            "16x UNIT ARRAY DID NOT MATERIALLY REDUCE tt_mm CELL ERROR",
            "TECHNOLOGY BOUNDARY",
            "Experiment 55: official model may be head-limited or poorly averaged; try documented family change, not invented A.",
        )
    return (
        "C",
        "MATCHING STILL UNRESOLVED AFTER AREA/TILING SWEEP",
        "TECHNOLOGY BOUNDARY",
        "Experiment 55: next documented resistor or ratio architecture. Not yield. Miller family stays closed.",
    )


def write_reports(report: dict) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / "exp54_resistor_tiling.json").write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8"
    )
    lines = [
        "# Experiment 54 — documented resistor area / unit tiling under tt_mm",
        "",
        "Experiments 1–53 were not modified. Behavioral TIA A=1e6. Official",
        "SKY130 `tt_mm` AGAUSS, not foundry yield. No resistor fitting.",
        "",
        f"**Status: {report['status']}**",
        f"**Decision {report['decision']} — {report['decision_label']}**",
        "",
        "## Official model (installed card, not invented)",
        "",
        "`res_match = 0.0347/sqrt(w*l*mult) * MC_MM_SWITCH * AGAUSS(0,1,1)`",
        "",
        "`rend_mm = 0.0472/sqrt(w)` on each head.",
        "",
        "Source: `C:/dev/pdk/sky130A/libs.ref/sky130_fd_pr/spice/"
        "sky130_fd_pr__res_xhigh_po.model.spice`.",
        "",
        "## Baseline",
        "",
        f"Experiment 53 nominal y = {Y_EXP53_NOM}",
        f"This experiment W=10 nominal y = {report['nominal']['w10'].get('y')}",
        f"Δy vs Exp53 = {report['baseline']['delta_y_vs_exp53']}",
        f"New W=10 tt_mm: pass = {report['stats']['w10']['n_pass']}/"
        f"{report['stats']['w10']['n_ok']}, mean |err| = "
        f"{report['stats']['w10']['mean']*1e3:.6f} mV "
        f"(Exp53 was 1/8, mean 3.23 mV; independent sample).",
        "",
        "## Nominal leftover (tt, no AGAUSS)",
        "",
        "| config | y (V) | |err| (mV) | pass | n devices | ΣWL (µm²) |",
        "| --- | ---: | ---: | --- | ---: | ---: |",
    ]
    for key, rec in report["nominal"].items():
        ae = rec.get("abs_err")
        inv = rec.get("inventory") or {}
        lines.append(
            f"| {key} | {rec.get('y')} | "
            f"{None if ae is None else ae * 1e3:.6f} | {rec.get('analog_pass')} | "
            f"{inv.get('n')} | {inv.get('wl_sum_um2')} |"
        )
    lines += [
        "",
        "## tt_mm cell |y−z| (not yield)",
        "",
        "| config | n | pass | mean (mV) | median (mV) | max (mV) | std (mV) |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for key, st in report["stats"].items():
        if not st:
            continue
        lines.append(
            f"| {key} | {st['n_ok']} | {st['n_pass']}/{st['n_ok']} | "
            f"{st['mean']*1e3:.6f} | {st['median']*1e3:.6f} | "
            f"{st['max']*1e3:.6f} | {st['std']*1e3:.6f} |"
        )
    if report.get("ratio_stats"):
        lines += [
            "",
            "## 1:1 invert-unit ratio |ΔR/R| (primitive, not the neuron)",
            "",
            "| config | corner | n | mean |Rrel| | max |",
            "| --- | --- | ---: | ---: | ---: |",
        ]
        for key, st in report["ratio_stats"].items():
            lines.append(
                f"| {st['config']} | {st['corner']} | {st['n']} | "
                f"{st['mean']*1e2:.4f}% | {st['max']*1e2:.4f}% |"
            )
    lines += [
        "",
        report["conclusion"],
        "",
        "## Next experiment",
        "",
        report["next_experiment"],
        "",
    ]
    (RESULTS_DIR / "exp54_resistor_tiling.md").write_text("\n".join(lines), encoding="utf-8")


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

    print("==== Reproduce Experiment 53 nominal ====", flush=True)
    exp53 = PROJECT_ROOT / "circuits" / "exp53_o2" / "tt_nominal.cir"
    base = eval_cell(ng, exp53, z0, timeout=180.0)
    dy = None if base.get("y") is None else float(base["y"]) - Y_EXP53_NOM
    print(f"  Exp53 file y={base.get('y')} dY={dy}", flush=True)
    if base.get("failed") or dy is None or abs(dy) > NOM_ATOL_V:
        raise SystemExit(f"BLOCKED Exp53 nominal repeat y={base.get('y')} dY={dy}")

    fabs = fabrics(net0, cat)
    order = ["w10", "w20", "w10_2s2p", "w10_4s4p", "w10_s4"]

    print("==== Nominal tt leftover ====", flush=True)
    nominal = {}
    for key in order:
        nominal[key] = run_nominal(ng, key, fabs[key], hy, z0)

    w10y = nominal["w10"].get("y")
    if w10y is None or abs(float(w10y) - Y_EXP53_NOM) > NOM_ATOL_V:
        raise SystemExit(f"BLOCKED new W=10 nominal y={w10y} vs Exp53 {Y_EXP53_NOM}")

    stats = {}
    draws = {}
    for key in order:
        print(f"==== tt_mm {key} n={N_MC} ====", flush=True)
        rows = run_mc(ng, key, fabs[key]["net"], hy, z0, N_MC)
        draws[key] = [
            {
                "draw": r.get("draw"),
                "y": r.get("y"),
                "abs_err": r.get("abs_err"),
                "analog_pass": r.get("analog_pass"),
                "failed": r.get("failed"),
                "seed": r.get("seed"),
            }
            for r in rows
        ]
        stats[key] = summarize(rows)
        print(f"  STAT {key} {stats[key]}", flush=True)

    print("==== 1:1 ratio primitive ====", flush=True)
    l_inv = 49.614372
    r_inv = xhigh_r_pred(10.0, l_inv)
    w20, l20 = geometry_for_r_w(r_inv, 20.0)
    ratio_cfgs = {
        "w10": ratio_net(10.0, l_inv, 1, 1),
        "w20": ratio_net(w20, l20, 1, 1),
        "w10_2s2p": ratio_net(10.0, l_inv, 2, 2),
        "w10_4s4p": ratio_net(10.0, l_inv, 4, 4),
    }
    ratio_rows = []
    for key, net in ratio_cfgs.items():
        ratio_rows.append(eval_ratio(ng, key, net, 0, "tt"))
        for i in range(N_MC_RATIO):
            ratio_rows.append(eval_ratio(ng, key, net, i, "tt_mm"))

    ratio_stats = {}
    for key in ratio_cfgs:
        mm = [
            r
            for r in ratio_rows
            if r["config"] == key and r["corner"] == "tt_mm" and r.get("abs_rel") is not None
        ]
        if not mm:
            continue
        arr = np.array([float(r["abs_rel"]) for r in mm], dtype=float)
        ratio_stats[key] = {
            "config": key,
            "corner": "tt_mm",
            "n": len(mm),
            "mean": float(arr.mean()),
            "max": float(arr.max()),
            "std": float(arr.std(ddof=1) if len(arr) > 1 else 0.0),
        }

    decision, label, status, nxt = decide(nominal, stats)
    report = {
        "experiment_id": "exp54",
        "kind": "SKY130 documented resistor area / unit tiling under tt_mm",
        "status": status,
        "decision": decision,
        "decision_label": label,
        "yield_claim": False,
        "silicon": False,
        "realism_level": 4,
        "realism_note": "Official PDK resistor compact model + behavioral TIA. Not silicon.",
        "A": A,
        "N_MC": N_MC,
        "official_body_pelgrom": XHIGH_PELGROM,
        "official_rend_mm_A": REND_MM_A,
        "baseline": {
            "exp53_nominal_y": Y_EXP53_NOM,
            "exp53_file_y": base.get("y"),
            "delta_y_vs_exp53": dy,
            "new_w10_nominal_y": nominal["w10"].get("y"),
        },
        "inventory": {k: inventory(fabs[k]["net"]) for k in order},
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
        "ratio_stats": ratio_stats,
        "ratio_nominal": [r for r in ratio_rows if r["corner"] == "tt"],
        "matching": "UNRESOLVED" if decision in {"C", "D", "E"} else "IMPROVED_IN_SAMPLE",
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
    print(f"Experiment 54 Decision {decision} — {label}", flush=True)


if __name__ == "__main__":
    main()
