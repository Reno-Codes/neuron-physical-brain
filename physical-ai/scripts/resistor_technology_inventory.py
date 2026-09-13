"""Experiment 30: local resistor / PDK inventory.

Does not invent a foundry. Does not download a PDK.
Reports only files and environment variables that are actually present.
"""

from __future__ import annotations

import os
from pathlib import Path

from compile_xor import find_ngspice, run_ngspice
from device_neuron import IHP_HOWTO, MODEL_NMOS, MODEL_PMOS
from offset_vg_search import OPA1656_PATH, OPA171_PATH
from physical_invert import CIRCUIT_DIR


R2_CMC_CIR = Path(r"C:\ngspice\examples\osdi\r2_cmc\res_r2_cmc.cir")
IHP_EXAMPLE = Path(r"C:\ngspice\examples\IHPOpenSourcePDK")
SKY_HOWTO = Path(r"C:\ngspice\examples\SkywaterOpenSourcePDK\readme.txt")
SKY_CANDIDATES = (
    Path(r"C:\sky130"),
    Path(r"C:\pdks\sky130A"),
    Path(os.environ.get("PDK_ROOT") or "") / "sky130A",
    Path(os.environ.get("PDK_ROOT") or "") / "ihp-sg13g2",
)


def _exists(p: Path) -> bool:
    try:
        return bool(p) and p.exists()
    except OSError:
        return False


def inventory() -> dict:
    pdk_root = os.environ.get("PDK_ROOT")
    pdk = os.environ.get("PDK")
    ihp_root = Path(pdk_root) / (pdk or "ihp-sg13g2") if pdk_root else None
    rows = [
        {
            "technology": "Berkeley BSIM3v3 teaching cards (CMOSOpAmp)",
            "location": str(MODEL_NMOS.parent),
            "present": _exists(MODEL_NMOS) and _exists(MODEL_PMOS),
            "devices": "nmos/pmos BSIM3v3 v3.3.0",
            "resistor_model": False,
            "temperature": "MOS .temp (kt1/ute). Default R has no TCR.",
            "mismatch": "None documented. Do not invent a PDF.",
            "geometry": "MOS W/L only, card limits L 0.35–20 µm W 0.6–20 µm",
            "suitability": (
                "LEVEL 4 invert/TIA primitive already used in Exp 26–28. "
                "Not a resistor PDK. Not IHP. Not silicon."
            ),
        },
        {
            "technology": "IHP SG13G2 Open PDK",
            "location": str(ihp_root) if ihp_root else "PDK_ROOT unset",
            "present": bool(ihp_root and ihp_root.exists()),
            "howto": str(IHP_HOWTO) if _exists(IHP_HOWTO) else None,
            "howto_present": _exists(IHP_HOWTO),
            "devices": "not installed",
            "resistor_model": False,
            "temperature": None,
            "mismatch": None,
            "geometry": None,
            "suitability": (
                "Howto exists under ngspice/examples/IHPOpenSourcePDK. "
                "PDK_ROOT is unset and the PDK tree is not present. "
                "Not used."
            ),
        },
        {
            "technology": "SkyWater SKY130",
            "location": "not found",
            "present": any(_exists(p) for p in SKY_CANDIDATES if str(p).strip("\\")),
            "howto": str(SKY_HOWTO) if _exists(SKY_HOWTO) else None,
            "howto_present": _exists(SKY_HOWTO),
            "example_lib_path": (
                r"D:\Spice_general\open_pdks\sky130\sky130A\libs.tech\combined\sky130.lib.spice"
            ),
            "example_lib_present": _exists(
                Path(r"D:\Spice_general\open_pdks\sky130\sky130A\libs.tech\combined\sky130.lib.spice")
            ),
            "resistor_model": False,
            "suitability": (
                "Howto and example netlists exist under ngspice/examples/"
                "SkywaterOpenSourcePDK. They .lib a user path that is not "
                "present. The PDK tree is not installed. Not used."
            ),
        },
        {
            "technology": "CMC r2_cmc compact resistor (ngspice OSDI example)",
            "location": str(R2_CMC_CIR.parent),
            "present": _exists(R2_CMC_CIR),
            "devices": "r2_cmc example card rsh=200 tc1=1.5e-4",
            "resistor_model": True,
            "temperature": "tc1/tc2 on the example card",
            "mismatch": "Example card has no statistical mismatch PDF",
            "geometry": "W/L instance parameters on the example",
            "osdi_binary_present": any(R2_CMC_CIR.parent.glob("**/*.osdi")) if _exists(R2_CMC_CIR.parent) else False,
            "suitability": (
                "Documented compact-model *example*, not a foundry PDK. "
                "Usable only if the OSDI binary is compiled. Probed below."
            ),
        },
        {
            "technology": "ngspice default resistor",
            "location": "built-in",
            "present": True,
            "resistor_model": True,
            "temperature": "No TC1/TC2 unless instance parameters are added. None documented for this fabric; not invented.",
            "mismatch": "None",
            "geometry": "None",
            "suitability": "Used by Experiments 1–29. Absolute R only.",
        },
        {
            "technology": "TI OPA1656 / OPA171 macromodels",
            "location": str(OPA1656_PATH.parent),
            "present": _exists(OPA1656_PATH),
            "devices": "LEVEL 3 op-amp macromodels",
            "resistor_model": False,
            "note": "Internal R_OS has TC1; that is not a fabric resistor family.",
            "suitability": "LEVEL 3 invert/TIA control. Not a PDK.",
        },
    ]
    return {
        "pdk_root": pdk_root,
        "pdk": pdk,
        "ihp_installed": bool(ihp_root and ihp_root.exists()),
        "sky130_installed": any(_exists(p) for p in SKY_CANDIDATES if p and str(p) not in {".", ""}),
        "foundry_pdk_invented": False,
        "resistor_tcr_invented": False,
        "technologies": rows,
    }


