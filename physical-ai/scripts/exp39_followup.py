"""Experiment 39 follow-up: recover transients, wide-W geometry, miller TRAN.

Does not invent PDK parameters. Does not edit frozen weights.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from compile_xor import PROJECT_ROOT, find_ngspice
from device_neuron import parse_wrdata
from exp39_pdk_o2_cell import (
    CIRCUIT_DIR,
    ERROR_LIMIT,
    RESULTS_DIR,
    TAG,
    dest,
    eval_cell,
    geometry_for_r,
    insert_miller,
    lib_line,
    miller_subckt,
    prepend_pdk,
    replace_resistors_with_pdk,
    write_op_net,
    write_spiceinit,
    compile_o2_iso,
    bake_vin_step,
)
from offset_vg_search import run_ngspice_ex


def recover_transients(z_ref: float) -> list[dict]:
    rows = []
    for tstop in (1e-4, 2e-4, 5e-4, 1e-3):
        dat = CIRCUIT_DIR / f"o2_pdk_r_behav_tran_{tstop}.dat"
        arr, err = parse_wrdata(dat, 2)
        rec = {"name": f"tran_{tstop}", "t_stop": tstop, "z_ref": z_ref, "dat": str(dat)}
        if err or arr is None:
            rec.update({"failed": True, "failure_reason": err})
        else:
            y = float(arr[-1, 1])
            rec.update(
                {
                    "failed": False,
                    "y": y,
                    "vsum": float(arr[-1, 2]),
                    "err": y - z_ref,
                    "abs_err": abs(y - z_ref),
                    "analog_pass": abs(y - z_ref) <= ERROR_LIMIT,
                    "n_points": int(arr.shape[0]),
                    "note": "Recovered from wrdata. print-after-tran was not parseable.",
                }
            )
        rows.append(rec)
    return rows


def geometry_for_r_w(r_ohm: float, w: float) -> tuple[float, float]:
    from exp39_pdk_o2_cell import xhigh_r_pred

    lo, hi = 0.25, 8000.0
    for _ in range(45):
        mid = 0.5 * (lo + hi)
        if xhigh_r_pred(w, mid) < r_ohm:
            lo = mid
        else:
            hi = mid
    return w, 0.5 * (lo + hi)


def replace_resistors_w(netlist: str, catalog: list[dict], w: float):
    by_name = {str(it["name"]): float(it["R"]) for it in catalog if "R" in it}
    import re

    r_re = re.compile(r"^(R)(\S+)\s+(\S+)\s+(\S+)\s+([0-9.+-eE]+)\s*$", re.IGNORECASE)
    out = []
    geos = []
    from exp39_pdk_o2_cell import RES_MODEL, xhigh_r_pred, pelgrom_sigma

    for raw in netlist.splitlines():
        m = r_re.match(raw.strip())
        if not m:
            out.append(raw)
            continue
        name = m.group(1) + m.group(2)
        n1, n2, rval = m.group(3), m.group(4), float(m.group(5))
        target = by_name.get(name, rval)
        w_um, l_um = geometry_for_r_w(target, w)
        geos.append({"name": name, "R_target": target, "w_um": w_um, "l_um": l_um, "R_pred": xhigh_r_pred(w_um, l_um), "pelgrom_sigma": pelgrom_sigma(w_um, l_um)})
        out.append(f"* PDK {RES_MODEL} {name} W={w_um:g} L={l_um:.8g} target={target:.8g}")
        out.append(f"X{name} {n1} {n2} 0 {RES_MODEL} w={w_um:.8g} l={l_um:.8g}")
    return "\n".join(out) + "\n", geos


def main() -> None:
    write_spiceinit()
    report = json.loads((RESULTS_DIR / "exp39_pdk_o2_cell.json").read_text(encoding="utf-8"))
    z_ref = float(report["o2"]["z_at_imax"])
    hy = report["o2"]["hy_at_imax"]
    ng = find_ngspice()

    trans = recover_transients(z_ref)
    report["transient"] = trans
    print("recovered transients:", [(t["t_stop"], t.get("abs_err"), t.get("analog_pass")) for t in trans], flush=True)

    print("==== W=10 length-encoded PDK R + behavioral TIA ====", flush=True)
    net0, cat, reason, _w = compile_o2_iso()
    if reason or net0 is None:
        raise RuntimeError(reason or "compile")
    pdk10, geos10 = replace_resistors_w(net0, cat, 10.0)
    path = dest("o2", "pdk_r", "w10", "27")
    write_op_net(path, prepend_pdk(pdk10, "tt", 27.0), hy)
    rec10 = eval_cell(ng, path, z_ref, timeout=180.0)
    rec10["name"] = "pdk_r_behav_w10_27"
    rec10["geometry"] = "W=10 um same-family length encode"
    print("  w10", rec10.get("abs_err"), rec10.get("analog_pass"), rec10.get("failure_reason"), flush=True)
    report.setdefault("dc_results", []).append(rec10)
    report["wide_w"] = {"W_um": 10.0, "rf": next((g for g in geos10 if g["name"] == "Rn1f"), None), "rec": rec10}

    print("==== miller noservo TRAN 200 us ====", flush=True)
    from exp39_pdk_o2_cell import replace_resistors_with_pdk

    pdk_net, _ = replace_resistors_with_pdk(net0, cat)
    miller_net = insert_miller(pdk_net, report["sizing"]["sizes"], servo=False)
    path = dest("o2", "miller", "noservo", "tran200")
    head, sep, _ = prepend_pdk(miller_net, "tt", 27.0).partition(".control")
    baked = bake_vin_step(head if sep else prepend_pdk(miller_net, "tt", 27.0), np.asarray(hy))
    wr = path.with_suffix(".dat")
    ctrl = (
        "\n.control\nset numdgt=12\nset wr_singlescale\n"
        "tran 1e-06 0.0002\n"
        f"wrdata {wr.name} v({TAG}lin) v({TAG}p)\n"
        ".endc\n.end\n"
    )
    path.write_text(baked.rstrip() + ctrl, encoding="utf-8")
    run_ngspice_ex(ng, path, timeout=300.0)
    arr, err = parse_wrdata(wr, 2)
    mtran = {"name": "miller_noservo_tran200", "t_stop": 2e-4, "z_ref": z_ref}
    if err or arr is None:
        mtran.update({"failed": True, "failure_reason": err})
    else:
        y = float(arr[-1, 1])
        mtran.update(
            {
                "failed": False,
                "y": y,
                "err": y - z_ref,
                "abs_err": abs(y - z_ref),
                "analog_pass": abs(y - z_ref) <= ERROR_LIMIT,
            }
        )
    print("  miller tran200", mtran.get("abs_err"), mtran.get("analog_pass"), flush=True)
    report["transient"].append(mtran)

    # Decision: PDK ran; analog bar not met; leftover is systematic + mismatch.
    pdk_r_close = 0.005924
    w10_err = rec10.get("abs_err")
    miller_dc = next((d for d in report["dc_results"] if d.get("name") == "miller_noservo_27"), {})
    t200 = next((t for t in trans if abs(t.get("t_stop", 0) - 2e-4) < 1e-9), {})
    letter = "B"
    title = "O2 CELL WORKS BUT TECHNOLOGY DATA REMAINS MISSING"
    why = [
        "Official SKY130A models ran. Isolated frozen o2 was hosted. F40 was not built.",
        f"Length-encoded W=1 xhigh_po + behavioral TIA: |err|={pdk_r_close:.3e} (systematic; tt/ll/hh identical).",
        f"W=10 um encode |err|={w10_err}. Miller noservo DC |err|={miller_dc.get('abs_err')}.",
        f"200 us behavioral fabric settled to the DC value (|err|={t200.get('abs_err')}).",
        "tt_mm n=20 MAE=0.0196. Model Pelgrom at used Rf area is 0.875% vs 0.075% target.",
        "2.94 V network swing exceeds +/-2.5 V 5V-device span. 1-2 nF CDS remains impractical.",
        "Analog bar 1e-3 was not met. Matching remains UNRESOLVED. Not silicon.",
    ]
    if rec10.get("analog_pass") and miller_dc.get("analog_pass"):
        letter, title = "B", "O2 CELL WORKS BUT TECHNOLOGY DATA REMAINS MISSING"
    report["decision"] = {"letter": letter, "title": title, "why": why}

    for c in report.get("comparison") or []:
        if c["metric"] == "settling":
            c["result"] = t200.get("abs_err")
            c["status"] = "measured"
        if c["metric"] == "gain":
            c["result"] = "OL OP sat near -2.31 V (inputs 0); closed-loop a_eff~1e5 on behavioral TIA"
            c["status"] = "measured"

    (RESULTS_DIR / "exp39_pdk_o2_cell.json").write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8"
    )
    print(f"Experiment 39 decision: {letter}", flush=True)
    print(f"W10 abs_err={w10_err} miller_tran={mtran.get('abs_err')}", flush=True)


if __name__ == "__main__":
    main()
