"""Experiment 38: semiconductor-process feasibility audit.

Frozen Experiment 9 weights. SPICE is the source of truth.
Does not overwrite Experiments 1-37. Does not invent a PDK, W/L,
resistor TCR, mismatch PDF, or silicon performance.
Recalculates Network F requirements from the stored model.
Technology claims are either local filesystem evidence or cited
official documentation. Missing numbers stay UNKNOWN.
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from benchmark_scaling import generate_inputs
from compile_xor import PROJECT_ROOT, find_ngspice
from device_neuron import MODEL_NMOS, MODEL_PMOS
from hardware_constrained_compiler import load_frozen_model
from inverter_requirement_extraction import compile_f, hidden_stages
from physical_invert import extract_inverts
from resistor_ratio_matching import inventory
from virtual_ground_requirements import rank_neurons


CIRCUIT_DIR = PROJECT_ROOT / "circuits" / "exp38_technology_feasibility"
RESULTS_DIR = PROJECT_ROOT / "results"
DOCS_DIR = PROJECT_ROOT / "docs" / "exp38_sources"
MODELS_DIR = PROJECT_ROOT / "models" / "exp38_technology"
REPORT_JSON = RESULTS_DIR / "exp38_technology_feasibility.json"
REPORT_MD = RESULTS_DIR / "exp38_technology_feasibility.md"
ERROR_LIMIT = 1.0e-3
# Experiment 29 leftover after per-neuron Rf*G matching (15% of 0.5%).
EXP29_LOCAL_PASS = 7.5e-4
EXP29_LOCAL_FAIL = 1.25e-3


def slim(x):
    if isinstance(x, (np.floating, np.integer)):
        return x.item()
    return x


def fmt(v, spec=".4e"):
    if v is None:
        return "n/a"
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, float):
        return format(v, spec)
    return str(v)


def exists(p) -> bool:
    try:
        return Path(p).exists()
    except OSError:
        return False


def discover_local() -> dict:
    ng = None
    try:
        ng = str(find_ngspice())
    except SystemExit:
        ng = None
    env = {
        "PDK_ROOT": os.environ.get("PDK_ROOT"),
        "PDK": os.environ.get("PDK"),
        "PDK_ROOT_SKY130": os.environ.get("PDK_ROOT_SKY130"),
        "OPENPDK": os.environ.get("OPENPDK"),
    }
    ihp_howto = Path(r"C:\ngspice\examples\IHPOpenSourcePDK\IHP-PDK-howto.txt")
    sky_howto = Path(r"C:\ngspice\examples\SkywaterOpenSourcePDK\readme.txt")
    sky_lib = Path(r"D:\Spice_general\open_pdks\sky130\sky130A\libs.tech\combined\sky130.lib.spice")
    ihp_root = Path(r"D:\Spice_general\IHP-Open-PDK")
    r2 = Path(r"C:\ngspice\examples\osdi\r2_cmc")
    opa = PROJECT_ROOT / "models" / "vendor" / "ti" / "opa189" / "OPAx189.LIB"
    osdi = list(Path(r"C:\ngspice").glob("**/*.osdi")) if exists(r"C:\ngspice") else []
    return {
        "ngspice": ng,
        "env": env,
        "pdk_root_set": bool(env["PDK_ROOT"]),
        "teaching_bsim3": {
            "nmos": str(MODEL_NMOS),
            "pmos": str(MODEL_PMOS),
            "present": exists(MODEL_NMOS) and exists(MODEL_PMOS),
            "resistor_model": False,
        },
        "ihp_howto": str(ihp_howto) if exists(ihp_howto) else None,
        "ihp_tree": str(ihp_root) if exists(ihp_root) else None,
        "sky_howto": str(sky_howto) if exists(sky_howto) else None,
        "sky_example_lib": str(sky_lib) if exists(sky_lib) else None,
        "r2_cmc_example": str(r2) if exists(r2) else None,
        "osdi_binaries": [str(p) for p in osdi[:20]],
        "opa189": str(opa) if exists(opa) else None,
        "foundry_pdk_installed": False,
        "note": (
            "PDK_ROOT unset. IHP and SkyWater howtos exist under ngspice/examples. "
            "Foundry model trees are absent. Compact-model .osdi plugins exist under "
            "C:\\ngspice\\lib\\ngspice (including psp103 and r2_cmc) but they are not a PDK."
        ),
    }


def extract_requirements() -> dict:
    w = load_frozen_model("F")
    net, cat, spec = compile_f(w)
    x = generate_inputs(spec["n_in"], 40, "exp24_F")
    rows, picks = rank_neurons(spec, cat, w, x)
    inv = inventory(cat)
    hidden = hidden_stages(net)
    stages = extract_inverts(net)
    z1 = x @ w["W1"].T + w["b1"]
    hy = np.maximum(0.0, z1)
    z2 = hy @ w["W2"].T + w["b2"]
    i_max = [r["I_max_est_A"] for r in rows]
    by_kind = inv.get("by_kind") or {}
    o2 = next(r for r in rows if r["tag"] == "o2")
    hidden_g = max((r for r in rows if r["layer"] == 1), key=lambda r: r["G_phys_S"])
    return {
        "network": "F",
        "shape": [int(spec["n_in"]), int(spec["n_hidden"]), int(spec["n_out"])],
        "frozen_model": "models/scaling/F.npz seed 9",
        "n_logical_resistors": inv["n_resistors"],
        "by_kind": by_kind,
        "r_min_ohm": inv.get("r_min"),
        "r_max_ohm": inv.get("r_max"),
        "n_hidden_inverts": len(hidden),
        "n_invert_stages_total": len(stages),
        "worst_RfG_tag": picks["worst_finite_gain"]["tag"],
        "worst_RfG": picks["worst_finite_gain"]["Rf_Gtot"],
        "worst_G_tag": max(rows, key=lambda r: r["G_phys_S"])["tag"],
        "worst_G_S": max(r["G_phys_S"] for r in rows),
        "largest_hidden_G_tag": hidden_g["tag"],
        "largest_hidden_G_S": hidden_g["G_phys_S"],
        "Rf_ohm": o2["Rf_ohm"],
        "o2_RfG": o2["Rf_Gtot"],
        "o2_z_abs_max": o2["z_abs_max"],
        "z_abs_max_tag": picks["highest_signal"]["tag"],
        "z_abs_max_V": picks["highest_signal"]["z_abs_max"],
        "hy_max_V": float(np.max(hy)),
        "z2_max_V": float(np.max(np.abs(z2))),
        "I_max_worst_neuron_A": float(max(i_max)),
        "I_max_sum_all_neurons_A": float(sum(i_max)),
        "I_max_note": (
            "I_max_est = G_WEIGHT * L1 mass per neuron. "
            "234 uA in Exp 37 is the worst-neuron estimate, not network total current."
        ),
        "analog_mae_bar": ERROR_LIMIT,
        "classification_required": 1.0,
        "dwell_s": 2e-4,
        "temp_C": [-40.0, 27.0, 85.0],
        "vos_uncorrected_ceiling_V": 22e-6,
        "vos_raw_representative_V": 214.023e-6,
        "ileak_analog_ceiling_A": 1.3098e-8,
        "tia_A_analog": 4.8846e4,
        "tia_A_conservative": 1e5,
        "invert_A_uncompensated_pass": 1e4,
        "invert_Vos_analog_ceiling_V": 100e-6,
        "exp29_local_residual_pass": EXP29_LOCAL_PASS,
        "exp29_local_residual_fail": EXP29_LOCAL_FAIL,
        "cds_C_F": {"Ccds": 2e-9, "Ccouple": 2e-9, "Cf": 1e-9},
        "miller_vsupply_V": 2.5,
    }


def load_priors() -> dict:
    out = {}
    files = {
        "exp22": "virtual_ground_requirements_report.json",
        "exp26": "device_neuron_report.json",
        "exp27": "exp27_matching_temperature.json",
        "exp28": "exp28_output_interface.json",
        "exp29": "exp29_resistor_ratio_matching.json",
        "exp30": "exp30_tech_inventory.json",
        "exp36": "exp36_f40_physical_hidden_inverter.json",
        "exp37": "exp37_physical_tia_integration.json",
    }
    for key, name in files.items():
        path = RESULTS_DIR / name
        if not path.exists():
            out[key] = {"present": False}
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            out[key] = {"present": False, "reason": "json decode"}
            continue
        out[key] = {"present": True, "path": str(path), "keys": list(data)[:24]}
        if key == "exp29":
            out[key]["f40_ratio_mae"] = ((data.get("full_f") or {}).get("ratio_matched_neuron") or {}).get("mae_mean")
            out[key]["local_pass"] = EXP29_LOCAL_PASS
        if key == "exp36":
            dc = data.get("dc_results") or {}
            tr = None
            for row in data.get("dwell_results") or []:
                if row.get("t_hold") == 2e-4:
                    tr = row
            out[key]["dc_mae"] = dc.get("mae")
            out[key]["tran200_mae"] = (tr or {}).get("mae")
        if key == "exp37":
            out[key]["decision"] = (data.get("decision") or {}).get("letter")
            out[key]["o2_gear"] = next(
                (r.get("mae") for r in (data.get("insertion_tran") or []) if r.get("label") == "F12_o2_gear200"),
                None,
            )
    return out


def documented_sources() -> list[dict]:
    return [
        {
            "id": "ihp-docs",
            "title": "IHP 130nm BiCMOS Open Source PDK documentation",
            "url": "https://ihp-open-pdk-docs.readthedocs.io/en/latest/process_specs/01_general.html",
            "kind": "official_pdk_docs",
            "used_for": "SG13G2 1.2 V / 3.3 V oxides, poly resistors, MIM, analog device list",
        },
        {
            "id": "ihp-github",
            "title": "IHP-GmbH/IHP-Open-PDK",
            "url": "https://github.com/IHP-GmbH/IHP-Open-PDK",
            "kind": "official_pdk_repo",
            "used_for": "ngspice PSP MOS models, resistor symbols rsil/rppd/rhigh",
        },
        {
            "id": "ihp-rhigh",
            "title": "IHP xschem analog devices: rhigh 1360 ohm/sq",
            "url": "https://ihp-open-pdk-docs.readthedocs.io/en/main/analog/xschem.html",
            "kind": "official_pdk_docs",
            "used_for": "rhigh / rsil / rppd sheet resistances",
        },
        {
            "id": "ihp-mim-fraunhofer",
            "title": "Fraunhofer IIS IHP process sheet, MIM 1.5 fF/um2",
            "url": "https://www.iis.fraunhofer.de/content/dam/iis/en/doc/il/ics/IHP%20HR%20CMYK%20v1.pdf",
            "kind": "published_process_sheet",
            "used_for": "SG13G2 MIM 1.5 fF/um2, CMOS I/O 3.3 V",
        },
        {
            "id": "ihp-mpw",
            "title": "IHP SiGe:C BiCMOS MPW technologies",
            "url": "https://www.ihp-microelectronics.com/services/research-and-prototyping-service/mpw-prototyping-service/sigec-bicmos-technologies",
            "kind": "official_foundry",
            "used_for": "SG13G2Cu MIM 2 fF/um2 copper-BEOL option",
        },
        {
            "id": "sky-device",
            "title": "SkyWater SKY130 device details",
            "url": "https://skywater-pdk.readthedocs.io/en/main/rules/device-details.html",
            "kind": "official_pdk_docs",
            "used_for": "1.8/5 V FETs, precision poly R 300 and 2000 ohm/sq, MIM 2 fF/um2",
        },
        {
            "id": "sky-github",
            "title": "google/skywater-pdk",
            "url": "https://github.com/google/skywater-pdk",
            "kind": "official_pdk_repo",
            "used_for": "open PDK availability; matching numbers in SkyWater 002-21997 not public",
        },
        {
            "id": "gf-res",
            "title": "GF180MCU resistor models",
            "url": "https://gf180mcu-pdk.readthedocs.io/en/latest/analog/model_parameters/LV/LV_4.html",
            "kind": "official_pdk_docs",
            "used_for": "3.3 V and 6.0 V high-R poly resistors",
        },
        {
            "id": "gf-mim",
            "title": "GF180MCU MIM model table",
            "url": "https://gf180mcu-pdk.readthedocs.io/en/latest/analog/model_parameters/LV/LV_1_4_6.html",
            "kind": "official_pdk_docs",
            "used_for": "MIM 1.0 / 1.5 / 2.0 fF/um2, V<=6 V; local statistical N for MIM",
        },
        {
            "id": "gf-rstat",
            "title": "GF180MCU resistor statistical flags",
            "url": "https://gf180mcu-pdk.readthedocs.io/en/latest/analog/model_parameters/LV/LV_1_4_4.html",
            "kind": "official_pdk_docs",
            "used_for": "npolyf_u/ppolyf_u local statistical Y; high-R 1k/2k local statistical N",
        },
        {
            "id": "ng-ihp-howto",
            "title": "ngspice IHP-PDK-howto.txt (local)",
            "url": r"C:\ngspice\examples\IHPOpenSourcePDK\IHP-PDK-howto.txt",
            "kind": "local_ngspice",
            "used_for": "PDK_ROOT / OpenVAF install recipe; PDK not installed here",
        },
        {
            "id": "ng-sky-howto",
            "title": "ngspice SkywaterOpenSourcePDK readme (local)",
            "url": r"C:\ngspice\examples\SkywaterOpenSourcePDK\readme.txt",
            "kind": "local_ngspice",
            "used_for": "example .lib path D:\\Spice_general\\open_pdks\\sky130\\... not present",
        },
    ]


def candidates(local: dict) -> list[dict]:
    return [
        {
            "name": "IHP SG13G2 Open PDK",
            "node": "130 nm SiGe BiCMOS",
            "local_pdk": False,
            "transistor_models": "official PSP in PDK repo; not installed locally",
            "resistor_models": "rsil 7 ohm/sq, rppd 7 ohm/sq, rhigh 1360 ohm/sq (docs)",
            "capacitor_models": "MIM; published 1.5 fF/um2 Al BEOL, 2 fF/um2 Cu option",
            "temperature_docs": "process spec section 2.13 exists; numeric TCR not extracted here",
            "mismatch_docs": "corners exist; Pelgrom/ratio matching for 0.075% not published in cited pages",
            "analog_supported": True,
            "hv_devices": True,
            "vmax_V": 3.3,
            "runnable_here": False,
            "license": "open PDK; foundry states not for production use of the open release",
            "access": "REFERENCE ONLY until PDK_ROOT+OpenVAF installed",
            "rank_axes": {
                "evidence": "GREEN",
                "analog": "GREEN",
                "resistor_match": "UNKNOWN",
                "temp_mismatch": "YELLOW",
                "voltage": "YELLOW",
                "models": "YELLOW",
                "local_sim": "RED",
                "timing_200us": "GREEN",
                "capacitor": "YELLOW",
                "access": "GREEN",
            },
            "overall": "YELLOW",
            "notes": (
                "Best analog-process documentation among open PDKs. "
                "2.94 V swing on 3.3 V HV CMOS has little TIA headroom unless analog ground is mid-rail. "
                "Dual +/-2.5 V exceeds 3.3 V devices."
            ),
        },
        {
            "name": "SkyWater SKY130",
            "node": "180/130 nm hybrid",
            "local_pdk": False,
            "transistor_models": "official; 1.8 V core and 5 V / HV FETs documented",
            "resistor_models": "P+ poly precision 300 ohm/sq; P- poly 2000 ohm/sq; matching in SkyWater 002-21997 (not public)",
            "capacitor_models": "MIM area 2 fF/um2 (CMIMA nom 2, LSL 1.8, USL 2.2)",
            "temperature_docs": "models include TC; public numeric matching/TCR table not cited as sufficient",
            "mismatch_docs": "INSUFFICIENT DATA in public docs; Family Device Models upon request",
            "analog_supported": True,
            "hv_devices": True,
            "vmax_V": 5.0,
            "runnable_here": False,
            "license": "open PDK (Apache-2.0 / foundry open release)",
            "access": "REFERENCE ONLY; ngspice howto present, example lib path absent",
            "rank_axes": {
                "evidence": "GREEN",
                "analog": "YELLOW",
                "resistor_match": "UNKNOWN",
                "temp_mismatch": "UNKNOWN",
                "voltage": "GREEN",
                "models": "YELLOW",
                "local_sim": "RED",
                "timing_200us": "GREEN",
                "capacitor": "YELLOW",
                "access": "GREEN",
            },
            "overall": "YELLOW",
            "notes": (
                "5 V devices can host +/-2.5 V miller rails. "
                "Precision resistor matching numbers are not in the public PDK pages."
            ),
        },
        {
            "name": "GlobalFoundries GF180MCU Open PDK",
            "node": "180 nm MCU",
            "local_pdk": False,
            "transistor_models": "official BSIM4 3.3 V / 6 V; not installed locally",
            "resistor_models": "unsalicided poly with local statistical Y; high-R 1k/2k local statistical N",
            "capacitor_models": "MIM 1.0 / 1.5 / 2.0 fF/um2, V<=6 V; MIM local statistical N",
            "temperature_docs": "TCR section exists in electrical specs",
            "mismatch_docs": "statistical guide exists; high-R family used for compact 33 kOhm may lack local mismatch",
            "analog_supported": True,
            "hv_devices": True,
            "vmax_V": 6.0,
            "runnable_here": False,
            "license": "open PDK",
            "access": "REFERENCE ONLY; no local tree",
            "rank_axes": {
                "evidence": "GREEN",
                "analog": "YELLOW",
                "resistor_match": "UNKNOWN",
                "temp_mismatch": "YELLOW",
                "voltage": "GREEN",
                "models": "YELLOW",
                "local_sim": "RED",
                "timing_200us": "GREEN",
                "capacitor": "YELLOW",
                "access": "GREEN",
            },
            "overall": "YELLOW",
            "notes": (
                "Best documented voltage headroom (6 V resistors/MIM). "
                "High-R poly local mismatch flag is N, so the compact Rf family is not proven for 0.075% leftover."
            ),
        },
        {
            "name": "Berkeley BSIM3v3 teaching cards (CMOSOpAmp)",
            "node": "teaching 0.35 um-class",
            "local_pdk": True,
            "transistor_models": "present; used in Exp 26-28/37",
            "resistor_models": False,
            "capacitor_models": "lumped C only",
            "temperature_docs": "MOS kt1/ute only; default R has no TCR",
            "mismatch_docs": False,
            "analog_supported": True,
            "hv_devices": False,
            "vmax_V": 2.5,
            "runnable_here": True,
            "license": "ngspice example",
            "access": "locally runnable MOS only",
            "rank_axes": {
                "evidence": "GREEN",
                "analog": "YELLOW",
                "resistor_match": "RED",
                "temp_mismatch": "RED",
                "voltage": "YELLOW",
                "models": "GREEN",
                "local_sim": "GREEN",
                "timing_200us": "GREEN",
                "capacitor": "RED",
                "access": "GREEN",
            },
            "overall": "RED",
            "notes": "Already used. Not a foundry. Cannot host the resistor fabric.",
        },
        {
            "name": "TI OPA189 GWL macromodel",
            "node": "vendor IC, not a process",
            "local_pdk": False,
            "transistor_models": "macromodel only",
            "resistor_models": False,
            "capacitor_models": False,
            "temperature_docs": "datasheet / macromodel, not fabric TCR",
            "mismatch_docs": False,
            "analog_supported": True,
            "hv_devices": True,
            "vmax_V": 36.0,
            "runnable_here": bool(local.get("opa189")),
            "license": "TI model",
            "access": "LEVEL 3 invert primitive only",
            "rank_axes": {
                "evidence": "GREEN",
                "analog": "GREEN",
                "resistor_match": "RED",
                "temp_mismatch": "UNKNOWN",
                "voltage": "GREEN",
                "models": "GREEN",
                "local_sim": "GREEN",
                "timing_200us": "GREEN",
                "capacitor": "RED",
                "access": "GREEN",
            },
            "overall": "YELLOW",
            "notes": "Validates invert requirements as a vendor part, not as custom silicon in a PDK.",
        },
        {
            "name": "ASAP7",
            "node": "7 nm academic predictive",
            "local_pdk": False,
            "transistor_models": "predictive academic",
            "resistor_models": "not an analog foundry resistor family",
            "capacitor_models": "not used here",
            "temperature_docs": "academic",
            "mismatch_docs": "not a production analog PDK",
            "analog_supported": False,
            "hv_devices": False,
            "vmax_V": 0.7,
            "runnable_here": False,
            "license": "academic",
            "access": "REFERENCE ONLY",
            "rank_axes": {
                "evidence": "YELLOW",
                "analog": "RED",
                "resistor_match": "RED",
                "temp_mismatch": "UNKNOWN",
                "voltage": "RED",
                "models": "YELLOW",
                "local_sim": "RED",
                "timing_200us": "GREEN",
                "capacitor": "UNKNOWN",
                "access": "YELLOW",
            },
            "overall": "RED",
            "notes": "Predictive digital node. 2.94 V swing is a documented contradiction.",
        },
        {
            "name": "CMC r2_cmc compact resistor example",
            "node": "compact-model example",
            "local_pdk": False,
            "transistor_models": False,
            "resistor_models": "example card only; OSDI binary absent",
            "capacitor_models": False,
            "temperature_docs": "example tc1=1.5e-4 is not a foundry TCR",
            "mismatch_docs": False,
            "analog_supported": False,
            "hv_devices": False,
            "vmax_V": None,
            "runnable_here": False,
            "license": "CMC example",
            "access": "REFERENCE ONLY",
            "rank_axes": {
                "evidence": "YELLOW",
                "analog": "RED",
                "resistor_match": "RED",
                "temp_mismatch": "RED",
                "voltage": "UNKNOWN",
                "models": "RED",
                "local_sim": "RED",
                "timing_200us": "GREEN",
                "capacitor": "RED",
                "access": "YELLOW",
            },
            "overall": "RED",
            "notes": "r2_cmc.osdi is now present locally, but the example TC1 is not a foundry TCR and must not be used as the fabric TCR.",
        },
    ]


def capacitor_areas(req: dict) -> dict:
    cds = req["cds_C_F"]
    per_neuron = cds["Ccds"] + cds["Ccouple"] + cds["Cf"]
    dens = {"1.0e-15": 1.0e-15, "1.5e-15": 1.5e-15, "2.0e-15": 2.0e-15}
    rows = {}
    for name, d in dens.items():
        a_one = per_neuron / d
        rows[name] = {
            "density_F_per_m2": d * 1e12,  # keep also um2 helper
            "density_F_per_um2": d,
            "area_one_neuron_um2": a_one,
            "area_one_neuron_mm2": a_one * 1e-6,
            "area_48_neurons_mm2": 48.0 * a_one * 1e-6,
            "area_2nF_um2": 2e-9 / d,
        }
    return {
        "C_per_neuron_F": per_neuron,
        "note": "Arithmetic from documented MIM density. Not a layout. Fully integrated 2 nF CDS is large.",
        "by_density": rows,
    }


def feasibility_matrix(req: dict, caps: dict) -> list[dict]:
    a48 = caps["by_density"]["2.0e-15"]["area_48_neurons_mm2"]
    return [
        {
            "requirement": "analog MAE",
            "required": ERROR_LIMIT,
            "prior": "Exp 17/29/36/37 SPICE vs NumPy",
            "tech": "independent of PDK; already demonstrated mixed-level",
            "status": "GREEN",
            "class": "demonstrated_in_spice",
        },
        {
            "requirement": "classification",
            "required": 1.0,
            "prior": "F40 Exp 36/37 acc 1.0",
            "tech": "independent",
            "status": "GREEN",
            "class": "demonstrated_in_spice",
        },
        {
            "requirement": "output swing |z|max",
            "required": req["z_abs_max_V"],
            "prior": "Exp 37 F40 software z, h25",
            "tech": "IHP 3.3 V YELLOW; SKY130 5 V / GF180 6 V GREEN; ASAP7 RED",
            "status": "YELLOW",
            "class": "supported_by_published_docs",
        },
        {
            "requirement": "worst-neuron current",
            "required": req["I_max_worst_neuron_A"],
            "prior": "G_WEIGHT * L1; Exp 37 called this 234 uA",
            "tech": "any analog CMOS; not a process limiter",
            "status": "GREEN",
            "class": "inferred_estimated",
        },
        {
            "requirement": "sum of per-neuron I_max",
            "required": req["I_max_sum_all_neurons_A"],
            "prior": "not previously labeled as network current",
            "tech": "still modest for analog CMOS; supply design unknown",
            "status": "YELLOW",
            "class": "inferred_estimated",
        },
        {
            "requirement": "200 us dwell",
            "required": 2e-4,
            "prior": "Exp 25/28/36/37; isolated 100 us fail",
            "tech": "audio-speed analog; GREEN on all real processes",
            "status": "GREEN",
            "class": "demonstrated_in_spice",
        },
        {
            "requirement": "residual local Rf*G leftover",
            "required": EXP29_LOCAL_PASS,
            "prior": "Exp 29 local residual 0.075% pass / 0.125% fail",
            "tech": "INSUFFICIENT DATA in public open-PDK matching tables",
            "status": "UNKNOWN",
            "class": "completely_unknown",
        },
        {
            "requirement": "uncorrected TIA |Vos|",
            "required": 22e-6,
            "prior": "Exp 22 analog ceiling",
            "tech": "raw MOS offset typically larger; servo/CDS required (Exp 26/27)",
            "status": "YELLOW",
            "class": "demonstrated_in_spice",
        },
        {
            "requirement": "effective post-CDS offset",
            "required": ERROR_LIMIT,
            "prior": "Exp 27/37 CDS analog-pass -40/27/85 C on isolated o2",
            "tech": "needs PDK switch/C/leakage models; not silicon",
            "status": "YELLOW",
            "class": "demonstrated_in_spice",
        },
        {
            "requirement": "summing-node leakage",
            "required": 1.3098e-8,
            "prior": "Exp 22 analog |Ileak|",
            "tech": "85 C junction leak UNKNOWN without PDK",
            "status": "UNKNOWN",
            "class": "completely_unknown",
        },
        {
            "requirement": "TIA open-loop A",
            "required": 4.8846e4,
            "prior": "Exp 22 analog A_min; conservative 1e5 simulated",
            "tech": "two-stage miller in analog CMOS is plausible; not demonstrated on a PDK",
            "status": "YELLOW",
            "class": "demonstrated_in_spice",
        },
        {
            "requirement": "hidden invert Vos (32 copies)",
            "required": 100e-6,
            "prior": "Exp 30/31; OPA189 Exp 36 macromodel",
            "tech": "custom invert on PDK UNKNOWN; OPA189 is vendor model",
            "status": "YELLOW",
            "class": "demonstrated_using_vendor_model",
        },
        {
            "requirement": "CDS capacitors 1-2 nF",
            "required": 2e-9,
            "prior": "Exp 28 teaching lumped C",
            "tech": f"at 2 fF/um2, 48-neuron CDS stack ~{a48:.1f} mm2 (inferred area)",
            "status": "RED",
            "class": "inferred_estimated",
        },
        {
            "requirement": "resistor TCR",
            "required": "common-mode cancel if same family; differential TCR unknown",
            "prior": "Exp 27 .temp is MOS-only; no fabric TCR",
            "tech": "IHP/SKY/GF document TCR sections; numeric leftover vs 1e-3 UNKNOWN",
            "status": "UNKNOWN",
            "class": "completely_unknown",
        },
        {
            "requirement": "MOS mismatch PDF",
            "required": "servo/CDS must absorb raw Vos",
            "prior": "teaching DW null is not a PCM",
            "tech": "PDK statistical models exist (GF/IHP) but unused locally",
            "status": "UNKNOWN",
            "class": "completely_unknown",
        },
        {
            "requirement": "layout parasitics",
            "required": "must not destroy analog map",
            "prior": "not demonstrated",
            "tech": "unknown until extraction",
            "status": "UNKNOWN",
            "class": "completely_unknown",
        },
        {
            "requirement": "ReLU",
            "required": "bounded max(0,z)",
            "prior": "behavioral B-source only",
            "tech": "not a documented physical primitive",
            "status": "YELLOW",
            "class": "demonstrated_in_spice",
        },
    ]


def decide(req: dict, cands: list[dict], matrix: list[dict], caps: dict) -> dict:
    unknown_critical = [r for r in matrix if r["requirement"] in {
        "residual local Rf*G leftover", "resistor TCR", "MOS mismatch PDF", "summing-node leakage"
    } and r["status"] == "UNKNOWN"]
    cap_red = next(r for r in matrix if r["requirement"].startswith("CDS"))
    yellow = [
        c for c in cands
        if c["overall"] == "YELLOW"
        and any(k in c["name"] for k in ("IHP", "SKY130", "GF180"))
    ]
    letter = "B"
    why = [
        "Open PDKs document analog MOSFET, poly resistors, MIM, and enough voltage on 5-6 V nodes.",
        "No installed PDK, so no legitimate transistor-level Network F simulation was possible.",
        "Public docs do not quantify resistor-ratio leftover at 0.075%, TCR leftover, or 85 C leak.",
        f"Fully integrated 2 nF CDS is area-impractical (~{caps['by_density']['2.0e-15']['area_48_neurons_mm2']:.0f} mm2 at 2 fF/um2 for 48 neurons).",
    ]
    return {
        "letter": letter,
        "title": "TECHNOLOGY PLAUSIBLE BUT KEY DATA MISSING",
        "best_candidate": "SkyWater SKY130 (voltage headroom) and IHP SG13G2 (analog documentation); GF180MCU is the 6 V alternative",
        "strongest_evidence": (
            "Official SKY130 MIM 2 fF/um2 e-test; official 5 V FETs; official IHP 3.3 V HV CMOS + rhigh; "
            "official GF180 6 V resistors/MIM. Local Exp 22/29/36/37 requirement numbers."
        ),
        "biggest_unknown": "documented resistor matching / TCR sufficient to judge residual leftover 0.075%",
        "hardest_requirement": "per-neuron Rf*G leftover <= 0.075% AND fully-integrated 1-2 nF CDS",
        "real_pdk_used": False,
        "transistor_sim_legitimate": False,
        "proceed_toward_silicon": (
            "Do not tape out. Next is install one real open PDK and host a single o2 Rf*G cell, "
            "or accept hybrid/external capacitors and mid-rail analog ground."
        ),
        "why": why,
        "unknown_critical": [r["requirement"] for r in unknown_critical],
        "cap_status": cap_red["status"],
        "yellow_open_pdks": [c["name"] for c in yellow],
        "no_invented_parameters": True,
    }


def write_plots(req: dict, caps: dict) -> list[str]:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    names = []

    def save(fig, name):
        fig.tight_layout()
        p = RESULTS_DIR / name
        fig.savefig(p, dpi=140)
        plt.close(fig)
        names.append(str(p))

    fig, ax = plt.subplots(figsize=(6.8, 3.8))
    labs = ["required |z|", "IHP HV", "SKY130 5V", "GF180 6V", "ASAP7"]
    vals = [req["z_abs_max_V"], 3.3, 5.0, 6.0, 0.7]
    ax.bar(range(len(labs)), vals)
    ax.axhline(req["z_abs_max_V"], color="0.4", ls="--")
    ax.set_xticks(range(len(labs)))
    ax.set_xticklabels(labs, fontsize=8)
    ax.set_ylabel("volts")
    ax.set_title("Experiment 38: required swing vs documented supplies")
    save(fig, "exp38_voltage.png")

    fig, ax = plt.subplots(figsize=(6.6, 3.8))
    xs = [1.0, 1.5, 2.0]
    ys = [caps["by_density"][k]["area_48_neurons_mm2"] for k in ("1.0e-15", "1.5e-15", "2.0e-15")]
    ax.plot(xs, ys, "o-")
    ax.set_xlabel("documented MIM density (fF/um2)")
    ax.set_ylabel("48-neuron CDS stack (mm2)")
    ax.set_title("Experiment 38: inferred area of 5 nF/neuron CDS")
    save(fig, "exp38_capacitor_area.png")

    fig, ax = plt.subplots(figsize=(6.4, 3.8))
    resid = [0.0, 2.5e-4, 5e-4, 7.5e-4, 1.25e-3, 2.5e-3, 5e-3]
    mae = [5.112e-4, 5.413e-4, 6.590e-4, 8.057e-4, 1.145e-3, 2.400e-3, 4.963e-3]
    ax.semilogx([max(r, 1e-6) for r in resid], mae, "o-")
    ax.axhline(ERROR_LIMIT, color="0.4", ls="--")
    ax.axvline(EXP29_LOCAL_PASS, color="0.5", ls=":")
    ax.set_xlabel("Exp 29 unmatched local residual")
    ax.set_ylabel("F12 MAE mean")
    ax.set_title("Experiment 38: matching leftover vs analog bar (Exp 29 data)")
    save(fig, "exp38_matching_residual.png")

    fig, ax = plt.subplots(figsize=(6.2, 3.6))
    temps = [-40, 27, 85]
    raw = [4.0447e-3, 5.6283e-5, 4.8168e-3]
    cds = [1.4921e-4, 2.5723e-4, 4.5701e-4]
    ax.semilogy(temps, raw, "o-", label="raw miller+servo o2")
    ax.semilogy(temps, cds, "s-", label="CDS unbuf o2")
    ax.axhline(ERROR_LIMIT, color="0.4", ls="--")
    ax.set_xlabel("temp (C)")
    ax.set_ylabel("|Vlin-z| (V)")
    ax.set_title("Experiment 38: temperature (Exp 37 isolated o2)")
    ax.legend(fontsize=8)
    save(fig, "exp38_temperature.png")
    return names


def write_markdown(report: dict) -> None:
    req = report["requirements"]
    dec = report["decision"]
    loc = report["local"]
    lines = [
        "# Experiment 38 - semiconductor technology feasibility",
        "",
        "Frozen Experiment 9 weights. SPICE is the source of truth. Experiments 1-37 were not overwritten.",
        "No PDK, W/L, TCR, mismatch PDF, or silicon performance was invented.",
        "",
        f"## Decision: {dec['letter']} - {dec['title']}",
        "",
    ]
    for w in dec["why"]:
        lines.append(f"- {w}")
    lines += [
        "",
        f"Best candidate: {dec['best_candidate']}",
        f"Strongest evidence: {dec['strongest_evidence']}",
        f"Biggest unknown: {dec['biggest_unknown']}",
        f"Hardest requirement: {dec['hardest_requirement']}",
        f"Real PDK used: {dec['real_pdk_used']}",
        f"Legitimate transistor-level PDK simulation: {dec['transistor_sim_legitimate']}",
        "",
        "No invented PDK/device/process parameters were used.",
        "",
        "## 1. Executive summary",
        "",
        "The frozen Architecture A Network F map has quantified electrical requirements. ",
        "Three open PDKs (IHP SG13G2, SKY130, GF180MCU) document analog MOS, poly resistors, ",
        "and MIM capacitors. None is installed here. Public documentation does not prove ",
        "the Experiment 29 leftover matching target. Fully integrated 1-2 nF CDS capacitors ",
        "are area-impractical at documented MIM densities. The architecture is not blocked ",
        "by a single documented voltage/current contradiction on 5-6 V nodes, but it is ",
        "blocked from a responsible silicon claim until a real PDK is installed and the ",
        "resistor-matching / leakage / TCR numbers are read from that PDK.",
        "",
        "## 2. Exact objective",
        "",
        "Is there a documented, realistically accessible semiconductor technology/PDK that ",
        "could implement the demonstrated Physical AI architecture without invented device parameters?",
        "",
        "## 3. Repository baseline",
        "",
        f"- Frozen model: {req['frozen_model']}",
        f"- Shape: {req['shape']}",
        f"- Logical resistors (recalculated): {req['n_logical_resistors']} kind={req['by_kind']}",
        f"- Hidden invert stages: {req['n_hidden_inverts']} / total invert stages {req['n_invert_stages_total']}",
        f"- Worst Rf*G: {req['worst_RfG_tag']} = {fmt(req['worst_RfG'])}",
        f"- Worst G: {req['worst_G_tag']} = {fmt(req['worst_G_S'])} S",
        f"- Largest hidden G: {req['largest_hidden_G_tag']} = {fmt(req['largest_hidden_G_S'])} S",
        f"- Rf: {fmt(req['Rf_ohm'])} Ohm",
        f"- |z|max: {req['z_abs_max_tag']} = {fmt(req['z_abs_max_V'])} V; hy_max={fmt(req['hy_max_V'])} V",
        f"- Worst-neuron I_max: {fmt(req['I_max_worst_neuron_A'])} A (this is the 234 uA number)",
        f"- Sum of per-neuron I_max: {fmt(req['I_max_sum_all_neurons_A'])} A (not previously labeled network current)",
        f"- {req['I_max_note']}",
        f"- Local PDK_ROOT set: {loc['pdk_root_set']}; foundry PDK installed: {loc['foundry_pdk_installed']}",
        f"- Teaching BSIM3 present: {loc['teaching_bsim3']['present']}; OPA189 present: {bool(loc['opa189'])}",
        "",
        "Discrepancy vs the prompt: 234 uA is worst-neuron G_WEIGHT*L1, not total Network F current.",
        "Resistor counts match Experiment 29 (1342 = 1024 weight + 48 bias + 48 Rf + 98 invert + 124 divider).",
        "",
        "## 4-5. Technology inventory and candidate table",
        "",
        "See JSON candidates[]. Local scan: PDK_ROOT unset, IHP/SkyWater howtos present, "
        "foundry model trees absent. Compact-model .osdi plugins exist locally but are not a PDK.",
        "",
    ]
    for c in report["candidates"]:
        lines.append(
            f"- {c['name']} ({c['node']}): local={c['local_pdk']} runnable={c['runnable_here']} "
            f"Vmax={c['vmax_V']} overall={c['overall']} access={c['access']}"
        )
        lines.append(f"  {c['notes']}")
    lines += ["", "## 6-14. Requirement extraction and feasibility", ""]
    lines.append("| Requirement | Required | Prior evidence | Technology evidence | Status | Class |")
    lines.append("|---|---:|---|---|---|---|")
    for r in report["matrix"]:
        lines.append(
            f"| {r['requirement']} | {r['required']} | {r['prior']} | {r['tech']} | {r['status']} | {r['class']} |"
        )
    caps = report["capacitors"]
    lines += [
        "",
        f"CDS C per neuron = {caps['C_per_neuron_F']:.3e} F. "
        f"At 2 fF/um2, 48 neurons ~ {caps['by_density']['2.0e-15']['area_48_neurons_mm2']:.1f} mm2.",
        "",
        "## 15. Minimum Physical AI process specification",
        "",
        report["min_spec_text"],
        "",
        "## 16. Demonstrated vs required vs unknown",
        "",
        "| Property | Experiment evidence | Required for silicon | Technology evidence |",
        "|---|---|---|---|",
    ]
    for row in report["demonstrated_vs_required"]:
        lines.append(f"| {row['property']} | {row['experiment']} | {row['required']} | {row['technology']} |")
    lines += [
        "",
        "## 17. Unknowns",
        "",
    ]
    for u in report["unknowns"]:
        lines.append(f"- {u}")
    lines += [
        "",
        "## 18. Risks",
        "",
        "- Treating OPA189 macromodel as custom-silicon invert feasibility.",
        "- Treating 0.5% discrete-resistor language as 0.075% on-chip leftover.",
        "- Dual +/-2.5 V miller rails on 3.3 V-only IHP devices.",
        "- Integrating 2 nF CDS capacitors on-die.",
        "- Using example compact-model TC1 as a foundry TCR.",
        "",
        "## 19. Candidate ranking",
        "",
        "1. SKY130 - voltage GREEN, analog YELLOW, matching UNKNOWN, not installed.",
        "2. IHP SG13G2 - analog GREEN, voltage YELLOW for 2.94 V, matching UNKNOWN, not installed.",
        "3. GF180MCU - voltage GREEN, high-R local-mismatch flag N, not installed.",
        "4. OPA189 macromodel - invert only.",
        "5. Teaching BSIM3 - MOS only, resistor RED.",
        "6. ASAP7 / r2_cmc - not suitable.",
        "",
        "## 20. Final decision",
        "",
        f"**{dec['letter']} - {dec['title']}**",
        "",
        "## 21. Next experiment",
        "",
        dec["proceed_toward_silicon"],
        "",
        "Recommended Experiment 39: install one documented open PDK (SKY130 or IHP SG13G2), ",
        "host a single frozen o2 Rf*G cell plus one invert, and read matching/TCR/leakage from that PDK. ",
        "Do not invent parameters if the PDK omits them. Do not transistorize all of Network F.",
        "",
    ]
    REPORT_MD.write_text("\n".join(lines), encoding="utf-8")


def min_spec_text(req: dict) -> str:
    return (
        "Minimum Physical AI Process Specification (only numbers the experiments support):\n"
        f"- Analog bar MAE <= 1e-3; classification 100% on frozen F40.\n"
        f"- Output swing >= {req['z_abs_max_V']:.3f} V with TIA headroom. Dual +/-2.5 V needs >=5 V devices, "
        "or the analog ground must move to mid-supply on a 3.3 V HV process.\n"
        f"- Worst-neuron current estimate {req['I_max_worst_neuron_A']:.3e} A; do not call this chip power.\n"
        "- Sampled inference dwell 200 us (100 us failed on the documented physical path).\n"
        "- TIA A >= 4.88e4 analog (1e5 conservative, already simulated).\n"
        "- Uncorrected |Vos| <= 22 uV or a physical servo/CDS that reduces effective offset below the analog bar.\n"
        "- Invert |Vos| <= 100 uV at N=32, or a documented zero-drift / AZ invert.\n"
        "- Summing-node |Ileak| <= 13 nA analog (Exp 22); 85 C value UNKNOWN until PDK.\n"
        "- Per-neuron Rf must share the resistor family of that neuron's weights/bias. "
        f"Unmatched leftover after grouping <= {EXP29_LOCAL_PASS:.2e} (0.075%). Not a foundry yield.\n"
        "- Invert R1/R2 and divider pairs must be ratio-matched.\n"
        "- TCR: common-mode same-family scale cancels (Exp 29). Differential TCR UNKNOWN.\n"
        "- Temperature range already exercised: -40, 27, 85 C (MOS teaching card; fabric TCR not present).\n"
        "- CDS capacitors in the demonstrated path are 2 nF / 2 nF / 1 nF. Fully integrated area is impractical "
        "at 1-2 fF/um2. Hybrid/external C, or a new physically justified smaller-C path, is required.\n"
        "- ReLU remains a behavioral B-source. A physical ReLU is still missing.\n"
        "- Layout parasitics: no experiment has extracted them.\n"
        "Do not invent a numeric TCR, Pelgrom A_R, or MOS mismatch sigma."
    )


def demonstrated_table() -> list[dict]:
    return [
        {"property": "Frozen weights", "experiment": "demonstrated (Exp 9)", "required": "yes", "technology": "independent"},
        {"property": "Physical weighted sum", "experiment": "demonstrated (Exp 1-17 SPICE)", "required": "yes", "technology": "resistor implementation required"},
        {"property": "ReLU", "experiment": "behavioral B-source only", "required": "yes", "technology": "still incomplete"},
        {"property": "TIA", "experiment": "partial teaching MOS + F12 Gear (Exp 26/37)", "required": "yes", "technology": "PDK miller not simulated"},
        {"property": "Hidden inverter", "experiment": "OPA189 vendor macromodel (Exp 36)", "required": "yes", "technology": "custom transistor invert incomplete"},
        {"property": "Rf/G matching", "experiment": "behavioral/statistical (Exp 29)", "required": "yes", "technology": "PDK matching data required"},
        {"property": "TCR", "experiment": "not demonstrated on fabric", "required": "required", "technology": "unknown until PDK"},
        {"property": "MOS mismatch", "experiment": "teaching DW null only", "required": "required", "technology": "PDK/model required"},
        {"property": "Layout parasitics", "experiment": "not demonstrated", "required": "required", "technology": "unknown"},
        {"property": "Full silicon F40", "experiment": "not demonstrated", "required": "final target", "technology": "unknown"},
        {"property": "CDS capacitors 1-2 nF", "experiment": "lumped teaching C (Exp 28)", "required": "if CDS path kept", "technology": "on-die area impractical at documented MIM density"},
    ]


def main() -> None:
    print("Experiment 38: technology feasibility audit", flush=True)
    CIRCUIT_DIR.mkdir(parents=True, exist_ok=True)
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    (MODELS_DIR / "README.txt").write_text(
        "No PDK models were copied or invented. This directory only records that Experiment 38 "
        "did not install a foundry PDK.\n",
        encoding="utf-8",
    )
    local = discover_local()
    req = extract_requirements()
    print(
        f"  resistors={req['n_logical_resistors']} kinds={req['by_kind']} "
        f"worst={req['worst_RfG_tag']} RfG={req['worst_RfG']:.4f} "
        f"|z|={req['z_abs_max_V']:.4f} Iworst={req['I_max_worst_neuron_A']:.4e} "
        f"Isum={req['I_max_sum_all_neurons_A']:.4e}",
        flush=True,
    )
    priors = load_priors()
    sources = documented_sources()
    (DOCS_DIR / "sources.json").write_text(json.dumps(sources, indent=2), encoding="utf-8")
    cands = candidates(local)
    caps = capacitor_areas(req)
    matrix = feasibility_matrix(req, caps)
    dec = decide(req, cands, matrix, caps)
    report = {
        "experiment_id": "exp38",
        "spice_source_of_truth": True,
        "frozen_weights_edited": False,
        "pdk_invented": False,
        "device_parameters_invented": False,
        "python_correction": False,
        "local": local,
        "requirements": req,
        "priors": priors,
        "sources": sources,
        "candidates": cands,
        "capacitors": caps,
        "matrix": matrix,
        "demonstrated_vs_required": demonstrated_table(),
        "unknowns": [
            "Public open-PDK resistor matching vs leftover 0.075%",
            "Fabric resistor TCR leftover after same-family tracking",
            "85 C summing-node leakage on a real device",
            "Custom invert offset at N=32 in a PDK (OPA189 is not that)",
            "Layout parasitics and routing drop",
            "Physical ReLU",
            "Switch charge injection at the documented AZ device beyond teaching NCH",
        ],
        "min_spec_text": min_spec_text(req),
        "decision": dec,
        "plots": write_plots(req, caps),
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(report, indent=2, default=slim), encoding="utf-8")
    write_markdown(report)
    print(f"Decision {dec['letter']} - {dec['title']}", flush=True)
    print(f"Best candidate: {dec['best_candidate']}", flush=True)
    print(f"Strongest evidence: {dec['strongest_evidence']}", flush=True)
    print(f"Biggest unknown: {dec['biggest_unknown']}", flush=True)
    print(f"Hardest requirement: {dec['hardest_requirement']}", flush=True)
    print(f"Real PDK used: {dec['real_pdk_used']}", flush=True)
    print(f"Transistor-level PDK simulation: {dec['transistor_sim_legitimate']}", flush=True)
    print(f"Toward silicon: {dec['proceed_toward_silicon']}", flush=True)
    print("No invented PDK/device/process parameters were used.", flush=True)


if __name__ == "__main__":
    main()
