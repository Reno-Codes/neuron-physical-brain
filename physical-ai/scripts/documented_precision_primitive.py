"""Experiment 33: documented precision-inverter model / PDK helpers.

Frozen Experiment 9 weights. SPICE is the source of truth.
Does not overwrite Experiments 1-32. Does not transistorize Network F.
Does not invent MOS W/L. Does not edit acquired vendor model files.
"""

from __future__ import annotations

import json
import os
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen

from compile_xor import PROJECT_ROOT
from device_neuron import MODEL_NMOS, MODEL_PMOS
from offset_vg_search import (
    MCP6041_PATH,
    OPA1611_PATH,
    OPA1656_PATH,
    OPA171_PATH,
    TLV6001_PATH,
    TLV9002_PATH,
)
from physical_invert import E_INV


CIRCUIT_DIR = PROJECT_ROOT / "circuits" / "exp33_documented_precision_primitive"
RESULTS_DIR = PROJECT_ROOT / "results"
VENDOR_DIR = PROJECT_ROOT / "models" / "vendor" / "ti"
ERROR_LIMIT = 1.0e-3
TIER1_RESIDUAL = 100e-6
R_INV = 10_000.0
R_LOAD_W = 4914.013048625536
VIN_SWING = 2.6081758652291698
VINS = (0.0, -1.0, 1.0, 1.5, 2.0, 2.5, VIN_SWING, -VIN_SWING)

IHP_HOWTO = Path(r"C:\ngspice\examples\IHPOpenSourcePDK")
SKY_HOWTO = Path(r"C:\ngspice\examples\SkywaterOpenSourcePDK")
OSDI_DIR = Path(r"C:\ngspice\examples\osdi")
OPTRAN = Path(r"C:\ngspice\examples\optran\models")
P2N = Path(r"C:\ngspice\examples\p-to-n-examples")
R2_CMC = OSDI_DIR / "r2_cmc" / "res_r2_cmc.cir"

# Official TI PSpice zips. Same class of source as the already-installed
# OPA1656/OPA1611 models documented in ngspice Models-for-Debian.txt.
TI_CANDIDATES = (
    {
        "part": "OPA189",
        "class": "zero-drift 36 V",
        "zip_id": "sbomae9",
        "source": "https://www.ti.com/lit/zip/sbomae9",
        "product": "https://www.ti.com/product/OPA189",
        "datasheet_vos_V": 3e-6,
        "datasheet_vos_typ_V": 0.4e-6,
        "vsupply_max": 18.0,
        "vsupply_min": 2.25,
        "iout_A": 0.065,
        "note": "Zero-drift. Datasheet Vos 3 uV max. Do not trust headline.",
    },
    {
        "part": "OPA192",
        "class": "e-trim precision 36 V",
        "zip_id": "sbom862",
        "source": "https://www.ti.com/lit/zip/sbom862",
        "product": "https://www.ti.com/product/OPA192",
        "datasheet_vos_V": 25e-6,
        "datasheet_vos_typ_V": 5e-6,
        "vsupply_max": 18.0,
        "vsupply_min": 2.25,
        "iout_A": 0.065,
        "note": "Precision CMOS e-trim. 36 V. Adequate swing/current on paper.",
    },
    {
        "part": "OPA388",
        "class": "zero-drift 5.5 V",
        "zip_id": "sbomab3",
        "source": "https://www.ti.com/lit/zip/sbomab3",
        "product": "https://www.ti.com/product/OPA388",
        "datasheet_vos_V": 5e-6,
        "datasheet_vos_typ_V": 0.25e-6,
        "vsupply_max": 2.75,
        "vsupply_min": 0.9,
        "iout_A": 0.060,
        "note": "Zero-drift but 5.5 V total supply. Hidden 2.61 V likely clips.",
    },
)


