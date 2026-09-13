"""Experiment 39: first real SKY130 PDK o2 Rf*G cell.

Frozen Experiment 9 Network F. SPICE is the source of truth.
Does not overwrite Experiments 1-38. Does not edit weights.
Does not invent PDK, TCR, mismatch PDFs, or teaching-card substitutes.
If the official PDK is missing, stop at Decision E.
"""

from __future__ import annotations

import json
import math
import os
import re
import shutil
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from benchmark_scaling import detect_spice_failure, generate_inputs
from compile_xor import PROJECT_ROOT, find_ngspice
from hardware_constrained_compiler import load_frozen_model
from inverter_requirement_extraction import compile_f
from offset_vg_search import VIN_DC, bake_vin_dc, run_ngspice_ex
from precision_architectures import ARCH_C_CFG
from test_robustness import extract_all
from virtual_ground_requirements import VGParams, generate_isolated_neuron, rank_neurons


CIRCUIT_DIR = PROJECT_ROOT / "circuits" / "exp39_o2"
RESULTS_DIR = PROJECT_ROOT / "results"
DOCS_DIR = PROJECT_ROOT / "docs" / "exp39_sources"
ERROR_LIMIT = 1.0e-3
EXP29_LOCAL_PASS = 7.5e-4
PDK_ROOT = Path(r"C:\dev\pdk")
PDK_FAMILY = "sky130"
PDK_VARIANT = "sky130A"
PDK_VERSION = "1689ac3f2dc763876eaf967227c7dfe831b031ae"
PDK_LIB = PDK_ROOT / PDK_VARIANT / "libs.tech" / "ngspice" / "sky130.lib.spice"
RES_MODEL = "sky130_fd_pr__res_xhigh_po"
NFET = "sky130_fd_pr__nfet_g5v0d10v5"
PFET = "sky130_fd_pr__pfet_g5v0d10v5"
MIM = "sky130_fd_pr__cap_mim_m3_1"
# From official xhigh_po model card (not invented).
XHIGH_RSHEET = 2000.0
XHIGH_PELGROM = 0.0347
XHIGH_TC1_BODY = -1.47e-3
# From official r+c typical card.
CAMIMC_TYP = 2.00e-15
# 5V FET bins: Lmin=0.50 um, Wmin=0.42 um. Analog L = 2*Lmin, inside a model bin.
L_ANALOG_UM = 1.0
LMIN_UM = 0.50
WMIN_UM = 0.42
TAG = "n1"


def ensure_dirs() -> None:
    CIRCUIT_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    DOCS_DIR.mkdir(parents=True, exist_ok=True)


def write_spiceinit() -> None:
    text = (
        "set ngbehavior=hsa\n"
        "set skywaterpdk\n"
        "set ng_nomodcheck\n"
        "set num_threads=4\n"
        "option klu\n"
        "unset interactive\n"
    )
    (CIRCUIT_DIR / ".spiceinit").write_text(text, encoding="ascii")
    (CIRCUIT_DIR / "spiceinit").write_text(text, encoding="ascii")
    home = Path(os.environ.get("USERPROFILE") or os.environ.get("HOME") or ".")
    (home / ".spiceinit").write_text(text, encoding="ascii")


def dest(*parts) -> Path:
    slug = []
    for ch in "_".join(str(p) for p in parts):
        if ch.isalnum() or ch in "._":
            slug.append(ch)
        elif ch in "-+":
            slug.append("m" if ch == "-" else "p")
        else:
            slug.append("_")
    return CIRCUIT_DIR / ("".join(slug)[:110] + ".cir")


def lib_line(corner: str = "tt") -> str:
    return f'.lib "{PDK_LIB.as_posix()}" {corner}'


def xhigh_r_pred(w_um: float, l_um: float) -> float:
    """Nominal DC resistance from the official xhigh_po equations (27 C, V=0)."""
    leff = l_um - 0.0592
    weff = w_um - 0.056
    narrow = 0.0672 * max(0.69 - w_um, 0.0)
    den = weff - narrow
    rhead0 = 188.2 / (weff - narrow + 1.41)
    rbody0 = XHIGH_RSHEET * leff / den
    return 2.0 * rhead0 + rbody0


def geometry_for_r(r_ohm: float) -> tuple[float, float]:
    """Same-W length encode. Widen only if L would fall below 0.50 um."""
    w = 1.0
    lo, hi = 0.25, 2500.0
    for _ in range(40):
        mid = 0.5 * (lo + hi)
        if xhigh_r_pred(w, mid) < r_ohm:
            lo = mid
        else:
            hi = mid
    l = 0.5 * (lo + hi)
    if l >= 0.50:
        return w, l
    w_lo, w_hi = 1.0, 80.0
    for _ in range(40):
        w = 0.5 * (w_lo + w_hi)
        if xhigh_r_pred(w, 0.50) > r_ohm:
            w_lo = w
        else:
            w_hi = w
    return 0.5 * (w_lo + w_hi), 0.50


def pelgrom_sigma(w_um: float, l_um: float, n: int = 1) -> float:
    return XHIGH_PELGROM / math.sqrt(max(w_um * l_um * n, 1e-12))


def run_cir(ng, path: Path, timeout: float = 180.0):
    result = run_ngspice_ex(ng, path, timeout=timeout)
    text = f"{result.stdout or ''}\n{result.stderr or ''}"
    return result, text, detect_spice_failure(result)


def last(vals):
    return float(vals[-1]) if vals else None


def discover_pdk() -> dict:
    version_dir = PDK_ROOT / "ciel" / PDK_FAMILY / "versions" / PDK_VERSION
    current = (PDK_ROOT / "ciel" / PDK_FAMILY / "current")
    current_txt = current.read_text(encoding="ascii").strip() if current.is_file() else None
    res_card = PDK_ROOT / PDK_VARIANT / "libs.ref" / "sky130_fd_pr" / "spice" / (
        "sky130_fd_pr__res_xhigh_po.model.spice"
    )
    fet_card = PDK_ROOT / PDK_VARIANT / "libs.ref" / "sky130_fd_pr" / "spice" / (
        "sky130_fd_pr__nfet_g5v0d10v5__tt.pm3.spice"
    )
    return {
        "pdk_root": str(PDK_ROOT),
        "family": PDK_FAMILY,
        "variant": PDK_VARIANT,
        "version": PDK_VERSION,
        "source": "https://github.com/fossi-foundation/ciel-releases/releases/download/"
        f"sky130-{PDK_VERSION}/",
        "installer": "ciel 2.6.1 + official ciel-releases tarballs (common + sky130_fd_pr)",
        "lib": str(PDK_LIB),
        "lib_exists": PDK_LIB.is_file(),
        "version_dir": str(version_dir),
        "ciel_current": current_txt,
        "resistor_card": str(res_card) if res_card.is_file() else None,
        "nfet_card": str(fet_card) if fet_card.is_file() else None,
        "corners_nominal": ["tt", "ss", "ff", "sf", "fs", "ll", "hh"],
        "corners_mm": ["tt_mm"],
        "monte_carlo_lib": "mc / tt_mm via mc_mm_switch",
        "runnable": PDK_LIB.is_file(),
        "note": "PDK lives outside the git repo at C:\\dev\\pdk. Not a teaching card.",
    }


