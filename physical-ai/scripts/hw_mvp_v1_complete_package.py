"""Emit remaining MVP-H1 builder tables. Does not touch frozen xor_2_4_1 files."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HW = ROOT / "hardware" / "mvp_v1_xor_2_4_1"
FROZEN = ROOT / "physical_design" / "xor_2_4_1"
MODEL = ROOT / "models" / "xor_model.npz"

OPA_INSTANCES = [
    ("Xinv1", "unity invert IN1 -> IN1N"),
    ("Xinv2", "unity invert IN2 -> IN2N"),
    ("Xinvref", "unity invert VREF -> VREFN"),
    ("Xh1tia", "hidden h1 TIA (inverts; H1_LIN = -z1)"),
    ("Xh1relu", "hidden h1 rectifier op-amp"),
    ("Xh1inv", "unity invert H1_OUT -> H1_YN"),
    ("Xh2tia", "hidden h2 TIA"),
    ("Xh2relu", "hidden h2 rectifier op-amp"),
    ("Xh2inv", "unity invert H2_OUT -> H2_YN"),
    ("Xh3tia", "hidden h3 TIA"),
    ("Xh3relu", "hidden h3 rectifier op-amp"),
    ("Xh3inv", "unity invert H3_OUT -> H3_YN"),
    ("Xh4tia", "hidden h4 TIA"),
    ("Xh4relu", "hidden h4 rectifier op-amp"),
    ("Xh4inv", "unity invert H4_OUT -> H4_YN"),
    ("Xo1tia", "output TIA (does not invert math; O1_LIN = +y)"),
]

DIODES = [
    ("Xh1d1", "h1rinn", "h1amp", "h1 clamp"),
    ("Xh1d2", "h1amp", "h1y", "h1 forward"),
    ("Xh2d1", "h2rinn", "h2amp", "h2 clamp"),
    ("Xh2d2", "h2amp", "h2y", "h2 forward"),
    ("Xh3d1", "h3rinn", "h3amp", "h3 clamp"),
    ("Xh3d2", "h3amp", "h3y", "h3 forward"),
    ("Xh4d1", "h4rinn", "h4amp", "h4 clamp"),
    ("Xh4d2", "h4amp", "h4y", "h4 forward"),
]

DNP_CAPS = [
    "Cinv1",
    "Cinv2",
    "Cinvref",
    "Ch1tia",
    "Ch1rl",
    "Ch1inv",
    "Ch2tia",
    "Ch2rl",
    "Ch2inv",
    "Ch3tia",
    "Ch3rl",
    "Ch3inv",
    "Ch4tia",
    "Ch4rl",
    "Ch4inv",
    "Co1tia",
]

PROC = "PROCUREMENT VERIFICATION REQUIRED"
R_SPEC = "thin-film 0.1% <=25 ppm/C 0805 or 1206 50 V 0.1 W min"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def fmt_ohm(value: float) -> str:
    if abs(value - round(value)) < 1e-9:
        value = float(round(value))
    if value >= 1e6:
        v = value / 1e6
        s = f"{v:g}M"
    elif value >= 1000:
        v = value / 1000
        s = f"{v:g}k"
    else:
        s = f"{value:g}"
    return s.replace(".", "p") if False else s


def parse_netlist(path: Path) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    resistors, amps, diodes, caps = [], [], [], []
    in_control = False
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("*"):
            continue
        low = line.lower()
        if low.startswith(".control"):
            in_control = True
            continue
        if low.startswith(".endc"):
            in_control = False
            continue
        if in_control or line.startswith("."):
            continue
        parts = line.split()
        name = parts[0]
        if name.startswith("R"):
            resistors.append({"ref": name, "n1": parts[1], "n2": parts[2], "ohm": parts[3]})
        elif name.startswith("X") and parts[-1] == "OPAx189":
            amps.append(
                {
                    "ref": name,
                    "inp": parts[1],
                    "inn": parts[2],
                    "vcc": parts[3],
                    "vee": parts[4],
                    "out": parts[5],
                }
            )
        elif name.startswith("X") and parts[-1] == "1N4148":
            diodes.append({"ref": name, "anode": parts[1], "cathode": parts[2]})
        elif name.startswith("C"):
            caps.append({"ref": name, "n1": parts[1], "n2": parts[2], "farad": parts[3]})
        elif name.startswith("V"):
            continue
        else:
            raise SystemExit(f"unparsed netlist line: {line}")
    return resistors, amps, diodes, caps


def physical_resistor_rows(combos: list[dict]) -> list[dict]:
    rows = []
    for c in combos:
        kind = c["preferred"]["kind"]
        parts = c["preferred"]["parts"]
        src = c.get("from") or ""
        dst = c.get("to") or ""
        if kind == "single":
            rows.append(
                {
                    "ref": c["ref"],
                    "qty": 1,
                    "compiled_ref": c["ref"],
                    "value": fmt_ohm(parts[0]),
                    "exact_target_ohm": f"{c['exact_ohm']:.15g}",
                    "network": "single",
                    "from_node": src,
                    "to_node": dst,
                    "role": c["role"] or "support",
                }
            )
        elif kind == "series":
            for i, p in enumerate(parts, start=1):
                rows.append(
                    {
                        "ref": f"{c['ref']}_{chr(64 + i)}",
                        "qty": 1,
                        "compiled_ref": c["ref"],
                        "value": fmt_ohm(p),
                        "exact_target_ohm": f"{c['exact_ohm']:.15g}",
                        "network": "series",
                        "from_node": src if i == 1 else f"{c['ref']}_series",
                        "to_node": f"{c['ref']}_series" if i == 1 else dst,
                        "role": c["role"] or "support",
                    }
                )
        elif kind == "parallel":
            for i, p in enumerate(parts, start=1):
                rows.append(
                    {
                        "ref": f"{c['ref']}_{chr(64 + i)}",
                        "qty": 1,
                        "compiled_ref": c["ref"],
                        "value": fmt_ohm(p),
                        "exact_target_ohm": f"{c['exact_ohm']:.15g}",
                        "network": "parallel",
                        "from_node": src,
                        "to_node": dst,
                        "role": c["role"] or "support",
                    }
                )
        else:
            raise SystemExit(f"unknown combo kind {kind}")
    return rows


def write_bom(combos: list[dict]) -> None:
    phys = physical_resistor_rows(combos)
    header = [
        "ref",
        "qty",
        "description",
        "value",
        "tol",
        "voltage",
        "power",
        "package",
        "mpn",
        "notes",
    ]
    rows: list[list[object]] = []

    def add(**kw: object) -> None:
        rows.append([kw[k] for k in header])  # type: ignore[index]

    for ref, role in OPA_INSTANCES:
        add(
            ref=ref,
            qty=1,
            description="zero-drift op-amp (frozen neural channel)",
            value="OPA189 family",
            tol="",
            voltage="+/-15 V",
            power="",
            package="SOIC-8 D preferred; see opa189_pinout.md",
            mpn=PROC,
            notes=f"{role}. TI SBOS830. Alt: 4x OPA4189 quads covering the same 16 channels.",
        )
    add(
        ref="U_VREFBUF",
        qty=1,
        description="VREF buffer (hardware-only, not in frozen 16)",
        value="OPA189 family",
        tol="",
        voltage="+/-15 V",
        power="",
        package="SOIC-8 D",
        mpn=PROC,
        notes="Buffers 1.000 V. Do not count as a neural MAC stage.",
    )
    add(
        ref="U_VREF",
        qty=1,
        description="1.000 V reference chain",
        value="1.000 V",
        tol="0.05% goal",
        voltage="",
        power="",
        package="",
        mpn=PROC,
        notes="SPICE Vref was ideal. See reference_voltage.md.",
    )
    for ref, anode, cathode, role in DIODES:
        add(
            ref=ref,
            qty=1,
            description="ReLU rectifier diode",
            value="1N4148",
            tol="",
            voltage="75 V class",
            power="",
            package="SOD-123 or DO-35",
            mpn=PROC,
            notes=f"{role}. Anode={anode} cathode={cathode} (1N4148 pin 1=anode, pin 2=cathode).",
        )
    for p in phys:
        add(
            ref=p["ref"],
            qty=1,
            description=f"compiled {p['compiled_ref']} ({p['role']}, {p['network']})",
            value=p["value"],
            tol="0.1%",
            voltage="50 V",
            power="0.1 W min",
            package="0805 or 1206 thin film",
            mpn=PROC,
            notes=f"{R_SPEC}. Target {p['exact_target_ohm']} ohm. {p['from_node']} -> {p['to_node']}. Do not coarse-E96 snap.",
        )
    add(
        ref="C_VDD_BULK",
        qty=1,
        description="bulk decouple +15 V",
        value="10uF",
        tol="20%",
        voltage=">=35 V",
        power="",
        package="electrolytic or 1210 ceramic",
        mpn=PROC,
        notes="Hardware-only. VDD to GND.",
    )
    add(
        ref="C_VSS_BULK",
        qty=1,
        description="bulk decouple -15 V",
        value="10uF",
        tol="20%",
        voltage=">=35 V",
        power="",
        package="electrolytic or 1210 ceramic",
        mpn=PROC,
        notes="Hardware-only. VSS to GND.",
    )
    for ref, _role in OPA_INSTANCES:
        add(
            ref=f"C_{ref}_VP",
            qty=1,
            description=f"local V+ decouple {ref}",
            value="100nF X7R",
            tol="10%",
            voltage=">=50 V",
            power="",
            package="0805",
            mpn=PROC,
            notes="Hardware-only. Package V+ to GND, <5 mm. Omit duplicates if using OPA4189 quads (one pair per package).",
        )
        add(
            ref=f"C_{ref}_VN",
            qty=1,
            description=f"local V- decouple {ref}",
            value="100nF X7R",
            tol="10%",
            voltage=">=50 V",
            power="",
            package="0805",
            mpn=PROC,
            notes="Hardware-only. Package V- to GND, <5 mm.",
        )
    add(
        ref="C_U_VREFBUF_VP",
        qty=1,
        description="local V+ decouple U_VREFBUF",
        value="100nF X7R",
        tol="10%",
        voltage=">=50 V",
        power="",
        package="0805",
        mpn=PROC,
        notes="Hardware-only.",
    )
    add(
        ref="C_U_VREFBUF_VN",
        qty=1,
        description="local V- decouple U_VREFBUF",
        value="100nF X7R",
        tol="10%",
        voltage=">=50 V",
        power="",
        package="0805",
        mpn=PROC,
        notes="Hardware-only.",
    )
    for cap in DNP_CAPS:
        add(
            ref=cap,
            qty=0,
            description="SPICE 1 pF node capacitor — DO NOT PLACE",
            value="1pF",
            tol="",
            voltage="",
            power="",
            package="DNP",
            mpn="DNP",
            notes="Class C. capacitor_audit.md: removing all 16 did not change XOR yo1.",
        )
    add(
        ref="SW_IN1",
        qty=1,
        description="manual input IN1",
        value="SPDT GND/VREF",
        tol="",
        voltage="",
        power="",
        package="",
        mpn=PROC,
        notes="Omit if using DAC/lab source.",
    )
    add(
        ref="SW_IN2",
        qty=1,
        description="manual input IN2",
        value="SPDT GND/VREF",
        tol="",
        voltage="",
        power="",
        package="",
        mpn=PROC,
        notes="Omit if using DAC/lab source.",
    )
    add(
        ref="J_PWR",
        qty=1,
        description="power connector",
        value="+15 / GND / -15",
        tol="",
        voltage=">=15 V",
        power="",
        package="terminal block or banana",
        mpn=PROC,
        notes="",
    )
    add(
        ref="J_IN",
        qty=1,
        description="optional input connector",
        value="IN1 IN2 GND",
        tol="",
        voltage="",
        power="",
        package="",
        mpn=PROC,
        notes="See input_interface.md.",
    )
    tps = [
        "TP_P15",
        "TP_M15",
        "TP_GND",
        "TP_VREF",
        "TP_VREFN",
        "TP_IN1",
        "TP_IN2",
        "TP_IN1N",
        "TP_IN2N",
        "TP_H1_SUM",
        "TP_H1_LIN",
        "TP_H1_OUT",
        "TP_H1_YN",
        "TP_H2_SUM",
        "TP_H2_LIN",
        "TP_H2_OUT",
        "TP_H2_YN",
        "TP_H3_SUM",
        "TP_H3_LIN",
        "TP_H3_OUT",
        "TP_H3_YN",
        "TP_H4_SUM",
        "TP_H4_LIN",
        "TP_H4_OUT",
        "TP_H4_YN",
        "TP_O1_SUM",
        "TP_O1LIN",
    ]
    for tp in tps:
        add(
            ref=tp,
            qty=1,
            description="test point",
            value="see test_point_map.md",
            tol="",
            voltage="",
            power="",
            package="1.0 mm or 1.27 mm loop/header",
            mpn=PROC,
            notes="Primary analog neural output is TP_O1LIN.",
        )

    with (HW / "BOM.csv").open("w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows([header, *rows])

    shop: Counter[str] = Counter()
    for p in phys:
        shop[p["value"]] += 1
    with (HW / "resistor_shopping.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(
            [
                "e192_value",
                "qty_minimum",
                "qty_buy_suggested",
                "tol",
                "tcr",
                "package",
                "voltage",
                "power",
                "mpn",
                "used_by",
            ]
        )
        used: dict[str, list[str]] = {}
        for p in phys:
            used.setdefault(p["value"], []).append(p["ref"])
        for value, qty in sorted(shop.items(), key=lambda kv: (-kv[1], kv[0])):
            w.writerow(
                [
                    value,
                    qty,
                    qty + max(2, qty // 5),
                    "0.1%",
                    "<=25 ppm/C preferred",
                    "0805 or 1206 thin film",
                    "50 V",
                    "0.1 W min",
                    PROC,
                    ";".join(used[value]),
                ]
            )


def write_connectivity(resistors: list[dict], amps: list[dict], diodes: list[dict], caps: list[dict]) -> None:
    lines = [
        "# Schematic connectivity (human-readable)",
        "",
        "This is the **authoritative wiring list** for MVP-H1 neural topology.",
        "It is a transcription of frozen `physical_design/xor_2_4_1/netlist.cir`.",
        "Hardware net names **are** the SPICE node names (uppercase in silkscreen is allowed; do not rename).",
        "",
        "OPA189 SPICE order: `IN+ IN- VCC VEE OUT`. Package pin numbers: `opa189_pinout.md` (TI SBOS830).",
        "1N4148: anode = pin 1, cathode = pin 2.",
        "",
        "Do **not** place the 1 pF capacitors (`capacitor_audit.md`).",
        "",
        "## Unity inverters and output TIA — op-amp pins",
        "",
        "| Instance | IN+ | IN- | V+ | V- | OUT | Role |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    roles = {r: n for r, n in OPA_INSTANCES}
    for a in amps:
        lines.append(
            f"| `{a['ref']}` | `{a['inp']}` | `{a['inn']}` | `{a['vcc']}` | `{a['vee']}` | `{a['out']}` | {roles.get(a['ref'], '')} |"
        )
    lines += [
        "",
        "## Resistors (compiled)",
        "",
        "| Ref | Node A | Node B | Exact ohm |",
        "| --- | --- | --- | ---: |",
    ]
    for r in resistors:
        lines.append(f"| `{r['ref']}` | `{r['n1']}` | `{r['n2']}` | {r['ohm']} |")
    lines += [
        "",
        "## Diodes",
        "",
        "| Ref | Anode | Cathode |",
        "| --- | --- | --- |",
    ]
    for d in diodes:
        lines.append(f"| `{d['ref']}` | `{d['anode']}` | `{d['cathode']}` |")
    lines += [
        "",
        "## SPICE capacitors (do not fit)",
        "",
        "| Ref | Node A | Node B | Value | Placement |",
        "| --- | --- | --- | --- | --- |",
    ]
    for c in caps:
        lines.append(f"| `{c['ref']}` | `{c['n1']}` | `{c['n2']}` | {c['farad']} F | **DNP** class C |")
    lines += [
        "",
        "## Hardware-only (not in frozen netlist)",
        "",
        "| Item | Connection |",
        "| --- | --- |",
        "| `J_PWR` | `vdd`=+15 V, `0`=GND, `vss`=−15 V |",
        "| `C_VDD_BULK` | `vdd` to `0` |",
        "| `C_VSS_BULK` | `vss` to `0` |",
        "| 100 nF per package | each OPA189 V+ and V− to `0` |",
        "| `U_VREF` + `U_VREFBUF` | drive `vref`; SPICE used ideal 1 V |",
        "| `SW_IN1` / DAC | `in1` to `0` or `vref` |",
        "| `SW_IN2` / DAC | `in2` to `0` or `vref` |",
        "| `TP_O1LIN` | `o1lin` |",
        "",
        "Block diagrams: `schematics/*.svg`. CAD import: `kicad_import_notes.md`.",
        "",
    ]
    (HW / "schematic_connectivity.md").write_text("\n".join(lines), encoding="utf-8")


def write_simulation_baseline(raw: dict) -> None:
    rows = raw["rows"][:4]
    lines = [
        "# Reproducible SPICE / hardware correlation baseline",
        "",
        "This is the hardware-package replay of the frozen XOR netlist. It does **not** modify Experiments 1–67.",
        "",
        "## Simulation settings",
        "",
        "| Item | Value |",
        "| --- | --- |",
        "| Netlist | `physical_design/xor_2_4_1/netlist.cir` |",
        f"| SHA-256 `netlist.cir` | `{sha256(FROZEN / 'netlist.cir')}` |",
        f"| SHA-256 `xor_model.npz` | `{sha256(MODEL)}` |",
        "| Analysis | `tran 5e-06 0.002 uic` |",
        "| Solver | ngspice `ngbehavior=ps` (PSpice compatibility for OPA189) |",
        "| Temperature | 27 °C implied (no `.temp` card in frozen deck) |",
        "| Supplies | `Vdd=+15 V`, `Vss=−15 V` ideal |",
        "| VREF | ideal `DC 1` |",
        "| Inputs | ideal `Vin1`/`Vin2` 0 V or 1 V |",
        "| Op-amp model | `models/vendor/ti/opa189/OPAx189.LIB` |",
        "| Diode model | `models/vendor/ti/1n4148/1N4148.LIB` |",
        "| Resistors | exact compiled ohms (not E96) |",
        "| 1 pF caps | present in frozen deck; removing them changed yo1 by 0 V |",
        "| Claim level | MIXED-LEVEL (vendor macromodel + discrete R). Not silicon. |",
        "",
        "Fill measured columns in `hardware_correlation_template.csv`. Do not substitute a NumPy forward pass for `TP_O1LIN`.",
        "",
        "## Node voltages (27 °C UIC TRAN 2 ms)",
        "",
    ]
    keys = [
        ("in1", "IN1"),
        ("in2", "IN2"),
        ("in1n", "IN1N"),
        ("in2n", "IN2N"),
        ("vref", "VREF"),
        ("vrefn", "VREFN"),
        ("h1lin", "H1_LIN"),
        ("h1y", "H1_OUT"),
        ("h2lin", "H2_LIN"),
        ("h2y", "H2_OUT"),
        ("h3lin", "H3_LIN"),
        ("h3y", "H3_OUT"),
        ("h4lin", "H4_LIN"),
        ("h4y", "H4_OUT"),
        ("o1lin", "O1_LIN"),
        ("h1sum", "H1_SUM"),
        ("h2sum", "H2_SUM"),
        ("h3sum", "H3_SUM"),
        ("h4sum", "H4_SUM"),
        ("o1sum", "O1_SUM"),
        ("i_vdd", "i(Vdd)"),
        ("i_vss", "i(Vss)"),
    ]
    header = "| Node | 00 | 01 | 10 | 11 |"
    sep = "| --- | ---: | ---: | ---: | ---: |"
    lines.append(header)
    lines.append(sep)
    for spice, name in keys:
        vals = [f"{rows[i][spice]:.9g}" for i in range(4)]
        lines.append(f"| {name} (`{spice}`) | " + " | ".join(vals) + " |")
    lines += [
        "",
        "Classification from `O1_LIN`: 00→0, 01→1, 10→1, 11→0 using threshold 0.5 V.",
        "",
        "Raw JSON: `spice_correlation_raw.json`.",
        "",
    ]
    (HW / "simulation_baseline.md").write_text("\n".join(lines), encoding="utf-8")


def verify_provenance() -> None:
    prov = json.loads((HW / "FROZEN_PROVENANCE.json").read_text(encoding="utf-8"))
    mismatches = []
    got_model = sha256(MODEL)
    if got_model != prov["xor_model.npz"]:
        mismatches.append(("xor_model.npz", prov["xor_model.npz"], got_model))
    for name, expected in prov["files"].items():
        got = sha256(FROZEN / name)
        if got != expected:
            mismatches.append((name, expected, got))
    if mismatches:
        raise SystemExit(f"provenance mismatch: {mismatches}")
    print("frozen provenance OK")


def main() -> None:
    verify_provenance()
    combos = json.loads((HW / "resistor_combos.json").read_text(encoding="utf-8"))
    raw = json.loads((HW / "spice_correlation_raw.json").read_text(encoding="utf-8"))
    resistors, amps, diodes, caps = parse_netlist(FROZEN / "netlist.cir")
    if len(amps) != 16 or len(diodes) != 8 or len(resistors) != 48 or len(caps) != 16:
        raise SystemExit(
            f"unexpected counts R={len(resistors)} Xopa={len(amps)} D={len(diodes)} C={len(caps)}"
        )
    write_bom(combos)
    write_connectivity(resistors, amps, diodes, caps)
    write_simulation_baseline(raw)
    print("complete package tables written")


if __name__ == "__main__":
    main()
