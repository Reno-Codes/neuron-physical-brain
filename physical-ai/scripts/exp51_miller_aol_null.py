"""Experiment 51: offset-null existing sky_miller, then incremental A_ol.

No W/L resize. Does not modify Experiments 1-50. Not silicon.
"""

from __future__ import annotations

import json
from pathlib import Path

from compile_xor import PROJECT_ROOT, find_ngspice
from exp39_pdk_o2_cell import (
    PDK_VERSION,
    discover_pdk,
    last,
    lib_line,
    miller_subckt,
    run_cir,
)
from exp41_o2_residual import MILLER_SIZES
from exp44_tia_requirements import A_CROSS
from exp45_documented_tia import spiceinit_hsa
from exp50_pdk_amp_inventory import VSUPPLY
from test_robustness import extract_all

CIRCUIT_DIR = PROJECT_ROOT / "circuits" / "exp51_amp"
RESULTS_DIR = PROJECT_ROOT / "results"
I_LOAD = 73.71e-6
DVID = 20e-6


def write_ol(path: Path, vid: float, i_load: float | None) -> None:
    lines = [
        "* Experiment 51 offset-null miller A_ol · no W/L resize",
        lib_line("tt"),
        ".temp 27",
        *miller_subckt(MILLER_SIZES),
        f"Vdd vdd 0 DC {VSUPPLY}",
        f"Vss vss 0 DC {-VSUPPLY}",
        "Vinn inn 0 DC 0",
        f"Vinp inp 0 DC {vid:.15g}",
        "Xamp inp inn out vdd vss sky_miller",
        "Cload out 0 1p",
    ]
    if i_load:
        lines.append(f"Iload out 0 DC {i_load:.15g}")
    lines += [
        ".control",
        "set numdgt=12",
        "op",
        "print v(out)",
        ".endc",
        ".end",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def vout_at(ng, vid: float, i_load: float | None, tag: str) -> dict:
    path = CIRCUIT_DIR / f"{tag}.cir"
    write_ol(path, vid, i_load)
    _r, text, fail = run_cir(ng, path, timeout=90.0)
    rec = {"vid": vid, "i_load": i_load, "failed": bool(fail), "failure_reason": fail, "path": str(path)}
    if fail:
        print(f"  {tag} FAIL {fail}", flush=True)
        return rec
    rec["vout"] = last(extract_all(text, "v(out)"))
    rec["headroom_p"] = None if rec["vout"] is None else VSUPPLY - rec["vout"]
    rec["headroom_n"] = None if rec["vout"] is None else rec["vout"] + VSUPPLY
    rec["linearish"] = (
        rec["headroom_p"] is not None
        and rec["headroom_p"] > 0.15
        and rec["headroom_n"] > 0.15
    )
    print(f"  {tag} vid={vid} vout={rec.get('vout')} lin={rec.get('linearish')}", flush=True)
    return rec


def null_vid(ng, i_load: float | None, prefix: str) -> dict:
    lo, hi = 0.0, 0.02
    vlo = vout_at(ng, lo, i_load, f"{prefix}_lo")
    vhi = vout_at(ng, hi, i_load, f"{prefix}_hi")
    mid_rec = None
    for i in range(12):
        mid = 0.5 * (lo + hi)
        mid_rec = vout_at(ng, mid, i_load, f"{prefix}_m{i}")
        y = mid_rec.get("vout")
        if y is None:
            break
        if y < 0:
            lo = mid
        else:
            hi = mid
        if abs(y) < 0.05 and mid_rec.get("linearish"):
            break
    return {"lo": vlo, "hi": vhi, "null": mid_rec}


def incremental(ng, vid0: float, i_load: float | None, prefix: str) -> dict:
    a = vout_at(ng, vid0 - DVID, i_load, f"{prefix}_m")
    b = vout_at(ng, vid0 + DVID, i_load, f"{prefix}_p")
    ya, yb = a.get("vout"), b.get("vout")
    rec = {
        "vid0": vid0,
        "dvid": DVID,
        "minus": a,
        "plus": b,
        "linear_pair": bool(a.get("linearish") and b.get("linearish")),
        "python_corrected": False,
    }
    if ya is not None and yb is not None:
        rec["a_inc"] = (yb - ya) / (2.0 * DVID)
        rec["both_linear"] = rec["linear_pair"]
    print(f"  incremental A={rec.get('a_inc')} linear={rec.get('linear_pair')}", flush=True)
    return rec


def main() -> None:
    pdk = discover_pdk()
    if pdk.get("ciel_current") != PDK_VERSION:
        raise SystemExit("BLOCKED PDK")
    CIRCUIT_DIR.mkdir(parents=True, exist_ok=True)
    spiceinit_hsa(CIRCUIT_DIR)
    ng = find_ngspice()

    print("Null no-load", flush=True)
    n0 = null_vid(ng, None, "bare")
    print("Null 73.71 uA load", flush=True)
    n1 = null_vid(ng, I_LOAD, "load")

    inc0 = inc1 = None
    if n0.get("null") and n0["null"].get("vid") is not None:
        inc0 = incremental(ng, n0["null"]["vid"], None, "bare_inc")
    if n1.get("null") and n1["null"].get("vid") is not None:
        inc1 = incremental(ng, n1["null"]["vid"], I_LOAD, "load_inc")

    a_load = (inc1 or {}).get("a_inc")
    lin = bool((inc1 or {}).get("linear_pair"))
    if lin and a_load is not None and abs(a_load) >= A_CROSS:
        decision, label, status = (
            "A",
            "OFFSET-NULLED MILLER A_ol MEETS 128203",
            "PARTIALLY VALIDATED",
        )
        nxt = "Experiment 52: use that linear region in the W=10 TIA (still no new W/L)."
    elif lin and a_load is not None:
        n = None
        if abs(a_load) > 1:
            import math

            n = int(math.ceil(math.log(A_CROSS) / math.log(abs(a_load))))
        decision, label, status = (
            "B",
            f"OFFSET-NULLED A_ol = {a_load:.4g}; IDENTICAL CASCADE NEEDS ~{n} STAGES",
            "PARTIALLY VALIDATED",
        )
        nxt = (
            "Experiment 52: if n<=3, test that many copies of sky_miller as a "
            "composite TIA on W=10 o2. If n>3, close identical-miller cascade."
        )
    else:
        decision, label, status = (
            "E",
            "COULD NOT HOLD A LINEAR REGION AFTER OFFSET NULL",
            "NUMERICAL ISSUE",
        )
        nxt = (
            "Experiment 52: accept in-TIA a_eff~245 as the gain bound and close "
            "this miller family, or move the matching track. Level-1 host remains OPA189."
        )

    report = {
        "experiment_id": "exp51",
        "kind": "Offset-nulled incremental A_ol of existing sky_miller",
        "status": status,
        "decision": decision,
        "decision_label": label,
        "physical_tia_validated": False,
        "resized": False,
        "A_need": A_CROSS,
        "null_noload": n0,
        "null_loaded": n1,
        "inc_noload": inc0,
        "inc_loaded": inc1,
        "exp50_A_ol_withdrawn": True,
        "matching": "UNRESOLVED",
        "next_experiment": nxt,
        "conclusion": (
            f"Decision {decision} — {label}. "
            "No W/L invented. Not silicon. Experiment 50 rail/Vid ratio remains withdrawn."
        ),
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / "exp51_miller_aol_null.json").write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8"
    )
    a0 = (inc0 or {}).get("a_inc")
    lines = [
        "# Experiment 51 — offset-nulled incremental miller A_ol",
        "",
        "Experiments 1–50 were not modified. No W/L resize. Not silicon.",
        "",
        f"**Status: {status}**",
        f"**Decision {decision} — {label}**",
        "",
        f"- Null Vid no-load = {None if not n0.get('null') else n0['null'].get('vid')}",
        f"- Null Vid 73.71 µA = {None if not n1.get('null') else n1['null'].get('vid')}",
        f"- Incremental A no-load = {a0}",
        f"- Incremental A loaded = {a_load}",
        f"- Linear pair loaded = {lin}",
        "",
        report["conclusion"],
        "",
        "## Next experiment",
        "",
        nxt,
        "",
    ]
    (RESULTS_DIR / "exp51_miller_aol_null.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"Experiment 51 Decision {decision} — {label}", flush=True)


if __name__ == "__main__":
    main()