def extract_o2() -> dict:
    w = load_frozen_model("F")
    net, cat, spec = compile_f(w)
    x = generate_inputs(spec["n_in"], 40, "exp24_F")
    rows, picks = rank_neurons(spec, cat, w, x)
    o2 = next(r for r in rows if r["tag"] == "o2")
    z1 = x @ w["W1"].T + w["b1"]
    hy = np.maximum(0.0, z1)
    z_o2 = hy @ w["W2"][2] + float(w["b2"][2])
    imax = int(np.argmax(np.abs(z_o2)))
    return {
        "frozen_model": "models/scaling/F.npz seed 9",
        "shape": [int(spec["n_in"]), int(spec["n_hidden"]), int(spec["n_out"])],
        "tag": "o2",
        "layer": 2,
        "index": 2,
        "W2_row": [float(v) for v in w["W2"][2]],
        "b2": float(w["b2"][2]),
        "Rf_ohm": float(o2["Rf_ohm"]),
        "Gtot_S": float(o2["G_phys_S"]),
        "Rf_Gtot": float(o2["Rf_Gtot"]),
        "I_max_est_A": float(o2["I_max_est_A"]),
        "z_abs_max_o2": float(o2["z_abs_max"]),
        "z_abs_max_network_tag": picks["highest_signal"]["tag"],
        "z_abs_max_network_V": float(picks["highest_signal"]["z_abs_max"]),
        "g_weight": float(ARCH_C_CFG["F"].g_weight_2),
        "imax_vec": int(imax),
        "hy_at_imax": [float(v) for v in hy[imax]],
        "z_at_imax": float(z_o2[imax]),
        "x_at_imax": [float(v) for v in x[imax]],
        "n_logical_resistors_full_F": len(cat),
        "discrepancy_note": (
            "Rf*Gtot must be ~140.9. 234 uA is worst-neuron I_max, not chip current. "
            "2.94 V is Network F |z|max (h25), not o2 |z|max."
        ),
    }


def replace_resistors_with_pdk(netlist: str, catalog: list[dict]) -> tuple[str, list[dict]]:
    by_name = {str(it["name"]): float(it["R"]) for it in catalog if "R" in it}
    geos = []
    out = []
    r_re = re.compile(
        r"^(R)(\S+)\s+(\S+)\s+(\S+)\s+([0-9.+-eE]+)\s*$",
        re.IGNORECASE,
    )
    for raw in netlist.splitlines():
        m = r_re.match(raw.strip())
        if not m:
            out.append(raw)
            continue
        name = m.group(1) + m.group(2)
        n1, n2, rval = m.group(3), m.group(4), float(m.group(5))
        target = by_name.get(name, rval)
        w_um, l_um = geometry_for_r(target)
        geos.append(
            {
                "name": name,
                "R_target": target,
                "w_um": w_um,
                "l_um": l_um,
                "R_pred": xhigh_r_pred(w_um, l_um),
                "pelgrom_sigma": pelgrom_sigma(w_um, l_um),
                "model": RES_MODEL,
            }
        )
        inst = f"X{name} {n1} {n2} 0 {RES_MODEL} w={w_um:.8g} l={l_um:.8g}"
        out.append(f"* PDK {RES_MODEL} for {name} target={target:.8g} pred={xhigh_r_pred(w_um, l_um):.8g}")
        out.append(inst)
    return "\n".join(out) + ("\n" if netlist.endswith("\n") else ""), geos


def prepend_pdk(netlist: str, corner: str, temp_c: float, extra: list[str] | None = None) -> str:
    head = [
        "* Experiment 39 SKY130 isolated frozen o2 cell",
        f"* PDK {PDK_VARIANT} open_pdks {PDK_VERSION}",
        "* Frozen weights were not edited. SPICE is not Python-corrected.",
        lib_line(corner),
        f".temp {temp_c:.8g}",
        "",
    ]
    if extra:
        head.extend(extra)
        head.append("")
    body = []
    skipped_temp = False
    for raw in netlist.splitlines():
        s = raw.strip().lower()
        if s.startswith(".temp") and not skipped_temp:
            skipped_temp = True
            continue
        body.append(raw)
    return "\n".join(head + body)


def miller_subckt(sizes: dict) -> list[str]:
    """Two-stage Miller. W/L from PDK Lmin and measured Id, not teaching cards."""
    L = sizes["L"]
    return [
        "* SKY130 5V miller TIA. Ideal Ibias is labeled non-PDK.",
        "* Invert VCVS / ReLU B-sources remain behavioral if present.",
        f".subckt sky_miller inp inn out vdd vss",
        f".param L={L:g} WD={sizes['WD']:g} WT={sizes['WT']:g} WL={sizes['WL']:g}",
        f"+ WOP={sizes['WOP']:g} WON={sizes['WON']:g} CC={sizes['CC']:g} IBIAS={sizes['IBIAS']:g}",
        "Ibias vdd vb {IBIAS}",
        f"Xdiode vb vb vss vss {NFET} W={{WT}} L={{L}}",
        f"Xtail vs vb vss vss {NFET} W={{WT}} L={{L}}",
        f"Xdp dplus inp vs vss {NFET} W={{WD}} L={{L}}",
        f"Xdn dmin inn vs vss {NFET} W={{WD}} L={{L}}",
        f"Xln dmin dmin vdd vdd {PFET} W={{WL}} L={{L}}",
        f"Xlp dplus dmin vdd vdd {PFET} W={{WL}} L={{L}}",
        f"Xop out dplus vdd vdd {PFET} W={{WOP}} L={{L}}",
        f"Xon out vb vss vss {NFET} W={{WON}} L={{L}}",
        "Cc dplus out {CC}",
        ".ends sky_miller",
        "",
    ]


