"""Experiment 50: Track B inventory + existing miller open-loop A.

No W/L resize. No invented devices. Experiments 1-49 not modified.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from compile_xor import PROJECT_ROOT, find_ngspice
from exp39_pdk_o2_cell import (
    ERROR_LIMIT,
    NFET,
    PDK_LIB,
    PDK_VERSION,
    PFET,
    discover_pdk,
    last,
    lib_line,
    miller_subckt,
    run_cir,
)
from exp41_o2_residual import MILLER_SIZES
from exp44_tia_requirements import A_CROSS, RFG
from exp45_documented_tia import spiceinit_hsa
from test_robustness import extract_all

CIRCUIT_DIR = PROJECT_ROOT / "circuits" / "exp50_amp"
RESULTS_DIR = PROJECT_ROOT / "results"
VSUPPLY = 2.5
A_NEED = A_CROSS
I_LOAD = 73.71e-6
VIDS = (10e-6, 100e-6, 1e-3, 10e-3)


def inventory(pdk: dict) -> dict:
    tech = Path(pdk["lib"]).parent if pdk.get("lib") else None
    analog_hits = []
    if tech and tech.is_dir():
        for p in tech.rglob("*"):
            n = p.name.lower()
            if any(k in n for k in ("opamp", "ota", "folded", "telescop", "gainboost")):
                analog_hits.append(str(p))
    return {
        "pdk": pdk.get("variant"),
        "version": pdk.get("ciel_current"),
        "lib": pdk.get("lib"),
        "runnable": pdk.get("runnable"),
        "devices_used": [NFET, PFET, "sky130_fd_pr__res_xhigh_po"],
        "documented_opamp_cells_in_tech": analog_hits[:20],
        "ihp_installed": False,
        "gf180_installed": False,
        "note": (
            "SKY130A fd_pr has 5V MOS and xhigh_po. A filename scan of the "
            "ngspice tech tree found no opamp/OTA IP cells. The existing "
            "sky_miller is a campaign-constructed two-stage using documented "
            "5V FETs and Experiment 39 sizes, not a foundry analog library cell."
        ),
    }


def write_ol(path: Path, vid: float, i_load: float | None) -> None:
    lines = [
        "* Experiment 50 isolated sky_miller open-loop · no W/L resize",
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
        "print v(inp)",
        "print v(inn)",
        ".endc",
        ".end",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def run_ol(ng, vid: float, i_load: float | None, name: str) -> dict:
    path = CIRCUIT_DIR / f"{name}.cir"
    write_ol(path, vid, i_load)
    _r, text, fail = run_cir(ng, path, timeout=120.0)
    rec = {
        "name": name,
        "vid": vid,
        "i_load": i_load,
        "failed": bool(fail),
        "failure_reason": fail,
        "python_corrected": False,
        "resized": False,
    }
    if fail:
        rec["log_tail"] = text[-400:]
        print(f"  {name} FAIL {fail}", flush=True)
        return rec
    vout = last(extract_all(text, "v(out)"))
    rec["vout"] = vout
    rec["a_ol"] = None if vout is None or vid == 0 else vout / vid
    rec["headroom_V"] = None if vout is None else VSUPPLY - vout
    print(f"  {name} vout={vout} A={rec['a_ol']} headroom={rec['headroom_V']}", flush=True)
    return rec


def stages_needed(a: float | None) -> int | None:
    if a is None or a <= 1.0:
        return None
    return int(math.ceil(math.log(A_NEED) / math.log(a)))


def main() -> None:
    pdk = discover_pdk()
    if pdk.get("ciel_current") != PDK_VERSION:
        raise SystemExit("BLOCKED PDK")
    CIRCUIT_DIR.mkdir(parents=True, exist_ok=True)
    spiceinit_hsa(CIRCUIT_DIR)
    ng = find_ngspice()
    inv = inventory(pdk)

    print("Open-loop existing miller, no load", flush=True)
    bare = [run_ol(ng, vid, None, f"ol_noload_vid{vid:.0e}") for vid in VIDS]
    print("Open-loop existing miller, 73.71 uA load", flush=True)
    loaded = [run_ol(ng, vid, I_LOAD, f"ol_load_vid{vid:.0e}") for vid in VIDS]

    def pick_a(rows):
        ok = [r for r in rows if r.get("a_ol") and r.get("headroom_V") and r["headroom_V"] > 0.05]
        return ok[0] if ok else None

    a_bare = pick_a(bare)
    a_load = pick_a(loaded)
    a0 = (a_bare or {}).get("a_ol")
    a1 = (a_load or {}).get("a_ol")
    n0 = stages_needed(a0)
    n1 = stages_needed(a1)

    # Two identical copies in cascade would give A^2 if each stays linear.
    a2 = None if a1 is None else a1 * a1
    two_enough = a2 is not None and a2 >= A_NEED

    if a1 is not None and a1 >= A_NEED:
        decision, label, status = (
            "A",
            "EXISTING MILLER OPEN-LOOP ALREADY MEETS A_ol",
            "PARTIALLY VALIDATED",
        )
        nxt = "Experiment 51: explain why the TIA a_eff is only 245 if A_ol is large."
    elif two_enough:
        decision, label, status = (
            "B",
            "TWO IDENTICAL DOCUMENTED MILLERS COULD MEET A_ol IN CASCADE",
            "PROJECTED",
        )
        nxt = (
            "Experiment 51: close the TIA loop around two copies of the existing "
            "sky_miller (no new W/L). Measure isolated W=10 o2."
        )
    elif n1 is not None and n1 <= 3:
        decision, label, status = (
            "B",
            f"IDENTICAL-MILLER CASCADE WOULD NEED {n1} STAGES FOR A_ol",
            "PROJECTED",
        )
        nxt = (
            f"Experiment 51: test a {n1}-copy cascade of the existing sky_miller "
            "as a composite TIA on W=10 o2. No new W/L. TRAN for stability."
        )
    else:
        decision, label, status = (
            "C",
            "EXISTING MILLER GAIN IS TOO LOW FOR A SHORT IDENTICAL CASCADE",
            "TECHNOLOGY BOUNDARY",
        )
        nxt = (
            "Experiment 51: another documented architecture class, or accept "
            "Level-1 OPA189 as the TIA host and move the resistor-matching track."
        )

    report = {
        "experiment_id": "exp50",
        "kind": "Track B inventory + existing miller A_ol",
        "status": status,
        "decision": decision,
        "decision_label": label,
        "physical_tia_validated": False,
        "resized": False,
        "A_need": A_NEED,
        "RfG": RFG,
        "inventory": inv,
        "bare": bare,
        "loaded": loaded,
        "A_ol_noload_pick": a0,
        "A_ol_loaded_pick": a1,
        "identical_stages_needed_loaded": n1,
        "A_two_copy_projected": a2,
        "two_copy_meets_A": two_enough,
        "matching": "UNRESOLVED",
        "next_experiment": nxt,
        "conclusion": (
            f"Decision {decision} — {label}. "
            f"Loaded A_ol pick = {a1}; stages for A>={A_NEED:.0f} = {n1}. "
            "No foundry opamp cell was found in the SKY130A tech tree. "
            "Not silicon. No W/L invented."
        ),
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / "exp50_pdk_amp_inventory.json").write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8"
    )
    lines = [
        "# Experiment 50 — Track B inventory and existing miller A_ol",
        "",
        "Experiments 1–49 were not modified. No W/L resize. Not silicon.",
        "",
        f"**Status: {status}**",
        f"**Decision {decision} — {label}**",
        "",
        "## Inventory",
        "",
        inv["note"],
        "",
        f"- Documented opamp/OTA filenames in tech tree: {inv['documented_opamp_cells_in_tech'] or 'none'}",
        f"- IHP / GF180 installed: no",
        "",
        "## Isolated sky_miller open-loop (Exp39 sizes)",
        "",
        "| load | Vid | Vout (V) | A_ol | headroom (V) |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for r in bare + loaded:
        load = "none" if not r.get("i_load") else f"{r['i_load']*1e6:.2f} uA"
        lines.append(
            f"| {load} | {r.get('vid')} | {r.get('vout')} | {r.get('a_ol')} | {r.get('headroom_V')} |"
        )
    lines += [
        "",
        f"A required (Exp43/44) = {A_NEED:.8g}. Loaded A_ol pick = {a1}. "
        f"Identical stages needed = {n1}. Two-copy A projected = {a2}.",
        "",
        report["conclusion"],
        "",
        "## Next experiment",
        "",
        nxt,
        "",
    ]
    (RESULTS_DIR / "exp50_pdk_amp_inventory.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"Experiment 50 Decision {decision} — {label}", flush=True)


if __name__ == "__main__":
    main()