def dest(*parts) -> Path:
    raw = "_".join(str(p) for p in parts)
    slug = []
    for ch in raw:
        if ch.isalnum() or ch in "._":
            slug.append(ch)
        elif ch in "-+":
            slug.append("m" if ch == "-" else "p")
        elif ch in " .":
            slug.append("_")
        else:
            slug.append("")
    CIRCUIT_DIR.mkdir(parents=True, exist_ok=True)
    return CIRCUIT_DIR / f"{''.join(slug).replace('.', 'p')[:90]}.cir"


def _exists(p: Path) -> bool:
    try:
        return bool(p) and Path(p).exists()
    except OSError:
        return False


def classify_status(present: bool, remote: bool = False, unused: bool = False, incompatible: bool = False) -> str:
    if incompatible:
        return "incompatible with ngspice"
    if present and unused:
        return "available locally but unused"
    if present:
        return "already installed"
    if remote:
        return "available remotely/documented"
    return "not available"


def environment_inventory() -> dict:
    pdk_root = os.environ.get("PDK_ROOT")
    pdk = os.environ.get("PDK")
    osdi_bins = list(OSDI_DIR.rglob("*.osdi")) if _exists(OSDI_DIR) else []
    optran = sorted(p.name for p in OPTRAN.glob("*")) if _exists(OPTRAN) else []
    p2n = sorted(p.name for p in P2N.glob("*")) if _exists(P2N) else []
    items = [
        {
            "name": "PDK_ROOT",
            "path": pdk_root,
            "status": classify_status(bool(pdk_root)),
        },
        {
            "name": "PDK",
            "path": pdk,
            "status": classify_status(bool(pdk)),
        },
        {
            "name": "IHP SG13G2 tree",
            "path": str(Path(pdk_root) / (pdk or "ihp-sg13g2")) if pdk_root else None,
            "status": classify_status(False, remote=True),
            "howto": str(IHP_HOWTO / "IHP-PDK-howto.txt") if _exists(IHP_HOWTO) else None,
            "note": "Howto + digital/device examples only. Requires github clone, PDK_ROOT, psp103.osdi.",
        },
        {
            "name": "SkyWater SKY130 tree",
            "path": None,
            "status": classify_status(False, remote=True),
            "howto": str(SKY_HOWTO / "readme.txt") if _exists(SKY_HOWTO) else None,
            "note": "Example is a 1.8 V digital CMOS inverter. Cannot meet 2.61 V hidden swing.",
        },
        {
            "name": "CMC r2_cmc OSDI binary",
            "path": str(OSDI_DIR / "r2_cmc"),
            "status": classify_status(False, remote=True),
            "example_present": _exists(R2_CMC),
            "osdi_binaries": [str(p) for p in osdi_bins],
        },
        {
            "name": "Berkeley BSIM3v3 teaching cards",
            "path": str(MODEL_NMOS.parent),
            "status": classify_status(_exists(MODEL_NMOS) and _exists(MODEL_PMOS), unused=True),
            "note": "Exp 26-32 miller. Drive/swing fail at hidden invert. Do not invent W/L.",
        },
        {
            "name": "ngspice optran vendor macros",
            "path": str(OPTRAN),
            "status": classify_status(_exists(OPTRAN)),
            "files": optran,
        },
        {
            "name": "ngspice p-to-n vendor macros",
            "path": str(P2N),
            "status": classify_status(_exists(P2N)),
            "files": p2n,
        },
        {
            "name": "XSPICE limit primitive",
            "path": "ngspice built-in",
            "status": classify_status(True),
            "note": "LEVEL 2. Exp 30/32 analog-pass. Not a physical device.",
        },
        {
            "name": "chopper / auto-zero / OP07 / OPA189 macromodel",
            "path": None,
            "status": classify_status(False, remote=True),
            "note": "Not installed before Experiment 33. TI PSpice zips documented on ti.com.",
        },
    ]
    installed_precision = [
        {"part": "OPA1656", "path": str(OPA1656_PATH), "present": _exists(OPA1656_PATH), "doc_vos_V": 8.75e-6},
        {"part": "OPA1611", "path": str(OPA1611_PATH), "present": _exists(OPA1611_PATH), "doc_vos_V": 9.729e-5},
        {"part": "OPA171", "path": str(OPA171_PATH), "present": _exists(OPA171_PATH), "doc_vos_V": 214.023e-6},
        {"part": "MCP6041", "path": str(MCP6041_PATH), "present": _exists(MCP6041_PATH), "doc_vos_V": None},
        {"part": "TLV6001", "path": str(TLV6001_PATH), "present": _exists(TLV6001_PATH), "doc_vos_V": 595.218e-6},
        {"part": "TLV9002", "path": str(TLV9002_PATH), "present": _exists(TLV9002_PATH), "doc_vos_V": 396.11e-6},
        {"part": "TL072-dual", "path": str(OPTRAN / "TL072-dual.lib"), "present": _exists(OPTRAN / "TL072-dual.lib"), "doc_vos_V": None},
        {"part": "AD22057N", "path": str(P2N / "ad22057n.lib"), "present": _exists(P2N / "ad22057n.lib"), "doc_vos_V": None, "note": "G=20 CS amp, not a unity invert."},
    ]
    remote = [
        {
            **c,
            "status": "available remotely/documented",
            "local_path": None,
        }
        for c in TI_CANDIDATES
    ]
    return {
        "pdk_root": pdk_root,
        "pdk": pdk,
        "ihp_installed": False,
        "sky130_installed": False,
        "osdi_binary_present": bool(osdi_bins),
        "foundry_pdk_invented": False,
        "environment": items,
        "installed_precision_macros": installed_precision,
        "remote_documented_candidates": remote,
        "acquisition_not_yet_attempted": True,
    }