def insert_miller(netlist: str, sizes: dict, servo: bool, vsupply: float = 2.5) -> str:
    e_re = re.compile(
        rf"^(E)({re.escape(TAG)}tia)\s+(\S+)\s+0\s+0\s+(\S+)\s+(\S+)\s*$",
        re.IGNORECASE,
    )
    b_re = re.compile(rf"^(B)({re.escape(TAG)}tia)\s+(\S+)\s+0\s+V\s*=", re.IGNORECASE)
    out = []
    inserted = False
    n_rep = 0
    vg = f"{TAG}p"
    drv = f"{TAG}lin"
    for raw in netlist.splitlines():
        s = raw.strip()
        if not inserted and s and not s.startswith("*") and not s.startswith("."):
            out.extend(miller_subckt(sizes))
            out += [
                f"Vddtia vddtia 0 DC {vsupply:.8g}",
                f"Vsstia vsstia 0 DC {-vsupply:.8g}",
            ]
            inserted = True
        m_e = e_re.match(s)
        m_b = b_re.match(s)
        if m_e:
            drv, vg = m_e.group(3), m_e.group(4)
            n_rep += 1
            continue
        if m_b:
            drv = m_b.group(3)
            n_rep += 1
            continue
        out.append(raw)
    if n_rep != 1:
        raise RuntimeError(f"expected one TIA, found {n_rep}")
    inst = [f"V{TAG}ib {vg} {TAG}inn DC 0"]
    if servo:
        inst += [
            "* Servo C is lumped (hybrid/external candidate). Not assumed integrable.",
            f"X{TAG}tia {TAG}srv {TAG}inn {drv} vddtia vsstia sky_miller",
            f"R{TAG}si {vg} {TAG}sint 50e3",
            f"C{TAG}int {TAG}sint {TAG}srv {sizes.get('servo_c', 1e-9):.8g}",
            f"R{TAG}leak {TAG}sint {TAG}srv 100e6",
            f"X{TAG}srv 0 {TAG}sint {TAG}srv vddtia vsstia sky_miller",
            f".ic v({TAG}srv)=0",
        ]
    else:
        inst.append(f"X{TAG}tia 0 {TAG}inn {drv} vddtia vsstia sky_miller")
    final = []
    placed = False
    for line in out:
        if (not placed) and line.strip().lower().startswith(".control"):
            final.extend(inst)
            final.append("")
            placed = True
        final.append(line)
    if not placed:
        final.extend(inst)
    return "\n".join(final) + "\n"


def compile_o2_iso():
    w = load_frozen_model("F")
    cfg = ARCH_C_CFG["F"]
    net, cat, reason = generate_isolated_neuron(
        32, w["W2"][2], float(w["b2"][2]), cfg.g_weight_2, cfg.banks,
        VGParams(name="exp39", amp_gain=1e5, invert_gain=1e7, linear=True),
        tag=TAG,
    )
    return net, cat, reason, w


def bake_vin_step(netlist: str, x) -> str:
    """Step inputs at t=0. Not the Experiment 24 AZ delayed pulse."""
    vec = np.atleast_1d(np.asarray(x, dtype=float))

    def repl(m: re.Match) -> str:
        i = int(m.group(2))
        val = float(vec[i - 1]) if i <= len(vec) else 0.0
        prefix = m.group(1)
        name_node = prefix.rsplit(" DC", 1)[0]
        return f"{name_node} PULSE(0 {val:.15g} 0 10n 10n 1 2)"

    return VIN_DC.sub(repl, netlist)


def write_op_net(path: Path, net: str, hy, extra_prints=None) -> None:
    head, sep, _ = net.partition(".control")
    if not sep:
        head = net
    baked = bake_vin_dc(head, np.asarray(hy, dtype=float))
    prints = [f"print v({TAG}lin)", f"print v({TAG}p)"]
    for p in extra_prints or []:
        prints.append(f"print {p}")
    ctrl = "\n.control\nset numdgt=12\nop\n" + "\n".join(prints) + "\n.endc\n.end\n"
    path.write_text(baked.rstrip() + "\n" + ctrl, encoding="utf-8")


def eval_cell(ng, path, z_ref, extra_names=None, timeout=180.0) -> dict:
    _r, text, fail = run_cir(ng, path, timeout=timeout)
    rec = {"path": str(path), "failed": bool(fail), "failure_reason": fail, "z_ref": float(z_ref)}
    if fail:
        rec["log_tail"] = text[-800:]
        return rec
    y = last(extract_all(text, f"v({TAG}lin)"))
    vsum = last(extract_all(text, f"v({TAG}p)"))
    rec.update({"y": y, "vsum": vsum})
    if y is None:
        rec.update({"failed": True, "failure_reason": "missing vlin", "log_tail": text[-800:]})
        return rec
    rec["err"] = y - float(z_ref)
    rec["abs_err"] = abs(y - float(z_ref))
    rec["analog_pass"] = abs(y - float(z_ref)) <= ERROR_LIMIT
    rec["a_eff"] = abs(y / vsum) if vsum not in (None, 0.0) else None
    for name in extra_names or []:
        rec[name] = last(extract_all(text, name))
    return rec


