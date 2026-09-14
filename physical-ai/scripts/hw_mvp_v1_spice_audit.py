"""Hardware package support: freeze checksums, SPICE correlation, cap audit.

Does not modify Experiments 1-67 or frozen xor_2_4_1 artifacts.
Does not edit neural weights. UIC TRAN matches the validated compiler deck.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmark_scaling import detect_spice_failure
from compile_xor import XOR_X, find_ngspice
from exp39_pdk_o2_cell import last
from exp45_documented_tia import spiceinit_behavior
from offset_vg_search import run_ngspice_ex
from test_robustness import extract_all

FROZEN_DIR = PROJECT_ROOT / "physical_design" / "xor_2_4_1"
HW_DIR = PROJECT_ROOT / "hardware" / "mvp_v1_xor_2_4_1"
CIRCUIT_DIR = PROJECT_ROOT / "circuits" / "hw_mvp_v1_xor"
MODEL = PROJECT_ROOT / "models" / "xor_model.npz"
TSTOP = 0.002

NODES = [
    "in1", "in2", "in1n", "in2n", "vref", "vrefn",
    "h1sum", "h1lin", "h1amp", "h1y", "h1yn",
    "h2sum", "h2lin", "h2amp", "h2y", "h2yn",
    "h3sum", "h3lin", "h3amp", "h3y", "h3yn",
    "h4sum", "h4lin", "h4amp", "h4y", "h4yn",
    "o1sum", "o1lin",
]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def set_inputs(net: str, x) -> str:
    out = []
    for raw in net.splitlines():
        s = raw.strip()
        replaced = False
        for i, val in enumerate(x, start=1):
            if s.startswith(f"Vin{i} "):
                out.append(f"Vin{i} in{i} 0 DC {float(val):.15g}")
                replaced = True
                break
        if not replaced:
            out.append(raw)
    return "\n".join(out) + "\n"


def expand_meas(net: str) -> str:
    extra = [f"meas tran n_{n} FIND v({n}) AT={TSTOP:.15g}" for n in NODES]
    extra += [
        f"meas tran idd FIND i(vdd) AT={TSTOP:.15g}",
        f"meas tran iss FIND i(vss) AT={TSTOP:.15g}",
        "print idd iss",
        *[f"print n_{n}" for n in NODES],
    ]
    # insert prints before .endc
    lines = net.splitlines()
    out = []
    for raw in lines:
        if raw.strip() == ".endc":
            out.extend(extra)
        out.append(raw)
    return "\n".join(out) + "\n"


def strip_1pf(net: str) -> str:
    out = []
    for raw in net.splitlines():
        parts = raw.split()
        if (
            len(parts) >= 4
            and parts[0].lower().startswith("c")
            and not parts[0].startswith("*")
            and "1e-12" in raw.replace(" ", "").lower()
        ):
            out.append(f"* HW AUDIT removed 1pF {raw}")
            continue
        out.append(raw)
    return "\n".join(out) + "\n"


def parse(text: str) -> dict:
    rec = {n: last(extract_all(text, f"n_{n}")) for n in NODES}
    rec["i_vdd"] = last(extract_all(text, "idd"))
    rec["i_vss"] = last(extract_all(text, "iss"))
    rec["yo1"] = last(extract_all(text, "yo1"))
    return rec


def main() -> None:
    HW_DIR.mkdir(parents=True, exist_ok=True)
    CIRCUIT_DIR.mkdir(parents=True, exist_ok=True)
    spiceinit_behavior(CIRCUIT_DIR, "ps")
    ng = find_ngspice()
    net0 = (FROZEN_DIR / "netlist.cir").read_text(encoding="utf-8")

    frozen = {
        "note": "SHA-256 of the validated compiler package. Hardware docs must not edit these files.",
        "xor_model.npz": sha256(MODEL),
        "files": {p.name: sha256(p) for p in sorted(FROZEN_DIR.iterdir()) if p.is_file()},
        "netlist_header": net0.splitlines()[:6],
        "analysis": "tran 5e-06 0.002 uic, ngbehavior=ps, 27 C implied",
        "weights_frozen": True,
        "experiments_1_to_67_unmodified": True,
    }
    (HW_DIR / "FROZEN_PROVENANCE.json").write_text(
        json.dumps(frozen, indent=2), encoding="utf-8"
    )

    rows = []
    nocap_rows = []
    print("==== hardware correlation SPICE ====", flush=True)
    for i, x in enumerate(XOR_X):
        net = expand_meas(set_inputs(net0, x))
        path = CIRCUIT_DIR / f"corr_{i}.cir"
        path.write_text(net, encoding="utf-8")
        result = run_ngspice_ex(ng, path, timeout=180.0, pspice=True)
        text = f"{result.stdout or ''}\n{result.stderr or ''}"
        fail = detect_spice_failure(result)
        rec = parse(text)
        rec.update(
            {
                "vector": i,
                "x": [float(v) for v in x],
                "failed": bool(fail),
                "failure_reason": fail,
                "path": str(path),
            }
        )
        rows.append(rec)
        print(
            f"  vec={i} yo1={rec.get('yo1')} idd={rec.get('i_vdd')} fail={fail}",
            flush=True,
        )

        net_nc = expand_meas(strip_1pf(set_inputs(net0, x)))
        p2 = CIRCUIT_DIR / f"nocap_{i}.cir"
        p2.write_text(net_nc, encoding="utf-8")
        r2 = run_ngspice_ex(ng, p2, timeout=180.0, pspice=True)
        t2 = f"{r2.stdout or ''}\n{r2.stderr or ''}"
        f2 = detect_spice_failure(r2)
        rec2 = parse(t2)
        rec2.update({"vector": i, "failed": bool(f2), "failure_reason": f2})
        nocap_rows.append(rec2)
        dy = None
        if rec.get("yo1") is not None and rec2.get("yo1") is not None:
            dy = rec2["yo1"] - rec["yo1"]
        print(f"    no-1pF yo1={rec2.get('yo1')} dY={dy} fail={f2}", flush=True)

    report = {
        "kind": "hardware package SPICE correlation / capacitor audit",
        "modifies_experiments_1_67": False,
        "modifies_frozen_design_files": False,
        "python_corrected": False,
        "silicon": False,
        "rows": rows,
        "no_1pF_rows": nocap_rows,
        "yo1_delta_no_1pF": [
            None
            if a.get("yo1") is None or b.get("yo1") is None
            else b["yo1"] - a["yo1"]
            for a, b in zip(rows, nocap_rows)
        ],
    }
    (HW_DIR / "spice_correlation_raw.json").write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8"
    )
    print("wrote", HW_DIR / "spice_correlation_raw.json", flush=True)


if __name__ == "__main__":
    main()