def write_inventory(path: Path, extra: dict | None = None) -> dict:
    data = environment_inventory()
    if extra:
        data.update(extra)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data


def _find_lib(root: Path, part: str) -> Path | None:
    hits = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        name = p.name.lower()
        stem = part.lower().replace("opa", "opax", 1) if part.lower().startswith("opa") else part.lower()
        if p.suffix.lower() not in {".lib", ".mod", ".txt", ".cir"}:
            continue
        if part.lower() in name or stem in name:
            hits.append(p)
    if not hits:
        return None
    hits.sort(key=lambda p: (0 if p.suffix.lower() == ".lib" else 1, len(p.name)))
    return hits[0]


def acquire_ti_zip(part: str, url: str, dest_dir: Path) -> dict:
    """Download an official TI PSpice zip. Do not edit extracted files."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    zip_path = dest_dir / f"{part.lower()}_ti.zip"
    rec = {
        "part": part,
        "source": url,
        "manufacturer": "Texas Instruments",
        "attempted": True,
        "downloaded": False,
        "extracted": False,
        "lib_path": None,
        "unmodified": True,
        "failure_reason": None,
    }
    try:
        req = Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; physical-ai-exp33/1.0; +https://www.ti.com/)",
                "Accept": "application/zip,*/*",
            },
        )
        with urlopen(req, timeout=60) as resp:
            data = resp.read()
            rec["http_status"] = getattr(resp, "status", None)
            rec["final_url"] = resp.geturl()
            rec["content_type"] = resp.headers.get("Content-Type")
        if len(data) < 200 or data[:20].lstrip().startswith(b"<"):
            rec["failure_reason"] = "download did not return a zip (likely license/HTML wall)"
            rec["nbytes"] = len(data)
            return rec
        zip_path.write_bytes(data)
        rec["downloaded"] = True
        rec["nbytes"] = len(data)
        rec["sha256"] = __import__("hashlib").sha256(data).hexdigest()
        extract_dir = dest_dir / part.lower()
        extract_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path) as zf:
            rec["zip_names"] = zf.namelist()
            zf.extractall(extract_dir)
        rec["extracted"] = True
        lib = _find_lib(extract_dir, part)
        if lib is None:
            rec["failure_reason"] = "zip extracted but no .lib matching the part"
            return rec
        rec["lib_path"] = str(lib)
        rec["subckt"] = _peek_subckt(lib)
    except Exception as exc:
        rec["failure_reason"] = f"{type(exc).__name__}: {exc}"
    return rec


def _peek_subckt(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for raw in text.splitlines():
        s = raw.strip()
        if s.lower().startswith(".subckt"):
            return s
    return None


def inspect_model_mechanism(path: Path) -> dict:
    """Heuristic: is this a static Vos or does it mention chopping/AZ switches?"""
    text = path.read_text(encoding="utf-8", errors="replace")
    low = text.lower()
    return {
        "path": str(path),
        "n_lines": text.count("\n") + 1,
        "mentions_chopper": "chop" in low,
        "mentions_auto_zero": "auto-zero" in low or "auto zero" in low or "autozero" in low,
        "mentions_switch": ".model" in low and "sw" in low,
        "mentions_vos": "vos" in low or "vneg" in low,
        "mentions_temp": "temp" in low or "drift" in low,
        "encrypted": "encrypt" in low or "$begin" in low,
        "subckt": _peek_subckt(path),
        "label": (
            "encrypted"
            if ("encrypt" in low or "$begin" in low)
            else (
                "explicit switching dynamics claimed in comments/devices"
                if (("chop" in low or "auto-zero" in low or "autozero" in low) and "sw" in low)
                else (
                    "zero-drift / AZ mentioned; likely static behavioral Vos"
                    if ("chop" in low or "zero-drift" in low or "zero drift" in low or "auto-zero" in low)
                    else "static macromodel"
                )
            )
        ),
    }


def isolated_bench(
    vin: float,
    kind: str,
    r_load: float = R_LOAD_W,
    r1: float = R_INV,
    r2: float = R_INV,
    opa_path: Path | None = None,
    opa_name: str | None = None,
    vsupply: float = 15.0,
    temp_c: float | None = None,
    t_hold: float | None = None,
) -> str:
    """Standardized Experiment 33 isolated gain=-1 invert."""
    lines = [
        f"* Experiment 33 isolated invert kind={kind} Vin={vin:g} Rload={r_load:g}",
        f"Vin in 0 DC {vin:.15g}",
        f"R1 in mid {r1:.15g}",
        f"R2 out mid {r2:.15g}",
        f"Rload out 0 {r_load:.15g}",
    ]
    if temp_c is not None:
        lines.append(f".temp {float(temp_c):.15g}")
    extra = ["print i(Rload)"]
    if kind == "limit":
        lines += [
            ".model limiso limit(gain=1e5 in_offset=0 out_lower_limit=-15 "
            "out_upper_limit=15 fraction=false limit_range=0.05)",
            "Ainv %vd(0 mid) out limiso",
        ]
    elif kind == "miller":
        from device_neuron import MosParams, mos_include_block

        p = MosParams(name="iso33")
        lines += mos_include_block()
        lines += [
            "Vdd vdd 0 DC 2.5",
            "Vss vss 0 DC -2.5",
            (
                f"Xinv 0 mid out vdd vss miller_tia "
                f"MD={p.m_diff} MT={p.m_tail} MO={p.m_out} "
                f"CC={p.cc_f:.15g} IBIAS={p.ibias:.15g} DW=0.0026 L1={p.l1_m}u"
            ),
        ]
        extra.append("print i(Vdd)")
    elif kind == "replica_neg_1656":
        lines += [
            f'.include "{OPA1656_PATH.resolve().as_posix()}"',
            "Vdd vdd 0 DC 15",
            "Vss vss 0 DC -15",
            f"Rra 0 rmid {r1:.15g}",
            f"Rrb rout rmid {r2:.15g}",
            "Xrep 0 rmid vdd vss rout OPA1656",
            "Crc rout 0 1p",
            f"Rrl rout 0 {r_load:.15g}",
            "Eref inp 0 rmid 0 -1",
            "Xinv inp mid vdd vss out OPA1656",
            "Ccl out 0 1p",
        ]
        extra += ["print v(rmid)", "print v(inp)", "print i(Vdd)"]
    elif kind == "physical_sign":
        if opa_path is None or opa_name is None:
            raise ValueError("physical_sign needs opa")
        lines += [
            f'.include "{OPA1656_PATH.resolve().as_posix()}"',
            f'.include "{Path(opa_path).resolve().as_posix()}"',
            "Vdd vdd 0 DC 15",
            "Vss vss 0 DC -15",
            "* replica OPA1656; physical invert of replica mid by candidate (no E-source)",
            f"Rra 0 rmid {r1:.15g}",
            f"Rrb rout rmid {r2:.15g}",
            "Xrep 0 rmid vdd vss rout OPA1656",
            "Crc rout 0 1p",
            f"Rrl rout 0 {r_load:.15g}",
            f"Rs1 rmid smid {r1:.15g}",
            f"Rs2 sout smid {r2:.15g}",
            f"Xsign 0 smid vdd vss sout {opa_name}",
            "Csign sout 0 1p",
            "Xinv sout mid vdd vss out OPA1656",
            "Ccl out 0 1p",
        ]
        extra += ["print v(rmid)", "print v(sout)", "print v(smid)", "print i(Vdd)"]
    else:
        if opa_path is None or opa_name is None:
            raise ValueError(kind)
        lines += [
            f'.include "{Path(opa_path).resolve().as_posix()}"',
            f"Vdd vdd 0 DC {vsupply:.15g}",
            f"Vss vss 0 DC {-vsupply:.15g}",
            f"Xinv 0 mid vdd vss out {opa_name}",
            "Ccl out 0 1p",
        ]
        extra.append("print i(Vdd)")
    extra += ["print v(out)", "print v(mid)", "print v(in)"]
    if t_hold is None:
        ctrl = [".control", "set numdgt=15", "op", *extra, ".endc", ".end", ""]
    else:
        ctrl = [
            ".control",
            "set numdgt=15",
            f"tran {max(t_hold / 200.0, 1e-7):.15g} {t_hold:.15g}",
            f"meas tran vout_end find v(out) at={t_hold:.15g}",
            f"meas tran vmid_end find v(mid) at={t_hold:.15g}",
            "print vout_end",
            "print vmid_end",
            ".endc",
            ".end",
            "",
        ]
    return "\n".join(lines + ctrl)


def isolated_history_tran(
    kind: str,
    opa_path: Path | None = None,
    opa_name: str | None = None,
    vsupply: float = 15.0,
    dwell: float = 2e-4,
    amps: tuple[float, float, float] = (0.0, VIN_SWING, 1.0),
) -> str:
    t = 0.0
    pwl = [(0.0, amps[0])]
    samples = []
    seq = [amps[0], amps[1], amps[2], amps[0]]
    for i, a in enumerate(seq):
        t_end = (i + 1) * dwell
        if i:
            pwl.append((t + 1e-6, a))
        pwl.append((t_end, a))
        samples.append((f"s{i}", t_end, a))
        t = t_end
    pwl_s = " ".join(f"{tt:.15g} {vv:.15g}" for tt, vv in pwl)
    body = isolated_bench(0.0, kind, opa_path=opa_path, opa_name=opa_name, vsupply=vsupply)
    head, _, _ = body.partition(".control")
    head = head.replace("Vin in 0 DC 0", f"Vin in 0 PWL({pwl_s})", 1)
    meas = []
    for name, ts, _a in samples:
        meas += [f"meas tran v{name} find v(out) at={ts:.15g}", f"print v{name}"]
    ctrl = [
        ".control",
        "set numdgt=15",
        f"tran {max(t / 400.0, 1e-7):.15g} {t:.15g}",
        *meas,
        ".endc",
        ".end",
        "",
    ]
    return head.rstrip() + "\n" + "\n".join(ctrl)