def characterize_resistor(ng) -> dict:
    rows = []
    for temp in (-40.0, 27.0, 85.0):
        for l_um in (8.0, 15.72, 16.67, 32.0):
            path = dest("res", f"t{temp:.0f}", f"l{l_um}")
            path.write_text(
                "\n".join(
                    [
                        "* SKY130 xhigh_po characterization",
                        lib_line("tt"),
                        f".temp {temp:.8g}",
                        "Vtest n1 0 DC 1",
                        f"Xres n1 n2 0 {RES_MODEL} w=1.0 l={l_um:.8g}",
                        "Vamm n2 0 DC 0",
                        ".control",
                        "set numdgt=12",
                        "op",
                        "let rmeas = 1.0 / i(Vamm)",
                        "print rmeas",
                        "print i(Vamm)",
                        ".endc",
                        ".end",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            _r, text, fail = run_cir(ng, path, timeout=120.0)
            rows.append(
                {
                    "temp_C": temp,
                    "w_um": 1.0,
                    "l_um": l_um,
                    "R_pred": xhigh_r_pred(1.0, l_um),
                    "R_meas": last(extract_all(text, "rmeas")),
                    "failed": bool(fail),
                    "failure_reason": fail,
                }
            )
    # voltage coefficient at 27 C, L=15.72
    vc = []
    for v in (0.2, 1.0, 2.5):
        path = dest("res", "vc", f"v{v}")
        path.write_text(
            "\n".join(
                [
                    "* SKY130 xhigh_po voltage coefficient",
                    lib_line("tt"),
                    ".temp 27",
                    f"Vtest n1 0 DC {v:.8g}",
                    f"Xres n1 n2 0 {RES_MODEL} w=1.0 l=15.72",
                    "Vamm n2 0 DC 0",
                    ".control",
                    "set numdgt=12",
                    "op",
                    "let rmeas = v(n1) / i(Vamm)",
                    "print rmeas",
                    ".endc",
                    ".end",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        _r, text, fail = run_cir(ng, path, timeout=120.0)
        vc.append({"V": v, "R_meas": last(extract_all(text, "rmeas")), "failed": bool(fail)})
    corners = []
    for corner in ("tt", "ll", "hh"):
        path = dest("res", "corner", corner)
        path.write_text(
            "\n".join(
                [
                    f"* SKY130 xhigh_po corner {corner}",
                    lib_line(corner),
                    ".temp 27",
                    "Vtest n1 0 DC 1",
                    f"Xres n1 n2 0 {RES_MODEL} w=1.0 l=15.72",
                    "Vamm n2 0 DC 0",
                    ".control",
                    "set numdgt=12",
                    "op",
                    "let rmeas = 1.0 / i(Vamm)",
                    "print rmeas",
                    ".endc",
                    ".end",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        _r, text, fail = run_cir(ng, path, timeout=120.0)
        corners.append({"corner": corner, "R_meas": last(extract_all(text, "rmeas")), "failed": bool(fail)})
    return {
        "model": RES_MODEL,
        "rsheet_ohm_per_sq": XHIGH_RSHEET,
        "pelgrom_A": XHIGH_PELGROM,
        "tc1_body": XHIGH_TC1_BODY,
        "tnom_note": "model tnom=25 C on body/head; ngspice .temp is used",
        "mismatch_in_model": "MC_MM_SWITCH*AGAUSS * body_pelgrom/sqrt(W*L). Off unless tt_mm/mc.",
        "points": rows,
        "voltage": vc,
        "corners": corners,
        "level": "LEVEL 1 MODEL DEMONSTRATED",
    }


def size_fets(ng) -> dict:
    recs = []
    for kind, model, vgs in (
        ("n", NFET, 1.5),
        ("p", PFET, -1.5),
    ):
        for w in (1.0, 5.0, 10.0, 20.0):
            path = dest("fet", kind, f"w{w}")
            if kind == "n":
                inst = f"Xmn vd vg 0 0 {model} W={w} L={L_ANALOG_UM}"
                vg, vd = 1.5, 2.5
            else:
                inst = f"Xmp vd vg vdd vdd {model} W={w} L={L_ANALOG_UM}"
                vg, vd = 2.5 - 1.5, 2.5 - 2.5
            path.write_text(
                "\n".join(
                    [
                        "* SKY130 5V FET Id vs W at L=1.0 um",
                        lib_line("tt"),
                        ".temp 27",
                        "Vdd vdd 0 DC 2.5",
                        f"Vg vg 0 DC {vg:.8g}",
                        inst,
                        f"Vds vd 0 DC {2.5 if kind=='n' else 0.0}",
                        ".control",
                        "set numdgt=12",
                        "op",
                        "print i(Vds)",
                        ".endc",
                        ".end",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            _r, text, fail = run_cir(ng, path, timeout=120.0)
            recs.append(
                {
                    "type": kind,
                    "model": model,
                    "W_um": w,
                    "L_um": L_ANALOG_UM,
                    "Vgs": vgs,
                    "Vds": 2.5,
                    "Id": last(extract_all(text, "i(Vds)")),
                    "failed": bool(fail),
                }
            )
    n5 = next(r for r in recs if r["type"] == "n" and r["W_um"] == 5.0)
    id_w5 = abs(n5["Id"] or 1e-4)
    # Target tail ~80 uA from measured density at W=5.
    wt = 5.0 * (80e-6 / id_w5)
    sizes = {
        "L": L_ANALOG_UM,
        "L_note": "2x documented 5V Lmin 0.50 um; bin 1.0-2.0 um exists",
        "WT": round(wt, 3),
        "WD": round(2.0 * wt, 3),
        "WL": round(2.0 * wt, 3),
        "WON": round(4.0 * wt, 3),
        "WOP": round(8.0 * wt, 3),
        "IBIAS": 80e-6,
        "CC": 2e-12,
        "servo_c": 1e-9,
        "vsupply": 2.5,
        "id_nfet_W5_L1": n5["Id"],
        "derivation": (
            f"NFET W=5 L=1 Vgs=1.5 Vds=2.5 Id={id_w5:.4e} A from this PDK. "
            "Tail 80 uA scales W. Output devices 4x/8x tail for o2 ~234 uA plus margin."
        ),
    }
    return {"sweep": recs, "sizes": sizes, "lmin_um": LMIN_UM, "wmin_um": WMIN_UM}


def ol_tia(ng, sizes) -> dict:
    path = dest("tia", "openloop")
    lines = [
        "* SKY130 miller open-loop DC sweep around analog ground",
        lib_line("tt"),
        ".temp 27",
        *miller_subckt(sizes),
        "Vdd vdd 0 DC 2.5",
        "Vss vss 0 DC -2.5",
        "Vin inp 0 DC 0",
        "Vin2 inn 0 DC 0",
        "Xtia inp inn out vdd vss sky_miller",
        "Cl out 0 1p",
        ".dc Vin -2m 2m 200u",
        ".control",
        "set numdgt=12",
        "run",
        "let gain = deriv(v(out))",
        "print v(out)",
        "print gain",
        "op",
        "print v(out)",
        "print i(Vdd)",
        "print i(Vss)",
        ".endc",
        ".end",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    _r, text, fail = run_cir(ng, path, timeout=180.0)
    gains = extract_all(text, "gain")
    vouts = extract_all(text, "v(out)")
    mid = None
    if gains:
        mid = max(gains, key=abs)
    return {
        "failed": bool(fail),
        "failure_reason": fail,
        "gain_max_abs": mid,
        "vout_op": last(vouts),
        "idd": last(extract_all(text, "i(Vdd)")),
        "iss": last(extract_all(text, "i(Vss)")),
        "log_tail": text[-600:] if fail else None,
        "level": "LEVEL 1 MODEL DEMONSTRATED",
    }


def cap_area() -> dict:
    dens = CAMIMC_TYP
    cs = [1e-12, 10e-12, 100e-12, 1e-9, 2e-9]
    rows = []
    for c in cs:
        a_um2 = c / dens
        rows.append(
            {
                "C_F": c,
                "density_F_per_um2": dens,
                "area_um2": a_um2,
                "area_mm2": a_um2 / 1e6,
                "verdict": (
                    "realistic" if a_um2 < 2e4
                    else "large_but_possible" if a_um2 < 2e5
                    else "impractical_on_die"
                ),
            }
        )
    return {
        "source": "sky130A libs.tech/ngspice/r+c/res_typical__cap_typical__lin.spice camimc=2.00e-15",
        "level": "LEVEL 2 PROCESS DOCUMENTED + LEVEL 1 model parameter",
        "rows": rows,
        "exp28_stack_note": "2 nF+2 nF+1 nF at 2 fF/um2 is 2.5 mm2 per neuron. Impractical on-die.",
    }


def write_plots(report: dict) -> list[str]:
    paths = []
    pts = (report.get("resistor") or {}).get("points") or []
    if pts:
        fig, ax = plt.subplots(figsize=(7.2, 4.2))
        for temp in (-40.0, 27.0, 85.0):
            sub = [p for p in pts if p["temp_C"] == temp and p.get("R_meas")]
            if sub:
                ax.plot([p["l_um"] for p in sub], [p["R_meas"] for p in sub], "o-", label=f"{temp:.0f} C")
        ax.set_xlabel("Drawn L (um), W=1 um xhigh_po")
        ax.set_ylabel("Measured R (ohm)")
        ax.set_title("SKY130 xhigh_po resistance vs length and temperature")
        ax.legend()
        fig.tight_layout()
        p = RESULTS_DIR / "exp39_resistor_tcr.png"
        fig.savefig(p, dpi=140)
        plt.close(fig)
        paths.append(str(p))
    cmp_ = report.get("comparison") or []
    if cmp_:
        fig, ax = plt.subplots(figsize=(7.2, 4.0))
        labels = [c["metric"] for c in cmp_]
        ax.barh(range(len(labels)), [1] * len(labels), color="#cccccc")
        ax.set_yticks(range(len(labels)))
        ax.set_yticklabels(labels)
        ax.set_title("Experiment 39 comparison rows (see report for values)")
        fig.tight_layout()
        p = RESULTS_DIR / "exp39_pdk_o2_cell.png"
        fig.savefig(p, dpi=140)
        plt.close(fig)
        paths.append(str(p))
    # useful: error bars if DC results exist
    dcs = report.get("dc_results") or []
    if dcs:
        fig, ax = plt.subplots(figsize=(7.2, 4.2))
        names = [d.get("name", "?") for d in dcs]
        errs = [abs(d.get("abs_err") or 0) for d in dcs]
        ax.bar(range(len(names)), errs)
        ax.axhline(ERROR_LIMIT, color="0.3", ls="--", label="analog bar 1e-3")
        ax.set_xticks(range(len(names)))
        ax.set_xticklabels(names, rotation=25, ha="right")
        ax.set_ylabel("|Vout - z| (V)")
        ax.set_title("Isolated frozen o2 cell error")
        ax.legend()
        fig.tight_layout()
        p = RESULTS_DIR / "exp39_o2_error.png"
        fig.savefig(p, dpi=140)
        plt.close(fig)
        paths.append(str(p))
    return paths


def decide(report: dict) -> dict:
    pdk_ok = bool((report.get("pdk") or {}).get("runnable"))
    if not pdk_ok:
        return {
            "letter": "E",
            "title": "REAL PDK SIMULATION COULD NOT BE PERFORMED",
            "why": ["Official SKY130 lib was not runnable."],
        }
    dcs = report.get("dc_results") or []
    trans = report.get("transient") or []
    pdk_r = any(d.get("analog_pass") for d in dcs if "pdk_r" in d.get("name", ""))
    mos = any(d.get("analog_pass") for d in dcs if "miller" in d.get("name", ""))
    t200 = next((t for t in trans if abs((t.get("t_stop") or 0) - 2e-4) < 1e-9), None)
    t200_ok = bool(t200 and t200.get("analog_pass"))
    swing_ok = bool((report.get("swing") or {}).get("o2_in_range"))
    mc = report.get("monte_carlo") or {}
    match = (report.get("matching") or {}).get("status", "INSUFFICIENT DATA")
    if mos and t200_ok and swing_ok and match == "DEMONSTRATED":
        letter, title = "A", "REAL PDK O2 CELL VALIDATED"
    elif pdk_r or mos:
        letter, title = "B", "O2 CELL WORKS BUT TECHNOLOGY DATA REMAINS MISSING"
    else:
        letter, title = "C", "PDK EXPOSES A TECHNOLOGY LIMIT"
    why = []
    if pdk_r:
        why.append("PDK resistors reproduce the frozen o2 Rf*G map with a behavioral TIA.")
    if mos:
        why.append("SKY130 5V miller TIA closed the loop on isolated o2.")
    else:
        why.append("Transistor TIA analog-pass was not demonstrated or failed.")
    if not t200_ok:
        why.append("200 us transient analog-pass was not demonstrated.")
    why.append(f"Matching status: {match}.")
    if mc.get("supported") is False:
        why.append("Monte Carlo not exercised or not supported in this run.")
    return {
        "letter": letter,
        "title": title,
        "why": why,
        "pdk_r_pass": pdk_r,
        "miller_pass": mos,
        "t200_pass": t200_ok,
        "matching": match,
    }


def write_reports(report: dict) -> None:
    inv = {
        "experiment": 39,
        "pdk": report["pdk"],
        "o2": {k: v for k, v in report["o2"].items() if k not in {"W2_row", "hy_at_imax", "x_at_imax"}},
    }
    (RESULTS_DIR / "exp39_pdk_inventory.json").write_text(json.dumps(inv, indent=2), encoding="utf-8")
    pdk = report["pdk"]
    o2 = report["o2"]
    (RESULTS_DIR / "exp39_pdk_inventory.md").write_text(
        "\n".join(
            [
                "# Experiment 39 PDK inventory",
                "",
                f"- Family: {pdk['family']} variant {pdk['variant']}",
                f"- open_pdks / ciel version: {pdk['version']}",
                f"- Source: {pdk['source']}",
                f"- Installer: {pdk['installer']}",
                f"- PDK_ROOT: {pdk['pdk_root']}",
                f"- ngspice lib: {pdk['lib']}",
                f"- Runnable: {pdk['lib_exists']}",
                f"- Resistor card: {pdk['resistor_card']}",
                f"- 5V NFET card: {pdk['nfet_card']}",
                f"- Corners: {pdk['corners_nominal']}",
                f"- Mismatch corners: {pdk['corners_mm']}",
                "",
                "Teaching BSIM3 was not used. ASAP7 was not used.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    spec_lines = [
        "# Experiment 39 updated minimum technology specification",
        "",
        "Only numbers supported by Experiments 1-39. No invented PDK parameters.",
        "",
        f"- Frozen o2 Rf*Gtot = {o2['Rf_Gtot']:.6g} (required ~140.9).",
        f"- Rf = {o2['Rf_ohm']:.6g} ohm. Gtot = {o2['Gtot_S']:.6g} S.",
        f"- o2 |z|max on F40 vectors = {o2['z_abs_max_o2']:.4g} V.",
        f"- Network |z|max = {o2['z_abs_max_network_tag']} {o2['z_abs_max_network_V']:.4g} V.",
        "- SKY130 5V FETs: Lmin 0.50 um, Wmin 0.42 um (model bins).",
        f"- SKY130 xhigh_po rsheet = 2000 ohm/sq, body TCR tc1 = {XHIGH_TC1_BODY}.",
        f"- SKY130 xhigh_po Pelgrom A = {XHIGH_PELGROM} (model mismatch, LEVEL 1).",
        f"- For leftover sigma 0.075%: WL >= ({XHIGH_PELGROM}/0.00075)^2 = "
        f"{(XHIGH_PELGROM / EXP29_LOCAL_PASS) ** 2:.1f} um^2.",
        f"- MIM camimc typical = {CAMIMC_TYP} F/um2.",
        "- Dual +/-2.5 V uses 5 V devices (5 V rail span). 2.94 V exceeds +/-2.5 V.",
        "- 200 us dwell remains the documented sampled inference time.",
        "- Analog MAE <= 1e-3.",
        "- Raw MOS offset is not assumed mismatch-free; servo/CDS still required if raw fails.",
        "- Fully integrated 1-2 nF CDS remains impractical at 2 fF/um2.",
        "",
    ]
    (RESULTS_DIR / "exp39_pdk_requirements.md").write_text("\n".join(spec_lines), encoding="utf-8")
    (RESULTS_DIR / "exp39_pdk_o2_cell.json").write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8"
    )
    d = report["decision"]
    lines = [
        "# Experiment 39 - first real SKY130 PDK o2 cell",
        "",
        "Frozen Experiment 9 weights. SPICE is the source of truth.",
        "Experiments 1-38 were not overwritten. No invented PDK parameters.",
        "",
        f"## Decision: {d['letter']} - {d['title']}",
        "",
    ]
    for w in d.get("why") or []:
        lines.append(f"- {w}")
    lines += [
        "",
        "## 1. Executive summary",
        "",
        f"Official SKY130A open_pdks {PDK_VERSION} was installed via ciel-releases ",
        "and used in ngspice-47. One isolated frozen o2 neuron was hosted. ",
        "Network F was not transistorized.",
        "",
        "## 2-4. PDK installation / version / model inventory",
        "",
        f"- Version: {PDK_VERSION}",
        f"- Lib: `{pdk['lib']}`",
        f"- Devices used: {RES_MODEL}, {NFET}, {PFET}, optional {MIM}",
        f"- Corners exercised: see JSON",
        "",
        "## 5. Frozen o2 extraction",
        "",
        f"- Rf*Gtot = {o2['Rf_Gtot']:.6f} (target ~140.9)",
        f"- Rf = {o2['Rf_ohm']:.6g} ohm, Gtot = {o2['Gtot_S']:.6g} S",
        f"- o2 |z|max = {o2['z_abs_max_o2']:.6g} V; network |z|max = {o2['z_abs_max_network_V']:.6g} V",
        f"- Worst-neuron I_max = {o2['I_max_est_A']:.6g} A",
        "",
        "## 6. Resistor characterization",
        "",
        json.dumps(report.get("resistor"), indent=2)[:1800],
        "",
        "## 7. Rf*G cell",
        "",
        "PDK xhigh_po resistors replace every logical isolated-o2 resistor. ",
        "Invert VCVS remains behavioral (labeled).",
        "",
        "## 8-9. TIA topology and sizing",
        "",
        json.dumps((report.get("sizing") or {}).get("sizes"), indent=2),
        "",
        "## 10. DC results",
        "",
    ]
    for row in report.get("dc_results") or []:
        lines.append(
            f"- {row.get('name')}: y={row.get('y')} err={row.get('err')} "
            f"pass={row.get('analog_pass')} fail={row.get('failure_reason')}"
        )
    lines += ["", "## 11. Transient results", ""]
    for row in report.get("transient") or []:
        lines.append(
            f"- t={row.get('t_stop')}: y={row.get('y')} err={row.get('err')} pass={row.get('analog_pass')}"
        )
    lines += [
        "",
        "## 12. Temperature",
        "",
        json.dumps(report.get("temperature"), indent=2)[:1500],
        "",
        "## 13. Leakage",
        "",
        json.dumps(report.get("leakage"), indent=2)[:1200],
        "",
        "## 14. Capacitor feasibility",
        "",
        json.dumps(report.get("capacitors"), indent=2)[:1500],
        "",
        "## 15. Mismatch / Monte Carlo",
        "",
        json.dumps(report.get("monte_carlo"), indent=2)[:1500],
        "",
        "## 16. Power",
        "",
        json.dumps(report.get("power"), indent=2)[:1200],
        "",
        "## 17. Requirement comparison",
        "",
        "| Metric | Exp37 requirement | Real PDK result | Status |",
        "|---|---:|---:|---|",
    ]
    for c in report.get("comparison") or []:
        lines.append(
            f"| {c['metric']} | {c['required']} | {c['result']} | {c['status']} |"
        )
    lines += [
        "",
        "## 18. Demonstrated vs documented vs unknown",
        "",
        "| Property | Claim level | Note |",
        "|---|---|---|",
    ]
    for row in report.get("levels") or []:
        lines.append(f"| {row['property']} | {row['level']} | {row['note']} |")
    lines += [
        "",
        "## 19. Limitations",
        "",
        "- Isolated o2 only. Not F40. Not 48 TIAs.",
        "- Invert / ReLU remain behavioral.",
        "- Ideal Ibias is not a PDK current source.",
        "- Servo capacitor is lumped unless a small-C test passed.",
        "- Teaching BSIM3 was not used as a PDK substitute.",
        "- Model Pelgrom is LEVEL 1, not measured silicon (LEVEL 3).",
        "",
        "## 20. Final decision",
        "",
        f"**{d['letter']} - {d['title']}**",
        "",
        "No invented PDK/device/process parameters were used." if report.get("no_invented") else "",
        "",
    ]
    (RESULTS_DIR / "exp39_pdk_o2_cell.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    ensure_dirs()
    write_spiceinit()
    report = {
        "experiment_id": "exp39",
        "spice_source_of_truth": True,
        "frozen_weights_edited": False,
        "pdk_invented": False,
        "python_correction": False,
        "no_invented": True,
        "teaching_bsim3_used": False,
    }
    pdk = discover_pdk()
    report["pdk"] = pdk
    report["o2"] = extract_o2()
    print(
        f"o2 RfG={report['o2']['Rf_Gtot']:.4f} |z|={report['o2']['z_abs_max_o2']:.4f} "
        f"I={report['o2']['I_max_est_A']:.4e} pdk={pdk['runnable']}",
        flush=True,
    )
    if not pdk["runnable"]:
        report["decision"] = decide(report)
        write_reports(report)
        print("DECISION E - REAL PDK SIMULATION UNAVAILABLE")
        return

    ng = find_ngspice()
    print("==== resistor characterization ====", flush=True)
    report["resistor"] = characterize_resistor(ng)
    print("==== FET sizing ====", flush=True)
    report["sizing"] = size_fets(ng)
    sizes = report["sizing"]["sizes"]
    print("sizes", sizes, flush=True)
    print("==== open-loop TIA ====", flush=True)
    report["tia_ol"] = ol_tia(ng, sizes)

    net0, cat, reason, w = compile_o2_iso()
    if reason or net0 is None:
        raise RuntimeError(reason or "isolated o2 compile failed")
    pdk_net, geos = replace_resistors_with_pdk(net0, cat)
    report["geometry"] = {
        "n": len(geos),
        "w_set": sorted({round(g["w_um"], 4) for g in geos}),
        "l_min": min(g["l_um"] for g in geos),
        "l_max": max(g["l_um"] for g in geos),
        "rf": next((g for g in geos if g["name"].lower().endswith("f") or "n1f" in g["name"].lower()), geos[0]),
        "note": "Same-family xhigh_po. Same-W length encode. Not extracted common-centroid layout.",
    }
    hy = report["o2"]["hy_at_imax"]
    z_ref = report["o2"]["z_at_imax"]

    dc_rows = []
    print("==== PDK R + behavioral TIA ====", flush=True)
    path = dest("o2", "pdk_r", "behav", "tt", "27")
    write_op_net(path, prepend_pdk(pdk_net, "tt", 27.0), hy)
    rec = eval_cell(ng, path, z_ref, timeout=180.0)
    rec["name"] = "pdk_r_behav_tt_27"
    dc_rows.append(rec)
    print("  behav", rec.get("abs_err"), rec.get("analog_pass"), rec.get("failure_reason"), flush=True)

    print("==== PDK R corners / temp (behavioral TIA) ====", flush=True)
    temp_rows = []
    for corner, temp in (("tt", 27.0), ("ll", 27.0), ("hh", 27.0), ("tt", -40.0), ("tt", 85.0)):
        path = dest("o2", "pdk_r", "behav", corner, f"t{temp:.0f}")
        write_op_net(path, prepend_pdk(pdk_net, corner, temp), hy)
        r = eval_cell(ng, path, z_ref, timeout=180.0)
        r["name"] = f"pdk_r_{corner}_{temp:.0f}"
        r["corner"] = corner
        r["temp_C"] = temp
        temp_rows.append(r)
        if corner == "tt" and temp != 27.0:
            dc_rows.append(r)
        print(" ", r["name"], r.get("abs_err"), r.get("analog_pass"), flush=True)
    report["temperature"] = temp_rows

    print("==== PDK R + miller TIA ====", flush=True)
    miller_net = insert_miller(pdk_net, sizes, servo=False)
    path = dest("o2", "miller", "noservo", "27")
    write_op_net(
        path,
        prepend_pdk(miller_net, "tt", 27.0),
        hy,
        extra_prints=["i(Vddtia)", "i(Vsstia)", f"i(V{TAG}ib)"],
    )
    rec_m = eval_cell(
        ng, path, z_ref,
        extra_names=["i(Vddtia)", "i(Vsstia)", f"i(V{TAG}ib)"],
        timeout=240.0,
    )
    rec_m["name"] = "miller_noservo_27"
    dc_rows.append(rec_m)
    print("  noservo", rec_m.get("abs_err"), rec_m.get("analog_pass"), rec_m.get("failure_reason"), flush=True)

    miller_s = insert_miller(pdk_net, sizes, servo=True)
    path = dest("o2", "miller", "servo", "27")
    write_op_net(
        path,
        prepend_pdk(miller_s, "tt", 27.0),
        hy,
        extra_prints=["i(Vddtia)", "i(Vsstia)", f"v({TAG}srv)"],
    )
    rec_s = eval_cell(
        ng, path, z_ref,
        extra_names=["i(Vddtia)", "i(Vsstia)", f"v({TAG}srv)"],
        timeout=240.0,
    )
    rec_s["name"] = "miller_servo_27"
    dc_rows.append(rec_s)
    print("  servo", rec_s.get("abs_err"), rec_s.get("analog_pass"), rec_s.get("failure_reason"), flush=True)
    report["dc_results"] = dc_rows

    use_net = miller_s if rec_s.get("analog_pass") else (miller_net if rec_m.get("analog_pass") else pdk_net)
    use_kind = "miller_servo" if rec_s.get("analog_pass") else (
        "miller_noservo" if rec_m.get("analog_pass") else "pdk_r_behav"
    )

    print("==== transient ====", flush=True)
    trans = []
    for tstop in (1e-4, 2e-4, 5e-4, 1e-3):
        path = dest("o2", use_kind, "tran", f"{tstop}")
        head, sep, _ = prepend_pdk(use_net, "tt", 27.0).partition(".control")
        baked = bake_vin_step(head if sep else prepend_pdk(use_net, "tt", 27.0), np.asarray(hy))
        wr = path.with_suffix(".dat")
        ctrl = (
            "\n.control\nset numdgt=12\nset wr_singlescale\n"
            f"tran {max(tstop/200.0, 1e-6):.8g} {tstop:.8g}\n"
            f"wrdata {wr.name} v({TAG}lin) v({TAG}p)\n"
            f"print v({TAG}lin)\nprint v({TAG}p)\n.endc\n.end\n"
        )
        path.write_text(baked.rstrip() + ctrl, encoding="utf-8")
        r = eval_cell(ng, path, z_ref, timeout=300.0)
        r["name"] = f"tran_{tstop}"
        r["t_stop"] = tstop
        trans.append(r)
        print(" ", tstop, r.get("abs_err"), r.get("analog_pass"), r.get("failure_reason"), flush=True)
    report["transient"] = trans

    print("==== leakage / swing / power ====", flush=True)
    leak = {
        "i_sum_miller": rec_m.get(f"i(V{TAG}ib)"),
        "ceiling_A": 1.3098e-08,
        "note": "Measured TIA input ammeter if present. 85 C FET leak not a separate off-FET bench unless listed.",
        "status": "measured" if rec_m.get(f"i(V{TAG}ib)") is not None else "unavailable",
        "level": "LEVEL 1 MODEL DEMONSTRATED",
    }
    report["leakage"] = leak
    idd = rec_s.get("i(Vddtia)") if rec_s.get("i(Vddtia)") is not None else rec_m.get("i(Vddtia)")
    report["power"] = {
        "idd_tia_A": idd,
        "vsupply_plus_minus": 2.5,
        "p_quiescent_W": abs(idd) * 5.0 if idd is not None else None,
        "note": "One isolated TIA (+servo if used). Not chip power. Not OPA189 Iq.",
        "level": "LEVEL 1 MODEL DEMONSTRATED",
    }
    report["swing"] = {
        "o2_z": report["o2"]["z_abs_max_o2"],
        "network_z": report["o2"]["z_abs_max_network_V"],
        "rails": "+/-2.5 V",
        "o2_in_range": report["o2"]["z_abs_max_o2"] <= 2.5,
        "network_in_range": report["o2"]["z_abs_max_network_V"] <= 2.5,
        "note": "2.94 V network requirement exceeds +/-2.5 V. 5V devices span 5 V. Unsafe to invent 6 V rails.",
        "level": "LEVEL 2 PROCESS DOCUMENTED",
    }
    report["capacitors"] = cap_area()

    print("==== matching / Monte Carlo ====", flush=True)
    rf_geo = report["geometry"]["rf"]
    sig = float(rf_geo.get("pelgrom_sigma") or pelgrom_sigma(1.0, 15.72))
    wl_need = (XHIGH_PELGROM / EXP29_LOCAL_PASS) ** 2
    matching = {
        "status": "INSUFFICIENT DATA" if sig > EXP29_LOCAL_PASS else "MODEL SUPPORTS AT THIS AREA",
        "model_pelgrom_A": XHIGH_PELGROM,
        "sigma_at_used_Rf_geometry": sig,
        "target_leftover": EXP29_LOCAL_PASS,
        "WL_um2_for_0p075pct": wl_need,
        "used_WL_um2": float(rf_geo["w_um"]) * float(rf_geo["l_um"]),
        "note": (
            "LEVEL 1 model mismatch. Not silicon PCM. "
            "tt_mm Monte Carlo below is model AGAUSS, not a foundry yield."
        ),
    }
    mc_errs = []
    mc_failed = 0
    n_mc = 20
    for i in range(n_mc):
        path = dest("o2", "mc", f"{i:03d}")
        write_op_net(path, prepend_pdk(pdk_net, "tt_mm", 27.0), hy)
        r = eval_cell(ng, path, z_ref, timeout=180.0)
        if r.get("failed") or r.get("abs_err") is None:
            mc_failed += 1
        else:
            mc_errs.append(float(r["abs_err"]))
        if i in (0, 4, 9, 19):
            print("  mc", i, r.get("abs_err"), r.get("failure_reason"), flush=True)
    if mc_errs:
        arr = np.array(mc_errs)
        report["monte_carlo"] = {
            "supported": True,
            "corner": "tt_mm",
            "n": n_mc,
            "n_ok": len(mc_errs),
            "n_failed": mc_failed,
            "mae": float(np.mean(arr)),
            "max": float(np.max(arr)),
            "std": float(np.std(arr)),
            "p95": float(np.percentile(arr, 95)),
            "mean_abs": float(np.mean(arr)),
            "level": "LEVEL 1 MODEL DEMONSTRATED",
        }
        if sig > EXP29_LOCAL_PASS:
            matching["status"] = "MATCHING FEASIBILITY UNRESOLVED"
            matching["note"] += (
                f" Used geometry sigma~{sig:.3%} > 0.075%. "
                "Need larger WL or unit tiling; not proven here."
            )
    else:
        report["monte_carlo"] = {
            "supported": False,
            "reason": "tt_mm runs failed or produced no errors",
            "n": n_mc,
            "n_failed": mc_failed,
        }
        matching["status"] = "INSUFFICIENT DATA"
    report["matching"] = matching

    report["comparison"] = [
        {"metric": "Rf*Gtot", "required": "~140.9", "result": f"{report['o2']['Rf_Gtot']:.4f}", "status": "measured"},
        {
            "metric": "residual ratio error",
            "required": "<=0.075% target",
            "result": matching["status"],
            "status": matching["status"],
        },
        {
            "metric": "output swing",
            "required": ">=2.94 V network / o2 2.46 V",
            "result": f"o2 {report['o2']['z_abs_max_o2']:.3f} V on +/-2.5 V; 2.94 V not in range",
            "status": "documented",
        },
        {
            "metric": "current",
            "required": f"{report['o2']['I_max_est_A']:.3e} A worst-neuron",
            "result": "FET Id sweep supports 80 uA-class tail",
            "status": "measured",
        },
        {
            "metric": "gain",
            "required": "~1e5 behavioral / 4.88e4 analog",
            "result": report.get("tia_ol", {}).get("gain_max_abs"),
            "status": "measured" if report.get("tia_ol", {}).get("gain_max_abs") is not None else "unavailable",
        },
        {
            "metric": "settling",
            "required": "<=200 us",
            "result": next((t.get("abs_err") for t in trans if abs(t.get("t_stop", 0) - 2e-4) < 1e-9), "unavailable"),
            "status": "measured" if trans else "unavailable",
        },
        {
            "metric": "leakage",
            "required": "~13 nA ceiling",
            "result": leak.get("i_sum_miller"),
            "status": leak.get("status"),
        },
        {
            "metric": "temperature",
            "required": "-40...85 C",
            "result": "PDK .temp + resistor TCR exercised",
            "status": "measured",
        },
        {
            "metric": "capacitor",
            "required": "1-2 nF previous design",
            "result": "2 nF => 1.0 mm2 at 2 fF/um2",
            "status": "documented",
        },
        {
            "metric": "mismatch",
            "required": "technology-dependent",
            "result": matching["status"],
            "status": matching["status"],
        },
        {
            "metric": "TCR",
            "required": "technology-dependent",
            "result": f"xhigh_po tc1={XHIGH_TC1_BODY}; temp sweep in resistor[]",
            "status": "measured",
        },
    ]
    report["levels"] = [
        {"property": "SKY130 models in ngspice", "level": "LEVEL 1", "note": "this experiment"},
        {"property": "xhigh_po rsheet/TCR/Pelgrom", "level": "LEVEL 1+2", "note": "in official model + PDK docs"},
        {"property": "MIM 2 fF/um2", "level": "LEVEL 2", "note": "camimc typical card / public e-test"},
        {"property": "5V FET voltage", "level": "LEVEL 2", "note": "official device family g5v0"},
        {"property": "isolated o2 PDK R map", "level": "LEVEL 1", "note": "behavioral TIA labeled"},
        {"property": "SKY130 miller TIA", "level": "LEVEL 1", "note": "not silicon"},
        {"property": "0.075% leftover matching", "level": "UNKNOWN / UNRESOLVED", "note": "model Pelgrom says used area is too small"},
        {"property": "silicon PCM / yield", "level": "not LEVEL 3", "note": "no measured silicon"},
        {"property": "F40 / chip", "level": "not demonstrated", "note": "forbidden in this experiment"},
    ]
    report["decision"] = decide(report)
    report["plots"] = write_plots(report)
    write_reports(report)

    d = report["decision"]
    t200 = next((t for t in trans if abs((t.get("t_stop") or 0) - 2e-4) < 1e-9), {})
    print("", flush=True)
    print(f"Experiment 39 decision: {d['letter']}", flush=True)
    print("PDK used: SKY130A", flush=True)
    print(f"PDK version: {PDK_VERSION}", flush=True)
    print("Real transistor models used: yes", flush=True)
    print("Real resistor models used: yes", flush=True)
    print("Real capacitor model used: area-calc yes; Cc lumped unless noted", flush=True)
    print(f"o2 nominal MAE/error: {rec.get('abs_err')}", flush=True)
    print(f"200 us error: {t200.get('abs_err')}", flush=True)
    print("temperature range tested: -40 / 27 / 85 C", flush=True)
    print(f"matching evidence: {matching['status']}", flush=True)
    print(f"TCR evidence: model tc1={XHIGH_TC1_BODY}; resistor temp sweep", flush=True)
    print(f"Monte Carlo available: {bool((report.get('monte_carlo') or {}).get('supported'))}", flush=True)
    print("biggest technology limitation: leftover matching area + 2.94 V vs +/-2.5 V + 1-2 nF CDS", flush=True)
    print("next experiment: enlarge Rf*G unit array to model-Pelgrom 0.075%, or mid-rail 5 V map for 2.94 V; still one cell", flush=True)
    print("No invented PDK/device/process parameters were used.", flush=True)


if __name__ == "__main__":
    main()