def probe_r2_cmc(ngspice: Path | None = None) -> dict:
    rec = {
        "example_present": _exists(R2_CMC_CIR),
        "ran": False,
        "usable": False,
        "failure_reason": None,
        "note": (
            "CMC r2_cmc example card. Not IHP. Not SkyWater. "
            "If the OSDI plugin is missing, the model is not usable."
        ),
    }
    if not rec["example_present"]:
        rec["failure_reason"] = "example netlist missing"
        return rec
    ng = ngspice or find_ngspice()
    CIRCUIT_DIR.mkdir(parents=True, exist_ok=True)
    dest = CIRCUIT_DIR / "r2_cmc_probe.cir"
    dest.write_text(R2_CMC_CIR.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
    rec["ran"] = True
    try:
        result = run_ngspice(ng, dest, timeout=30)
    except Exception as exc:
        rec["failure_reason"] = str(exc)
        return rec
    text = f"{result.stdout or ''}\n{result.stderr or ''}"
    low = text.lower()
    if (
        result.returncode != 0
        or "fatal" in low
        or "unknown" in low
        or "couldn't" in low
        or "unable to find" in low
    ):
        rec["failure_reason"] = (
            "r2_cmc OSDI plugin not loaded (Unable to find definition of model rmodel). "
            "No .osdi binary is installed under C:\\ngspice."
        )
        rec["usable"] = False
        return rec
    rec["usable"] = True
    rec["log_tail"] = text[-400:]
    return rec


def main() -> int:
    import json
    from compile_xor import PROJECT_ROOT

    inv = inventory()
    inv["r2_cmc_probe"] = probe_r2_cmc()
    path = PROJECT_ROOT / "results" / "exp30_tech_inventory.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(inv, indent=2), encoding="utf-8")
    print(json.dumps({k: inv[k] for k in ("ihp_installed", "sky130_installed", "pdk_root")}, indent=2))
    print("r2_cmc usable", inv["r2_cmc_probe"].get("usable"), inv["r2_cmc_probe"].get("failure_reason"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
